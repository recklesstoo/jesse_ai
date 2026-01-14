from __future__ import annotations

import asyncio
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from backend.database import SessionLocal
from backend.models import Bar
from backend.state import ws_bots, ws_last_rx_ts
from backend.ws import server as ws_server


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _should_run() -> bool:
    raw = os.getenv("WYCKOFF_SIM_FEED", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _is_real_bridge_active(bot_id: str, max_silence_sec: float = 3.0) -> bool:
    websocket = ws_bots.get(bot_id)
    if websocket is None:
        return False
    last = ws_last_rx_ts.get(bot_id)
    if last is None:
        return True
    return (datetime.now(timezone.utc) - last).total_seconds() <= max_silence_sec


def _seed_db(bot_id: str, symbol: str, timeframe: str, target_bars: int = 350) -> None:
    session = SessionLocal()
    try:
        existing = (
            session.query(Bar)
            .filter(Bar.bot_id == bot_id, Bar.symbol == symbol)
            .count()
        )
        if existing >= target_bars:
            return

        missing = max(0, target_bars - existing)
        if missing == 0:
            return

        now = datetime.now(timezone.utc)
        start = now - timedelta(seconds=missing)
        price = 15000.0 + random.random() * 50.0
        rows = []
        for i in range(missing):
            ts = start + timedelta(seconds=i)
            open_p = price
            close_p = open_p + (random.random() - 0.5) * 6.0
            high_p = max(open_p, close_p) + random.random() * 2.0
            low_p = min(open_p, close_p) - random.random() * 2.0
            volume = int(random.randint(200, 4000))
            rows.append(
                Bar(
                    bot_id=bot_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    ts_utc=ts,
                    open=float(f"{open_p:.2f}"),
                    high=float(f"{high_p:.2f}"),
                    low=float(f"{low_p:.2f}"),
                    close=float(f"{close_p:.2f}"),
                    volume=volume,
                    mode="SIM",
                )
            )
            price = close_p
        session.bulk_save_objects(rows)
        session.commit()
    finally:
        session.close()


@dataclass
class SimFeedConfig:
    bot_id: str = "bot-1"
    symbol: str = "MNQ"
    timeframe: str = "1s"
    interval_sec: float = 1.0


async def run_sim_feed(config: SimFeedConfig, stop_event: asyncio.Event) -> None:
    if not _should_run():
        return

    await asyncio.to_thread(_seed_db, config.bot_id, config.symbol, config.timeframe)

    price = 15000.0 + random.random() * 50.0
    send_count = 0
    skip_count = 0
    last_monitor = 0.0

    loop = asyncio.get_running_loop()
    while not stop_event.is_set():
        if _is_real_bridge_active(config.bot_id):
            await asyncio.sleep(config.interval_sec)
            continue

        now = datetime.now(timezone.utc)
        open_p = price
        close_p = open_p + (random.random() - 0.5) * 8.0
        high_p = max(open_p, close_p) + random.random() * 3.0
        low_p = min(open_p, close_p) - random.random() * 3.0
        volume = int(random.randint(250, 6000))
        price = close_p

        bar_payload: Dict[str, Any] = {
            "timestamp": _iso_z(now),
            "symbol": config.symbol,
            "timeframe": config.timeframe,
            "open": float(f"{open_p:.2f}"),
            "high": float(f"{high_p:.2f}"),
            "low": float(f"{low_p:.2f}"),
            "close": float(f"{close_p:.2f}"),
            "volume": volume,
            "mode": "SIM",
            "sessionBarCount": send_count,
            "vwap": float(f"{(open_p + close_p) / 2:.2f}"),
            "volOk": True,
        }

        try:
            await ws_server._handle_bar_data(config.bot_id, bar_payload)
            send_count += 1
        except Exception:
            skip_count += 1

        # Emit monitor snapshot every ~3 seconds.
        if loop.time() - last_monitor >= 3.0:
            last_monitor = loop.time()
            monitor_payload: Dict[str, Any] = {
                "ts": _iso_z(now),
                "mode": "SIM",
                "wsState": "SIM",
                "sendCount": send_count,
                "skipCount": skip_count,
            }
            try:
                await ws_server._handle_monitor(config.bot_id, monitor_payload)
            except Exception:
                pass

        await asyncio.sleep(config.interval_sec)


def start_sim_tasks(stop_event: asyncio.Event) -> list[asyncio.Task[Any]]:
    if not _should_run():
        return []
    tasks: list[asyncio.Task[Any]] = []
    for bot_id in ("bot-1", "test-bot"):
        cfg = SimFeedConfig(bot_id=bot_id)
        tasks.append(asyncio.create_task(run_sim_feed(cfg, stop_event)))
    return tasks

