# jesse_ai

## Estado actual (Tech Lead / SRE)

- Backend: FastAPI `http://127.0.0.1:8000` con WS `ws://127.0.0.1:8000/ws/live` (UI) y `ws://127.0.0.1:8000/ws/{botId}` (BridgePuppet/Ninja).
- Frontend: Vite/React `http://127.0.0.1:3001` (proxy a `/api` y `/ws` hacia `8000`).
- Verdad única de estado para un bot (via `GET /api/v1/state?botId=...`):
  - `transport_connected` / `ws_connected`: BridgePuppet conectado al WS del bot.
  - `nt_mode`: estado reportado por Ninja (`LIVE`/`BACKTEST`/`UNKNOWN`).
  - `mode`: modo de plataforma (`LIVE`/`BACKTEST`/`SIM`/`UNKNOWN`) derivado de `state.mode` + `nt_mode`.
  - `data_source`: `LIVE_WS | CACHED | NONE | UNKNOWN_TS | SIMULATED`.
  - `feed_status`: `LIVE | STALE | NO_FEED` + `feed_reason` para explicar por qué dice STALE.

## Cómo validar (3 comandos)

1) `.\scripts\doctor.ps1`
2) `curl http://127.0.0.1:8000/api/v1/health`
3) `cd frontend; npm run doctor:ui`

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
- `ws_open` + `last_seen_utc`: `last_seen_utc` is updated only when a **real WS message** arrives from Ninja (`BAR_DATA` / `HEARTBEAT`). It is always the server receive time in UTC (never the payload timestamp).
- `bar_ts_utc`: timestamp parsed from the incoming bar payload (if present). This is separate from `last_seen_utc` on purpose.
- `NT MODE`: derived from the latest Ninja `payload.mode` (`LIVE` / `BACKTEST` / `UNKNOWN`).
- `MODE`: derived from bot state + NT mode (`mode`: `LIVE` / `BACKTEST` / `SIM` / `UNKNOWN`).
- `WS AGE`: seconds since the last Ninja WS event received (`ws_age_sec`, any message type).
- `SRC`: `data_source` (`LIVE_WS | CACHED | NONE | UNKNOWN_TS | SIMULATED`).
- `BAR AGE` + `FEED`: seconds since the last `BAR_DATA` was received (`bar_age_sec`) and `feed_status` (`NO_FEED` / `LIVE` / `STALE`). Hover tooltip uses `feed_reason`. **UI "LIVE" only means `SRC=LIVE_WS` + recent bars**.
- `MON AGE` + `MONITOR`: seconds since the last `MONITOR` was received (`monitor_age_sec`) and `monitor_status` (`NO_MONITOR` / `OK` / `STALE`).

Note: `BAR AGE`/staleness is computed from the server-side receive time (not the payload timestamp) to avoid false STALE during backtests or clock drift.

### Regla de “Connected” (Ninja real)

El badge **CONNECTED** en UI significa: `ws_open=true` y `last_seen_age_seconds <= 5`. Si no se cumple, el UI no muestra precios/OHLC como reales y marca `CACHED/SIMULATED/UNKNOWN_TS` explícitamente (sin ilusión de LIVE).

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
- Ops chat (tools + local-doc RAG): `POST http://127.0.0.1:8000/api/v1/assistant/chat` body `{ "botId":"bot-1", "message":"...", "opsMode": true, "includeWeb": false, "sessionId":"optional" }`
  - `opsMode=true` enables read-only tool calls to real endpoints (`/state`, `/monitor/status`, `/execution/status`, `/swarm/rank`, `/events`, `/data/summary`).
  - `includeWeb=true` allows optional web search results (if configured) and they are labeled as WEB sources.

OpenAI ChatGPT configuration (no local LLM):
- `OPENAI_API_KEY` (required)
- `OPENAI_MODEL` (optional, default `gpt-4o-mini`)
- `OPENAI_BASE_URL` (optional, default `https://api.openai.com/v1/chat/completions`)

Quick test (PowerShell):
- `$env:OPENAI_API_KEY="..."; $env:OPENAI_MODEL="gpt-4o-mini"`
- `curl -X POST http://127.0.0.1:8000/api/v1/assistant/chat -H "Content-Type: application/json" -d "{\"botId\":\"bot-1\",\"message\":\"Qué está pasando ahora?\",\"opsMode\":true,\"includeWeb\":false,\"sessionId\":\"demo\"}"`

### Wyckoff Doctor Trader (persona)

`POST /api/v1/assistant/chat` habla como “doctor en finanzas” con mentalidad agresiva y realista de trader:
- Reporta estado operativo real (`nt_mode`, `mode`, `feed_status`, `data_source`, `ws_age_sec`, `bar_age_sec`) y explica STALE con `feed_reason`.
- Nunca ejecuta órdenes: si pides ejecución, devuelve plan (setup, riesgo, invalidación) y pasos manuales.
- Memoria por sesión: guarda últimos turnos + resumen en `logs/doctor_sessions/` y audita en `logs/doctor_assistant_sessions.jsonl`.

Logs: `logs/ai_assistant.log` (and `logs/ai_web.log` only if web tools are enabled/configured).

## Fix: UI crash on startup

Root cause of the blank screen: `frontend/src/App.jsx` contained stray derived constants **after** the component export, so the module threw on import (`ReferenceError: dataSourceStream is not defined`) and React never mounted.
Fix: moved the derived display fields back inside `App()` and added a bootstrap guard in `frontend/src/main.jsx` that renders a startup error panel instead of a silent blank screen if a module fails before React mounts.

The dashboard uses a React `ErrorBoundary`. Previously it swallowed the real exception details (state mutation bug), making startup crashes show only “Something went wrong.”.
The ErrorBoundary now shows the full `message`, `stack`, and `componentStack` in DEV (and provides “Copy diagnostic” in PROD), so the root cause is visible and actionable. Proxying `/api` and `/ws` through Vite on port `3001` is also enforced (`strictPort`) and validated via `npm run doctor:ui`.

Additionally, `DataManagerPanel` could crash on load with `Objects are not valid as a React child` when the API returned day summaries as objects (e.g. `{day, symbol, botId, bars, ...}`) but the UI tried to render them directly. The panel now normalizes multiple response shapes (`[]`, `{days:[]}`, `{items:[]}`) and renders explicit fields in a table-like view; in DEV it shows an “Unexpected data shape” warning with the raw JSON (inside `<pre>`) instead of throwing. A small SSR smoke test (`npm run test:ui`) ensures it renders without exceptions.

## Data Manager (import + cleanup)

The backend stores bars/trades with a `data_source`:
`LIVE_WS | IMPORT | CACHED | SIMULATED | ARCHIVED` and all timestamps are treated as UTC.

- V2 Days available (SQLite table `data_bars`): `GET http://127.0.0.1:8000/api/v1/data/days?symbol=MNQ&timeframe=1m`
- V2 Ingest CSV (explicit): `POST http://127.0.0.1:8000/api/v1/data/ingest` (multipart)
- V2 Clean (explicit): `POST http://127.0.0.1:8000/api/v1/data/clean` with `{ "dryRun": true, "rules": {...} }`
- Cleanup (confirmation required): `POST http://127.0.0.1:8000/api/v1/data/cleanup?mode=sim_only|all_invalid` with body `{ "confirm": false, "rules": {"symbol":"MNQ","timeframe":"1m"} }` (set `confirm:true` to apply)
- Legacy (existing bars tables):
  - Summary totals (optionally per day): `GET http://127.0.0.1:8000/api/v1/data/summary` and `GET http://127.0.0.1:8000/api/v1/data/summary?day=YYYY-MM-DD&symbol=MNQ`
  - Days available (legacy shape): `GET http://127.0.0.1:8000/api/v1/data/days_legacy?symbol=MNQ&botId=bot-1&source=LIVE_WS,IMPORT`
  - Import (explicit): `POST http://127.0.0.1:8000/api/v1/data/import` (multipart CSV/JSON)
  - Cleanup (explicit, token-confirmed):
    - Preview: `POST http://127.0.0.1:8000/api/v1/data/cleanup/preview` returns `confirm_token`
    - Apply: `POST http://127.0.0.1:8000/api/v1/data/cleanup/apply` with `confirm_token`

Logs: `logs/data_manager.log`.

## TODOs técnicos (siguiente fase)

- Unificar tests: `pytest` corre `tests/` y `backend/tests/`; algunos tests históricos asumen ACKs simulados (ya deshabilitados).
- Reducir ruido de estados: separar claramente “UI WS (/ws/live)” vs “BridgePuppet WS (/ws/{botId})” en todos los paneles.
- Revisar consistencia de `state` keys (`connected` vs `ws_connected`) y documentar contrato estable para UI/BridgePuppet.
- Auditar tablas `bars`/`trade_events` vs `data_bars` para evitar duplicidad de conceptos (ingesta vs feed en vivo).
