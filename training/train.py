"""Training service.

Flow: load data (+ production events) -> event-level chronological ledger -> retrieval artifacts
      -> one query per interaction (Target = event_i, History = ONLY the user's earlier events)
      -> LGBMRanker on the FIXED canonical 17 features -> validation gates -> save models/vN -> publish current.json

Usage:
  python -m training.train --once        train one version now
  python -m training.train --schedule    weekly (Sunday 00:00) loop; bootstraps if no usable model exists
"""
import argparse
import datetime as dt
import hashlib
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import config as C  # noqa: E402
from common import db, registry  # noqa: E402
from common.build import build_artifacts, load_artifacts, load_raw, save_artifacts  # noqa: E402
from common.core import (CANONICAL_17, CONTRACT, HistEntry, LeakageError, area_view, as_of_day,  # noqa: E402
                         assert_canonical, build_features, default_user_static, eligible_mask, fit_score_table,
                         fold_history, generate_candidates, order_frame, profile_area, row_keys, save_json,
                         score_for_flags)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("train")

SEED = 42
MAX_REGRESSION = float(os.getenv("MAX_REGRESSION", "0.02"))    # new vs current production (test)
KEEP_VERSIONS = int(os.getenv("KEEP_VERSIONS", "5"))
BOOTSTRAP_RETRY_S = int(os.getenv("BOOTSTRAP_RETRY_SECONDS", "900"))
# Regularised: with ~1 positive per query and a median of 2 interactions per user the old settings overfit
# (the final model stopped at 3 iterations). Chosen on validation queries with past-only history.
PARAMS = dict(objective="lambdarank", metric="ndcg", eval_at=[5, 10], boosting_type="gbdt",
              n_estimators=600, learning_rate=0.03, num_leaves=15, min_data_in_leaf=300, lambda_l2=10.0,
              feature_fraction=0.6, bagging_fraction=0.85, bagging_freq=1, random_state=SEED,
              verbosity=-1, importance_type="gain")


# ------------------------------------------------------------------ data
class MissingData(RuntimeError):
    pass


def require_data():
    need = ("user_features.csv", "train_interactions.csv", "offer_features.csv")
    missing = [f for f in need if not (Path(C.DATA_DIR) / f).exists()]
    if missing:
        raise MissingData(f"missing in {C.DATA_DIR}/: {', '.join(missing)} - add the dataset files, nothing is generated")


EVENT_POS = {"open": 0, "click": 1, "purchase": 2, "redemption": 3}  # index into the 4 interaction flags
_FLAG_NAMES = ("has_open", "has_investigation", "has_purchase", "has_redemption")


def load_production_events(conn, offers: pd.DataFrame) -> pd.DataFrame:
    """The production event LEDGER from PostgreSQL, one row per event, ordered by (user_id, ts, event_id).
    Nothing is aggregated here, so the order of a user's events survives until the training queries are built."""
    with conn.cursor() as cur:
        cur.execute("SELECT event_id, user_id, offer_id, event, ts FROM events ORDER BY user_id, ts, event_id")
        ev = pd.DataFrame(cur.fetchall(), columns=["event_id", "user_id", "offer_id", "event", "ts"])
    if ev.empty:
        return ev
    ev = ev[ev.offer_id.isin(set(offers.offer_id)) & ev.event.isin(EVENT_POS)].copy()
    ev["ts"] = pd.to_datetime(ev.ts, utc=True)
    return ev.sort_values(["user_id", "ts", "event_id"], kind="stable").reset_index(drop=True)


def events_to_rows(ev: pd.DataFrame, ti: pd.DataFrame, offers: pd.DataFrame, users: pd.DataFrame,
                   score_table: dict) -> pd.DataFrame:
    """(user, offer) ROWS of the production events of dataset users. Only for the order-free population statistics of
    the retrieval artifacts and for the stored history served to those users; the training QUERIES come from the
    event-level ledger (build_ledger), never from these aggregated rows."""
    ev = ev[ev.user_id.isin(set(users.user_id))]
    if ev.empty:
        return ti
    waff = dict(zip(offers.offer_id, offers.offer_type.str.lower().eq("waffarha").astype(int)))
    day0 = int(ti.days_since_first_event.max()) + 1
    t0 = ev.ts.min()
    rows = []
    for (u, o), g in ev.groupby(["user_id", "offer_id"], sort=False):
        cnt = g.event.value_counts()
        has = lambda e: int(cnt.get(e, 0) > 0)
        score = score_for_flags(score_table, has("open"), has("click"), has("purchase"), has("redemption"))
        last = g.iloc[-1]  # the row's position in the user's history = its LAST event (drives the serving anchor)
        rows.append((u, o, score, has("open"), has("click"), has("purchase"), has("redemption"), waff.get(o, 0),
                     int(cnt.sum()), day0 + int((last.ts - t0).days), 1, last.ts.timestamp(), str(last.event_id)))
    new = pd.DataFrame(rows, columns=["user_id", "offer_id", "score", "has_open", "has_investigation",
                                      "has_purchase", "has_redemption", "is_waffarha_signal", "interaction_count",
                                      "days_since_first_event", "_src", "_tsk", "_tie"])
    log.info("merged %d interaction rows from %d production events (artifacts only; queries use the event ledger)",
             len(new), len(ev))
    return pd.concat([ti, new], ignore_index=True)


# ------------------------------------------------------------------ event ledger
def build_ledger(art, ti: pd.DataFrame, ev: pd.DataFrame | None) -> pd.DataFrame:
    """Event-level chronological ledger of every user: dataset rows (one entry per row, ordered by day, then by the
    optional dataset timestamp column, then CSV position) followed by the production events (ordered by ts, event_id).
    Columns: user_id, item, ff0..3 flags, nn0..3 per-type event counts, base_count, ds_score, cal (is the entry's
    day on the offers' calendar?), _day, plus the sort keys _src/_day/_tsk/_tie. Sorted by core.order_frame."""
    known = ti.offer_id.isin(art.item_index)
    d = ti[known]
    parts = [pd.DataFrame({
        "user_id": d.user_id.to_numpy(), "item": d.offer_id.map(art.item_index).to_numpy().astype(int),
        **{f"ff{k}": d[c].gt(0).astype(int).to_numpy() for k, c in enumerate(_FLAG_NAMES)},
        **{f"nn{k}": 0 for k in range(4)},
        "base_count": d.interaction_count.astype(float).to_numpy(), "ds_score": d.score.astype(float).to_numpy(),
        "days_since_first_event": d.days_since_first_event.astype(int).to_numpy(),
        "_src": 0, "_pos": d["_pos"].to_numpy(), "cal": bool(art.day_axis_aligned),
        **({c: d[c].to_numpy() for c in ("event_ts", "first_event_ts", "ts", "timestamp") if c in d.columns}),
    })]
    if ev is not None and len(ev):
        pos = ev.event.map(EVENT_POS).to_numpy()
        onehot = {f"ff{k}": (pos == k).astype(int) for k in range(4)}
        parts.append(pd.DataFrame({
            "user_id": ev.user_id.to_numpy(), "item": ev.offer_id.map(art.item_index).to_numpy().astype(int),
            **onehot, **{f"nn{k}": onehot[f"ff{k}"] for k in range(4)},
            "base_count": 0.0, "ds_score": np.nan,
            # the day the API would have used for this event (AS_OF_DATE): same reference in training and serving
            "days_since_first_event": [as_of_day(art, C.AS_OF_DATE, t.date()) for t in ev.ts],
            "_src": 1, "_tsk": ev.ts.map(lambda t: t.timestamp()).to_numpy(), "_tie": ev.event_id.astype(str).to_numpy(),
            "cal": True,
        }))
    led = pd.concat(parts, ignore_index=True)
    return order_frame(led)


def new_user_split(u: str) -> str:
    """Users that are not in user_features.csv (sign-ups) have no split: assign one by a stable hash (never test)."""
    return "val" if int(hashlib.md5(u.encode()).hexdigest(), 16) % 100 < 15 else "train"


# ------------------------------------------------------------------ query table
def stratified_split(users_a, users_b, frac, seed):
    r = np.random.default_rng(seed)
    ua, ub = np.array(sorted(users_a)), np.array(sorted(users_b))
    r.shuffle(ua), r.shuffle(ub)
    na, nb = int(len(ua) * frac), int(len(ub) * frac)
    return set(ua[na:]) | set(ub[nb:]), set(ua[:na]) | set(ub[:nb])


def make_splits(users: pd.DataFrame, ti: pd.DataFrame):
    """100 sandbox users = untouched test; the rest 85/15 train/val, stratified cold (1 row) / warm (>1 rows)."""
    rng = np.random.default_rng(SEED)
    all_users = users.user_id.to_numpy()
    sandbox = set(rng.choice(all_users, size=min(100, len(all_users) // 10), replace=False))
    pool_ti = ti[~ti.user_id.isin(sandbox)]
    counts = pool_ti.groupby("user_id").size()
    train_u, val_u = stratified_split(set(counts[counts == 1].index), set(counts[counts > 1].index), 0.15, SEED)
    split_of = {**{u: "train" for u in train_u}, **{u: "val" for u in val_u}, **{u: "test" for u in sandbox}}
    return split_of, train_u, sandbox


def grade(ff) -> float:
    """Relevance of the TARGET event: purchase/redemption 4, click 2, open 1."""
    return 4.0 if (ff[2] or ff[3]) else 2.0 if ff[1] else 1.0 if ff[0] else 0.0


def build_query_table(art, ledger: pd.DataFrame, split_of: dict, tr_row: dict):
    """Sequential point-in-time queries: ONE query per interaction event i of a user, in chronological order.
        Target  = event_i
        History = ONLY the events strictly before it in the user's ledger  (A,B,C -> [], [A], [A,B])
    Never leave-one-out: a target never sees a later event. Everything that depends on history (live preferences,
    counters, retrieval seeds, anchor = the previous event) is rebuilt from that prefix by core.fold_history - the
    function the API uses. Candidates come from core.generate_candidates (eligibility filters inside the 6 channels),
    features from core.build_features(CANONICAL_17). Events on an offer the user already touched are history
    updates, not targets (serving never recommends a seen offer).
    Returns (table, meta, stats)."""
    X, y, qid, part, cold, hit, prior, uid = [], [], [], [], [], [], [], []
    q, skipped, repeats = 0, 0, 0
    t0, next_log = time.time(), 2000
    for u, g in ledger.groupby("user_id", sort=False):
        user = art.user_static.get(u) or default_user_static(art)
        sp = split_of.get(u) or new_user_split(u)
        in_bank = sp == "train" and u in tr_row
        items = g["item"].to_numpy()
        keys = row_keys(g)
        if any(k2 <= k1 for k1, k2 in zip(keys, keys[1:])):  # strictly increasing = a real, unambiguous order
            raise LeakageError(f"ledger of {u} is not strictly chronological")
        ff, nn = g[[f"ff{k}" for k in range(4)]].to_numpy(), g[[f"nn{k}" for k in range(4)]].to_numpy()
        base, ds = g["base_count"].to_numpy(), g["ds_score"].to_numpy()
        entries = [HistEntry(int(items[i]), tuple(ff[i]), tuple(nn[i]), float(base[i]),
                             None if np.isnan(ds[i]) else float(ds[i])) for i in range(len(g))]
        days, cal = g["_day"].to_numpy(), g["cal"].to_numpy()
        area = profile_area(art, user)  # same area the API falls back to when no request area / location is given
        ue = area_view(art, user, area)
        own = np.unique(items) if in_bank else None  # train users only: remove their own contribution (see core.retrieve)
        seen_items = set()
        for i in range(len(g)):
            tgt = int(items[i])
            if tgt in seen_items:  # repeat event on an already-seen offer: updates the history, is not a target
                repeats += 1
                continue
            live = fold_history(art, user, entries[:i], keys[:i], keys[i])  # raises if the target/future leaks in
            if tgt in live["seen_idx"] or live["n_rows"] != len(seen_items):
                raise LeakageError("target offer or future event present in the history state")
            seen_items.add(tgt)
            is_cold = i == 0
            day = int(days[i]) if cal[i] else None  # None = this entry has no calendar date (see config.DAY0_DATE)
            seen = np.zeros(len(art.item_ids), dtype=bool)
            if live["seen_idx"]:
                seen[list(live["seen_idx"])] = True
            open_ = eligible_mask(art, day, area) & ~seen
            cand, cc, _, text_all = generate_candidates(
                art, ue, live, open_, area, live["last_item"],
                exclude_row=tr_row.get(u) if in_bank else None, own_items=own)
            found = bool((cand == tgt).any())
            if sp == "train" and not found:
                if not C.INJECT_MISSED_POSITIVE:
                    skipped += 1
                    continue  # nothing to rank: the positive is outside the candidate set (as it would be in serving)
                # notebook practice (INJECT_MISSED_POSITIVE=1): inject the positive when retrieval missed it. Count is
                # 1 (not 0): a 0 can never occur naturally, so the ranker would learn "count==0 => positive" (leak).
                cand, cc = np.append(cand, tgt), np.append(cc, 1.0)
            live_day = day if day is not None else as_of_day(art)  # the API's reference day when no calendar date
            X.append(build_features(art, CANONICAL_17, ue, live, cand, cc, live_day, text_all))
            lab = np.zeros(len(cand), np.float32)
            lab[cand == tgt] = grade(ff[i])
            y.append(lab)
            qid.append(np.full(len(cand), q)), part.append(sp), cold.append(is_cold), hit.append(found)
            prior.append(i), uid.append(u)
            q += 1
        if q >= next_log:
            log.info("  built %d queries (%.0fs)", q, time.time() - t0)
            next_log += 2000
    sizes = np.array([len(a) for a in y])
    df = pd.DataFrame(np.vstack(X), columns=CANONICAL_17)
    df["label"] = np.concatenate(y)
    df["qid"] = np.concatenate(qid)
    meta = pd.DataFrame({"qid": np.arange(q), "split": part, "cold": cold, "retrieval_hit": hit, "prior": prior,
                         "user_id": uid})
    df = df.merge(meta[["qid", "split", "cold", "retrieval_hit"]], on="qid")
    stats = {"queries": q, "train_skipped_not_retrieved": skipped, "repeat_events_not_targets": repeats}
    log.info("query table: %d queries, %d rows, mean candidates %.0f (%d train queries skipped: positive not retrieved; "
             "%d repeat events used as history only)", q, len(df), sizes.mean(), skipped, repeats)
    return df, meta, stats


# ------------------------------------------------------------------ metrics / models
def ndcg_at_10(df: pd.DataFrame, scores: np.ndarray) -> float:
    d = df[["qid", "label"]].copy()
    d["s"] = scores
    out = []
    for _, g in d.groupby("qid", sort=False):
        lab = g.label.to_numpy()
        top = lab[np.argsort(-g.s.to_numpy(), kind="stable")][:10]
        ideal = np.sort(lab)[::-1][:10]
        disc = 1.0 / np.log2(np.arange(2, 12))
        idcg = ((2.0 ** ideal - 1) * disc[: len(ideal)]).sum()
        out.append(((2.0 ** top - 1) * disc[: len(top)]).sum() / idcg if idcg > 0 else 0.0)
    return float(np.mean(out)) if out else 0.0


def recall_at_10(df: pd.DataFrame, scores: np.ndarray) -> float:
    d = df[["qid", "label"]].copy()
    d["s"] = scores
    hits = [(g.label.to_numpy()[np.argsort(-g.s.to_numpy(), kind="stable")][:10] > 0).any()
            for _, g in d.groupby("qid", sort=False)]
    return float(np.mean(hits)) if hits else 0.0


def fit_ranker(train: pd.DataFrame, val: pd.DataFrame, cols: list, tag: str) -> lgb.LGBMRanker:
    train, val = train.sort_values("qid", kind="stable"), val.sort_values("qid", kind="stable")
    g_tr = train.groupby("qid", sort=False).size().to_numpy()
    g_va = val.groupby("qid", sort=False).size().to_numpy()
    log.info("[%s] train %d queries / %d rows | val %d queries", tag, len(g_tr), len(train), len(g_va))
    m = lgb.LGBMRanker(**PARAMS)
    m.fit(train[cols], train.label, group=g_tr, eval_set=[(val[cols], val.label)], eval_group=[g_va],
          callbacks=[lgb.early_stopping(150, verbose=False), lgb.log_evaluation(100)])
    log.info("[%s] best_iteration=%s", tag, m.best_iteration_)
    return m


def evaluate(model, df, cols) -> dict:
    s = model.predict(df[cols])
    return {"ndcg@10": ndcg_at_10(df, s), "recall@10": recall_at_10(df, s)}


def day_alignment_report(art, ti: pd.DataFrame) -> dict:
    """Do days_since_first_event and the offers' start/end dates live on the same calendar? If most interactions
    happen on offers that 'have not started yet', they do not, and any date-derived feature is meaningless."""
    items = ti.offer_id.map(art.item_index)
    ok = items.notna().to_numpy()
    it, d = items[ok].astype(int).to_numpy(), ti.days_since_first_event.to_numpy()[ok]
    rep_ = {"anchor_date": art.anchor_date,
            "share_before_offer_start": float((art.start_day[it] > d).mean()),
            "share_after_offer_end": float((art.end_day[it] < d).mean())}
    bad = rep_["share_before_offer_start"] > 0.05 or rep_["share_after_offer_end"] > 0.05
    rep_["aligned"] = not bad
    if bad:
        log.warning("DAY AXIS MISMATCH: %.1f%% of interactions are dated BEFORE their offer starts and %.1f%% AFTER it "
                    "ends (day 0 assumed = %s). Dataset rows therefore carry no usable calendar date: the date filter is "
                    "not applied to their training queries and log_days_to_expire is evaluated at the API's reference "
                    "day (AS_OF_DATE). Production events always use their real date. Fix: set DAY0_DATE to the real "
                    "date of day 0.", 100 * rep_["share_before_offer_start"], 100 * rep_["share_after_offer_end"],
                    art.anchor_date)
    return rep_


# ------------------------------------------------------------------ main pipeline
def current_usable() -> bool:
    """Is a published model present AND trained under the sequential point-in-time / canonical-17 contract?"""
    cur = registry.read_current()
    if not cur:
        return False
    try:
        return json.loads((registry.root() / cur["version"] / "metadata.json").read_text()).get("contract") == CONTRACT
    except Exception:
        return False


def run_training() -> dict:
    require_data()
    users, ti_ds, offers = load_raw(C.DATA_DIR)
    conn, ev, ti_rows = None, None, ti_ds
    score_table = fit_score_table(ti_ds)  # event -> score calibration, fitted on the dataset rows
    log.info("score table (flags open|click|buy|redeem -> mean score, n): %s",
             {f"{k:04b}"[::-1]: (round(m, 2), n) for k, (m, n) in sorted(score_table.items())})
    try:
        conn = db.connect(retries=5)
        db.init_schema(conn)
        db.seed_catalog(conn, users, offers)
        ev = load_production_events(conn, offers)
        ti_rows = events_to_rows(ev, ti_ds, offers, users, score_table)
    except Exception as e:  # DB is optional for training itself
        log.warning("postgres unavailable (%s) - training on dataset files only", e)

    version = registry.next_version()
    log.info("=== training %s ===", version)

    split_of, train_u, sandbox = make_splits(users, ti_rows)
    log.info("users: train=%d val=%d test(sandbox)=%d", len(train_u), sum(v == "val" for v in split_of.values()),
             len(sandbox))

    log.info("building retrieval artifacts (fit on train users only)")
    art = build_artifacts(users, ti_rows, offers, train_u, score_table, split_of)
    alignment = day_alignment_report(art, ti_ds)
    art.day_axis_aligned = bool(alignment["aligned"])
    ts_col = next((c for c in ("event_ts", "first_event_ts", "ts", "timestamp") if c in ti_ds.columns), None)
    log.info("order inside a day: dataset rows by %s, production events by (ts, event_id)",
             f"the '{ts_col}' column" if ts_col else "CSV position (the dataset has no intra-day timestamp)")
    log.info("canonical features (%d): %s", len(CANONICAL_17), ", ".join(CANONICAL_17))
    bank_users = sorted(ti_rows[ti_rows.user_id.isin(train_u)].user_id.unique())
    tr_row = {u: i for i, u in enumerate(bank_users)}

    ledger = build_ledger(art, ti_ds[ti_ds.user_id.isin(split_of)], ev)
    log.info("ledger: %d events (%d production) of %d users", len(ledger), int((ledger._src == 1).sum()),
             ledger.user_id.nunique())
    log.info("building the sequential point-in-time query table (Target=event_i, History=earlier events only)")
    tab, meta, qstats = build_query_table(art, ledger, split_of, tr_row)
    tr, va, te = (tab[tab.split == s] for s in ("train", "val", "test"))
    recall150 = float(meta[meta.split != "train"].retrieval_hit.mean())
    log.info("Stage-1 recall@~candidates on val+test: %.4f", recall150)

    # ---- the ranker: LambdaRank on the FIXED canonical 17 (no feature selection)
    cols = list(CANONICAL_17)
    assert_canonical(cols)
    m17 = fit_ranker(tr, va, cols, "canonical-17")
    imp = pd.Series(m17.feature_importances_, index=cols).sort_values(ascending=False)  # gain, informational only
    log.info("gain importance of the canonical 17:")
    for i, (f, v) in enumerate(imp.items(), 1):
        log.info("  %2d. %-34s %14.1f", i, f, v)

    val17, test17 = evaluate(m17, va, cols), evaluate(m17, te, cols)
    pop_test = ndcg_at_10(te, te.log_popularity.to_numpy())
    pop_val = ndcg_at_10(va, va.log_popularity.to_numpy())
    log.info("NDCG@10 (17 features) val=%.4f test=%.4f", val17["ndcg@10"], test17["ndcg@10"])
    log.info("popularity baseline NDCG@10  val=%.4f test=%.4f", pop_val, pop_test)

    # ---- validation gates
    gates = {
        "converged (best_iteration >= 20)": bool(m17.best_iteration_ and m17.best_iteration_ >= 20),
        "val NDCG@10 >= popularity baseline": val17["ndcg@10"] >= pop_val,
    }
    cur = registry.read_current()
    cur_test = None
    if cur and current_usable():  # only compare with a model trained under the same contract
        try:
            cdir = registry.root() / cur["version"]
            cb = lgb.Booster(model_file=str(cdir / "model.txt"))
            ccols = json.loads((cdir / "feature_schema.json").read_text())["features"]
            cur_test = ndcg_at_10(te, cb.predict(te[ccols]))
            gates[f"test NDCG@10 >= current {cur['version']} ({cur_test:.4f}) - {MAX_REGRESSION}"] = (
                test17["ndcg@10"] >= cur_test - MAX_REGRESSION)
        except Exception as e:
            log.warning("could not score current model on new test set: %s", e)
    elif cur:
        log.info("current model %s was trained under an older contract - not used as a regression baseline",
                 cur["version"])
    passed = all(gates.values())
    for k, v in gates.items():
        log.info("gate %-70s %s", k, "PASS" if v else "FAIL")

    # ---- save (versions are immutable; rejected ones stay on disk but are never published)
    vdir = registry.root() / version
    tmp = registry.root() / f".{version}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    m17.booster_.save_model(str(tmp / "model.txt"), num_iteration=m17.best_iteration_)
    save_artifacts(art, tmp / "artifacts.pkl")
    save_json(tmp / "feature_schema.json", {
        "features": cols, "n_features": len(cols), "contract": CONTRACT, "feature_selection": "none (fixed canonical 17)",
        "importance_type": "gain", "importance": {k: float(v) for k, v in imp.items()}})
    metrics = {"val_17": val17, "test_17": test17, "popularity_val": pop_val, "popularity_test": pop_test,
               "stage1_recall": recall150, "current_test_ndcg": cur_test, "best_iteration_17": m17.best_iteration_}
    meta_doc = {"version": version, "status": "ready" if passed else "rejected", "contract": CONTRACT,
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "gates": gates,
                "history": "sequential point-in-time: Target=event_i, History=only earlier events (no leave-one-out)",
                "metrics": metrics, "n_train_queries": int(tr.qid.nunique()),
                "n_val_queries": int(va.qid.nunique()), "n_test_queries": int(te.qid.nunique()),
                "n_offers": int(len(art.item_ids)), "n_users": int(len(users)), "params": PARAMS,
                "queries": qstats, "n_ledger_events": int(len(ledger)),
                "n_production_events": int((ledger._src == 1).sum()),
                "intraday_order": f"dataset '{ts_col}' column" if ts_col else "CSV position (no intra-day timestamp)",
                "day_alignment": alignment, "score_table": {str(k): list(v) for k, v in score_table.items()}}
    save_json(tmp / "metadata.json", meta_doc)
    os.replace(tmp, vdir)

    if conn:
        try:  # ndcg_before = popularity-only baseline, ndcg_after = the model (validation)
            db.record_version(conn, version, meta_doc["status"], len(cols), pop_val,
                              val17["ndcg@10"], {"gates": gates, "metrics": metrics})
        except Exception as e:
            log.warning("could not record version in postgres: %s", e)

    if passed:
        doc = registry.publish(version)
        log.info("=== %s READY and published: current=%s previous=%s ===", version, doc["version"], doc["previous"])
        prune()
    else:
        log.error("=== %s REJECTED - production stays on %s ===", version, (cur or {}).get("version"))
        prune_rejected()
    return meta_doc


def prune_rejected(keep_last: int = 2):
    """Rejected versions are never served; keep only the newest few for inspection so repeated failures cannot fill the disk."""
    rej = []
    for v in registry.versions():
        try:
            if json.loads((registry.root() / v / "metadata.json").read_text()).get("status") == "rejected":
                rej.append(v)
        except Exception:
            continue
    for v in rej[:-keep_last] if keep_last else rej:
        shutil.rmtree(registry.root() / v, ignore_errors=True)


def prune():
    cur = registry.read_current() or {}
    keep = {cur.get("version"), cur.get("previous")} | set(registry.versions()[-KEEP_VERSIONS:])
    for v in registry.versions():
        if v not in keep:
            shutil.rmtree(registry.root() / v, ignore_errors=True)


# ------------------------------------------------------------------ scheduler
def seconds_until_next_run(now: dt.datetime, weekday: int = 6, hour: int = 0) -> float:
    """Next weekly run (default Sunday 00:00 local container time)."""
    days = (weekday - now.weekday()) % 7
    nxt = (now + dt.timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    if nxt <= now:
        nxt += dt.timedelta(days=7)
    return (nxt - now).total_seconds()


def schedule_loop():
    while not current_usable():  # bootstrap: no model, or only an old-contract one the API refuses to serve
        try:
            log.info("no production model yet -> bootstrap training")
            run_training()
            if not current_usable():  # trained but REJECTED: do not retrain in a tight loop
                log.error("bootstrap model was rejected - retrying in %d s (fix the data/gates first)", BOOTSTRAP_RETRY_S)
                time.sleep(BOOTSTRAP_RETRY_S)
        except MissingData as e:
            log.error("%s - retrying in 30 s", e)
            time.sleep(30)
        except Exception:
            log.exception("bootstrap training failed - retrying in 120 s")
            time.sleep(120)
    while True:
        wait = seconds_until_next_run(dt.datetime.now())
        log.info("next weekly training in %.1f h", wait / 3600)
        time.sleep(wait)
        try:
            run_training()
        except Exception:
            log.exception("weekly training failed - production model unchanged")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--schedule", action="store_true")
    a = ap.parse_args()
    if a.schedule:
        schedule_loop()
    else:
        try:
            res = run_training()
        except MissingData as e:
            sys.exit(f"ERROR: {e}")
        sys.exit(0 if res["status"] == "ready" else 1)
