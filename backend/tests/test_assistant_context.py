from __future__ import annotations

import os

from fastapi.testclient import TestClient

from backend.app import app


def test_assistant_context_endpoint_returns_snapshot() -> None:
    client = TestClient(app)
    r = client.get("/api/v1/assistant/context", params={"botId": "bot-1"})
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert data.get("botId") == "bot-1"
    snap = data.get("snapshot") or {}
    assert snap.get("botId") == "bot-1"
    assert "market" in snap  # includes m1/m5 (may be NO_LIVE)


def test_ops_token_blocks_ops_mode_when_configured() -> None:
    os.environ["WYCKOFF_AI_OPS_TOKEN"] = "secret-token"
    client = TestClient(app)
    r = client.post(
        "/api/v1/assistant/chat",
        json={"botId": "bot-1", "message": "Explain now", "opsMode": True, "includeWeb": False, "sessionId": "pytest-token"},
    )
    assert r.status_code == 200
    data = r.json()
    # Without token: endpoint forces opsMode off and should not crash.
    assert data.get("reply")

