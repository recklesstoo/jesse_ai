from __future__ import annotations

import io
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app import app


def main() -> int:
    client = TestClient(app)

    r = client.get("/api/v1/data/days", params={"symbol": "MNQ", "timeframe": "1m"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True

    r2 = client.post("/api/v1/data/clean", json={"dryRun": True, "rules": {"symbol": "MNQ", "timeframe": "1m"}})
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["ok"] is True
    assert body2["dryRun"] is True

    # Optional ingest with tiny CSV (2 rows).
    csv_bytes = b"timestamp,open,high,low,close,volume\n2026-01-14T12:34:56Z,1,2,0.5,1.5,10\n2026-01-14T12:34:57Z,1,2,0.5,1.6,11\n"
    files = {"file": ("tiny.csv", io.BytesIO(csv_bytes), "text/csv")}
    data = {"symbol": "MNQ", "timeframe": "1m", "source": "CSV_INGEST", "is_simulated": "false"}
    r3 = client.post("/api/v1/data/ingest", data=data, files=files)
    assert r3.status_code == 200
    body3 = r3.json()
    assert body3["ok"] is True

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
