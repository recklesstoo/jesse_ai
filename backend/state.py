from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket

ws_bots: Dict[str, WebSocket] = {}
ws_live_clients: Set[WebSocket] = set()
ws_last_rx_ts: Dict[str, datetime] = {}
bot_state: Dict[str, Dict[str, Any]] = {}
state_lock = asyncio.Lock()


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
