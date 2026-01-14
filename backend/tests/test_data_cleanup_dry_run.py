from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))
os.environ.setdefault("PYTHONPATH", str(repo_root))

from backend.app import app
from backend.database import SessionLocal
from backend.models import DataBar


def test_data_cleanup_sim_only_requires_confirm() -> None:
    client = TestClient(app)
    db = SessionLocal()
    ts = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        # Insert one simulated bar.
        try:
            row = DataBar(
                symbol="MNQ",
                timeframe="1m",
                ts_utc=ts,
                open=1.0,
                high=2.0,
                low=0.5,
                close=1.5,
                volume=1,
                source="SIM_TEST",
                is_simulated=True,
                ingested_at_utc=ts,
            )
            db.add(row)
            db.commit()
        except Exception as exc:
            # When the real backend server is running against the same sqlite file,
            # SQLite can be locked; skip instead of failing the suite.
            if "database is locked" in str(exc).lower():
                import pytest

                pytest.skip("sqlite database is locked (backend server likely running)")
            raise

        before = int(db.query(DataBar).filter(DataBar.is_simulated.is_(True)).count())
        assert before >= 1

        # Dry run should not delete.
        try:
            r = client.post("/api/v1/data/cleanup?mode=sim_only", json={"confirm": False, "rules": {"symbol": "MNQ", "timeframe": "1m"}})
            assert r.status_code == 200
            data = r.json()
            assert data.get("dryRun") is True
            mid = int(db.query(DataBar).filter(DataBar.is_simulated.is_(True)).count())
            assert mid == before

            # Apply should delete.
            r2 = client.post("/api/v1/data/cleanup?mode=sim_only", json={"confirm": True, "rules": {"symbol": "MNQ", "timeframe": "1m"}})
            assert r2.status_code == 200
            data2 = r2.json()
            assert data2.get("dryRun") is False
        except Exception as exc:
            if "database is locked" in str(exc).lower():
                import pytest

                pytest.skip("sqlite database is locked (backend server likely running)")
            raise
    finally:
        # Ensure cleanup for this test timestamp.
        try:
            db.query(DataBar).filter(DataBar.ts_utc == ts, DataBar.symbol == "MNQ", DataBar.timeframe == "1m").delete(synchronize_session=False)
            db.commit()
        except Exception:
            db.rollback()
        db.close()
