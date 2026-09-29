"""Thin client for the recommendation backend. Every call goes through Traefik, so the load balancer is used."""
import os

import httpx

API_BASE = os.getenv("API_BASE", "http://localhost:8000")
_client = httpx.Client(base_url=API_BASE, timeout=float(os.getenv("API_TIMEOUT", "8")))


def _err(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        if e.response.status_code in (404, 502, 503, 504):
            return "Recommendation service is not ready yet (the first model may still be training)."
        return f"Backend error {e.response.status_code}."
    return "Cannot reach the recommendation backend."


def recommendations(user_id: str, top_n: int = 10):
    """-> (data | None, error | None). `data` adds `served_by` (the API replica that answered)."""
    try:
        r = _client.post("/recommendations", json={"user_id": user_id, "top_n": top_n})
        r.raise_for_status()
        data = r.json()
        data["served_by"] = r.headers.get("x-served-by", "")
        return data, None
    except httpx.HTTPError as e:
        return None, _err(e)


def send_event(user_id: str, offer_id: str, event: str):
    """-> (ok, error | None)"""
    try:
        _client.post("/events", json={"user_id": user_id, "offer_id": offer_id, "event": event}).raise_for_status()
        return True, None
    except httpx.HTTPError as e:
        return False, _err(e)
