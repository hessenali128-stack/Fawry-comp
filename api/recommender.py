"""Model loading/hot-swap, Redis user state, and the recommendation flow (Stage 1 -> 17 features -> LGBM)."""
import json
import logging
import threading
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

import lightgbm as lgb
import numpy as np

from api import config as cfg
from common import geo, registry
from common.build import load_artifacts
from common.core import (CONTRACT, ContractError, HistEntry, area_view, as_of_day, assert_canonical, build_features,
                         default_user_static, eligible_mask, empty_live, fold_history, generate_candidates,
                         known_areas)

log = logging.getLogger("api.model")


# ------------------------------------------------------------------ model bundle + hot swap
class Bundle:
    def __init__(self, version: str):
        d = Path(cfg.MODELS_DIR) / version
        self.version = version
        self.art = load_artifacts(d / "artifacts.pkl")
        self.booster = lgb.Booster(model_file=str(d / "model.txt"))
        schema = json.loads((d / "feature_schema.json").read_text())
        self.cols = schema["features"]
        self.meta = json.loads((d / "metadata.json").read_text())
        # production contract: sequential point-in-time history + the canonical 17 features, in this exact order
        if self.meta.get("contract") != CONTRACT or getattr(self.art, "contract", "") != CONTRACT:
            raise ContractError(f"{version} was not trained under contract {CONTRACT} (retrain: python -m training.train --once)")
        assert_canonical(self.cols)
        self.loaded_at = time.time()
        a = self.art
        self.cat_index = {c: i for i, c in enumerate(a.macro_cats)}
        self.item_index = a.item_index
        self.partner_name = {i: p for p, i in a.partner_index.items()}
        self.gt_name = {i: g for g, i in a.gt_index.items()}
        self.default_user = default_user_static(a)

        self.areas = known_areas(a)
        self.area_index = {geo.canonical(g): g for g in self.areas}
        self.area_centroids = {g: geo.CENTROIDS[geo.canonical(g)] for g in self.areas if geo.canonical(g) in geo.CENTROIDS}

    def as_of_day(self) -> int:
        return as_of_day(self.art, cfg.AS_OF_DATE)

    def as_of_date(self, day: int) -> str:
        return (date.fromisoformat(self.art.anchor_date) + timedelta(days=int(day))).isoformat()


class ModelManager:
    """Holds ONE bundle reference. A background thread watches models/current.json; a new version is loaded and
    smoke-tested off to the side, then swapped in with a single reference assignment (no downtime)."""

    def __init__(self):
        self.bundle: Bundle | None = None
        self.failed: str | None = None
        self.last_error: str | None = None
        self._stop = threading.Event()

    def start(self):
        self.check()
        threading.Thread(target=self._loop, daemon=True, name="model-watcher").start()

    def _loop(self):
        while not self._stop.wait(cfg.MODEL_POLL_SECONDS):
            try:
                self.check()
            except Exception:
                log.exception("model check failed")

    def check(self):
        cur = registry.read_current()
        if not cur:
            return
        want = cur["version"]
        if self.bundle and self.bundle.version == want:
            self.failed = self.last_error = None  # e.g. after a rollback to the version we are already serving
            return
        if self.failed == want:
            return  # already failed this version; wait until current.json changes again
        try:
            t0 = time.time()
            new = Bundle(want)
            smoke_test(new)
            old = self.bundle.version if self.bundle else None
            self.bundle = new  # atomic swap
            self.failed = self.last_error = None
            log.info("MODEL SWAP %s -> %s (loaded+tested in %.1fs)", old, want, time.time() - t0)
        except Exception as e:
            self.failed, self.last_error = want, repr(e)
            log.error("could not load %s (%s) - production stays on %s", want, e,
                      self.bundle.version if self.bundle else None)


def smoke_test(b: Bundle):
    """A candidate model must score a request before it is allowed to serve traffic."""
    uid = b.art.user_ids[0] if b.art.user_ids else "smoke"
    user = b.art.user_static.get(uid, b.default_user)
    res = rank(b, user, empty_live(b.art, user), 10, None, None, None)  # day=None: test the mechanics, not the calendar
    if not res["exploit"]:
        raise RuntimeError("smoke test returned no recommendations")


# ------------------------------------------------------------------ Redis user state
def ukey(uid):
    return f"user:{uid}"


def ckey(uid):
    return f"recommendations:{uid}"


EVENT_POS = {"open": 0, "click": 1, "purchase": 2, "redemption": 3}  # index into the 4 interaction flags


def load_live(b: Bundle, user: dict, h: dict, user_id: str | None = None) -> dict:
    """Rebuild the user's live state at THIS moment = fold_history over everything the user has done so far: the dataset
    history (warm users; chronological) + the events recorded in Redis. It is the same function the trainer applies to a
    chronological prefix, so a user's features are identical in training and serving. A brand-new user has no
    entries: every live counter/preference is 0 and only static/profile data is used (cold start). After each click the
    event is already in Redis, so the very next call sees it as history (and as the anchor), never as a target."""
    a = b.art
    entries, ds_last = [], None
    hist = getattr(a, "user_hist", {}).get(user_id) if user_id else None
    if hist:
        for it, fl, cnt, sc in zip(hist["items"], hist["flags"], hist["count"], hist["score"]):
            entries.append(HistEntry(int(it), tuple(int(x) for x in fl), (0, 0, 0, 0), float(cnt), float(sc)))
        ds_last = int(hist["items"][-1])  # user_hist is chronological: the latest dataset interaction
    for k, v in (h or {}).items():
        if not k.startswith("ev:"):
            continue  # older state formats (cat:/offer: weights) are ignored; they were on a different score scale
        offer, ev = k[3:].rsplit(":", 1)
        item, pos = b.item_index.get(offer), EVENT_POS.get(ev)
        if item is None or pos is None:
            continue
        flags, n = [0, 0, 0, 0], [0, 0, 0, 0]
        flags[pos], n[pos] = 1, int(float(v))
        entries.append(HistEntry(int(item), tuple(flags), tuple(n), 0.0, None))
    live = fold_history(a, user, entries)
    live["n_events"] = int(float((h or {}).get("n_events", 0)))
    anchor = ds_last  # latest observed interaction = the anchor ("similar to your last click")
    if h and h.get("last_offer"):
        fresh = cfg.ANCHOR_MAX_AGE <= 0 or time.time() - float(h.get("last_ts", 0)) <= cfg.ANCHOR_MAX_AGE
        if fresh and b.item_index.get(h["last_offer"]) is not None:
            anchor = b.item_index[h["last_offer"]]
    live["anchor"] = live["last_item"] = anchor
    return live


def apply_event(r, b: Bundle, user_id: str, offer_id: str, event: str) -> str:
    """Record the event as a per-(offer, event) counter, drop the recommendation cache, push to the stream.
    Preferences and scores are derived from these counters at read time (see load_live)."""
    if offer_id not in b.item_index:
        raise KeyError(offer_id)
    event_id = uuid.uuid4().hex
    pipe = r.pipeline(transaction=True)
    k = ukey(user_id)
    pipe.hincrby(k, f"ev:{offer_id}:{event}", 1)
    pipe.hincrby(k, "n_events", 1)
    if event == "open":
        pipe.hincrby(k, "open_cnt", 1)
    if event == "purchase":
        pipe.hincrby(k, "purch_cnt", 1)
    pipe.hset(k, mapping={"last_offer": offer_id, "last_event": event, "last_ts": int(time.time())})
    pipe.expire(k, cfg.USER_TTL)
    pipe.delete(ckey(user_id))  # next request regenerates fresh recommendations
    pipe.xadd(cfg.STREAM, {"event_id": event_id, "user_id": user_id, "offer_id": offer_id,
                           "event": event, "ts": time.time()},
              maxlen=cfg.STREAM_MAXLEN, approximate=True)
    pipe.execute()
    return event_id


# ------------------------------------------------------------------ ranking
def resolve_area(b: Bundle, user: dict, area, lat, lon):
    """Where is the user now? request area > device location > profile governorate. -> (area|None, source, warning|None)
    An unknown `area` no longer hides a valid lat/lon: we fall through to the location and just warn."""
    warn = None
    if area:
        hit = b.area_index.get(geo.canonical(area))
        if hit:
            return hit, "request", None
        warn = f"Unknown area '{area}'."
    if lat is not None and lon is not None:
        near = geo.nearest_area(lat, lon, b.area_centroids, cfg.MAX_AREA_KM)
        if near:
            return near[0], "location", warn
        warn = (warn + " " if warn else "") + "Your location could not be matched to an area in the data."
    if user["gov"] in b.areas:
        return user["gov"], "profile", warn
    return None, "none", (warn + " No location filter applied.") if warn else None


def rank(b: Bundle, user: dict, live: dict, top_n: int, day, area, anchor) -> dict:
    """FILTERS (active on `day`, in `area`, not already seen) applied INSIDE the 6 retrieval channels (core.
    generate_candidates, the same function the trainer uses) -> 17 canonical features -> LGBMRanker. Offers similar to
    the last interaction (`anchor`) are added to the pool and the best are pinned. day=None: no date filter (smoke test)."""
    a = b.art
    ue = area_view(a, user, area)
    elig = eligible_mask(a, day, area)
    seen = np.zeros(len(a.item_ids), dtype=bool)
    if live["seen_idx"]:
        seen[list(live["seen_idx"])] = True
    open_ = elig & ~seen  # what the user may be shown: valid, in area, not interacted with before
    cand, cc, sim, text_all = generate_candidates(a, ue, live, open_, area, anchor)
    fb = np.where(elig & seen)[0]  # last resort only: already-seen offers, if nothing else is left to show
    fallback = [int(i) for i in fb[np.argsort(-a.pop[fb])][: cfg.MAX_TOP_N]]
    if len(cand) == 0:
        return {"exploit": [], "pinned": [], "explore": [], "fallback": fallback}

    feat_day = day if day is not None else as_of_day(a, cfg.AS_OF_DATE)
    scores = b.booster.predict(build_features(a, b.cols, ue, live, cand, cc, feat_day, text_all))
    exploit = [(int(cand[i]), float(scores[i])) for i in np.argsort(-scores)[: cfg.MAX_TOP_N]]
    score_of = dict(zip(cand.tolist(), scores.tolist()))
    pinned = sorted(((int(i), float(score_of[int(i)])) for i in sim), key=lambda t: -t[1])[: cfg.SIMILAR_PIN]

    idx = np.where(open_)[0]  # exploration pool: valid, unseen offers with the best signal quality
    q = a.static_cols["signal_quality"][idx] * 10 + a.static_cols["log_popularity"][idx]
    explore = [int(i) for i in idx[np.argsort(-q)][: cfg.MAX_TOP_N * 2]]
    return {"exploit": exploit, "pinned": pinned, "explore": explore, "fallback": fallback}


def assemble(b: Bundle, pools: dict, top_n: int, explore_frac: float) -> list:
    a = b.art
    n_exploit = max(1, int(round(top_n * (1 - explore_frac))))
    pinned = pools["pinned"][: min(cfg.SIMILAR_PIN, n_exploit)]
    pin_ids = {i for i, _ in pinned}
    rest = [(i, s) for i, s in pools["exploit"] if i not in pin_ids][: n_exploit - len(pinned)]
    out = [(i, s, "similar") for i, s in pinned] + [(i, s, "model") for i, s in rest]
    ids = {o[0] for o in out}
    cats = {int(a.offer_cat_idx[i]) for i in ids}
    for i in pools["explore"]:
        if len(out) >= top_n:
            break
        if i not in ids and int(a.offer_cat_idx[i]) not in cats:
            out.append((i, None, "explore"))
    used = {o[0] for o in out}
    for i, s in pools["exploit"]:  # top up if the exploration pool ran short
        if len(out) >= top_n:
            break
        if i not in used:
            out.append((i, s, "model"))
            used.add(i)
    for i in pools.get("fallback", []):  # only when the catalog is nearly exhausted for this user
        if len(out) >= top_n:
            break
        if i not in used:
            out.append((i, None, "repeat"))
            used.add(i)
    meta = getattr(a, "offer_meta", None)
    return [{"rank": r + 1, "offer_id": str(a.item_ids[i]), "score": None if s is None else round(s, 5),
             "source": src, "category": a.macro_cats[a.offer_cat_idx[i]], **(meta[i] if meta else {})}
            for r, (i, s, src) in enumerate(out[:top_n])]


def recommend(r, mgr: ModelManager, user_id: str, top_n: int, area=None, lat=None, lon=None) -> dict:
    b = mgr.bundle  # one reference for the whole request (safe across a hot swap)
    user = b.art.user_static.get(user_id, b.default_user)
    area, area_src, warn = resolve_area(b, user, area, lat, lon)
    day = b.as_of_day()
    base = {"model_version": b.version, "area": {"name": area, "source": area_src}, "as_of": b.as_of_date(day)}

    def done(cached, pools, explore_frac, anchor_id):
        recs = assemble(b, pools, top_n, explore_frac)
        w = warn
        if not recs:
            w = (f"No active offers as of {base['as_of']}" + (f" in area '{area}'" if area else "")
                 + ". Check AS_OF_DATE and the offer dates in your data.")
        return {**base, "cached": cached, "anchor_offer_id": anchor_id, "warning": w, "recommendations": recs}

    raw = r.get(ckey(user_id))
    if raw:
        c = json.loads(raw)
        if c["v"] == b.version and c["n"] >= top_n and c["area"] == (area or "") and c["day"] == day:
            return done(True, c["pools"], c["explore_frac"], c["anchor"])
    live = load_live(b, user, r.hgetall(ukey(user_id)), user_id)
    explore_frac = cfg.EXPLORE_FRAC if live["n_rows"] > 0 else 0.0  # notebook: no exploration for a cold slate
    n_build = max(top_n, 10)
    anchor = live["anchor"]
    pools = rank(b, user, live, n_build, day, area, anchor)
    anchor_id = str(b.art.item_ids[anchor]) if anchor is not None else None
    r.set(ckey(user_id), json.dumps({"v": b.version, "n": n_build, "area": area or "", "day": day, "anchor": anchor_id,
                                     "explore_frac": explore_frac, "pools": pools}), ex=cfg.CACHE_TTL)
    return done(False, pools, explore_frac, anchor_id)
