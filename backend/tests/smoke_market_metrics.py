from __future__ import annotations

import json
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
    r = client.get("/api/v1/market/metrics", params={"symbol": "MNQ", "timeframe": "1m", "lookback": 200, "mode": "summary"})
    if r.status_code != 200:
        print("FAIL", r.status_code, r.text)
        return 1
    data = r.json()
    if data.get("version") != "market-metrics.v1":
        print("FAIL: unexpected version")
        print(json.dumps(data, indent=2))
        return 1
    if data.get("symbol") != "MNQ" or data.get("timeframe") != "1m":
        print("FAIL: bad echo fields")
        print(json.dumps(data, indent=2))
        return 1
    print("OK", data.get("feed_status"), data.get("confidence"), "notes=", len(data.get("notes") or []))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

