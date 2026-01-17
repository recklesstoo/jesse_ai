from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


FeedStatusV1 = Literal["LIVE", "STALE", "NO_LIVE"]
ConfidenceV1 = Literal["high", "medium", "low"]


class MarketMetricsV1(BaseModel):
    """
    Stable contract for /api/v1/market/metrics.

    Extra fields are allowed so the backend can evolve metrics layers without breaking clients.
    """

    model_config = ConfigDict(extra="allow")

    version: str = Field(..., examples=["market-metrics.v1"])
    symbol: str
    timeframe: str
    lookback: int

    source: str
    feed_status: FeedStatusV1
    confidence: ConfidenceV1

    server_ts_utc: str
    last_ws_ts_utc: Optional[str] = None
    last_bar_ts_utc: Optional[str] = None

    ws_age_sec: Optional[float] = None
    bar_age_sec: Optional[float] = None

    ws_stale_sec: float = 10.0
    bar_stale_sec: float

    notes: List[str] = Field(default_factory=list)

    # Common optional payloads
    timestamps: Optional[Dict[str, Any]] = None
    ages: Optional[Dict[str, Any]] = None
    thresholds: Optional[Dict[str, Any]] = None
    availability: Optional[Dict[str, Any]] = None
    instrument: Optional[Dict[str, Any]] = None
    metrics: Optional[Dict[str, Any]] = None
    bars_preview: Optional[List[Dict[str, Any]]] = None
    raw_bars: Optional[List[Dict[str, Any]]] = None

