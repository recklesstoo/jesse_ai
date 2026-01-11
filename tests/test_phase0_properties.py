import asyncio
import uuid

from fastapi.testclient import TestClient
from hypothesis import given, strategies as st

import backend.app as app_module


class RecordingWebSocket:
    def __init__(self) -> None:
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


class FailingWebSocket:
    async def send_json(self, message):
        raise RuntimeError("send failed")


def run(coro):
    return asyncio.run(coro)


json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1_000_000, max_value=1_000_000),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.text(min_size=1, max_size=16, alphabet=st.characters(min_codepoint=32, max_codepoint=126)),
)


@given(message=st.dictionaries(keys=st.text(min_size=1, max_size=8), values=json_scalars, max_size=6))
def test_ws_broadcast_delivers_to_live_clients(message):
    original = list(app_module.live_ws_connections)
    try:
        ws1 = RecordingWebSocket()
        ws2 = RecordingWebSocket()
        app_module.live_ws_connections = [ws1, ws2]
        run(app_module._broadcast_live(message))
        assert ws1.messages and ws1.messages[-1] == message
        assert ws2.messages and ws2.messages[-1] == message
    finally:
        app_module.live_ws_connections = original


@given(message=st.dictionaries(keys=st.text(min_size=1, max_size=8), values=json_scalars, max_size=6))
def test_ws_broadcast_recovers_after_disconnect(message):
    original = list(app_module.live_ws_connections)
    try:
        ws_ok = RecordingWebSocket()
        ws_dead = FailingWebSocket()
        app_module.live_ws_connections = [ws_ok, ws_dead]
        run(app_module._broadcast_live(message))
        assert ws_dead not in app_module.live_ws_connections

        ws_ok2 = RecordingWebSocket()
        app_module.live_ws_connections.append(ws_ok2)
        run(app_module._broadcast_live(message))
        assert ws_ok2.messages and ws_ok2.messages[-1] == message
    finally:
        app_module.live_ws_connections = original


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


@given(bars=st.lists(bar_strategy, min_size=1, max_size=5))
def test_bar_data_flow_persists_last_bar(bars):
    client = TestClient(app_module.app)
    bot_id = f"test-bot-{uuid.uuid4().hex}"
    try:
        payload = {"botId": bot_id, "mode": "LIVE", "bars": bars}
        resp = client.post("/api/v1/bars/batch", json=payload)
        assert resp.status_code == 200
        assert app_module.bars_store[bot_id]
        assert app_module.bars_store[bot_id][-1]["c"] == bars[-1]["c"]
    finally:
        app_module.bars_store.pop(bot_id, None)
        app_module.bots.pop(bot_id, None)


@given(bar=bar_strategy)
def test_bar_update_structure_matches_bar(bar):
    msg = app_module._build_bar_update("bot-1", bar)
    assert msg["type"] == "bar_update"
    data = msg["data"]
    assert data["price"] == bar["c"]
    assert data["timestamp"] == bar["ts"]
    assert data["ohlc"]["open"] == bar["o"]
    assert data["ohlc"]["high"] == bar["h"]
    assert data["ohlc"]["low"] == bar["l"]
    assert data["ohlc"]["close"] == bar["c"]


@given(bar=bar_strategy)
def test_price_display_uses_latest_close(bar):
    msg = app_module._build_bar_update("bot-1", bar)
    assert msg["data"]["price"] == bar["c"]


def test_bot_status_payload_includes_last_seen():
    bot_id = f"test-bot-{uuid.uuid4().hex}"
    try:
        app_module.update_bot_state(bot_id, mode="LIVE")
        msg = app_module._build_bot_status(bot_id)
        assert msg["data"]["botId"] == bot_id
        assert "last_seen_utc" in msg["data"]["status"]
    finally:
        app_module.bots.pop(bot_id, None)


@given(bar=bar_strategy)
def test_bar_ingest_endpoint_reliable(bar):
    client = TestClient(app_module.app)
    bot_id = f"test-bot-{uuid.uuid4().hex}"
    try:
        payload = {"botId": bot_id, "mode": "LIVE", "bars": [bar]}
        resp = client.post("/api/v1/bars/batch", json=payload)
        assert resp.status_code == 200
        assert resp.json()["received"] == 1
    finally:
        app_module.bars_store.pop(bot_id, None)
        app_module.bots.pop(bot_id, None)
