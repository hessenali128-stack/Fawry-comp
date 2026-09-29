"""Shared logic for training and serving: text cleaning, artifacts, Stage-1 channels, features.

The API and the trainer import the SAME functions, so a feature has one definition.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.preprocessing import normalize

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


# --------------------------------------------------------------------------------------
# Stage 1 channels (same math as notebook, one query at a time)
# --------------------------------------------------------------------------------------
def ch_a(art: Artifacts, seeds: np.ndarray, top_k=120) -> np.ndarray:
    if len(seeds) == 0:
        return np.array([], dtype=int)
    agg = np.asarray(art.item_sim[seeds].sum(axis=0)).ravel()
    agg[seeds] = -1.0
    k = min(top_k, int((agg > 0).sum()))
    return _topk(agg, k) if k else np.array([], dtype=int)


def ch_b(art: Artifacts, gov: str, top_cat: str, top_k=60) -> np.ndarray:
    e = np.array([], dtype=int)
    parts = [art.gov_top.get(gov, e)[:15], art.govset_top.get(gov, e)[:15],
             art.cat_top.get(top_cat, e)[:15], art.nationwide_top[:40]]
    merged = np.concatenate(parts)
    _, first = np.unique(merged, return_index=True)
    return merged[np.sort(first)][:top_k]


def ch_c(art: Artifacts, spend_norm: np.ndarray, text_sim: np.ndarray, top_k=40, w_cat=0.6, w_txt=0.4):
    scores = w_cat * (art.content_vec @ spend_norm) + w_txt * text_sim
    return _topk(scores.astype(np.float32), top_k)


def ch_d(art: Artifacts, cat_pref, gt_pref, spend_norm, top_users=20, top_items=60, exclude_row=None) -> np.ndarray:
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
    kk = int((scores > 0).sum())
    return _topk(scores, min(top_items, kk)) if kk else np.array([], dtype=int)


def ch_e(art: Artifacts, seeds: np.ndarray, top_partners=10, per_partner=3) -> np.ndarray:
    if len(seeds) == 0:
        return np.array([], dtype=int)
    parts, cnts = np.unique(art.offer_partner_idx[seeds], return_counts=True)
    out = []
    for p in parts[np.argsort(-cnts)[:top_partners]]:
        lst = art.partner_top.get(int(p))
        if lst is None or len(lst) == 0:
            continue
        lst = lst[~np.isin(lst, seeds)]
        if len(lst):
            out.append(lst[:per_partner])
    return np.unique(np.concatenate(out)) if out else np.array([], dtype=int)


def ch_f(art: Artifacts, cell: str, seeds: np.ndarray, top_k=60, own_items=None) -> np.ndarray:
    cnt = art.demo_cell_cnt.get(cell)
    if cnt is None or not cnt.any():
        return np.array([], dtype=int)
    if own_items is not None and len(own_items):
        cnt = np.maximum(cnt - np.bincount(own_items, minlength=len(cnt)).astype(np.float32), 0.0)
    k = int((cnt > 0).sum())
    if k == 0:
        return np.array([], dtype=int)
    top = _topk(cnt, min(top_k, k))
    return top[~np.isin(top, seeds)]


def retrieve(art: Artifacts, user: dict, live: dict, text_sim_all: np.ndarray,
             exclude_row=None, own_items=None):
    """Union of the six channels + how many channels surfaced each candidate.
    exclude_row / own_items are training-only leave-one-out switches (None in serving)."""
    seeds = np.array(sorted(live["seen_idx"]), dtype=int)
    a = ch_a(art, seeds)
    b = ch_b(art, user["gov"], user["top_cat"])
    c = ch_c(art, user["spend_norm"], text_sim_all)
    d = ch_d(art, live["cat_pref"], live["gt_pref"], user["spend_norm"], exclude_row=exclude_row)
    e = ch_e(art, seeds)
    f = ch_f(art, user["cell"], seeds, own_items=own_items)
    cand = np.unique(np.concatenate([a, b, c, d, e, f]))
    cc = sum(np.isin(cand, ch).astype(np.int8) for ch in (a, b, c, d, e, f))
    return cand, cc.astype(np.float32)


# --------------------------------------------------------------------------------------
# Feature builder: ONE definition for serving and for training-time evaluation
# --------------------------------------------------------------------------------------
def expanded_geo(art: Artifacts, user_gov: str, user_gov_tag: int, cand: np.ndarray) -> np.ndarray:
    prim = art.offer_gov[cand]
    exact = prim == user_gov
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


def validity_filter(art: Artifacts, cand: np.ndarray, day: int, top_n: int) -> np.ndarray:
    active = (art.start_day[cand] <= day) & (day <= art.end_day[cand])
    keep = cand[active]
    if len(keep) >= top_n:
        return keep
    pruned = cand[~active]
    back = pruned[np.argsort(-art.pop[pruned])][: top_n - len(keep)]
    return np.concatenate([keep, back])


def empty_live(art: Artifacts, user: dict) -> dict:
    return {
        "cat_pref": np.zeros(len(art.macro_cats), np.float32),
        "partner_pref": np.zeros(art.n_partners + 1, np.float32),
        "gt_pref": np.zeros(len(art.gt_index), np.float32),
        "tfidf": np.zeros(art.tfidf_dense.shape[1], np.float32),
        "seen_idx": set(), "n_events": 0, "n_rows": 0, "total_interactions": 0.0,
        "sum_score": 0.0, "max_score": 0.0, "redemptions": 0.0, "waff_events": 0.0,
        "open_intensity": float(user["raw_open"]), "purch_intensity": float(user["raw_purch"]),
        "last_day": None,
    }


def add_interaction(art: Artifacts, live: dict, item: int, score: float, count: float = 1.0,
                    has_red: float = 0.0, waff: float = 0.0, has_open: float = 0.0, has_purch: float = 0.0):
    """Fold one (user, offer) interaction row into the live state. Used by training (leave-one-out
    history) AND serving (Redis state) so both build features from identical semantics."""
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


def save_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def load_json(path):
    return json.loads(Path(path).read_text())
