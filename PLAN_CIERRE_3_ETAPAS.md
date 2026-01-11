# 📋 FASE 2 — PLAN DE CIERRE - WYCKOFF AI FRAMEWORK

## 🎯 PLAN DE 3 ETAPAS CON TAREAS ATÓMICAS

### ETAPA A: MÍNIMO VIABLE CIENTÍFICO (Shadow Mode Real)

#### **Objetivo**: Implementar shadow mode que decide y loguea sin enviar órdenes reales

#### **Tareas Atómicas**:

**A1. Detectar Punto de Enqueue Exacto**
- **Archivo**: `backend/app.py`
- **Cambio**: Agregar flag SHADOW antes de `await q.put(payload)` en línea 347
- **Criterio**: Flag detectado correctamente desde config/env

**A2. Agregar Flag SHADOW a Config**
- **Archivo**: `config.json` 
- **Cambio**: Agregar `"shadow_mode": false` en sección `"system"`
- **Criterio**: Config cargado y accesible en backend

**A3. Implementar Shadow Decision Logging**
- **Archivo**: `backend/app.py`
- **Cambio**: Crear función `log_shadow_decision()` que guarda en SQLite
- **Schema**: `{id, ts, botId, instrument, signal, payloadOriginal, reason, status="SHADOW"}`
- **Criterio**: SQLite file creado y decisiones persistidas

**A4. Modificar enqueue_command() para Shadow**
- **Archivo**: `backend/app.py` línea 336-347
- **Cambio**: 
```python
if is_shadow_mode():
    log_shadow_decision(bot_id, cmd_id, payload, "SHADOW_MODE_ACTIVE")
    return {"ok": True, "botId": bot_id, "shadow": True, "logged": payload, "ts": now_iso()}
else:
    await q.put(payload)  # Comportamiento original
```
- **Criterio**: Comandos NO se encolan cuando SHADOW=true

**A5. Nuevo Endpoint Shadow Recent**
- **Archivo**: `backend/app.py`
- **Cambio**: Agregar `GET /api/v1/shadow/recent?limit=200`
- **Response**: Lista de ShadowDecision desde SQLite
- **Criterio**: Endpoint retorna decisiones shadow correctamente

**A6. Frontend Shadow Badge**
- **Archivo**: `frontend/src/App.jsx`
- **Cambio**: Detectar shadow mode via endpoint `/api/v1/health` (agregar campo `shadow_mode`)
- **UI**: Badge "SHADOW" visible cuando activo
- **Criterio**: Badge aparece/desaparece según configuración

**A7. Frontend Shadow Panel**
- **Archivo**: `frontend/src/App.jsx`
- **Cambio**: Nueva sección con tabla de decisiones shadow recientes
- **Datos**: Consume `/api/v1/shadow/recent`
- **Criterio**: Tabla muestra decisiones con timestamp, acción, símbolo

#### **Scripts/Tests ETAPA A**:
```bash
# Test 1: Verificar shadow mode OFF (comportamiento normal)
curl -X POST http://localhost:8000/api/v1/commands/bot-1 \
  -H "Content-Type: application/json" \
  -d '{"action":"BUY","qty":1,"symbol":"MNQ"}'
# Verificar: comando aparece en queue, NO en shadow log

# Test 2: Activar shadow mode
# Editar config.json: "shadow_mode": true
# Reiniciar backend

# Test 3: Verificar shadow mode ON
curl -X POST http://localhost:8000/api/v1/commands/bot-1 \
  -H "Content-Type: application/json" \
  -d '{"action":"BUY","qty":1,"symbol":"MNQ"}'
# Verificar: comando NO en queue, SÍ en shadow log

# Test 4: Verificar endpoint shadow
curl http://localhost:8000/api/v1/shadow/recent?limit=10
# Verificar: retorna decisiones shadow

# Test 5: Verificar frontend
# Abrir http://localhost:3001
# Verificar: Badge "SHADOW" visible, tabla con decisiones
```

---

### ETAPA B: ESTADO CONFIABLE (Snapshot y Reconciliación)

#### **Objetivo**: Snapshot de posición/órdenes desde Ninja y monitor de estado

#### **Tareas Atómicas**:

**B1. Nuevo Modelo Snapshot**
- **Archivo**: `backend/app.py`
- **Cambio**: Agregar `class PositionSnapshot(BaseModel)` con campos position, orders, fills
- **Criterio**: Modelo Pydantic validado

**B2. Endpoint Snapshot Ingestion**
- **Archivo**: `backend/app.py`
- **Cambio**: `POST /api/v1/snapshot/{bot_id}` para recibir snapshot desde Ninja
- **Store**: Nuevo `snapshot_store: Dict[str, dict]` en memoria
- **Criterio**: Endpoint recibe y almacena snapshots

**B3. Modificar BridgePuppet para Enviar Snapshot**
- **Archivo**: `BridgePuppet.cs`
- **Cambio**: Agregar método `SendPositionSnapshot()` que envía posición actual
- **Trigger**: Cada 30 segundos y al cambio de posición
- **Criterio**: Ninja envía snapshots periódicamente

**B4. Extender Health Endpoint**
- **Archivo**: `backend/app.py` línea 189-195
- **Cambio**: Agregar `lastSnapshotAge` y `positionState` a response
- **Criterio**: Health incluye info de snapshot

**B5. Frontend Monitor Status**
- **Archivo**: `frontend/src/App.jsx`
- **Cambio**: Mostrar `lastSnapshotAge` en bot status panel
- **Alert**: Warning si snapshot > 60 segundos
- **Criterio**: UI muestra edad del snapshot

#### **Scripts/Tests ETAPA B**:
```bash
# Test 1: Enviar snapshot manual
curl -X POST http://localhost:8000/api/v1/snapshot/bot-1 \
  -H "Content-Type: application/json" \
  -d '{"position":{"symbol":"MNQ","qty":1,"avgPrice":21150},"orders":[],"ts":"2026-01-05T01:45:00.000Z"}'

# Test 2: Verificar health con snapshot
curl http://localhost:8000/api/v1/health
# Verificar: incluye lastSnapshotAge

# Test 3: Verificar frontend muestra snapshot age
# Abrir http://localhost:3001
# Verificar: Bot status muestra "Last Snapshot: 30s ago"
```

---

### ETAPA C: SEGURIDAD Y ROBUSTEZ (Idempotencia y Kill Switch)

#### **Objetivo**: Idempotencia persistente, handshake tras reconexión, kill switch

#### **Tareas Atómicas**:

**C1. Persistir cmd_log en SQLite**
- **Archivo**: `backend/app.py`
- **Cambio**: Reemplazar `cmd_log: Dict` por SQLite table `command_log`
- **Schema**: `id, bot_id, event, payload, ts`
- **Criterio**: Logs persisten tras reinicio backend

**C2. Implementar Dedupe por CommandId**
- **Archivo**: `backend/app.py` en `enqueue_command()`
- **Cambio**: Check SQLite antes de encolar, skip si ya existe
- **Criterio**: Comandos duplicados rechazados

**C3. Handshake tras Reconexión WS**
- **Archivo**: `backend/app.py` WebSocket endpoint línea 381
- **Cambio**: Enviar pending commands al reconectar
- **Criterio**: Comandos pendientes se reenvían tras reconexión

**C4. Kill Switch Endpoint**
- **Archivo**: `backend/app.py`
- **Cambio**: `POST /api/v1/emergency/stop` que cancela todas las queues
- **Criterio**: Endpoint para emergencia funcional

**C5. Frontend Kill Switch Button**
- **Archivo**: `frontend/src/App.jsx`
- **Cambio**: Botón rojo "EMERGENCY STOP" que llama kill switch
- **Criterio**: Botón para emergencia visible y funcional

#### **Scripts/Tests ETAPA C**:
```bash
# Test 1: Verificar idempotencia
curl -X POST http://localhost:8000/api/v1/commands/bot-1 \
  -H "Content-Type: application/json" \
  -d '{"action":"BUY","qty":1,"symbol":"MNQ"}'
# Repetir mismo comando
# Verificar: segundo comando rechazado

# Test 2: Kill switch
curl -X POST http://localhost:8000/api/v1/emergency/stop
# Verificar: todas las queues vaciadas

# Test 3: Persistencia tras reinicio
# Reiniciar backend
curl http://localhost:8000/api/v1/commands/bot-1/log
# Verificar: logs anteriores siguen disponibles
```

---

## 📁 ARCHIVOS A TOCAR POR ETAPA

### **ETAPA A (Shadow Mode)**
- `config.json` - Agregar shadow_mode flag
- `backend/app.py` - Modificar enqueue_command(), agregar shadow endpoints, SQLite
- `frontend/src/App.jsx` - Badge shadow, panel decisiones

### **ETAPA B (Snapshot)**  
- `backend/app.py` - Modelo snapshot, endpoint, extender health
- `BridgePuppet.cs` - Método SendPositionSnapshot()
- `frontend/src/App.jsx` - Monitor snapshot age

### **ETAPA C (Seguridad)**
- `backend/app.py` - SQLite cmd_log, dedupe, handshake, kill switch
- `frontend/src/App.jsx` - Botón emergency stop

---

## ✅ CRITERIOS DE ACEPTACIÓN GLOBALES

### **ETAPA A**: 
- ✅ Shadow mode configurable via config.json
- ✅ Comandos NO se encolan cuando shadow=true  
- ✅ Decisiones shadow logueadas en SQLite
- ✅ Frontend muestra badge y tabla shadow
- ✅ Tests pasan: shadow ON/OFF, endpoint, UI

### **ETAPA B**:
- ✅ Ninja envía snapshots cada 30s
- ✅ Backend almacena y reporta snapshot age
- ✅ Frontend alerta si snapshot > 60s
- ✅ Tests pasan: snapshot ingestion, health, UI

### **ETAPA C**:
- ✅ cmd_log persiste en SQLite
- ✅ Comandos duplicados rechazados
- ✅ Kill switch funcional
- ✅ Tests pasan: idempotencia, persistencia, emergency

---

## 🚨 REGLAS DE IMPLEMENTACIÓN

1. **NO ROMPER CONTRATOS**: Mantener compatibilidad con endpoints existentes
2. **CAMBIOS INCREMENTALES**: Cada tarea debe ser verificable independientemente  
3. **FALLBACK SEGURO**: Shadow mode debe ser OFF por defecto
4. **TESTING OBLIGATORIO**: Cada etapa debe pasar sus tests antes de continuar

---

## ✅ ENTREGABLE 2 COMPLETADO

**Plan de 3 etapas con tareas atómicas, archivos específicos, cambios exactos y scripts de validación. Listo para FASE 3 - IMPLEMENTACIÓN ETAPA A.**