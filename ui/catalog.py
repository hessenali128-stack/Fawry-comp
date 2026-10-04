"""Offer catalog for the 'All offers' tab: read straight from offers.csv (a slim copy of data/offer_features.csv),
so browsing and searching never depends on the recommendation API / model being up."""
import csv
import re
from datetime import date, datetime, timedelta
from pathlib import Path

_PATH = Path(__file__).with_name("offers.csv")
OFFERS = []
# accepts the slim offers.csv AND the raw data/offer_features.csv (so a wrong copy cannot crash the UI)
_MAP = {"partner": "offer_partner_en", "category": "offer_category", "description": "gift_description", "start": "gift_start_date",
        "end": "gift_end_date", "price": "gift_customer_price", "type": "offer_type", "gov": "offer_gov_primary",
        "govset": "offer_gov_set", "area": "offer_area_primary", "dtype": "offer_discount_type", "dvalue": "offer_discount_value", "cash": "offer_cash_amount",
        "pop": "popularity"}
_SRC = _PATH if _PATH.exists() else Path(__file__).parent.parent / "data" / "offer_features.csv"
if _SRC.exists():
    for raw in csv.DictReader(open(_SRC, encoding="utf-8-sig")):
        r = {"offer_id": raw.get("offer_id", "")}
        for k, alt in _MAP.items():
            r[k] = (raw.get(k) if raw.get(k) is not None else raw.get(alt)) or ""
        r["start"], r["end"] = r["start"][:10], r["end"][:10]
        # governorates the offer is really valid in: primary + the offer_gov_set (same rule as the backend's expanded_geo)
        r["govs"] = sorted({g.strip() for g in ([r["gov"]] + r["govset"].split("|")) if g.strip() and g.strip().upper() != "NATIONWIDE"})
        r["category"] = r["category"].strip()
        for k in ("price", "pop", "dvalue", "cash"):
            try: r[k] = float(r[k] or 0)
            except ValueError: r[k] = 0.0
        r["hay"] = " ".join(str(r[k]) for k in ("offer_id", "partner", "category", "description", "type", "gov", "area")).lower().replace("_", " ")
        if r["offer_id"]: OFFERS.append(r)
GOVS = sorted({g for o in OFFERS for g in o["govs"]})


def in_area(o, gov):
    """Offer is available in `gov`: nationwide, or its primary governorate / governorate set contains it."""
    return not gov or o["gov"].upper() == "NATIONWIDE" or gov.lower() in {g.lower() for g in o["govs"]}


def today():
    return (datetime.utcnow() + timedelta(hours=3)).date().isoformat()


def is_active(o, t=None): return o["start"] <= (t or today()) <= o["end"] or (o["end"] >= (t or today()))


def search(q="", category="", gov="", active_only=False, limit=24):
    """-> dict(total, offers[:limit], categories[with counts], active, as_of). Active offers first, then by popularity."""
    t = today()
    toks = [w for w in re.split(r"\s+", (q or "").lower().strip()) if w]
    base = [o for o in OFFERS if all(w in o["hay"] for w in toks)
            and in_area(o, gov)
            and (not active_only or o["end"] >= t)]
    cats = {}
    for o in base:
        cats[o["category"]] = cats.get(o["category"], 0) + 1
    rows = [o for o in base if not category or o["category"] == category]
    first = toks[0] if toks else ""
    rows.sort(key=lambda o: (o["end"] < t, not (first and o["partner"].lower().startswith(first)), -o["pop"]))
    return {"total": len(rows), "as_of": t, "active": sum(1 for o in rows if o["end"] >= t),
            "categories": [{"name": k, "count": v} for k, v in sorted(cats.items(), key=lambda x: -x[1])],
            "offers": rows[:limit]}
