from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))
    os.environ.setdefault("PYTHONPATH", str(repo_root))

    from backend.app import app

    client = TestClient(app)
    r = client.get("/api/v1/assistant/context", params={"botId": "bot-1"})
    if r.status_code != 200:
        print("FAIL", r.status_code, r.text)
        return 1
    data = r.json()
    snap = data.get("snapshot") or {}
    if not snap.get("market"):
        print("FAIL: expected market in snapshot")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

