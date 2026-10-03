"""Does personalization really get better with more history?  Serving-faithful evaluation by number of PRIOR interactions.

Every val/test interaction (the model never trained on those users) is a query: Target = event_i, History = ONLY the
same user's earlier events (a chronological prefix, built by the same core.fold_history / generate_candidates /
build_features the API uses, with the same canonical 17 features). Queries are bucketed by how many interactions the
user had BEFORE the target (0 = brand-new / cold start) and compared with a popularity-only ranking on the same
candidate lists.

Nothing here assumes the metric rises with each interaction: the report gives, per bucket, NDCG@10 of the model and of
popularity, the paired lift (model - popularity) with a bootstrap 95% CI, and a rank-correlation test of lift vs
number of prior interactions. Small buckets are noisy - read the CI, not single cells.

Usage:  python scripts/eval_history.py --models models --data data [--version v3] [--boot 1000]
"""
import argparse
import json
import logging
import sys
import warnings
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")

from common.build import load_artifacts, load_raw  # noqa: E402
from common.core import CONTRACT, ContractError, assert_canonical  # noqa: E402
from training import train as T  # noqa: E402

BUCKETS = [-1, 0, 1, 2, 3, 5, 9, 10_000]
LABELS = ["0 (cold)", "1", "2", "3", "4-5", "6-9", "10+"]


def ndcg10(labels: np.ndarray, scores: np.ndarray) -> float:
    top = labels[np.argsort(-scores, kind="stable")][:10]
    ideal = np.sort(labels)[::-1][:10]
    disc = 1.0 / np.log2(np.arange(2, 12))
    idcg = ((2.0 ** ideal - 1) * disc[: len(ideal)]).sum()
    return float(((2.0 ** top - 1) * disc[: len(top)]).sum() / idcg) if idcg > 0 else 0.0


def boot_ci(x: np.ndarray, n: int, rng) -> tuple:
    if len(x) < 2:
        return (np.nan, np.nan)
    m = rng.choice(x, size=(n, len(x)), replace=True).mean(axis=1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="models")
    ap.add_argument("--data", default="data")
    ap.add_argument("--version", default=None, help="default: models/current.json")
    ap.add_argument("--boot", type=int, default=1000, help="bootstrap resamples for the confidence intervals")
    a = ap.parse_args()
    logging.disable(logging.CRITICAL)

    root = Path(a.models)
    version = a.version or json.loads((root / "current.json").read_text())["version"]
    users, ti, _ = load_raw(a.data)
    art = load_artifacts(root / version / "artifacts.pkl")
    meta_doc = json.loads((root / version / "metadata.json").read_text())
    if meta_doc.get("contract") != CONTRACT or getattr(art, "contract", "") != CONTRACT:
        raise ContractError(f"{version} was not trained under contract {CONTRACT}; retrain first")
    booster = lgb.Booster(model_file=str(root / version / "model.txt"))
    cols = json.loads((root / version / "feature_schema.json").read_text())["features"]
    assert_canonical(cols)  # the SAME 17 features, same order, as training and serving

    # the trainer's own split (stored in the artifacts); never re-derived, so val/test users are truly unseen
    split_of = art.split_of or T.make_splits(users, ti)[0]
    train_u = {u for u, s in split_of.items() if s == "train"}
    bank = sorted(ti[ti.user_id.isin(train_u)].user_id.unique())
    tr_row = {u: i for i, u in enumerate(bank)}
    ev_users = {u for u, s in split_of.items() if s != "train"}
    ledger = T.build_ledger(art, ti[ti.user_id.isin(ev_users)], None)  # dataset interactions, chronological
    tab, meta, qstats = T.build_query_table(art, ledger, split_of, tr_row)
    tab["model"] = booster.predict(tab[cols])
    prior = dict(zip(meta.qid, meta.prior))

    rows = []
    for qid, g in tab.groupby("qid", sort=False):
        lab = g.label.to_numpy()
        m, p = ndcg10(lab, g.model.to_numpy()), ndcg10(lab, g.log_popularity.to_numpy())
        rows.append((prior[qid], m, p, m - p, float(lab.max() > 0)))
    r = pd.DataFrame(rows, columns=["prior", "model", "popularity", "lift", "retrieved"])
    r["bucket"] = pd.cut(r.prior, BUCKETS, labels=LABELS)

    rng = np.random.default_rng(0)
    out = []
    for b, g in r.groupby("bucket", observed=True):
        lo, hi = boot_ci(g.lift.to_numpy(), a.boot, rng)
        out.append({"prior_interactions": b, "queries": len(g), "stage1_hit": round(g.retrieved.mean(), 3),
                    "model_ndcg10": round(g.model.mean(), 3), "popularity_ndcg10": round(g.popularity.mean(), 3),
                    "lift": round(g.lift.mean(), 3), "lift_ci95": f"[{lo:+.3f}, {hi:+.3f}]"})
    print(f"model {version} ({CONTRACT}): {len(r)} val+test queries | NDCG@10 model {r.model.mean():.3f} vs popularity "
          f"{r.popularity.mean():.3f} | repeat events skipped as targets: {qstats['repeat_events_not_targets']}")
    print(pd.DataFrame(out).to_string(index=False))

    warm = r[r.prior > 0]
    if len(warm) > 10 and warm.prior.nunique() > 1:
        rho, pv = stats.spearmanr(warm.prior, warm.lift)
        print(f"\nlift vs number of prior interactions (warm queries, n={len(warm)}): Spearman rho={rho:+.3f}, p={pv:.3f}")
    cold, hot = r[r.prior == 0].lift.to_numpy(), r[r.prior >= 3].lift.to_numpy()
    if len(cold) > 1 and len(hot) > 1:
        d = rng.choice(hot, (a.boot, len(hot))).mean(1) - rng.choice(cold, (a.boot, len(cold))).mean(1)
        print(f"lift(3+ prior) - lift(cold): {hot.mean() - cold.mean():+.3f}  "
              f"95% CI [{np.percentile(d, 2.5):+.3f}, {np.percentile(d, 97.5):+.3f}]  "
              "(CI containing 0 = no evidence that more history helps)")
    print("\nThe trend is measured, not assumed: it can be flat or non-monotonic. Small buckets are noisy.")


if __name__ == "__main__":
    main()
