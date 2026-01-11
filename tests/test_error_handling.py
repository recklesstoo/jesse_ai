import asyncio

from hypothesis import given, strategies as st

import backend.app as app_module


class FailingWebSocket:
    async def send_json(self, message):
        raise RuntimeError("send failed")


@given(attempt=st.integers(min_value=-3, max_value=20))
def test_retry_delay_bounds(attempt):
    delay = app_module.retry_delay_ms(attempt, base_ms=1000, max_ms=30000)
    assert delay >= 1000
    assert delay <= 30000


def test_broadcast_recovers_from_dead_connection():
    original = list(app_module.live_ws_connections)
    try:
        app_module.live_ws_connections = [FailingWebSocket()]
        asyncio.run(app_module._broadcast_live({"type": "ping"}))
        assert len(app_module.live_ws_connections) == 0
    finally:
        app_module.live_ws_connections = original


@given(attempts=st.lists(st.integers(min_value=0, max_value=12), min_size=2, max_size=8))
def test_retry_delay_monotonic(attempts):
    ordered = sorted(attempts)
    delays = [app_module.retry_delay_ms(a, base_ms=1000, max_ms=30000) for a in ordered]
    assert delays == sorted(delays)


@given(actions=st.lists(st.sampled_from(["BUY", "SELL", "FLATTEN", "CLOSE"]), min_size=1, max_size=6))
def test_command_queue_persists_without_ws(actions):
    bot_id = "test-bot-queue"
    try:
        app_module.bot_ws_connections.pop(bot_id, None)
        for action in actions:
            asyncio.run(app_module._enqueue_command_payload(bot_id, {"action": action, "qty": 1}))

        q = asyncio.run(app_module.get_queue(bot_id))
        assert q.qsize() == len(actions)
        ids = [item.get("id") for item in list(q._queue)]
        assert len(ids) == len(set(ids))
    finally:
        app_module._queues.pop(bot_id, None)
        app_module.cmd_log.pop(bot_id, None)
        app_module.cmd_index.pop(bot_id, None)
        app_module.bots.pop(bot_id, None)
