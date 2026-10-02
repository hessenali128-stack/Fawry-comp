import os

MODELS_DIR = os.getenv("MODELS_DIR", "models")
DATA_DIR = os.getenv("DATA_DIR", "data")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://fawry:fawry@postgres:5432/fawry")

STREAM = "events:stream"
GROUP = "event-workers"
CACHE_TTL = int(os.getenv("CACHE_TTL", "30"))
USER_TTL = int(os.getenv("USER_STATE_TTL", str(30 * 24 * 3600)))
MAX_TOP_N = 50

# Event -> score weight. Assumption: notebook row score = sum of event weights (purchase > click/open).
EVENT_WEIGHT = {"click": 1.0, "open": 1.0, "purchase": 3.0, "redemption": 2.0}
EVENTS = tuple(EVENT_WEIGHT)

# Reference date for the expiry filter and log_days_to_expire: "today" (real date), "dataset" (last day in the
# interaction logs, as in the notebook) or an ISO date such as 2025-06-30.
AS_OF_DATE = os.getenv("AS_OF_DATE", "today")
EXPLORE_FRAC = 0.2

# Serving-only: filters run after retrieval and before the reranker.
MIN_POOL = int(os.getenv("MIN_POOL", "50"))                 # top up the filtered pool from eligible offers only
MAX_AREA_KM = float(os.getenv("MAX_AREA_KM", "250"))        # farther than this from every area -> no location filter
SIMILAR_PIN = int(os.getenv("SIMILAR_PIN", "3"))            # slots reserved for offers similar to the last interaction
SIMILAR_POOL = int(os.getenv("SIMILAR_POOL", "15"))
ANCHOR_MAX_AGE = int(os.getenv("ANCHOR_MAX_AGE_SECONDS", str(24 * 3600)))

N_FEATURES_FULL = 34
N_FEATURES_FINAL = 17
