from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.compat import (
    ai_signal_history,
    ai_signal_store,
    bars_store,
    get_queue,
    update_ai_signal,
    update_bot_state,
)
from backend.config import (
    EXECUTION_MODE_DISABLED,
    EXECUTION_MODE_MANUAL_ONLY,
    get_execution_mode,
    get_shadow_decisions,
    is_shadow_mode,
    log_shadow_decision,
)
from backend.database import SessionLocal, get_db
from backend.models import Bar, CommandEvent
from backend.schemas import (
    AISignalOut,
    ChatIn,
    CommandIn,
    MLTrainRequest,
    RestoreRequest,
)
from backend.services.chat_service import chat_service
from backend.services.ml_service import ml_service
from backend.state import (
    _append_log,
    _get_bot_state,
    _iso,
    _update_log_event,
    bot_state,
    compute_feed_status,
    AI_MIN_LIVE_BARS,
    state_lock,
    ws_bots,
)

router = APIRouter()

_calendar_state: Dict[str, Any] = {"timezone": "UTC", "last_refresh": None, "events": []}


def _persist_command_event(bot_id: str, cmd_id: str, queued: Dict[str, Any]) -> None:
    session = SessionLocal()
    try:
        event = CommandEvent(cmd_id=cmd_id, bot_id=bot_id, event="QUEUED", payload=queued)
        session.add(event)
        session.commit()
    except Exception as exc:
        print(f"[commands] persist error: {exc}")
    finally:
        session.close()


@router.post("/api/v1/commands/{bot_id}")
async def post_command(bot_id: str, cmd: CommandIn) -> Dict[str, Any]:
    cmd_id = f"cmd_{uuid.uuid4().hex[:12]}"
    queued_at = _iso(datetime.utcnow())
    queued = {
        "id": cmd_id,
        "action": cmd.action.upper().strip(),
        "qty": int(cmd.qty or 0),
        "slTicks": int(cmd.slTicks or 0),
        "tpTicks": int(cmd.tpTicks or 0),
        "tag": cmd.tag or "manual",
        "symbol": cmd.symbol or "MNQ",
        "queuedAt": queued_at,
    }

    if is_shadow_mode():
        log_shadow_decision(bot_id, queued)
        async with state_lock:
            _append_log(
                bot_id,
                {
                    "id": cmd_id,
                    "event": "SHADOW_LOGGED",
                    "ts": queued_at,
                    "payload": {"queued": queued},
                },
            )
        return {"ts": queued_at, "queued": queued, "shadow": True, "status": "SHADOW"}

    asyncio.create_task(
        asyncio.to_thread(_persist_command_event, bot_id, cmd_id, queued)
    )

    async with state_lock:
        _append_log(
            bot_id,
            {
                "id": cmd_id,
                "event": "QUEUED",
                "ts": queued_at,
                "payload": {"queued": queued},
            },
        )
        ws = ws_bots.get(bot_id)

    execution_mode = get_execution_mode()
    tag = str(queued.get("tag") or "").strip().lower()
    manual_tags = {"manual", "limit"}

    if execution_mode == EXECUTION_MODE_DISABLED:
        ack_payload = {
            "id": cmd_id,
            "status": "REJECTED",
            "reason": "execution disabled by policy",
            "reject_reason": "execution disabled by policy",
            "execution_mode": execution_mode,
            "ts": _iso(datetime.utcnow()),
        }
        async with state_lock:
            _update_log_event(bot_id, cmd_id, "ACK_REJECTED", {"queued": queued, "ack": ack_payload})
        return {"ok": False, "ts": queued_at, "queued": queued, "ack": ack_payload}

    if execution_mode == EXECUTION_MODE_MANUAL_ONLY and tag not in manual_tags:
        ack_payload = {
            "id": cmd_id,
            "status": "REJECTED",
            "reason": "manual-only policy",
            "reject_reason": f"execution mode MANUAL_ONLY (tag '{tag}' not allowed)",
            "execution_mode": execution_mode,
            "ts": _iso(datetime.utcnow()),
        }
        async with state_lock:
            _update_log_event(bot_id, cmd_id, "ACK_REJECTED", {"queued": queued, "ack": ack_payload})
        return {"ok": False, "ts": queued_at, "queued": queued, "ack": ack_payload}

    # Compatibility: always enqueue allowed commands (even if the bot WS is offline),
    # so `/api/v1/commands/{botId}` can be used by test harnesses/debug tools.
    queue = await get_queue(bot_id)
    await queue.put(queued)

    if ws is None:
        ack_payload = {
            "id": cmd_id,
            "status": "IGNORED",
            "reason": "bot not connected",
            "reject_reason": "bot not connected (ws not open)",
            "execution_mode": execution_mode,
            "ts": _iso(datetime.utcnow()),
        }
        async with state_lock:
            _update_log_event(bot_id, cmd_id, "ACK_IGNORED", {"queued": queued, "ack": ack_payload})
        return {"ok": False, "ts": queued_at, "queued": queued, "ack": ack_payload}

    try:
        payload = {**queued, "id": cmd_id}
        await ws.send_text(json.dumps(payload, ensure_ascii=False))
        async with state_lock:
            _update_log_event(bot_id, cmd_id, "DELIVERED", {"queued": queued})
    except Exception:
        ack_payload = {
            "id": cmd_id,
            "status": "IGNORED",
            "reason": "ws delivery failed",
            "reject_reason": "ws send_text failed (delivery error)",
            "execution_mode": execution_mode,
            "ts": _iso(datetime.utcnow()),
        }
        async with state_lock:
            _update_log_event(bot_id, cmd_id, "ACK_IGNORED", {"queued": queued, "ack": ack_payload})
        return {"ok": False, "ts": queued_at, "queued": queued, "ack": ack_payload}

    return {"ok": True, "ts": queued_at, "queued": queued, "execution_mode": execution_mode}


@router.post("/api/v1/commands/{bot_id}/ack")
async def command_ack(bot_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    cmd_id = payload.get("id")
    status = (payload.get("status") or "ACK").upper()
    if not cmd_id:
        return {"ok": False, "reason": "missing_id"}
    if status.startswith("SIM"):
        status = "REJECTED"
        payload = {**payload, "status": status, "reason": payload.get("reason") or "simulated acks disabled"}

    async with state_lock:
        _update_log_event(bot_id, cmd_id, f"ACK_{status}", {"ack": payload})
    return {"ok": True, "id": cmd_id, "status": status}


@router.get("/api/v1/commands/{bot_id}/log")
async def get_command_log(bot_id: str, limit: int = 200) -> Dict[str, Any]:
    async with state_lock:
        entries = _get_bot_state(bot_id).get("command_log", [])[: max(1, min(1000, limit))]
    return {"log": entries}


@router.get("/api/v1/commands/{bot_id}")
async def commands_queue(bot_id: str, wait_ms: int = Query(0)) -> Dict[str, Any]:
    queue = await get_queue(bot_id)
    try:
        if wait_ms > 0:
            payload = await asyncio.wait_for(queue.get(), timeout=wait_ms / 1000)
        else:
            payload = queue.get_nowait()
    except asyncio.QueueEmpty:
        return {"ok": False, "reason": "empty"}
    except asyncio.TimeoutError:
        return {"ok": False, "reason": "timeout"}
    return payload


@router.get("/api/v1/ai-signals")
async def ai_signals(botId: str = Query(..., alias="botId")) -> AISignalOut:
    async with state_lock:
        feed = compute_feed_status(botId)
        state = _get_bot_state(botId)
        if feed["feed_status"] != "LIVE":
            now = _iso(datetime.utcnow())
            sig = {
                "signal": "NONE",
                "bias": "NEUTRAL",
                "confidence": 0.0,
                "explain": "NO DATA: waiting for NinjaTrader feed.",
                "updatedAt": now,
                "barTs": feed.get("last_bar_ts_utc"),
            }
        else:
            live_count = int(state.get("live_bar_count") or 0)
            if live_count < AI_MIN_LIVE_BARS:
                now = _iso(datetime.utcnow())
                sig = {
                    "signal": "NONE",
                    "bias": "NEUTRAL",
                    "confidence": 0.0,
                    "explain": f"Collecting live bars from NinjaTrader (need >= {AI_MIN_LIVE_BARS}, have {live_count}).",
                    "updatedAt": now,
                    "barTs": feed.get("last_bar_ts_utc"),
                }
                return {"ok": True, **sig}
            sig = state.get("ai_signal")
            if not sig:
                now = _iso(datetime.utcnow())
                sig = {
                    "signal": "NONE",
                    "bias": "NEUTRAL",
                    "confidence": 0.0,
                    "explain": f"Collecting live bars from NinjaTrader (need >= {AI_MIN_LIVE_BARS}).",
                    "updatedAt": now,
                    "barTs": feed.get("last_bar_ts_utc"),
                }
    return {"ok": True, **sig}


@router.get("/api/v1/ai-signals/{bot_id}/history")
async def ai_history(bot_id: str, limit: int = 10) -> Dict[str, Any]:
    async with state_lock:
        history = _get_bot_state(bot_id).get("ai_history", [])[: max(1, min(200, limit))]
    return {"ok": True, "history": history, "count": len(history)}


@router.get("/api/v1/strategy/state")
async def strategy_state(botId: str = Query(..., alias="botId")) -> Dict[str, Any]:
    async with state_lock:
        snapshot = dict(_get_bot_state(botId))
    return {"ok": True, "state": snapshot}


@router.get("/api/v1/state")
async def api_state(botId: str = Query("bot-1", alias="botId")) -> Dict[str, Any]:
    async with state_lock:
        feed = compute_feed_status(botId)
        snapshot = dict(_get_bot_state(botId))
    return {"ok": True, **feed, "state": snapshot}


@router.get("/api/v1/signals/latest")
async def signals_latest(botId: str = Query("bot-1", alias="botId")) -> AISignalOut:
    return await ai_signals(botId=botId)


@router.get("/api/v1/signals/history")
async def signals_history(botId: str = Query("bot-1", alias="botId"), limit: int = 10) -> Dict[str, Any]:
    return await ai_history(bot_id=botId, limit=limit)


@router.get("/api/v1/bots")
async def list_bots() -> Dict[str, Any]:
    async with state_lock:
        snapshot = {bot_id: dict(state) for bot_id, state in bot_state.items()}
        computed = {bot_id: compute_feed_status(bot_id) for bot_id in snapshot.keys()}
    return {"ok": True, "bots": snapshot, "computed": computed}


@router.post("/api/v1/ai-order")
async def ai_order(payload: Dict[str, Any]) -> Dict[str, Any]:
    raise HTTPException(
        status_code=403,
        detail="AI execution is disabled. Use manual controls; swarm/orchestrator is read-only.",
    )


@router.get("/api/v1/wyckoff/config")
async def get_wyckoff_config(botId: str = Query(..., alias="botId")) -> Dict[str, Any]:
    async with state_lock:
        state = _get_bot_state(botId)
        cfg = state.get("wyckoff_config") or {
            "window": 20,
            "min_bars": 10,
            "vol_mult": 1.5,
            "break_pct": 0.001,
            "break_range_mult": 1.2,
            "sos_pct": 0.001,
            "sow_pct": 0.001,
            "range_window": 30,
        }
        state["wyckoff_config"] = cfg
    return {"config": cfg}


@router.post("/api/v1/wyckoff/config")
async def post_wyckoff_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    bot_id = payload.get("botId") or payload.get("bot_id") or "bot-1"
    config = {k: v for k, v in payload.items() if k not in ("botId", "bot_id")}
    async with state_lock:
        _get_bot_state(bot_id)["wyckoff_config"] = config
    return {"config": config}


@router.get("/api/v1/ai/auto-config")
async def get_auto_config(botId: str = Query(..., alias="botId")) -> Dict[str, Any]:
    async with state_lock:
        state = _get_bot_state(botId)
        cfg = state.get("auto_config") or {
            "enabled": False,
            "min_confidence": 0.6,
            "max_per_hour": 0,
            "cooldown_seconds": 60,
            "max_qty": 1,
            "allowed_signals": ["SOS", "SOW", "SPRING", "UPTHRUST"],
        }
        state["auto_config"] = cfg
    return {"config": cfg}


@router.post("/api/v1/ai/auto-config")
async def post_auto_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    bot_id = payload.get("botId") or payload.get("bot_id") or "bot-1"
    config = {k: v for k, v in payload.items() if k not in ("botId", "bot_id")}
    async with state_lock:
        _get_bot_state(bot_id)["auto_config"] = config
    return {"config": config}


@router.get("/api/v1/shadow/recent")
async def shadow_recent(limit: int = 50) -> Dict[str, Any]:
    decisions = get_shadow_decisions(limit)
    return {"count": len(decisions), "shadow_mode": is_shadow_mode(), "decisions": decisions}


@router.post("/api/v1/bots/instrument")
async def set_instrument(payload: Dict[str, Any]) -> Dict[str, Any]:
    bot_id = payload.get("botId") or payload.get("bot_id") or "bot-1"
    instrument = (payload.get("instrument") or "MNQ").upper().strip()
    async with state_lock:
        _get_bot_state(bot_id)["instrument"] = instrument
    return {"ok": True, "botId": bot_id, "instrument": instrument}


@router.post("/api/v1/chat")
async def chat(req: ChatIn, db: Session = Depends(get_db)) -> Dict[str, Any]:
    async with state_lock:
        snapshot = dict(_get_bot_state(req.botId))

    reply = await asyncio.get_running_loop().run_in_executor(
        None, chat_service.generate_reply, req.botId, req.messages, snapshot, db
    )
    return {"reply": reply}


@router.post("/api/v1/ml/train")
async def ml_train(req: MLTrainRequest) -> Dict[str, Any]:
    def _train() -> tuple[bool, Dict[str, Any]]:
        db = next(get_db())
        try:
            params = {"n_estimators": req.n_estimators, "max_depth": req.max_depth}
            return ml_service.train_from_db(req.botId, db, hyperparams=params, test_size=req.test_size)
        finally:
            db.close()

    success, details = await asyncio.get_running_loop().run_in_executor(None, _train)
    return {"trained": success, "details": details}


@router.get("/api/v1/ml/history/{bot_id}")
async def ml_history(bot_id: str) -> Dict[str, Any]:
    return {"history": ml_service.get_history(bot_id)}


@router.get("/api/v1/ml/status")
async def ml_status(botId: str = Query("bot-1", alias="botId")) -> Dict[str, Any]:
    history = ml_service.get_history(botId)
    latest = history[-1] if history else None
    return {
        "ok": True,
        "botId": botId,
        "model_path": ml_service.get_model_path(botId),
        "last_training": latest,
        "history_count": len(history),
    }


@router.delete("/api/v1/ml/history/{bot_id}")
async def ml_history_clear(bot_id: str) -> Dict[str, Any]:
    success = ml_service.clear_history(bot_id)
    return {"ok": success}


@router.get("/api/v1/ml/confusion-matrix/{bot_id}")
async def ml_confusion_matrix(bot_id: str, limit: Optional[int] = None) -> Dict[str, Any]:
    return {"confusion_matrix": ml_service.get_confusion_matrix(bot_id, limit)}


@router.get("/api/v1/ml/recommendation/{bot_id}")
async def ml_recommendation(bot_id: str) -> Dict[str, Any]:
    return ml_service.get_recommendation(bot_id)


@router.get("/api/v1/ml/model/{bot_id}")
async def download_model(bot_id: str) -> Any:
    path = Path(ml_service.get_model_path(bot_id))
    if path.exists():
        return FileResponse(
            path,
            media_type="application/octet-stream",
            filename=f"{bot_id}.joblib",
        )
    return {"error": "Model not found", "ok": False}


@router.post("/api/v1/ml/upload/{bot_id}")
async def upload_model(bot_id: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    path = Path(ml_service.get_model_path(bot_id))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as buffer:
            buffer.write(file.file.read())
        if bot_id in ml_service.models:
            del ml_service.models[bot_id]
        return {"ok": True, "bot_id": bot_id, "filename": file.filename}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/api/v1/ml/backups")
async def list_backups() -> Dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    backups_dir = root / "backups"
    results: List[Dict[str, Any]] = []
    if backups_dir.exists():
        for folder in backups_dir.iterdir():
            if folder.is_dir() and folder.name.startswith("models_"):
                models = [f.name for f in folder.glob("*.joblib")]
                if not models:
                    continue
                timestamp = folder.name.replace("models_", "")
                results.append({"folder": folder.name, "timestamp": timestamp, "models": models})
    results.sort(key=lambda item: item["timestamp"], reverse=True)
    return {"backups": results}


@router.post("/api/v1/ml/restore")
async def restore_backup(req: RestoreRequest) -> Dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    source = root / "backups" / req.folder / req.filename
    target = Path(ml_service.get_model_path(req.botId))
    if not source.exists():
        return {"ok": False, "error": "Backup file not found"}
    if ".." in req.folder or ".." in req.filename:
        return {"ok": False, "error": "Invalid path"}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as src, target.open("wb") as dst:
            dst.write(src.read())
        if req.botId in ml_service.models:
            del ml_service.models[req.botId]
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/api/v1/bars/batch")
async def bars_batch(payload: Dict[str, Any]) -> Dict[str, Any]:
    bot_id = payload.get("botId") or payload.get("bot_id") or "bot-1"
    bars = payload.get("bars") or []
    store = bars_store.setdefault(bot_id, [])
    store.extend(bars)
    if len(store) > 500:
        del store[: len(store) - 500]
    update_bot_state(bot_id, mode=payload.get("mode", "LIVE"), instrument=payload.get("instrument", "MNQ"))
    if bars:
        update_ai_signal(bot_id)
        async with state_lock:
            state = _get_bot_state(bot_id)
            state["ai_signal"] = ai_signal_store.get(bot_id, state.get("ai_signal"))
            state["ai_history"] = ai_signal_history.get(bot_id, [])[:200]
    return {"received": len(bars)}


@router.get("/api/v1/history/{bot_id}")
async def history(bot_id: str, limit: int = 50, db: Session = Depends(get_db)) -> Dict[str, Any]:
    bars = (
        db.query(Bar)
        .filter(Bar.bot_id == bot_id)
        .order_by(Bar.ts_utc.desc())
        .limit(limit)
        .all()
    )
    serialized = [
        {
            "symbol": bar.symbol,
            "timeframe": bar.timeframe,
            "ts_utc": bar.ts_utc.isoformat() if bar.ts_utc else None,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "mode": bar.mode,
        }
        for bar in bars
    ]
    return {"count": len(serialized), "bars": serialized}


@router.get("/api/v1/calendar/ff/status")
async def cal_status() -> Dict[str, Any]:
    return {
        "timezone": _calendar_state.get("timezone", "UTC"),
        "last_refresh": _calendar_state.get("last_refresh"),
        "ok": True,
    }


@router.get("/api/v1/calendar/ff/upcoming")
async def cal_upcoming(days: int = 7, limit: int = 200) -> Dict[str, Any]:
    events = list(_calendar_state.get("events", []))[: max(0, min(1000, limit))]
    return {"events": events, "days": days}


@router.post("/api/v1/calendar/ff/refresh")
async def cal_refresh(days: int = 7) -> Dict[str, Any]:
    _calendar_state["last_refresh"] = _iso(datetime.utcnow())
    _calendar_state["events"] = []
    return {"ok": True, "last_refresh": _calendar_state["last_refresh"], "days": days}
