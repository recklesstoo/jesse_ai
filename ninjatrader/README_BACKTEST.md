# NT8 Swarm v1 (Strategy Analyzer Optimization) — BotBacktestRunner

Objetivo: ejecutar decisiones *en barras cerradas* (determinístico) y dejar que Ninja (Strategy Analyzer / Optimization) simule fills para medir PnL/DD/winrate **sin backend, sin WS, sin DB**.

## Archivo
- `ninjatrader/BotBacktestRunner.cs` (standalone)

## Reglas críticas
- `Calculate=OnBarClose` (ya viene hard-coded).
- 1 decisión por barra cerrada.
- No HTTP/WebSocket/SQLite.
- Si no hay setup → no opera (0 trades es OK).

## Cómo correr el “enjambre” (Optimization)
1) En NinjaTrader 8 → New → NinjaScript Editor → agrega estos archivos (mismo namespace).
2) Strategy Analyzer:
   - Strategy: `BotBacktestRunner`
3) Optimization:
   - Define rangos:
     - `StopLossTicks`, `TakeProfitTicks`, `MinAtrTicks`, `CooldownBars`, `MaxTradesPerSession`, `MinConfidence`
     - `SessionMode` (`RTH/ETH/BOTH`) y ventana `StartTimeHHmm/EndTimeHHmm` si aplica.
4) Ejecuta.
5) Busca en Output el JSON final: `{"type":"BACKTEST_SUMMARY", ... }`

## Validación rápida
- Si no hay setup → `trades=0` y está bien.
- Si hay setup → debe ver entradas `bt_buy`/`bt_sell` con SL/TP por ticks, y métricas en Strategy Analyzer.
