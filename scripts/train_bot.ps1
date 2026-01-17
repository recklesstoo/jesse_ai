param(
    [string]$BotId = "bot-1",
    [string]$Symbol = "MNQ",
    [string[]]$Timeframes = @("1m", "5m"),
    [int]$LookbackDays = 60,
    [string]$ApiBase = "http://127.0.0.1:8000",
    [int]$PollSec = 2
)

$ErrorActionPreference = "Stop"

$body = @{
    botId        = $BotId
    symbol       = $Symbol
    timeframes   = $Timeframes
    lookback_days = $LookbackDays
    config       = @{}
} | ConvertTo-Json -Depth 6

Write-Host "POST $ApiBase/api/v1/bots/train"
Write-Host $body

$res = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/v1/bots/train" -ContentType "application/json" -Body $body
Write-Host ("run_ids=" + (($res.run_ids | ForEach-Object { $_ }) -join ", "))

while ($true) {
    Start-Sleep -Seconds $PollSec
    $st = Invoke-RestMethod -Method Get -Uri "$ApiBase/api/v1/bots/train/status?botId=$BotId"
    $runs = @($st.runs | Select-Object -First 5)
    Write-Host ("status ts=" + (Get-Date).ToString("HH:mm:ss") + " latest=" + (($runs | ForEach-Object { "$($_.timeframe):$($_.status)" }) -join " "))
    if ($runs.Count -gt 0 -and ($runs | Where-Object { $_.status -in @("RUNNING") }).Count -eq 0) {
        break
    }
}

Write-Host "DONE. Latest models:"
Invoke-RestMethod -Method Get -Uri "$ApiBase/api/v1/bots/models?botId=$BotId" | ConvertTo-Json -Depth 6

