"""Point production back at a previous version. The API hot-swaps within a few seconds.
  python scripts/rollback.py          -> the `previous` version in models/current.json
  python scripts/rollback.py v2       -> a specific version"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import registry  # noqa: E402

cur = registry.read_current() or {}
target = sys.argv[1] if len(sys.argv) > 1 else cur.get("previous")
if not target or target not in registry.versions():
    sys.exit(f"nothing to roll back to (requested={target}, available={registry.versions()})")
meta = registry.root() / target / "metadata.json"
if '"status": "ready"' not in meta.read_text():
    sys.exit(f"{target} was rejected by validation - refusing to publish it")
print(registry.publish(target))
