"""Shared logic for training and serving: text cleaning, artifacts, Stage-1 channels, features.

The API and the trainer import the SAME functions, so a feature has one definition.
"""
import json
import re
from collections import namedtuple
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.preprocessing import normalize

from common import config as _cfg

ALL_34 = [
    "log_price", "discount_norm", "signal_quality", "log_popularity", "offer_purchase_rate",
    "offer_redemption_rate", "cash_amount_norm", "dtype_percentage", "dtype_fixed", "dtype_unknown",
    "is_waffarha_offer", "cat_affinity_score", "waffarha_synergy", "cat_match_top_spend",
    "retrieval_channel_count", "user_candidate_partner_affinity", "user_spend_in_candidate_category",
    "affordability_ratio", "user_has_yc", "user_has_bnpl", "user_has_credit", "user_has_debit",
    "user_total_interactions", "user_avg_score", "user_max_score", "user_waffarha_affinity",
    "user_redemption_rate_hist", "expanded_geo_match", "discount_cash_impact", "log_days_to_expire",
    "yc_category_share", "description_tfidf_sim", "user_30d_open_intensity", "user_30d_conversion_ratio",
]

# THE production feature contract: the 17 features (names, ORDER and formulas) used by training, evaluation and
# serving. They are NOT re-selected from the 34 on each training run. Order = gain order of the model that was in
# production when the contract was frozen (models/v1/feature_schema.json). ALL_34 stays the full catalogue
# (build_features can compute all of them) so old model versions still load.
CANONICAL_17 = [
    "log_days_to_expire", "log_popularity", "retrieval_channel_count", "offer_purchase_rate", "cat_affinity_score",
    "log_price", "description_tfidf_sim", "discount_norm", "user_candidate_partner_affinity",
    "user_total_interactions", "affordability_ratio", "user_avg_score", "waffarha_synergy",
    "user_waffarha_affinity", "user_max_score", "user_30d_open_intensity", "discount_cash_impact",
]
assert len(CANONICAL_17) == 17 and set(CANONICAL_17) <= set(ALL_34) and len(set(CANONICAL_17)) == 17

# Marks models trained with sequential point-in-time history + the canonical 17. The API refuses other models.
CONTRACT = "seq-pit-17-v1"


class ContractError(RuntimeError):
    pass


class LeakageError(AssertionError):
    pass


def assert_canonical(cols) -> None:
    if list(cols) != CANONICAL_17:
        raise ContractError(f"feature schema differs from the canonical 17: {list(cols)}")


FLAG_COLS = ("has_open", "has_investigation", "has_purchase", "has_redemption")
_LEGACY_FLAG_SCORE = (1.0, 1.0, 3.0, 2.0)  # only for model versions saved before score tables existed


def flag_key(o, i, p, r) -> int:
    return int(o > 0) | (int(i > 0) << 1) | (int(p > 0) << 2) | (int(r > 0) << 3)


def fit_score_table(ti: pd.DataFrame) -> dict:
    """flag-combination -> (mean row score, n rows), measured on the data the model is trained on."""
    key = (ti["has_open"].gt(0).astype(int) + 2 * ti["has_investigation"].gt(0).astype(int)
           + 4 * ti["has_purchase"].gt(0).astype(int) + 8 * ti["has_redemption"].gt(0).astype(int))
    g = ti.assign(_k=key).groupby("_k")["score"].agg(["mean", "count"])
    return {int(k): (float(r["mean"]), int(r["count"])) for k, r in g.iterrows()}


def score_for_flags(table: dict, o, i, p, r, min_n: int = 5) -> float:
    """Score of one (user, offer) row with the given event flags. Exact combo if seen often enough in the data,
    else the same combo ignoring redemption, else the strongest single flag, else the global mean."""
    k = flag_key(o, i, p, r)
    if not table:
        return max([w for w, f in zip(_LEGACY_FLAG_SCORE, (o, i, p, r)) if f > 0] or [0.0])
    for kk in (k, k & 7):
        hit = table.get(kk)
        if hit and hit[1] >= min_n:
            return hit[0]
    singles = [table[b][0] for b in (1, 2, 4, 8) if (k & b) and b in table and table[b][1] >= min_n]
    if singles:
        return max(singles)
    return float(np.mean([v[0] for v in table.values()]))


CORE_STAT_COLS = ["total_interactions", "unique_offers_seen", "avg_score", "max_score", "total_redemptions",
                  "total_purchases", "total_opens", "waffarha_interactions", "user_redemption_rate",
                  "waffarha_affinity"]

_AR_DIAC = re.compile(r"[\u064B-\u0652\u0670\u0640]")
_AR_PUNCT = re.compile(r"[^\w\s\u0600-\u06FF]")


def normalize_arabic(text) -> str:
    if text is None or (isinstance(text, float) and np.isnan(text)):
        return ""
    s = str(text)
    for a, b in (("إ", "ا"), ("أ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي")):
        s = s.replace(a, b)
    s = _AR_PUNCT.sub(" ", _AR_DIAC.sub("", s))
    return re.sub(r"\s+", " ", s).strip()


def sanitize(s) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(s).strip().lower())
    return re.sub(r"_+", "_", s).strip("_")


def _topk(scores: np.ndarray, k: int) -> np.ndarray:
    k = min(k, len(scores))
    if k <= 0:
        return np.array([], dtype=int)
    top = np.argpartition(-scores, k - 1)[:k]
    return top[np.argsort(-scores[top])]


@dataclass
class Artifacts:
    """Everything derived from the catalog + training interactions. One object = one model version."""
    item_ids: np.ndarray
    item_index: dict
    macro_cats: list
    partner_index: dict
    gt_index: dict
    n_partners: int
    # offer arrays
    offer_cat_idx: np.ndarray
    offer_partner_idx: np.ndarray
    offer_gt_idx: np.ndarray
    offer_gov: np.ndarray
    gov_set_membership: np.ndarray
    gov_tag_idx: dict
    nationwide_idx: int
    is_waffarha: np.ndarray
    static_cols: dict  # name -> float32 array over items
    offer_meta: list  # per-offer display fields for the UI (partner, description, price, type)
    gift_price: np.ndarray
    discount_norm: np.ndarray
    start_day: np.ndarray
    end_day: np.ndarray
    anchor_date: str
    eval_day: int
    tfidf_dense: np.ndarray
    tfidf_vocab: dict
    tfidf_idf: np.ndarray
    content_vec: np.ndarray
    # retrieval
    item_sim: sparse.csr_matrix
    pop: np.ndarray
    gov_top: dict
    govset_top: dict
    cat_top: dict
    nationwide_top: np.ndarray
    partner_top: dict
    demo_cell_cnt: dict
    bank_norm: np.ndarray
    bank_items: list
    # users (static side)
    user_ids: list = field(default_factory=list)
    user_static: dict = field(default_factory=dict)  # uid -> dict of static user features
    score_table: dict = field(default_factory=dict)  # flag combo -> (mean score, n)  (event -> score calibration)
    user_hist: dict = field(default_factory=dict)    # uid -> past interaction rows from the dataset (warm users)
    item_cooc: object = None  # raw item-item co-occurrence over train users (csr); lets the trainer remove one user
    item_diag: object = None  # number of train users per item
    contract: str = ""  # == CONTRACT for models trained with sequential point-in-time history + the canonical 17
    day_axis_aligned: bool = False  # does days_since_first_event live on the offers' calendar? (trainer sets it)
    split_of: dict = field(default_factory=dict)  # uid -> train|val|test, so evaluation reuses the trainer's split


# --------------------------------------------------------------------------------------
# Stage 1 channels (same math as notebook, one query at a time)
# --------------------------------------------------------------------------------------
def _agg_sim_without_user(art: Artifacts, seeds: np.ndarray, own_items: np.ndarray) -> np.ndarray:
    """sum_s sim(s, .) with ONE train user's whole contribution removed from the co-occurrence counts (TRAINING ONLY).
    Without this, a train query's Channel A is built from co-occurrence that includes the very user (and the very
    target) it is trying to predict, which inflates train recall vs. val/test and leaks into retrieval_channel_count."""
    n = art.item_cooc.shape[0]
    own = np.zeros(n, np.float32)
    own[np.asarray(own_items, dtype=int)] = 1.0
    d = np.maximum(art.item_diag - own, 0.0)
    nrm = np.sqrt(np.where(d > 0, d, 1.0)).astype(np.float32)
    rows = art.item_cooc[seeds].toarray().astype(np.float32)
    rows -= own[seeds][:, None] * own[None, :]
    rows[np.arange(len(seeds)), seeds] = 0.0
    np.maximum(rows, 0.0, out=rows)
    return (rows / nrm[seeds][:, None]).sum(axis=0) / nrm


def ch_a(art: Artifacts, seeds: np.ndarray, top_k=120, elig=None, own_items=None) -> np.ndarray:
    if len(seeds) == 0:
        return np.array([], dtype=int)
    if own_items is not None and len(own_items) and art.item_cooc is not None:
        agg = _agg_sim_without_user(art, seeds, own_items)
    else:
        agg = np.asarray(art.item_sim[seeds].sum(axis=0)).ravel()
    agg[seeds] = -1.0
    if elig is not None:
        agg[~elig] = -1.0
    k = min(top_k, int((agg > 0).sum()))
    return _topk(agg, k) if k else np.array([], dtype=int)


def ch_b(art: Artifacts, gov: str, top_cat: str, top_k=60, elig=None) -> np.ndarray:
    e = np.array([], dtype=int)
    f = (lambda x: x) if elig is None else (lambda x: x[elig[x]])
    parts = [f(art.gov_top.get(gov, e))[:15], f(art.govset_top.get(gov, e))[:15],
             f(art.cat_top.get(top_cat, e))[:15], f(art.nationwide_top)[:40]]
    merged = np.concatenate(parts)
    _, first = np.unique(merged, return_index=True)
    return merged[np.sort(first)][:top_k]


def ch_c(art: Artifacts, spend_norm: np.ndarray, text_sim: np.ndarray, top_k=40, w_cat=0.6, w_txt=0.4, elig=None):
    scores = (w_cat * (art.content_vec @ spend_norm) + w_txt * text_sim).astype(np.float32)
    if elig is not None:
        scores[~elig] = -np.inf
    top = _topk(scores, top_k)
    return top[np.isfinite(scores[top])]


def ch_d(art: Artifacts, cat_pref, gt_pref, spend_norm, top_users=20, top_items=60, exclude_row=None,
         elig=None) -> np.ndarray:
    q = np.concatenate([cat_pref, gt_pref, spend_norm]).astype(np.float32)
    qn = np.linalg.norm(q)
    if qn == 0:
        return np.array([], dtype=int)
    sims = art.bank_norm @ (q / qn)
    if exclude_row is not None:
        sims[exclude_row] = -1.0
    top_u = _topk(sims, top_users)
    scores = np.zeros(len(art.item_ids), dtype=np.float32)
    for ui in top_u:
        w = max(float(sims[ui]), 0.0)
        if w > 0:
            scores[art.bank_items[ui]] += w
    if elig is not None:
        scores[~elig] = 0.0
    kk = int((scores > 0).sum())
    return _topk(scores, min(top_items, kk)) if kk else np.array([], dtype=int)


def ch_e(art: Artifacts, seeds: np.ndarray, top_partners=10, per_partner=3, elig=None) -> np.ndarray:
    if len(seeds) == 0:
        return np.array([], dtype=int)
    parts, cnts = np.unique(art.offer_partner_idx[seeds], return_counts=True)
    out = []
    for p in parts[np.argsort(-cnts)[:top_partners]]:
        lst = art.partner_top.get(int(p))
        if lst is None or len(lst) == 0:
            continue
        lst = lst[~np.isin(lst, seeds)]
        if elig is not None:
            lst = lst[elig[lst]]
        if len(lst):
            out.append(lst[:per_partner])
    return np.unique(np.concatenate(out)) if out else np.array([], dtype=int)


def ch_f(art: Artifacts, cell: str, seeds: np.ndarray, top_k=60, own_items=None, elig=None) -> np.ndarray:
    cnt = art.demo_cell_cnt.get(cell)
    if cnt is None or not cnt.any():
        return np.array([], dtype=int)
    if elig is not None:
        cnt = np.where(elig, cnt, 0.0).astype(np.float32)
    if own_items is not None and len(own_items):
        cnt = np.maximum(cnt - np.bincount(own_items, minlength=len(cnt)).astype(np.float32), 0.0)
    k = int((cnt > 0).sum())
    if k == 0:
        return np.array([], dtype=int)
    top = _topk(cnt, min(top_k, k))
    return top[~np.isin(top, seeds)]


def retrieve(art: Artifacts, user: dict, live: dict, text_sim_all: np.ndarray,
             exclude_row=None, own_items=None, gov=None, elig=None, exclude_seen=True):
    """Union of the six channels + how many channels surfaced each candidate.

    elig: boolean mask over the catalog (serving: active today, in the user's area, not already seen). It is applied
    INSIDE every channel, before its top-K, so expired/out-of-area offers cannot use up candidate slots.
    exclude_seen: the user's already-interacted offers are never candidates (training and serving alike, so the
    ranker does not learn "high affinity with this partner/category => negative" from seen offers).
    exclude_row / own_items are training-only leave-one-out switches (None in serving)."""
    seeds = np.array(sorted(live["seen_idx"]), dtype=int)
    a = ch_a(art, seeds, elig=elig, own_items=own_items)
    b = ch_b(art, gov or user["gov"], user["top_cat"], elig=elig)
    c = ch_c(art, user["spend_norm"], text_sim_all, elig=elig)
    d = ch_d(art, live["cat_pref"], live["gt_pref"], user["spend_norm"], exclude_row=exclude_row, elig=elig)
    e = ch_e(art, seeds, elig=elig)
    f = ch_f(art, user["cell"], seeds, own_items=own_items, elig=elig)
    chans = (a, b, c, d, e, f)
    cand = np.unique(np.concatenate(chans))
    if exclude_seen and len(seeds):
        cand = cand[~np.isin(cand, seeds)]
    cc = sum(np.isin(cand, ch).astype(np.int8) for ch in chans)
    return cand, np.asarray(cc, dtype=np.float32)


# --------------------------------------------------------------------------------------
# Feature builder: ONE definition for serving and for training-time evaluation
# --------------------------------------------------------------------------------------
def expanded_geo(art: Artifacts, user_gov: str, user_gov_tag: int, cand: np.ndarray) -> np.ndarray:
    prim = art.offer_gov[cand]
    exact = (prim == user_gov) & (user_gov not in ("unknown", "", None))  # unknown never "matches" unknown
    in_set = np.zeros(len(cand), dtype=bool)
    if user_gov_tag >= 0:
        in_set = art.gov_set_membership[cand, user_gov_tag] > 0
    m = np.where(exact, 2.0, np.where(in_set, 1.5, 0.0)).astype(np.float32)
    nation = prim == "nationwide"
    if art.nationwide_idx >= 0:
        nation = nation | (art.gov_set_membership[cand, art.nationwide_idx] > 0)
    return np.where((m == 0.0) & nation, 1.0, m)


def build_features(art: Artifacts, cols: list, user: dict, live: dict, cand: np.ndarray,
                   channel_count: np.ndarray, live_day: int, text_sim: np.ndarray) -> np.ndarray:
    """Return an (n_cand, len(cols)) float32 matrix. Only computes what `cols` asks for."""
    n = len(cand)
    cat_i = art.offer_cat_idx[cand]
    par_i = art.offer_partner_idx[cand]
    spend_in_cat = user["spend_amt"][cat_i].astype(np.float32)
    waff_pref = float(live["gt_pref"][art.gt_index["waffarha"]]) if "waffarha" in art.gt_index else 0.0
    open_i, purch_i = float(live["open_intensity"]), float(live["purch_intensity"])

    def const(v):
        return np.full(n, v, dtype=np.float32)

    builders = {
        "cat_affinity_score": lambda: live["cat_pref"][cat_i],
        "waffarha_synergy": lambda: waff_pref * art.is_waffarha[cand],
        "cat_match_top_spend": lambda: (cat_i == user["top_cat_idx"]).astype(np.float32),
        "retrieval_channel_count": lambda: channel_count,
        "user_candidate_partner_affinity": lambda: live["partner_pref"][par_i],
        "user_spend_in_candidate_category": lambda: spend_in_cat,
        "affordability_ratio": lambda: art.static_cols["log_price"][cand] / user["affluence"],
        "user_has_yc": lambda: const(user["flags"][0]),
        "user_has_bnpl": lambda: const(user["flags"][1]),
        "user_has_credit": lambda: const(user["flags"][2]),
        "user_has_debit": lambda: const(user["flags"][3]),
        "user_total_interactions": lambda: const(live["total_interactions"]),
        "user_avg_score": lambda: const(live["sum_score"] / live["n_rows"] if live["n_rows"] > 0 else 0.0),
        "user_max_score": lambda: const(live["max_score"]),
        "user_waffarha_affinity": lambda: const(live["waff_events"] / live["total_interactions"]
                                                if live["total_interactions"] > 0 else 0.0),
        "user_redemption_rate_hist": lambda: const(live["redemptions"] / live["total_interactions"]
                                                   if live["total_interactions"] > 0 else 0.0),
        "expanded_geo_match": lambda: expanded_geo(art, user["gov"], user["gov_tag"], cand),
        "discount_cash_impact": lambda: (art.gift_price[cand] * art.discount_norm[cand]).astype(np.float32),
        "log_days_to_expire": lambda: np.log1p(np.clip(art.end_day[cand] - live_day, 0, None)).astype(np.float32),
        "yc_category_share": lambda: spend_in_cat / (user["total_spend"] + 1.0),
        "description_tfidf_sim": lambda: text_sim[cand].astype(np.float32),
        "user_30d_open_intensity": lambda: const(open_i),
        "user_30d_conversion_ratio": lambda: const(purch_i / (open_i + 1.0)),
    }
    out = np.empty((n, len(cols)), dtype=np.float32)
    for j, c in enumerate(cols):
        out[:, j] = art.static_cols[c][cand] if c in art.static_cols else builders[c]()
    return out


def text_similarity(art: Artifacts, tfidf_profile: np.ndarray) -> np.ndarray:
    nrm = np.linalg.norm(tfidf_profile)
    if nrm <= 0:
        return np.zeros(len(art.item_ids), dtype=np.float32)
    return np.clip((art.tfidf_dense @ tfidf_profile) / nrm, 0.0, 1.0).astype(np.float32)


def eligible_mask(art: Artifacts, day, area) -> np.ndarray:
    """Filters over the whole catalog: offer is active on `day` (None = calendar unknown, no date filter) AND available
    in `area` (None = any area)."""
    ok = np.ones(len(art.item_ids), dtype=bool) if day is None else (art.start_day <= day) & (day <= art.end_day)
    if area:
        idx = np.arange(len(art.item_ids))
        ok &= expanded_geo(art, area, art.gov_tag_idx.get(area, -1), idx) > 0
    return ok


def known_areas(art: Artifacts) -> list:
    """Areas (governorates) that exist in the catalog; the same list for serving and training."""
    c = getattr(art, "_areas_cache", None)
    if c is None:
        c = sorted(g for g in set(art.offer_gov) | set(art.gov_tag_idx) if g not in ("nationwide", "unknown", ""))
        art._areas_cache = c
    return c


def profile_area(art: Artifacts, user: dict):
    """Area implied by the user's profile governorate (None if unknown). Serving prefers request area / device location
    and falls back to this; training always uses it."""
    return user["gov"] if user["gov"] in known_areas(art) else None


def area_view(art: Artifacts, user: dict, area) -> dict:
    return {**user, "gov": area, "gov_tag": art.gov_tag_idx.get(area, -1)} if area else user


def as_of_day(art: Artifacts, mode: str = None, when: date = None) -> int:
    """Day index (same axis as start_day/end_day) of the reference date. mode: today | dataset | ISO date.
    `when` replaces 'today' (the trainer passes the calendar date of a production event)."""
    mode = mode or _cfg.AS_OF_DATE
    if mode == "dataset":
        return int(art.eval_day)
    ref = (when or date.today()) if mode == "today" else date.fromisoformat(mode)
    return (ref - date.fromisoformat(art.anchor_date)).days


def default_user_static(art: Artifacts) -> dict:
    """A user we know nothing about (new sign-up / not in user_features.csv): no spend, no flags, unknown profile."""
    n = len(art.macro_cats)
    return {"gov": "unknown", "gov_tag": -1, "cell": "unknown", "spend_amt": np.zeros(n, np.float32),
            "spend_norm": np.zeros(n, np.float32), "affluence": 1.0, "total_spend": 0.0, "top_cat_idx": -1,
            "top_cat": "", "flags": [0.0] * 4, "raw_open": 0.0, "raw_purch": 0.0}


def similar_offers(art: Artifacts, anchor: int, elig: np.ndarray, k: int) -> np.ndarray:
    """Eligible offers most similar to `anchor`: description TF-IDF cosine + same partner + same category."""
    sim = 0.5 * (art.tfidf_dense @ art.tfidf_dense[anchor])
    sim = sim + 0.3 * ((art.offer_partner_idx == art.offer_partner_idx[anchor]) & (art.offer_partner_idx < art.n_partners))
    sim = sim + 0.2 * (art.offer_cat_idx == art.offer_cat_idx[anchor])
    sim = np.where(elig, sim, -1.0)
    sim[anchor] = -1.0
    top = _topk(sim.astype(np.float32), k)
    return top[sim[top] > 0]


def empty_live(art: Artifacts, user: dict) -> dict:
    """Live state of a user with NO history: every live history/preference/event counter is 0 (cold start). Only the
    static profile (art.user_static / default_user_static) is available."""
    return {
        "cat_pref": np.zeros(len(art.macro_cats), np.float32),
        "partner_pref": np.zeros(art.n_partners + 1, np.float32),
        "gt_pref": np.zeros(len(art.gt_index), np.float32),
        "tfidf": np.zeros(art.tfidf_dense.shape[1], np.float32),
        "seen_idx": set(), "n_events": 0, "n_rows": 0, "total_interactions": 0.0,
        "sum_score": 0.0, "max_score": 0.0, "redemptions": 0.0, "waff_events": 0.0,
        "open_intensity": 0.0, "purch_intensity": 0.0,
        "last_day": None, "last_item": None,
    }


def add_interaction(art: Artifacts, live: dict, item: int, score: float, count: float = 1.0,
                    has_red: float = 0.0, waff: float = 0.0, has_open: float = 0.0, has_purch: float = 0.0):
    """Fold one (user, offer) interaction row into the live state. Only fold_history calls this, so training queries,
    evaluation and the API all build the live state the same way."""
    live["cat_pref"][art.offer_cat_idx[item]] += score
    p = art.offer_partner_idx[item]
    if p < art.n_partners:
        live["partner_pref"][p] += score
    g = art.offer_gt_idx[item]
    if g >= 0:
        live["gt_pref"][g] += score
    live["tfidf"] += score * art.tfidf_dense[item]
    live["seen_idx"].add(int(item))
    live["n_rows"] += 1
    live["total_interactions"] += count
    live["sum_score"] += score
    live["max_score"] = max(live["max_score"], score)
    live["redemptions"] += has_red
    live["waff_events"] += waff
    live["open_intensity"] += has_open
    live["purch_intensity"] += has_purch


# --------------------------------------------------------------------------------------
# Chronological order of interactions (one definition for build / train / eval)
# --------------------------------------------------------------------------------------
TS_COLS = ("event_ts", "first_event_ts", "ts", "timestamp")  # optional dataset timestamp columns (real order inside a day)
ORDER_COLS = ["_src", "_day", "_tsk", "_tie"]


def order_frame(df: pd.DataFrame, day_col: str = "days_since_first_event") -> pd.DataFrame:
    """Sort interaction rows/events chronologically within each user. Total order (lexicographic):
        _src  0 = dataset row, 1 = production event (production always happens after the dataset logs)
        _day  day index (days_since_first_event; production: the as-of day of the event)
        _tsk  event timestamp in epoch seconds - a real dataset timestamp column (TS_COLS) when the CSV has one, the
              PostgreSQL events.ts for production events, else 0
        _tie  stable tie-breaker: dataset rows = their position in the CSV (the dataset has NO intra-day timestamp, so
              the file order is the deterministic proxy), production events = event_id
    Returns a copy with those four columns, sorted by (user_id, _src, _day, _tsk, _tie)."""
    d = df.copy()
    n = len(d)
    if "_src" not in d:
        d["_src"] = 0
    d["_src"] = d["_src"].fillna(0).astype(int)
    d["_day"] = d[day_col].astype(int)
    tsk = d["_tsk"].astype(float) if "_tsk" in d else pd.Series(np.nan, index=d.index)
    tc = next((c for c in TS_COLS if c in d.columns), None)
    if tc:  # rows without their own _tsk take a real dataset timestamp when the CSV has one
        t = pd.to_datetime(d[tc], utc=True, errors="coerce")
        tsk = tsk.fillna((t - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds())
    d["_tsk"] = tsk.fillna(0.0)
    pos = (d["_pos"] if "_pos" in d else pd.Series(np.arange(n), index=d.index)).fillna(0)
    tie = d["_tie"].fillna("").astype(str) if "_tie" in d else pd.Series("", index=d.index)
    d["_tie"] = tie.where(tie.str.len() > 0, pos.map(lambda i: f"{int(i):09d}"))
    return d.sort_values(["user_id"] + ORDER_COLS, kind="stable").reset_index(drop=True)


def row_keys(d: pd.DataFrame) -> list:
    return list(zip(d["_src"].tolist(), d["_day"].tolist(), d["_tsk"].tolist(), d["_tie"].tolist()))


# One interaction event of a user's chronological ledger.
#   flags      (open, click, purchase, redemption) 0/1 - what this entry reports
#   n_by_type  events of each type (production events: one-hot; dataset rows: zeros - they only carry `base_count`)
#   base_count dataset `interaction_count` of the row (0 for production events)
#   ds_score   dataset row score (None for production events: scored through the fitted score table)
HistEntry = namedtuple("HistEntry", "item flags n_by_type base_count ds_score")


def fold_history(art: Artifacts, user: dict, entries, keys=None, target_key=None) -> dict:
    """THE history builder. `entries` = the user's EARLIER interaction events, oldest first (a chronological prefix).
    Events on the same offer collapse into ONE (user, offer) row (flags OR-ed, like the dataset rows); the row score
    comes from the fitted score table (dataset rows keep their real score). Used with a ledger prefix by the trainer and
    the evaluation and with dataset history + Redis counters by the API, so a user's state is identical in all three.

    keys/target_key (optional, training/eval): chronological sort keys of the entries and of the target event - raises
    LeakageError if any entry is not STRICTLY before the target, i.e. if the target or a future event leaks in."""
    if target_key is not None:
        if keys is None or len(keys) != len(entries):
            raise LeakageError("history entries without chronological keys")
        if any(k >= target_key for k in keys):
            raise LeakageError("history contains an event that is not strictly before the target")
    live = empty_live(art, user)
    rows = {}
    for e in entries:
        r = rows.get(e.item)
        if r is None:
            r = rows[e.item] = {"f": [0, 0, 0, 0], "n": [0, 0, 0, 0], "base": 0.0, "ds": None}
        for k in range(4):
            r["f"][k] |= int(e.flags[k] > 0)
            r["n"][k] += int(e.n_by_type[k])
        r["base"] = max(r["base"], float(e.base_count))
        if e.ds_score is not None:
            r["ds"] = float(e.ds_score) if r["ds"] is None else max(r["ds"], float(e.ds_score))
    for item, r in rows.items():
        n_ev = max(r["n"])  # open+click on one offer = ONE interaction (like interaction_count)
        if n_ev == 0 and r["ds"] is not None:
            score = r["ds"]  # untouched dataset row: keep its real score
        else:
            score = score_for_flags(art.score_table, *r["f"])
            if r["ds"] is not None:
                score = max(score, r["ds"])
        add_interaction(art, live, item, score, max(r["base"], float(n_ev)), float(r["f"][3]),
                        float(art.is_waffarha[item] > 0), float(r["f"][0]), float(r["f"][2]))
    live["last_item"] = int(entries[-1].item) if len(entries) else None
    return live


def generate_candidates(art: Artifacts, ue: dict, live: dict, open_mask: np.ndarray, area, anchor,
                        exclude_row=None, own_items=None):
    """Stage 1, identical for serving and for training queries:
    eligibility filters (`open_mask`: active, in area, not yet seen) applied INSIDE each of the 6 channels before its
    top-K -> union (+ offers similar to the anchor = the latest interaction) -> top-up from eligible offers if the pool
    is small. Returns (cand, channel_count, similar_ids, text_sim_all)."""
    text_all = text_similarity(art, live["tfidf"])
    cand, cc = retrieve(art, ue, live, text_all, exclude_row=exclude_row, own_items=own_items, gov=area,
                        elig=open_mask)
    sim = np.array([], dtype=int)
    if anchor is not None:
        sim = similar_offers(art, anchor, open_mask, _cfg.SIMILAR_POOL)
        new = sim[~np.isin(sim, cand)]
        cand, cc = np.concatenate([cand, new]), np.concatenate([cc, np.ones(len(new), np.float32)])
    if len(cand) < _cfg.MIN_POOL:  # top up from valid offers only, most popular first
        pool = np.where(open_mask)[0]
        pool = pool[~np.isin(pool, cand)]
        pool = pool[np.argsort(-art.pop[pool])][: _cfg.MIN_POOL - len(cand)]
        cand, cc = np.concatenate([cand, pool]), np.concatenate([cc, np.ones(len(pool), np.float32)])
    return cand, cc, sim, text_all


def save_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def load_json(path):
    return json.loads(Path(path).read_text())
