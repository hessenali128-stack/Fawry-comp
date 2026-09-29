"""models/vN/ + models/current.json  (atomic publish, rollback pointer)."""
import json
import os
import re
from pathlib import Path

from common.config import MODELS_DIR


def root() -> Path:
    p = Path(MODELS_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def versions() -> list:
    vs = [d.name for d in root().iterdir() if d.is_dir() and re.fullmatch(r"v\d+", d.name)]
    return sorted(vs, key=lambda v: int(v[1:]))


def next_version() -> str:
    vs = versions()
    return f"v{int(vs[-1][1:]) + 1}" if vs else "v1"


def read_current() -> dict | None:
    f = root() / "current.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except json.JSONDecodeError:
        return None


def publish(version: str):
    """Point production at `version`, remembering the previous one for rollback. Atomic rename."""
    cur = read_current()
    doc = {"version": version, "previous": cur["version"] if cur and cur["version"] != version else
           (cur or {}).get("previous")}
    tmp = root() / "current.json.tmp"
    tmp.write_text(json.dumps(doc, indent=2))
    os.replace(tmp, root() / "current.json")
    return doc
