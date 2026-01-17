param(
    [string]$ApiBase = "http://127.0.0.1:8000",
    [string]$Symbol = "MNQ",
    [string]$Timeframe = "1m",
    [int]$LookbackDays = 60,
    [string[]]$MLTimeframes = @("1m", "5m"),
    [bool]$CreateBots = $true,
    [bool]$TrainML = $true,
    [bool]$RunBacktests = $false,
    [string]$StartDay = "",
    [string]$EndDay = "",
    [int]$PollSec = 2
)

$ErrorActionPreference = "Stop"

function Wait-BacktestOrOptimize {
    param(
        [string]$ResultsUrl
    )

    while ($true) {
        Start-Sleep -Seconds $PollSec
        $r = Invoke-RestMethod -Method Get -Uri $ResultsUrl
        if ($r.status -in @("DONE", "ERROR")) { return $r }
    }
}

function Wait-TrainingDone {
    param(
        [string]$BotId
    )

    while ($true) {
        Start-Sleep -Seconds $PollSec
        $st = Invoke-RestMethod -Method Get -Uri "$ApiBase/api/v1/bots/train/status?botId=$([uri]::EscapeDataString($BotId))"
        $running = @($st.runs | Where-Object { $_.status -eq "RUNNING" })
        if ($running.Count -eq 0) { return $st }
    }
}

$bots = @(
    @{
        botId = "wyckoff-01-trend-pb"
        name = "Wyckoff 01 - Trend Pullback + BOS (SOS template)"
        setup = @{ kind = "trend_pullback_bos"; ema_trend_len = 200; ema_pullback_len = 20; bos_lookback = 10 }
        tags = @("wyckoff", "sos", "trend", "v1")
        train = @{ horizon_bars = 10; random_state = 101 }
    },
    @{
        botId = "wyckoff-02-spring"
        name = "Wyckoff 02 - Spring (Accumulation)"
        setup = @{ kind = "wyckoff_spring"; range_lookback = 200; buffer_ticks = 2; min_rvol20 = 1.15 }
        tags = @("wyckoff", "spring", "accumulation", "vsa", "v1")
        train = @{ horizon_bars = 8; random_state = 102 }
    },
    @{
        botId = "wyckoff-03-upthrust"
        name = "Wyckoff 03 - Upthrust (Distribution)"
        setup = @{ kind = "wyckoff_upthrust"; range_lookback = 200; buffer_ticks = 2; min_rvol20 = 1.15 }
        tags = @("wyckoff", "upthrust", "distribution", "vsa", "v1")
        train = @{ horizon_bars = 8; random_state = 103 }
    },
    @{
        botId = "wyckoff-04-sos-lps"
        name = "Wyckoff 04 - SOS + LPS (Breakout then Pullback)"
        setup = @{ kind = "wyckoff_sos_lps"; range_lookback = 240; breakout_buffer_ticks = 1; pullback_buffer_ticks = 1; min_rvol20_breakout = 1.25; memory_bars = 120 }
        tags = @("wyckoff", "sos", "lps", "breakout", "v1")
        train = @{ horizon_bars = 15; random_state = 104 }
    },
    @{
        botId = "wyckoff-05-sow-lpsy"
        name = "Wyckoff 05 - SOW + LPSY (Breakdown then Rally)"
        setup = @{ kind = "wyckoff_sow_lpsy"; range_lookback = 240; breakout_buffer_ticks = 1; pullback_buffer_ticks = 1; min_rvol20_breakout = 1.25; memory_bars = 120 }
        tags = @("wyckoff", "sow", "lpsy", "breakdown", "v1")
        train = @{ horizon_bars = 15; random_state = 105 }
    },
    @{
        botId = "wyckoff-06-selling-climax"
        name = "Wyckoff 06 - VSA Selling Climax (Reversal Long)"
        setup = @{ kind = "vsa_selling_climax"; min_vol_z50 = 2.3; min_spread_ticks = 12; close_pos_max = 0.35 }
        tags = @("wyckoff", "vsa", "climax", "reversal", "long", "v1")
        train = @{ horizon_bars = 6; random_state = 106 }
    },
    @{
        botId = "wyckoff-07-buying-climax"
        name = "Wyckoff 07 - VSA Buying Climax (Reversal Short)"
        setup = @{ kind = "vsa_buying_climax"; min_vol_z50 = 2.3; min_spread_ticks = 12; close_pos_min = 0.65 }
        tags = @("wyckoff", "vsa", "climax", "reversal", "short", "v1")
        train = @{ horizon_bars = 6; random_state = 107 }
    },
    @{
        botId = "wyckoff-08-range-reversion"
        name = "Wyckoff 08 - Range Reversion (Accum/Dist range)"
        setup = @{ kind = "wyckoff_range_reversion"; range_lookback = 300; entry_band_ticks = 4; side = "BOTH" }
        tags = @("wyckoff", "range", "mean-reversion", "v1")
        train = @{ horizon_bars = 5; random_state = 108 }
    },
    @{
        botId = "wyckoff-09-or-breakout"
        name = "Wyckoff 09 - Opening Range Breakout (OR15)"
        setup = @{ kind = "opening_range_breakout"; or_minutes = 15; buffer_ticks = 1; min_rvol20 = 1.05 }
        tags = @("wyckoff", "or", "breakout", "v1")
        train = @{ horizon_bars = 12; random_state = 109 }
    },
    @{
        botId = "wyckoff-10-contraction-breakout"
        name = "Wyckoff 10 - Contraction -> Breakout (Re-accum/Re-dist)"
        setup = @{ kind = "wyckoff_contraction_breakout"; range_lookback = 240; contraction_bars = 30; max_atr_ticks = 8; buffer_ticks = 1; min_rvol20 = 1.10 }
        tags = @("wyckoff", "contraction", "breakout", "continuation", "v1")
        train = @{ horizon_bars = 20; random_state = 110 }
    }
)

foreach ($b in $bots) {
    $botId = $b.botId
    Write-Host ""
    Write-Host "=== $botId ==="

    if ($CreateBots) {
        $spec = @{
            version  = "bot-spec.v1"
            botId    = $botId
            name     = $b.name
            symbol   = $Symbol.ToUpper()
            timeframe = $Timeframe.ToLower()
            session  = @{ mode = "BOTH"; tz = "America/New_York"; start_hhmm = 930; end_hhmm = 1600 }
            risk     = @{ qty = 1; stop_loss_ticks = 10; take_profit_ticks = 12; max_loss_usd = 1200.0 }
            gates    = @{ min_confidence = 0.10; min_atr_ticks = 6; cooldown_bars = 2; max_trades_per_session = 20 }
            setup    = $b.setup
            tags     = $b.tags
        }

        Write-Host "POST $ApiBase/api/v1/bots"
        $res = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/v1/bots" -ContentType "application/json" -Body ($spec | ConvertTo-Json -Depth 10)
        if (-not $res.ok) { throw "create bot failed: $($res | ConvertTo-Json -Depth 10)" }
        Write-Host "OK created/updated bot spec"
    }

    if ($RunBacktests) {
        if (-not $StartDay -or -not $EndDay) { throw "RunBacktests requires -StartDay and -EndDay (YYYY-MM-DD)" }
        Write-Host "POST $ApiBase/api/v1/backtest/run"
        $run = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/v1/backtest/run" -ContentType "application/json" -Body (@{ botId = $botId; startDay = $StartDay; endDay = $EndDay } | ConvertTo-Json)
        $runId = $run.runId
        $done = Wait-BacktestOrOptimize -ResultsUrl "$ApiBase/api/v1/backtest/results/$runId"
        Write-Host ("Backtest status=" + $done.status + " netPnL=" + (($done.metrics.metrics.netPnL) -as [double]))
    }

    if ($TrainML) {
        $trainBody = @{
            botId = $botId
            symbol = $Symbol.ToUpper()
            timeframes = $MLTimeframes
            lookback_days = $LookbackDays
            config = $b.train
        }
        Write-Host "POST $ApiBase/api/v1/bots/train"
        $t = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/v1/bots/train" -ContentType "application/json" -Body ($trainBody | ConvertTo-Json -Depth 10)
        Write-Host ("run_ids=" + (($t.run_ids | ForEach-Object { $_ }) -join ", "))
        $st = Wait-TrainingDone -BotId $botId
        $latest = @($st.runs | Select-Object -First 2)
        Write-Host ("Training done. Latest=" + (($latest | ForEach-Object { "$($_.timeframe):$($_.status)" }) -join " "))
    }
}

Write-Host ""
Write-Host "DONE."
