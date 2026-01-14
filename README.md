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
- To execute orders from the dashboard, the NinjaTrader strategy properties must allow it:
  - `Enable Receive Commands = true` (otherwise commands are ignored)
  - `Enable LIVE Execution = true` for live trading (otherwise BridgePuppet returns `ACK_IGNORED` with message about `EnableLiveExecution=false`)

### Troubleshooting: BAR_DATA timestamp

Previously, `/ws/{botId}` could crash if a `BAR_DATA` payload arrived without a valid timestamp, causing disconnect/reconnect loops.
The backend now parses timestamps defensively and **never throws**: if `ts`/`timestamp` is missing or invalid, it marks the bot as `feed_status=STALE` and `data_source=UNKNOWN_TS`, records `last_bar_rx_utc` for debugging, and keeps the WebSocket alive.

## Manual commands

- Backend (for debugging): `.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload`.
- Frontend: from `frontend\`, run `npm install` once and then `npm run dev -- --port 3001`.

Execution gating (backend policy):

- Backend policy uses `execution_mode`: `DISABLED | MANUAL_ONLY | LIVE_ALLOWED` (default: `MANUAL_ONLY`).
- Query: `GET http://127.0.0.1:8000/api/v1/execution/status?botId=bot-1`
- Set: `POST http://127.0.0.1:8000/api/v1/execution/enable` with JSON `{ "mode": "MANUAL_ONLY" }`
  - Protect the toggle by setting env `WYCKOFF_EXECUTION_TOKEN` and sending header `x-execution-token`.
- If policy rejects a command or the bot is disconnected, the backend returns an ACK object with a clear `reject_reason` (no simulated acks).

## Health & deployment checks

- `/api/v1/health` returns `{"ok": true, ...}` so the doctor script treats it as success (the endpoint must be responsive for the run to finish cleanly).
- `/ws/test-bot` performs a minimal WebSocket handshake to confirm `/ws/{botId}` is reachable.
- Logs live in `logs/` and are ignored by Git. `doctor.ps1` will tail the logs referenced in `logs\latest.json` after a successful run.

## Dashboard badges (NT MODE / STALE)

The top badges are driven by `GET http://127.0.0.1:8000/api/v1/state?botId=...` and are computed server-side in **UTC**:

- `CONNECTED`: the BridgePuppet socket is connected (`ws_connected=true`).
- `NT MODE`: derived from the latest Ninja `payload.mode` (`LIVE` / `BACKTEST` / `UNKNOWN`).
- `WS AGE`: seconds since the last Ninja WS event received (`ws_age_sec`, any message type).
- `SRC`: `LIVE_WS` when the Ninja socket is connected, otherwise `CACHED` if the UI is showing the last known values, else `NONE`.
- `BAR AGE` + `FEED`: seconds since the last `BAR_DATA` was received (`bar_age_sec`) and `feed_status` (`NO_FEED` / `LIVE` / `STALE`). **UI "LIVE" only means `SRC=LIVE_WS` + recent bars**.
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

## AI Assistant (no orders)

The Advanced AI Assistant is a read-only operator. It can summarize health, diagnose WS/feed issues, rank bots, analyze events/data quality, and suggest actions — but it **never places or executes trades**.

- Capabilities: `GET http://127.0.0.1:8000/api/v1/ai/capabilities`
- Context snapshot: `GET http://127.0.0.1:8000/api/v1/ai/context?botId=bot-1`
- Chat: `POST http://127.0.0.1:8000/api/v1/ai/chat` body `{ "message": "...", "botId": "bot-1", "tools": false }`

Logs: `logs/ai_assistant.log` (and `logs/ai_web.log` only if web tools are enabled/configured).

## Fix: UI crash on startup

The dashboard uses a React `ErrorBoundary`. Previously it swallowed the real exception details (state mutation bug), making startup crashes show only “Something went wrong.”.
The ErrorBoundary now shows the full `message`, `stack`, and `componentStack` in DEV (and provides “Copy diagnostic” in PROD), so the root cause is visible and actionable. Proxying `/api` and `/ws` through Vite on port `3001` is also enforced (`strictPort`) and validated via `npm run doctor:ui`.

Additionally, `DataManagerPanel` could crash on load with `Objects are not valid as a React child` when the API returned day summaries as objects (e.g. `{day, symbol, botId, bars, ...}`) but the UI tried to render them directly. The panel now normalizes multiple response shapes (`[]`, `{days:[]}`, `{items:[]}`) and renders explicit fields in a table-like view; in DEV it shows an “Unexpected data shape” warning with the raw JSON (inside `<pre>`) instead of throwing. A small SSR smoke test (`npm run test:ui`) ensures it renders without exceptions.

## Data Manager (import + cleanup)

The backend stores bars/trades with a `data_source`:
`LIVE_WS | IMPORT | CACHED | SIMULATED | ARCHIVED` and all timestamps are treated as UTC.

- V2 Days available (SQLite table `data_bars`): `GET http://127.0.0.1:8000/api/v1/data/days?symbol=MNQ&timeframe=1m`
- V2 Ingest CSV (explicit): `POST http://127.0.0.1:8000/api/v1/data/ingest` (multipart)
- V2 Clean (explicit): `POST http://127.0.0.1:8000/api/v1/data/clean` with `{ "dryRun": true, "rules": {...} }`
- Legacy (existing bars tables):
  - Summary totals (optionally per day): `GET http://127.0.0.1:8000/api/v1/data/summary` and `GET http://127.0.0.1:8000/api/v1/data/summary?day=YYYY-MM-DD&symbol=MNQ`
  - Days available (legacy shape): `GET http://127.0.0.1:8000/api/v1/data/days_legacy?symbol=MNQ&botId=bot-1&source=LIVE_WS,IMPORT`
  - Import (explicit): `POST http://127.0.0.1:8000/api/v1/data/import` (multipart CSV/JSON)
  - Cleanup (explicit, token-confirmed):
    - Preview: `POST http://127.0.0.1:8000/api/v1/data/cleanup/preview` returns `confirm_token`
    - Apply: `POST http://127.0.0.1:8000/api/v1/data/cleanup/apply` with `confirm_token`

Logs: `logs/data_manager.log`.
