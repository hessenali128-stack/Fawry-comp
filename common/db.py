import json
import time

import psycopg

from common.config import DATABASE_URL

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY, governorate TEXT, age_bucket TEXT, gender TEXT,
  created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS offers (
  offer_id TEXT PRIMARY KEY, category TEXT, partner TEXT, offer_type TEXT, gov_primary TEXT,
  start_date DATE, end_date DATE, popularity DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS events (
  id BIGSERIAL PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, user_id TEXT NOT NULL,
  offer_id TEXT NOT NULL, event TEXT NOT NULL, ts TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS events_user_idx ON events (user_id, ts);
CREATE TABLE IF NOT EXISTS model_versions (
  version TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT now(),
  n_features INT, ndcg_before DOUBLE PRECISION, ndcg_after DOUBLE PRECISION, details JSONB);
"""


def connect(retries=30):
    for i in range(retries):
        try:
            return psycopg.connect(DATABASE_URL, autocommit=True)
        except psycopg.OperationalError:
            time.sleep(1)
    raise RuntimeError("postgres not reachable")


def init_schema(conn):
    conn.execute(SCHEMA)


def seed_catalog(conn, users, offers):
    """Idempotent: copy users/offers CSV rows into PostgreSQL."""
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO users(user_id,governorate,age_bucket,gender) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            users[["user_id", "governorate", "age_bucket", "gender"]].astype(str).values.tolist())
        rows = offers[["offer_id", "offer_category", "offer_partner_en", "offer_type", "offer_gov_primary",
                       "gift_start_date", "gift_end_date", "popularity"]].copy()
        rows = rows.astype(object).where(rows.notna(), None).values.tolist()
        cur.executemany(
            "INSERT INTO offers VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", rows)


def record_version(conn, version, status, n_features, before, after, details):
    conn.execute(
        """INSERT INTO model_versions(version,status,n_features,ndcg_before,ndcg_after,details)
           VALUES (%s,%s,%s,%s,%s,%s)
           ON CONFLICT (version) DO UPDATE SET status=EXCLUDED.status, ndcg_before=EXCLUDED.ndcg_before,
           ndcg_after=EXCLUDED.ndcg_after, details=EXCLUDED.details""",
        (version, status, n_features, before, after, json.dumps(details, default=float)))
