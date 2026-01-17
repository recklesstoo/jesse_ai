from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, JSON, String, Index, Boolean, UniqueConstraint
from sqlalchemy.sql import func

from backend.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

DATA_SOURCE_LIVE_WS = "LIVE_WS"
DATA_SOURCE_IMPORT = "IMPORT"
DATA_SOURCE_CACHED = "CACHED"
DATA_SOURCE_SIMULATED = "SIMULATED"
DATA_SOURCE_ARCHIVED = "ARCHIVED"


class Bar(Base):
    __tablename__ = "bars"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(String, index=True)
    symbol = Column(String)
    timeframe = Column(String)
    ts_utc = Column(DateTime(timezone=True), index=True)
    day_utc = Column(String, index=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Integer)
    mode = Column(String, default="LIVE")
    data_source = Column(String, default=DATA_SOURCE_LIVE_WS, index=True)
    ingested_at_utc = Column(DateTime(timezone=True), default=utc_now, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_bars_bot_ts", "bot_id", "ts_utc"),
        Index("idx_bars_bot_day", "bot_id", "day_utc"),
        Index("idx_bars_key", "bot_id", "symbol", "timeframe", "ts_utc"),
    )


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
    day_utc = Column(String, index=True)
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


class DataBar(Base):
    __tablename__ = "data_bars"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    timeframe = Column(String, index=True)
    ts_utc = Column(DateTime(timezone=True), index=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Integer)
    source = Column(String, default=DATA_SOURCE_IMPORT, index=True)
    is_simulated = Column(Boolean, default=False, index=True)
    ingested_at_utc = Column(DateTime(timezone=True), default=utc_now, index=True)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "ts_utc", name="uq_data_bars_key"),
        Index("idx_data_bars_key", "symbol", "timeframe", "ts_utc"),
    )


class IngestJob(Base):
    __tablename__ = "ingest_jobs"

    id = Column(String, primary_key=True)
    created_at_utc = Column(DateTime(timezone=True), default=utc_now, index=True)
    finished_at_utc = Column(DateTime(timezone=True), nullable=True, index=True)
    status = Column(String, default="RUNNING", index=True)  # RUNNING, DONE, ERROR
    params = Column(JSON)
    result = Column(JSON)


class IngestEvent(Base):
    __tablename__ = "ingest_events"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, index=True)
    ts_utc = Column(DateTime(timezone=True), default=utc_now, index=True)
    level = Column(String, default="INFO", index=True)
    message = Column(String)
    data = Column(JSON)


class AssistantSession(Base):
    __tablename__ = "assistant_sessions"

    session_id = Column(String, primary_key=True)
    bot_id = Column(String, index=True)
    provider = Column(String, default="openai", index=True)
    turns = Column(JSON)  # list[{role, content}]
    updated_at_utc = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, index=True)


class ModelRun(Base):
    __tablename__ = "model_runs"

    id = Column(String, primary_key=True)
    bot_id = Column(String, index=True)
    symbol = Column(String, index=True)
    timeframe = Column(String, index=True)
    started_at_utc = Column(DateTime(timezone=True), default=utc_now, index=True)
    finished_at_utc = Column(DateTime(timezone=True), nullable=True, index=True)
    status = Column(String, default="RUNNING", index=True)  # RUNNING, DONE, ERROR, REFUSED
    metrics = Column(JSON)
    train_config = Column(JSON)
    artifact_path = Column(String)
    error = Column(String)

    __table_args__ = (Index("idx_model_runs_key", "bot_id", "symbol", "timeframe", "started_at_utc"),)


class BotSpec(Base):
    __tablename__ = "bot_specs"

    bot_id = Column(String, primary_key=True)
    created_at_utc = Column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at_utc = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, index=True)
    spec_version = Column(String, default="bot-spec.v1", index=True)
    spec = Column(JSON)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id = Column(String, primary_key=True)  # runId
    bot_id = Column(String, index=True)
    created_at_utc = Column(DateTime(timezone=True), default=utc_now, index=True)
    started_at_utc = Column(DateTime(timezone=True), nullable=True, index=True)
    finished_at_utc = Column(DateTime(timezone=True), nullable=True, index=True)
    status = Column(String, default="RUNNING", index=True)  # RUNNING, DONE, ERROR
    params = Column(JSON)
    metrics = Column(JSON)
    error = Column(String)

    __table_args__ = (Index("idx_backtest_runs_key", "bot_id", "created_at_utc"),)


class OptimizeRun(Base):
    __tablename__ = "optimize_runs"

    id = Column(String, primary_key=True)  # runId
    bot_id = Column(String, index=True)
    created_at_utc = Column(DateTime(timezone=True), default=utc_now, index=True)
    started_at_utc = Column(DateTime(timezone=True), nullable=True, index=True)
    finished_at_utc = Column(DateTime(timezone=True), nullable=True, index=True)
    status = Column(String, default="RUNNING", index=True)  # RUNNING, DONE, ERROR
    params = Column(JSON)
    results = Column(JSON)  # list summaries per variant (capped)
    error = Column(String)

    __table_args__ = (Index("idx_optimize_runs_key", "bot_id", "created_at_utc"),)
