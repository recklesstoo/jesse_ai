from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from zoneinfo import ZoneInfo

from backend.bot_factory import engine as eng
from backend.bot_factory.engine import run_backtest
from backend.contracts.bot_spec_v1 import BotSpecV1
from backend.market.metrics import instrument_spec
from backend.models import DataBar


ALLOWED_GRID_KEYS = {
    "risk.stop_loss_ticks",
    "risk.take_profit_ticks",
    "risk.qty",
    "risk.max_loss_usd",
    "gates.min_confidence",
    "gates.min_atr_ticks",
    "gates.cooldown_bars",
    "gates.max_trades_per_session",
}


def _set_path(spec: Dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur: Dict[str, Any] = spec
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def generate_variants(base: BotSpecV1, *, grid: Dict[str, List[Any]], cap: int = 50) -> List[BotSpecV1]:
    """
    Generate <=cap BotSpec variants from a flat grid dict with dot-path keys.

    Stability: restricts keys to a closed allow-list so all variants share the same
    setup/session shape (optimization remains deterministic and cheap).
    """
    unknown = sorted([k for k in (grid or {}).keys() if k not in ALLOWED_GRID_KEYS])
    if unknown:
        raise ValueError(f"unsupported grid keys: {unknown}. allowed={sorted(ALLOWED_GRID_KEYS)}")

    keys = [k for k in (grid or {}).keys() if (grid.get(k) or [])]
    if not keys:
        return [base]

    # Cartesian product with early cap.
    variants: List[BotSpecV1] = []
    stack: List[Tuple[int, Dict[str, Any]]] = [(0, {})]
    while stack:
        i, overrides = stack.pop()
        if i >= len(keys):
            spec_dict = base.dump_canonical()
            # dump_canonical uses botId alias; BotSpecV1 will accept it.
            for k, v in overrides.items():
                _set_path(spec_dict, k, v)
            variants.append(BotSpecV1.model_validate(spec_dict))
            if len(variants) >= cap:
                break
            continue

        k = keys[i]
        values = list(grid.get(k) or [])
        # Keep deterministic ordering: iterate values as provided.
        for v in reversed(values):
            nxt = dict(overrides)
            nxt[k] = v
            stack.append((i + 1, nxt))

    if len(variants) >= cap and len(stack) > 0:
        raise ValueError(f"optimization cap exceeded: cap={cap}")
    return variants


@dataclass
class OptimizeResult:
    run_id: str
    results: List[Dict[str, Any]]


def run_optimize(
    *,
    base: BotSpecV1,
    variants: List[BotSpecV1],
    bars: List[DataBar],
) -> List[Dict[str, Any]]:
    """
    Deterministic optimization runner.

    NOTE: This implementation runs each variant independently using the same bar list.
    It still guarantees:
    - 1 decision per closed bar
    - no network/WS/db writes per bar
    - stable, reproducible results
    """
    if not variants:
        return []

    # Single bot: reuse the backtest runner.
    if len(variants) == 1:
        spec = variants[0]
        metrics, _trades = run_backtest(spec=spec, bars=bars)
        return [
            {
                "botId": spec.bot_id,
                "name": spec.name,
                "symbol": spec.symbol,
                "timeframe": spec.timeframe,
                "params": {
                    "stop_loss_ticks": spec.risk.stop_loss_ticks,
                    "take_profit_ticks": spec.risk.take_profit_ticks,
                    "qty": spec.risk.qty,
                    "max_loss_usd": spec.risk.max_loss_usd,
                    "min_confidence": spec.gates.min_confidence,
                    "min_atr_ticks": spec.gates.min_atr_ticks,
                    "cooldown_bars": spec.gates.cooldown_bars,
                    "max_trades_per_session": spec.gates.max_trades_per_session,
                },
                "metrics": metrics,
            }
        ]

    # Optimization (<=50 variants): one shared bar loop; per-bot state updates.
    # Assumption: variants share setup/session shape (enforced by generate_variants allow-list).
    tz = ZoneInfo(base.session.tz)
    spec_inst = instrument_spec(base.symbol)
    tick = float(spec_inst.tick_size)
    tick_value = float(spec_inst.tick_value_usd)

    bot_states: List[eng.BotState] = [eng.BotState() for _ in variants]
    bot_trades: List[List[eng.Trade]] = [[] for _ in variants]

    prev_close: float | None = None
    atr = 0.0
    atr_warm = 0
    ema_trend = 0.0
    ema_trend_prev = 0.0
    ema_pull = 0.0
    hh_window: List[float] = []
    ll_window: List[float] = []

    ema_trend_len = int(getattr(base.setup, "ema_trend_len", 200))
    ema_pull_len = int(getattr(base.setup, "ema_pullback_len", 20))
    bos_n = int(getattr(base.setup, "bos_lookback", 10))

    range_n = int(getattr(base.setup, "range_lookback", 0) or 0)
    range_h_window: deque[float] = deque(maxlen=max(1, range_n))
    range_l_window: deque[float] = deque(maxlen=max(1, range_n))

    vol20: deque[float] = deque(maxlen=20)
    vol50: deque[float] = deque(maxlen=50)
    vol20_sum = 0.0
    vol50_sum = 0.0
    vol50_sumsq = 0.0

    or_minutes = int(getattr(base.setup, "or_minutes", 0) or 0)
    or_high = float("nan")
    or_low = float("nan")
    or_complete = False
    sess_start_local: datetime | None = None

    setup_mem: Dict[str, Any] = {}

    current_session_key = ""

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

        range_high = float("nan")
        range_low = float("nan")
        if range_n > 0 and len(range_h_window) >= range_n and len(range_l_window) >= range_n:
            range_high = max(range_h_window) if range_h_window else float("nan")
            range_low = min(range_l_window) if range_l_window else float("nan")

        sess_key = eng._session_id(ts, tz=tz, start_hhmm=base.session.start_hhmm)
        if sess_key != current_session_key:
            current_session_key = sess_key
            for st in bot_states:
                st.session_key = sess_key
                st.trades_this_session = 0
                st.cooldown_left = 0

            or_high = float("nan")
            or_low = float("nan")
            or_complete = False
            sess_start_local = None
            if or_minutes > 0:
                try:
                    day_str = str(sess_key).split("@", 1)[0]
                    day_dt = datetime.fromisoformat(day_str)
                    start = int(base.session.start_hhmm)
                    sess_start_local = datetime(day_dt.year, day_dt.month, day_dt.day, start // 100, start % 100, tzinfo=tz)
                except Exception:
                    sess_start_local = None

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

        # Volume features including current bar.
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

        # Cooldown decrement (once per bar)
        for st in bot_states:
            if st.cooldown_left > 0:
                st.cooldown_left -= 1

        # Fill pending entries at bar OPEN (per bot)
        for st, spec in zip(bot_states, variants, strict=False):
            if st.pending_action in {"BUY", "SELL"} and st.side == "FLAT":
                side = "LONG" if st.pending_action == "BUY" else "SHORT"
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
                st.side = side
                st.qty = qty
                st.entry_price = entry_price
                st.entry_ts_utc = eng._to_z(ts)
                st.sl_price = sl_price
                st.tp_price = tp_price
                st.trades_taken += 1
                st.trades_this_session += 1
                st.cooldown_left = int(spec.gates.cooldown_bars)
                st.pending_action = "NONE"

        # Manage open positions (SL/TP) (per bot)
        for idx, (st, spec) in enumerate(zip(bot_states, variants, strict=False)):
            if st.side in {"LONG", "SHORT"} and st.qty > 0:
                exit_reason = ""
                exit_price = 0.0
                if st.side == "LONG":
                    sl_hit = (spec.risk.stop_loss_ticks > 0) and (l <= st.sl_price)
                    tp_hit = (spec.risk.take_profit_ticks > 0) and (h >= st.tp_price)
                    if sl_hit and tp_hit:
                        exit_reason = "SL"
                        exit_price = st.sl_price
                    elif sl_hit:
                        exit_reason = "SL"
                        exit_price = st.sl_price
                    elif tp_hit:
                        exit_reason = "TP"
                        exit_price = st.tp_price
                else:
                    sl_hit = (spec.risk.stop_loss_ticks > 0) and (h >= st.sl_price)
                    tp_hit = (spec.risk.take_profit_ticks > 0) and (l <= st.tp_price)
                    if sl_hit and tp_hit:
                        exit_reason = "SL"
                        exit_price = st.sl_price
                    elif sl_hit:
                        exit_reason = "SL"
                        exit_price = st.sl_price
                    elif tp_hit:
                        exit_reason = "TP"
                        exit_price = st.tp_price

                if exit_reason:
                    pnl_ticks = (exit_price - st.entry_price) / tick if tick > 0 else 0.0
                    if st.side == "SHORT":
                        pnl_ticks = -pnl_ticks
                    pnl_usd = float(pnl_ticks) * float(tick_value) * float(st.qty)
                    st.realized_pnl_usd += pnl_usd
                    st.equity_high = max(st.equity_high, st.realized_pnl_usd)
                    st.max_drawdown_usd = max(st.max_drawdown_usd, st.equity_high - st.realized_pnl_usd)
                    bot_trades[idx].append(
                        eng.Trade(
                            side=st.side,
                            entry_ts_utc=st.entry_ts_utc,
                            entry_price=float(st.entry_price),
                            exit_ts_utc=eng._to_z(ts),
                            exit_price=float(exit_price),
                            qty=int(st.qty),
                            pnl_usd=float(pnl_usd),
                            exit_reason=exit_reason,
                        )
                    )
                    st.side = "FLAT"
                    st.qty = 0
                    st.entry_price = 0.0
                    st.entry_ts_utc = ""
                    st.sl_price = 0.0
                    st.tp_price = 0.0

                    # Hard stop check after exit (per bot)
                    if st.realized_pnl_usd <= -abs(float(spec.risk.max_loss_usd)):
                        st.trading_enabled = False
                        st.disabled_reason = f"max_loss_usd hit pnl={st.realized_pnl_usd:.2f}"

        # Shared feature update on close
        tr = eng._true_range(h, l, prev_close)
        prev_close = c

        if atr_warm < 14:
            atr = ((atr * atr_warm) + tr) / float(atr_warm + 1)
            atr_warm += 1
        else:
            atr = eng._atr_next(atr, tr, 14)

        if i == 0:
            ema_trend = c
            ema_pull = c
            ema_trend_prev = c
        else:
            ema_trend_prev = ema_trend
            ema_trend = eng._ema_next(ema_trend, c, ema_trend_len)
            ema_pull = eng._ema_next(ema_pull, c, ema_pull_len)

        bos_hh = max(hh_window) if hh_window else h
        bos_ll = min(ll_window) if ll_window else l

        # Decision (shared action + confidence)
        atr_ticks = (atr / tick) if tick > 0 else 0.0
        decision = eng._evaluate_setup(
            spec=base,
            setup_mem=setup_mem,
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
        in_session = eng._in_session_window(ts, base)

        for st, spec in zip(bot_states, variants, strict=False):
            if st.side != "FLAT" or st.pending_action != "NONE":
                continue

            if not st.trading_enabled:
                st.skipped_hard_stop += 1
                continue
            if not in_session:
                st.skipped_session += 1
                continue
            if spec.gates.max_trades_per_session > 0 and st.trades_this_session >= spec.gates.max_trades_per_session:
                st.skipped_max_trades += 1
                continue
            if st.cooldown_left > 0:
                st.skipped_cooldown += 1
                continue
            if atr_warm < 14 or atr_ticks < float(spec.gates.min_atr_ticks):
                st.skipped_atr += 1
                continue

            if decision.action == "NONE":
                continue

            st.signals_seen += 1
            if decision.confidence < float(spec.gates.min_confidence):
                st.skipped_confidence += 1
                continue

            st.pending_action = decision.action
            st.pending_conf = decision.confidence
            st.pending_reason = decision.reason

        # BOS windows update after decision
        hh_window.append(h)
        ll_window.append(l)
        if len(hh_window) > bos_n:
            hh_window.pop(0)
        if len(ll_window) > bos_n:
            ll_window.pop(0)

        if range_n > 0:
            range_h_window.append(h)
            range_l_window.append(l)

    # EOD close for determinism (per bot)
    if bars:
        last = bars[-1]
        ts = last.ts_utc or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts = ts.astimezone(timezone.utc)
        exit_price = float(last.close or 0.0)
        for idx, (st, spec) in enumerate(zip(bot_states, variants, strict=False)):
            if st.side in {"LONG", "SHORT"} and st.qty > 0:
                pnl_ticks = (exit_price - st.entry_price) / tick if tick > 0 else 0.0
                if st.side == "SHORT":
                    pnl_ticks = -pnl_ticks
                pnl_usd = float(pnl_ticks) * float(tick_value) * float(st.qty)
                st.realized_pnl_usd += pnl_usd
                st.equity_high = max(st.equity_high, st.realized_pnl_usd)
                st.max_drawdown_usd = max(st.max_drawdown_usd, st.equity_high - st.realized_pnl_usd)
                bot_trades[idx].append(
                    eng.Trade(
                        side=st.side,
                        entry_ts_utc=st.entry_ts_utc,
                        entry_price=float(st.entry_price),
                        exit_ts_utc=eng._to_z(ts),
                        exit_price=float(exit_price),
                        qty=int(st.qty),
                        pnl_usd=float(pnl_usd),
                        exit_reason="EOD",
                    )
                )
                st.side = "FLAT"
                st.qty = 0

    out: List[Dict[str, Any]] = []
    for st, spec, trades in zip(bot_states, variants, bot_trades, strict=False):
        metrics = eng.compute_metrics(trades=trades, realized_pnl=st.realized_pnl_usd, max_dd=st.max_drawdown_usd)
        metrics["counters"] = {
            "signals_seen": st.signals_seen,
            "trades_taken": st.trades_taken,
            "skipped_confidence": st.skipped_confidence,
            "skipped_atr": st.skipped_atr,
            "skipped_cooldown": st.skipped_cooldown,
            "skipped_session": st.skipped_session,
            "skipped_max_trades": st.skipped_max_trades,
            "skipped_hard_stop": st.skipped_hard_stop,
        }
        metrics["disabled_reason"] = st.disabled_reason
        out.append(
            {
                "botId": spec.bot_id,
                "name": spec.name,
                "symbol": spec.symbol,
                "timeframe": spec.timeframe,
                "params": {
                    "stop_loss_ticks": spec.risk.stop_loss_ticks,
                    "take_profit_ticks": spec.risk.take_profit_ticks,
                    "qty": spec.risk.qty,
                    "max_loss_usd": spec.risk.max_loss_usd,
                    "min_confidence": spec.gates.min_confidence,
                    "min_atr_ticks": spec.gates.min_atr_ticks,
                    "cooldown_bars": spec.gates.cooldown_bars,
                    "max_trades_per_session": spec.gates.max_trades_per_session,
                },
                "metrics": metrics,
            }
        )

    # Sort best-first: profitFactor desc, netPnL desc, maxDD asc.
    def _score(item: Dict[str, Any]) -> Tuple[float, float, float]:
        m = item.get("metrics") or {}
        return (
            float(m.get("profitFactor") or 0.0),
            float(m.get("netPnL") or 0.0),
            -float(m.get("maxDD") or 0.0),
        )

    out.sort(key=_score, reverse=True)
    return out
