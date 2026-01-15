from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))
    os.environ.setdefault("PYTHONPATH", str(repo_root))

    from backend.app import app

    client = TestClient(app)
    payload = {"botId": "bot-1", "message": "status bot-1 (ws/feed/execution)", "opsMode": True, "includeWeb": False, "sessionId": "smoke"}
    r = client.post("/api/v1/assistant/chat", json=payload)
    if r.status_code != 200:
        print("FAIL", r.status_code, r.text)
        return 1
    data = r.json()
    if not data.get("reply"):
        print("FAIL: missing reply")
        print(json.dumps(data, indent=2))
        return 1

    # If OpenAI is not configured, the endpoint should return a clear diagnostic (but still 200).
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        print("OK (OPENAI_API_KEY not set; assistant returned a diagnostic reply)")
        return 0

    tool_results = data.get("tool_results") or []
    if not any((tr or {}).get("name") in ("tool_get_state", "tool_get_monitor_status", "tool_get_commands_log") for tr in tool_results):
        print("FAIL: expected at least one ops tool result in tool_results")
        print(json.dumps(data, indent=2))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
