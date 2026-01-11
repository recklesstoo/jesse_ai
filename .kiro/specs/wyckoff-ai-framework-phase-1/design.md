# Design Document - Wyckoff AI Framework Phase 1

## Overview
Phase 1 adds Wyckoff detection and signal generation on top of the Phase 0
pipeline. Signals are computed per bot from the latest bars and exposed through
an API and the dashboard.

## Data Flow
1. Bar arrives via `/api/v1/bars/batch`.
2. Backend updates in-memory store and computes Wyckoff signals.
3. Frontend receives the latest signal via polling or WebSocket broadcast.

## Signal Model
```
{
  "botId": "bot-1",
  "signal": "SPRING",
  "bias": "BULLISH",
  "confidence": 0.62,
  "barTs": "2026-01-07T12:00:00.000Z",
  "explain": "Price undercut prior low with high volume."
}
```

## Detection Rules (initial)
- Phase detection from rolling high/low + volume trend.
- SPRING if price dips below recent low and closes back above on higher volume.
- UPTHRUST if price breaks recent high and closes below on higher volume.
- SOS/SOW based on higher highs/lower lows with volume confirmation.

## Integration Points
- Backend: extend `/api/v1/ai-signals` to return Wyckoff signals.
- Frontend: add a signal card and a short explanation string.
