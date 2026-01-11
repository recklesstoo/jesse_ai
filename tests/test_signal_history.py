import uuid

from fastapi.testclient import TestClient

import backend.app as app_module


def test_signal_history_endpoint():
    client = TestClient(app_module.app)
    bot_id = f"test-bot-{uuid.uuid4().hex}"
    try:
        bars = []
        for i in range(10):
            bars.append(
                {
                    "ts": f"2026-01-01T00:0{i}:00Z",
                    "symbol": "MNQ",
                    "timeframe": "1 Minute",
                    "o": 100,
                    "h": 101,
                    "l": 99,
                    "c": 100,
                    "v": 1000,
                }
            )
        payload = {"botId": bot_id, "mode": "LIVE", "bars": bars}
        res = client.post("/api/v1/bars/batch", json=payload)
        assert res.status_code == 200

        history = client.get(f"/api/v1/ai-signals/{bot_id}/history?limit=5").json()
        assert history["ok"] is True
        assert history["count"] >= 1
    finally:
        app_module.bars_store.pop(bot_id, None)
        app_module.ai_signal_store.pop(bot_id, None)
        app_module.ai_signal_history.pop(bot_id, None)
