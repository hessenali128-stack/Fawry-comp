"""Simple autoscaler for the `api` service using the Docker SDK (no Kubernetes).

Every INTERVAL seconds: read CPU (docker stats), requests/sec and p95 latency (each API's /internal/stats),
then add or remove ONE api container within [MIN_REPLICAS, MAX_REPLICAS], with cooldowns.
New replicas are clones of the compose-created api container (same image/env/labels), so Traefik discovers
them through Docker labels and only routes to them once their healthcheck (/ready) passes.
"""
import json
import logging
import math
import os
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer

import docker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("autoscaler")

E = os.getenv
MIN_REPLICAS, MAX_REPLICAS = int(E("MIN_REPLICAS", "1")), int(E("MAX_REPLICAS", "10"))
UP_COOLDOWN, DOWN_COOLDOWN = float(E("SCALE_UP_COOLDOWN", "30")), float(E("SCALE_DOWN_COOLDOWN", "60"))
INTERVAL = float(E("INTERVAL", "5"))
CPU_UP, CPU_DOWN = float(E("CPU_UP", "70")), float(E("CPU_DOWN", "30"))          # % of each container's CPU limit
P95_UP_MS, P95_DOWN_MS = float(E("P95_UP_MS", "150")), float(E("P95_DOWN_MS", "60"))
# Requests/sec one replica should handle. PLACEHOLDER: calibrate from the load test (README) - not a claim.
TARGET_RPS = float(E("TARGET_RPS_PER_REPLICA", "40"))
SERVICE, PORT = E("SERVICE", "api"), int(E("API_PORT", "8000"))

client = docker.from_env()
me = client.containers.get(os.getenv("HOSTNAME"))
PROJECT = me.labels["com.docker.compose.project"]
FILTER = {"label": [f"com.docker.compose.project={PROJECT}", f"com.docker.compose.service={SERVICE}"]}
status = {"replicas": 0}


def api_containers():
    return [c for c in client.containers.list(filters=FILTER) if c.status == "running"]


def health(c):
    return c.attrs["State"].get("Health", {}).get("Status", "healthy")


def cpu_and_mem(c):
    s = c.stats(stream=False)
    cpu, pre = s["cpu_stats"], s["precpu_stats"]
    d_cpu = cpu["cpu_usage"]["total_usage"] - pre["cpu_usage"]["total_usage"]
    d_sys = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
    ncpu = cpu.get("online_cpus") or len(cpu["cpu_usage"].get("percpu_usage") or [1])
    cores_used = (d_cpu / d_sys) * ncpu if d_sys > 0 else 0.0
    limit = (c.attrs["HostConfig"].get("NanoCpus") or 0) / 1e9 or ncpu
    mem = s["memory_stats"]
    used = mem.get("usage", 0) - mem.get("stats", {}).get("inactive_file", mem.get("stats", {}).get("cache", 0))
    return 100.0 * cores_used / limit, used / 1e6


def app_stats(c):
    ip = next(iter(c.attrs["NetworkSettings"]["Networks"].values()))["IPAddress"]
    with urllib.request.urlopen(f"http://{ip}:{PORT}/internal/stats", timeout=2) as r:
        return json.load(r)


def collect(cs):
    def one(c):
        try:
            cpu, mem = cpu_and_mem(c)
            return cpu, mem, app_stats(c)
        except Exception as e:
            log.warning("metrics failed for %s: %s", c.name, e)
            return None
    with ThreadPoolExecutor(max_workers=max(1, len(cs))) as ex:
        return [r for r in ex.map(one, cs) if r]


def scale_up(cs):
    tpl = next((c for c in cs if c.labels.get("autoscaler.managed") != "true"), cs[0])
    a, hc = tpl.attrs, tpl.attrs["HostConfig"]
    n = max([int(c.labels.get("com.docker.compose.container-number", 1)) for c in cs] + [0]) + 1
    labels = {**tpl.labels, "com.docker.compose.container-number": str(n), "autoscaler.managed": "true"}
    net = next(iter(a["NetworkSettings"]["Networks"]))
    new = client.containers.run(
        a["Config"]["Image"], detach=True, name=f"{PROJECT}-{SERVICE}-{n}-as{int(time.time())}", labels=labels,
        environment=a["Config"]["Env"], network=net, volumes=hc.get("Binds") or None,
        nano_cpus=hc.get("NanoCpus") or None, mem_limit=hc.get("Memory") or None,
        restart_policy={"Name": "unless-stopped"}, command=a["Config"].get("Cmd"))
    log.info("SCALE UP -> started %s", new.name)


def scale_down(cs):
    managed = [c for c in cs if c.labels.get("autoscaler.managed") == "true"]
    victim = max(managed or cs, key=lambda c: c.attrs["Created"])
    log.info("SCALE DOWN -> stopping %s", victim.name)
    victim.stop(timeout=15)
    victim.remove()


def decide(n, ready, cpu, p95, per_replica_rps, now, last_change):
    """Pure scaling decision: returns 'up', 'down' or '-'. One step at a time, with cooldowns."""
    if n < MIN_REPLICAS:
        return "up"
    if n > MAX_REPLICAS:
        return "down"
    up = cpu > CPU_UP or p95 > P95_UP_MS or per_replica_rps > TARGET_RPS
    down = cpu < CPU_DOWN and p95 < P95_DOWN_MS and per_replica_rps < 0.5 * TARGET_RPS
    if up and n < MAX_REPLICAS and now - last_change >= UP_COOLDOWN and ready >= n:  # not while one is booting
        return "up"
    if down and n > MIN_REPLICAS and now - last_change >= DOWN_COOLDOWN:
        return "down"
    return "-"


def loop():
    last_change = 0.0
    while True:
        try:
            cs = api_containers()
            n = len(cs)
            ready = [c for c in cs if health(c) == "healthy"]
            m = collect(ready)
            cpu = sum(x[0] for x in m) / len(m) if m else 0.0
            rps = sum(x[2]["rps"] for x in m)
            p95 = max((x[2]["p95"] for x in m), default=0.0)
            mem = sum(x[1] for x in m)
            per = rps / max(n, 1)
            status.update(replicas=n, ready=len(ready), cpu_avg=round(cpu, 1), rps=round(rps, 1),
                          p95_ms=round(p95, 1), mem_mb_total=round(mem, 1), ts=time.time())

            now = time.time()
            action = decide(n, len(ready), cpu, p95, per, now, last_change) if cs else "-"
            if action == "up":
                scale_up(cs)
                last_change = now
            elif action == "down":
                scale_down(cs)
                last_change = now
            log.info("replicas=%d(ready %d) rps=%.1f (%.1f/replica) p95=%.1fms cpu=%.0f%% -> %s",
                     n, len(ready), rps, per, p95, cpu, action)
        except Exception:
            log.exception("autoscaler tick failed")
        time.sleep(INTERVAL)


class Status(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(status).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", 9000), Status).serve_forever(), daemon=True).start()
    log.info("autoscaler up: project=%s min=%d max=%d target_rps/replica=%.0f", PROJECT, MIN_REPLICAS, MAX_REPLICAS, TARGET_RPS)
    loop()
