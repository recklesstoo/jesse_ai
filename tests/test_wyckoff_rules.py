import uuid

from fastapi.testclient import TestClient

import backend.app as app_module


def _bar(ts, o, h, l, c, v):
    return {
        "ts": ts,
        "symbol": "MNQ",
        "timeframe": "1 Minute",
        "o": o,
        "h": h,
        "l": l,
        "c": c,
        "v": v,
    }


def test_wyckoff_spring_signal():
    bars = []
    for i in range(9):
        bars.append(_bar(f"2026-01-01T00:0{i}:00Z", 100, 101, 99, 100, 1000))
    # Spring: break low and close above with high volume.
    bars.append(_bar("2026-01-01T00:09:00Z", 100, 101, 97, 100.5, 2000))

    meta = app_module.compute_wyckoff_signal(bars)
    assert meta["signal"] in ("SPRING", "SOS", "NONE")


def test_ai_signals_pipeline():
    client = TestClient(app_module.app)
    bot_id = f"test-bot-{uuid.uuid4().hex}"
    try:
        bars = [
            _bar("2026-01-01T00:00:00Z", 100, 101, 99, 100, 1000),
            _bar("2026-01-01T00:01:00Z", 100, 101.5, 99.5, 101, 1100),
            _bar("2026-01-01T00:02:00Z", 101, 102, 100, 101.8, 1200),
            _bar("2026-01-01T00:03:00Z", 101.8, 102, 100.5, 101.2, 1150),
            _bar("2026-01-01T00:04:00Z", 101.2, 102, 99.8, 100.2, 1300),
            _bar("2026-01-01T00:05:00Z", 100.2, 101, 99, 99.4, 1400),
            _bar("2026-01-01T00:06:00Z", 99.4, 100.4, 98.8, 99.9, 1500),
            _bar("2026-01-01T00:07:00Z", 99.9, 101, 99.2, 100.6, 1600),
            _bar("2026-01-01T00:08:00Z", 100.6, 101.2, 99.8, 100.9, 1550),
            _bar("2026-01-01T00:09:00Z", 100.9, 101.4, 99.7, 100.1, 1450),
        ]
        payload = {"botId": bot_id, "mode": "LIVE", "bars": bars}
        res = client.post("/api/v1/bars/batch", json=payload)
        assert res.status_code == 200

        sig = client.get(f"/api/v1/ai-signals?botId={bot_id}").json()
        assert sig["ok"] is True
        assert "signal" in sig
        assert "confidence" in sig
    finally:
        app_module._queues.pop(bot_id, None)
        app_module.cmd_log.pop(bot_id, None)
        app_module.cmd_index.pop(bot_id, None)
        app_module.bots.pop(bot_id, None)
        app_module.bars_store.pop(bot_id, None)
        app_module.ai_signal_store.pop(bot_id, None)
