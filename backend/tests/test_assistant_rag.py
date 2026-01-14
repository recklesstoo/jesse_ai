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
    tool_calls = data.get("tool_calls") or []
    tool_results = data.get("tool_results") or []
    assert any(tc.get("name") == "tool_get_status" for tc in tool_calls)
    assert any(tr.get("name") == "tool_get_status" for tr in tool_results)
