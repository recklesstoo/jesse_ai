# WYCKOFF AI FRAMEWORK - RESUMEN EJECUTIVO

## CONTEXTO DEL PROYECTO

### Concepto central
Framework que combina la metodologia de Richard Wyckoff con IA para trading automatizado.

### Arquitectura del sistema
- NinjaTrader (BridgePuppet): ejecuta comandos y envia OHLCV por WebSocket
- Backend FastAPI: ingesta, colas de comandos, WebSocket, memoria en RAM
- Frontend React: dashboard en tiempo real, trading manual, logs, asistente IA

## FLUJO DE OPERACION

### Datos en tiempo real
1. NinjaTrader -> Backend (OHLCV)
2. Backend -> Frontend (WebSocket)
3. Frontend actualiza dashboard

### Monitoreo operativo
- `GET /api/monitor/status`: estado de WS, edad del ultimo bar en memoria/DB, colas y bot status.
- `POST /api/monitor/repair`: sincroniza estado desde DB y re-emite estado por WS.

### Comandos de trading
1. Frontend/IA -> Backend (enqueue)
2. Backend -> NinjaTrader (long-poll o WS)
3. NinjaTrader ejecuta -> Backend (ACK)
4. Backend -> Frontend (estado y log)

## ESTADO ACTUAL DEL PROYECTO

### Funcionalidades operativas
- WebSocket estable con reintentos/backoff
- Streaming de datos en tiempo real
- Sistema de comandos con ACK y log
- Trading manual con tracking de ACK
- Dashboard con panel de errores

### Servicios pendientes
- Sistema de noticias: endpoints basicos listos (in-memory)
- Shadow mode parcial

### Fase actual: Fase 1 - Wyckoff + IA
- Objetivo: senales Wyckoff, auto-route y ajustes dinamicos
- Estado: en progreso

## CONFIGURACION TECNICA

### Puertos y servicios
- Backend: http://localhost:8000
- Frontend: http://localhost:3001
- WebSocket: ws://localhost:8000/ws/live

### Nota sobre backtest
- En backtest, el Bridge debe enviar `mode=BACKTEST` (si no, el backend queda en LIVE).
- Si `lastBarAge` es alto en monitor, el replay no esta corriendo o la estrategia no esta en el grafico correcto.

### Tecnologias
- Backend: Python, FastAPI, WebSockets, Pydantic
- Frontend: React 18, Vite
- Trading: NinjaTrader 8, NinjaScript (C#)

## LISTA DE TAREAS (FASE 0)

### Prioridad critica
- [x] Tests WS broadcast y reconnection
- [x] Tests bar data flow y estructura
- [x] Tests price display y bot status
- [x] ACK endpoint y tests de ACK
- [x] BridgePuppet ACKs y FIFO
- [x] CommandLog y tracking en UI

### Prioridad alta
- [x] Error handling y recovery (UI + tests)
- [x] Endpoints faltantes criticos
- [x] Proxy Vite + tests

### Prioridad media
- [x] Tests integracion pipeline
- [x] Validacion de endpoints
- [x] Performance validation

## PROXIMOS PASOS RECOMENDADOS

1. Terminar ajustes dinamicos y selector de instrumento
2. Resolver servicios pendientes (noticias, shadow mode)
3. Definir metricas de confiabilidad (uptime, recovery, coverage)
4. Ejecutar smoke tests con `scripts/test-endpoints.ps1` tras cada cambio de API

## CONTACTO Y DOCUMENTACION

- Spec completo: .kiro/specs/wyckoff-ai-framework-phase-0/
- Analisis de servicios: SERVICIOS_ROTOS_ANALISIS.md
- Configuracion: config.json
- Tasks detalladas: .kiro/specs/wyckoff-ai-framework-phase-0/tasks.md

## CAMBIOS RECIENTES

- 2026-01-08: Wyckoff config y auto-route por bot (endpoints + UI)
- 2026-01-08: Defaults por instrumento (MNQ/NQ/ES/GC) y selector en UI
- 2026-01-08: Auto-calibracion con datos reales (200 barras, cada 500, +/-10%)
- 2026-01-08: Tests nuevos para defaults y auto calibracion (OK)
- 2026-01-08: Endpoints faltantes reparados (strategy params, dynamic/config prices, news, manual-order-advanced)
- 2026-01-08: Script de smoke tests de endpoints y WS (`scripts/test-endpoints.ps1`)
- 2026-01-10: Endpoints de monitoreo y repair (`/api/monitor/status`, `/api/monitor/repair`)

---

Estado: Fase 1 en progreso
Proximo milestone: Fase 1 (Wyckoff + IA)
Timeline estimado: definir tras cierre de ajustes dinamicos
