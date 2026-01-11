from __future__ import annotations

import asyncio
import json
import uuid
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from .database import engine, Base, get_db
from .chat import chat_service
from .models import Bar, CommandEvent, AISignal, BotConfig, MonitorSnapshot

from .ml import ml_service
# from .chat import chat_service  # (solo si de verdad lo usas; ahora mismo NO lo usas)

from .schemas import CommandIn, ChatIn, MLTrainRequest

app = FastAPI(title="Wyckoff AI Lab Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Startup Event ---
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

# -------------------------
# Utils
# -------------------------
def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None

def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None

def _safe_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None

# -------------------------
# In-memory state
# -------------------------
ws_bots: Dict[str, WebSocket] = {}          # bot_id -> websocket (Ninja)
ws_live_clients: Set[WebSocket] = set()     # frontend subscribers
ws_last_rx_ts: Dict[str, datetime] = {}     # bot_id -> last message rx UTC

bot_state: Dict[str, Dict[str, Any]] = {}   # bot_id -> dict state

state_lock = asyncio.Lock()

# -------------------------
# Models
# -------------------------
# (Moved to schemas.py, imported above)

# -------------------------
# Broadcast helpers
# -------------------------
async def _broadcast_live(payload: Dict[str, Any]) -> None:
    dead: List[WebSocket] = []
    msg = json.dumps(payload, ensure_ascii=False)
    for ws in list(ws_live_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_live_clients.discard(ws)

async def _set_bot_state(bot_id: str, patch: Dict[str, Any]) -> None:
    s = bot_state.setdefault(bot_id, {})
    s.update(patch)

def _get_bot_state(bot_id: str) -> Dict[str, Any]:
    return bot_state.setdefault(bot_id, {})

def _append_log(bot_id: str, row: Dict[str, Any]) -> None:
    s = _get_bot_state(bot_id)
    log = s.setdefault("command_log", [])
    log.insert(0, row)
    if len(log) > 500:
        del log[500:]

def _update_log_event(bot_id: str, cmd_id: str, event: str, payload: Optional[Dict[str, Any]] = None) -> None:
    s = _get_bot_state(bot_id)
    log = s.setdefault("command_log", [])
    for row in log:
        if row.get("id") == cmd_id:
            row["event"] = event
            row["ts"] = _iso(_utc_now())
            if payload is not None:
                row["payload"] = payload
            return
    # if not found, add
    _append_log(bot_id, {
        "id": cmd_id,
        "event": event,
        "ts": _iso(_utc_now()),
        "payload": payload or {}
    })

# -------------------------
# Async DB Helpers
# -------------------------
def _save_bar_sync(bot_id: str, payload: dict):
    db = next(get_db())
    try:
        ts_str = payload.get("timestamp")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except:
            ts = datetime.now(timezone.utc)
            
        bar = Bar(
            bot_id=bot_id,
            symbol=payload.get("symbol"),
            timeframe=payload.get("timeframe"),
            ts_utc=ts,
            open=_safe_float(payload.get("open")),
            high=_safe_float(payload.get("high")),
            low=_safe_float(payload.get("low")),
            close=_safe_float(payload.get("close")),
            volume=_safe_int(payload.get("volume")),
            mode=payload.get("mode", "LIVE")
        )
        db.add(bar)
        
        # Retention Policy (1% chance to prune)
        if random.random() < 0.01:
            # Keep last 100k bars
            subq = db.query(Bar.id).filter(Bar.bot_id == bot_id).order_by(Bar.ts_utc.desc()).limit(100000).subquery()
            db.query(Bar).filter(Bar.bot_id == bot_id, ~Bar.id.in_(subq)).delete(synchronize_session=False)
            
        db.commit()
    except Exception as e:
        print(f"DB Error saving bar: {e}")
    finally:
        db.close()

def _save_signal_sync(bot_id: str, sig_data: dict):
    db = next(get_db())
    try:
        sig = AISignal(
            bot_id=bot_id,
            symbol=sig_data.get("symbol"),
            signal=sig_data.get("signal"),
            bias=sig_data.get("bias"),
            confidence=sig_data.get("confidence"),
            explain=sig_data.get("explain"),
            bar_ts_utc=datetime.fromisoformat(sig_data.get("barTs")) if sig_data.get("barTs") else None
        )
        db.add(sig)
        db.commit()
    except Exception as e:
        print(f"DB Error saving signal: {e}")
    finally:
        db.close()

# -------------------------
# WebSocket endpoints
# -------------------------
@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    ws_live_clients.add(websocket)
    # send initial connection status snapshot
    await websocket.send_text(json.dumps({
        "type": "connection_status",
        "data": {"connected": True}
    }))
    try:
        while True:
            # we don't need messages from frontend, but keep it open
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_live_clients.discard(websocket)

@app.websocket("/ws/{bot_id}")
async def ws_bot(websocket: WebSocket, bot_id: str, background_tasks: BackgroundTasks = None):
    # Note: BackgroundTasks cannot be injected into websocket directly easily in FastAPI < 0.100
    # We will use asyncio.to_thread for DB operations to avoid blocking WS loop
    await websocket.accept()

    async with state_lock:
        ws_bots[bot_id] = websocket
        ws_last_rx_ts[bot_id] = _utc_now()
        st = _get_bot_state(bot_id)
        st.setdefault("instrument", "MNQ")
        st["connected"] = True
        st["last_seen_utc"] = _iso(_utc_now())

    await _broadcast_live({
        "type": "bot_status",
        "data": {"status": {"botId": bot_id, "connected": True, "last_seen_utc": _iso(_utc_now())}}
    })

    try:
        while True:
            raw = await websocket.receive_text()
            async with state_lock:
                ws_last_rx_ts[bot_id] = _utc_now()
                _get_bot_state(bot_id)["last_seen_utc"] = _iso(_utc_now())

            # Parse JSON safely
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            mtype = (msg.get("type") or "").upper()
            payload = msg.get("payload") or {}

            if mtype == "BAR_DATA":
                # payload: timestamp, symbol, timeframe, open, high, low, close, volume, mode
                ts = payload.get("timestamp")
                symbol = payload.get("symbol") or "MNQ"
                o = _safe_float(payload.get("open"))
                h = _safe_float(payload.get("high"))
                l = _safe_float(payload.get("low"))
                c = _safe_float(payload.get("close"))
                vol = _safe_int(payload.get("volume"))

                async with state_lock:
                    st = _get_bot_state(bot_id)
                    prev_ts = st.get("last_bar_ts")
                    st["last_bar_ts"] = ts
                    st["last_bar_dt"] = _iso(_utc_now())
                    st["last_price"] = c
                    st["last_ohlc"] = {"open": o, "high": h, "low": l, "close": c}
                    st["last_volume"] = vol
                    st["instrument"] = symbol

                    # bar interval estimate
                    try:
                        if prev_ts and ts:
                            pdt = datetime.fromisoformat(prev_ts.replace("Z", "+00:00"))
                            ndt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            diff_ms = int(max(0, (ndt - pdt).total_seconds() * 1000))
                            if diff_ms > 0:
                                st["bar_interval_ms"] = diff_ms
                    except Exception:
                        pass

                # 1. Save Bar to DB (Async)
                asyncio.get_event_loop().run_in_executor(None, _save_bar_sync, bot_id, payload)

                await _broadcast_live({
                    "type": "bar_update",
                    "data": {
                        "symbol": symbol,
                        "price": c,
                        "ohlc": {"open": o, "high": h, "low": l, "close": c},
                        "volume": vol,
                        "timestamp": ts
                    }
                })

                # 2. Update AI signal (ML Inference)
                await _run_inference_and_update(bot_id, payload)

            elif mtype == "MONITOR":
                # payload: ts, mode, wsState, strategyState, sendIndex, lastBar..., ages, etc
                async with state_lock:
                    st = _get_bot_state(bot_id)
                    st["strategyMonitor"] = payload
                    st["strategyMonitor_ts"] = payload.get("ts") or _iso(_utc_now())
                    st["mode"] = payload.get("mode") or st.get("mode") or "UNKNOWN"

                await _broadcast_live({
                    "type": "bot_status",
                    "data": {"status": {"botId": bot_id, "mode": _get_bot_state(bot_id).get("mode"), "last_seen_utc": _iso(_utc_now()), "instrument": _get_bot_state(bot_id).get("instrument")}}
                })

            elif mtype == "ACK":
                ack = payload
                cmd_id = ack.get("id")
                status = ack.get("status") or "ACK"
                if cmd_id:
                    async with state_lock:
                        _update_log_event(bot_id, cmd_id, f"ACK_{status}", {"ack": ack})
                # no echo back (Ninja doesn't need it)

            else:
                # ignore unknown types
                pass

    except WebSocketDisconnect:
        pass
    finally:
        async with state_lock:
            if ws_bots.get(bot_id) is websocket:
                ws_bots.pop(bot_id, None)
            ws_last_rx_ts.pop(bot_id, None)
            st = _get_bot_state(bot_id)
            st["connected"] = False
            st["last_seen_utc"] = _iso(_utc_now())

        await _broadcast_live({
            "type": "bot_status",
            "data": {"status": {"botId": bot_id, "connected": False, "last_seen_utc": _iso(_utc_now())}}
        })

# -------------------------
# AI Signal (minimal stub)
# -------------------------
async def _run_inference_and_update(bot_id: str, bar_payload: dict) -> None:
    st = _get_bot_state(bot_id)
    ts = st.get("last_bar_ts")
    
    # Run ML Inference in thread
    def _infer():
        db = next(get_db())
        try:
            return ml_service.infer_signal(bot_id, bar_payload, db)
        finally:
            db.close()
            
    result = await asyncio.get_event_loop().run_in_executor(None, _infer)

    new_obj = {
        **result,
        "symbol": bar_payload.get("symbol"),
        "updatedAt": _iso(_utc_now()),
        "barTs": ts
    }
    
    # Update Memory
    st["ai_signal"] = new_obj
    hist = st.setdefault("ai_history", [])
    hist.insert(0, new_obj)
    if len(hist) > 50:
        del hist[50:]
        
    # Save to DB
    asyncio.get_event_loop().run_in_executor(None, _save_signal_sync, bot_id, new_obj)

# -------------------------
# REST endpoints (what App.js calls)
# -------------------------
@app.get("/api/v1/health")
async def health():
    async with state_lock:
        # report ages per bot
        ages: Dict[str, Optional[float]] = {}
        pos_state: Dict[str, Any] = {}
        for bot_id, st in bot_state.items():
            last_bar_dt_iso = st.get("last_bar_dt")
            if last_bar_dt_iso:
                try:
                    last_dt = datetime.fromisoformat(last_bar_dt_iso)
                    ages[bot_id] = (_utc_now() - last_dt).total_seconds()
                except Exception:
                    ages[bot_id] = None
            else:
                ages[bot_id] = None

            # placeholder position state (if you later wire real position)
            if st.get("positionState"):
                pos_state[bot_id] = st["positionState"]

        return {
            "ok": True,
            "shadow_mode": bool(bot_state.get("global", {}).get("shadow_mode", False)),
            "lastSnapshotAgeSec": ages,
            "positionState": pos_state
        }

@app.get("/api/v1/metrics")
async def metrics(botId: str = Query(..., alias="botId")):
    async with state_lock:
        st = _get_bot_state(botId)
        last_bar_dt_iso = st.get("last_bar_dt")
        last_age_ms = None
        if last_bar_dt_iso:
            try:
                last_dt = datetime.fromisoformat(last_bar_dt_iso)
                last_age_ms = int(max(0, (_utc_now() - last_dt).total_seconds() * 1000))
            except Exception:
                last_age_ms = None

        return {
            "bots": {
                botId: {
                    "last_bar_age_ms": last_age_ms,
                    "bar_interval_ms": st.get("bar_interval_ms")
                }
            }
        }

@app.get("/api/v1/monitor/status")
async def monitor_status(botId: str = Query(..., alias="botId")):
    async with state_lock:
        st = _get_bot_state(botId)
        last_bar_dt_iso = st.get("last_bar_dt")
        last_bar_age_sec = None
        if last_bar_dt_iso:
            try:
                last_dt = datetime.fromisoformat(last_bar_dt_iso)
                last_bar_age_sec = (_utc_now() - last_dt).total_seconds()
            except Exception:
                last_bar_age_sec = None

        sm_ts = st.get("strategyMonitor_ts")
        sm_age = None
        if sm_ts:
            try:
                dt = datetime.fromisoformat(sm_ts.replace("Z", "+00:00"))
                sm_age = (_utc_now() - dt).total_seconds()
            except Exception:
                sm_age = None

        ok = (last_bar_age_sec is not None and last_bar_age_sec <= 1.5) and (sm_age is not None and sm_age <= 15)

        return {
            "ok": bool(ok),
            "lastBarTs": st.get("last_bar_ts"),
            "lastBarAgeSec": last_bar_age_sec,
            "lastBarReceivedAgeSec": last_bar_age_sec,
            "strategyMonitorAgeSec": sm_age,
            "strategyMonitor": st.get("strategyMonitor") or {}
        }

@app.post("/api/v1/commands/{bot_id}")
async def post_command(bot_id: str, cmd: CommandIn, db: Session = Depends(get_db)):
    cmd_id = f"cmd_{uuid.uuid4().hex[:12]}"
    queued_at = _iso(_utc_now())
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
    
    # Save to DB
    evt = CommandEvent(cmd_id=cmd_id, bot_id=bot_id, event="QUEUED", payload=queued)
    db.add(evt)
    db.commit()

    async with state_lock:
        _append_log(bot_id, {
            "id": cmd_id,
            "event": "QUEUED",
            "ts": queued_at,
            "payload": {"queued": queued}
        })
        ws = ws_bots.get(bot_id)

    # Try deliver immediately
    if ws:
        try:
            wire = {**queued, "id": cmd_id}  # Ninja expects id at root
            await ws.send_text(json.dumps(wire, ensure_ascii=False))
            async with state_lock:
                _update_log_event(bot_id, cmd_id, "DELIVERED", {"queued": queued})
        except Exception:
            async with state_lock:
                _update_log_event(bot_id, cmd_id, "ERROR_DELIVERY", {"queued": queued})

    return {"ts": queued_at, "queued": queued}

@app.get("/api/v1/commands/{bot_id}/log")
async def get_command_log(bot_id: str, limit: int = 200):
    async with state_lock:
        st = _get_bot_state(bot_id)
        log = st.get("command_log", [])[: max(1, min(1000, limit))]
        return {"log": log}

@app.get("/api/v1/ai-signals")
async def ai_signals(botId: str = Query(..., alias="botId")):
    async with state_lock:
        st = _get_bot_state(botId)
        sig = st.get("ai_signal")
        if not sig:
            sig = {
                "signal": "NONE",
                "bias": "NEUTRAL",
                "confidence": 0.0,
                "explain": "No data yet.",
                "updatedAt": _iso(_utc_now()),
                "barTs": None
            }
        return sig

@app.get("/api/v1/ai-signals/{bot_id}/history")
async def ai_history(bot_id: str, limit: int = 10):
    async with state_lock:
        st = _get_bot_state(bot_id)
        hist = st.get("ai_history", [])[: max(1, min(200, limit))]
        return {"history": hist}

@app.post("/api/v1/ai-order")
async def ai_order(payload: Dict[str, Any]):
    # Just route into commands
    bot_id = payload.get("botId") or payload.get("bot_id") or "bot-1"
    action = payload.get("action") or "NONE"
    if action == "NONE":
        return {"ok": False, "reason": "NONE"}
    cmd = CommandIn(
        action=action,
        qty=int(payload.get("qty") or 0),
        slTicks=int(payload.get("slTicks") or 0),
        tpTicks=int(payload.get("tpTicks") or 0),
        tag=payload.get("tag") or "ai",
        symbol=payload.get("symbol") or "MNQ",
    )
    return await post_command(bot_id, cmd)

@app.get("/api/v1/wyckoff/config")
async def get_wyckoff_config(botId: str = Query(..., alias="botId")):
    async with state_lock:
        st = _get_bot_state(botId)
        cfg = st.get("wyckoff_config") or {
            "window": 20,
            "min_bars": 10,
            "vol_mult": 1.5,
            "break_pct": 0.001,
            "break_range_mult": 1.2,
            "sos_pct": 0.001,
            "sow_pct": 0.001,
            "range_window": 30,
        }
        st["wyckoff_config"] = cfg
        return {"config": cfg}

@app.post("/api/v1/wyckoff/config")
async def post_wyckoff_config(payload: Dict[str, Any]):
    bot_id = payload.get("botId") or payload.get("bot_id") or "bot-1"
    cfg = {k: v for k, v in payload.items() if k != "botId" and k != "bot_id"}
    async with state_lock:
        st = _get_bot_state(bot_id)
        st["wyckoff_config"] = cfg
    return {"config": cfg}

@app.get("/api/v1/ai/auto-config")
async def get_auto_config(botId: str = Query(..., alias="botId")):
    async with state_lock:
        st = _get_bot_state(botId)
        cfg = st.get("auto_config") or {
            "enabled": False,
            "min_confidence": 0.6,
            "max_per_hour": 0,
            "cooldown_seconds": 60,
            "max_qty": 1,
            "allowed_signals": ["SOS", "SOW", "SPRING", "UPTHRUST"]
        }
        st["auto_config"] = cfg
        return {"config": cfg}

@app.post("/api/v1/ai/auto-config")
async def post_auto_config(payload: Dict[str, Any]):
    bot_id = payload.get("botId") or payload.get("bot_id") or "bot-1"
    cfg = {k: v for k, v in payload.items() if k != "botId" and k != "bot_id"}
    async with state_lock:
        st = _get_bot_state(bot_id)
        st["auto_config"] = cfg
    return {"config": cfg}

@app.get("/api/v1/shadow/recent")
async def shadow_recent(limit: int = 50):
    # placeholder
    return {"decisions": []}

@app.post("/api/v1/bots/instrument")
async def set_instrument(payload: Dict[str, Any]):
    bot_id = payload.get("botId") or "bot-1"
    inst = (payload.get("instrument") or "MNQ").upper().strip()
    async with state_lock:
        st = _get_bot_state(bot_id)
        st["instrument"] = inst
    return {"ok": True, "botId": bot_id, "instrument": inst}

@app.post("/api/v1/chat")
async def chat(req: ChatIn):
    # very simple assistant (no LLM here)
    last_user = ""
    for m in reversed(req.messages or []):
        if m.get("role") == "user":
            last_user = m.get("content", "")
            break

    async with state_lock:
        st = _get_bot_state(req.botId)
        price = st.get("last_price")
        ts = st.get("last_bar_ts")
        mode = st.get("mode", "UNKNOWN")
        connected = bool(st.get("connected", False))

    reply = f"Estado bot={req.botId} connected={connected} mode={mode} last={price} ts={ts}. "
    if "riesgo" in last_user.lower():
        reply += "Riesgo: usa qty bajo, SL/TP definidos, evita operar con feed stale."
    elif "estado" in last_user.lower() or "status" in last_user.lower():
        reply += "Todo lo esencial está arriba: conexión, edad de barra y monitor."
    else:
        reply += "Dime si quieres BUY/SELL/FLATTEN y con qué SL/TP."

    return {"reply": reply}

# -------------------------
# Calendar (ForexFactory placeholder)
# -------------------------
_calendar_state: Dict[str, Any] = {
    "timezone": "UTC",
    "last_refresh": None,
    "events": []
}

@app.get("/api/v1/calendar/ff/status")
async def cal_status():
    return {
        "timezone": _calendar_state.get("timezone", "UTC"),
        "last_refresh": _calendar_state.get("last_refresh"),
        "ok": True
    }

@app.get("/api/v1/calendar/ff/upcoming")
async def cal_upcoming(days: int = 7, limit: int = 200):
    # placeholder empty list (no scraping here)
    events = list(_calendar_state.get("events", []))[: max(0, min(1000, limit))]
    return {"events": events, "days": days}

@app.post("/api/v1/calendar/ff/refresh")
async def cal_refresh(days: int = 7):
    _calendar_state["last_refresh"] = _iso(_utc_now())
    _calendar_state["events"] = []  # keep empty until you plug real scraper
    return {"ok": True, "last_refresh": _calendar_state["last_refresh"], "days": days}
