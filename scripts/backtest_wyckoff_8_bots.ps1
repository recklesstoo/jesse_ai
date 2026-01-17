param(
    [string]$ApiBase = "http://127.0.0.1:8000",
    [string]$Symbol = "MNQ",
    [string]$Timeframe = "1m",
    [string]$StartDay = "",
    [string]$EndDay = "",
    [int]$PollSec = 1
)

$ErrorActionPreference = "Stop"

function Get-Days {
    $url = "$ApiBase/api/v1/data/days?symbol=$([uri]::EscapeDataString($Symbol.ToUpper()))&timeframe=$([uri]::EscapeDataString($Timeframe.ToLower()))"
    return Invoke-RestMethod -Method Get -Uri $url
}

function Wait-BacktestDone {
    param([string]$RunId)
    while ($true) {
        Start-Sleep -Seconds $PollSec
        $res = Invoke-RestMethod -Method Get -Uri "$ApiBase/api/v1/backtest/results/$RunId"
        if ($res.status -in @("DONE", "ERROR")) { return $res }
    }
}

try {
    Invoke-RestMethod -Method Get -Uri "$ApiBase/api/v1/health" | Out-Null
} catch {
    throw "Backend not reachable at $ApiBase (try starting it first)."
}

$daysResp = Get-Days
if (-not $daysResp.ok -or -not $daysResp.days -or $daysResp.days.Count -eq 0) {
    throw "No data_bars found for $Symbol $Timeframe. Import or ingest data first."
}

if (-not $StartDay -or -not $EndDay) {
    # Use the widest available range: oldest -> newest.
    $sorted = @($daysResp.days | Sort-Object)
    $StartDay = $sorted[0]
    $EndDay = $sorted[$sorted.Count - 1]
}

Write-Host "Using backtest range $StartDay -> $EndDay (symbol=$Symbol tf=$Timeframe)"

$bots = @(
    @{
        botId = "w8-01-spring"
        name = "Wyckoff Specialist 01 - Spring (Accumulation)"
        setup = @{ kind = "wyckoff_spring"; range_lookback = 200; buffer_ticks = 2; min_rvol20 = 1.10 }
        tags = @("wyckoff", "spring", "accumulation", "specialist", "v1")
        gates = @{ min_confidence = 0.10; min_atr_ticks = 6; cooldown_bars = 2; max_trades_per_session = 12 }
        risk  = @{ qty = 1; stop_loss_ticks = 12; take_profit_ticks = 16; max_loss_usd = 1200.0 }
    },
    @{
        botId = "w8-02-upthrust"
        name = "Wyckoff Specialist 02 - Upthrust (Distribution)"
        setup = @{ kind = "wyckoff_upthrust"; range_lookback = 200; buffer_ticks = 2; min_rvol20 = 1.10 }
        tags = @("wyckoff", "upthrust", "distribution", "specialist", "v1")
        gates = @{ min_confidence = 0.10; min_atr_ticks = 6; cooldown_bars = 2; max_trades_per_session = 12 }
        risk  = @{ qty = 1; stop_loss_ticks = 12; take_profit_ticks = 16; max_loss_usd = 1200.0 }
    },
    @{
        botId = "w8-03-sos-lps"
        name = "Wyckoff Specialist 03 - SOS + LPS"
        setup = @{ kind = "wyckoff_sos_lps"; range_lookback = 240; breakout_buffer_ticks = 1; pullback_buffer_ticks = 1; min_rvol20_breakout = 1.20; memory_bars = 120 }
        tags = @("wyckoff", "sos", "lps", "breakout", "specialist", "v1")
        gates = @{ min_confidence = 0.10; min_atr_ticks = 6; cooldown_bars = 1; max_trades_per_session = 10 }
        risk  = @{ qty = 1; stop_loss_ticks = 10; take_profit_ticks = 18; max_loss_usd = 1200.0 }
    },
    @{
        botId = "w8-04-sow-lpsy"
        name = "Wyckoff Specialist 04 - SOW + LPSY"
        setup = @{ kind = "wyckoff_sow_lpsy"; range_lookback = 240; breakout_buffer_ticks = 1; pullback_buffer_ticks = 1; min_rvol20_breakout = 1.20; memory_bars = 120 }
        tags = @("wyckoff", "sow", "lpsy", "breakdown", "specialist", "v1")
        gates = @{ min_confidence = 0.10; min_atr_ticks = 6; cooldown_bars = 1; max_trades_per_session = 10 }
        risk  = @{ qty = 1; stop_loss_ticks = 10; take_profit_ticks = 18; max_loss_usd = 1200.0 }
    },
    @{
        botId = "w8-05-selling-climax"
        name = "Wyckoff Specialist 05 - VSA Selling Climax"
        setup = @{ kind = "vsa_selling_climax"; min_vol_z50 = 2.0; min_spread_ticks = 10; close_pos_max = 0.35 }
        tags = @("wyckoff", "vsa", "selling-climax", "reversal", "specialist", "v1")
        gates = @{ min_confidence = 0.10; min_atr_ticks = 4; cooldown_bars = 2; max_trades_per_session = 8 }
        risk  = @{ qty = 1; stop_loss_ticks = 14; take_profit_ticks = 14; max_loss_usd = 1200.0 }
    },
    @{
        botId = "w8-06-buying-climax"
        name = "Wyckoff Specialist 06 - VSA Buying Climax"
        setup = @{ kind = "vsa_buying_climax"; min_vol_z50 = 2.0; min_spread_ticks = 10; close_pos_min = 0.65 }
        tags = @("wyckoff", "vsa", "buying-climax", "reversal", "specialist", "v1")
        gates = @{ min_confidence = 0.10; min_atr_ticks = 4; cooldown_bars = 2; max_trades_per_session = 8 }
        risk  = @{ qty = 1; stop_loss_ticks = 14; take_profit_ticks = 14; max_loss_usd = 1200.0 }
    },
    @{
        botId = "w8-07-contraction-breakout"
        name = "Wyckoff Specialist 07 - Contraction -> Breakout"
        setup = @{ kind = "wyckoff_contraction_breakout"; range_lookback = 240; contraction_bars = 25; max_atr_ticks = 8; buffer_ticks = 1; min_rvol20 = 1.05 }
        tags = @("wyckoff", "contraction", "breakout", "continuation", "specialist", "v1")
        gates = @{ min_confidence = 0.10; min_atr_ticks = 2; cooldown_bars = 1; max_trades_per_session = 12 }
        risk  = @{ qty = 1; stop_loss_ticks = 10; take_profit_ticks = 16; max_loss_usd = 1200.0 }
    },
    @{
        botId = "w8-08-trend-pullback-bos"
        name = "Wyckoff Specialist 08 - Trend Pullback + BOS"
        setup = @{ kind = "trend_pullback_bos"; ema_trend_len = 200; ema_pullback_len = 20; bos_lookback = 10 }
        tags = @("wyckoff", "trend", "bos", "specialist", "v1")
        gates = @{ min_confidence = 0.10; min_atr_ticks = 6; cooldown_bars = 2; max_trades_per_session = 20 }
        risk  = @{ qty = 1; stop_loss_ticks = 10; take_profit_ticks = 12; max_loss_usd = 1200.0 }
    }
)

$results = @()

foreach ($b in $bots) {
    $botId = $b.botId
    Write-Host ""
    Write-Host "=== Creating bot $botId ==="

    $spec = @{
        version  = "bot-spec.v1"
        botId    = $botId
        name     = $b.name
        symbol   = $Symbol.ToUpper()
        timeframe = $Timeframe.ToLower()
        session  = @{ mode = "BOTH"; tz = "America/New_York"; start_hhmm = 930; end_hhmm = 1600 }
        risk     = $b.risk
        gates    = $b.gates
        setup    = $b.setup
        tags     = $b.tags
    }

    $create = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/v1/bots" -ContentType "application/json" -Body ($spec | ConvertTo-Json -Depth 10)
    if (-not $create.ok) { throw "create bot failed: $($create | ConvertTo-Json -Depth 10)" }

    Write-Host "=== Backtesting $botId ==="
    $run = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/v1/backtest/run" -ContentType "application/json" -Body (@{ botId = $botId; startDay = $StartDay; endDay = $EndDay } | ConvertTo-Json)
    $runId = $run.runId
    $done = Wait-BacktestDone -RunId $runId

    if ($done.status -ne "DONE") {
        $results += [pscustomobject]@{ botId = $botId; status = $done.status; error = $done.error; netPnL = $null; maxDD = $null; trades = $null; profitFactor = $null }
        Write-Host ("ERROR status=" + $done.status + " err=" + $done.error)
        continue
    }

    $m = $done.metrics.metrics
    $results += [pscustomobject]@{
        botId = $botId
        status = $done.status
        netPnL = [double]$m.netPnL
        maxDD = [double]$m.maxDD
        trades = [int]$m.trades
        profitFactor = [double]$m.profitFactor
        winrate = [double]$m.winrate
        avgTrade = [double]$m.avgTrade
        runId = $runId
    }

    Write-Host ("DONE netPnL=" + ([double]$m.netPnL).ToString("0.00") + " trades=" + $m.trades + " pf=" + ([double]$m.profitFactor).ToString("0.00"))
}

Write-Host ""
Write-Host "=== SUMMARY (sorted by netPnL desc) ==="
$results | Sort-Object -Property netPnL -Descending | Format-Table -AutoSize botId,status,netPnL,maxDD,trades,profitFactor,winrate,avgTrade,runId
