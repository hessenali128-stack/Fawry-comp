"""Training service.

Flow: load data -> retrieval artifacts -> 34-feature table -> LGBMRanker(34) -> gain importance
      -> top 17 -> LGBMRanker(17) -> validation gates -> save models/vN -> publish current.json

Usage:
  python -m training.train --once        train one version now
  python -m training.train --schedule    weekly (Sunday 00:00) loop; bootstraps if no model exists
"""
import argparse
import datetime as dt
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
from common.core import (ALL_34, add_interaction, build_features, empty_live, retrieve,  # noqa: E402
                         save_json, text_similarity)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("train")

SEED = 42
MAX_NDCG_DROP = float(os.getenv("MAX_NDCG_DROP", "0.01"))      # 17-feature vs 34-feature (validation)
MAX_REGRESSION = float(os.getenv("MAX_REGRESSION", "0.02"))    # new vs current production (test)
KEEP_VERSIONS = int(os.getenv("KEEP_VERSIONS", "5"))
PARAMS = dict(objective="lambdarank", metric="ndcg", eval_at=[5, 10], boosting_type="gbdt",
              n_estimators=400, learning_rate=0.05, num_leaves=31, min_data_in_leaf=50, lambda_l2=1.0,
              feature_fraction=0.85, bagging_fraction=0.85, bagging_freq=1, random_state=SEED,
              verbosity=-1, importance_type="gain")


# ------------------------------------------------------------------ data
class MissingData(RuntimeError):
    pass


def require_data():
    need = ("user_features.csv", "train_interactions.csv", "offer_features.csv")
    missing = [f for f in need if not (Path(C.DATA_DIR) / f).exists()]
    if missing:
        raise MissingData(f"missing in {C.DATA_DIR}/: {', '.join(missing)} - add the dataset files, nothing is generated")


def events_to_interactions(conn, ti: pd.DataFrame, offers: pd.DataFrame, users: pd.DataFrame) -> pd.DataFrame:
    """Turn production events in PostgreSQL into interaction rows (one row per user+offer)."""
    with conn.cursor() as cur:
        cur.execute("SELECT user_id, offer_id, event, ts FROM events")
        ev = pd.DataFrame(cur.fetchall(), columns=["user_id", "offer_id", "event", "ts"])
    if ev.empty:
        return ti
    ev = ev[ev.user_id.isin(set(users.user_id)) & ev.offer_id.isin(set(offers.offer_id))]
    if ev.empty:
        return ti
    ev["day"] = (ev.ts - ev.ts.min()).dt.days + int(ti.days_since_first_event.max()) + 1
    waff = dict(zip(offers.offer_id, offers.offer_type.str.lower().eq("waffarha").astype(int)))
    rows = []
    for (u, o), g in ev.groupby(["user_id", "offer_id"]):
        cnt = g.event.value_counts()
        has = lambda e: int(cnt.get(e, 0) > 0)
        rows.append((u, o, sum(C.EVENT_WEIGHT[e] * n for e, n in cnt.items()), has("open"), has("click"),
                     has("purchase"), has("redemption"), waff.get(o, 0), int(cnt.sum()), int(g.day.max())))
    new = pd.DataFrame(rows, columns=["user_id", "offer_id", "score", "has_open", "has_investigation",
                                      "has_purchase", "has_redemption", "is_waffarha_signal",
                                      "interaction_count", "days_since_first_event"])
    log.info("merged %d interaction rows from %d production events", len(new), len(ev))
    return pd.concat([ti, new], ignore_index=True)


# ------------------------------------------------------------------ query table
def stratified_split(users_a, users_b, frac, seed):
    r = np.random.default_rng(seed)
    ua, ub = np.array(sorted(users_a)), np.array(sorted(users_b))
    r.shuffle(ua), r.shuffle(ub)
    na, nb = int(len(ua) * frac), int(len(ub) * frac)
    return set(ua[na:]) | set(ub[nb:]), set(ua[:na]) | set(ub[:nb])


def grade(r) -> float:
    return 4.0 if r.has_purchase else 2.0 if r.has_investigation else 1.0 if r.has_open else 0.0


def build_query_table(art, ti_all: pd.DataFrame, split_of: dict, tr_row: dict, history: str = "loo"):
    """One query per interaction row. history="loo" (default, as in the notebook): live state = ALL the user's other
    rows, including later ones. history="past": only rows from strictly earlier days (serving semantics).
    Features come from common.core.build_features - the same function the API calls."""
    X, y, qid, part, cold, hit = [], [], [], [], [], []
    by_user = {u: g.reset_index(drop=True) for u, g in ti_all.groupby("user_id")}
    q = 0
    t0 = time.time()
    for u, g in by_user.items():
        if u not in art.user_static:
            continue
        user = art.user_static[u]
        items = g.offer_id.map(art.item_index).to_numpy()
        day = g.days_since_first_event.to_numpy()
        split = split_of[u]
        for i, r in enumerate(g.itertuples(index=False)):
            tgt = int(items[i])
            live = empty_live(art, user)
            others = ([j for j in range(len(g)) if j != i] if history == "loo"
                      else [j for j in range(len(g)) if day[j] < day[i]])
            for j in others:
                rj = g.iloc[j]
                add_interaction(art, live, int(items[j]), float(rj.score), float(rj.interaction_count),
                                float(rj.has_redemption), float(rj.is_waffarha_signal))
            is_cold = len(others) == 0
            if is_cold:
                live["open_intensity"] = live["purch_intensity"] = 0.0
            else:
                live["open_intensity"] = max(user["raw_open"] - float(r.has_open), 0.0)
                live["purch_intensity"] = max(user["raw_purch"] - float(r.has_purchase), 0.0)
            live["seen_idx"].discard(tgt)  # Channels A/E never see the target
            text_all = text_similarity(art, live["tfidf"])
            cand, cc = retrieve(art, user, live, text_all,
                                exclude_row=tr_row.get(u) if split == "train" else None,
                                own_items=items if split == "train" else None)
            found = bool((cand == tgt).any())
            if split == "train" and not found:
                # notebook practice: inject the positive when retrieval missed it. Count is 1 (not 0):
                # a 0 can never occur naturally, so the ranker would learn "count==0 => positive" (leak).
                cand, cc = np.append(cand, tgt), np.append(cc, 1.0)
            feats = build_features(art, ALL_34, user, live, cand, cc, int(r.days_since_first_event), text_all)
            X.append(feats)
            lab = np.zeros(len(cand), np.float32)
            lab[cand == tgt] = grade(r)
            y.append(lab)
            qid.append(np.full(len(cand), q)), part.append(split), cold.append(is_cold), hit.append(found)
            q += 1
        if q and q % 2000 == 0:
            log.info("  built %d queries (%.0fs)", q, time.time() - t0)
    sizes = np.array([len(a) for a in y])
    df = pd.DataFrame(np.vstack(X), columns=ALL_34)
    df["label"] = np.concatenate(y)
    df["qid"] = np.concatenate(qid)
    meta = pd.DataFrame({"qid": np.arange(q), "split": part, "cold": cold, "retrieval_hit": hit})
    df = df.merge(meta, on="qid")
    log.info("query table: %d queries, %d rows, mean candidates %.0f", q, len(df), sizes.mean())
    return df, meta


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


# ------------------------------------------------------------------ main pipeline
def run_training() -> dict:
    require_data()
    users, ti, offers = load_raw(C.DATA_DIR)
    conn = None
    try:
        conn = db.connect(retries=5)
        db.init_schema(conn)
        db.seed_catalog(conn, users, offers)
        ti = events_to_interactions(conn, ti, offers, users)
    except Exception as e:  # DB is optional for training itself
        log.warning("postgres unavailable (%s) - training on dataset files only", e)

    version = registry.next_version()
    log.info("=== training %s ===", version)

    # splits: 100 sandbox users = untouched test; rest 85/15 train/val (stratified cold/warm)
    rng = np.random.default_rng(SEED)
    all_users = users.user_id.to_numpy()
    sandbox = set(rng.choice(all_users, size=min(100, len(all_users) // 10), replace=False))
    pool_ti = ti[~ti.user_id.isin(sandbox)]
    counts = pool_ti.groupby("user_id").size()
    train_u, val_u = stratified_split(set(counts[counts == 1].index), set(counts[counts > 1].index), 0.15, SEED)
    split_of = {**{u: "train" for u in train_u}, **{u: "val" for u in val_u}, **{u: "test" for u in sandbox}}
    log.info("users: train=%d val=%d test(sandbox)=%d", len(train_u), len(val_u), len(sandbox))

    log.info("building retrieval artifacts (fit on train users only)")
    art = build_artifacts(users, ti, offers, train_u)
    bank_users = sorted(ti[ti.user_id.isin(train_u)].user_id.unique())
    tr_row = {u: i for i, u in enumerate(bank_users)}

    log.info("building 34-feature query table")
    ti_use = ti[ti.user_id.isin(split_of)]
    tab, meta = build_query_table(art, ti_use, split_of, tr_row)
    tr, va, te = (tab[tab.split == s] for s in ("train", "val", "test"))
    recall150 = float(meta[meta.split != "train"].retrieval_hit.mean())
    log.info("Stage-1 recall@~candidates on val+test: %.4f", recall150)

    # ---- step 2-3: 34-feature model + gain importance
    m34 = fit_ranker(tr, va, ALL_34, "34 features")
    imp = pd.Series(m34.feature_importances_, index=ALL_34).sort_values(ascending=False)  # gain
    top17 = imp.index[: C.N_FEATURES_FINAL].tolist()
    assert set(top17) <= set(ALL_34)
    log.info("Top %d features by GAIN importance:", C.N_FEATURES_FINAL)
    for i, (f, v) in enumerate(imp.head(C.N_FEATURES_FINAL).items(), 1):
        log.info("  %2d. %-34s %14.1f", i, f, v)
    log.info("  dropped: %s", ", ".join(imp.index[C.N_FEATURES_FINAL:]))

    # ---- step 6: final 17-feature model
    m17 = fit_ranker(tr, va, top17, "top-17")

    val34, val17 = evaluate(m34, va, ALL_34), evaluate(m17, va, top17)
    test34, test17 = evaluate(m34, te, ALL_34), evaluate(m17, te, top17)
    pop_test = ndcg_at_10(te, te.log_popularity.to_numpy())
    pop_val = ndcg_at_10(va, va.log_popularity.to_numpy())
    log.info("NDCG@10 BEFORE (34 features) val=%.4f test=%.4f", val34["ndcg@10"], test34["ndcg@10"])
    log.info("NDCG@10 AFTER  (17 features) val=%.4f test=%.4f", val17["ndcg@10"], test17["ndcg@10"])
    log.info("popularity baseline NDCG@10  val=%.4f test=%.4f", pop_val, pop_test)

    # ---- validation gates
    gates = {
        "converged (best_iteration >= 20)": bool(m17.best_iteration_ and m17.best_iteration_ >= 20),
        f"val NDCG@10 (17) >= val NDCG@10 (34) - {MAX_NDCG_DROP}": val17["ndcg@10"] >= val34["ndcg@10"] - MAX_NDCG_DROP,
        "val NDCG@10 (17) >= popularity baseline": val17["ndcg@10"] >= pop_val,
    }
    cur = registry.read_current()
    cur_test = None
    if cur:
        try:
            cdir = registry.root() / cur["version"]
            cb = lgb.Booster(model_file=str(cdir / "model.txt"))
            ccols = json.loads((cdir / "feature_schema.json").read_text())["features"]
            cur_test = ndcg_at_10(te, cb.predict(te[ccols]))
            gates[f"test NDCG@10 >= current {cur['version']} ({cur_test:.4f}) - {MAX_REGRESSION}"] = (
                test17["ndcg@10"] >= cur_test - MAX_REGRESSION)
        except Exception as e:
            log.warning("could not score current model on new test set: %s", e)
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
        "features": top17, "n_features": len(top17),
        "importance_type": "gain", "importance_all_34": {k: float(v) for k, v in imp.items()}})
    metrics = {"val_34": val34, "val_17": val17, "test_34": test34, "test_17": test17,
               "popularity_val": pop_val, "popularity_test": pop_test, "stage1_recall": recall150,
               "current_test_ndcg": cur_test, "best_iteration_34": m34.best_iteration_,
               "best_iteration_17": m17.best_iteration_}
    meta_doc = {"version": version, "status": "ready" if passed else "rejected",
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "gates": gates,
                "metrics": metrics, "n_train_queries": int(tr.qid.nunique()),
                "n_val_queries": int(va.qid.nunique()), "n_test_queries": int(te.qid.nunique()),
                "n_offers": int(len(art.item_ids)), "n_users": int(len(users)), "params": PARAMS}
    save_json(tmp / "metadata.json", meta_doc)
    os.replace(tmp, vdir)

    if conn:
        try:
            db.record_version(conn, version, meta_doc["status"], len(top17), val34["ndcg@10"],
                              val17["ndcg@10"], {"gates": gates, "metrics": metrics})
        except Exception as e:
            log.warning("could not record version in postgres: %s", e)

    if passed:
        doc = registry.publish(version)
        log.info("=== %s READY and published: current=%s previous=%s ===", version, doc["version"], doc["previous"])
        prune()
    else:
        log.error("=== %s REJECTED - production stays on %s ===", version, (cur or {}).get("version"))
    return meta_doc


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
    while registry.read_current() is None:  # bootstrap: wait for the dataset files, then train the first model
        try:
            log.info("no production model yet -> bootstrap training")
            run_training()
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
