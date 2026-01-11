import uuid

from fastapi.testclient import TestClient
from hypothesis import given, strategies as st

import backend.app as app_module


@given(bot_suffix=st.text(min_size=1, max_size=8, alphabet=st.characters(min_codepoint=48, max_codepoint=122)))
def test_endpoints_reliable_for_bot_ids(bot_suffix):
    client = TestClient(app_module.app)
    bot_id = f"test-{bot_suffix}-{uuid.uuid4().hex[:6]}"

    res_health = client.get("/api/v1/health")
    assert res_health.status_code == 200

    res_state = client.get(f"/api/v1/strategy/state?botId={bot_id}")
    assert res_state.status_code == 200

    res_log = client.get(f"/api/v1/commands/{bot_id}/log?limit=5")
    assert res_log.status_code == 200

    res_ai = client.get(f"/api/v1/ai-signals?botId={bot_id}")
    assert res_ai.status_code == 200


def test_validate_core_endpoints():
    client = TestClient(app_module.app)
    bot_id = f"validate-{uuid.uuid4().hex}"
    try:
        res_root = client.get("/")
        assert res_root.status_code in (200, 404)

        res_health = client.get("/api/v1/health")
        assert res_health.status_code == 200

        res_bots = client.get("/api/v1/bots")
        assert res_bots.status_code == 200

        res_state = client.get(f"/api/v1/strategy/state?botId={bot_id}")
        assert res_state.status_code == 200

        res_current = client.get(f"/api/v1/ai-signals?botId={bot_id}")
        assert res_current.status_code == 200

        res_history = client.get(f"/api/v1/ai-signals/{bot_id}/history?limit=5")
        assert res_history.status_code == 200

        res_log = client.get(f"/api/v1/commands/{bot_id}/log?limit=5")
        assert res_log.status_code == 200
    finally:
        app_module.cmd_log.pop(bot_id, None)
        app_module.cmd_index.pop(bot_id, None)
        app_module.bots.pop(bot_id, None)
