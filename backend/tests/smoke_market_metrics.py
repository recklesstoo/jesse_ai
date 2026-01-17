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
    for tf, expected_bar_stale in (("1m", 90.0), ("5m", 450.0)):
        r = client.get("/api/v1/market/metrics", params={"symbol": "MNQ", "timeframe": tf, "lookback": 200, "mode": "summary"})
        if r.status_code != 200:
            print("FAIL", tf, r.status_code, r.text)
            return 1
        data = r.json()
        if data.get("version") != "market-metrics.v1":
            print("FAIL: unexpected version")
            print(json.dumps(data, indent=2))
            return 1
        if data.get("symbol") != "MNQ" or data.get("timeframe") != tf:
            print("FAIL: bad echo fields")
            print(json.dumps(data, indent=2))
            return 1
        for k in ("source", "feed_status", "confidence", "server_ts_utc", "ws_stale_sec", "bar_stale_sec", "ws_age_sec", "bar_age_sec"):
            if k not in data:
                print(f"FAIL: missing top-level field {k}")
                print(json.dumps(data, indent=2))
                return 1
        if data.get("feed_status") not in {"LIVE", "STALE", "NO_LIVE"}:
            print("FAIL: unexpected feed_status")
            print(json.dumps(data, indent=2))
            return 1
        if data.get("ws_stale_sec") != 10.0:
            print("FAIL: ws_stale_sec must be 10.0")
            print(json.dumps(data, indent=2))
            return 1
        if float(data.get("bar_stale_sec")) != float(expected_bar_stale):
            print(f"FAIL: bar_stale_sec must be {expected_bar_stale} for {tf}")
            print(json.dumps(data, indent=2))
            return 1
        if data.get("feed_status") in {"STALE", "NO_LIVE"}:
            notes = data.get("notes") or []
            if not any(isinstance(n, str) and "freshness:" in n and "ws_age_sec=" in n and "bar_age_sec=" in n for n in notes):
                print("FAIL: stale/no_live must include freshness note with numbers")
                print(json.dumps(data, indent=2))
                return 1
        print("OK", tf, data.get("feed_status"), data.get("confidence"), "notes=", len(data.get("notes") or []))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
