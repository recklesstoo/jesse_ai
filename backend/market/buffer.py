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
    # Server receive timestamp (UTC). Optional, but used for staleness computations.
    rx_ts_utc: Optional[datetime] = None


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

    def upsert(self, bar: MarketBar) -> None:
        """
        Append a new bar, but if the last bar shares the same ts_utc, replace it.

        Bridge/Ninja can send partial updates for the same bar timestamp. For market metrics
        determinism (and memory safety), treat same-ts updates as replacements.
        """
        try:
            last = self._dq[-1]
        except Exception:
            last = None
        if last is not None and last.ts_utc == bar.ts_utc:
            try:
                self._dq.pop()
            except Exception:
                pass
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
        self._last_rx_utc: Dict[Tuple[str, str], datetime] = {}
        # Track which input timeframes have been observed per symbol.
        # This lets us avoid double-producing 5m bars if Ninja already sends real 5m bars,
        # and prefer higher-resolution inputs (e.g., 1s) for aggregation.
        self._has_input_tf: Dict[Tuple[str, str], bool] = {}

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
                rx_ts_utc=part.get("last_rx_utc"),
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
        rx_ts = bar.rx_ts_utc or datetime.now(timezone.utc)
        self._last_rx_utc[key] = rx_ts
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
                "last_rx_utc": rx_ts,
            }
            self._partials[key] = part
            return

        part["high"] = max(float(part.get("high") or bar.high), float(bar.high))
        part["low"] = min(float(part.get("low") or bar.low), float(bar.low))
        part["close"] = bar.close
        part["volume"] = int(part.get("volume") or 0) + int(bar.volume or 0)
        part["bid"] = bar.bid
        part["ask"] = bar.ask
        part["last_rx_utc"] = rx_ts

    def add_bar(self, bar: MarketBar) -> None:
        with self._lock:
            symbol = bar.symbol.upper()
            tf = normalize_timeframe(bar.timeframe)
            rx_ts = bar.rx_ts_utc or datetime.now(timezone.utc)
            if tf:
                self._has_input_tf[(symbol, tf)] = True
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
                rx_ts_utc=rx_ts,
            )
            self._ensure_ring(symbol, tf).upsert(normalized)
            self._last_rx_utc[(symbol, tf)] = rx_ts

            # v1 aggregation: if we receive 1s bars, build 1m and 5m bars for metrics.
            if tf == "1s":
                self._aggregate_tick_bar(normalized, "1m")
                self._aggregate_tick_bar(normalized, "5m")
                return

            # If we receive 1m bars (common setup), optionally build 5m bars.
            # Avoid double-counting if a higher-resolution input exists (1s) or real 5m is present.
            if tf == "1m":
                has_1s = bool(self._has_input_tf.get((symbol, "1s")))
                has_5m = bool(self._has_input_tf.get((symbol, "5m")))
                if not has_1s and not has_5m:
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

    def last_rx_ts(self, *, symbol: str, timeframe: str) -> Optional[datetime]:
        key = (str(symbol).upper(), normalize_timeframe(timeframe))
        with self._lock:
            ts = self._last_rx_utc.get(key)
            if ts is None:
                return None
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts.astimezone(timezone.utc)


market_buffer = MarketBuffer(capacity_per_key=2000)
