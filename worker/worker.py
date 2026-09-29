"""Event worker: Redis Stream -> PostgreSQL.

The API already applied the event to the live Redis state (so the next request sees it). This service makes
it durable: consumer group + ack after commit = at-least-once; UNIQUE(event_id) makes replays harmless.
"""
import logging
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import redis

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import config as C  # noqa: E402
from common import db  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("worker")

CONSUMER = os.getenv("HOSTNAME", socket.gethostname())
BATCH = int(os.getenv("BATCH", "200"))
CLAIM_IDLE_MS = 60_000


def persist(conn, messages) -> int:
    """messages: [(msg_id, fields)] -> one batched INSERT; duplicates ignored."""
    rows = [(f["event_id"], f["user_id"], f["offer_id"], f["event"],
             datetime.fromtimestamp(float(f["ts"]), tz=timezone.utc)) for _, f in messages]
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO events(event_id,user_id,offer_id,event,ts) VALUES (%s,%s,%s,%s,%s) "
                        "ON CONFLICT (event_id) DO NOTHING", rows)
    return len(rows)


def main():
    r = redis.Redis.from_url(C.REDIS_URL, decode_responses=True)
    conn = db.connect()
    db.init_schema(conn)
    try:
        r.xgroup_create(C.STREAM, C.GROUP, id="0", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise
    log.info("worker %s consuming %s/%s", CONSUMER, C.STREAM, C.GROUP)
    total, last_claim, backlog = 0, 0.0, True

    while True:
        try:
            if conn.closed:
                conn = db.connect()
            msgs = []
            if backlog:  # first drain messages that were delivered to us but never acked (crash recovery)
                res = r.xreadgroup(C.GROUP, CONSUMER, {C.STREAM: "0"}, count=BATCH)
                msgs = res[0][1] if res else []
                if not msgs:
                    backlog = False
            if not msgs and time.time() - last_claim > 30:  # take over messages of dead consumers
                last_claim = time.time()
                claimed = r.xautoclaim(C.STREAM, C.GROUP, CONSUMER, min_idle_time=CLAIM_IDLE_MS, count=BATCH)
                msgs = claimed[1] if claimed else []
            if not msgs:
                res = r.xreadgroup(C.GROUP, CONSUMER, {C.STREAM: ">"}, count=BATCH, block=2000)
                msgs = res[0][1] if res else []
            if not msgs:
                continue
            ids = [i for i, _ in msgs]
            valid = [(i, f) for i, f in msgs if f]  # empty fields = entry trimmed from the stream
            if valid:
                total += persist(conn, valid)
            r.xack(C.STREAM, C.GROUP, *ids)  # ack only after the INSERT committed (autocommit)
            if valid and total % 1000 < len(valid):
                log.info("persisted %d events so far", total)
        except Exception as e:  # keep the worker alive; the batch is retried
            log.error("batch failed (%s) - retrying in 2s; unacked events are redelivered", e)
            backlog = True
            time.sleep(2)


if __name__ == "__main__":
    main()
