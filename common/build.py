"""Build retrieval artifacts from raw CSVs (notebook §1.4-§2.1) and persist/load them per version."""
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from common.core import Artifacts, normalize_arabic, sanitize

MERCHANT_TO_MACRO = {
    "accounting": "services", "admin_payments": "services", "advertising_services": "services",
    "agricultural_cooperatives_": "services", "arts": "entertainment", "bicycle_shops": "retail_services",
    "book_stores": "books_stationery", "business_services": "services", "car_washes": "retail_services",
    "clubs": "entertainment", "consulting": "services", "deposit_or_withdrawal": "services",
    "digital_goods": "online", "donations": "gifts", "education": "services",
    "electronics_and_appliances": "electronics", "entertainment": "entertainment",
    "fashion_and_accessories": "fashion_footwear", "fifa_world_cup_2022_subscription": "entertainment",
    "fines": "services", "florists_and_landscaping": "household",
    "food_and_beverages__restaurants_and_dining": "food_beverages", "furniture": "household",
    "furniture_and_remodling": "household", "gifts": "gifts", "government_services": "services",
    "groceries": "groceries", "housing": "household", "industrial_supplies": "retail_services",
    "installments": "services", "insurance": "services", "insurance_": "services",
    "investments_and_savings": "services", "landscaping_services": "household", "loans": "services",
    "medical_": "health_beauty", "medical_and_healthcare": "health_beauty", "money_deposit": "services",
    "motion_picture_theaters": "entertainment", "office_equipment": "retail_services",
    "online_shopping": "online", "others": "services", "personal_care": "health_beauty",
    "pet_shops": "retail_services", "photographic_studios": "services",
    "publishing_and_printing_": "books_stationery", "restaurants_and_dining": "food_beverages",
    "retail": "retail_services", "saq_elodheya": "retail_services", "tax_payments": "services",
    "telecom_and_internet": "services", "transfer": "services", "transportation": "transportation",
    "transportation_gasuber_": "transportation", "travel_and_hotels": "travel_hotels",
    "utilities": "household", "veterinary_services_": "retail_services",
}


def load_raw(data_dir: str):
    d = Path(data_dir)
    return (pd.read_csv(d / "user_features.csv"), pd.read_csv(d / "train_interactions.csv"),
            pd.read_csv(d / "offer_features.csv"))


def prepare_offers(offers: pd.DataFrame) -> pd.DataFrame:
    o = offers.copy()
    o["gift_description_clean"] = o["gift_description"].apply(normalize_arabic)
    o["cat_san"] = o["offer_category"].apply(sanitize)
    o["partner_san"] = o["offer_partner_en"].apply(sanitize)
    o["gt_san"] = o["offer_type"].str.lower()
    o["gov_san"] = o["offer_gov_primary"].str.strip().str.lower()
    med = o.groupby("cat_san")["gift_customer_price"].transform("median")
    o["gift_customer_price"] = o["gift_customer_price"].fillna(med).fillna(0.0)
    o["log_price"] = np.log1p(o["gift_customer_price"])
    o["log_popularity"] = np.log1p(o["popularity"])
    return o


def spend_matrix(users: pd.DataFrame, macro_cats: list) -> np.ndarray:
    """Roll fine-grained merchant spend into macro-category amounts (notebook §1.4)."""
    out = np.zeros((len(users), len(macro_cats)), dtype=np.float64)
    for j, macro in enumerate(macro_cats):
        for sub, m in MERCHANT_TO_MACRO.items():
            col = f"uv_{sub}_yc_merchant_amt_30d"
            if m == macro and col in users.columns:
                out[:, j] += users[col].fillna(0).to_numpy()
    return out


def build_artifacts(users_raw, ti, offers_raw, train_users: set) -> Artifacts:
    """Fit every retrieval index on `train_users` only (notebook §2.0-2.1)."""
    offers = prepare_offers(offers_raw)
    item_ids = offers["offer_id"].to_numpy()
    item_index = {o: i for i, o in enumerate(item_ids)}
    n_items = len(item_ids)
    macro_cats = sorted(offers["cat_san"].unique())
    macro_idx = {m: i for i, m in enumerate(macro_cats)}

    partner_cols = sorted(c for c in users_raw.columns if c.startswith("partner_pref_"))
    partner_index = {c[len("partner_pref_"):]: i for i, c in enumerate(partner_cols)}
    n_partners = len(partner_cols)
    gt_cols = sorted(c for c in users_raw.columns if c.startswith("gt_pref_"))
    gt_index = {c[len("gt_pref_"):]: i for i, c in enumerate(gt_cols)}
    cat_cols = sorted(c for c in users_raw.columns if c.startswith("cat_pref_"))

    offer_cat_idx = offers["cat_san"].map(macro_idx).to_numpy()
    offer_partner_idx = offers["partner_san"].map(partner_index).fillna(n_partners).astype(int).to_numpy()
    offer_gov = offers["gov_san"].fillna("unknown").to_numpy()

    gov_sets = (offers["offer_gov_set"].fillna("").astype(str)
                .map(lambda s: frozenset(g.strip().lower() for g in s.split("|") if g.strip())))
    tags = sorted(set().union(*gov_sets))
    gov_tag_idx = {g: i for i, g in enumerate(tags)}
    membership = np.zeros((n_items, len(tags)), dtype=np.float32)
    for j, gs in enumerate(gov_sets):
        for g in gs:
            membership[j, gov_tag_idx[g]] = 1.0

    f32 = lambda s: offers[s].fillna(0).to_numpy(np.float32)
    static_cols = {
        "log_price": f32("log_price"), "discount_norm": f32("discount_value_norm"),
        "signal_quality": f32("signal_quality"), "log_popularity": f32("log_popularity"),
        "offer_purchase_rate": f32("offer_purchase_rate"), "offer_redemption_rate": f32("offer_redemption_rate"),
        "cash_amount_norm": f32("cash_amount_norm"), "dtype_percentage": f32("dtype_percentage"),
        "dtype_fixed": f32("dtype_fixed"), "dtype_unknown": f32("dtype_unknown"),
        "is_waffarha_offer": f32("is_waffarha"),
    }

    offer_meta = [{"partner": str(r.offer_partner_en), "description": str(r.gift_description)[:140],
                   "type": str(r.offer_type), "price": round(float(r.gift_customer_price), 2),
                   "gov": str(r.offer_gov_primary), "ends": str(r.gift_end_date)}
                  for r in offers.itertuples()]

    anchor = pd.to_datetime(offers["gift_start_date"]).min()
    start_day = (pd.to_datetime(offers["gift_start_date"]) - anchor).dt.days.to_numpy()
    end_day = (pd.to_datetime(offers["gift_end_date"]) - anchor).dt.days.to_numpy()
    eval_day = int(ti["days_since_first_event"].max())

    # TF-IDF on cleaned description (notebook §1.7a)
    tf = TfidfVectorizer(max_features=2500, ngram_range=(1, 2))
    mat = normalize(tf.fit_transform(offers["gift_description_clean"]).astype(np.float32), axis=1)
    tfidf_dense = np.asarray(mat.todense(), dtype=np.float32)

    # user static side
    spend_amt = spend_matrix(users_raw, macro_cats)
    spend_norm = normalize(np.log1p(spend_amt), axis=1)
    affluence = np.log1p(spend_amt.sum(axis=1)) + 1.0
    total_spend = spend_amt.sum(axis=1).astype(np.float32)
    top_cat_idx = spend_amt.argmax(axis=1)
    open_cols = sorted(c for c in users_raw.columns if c.endswith("_offer_open_cnt_30d"))
    purch_cols = sorted(c for c in users_raw.columns if c.endswith("_offer_purchase_cnt_30d"))
    raw_open = users_raw[open_cols].sum(axis=1).to_numpy()
    raw_purch = users_raw[purch_cols].sum(axis=1).to_numpy()
    flags = users_raw[["uv_has_yc", "uv_has_bnpl", "uv_has_credit", "uv_has_debit"]].to_numpy(np.float32)
    cells = (users_raw["governorate"].astype(str) + "|" + users_raw["age_bucket"].astype(str) + "|"
             + users_raw["gender"].astype(str)).to_numpy()
    govs = users_raw["governorate"].str.strip().str.lower().to_numpy()

    user_static = {}
    for i, uid in enumerate(users_raw["user_id"]):
        user_static[uid] = {
            "gov": govs[i], "gov_tag": gov_tag_idx.get(govs[i], -1), "cell": cells[i],
            "spend_amt": spend_amt[i].astype(np.float32), "spend_norm": spend_norm[i].astype(np.float32),
            "affluence": float(affluence[i]), "total_spend": float(total_spend[i]),
            "top_cat_idx": int(top_cat_idx[i]), "top_cat": macro_cats[int(top_cat_idx[i])],
            "flags": flags[i].tolist(), "raw_open": float(raw_open[i]), "raw_purch": float(raw_purch[i]),
        }

    # ---- Stage-1 indices fitted on train users only ----
    tr = ti[ti["user_id"].isin(train_users)]
    tr_users = sorted(tr["user_id"].unique())
    tr_pos = {u: i for i, u in enumerate(tr_users)}
    rows = tr["user_id"].map(tr_pos).to_numpy()
    cols = tr["offer_id"].map(item_index).to_numpy()
    ui = (sparse.csr_matrix((tr["score"].to_numpy(), (rows, cols)), shape=(len(tr_users), n_items)) > 0).astype(np.float32)
    cooc = (ui.T @ ui).astype(np.float32)
    norms = np.sqrt(cooc.diagonal())
    norms[norms == 0] = 1.0
    sim = (sparse.diags(1.0 / norms) @ cooc @ sparse.diags(1.0 / norms)).tocsr()
    sim.setdiag(0.0)
    sim.eliminate_zeros()

    pop = f32("log_popularity")
    order = lambda idx: idx[np.argsort(-pop[idx])]
    gov_top = {g: order(np.where(offer_gov == g)[0]) for g in np.unique(offer_gov)}
    govset_top = {g: order(np.where(membership[:, i] > 0)[0]) for g, i in gov_tag_idx.items()}
    cat_top = {c: order(np.where(offer_cat_idx == i)[0]) for c, i in macro_idx.items()}
    nationwide_top = order(np.where(offer_gov == "nationwide")[0])
    partner_top = {int(p): order(np.where(offer_partner_idx == p)[0]) for p in np.unique(offer_partner_idx)}

    user_items = tr.groupby("user_id")["offer_id"].apply(lambda s: s.map(item_index).to_numpy())
    demo_cnt = {}
    cell_of = dict(zip(users_raw["user_id"], cells))
    for u, items in user_items.items():
        cnt = demo_cnt.setdefault(cell_of[u], np.zeros(n_items, np.float32))
        np.add.at(cnt, items, 1.0)

    ub = users_raw.set_index("user_id").loc[tr_users]
    pos_in_users = {u: i for i, u in enumerate(users_raw["user_id"])}
    bank_raw = np.concatenate([ub[cat_cols].to_numpy(), ub[gt_cols].to_numpy(),
                               spend_norm[[pos_in_users[u] for u in tr_users]]], axis=1).astype(np.float32)
    bank_norm = normalize(bank_raw, axis=1)
    bank_items = [user_items.get(u, np.array([], dtype=int)) for u in tr_users]

    onehot = pd.get_dummies(offers["cat_san"]).reindex(columns=macro_cats, fill_value=0).to_numpy(np.float32)

    return Artifacts(
        item_ids=item_ids, item_index=item_index, macro_cats=macro_cats, partner_index=partner_index,
        gt_index=gt_index, n_partners=n_partners, offer_cat_idx=offer_cat_idx,
        offer_partner_idx=offer_partner_idx,
        offer_gt_idx=offers["gt_san"].map(gt_index).fillna(-1).astype(int).to_numpy(), offer_gov=offer_gov, gov_set_membership=membership,
        gov_tag_idx=gov_tag_idx, nationwide_idx=gov_tag_idx.get("nationwide", -1),
        is_waffarha=f32("is_waffarha"), static_cols=static_cols, offer_meta=offer_meta, gift_price=f32("gift_customer_price"),
        discount_norm=f32("discount_value_norm"), start_day=start_day, end_day=end_day,
        anchor_date=str(anchor.date()), eval_day=eval_day, tfidf_dense=tfidf_dense,
        tfidf_vocab={k: int(v) for k, v in tf.vocabulary_.items()}, tfidf_idf=tf.idf_.astype(np.float32),
        content_vec=normalize(onehot, axis=1), item_sim=sim, pop=pop, gov_top=gov_top,
        govset_top=govset_top, cat_top=cat_top, nationwide_top=nationwide_top, partner_top=partner_top,
        demo_cell_cnt=demo_cnt, bank_norm=bank_norm, bank_items=bank_items,
        user_ids=list(users_raw["user_id"]), user_static=user_static,
    )


def save_artifacts(art: Artifacts, path: Path):
    with open(path, "wb") as f:
        pickle.dump(art, f, protocol=pickle.HIGHEST_PROTOCOL)


def load_artifacts(path: Path) -> Artifacts:
    with open(path, "rb") as f:
        return pickle.load(f)
