from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app import app


def main() -> int:
    client = TestClient(app)

    r = client.post("/api/v1/ai/chat", json={"message": "status bots", "botId": "bot-1", "tools": False})
    assert r.status_code == 200
    body = r.json()
    assert "answer" in body

    r2 = client.post("/api/v1/ai/chat", json={"message": "health + swarm rank", "botId": "bot-1", "tools": True})
    assert r2.status_code == 200
    body2 = r2.json()
    assert "answer" in body2

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
