import uuid

from fastapi.testclient import TestClient
from hypothesis import given, strategies as st

import backend.app as app_module


status_chars = st.characters(min_codepoint=48, max_codepoint=90)
status_strategy = st.text(alphabet=status_chars, min_size=1, max_size=12)

action_strategy = st.lists(
    st.sampled_from(["BUY", "SELL", "FLATTEN", "CLOSE"]),
    min_size=1,
    max_size=8,
)

qty_strategy = st.lists(
    st.integers(min_value=1, max_value=10),
    min_size=1,
    max_size=8,
)


def test_command_ack_logged():
    client = TestClient(app_module.app)
    bot_id = f"test-bot-{uuid.uuid4().hex}"
    try:
        app_module.update_bot_state(bot_id, mode="LIVE")
        res = client.post(f"/api/v1/commands/{bot_id}", json={"action": "BUY", "qty": 1})
        assert res.status_code == 200
        cmd_id = res.json()["queued"]["id"]

        ack_res = client.post(
            f"/api/v1/commands/{bot_id}/ack", json={"id": cmd_id, "status": "SENT"}
        )
        assert ack_res.status_code == 200

        log_res = client.get(f"/api/v1/commands/{bot_id}/log?limit=50")
        assert log_res.status_code == 200
        events = [row["event"] for row in log_res.json()["log"]]
        assert "ACK_SENT" in events
    finally:
        app_module._queues.pop(bot_id, None)
        app_module.cmd_log.pop(bot_id, None)
        app_module.cmd_index.pop(bot_id, None)
        app_module.bots.pop(bot_id, None)


@given(status=status_strategy)
def test_command_ack_property(status):
    client = TestClient(app_module.app)
    bot_id = f"test-bot-{uuid.uuid4().hex}"
    try:
        app_module.update_bot_state(bot_id, mode="LIVE")
        res = client.post(f"/api/v1/commands/{bot_id}", json={"action": "BUY", "qty": 1})
        assert res.status_code == 200
        cmd_id = res.json()["queued"]["id"]

        ack_res = client.post(
            f"/api/v1/commands/{bot_id}/ack", json={"id": cmd_id, "status": status}
        )
        assert ack_res.status_code == 200

        log_res = client.get(f"/api/v1/commands/{bot_id}/log?limit=50")
        assert log_res.status_code == 200
        events = [row["event"] for row in log_res.json()["log"]]
        # SIM acks are coerced to REJECTED (simulated acks disabled).
        expected = "ACK_REJECTED" if str(status).upper().startswith("SIM") else f"ACK_{status}"
        assert expected in events
    finally:
        app_module._queues.pop(bot_id, None)
        app_module.cmd_log.pop(bot_id, None)
        app_module.cmd_index.pop(bot_id, None)
        app_module.bots.pop(bot_id, None)


def test_command_queue_fifo_delivery():
    client = TestClient(app_module.app)
    bot_id = f"test-bot-{uuid.uuid4().hex}"
    try:
        app_module.update_bot_state(bot_id, mode="LIVE")
        res1 = client.post(f"/api/v1/commands/{bot_id}", json={"action": "BUY", "qty": 1})
        res2 = client.post(f"/api/v1/commands/{bot_id}", json={"action": "SELL", "qty": 1})
        assert res1.status_code == 200
        assert res2.status_code == 200
        cmd1 = res1.json()["queued"]["id"]
        cmd2 = res2.json()["queued"]["id"]

        get1 = client.get(f"/api/v1/commands/{bot_id}?wait_ms=0").json()
        get2 = client.get(f"/api/v1/commands/{bot_id}?wait_ms=0").json()
        ids = {get1["id"], get2["id"]}
        assert ids == {cmd1, cmd2}
    finally:
        app_module._queues.pop(bot_id, None)
        app_module.cmd_log.pop(bot_id, None)
        app_module.cmd_index.pop(bot_id, None)
        app_module.bots.pop(bot_id, None)


@given(actions=action_strategy)
def test_command_queue_fifo_property(actions):
    client = TestClient(app_module.app)
    bot_id = f"test-bot-{uuid.uuid4().hex}"
    try:
        app_module.update_bot_state(bot_id, mode="LIVE")
        queued_ids = []
        for action in actions:
            res = client.post(f"/api/v1/commands/{bot_id}", json={"action": action, "qty": 1})
            assert res.status_code == 200
            queued_ids.append(res.json()["queued"]["id"])

        delivered_ids = []
        for _ in actions:
            res = client.get(f"/api/v1/commands/{bot_id}?wait_ms=0")
            assert res.status_code == 200
            delivered_ids.append(res.json()["id"])

        assert delivered_ids == queued_ids
    finally:
        app_module._queues.pop(bot_id, None)
        app_module.cmd_log.pop(bot_id, None)
        app_module.cmd_index.pop(bot_id, None)
        app_module.bots.pop(bot_id, None)


@given(actions=action_strategy, qtys=qty_strategy)
def test_command_enqueue_unique_ids(actions, qtys):
    client = TestClient(app_module.app)
    bot_id = f"test-bot-{uuid.uuid4().hex}"
    try:
        app_module.update_bot_state(bot_id, mode="LIVE")
        queued_ids = set()
        count = min(len(actions), len(qtys))
        for i in range(count):
            res = client.post(
                f"/api/v1/commands/{bot_id}",
                json={"action": actions[i], "qty": qtys[i]},
            )
            assert res.status_code == 200
            cmd_id = res.json()["queued"]["id"]
            assert cmd_id not in queued_ids
            queued_ids.add(cmd_id)
    finally:
        app_module._queues.pop(bot_id, None)
        app_module.cmd_log.pop(bot_id, None)
        app_module.cmd_index.pop(bot_id, None)
        app_module.bots.pop(bot_id, None)
