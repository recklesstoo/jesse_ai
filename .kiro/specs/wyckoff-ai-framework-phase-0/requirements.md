# Requirements Document

## Introduction

Framework científico estilo "Wyckoff + IA" - Fase 0: Base estable. Establecer comunicación nativa y robusta entre NinjaTrader (brazo ejecutor), Backend (cerebro analítico) y Frontend (panel de control) para mostrar datos de mercado en tiempo real.

## Glossary

- **BridgePuppet**: Estrategia NinjaScript que actúa como puente de comunicación
- **Backend**: Servidor FastAPI que procesa y almacena datos
- **Frontend**: Dashboard React/Vite para visualización y control
- **Bot**: Instancia de BridgePuppet identificada por botId
- **LIVE_Mode**: Modo de operación con datos reales del mercado
- **BACKTEST_Mode**: Modo de simulación histórica

## Requirements

### Requirement 1: NinjaTrader Data Streaming

**User Story:** As a trader, I want to see live market data from NinjaTrader in my dashboard, so that I can monitor real-time price movements.

#### Acceptance Criteria

1. WHEN BridgePuppet receives a new bar, THE System SHALL send bar data to backend within 100ms
2. WHEN sending bar data, THE BridgePuppet SHALL include botId, timestamp, symbol, timeframe, OHLCV, and mode
3. WHEN in LIVE mode, THE BridgePuppet SHALL send bars continuously during market hours
4. THE Bar_Data SHALL follow the exact JSON contract: botId, timestamp, symbol, timeframe, open, high, low, close, volume, mode
5. WHEN backend receives bar data, THE System SHALL store it and emit to frontend via WebSocket

### Requirement 2: Command System Integration

**User Story:** As a trader, I want to send trading commands from the frontend that get executed in NinjaTrader, so that I can control my trading remotely.

#### Acceptance Criteria

1. WHEN a command is sent from frontend, THE Backend SHALL enqueue it with unique ID and timestamp
2. WHEN BridgePuppet polls for commands, THE Backend SHALL return the next command in queue (LIVE mode only)
3. WHEN no commands are available, THE Backend SHALL wait up to 900ms before returning NONE command
4. THE Command SHALL include: id, action (BUY/SELL/FLATTEN/CLOSE), qty, slTicks, tpTicks, tag, symbol
5. WHEN BridgePuppet receives a command, THE System SHALL send ACK back to backend with execution status

### Requirement 3: Real-time Dashboard Display

**User Story:** As a trader, I want to see live price updates in my dashboard, so that I can make informed trading decisions.

#### Acceptance Criteria

1. WHEN new bar data arrives, THE Frontend SHALL update price display within 200ms
2. WHEN displaying prices, THE System SHALL show current OHLC, volume, and timestamp
3. WHEN connection is lost, THE Frontend SHALL show disconnected status with last update time
4. THE Dashboard SHALL display bot status: LIVE/BACKTEST, last seen timestamp, and connection health
5. WHEN backend is unreachable, THE Frontend SHALL show error state and retry automatically

### Requirement 4: Backend API Endpoints

**User Story:** As a system integrator, I want standardized API endpoints, so that all components can communicate reliably.

#### Acceptance Criteria

1. THE Backend SHALL expose /api/v1/health endpoint returning system status and bot count
2. THE Backend SHALL expose /api/v1/bots endpoint returning all registered bots with their status
3. THE Backend SHALL expose /api/v1/commands/{botId} for POST (enqueue) and GET (long-poll) operations
4. THE Backend SHALL expose /api/v1/bars/batch for receiving bar data from BridgePuppet
5. THE Backend SHALL expose /api/v1/commands/{botId}/ack for receiving command acknowledgments
### Requirement 5: WebSocket Real-time Communication

**User Story:** As a trader, I want instant updates when market data changes, so that I don't miss important price movements.

#### Acceptance Criteria

1. WHEN bar data is received by backend, THE System SHALL broadcast it via WebSocket to all connected clients
2. WHEN frontend connects, THE WebSocket SHALL send current bot status and latest bar data
3. WHEN WebSocket connection drops, THE Frontend SHALL attempt reconnection every 3 seconds
4. THE WebSocket SHALL emit events: bar_update, bot_status, command_ack, connection_status
5. WHEN multiple clients are connected, THE System SHALL broadcast to all simultaneously

### Requirement 6: Proxy Configuration for Development

**User Story:** As a developer, I want seamless API communication without CORS issues, so that development is smooth and production-ready.

#### Acceptance Criteria

1. THE Vite_Development_Server SHALL proxy /api requests to backend automatically
2. WHEN frontend makes API calls, THE System SHALL route them through proxy without CORS headers
3. WHEN in production, THE System SHALL work with direct backend communication
4. THE Proxy SHALL handle both HTTP and WebSocket connections transparently
5. WHEN proxy fails, THE System SHALL show clear error messages with troubleshooting hints

### Requirement 7: Error Handling and Recovery

**User Story:** As a trader, I want the system to handle errors gracefully and recover automatically, so that my trading is not interrupted.

#### Acceptance Criteria

1. WHEN BridgePuppet loses connection, THE System SHALL retry connection every 5 seconds
2. WHEN backend is down, THE Frontend SHALL show maintenance mode and keep retrying
3. WHEN invalid data is received, THE System SHALL log error and continue processing
4. THE System SHALL maintain command queue during temporary disconnections
5. WHEN errors occur, THE System SHALL provide actionable error messages to the user