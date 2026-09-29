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

# "dataset": live day = last day in the dataset (as in the notebook). "calendar": real today vs anchor.
LIVE_DAY_MODE = os.getenv("LIVE_DAY_MODE", "dataset")
EXPLORE_FRAC = 0.2

N_FEATURES_FULL = 34
N_FEATURES_FINAL = 17
