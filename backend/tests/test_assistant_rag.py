from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))
os.environ.setdefault("PYTHONPATH", str(repo_root))

from backend.app import app
from backend.assistant.service import get_assistant_service
from backend.database import PROJECT_ROOT


def test_doc_search_returns_citations() -> None:
    svc = get_assistant_service(PROJECT_ROOT)
    svc.build_index()
    hits = svc.doc_index.search("Release-Port arranque.ps1", k=5)
    assert hits
    assert any("scripts/arranque.ps1" in h.get("path", "") for h in hits)


def test_assistant_chat_calls_tools() -> None:
    client = TestClient(app)
    r = client.post(
        "/api/v1/assistant/chat",
        json={"botId": "bot-1", "message": "what is current bot status?", "opsMode": True, "includeWeb": False, "sessionId": "pytest"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("reply")

    # opsMode can be server-disabled (e.g., WYCKOFF_AI_OPS_TOKEN required but not provided).
    status = data.get("status") or {}
    if isinstance(status, dict) and status.get("ops_mode") is False:
        return

    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        # Not configured: should still return a diagnostic reply without throwing.
        return

    tool_results = data.get("tool_results") or []
    assert any(tr.get("name") in ("tool_get_state", "tool_get_monitor_status", "tool_get_commands_log") for tr in tool_results)


def test_assistant_include_web_off_never_calls_web() -> None:
    client = TestClient(app)
    r = client.post(
        "/api/v1/assistant/chat",
        json={"botId": "bot-1", "message": "web search ninjatrader ws", "opsMode": True, "includeWeb": False, "sessionId": "pytest"},
    )
    assert r.status_code == 200
    data = r.json()
    assert not any(tc.get("name") == "tool_web_search" for tc in (data.get("tool_calls") or []))
