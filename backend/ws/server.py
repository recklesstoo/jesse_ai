from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import WebSocket, WebSocketDisconnect

from backend.compat import bars_store, update_bot_state
from backend.database import get_db
from backend.models import AISignal, Bar, MonitorSnapshot, TradeEvent
from backend.services.ml_service import ml_service
from backend.state import (
    _append_log,
    _broadcast_live,
    _get_bot_state,
    _iso,
    _safe_float,
    _safe_int,
    _set_bot_state,
    _update_log_event,
    state_lock,
    ws_bots,
    ws_last_rx_ts,
    ws_live_clients,
)

MAX_BARS_CACHE = 400


def _open_db():
    return next(get_db())


def _parse_timestamp(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value)
    except Exception:
        return datetime.now(timezone.utc)


def _save_bar_sync(bot_id: str, payload: Dict[str, Any]) -> None:
    db = _open_db()
    try:
        ts = _parse_timestamp(payload.get("timestamp"))
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
            mode=payload.get("mode", "LIVE"),
        )
        db.add(bar)
        if random.random() < 0.01:
            subq = (
                db.query(Bar.id)
                .filter(Bar.bot_id == bot_id)
                .order_by(Bar.ts_utc.desc())
                .limit(100000)
                .subquery()
            )
            db.query(Bar).filter(Bar.bot_id == bot_id, ~Bar.id.in_(subq)).delete(
                synchronize_session=False
            )
        db.commit()
    except Exception as exc:
        print(f"[ws] DB save bar error: {exc}")
    finally:
        db.close()


def _save_signal_sync(bot_id: str, sig_data: Dict[str, Any]) -> None:
    db = _open_db()
    try:
        signal = AISignal(
            bot_id=bot_id,
            symbol=sig_data.get("symbol"),
            signal=sig_data.get("signal"),
            bias=sig_data.get("bias"),
            confidence=sig_data.get("confidence"),
            explain=sig_data.get("explain"),
            bar_ts_utc=_parse_timestamp(sig_data.get("barTs")),
        )
        db.add(signal)
        db.commit()
    except Exception as exc:
        print(f"[ws] DB save signal error: {exc}")
    finally:
        db.close()


def _save_monitor_snapshot_sync(bot_id: str, payload: Dict[str, Any]) -> None:
    db = _open_db()
    try:
        snapshot = MonitorSnapshot(
            bot_id=bot_id,
            data=payload,
            ts_utc=datetime.now(timezone.utc),
        )
        db.add(snapshot)
        db.commit()
    except Exception as exc:
        print(f"[ws] Monitor save error: {exc}")
    finally:
        db.close()


def _save_trade_event_sync(bot_id: str, payload: Dict[str, Any]) -> None:
    db = _open_db()
    try:
        trade = TradeEvent(
            bot_id=bot_id,
            symbol=payload.get("symbol"),
            action=payload.get("action"),
            qty=_safe_int(payload.get("qty")),
            price=_safe_float(payload.get("price")),
            ts_utc=_parse_timestamp(payload.get("ts")),
            market_position=payload.get("marketPosition"),
            reason=payload.get("reason"),
            payload=payload,
        )
        db.add(trade)
        db.commit()
    except Exception as exc:
        print(f"[ws] Trade event save error: {exc}")
    finally:
        db.close()


async def _run_inference_and_update(bot_id: str, payload: Dict[str, Any]) -> None:
    loop = asyncio.get_running_loop()

    def _infer():
        db = _open_db()
        try:
            cfg = _get_bot_state(bot_id).get("wyckoff_config")
            return ml_service.infer_signal(bot_id, payload, db, wyckoff_config=cfg)
        finally:
            db.close()

    result = await loop.run_in_executor(None, _infer)
    new_entry = {
        **result,
        "symbol": payload.get("symbol"),
        "updatedAt": _iso(datetime.now(timezone.utc)),
        "barTs": _iso(_parse_timestamp(payload.get("timestamp"))),
    }
    _set_bot_state(bot_id, {"ai_signal": new_entry})
    hist = _get_bot_state(bot_id).setdefault("ai_history", [])
    hist.insert(0, new_entry)
    if len(hist) > 50:
        del hist[50:]
    asyncio.create_task(asyncio.to_thread(_save_signal_sync, bot_id, new_entry))


def _update_bot_connection(bot_id: str, websocket: WebSocket) -> None:
    current_instrument = _get_bot_state(bot_id).get("instrument", "MNQ")
    api_key = websocket.headers.get("x-api-key")
    _set_bot_state(
        bot_id,
        {
            "connected": True,
            "last_seen_utc": _iso(datetime.now(timezone.utc)),
            "instrument": current_instrument,
            "api_key": api_key,
        },
    )
    ws_bots[bot_id] = websocket
    ws_last_rx_ts[bot_id] = datetime.now(timezone.utc)


def _cleanup_bot(bot_id: str, websocket: WebSocket) -> None:
    if ws_bots.get(bot_id) is websocket:
        ws_bots.pop(bot_id, None)
    ws_last_rx_ts.pop(bot_id, None)
    _set_bot_state(
        bot_id,
        {
            "connected": False,
            "last_seen_utc": _iso(datetime.now(timezone.utc)),
        },
    )


async def ws_live(websocket: WebSocket) -> None:
    await websocket.accept()
    ws_live_clients.add(websocket)
    await websocket.send_text(
        json.dumps({"type": "connection_status", "data": {"connected": True}}, ensure_ascii=False)
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_live_clients.discard(websocket)


async def ws_bot(websocket: WebSocket, bot_id: str) -> None:
    await websocket.accept()
    async with state_lock:
        _update_bot_connection(bot_id, websocket)
    await _broadcast_live(
        {
            "type": "bot_status",
            "data": {
                "status": {
                    "botId": bot_id,
                    "connected": True,
                    "last_seen_utc": _iso(datetime.now(timezone.utc)),
                }
            },
        }
    )

    try:
        while True:
            raw = await websocket.receive_text()
            async with state_lock:
                ws_last_rx_ts[bot_id] = datetime.now(timezone.utc)
                _set_bot_state(bot_id, {"last_seen_utc": _iso(datetime.now(timezone.utc))})
            try:
                message = json.loads(raw)
            except Exception:
                continue
            msg_type = (message.get("type") or "").upper()
            payload = message.get("payload") or {}

            if msg_type == "BAR_DATA":
                await _handle_bar_data(bot_id, payload)
            elif msg_type == "MONITOR":
                await _handle_monitor(bot_id, payload)
            elif msg_type == "TRADE_EVENT":
                await _handle_trade_event(bot_id, payload)
            elif msg_type == "ACK":
                await _handle_ack(bot_id, payload)

    except WebSocketDisconnect:
        pass
    finally:
        async with state_lock:
            _cleanup_bot(bot_id, websocket)
        await _broadcast_live(
            {
                "type": "bot_status",
                "data": {"status": {"botId": bot_id, "connected": False}},
            }
        )


async def _handle_bar_data(bot_id: str, payload: Dict[str, Any]) -> None:
    ts = payload.get("timestamp")
    ts_dt: Optional[datetime] = None
    if ts:
        try:
            ts_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:
            ts_dt = None
    symbol = payload.get("symbol") or "MNQ"
    o = _safe_float(payload.get("open"))
    h = _safe_float(payload.get("high"))
    l = _safe_float(payload.get("low"))
    c = _safe_float(payload.get("close"))
    vol = _safe_int(payload.get("volume"))
    async with state_lock:
        state = _get_bot_state(bot_id)
        prev_ts = state.get("last_bar_ts")
        current_mode = state.get("mode", "LIVE")
        state = update_bot_state(
            bot_id,
            instrument=symbol,
            mode=payload.get("mode", current_mode),
        )
        state["last_bar_ts"] = ts
        if ts_dt is not None:
            state["last_bar_dt"] = ts_dt.isoformat()
        state["last_price"] = c
        state["last_ohlc"] = {"open": o, "high": h, "low": l, "close": c}
        state["last_volume"] = vol
        state["instrument"] = symbol
        state["sessionBarCount"] = payload.get("sessionBarCount", state.get("sessionBarCount"))
        state["last_vwap"] = payload.get("vwap")
        state["vol_ok"] = payload.get("volOk")
        recent_bars = bars_store.setdefault(bot_id, [])
        recent_bars.append(payload.copy())
        if len(recent_bars) > MAX_BARS_CACHE:
            del recent_bars[: len(recent_bars) - MAX_BARS_CACHE]
        if prev_ts and ts:
            try:
                prev_dt = datetime.fromisoformat(prev_ts.replace("Z", "+00:00"))
                curr_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                diff_ms = int(max(0, (curr_dt - prev_dt).total_seconds() * 1000))
                if diff_ms > 0:
                    state["bar_interval_ms"] = diff_ms
            except Exception:
                pass

    asyncio.create_task(asyncio.to_thread(_save_bar_sync, bot_id, payload))
    await _broadcast_live(
        {
            "type": "bar_update",
            "data": {
                "symbol": symbol,
                "price": c,
                "ohlc": {"open": o, "high": h, "low": l, "close": c},
                "volume": vol,
                "timestamp": ts,
            },
        }
    )
    await _run_inference_and_update(bot_id, payload)


async def _handle_monitor(bot_id: str, payload: Dict[str, Any]) -> None:
    async with state_lock:
        state = _get_bot_state(bot_id)
        state["strategyMonitor"] = payload
        state["strategyMonitor_ts"] = payload.get("ts") or _iso(datetime.now(timezone.utc))
        state["mode"] = payload.get("mode") or state.get("mode") or "UNKNOWN"
    asyncio.create_task(asyncio.to_thread(_save_monitor_snapshot_sync, bot_id, payload))
    await _broadcast_live(
        {
            "type": "bot_status",
            "data": {
                "status": {
                    "botId": bot_id,
                    "mode": _get_bot_state(bot_id).get("mode"),
                    "last_seen_utc": _iso(datetime.now(timezone.utc)),
                    "instrument": _get_bot_state(bot_id).get("instrument"),
                }
            },
        }
    )


async def _handle_trade_event(bot_id: str, payload: Dict[str, Any]) -> None:
    asyncio.create_task(asyncio.to_thread(_save_trade_event_sync, bot_id, payload))
    async with state_lock:
        _append_log(bot_id, {"id": payload.get("orderId", "<unknown>"), "event": "TRADE_EVENT", "ts": _iso(datetime.now(timezone.utc)), "payload": payload})
    await _broadcast_live({"type": "trade_event", "data": {"botId": bot_id, "payload": payload}})


async def _handle_ack(bot_id: str, payload: Dict[str, Any]) -> None:
    cmd_id = payload.get("id")
    status = payload.get("status") or "ACK"
    if cmd_id:
        async with state_lock:
            _update_log_event(bot_id, cmd_id, f"ACK_{status}", {"ack": payload})


def compute_wyckoff_signal(bars: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not bars:
        return {"signal": "NONE", "phase": "NEUTRAL", "confidence": 0.0, "explain": "No bars provided"}
    import pandas as pd

    df = pd.DataFrame(bars)
    column_mapping = {
        "ts": "ts_utc",
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
        "timeframe": "timeframe",
        "symbol": "symbol",
    }
    df = df.rename(columns=column_mapping)
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            df[col] = 0.0
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)
    signal = ml_service._wyckoff_phase_analysis(df).get("last_event")
    signal_value = signal or "NONE"
    bias = "NEUTRAL"
    if signal_value in ("SPRING", "BUYING_CLIMAX"):
        bias = "BULLISH"
    elif signal_value in ("DOWNTHRUST", "SELLING_CLIMAX"):
        bias = "BEARISH"
    explanation = f"Wyckoff event: {signal_value}"
    return {"signal": signal_value, "bias": bias, "confidence": 0.0, "explain": explanation}
