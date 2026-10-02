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


def recommendations(user_id: str, top_n: int = 10, lat=None, lon=None, area=None):
    """-> (data | None, error | None). `data` adds `served_by` (the API replica that answered).
    Location is sent only for this request; the area (if chosen) wins over lat/lon."""
    body = {"user_id": user_id, "top_n": top_n}
    if area:
        body["area"] = area
    elif lat is not None and lon is not None:
        body.update(lat=float(lat), lon=float(lon))
    try:
        r = _client.post("/recommendations", json=body)
        r.raise_for_status()
        data = r.json()
        data["served_by"] = r.headers.get("x-served-by", "")
        return data, None
    except httpx.HTTPError as e:
        return None, _err(e)


def areas():
    """Areas (governorates) that exist in the dataset, for the manual selector."""
    try:
        r = _client.get("/areas")
        r.raise_for_status()
        return r.json().get("areas", [])
    except httpx.HTTPError:
        return []


def send_event(user_id: str, offer_id: str, event: str):
    """-> (ok, error | None)"""
    try:
        _client.post("/events", json={"user_id": user_id, "offer_id": offer_id, "event": event}).raise_for_status()
        return True, None
    except httpx.HTTPError as e:
        return False, _err(e)
