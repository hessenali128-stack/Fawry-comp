"""Area (governorate) helpers for serving. CENTROIDS are approximate constants used only to map a device location
to the nearest governorate present in the dataset; they are not polygons, so borders (e.g. Cairo/Giza) are fuzzy."""
import math
import re

CENTROIDS = {
    "cairo": (30.04, 31.31), "giza": (29.98, 31.10), "alexandria": (31.20, 29.92), "qalyubia": (30.33, 31.21),
    "dakahlia": (31.05, 31.38), "sharqia": (30.60, 31.50), "gharbia": (30.87, 31.03), "menoufia": (30.55, 30.99),
    "beheira": (30.85, 30.34), "kafr el sheikh": (31.11, 30.94), "damietta": (31.42, 31.81),
    "port said": (31.27, 32.30), "ismailia": (30.60, 32.27), "suez": (29.97, 32.55),
    "north sinai": (31.13, 33.80), "south sinai": (28.24, 33.62), "red sea": (26.55, 33.80),
    "matrouh": (31.35, 27.24), "fayoum": (29.31, 30.84), "beni suef": (29.07, 31.10), "minya": (28.11, 30.75),
    "assiut": (27.18, 31.18), "sohag": (26.56, 31.69), "qena": (26.16, 32.72), "luxor": (25.70, 32.64),
    "aswan": (24.09, 32.90), "new valley": (25.45, 30.55),
}
ALIASES = {
    "alex": "alexandria", "qaliubiya": "qalyubia", "qalubia": "qalyubia", "kalyubia": "qalyubia",
    "qalyubiyya": "qalyubia", "sharkia": "sharqia", "sharqiyah": "sharqia", "gharbiyah": "gharbia",
    "monufia": "menoufia", "menofia": "menoufia", "minufiyah": "menoufia", "behera": "beheira",
    "buhayra": "beheira", "kafr elsheikh": "kafr el sheikh", "kafr el shaikh": "kafr el sheikh",
    "kafrelsheikh": "kafr el sheikh", "portsaid": "port said", "asyut": "assiut", "assuit": "assiut",
    "faiyum": "fayoum", "fayyum": "fayoum", "bani suef": "beni suef", "beni suwayf": "beni suef",
    "menia": "minya", "matruh": "matrouh", "marsa matrouh": "matrouh", "dakahliyah": "dakahlia",
    "daqahliyah": "dakahlia", "wadi el gedid": "new valley", "al wadi al jadid": "new valley",
    "al bahr al ahmar": "red sea", "janub sina": "south sinai", "shamal sina": "north sinai",
}


def canonical(name: str) -> str:
    n = re.sub(r"[^\w\s]", " ", str(name).lower())
    n = re.sub(r"\bgovernorate\b", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return ALIASES.get(n, n)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def nearest_area(lat: float, lon: float, centroids: dict, max_km: float):
    """centroids: {dataset_area_name: (lat, lon)} -> (area, km) or None if nothing is within max_km."""
    best = min(((a, haversine_km(lat, lon, *c)) for a, c in centroids.items()), key=lambda t: t[1], default=None)
    return best if best and best[1] <= max_km else None
