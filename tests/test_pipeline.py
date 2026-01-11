import uuid

from fastapi.testclient import TestClient
from hypothesis import given, strategies as st

import backend.app as app_module


def test_end_to_end_flow_pipeline():
    client = TestClient(app_module.app)
    bot_id = f"test-bot-{uuid.uuid4().hex}"
    try:
        bar_payload = {
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
        res_bar = client.post("/api/v1/bars/batch", json=bar_payload)
        assert res_bar.status_code == 200
        assert app_module.bars_store[bot_id]

        res_cmd = client.post(f"/api/v1/commands/{bot_id}", json={"action": "BUY", "qty": 1})
        assert res_cmd.status_code == 200
        cmd_id = res_cmd.json()["queued"]["id"]

        res_ack = client.post(
            f"/api/v1/commands/{bot_id}/ack",
            json={"id": cmd_id, "status": "SENT"},
        )
        assert res_ack.status_code == 200

        res_log = client.get(f"/api/v1/commands/{bot_id}/log?limit=50")
        assert res_log.status_code == 200
        events = [row["event"] for row in res_log.json()["log"]]
        assert "ACK_SENT" in events
    finally:
        app_module._queues.pop(bot_id, None)
        app_module.cmd_log.pop(bot_id, None)
        app_module.cmd_index.pop(bot_id, None)
        app_module.bots.pop(bot_id, None)
        app_module.bars_store.pop(bot_id, None)


bar_strategy = st.fixed_dictionaries(
    {
        "ts": st.text(min_size=10, max_size=32),
        "symbol": st.text(min_size=1, max_size=8),
        "timeframe": st.text(min_size=1, max_size=16),
        "o": st.floats(allow_nan=False, allow_infinity=False, width=32),
        "h": st.floats(allow_nan=False, allow_infinity=False, width=32),
        "l": st.floats(allow_nan=False, allow_infinity=False, width=32),
        "c": st.floats(allow_nan=False, allow_infinity=False, width=32),
        "v": st.integers(min_value=0, max_value=1_000_000),
    }
)


@given(bar=bar_strategy)
def test_bar_round_trip_serialization(bar):
    client = TestClient(app_module.app)
    bot_id = f"test-bot-{uuid.uuid4().hex}"
    try:
        payload = {"botId": bot_id, "mode": "LIVE", "bars": [bar]}
        res = client.post("/api/v1/bars/batch", json=payload)
        assert res.status_code == 200
        stored = app_module.bars_store[bot_id][-1]
        assert stored["ts"] == bar["ts"]
        assert stored["symbol"] == bar["symbol"]
        assert stored["timeframe"] == bar["timeframe"]
        assert stored["o"] == bar["o"]
        assert stored["h"] == bar["h"]
        assert stored["l"] == bar["l"]
        assert stored["c"] == bar["c"]
        assert stored["v"] == bar["v"]
    finally:
        app_module.bars_store.pop(bot_id, None)
        app_module.bots.pop(bot_id, None)
