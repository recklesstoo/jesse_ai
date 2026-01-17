from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import SessionLocal, get_db
from backend.models import ModelRun
from backend.training.pipeline import TrainConfig, train_from_db
from backend.training.registry import TrainingStatus, list_statuses, utc_iso


router = APIRouter()


class TrainRequest(BaseModel):
    botId: str = Field(default="bot-1")
    symbol: str = Field(default="MNQ")
    timeframes: List[str] = Field(default_factory=lambda: ["1m", "5m"])
    lookback_days: int = 60
    config: Dict[str, Any] = Field(default_factory=dict)


@router.post("/api/v1/bots/train")
async def bots_train(payload: TrainRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    bot_id = (payload.botId or "bot-1").strip()
    symbol = (payload.symbol or "MNQ").upper().strip()
    if not bot_id:
        raise HTTPException(status_code=400, detail="botId required")
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol required")

    timeframes = [str(tf).strip().lower() for tf in (payload.timeframes or [])]
    timeframes = [tf for tf in timeframes if tf in {"1m", "5m"}]
    if not timeframes:
        raise HTTPException(status_code=400, detail="timeframes must include at least one of: 1m, 5m")

    cfg = TrainConfig(
        lookback_days=int(payload.lookback_days or 60),
        horizon_bars=int(payload.config.get("horizon_bars") or 10),
        # Guardrail: never allow lowering below 10k real bars per timeframe.
        min_real_bars=max(10_000, int(payload.config.get("min_real_bars") or 10_000)),
        random_state=int(payload.config.get("random_state") or 42),
    )

    run_ids: List[str] = []

    async def _run(tf: str, run_id: str) -> None:
        # Run training in a worker thread (deterministic, no execution side-effects).
        def _sync() -> None:
            local = SessionLocal()
            try:
                train_from_db(db=local, bot_id=bot_id, symbol=symbol, timeframe=tf, config=cfg, run_id=run_id)
            finally:
                local.close()

        await asyncio.to_thread(_sync)

    for tf in timeframes:
        run_id = f"mr_{uuid.uuid4().hex}"
        run_ids.append(run_id)
        # Insert RUNNING row immediately so status endpoints can see it even after restart.
        db.add(
            ModelRun(
                id=run_id,
                bot_id=bot_id,
                symbol=symbol,
                timeframe=tf,
                started_at_utc=datetime.now(timezone.utc),
                status="RUNNING",
                train_config=cfg.__dict__,
                metrics=None,
                artifact_path=None,
                error=None,
            )
        )
    db.commit()

    for tf, run_id in zip(timeframes, run_ids, strict=False):
        asyncio.create_task(_run(tf, run_id))

    return {"ok": True, "botId": bot_id, "symbol": symbol, "run_ids": run_ids, "status": "RUNNING", "started_at_utc": utc_iso()}


@router.get("/api/v1/bots/train/status")
async def bots_train_status(botId: str = Query("bot-1", alias="botId"), db: Session = Depends(get_db)) -> Dict[str, Any]:
    bot_id = (botId or "bot-1").strip()
    in_mem = list_statuses(bot_id=bot_id)
    rows = (
        db.query(ModelRun)
        .filter(ModelRun.bot_id == bot_id)
        .order_by(ModelRun.started_at_utc.desc())
        .limit(50)
        .all()
    )
    return {
        "ok": True,
        "botId": bot_id,
        "in_memory": {k: v.__dict__ for k, v in in_mem.items()},
        "runs": [
            {
                "id": r.id,
                "botId": r.bot_id,
                "symbol": r.symbol,
                "timeframe": r.timeframe,
                "started_at_utc": r.started_at_utc.isoformat().replace("+00:00", "Z") if r.started_at_utc else None,
                "finished_at_utc": r.finished_at_utc.isoformat().replace("+00:00", "Z") if r.finished_at_utc else None,
                "status": r.status,
                "metrics": r.metrics,
                "artifact_path": r.artifact_path,
                "error": r.error,
            }
            for r in rows
        ],
    }


@router.get("/api/v1/bots/models")
async def bots_models(botId: str = Query("bot-1", alias="botId"), db: Session = Depends(get_db)) -> Dict[str, Any]:
    bot_id = (botId or "bot-1").strip()
    rows = (
        db.query(ModelRun)
        .filter(ModelRun.bot_id == bot_id)
        .filter(ModelRun.status == "DONE")
        .order_by(ModelRun.started_at_utc.desc())
        .limit(200)
        .all()
    )
    return {
        "ok": True,
        "botId": bot_id,
        "models": [
            {
                "id": r.id,
                "symbol": r.symbol,
                "timeframe": r.timeframe,
                "started_at_utc": r.started_at_utc.isoformat().replace("+00:00", "Z") if r.started_at_utc else None,
                "metrics": r.metrics,
                "artifact_path": r.artifact_path,
            }
            for r in rows
        ],
    }


@router.get("/api/v1/bots/models/latest")
async def bots_models_latest(
    botId: str = Query("bot-1", alias="botId"),
    symbol: str = Query("MNQ"),
    timeframe: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    bot_id = (botId or "bot-1").strip()
    sym = (symbol or "MNQ").upper().strip()
    q = db.query(ModelRun).filter(ModelRun.bot_id == bot_id, ModelRun.symbol == sym, ModelRun.status == "DONE")
    if timeframe:
        q = q.filter(ModelRun.timeframe == str(timeframe).strip().lower())
    r = q.order_by(ModelRun.started_at_utc.desc()).first()
    if not r:
        return {"ok": False, "error": "no_models", "botId": bot_id, "symbol": sym, "timeframe": timeframe}
    return {
        "ok": True,
        "botId": bot_id,
        "symbol": sym,
        "timeframe": r.timeframe,
        "model": {
            "id": r.id,
            "started_at_utc": r.started_at_utc.isoformat().replace("+00:00", "Z") if r.started_at_utc else None,
            "metrics": r.metrics,
            "artifact_path": r.artifact_path,
        },
    }
