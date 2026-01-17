from __future__ import annotations

from datetime import datetime, timezone


def test_parse_ws_message_accepts_v2_envelope_and_normalizes_timeframe() -> None:
    from backend.ws.server import _parse_ws_message

    raw = (
        '{"type":"BAR_DATA","v":2,"source":"NINJA_WS","botId":"bot-1","seq":123,'
        '"send_ts_utc":"2026-01-16T00:00:00Z",'
        '"payload":{"bar_ts_utc":"2026-01-16T00:00:00Z","timestamp":"2026-01-16T00:00:00Z",'
        '"symbol":"MNQ","timeframe":"1 Minute","open":1,"high":2,"low":0.5,"close":1.5,"volume":10}}'
    )
    effective_bot_id, msg_type, payload, env = _parse_ws_message(raw, "bot-1")

    assert effective_bot_id == "bot-1"
    assert msg_type == "BAR_DATA"
    assert payload["timeframe"] == "1m"
    assert env["v"] == 2
    assert env["source"] == "NINJA_WS"
    assert env["seq"] == 123


def test_market_buffer_upsert_replaces_same_timestamp() -> None:
    from backend.market.buffer import MarketBar, MarketBuffer

    buf = MarketBuffer(capacity_per_key=10)
    ts = datetime(2026, 1, 16, 0, 0, 0, tzinfo=timezone.utc)

    buf.add_bar(
        MarketBar(
            ts_utc=ts,
            symbol="MNQ",
            timeframe="1m",
            open=1.0,
            high=2.0,
            low=0.5,
            close=1.5,
            volume=10,
            rx_ts_utc=ts,
        )
    )
    buf.add_bar(
        MarketBar(
            ts_utc=ts,
            symbol="MNQ",
            timeframe="1m",
            open=1.0,
            high=3.0,
            low=0.5,
            close=2.5,
            volume=20,
            rx_ts_utc=ts,
        )
    )

    bars = buf.get_bars(symbol="MNQ", timeframe="1m", limit=10)
    assert len(bars) == 1
    assert bars[0].high == 3.0
    assert bars[0].close == 2.5
    assert bars[0].volume == 20

