# Implementation Plan: Wyckoff AI Framework Phase 0

## Overview

Implementation plan for establishing stable communication between NinjaTrader (BridgePuppet), FastAPI backend, and React frontend. Focus on real-time data streaming, command execution, and live dashboard display.

## Tasks

- [x] 1. Configure Vite Proxy and Backend CORS
  - Set up Vite proxy configuration to route /api requests to backend
  - Update backend CORS settings for seamless development
  - Test proxy functionality with existing endpoints
  - _Requirements: 6.1, 6.2_

- [-] 2. Implement WebSocket Real-time Communication
  - [x] 2.1 Add WebSocket endpoint to FastAPI backend
    - Create /ws/live WebSocket endpoint
    - Implement connection management and client tracking
    - _Requirements: 5.1, 5.2_

  - [ ] 2.2 Write property test for WebSocket broadcast
    - **Property 16: Multi-client broadcast consistency**
    - **Validates: Requirements 5.1, 5.5**

  - [x] 2.3 Create WebSocket hook in React frontend
    - Implement useWebSocket hook with reconnection logic
    - Handle connection states and error recovery
    - _Requirements: 5.3, 3.3_

  - [ ] 2.4 Write property test for WebSocket reconnection
    - **Property 18: WebSocket reconnection timing**
    - **Validates: Requirements 5.3**

- [-] 3. Enhance Bar Data Processing Pipeline
  - [x] 3.1 Update backend bar data endpoints
    - Enhance /api/v1/bars/batch to emit WebSocket events
    - Add data validation and error handling
    - _Requirements: 1.5, 4.4_

  - [ ] 3.2 Write property test for bar data flow
    - **Property 4: Bar data storage and broadcast**
    - **Validates: Requirements 1.5**
  - [x] 3.3 Update BridgePuppet bar transmission
    - Ensure bar data includes all required fields
    - Add timing optimization for <100ms transmission
    - _Requirements: 1.1, 1.2_

  - [ ] 3.4 Write property test for bar data structure
    - **Property 2: Bar data structure completeness**
    - **Validates: Requirements 1.2**


- [-] 4. Implement Live Price Display Component
  - [x] 4.1 Create enhanced LivePriceDisplay component
    - Display real-time OHLCV data from WebSocket
    - Show timestamp and volume information
    - Add connection status indicators
    - _Requirements: 3.1, 3.2_


  - [x] 4.3 Create BotStatusPanel component
    - Display bot mode (LIVE/BACKTEST), last seen timestamp
    - Show connection health and status indicators
    - _Requirements: 3.4_

  - [ ] 4.4 Write property test for bot status display
    - **Property 12: Connection status accuracy**
    - **Validates: Requirements 3.3, 3.5**

- [ ] 5. Checkpoint - Verify Real-time Data Flow
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Enhance Command System with Acknowledgments
  - [ ] 6.1 Add command acknowledgment endpoint
    - Implement /api/v1/commands/{botId}/ack endpoint
    - Store and track command execution status
    - _Requirements: 4.5, 2.5_

  - [x] 6.2 Write property test for command acknowledgments
    - **Property 9: Command acknowledgment flow**
    - **Validates: Requirements 2.5**

- [x] 11. Final checkpoint - Complete system operational
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- All tasks are now required for comprehensive implementation
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties
- Integration tests validate complete system functionality
- Testing framework: Jest with property-based testing library (fast-check)
- Minimum 100 iterations per property test for thorough validation
- Smoke tests: run `scripts/test-endpoints.ps1` to validate HTTP + WS after API changes







