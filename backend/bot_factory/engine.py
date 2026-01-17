from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from zoneinfo import ZoneInfo

from backend.contracts.bot_spec_v1 import BotSpecV1
from backend.market.metrics import instrument_spec
from backend.models import DataBar


@dataclass
class Decision:
    action: str  # NONE|BUY|SELL
    confidence: float
    reason: str


@dataclass
class Trade:
    side: str  # LONG|SHORT
    entry_ts_utc: str
    entry_price: float
    exit_ts_utc: str
    exit_price: float
    qty: int
    pnl_usd: float
    exit_reason: str  # SL|TP|EOD|FLAT


@dataclass
class BotState:
    # position
    side: str = "FLAT"  # FLAT|LONG|SHORT
    qty: int = 0
    entry_price: float = 0.0
    entry_ts_utc: str = ""
    sl_price: float = 0.0
    tp_price: float = 0.0

    # pending entry for next bar open
    pending_action: str = "NONE"  # NONE|BUY|SELL
    pending_conf: float = 0.0
    pending_reason: str = ""

    # gates
    cooldown_left: int = 0
    trades_this_session: int = 0
    trading_enabled: bool = True
    disabled_reason: str = ""

    # equity
    realized_pnl_usd: float = 0.0
    equity_high: float = 0.0
    max_drawdown_usd: float = 0.0

    # counters
    signals_seen: int = 0
    trades_taken: int = 0
    skipped_confidence: int = 0
    skipped_atr: int = 0
    skipped_cooldown: int = 0
    skipped_session: int = 0
    skipped_max_trades: int = 0
    skipped_hard_stop: int = 0

    # session tracking
    session_key: str = ""

    # strategy memory (used by some Wyckoff/VSA setups)
    setup_mem: Dict[str, Any] = field(default_factory=dict)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _to_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _hhmm_local(ts_utc: datetime, tz: ZoneInfo) -> int:
    local = ts_utc.astimezone(tz)
    return (local.hour * 100) + local.minute


def _session_id(ts_utc: datetime, *, tz: ZoneInfo, start_hhmm: int) -> str:
    """
    Session key anchored by the local date that contains start_hhmm.
    Deterministic and stable for RTH windows.
    """
    local = ts_utc.astimezone(tz)
    hhmm = (local.hour * 100) + local.minute
    day = local.date()
    # If before start time, treat as previous session day (overnight)
    if hhmm < start_hhmm:
        day = day.fromordinal(day.toordinal() - 1)
    return f"{day.isoformat()}@{tz.key}"


def _in_session_window(ts_utc: datetime, spec: BotSpecV1) -> bool:
    mode = spec.session.mode
    if mode == "BOTH":
        return True

    tz = ZoneInfo(spec.session.tz)
    hhmm = _hhmm_local(ts_utc, tz)
    start = int(spec.session.start_hhmm)
    end = int(spec.session.end_hhmm)

    in_rth = True
    if start != 0 or end != 0:
        if start <= end:
            in_rth = start <= hhmm <= end
        else:
            in_rth = hhmm >= start or hhmm <= end

    if mode == "RTH":
        return in_rth
    return not in_rth


def _ema_next(prev: float, value: float, length: int) -> float:
    if length <= 1:
        return float(value)
    alpha = 2.0 / (float(length) + 1.0)
    return (alpha * float(value)) + ((1.0 - alpha) * float(prev))


def _atr_next(prev_atr: float, tr: float, n: int) -> float:
    # Wilder smoothing
    if n <= 1:
        return float(tr)
    return ((float(prev_atr) * (n - 1)) + float(tr)) / float(n)


def _true_range(high: float, low: float, prev_close: Optional[float]) -> float:
    if prev_close is None:
        return float(high) - float(low)
    return max(float(high) - float(low), abs(float(high) - float(prev_close)), abs(float(low) - float(prev_close)))


def _evaluate_setup(
    *,
    spec: BotSpecV1,
    setup_mem: Dict[str, Any],
    bar_index: int,
    close: float,
    open_: float,
    high: float,
    low: float,
    volume: float,
    ema_trend: float,
    ema_trend_prev: float,
    ema_pull: float,
    bos_hh: float,
    bos_ll: float,
    atr: float,
    tick_size: float,
    atr_ticks: float,
    range_high: float,
    range_low: float,
    rvol20: float,
    vol_z50: float,
    spread_ticks: float,
    or_high: float,
    or_low: float,
    or_complete: bool,
) -> Decision:
    kind = spec.setup.kind

    if kind == "trend_pullback_bos":
        trend_up = close > ema_trend and ema_trend >= ema_trend_prev
        trend_down = close < ema_trend and ema_trend <= ema_trend_prev

        pull_long = low <= ema_pull <= close
        pull_short = high >= ema_pull >= close

        bos_up = close > bos_hh
        bos_down = close < bos_ll

        dist_trend_ticks = (abs(close - ema_trend) / tick_size) if tick_size > 0 else 0.0
        dist_score = _clamp01(dist_trend_ticks / max(1.0, atr_ticks)) if atr_ticks > 0 else 0.0
        bos_score = 0.45 if (bos_up or bos_down) else 0.0
        candle_score = 0.15 if (close != open_) else 0.0

        if trend_up and pull_long and bos_up:
            conf = _clamp01(0.25 + dist_score * 0.25 + bos_score + candle_score)
            return Decision(action="BUY", confidence=conf, reason="trend_up+pullback+bos")

        if trend_down and pull_short and bos_down:
            conf = _clamp01(0.25 + dist_score * 0.25 + bos_score + candle_score)
            return Decision(action="SELL", confidence=conf, reason="trend_down+pullback+bos")

        return Decision(action="NONE", confidence=0.0, reason="no_setup")

    if kind == "wyckoff_spring":
        if not (math.isfinite(range_low) and tick_size > 0):
            return Decision(action="NONE", confidence=0.0, reason="no_range")
        buf = float(spec.setup.buffer_ticks) * float(tick_size)
        swept = low < (range_low - buf)
        reclaimed = close > range_low
        if swept and reclaimed and (math.isfinite(rvol20) and float(rvol20) >= float(spec.setup.min_rvol20)):
            rv_score = _clamp01((float(rvol20) - float(spec.setup.min_rvol20)) / 1.5)
            sweep_ticks = (range_low - low) / tick_size
            sweep_score = _clamp01(sweep_ticks / max(1.0, float(spec.setup.buffer_ticks) * 4.0))
            conf = _clamp01(0.45 + 0.25 * rv_score + 0.20 * sweep_score)
            return Decision(action="BUY", confidence=conf, reason="spring_sweep+reclaim")
        return Decision(action="NONE", confidence=0.0, reason="no_setup")

    if kind == "wyckoff_upthrust":
        if not (math.isfinite(range_high) and tick_size > 0):
            return Decision(action="NONE", confidence=0.0, reason="no_range")
        buf = float(spec.setup.buffer_ticks) * float(tick_size)
        swept = high > (range_high + buf)
        rejected = close < range_high
        if swept and rejected and (math.isfinite(rvol20) and float(rvol20) >= float(spec.setup.min_rvol20)):
            rv_score = _clamp01((float(rvol20) - float(spec.setup.min_rvol20)) / 1.5)
            sweep_ticks = (high - range_high) / tick_size
            sweep_score = _clamp01(sweep_ticks / max(1.0, float(spec.setup.buffer_ticks) * 4.0))
            conf = _clamp01(0.45 + 0.25 * rv_score + 0.20 * sweep_score)
            return Decision(action="SELL", confidence=conf, reason="upthrust_sweep+reject")
        return Decision(action="NONE", confidence=0.0, reason="no_setup")

    if kind == "wyckoff_sos_lps":
        if not (math.isfinite(range_high) and tick_size > 0):
            return Decision(action="NONE", confidence=0.0, reason="no_range")
        exp = int(setup_mem.get("sos_expire_i") or -1)
        if bar_index > exp:
            setup_mem.pop("sos_expire_i", None)
            exp = -1

        brk_buf = float(spec.setup.breakout_buffer_ticks) * float(tick_size)
        pb_buf = float(spec.setup.pullback_buffer_ticks) * float(tick_size)

        breakout = close > (range_high + brk_buf) and (math.isfinite(rvol20) and float(rvol20) >= float(spec.setup.min_rvol20_breakout))
        if breakout:
            setup_mem["sos_expire_i"] = int(bar_index) + int(spec.setup.memory_bars)
            exp = int(setup_mem["sos_expire_i"])

        in_window = exp >= bar_index
        pullback_hold = low <= (range_high + pb_buf) and close >= (range_high - pb_buf)
        if in_window and pullback_hold:
            rv_score = _clamp01((float(rvol20) - 1.0) / 1.5) if math.isfinite(rvol20) else 0.0
            conf = _clamp01(0.40 + 0.20 * rv_score + 0.15)
            return Decision(action="BUY", confidence=conf, reason="sos_then_lps")
        return Decision(action="NONE", confidence=0.0, reason="no_setup")

    if kind == "wyckoff_sow_lpsy":
        if not (math.isfinite(range_low) and tick_size > 0):
            return Decision(action="NONE", confidence=0.0, reason="no_range")
        exp = int(setup_mem.get("sow_expire_i") or -1)
        if bar_index > exp:
            setup_mem.pop("sow_expire_i", None)
            exp = -1

        brk_buf = float(spec.setup.breakout_buffer_ticks) * float(tick_size)
        pb_buf = float(spec.setup.pullback_buffer_ticks) * float(tick_size)

        breakdown = close < (range_low - brk_buf) and (math.isfinite(rvol20) and float(rvol20) >= float(spec.setup.min_rvol20_breakout))
        if breakdown:
            setup_mem["sow_expire_i"] = int(bar_index) + int(spec.setup.memory_bars)
            exp = int(setup_mem["sow_expire_i"])

        in_window = exp >= bar_index
        pullback_fail = high >= (range_low - pb_buf) and close <= (range_low + pb_buf)
        if in_window and pullback_fail:
            rv_score = _clamp01((float(rvol20) - 1.0) / 1.5) if math.isfinite(rvol20) else 0.0
            conf = _clamp01(0.40 + 0.20 * rv_score + 0.15)
            return Decision(action="SELL", confidence=conf, reason="sow_then_lpsy")
        return Decision(action="NONE", confidence=0.0, reason="no_setup")

    if kind in {"vsa_selling_climax", "vsa_buying_climax"}:
        # Deterministic VSA climax proxy: vol_z50 + wide spread + close near one extreme.
        spread = max(0.0, float(high) - float(low))
        pos = 0.5 if spread <= 0 else (float(close) - float(low)) / spread  # 0=low, 1=high
        if not (math.isfinite(vol_z50) and math.isfinite(spread_ticks)):
            return Decision(action="NONE", confidence=0.0, reason="no_vsa")

        if kind == "vsa_selling_climax":
            ok = float(vol_z50) >= float(spec.setup.min_vol_z50) and float(spread_ticks) >= float(spec.setup.min_spread_ticks) and pos <= float(spec.setup.close_pos_max)
            if ok:
                vol_score = _clamp01((float(vol_z50) - float(spec.setup.min_vol_z50)) / 2.0)
                conf = _clamp01(0.55 + 0.25 * vol_score)
                return Decision(action="BUY", confidence=conf, reason="vsa_selling_climax")
            return Decision(action="NONE", confidence=0.0, reason="no_setup")

        ok = float(vol_z50) >= float(spec.setup.min_vol_z50) and float(spread_ticks) >= float(spec.setup.min_spread_ticks) and pos >= float(spec.setup.close_pos_min)
        if ok:
            vol_score = _clamp01((float(vol_z50) - float(spec.setup.min_vol_z50)) / 2.0)
            conf = _clamp01(0.55 + 0.25 * vol_score)
            return Decision(action="SELL", confidence=conf, reason="vsa_buying_climax")
        return Decision(action="NONE", confidence=0.0, reason="no_setup")

    if kind == "wyckoff_range_reversion":
        if not (math.isfinite(range_high) and math.isfinite(range_low) and tick_size > 0):
            return Decision(action="NONE", confidence=0.0, reason="no_range")
        band = float(spec.setup.entry_band_ticks) * float(tick_size)
        if band <= 0:
            return Decision(action="NONE", confidence=0.0, reason="no_band")

        do_buy = spec.setup.side in {"BOTH", "BUY_LOW"}
        do_sell = spec.setup.side in {"BOTH", "SELL_HIGH"}
        if do_buy and close <= (range_low + band):
            dist = (close - range_low) / band
            conf = _clamp01(0.35 + 0.35 * (1.0 - _clamp01(dist)))
            return Decision(action="BUY", confidence=conf, reason="range_buy_low")
        if do_sell and close >= (range_high - band):
            dist = (range_high - close) / band
            conf = _clamp01(0.35 + 0.35 * (1.0 - _clamp01(dist)))
            return Decision(action="SELL", confidence=conf, reason="range_sell_high")
        return Decision(action="NONE", confidence=0.0, reason="no_setup")

    if kind == "opening_range_breakout":
        if not or_complete or not (math.isfinite(or_high) and math.isfinite(or_low) and tick_size > 0):
            return Decision(action="NONE", confidence=0.0, reason="or_not_ready")
        buf = float(spec.setup.buffer_ticks) * float(tick_size)
        if math.isfinite(rvol20) and float(rvol20) < float(spec.setup.min_rvol20):
            return Decision(action="NONE", confidence=0.0, reason="low_rvol")

        if close > (or_high + buf):
            rv_score = _clamp01((float(rvol20) - float(spec.setup.min_rvol20)) / 1.5) if math.isfinite(rvol20) else 0.0
            conf = _clamp01(0.40 + 0.25 * rv_score + 0.10)
            return Decision(action="BUY", confidence=conf, reason="or_break_up")
        if close < (or_low - buf):
            rv_score = _clamp01((float(rvol20) - float(spec.setup.min_rvol20)) / 1.5) if math.isfinite(rvol20) else 0.0
            conf = _clamp01(0.40 + 0.25 * rv_score + 0.10)
            return Decision(action="SELL", confidence=conf, reason="or_break_down")
        return Decision(action="NONE", confidence=0.0, reason="no_setup")

    if kind == "wyckoff_contraction_breakout":
        if not (math.isfinite(range_high) and math.isfinite(range_low) and tick_size > 0):
            return Decision(action="NONE", confidence=0.0, reason="no_range")
        max_atr = float(spec.setup.max_atr_ticks)
        count = int(setup_mem.get("contract_count") or 0)
        if atr_ticks <= max_atr:
            count += 1
        else:
            count = 0
        setup_mem["contract_count"] = count

        if count < int(spec.setup.contraction_bars):
            return Decision(action="NONE", confidence=0.0, reason="waiting_contraction")

        buf = float(spec.setup.buffer_ticks) * float(tick_size)
        if math.isfinite(rvol20) and float(rvol20) < float(spec.setup.min_rvol20):
            return Decision(action="NONE", confidence=0.0, reason="low_rvol")

        if close > (range_high + buf):
            rv_score = _clamp01((float(rvol20) - float(spec.setup.min_rvol20)) / 1.5) if math.isfinite(rvol20) else 0.0
            conf = _clamp01(0.42 + 0.25 * rv_score + 0.10)
            return Decision(action="BUY", confidence=conf, reason="contraction_break_up")
        if close < (range_low - buf):
            rv_score = _clamp01((float(rvol20) - float(spec.setup.min_rvol20)) / 1.5) if math.isfinite(rvol20) else 0.0
            conf = _clamp01(0.42 + 0.25 * rv_score + 0.10)
            return Decision(action="SELL", confidence=conf, reason="contraction_break_down")
        return Decision(action="NONE", confidence=0.0, reason="no_setup")

    return Decision(action="NONE", confidence=0.0, reason="unsupported_setup")


def run_backtest(
    *,
    spec: BotSpecV1,
    bars: List[DataBar],
) -> Tuple[Dict[str, Any], List[Trade]]:
    """
    Deterministic backtest engine:
    - 1 decision per CLOSED bar (computed on bar close)
    - entry filled at NEXT bar open
    - SL/TP evaluated on subsequent bars using high/low
    - no DB writes per bar (caller persists only summary)
    """
    sym = (spec.symbol or "").upper()
    tf = spec.timeframe
    tz = ZoneInfo(spec.session.tz)
    tick = instrument_spec(sym).tick_size
    tick_value = instrument_spec(sym).tick_value_usd

    state = BotState()
    trades: List[Trade] = []

    # feature streams
    ema_trend = 0.0
    ema_trend_prev = 0.0
    ema_pull = 0.0
    atr = 0.0
    atr_warm = 0
    prev_close: Optional[float] = None

    ema_trend_len = int(getattr(spec.setup, "ema_trend_len", 200))
    ema_pull_len = int(getattr(spec.setup, "ema_pullback_len", 20))

    # BOS rolling window over highs/lows (trend_pullback_bos)
    hh_window: List[float] = []
    ll_window: List[float] = []
    bos_n = int(getattr(spec.setup, "bos_lookback", 10))

    # Range window (Wyckoff range-based setups)
    range_n = int(getattr(spec.setup, "range_lookback", 0) or 0)
    range_h_window: deque[float] = deque(maxlen=max(1, range_n))
    range_l_window: deque[float] = deque(maxlen=max(1, range_n))

    # Volume windows for RVOL/Zscore (VSA/Wyckoff proxies)
    vol20: deque[float] = deque(maxlen=20)
    vol50: deque[float] = deque(maxlen=50)
    vol20_sum = 0.0
    vol50_sum = 0.0
    vol50_sumsq = 0.0

    # Opening range tracking (only used if setup has or_minutes)
    or_minutes = int(getattr(spec.setup, "or_minutes", 0) or 0)
    or_high = float("nan")
    or_low = float("nan")
    or_complete = False
    sess_start_local: Optional[datetime] = None

    def hard_stop() -> None:
        if spec.risk.max_loss_usd <= 0:
            return
        if state.realized_pnl_usd <= -abs(float(spec.risk.max_loss_usd)):
            state.trading_enabled = False
            state.disabled_reason = f"max_loss_usd hit pnl={state.realized_pnl_usd:.2f}"

    for i in range(len(bars)):
        b = bars[i]
        if not b.ts_utc:
            continue
        ts = b.ts_utc
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts = ts.astimezone(timezone.utc)

        o = float(b.open or 0.0)
        h = float(b.high or 0.0)
        l = float(b.low or 0.0)
        c = float(b.close or 0.0)
        v = float(b.volume or 0.0)

        # Range boundaries from prior bars (avoid lookahead).
        range_high = float("nan")
        range_low = float("nan")
        if range_n > 0 and len(range_h_window) >= range_n and len(range_l_window) >= range_n:
            range_high = max(range_h_window) if range_h_window else float("nan")
            range_low = min(range_l_window) if range_l_window else float("nan")

        # Opening range update (session-scoped)
        if or_minutes > 0 and sess_start_local is not None and not or_complete:
            try:
                mins = int((ts.astimezone(tz) - sess_start_local).total_seconds() // 60)
            except Exception:
                mins = 0
            if mins < or_minutes:
                or_high = h if not math.isfinite(or_high) else max(or_high, h)
                or_low = l if not math.isfinite(or_low) else min(or_low, l)
            else:
                or_complete = bool(math.isfinite(or_high) and math.isfinite(or_low))

        # Volume features (RVOL20 / VolZ50) computed including current bar (deterministic at close).
        if len(vol20) == vol20.maxlen:
            vol20_sum -= float(vol20[0])
        vol20.append(v)
        vol20_sum += v
        rvol20 = float("nan")
        if len(vol20) >= 20:
            mu20 = vol20_sum / float(len(vol20))
            rvol20 = float(v / mu20) if mu20 > 0 else float("nan")

        if len(vol50) == vol50.maxlen:
            old = float(vol50[0])
            vol50_sum -= old
            vol50_sumsq -= old * old
        vol50.append(v)
        vol50_sum += v
        vol50_sumsq += v * v
        vol_z50 = float("nan")
        if len(vol50) >= 50:
            mu50 = vol50_sum / float(len(vol50))
            var50 = max(0.0, (vol50_sumsq / float(len(vol50))) - (mu50 * mu50))
            sd50 = math.sqrt(var50)
            vol_z50 = float((v - mu50) / sd50) if sd50 > 0 else float("nan")

        spread_ticks = ((h - l) / tick) if tick > 0 else float("nan")

        # Update session
        sess_key = _session_id(ts, tz=tz, start_hhmm=spec.session.start_hhmm)
        if sess_key != state.session_key:
            state.session_key = sess_key
            state.trades_this_session = 0
            state.cooldown_left = 0

            # Reset session-scoped opening range tracking.
            or_high = float("nan")
            or_low = float("nan")
            or_complete = False
            sess_start_local = None
            if or_minutes > 0:
                try:
                    day_str = str(sess_key).split("@", 1)[0]
                    day_dt = datetime.fromisoformat(day_str)
                    start = int(spec.session.start_hhmm)
                    sess_start_local = datetime(day_dt.year, day_dt.month, day_dt.day, start // 100, start % 100, tzinfo=tz)
                except Exception:
                    sess_start_local = None

        # decrement cooldown once per bar
        if state.cooldown_left > 0:
            state.cooldown_left -= 1

        # Fill pending entry at bar OPEN
        if state.pending_action in {"BUY", "SELL"} and state.side == "FLAT":
            side = "LONG" if state.pending_action == "BUY" else "SHORT"
            qty = int(spec.risk.qty)
            entry_price = o
            sl_ticks = int(spec.risk.stop_loss_ticks)
            tp_ticks = int(spec.risk.take_profit_ticks)
            if side == "LONG":
                sl_price = entry_price - (sl_ticks * tick)
                tp_price = entry_price + (tp_ticks * tick)
            else:
                sl_price = entry_price + (sl_ticks * tick)
                tp_price = entry_price - (tp_ticks * tick)
            state.side = side
            state.qty = qty
            state.entry_price = entry_price
            state.entry_ts_utc = _to_z(ts)
            state.sl_price = sl_price
            state.tp_price = tp_price
            state.trades_taken += 1
            state.trades_this_session += 1
            state.cooldown_left = int(spec.gates.cooldown_bars)
            state.pending_action = "NONE"

        # Manage open position: SL/TP
        if state.side in {"LONG", "SHORT"} and state.qty > 0:
            exit_reason = ""
            exit_price = 0.0

            if state.side == "LONG":
                sl_hit = (spec.risk.stop_loss_ticks > 0) and (l <= state.sl_price)
                tp_hit = (spec.risk.take_profit_ticks > 0) and (h >= state.tp_price)
                if sl_hit and tp_hit:
                    # conservative: SL first
                    exit_reason = "SL"
                    exit_price = state.sl_price
                elif sl_hit:
                    exit_reason = "SL"
                    exit_price = state.sl_price
                elif tp_hit:
                    exit_reason = "TP"
                    exit_price = state.tp_price
            else:
                sl_hit = (spec.risk.stop_loss_ticks > 0) and (h >= state.sl_price)
                tp_hit = (spec.risk.take_profit_ticks > 0) and (l <= state.tp_price)
                if sl_hit and tp_hit:
                    exit_reason = "SL"
                    exit_price = state.sl_price
                elif sl_hit:
                    exit_reason = "SL"
                    exit_price = state.sl_price
                elif tp_hit:
                    exit_reason = "TP"
                    exit_price = state.tp_price

            if exit_reason:
                pnl_ticks = (exit_price - state.entry_price) / tick if tick > 0 else 0.0
                if state.side == "SHORT":
                    pnl_ticks = -pnl_ticks
                pnl_usd = float(pnl_ticks) * float(tick_value) * float(state.qty)
                state.realized_pnl_usd += pnl_usd
                state.equity_high = max(state.equity_high, state.realized_pnl_usd)
                state.max_drawdown_usd = max(state.max_drawdown_usd, state.equity_high - state.realized_pnl_usd)
                trades.append(
                    Trade(
                        side=state.side,
                        entry_ts_utc=state.entry_ts_utc,
                        entry_price=float(state.entry_price),
                        exit_ts_utc=_to_z(ts),
                        exit_price=float(exit_price),
                        qty=int(state.qty),
                        pnl_usd=float(pnl_usd),
                        exit_reason=exit_reason,
                    )
                )
                state.side = "FLAT"
                state.qty = 0
                state.entry_price = 0.0
                state.entry_ts_utc = ""
                state.sl_price = 0.0
                state.tp_price = 0.0
                hard_stop()

        # Feature update on close
        tr = _true_range(h, l, prev_close)
        prev_close = c

        if atr_warm < 14:
            atr = ((atr * atr_warm) + tr) / float(atr_warm + 1)
            atr_warm += 1
        else:
            atr = _atr_next(atr, tr, 14)

        if i == 0:
            ema_trend = c
            ema_pull = c
            ema_trend_prev = c
        else:
            ema_trend_prev = ema_trend
            ema_trend = _ema_next(ema_trend, c, ema_trend_len)
            ema_pull = _ema_next(ema_pull, c, ema_pull_len)

        # BOS windows (exclude current): update after decision stage; so compute using prior window values
        # We'll compute bos_hh/bos_ll from window, and then append current high/low after decision.
        bos_hh = max(hh_window) if hh_window else h
        bos_ll = min(ll_window) if ll_window else l

        # Decision on bar close (if flat)
        if state.side == "FLAT" and state.pending_action == "NONE":
            if not state.trading_enabled:
                state.skipped_hard_stop += 1
            elif not _in_session_window(ts, spec):
                state.skipped_session += 1
            elif spec.gates.max_trades_per_session > 0 and state.trades_this_session >= spec.gates.max_trades_per_session:
                state.skipped_max_trades += 1
            elif state.cooldown_left > 0:
                state.skipped_cooldown += 1
            else:
                atr_ticks = (atr / tick) if tick > 0 else 0.0
                if atr_warm < 14 or atr_ticks < float(spec.gates.min_atr_ticks):
                    state.skipped_atr += 1
                else:
                    decision = _evaluate_setup(
                        spec=spec,
                        setup_mem=state.setup_mem,
                        bar_index=i,
                        close=c,
                        open_=o,
                        high=h,
                        low=l,
                        volume=v,
                        ema_trend=ema_trend,
                        ema_trend_prev=ema_trend_prev,
                        ema_pull=ema_pull,
                        bos_hh=bos_hh,
                        bos_ll=bos_ll,
                        atr=atr,
                        tick_size=tick,
                        atr_ticks=atr_ticks,
                        range_high=range_high,
                        range_low=range_low,
                        rvol20=rvol20,
                        vol_z50=vol_z50,
                        spread_ticks=spread_ticks,
                        or_high=or_high,
                        or_low=or_low,
                        or_complete=or_complete,
                    )
                    if decision.action == "NONE":
                        pass
                    else:
                        state.signals_seen += 1
                        if decision.confidence < float(spec.gates.min_confidence):
                            state.skipped_confidence += 1
                        else:
                            # schedule entry next bar open
                            state.pending_action = decision.action
                            state.pending_conf = decision.confidence
                            state.pending_reason = decision.reason

        # Update BOS windows with current bar after decision
        hh_window.append(h)
        ll_window.append(l)
        if len(hh_window) > bos_n:
            hh_window.pop(0)
        if len(ll_window) > bos_n:
            ll_window.pop(0)

        # Update range windows with current bar after decision (avoid lookahead).
        if range_n > 0:
            range_h_window.append(h)
            range_l_window.append(l)

    # Close any open position at last close (EOD) for determinism
    if state.side in {"LONG", "SHORT"} and state.qty > 0 and bars:
        last = bars[-1]
        ts = last.ts_utc or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts = ts.astimezone(timezone.utc)
        exit_price = float(last.close or 0.0)
        pnl_ticks = (exit_price - state.entry_price) / tick if tick > 0 else 0.0
        if state.side == "SHORT":
            pnl_ticks = -pnl_ticks
        pnl_usd = float(pnl_ticks) * float(tick_value) * float(state.qty)
        state.realized_pnl_usd += pnl_usd
        state.equity_high = max(state.equity_high, state.realized_pnl_usd)
        state.max_drawdown_usd = max(state.max_drawdown_usd, state.equity_high - state.realized_pnl_usd)
        trades.append(
            Trade(
                side=state.side,
                entry_ts_utc=state.entry_ts_utc,
                entry_price=float(state.entry_price),
                exit_ts_utc=_to_z(ts),
                exit_price=float(exit_price),
                qty=int(state.qty),
                pnl_usd=float(pnl_usd),
                exit_reason="EOD",
            )
        )

    metrics = compute_metrics(trades=trades, realized_pnl=state.realized_pnl_usd, max_dd=state.max_drawdown_usd)
    metrics["counters"] = {
        "signals_seen": state.signals_seen,
        "trades_taken": state.trades_taken,
        "skipped_confidence": state.skipped_confidence,
        "skipped_atr": state.skipped_atr,
        "skipped_cooldown": state.skipped_cooldown,
        "skipped_session": state.skipped_session,
        "skipped_max_trades": state.skipped_max_trades,
        "skipped_hard_stop": state.skipped_hard_stop,
    }
    metrics["disabled_reason"] = state.disabled_reason
    return metrics, trades


def compute_metrics(*, trades: List[Trade], realized_pnl: float, max_dd: float) -> Dict[str, Any]:
    wins = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd < 0]
    gross_profit = sum(t.pnl_usd for t in wins)
    gross_loss = -sum(t.pnl_usd for t in losses)
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    winrate = (len(wins) / len(trades)) if trades else 0.0
    avg_trade = (sum(t.pnl_usd for t in trades) / len(trades)) if trades else 0.0
    expectancy = avg_trade
    return {
        "netPnL": float(realized_pnl),
        "maxDD": float(max_dd),
        "trades": int(len(trades)),
        "winrate": float(winrate),
        "profitFactor": float(pf) if pf != float("inf") else 9999.0,
        "avgTrade": float(avg_trade),
        "expectancy": float(expectancy),
        "grossProfit": float(gross_profit),
        "grossLoss": float(gross_loss),
    }
