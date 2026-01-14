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
    if not any((tc or {}).get("name") == "tool_get_status" for tc in (data.get("tool_calls") or [])):
        print("FAIL: expected tool_get_status in tool_calls")
        print(json.dumps(data, indent=2))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
