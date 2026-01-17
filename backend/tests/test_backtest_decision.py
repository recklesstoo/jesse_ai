from __future__ import annotations

from fastapi.testclient import TestClient


def test_backtest_decision_default_hold() -> None:
    from backend.app import app

    client = TestClient(app)
    payload = {
        "botId": "bot-1",
        "symbol": "MNQ",
        "timeframe": "1m",
        "bar": {"ts": "2026-01-01T00:00:00Z", "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 10},
        "position_state": {"marketPosition": "Flat", "qty": 0},
    }
    r = client.post("/api/v1/backtest/decision", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["action"] == "HOLD"
    assert "reason" in data

