from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Deque, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class MarketBar:
    ts_utc: datetime
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    bid: Optional[float] = None
    ask: Optional[float] = None


def normalize_timeframe(value: Any) -> str:
    """
    Normalize timeframe strings to canonical codes.
    Examples:
      - "1m", "5m" -> "1m", "5m"
      - "1 Min", "5 Minute" -> "1m", "5m"
      - "1 Second" -> "1s"
    """
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    s_low = s.lower()
    # Canonical already
    if len(s_low) >= 2 and s_low[:-1].isdigit() and s_low[-1] in ("s", "m", "h"):
        return s_low

    # Try parse formats like "1 Second", "5 Minute", "15 Min"
    parts = s_low.replace("-", " ").replace("_", " ").split()
    n: Optional[int] = None
    unit: str = ""
    for p in parts:
        if n is None and p.isdigit():
            n = int(p)
            continue
        if n is not None and not unit:
            unit = p
            break
    if n is None:
        return s  # leave as-is
    if unit.startswith("sec"):
        return f"{n}s"
    if unit.startswith("min"):
        return f"{n}m"
    if unit.startswith("hour") or unit.startswith("hr"):
        return f"{n}h"
    return s


class MarketRing:
    def __init__(self, capacity: int) -> None:
        self.capacity = max(1, int(capacity))
        self._dq: Deque[MarketBar] = deque(maxlen=self.capacity)

    def append(self, bar: MarketBar) -> None:
        self._dq.append(bar)

    def tail(self, n: int) -> List[MarketBar]:
        if n <= 0:
            return []
        items = list(self._dq)
        return items[-n:]

    def all(self) -> List[MarketBar]:
        return list(self._dq)

    def last(self) -> Optional[MarketBar]:
        try:
            return self._dq[-1]
        except Exception:
            return None


class MarketBuffer:
    """
    In-memory ring buffer keyed by (symbol, timeframe).
    v1 target: keep enough bars to compute market metrics deterministically without DB.
    """

    def __init__(self, *, capacity_per_key: int = 2000) -> None:
        self.capacity_per_key = max(1, int(capacity_per_key))
        self._lock = Lock()
        self._rings: Dict[Tuple[str, str], MarketRing] = {}
        self._partials: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def _bucket_start(self, ts_utc: datetime, target_tf: str) -> datetime:
        if ts_utc.tzinfo is None:
            ts_utc = ts_utc.replace(tzinfo=timezone.utc)
        ts_utc = ts_utc.astimezone(timezone.utc)
        if target_tf == "1m":
            return ts_utc.replace(second=0, microsecond=0)
        if target_tf == "5m":
            minute = (ts_utc.minute // 5) * 5
            return ts_utc.replace(minute=minute, second=0, microsecond=0)
        return ts_utc

    def _finalize_partial(self, symbol: str, target_tf: str, part: Dict[str, Any]) -> None:
        ts = part.get("bucket_start")
        if not isinstance(ts, datetime):
            return
        self._ensure_ring(symbol, target_tf).append(
            MarketBar(
                ts_utc=ts.astimezone(timezone.utc),
                symbol=symbol,
                timeframe=target_tf,
                open=float(part.get("open") or 0.0),
                high=float(part.get("high") or 0.0),
                low=float(part.get("low") or 0.0),
                close=float(part.get("close") or 0.0),
                volume=int(part.get("volume") or 0),
                bid=part.get("bid"),
                ask=part.get("ask"),
            )
        )

    def _ensure_ring(self, symbol: str, timeframe: str) -> MarketRing:
        key = (symbol.upper(), normalize_timeframe(timeframe))
        ring = self._rings.get(key)
        if ring is None:
            ring = MarketRing(self.capacity_per_key)
            self._rings[key] = ring
        return ring

    def _aggregate_tick_bar(self, bar: MarketBar, target_tf: str) -> None:
        symbol = bar.symbol.upper()
        bucket = self._bucket_start(bar.ts_utc, target_tf)
        key = (symbol, target_tf)
        part = self._partials.get(key)
        if part is None or part.get("bucket_start") != bucket:
            if part is not None:
                self._finalize_partial(symbol, target_tf, part)
            part = {
                "bucket_start": bucket,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "bid": bar.bid,
                "ask": bar.ask,
            }
            self._partials[key] = part
            return

        part["high"] = max(float(part.get("high") or bar.high), float(bar.high))
        part["low"] = min(float(part.get("low") or bar.low), float(bar.low))
        part["close"] = bar.close
        part["volume"] = int(part.get("volume") or 0) + int(bar.volume or 0)
        part["bid"] = bar.bid
        part["ask"] = bar.ask

    def add_bar(self, bar: MarketBar) -> None:
        with self._lock:
            symbol = bar.symbol.upper()
            tf = normalize_timeframe(bar.timeframe)
            normalized = MarketBar(
                ts_utc=bar.ts_utc.astimezone(timezone.utc) if bar.ts_utc.tzinfo else bar.ts_utc.replace(tzinfo=timezone.utc),
                symbol=symbol,
                timeframe=tf,
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=int(bar.volume),
                bid=bar.bid,
                ask=bar.ask,
            )
            self._ensure_ring(symbol, tf).append(normalized)

            # v1 aggregation: if we receive 1s bars, build 1m and 5m bars for metrics.
            if tf == "1s":
                self._aggregate_tick_bar(normalized, "1m")
                self._aggregate_tick_bar(normalized, "5m")

    def get_bars(self, *, symbol: str, timeframe: str, limit: int) -> List[MarketBar]:
        key = (str(symbol).upper(), normalize_timeframe(timeframe))
        with self._lock:
            ring = self._rings.get(key)
            if ring is None:
                return []
            return ring.tail(max(1, int(limit)))

    def last_bar_ts(self, *, symbol: str, timeframe: str) -> Optional[datetime]:
        key = (str(symbol).upper(), normalize_timeframe(timeframe))
        with self._lock:
            ring = self._rings.get(key)
            last = ring.last() if ring else None
            if last is None:
                return None
            ts = last.ts_utc
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts.astimezone(timezone.utc)


market_buffer = MarketBuffer(capacity_per_key=2000)
