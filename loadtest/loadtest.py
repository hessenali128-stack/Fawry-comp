"""Open-loop load test: 10/25/50/100/200 RPS against Traefik. Prints + saves RPS, p50/p95/p99, errors,
CPU, RAM and number of API containers per level (from the autoscaler's /status).

  python loadtest/loadtest.py                       # autoscaler ON  (what the system does under load)
  docker compose stop autoscaler && python loadtest/loadtest.py --levels 10 25 50 --settle 5
                                                    # fixed 1 replica -> measures ONE container's capacity
"""
import argparse
import asyncio
import csv
import json
import random
import time
import urllib.request
from pathlib import Path

import httpx
import numpy as np


def read_ids(data_dir):
    import pandas as pd
    u = pd.read_csv(Path(data_dir) / "user_features.csv", usecols=["user_id"]).user_id.tolist()
    o = pd.read_csv(Path(data_dir) / "offer_features.csv", usecols=["offer_id"]).offer_id.tolist()
    return u, o


def status(url):
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return json.load(r)
    except Exception:
        return {}


async def run_level(client, base, rps, seconds, users, offers, event_ratio, hot):
    lat, errs, kinds = [], 0, {"rec": 0, "evt": 0}
    pool = users[:hot] if hot else users
    samples, stop = [], asyncio.Event()

    async def sampler(url):
        while not stop.is_set():
            s = await asyncio.get_running_loop().run_in_executor(None, status, url)
            if s:
                samples.append(s)
            await asyncio.sleep(2)

    async def one():
        nonlocal errs
        is_evt = random.random() < event_ratio
        t0 = time.perf_counter()
        try:
            if is_evt:
                r = await client.post(f"{base}/events", json={"user_id": random.choice(pool),
                                      "offer_id": random.choice(offers), "event": random.choice(["click", "open", "purchase"])})
            else:
                r = await client.post(f"{base}/recommendations", json={"user_id": random.choice(pool), "top_n": 10})
            ok = r.status_code < 400
        except Exception:
            ok = False
        lat.append((time.perf_counter() - t0) * 1000)
        kinds["evt" if is_evt else "rec"] += 1
        errs += 0 if ok else 1

    tasks = []
    st = asyncio.create_task(sampler(f"{base.replace(':8000', ':9100')}/status"))
    start = time.perf_counter()
    n = int(rps * seconds)
    for i in range(n):  # fixed arrival schedule: request i is due at start + i/rps
        due = start + i / rps
        delay = due - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        tasks.append(asyncio.create_task(one()))
    offered = n / (time.perf_counter() - start)
    await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - start
    stop.set(); await st
    a = np.array(lat)
    cont = [s.get("replicas", 0) for s in samples]
    return {"target_rps": rps, "offered_rps": round(offered, 1), "achieved_rps": round((len(a) - errs) / elapsed, 1),
            "p50_ms": round(np.percentile(a, 50), 1), "p95_ms": round(np.percentile(a, 95), 1),
            "p99_ms": round(np.percentile(a, 99), 1), "errors": errs, "error_pct": round(100 * errs / len(a), 2),
            "containers_end": cont[-1] if cont else "n/a", "containers_max": max(cont) if cont else "n/a",
            "cpu_avg_pct": round(np.mean([s.get("cpu_avg", 0) for s in samples]), 1) if samples else "n/a",
            "ram_mb_total": round(max([s.get("mem_mb_total", 0) for s in samples]), 0) if samples else "n/a"}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--levels", type=int, nargs="+", default=[10, 25, 50, 100, 200])
    ap.add_argument("--seconds", type=int, default=30, help="duration of each level")
    ap.add_argument("--settle", type=int, default=10, help="pause between levels")
    ap.add_argument("--event-ratio", type=float, default=0.1, help="share of requests that are POST /events")
    ap.add_argument("--hot-users", type=int, default=0, help="restrict to N users (raises cache hit rate); 0=all")
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    users, offers = read_ids(a.data)
    limits = httpx.Limits(max_connections=1000, max_keepalive_connections=200)
    async with httpx.AsyncClient(limits=limits, timeout=30) as client:
        for _ in range(20):  # wait until the stack answers
            try:
                if (await client.get(f"{a.base}/ready")).status_code == 200:
                    break
            except Exception:
                pass
            await asyncio.sleep(2)
        rows = []
        print(f"{'target':>6} {'offered':>8} {'RPS':>7} {'p50':>7} {'p95':>7} {'p99':>8} {'err%':>6} {'cont':>5} {'max':>4} {'cpu%':>6} {'RAM MB':>7}")
        for rps in a.levels:
            r = await run_level(client, a.base, rps, a.seconds, users, offers, a.event_ratio, a.hot_users)
            rows.append(r)
            print(f"{r['target_rps']:>6} {r['offered_rps']:>8} {r['achieved_rps']:>7} {r['p50_ms']:>7} {r['p95_ms']:>7} "
                  f"{r['p99_ms']:>8} {r['error_pct']:>6} {r['containers_end']:>5} {r['containers_max']:>4} "
                  f"{r['cpu_avg_pct']:>6} {r['ram_mb_total']:>7}")
            await asyncio.sleep(a.settle)
    out = Path("loadtest/results"); out.mkdir(parents=True, exist_ok=True)
    f = out / f"loadtest_{int(time.time())}.csv"
    with open(f, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(f"\nsaved {f}\nNote: run the load generator on a different machine than the stack for clean numbers; "
          f"'offered' < 'target' means the generator itself was saturated.")


if __name__ == "__main__":
    asyncio.run(main())
