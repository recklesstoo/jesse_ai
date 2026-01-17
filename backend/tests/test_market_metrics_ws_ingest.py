from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import monotonic, sleep

from fastapi.testclient import TestClient


def test_market_metrics_live_after_ws_ingest() -> None:
    from backend.app import app
    from backend.state import _get_bot_state
    from backend.ws import server as ws_server

    # This is a throughput test for the WS -> in-memory ring buffer -> metrics path.
    # Disable per-bar ML inference to keep the test fast/deterministic.
    ws_server.AI_MIN_LIVE_BARS = 10**9
    # Disable BAR_DATA rate limiting for this test (it intentionally bursts many bars quickly).
    ws_server.BAR_RATE_PER_SEC = 1e9
    ws_server.BAR_BURST = 1e9
    try:
        ws_server._bar_bucket.clear()
    except Exception:
        pass

    client = TestClient(app)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)

    with client.websocket_connect("/ws/bot-1") as ws:
        # Send enough 1m bars to reach stable stats (>=30 => confidence=medium) and keep bar_age/ws_age fresh.
        bar_count = 35
        for i in range(bar_count):
            ts = now - timedelta(minutes=((bar_count - 1) - i))
            close = 25000.0 + float(i) * 0.25
            ts_iso = ts.isoformat().replace("+00:00", "Z")
            ws.send_json(
                {
                    "type": "BAR_DATA",
                    "payload": {
                        "symbol": "MNQ",
                        "timeframe": "1m",
                        # Provide both keys; different code paths consume different timestamp fields.
                        "ts": ts_iso,
                        "timestamp": ts_iso,
                        "open": close - 0.25,
                        "high": close + 0.25,
                        "low": close - 0.5,
                        "close": close,
                        "volume": 100 + (i % 5),
                        "mode": "LIVE",
                    },
                }
            )

        # Allow the WS consumer to process all bars before computing metrics.
        deadline = monotonic() + 5.0
        while monotonic() < deadline:
            st = _get_bot_state("bot-1")
            if int(st.get("live_bar_count") or 0) >= bar_count:
                break
            sleep(0.05)

        # Query while WS is still connected so the platform truth is LIVE_WS+LIVE.
        r = client.get(
            "/api/v1/market/metrics",
            params={"symbol": "MNQ", "timeframe": "1m", "lookback": 500, "mode": "summary"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["source"] == "LIVE_WS"
        assert data["feed_status"] == "LIVE"
        assert data["confidence"] in {"high", "medium"}
        assert data["ws_stale_sec"] == 10.0
        assert data["bar_stale_sec"] == 90.0
        assert isinstance(data.get("notes"), list)


if __name__ == "__main__":
    import sys
    import pytest

    raise SystemExit(pytest.main([__file__, *sys.argv[1:]]))
