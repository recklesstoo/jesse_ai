from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
import os
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket

ws_bots: Dict[str, WebSocket] = {}
ws_live_clients: Set[WebSocket] = set()
bot_state: Dict[str, Dict[str, Any]] = {}
state_lock = asyncio.Lock()

FEED_STALE_SEC_DEFAULT_1S = float(os.getenv("WYCKOFF_FEED_STALE_SEC_DEFAULT_1S", "10.0"))
FEED_STALE_SEC_DEFAULT_1M = float(os.getenv("WYCKOFF_FEED_STALE_SEC_DEFAULT_1M", "180.0"))
FEED_STALE_SEC_FALLBACK = float(os.getenv("WYCKOFF_FEED_STALE_SEC_FALLBACK", "10.0"))
MONITOR_STALE_SEC_FALLBACK = float(os.getenv("WYCKOFF_MONITOR_STALE_SEC_FALLBACK", "30.0"))
AI_MIN_LIVE_BARS = int(os.getenv("WYCKOFF_AI_MIN_LIVE_BARS", "50"))
WS_STALE_SEC_FALLBACK = float(os.getenv("WYCKOFF_WS_STALE_SEC_FALLBACK", "2.0"))


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


def _parse_timeframe_seconds(value: Any) -> Optional[float]:
    if not value:
        return None
    raw = str(value).strip().lower()
    raw = (
        raw.replace("minutes", "minute")
        .replace("mins", "min")
        .replace("seconds", "second")
        .replace("secs", "sec")
    )

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


def _normalize_nt_mode(value: Any) -> str:
    if not value:
        return "UNKNOWN"
    raw = str(value).strip().upper()
    if not raw:
        return "UNKNOWN"
    if "BACK" in raw or "HIST" in raw or "ANALYZ" in raw:
        return "BACKTEST"
    if "LIVE" in raw or "REAL" in raw:
        return "LIVE"
    return "UNKNOWN"


def _compute_feed_stale_sec(timeframe_seconds: Optional[float]) -> float:
    if timeframe_seconds is None or timeframe_seconds <= 0:
        return FEED_STALE_SEC_FALLBACK
    if timeframe_seconds <= 2:
        return max(FEED_STALE_SEC_DEFAULT_1S, 3.0 * timeframe_seconds)
    if timeframe_seconds >= 60:
        return max(FEED_STALE_SEC_DEFAULT_1M, 3.0 * timeframe_seconds)
    return max(FEED_STALE_SEC_FALLBACK, 3.0 * timeframe_seconds)


def _compute_monitor_stale_sec(monitor_interval_sec: Optional[float]) -> float:
    if monitor_interval_sec is None or monitor_interval_sec <= 0:
        return MONITOR_STALE_SEC_FALLBACK
    return max(MONITOR_STALE_SEC_FALLBACK, 3.0 * monitor_interval_sec)


def compute_feed_status(bot_id: str) -> Dict[str, Any]:
    state = _get_bot_state(bot_id)

    now = _utc_now()

    ws_connected = bool(state.get("connected"))
    ws_open = ws_connected

    # last_seen_utc is authoritative: updated only on BAR_DATA/HEARTBEAT receive time.
    last_seen_dt = _parse_dt(state.get("last_seen_utc"))
    last_seen_age_sec: Optional[float] = None
    if last_seen_dt is not None:
        last_seen_age_sec = (now - last_seen_dt).total_seconds()

    last_ws_rx_dt = _parse_dt(state.get("last_ws_rx_utc"))
    ws_age_sec: Optional[float] = None
    if last_ws_rx_dt is not None:
        ws_age_sec = (now - last_ws_rx_dt).total_seconds()

    bar_interval_ms = state.get("bar_interval_ms")
    interval_sec: Optional[float] = None
    if bar_interval_ms is not None:
        try:
            interval_sec = max(0.0, float(bar_interval_ms) / 1000.0)
        except Exception:
            interval_sec = None
    if interval_sec is None:
        interval_sec = _parse_timeframe_seconds(state.get("timeframe"))

    feed_stale_sec = _compute_feed_stale_sec(interval_sec)
    ws_stale_sec = max(WS_STALE_SEC_FALLBACK, min(10.0, feed_stale_sec))

    last_bar_rx_dt = _parse_dt(state.get("last_bar_rx_utc"))
    bar_age_sec: Optional[float] = None
    if last_bar_rx_dt is not None:
        bar_age_sec = (now - last_bar_rx_dt).total_seconds()

    last_monitor_rx_dt = _parse_dt(state.get("last_monitor_rx_utc"))
    monitor_age_sec: Optional[float] = None
    if last_monitor_rx_dt is not None:
        monitor_age_sec = (now - last_monitor_rx_dt).total_seconds()

    monitor_interval_sec: Optional[float] = None
    if state.get("monitor_interval_sec") is not None:
        try:
            monitor_interval_sec = float(state.get("monitor_interval_sec"))
        except Exception:
            monitor_interval_sec = None
    monitor_stale_sec = _compute_monitor_stale_sec(monitor_interval_sec)

    nt_mode = _normalize_nt_mode(state.get("last_mode"))
    last_bar_payload_dt = _parse_dt(state.get("last_bar_payload_ts_utc"))
    last_bar_payload_iso = last_bar_payload_dt.isoformat().replace("+00:00", "Z") if last_bar_payload_dt is not None else None

    explicit_source = state.get("data_source")
    explicit_source_norm = str(explicit_source).strip().upper() if explicit_source is not None else ""

    # Prefer explicit data_source markers written by WS handlers (e.g., UNKNOWN_TS),
    # otherwise derive from connection/cached state.
    if explicit_source_norm in {"UNKNOWN_TS", "SIMULATED"}:
        data_source = explicit_source_norm
    elif ws_connected:
        data_source = "LIVE_WS"
    elif state.get("last_price") is not None or last_bar_rx_dt is not None:
        data_source = "CACHED"
    else:
        data_source = "NONE"

    data_source_kind = "NONE"
    if data_source == "LIVE_WS":
        data_source_kind = "NINJA_REAL"
    elif data_source in {"SIMULATED", "UNKNOWN_TS", "CACHED"}:
        data_source_kind = data_source

    # v1 status aligns with Market Metrics: LIVE|STALE|NO_LIVE.
    # Rule: only LIVE_WS + fresh BAR_DATA can be LIVE.
    if last_bar_rx_dt is None:
        feed_status = "NO_LIVE"
    elif data_source == "UNKNOWN_TS":
        feed_status = "STALE"
    elif data_source != "LIVE_WS":
        feed_status = "NO_LIVE"
    elif bar_age_sec is not None and bar_age_sec <= feed_stale_sec:
        feed_status = "LIVE"
    else:
        feed_status = "STALE"

    if last_monitor_rx_dt is None:
        monitor_status = "NO_MONITOR"
    elif monitor_age_sec is not None and monitor_age_sec <= monitor_stale_sec:
        monitor_status = "OK"
    else:
        monitor_status = "STALE"

    # Canonical high-level mode (platform state), distinct from feed freshness.
    raw_mode = state.get("mode") or state.get("last_mode") or ""
    raw_mode_u = str(raw_mode).strip().upper()
    if raw_mode_u.startswith("SIM"):
        mode = "SIM"
    elif nt_mode == "BACKTEST":
        mode = "BACKTEST"
    elif nt_mode == "LIVE":
        mode = "LIVE"
    else:
        mode = "UNKNOWN"

    # Explain "STALE" concisely for UI tooltips.
    feed_reason = "ok"
    if last_bar_rx_dt is None:
        feed_reason = "no BAR_DATA received"
    elif data_source == "UNKNOWN_TS":
        feed_reason = "BAR_DATA missing/invalid timestamp (UNKNOWN_TS)"
    elif data_source != "LIVE_WS":
        feed_reason = f"data_source={data_source}"
    elif bar_age_sec is not None and bar_age_sec > feed_stale_sec:
        feed_reason = f"bar_age_sec>{round(feed_stale_sec, 3)}"
    elif ws_age_sec is not None and ws_age_sec > ws_stale_sec:
        feed_reason = f"ws_age_sec>{round(ws_stale_sec, 3)}"

    # Backward-compatible alias used by older UI/widgets/tests.
    # Legacy used "NO_FEED" where v1 uses "NO_LIVE".
    feed_status_legacy = "NO_FEED" if feed_status == "NO_LIVE" else feed_status

    # Connection health (for "Connected" UI): ws open + last_seen receive time.
    # IMPORTANT:
    # - BAR_DATA may arrive only once per minute (1m) while WS is still healthy.
    # - MONITOR is a real Ninja WS message too, and ws_age_sec tracks any WS activity.
    # Use ws_age_sec + ws_stale_sec for connection health to avoid "DISCONNECTED" flicker.
    conn_threshold_sec = float(max(5.0, min(30.0, ws_stale_sec)))
    connection_status = "DISCONNECTED"
    if ws_open:
        conn_age = ws_age_sec if ws_age_sec is not None else last_seen_age_sec
        if conn_age is not None and conn_age <= conn_threshold_sec:
            connection_status = "OK"
        else:
            connection_status = "STALE"

    # Stream source label (UI should treat only NINJA as real-time).
    data_source_stream = "UNKNOWN"
    if ws_open and connection_status == "OK" and data_source == "LIVE_WS":
        data_source_stream = "NINJA"
    elif data_source in {"CACHED", "SIMULATED", "UNKNOWN_TS"}:
        data_source_stream = data_source
    elif data_source == "NONE":
        data_source_stream = "UNKNOWN"

    return {
        "bot_id": bot_id,
        "feed_status": feed_status,
        "feed_status_legacy": feed_status_legacy,
        "ws_connected": ws_connected,
        "transport_connected": ws_connected,
        "ws_open": ws_open,
        "last_seen_utc": _iso(last_seen_dt),
        "last_seen_age_seconds": last_seen_age_sec,
        "connection_status": connection_status,
        "ws_age_sec": ws_age_sec,
        "ws_stale_sec": ws_stale_sec,
        "monitor_status": monitor_status,
        "bar_age_sec": bar_age_sec,
        "monitor_age_sec": monitor_age_sec,
        "feed_stale_sec": feed_stale_sec,
        "monitor_stale_sec": monitor_stale_sec,
        "mode": mode,
        "nt_mode": nt_mode,
        "data_source": data_source,
        "data_source_kind": data_source_kind,
        "data_source_stream": data_source_stream,
        "feed_reason": feed_reason,
        "last_mode": state.get("last_mode"),
        "last_bar_ts_utc": last_bar_payload_iso,
        "last_bar_rx_utc": _iso(last_bar_rx_dt),
        "last_monitor_rx_utc": _iso(last_monitor_rx_dt),
        "bar_interval_ms": bar_interval_ms,
        "instrument": state.get("instrument"),
        "timeframe_text": state.get("timeframe"),
        "last_symbol": state.get("instrument"),
        "last_timeframe": state.get("timeframe"),
        "last_price": state.get("last_price"),
        "last_ohlc": state.get("last_ohlc"),
        "last_volume": state.get("last_volume"),
        "last_vwap": state.get("last_vwap"),
        "vol_ok": state.get("vol_ok"),
        # Backpressure / diagnostics (optional; stable keys for ops/UI).
        "dropped_bar_count": int(state.get("dropped_bar_count") or 0),
        "last_drop_ts_utc": state.get("last_drop_ts_utc"),
        "drop_reason": state.get("drop_reason"),
        "dropped_persist_bar_count": int(state.get("dropped_persist_bar_count") or 0),
        "last_persist_drop_ts_utc": state.get("last_persist_drop_ts_utc"),
    }
