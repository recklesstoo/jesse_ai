from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.bot_factory.engine import run_backtest
from backend.bot_factory.optimize import generate_variants, run_optimize
from backend.contracts.bot_spec_v1 import BotSpecV1
from backend.database import SessionLocal, get_db
from backend.market.metrics import instrument_spec
from backend.models import BacktestRun, BotSpec, DataBar, OptimizeRun


router = APIRouter()


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_day(s: str) -> date:
    try:
        return date.fromisoformat(str(s).strip())
    except Exception:
        raise HTTPException(status_code=400, detail=f"invalid day (expected YYYY-MM-DD): {s!r}")


def _parse_range(payload: Dict[str, Any]) -> tuple[datetime, datetime]:
    start_day = payload.get("startDay") or payload.get("start_day")
    end_day = payload.get("endDay") or payload.get("end_day")
    if not start_day or not end_day:
        raise HTTPException(status_code=400, detail="startDay and endDay are required (YYYY-MM-DD)")

    sd = _parse_day(start_day)
    ed = _parse_day(end_day)
    if ed < sd:
        raise HTTPException(status_code=400, detail="endDay must be >= startDay")

    start = datetime(sd.year, sd.month, sd.day, tzinfo=timezone.utc)
    end = datetime(ed.year, ed.month, ed.day, tzinfo=timezone.utc) + timedelta(days=1)
    return start, end


def _load_spec(db: Session, bot_id: str) -> BotSpecV1:
    row = db.query(BotSpec).filter(BotSpec.bot_id == bot_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"bot not found: {bot_id}")
    try:
        return BotSpecV1.model_validate(row.spec or {})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"stored BotSpec invalid: {exc}")


def _load_bars(db: Session, *, symbol: str, timeframe: str, start_utc: datetime, end_utc: datetime) -> List[DataBar]:
    q = (
        db.query(DataBar)
        .filter(DataBar.symbol == symbol)
        .filter(DataBar.timeframe == timeframe)
        .filter(DataBar.ts_utc >= start_utc)
        .filter(DataBar.ts_utc < end_utc)
        .order_by(DataBar.ts_utc.asc())
    )
    return list(q.all())


class BacktestRunRequest(BaseModel):
    botId: str = Field(default="bot-1")
    startDay: str
    endDay: str


class OptimizeRunRequest(BaseModel):
    botId: str = Field(default="bot-1")
    startDay: str
    endDay: str
    grid: Dict[str, List[Any]] = Field(default_factory=dict)


class InstructBotsRequest(BaseModel):
    symbol: str = Field(default="MNQ")
    timeframe: str = Field(default="1m", description="1m|5m")
    startDay: str
    endDay: str
    botIdPrefix: str = Field(default="ai-wyckoff")
    maxBots: int = Field(default=8, ge=1, le=20)
    create: bool = True
    backtest: bool = True


def _clamp_int(v: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, int(round(float(v))))))


def _market_stats(*, bars: List[DataBar], tick: float) -> Dict[str, Any]:
    closes = np.array([float(b.close or 0.0) for b in bars], dtype=float)
    highs = np.array([float(b.high or 0.0) for b in bars], dtype=float)
    lows = np.array([float(b.low or 0.0) for b in bars], dtype=float)
    vols = np.array([float(b.volume or 0.0) for b in bars], dtype=float)

    # True range ticks (uses previous close)
    prev_close = np.roll(closes, 1)
    prev_close[0] = closes[0] if len(closes) else 0.0
    tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_close), np.abs(lows - prev_close)))
    tr_ticks = (tr / tick) if tick > 0 else np.zeros_like(tr)

    atr_median = float(np.median(tr_ticks)) if len(tr_ticks) else 0.0
    atr_p90 = float(np.percentile(tr_ticks, 90)) if len(tr_ticks) else 0.0

    vol_mu = float(np.mean(vols)) if len(vols) else 0.0
    vol_sd = float(np.std(vols)) if len(vols) else 0.0
    vol_cv = float(vol_sd / vol_mu) if vol_mu > 0 else 0.0

    # Trend score: linear regression r2 + slope normalized by ATR (very rough proxy).
    trend_r2 = 0.0
    trend_slope_atr = 0.0
    if len(closes) >= 60:
        n = min(300, len(closes))
        y = closes[-n:]
        x = np.arange(n, dtype=float)
        x_mu = float(np.mean(x))
        y_mu = float(np.mean(y))
        cov = float(np.sum((x - x_mu) * (y - y_mu)))
        var = float(np.sum((x - x_mu) ** 2))
        b = 0.0 if var <= 0 else cov / var
        a = y_mu - b * x_mu
        y_hat = a + b * x
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - y_mu) ** 2))
        trend_r2 = 0.0 if ss_tot <= 0 else max(0.0, min(1.0, 1.0 - ss_res / ss_tot))
        atr_norm = float(np.median(tr_ticks[-n:])) if len(tr_ticks) >= n else atr_median
        trend_slope_atr = float((b / tick) / max(1.0, atr_norm)) if tick > 0 else 0.0

    return {
        "bars": int(len(bars)),
        "atr_ticks_median": atr_median,
        "atr_ticks_p90": atr_p90,
        "vol_mu": vol_mu,
        "vol_cv": vol_cv,
        "trend_r2": trend_r2,
        "trend_slope_atr": trend_slope_atr,
    }


def _suggest_specs(*, req: InstructBotsRequest, stats: Dict[str, Any]) -> List[BotSpecV1]:
    tick = instrument_spec(req.symbol).tick_size
    atr_med = float(stats.get("atr_ticks_median") or 0.0)
    atr_p90 = float(stats.get("atr_ticks_p90") or 0.0)
    vol_cv = float(stats.get("vol_cv") or 0.0)
    trend_r2 = float(stats.get("trend_r2") or 0.0)
    trend_slope_atr = float(stats.get("trend_slope_atr") or 0.0)

    # Heuristic knobs derived from market stats (kept conservative).
    buffer_ticks = _clamp_int(max(1.0, atr_med * 0.15), 1, 4)
    entry_band_ticks = _clamp_int(max(2.0, atr_med * 0.4), 2, 10)
    range_lookback = _clamp_int(120 + (atr_p90 * 2.0), 120, 400)
    min_rvol = float(max(1.05, min(1.25, 1.05 + vol_cv * 0.15)))

    # Choose a mix of setups. If trend is strong, include more trend/breakout; else more range/mean-reversion.
    is_trending = (trend_r2 >= 0.20 and abs(trend_slope_atr) >= 0.03)

    setups: List[Dict[str, Any]] = []
    if is_trending:
        setups.extend(
            [
                {"kind": "trend_pullback_bos", "ema_trend_len": 200, "ema_pullback_len": 20, "bos_lookback": 10},
                {"kind": "opening_range_breakout", "or_minutes": 15, "buffer_ticks": buffer_ticks, "min_rvol20": min_rvol},
                {
                    "kind": "wyckoff_contraction_breakout",
                    "range_lookback": range_lookback,
                    "contraction_bars": 25,
                    "max_atr_ticks": _clamp_int(max(6.0, atr_med * 0.9), 4, 14),
                    "buffer_ticks": buffer_ticks,
                    "min_rvol20": min_rvol,
                },
            ]
        )
    else:
        setups.extend(
            [
                {"kind": "wyckoff_range_reversion", "range_lookback": range_lookback, "entry_band_ticks": entry_band_ticks, "side": "BOTH"},
                {"kind": "wyckoff_spring", "range_lookback": range_lookback, "buffer_ticks": buffer_ticks, "min_rvol20": max(1.10, min_rvol)},
                {"kind": "wyckoff_upthrust", "range_lookback": range_lookback, "buffer_ticks": buffer_ticks, "min_rvol20": max(1.10, min_rvol)},
            ]
        )

    # Always include core Wyckoff event specialists (works in both regimes).
    setups.extend(
        [
            {
                "kind": "wyckoff_sos_lps",
                "range_lookback": range_lookback,
                "breakout_buffer_ticks": buffer_ticks,
                "pullback_buffer_ticks": buffer_ticks,
                "min_rvol20_breakout": max(1.15, min_rvol),
                "memory_bars": 120,
            },
            {
                "kind": "wyckoff_sow_lpsy",
                "range_lookback": range_lookback,
                "breakout_buffer_ticks": buffer_ticks,
                "pullback_buffer_ticks": buffer_ticks,
                "min_rvol20_breakout": max(1.15, min_rvol),
                "memory_bars": 120,
            },
            {"kind": "vsa_selling_climax", "min_vol_z50": 2.0, "min_spread_ticks": _clamp_int(max(8.0, atr_med * 1.1), 6, 18), "close_pos_max": 0.35},
            {"kind": "vsa_buying_climax", "min_vol_z50": 2.0, "min_spread_ticks": _clamp_int(max(8.0, atr_med * 1.1), 6, 18), "close_pos_min": 0.65},
        ]
    )

    # Ensure we can reach maxBots by adding deterministic fallbacks (no duplicates by kind).
    wanted = int(req.maxBots)
    existing_kinds = {str(s.get("kind")) for s in setups if isinstance(s, dict) and s.get("kind")}
    fallbacks: List[Dict[str, Any]] = [
        {"kind": "opening_range_breakout", "or_minutes": 15, "buffer_ticks": buffer_ticks, "min_rvol20": min_rvol},
        {"kind": "wyckoff_range_reversion", "range_lookback": range_lookback, "entry_band_ticks": entry_band_ticks, "side": "BOTH"},
        {"kind": "trend_pullback_bos", "ema_trend_len": 200, "ema_pullback_len": 20, "bos_lookback": 10},
        {"kind": "wyckoff_spring", "range_lookback": range_lookback, "buffer_ticks": buffer_ticks, "min_rvol20": max(1.10, min_rvol)},
        {"kind": "wyckoff_upthrust", "range_lookback": range_lookback, "buffer_ticks": buffer_ticks, "min_rvol20": max(1.10, min_rvol)},
    ]
    for f in fallbacks:
        if len(setups) >= wanted:
            break
        k = str(f.get("kind"))
        if k and k not in existing_kinds:
            setups.append(f)
            existing_kinds.add(k)

    setups = setups[:wanted]

    base: Dict[str, Any] = {
        "version": "bot-spec.v1",
        "symbol": req.symbol.upper().strip(),
        "timeframe": req.timeframe.strip().lower(),
        "session": {"mode": "BOTH", "tz": "America/New_York", "start_hhmm": 930, "end_hhmm": 1600},
        "risk": {
            "qty": 1,
            "stop_loss_ticks": _clamp_int(max(8.0, atr_med * 1.1), 6, 24),
            "take_profit_ticks": _clamp_int(max(10.0, atr_med * 1.4), 8, 36),
            "max_loss_usd": 1200.0,
        },
        "gates": {"min_confidence": 0.10, "min_atr_ticks": _clamp_int(max(2.0, atr_med * 0.5), 0, 20), "cooldown_bars": 2, "max_trades_per_session": 20},
        "tags": ["auto", "wyckoff", "data_driven", "v1"],
    }

    out: List[BotSpecV1] = []
    for idx, setup in enumerate(setups, start=1):
        spec = dict(base)
        spec["botId"] = f"{req.botIdPrefix}-{idx:02d}"
        spec["name"] = f"AutoWyckoff {idx:02d} ({setup.get('kind')})"
        spec["setup"] = setup
        out.append(BotSpecV1.model_validate(spec))
    return out


@router.post("/api/v1/bots/instruct")
async def instruct_bots(payload: InstructBotsRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    symbol = (payload.symbol or "MNQ").upper().strip()
    timeframe = str(payload.timeframe or "1m").strip().lower()
    if timeframe not in {"1m", "5m"}:
        raise HTTPException(status_code=400, detail="timeframe must be 1m or 5m")

    start_utc, end_utc = _parse_range(payload.model_dump())
    bars = _load_bars(db, symbol=symbol, timeframe=timeframe, start_utc=start_utc, end_utc=end_utc)
    if not bars:
        raise HTTPException(status_code=400, detail="no_data_bars")

    tick = float(instrument_spec(symbol).tick_size)
    stats = _market_stats(bars=bars, tick=tick)
    specs = _suggest_specs(req=payload, stats=stats)

    results: List[Dict[str, Any]] = []
    for spec in specs:
        if payload.create:
            row = db.query(BotSpec).filter(BotSpec.bot_id == spec.bot_id).first()
            if row is None:
                row = BotSpec(bot_id=spec.bot_id, spec_version=spec.version, spec=spec.dump_canonical())
                db.add(row)
            else:
                row.spec_version = spec.version
                row.spec = spec.dump_canonical()
        metrics = None
        if payload.backtest:
            m, _trades = run_backtest(spec=spec, bars=bars)
            metrics = m
        results.append({"botId": spec.bot_id, "spec": spec.dump_canonical(), "metrics": metrics})

    if payload.create:
        db.commit()

    # Sort best-first when we have metrics.
    def _score(item: Dict[str, Any]) -> float:
        m = item.get("metrics") or {}
        return float(m.get("netPnL") or 0.0)

    if payload.backtest:
        results.sort(key=_score, reverse=True)

    return {"ok": True, "symbol": symbol, "timeframe": timeframe, "range": {"startDay": payload.startDay, "endDay": payload.endDay}, "stats": stats, "bots": results, "ts_utc": _utc_iso()}


@router.get("/api/v1/bots/specs")
async def list_bots(db: Session = Depends(get_db)) -> Dict[str, Any]:
    rows = db.query(BotSpec).order_by(BotSpec.updated_at_utc.desc()).all()
    bots: List[Dict[str, Any]] = []
    for r in rows:
        spec = r.spec or {}
        setup = spec.get("setup") if isinstance(spec, dict) else {}
        kind = setup.get("kind") if isinstance(setup, dict) else None
        bots.append(
            {
                "botId": r.bot_id,
                "spec_version": r.spec_version,
                "name": spec.get("name") if isinstance(spec, dict) else None,
                "symbol": spec.get("symbol") if isinstance(spec, dict) else None,
                "timeframe": spec.get("timeframe") if isinstance(spec, dict) else None,
                "setup_kind": kind,
                "tags": spec.get("tags") if isinstance(spec, dict) else None,
                "updated_at_utc": r.updated_at_utc.isoformat().replace("+00:00", "Z") if r.updated_at_utc else None,
                "created_at_utc": r.created_at_utc.isoformat().replace("+00:00", "Z") if r.created_at_utc else None,
            }
        )
    return {"ok": True, "count": len(bots), "bots": bots, "ts_utc": _utc_iso()}


@router.post("/api/v1/bots")
async def create_bot(spec: BotSpecV1, db: Session = Depends(get_db)) -> Dict[str, Any]:
    bot_id = (spec.bot_id or "").strip()
    if not bot_id:
        raise HTTPException(status_code=400, detail="botId required")

    row = db.query(BotSpec).filter(BotSpec.bot_id == bot_id).first()
    if row is None:
        row = BotSpec(bot_id=bot_id, spec_version=spec.version, spec=spec.dump_canonical())
        db.add(row)
    else:
        row.spec_version = spec.version
        row.spec = spec.dump_canonical()
    db.commit()

    return {"ok": True, "botId": bot_id, "spec": spec.dump_canonical(), "ts_utc": _utc_iso()}


@router.get("/api/v1/bots/{botId}")
async def get_bot(botId: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    bot_id = (botId or "").strip()
    row = db.query(BotSpec).filter(BotSpec.bot_id == bot_id).first()
    if not row:
        return {"ok": False, "botId": bot_id, "error": "not_found", "ts_utc": _utc_iso()}
    return {"ok": True, "botId": bot_id, "spec": row.spec, "spec_version": row.spec_version, "ts_utc": _utc_iso()}


@router.post("/api/v1/backtest/run")
async def backtest_run(payload: BacktestRunRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    bot_id = (payload.botId or "").strip()
    if not bot_id:
        raise HTTPException(status_code=400, detail="botId required")

    start_utc, end_utc = _parse_range(payload.model_dump())
    spec = _load_spec(db, bot_id)

    run_id = f"bt_{uuid.uuid4().hex}"
    db.add(
        BacktestRun(
            id=run_id,
            bot_id=bot_id,
            started_at_utc=datetime.now(timezone.utc),
            status="RUNNING",
            params={"startDay": payload.startDay, "endDay": payload.endDay, "symbol": spec.symbol, "timeframe": spec.timeframe},
            metrics=None,
            error=None,
        )
    )
    db.commit()

    async def _worker() -> None:
        local = SessionLocal()
        try:
            spec_local = _load_spec(local, bot_id)
            bars = _load_bars(local, symbol=spec_local.symbol, timeframe=spec_local.timeframe, start_utc=start_utc, end_utc=end_utc)
            if not bars:
                row = local.query(BacktestRun).filter(BacktestRun.id == run_id).first()
                if row:
                    row.status = "ERROR"
                    row.error = "no_data_bars"
                    row.finished_at_utc = datetime.now(timezone.utc)
                    local.commit()
                return

            metrics, trades = run_backtest(spec=spec_local, bars=bars)
            row = local.query(BacktestRun).filter(BacktestRun.id == run_id).first()
            if row:
                row.status = "DONE"
                row.finished_at_utc = datetime.now(timezone.utc)
                row.metrics = {"metrics": metrics, "trades": [t.__dict__ for t in trades], "spec": spec_local.dump_canonical()}
                row.error = None
                local.commit()
        except Exception as exc:
            row = local.query(BacktestRun).filter(BacktestRun.id == run_id).first()
            if row:
                row.status = "ERROR"
                row.error = str(exc)
                row.finished_at_utc = datetime.now(timezone.utc)
                local.commit()
        finally:
            local.close()

    asyncio.create_task(_worker())
    return {"ok": True, "runId": run_id, "botId": bot_id, "status": "RUNNING", "started_at_utc": _utc_iso()}


@router.get("/api/v1/backtest/results/{runId}")
async def backtest_results(runId: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    run_id = (runId or "").strip()
    row = db.query(BacktestRun).filter(BacktestRun.id == run_id).first()
    if not row:
        return {"ok": False, "runId": run_id, "error": "not_found", "ts_utc": _utc_iso()}
    return {
        "ok": True,
        "runId": run_id,
        "botId": row.bot_id,
        "status": row.status,
        "params": row.params,
        "metrics": row.metrics,
        "error": row.error,
        "started_at_utc": row.started_at_utc.isoformat().replace("+00:00", "Z") if row.started_at_utc else None,
        "finished_at_utc": row.finished_at_utc.isoformat().replace("+00:00", "Z") if row.finished_at_utc else None,
        "ts_utc": _utc_iso(),
    }


@router.post("/api/v1/optimize/run")
async def optimize_run(payload: OptimizeRunRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    bot_id = (payload.botId or "").strip()
    if not bot_id:
        raise HTTPException(status_code=400, detail="botId required")

    start_utc, end_utc = _parse_range(payload.model_dump())
    base = _load_spec(db, bot_id)

    try:
        variants = generate_variants(base, grid=payload.grid or {}, cap=50)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    run_id = f"opt_{uuid.uuid4().hex}"
    db.add(
        OptimizeRun(
            id=run_id,
            bot_id=bot_id,
            started_at_utc=datetime.now(timezone.utc),
            status="RUNNING",
            params={"startDay": payload.startDay, "endDay": payload.endDay, "grid": payload.grid, "variants": len(variants)},
            results=None,
            error=None,
        )
    )
    db.commit()

    async def _worker() -> None:
        local = SessionLocal()
        try:
            base_local = _load_spec(local, bot_id)
            bars = _load_bars(local, symbol=base_local.symbol, timeframe=base_local.timeframe, start_utc=start_utc, end_utc=end_utc)
            if not bars:
                row = local.query(OptimizeRun).filter(OptimizeRun.id == run_id).first()
                if row:
                    row.status = "ERROR"
                    row.error = "no_data_bars"
                    row.finished_at_utc = datetime.now(timezone.utc)
                    local.commit()
                return

            # Re-validate variants using the local base spec (ensures stored base didn't change).
            variants_local = generate_variants(base_local, grid=payload.grid or {}, cap=50)
            results = run_optimize(base=base_local, variants=variants_local, bars=bars)
            row = local.query(OptimizeRun).filter(OptimizeRun.id == run_id).first()
            if row:
                row.status = "DONE"
                row.finished_at_utc = datetime.now(timezone.utc)
                row.results = {"base": base_local.dump_canonical(), "results": results}
                row.error = None
                local.commit()
        except Exception as exc:
            row = local.query(OptimizeRun).filter(OptimizeRun.id == run_id).first()
            if row:
                row.status = "ERROR"
                row.error = str(exc)
                row.finished_at_utc = datetime.now(timezone.utc)
                local.commit()
        finally:
            local.close()

    asyncio.create_task(_worker())
    return {"ok": True, "runId": run_id, "botId": bot_id, "status": "RUNNING", "started_at_utc": _utc_iso(), "variants": len(variants)}


@router.get("/api/v1/optimize/results/{runId}")
async def optimize_results(runId: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    run_id = (runId or "").strip()
    row = db.query(OptimizeRun).filter(OptimizeRun.id == run_id).first()
    if not row:
        return {"ok": False, "runId": run_id, "error": "not_found", "ts_utc": _utc_iso()}
    return {
        "ok": True,
        "runId": run_id,
        "botId": row.bot_id,
        "status": row.status,
        "params": row.params,
        "results": row.results,
        "error": row.error,
        "started_at_utc": row.started_at_utc.isoformat().replace("+00:00", "Z") if row.started_at_utc else None,
        "finished_at_utc": row.finished_at_utc.isoformat().replace("+00:00", "Z") if row.finished_at_utc else None,
        "ts_utc": _utc_iso(),
    }


@router.get("/api/v1/perf/summary")
async def perf_summary(botId: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    bot_id = (botId or "").strip()
    if not bot_id:
        raise HTTPException(status_code=400, detail="botId required")

    bt = (
        db.query(BacktestRun)
        .filter(BacktestRun.bot_id == bot_id)
        .filter(BacktestRun.status == "DONE")
        .order_by(BacktestRun.finished_at_utc.desc())
        .first()
    )
    opt = (
        db.query(OptimizeRun)
        .filter(OptimizeRun.bot_id == bot_id)
        .filter(OptimizeRun.status == "DONE")
        .order_by(OptimizeRun.finished_at_utc.desc())
        .first()
    )
    latest_bt_metrics = (bt.metrics or {}).get("metrics") if bt and isinstance(bt.metrics, dict) else None
    best_opt = None
    if opt and isinstance(opt.results, dict):
        items = (opt.results or {}).get("results") or []
        if isinstance(items, list) and items:
            best_opt = items[0]

    return {
        "ok": True,
        "botId": bot_id,
        "latest_backtest": {"runId": bt.id, "metrics": latest_bt_metrics} if bt else None,
        "latest_optimize_best": {"runId": opt.id, "best": best_opt} if opt else None,
        "ts_utc": _utc_iso(),
    }
