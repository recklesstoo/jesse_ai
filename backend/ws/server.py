from __future__ import annotations

import asyncio
import json
import os
import random
from datetime import datetime, timezone
from threading import Lock as ThreadLock
from time import sleep
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
from backend.market.buffer import MarketBar, market_buffer, normalize_timeframe
from backend.market.metrics import compute_market_metrics_v1
from backend.state import compute_feed_status
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

# WS backpressure (BAR_DATA flood protection).
BAR_RATE_PER_SEC = float(os.getenv("WYCKOFF_WS_BAR_RATE_PER_SEC", "10.0"))
BAR_BURST = float(os.getenv("WYCKOFF_WS_BAR_BURST", "20.0"))
_bar_bucket: dict[str, dict[str, Any]] = {}

# Backpressure guards: Ninja/Bridge can flood BAR_DATA (especially in BACKTEST/replay).
# Keep the WS receive loop fast by throttling expensive work.
_inference_inflight: set[str] = set()
_last_bar_update_broadcast_utc: dict[str, datetime] = {}
_last_market_metrics_broadcast_utc: dict[str, datetime] = {}

# DB persistence batching (prevents task/DB flood from high-frequency BAR_DATA).
_persist_lock = ThreadLock()
_pending_bar_persist: dict[str, Dict[str, Any]] = {}
_bar_persist_tasks: dict[str, asyncio.Task] = {}


def _schedule_persist_bar(bot_id: str, payload: Dict[str, Any]) -> bool:
    """
    Coalesce BAR_DATA DB writes per bot: keep only the latest pending payload.
    Returns True if an older pending payload was replaced (dropped).
    """
    replaced = False
    with _persist_lock:
        replaced = bot_id in _pending_bar_persist
        _pending_bar_persist[bot_id] = payload
        t = _bar_persist_tasks.get(bot_id)
        if t is None or t.done():
            _bar_persist_tasks[bot_id] = asyncio.create_task(_persist_bar_worker(bot_id))
    return replaced


async def _persist_bar_worker(bot_id: str) -> None:
    while True:
        with _persist_lock:
            payload = _pending_bar_persist.pop(bot_id, None)
        if payload is None:
            return
        try:
            await asyncio.to_thread(_save_bar_sync, bot_id, payload)
        except Exception:
            # Never let DB issues impact WS health.
            await asyncio.sleep(0)


def _allow_bar(bot_id: str, now: datetime) -> bool:
    """
    Token bucket per bot for BAR_DATA. If we drop bars, we still keep MONITOR/ACK/TRADE_EVENT flowing.
    """
    rate = max(0.1, float(BAR_RATE_PER_SEC))
    burst = max(1.0, float(BAR_BURST))
    st = _bar_bucket.get(bot_id)
    if st is None:
        st = {"tokens": burst, "last": now, "dropped": 0, "last_drop": None}
        _bar_bucket[bot_id] = st
    last = st.get("last") or now
    if isinstance(last, datetime):
        elapsed = max(0.0, (now - last).total_seconds())
    else:
        elapsed = 0.0
    st["last"] = now
    st["tokens"] = min(burst, float(st.get("tokens") or burst) + (elapsed * rate))
    if float(st["tokens"]) < 1.0:
        st["dropped"] = int(st.get("dropped") or 0) + 1
        st["last_drop"] = now
        return False
    st["tokens"] = float(st["tokens"]) - 1.0
    return True


def _parse_ws_message(raw: str, path_bot_id: str) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    """
    Accepts both legacy and Bridge WS v2 envelope fields.

    v2 envelope (top-level): v, source, botId, seq, send_ts_utc
    legacy: {type: "...", payload: {...}}
    """
    message = json.loads(raw)
    msg_type = (message.get("type") or "").upper()
    payload = message.get("payload") or {}

    env: dict[str, Any] = {
        "v": message.get("v"),
        "source": message.get("source"),
        "botId": message.get("botId") or message.get("bot_id"),
        "seq": message.get("seq"),
        "send_ts_utc": message.get("send_ts_utc"),
    }

    effective_bot_id = (env.get("botId") or path_bot_id or "").strip() or path_bot_id
    # Enforce WS path as source-of-truth for routing. Keep mismatch only for diagnostics.
    if effective_bot_id != path_bot_id:
        env["botId_mismatch"] = {"path": path_bot_id, "envelope": effective_bot_id}
        effective_bot_id = path_bot_id

    if isinstance(payload, dict):
        tf = payload.get("timeframe")
        if tf is not None:
            payload["timeframe"] = normalize_timeframe(tf)

    return effective_bot_id, msg_type, payload, env


def _commit_with_retry(db, *, label: str, max_attempts: int = 5) -> bool:
    """
    SQLite can transiently raise "database is locked" under concurrent WS writes.
    This is a best-effort retry to avoid noisy errors in logs.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            db.commit()
            return True
        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()
            if "database is locked" not in msg:
                break
            try:
                db.rollback()
            except Exception:
                pass
            sleep(min(0.25 * attempt, 1.0))
    if last_exc is not None:
        print(f"[ws] {label} commit failed: {last_exc}")
    return False


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
        for key in ("bar_ts_utc", "barTsUtc", "timestamp", "ts", "time", "bar_ts", "barTs", "t"):
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
        _commit_with_retry(db, label="save_bar")
    except Exception as exc:
        try:
            from backend.state import _get_bot_state, _iso, state_lock

            # Best-effort in-memory diagnostics. Never block on the lock here.
            st = _get_bot_state(bot_id)
            st["db_bar_errors"] = int(st.get("db_bar_errors") or 0) + 1
            st["last_db_bar_error_utc"] = _iso(datetime.now(timezone.utc))
            st["last_db_bar_error"] = str(exc)
        except Exception:
            pass
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
        _commit_with_retry(db, label="save_signal")
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
        _commit_with_retry(db, label="save_monitor_snapshot")
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
        _commit_with_retry(db, label="save_trade_event")
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
                        "last_ws_rx_utc": _iso(now),
                    },
                )
            try:
                effective_bot_id, msg_type, payload, env = _parse_ws_message(raw, bot_id)
            except Exception:
                continue

            # Persist envelope metadata for diagnostics.
            try:
                async with state_lock:
                    st = _get_bot_state(effective_bot_id)
                    if env.get("v") is not None:
                        st["bridge_v"] = env.get("v")
                    if env.get("source") is not None:
                        st["bridge_source"] = env.get("source")
                    if env.get("seq") is not None:
                        st["bridge_seq"] = env.get("seq")
                    if env.get("send_ts_utc") is not None:
                        st["bridge_send_ts_utc"] = env.get("send_ts_utc")
                    if env.get("botId_mismatch") is not None:
                        st["bridge_botId_mismatch"] = env.get("botId_mismatch")
            except Exception:
                pass

            if msg_type == "BAR_DATA":
                # Backpressure: drop low-priority bars when client floods.
                if not _allow_bar(effective_bot_id, now):
                    async with state_lock:
                        st = _get_bot_state(effective_bot_id)
                        st["dropped_bar_count"] = int(st.get("dropped_bar_count") or 0) + 1
                        st["last_drop_ts_utc"] = _iso(now)
                        st["drop_reason"] = "bar_rate_limited"
                    continue
                await _handle_bar_data(effective_bot_id, payload)
            elif msg_type in ("HEARTBEAT", "PING"):
                await _handle_heartbeat(effective_bot_id, payload)
            elif msg_type == "MONITOR":
                await _handle_monitor(effective_bot_id, payload)
            elif msg_type == "TRADE_EVENT":
                await _handle_trade_event(effective_bot_id, payload)
            elif msg_type == "ACK":
                await _handle_ack(effective_bot_id, payload)

    except WebSocketDisconnect as exc:
        try:
            client = getattr(websocket, "client", None)
            code = getattr(exc, "code", None)
            print(f"[ws] ws_bot disconnect bot_id={bot_id} client={client} code={code}")
        except Exception:
            pass
    except Exception as exc:
        try:
            client = getattr(websocket, "client", None)
            print(f"[ws] ws_bot error bot_id={bot_id} client={client} err={exc!r}")
        except Exception:
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
    mode_raw = payload.get("nt_mode") or payload.get("mode")
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
    timeframe = normalize_timeframe(payload.get("timeframe"))
    # Ensure downstream consumers (DB + caches) see canonical keys.
    payload["symbol"] = symbol
    payload["timeframe"] = timeframe
    if ts_iso and not payload.get("timestamp"):
        payload["timestamp"] = ts_iso
    o = _safe_float(payload.get("open"))
    h = _safe_float(payload.get("high"))
    l = _safe_float(payload.get("low"))
    c = _safe_float(payload.get("close"))
    vol = _safe_int(payload.get("volume"))
    bid = _safe_float(payload.get("bid") or payload.get("Bid"))
    ask = _safe_float(payload.get("ask") or payload.get("Ask"))

    if ts is None:
        # Never crash the WS if a BAR_DATA arrives without a valid timestamp.
        async with state_lock:
            state = _get_bot_state(bot_id)
            state["feed_status"] = "STALE"
            state["data_source"] = "UNKNOWN_TS"
            state["last_seen_utc"] = _iso(now)
            state["last_bar_rx_utc"] = _iso(now)
            state["last_bad_bar_ts_utc"] = _iso(now)
            state["last_bad_bar_ts_reason"] = "missing_or_invalid_ts"
        print(f"[ws] BAR_DATA missing/invalid timestamp; bot_id={bot_id} keys={sorted(list(payload.keys()))}")
        return

    persist_new_bar = False
    async with state_lock:
        state = _get_bot_state(bot_id)
        prev_ts = state.get("last_bar_payload_ts_utc") or state.get("last_bar_ts")
        current_mode = state.get("mode", "LIVE")
        incoming_mode = payload.get("nt_mode") or payload.get("mode") or current_mode
        state = update_bot_state(
            bot_id,
            instrument=symbol,
            mode=incoming_mode,
        )
        # last_seen_utc must reflect WS receive time (never payload ts).
        state["last_seen_utc"] = _iso(now)
        state["last_bar_ts"] = ts_iso
        state["last_bar_payload_ts_utc"] = ts_iso
        state["bar_ts_utc"] = ts_iso
        state["last_bar_rx_utc"] = _iso(now)
        if incoming_mode is not None:
            state["last_mode"] = incoming_mode
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

        # Coalesce DB persistence: persist only when the payload bar timestamp advances for this timeframe.
        try:
            if timeframe:
                m = state.get("last_persisted_bar_ts_by_tf")
                if not isinstance(m, dict):
                    m = {}
                if m.get(timeframe) != ts_iso:
                    m[timeframe] = ts_iso
                    state["last_persisted_bar_ts_by_tf"] = m
                    persist_new_bar = True
        except Exception:
            persist_new_bar = False

    # Update market ring-buffer (symbol+timeframe) for deterministic market metrics.
    try:
        market_buffer.add_bar(
            MarketBar(
                ts_utc=ts.astimezone(timezone.utc),
                symbol=str(symbol),
                timeframe=str(timeframe or ""),
                open=float(o or 0.0),
                high=float(h or 0.0),
                low=float(l or 0.0),
                close=float(c or 0.0),
                volume=int(vol or 0),
                bid=float(bid) if bid is not None else None,
                ask=float(ask) if ask is not None else None,
                rx_ts_utc=now,
            )
        )
    except Exception:
        # Never break WS path on metrics cache updates.
        pass

    # Persist BAR_DATA to DB only on new bars (per timeframe) and coalesce pending writes.
    if persist_new_bar:
        replaced = _schedule_persist_bar(bot_id, payload)
        if replaced:
            async with state_lock:
                st = _get_bot_state(bot_id)
                st["dropped_persist_bar_count"] = int(st.get("dropped_persist_bar_count") or 0) + 1
                st["last_persist_drop_ts_utc"] = _iso(now)

    # Throttle bar_update broadcasts (UI can render from Market Metrics v1 anyway).
    try:
        last = _last_bar_update_broadcast_utc.get(bot_id)
        if last is None or (now - last).total_seconds() >= 0.25:
            _last_bar_update_broadcast_utc[bot_id] = now
            asyncio.create_task(
                _broadcast_live(
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
            )
    except Exception:
        pass

    # Broadcast Market Metrics v1 snapshots so the UI and assistant see the same facts.
    try:
        # Throttle metrics broadcasts to avoid blocking Ninja WS receive loop.
        do_broadcast = True
        last_mm = _last_market_metrics_broadcast_utc.get(bot_id)
        if last_mm is not None and (now - last_mm).total_seconds() < 1.0:
            do_broadcast = False
        else:
            _last_market_metrics_broadcast_utc[bot_id] = now

        now_utc = now
        feed = compute_feed_status(bot_id)
        data_source = (feed.get("data_source") or "UNKNOWN").upper()
        platform_fs = (feed.get("feed_status") or "").upper()

        def _to_z(value: Optional[str]) -> Optional[str]:
            if not value:
                return None
            s = str(value).strip()
            if s.endswith("Z"):
                return s
            if s.endswith("+00:00"):
                return s.replace("+00:00", "Z")
            return s

        last_ws_ts_utc = _to_z(feed.get("last_seen_utc") or feed.get("last_ws_rx_utc"))
        ws_age_sec = feed.get("ws_age_sec")

        if do_broadcast:
            # Always publish 1m and 5m (if present) for the current symbol.
            for tf in ("1m", "5m"):
                bars_tf = market_buffer.get_bars(symbol=str(symbol), timeframe=tf, limit=500)
                last_rx = market_buffer.last_rx_ts(symbol=str(symbol), timeframe=tf)
                bar_age_sec = float(max(0.0, (now_utc - last_rx).total_seconds())) if last_rx is not None else None
                metrics, notes = compute_market_metrics_v1(
                    bars=bars_tf,
                    symbol=str(symbol).upper(),
                    timeframe=tf,
                    ws_age_sec=ws_age_sec,
                    bar_age_sec_override=bar_age_sec,
                    last_ws_ts_utc=last_ws_ts_utc,
                    ws_stale_sec=10.0,
                    lookback=500,
                    mode="summary",
                )

                # Coherence/anti-invention gating (same policy as the HTTP endpoint):
                def _freshness_note() -> str:
                    ws_age_s = "null" if metrics.get("ws_age_sec") is None else f"{float(metrics.get('ws_age_sec')):.3f}"
                    bar_age_s = "null" if metrics.get("bar_age_sec") is None else f"{float(metrics.get('bar_age_sec')):.3f}"
                    return (
                        "freshness:"
                        f" ws_age_sec={ws_age_s}"
                        f" bar_age_sec={bar_age_s}"
                        f" ws_stale_sec={float(metrics.get('ws_stale_sec') or 10.0):.3f}"
                        f" bar_stale_sec={float(metrics.get('bar_stale_sec') or 0.0):.3f}"
                    )

                if data_source != "LIVE_WS":
                    metrics["source"] = data_source
                    metrics["feed_status"] = "NO_LIVE"
                    metrics["confidence"] = "low"
                    notes.append(f"non-live data_source={data_source}")
                    notes.append(_freshness_note())
                else:
                    metrics["source"] = "LIVE_WS"

                if platform_fs != "LIVE":
                    if platform_fs == "NO_LIVE":
                        metrics["feed_status"] = "NO_LIVE"
                    elif metrics.get("feed_status") == "LIVE":
                        metrics["feed_status"] = "STALE"
                    metrics["confidence"] = "low"
                    notes.append(f"platform feed_status={platform_fs}")
                    notes.append(_freshness_note())

                if metrics.get("source") != "LIVE_WS" or metrics.get("feed_status") in {"STALE", "NO_LIVE"}:
                    metrics["confidence"] = "low"
                    notes.append(_freshness_note())

                metrics["notes"] = list(dict.fromkeys(notes))

                asyncio.create_task(
                    _broadcast_live(
                        {
                            "type": "market_metrics",
                            "data": {"botId": bot_id, "symbol": str(symbol).upper(), "timeframe": tf, "metrics": metrics},
                        }
                    )
                )
    except Exception:
        pass

    # Never block the WS receive loop on inference. Ensure at most one in-flight job per bot.
    try:
        if bot_id not in _inference_inflight:
            _inference_inflight.add(bot_id)

            async def _infer_guarded() -> None:
                try:
                    await _run_inference_and_update(bot_id, payload)
                finally:
                    _inference_inflight.discard(bot_id)

            asyncio.create_task(_infer_guarded())
    except Exception:
        _inference_inflight.discard(bot_id)


async def _handle_heartbeat(bot_id: str, payload: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    async with state_lock:
        state = _get_bot_state(bot_id)
        state["last_seen_utc"] = _iso(now)
        state["last_heartbeat_rx_utc"] = _iso(now)
        if payload.get("mode") is not None:
            state["last_mode"] = payload.get("mode")
    asyncio.create_task(asyncio.to_thread(_save_event_sync, bot_id, "HEARTBEAT_RX", {"botId": bot_id}))


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
        _commit_with_retry(db, label="save_system_event")
    except Exception as exc:
        print(f"[ws] Event save error: {exc}")
    finally:
        db.close()
