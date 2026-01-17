from __future__ import annotations

import os
import sys
import time
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))
    os.environ.setdefault("PYTHONPATH", str(repo_root))

    from backend.app import app
    from backend.database import Base, SessionLocal, engine
    from backend.models import DataBar, ModelRun

    client = TestClient(app)

    Base.metadata.create_all(bind=engine)

    bot_id = "smoke-bot"
    symbol = "ZZZ_SMOKE"
    timeframe = "1m"

    with tempfile.TemporaryDirectory(prefix="wyckoff_models_") as models_dir:
        os.environ["WYCKOFF_MODELS_DIR"] = models_dir

        db = SessionLocal()
        try:
            db.query(DataBar).filter(DataBar.symbol == symbol, DataBar.timeframe == timeframe).delete(synchronize_session=False)
            db.query(ModelRun).filter(ModelRun.bot_id == bot_id, ModelRun.symbol == symbol, ModelRun.timeframe == timeframe).delete(
                synchronize_session=False
            )
            db.commit()

            # Insert deterministic bars: 10,050 rows (guardrail requires >=10k).
            start = datetime(2024, 1, 1, tzinfo=timezone.utc)
            rows = []
            price = 100.0
            for i in range(10_050):
                ts = start + timedelta(minutes=i)
                price += 0.2 if (i % 4) < 2 else -0.2
                rows.append(
                    DataBar(
                        symbol=symbol,
                        timeframe=timeframe,
                        ts_utc=ts,
                        open=price - 0.05,
                        high=price + 0.10,
                        low=price - 0.10,
                        close=price,
                        volume=100 + (i % 10),
                        source="IMPORT",
                        is_simulated=False,
                    )
                )
            db.bulk_save_objects(rows)
            db.commit()

            payload = {"botId": bot_id, "symbol": symbol, "timeframes": [timeframe], "lookback_days": 3650, "config": {}}
            r = client.post("/api/v1/bots/train", json=payload)
            if r.status_code != 200:
                print("FAIL train", r.status_code, r.text)
                return 1
            data = r.json()
            run_ids = data.get("run_ids") or []
            if not run_ids:
                print("FAIL: no run_ids")
                print(data)
                return 1

            run_id = run_ids[0]
            deadline = time.time() + 120
            last = None
            while time.time() < deadline:
                s = client.get("/api/v1/bots/train/status", params={"botId": bot_id}).json()
                runs = s.get("runs") or []
                last = next((x for x in runs if x.get("id") == run_id), None)
                if last and last.get("status") in {"DONE", "ERROR", "REFUSED"}:
                    break
                time.sleep(2)

            if not last:
                print("FAIL: did not find run_id in status")
                print(s)
                return 1
            if last.get("status") != "DONE":
                print("FAIL: training not DONE. status=", last.get("status"), "error=", last.get("error"))
                return 1
            artifact = last.get("artifact_path")
            if not artifact or not Path(artifact).exists():
                print("FAIL: artifact_path missing/does not exist:", artifact)
                return 1
            if not (Path(artifact) / "model.pkl").exists():
                print("FAIL: model.pkl missing in", artifact)
                return 1

            print("OK", run_id, "artifact=", artifact)
            return 0
        finally:
            try:
                db.query(DataBar).filter(DataBar.symbol == symbol, DataBar.timeframe == timeframe).delete(synchronize_session=False)
                db.query(ModelRun).filter(ModelRun.bot_id == bot_id, ModelRun.symbol == symbol, ModelRun.timeframe == timeframe).delete(
                    synchronize_session=False
                )
                db.commit()
            finally:
                db.close()


if __name__ == "__main__":
    raise SystemExit(main())
