from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, Index
from sqlalchemy.sql import func
from .database import Base
import datetime

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)

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
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Índice compuesto para búsquedas rápidas de series temporales
    __table_args__ = (Index('idx_bars_bot_ts', 'bot_id', 'ts_utc'),)

class CommandEvent(Base):
    __tablename__ = "command_events"

    id = Column(Integer, primary_key=True, index=True)
    cmd_id = Column(String, index=True)
    bot_id = Column(String, index=True)
    event = Column(String) # QUEUED, SENT, ACK, ERROR
    ts_utc = Column(DateTime(timezone=True), default=utc_now)
    payload = Column(JSON)

class AISignal(Base):
    __tablename__ = "ai_signals"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(String, index=True)
    ts_utc = Column(DateTime(timezone=True), default=utc_now)
    bar_ts_utc = Column(DateTime(timezone=True))
    symbol = Column(String)
    signal = Column(String) # NONE, SOS, SOW, etc.
    bias = Column(String)   # BULLISH, BEARISH, NEUTRAL
    confidence = Column(Float)
    explain = Column(String)
    features = Column(JSON) # Guardar features usadas
    model_version = Column(String)

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

class TradeFill(Base):
    __tablename__ = "trade_fills"
    
    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(String, index=True)
    symbol = Column(String)
    side = Column(String) # BUY, SELL
    qty = Column(Integer)
    price = Column(Float)
    ts_utc = Column(DateTime(timezone=True))