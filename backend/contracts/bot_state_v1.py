from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


FeedStatusV1 = Literal["LIVE", "STALE", "NO_LIVE"]


class BotStateV1(BaseModel):
    """
    Stable contract for /api/v1/state.

    Notes:
    - `feed_status` is aligned with Market Metrics v1: LIVE|STALE|NO_LIVE.
    - Legacy/compat fields are included as aliases to avoid breaking older clients.
    """

    model_config = ConfigDict(extra="allow")

    ok: bool = True

    bot_id: str = Field(..., alias="bot_id")
    ws_connected: bool = False
    transport_connected: bool = False
    ws_open: bool = False

    nt_mode: str = "UNKNOWN"
    mode: str = "UNKNOWN"

    data_source: str = "NONE"
    data_source_kind: Optional[str] = None
    data_source_stream: Optional[str] = None

    feed_status: FeedStatusV1 = "NO_LIVE"
    feed_reason: str = "ok"

    ws_age_sec: Optional[float] = None
    bar_age_sec: Optional[float] = None
    monitor_age_sec: Optional[float] = None

    ws_stale_sec: Optional[float] = None
    feed_stale_sec: Optional[float] = None

    last_seen_utc: Optional[str] = None
    last_bar_ts_utc: Optional[str] = None

    # Backward-compatible legacy fields (kept for UI/older tools)
    feed_status_legacy: Optional[str] = None

    # Raw bot state snapshot (legacy behavior)
    state: Dict[str, Any] = Field(default_factory=dict)

