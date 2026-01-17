from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.bot_factory.engine import run_backtest
from backend.bot_factory.optimize import generate_variants, run_optimize
from backend.contracts.bot_spec_v1 import BotSpecV1
from backend.database import SessionLocal, get_db
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
