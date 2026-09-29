"""Model loading/hot-swap, Redis user state, and the recommendation flow (Stage 1 -> 17 features -> LGBM)."""
import json
import logging
import threading
import time
import uuid
from datetime import date
from pathlib import Path

import lightgbm as lgb
import numpy as np

from api import config as cfg
from common import registry
from common.build import load_artifacts
from common.core import (build_features, empty_live, retrieve, text_similarity, validity_filter)

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
        self.loaded_at = time.time()
        a = self.art
        self.cat_index = {c: i for i, c in enumerate(a.macro_cats)}
        self.item_index = a.item_index
        self.partner_name = {i: p for p, i in a.partner_index.items()}
        self.gt_name = {i: g for g, i in a.gt_index.items()}
        self.default_user = {
            "gov": "unknown", "gov_tag": -1, "cell": "unknown", "spend_amt": np.zeros(len(a.macro_cats), np.float32),
            "spend_norm": np.zeros(len(a.macro_cats), np.float32), "affluence": 1.0, "total_spend": 0.0,
            "top_cat_idx": 0, "top_cat": a.macro_cats[0], "flags": [0.0] * 4, "raw_open": 0.0, "raw_purch": 0.0}

    def live_day(self) -> int:
        if cfg.LIVE_DAY_MODE == "calendar":
            return (date.today() - date.fromisoformat(self.art.anchor_date)).days
        return int(self.art.eval_day)


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
    res = rank(b, user, empty_live(b.art, user), 10)
    if not res["exploit"]:
        raise RuntimeError("smoke test returned no recommendations")


# ------------------------------------------------------------------ Redis user state
def ukey(uid):
    return f"user:{uid}"


def ckey(uid):
    return f"recommendations:{uid}"


def load_live(b: Bundle, user: dict, h: dict) -> dict:
    """Rebuild the live feature state from the Redis hash."""
    live = empty_live(b.art, user)
    if not h:
        return live
    a = b.art
    for k, v in h.items():
        if k.startswith("cat:"):
            i = b.cat_index.get(k[4:])
            if i is not None:
                live["cat_pref"][i] = float(v)
        elif k.startswith("partner:"):
            i = a.partner_index.get(k[8:])
            if i is not None:
                live["partner_pref"][i] = float(v)
        elif k.startswith("gt:"):
            i = a.gt_index.get(k[3:])
            if i is not None:
                live["gt_pref"][i] = float(v)
        elif k.startswith("offer:"):
            item = b.item_index.get(k[6:])
            if item is not None:
                w = float(v)
                live["tfidf"] += w * a.tfidf_dense[item]
                live["seen_idx"].add(int(item))
                live["n_rows"] += 1
                live["sum_score"] += w
                live["max_score"] = max(live["max_score"], w)
    g = lambda f: float(h.get(f, 0))
    live["n_events"] = int(g("n_events"))
    live["total_interactions"] = g("n_events")
    live["redemptions"] = g("redemptions")
    live["waff_events"] = g("waff_events")
    live["open_intensity"] = user["raw_open"] + g("open_cnt")
    live["purch_intensity"] = user["raw_purch"] + g("purch_cnt")
    return live


def apply_event(r, b: Bundle, user_id: str, offer_id: str, event: str) -> str:
    """Update Redis user state, drop the recommendation cache, push to the stream. One round trip."""
    a = b.art
    item = b.item_index[offer_id]
    w = cfg.EVENT_WEIGHT[event]
    event_id = uuid.uuid4().hex
    p = a.offer_partner_idx[item]
    g = a.offer_gt_idx[item]
    pipe = r.pipeline(transaction=True)
    k = ukey(user_id)
    pipe.hincrbyfloat(k, f"cat:{a.macro_cats[a.offer_cat_idx[item]]}", w)
    if p < a.n_partners:
        pipe.hincrbyfloat(k, f"partner:{b.partner_name[int(p)]}", w)
    if g >= 0:
        pipe.hincrbyfloat(k, f"gt:{b.gt_name[int(g)]}", w)
    pipe.hincrbyfloat(k, f"offer:{offer_id}", w)
    pipe.hincrby(k, "n_events", 1)
    if event == "redemption":
        pipe.hincrby(k, "redemptions", 1)
    if event == "open":
        pipe.hincrby(k, "open_cnt", 1)
    if event == "purchase":
        pipe.hincrby(k, "purch_cnt", 1)
    if a.is_waffarha[item] > 0:
        pipe.hincrby(k, "waff_events", 1)
    pipe.hset(k, mapping={"last_offer": offer_id, "last_event": event, "last_ts": int(time.time())})
    pipe.expire(k, cfg.USER_TTL)
    pipe.delete(ckey(user_id))  # next request regenerates fresh recommendations
    pipe.xadd(cfg.STREAM, {"event_id": event_id, "user_id": user_id, "offer_id": offer_id,
                           "event": event, "ts": time.time()},
              maxlen=cfg.STREAM_MAXLEN, approximate=True)
    pipe.execute()
    return event_id


# ------------------------------------------------------------------ ranking
def rank(b: Bundle, user: dict, live: dict, top_n: int) -> dict:
    """Stage 1 (6 channels) -> validity filter -> 17 features -> LGBMRanker. Returns exploit + explore pools."""
    a = b.art
    day = b.live_day()
    text_all = text_similarity(a, live["tfidf"])
    cand, cc = retrieve(a, user, live, text_all)
    if len(cand) == 0:
        cand = a.nationwide_top[:100]
        cc = np.ones(len(cand), np.float32)
    cc_of = dict(zip(cand.tolist(), cc.tolist()))
    kept = validity_filter(a, cand, day, top_n)
    cand = kept
    cc = np.array([cc_of.get(int(i), 1.0) for i in kept], dtype=np.float32)  # backfilled items -> 1 channel
    X = build_features(a, b.cols, user, live, cand, cc, day, text_all)
    scores = b.booster.predict(X)
    order = np.argsort(-scores)[: cfg.MAX_TOP_N]
    exploit = [(int(cand[i]), float(scores[i])) for i in order]

    # exploration pool (notebook serving path): valid offers in user's governorate/nationwide, best signal quality
    valid = (a.start_day <= day) & (day <= a.end_day) & ((a.offer_gov == user["gov"]) | (a.offer_gov == "nationwide"))
    idx = np.where(valid)[0]
    q = a.static_cols["signal_quality"][idx] * 10 + a.static_cols["log_popularity"][idx]
    explore = [int(i) for i in idx[np.argsort(-q)][: cfg.MAX_TOP_N * 2]]
    return {"exploit": exploit, "explore": explore}


def assemble(b: Bundle, pools: dict, top_n: int, explore_frac: float) -> list:
    a = b.art
    n_exploit = max(1, int(round(top_n * (1 - explore_frac))))
    chosen = pools["exploit"][:n_exploit]
    ids = {i for i, _ in chosen}
    cats = {int(a.offer_cat_idx[i]) for i in ids}
    out = [(i, s, "model") for i, s in chosen]
    for i in pools["explore"]:
        if len(out) >= top_n:
            break
        if i not in ids and int(a.offer_cat_idx[i]) not in cats:
            out.append((i, None, "explore"))
    used = {o[0] for o in out}
    for i, s in pools["exploit"][n_exploit:]:  # top up if the exploration pool ran short
        if len(out) >= top_n:
            break
        if i not in used:
            out.append((i, s, "model"))
    meta = getattr(a, "offer_meta", None)
    return [{"rank": r + 1, "offer_id": str(a.item_ids[i]), "score": None if s is None else round(s, 5),
             "source": src, "category": a.macro_cats[a.offer_cat_idx[i]], **(meta[i] if meta else {})}
            for r, (i, s, src) in enumerate(out[:top_n])]


def recommend(r, mgr: ModelManager, user_id: str, top_n: int) -> dict:
    b = mgr.bundle  # one reference for the whole request (safe across a hot swap)
    raw = r.get(ckey(user_id))
    if raw:
        c = json.loads(raw)
        if c["v"] == b.version and c["n"] >= top_n:
            return {"model_version": b.version, "cached": True,
                    "recommendations": assemble(b, c["pools"], top_n, c["explore_frac"])}
    user = b.art.user_static.get(user_id, b.default_user)
    live = load_live(b, user, r.hgetall(ukey(user_id)))
    explore_frac = cfg.EXPLORE_FRAC if live["n_events"] > 0 else 0.0  # notebook: no exploration for a cold slate
    n_build = max(top_n, 10)
    pools = rank(b, user, live, n_build)
    r.set(ckey(user_id), json.dumps({"v": b.version, "n": n_build, "explore_frac": explore_frac, "pools": pools}),
          ex=cfg.CACHE_TTL)
    return {"model_version": b.version, "cached": False,
            "recommendations": assemble(b, pools, top_n, explore_frac)}
