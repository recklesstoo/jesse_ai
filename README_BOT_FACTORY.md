# Bot Factory v1 (no-code BotSpec)

Bot Factory v1 lets the assistant create bots by producing **only** a closed-schema `BotSpec v1` JSON. The backend validates it strictly and can run deterministic backtests and capped optimizations from stored `data_bars` (no WS, no DB flood per bar).

## 0) Preconditions
- Backend running on `http://127.0.0.1:8000`
- You have historical bars stored in `data_bars` for the `symbol` + `timeframe` you will backtest.
  - Check: `GET /api/v1/data/days?symbol=MNQ&timeframe=1m`

## 1) Create / update a bot (BotSpec v1)
```powershell
curl -X POST http://127.0.0.1:8000/api/v1/bots `
  -H "Content-Type: application/json" `
  -d '{
    "version":"bot-spec.v1",
    "botId":"bot-1",
    "name":"TrendPullbackBOS",
    "symbol":"MNQ",
    "timeframe":"1m",
    "session":{"mode":"BOTH","tz":"America/New_York","start_hhmm":930,"end_hhmm":1600},
    "risk":{"qty":1,"stop_loss_ticks":10,"take_profit_ticks":12,"max_loss_usd":1200},
    "gates":{"min_confidence":0.10,"min_atr_ticks":6,"cooldown_bars":2,"max_trades_per_session":20},
    "setup":{"kind":"trend_pullback_bos","ema_trend_len":200,"ema_pullback_len":20,"bos_lookback":10},
    "tags":["v1"]
  }'
```

Fetch it back:
```powershell
curl http://127.0.0.1:8000/api/v1/bots/bot-1
```

Schema (generated):
- `backend/contracts/bot_spec_v1.schema.json`

## 2) Run deterministic backtest
```powershell
$run = (curl -s -X POST http://127.0.0.1:8000/api/v1/backtest/run `
  -H "Content-Type: application/json" `
  -d '{"botId":"bot-1","startDay":"2024-01-02","endDay":"2024-01-05"}' | ConvertFrom-Json)

curl http://127.0.0.1:8000/api/v1/backtest/results/$($run.runId)
```

## 3) Run capped optimization (<= 50 variants)
Allowed grid keys:
- `risk.stop_loss_ticks`, `risk.take_profit_ticks`, `risk.qty`, `risk.max_loss_usd`
- `gates.min_confidence`, `gates.min_atr_ticks`, `gates.cooldown_bars`, `gates.max_trades_per_session`

```powershell
$opt = (curl -s -X POST http://127.0.0.1:8000/api/v1/optimize/run `
  -H "Content-Type: application/json" `
  -d '{
    "botId":"bot-1",
    "startDay":"2024-01-02",
    "endDay":"2024-01-05",
    "grid":{
      "risk.stop_loss_ticks":[8,10,12],
      "risk.take_profit_ticks":[10,12,14]
    }
  }' | ConvertFrom-Json)

curl http://127.0.0.1:8000/api/v1/optimize/results/$($opt.runId)
```

## 4) Performance summary
```powershell
curl "http://127.0.0.1:8000/api/v1/perf/summary?botId=bot-1"
```

## Notes (stability + safety)
- Backtest/optimize are **deterministic** and do not stream data.
- No per-bar DB writes; results are persisted at the end of each run.
- Live trade execution remains disabled by backend policy; Bot Factory is for research + SIM/backtest only.

