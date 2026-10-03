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

# Event -> interaction flag (the same flags the training rows carry). There are NO hand-set event weights any more:
# a (user, offer) row's score is looked up from a table fitted on the training data (Artifacts.score_table), so
# serving uses the same score scale the model was trained on.
EVENT_FLAG = {"click": "has_investigation", "open": "has_open", "purchase": "has_purchase", "redemption": "has_redemption"}
EVENTS = tuple(EVENT_FLAG)
# Legacy fallback ONLY for old model versions that were saved without a score table.
EVENT_WEIGHT = {"click": 1.0, "open": 1.0, "purchase": 3.0, "redemption": 2.0}

# History semantics are NOT configurable any more: every interaction is a target and its history is ONLY the same
# user's earlier interactions (sequential point-in-time, see common/core.py: fold_history). Leave-one-out is gone.

# Training queries whose true offer was NOT retrieved by Stage 1: the notebook injected the positive into the
# candidate list. Measured here (past-only history), that makes the ranker WORSE than plain popularity, because
# injected positives look different from retrieved ones. Default: drop such queries from the train split.
INJECT_MISSED_POSITIVE = os.getenv("INJECT_MISSED_POSITIVE", "0") == "1"

# The 17 serving/training features are FIXED (common/core.py: CANONICAL_17). log_days_to_expire is one of them; it is
# only meaningful in training if the dataset's day axis is aligned with the offers' calendar. Set DAY0_DATE to the real
# calendar date of days_since_first_event == 0 when you know it (default: earliest offer start, usually WRONG - the
# training log warns about it). When the axis is not aligned the trainer evaluates that feature at the same reference
# day the API uses (AS_OF_DATE), so the formula and the reference are identical in training and serving.
DAY0_DATE = os.getenv("DAY0_DATE", "")  # ISO date of days_since_first_event == 0; default: earliest offer start

# Reference date for the expiry filter and log_days_to_expire: "today" (real date), "dataset" (last day in the
# interaction logs, as in the notebook) or an ISO date such as 2025-06-30.
AS_OF_DATE = os.getenv("AS_OF_DATE", "today")
EXPLORE_FRAC = 0.2

# Candidate generation, shared by serving AND training queries (common/core.py: generate_candidates): the eligibility
# filters (date, area, already-seen) run INSIDE each retrieval channel before its top-K; then union -> 17 features -> ranker.
MIN_POOL = int(os.getenv("MIN_POOL", "50"))                 # top up the filtered pool from eligible offers only
MAX_AREA_KM = float(os.getenv("MAX_AREA_KM", "250"))        # farther than this from every area -> no location filter
SIMILAR_PIN = int(os.getenv("SIMILAR_PIN", "3"))            # slots reserved for offers similar to the last interaction
SIMILAR_POOL = int(os.getenv("SIMILAR_POOL", "15"))
# The latest observed interaction is ALWAYS the anchor (training does the same: anchor = last prefix event). 0 = no
# age limit; a positive value only ignores a live (Redis) anchor older than that many seconds.
ANCHOR_MAX_AGE = int(os.getenv("ANCHOR_MAX_AGE_SECONDS", "0"))

N_FEATURES_FULL = 34
N_FEATURES_FINAL = 17
