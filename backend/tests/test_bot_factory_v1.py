from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import Base, SessionLocal, engine
from backend.models import BacktestRun, BotSpec, DataBar, OptimizeRun


def _wait_for_status(client: TestClient, path: str, *, timeout_s: float = 10.0) -> dict:
    deadline = time.time() + timeout_s
    last = {}
    while time.time() < deadline:
        last = client.get(path).json()
        if last.get("status") in {"DONE", "ERROR"}:
            return last
        time.sleep(0.05)
    return last


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_bot_factory_create_backtest_and_optimize() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        bot_id = "bf-test"
        symbol = "ZZZ"
        timeframe = "1m"

        # Cleanup any previous leftovers (idempotent tests).
        db.query(DataBar).filter(DataBar.symbol == symbol, DataBar.timeframe == timeframe).delete(synchronize_session=False)
        db.query(BotSpec).filter(BotSpec.bot_id == bot_id).delete(synchronize_session=False)
        db.query(BacktestRun).filter(BacktestRun.bot_id == bot_id).delete(synchronize_session=False)
        db.query(OptimizeRun).filter(OptimizeRun.bot_id == bot_id).delete(synchronize_session=False)
        db.commit()

        # Insert deterministic 1m bars (enough to warm ATR).
        start = datetime(2024, 1, 2, tzinfo=timezone.utc)
        rows = []
        price = 100.0
        for i in range(240):
            ts = start + timedelta(minutes=i)
            price += 0.15 if (i % 6) < 3 else -0.10
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

        client = TestClient(app)

        spec = {
            "version": "bot-spec.v1",
            "botId": bot_id,
            "name": "BotFactoryTest",
            "symbol": symbol,
            "timeframe": timeframe,
            "session": {"mode": "BOTH", "tz": "UTC", "start_hhmm": 0, "end_hhmm": 0},
            "risk": {"qty": 1, "stop_loss_ticks": 10, "take_profit_ticks": 12, "max_loss_usd": 1200.0},
            "gates": {"min_confidence": 0.10, "min_atr_ticks": 0, "cooldown_bars": 0, "max_trades_per_session": 999},
            "setup": {"kind": "trend_pullback_bos", "ema_trend_len": 50, "ema_pullback_len": 10, "bos_lookback": 6},
            "tags": ["test"],
        }

        r = client.post("/api/v1/bots", json=spec)
        assert r.status_code == 200
        assert r.json().get("ok") is True

        # Backtest run
        run = client.post("/api/v1/backtest/run", json={"botId": bot_id, "startDay": "2024-01-02", "endDay": "2024-01-02"}).json()
        assert run.get("ok") is True
        run_id = run.get("runId")
        assert isinstance(run_id, str) and run_id

        res = _wait_for_status(client, f"/api/v1/backtest/results/{run_id}", timeout_s=10.0)
        assert res.get("ok") is True
        assert res.get("status") == "DONE", res
        metrics = ((res.get("metrics") or {}).get("metrics") or {})
        assert "netPnL" in metrics
        assert "maxDD" in metrics
        assert "trades" in metrics

        # Optimize run (<=50 variants)
        opt = client.post(
            "/api/v1/optimize/run",
            json={
                "botId": bot_id,
                "startDay": "2024-01-02",
                "endDay": "2024-01-02",
                "grid": {"risk.stop_loss_ticks": [8, 10], "risk.take_profit_ticks": [10, 12]},
            },
        ).json()
        assert opt.get("ok") is True
        opt_id = opt.get("runId")
        assert isinstance(opt_id, str) and opt_id

        opt_res = _wait_for_status(client, f"/api/v1/optimize/results/{opt_id}", timeout_s=10.0)
        assert opt_res.get("ok") is True
        assert opt_res.get("status") == "DONE", opt_res
        results = ((opt_res.get("results") or {}).get("results") or [])
        assert len(results) == 4
        for item in results:
            assert "metrics" in item
            assert "params" in item

        # Cap enforcement (>50 variants)
        bad = client.post(
            "/api/v1/optimize/run",
            json={
                "botId": bot_id,
                "startDay": "2024-01-02",
                "endDay": "2024-01-02",
                "grid": {"risk.stop_loss_ticks": list(range(1, 7)), "risk.take_profit_ticks": list(range(1, 11))},
            },
        )
        assert bad.status_code == 400
    finally:
        try:
            db.query(DataBar).filter(DataBar.symbol == symbol, DataBar.timeframe == timeframe).delete(synchronize_session=False)
            db.query(BotSpec).filter(BotSpec.bot_id == bot_id).delete(synchronize_session=False)
            db.query(BacktestRun).filter(BacktestRun.bot_id == bot_id).delete(synchronize_session=False)
            db.query(OptimizeRun).filter(OptimizeRun.bot_id == bot_id).delete(synchronize_session=False)
            db.commit()
        finally:
            db.close()

