from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from zoneinfo import ZoneInfo

import numpy as np

from backend.market.buffer import MarketBar


NY_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class InstrumentSpec:
    tick_size: float
    tick_value_usd: float


def instrument_spec(symbol: str) -> InstrumentSpec:
    s = (symbol or "").upper()
    if s.startswith("MNQ"):
        return InstrumentSpec(tick_size=0.25, tick_value_usd=0.50)
    if s.startswith("NQ"):
        return InstrumentSpec(tick_size=0.25, tick_value_usd=5.00)
    # Fallback: unknown instrument
    return InstrumentSpec(tick_size=0.25, tick_value_usd=0.0)


def timeframe_seconds(timeframe: str) -> int:
    tf = (timeframe or "").strip().lower()
    if tf.endswith("m") and tf[:-1].isdigit():
        return int(tf[:-1]) * 60
    if tf.endswith("s") and tf[:-1].isdigit():
        return int(tf[:-1])
    if tf.endswith("h") and tf[:-1].isdigit():
        return int(tf[:-1]) * 3600
    # Default to 60s (safe)
    return 60


def safe_tick_round(value: float, tick_size: float) -> float:
    if tick_size <= 0:
        return float(value)
    return round(float(value) / tick_size) * tick_size


def _ticks(value: float, tick_size: float) -> float:
    if tick_size <= 0:
        return 0.0
    return float(value) / tick_size


def _close_location(bar: MarketBar) -> float:
    span = float(bar.high) - float(bar.low)
    if span <= 0:
        return 0.5
    return (float(bar.close) - float(bar.low)) / span


def _sma(values: List[float], n: int) -> Optional[float]:
    if n <= 0 or len(values) < n:
        return None
    return float(sum(values[-n:])) / float(n)


def _zscore(values: List[float], n: int) -> Optional[float]:
    if n <= 1 or len(values) < n:
        return None
    arr = np.array(values[-n:], dtype=float)
    mu = float(arr.mean())
    sd = float(arr.std(ddof=0))
    if sd <= 0:
        return 0.0
    return float((arr[-1] - mu) / sd)


def _percentile(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    arr = np.array(values, dtype=float)
    return float(np.percentile(arr, p))


def compute_true_ranges_ticks(bars: List[MarketBar], tick_size: float) -> List[float]:
    trs: List[float] = []
    prev_close: Optional[float] = None
    for b in bars:
        high = float(b.high)
        low = float(b.low)
        if prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(_ticks(tr, tick_size))
        prev_close = float(b.close)
    return trs


def _fractal_pivots(bars: List[MarketBar], *, left: int = 3, right: int = 3) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    highs: List[Dict[str, Any]] = []
    lows: List[Dict[str, Any]] = []
    n = len(bars)
    if n < left + right + 1:
        return highs, lows
    for i in range(left, n - right):
        h = float(bars[i].high)
        l = float(bars[i].low)
        left_h = [float(bars[j].high) for j in range(i - left, i)]
        right_h = [float(bars[j].high) for j in range(i + 1, i + right + 1)]
        left_l = [float(bars[j].low) for j in range(i - left, i)]
        right_l = [float(bars[j].low) for j in range(i + 1, i + right + 1)]
        if h > max(left_h) and h >= max(right_h):
            highs.append({"ts_utc": bars[i].ts_utc.isoformat().replace("+00:00", "Z"), "price": h})
        if l < min(left_l) and l <= min(right_l):
            lows.append({"ts_utc": bars[i].ts_utc.isoformat().replace("+00:00", "Z"), "price": l})
    return highs, lows


def _bos_mss_last(bars: List[MarketBar], swings_high: List[Dict[str, Any]], swings_low: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not bars:
        return None
    last_close = float(bars[-1].close)
    last_ts = bars[-1].ts_utc.isoformat().replace("+00:00", "Z")
    last_high = swings_high[-1] if swings_high else None
    last_low = swings_low[-1] if swings_low else None
    if last_high and last_close > float(last_high["price"]):
        return {"type": "BOS_UP", "ts_utc": last_ts, "level": float(last_high["price"])}
    if last_low and last_close < float(last_low["price"]):
        return {"type": "BOS_DOWN", "ts_utc": last_ts, "level": float(last_low["price"])}
    return None


def _linreg_r2_slope(values: List[float]) -> Tuple[Optional[float], Optional[float]]:
    if len(values) < 5:
        return None, None
    y = np.array(values, dtype=float)
    x = np.arange(len(values), dtype=float)
    # y = a + b*x
    b, a = np.polyfit(x, y, 1)
    y_hat = a + b * x
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - float(y.mean())) ** 2))
    r2 = None if ss_tot <= 0 else max(0.0, min(1.0, 1.0 - ss_res / ss_tot))
    return r2, float(b)


def _compute_sessions(
    *,
    bars: List[MarketBar],
    now_utc: datetime,
) -> Dict[str, Any]:
    # Session identification: RTH if inside 09:30-16:00 ET, else ETH.
    now_et = now_utc.astimezone(NY_TZ)
    t = now_et.timetz()
    is_rth = (t.hour > 9 or (t.hour == 9 and t.minute >= 30)) and (t.hour < 16 or (t.hour == 16 and t.minute == 0))
    session_id = "RTH" if is_rth else "ETH"

    # ETH session window: 18:00 ET to 17:00 ET next day (rough; halt is out-of-scope v1).
    if session_id == "ETH":
        if (t.hour, t.minute) >= (18, 0):
            start_et = now_et.replace(hour=18, minute=0, second=0, microsecond=0)
        else:
            start_et = now_et.replace(hour=18, minute=0, second=0, microsecond=0) - timedelta(days=1)
        end_et = start_et.replace(hour=17, minute=0, second=0, microsecond=0)
        if end_et <= start_et:
            # end is next day
            end_et = end_et + timedelta(days=1)
    else:
        start_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        end_et = now_et.replace(hour=16, minute=0, second=0, microsecond=0)

    try:
        start_utc = start_et.astimezone(timezone.utc)
        end_utc = end_et.astimezone(timezone.utc)
    except Exception:
        start_utc = now_utc
        end_utc = now_utc

    session_bars = [b for b in bars if b.ts_utc >= start_utc and b.ts_utc <= now_utc]
    if session_bars:
        session_open = float(session_bars[0].open)
        session_high = float(max(float(b.high) for b in session_bars))
        session_low = float(min(float(b.low) for b in session_bars))
    else:
        session_open = session_high = session_low = 0.0

    # Previous NY day levels based on bar timestamps converted to NY local date.
    prev_day_high = prev_day_low = prev_day_close = 0.0
    if bars:
        ny_dates = [b.ts_utc.astimezone(NY_TZ).date() for b in bars]
        current_date = now_et.date()
        prev_dates = sorted({d for d in ny_dates if d < current_date})
        prev_date = prev_dates[-1] if prev_dates else None
        if prev_date:
            prev_bars = [b for b in bars if b.ts_utc.astimezone(NY_TZ).date() == prev_date]
            if prev_bars:
                prev_day_high = float(max(float(b.high) for b in prev_bars))
                prev_day_low = float(min(float(b.low) for b in prev_bars))
                prev_day_close = float(prev_bars[-1].close)

    # Opening range 15m for RTH: 09:30-09:45 ET
    or_high = or_low = 0.0
    or_start_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    or_end_et = now_et.replace(hour=9, minute=45, second=0, microsecond=0)
    try:
        or_start_utc = or_start_et.astimezone(timezone.utc)
        or_end_utc = or_end_et.astimezone(timezone.utc)
        or_bars = [b for b in bars if b.ts_utc >= or_start_utc and b.ts_utc < or_end_utc]
        if or_bars:
            or_high = float(max(float(b.high) for b in or_bars))
            or_low = float(min(float(b.low) for b in or_bars))
    except Exception:
        pass

    return {
        "session_id": session_id,
        "session_open": session_open,
        "session_high": session_high,
        "session_low": session_low,
        "prev_day_high": prev_day_high,
        "prev_day_low": prev_day_low,
        "prev_day_close": prev_day_close,
        "opening_range_15m": {"high": or_high, "low": or_low},
    }


def _compute_fvg(
    bars: List[MarketBar],
    *,
    last_price: float,
    tick_size: float,
) -> Dict[str, Any]:
    # Basic 3-bar FVG detection with unfilled tracking (lookback-limited).
    unfilled: List[Dict[str, Any]] = []
    last_fill: Optional[Dict[str, Any]] = None
    for i in range(2, len(bars)):
        b0 = bars[i - 2]
        b2 = bars[i]
        # Bullish gap: low[i] > high[i-2]
        if float(b2.low) > float(b0.high):
            gap = {
                "dir": "BULL",
                "low": float(b0.high),
                "high": float(b2.low),
                "ts_utc": b2.ts_utc.isoformat().replace("+00:00", "Z"),
            }
            unfilled.append(gap)
        # Bearish gap: high[i] < low[i-2]
        if float(b2.high) < float(b0.low):
            gap = {
                "dir": "BEAR",
                "low": float(b2.high),
                "high": float(b0.low),
                "ts_utc": b2.ts_utc.isoformat().replace("+00:00", "Z"),
            }
            unfilled.append(gap)

    # Fill detection: any later bar overlaps gap range.
    survivors: List[Dict[str, Any]] = []
    for g in unfilled:
        filled = False
        g_low = float(g["low"])
        g_high = float(g["high"])
        try:
            g_ts = datetime.fromisoformat(str(g["ts_utc"]).replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            g_ts = datetime.min.replace(tzinfo=timezone.utc)
        for b in bars:
            if b.ts_utc <= g_ts:
                continue
            if float(b.low) <= g_high and float(b.high) >= g_low:
                filled = True
                last_fill = {
                    "ts_utc": b.ts_utc.isoformat().replace("+00:00", "Z"),
                    "direction": g["dir"],
                    "size_ticks": round(_ticks(g_high - g_low, tick_size), 2),
                }
                break
        if not filled:
            survivors.append(g)

    above = [g for g in survivors if float(g["low"]) > last_price]
    below = [g for g in survivors if float(g["high"]) < last_price]
    nearest_above = min(above, key=lambda g: float(g["low"]) - last_price) if above else None
    nearest_below = min(below, key=lambda g: last_price - float(g["high"])) if below else None
    if nearest_above:
        nearest_above = {
            "low": safe_tick_round(float(nearest_above["low"]), tick_size),
            "high": safe_tick_round(float(nearest_above["high"]), tick_size),
            "age_bars": None,
        }
    if nearest_below:
        nearest_below = {
            "low": safe_tick_round(float(nearest_below["low"]), tick_size),
            "high": safe_tick_round(float(nearest_below["high"]), tick_size),
            "age_bars": None,
        }

    return {
        "nearest_above": nearest_above,
        "nearest_below": nearest_below,
        "unfilled_above_count": len(above),
        "unfilled_below_count": len(below),
        "last_fill_event": last_fill,
    }


def compute_market_metrics_v1(
    *,
    bars: List[MarketBar],
    symbol: str,
    timeframe: str,
    ws_age_sec: Optional[float],
    last_ws_ts_utc: Optional[str],
    ws_stale_sec: float = 10.0,
    lookback: int,
    mode: str,
) -> Tuple[Dict[str, Any], List[str]]:
    notes: List[str] = []
    now_utc = datetime.now(timezone.utc)
    spec = instrument_spec(symbol)
    tick_size = spec.tick_size

    tf_sec = timeframe_seconds(timeframe)
    bar_stale_sec = float(max(1.5 * tf_sec, 90))

    if not bars:
        notes.append("no bars available in memory buffer")
        resp = {
            "version": "market-metrics.v1",
            "symbol": symbol,
            "timeframe": timeframe,
            "lookback": lookback,
            "source": "NO_LIVE",
            "feed_status": "NO_LIVE",
            "confidence": "low",
            "timestamps": {
                "server_ts_utc": now_utc.isoformat().replace("+00:00", "Z"),
                "last_ws_ts_utc": last_ws_ts_utc,
                "last_bar_ts_utc": None,
            },
            "ages": {"ws_age_sec": ws_age_sec, "bar_age_sec": None},
            "thresholds": {"ws_stale_sec": ws_stale_sec, "bar_stale_sec": bar_stale_sec},
            "availability": {"bars": False, "quotes": False, "orderflow": False},
            "instrument": {"tick_size": tick_size, "tick_value_usd": spec.tick_value_usd},
            "metrics": {
                "base": {"last_price": 0, "true_range_last_ticks": 0, "atr_14_ticks": 0, "bid": None, "ask": None, "spread_ticks": None},
                "wyckoff": {"effort_result": 0, "rvol_20": 0, "vol_zscore_50": 0, "events": {"climax_bar": None, "sweep": None, "spring_upthrust": None}},
                "trend_pullback": {"linreg_r2_50": 0, "linreg_slope_50_atr_norm": 0, "swings": {"highs": [], "lows": []}, "bos_mss_last": None},
                "sessions": {"session_id": "ETH", "session_open": 0, "session_high": 0, "session_low": 0, "prev_day_high": 0, "prev_day_low": 0, "prev_day_close": 0, "opening_range_15m": {"high": 0, "low": 0}},
                "fvg": {"nearest_above": None, "nearest_below": None, "unfilled_above_count": 0, "unfilled_below_count": 0, "last_fill_event": None},
            },
            "bars_preview": [],
            "raw_bars": None,
            "notes": notes,
        }
        return resp, notes

    # Ensure UTC tz-aware
    cleaned: List[MarketBar] = []
    for b in bars[-min(len(bars), max(1, lookback)) :]:
        ts = b.ts_utc
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        cleaned.append(
            MarketBar(
                ts_utc=ts.astimezone(timezone.utc),
                symbol=b.symbol,
                timeframe=b.timeframe,
                open=float(b.open),
                high=float(b.high),
                low=float(b.low),
                close=float(b.close),
                volume=int(b.volume),
                bid=b.bid,
                ask=b.ask,
            )
        )

    last = cleaned[-1]
    last_bar_ts_utc = last.ts_utc.isoformat().replace("+00:00", "Z")
    bar_age_sec = float(max(0.0, (now_utc - last.ts_utc).total_seconds()))

    feed_ok = True
    if ws_age_sec is None:
        feed_ok = False
        notes.append("ws_age_sec unavailable")
    else:
        if float(ws_age_sec) > float(ws_stale_sec):
            feed_ok = False
            notes.append(f"ws stale (ws_age_sec={ws_age_sec:.1f} > {ws_stale_sec})")
    if bar_age_sec > bar_stale_sec:
        feed_ok = False
        notes.append(f"bar stale (bar_age_sec={bar_age_sec:.1f} > {bar_stale_sec})")

    confidence = "high"
    if not feed_ok:
        confidence = "low"
    elif len(cleaned) < 60:
        confidence = "medium" if len(cleaned) >= 30 else "low"
        notes.append(f"short lookback for stable stats (have={len(cleaned)} need>=60)")

    # Availability
    quotes_available = last.bid is not None and last.ask is not None
    if not quotes_available:
        notes.append("quotes unavailable: bid/ask not provided")

    # Base metrics
    last_price = float(last.close)
    trs = compute_true_ranges_ticks(cleaned, tick_size)
    tr_last = trs[-1] if trs else 0.0
    atr_14 = _sma(trs, 14) or 0.0

    spread_ticks = None
    if quotes_available and tick_size > 0:
        spread_ticks = round(_ticks(float(last.ask) - float(last.bid), tick_size), 2)

    # Wyckoff metrics
    vols = [float(b.volume) for b in cleaned]
    vol_last = vols[-1] if vols else 0.0
    rvol_20 = 0.0
    sma20 = _sma(vols, 20)
    if sma20 and sma20 > 0:
        rvol_20 = float(vol_last) / float(sma20)
    vol_z = _zscore(vols, 50)
    vol_zscore_50 = float(vol_z) if vol_z is not None else 0.0
    effort_result = float(vol_last) / float(max(tr_last, 1.0))

    # Events: climax + sweeps + spring/upthrust
    spread_series_ticks = [round(_ticks(float(b.high) - float(b.low), tick_size), 4) for b in cleaned[-50:]]
    p80 = _percentile(spread_series_ticks, 80.0) if spread_series_ticks else None
    climax_bar = None
    if vol_z is not None and p80 is not None:
        if vol_z >= 2.5 and spread_series_ticks and spread_series_ticks[-1] >= p80:
            climax_bar = {
                "type": "CLIMAX",
                "ts_utc": last_bar_ts_utc,
                "vol_zscore_50": round(float(vol_z), 2),
                "spread_ticks": round(float(spread_series_ticks[-1]), 2),
                "close_location": round(_close_location(last), 3),
                "evidence": {"rule_id": "climax_v1", "bar_index": len(cleaned) - 1},
            }

    swings_high, swings_low = _fractal_pivots(cleaned, left=3, right=3)
    swings_high = swings_high[-5:]
    swings_low = swings_low[-5:]
    sweep = None
    spring_upthrust = None
    # Sweep levels: last swing high/low if available
    last_swing_high = swings_high[-1]["price"] if swings_high else None
    last_swing_low = swings_low[-1]["price"] if swings_low else None
    if last_swing_high is not None:
        if float(last.high) > float(last_swing_high) and float(last.close) < float(last_swing_high):
            sweep = {
                "type": "SWEEP_HIGH",
                "ts_utc": last_bar_ts_utc,
                "level": float(last_swing_high),
                "reclaim": False,
                "evidence": {"rule_id": "sweep_high_v1", "bar_index": len(cleaned) - 1},
            }
    if last_swing_low is not None:
        if float(last.low) < float(last_swing_low) and float(last.close) > float(last_swing_low):
            sweep = {
                "type": "SWEEP_LOW",
                "ts_utc": last_bar_ts_utc,
                "level": float(last_swing_low),
                "reclaim": True,
                "evidence": {"rule_id": "sweep_low_v1", "bar_index": len(cleaned) - 1},
            }

    if sweep and rvol_20 >= 1.5:
        cl = _close_location(last)
        if sweep["type"] == "SWEEP_LOW" and cl > 0.5:
            spring_upthrust = {
                "type": "SPRING",
                "ts_utc": last_bar_ts_utc,
                "level": sweep["level"],
                "evidence": {"rule_id": "spring_v1", "bar_index": len(cleaned) - 1},
            }
        if sweep["type"] == "SWEEP_HIGH" and cl < 0.5:
            spring_upthrust = {
                "type": "UPTHRUST",
                "ts_utc": last_bar_ts_utc,
                "level": sweep["level"],
                "evidence": {"rule_id": "upthrust_v1", "bar_index": len(cleaned) - 1},
            }

    # Trend/pullback
    closes = [float(b.close) for b in cleaned]
    r2_50, slope_50 = _linreg_r2_slope(closes[-50:])
    atr_price = atr_14 * tick_size
    slope_norm = None
    if slope_50 is not None and atr_price > 0:
        slope_norm = float(slope_50) / float(atr_price)
    bos_mss_last = _bos_mss_last(cleaned, swings_high, swings_low)

    sessions = _compute_sessions(bars=cleaned, now_utc=now_utc)
    fvg = _compute_fvg(cleaned, last_price=last_price, tick_size=tick_size)

    bars_preview = [
        {
            "ts_utc": b.ts_utc.isoformat().replace("+00:00", "Z"),
            "open": float(b.open),
            "high": float(b.high),
            "low": float(b.low),
            "close": float(b.close),
            "volume": int(b.volume),
        }
        for b in cleaned[-5:]
    ]
    raw_bars = None
    if str(mode or "").lower() == "full":
        raw_bars = [
            {
                "ts_utc": b.ts_utc.isoformat().replace("+00:00", "Z"),
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": int(b.volume),
                "bid": b.bid,
                "ask": b.ask,
            }
            for b in cleaned
        ]

    resp = {
        "version": "market-metrics.v1",
        "symbol": symbol,
        "timeframe": timeframe,
        "lookback": lookback,
        "source": "LIVE_WS",
        "feed_status": "OK" if feed_ok else "STALE",
        "confidence": confidence,
        "timestamps": {
            "server_ts_utc": now_utc.isoformat().replace("+00:00", "Z"),
            "last_ws_ts_utc": last_ws_ts_utc,
            "last_bar_ts_utc": last_bar_ts_utc,
        },
        "ages": {"ws_age_sec": ws_age_sec, "bar_age_sec": round(bar_age_sec, 3)},
        "thresholds": {"ws_stale_sec": ws_stale_sec, "bar_stale_sec": bar_stale_sec},
        "availability": {"bars": True, "quotes": quotes_available, "orderflow": False},
        "instrument": {"tick_size": tick_size, "tick_value_usd": spec.tick_value_usd},
        "metrics": {
            "base": {
                "last_price": last_price,
                "bid": last.bid,
                "ask": last.ask,
                "spread_ticks": spread_ticks,
                "true_range_last_ticks": round(tr_last, 3),
                "atr_14_ticks": round(float(atr_14), 3),
            },
            "wyckoff": {
                "effort_result": round(float(effort_result), 3),
                "rvol_20": round(float(rvol_20), 3),
                "vol_zscore_50": round(float(vol_zscore_50), 3),
                "events": {"climax_bar": climax_bar, "sweep": sweep, "spring_upthrust": spring_upthrust},
            },
            "trend_pullback": {
                "linreg_r2_50": round(float(r2_50 or 0.0), 4),
                "linreg_slope_50_atr_norm": round(float(slope_norm or 0.0), 4),
                "swings": {"highs": swings_high, "lows": swings_low},
                "bos_mss_last": bos_mss_last,
            },
            "sessions": sessions,
            "fvg": fvg,
        },
        "bars_preview": bars_preview,
        "raw_bars": raw_bars,
        "notes": notes,
    }
    return resp, notes
