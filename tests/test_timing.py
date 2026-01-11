import os
import time
import uuid

from fastapi.testclient import TestClient

import backend.app as app_module


def test_timing_health_under_budget():
    client = TestClient(app_module.app)
    budget_ms = int(os.getenv("PERF_HEALTH_MS", "200"))
    start = time.perf_counter()
    res = client.get("/api/v1/health")
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert res.status_code == 200
    assert elapsed_ms <= budget_ms


def test_timing_commands_under_budget():
    client = TestClient(app_module.app)
    bot_id = f"perf-{uuid.uuid4().hex}"
    budget_ms = int(os.getenv("PERF_COMMAND_MS", "200"))
    try:
        app_module.update_bot_state(bot_id, mode="LIVE")
        start = time.perf_counter()
        res = client.get(f"/api/v1/commands/{bot_id}?wait_ms=0")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert res.status_code == 200
        assert elapsed_ms <= budget_ms
    finally:
        app_module._queues.pop(bot_id, None)
        app_module.bots.pop(bot_id, None)


def test_timing_bar_ingest_under_budget():
    client = TestClient(app_module.app)
    bot_id = f"perf-{uuid.uuid4().hex}"
    budget_ms = int(os.getenv("PERF_BAR_MS", "200"))
    try:
        payload = {
            "botId": bot_id,
            "mode": "LIVE",
            "bars": [
                {
                    "ts": "2026-01-01T00:00:00.000Z",
                    "symbol": "MNQ",
                    "timeframe": "1 Minute",
                    "o": 100.0,
                    "h": 101.0,
                    "l": 99.5,
                    "c": 100.5,
                    "v": 1234,
                }
            ],
        }
        start = time.perf_counter()
        res = client.post("/api/v1/bars/batch", json=payload)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert res.status_code == 200
        assert elapsed_ms <= budget_ms
    finally:
        app_module.bars_store.pop(bot_id, None)
        app_module.bots.pop(bot_id, None)
