from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.bot_factory.engine import run_backtest
from backend.contracts.bot_spec_v1 import BotSpecV1
from backend.database import Base, SessionLocal, engine
from backend.models import BotSpec, DataBar


@dataclass(frozen=True)
class BacktestSummary:
    bot_id: str
    name: str
    kind: str
    net_pnl: float
    max_dd: float
    trades: int
    profit_factor: float
    winrate: float


def _parse_day(s: str) -> datetime:
    d = datetime.fromisoformat(s.strip()).date()
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _load_bars(*, db, symbol: str, timeframe: str, start_day: str, end_day: str) -> List[DataBar]:
    start = _parse_day(start_day)
    end = _parse_day(end_day) + timedelta(days=1)
    return (
        db.query(DataBar)
        .filter(DataBar.symbol == symbol)
        .filter(DataBar.timeframe == timeframe)
        .filter(DataBar.ts_utc >= start)
        .filter(DataBar.ts_utc < end)
        .order_by(DataBar.ts_utc.asc())
        .all()
    )


def _upsert_spec(db, spec: BotSpecV1) -> None:
    row = db.query(BotSpec).filter(BotSpec.bot_id == spec.bot_id).first()
    if row is None:
        db.add(BotSpec(bot_id=spec.bot_id, spec_version=spec.version, spec=spec.dump_canonical()))
    else:
        row.spec_version = spec.version
        row.spec = spec.dump_canonical()


def _make_specs(symbol: str, timeframe: str) -> List[BotSpecV1]:
    base: Dict[str, Any] = {
        "version": "bot-spec.v1",
        "symbol": symbol,
        "timeframe": timeframe,
        "session": {"mode": "BOTH", "tz": "America/New_York", "start_hhmm": 930, "end_hhmm": 1600},
        "gates": {"min_confidence": 0.10, "min_atr_ticks": 6, "cooldown_bars": 2, "max_trades_per_session": 20},
        "risk": {"qty": 1, "stop_loss_ticks": 10, "take_profit_ticks": 12, "max_loss_usd": 1200.0},
        "tags": ["wyckoff", "specialist", "v1"],
    }

    presets: List[Dict[str, Any]] = [
        {
            "botId": "w8-01-spring",
            "name": "Wyckoff Specialist 01 - Spring (Accumulation)",
            "setup": {"kind": "wyckoff_spring", "range_lookback": 200, "buffer_ticks": 2, "min_rvol20": 1.10},
        },
        {
            "botId": "w8-02-upthrust",
            "name": "Wyckoff Specialist 02 - Upthrust (Distribution)",
            "setup": {"kind": "wyckoff_upthrust", "range_lookback": 200, "buffer_ticks": 2, "min_rvol20": 1.10},
        },
        {
            "botId": "w8-03-sos-lps",
            "name": "Wyckoff Specialist 03 - SOS + LPS",
            "setup": {
                "kind": "wyckoff_sos_lps",
                "range_lookback": 240,
                "breakout_buffer_ticks": 1,
                "pullback_buffer_ticks": 1,
                "min_rvol20_breakout": 1.20,
                "memory_bars": 120,
            },
            "risk": {"qty": 1, "stop_loss_ticks": 10, "take_profit_ticks": 18, "max_loss_usd": 1200.0},
            "gates": {"min_confidence": 0.10, "min_atr_ticks": 6, "cooldown_bars": 1, "max_trades_per_session": 10},
        },
        {
            "botId": "w8-04-sow-lpsy",
            "name": "Wyckoff Specialist 04 - SOW + LPSY",
            "setup": {
                "kind": "wyckoff_sow_lpsy",
                "range_lookback": 240,
                "breakout_buffer_ticks": 1,
                "pullback_buffer_ticks": 1,
                "min_rvol20_breakout": 1.20,
                "memory_bars": 120,
            },
            "risk": {"qty": 1, "stop_loss_ticks": 10, "take_profit_ticks": 18, "max_loss_usd": 1200.0},
            "gates": {"min_confidence": 0.10, "min_atr_ticks": 6, "cooldown_bars": 1, "max_trades_per_session": 10},
        },
        {
            "botId": "w8-05-selling-climax",
            "name": "Wyckoff Specialist 05 - VSA Selling Climax",
            "setup": {"kind": "vsa_selling_climax", "min_vol_z50": 2.0, "min_spread_ticks": 10, "close_pos_max": 0.35},
            "risk": {"qty": 1, "stop_loss_ticks": 14, "take_profit_ticks": 14, "max_loss_usd": 1200.0},
            "gates": {"min_confidence": 0.10, "min_atr_ticks": 4, "cooldown_bars": 2, "max_trades_per_session": 8},
        },
        {
            "botId": "w8-06-buying-climax",
            "name": "Wyckoff Specialist 06 - VSA Buying Climax",
            "setup": {"kind": "vsa_buying_climax", "min_vol_z50": 2.0, "min_spread_ticks": 10, "close_pos_min": 0.65},
            "risk": {"qty": 1, "stop_loss_ticks": 14, "take_profit_ticks": 14, "max_loss_usd": 1200.0},
            "gates": {"min_confidence": 0.10, "min_atr_ticks": 4, "cooldown_bars": 2, "max_trades_per_session": 8},
        },
        {
            "botId": "w8-07-contraction-breakout",
            "name": "Wyckoff Specialist 07 - Contraction -> Breakout",
            "setup": {
                "kind": "wyckoff_contraction_breakout",
                "range_lookback": 240,
                "contraction_bars": 25,
                "max_atr_ticks": 8,
                "buffer_ticks": 1,
                "min_rvol20": 1.05,
            },
            "gates": {"min_confidence": 0.10, "min_atr_ticks": 2, "cooldown_bars": 1, "max_trades_per_session": 12},
            "risk": {"qty": 1, "stop_loss_ticks": 10, "take_profit_ticks": 16, "max_loss_usd": 1200.0},
        },
        {
            "botId": "w8-08-trend-pullback-bos",
            "name": "Wyckoff Specialist 08 - Trend Pullback + BOS",
            "setup": {"kind": "trend_pullback_bos", "ema_trend_len": 200, "ema_pullback_len": 20, "bos_lookback": 10},
        },
    ]

    out: List[BotSpecV1] = []
    for p in presets:
        merged = dict(base)
        merged.update(p)
        out.append(BotSpecV1.model_validate(merged))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Create 8 Wyckoff specialist bots and run offline backtests.")
    ap.add_argument("--symbol", default="MNQ")
    ap.add_argument("--timeframe", default="1m")
    ap.add_argument("--start-day", required=True)
    ap.add_argument("--end-day", required=True)
    ap.add_argument("--print-specs", action="store_true")
    args = ap.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        symbol = str(args.symbol).upper().strip()
        timeframe = str(args.timeframe).lower().strip()

        bars = _load_bars(db=db, symbol=symbol, timeframe=timeframe, start_day=args.start_day, end_day=args.end_day)
        if not bars:
            raise SystemExit(f"no data_bars for {symbol} {timeframe} in range {args.start_day}..{args.end_day}")

        specs = _make_specs(symbol=symbol, timeframe=timeframe)
        for spec in specs:
            _upsert_spec(db, spec)
        db.commit()

        summaries: List[BacktestSummary] = []
        for spec in specs:
            metrics, _trades = run_backtest(spec=spec, bars=bars)
            summaries.append(
                BacktestSummary(
                    bot_id=spec.bot_id,
                    name=spec.name,
                    kind=spec.setup.kind,
                    net_pnl=float(metrics.get("netPnL") or 0.0),
                    max_dd=float(metrics.get("maxDD") or 0.0),
                    trades=int(metrics.get("trades") or 0),
                    profit_factor=float(metrics.get("profitFactor") or 0.0),
                    winrate=float(metrics.get("winrate") or 0.0),
                )
            )

        summaries.sort(key=lambda s: (s.net_pnl, -s.max_dd), reverse=True)

        print(f"bars={len(bars)} symbol={symbol} timeframe={timeframe} range={args.start_day}..{args.end_day}")
        for s in summaries:
            print(
                f"{s.bot_id:>22}  kind={s.kind:<26}  netPnL={s.net_pnl:>9.2f}  "
                f"maxDD={s.max_dd:>8.2f}  trades={s.trades:>4}  pf={s.profit_factor:>6.2f}  winrate={s.winrate:>5.2f}"
            )

        if args.print_specs:
            print("\n--- specs ---")
            print(json.dumps([sp.dump_canonical() for sp in specs], indent=2))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

