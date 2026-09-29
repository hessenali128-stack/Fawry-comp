"""FastAPI service: 1 process, 1 loaded model. Endpoints: /recommendations /events /health /ready /model."""
import logging
import os
import socket
import time
from collections import deque
from contextlib import asynccontextmanager
from threading import Lock
from typing import Literal

import numpy as np
import redis
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from api import config as cfg
from api.recommender import ModelManager, apply_event, recommend

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

SERVED_BY = os.getenv("HOSTNAME", socket.gethostname())
mgr = ModelManager()
rds = redis.Redis.from_url(cfg.REDIS_URL, decode_responses=True, max_connections=cfg.REDIS_MAX_CONNECTIONS,
                           socket_timeout=2, socket_connect_timeout=2)

_window = deque()  # (timestamp, latency_ms) of recent requests, read by the autoscaler via /internal/stats
_wlock = Lock()


@asynccontextmanager
async def lifespan(app):
    mgr.start()
    yield


app = FastAPI(title="Fawry Offer Recommendations", lifespan=lifespan)


@app.middleware("http")
async def track(request: Request, call_next):
    t0 = time.perf_counter()
    resp = await call_next(request)
    resp.headers["X-Served-By"] = SERVED_BY
    if request.url.path in ("/recommendations", "/events"):
        now = time.time()
        with _wlock:
            _window.append((now, (time.perf_counter() - t0) * 1000, resp.status_code >= 500))
            while _window and _window[0][0] < now - cfg.STATS_WINDOW_SECONDS:
                _window.popleft()
    return resp


class RecReq(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    top_n: int = Field(10, ge=1, le=cfg.MAX_TOP_N)


class EventReq(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    offer_id: str = Field(min_length=1, max_length=64)
    event: Literal["click", "open", "purchase", "redemption"]


@app.post("/recommendations")
def recommendations(req: RecReq):
    if mgr.bundle is None:
        raise HTTPException(503, "model not loaded")
    t0 = time.perf_counter()
    try:
        out = recommend(rds, mgr, req.user_id, req.top_n)
    except redis.RedisError as e:
        raise HTTPException(503, f"redis unavailable: {e}")
    out["user_id"] = req.user_id
    out["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return out


@app.post("/events", status_code=202)
def events(req: EventReq):
    b = mgr.bundle
    if b is None:
        raise HTTPException(503, "model not loaded")
    if req.offer_id not in b.item_index:
        raise HTTPException(422, f"unknown offer_id {req.offer_id}")
    try:
        event_id = apply_event(rds, b, req.user_id, req.offer_id, req.event)
    except redis.RedisError as e:
        raise HTTPException(503, f"redis unavailable: {e}")
    return {"status": "accepted", "event_id": event_id}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    if mgr.bundle is None:
        raise HTTPException(503, "model not loaded")
    try:
        rds.ping()
    except redis.RedisError:
        raise HTTPException(503, "redis unavailable")
    return {"status": "ready", "model_version": mgr.bundle.version}


@app.get("/model")
def model():
    b = mgr.bundle
    if b is None:
        raise HTTPException(503, "model not loaded")
    m = b.meta["metrics"]
    return {"version": b.version, "loaded_at": b.loaded_at, "n_features": len(b.cols), "features": b.cols,
            "created_at": b.meta["created_at"],
            "ndcg@10": {"34_features_val": m["val_34"]["ndcg@10"], "17_features_val": m["val_17"]["ndcg@10"],
                        "17_features_test": m["test_17"]["ndcg@10"]},
            "load_error": mgr.last_error, "rejected_version": mgr.failed}


@app.get("/internal/stats", include_in_schema=False)
def stats():
    """Rolling request stats for the autoscaler (not routed through Traefik)."""
    now = time.time()
    with _wlock:
        rows = [(t, l, e) for t, l, e in _window if t >= now - cfg.STATS_WINDOW_SECONDS]
    if not rows:
        return {"rps": 0.0, "p50": 0, "p95": 0, "p99": 0, "n": 0, "errors": 0}
    lat = np.array([l for _, l, _ in rows])
    span = max(now - rows[0][0], 1.0)
    return {"rps": round(len(rows) / min(span, cfg.STATS_WINDOW_SECONDS), 2),
            "p50": float(np.percentile(lat, 50)), "p95": float(np.percentile(lat, 95)),
            "p99": float(np.percentile(lat, 99)), "n": len(rows), "errors": sum(e for _, _, e in rows)}
