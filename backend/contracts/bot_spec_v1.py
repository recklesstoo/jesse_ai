from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class BotSpecV1Session(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["RTH", "ETH", "BOTH"] = "RTH"
    tz: str = "America/New_York"
    start_hhmm: int = Field(default=930, ge=0, le=2359)
    end_hhmm: int = Field(default=1600, ge=0, le=2359)


class BotSpecV1Risk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qty: int = Field(default=1, ge=1, le=200)
    stop_loss_ticks: int = Field(default=10, ge=0, le=500)
    take_profit_ticks: int = Field(default=12, ge=0, le=500)
    max_loss_usd: float = Field(default=1200.0, ge=0.0, le=100000.0)


class BotSpecV1Gates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_confidence: float = Field(default=0.10, ge=0.0, le=1.0)
    min_atr_ticks: int = Field(default=6, ge=0, le=500)
    cooldown_bars: int = Field(default=2, ge=0, le=500)
    max_trades_per_session: int = Field(default=20, ge=0, le=1000)


class BotSpecV1SetupTrendPullbackBos(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["trend_pullback_bos"] = "trend_pullback_bos"
    ema_trend_len: int = Field(default=200, ge=10, le=300)
    ema_pullback_len: int = Field(default=20, ge=5, le=200)
    bos_lookback: int = Field(default=10, ge=2, le=50)


class BotSpecV1(BaseModel):
    """
    Closed schema used by the assistant and APIs.
    The LLM may only output this JSON (no free-form code).
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal["bot-spec.v1"] = "bot-spec.v1"
    bot_id: str = Field(alias="botId")
    name: str = "WyckoffBot"

    symbol: str = "MNQ"
    timeframe: Literal["1m", "5m"] = "1m"

    session: BotSpecV1Session = Field(default_factory=BotSpecV1Session)
    risk: BotSpecV1Risk = Field(default_factory=BotSpecV1Risk)
    gates: BotSpecV1Gates = Field(default_factory=BotSpecV1Gates)
    setup: BotSpecV1SetupTrendPullbackBos = Field(default_factory=BotSpecV1SetupTrendPullbackBos)

    tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None

    def dump_canonical(self) -> Dict[str, Any]:
        return self.model_dump(by_alias=True)

