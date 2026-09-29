# Running the Fawry recommender stack — GitHub Codespaces, Docker, and native

This guide shows how to run and inspect **every part** of the project: Redis, PostgreSQL, Event Worker, API,
Training, Traefik (load balancer), Autoscaler, Load test and the Gradio UI. Part A uses Docker Compose inside a
GitHub Codespace (the intended way). Part B runs each service natively without Docker.

> **What was and was not tested.** The application code (training, API, worker, UI, load test, rollback, hot swap) was
> run for real together with a real Redis 7 and a real PostgreSQL, and the UI was driven through its API.
> **Docker, Traefik, the autoscaler container and GitHub Codespaces themselves were not available where this was built**,
> so those steps are written from how the tools work and have not been executed. If a command below fails, see
> [Troubleshooting](#troubleshooting) and treat it as a bug to fix, not as your mistake.

## Contents

1. [What runs where (ports)](#1-what-runs-where)
2. [Part A: Codespaces + Docker Compose](#2-part-a-codespaces--docker-compose)
3. [Working with each component](#3-working-with-each-component)
4. [Part B: without Docker](#4-part-b-native-without-docker)
5. [Stop, restart, cleanup, cost](#5-stop-restart-cleanup-cost)
6. [Troubleshooting](#troubleshooting)

---

## 1. What runs where

| Service | Container | Port in Codespace | What it is |
|---|---|---|---|
| UI | `ui` | **7860** | Fawry-style Gradio app (login, For you, Offers) |
| Load balancer | `traefik` | **8000** (dashboard **8080**) | Public entry to the API; spreads requests over API replicas |
| API | `api` (1..10 replicas) | internal `8000` | FastAPI: `/recommendations`, `/events`, `/health`, `/ready`, `/model` |
| Event Worker | `event-worker` | – | Redis Stream → PostgreSQL |
| Training | `training` | – | Weekly training + model publishing |
| Redis | `redis` | – | User live state, recommendation cache, event stream |
| PostgreSQL | `postgres` | – | `users`, `offers`, `events`, `model_versions` |
| Autoscaler | `autoscaler` | **9100** (`/status`) | Adds/removes API containers |

```
Browser ─► UI (7860) ──┐
curl / load test ──────┴─► Traefik (8000) ─► API replicas ─► Redis ─► Event Worker ─► PostgreSQL
                                                  ▲
                            Training ─► models/vN + models/current.json (API hot-swaps)
```

---

## 2. Part A: Codespaces + Docker Compose

### 2.1 Put the project on GitHub

Codespaces needs a GitHub repository (a private one is fine).

```bash
# on your machine, inside the unzipped project folder
git init && git add . && git commit -m "fawry recsys backend + ui"
# either create the repo on github.com and follow its push instructions, or with the GitHub CLI:
gh repo create fawry-recsys --private --source . --push
```

`.gitignore` already excludes `data/*.csv`, trained models and load-test results, so **your real Fawry CSVs are never
committed**. You will upload them inside the Codespace in step 2.3.

### 2.2 Create the Codespace

1. On the repository page: **Code → Codespaces → ⋯ → New with options**.
2. Machine type: **4-core / 16 GB** is recommended (needed for the autoscaling and load tests to mean anything).
   **2-core / 8 GB** is enough to run the stack and the UI, and to train on the sample data.
3. Create. The included `.devcontainer/devcontainer.json` selects a Python 3.12 image and enables **Docker-in-Docker**,
   and forwards ports 7860, 8000, 8080 and 9100.

In the Codespace terminal, check Docker works:

```bash
docker --version && docker compose version
docker ps            # empty list is fine
```

If `docker ps` says "cannot connect to the Docker daemon", rebuild the container
(**Command Palette → Codespaces: Rebuild Container**).

### 2.3 Provide the data

The training service reads three files from `data/`:

```
data/user_features.csv
data/train_interactions.csv
data/offer_features.csv
```

Upload them by dragging them into the **Explorer → data** folder (or `gh codespace cp` from your machine). They stay
inside the Codespace and are not committed.

```bash
ls -lh data
```

If `data/` is empty, training **generates a synthetic dataset** with the same schema so everything still runs; it logs a
warning. Never judge model quality from a synthetic run.

### 2.4 Start everything

```bash
docker compose up --build -d      # builds 5 images (api, training, worker, ui, autoscaler), pulls 3, starts 8 services
docker compose ps                 # all should be "running"; api becomes "healthy" only after a model exists
docker compose logs -f training   # wait for:  === v1 READY and published ===
```

The first start has no model, so the `training` service trains one (about 4 minutes on a 1-CPU test machine with the
sample-sized data; your time will differ). Until then `GET /ready` returns 503 and the UI shows *"Recommendation service is
not ready yet"*. As soon as `models/current.json` appears, every API container loads the model by itself; no restart.

Stop following logs with `Ctrl+C` (the services keep running).

### 2.5 Open the parts in the browser

Open the **PORTS** tab (next to *Terminal*). For each forwarded port, hover the *Local Address* column and click the globe
icon (or the port row → *Open in Browser*):

| Port | Open | What you should see |
|---|---|---|
| 7860 | UI | Fawry login screen |
| 8000 | `…/docs` | FastAPI interactive docs |
| 8000 | `…/ready` | `{"status":"ready","model_version":"v1"}` |
| 8080 | `…/dashboard/` (keep the trailing slash) | Traefik dashboard: routers, services, servers |
| 9100 | `…/status` | Autoscaler JSON (replicas, cpu, rps, p95) |

Ports are **private** by default, which means only you (logged into GitHub) can open the forwarded URLs. Keep them private.

### 2.6 Smoke test from the terminal

```bash
curl -s localhost:8000/ready
curl -s -X POST localhost:8000/recommendations -H 'content-type: application/json' \
     -d '{"user_id":"CUST_0007","top_n":5}' | python -m json.tool
```

Get real user and offer ids from your data:

```bash
python - <<'EOF'
import pandas as pd
print(pd.read_csv('data/user_features.csv', usecols=['user_id']).user_id.head(3).tolist())
print(pd.read_csv('data/offer_features.csv', usecols=['offer_id']).offer_id.head(3).tolist())
EOF
```

Unknown user ids are accepted and served as cold users.

---

## 3. Working with each component

### 3.1 The UI (port 7860)

* **Log in** with a customer id from your data (for example `CUST_0007`) and any non-empty password (the original demo
  has no real authentication).
* **Sign up** creates a *cold-start* user `USER_<your phone digits>`: watch the recommendations start generic and adapt as
  you interact.
* **Home → For you** shows the first 6 recommendations; **Offers** shows 10 with rank and *Top pick / Explore* badges.
* Buttons **Click / Open / Buy / Redeem** on an offer send `POST /events`. The list is then regenerated from the updated
  Redis state (the cache was deleted by the event).
* The small status line shows: model version, `fresh` or `cache hit`, latency, and **which API replica answered**.
* **Refresh recommendations** re-requests without sending an event: the second call inside 30 s is a cache hit.

```bash
docker compose logs -f ui         # UI logs
docker compose up -d --build ui   # rebuild after editing files in ui/
```

### 3.2 Redis

```bash
docker compose exec redis redis-cli ping
docker compose exec redis redis-cli
```

Inside `redis-cli` (after you clicked around in the UI as `CUST_0007`):

```
KEYS user:*                              # live state hashes
HGETALL user:CUST_0007                   # cat:*, partner:*, gt:*, offer:*, counters, last_event
KEYS recommendations:*                   # cached slates (30 s TTL)
TTL recommendations:CUST_0007            # seconds left, -2 = expired/deleted (an event deletes it)
XLEN events:stream                       # events waiting or kept in the stream
XINFO GROUPS events:stream               # consumer group: pending (unacked) and lag
XPENDING events:stream event-workers     # unacked messages summary
```

Watching cache invalidation: request recommendations → `TTL` shows ~30 → send an event for that user → `TTL` shows `-2` →
request again → new key.

### 3.3 PostgreSQL

```bash
docker compose exec postgres psql -U fawry -d fawry
```

```sql
\dt
SELECT count(*) FROM users;  SELECT count(*) FROM offers;  SELECT count(*) FROM events;
SELECT user_id, offer_id, event, ts FROM events ORDER BY id DESC LIMIT 10;
SELECT version, status, n_features, round(ndcg_before::numeric,4) AS ndcg34, round(ndcg_after::numeric,4) AS ndcg17
FROM model_versions ORDER BY created_at;
```

`users` and `offers` are seeded from the CSVs by the training service (first run). `events` are written by the worker.
`model_versions` is written by every training run, including rejected ones. The API never reads PostgreSQL per request.

### 3.4 Event Worker

```bash
docker compose logs -f event-worker
```

**Durability demo** (events survive a worker outage):

```bash
docker compose stop event-worker
for i in 1 2 3 4 5; do curl -s -X POST localhost:8000/events -H 'content-type: application/json' \
  -d '{"user_id":"CUST_0007","offer_id":"OFFER_0001","event":"click"}' >/dev/null; done
docker compose exec redis redis-cli XLEN events:stream          # grew
docker compose exec postgres psql -U fawry -d fawry -c "select count(*) from events"   # unchanged
docker compose start event-worker
sleep 5
docker compose exec postgres psql -U fawry -d fawry -c "select count(*) from events"   # +5
```

Replays never duplicate rows because `events.event_id` is `UNIQUE`.

### 3.5 API

```bash
docker compose logs -f api

curl -s localhost:8000/health
curl -s localhost:8000/ready
curl -s localhost:8000/model | python -m json.tool      # version, the 17 features, NDCG@10

curl -s -X POST localhost:8000/events -H 'content-type: application/json' \
     -d '{"user_id":"CUST_0007","offer_id":"OFFER_0868","event":"purchase"}'
```

`event` must be one of `click`, `open`, `purchase`, `redemption`; anything else returns `422`.
`top_n` must be 1–50.

### 3.6 Traefik (load balancer)

Dashboard: port 8080 → `/dashboard/` → **HTTP → Routers/Services**: you should see the `api` router and the `api` service with
one *server* per healthy API container.

**Prove the balancing.** Every API response carries `X-Served-By` (the container id). Stop the autoscaler so it does not
fight you, scale manually, then send requests:

```bash
docker compose stop autoscaler
docker compose up -d --no-deps --no-recreate --scale api=3 api
docker compose ps api                                   # wait until all 3 are healthy (~30 s)

for i in $(seq 1 12); do
  curl -s -i -X POST localhost:8000/recommendations -H 'content-type: application/json' \
       -d "{\"user_id\":\"CUST_$(printf %04d $i)\",\"top_n\":3}" | grep -i '^x-served-by'
done | sort | uniq -c                                   # requests spread over 3 different ids

docker ps --format '{{.ID}}  {{.Names}}' | grep api     # map ids to container names
```

Scale back and restore autoscaling:

```bash
docker compose up -d --no-deps --scale api=1 api
docker compose start autoscaler
```

Traefik only routes to a container after its healthcheck (`/ready`) passes, so new replicas receive no traffic while they
are still loading the model.

### 3.7 Training

```bash
docker compose logs -f training                                     # the scheduler + last run output
docker compose exec training python -m training.train --once        # train a new version right now
```

What you will see in the log, in this order: users split, retrieval artifacts, the 34-feature table, model training,
**Top 17 features by GAIN importance** (with values), the dropped features, `NDCG@10 BEFORE (34 features)` and
`AFTER (17 features)` on validation and test, the popularity baseline, one line per gate (`PASS`/`FAIL`), then
`READY and published` or `REJECTED`.

The schedule is **every Sunday 00:00** in the container's `TZ` (set in `docker-compose.yml`, `Africa/Cairo`).
The training container also trains once at start if no model exists.

Files created per version:

```bash
ls models/ models/v1
cat models/current.json
python -m json.tool models/v1/feature_schema.json | head -40      # the 17 features + all 34 gains
python -m json.tool models/v1/metadata.json | head -60            # metrics and gates
```

**See a rejection.** Force a failing gate (requires 17-feature NDCG to beat 34-feature NDCG by 1.0, which is impossible):

```bash
docker compose exec -e MAX_NDCG_DROP=-1 training python -m training.train --once
cat models/current.json         # unchanged: production stays on the old version
docker compose exec postgres psql -U fawry -d fawry -c "select version,status from model_versions"
```

Rejected versions stay on disk (their `metadata.json` says `rejected`) but are never published.

### 3.8 Hot model swap and rollback

Keep the API log open in one terminal and train in another:

```bash
docker compose logs -f api | grep -E "MODEL SWAP|could not load"
docker compose exec training python -m training.train --once        # second terminal
```

When the new version passes its gates you will see `MODEL SWAP v1 -> v2` in every API container within a few seconds
(polling interval 5 s), and `curl localhost:8000/model` reports `v2`. Requests keep being answered throughout.

**Roll back** to the previous version (rejected versions are refused):

```bash
docker compose exec training python scripts/rollback.py          # to "previous" in current.json
docker compose exec training python scripts/rollback.py v1       # or a specific version
```

**Simulate a broken release.** Files under `models/` are created by containers as root, so do file edits through a container:

```bash
docker compose exec training sh -c 'mkdir -p models/v99 && echo garbage > models/v99/model.txt \
  && echo "{\"version\": \"v99\", \"previous\": \"v1\"}" > models/current.json'
sleep 8
docker compose logs --tail 5 api            # "could not load v99 ... production stays on v1"
curl -s localhost:8000/model | python -m json.tool | grep -E '"version"|rejected|load_error'
# clean up
docker compose exec training sh -c 'rm -rf models/v99'
docker compose exec training python scripts/rollback.py v1
```

### 3.9 Autoscaler

```bash
docker compose logs -f autoscaler          # one line every 5 s: replicas, rps, p95, cpu, action
curl -s localhost:9100/status              # same numbers as JSON
watch -n 2 'docker ps --filter label=com.docker.compose.service=api --format "{{.Names}}  {{.Status}}"'
```

Rules: `MIN_REPLICAS=1`, `MAX_REPLICAS=10`; one container added or removed at a time; scale-up cooldown 30 s, scale-down
cooldown 60 s; never adds while a replica is still starting. Scale up when average CPU > 70 % of the 1-CPU limit,
p95 > 150 ms, or requests/sec per replica > `TARGET_RPS_PER_REPLICA`; scale down when all three are low.
Settings are environment variables of the `autoscaler` service in `docker-compose.yml`
(`docker compose up -d autoscaler` applies changes).

**Watch it scale.** Because of the cooldowns, growing to N replicas takes about `30 s × (N-1)`, so give the load time:

```bash
# terminal 1: docker compose logs -f autoscaler      terminal 2: the watch command above      terminal 3:
python loadtest/loadtest.py --levels 200 --seconds 180 --settle 0 --hot-users 300
```

After the load stops, replicas drop back one per 60 s.

> `TARGET_RPS_PER_REPLICA=40` is a **placeholder**, not a measurement (it is deliberately low so scaling is visible).
> On a 2–4 core Codespace, more replicas than cores will not add capacity, and the load generator runs on the same
> machine, so treat scaling here as a behavior demo, not a capacity test.

### 3.10 Load test

```bash
pip install httpx pandas numpy            # already done by the devcontainer postCreateCommand
python loadtest/loadtest.py               # 10 / 25 / 50 / 100 / 200 RPS, 30 s each
python loadtest/loadtest.py --levels 10 25 50 --seconds 15 --settle 5
python loadtest/loadtest.py --hot-users 200     # fewer distinct users -> more cache hits
python loadtest/loadtest.py --event-ratio 0.3   # 30 % of requests are POST /events
```

Output columns: `target` (asked), `offered` (actually generated; lower than target means the generator was saturated), `RPS`
(successful responses per second), `p50/p95/p99` in ms, `err%`, `cont` (API containers at the end of the level), `max`
(most containers seen during the level), `cpu%` (average CPU of API containers as % of their limit), `RAM MB` (sum over
API containers). A CSV is written to `loadtest/results/`; download it from the Explorer (right-click → Download).

**Calibrating the autoscaler** (do this once):

```bash
docker compose stop autoscaler
python loadtest/loadtest.py --levels 10 25 50 100 200 --seconds 30
```

With one replica, find the highest RPS where p95 is still acceptable and errors are 0, keep a safety margin, then set it as
`TARGET_RPS_PER_REPLICA` in `docker-compose.yml` and `docker compose up -d autoscaler`.

Reference point (not a promise about your machine): on a 1-CPU test box that also ran Redis, PostgreSQL, the worker and
the load generator, one API process handled 200 RPS with p95 ≈ 5 ms on the synthetic sample data (1,328 offers,
3,000 users). Real data and other hardware will differ, and the design has known limits at very large user counts
(see the README's *Known limitations*).

---

## 4. Part B: native (without Docker)

Useful for debugging one service at a time. Commands are for the Codespace (Debian/Ubuntu); use six terminals.

### 4.1 One-time setup

```bash
sudo apt-get update && sudo apt-get install -y redis-server postgresql
sudo service redis-server start && redis-cli ping                 # PONG
sudo service postgresql start
sudo -u postgres psql -c "CREATE USER fawry WITH PASSWORD 'fawry' SUPERUSER;" -c "CREATE DATABASE fawry OWNER fawry;"

# Two separate virtual environments: Gradio pins older pydantic/pandas than the backend does,
# so they cannot share one environment (in Docker they are separate images for the same reason).
python -m venv .venv    && .venv/bin/pip install -r requirements.txt        # training, API, worker, load test
python -m venv .venv-ui && .venv-ui/bin/pip install -r ui/requirements.txt  # UI only
```

In **every** terminal run `source .venv/bin/activate` (backend terminals) or `source .venv-ui/bin/activate` (the UI terminal), then:

```bash
export PYTHONPATH=.
export REDIS_URL=redis://localhost:6379/0
export DATABASE_URL=postgresql://fawry:fawry@localhost:5432/fawry
export MODELS_DIR=models DATA_DIR=data
export API_BASE=http://localhost:8000
```

### 4.2 Run each service

| Terminal | Command | Notes |
|---|---|---|
| 1 Training | `python -m training.train --once` | Publishes `models/v1`. Add `--schedule` to keep the weekly loop. Works without PostgreSQL (it warns). |
| 2 API | `uvicorn api.main:app --port 8000` | Returns 503 on `/ready` until a model exists, then loads it. Start several on other ports to imitate replicas. |
| 3 Worker | `python -m worker.worker` | Needs Redis + PostgreSQL. |
| 4 UI (`.venv-ui`) | `cd ui && python app.py` | Open forwarded port 7860. Talks to the API on `API_BASE` directly (no Traefik here). |
| 5 Load test | `python loadtest/loadtest.py --base http://localhost:8000` | `cont`, `cpu%` and `RAM` show `n/a` (no autoscaler). |
| 6 Rollback | `python scripts/rollback.py [vN]` | Same as in Docker. |

There is no Traefik or autoscaler in this mode; those are the Docker-only parts.

Inspecting Redis and PostgreSQL natively:

```bash
redis-cli HGETALL user:CUST_0007
PGPASSWORD=fawry psql -h localhost -U fawry -d fawry -c "select count(*) from events"
```

---

## 5. Stop, restart, cleanup, cost

```bash
docker compose stop            # stop containers, keep data (Redis, PostgreSQL volumes, models/)
docker compose up -d           # start again (no rebuild needed; add --build after code changes)
docker compose down            # remove containers (also removes autoscaler-created API replicas)
docker compose down -v         # also delete the Redis and PostgreSQL volumes (events history is lost)
rm -rf models/v* models/current.json     # force a fresh bootstrap training (run via sudo or a container: files are root-owned)
```

* A Codespace **stops after inactivity** (30 minutes by default); the workspace files and Docker volumes are kept.
  After it wakes up run `docker compose up -d`. Stop it yourself from the Codespaces page when you finish.
* Codespaces usage is billed in *core-hours* against your plan's monthly allowance, so a 4-core machine uses the allowance twice
  as fast as a 2-core one. Delete the Codespace when the project is done (the repository is untouched).

---

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| `/ready` = 503, UI says "not ready" | No model yet, or API can't reach Redis | `docker compose logs training` (wait for `READY`); `docker compose ps redis` |
| Training container exits / "Killed", exit code 137 | Out of memory while building the query table | Use a bigger Codespace machine; `docker stats`; for very large data chunk the table (see README limitations) |
| `training` logs "generating synthetic data" | `data/` has no CSVs | Upload the 3 CSVs to `data/`, delete `models/v*` and `models/current.json` (via container/sudo), `docker compose restart training` |
| Traefik returns `404 page not found` | No healthy API container yet | `docker compose ps api` (status must be *healthy*); `docker compose logs api` |
| UI shows "Cannot reach the recommendation backend" | Traefik or API down | `docker compose ps`; `curl localhost:8000/ready` inside the Codespace |
| UI page blank or stuck loading in the browser | Opened the wrong URL or an old tab | Open port 7860 from the PORTS tab, hard-refresh; check `docker compose logs ui` |
| Autoscaler logs "tick failed" / permission denied on `docker.sock` | Docker socket not accessible | `ls -l /var/run/docker.sock`; rebuild the Codespace container (Docker-in-Docker feature) |
| Replicas never go above 1 under load | Thresholds not exceeded, or one replica is still starting | Read the autoscaler log line: `rps`, `p95`, `cpu`; lower `TARGET_RPS_PER_REPLICA` for a demo |
| Load test shows `offered` < `target` | Load generator saturated the machine | Lower the levels or run on a bigger machine |
| `Permission denied` editing `models/...` | Files are root-owned (created in containers) | Edit via `docker compose exec training sh -c '…'` or use `sudo` |
| Port 8000 or 7860 already in use (native mode) | Another process or the Docker stack | `docker compose stop`, or change `--port` / `PORT` |
| Build fails on `pip install` | Network hiccup | Re-run `docker compose build --no-cache api` |
| `rollback.py` says "refusing to publish" | That version failed validation | Choose another version from `ls models/` |

Useful everyday commands:

```bash
docker compose ps
docker compose logs -f --tail 50 api event-worker training ui autoscaler
docker stats --no-stream
docker compose restart api          # restarts the compose-created api container only; use down/up for a full reset
```
