import os

from common.config import *  # noqa: F401,F403  (shared: REDIS_URL, MODELS_DIR, CACHE_TTL, ...)

MODEL_POLL_SECONDS = float(os.getenv("MODEL_POLL_SECONDS", "5"))
STATS_WINDOW_SECONDS = 15
REDIS_MAX_CONNECTIONS = int(os.getenv("REDIS_MAX_CONNECTIONS", "64"))
STREAM_MAXLEN = 200_000
