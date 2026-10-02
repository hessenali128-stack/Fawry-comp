# Fawry Offer Recommendations — FastAPI + Redis + PostgreSQL + Docker Compose + Traefik

Backend for the v5 hybrid cascade notebook: 6 retrieval channels → LightGBM `LGBMRanker` (LambdaRank),
with a new **34 → top-17 feature selection** step. Three application services (API, Training, Event Worker)
plus Redis, PostgreSQL, Traefik, a small autoscaler and the Fawry-style Gradio UI. No Kubernetes, no Kafka.

**Step-by-step operation of every part (GitHub Codespaces, Docker, native): [`CODESPACES_GUIDE.md`](CODESPACES_GUIDE.md) (English) · [`CODESPACES_GUIDE_AR.md`](CODESPACES_GUIDE_AR.md) (عربي + English, RTL).**

```
Browser → UI (Gradio :7860) ─┐
Users ───────────────────────┴→ Traefik → API #1..#N ──► Redis (user:{id}, recommendations:{id}, stream events:stream)
                                        │
                                        └──► Event Worker ──► PostgreSQL (users, offers, events, model_versions)
Training (weekly) ──► models/vN/ + models/current.json ◄── API hot-swaps
Autoscaler (Docker SDK) watches API containers and adds/removes replicas
```

## 0. Read this first

* **Put your real CSVs in `./data/`** (`user_features.csv`, `train_interactions.csv`, `offer_features.csv`).
  The project never generates data: if a file is missing, `training` logs what is missing and retries every 30 s, so you can
  upload the files after `docker compose up`. Offers and users come only from these files.
* The first `docker compose up` has no model yet: once the CSVs are present, the `training` service bootstraps one (a few
  minutes). The API answers `503 /ready` until `models/current.json` appears, then loads it automatically.
* **Expiry filter reference date:** `AS_OF_DATE` (default `today`). If every offer in your files has already expired, the API
  returns an empty list with a `warning` instead of expired offers; set `AS_OF_DATE=dataset` (last day of the logs) or a fixed
  date such as `2025-06-30` in `docker-compose.yml` for historical data. `GET /areas` shows how many offers are active.

## 1. Run

```bash
docker compose up --build
docker compose logs -f training      # wait for:  === v1 READY and published ===
curl localhost:8000/ready
```

Traefik listens on `localhost:8000` (dashboard: `localhost:8080/dashboard/`). The **UI is on `localhost:7860`**. Needs ~4 GB RAM free for training.

### UI (`ui/`)

Your Gradio app, same theme and components, now live:
log in with a customer id from your data (the password is not checked, as in the original demo) or sign up (creates a
cold-start user `USER_<phone>`). **Home → For you** and **Offers** show real `POST /recommendations` results; each offer has
**Click / Open / Buy / Redeem** buttons that send `POST /events`, after which the list is regenerated; the three offers most
similar to the last interaction are pinned on top (badge *Similar to your last click*). When the page opens the browser asks
for the device location; it is sent with each request (never stored) and the **Area** selector on the Offers page overrides
it. The status line shows model version, cache hit/fresh, latency, area and its source, the as-of date, and which API replica
answered (`X-Served-By`). The UI calls the API through Traefik (`API_BASE=http://traefik:80`). The UI shows no built-in
sample offers; Wallet, Quick pay and the *Featured* tiles are the original static screens, not data.

## 2. API usage

```bash
curl -X POST localhost:8000/recommendations -H 'content-type: application/json' \
     -d '{"user_id":"<USER_ID>","top_n":10}'

# optional: where the user is now (area name from GET /areas, or device lat+lon together)
curl -X POST localhost:8000/recommendations -H 'content-type: application/json' \
     -d '{"user_id":"<USER_ID>","top_n":10,"lat":31.2,"lon":29.95}'

curl -X POST localhost:8000/events -H 'content-type: application/json' \
     -d '{"user_id":"<USER_ID>","offer_id":"<OFFER_ID>","event":"click"}'      # click|open|purchase|redemption

curl localhost:8000/health     # liveness
curl localhost:8000/ready      # model loaded + Redis reachable
curl localhost:8000/model      # version, the 17 features, NDCG@10 of the loaded model
curl localhost:8000/areas      # areas in your data, as-of date, active offers today
```

`/recommendations` returns `model_version`, `cached`, `area` (`name`, `source` = request / location / profile / none),
`as_of`, `anchor_offer_id`, an optional `warning`, and `recommendations[]` (`rank, offer_id, score, source, category, …`).
`source` is `model` (LightGBM), `similar` (pinned, see §3) or `explore` (the notebook's 20 % exploration slots, used once a
user has events).
Unknown users are served as cold users (demographic/popularity channels only).

## 3. Redis cache

Redis holds exactly two things (plus the event stream):

| Key | Content | TTL |
|---|---|---|
| `user:{id}` (hash) | `cat:*`, `partner:*`, `gt:*` preference sums, `offer:{id}` interaction scores (the live TF-IDF profile is computed from these), counters, last event | 30 days |
| `recommendations:{user_id}` | ranked candidate pools for the current model version | 30 s |

Flow: cache hit → return. Miss → read `user:{id}` → Stage 1 (6 channels) → **filters** → build the 17 features → LightGBM →
cache → return. The cache is only reused for the same model version, area and as-of day. No Python dict holds user state, and
PostgreSQL is never touched per recommendation request.

### Serving filters, location and "similar to your click" (production path only; training is unchanged)

1. **Where is the user?** `area` in the request › `lat`+`lon` mapped to the nearest area of your data (farther than
   `MAX_AREA_KM`=250 km → ignored with a warning) › the governorate in `user_features.csv` › none (no area filter).
2. **Filters, after retrieval and before the reranker:** keep only offers that are *active on the as-of date*
   (`gift_start_date ≤ date ≤ gift_end_date`) and *available in the area* (same rule as the `expanded_geo_match` feature:
   primary governorate, governorate set, or nationwide). They are hard filters: if fewer than `MIN_POOL`=50 candidates
   survive, the pool is topped up from **eligible** offers only (most popular first), never from expired or out-of-area ones.
3. **Similar to the last interaction:** the offer of the latest event (within 24 h) is the anchor. The 15 eligible offers most
   similar to it (description TF-IDF cosine ×0.5 + same partner ×0.3 + same category ×0.2) join the pool, are scored by the
   ranker like everything else, and the best `SIMILAR_PIN`=3 are pinned to the top. The clicked offer itself is not repeated.
4. Channel B and the `expanded_geo_match` feature use the current area instead of the profile governorate.

Knobs (env on the `api` service): `AS_OF_DATE`, `MIN_POOL`, `MAX_AREA_KM`, `SIMILAR_PIN` (0 disables pinning), `SIMILAR_POOL`,
`ANCHOR_MAX_AGE_SECONDS`. The location is used only to pick the area for that request; it is not logged or stored. Area names
must match the governorate spellings in your files; location→area uses approximate centroids (nearest centroid, not polygons),
so it is unreliable near borders such as Cairo/Giza/Qalyubia — use the Area selector to correct it. Browsers only expose
location on HTTPS or `localhost` (a Codespaces forwarded URL is HTTPS).

## 4. Events

`POST /events` does one Redis round trip (atomic `MULTI`): update `user:{id}`, delete `recommendations:{user_id}`,
`XADD` to `events:stream`, return `202`. The next `/recommendations` regenerates fresh results.
The **Event Worker** reads the stream (consumer group, batched, ack *after* the INSERT commits, dead-consumer
reclaim) and writes `events` in PostgreSQL. `event_id` is `UNIQUE`, so redeliveries never duplicate rows.

Event → score weights are in `common/config.py` (`click 1, open 1, purchase 3, redemption 2`). **This is an assumption**:
the notebook's raw `score` formula is not in the files, so set it to match your data.

## 5. Training

`training/train.py --schedule` runs in the `training` container: bootstrap if no model exists, then **every Sunday 00:00**
(`TZ` in compose). Run one now: `docker compose exec training python -m training.train --once`.

```
load CSVs (+ production events from PostgreSQL)  →  retrieval artifacts (fit on train users only)
→ 34-feature query table (leave-one-out history; features computed by the same code the API uses)  →  LGBMRanker(34)
→ gain importance → top 17 → LGBMRanker(17) → validation gates → save models/vN → publish
```

Splits: 100 sandbox users = untouched **test**; the remaining users 85 % train / 15 % validation (stratified cold/warm).
The log prints the top-17 features with their gain, `NDCG@10 BEFORE (34)` and `AFTER (17)` on val and test, the popularity
baseline, and each gate. A version is **published only if all gates pass**:

1. converged (`best_iteration ≥ 20`)
2. val NDCG@10 (17 features) ≥ val NDCG@10 (34 features) − `MAX_NDCG_DROP` (0.01)
3. val NDCG@10 (17 features) ≥ popularity baseline
4. test NDCG@10 ≥ currently-serving model on the same test table − `MAX_REGRESSION` (0.02)

A rejected version stays on disk (`metadata.json` says `rejected`) and is never published. All versions are also
recorded in `model_versions` (PostgreSQL).

## 6. Top-17 feature selection

`LGBMRanker(importance_type="gain")`, `feature_importances_` sorted descending, first 17 kept, a fresh ranker trained on
only those. Names + all 34 gains are stored in `models/vN/feature_schema.json`; the API builds **only** those columns
(`common/core.py: build_features` computes only what the schema asks for). All 34 features are buildable in production.

## 7. Model versioning

```
models/
  v1/ v2/ v3/            model.txt  feature_schema.json  artifacts.pkl  metadata.json
  current.json           {"version": "v3", "previous": "v2"}
```

`artifacts.pkl` holds retrieval indices, TF-IDF, mappings and user static data. Versions are immutable; the last 5 are kept.
`current.json` is replaced atomically (`os.replace`).

## 8. Hot model swap and rollback

Every API container polls `current.json` (5 s). On a change it loads the new version **off to the side**, runs a smoke
request through it, then swaps one reference — in-flight requests finish on the old model, the server never stops.
If loading or the smoke test fails, the API keeps serving the old version (`/model` shows `rejected_version` and the error).
Cached recommendations carry the model version and are ignored after a swap.

Rollback (previous version stays on disk): `docker compose exec training python scripts/rollback.py` (or `... v2`).
It refuses versions that failed validation.

## 9. Autoscaling

`autoscaler/autoscaler.py` (Docker SDK) checks every 5 s: CPU (as % of each container's limit, 1 CPU each), requests/sec
and p95 (from each API's internal `/internal/stats`, not routed by Traefik). It adds/removes **one** `api` container at a
time between `MIN_REPLICAS=1` and `MAX_REPLICAS=10`, cooldowns **30 s up / 60 s down**, and never adds while a replica
is still booting. Scale up if CPU > 70 %, p95 > 150 ms, or RPS/replica > `TARGET_RPS_PER_REPLICA`; scale down if all are low.
New replicas are clones of the compose-created container; Traefik discovers them by Docker label and routes only after
`/ready` passes. Don't combine with `docker compose up --scale api=N`.

**`TARGET_RPS_PER_REPLICA=40` is a placeholder, not a measurement.** Calibrate it: `docker compose stop autoscaler`,
run the load test at 1 replica, and put the highest RPS that keeps p95 acceptable (with margin) in `docker-compose.yml`.

## 10. Load testing

```bash
pip install httpx pandas numpy
python loadtest/loadtest.py                                 # 10 / 25 / 50 / 100 / 200 RPS, 30 s each
python loadtest/loadtest.py --levels 10 25 --seconds 15 --hot-users 200   # raise cache hit rate
```

Open-loop (fixed arrival rate, so a slow server can't hide by slowing the client). 90 % `/recommendations` over random
users, 10 % `/events` (`--event-ratio`). Reports per level: achieved RPS, p50/p95/p99, error %, API containers (end/max),
average CPU %, RAM (from the autoscaler's `localhost:9100/status`), and saves a CSV in `loadtest/results/`.
`offered < target` means the load generator itself saturated — run it on another machine for clean numbers.

## Known limitations

* **User static data lives inside the model artifact** (all users' spend vectors, governorate, flags) and Stage-1 Channel D
  does a dense `train_users × dims` matrix product per request. Fine for the 3,000-user sample; at ~1M customers move
  user static features to Redis/PostgreSQL and replace Channel D's brute force with a batch-built neighbour table.
  Training also builds the query table in RAM (~2.3M rows for 10k queries here) — chunk it at larger scale.
* **Train/serve history mismatch.** Training builds each user's profile from *all their other rows* (leave-one-out, as in the
  notebook), which includes interactions that happened **after** the target; serving only knows past events and starts from an
  empty state. Run `python scripts/leakage_check.py --data data --model` on your real data to measure it (on a development
  sample: 69 % of warm training queries contained at least one future row, and the shipped model's NDCG@10 was 0.171 with
  leave-one-out history vs 0.156 with past-only history). A past-only mode exists (`build_query_table(..., history="past")`);
  the default is unchanged. The 30-day snapshot and spend columns are not time-filtered, and evaluation splits by user, not by time.
* The UI's login is a placeholder (any non-empty password); there is no real authentication or user registry.
* The UI layout was verified structurally (it builds, every handler runs, HTML renders) but not visually in a browser.
* Live state starts empty for every user (as in the notebook's Part 3); pre-go-live history is not replayed.
* Deviations from the notebook's serving code, all deliberate: retrieval-channel count, avg/max score and redemption rate are
  computed live (the notebook hard-coded 2.0 / 0.0); an `open`/`purchase` event *adds* to the 30-day intensity (the notebook
  subtracts, because it simulates held-out rows); the "inject the missed positive" step uses channel-count 1, not 0
  (0 can never occur naturally, so the ranker learns "0 ⇒ positive" — a leak); importance is **gain** (the notebook's `feature_importances_` was split-count by default).
* Worker and live state: the API updates Redis synchronously (so the next request sees the event); the worker does the
  durable PostgreSQL write. The worker does not touch live state again — doing so would double count.
* Expiry is judged against `AS_OF_DATE` (default: the real date). Training still uses each interaction's own day for
  `log_days_to_expire`, so with `today` and old offer dates that feature is evaluated outside the range seen in training.
* The device-location capture is browser JavaScript; the API/UI wiring was tested by sending coordinates through the UI's
  API, but the browser permission prompt itself was not exercised in a real browser.
* The autoscaler and Traefik mount `/var/run/docker.sock` (root-equivalent) — acceptable for a demo, not for production.
