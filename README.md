# jesse_ai

## Environment preparation

1. Copy `.env.example` to `.env`, adjust the database path, port overrides, and secrets as needed.
2. Work from the repository root (`D:\jesse_ai`).
3. Run `.\scripts\doctor.ps1` to bootstrap the whole stack: the script will create/validate `.venv`, install Python/node dependencies, release ports 8000/3001, launch `scripts\arranque.ps1`, and keep retrying until `/api/v1/health` signals OK and `ws://127.0.0.1:8000/ws/test-bot` completes a handshake.

## Starting the services

- `.\scripts\arranque.ps1` frees ports 8000/3001, writes `logs\backend_pid.txt`/`logs\frontend_pid.txt`, and launches the backend and frontend each in its own PowerShell console.
- Each start writes `logs\backend_YYYYMMDD_HHMMSS.log` and `logs\frontend_YYYYMMDD_HHMMSS.log` and updates `logs\latest.json` with the current PIDs/log paths.
- `.\scripts\monitor.ps1` is an optional wrapper that keeps re-running `doctor.ps1` until the checklist is OK.

## Real-time data (NinjaTrader / BridgePuppet)

- This dashboard shows **only real data** received from NinjaTrader via BridgePuppet.
- BridgePuppet must connect to `ws://127.0.0.1:8000/ws/{botId}` and send `BAR_DATA` / `MONITOR` messages.
- If BridgePuppet is not connected or not sending bars, the UI will show **WAITING FOR NINJATRADER DATA** and prices/OHLC stay as `--` (or the last real value marked stale).

## Manual commands

- Backend (for debugging): `.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload`.
- Frontend: from `frontend\`, run `npm install` once and then `npm run dev -- --port 3001`.

## Health & deployment checks

- `/api/v1/health` returns `{"ok": true, ...}` so the doctor script treats it as success (the endpoint must be responsive for the run to finish cleanly).
- `/ws/test-bot` performs a minimal WebSocket handshake to confirm `/ws/{botId}` is reachable.
- Logs live in `logs/` and are ignored by Git. `doctor.ps1` will tail the logs referenced in `logs\latest.json` after a successful run.

## Dashboard badges (NT MODE / STALE)

The top badges are driven by `GET http://127.0.0.1:8000/api/v1/state?botId=...` and are computed server-side in **UTC**:

- `CONNECTED`: the BridgePuppet socket is connected (`ws_connected=true`).
- `NT MODE`: derived from the latest Ninja `payload.mode` (`LIVE` / `BACKTEST` / `UNKNOWN`).
- `WS AGE`: seconds since the last Ninja WS event received (`ws_age_sec`, any message type).
- `BAR AGE` + `FEED`: seconds since the last `BAR_DATA` was received (`bar_age_sec`) and `feed_status` (`NO_FEED` / `LIVE` / `STALE`).
- `MON AGE` + `MONITOR`: seconds since the last `MONITOR` was received (`monitor_age_sec`) and `monitor_status` (`NO_MONITOR` / `OK` / `STALE`).

Note: `BAR AGE`/staleness is computed from the server-side receive time (not the payload timestamp) to avoid false STALE during backtests or clock drift.

## Bot Registry / Timeline / Swarm (read-only)

- Bots registry: `GET http://127.0.0.1:8000/api/v1/bots`
- Timeline: `GET http://127.0.0.1:8000/api/v1/events?limit=200&botId=bot-1`
- Swarm:
  - `GET http://127.0.0.1:8000/api/v1/swarm/summary`
  - `GET http://127.0.0.1:8000/api/v1/swarm/rank?limit=10`
  - `POST http://127.0.0.1:8000/api/v1/swarm/plan` (recommendations only)

Important: the orchestrator/swarm is **read-only** and does not execute trades.

## AI execution (disabled)

- `POST /api/v1/ai-order` is disabled on purpose (403). The dashboard can show signals, but execution must be manual.

## Data Manager (import + cleanup)

The backend stores bars/trades with a `data_source`:
`LIVE_WS | IMPORT | SIMULATED | ARCHIVED` and all timestamps are treated as UTC.

- Summary totals: `GET http://127.0.0.1:8000/api/v1/data/summary`
- Days available: `GET http://127.0.0.1:8000/api/v1/data/days?symbol=MNQ&botId=bot-1&source=LIVE_WS,IMPORT`
- Import (explicit): `POST http://127.0.0.1:8000/api/v1/data/import` (multipart CSV/JSON)
- Cleanup (explicit, safe by default):
  - Preview: `POST http://127.0.0.1:8000/api/v1/data/cleanup/preview` → returns `confirm_token`
  - Apply: `POST http://127.0.0.1:8000/api/v1/data/cleanup/apply` with `confirm_token`

The UI includes a **Data Manager** card for summary, day listing, import, and cleanup preview/apply.
