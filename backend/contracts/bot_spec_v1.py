from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Optional, Union

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


class BotSpecV1SetupWyckoffSpring(BaseModel):
    """
    Spring (accumulation): sweep below recent range low and close back above it.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["wyckoff_spring"] = "wyckoff_spring"
    range_lookback: int = Field(default=80, ge=10, le=500)
    buffer_ticks: int = Field(default=2, ge=0, le=50)
    min_rvol20: float = Field(default=1.15, ge=0.0, le=10.0)


class BotSpecV1SetupWyckoffUpthrust(BaseModel):
    """
    Upthrust (distribution): sweep above recent range high and close back below it.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["wyckoff_upthrust"] = "wyckoff_upthrust"
    range_lookback: int = Field(default=80, ge=10, le=500)
    buffer_ticks: int = Field(default=2, ge=0, le=50)
    min_rvol20: float = Field(default=1.15, ge=0.0, le=10.0)


class BotSpecV1SetupWyckoffSosLps(BaseModel):
    """
    SOS + LPS: breakout above range with volume, then buy pullback holding above prior resistance.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["wyckoff_sos_lps"] = "wyckoff_sos_lps"
    range_lookback: int = Field(default=120, ge=10, le=800)
    breakout_buffer_ticks: int = Field(default=1, ge=0, le=50)
    pullback_buffer_ticks: int = Field(default=1, ge=0, le=50)
    min_rvol20_breakout: float = Field(default=1.25, ge=0.0, le=10.0)
    memory_bars: int = Field(default=80, ge=1, le=2000)


class BotSpecV1SetupWyckoffSowLpsy(BaseModel):
    """
    SOW + LPSY: breakdown below range with volume, then sell rally failing below prior support.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["wyckoff_sow_lpsy"] = "wyckoff_sow_lpsy"
    range_lookback: int = Field(default=120, ge=10, le=800)
    breakout_buffer_ticks: int = Field(default=1, ge=0, le=50)
    pullback_buffer_ticks: int = Field(default=1, ge=0, le=50)
    min_rvol20_breakout: float = Field(default=1.25, ge=0.0, le=10.0)
    memory_bars: int = Field(default=80, ge=1, le=2000)


class BotSpecV1SetupVsaSellingClimax(BaseModel):
    """
    Selling climax: extreme volume + spread and close near the low -> buy reversal.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["vsa_selling_climax"] = "vsa_selling_climax"
    min_vol_z50: float = Field(default=2.3, ge=0.0, le=10.0)
    min_spread_ticks: int = Field(default=12, ge=0, le=500)
    close_pos_max: float = Field(default=0.35, ge=0.0, le=1.0)


class BotSpecV1SetupVsaBuyingClimax(BaseModel):
    """
    Buying climax: extreme volume + spread and close near the high -> sell reversal.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["vsa_buying_climax"] = "vsa_buying_climax"
    min_vol_z50: float = Field(default=2.3, ge=0.0, le=10.0)
    min_spread_ticks: int = Field(default=12, ge=0, le=500)
    close_pos_min: float = Field(default=0.65, ge=0.0, le=1.0)


class BotSpecV1SetupWyckoffRangeReversion(BaseModel):
    """
    Range reversion: fade near range extremes (accumulation/distribution range trading).
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["wyckoff_range_reversion"] = "wyckoff_range_reversion"
    range_lookback: int = Field(default=200, ge=20, le=2000)
    entry_band_ticks: int = Field(default=4, ge=0, le=200)
    side: Literal["BOTH", "BUY_LOW", "SELL_HIGH"] = "BOTH"


class BotSpecV1SetupOpeningRangeBreakout(BaseModel):
    """
    OR breakout (classic RTH-style): trade breaks of the first N minutes range.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["opening_range_breakout"] = "opening_range_breakout"
    or_minutes: int = Field(default=15, ge=1, le=120)
    buffer_ticks: int = Field(default=1, ge=0, le=50)
    min_rvol20: float = Field(default=1.05, ge=0.0, le=10.0)


class BotSpecV1SetupWyckoffContractionBreakout(BaseModel):
    """
    Contraction -> breakout: low ATR regime then break range with volume.
    Useful as a re-accumulation / re-distribution continuation template.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["wyckoff_contraction_breakout"] = "wyckoff_contraction_breakout"
    range_lookback: int = Field(default=120, ge=20, le=2000)
    contraction_bars: int = Field(default=30, ge=1, le=2000)
    max_atr_ticks: int = Field(default=8, ge=0, le=500)
    buffer_ticks: int = Field(default=1, ge=0, le=50)
    min_rvol20: float = Field(default=1.10, ge=0.0, le=10.0)


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
    setup: Annotated[
        Union[
            BotSpecV1SetupTrendPullbackBos,
            BotSpecV1SetupWyckoffSpring,
            BotSpecV1SetupWyckoffUpthrust,
            BotSpecV1SetupWyckoffSosLps,
            BotSpecV1SetupWyckoffSowLpsy,
            BotSpecV1SetupVsaSellingClimax,
            BotSpecV1SetupVsaBuyingClimax,
            BotSpecV1SetupWyckoffRangeReversion,
            BotSpecV1SetupOpeningRangeBreakout,
            BotSpecV1SetupWyckoffContractionBreakout,
        ],
        Field(discriminator="kind"),
    ] = Field(default_factory=BotSpecV1SetupTrendPullbackBos)

    tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None

    def dump_canonical(self) -> Dict[str, Any]:
        return self.model_dump(by_alias=True)
