from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import init_shadow_db
from backend.database import Base, engine
from backend.routers.health import router as health_router
from backend.routers.market import router as market_router
from backend.ws.server import (
    compute_wyckoff_signal as _compute_wyckoff_signal,
    ws_bot,
    ws_live,
)
from backend.compat import (
    _build_bar_update as compat_build_bar_update,
    _build_bot_status as compat_build_bot_status,
    _enqueue_command_payload as compat_enqueue_command_payload,
    ai_signal_history as compat_ai_signal_history,
    ai_signal_store as compat_ai_signal_store,
    auto_cal_state as compat_auto_cal_state,
    bars_store as compat_bars_store,
    bot_ws_connections as compat_bot_ws_connections,
    bots as compat_bots,
    cmd_index as compat_cmd_index,
    cmd_log as compat_cmd_log,
    retry_delay_ms as compat_retry_delay_ms,
    update_ai_signal,
    update_bot_state,
    wyckoff_config_store as compat_wyckoff_config_store,
    auto_trade_config_store as compat_auto_trade_config_store,
    _queues as compat_queues,
    get_auto_trade_config as compat_get_auto_trade_config,
    get_wyckoff_config as compat_get_wyckoff_config,
    get_queue as compat_get_queue,
    live_ws_connections as compat_live_ws_connections,
)

app = FastAPI(title="Wyckoff AI Lab Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(market_router)

@app.on_event("startup")
async def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    init_shadow_db()

app.websocket("/ws/live")(ws_live)
app.websocket("/ws/{bot_id}")(ws_bot)


def compute_wyckoff_signal(bars: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _compute_wyckoff_signal(bars)


live_ws_connections: List[Any] = []


async def _broadcast_live(payload: Dict[str, Any]) -> None:
    survivors: List[Any] = []
    for ws in list(live_ws_connections):
        try:
            await ws.send_json(payload)
            survivors.append(ws)
        except Exception:
            continue
    live_ws_connections[:] = survivors


async def _enqueue_command_payload(bot_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return await compat_enqueue_command_payload(bot_id, payload)


async def get_queue(bot_id: str) -> asyncio.Queue:
    return await compat_get_queue(bot_id)


def get_auto_trade_config(bot_id: str) -> Dict[str, Any]:
    return compat_get_auto_trade_config(bot_id)


def get_wyckoff_config(bot_id: str) -> Dict[str, Any]:
    return compat_get_wyckoff_config(bot_id)


bars_store = compat_bars_store
bots = compat_bots
cmd_log = compat_cmd_log
cmd_index = compat_cmd_index
ai_signal_store = compat_ai_signal_store
ai_signal_history = compat_ai_signal_history
auto_cal_state = compat_auto_cal_state
wyckoff_config_store = compat_wyckoff_config_store
auto_trade_config_store = compat_auto_trade_config_store
live_ws_connections = compat_live_ws_connections
bot_ws_connections = compat_bot_ws_connections
_queues = compat_queues
retry_delay_ms = compat_retry_delay_ms
_build_bar_update = compat_build_bar_update


def _build_bot_status(bot_id: str) -> Dict[str, Any]:
    payload = compat_build_bot_status(bot_id)
    payload.setdefault("data", {})["botId"] = bot_id
    return payload
