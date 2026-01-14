from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import WebSocket, WebSocketDisconnect

from backend.compat import bars_store, update_bot_state
from backend.database import SessionLocal
from backend.models import (
    AISignal,
    Bar,
    MonitorSnapshot,
    SystemEvent,
    TradeEvent,
    DATA_SOURCE_LIVE_WS,
    DATA_SOURCE_SIMULATED,
)
from backend.services.ml_service import ml_service
from backend.state import (
    AI_MIN_LIVE_BARS,
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
    ws_live_clients,
)

MAX_BARS_CACHE = 400


def _open_db():
    return SessionLocal()


def _parse_timestamp(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts_utc(payload: Dict[str, Any]) -> Optional[datetime]:
    """
    Robust timestamp parsing for BAR_DATA payloads.

    Accepts keys: ts, time, timestamp, bar_ts, barTs, t
    Supports:
      - epoch seconds (int/float)
      - epoch milliseconds (heuristic > 1e12)
      - ISO8601 strings with Z or offset

    Returns timezone-aware datetime in UTC, or None. Never raises.
    """
    try:
        raw = None
        for key in ("ts", "time", "timestamp", "bar_ts", "barTs", "t"):
            if key in payload and payload.get(key) is not None:
                raw = payload.get(key)
                break

        if raw is None:
            return None

        if isinstance(raw, (int, float)):
            v = float(raw)
            if v > 1e12:
                v = v / 1000.0
            return datetime.fromtimestamp(v, tz=timezone.utc)

        raw_s = str(raw).strip()
        if not raw_s:
            return None

        # Numeric string epoch
        try:
            v = float(raw_s)
            if v > 1e12:
                v = v / 1000.0
            if v > 0:
                return datetime.fromtimestamp(v, tz=timezone.utc)
        except Exception:
            pass

        # ISO8601
        try:
            if raw_s.endswith("Z"):
                raw_s = raw_s.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(raw_s)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            return None
    except Exception:
        return None


def _save_bar_sync(bot_id: str, payload: Dict[str, Any]) -> None:
    db = _open_db()
    try:
        ts = _parse_timestamp(payload.get("timestamp"))
        now = datetime.now(timezone.utc)
        bar = Bar(
            bot_id=bot_id,
            symbol=payload.get("symbol"),
            timeframe=payload.get("timeframe"),
            ts_utc=ts,
            day_utc=ts.astimezone(timezone.utc).date().isoformat(),
            open=_safe_float(payload.get("open")),
            high=_safe_float(payload.get("high")),
            low=_safe_float(payload.get("low")),
            close=_safe_float(payload.get("close")),
            volume=_safe_int(payload.get("volume")),
            mode=payload.get("mode", "LIVE"),
            data_source=DATA_SOURCE_LIVE_WS,
            ingested_at_utc=now,
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
        now = datetime.now(timezone.utc)
        signal = AISignal(
            bot_id=bot_id,
            symbol=sig_data.get("symbol"),
            signal=sig_data.get("signal"),
            bias=sig_data.get("bias"),
            confidence=sig_data.get("confidence"),
            explain=sig_data.get("explain"),
            bar_ts_utc=_parse_timestamp(sig_data.get("barTs")),
            data_source=DATA_SOURCE_LIVE_WS,
            ingested_at_utc=now,
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
        now = datetime.now(timezone.utc)
        snapshot = MonitorSnapshot(
            bot_id=bot_id,
            data=payload,
            ts_utc=now,
            data_source=DATA_SOURCE_LIVE_WS,
            ingested_at_utc=now,
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
        now = datetime.now(timezone.utc)
        ts = _parse_timestamp(payload.get("ts"))
        trade = TradeEvent(
            bot_id=bot_id,
            symbol=payload.get("symbol"),
            action=payload.get("action"),
            qty=_safe_int(payload.get("qty")),
            price=_safe_float(payload.get("price")),
            ts_utc=ts,
            day_utc=ts.astimezone(timezone.utc).date().isoformat(),
            market_position=payload.get("marketPosition"),
            reason=payload.get("reason"),
            payload=payload,
            data_source=DATA_SOURCE_LIVE_WS,
            ingested_at_utc=now,
        )
        db.add(trade)
        db.commit()
    except Exception as exc:
        print(f"[ws] Trade event save error: {exc}")
    finally:
        db.close()


async def _run_inference_and_update(bot_id: str, payload: Dict[str, Any]) -> None:
    loop = asyncio.get_running_loop()
    if _get_bot_state(bot_id).get("live_bar_count", 0) < AI_MIN_LIVE_BARS:
        return

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


def _cleanup_bot(bot_id: str, websocket: WebSocket) -> None:
    if ws_bots.get(bot_id) is websocket:
        ws_bots.pop(bot_id, None)
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
    asyncio.create_task(asyncio.to_thread(_save_event_sync, bot_id, "BOT_CONNECTED", {"botId": bot_id}))
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
                now = datetime.now(timezone.utc)
                _set_bot_state(
                    bot_id,
                    {
                        "last_seen_utc": _iso(now),
                        "last_ws_rx_utc": _iso(now),
                    },
                )
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
        asyncio.create_task(asyncio.to_thread(_save_event_sync, bot_id, "BOT_DISCONNECTED", {"botId": bot_id}))
        await _broadcast_live(
            {
                "type": "bot_status",
                "data": {"status": {"botId": bot_id, "connected": False}},
            }
        )


async def _handle_bar_data(bot_id: str, payload: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    mode_raw = payload.get("mode")
    if mode_raw is not None and str(mode_raw).strip().upper().startswith("SIM"):
        asyncio.create_task(
            asyncio.to_thread(
                _save_event_sync,
                bot_id,
                "REJECTED_SIMULATED_BAR",
                {"botId": bot_id, "mode": mode_raw},
            )
        )
        return

    ts = _parse_ts_utc(payload)
    ts_iso = _iso_z(ts) if ts is not None else None
    symbol = payload.get("symbol") or "MNQ"
    timeframe = payload.get("timeframe")
    o = _safe_float(payload.get("open"))
    h = _safe_float(payload.get("high"))
    l = _safe_float(payload.get("low"))
    c = _safe_float(payload.get("close"))
    vol = _safe_int(payload.get("volume"))

    if ts is None:
        # Never crash the WS if a BAR_DATA arrives without a valid timestamp.
        async with state_lock:
            state = _get_bot_state(bot_id)
            state["feed_status"] = "STALE"
            state["data_source"] = "UNKNOWN_TS"
            state["last_bar_rx_utc"] = _iso(now)
            state["last_bad_bar_ts_utc"] = _iso(now)
            state["last_bad_bar_ts_reason"] = "missing_or_invalid_ts"
        print(f"[ws] BAR_DATA missing/invalid timestamp; bot_id={bot_id} keys={sorted(list(payload.keys()))}")
        return

    async with state_lock:
        state = _get_bot_state(bot_id)
        prev_ts = state.get("last_bar_payload_ts_utc") or state.get("last_bar_ts")
        current_mode = state.get("mode", "LIVE")
        state = update_bot_state(
            bot_id,
            instrument=symbol,
            mode=payload.get("mode", current_mode),
        )
        state["last_bar_ts"] = ts_iso
        state["last_bar_payload_ts_utc"] = ts_iso
        state["last_bar_rx_utc"] = _iso(now)
        if payload.get("mode") is not None:
            state["last_mode"] = payload.get("mode")
        state["last_bar_dt"] = ts.astimezone(timezone.utc).isoformat()
        state["last_price"] = c
        state["last_ohlc"] = {"open": o, "high": h, "low": l, "close": c}
        state["last_volume"] = vol
        state["instrument"] = symbol
        if timeframe:
            state["timeframe"] = timeframe
        state["sessionBarCount"] = payload.get("sessionBarCount", state.get("sessionBarCount"))
        state["last_vwap"] = payload.get("vwap")
        state["vol_ok"] = payload.get("volOk")
        state["live_bar_count"] = int(state.get("live_bar_count") or 0) + 1
        recent_bars = bars_store.setdefault(bot_id, [])
        recent_bars.append(payload.copy())
        if len(recent_bars) > MAX_BARS_CACHE:
            del recent_bars[: len(recent_bars) - MAX_BARS_CACHE]
        prev_dt = _parse_timestamp(str(prev_ts)) if prev_ts else None
        if prev_dt is not None and prev_dt.tzinfo is None:
            prev_dt = prev_dt.replace(tzinfo=timezone.utc)
        if prev_dt is not None and ts.tzinfo is not None:
            try:
                diff_ms = int(max(0, (ts - prev_dt.astimezone(timezone.utc)).total_seconds() * 1000))
                if diff_ms > 0:
                    state["bar_interval_ms"] = diff_ms
            except Exception:
                pass

    asyncio.create_task(asyncio.to_thread(_save_bar_sync, bot_id, payload))
    asyncio.create_task(
        asyncio.to_thread(
            _save_event_sync,
            bot_id,
            "BAR_DATA_RX",
            {"botId": bot_id, "symbol": symbol, "timeframe": timeframe, "mode": payload.get("mode")},
        )
    )
    await _broadcast_live(
        {
            "type": "bar_update",
            "data": {
                "botId": bot_id,
                "symbol": symbol,
                "price": c,
                "ohlc": {"open": o, "high": h, "low": l, "close": c},
                "volume": vol,
                "timestamp": ts_iso,
            },
        }
    )
    await _run_inference_and_update(bot_id, payload)


async def _handle_monitor(bot_id: str, payload: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    mode_raw = payload.get("mode")
    if mode_raw is not None and str(mode_raw).strip().upper().startswith("SIM"):
        asyncio.create_task(
            asyncio.to_thread(
                _save_event_sync,
                bot_id,
                "REJECTED_SIMULATED_MONITOR",
                {"botId": bot_id, "mode": mode_raw},
            )
        )
        return
    ts_raw = payload.get("ts") or payload.get("timestamp")
    ts_dt = _parse_timestamp(str(ts_raw)) if ts_raw else None
    ts_iso = _iso_z(ts_dt) if ts_dt is not None else _iso_z(now)
    interval = (
        payload.get("MonitorIntervalSec")
        or payload.get("monitorIntervalSec")
        or payload.get("intervalSec")
        or payload.get("interval")
    )
    async with state_lock:
        state = _get_bot_state(bot_id)
        state["strategyMonitor"] = payload
        state["strategyMonitor_ts"] = ts_iso
        state["last_monitor_payload_ts_utc"] = ts_iso
        state["last_monitor_rx_utc"] = _iso(now)
        state["mode"] = payload.get("mode") or state.get("mode") or "UNKNOWN"
        if payload.get("mode") is not None:
            state["last_mode"] = payload.get("mode")
        if interval is not None:
            try:
                state["monitor_interval_sec"] = float(interval)
            except Exception:
                pass
    asyncio.create_task(asyncio.to_thread(_save_monitor_snapshot_sync, bot_id, payload))
    asyncio.create_task(
        asyncio.to_thread(
            _save_event_sync,
            bot_id,
            "MONITOR_RX",
            {"botId": bot_id, "mode": payload.get("mode"), "interval": interval},
        )
    )
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
    asyncio.create_task(
        asyncio.to_thread(_save_event_sync, bot_id, "TRADE_EVENT_RX", {"botId": bot_id, "payload": payload})
    )
    async with state_lock:
        _append_log(bot_id, {"id": payload.get("orderId", "<unknown>"), "event": "TRADE_EVENT", "ts": _iso(datetime.now(timezone.utc)), "payload": payload})
    await _broadcast_live({"type": "trade_event", "data": {"botId": bot_id, "payload": payload}})


async def _handle_ack(bot_id: str, payload: Dict[str, Any]) -> None:
    cmd_id = payload.get("id")
    status = (payload.get("status") or "ACK").upper()
    if status.startswith("SIM"):
        # Hard stop: no simulated execution acks should ever reach the UI/logs.
        status = "REJECTED"
        payload = {**payload, "status": status, "reason": payload.get("reason") or "simulated acks disabled"}
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
def _save_event_sync(bot_id: str, event_type: str, data: Dict[str, Any]) -> None:
    db = _open_db()
    try:
        row = SystemEvent(
            bot_id=bot_id,
            event_type=event_type,
            data=data,
            data_source=DATA_SOURCE_LIVE_WS,
            ts_utc=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
    except Exception as exc:
        print(f"[ws] Event save error: {exc}")
    finally:
        db.close()
