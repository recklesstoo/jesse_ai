from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.market.buffer import MarketBar
from backend.market.metrics import compute_market_metrics_v1


def _mk_bar(ts: datetime, close: float, *, symbol: str = "MNQ", tf: str = "1m", vol: int = 100) -> MarketBar:
    # Simple rising bars with a small range.
    o = close - 0.25
    h = close + 0.25
    l = close - 0.50
    return MarketBar(
        ts_utc=ts,
        symbol=symbol,
        timeframe=tf,
        open=o,
        high=h,
        low=l,
        close=close,
        volume=vol,
        bid=None,
        ask=None,
    )


def test_market_metrics_ok_when_fresh_and_enough_lookback() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    bars = [_mk_bar(now - timedelta(minutes=99 - i), close=25000 + i * 0.25, vol=100 + (i % 5)) for i in range(100)]
    resp, _ = compute_market_metrics_v1(
        bars=bars,
        symbol="MNQ",
        timeframe="1m",
        ws_age_sec=1.0,
        last_ws_ts_utc=(now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        ws_stale_sec=10.0,
        lookback=500,
        mode="summary",
    )
    assert resp["feed_status"] == "OK"
    assert resp["confidence"] in ("high", "medium")
    assert resp["availability"]["bars"] is True
    assert resp["metrics"]["base"]["atr_14_ticks"] > 0


def test_market_metrics_stale_when_ws_old() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    bars = [_mk_bar(now - timedelta(minutes=29 - i), close=25000 + i * 0.25) for i in range(30)]
    resp, notes = compute_market_metrics_v1(
        bars=bars,
        symbol="MNQ",
        timeframe="1m",
        ws_age_sec=25.0,
        last_ws_ts_utc=(now - timedelta(seconds=25)).isoformat().replace("+00:00", "Z"),
        ws_stale_sec=10.0,
        lookback=30,
        mode="summary",
    )
    assert resp["feed_status"] == "STALE"
    assert resp["confidence"] == "low"
    assert any("ws stale" in n for n in notes)

