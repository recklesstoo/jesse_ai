from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field


router = APIRouter()


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class BacktestBar(BaseModel):
    ts: str
    o: float
    h: float
    l: float
    c: float
    v: int = 0


class BacktestPositionState(BaseModel):
    marketPosition: str = "Flat"
    qty: int = 0


class BacktestDecisionRequest(BaseModel):
    botId: str = Field(default="bot-1")
    symbol: str = Field(default="MNQ")
    timeframe: str = Field(default="1m")
    bar: BacktestBar
    position_state: Optional[BacktestPositionState] = None


class BacktestDecision(BaseModel):
    action: str = Field(default="HOLD", description="HOLD|BUY|SELL|FLATTEN")
    confidence: float = 0.0
    qty: int = 0
    slTicks: int = 0
    tpTicks: int = 0
    reason: str = ""
    botName: str = "backend-hold"
    ts_utc: str = Field(default_factory=_utc_iso)


@router.post("/api/v1/backtest/decision", response_model=BacktestDecision)
def backtest_decision(req: BacktestDecisionRequest) -> BacktestDecision:
    """
    Backtest-only decision endpoint.
    MUST be deterministic and must NOT write bars to SQLite.

    Current behavior (safe default): HOLD.
    """
    _ = req  # reserved for future deterministic models
    return BacktestDecision(action="HOLD", confidence=0.0, qty=0, reason="backend_default_hold", botName="backend-hold")


@router.get("/api/v1/backtest/metrics")
def backtest_metrics(runId: str) -> Dict[str, Any]:
    # Placeholder: Ninja prints BACKTEST_SUMMARY; ingestion can be added later.
    return {"ok": False, "runId": runId, "error": "not_implemented", "ts_utc": _utc_iso()}

