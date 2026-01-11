# 🔍 FASE 1 — INSPECCIÓN Y CONTEXTO - WYCKOFF AI FRAMEWORK

## 1) RESUMEN EJECUTIVO

El sistema actual implementa una arquitectura de 3 capas funcional con comunicación WebSocket en tiempo real entre NinjaTrader (BridgePuppet.cs), Backend FastAPI (backend/app.py) y Frontend React (frontend/src/App.jsx). El backend maneja comandos via long-polling y almacena datos en memoria RAM. **CRÍTICO**: No existe snapshot de posiciones/órdenes, no hay modo SHADOW implementado, y el sistema pierde estado al reiniciar backend.

## 2) MAPA DE ARCHIVOS CLAVE

### Backend (FastAPI)
- `backend/app.py` - Servidor principal, endpoints REST, WebSocket, stores en RAM
- `backend/requirements.txt` - Dependencias Python
- `backend/.env` - Variables de entorno (no inspeccionado)

### Frontend (React)
- `frontend/src/App.jsx` - Dashboard principal, WebSocket client, envío comandos
- `frontend/package.json` - Dependencias Node.js
- `frontend/vite.config.js` - Configuración Vite

### NinjaTrader
- `BridgePuppet.cs` - Estrategia NinjaScript, envía BAR_DATA, recibe comandos
- `config.json` - Configuración sistema (modo PAPER, risk management)

### Otros
- `SERVICIOS_ROTOS_ANALISIS.md` - Análisis de endpoints faltantes
- `scripts/port-manager.js` - Gestión de puertos

## 3) CONTRATOS EXACTOS

| Endpoint/Evento | Payload | Productor | Consumidor |
|-----------------|---------|-----------|------------|
| **WebSocket `/ws/live`** | | | |
| `bar_update` | `{"type":"bar_update","data":{"botId":"bot-1","symbol":"MNQ","price":21151.00,"timestamp":"2026-01-05T01:45:00.000Z","volume":1250,"ohlc":{"open":21150.25,"high":21152.75,"low":21149.50,"close":21151.00}}}` | Backend | Frontend |
| `bot_status` | `{"type":"bot_status","data":{"botId":"bot-1","status":{"mode":"LIVE","last_seen_utc":"2026-01-05T01:45:00.000Z"},"ts":"2026-01-05T01:45:00.000Z"}}` | Backend | Frontend |
| `connection_status` | `{"type":"connection_status","data":{"connected":true,"bots":{},"ts":"2026-01-05T01:45:00.000Z"}}` | Backend | Frontend |
| **REST Endpoints** | | | |
| `POST /api/v1/commands/{bot_id}` | `{"action":"BUY","qty":1,"slTicks":10,"tpTicks":20,"tag":"manual","symbol":"MNQ"}` | Frontend | Backend |
| `GET /api/v1/commands/{bot_id}` | `{"id":"cmd_1767576679413","action":"BUY","qty":1,"slTicks":10,"tpTicks":20,"tag":"manual","symbol":"MNQ","enqueuedAt":"2026-01-05T01:45:00.000Z","botId":"bot-1"}` | Backend | BridgePuppet |
| `POST /api/v1/commands/{bot_id}/ack` | `{"id":"cmd_1767576679413","status":"FILLED","message":"Order executed successfully","orderId":"NT_12345","avgFillPrice":21151.25,"filledQty":1,"ts":"2026-01-05T01:45:01.500Z"}` | BridgePuppet | Backend |
| `POST /api/v1/bars/batch` | `{"botId":"bot-1","mode":"LIVE","account":"Sim101","instrument":"MNQ","bars":[{"ts":"2026-01-05T01:45:00.000Z","symbol":"MNQ","timeframe":"1 Minute","o":21150.25,"h":21152.75,"l":21149.50,"c":21151.00,"v":1250}]}` | BridgePuppet | Backend |
| **NinjaScript WebSocket** | | | |
| `BAR_DATA` | `{"type":"BAR_DATA","payload":{"timestamp":"2026-01-05T01:45:00.000Z","symbol":"MNQ","timeframe":"1 Minute","open":21150.25,"high":21152.75,"low":21149.50,"close":21151.00,"volume":1250,"mode":"LIVE"}}` | BridgePuppet | Backend |
| `ACK` | `{"type":"ACK","payload":{"id":"cmd_1767576679413","status":"FILLED","message":"Order executed successfully","ts":"2026-01-05T01:45:01.500Z"}}` | BridgePuppet | Backend |

## 4) MODO LIVE vs BACKTEST vs SHADOW

### Definición Actual
- **LIVE**: `Mode = "LIVE"` en backend/app.py línea 128
- **BACKTEST**: `Mode = "BACKTEST"` en backend/app.py línea 128  
- **SHADOW**: **NO EXISTE** - No implementado en el código

### Cómo se Define
- **Backend**: Recibe modo en `BarsBatch.mode` y `bar_data_form()` (línea 274-275)
- **BridgePuppet**: Detecta modo via `IsInStrategyAnalyzer` y `State.Historical` 
- **Config**: `config.json` tiene `"mode": "PAPER"` pero no se usa en backend
- **Frontend**: No controla modo, solo muestra status recibido

### Qué Cambia por Modo
- **LIVE**: Comandos se encolan y entregan via long-polling
- **BACKTEST**: Comandos retornan `none_cmd()` (línea 309-311)
- **SHADOW**: **NO IMPLEMENTADO**

## 5) SOURCE OF TRUTH REAL

### ❌ NO EXISTE Snapshot de Posición/Órdenes/Fills
- **Búsqueda exhaustiva**: No se encontró código para snapshot de posiciones
- **Stores existentes**: Solo `bars_store`, `exec_store`, `trade_store`, `cmd_log`
- **Sin persistencia**: Todo en RAM, se pierde al reiniciar backend

### ❌ Pérdida de Estado al Reiniciar Backend
- **cmd_log**: `Dict[str, Deque[dict]]` en memoria (línea 58)
- **cmd_index**: `Dict[str, Dict[str, dict]]` en memoria (línea 59)
- **bots**: `Dict[str, dict]` en memoria (línea 32)
- **Queues**: `_queues: Dict[str, asyncio.Queue]` en memoria (línea 56)

## 6) GAP ANALYSIS PRIORIZADO

| Gap | Falta | Riesgo | Impacto | Acción |
|-----|-------|--------|---------|--------|
| **CRÍTICO** | | | | |
| Shadow Mode | Sistema completo shadow mode | ALTO | Trading real accidental | Implementar flag SHADOW + logging |
| Snapshot State | Posiciones/órdenes desde Ninja | ALTO | Desincronización estado | Endpoint snapshot + reconciliación |
| Persistencia | Estado se pierde al reiniciar | MEDIO | Pérdida comandos/logs | SQLite para cmd_log + recovery |
| **ALTO** | | | | |
| Idempotencia | Comandos duplicados | MEDIO | Órdenes duplicadas | Dedupe por commandId |
| Kill Switch | Control emergencia | ALTO | Sin stop de emergencia | Endpoint /api/emergency/stop |
| **MEDIO** | | | | |
| Proxy Config | CORS en desarrollo | BAJO | Desarrollo lento | Vite proxy config |
| Health Check | Estado detallado sistema | BAJO | Debug difícil | Métricas extendidas |

## 7) PUNTOS CRÍTICOS IDENTIFICADOS

### 🚨 **Comando Enqueue Point** (CRÍTICO para Shadow Mode)
- **Ubicación exacta**: `backend/app.py` línea 336-347 en `enqueue_command()`
- **Código actual**:
```python
@app.post("/api/v1/commands/{bot_id}")
async def enqueue_command(bot_id: str, cmd: CommandIn):
    q = await get_queue(bot_id)  # ← AQUÍ se encola para Ninja
    cmd_id = f"cmd_{int(time.time() * 1000)}"
    payload = cmd.model_dump()
    # ... resto del código
    await q.put(payload)  # ← PUNTO EXACTO donde se envía
```

### 🔄 **WebSocket Endpoints Reales**
- **Backend**: `/ws/live` (línea 381-406)
- **Frontend**: `ws://127.0.0.1:8000/ws/live` (línea 492)
- **BridgePuppet**: Usa WebSocket directo, no REST polling

### 📊 **Stores en RAM Existentes**
```python
bars_store: Dict[str, Deque[dict]]     # MAX_BARS_PER_BOT = 200,000
exec_store: Dict[str, Deque[dict]]     # MAX_EXECS_PER_BOT = 100,000  
trade_store: Dict[str, Deque[dict]]    # MAX_TRADES_PER_BOT = 50,000
cmd_log: Dict[str, Deque[dict]]        # MAX_CMDLOG_PER_BOT = 10,000
```

---

## ✅ ENTREGABLE 1 COMPLETADO

**Arquitectura mapeada con rutas reales, contratos exactos extraídos del código, y gaps críticos identificados. Listo para FASE 2 - PLAN DE CIERRE.**