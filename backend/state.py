from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
import os
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket

ws_bots: Dict[str, WebSocket] = {}
ws_live_clients: Set[WebSocket] = set()
ws_last_rx_ts: Dict[str, datetime] = {}
bot_state: Dict[str, Dict[str, Any]] = {}
state_lock = asyncio.Lock()

FEED_LIVE_MAX_AGE_SEC = float(os.getenv("WYCKOFF_FEED_LIVE_MAX_AGE_SEC", "3.0"))
AI_MIN_LIVE_BARS = int(os.getenv("WYCKOFF_AI_MIN_LIVE_BARS", "50"))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (ValueError, TypeError):
        return None


def _get_bot_state(bot_id: str) -> Dict[str, Any]:
    return bot_state.setdefault(bot_id, {})


def _set_bot_state(bot_id: str, patch: Dict[str, Any]) -> None:
    state = _get_bot_state(bot_id)
    state.update(patch)


def _append_log(bot_id: str, row: Dict[str, Any]) -> None:
    state = _get_bot_state(bot_id)
    log = state.setdefault("command_log", [])
    log.insert(0, row)
    if len(log) > 500:
        del log[500:]


def _update_log_event(bot_id: str, cmd_id: str, event: str, payload: Optional[Dict[str, Any]] = None) -> None:
    state = _get_bot_state(bot_id)
    log = state.setdefault("command_log", [])
    for entry in log:
        if entry.get("id") == cmd_id:
            entry["event"] = event
            entry["ts"] = _iso(_utc_now())
            if payload is not None:
                entry["payload"] = payload
            return
    _append_log(bot_id, {"id": cmd_id, "event": event, "ts": _iso(_utc_now()), "payload": payload or {}})


async def _broadcast_live(payload: Dict[str, Any]) -> None:
    dead_connections: List[WebSocket] = []
    message = json.dumps(payload, ensure_ascii=False)
    for client in list(ws_live_clients):
        try:
            await client.send_text(message)
        except Exception:
            dead_connections.append(client)
    for client in dead_connections:
        ws_live_clients.discard(client)


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def compute_feed_status(bot_id: str) -> Dict[str, Any]:
    state = _get_bot_state(bot_id)
    ws_connected = bool(state.get("connected"))

    last_bar_ts = state.get("last_bar_dt") or state.get("last_bar_ts")
    last_bar_dt = _parse_dt(last_bar_ts)
    bar_age_sec: Optional[float] = None
    if last_bar_dt is not None:
        bar_age_sec = (_utc_now() - last_bar_dt).total_seconds()

    bar_interval_ms = state.get("bar_interval_ms")
    interval_sec: Optional[float] = None
    if bar_interval_ms is not None:
        try:
            interval_sec = max(0.0, float(bar_interval_ms) / 1000.0)
        except Exception:
            interval_sec = None

    def _parse_timeframe_seconds(value: Any) -> Optional[float]:
        if not value:
            return None
        raw = str(value).strip().lower()
        raw = raw.replace("minutes", "minute").replace("mins", "min").replace("seconds", "second").replace("secs", "sec")
        import re

        m = re.match(r"^(\d+)\s*(s|sec|second)$", raw)
        if m:
            return float(m.group(1))
        m = re.match(r"^(\d+)\s*(m|min|minute)$", raw)
        if m:
            return float(m.group(1)) * 60.0
        m = re.match(r"^(\d+)\s*(h|hour)$", raw)
        if m:
            return float(m.group(1)) * 3600.0
        m = re.match(r"^(\d+)(s|m|h)$", raw)
        if m:
            n = float(m.group(1))
            unit = m.group(2)
            return n if unit == "s" else (n * 60.0 if unit == "m" else n * 3600.0)
        return None

    if interval_sec is None:
        interval_sec = _parse_timeframe_seconds(state.get("timeframe"))

    feed_stale_threshold_sec = FEED_LIVE_MAX_AGE_SEC
    if interval_sec is not None and interval_sec > 0:
        feed_stale_threshold_sec = max(FEED_LIVE_MAX_AGE_SEC, interval_sec * 1.5 + 1.0)

    monitor_ts = state.get("strategyMonitor_ts")
    monitor_dt = _parse_dt(monitor_ts)
    monitor_age_sec: Optional[float] = None
    if monitor_dt is not None:
        monitor_age_sec = (_utc_now() - monitor_dt).total_seconds()

    feed_status = "LIVE" if (ws_connected and bar_age_sec is not None and bar_age_sec <= feed_stale_threshold_sec) else "NO_FEED"

    return {
        "bot_id": bot_id,
        "feed_status": feed_status,
        "ws_connected": ws_connected,
        "last_bar_ts_utc": last_bar_dt.isoformat() if last_bar_dt is not None else None,
        "bar_age_sec": bar_age_sec,
        "monitor_age_sec": monitor_age_sec,
        "bar_interval_ms": bar_interval_ms,
        "feed_stale_threshold_sec": feed_stale_threshold_sec,
        "last_symbol": state.get("instrument"),
        "last_timeframe": state.get("timeframe"),
        "last_price": state.get("last_price"),
        "last_ohlc": state.get("last_ohlc"),
        "last_volume": state.get("last_volume"),
        "last_vwap": state.get("last_vwap"),
        "vol_ok": state.get("vol_ok"),
    }
