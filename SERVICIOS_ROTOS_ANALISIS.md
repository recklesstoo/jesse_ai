# ANÁLISIS DE SERVICIOS ROTOS Y DEPENDENCIAS

## 🔍 RESUMEN EJECUTIVO

He identificado múltiples servicios rotos y dependencias problemáticas en el sistema de trading. El análisis revela inconsistencias entre el frontend y backend, endpoints faltantes, y configuraciones conflictivas.

## 🚨 SERVICIOS ROTOS CRÍTICOS

### 1. **ENDPOINTS FALTANTES EN BACKEND**

**Frontend solicita pero Backend NO implementa:**

- `/api/control/action` - Usado en App.jsx para acciones críticas
- `/api/toggle-mode` - Usado en TestingModeController.jsx y EmergencyControls.jsx  
- `/api/strategy/state` - Usado en ParameterEditor.jsx
- `/api/dynamic-prices` - Usado en ParameterEditor.jsx
- `/api/strategy/parameters` - Usado en ParameterEditor.jsx
- `/api/configure-prices` - Usado en ParameterEditor.jsx
- `/api/news/status` - Usado en NewsFilterCard.jsx
- `/api/news/upcoming` - Usado en NewsFilterCard.jsx
- `/api/news/add_event` - Usado en NewsFilterCard.jsx
- `/api/news/remove_event/{id}` - Usado en NewsFilterCard.jsx
- `/api/news/clear_past` - Usado en NewsFilterCard.jsx
- `/api/ai-signals` - Usado en AITradingPanel.jsx
- `/api/ai-order` - Usado en AITradingPanel.jsx
- `/api/manual-order-advanced` - Usado en AdvancedTradingPanel.jsx

### 2. **DEPENDENCIAS DE ARCHIVOS FALTANTES**

**Backend importa archivos que NO existen:**

```python
# En backend/main.py
from core.config import Config          # ✅ EXISTE
from core.logger import setup_logging   # ✅ EXISTE

# En backend/ninja_main.py  
from core.decision_engine import decision_engine    # ✅ EXISTE
from core.emergency_manager import emergency_manager # ✅ EXISTE
```

**Archivos de configuración problemáticos:**
- `backend/config.json` apunta a `../data/` que fue eliminado
- `config.json` apunta a `data/` que fue eliminado

### 3. **MÚLTIPLES BACKENDS CONFLICTIVOS**

**Problema:** Hay 3 archivos principales de backend que se ejecutan en el mismo puerto:

1. `backend/main.py` - Puerto 8000
2. `backend/ninja_main.py` - Puerto 8000  
3. `backend/api/app.py` - Importado pero no ejecutado directamente

**Conflicto:** Solo uno puede ejecutarse a la vez, causando confusión sobre cuál usar.

### 4. **COMPONENTES FRONTEND SIN BACKEND**

**Componentes que hacen llamadas a APIs inexistentes:**

- `SimplePriceDisplay` - Referenciado en App.jsx pero eliminado
- `SimpleManualTrading` - Referenciado en App.jsx pero eliminado
- `NewsFilterCard` - Múltiples endpoints faltantes
- `ParameterEditor` - Múltiples endpoints faltantes
- `AITradingPanel` - Endpoints de AI faltantes
- `ShadowModeCard` - Algunos endpoints existen en api/app.py pero no en main.py

## 🔧 DEPENDENCIAS ROTAS POR CATEGORÍA

### **CONFIGURACIÓN**
- ❌ Rutas de datos apuntan a directorios eliminados
- ❌ Configuraciones duplicadas entre root y backend
- ❌ Referencias a ChatGPT API sin implementación

### **LOGGING**
- ❌ Logger intenta escribir a `../data/logs` (eliminado)
- ✅ Configuración de logging funcional

### **BASE DE DATOS**
- ❌ Referencias a `../data/trading.db` (directorio eliminado)
- ❌ Schema de base de datos definido pero no inicializado

### **WEBSOCKETS**
- ✅ WebSocket funcional en backend
- ✅ Frontend tiene fallback HTTP
- ⚠️ Algunos endpoints de fallback faltantes

## 🎯 SERVICIOS FUNCIONALES

### **ENDPOINTS QUE SÍ FUNCIONAN:**

**En backend/main.py:**
- ✅ `/` - Root endpoint
- ✅ `/health` - Health check
- ✅ `/api/bar-data` - Recibe datos de NinjaTrader
- ✅ `/api/state/latest` - Estado del sistema
- ✅ `/api/current-price` - Precio actual
- ✅ `/api/manual-order` - Órdenes manuales
- ✅ `/api/register-strategy` - Registro de estrategias
- ✅ `/api/signals/{strategy_id}` - Señales por estrategia
- ✅ `/ws/live` - WebSocket en vivo

**En backend/ninja_main.py:**
- ✅ Mismos endpoints básicos
- ✅ Funcionalidad específica de NinjaTrader
- ✅ Manejo de datos síncronos/asíncronos

## 🚨 IMPACTO EN FUNCIONALIDAD

### **CRÍTICO (Sistema no funciona):**
- Control de emergencia (kill switch)
- Cambio de modos (testing/live)
- Configuración de parámetros
- Noticias y eventos
- Trading con AI

### **ALTO (Funcionalidad limitada):**
- Modo sombra (shadow mode)
- Configuración avanzada
- Métricas detalladas

### **MEDIO (Funciona con limitaciones):**
- Trading manual básico
- Visualización de precios
- WebSocket con fallback HTTP

### **BAJO (Funciona correctamente):**
- Conexión con NinjaTrader
- Recepción de datos de mercado
- Registro de estrategias

## 📋 RECOMENDACIONES INMEDIATAS

### **1. CONSOLIDAR BACKENDS**
- Decidir cuál backend usar (main.py vs ninja_main.py)
- Eliminar el backend no utilizado
- Unificar endpoints en un solo archivo

### **2. IMPLEMENTAR ENDPOINTS FALTANTES**
- Crear endpoints críticos para control de emergencia
- Implementar toggle de modos
- Agregar endpoints de configuración

### **3. REPARAR CONFIGURACIONES**
- Recrear directorio `data/` o actualizar rutas
- Consolidar archivos de configuración
- Reparar logging paths

### **4. LIMPIAR FRONTEND**
- Remover componentes que referencian servicios inexistentes
- Actualizar imports rotos
- Agregar manejo de errores para endpoints faltantes

### **5. TESTING**
- Probar cada endpoint individualmente
- Verificar flujo completo frontend-backend
- Validar manejo de errores

## 🎯 PRIORIDAD DE REPARACIÓN

1. **INMEDIATO:** Consolidar backends y reparar configuración
2. **URGENTE:** Implementar endpoints de control críticos
3. **ALTO:** Reparar componentes de trading manual
4. **MEDIO:** Implementar funcionalidades avanzadas
5. **BAJO:** Optimizar y limpiar código

---

**CONCLUSIÓN:** El sistema tiene una base funcional sólida para trading básico con NinjaTrader, pero múltiples servicios avanzados están rotos debido a endpoints faltantes y configuraciones problemáticas. La reparación debe priorizarse según el impacto en la funcionalidad crítica del trading.
---

## ACTUALIZACION 2026-01-08

- Backend consolidado en ackend/app.py.
- Endpoints ahora implementados:
  - /api/control/action, /api/toggle-mode`r
  - /api/strategy/state, /api/strategy/parameters`r
  - /api/dynamic-prices, /api/configure-prices`r
  - /api/news/status, /api/news/upcoming, /api/news/add_event, /api/news/remove_event/{id}, /api/news/clear_past`r
  - /api/ai-signals, /api/ai-order`r
  - /api/manual-order-advanced`r
- Noticias: almacenamiento en memoria (sin persistencia).

- Smoke test: scripts/test-endpoints.ps1 cubre HTTP y WS.

## ACTUALIZACION 2026-01-10

- Monitoreo operativo agregado:
  - /api/monitor/status y /api/v1/monitor/status
  - /api/monitor/repair y /api/v1/monitor/repair
- Nota backtest: si BridgePuppet envia mode=LIVE en backtest, el backend queda en LIVE y el feed se ve "stale".
- Diagnostico rapido:
  - wsConnected=true pero lastBarAgeSec alto indica replay detenido o estrategia no aplicada al grafico.
