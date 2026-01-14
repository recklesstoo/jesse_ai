param(
  [string]$ApiBase = "http://localhost:8000",
  [string]$FrontendBase = "http://localhost:3001",
  [string]$BotId = "bot-1",
  [string]$Token = "",
  [int]$TimeoutSec = 15
)

$ErrorActionPreference = "Stop"

function Assert-Ok($cond, $msg) {
  if (-not $cond) { throw $msg }
}

function Get-Json($url) {
  return Invoke-RestMethod -Method Get -Uri $url -TimeoutSec 5
}

function Post-Json($url, $obj, $headers = @{}) {
  $json = ($obj | ConvertTo-Json -Depth 10)
  return Invoke-RestMethod -Method Post -Uri $url -ContentType "application/json" -Headers $headers -Body $json -TimeoutSec 10
}

function Coalesce([object[]]$vals) {
  foreach ($v in $vals) {
    if ($null -ne $v -and ($v.ToString()).Length -gt 0) { return $v }
  }
  return $null
}

Write-Host "[1/6] Checking ports..." -ForegroundColor Cyan
$p8000 = Test-NetConnection -ComputerName "localhost" -Port 8000 -WarningAction SilentlyContinue
$p3001 = Test-NetConnection -ComputerName "localhost" -Port 3001 -WarningAction SilentlyContinue
Assert-Ok $p8000.TcpTestSucceeded "Port 8000 is not reachable."
Assert-Ok $p3001.TcpTestSucceeded "Port 3001 is not reachable."

Write-Host "[2/6] Checking /api/v1/health..." -ForegroundColor Cyan
$health = Get-Json "$ApiBase/api/v1/health"
Assert-Ok $health.ok "/api/v1/health not ok."

Write-Host "[3/6] Checking /api/v1/execution/status..." -ForegroundColor Cyan
$exec = Get-Json "$ApiBase/api/v1/execution/status?botId=$BotId"
Assert-Ok $exec.ok "/api/v1/execution/status not ok."
Write-Host ("execution_mode={0} token_required={1} ws_connected={2}" -f $exec.execution_mode, $exec.token_required, $exec.ws_connected)

Assert-Ok ($exec.ws_connected -eq $true) "BridgePuppet bot is not connected (ws_connected=false); cannot validate WS command delivery/ACK."

if ($exec.execution_mode -eq "DISABLED") {
  Write-Host "[INFO] execution_mode is DISABLED; attempting to set MANUAL_ONLY..." -ForegroundColor Yellow
  $headers = @{}
  if ($Token) { $headers["x-execution-token"] = $Token }
  $set = Post-Json "$ApiBase/api/v1/execution/enable" @{ mode = "MANUAL_ONLY" } $headers
  $why = Coalesce @($set.reason, $set.error, "unknown")
  Assert-Ok $set.ok ("execution/enable failed: {0}" -f $why)
  $exec = Get-Json "$ApiBase/api/v1/execution/status?botId=$BotId"
  Write-Host ("execution_mode={0}" -f $exec.execution_mode)
}

Write-Host "[4/6] Sending manual BUY command..." -ForegroundColor Cyan
$cmd = Post-Json "$ApiBase/api/v1/commands/$BotId" @{
  action = "BUY"
  qty = 1
  slTicks = 0
  tpTicks = 0
  tag = "manual"
  symbol = "MNQ"
}

$cmdId = $cmd.queued.id
Assert-Ok $cmdId "Missing cmd id in response."
if ($cmd.ok -eq $false -and $cmd.ack) {
  $why = Coalesce @($cmd.ack.reject_reason, $cmd.ack.reason, "")
  throw ("Command rejected/ignored: {0} ({1})" -f $cmd.ack.status, $why)
}

Write-Host ("cmd_id={0}" -f $cmdId)

Write-Host "[5/6] Polling command log for DELIVERED + ACK_SENT..." -ForegroundColor Cyan
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$delivered = $false
$ack = $null

while ((Get-Date) -lt $deadline) {
  $log = Get-Json "$ApiBase/api/v1/commands/$BotId/log?limit=200"
  $row = $log.log | Where-Object { $_.id -eq $cmdId } | Select-Object -First 1
  if ($row) {
    if ($row.event -eq "DELIVERED") { $delivered = $true }
    if ($row.event -like "ACK_*") { $ack = $row.event }
    if ($delivered -and $ack) { break }
  }
  Start-Sleep -Milliseconds 500
}

Assert-Ok $delivered "Did not observe DELIVERED for cmd in command log."
if (-not $ack) {
  Write-Host "[WARN] Delivered, but no ACK_* observed yet (BridgePuppet may be offline)." -ForegroundColor Yellow
} else {
  Write-Host ("ACK observed: {0}" -f $ack) -ForegroundColor Green
  Assert-Ok ($ack -eq "ACK_SENT" -or $ack -eq "ACK_RECEIVED") ("Unexpected ACK status: {0}" -f $ack)
}

Write-Host "[6/6] OK" -ForegroundColor Green
