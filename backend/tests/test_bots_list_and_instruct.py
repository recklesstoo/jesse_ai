from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import Base, SessionLocal, engine
from backend.models import BotSpec, DataBar


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_list_bots_and_instruct_endpoint() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    symbol = "ZZZ"
    timeframe = "1m"
    prefix = "itest-wy"
    try:
        # Cleanup from prior runs.
        db.query(DataBar).filter(DataBar.symbol == symbol, DataBar.timeframe == timeframe).delete(synchronize_session=False)
        db.query(BotSpec).filter(BotSpec.bot_id.like(f"{prefix}-%")).delete(synchronize_session=False)
        db.commit()

        # Seed some 1m bars for one day.
        start = datetime(2024, 1, 2, tzinfo=timezone.utc)
        rows = []
        price = 100.0
        for i in range(260):
            ts = start + timedelta(minutes=i)
            price += 0.20 if (i % 10) < 6 else -0.15
            rows.append(
                DataBar(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts_utc=ts,
                    open=price - 0.05,
                    high=price + 0.10,
                    low=price - 0.10,
                    close=price,
                    volume=100 + (i % 25),
                    source="IMPORT",
                    is_simulated=False,
                )
            )
        db.bulk_save_objects(rows)
        db.commit()

        client = TestClient(app)

        # Instruct bots and backtest them using seeded data.
        res = client.post(
            "/api/v1/bots/instruct",
            json={
                "symbol": symbol,
                "timeframe": timeframe,
                "startDay": "2024-01-02",
                "endDay": "2024-01-02",
                "botIdPrefix": prefix,
                "maxBots": 8,
                "create": True,
                "backtest": True,
            },
        )
        assert res.status_code == 200, res.text
        data = res.json()
        assert data.get("ok") is True
        bots = data.get("bots") or []
        assert len(bots) == 8
        for item in bots:
            assert str(item.get("botId") or "").startswith(prefix + "-")
            assert isinstance(item.get("spec"), dict)
            metrics = item.get("metrics")
            assert isinstance(metrics, dict)
            assert "netPnL" in metrics
            assert "trades" in metrics

        # List bots should include them.
        listed = client.get("/api/v1/bots/specs").json()
        assert listed.get("ok") is True
        ids = [b.get("botId") for b in (listed.get("bots") or [])]
        for i in range(1, 9):
            assert f"{prefix}-{i:02d}" in ids
    finally:
        try:
            db.query(DataBar).filter(DataBar.symbol == symbol, DataBar.timeframe == timeframe).delete(synchronize_session=False)
            db.query(BotSpec).filter(BotSpec.bot_id.like(f"{prefix}-%")).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()
