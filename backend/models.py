from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, JSON, String, Index
from sqlalchemy.sql import func

from backend.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

DATA_SOURCE_LIVE_WS = "LIVE_WS"
DATA_SOURCE_IMPORT = "IMPORT"
DATA_SOURCE_SIMULATED = "SIMULATED"
DATA_SOURCE_ARCHIVED = "ARCHIVED"


class Bar(Base):
    __tablename__ = "bars"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(String, index=True)
    symbol = Column(String)
    timeframe = Column(String)
    ts_utc = Column(DateTime(timezone=True), index=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Integer)
    mode = Column(String, default="LIVE")
    data_source = Column(String, default=DATA_SOURCE_LIVE_WS, index=True)
    ingested_at_utc = Column(DateTime(timezone=True), default=utc_now, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_bars_bot_ts", "bot_id", "ts_utc"),)


class CommandEvent(Base):
    __tablename__ = "command_events"

    id = Column(Integer, primary_key=True, index=True)
    cmd_id = Column(String, index=True)
    bot_id = Column(String, index=True)
    event = Column(String)  # QUEUED, SENT, ACK, ERROR
    ts_utc = Column(DateTime(timezone=True), default=utc_now)
    payload = Column(JSON)


class AISignal(Base):
    __tablename__ = "ai_signals"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(String, index=True)
    ts_utc = Column(DateTime(timezone=True), default=utc_now)
    bar_ts_utc = Column(DateTime(timezone=True))
    symbol = Column(String)
    signal = Column(String)
    bias = Column(String)
    confidence = Column(Float)
    explain = Column(String)
    features = Column(JSON)
    model_version = Column(String)
    data_source = Column(String, default=DATA_SOURCE_LIVE_WS, index=True)
    ingested_at_utc = Column(DateTime(timezone=True), default=utc_now, index=True)


class BotConfig(Base):
    __tablename__ = "bot_configs"

    bot_id = Column(String, primary_key=True)
    wyckoff_config = Column(JSON)
    auto_config = Column(JSON)
    updated_at = Column(DateTime(timezone=True), onupdate=utc_now)


class MonitorSnapshot(Base):
    __tablename__ = "monitor_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(String, index=True)
    ts_utc = Column(DateTime(timezone=True), default=utc_now)
    data = Column(JSON)
    data_source = Column(String, default=DATA_SOURCE_LIVE_WS, index=True)
    ingested_at_utc = Column(DateTime(timezone=True), default=utc_now, index=True)


class TradeEvent(Base):
    __tablename__ = "trade_events"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(String, index=True)
    symbol = Column(String)
    action = Column(String)
    qty = Column(Integer)
    price = Column(Float)
    ts_utc = Column(DateTime(timezone=True), default=utc_now)
    market_position = Column(String)
    reason = Column(String)
    order_id = Column(String)
    order_name = Column(String)
    payload = Column(JSON)
    data_source = Column(String, default=DATA_SOURCE_LIVE_WS, index=True)
    ingested_at_utc = Column(DateTime(timezone=True), default=utc_now, index=True)


class SystemEvent(Base):
    __tablename__ = "system_events"

    id = Column(Integer, primary_key=True, index=True)
    ts_utc = Column(DateTime(timezone=True), default=utc_now, index=True)
    bot_id = Column(String, index=True)
    event_type = Column(String, index=True)
    data = Column(JSON)
    data_source = Column(String, default=DATA_SOURCE_LIVE_WS, index=True)
