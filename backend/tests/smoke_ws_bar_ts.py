from __future__ import annotations

import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.ws.server import _handle_bar_data, _parse_ts_utc  # noqa: E402


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    payload_epoch_ms = {
        "ts": 1736860000123,
        "symbol": "MNQ",
        "timeframe": "1s",
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume": 10,
        "mode": "LIVE",
    }
    payload_iso = {
        "timestamp": "2026-01-14T12:34:56Z",
        "symbol": "MNQ",
        "timeframe": "1s",
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume": 10,
        "mode": "LIVE",
    }
    payload_no_ts = {
        "symbol": "MNQ",
        "timeframe": "1s",
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume": 10,
        "mode": "LIVE",
    }

    ts1 = _parse_ts_utc(payload_epoch_ms)
    _assert(ts1 is not None and ts1.tzinfo is not None, "epoch ms should parse to tz-aware datetime")

    ts2 = _parse_ts_utc(payload_iso)
    _assert(ts2 is not None and ts2.tzinfo is not None, "ISO Z should parse to tz-aware datetime")

    ts3 = _parse_ts_utc(payload_no_ts)
    _assert(ts3 is None, "missing timestamp should return None")

    # Ensure the ts-missing path never throws and returns early.
    asyncio.run(_handle_bar_data("smoke-bot", payload_no_ts))

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
