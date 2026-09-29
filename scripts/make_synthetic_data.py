"""Synthetic dataset with the exact schema of the Fawry notebook (3 CSVs).

Used only when the real CSVs are absent. Drop the real files into ./data to replace it.
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

N_USERS, N_OFFERS = 3000, 1328
SEED = 42

CATS = ["food_beverages", "fashion_footwear", "electronics", "health_beauty", "travel_hotels",
        "entertainment", "groceries", "household", "gifts", "online", "services",
        "transportation", "books_stationery", "retail_services"]
GOVS = ["cairo", "giza", "alexandria", "dakahlia", "sharqia", "gharbia", "qalyubia", "damietta"]
GTYPES = ["waffarha", "voucher", "cashback", "coupon"]
AGES = ["18-24", "25-34", "35-44", "45+"]
PARTNERS = [f"Partner {i}" for i in range(120)]
WORDS = ("خصم كاش باك مطعم قهوة ملابس احذية الكترونيات سفر فندق سينما بقالة اثاث هدية "
         "توصيل مجاني عرض خاص اشتري واحصل تخفيض صحة جمال عناية مواصلات كتب").split()


def sanitize(s):
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(s).strip().lower())).strip("_")


def main(out="data"):
    OUT = Path(out)
    rng = np.random.default_rng(SEED)
    OUT.mkdir(parents=True, exist_ok=True)

    # ---------------- offers ----------------
    part_ids = rng.integers(0, len(PARTNERS), N_OFFERS)
    cat_of_partner = rng.integers(0, len(CATS), len(PARTNERS))
    start = pd.Timestamp("2024-01-01") + pd.to_timedelta(rng.integers(0, 200, N_OFFERS), unit="D")
    end = start + pd.to_timedelta(rng.integers(30, 400, N_OFFERS), unit="D")
    govs = rng.choice(GOVS + ["nationwide"], N_OFFERS, p=[.1] * 8 + [.2])
    gov_sets = []
    for g in govs:
        if g == "nationwide":
            gov_sets.append("nationwide")
        else:
            extra = rng.choice(GOVS, rng.integers(0, 3), replace=False).tolist()
            gov_sets.append("|".join(sorted(set([g] + extra))))
    dtype = rng.choice(["percentage", "fixed", "unknown"], N_OFFERS, p=[.5, .3, .2])
    pop = rng.pareto(1.5, N_OFFERS) * 20 + 1
    offers = pd.DataFrame({
        "offer_id": [f"OFFER_{i:04d}" for i in range(N_OFFERS)],
        "offer_category": [CATS[cat_of_partner[p]] for p in part_ids],
        "offer_partner_en": [PARTNERS[p] for p in part_ids],
        "offer_type": rng.choice(GTYPES, N_OFFERS, p=[.3, .3, .2, .2]),
        "offer_gov_primary": govs,
        "offer_gov_set": gov_sets,
        "offer_area_primary": rng.choice(["مصر الجديدة", "المعادي", "الدقي", "سموحة"], N_OFFERS),
        "gift_description": [" ".join(rng.choice(WORDS, rng.integers(4, 10))) for _ in range(N_OFFERS)],
        "gift_customer_price": np.where(rng.random(N_OFFERS) < .003, np.nan, rng.lognormal(4, 1.2, N_OFFERS)),
        "gift_start_date": start.dt.strftime("%Y-%m-%d") if hasattr(start, "dt") else start.strftime("%Y-%m-%d"),
        "gift_end_date": end.dt.strftime("%Y-%m-%d") if hasattr(end, "dt") else end.strftime("%Y-%m-%d"),
        "popularity": pop.round(0),
        "is_waffarha": (rng.random(N_OFFERS) < .3).astype(int),
        "signal_quality": rng.random(N_OFFERS),
        "discount_value_norm": rng.random(N_OFFERS),
        "cash_amount_norm": rng.random(N_OFFERS),
        "offer_purchase_rate": rng.random(N_OFFERS) * .3,
        "offer_redemption_rate": rng.random(N_OFFERS) * .2,
        "dtype_percentage": (dtype == "percentage").astype(int),
        "dtype_fixed": (dtype == "fixed").astype(int),
        "dtype_unknown": (dtype == "unknown").astype(int),
    })
    offers["is_waffarha"] = (offers["offer_type"] == "waffarha").astype(int)

    # ---------------- users ----------------
    uid = [f"CUST_{i:04d}" for i in range(N_USERS)]
    users = pd.DataFrame({
        "user_id": uid,
        "governorate": rng.choice([g.title() for g in GOVS], N_USERS),
        "age_bucket": rng.choice(AGES, N_USERS),
        "gender": rng.choice(["M", "F"], N_USERS),
        "uv_has_yc": rng.integers(0, 2, N_USERS), "uv_has_bnpl": rng.integers(0, 2, N_USERS),
        "uv_has_credit": rng.integers(0, 2, N_USERS), "uv_has_debit": rng.integers(0, 2, N_USERS),
    })

    # ---------------- interactions ----------------
    # Structure the real data has: popularity, category taste, partner revisits, local geo, offer validity.
    anchor = start.min()
    s_day = (start - anchor).days.to_numpy()
    e_day = (end - anchor).days.to_numpy()
    cat_arr = offers.offer_category.to_numpy()
    par_arr = offers.offer_partner_en.to_numpy()
    gov_arr = offers.offer_gov_primary.to_numpy()
    pop_arr = offers.popularity.to_numpy(dtype=float)
    ugov = users.governorate.str.lower().to_numpy()
    fav = [rng.choice(CATS, 2, replace=False) for _ in range(N_USERS)]
    rows = []
    n_per_user = np.clip(rng.geometric(0.28, N_USERS), 1, 25)
    for u in range(N_USERS):
        seen, used_partners = set(), []
        day = int(rng.integers(20, 120))
        for _ in range(n_per_user[u]):
            w = pop_arr.copy()
            w *= np.where((s_day <= day) & (day <= e_day), 1.0, 0.05)
            w *= np.where((gov_arr == ugov[u]) | (gov_arr == "nationwide"), 4.0, 1.0)
            r = rng.random()
            if r < .35:
                w *= np.where(np.isin(cat_arr, fav[u]), 12.0, 1.0)
            elif r < .6 and used_partners:
                w *= np.where(np.isin(par_arr, used_partners), 25.0, 1.0)
            j = int(rng.choice(N_OFFERS, p=w / w.sum()))
            if j in seen:
                continue
            seen.add(j)
            used_partners.append(par_arr[j])
            has_open = 1
            has_inv = int(rng.random() < .5)
            has_purchase = int(rng.random() < .25)
            has_red = int(has_purchase and rng.random() < .6)
            score = 1 + 1 * has_inv + 3 * has_purchase + 2 * has_red
            day += int(rng.integers(0, 4))
            rows.append((uid[u], offers.offer_id[j], score, has_open, has_inv, has_purchase, has_red,
                         int(offers.is_waffarha[j]), int(rng.integers(1, 4)), day))
    ti = pd.DataFrame(rows, columns=["user_id", "offer_id", "score", "has_open", "has_investigation",
                                     "has_purchase", "has_redemption", "is_waffarha_signal",
                                     "interaction_count", "days_since_first_event"])

    # ---------------- user aggregate columns (raw, leaky snapshot, like the real file) ----------------
    o = ti.merge(offers[["offer_id", "offer_category", "offer_partner_en", "offer_type"]], on="offer_id")
    o["cat"] = o.offer_category.map(sanitize)
    o["par"] = o.offer_partner_en.map(sanitize)
    o["gt"] = o.offer_type.str.lower()

    def pref(key, prefix, names):
        pv = o.pivot_table(index="user_id", columns=key, values="score", aggfunc="sum", fill_value=0)
        pv = pv.reindex(index=uid, columns=sorted(set(names)), fill_value=0)
        pv.columns = [prefix + c for c in pv.columns]
        return pv.reset_index(drop=True)

    users = pd.concat([
        users,
        pref("cat", "cat_pref_", [sanitize(c) for c in CATS]),
        pref("par", "partner_pref_", [sanitize(p) for p in PARTNERS]),
        pref("gt", "gt_pref_", GTYPES),
    ], axis=1)
    g = ti.groupby("user_id")
    stats = pd.DataFrame({
        "total_interactions": g.interaction_count.sum(),
        "unique_offers_seen": g.offer_id.nunique(),
        "avg_score": g.score.mean(), "max_score": g.score.max(),
        "total_redemptions": g.has_redemption.sum(), "total_purchases": g.has_purchase.sum(),
        "total_opens": g.has_open.sum(), "waffarha_interactions": g.is_waffarha_signal.sum(),
    }).reindex(uid).fillna(0)
    stats["user_redemption_rate"] = (stats.total_redemptions / stats.total_interactions.replace(0, np.nan)).fillna(0)
    stats["waffarha_affinity"] = (stats.waffarha_interactions / stats.total_interactions.replace(0, np.nan)).fillna(0)
    users = pd.concat([users, stats.reset_index(drop=True)], axis=1)

    # 30d open / purchase counts per macro category (24 in the real data; here one per category)
    cats_s = sorted({sanitize(c) for c in CATS})
    for c in cats_s:
        sub = o[o.cat == c].groupby("user_id")
        users[f"uv_{c}_offer_open_cnt_30d"] = sub.has_open.sum().reindex(uid).fillna(0).to_numpy()
        users[f"uv_{c}_offer_purchase_cnt_30d"] = sub.has_purchase.sum().reindex(uid).fillna(0).to_numpy()

    # merchant spend columns (payments data, independent of interactions)
    for sub_cat in ["restaurants_and_dining", "groceries", "fashion_and_accessories", "transportation",
                    "electronics_and_appliances", "travel_and_hotels", "medical_and_healthcare",
                    "entertainment", "online_shopping", "furniture", "gifts", "telecom_and_internet"]:
        cnt = rng.poisson(3, N_USERS)
        amt = cnt * rng.lognormal(4.5, 1, N_USERS) * (rng.random(N_USERS) < .6)
        users[f"uv_{sub_cat}_yc_merchant_cnt_30d"] = cnt
        users[f"uv_{sub_cat}_yc_merchant_amt_30d"] = amt
        users[f"uv_{sub_cat}_yc_merchant_ticket_30d"] = np.where(cnt > 0, amt / np.maximum(cnt, 1), 0)

    offers.to_csv(OUT / "offer_features.csv", index=False)
    users.to_csv(OUT / "user_features.csv", index=False)
    ti.to_csv(OUT / "train_interactions.csv", index=False)
    print(f"offers={offers.shape} users={users.shape} interactions={ti.shape} -> {OUT}/")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data")
