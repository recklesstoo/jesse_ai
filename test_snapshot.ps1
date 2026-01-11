# =============================================================================
# test_snapshot.ps1
# Validación end-to-end ETAPA B (Snapshot)
# =============================================================================

$ErrorActionPreference = "Stop"

$base = "http://localhost:8000"
$api  = "$base/api/v1"
$bot  = "bot-test-ps1"

function Fail($msg) {
  Write-Host "[FAIL] $msg" -ForegroundColor Red
  exit 1
}

Write-Host "--- Ejecutando pruebas contra $base ---" -ForegroundColor Cyan

# 1) HEALTH
try {
  $health = Invoke-RestMethod "$api/health" -Method GET
} catch {
  Fail "No responde /api/v1/health. ¿Está levantado el backend? Error: $($_.Exception.Message)"
}
if ($health.status -ne "healthy") {
  Fail "Health.status != healthy. Recibido: $($health.status)"
}
Write-Host "[PASS] Health inicial" -ForegroundColor Green

# 2) OPENAPI contiene snapshot
try {
  $openapi = Invoke-RestMethod "$base/openapi.json" -Method GET
} catch {
  Fail "No responde /openapi.json. Error: $($_.Exception.Message)"
}
$path = "/api/v1/snapshot/{bot_id}"
if (-not ($openapi.paths.PSObject.Properties.Name -contains $path)) {
  Fail "OpenAPI no contiene '$path'"
}
Write-Host "[PASS] OpenAPI incluye snapshot" -ForegroundColor Green

# 3) POST Snapshot (payload completo)
$payloadObj = @{
  botId    = $bot
  ts       = (Get-Date).ToUniversalTime().ToString("o")
  position = @{ symbol="MNQ"; qty=10; avgPrice=21500.5 }
  orders   = @(@{ orderId="ORD1"; symbol="MNQ"; action="BUY"; qty=1; price=21495; state="WORKING" })
  fills    = @()
}
$payload = $payloadObj | ConvertTo-Json -Depth 10

try {
  $res = Invoke-RestMethod "$api/snapshot/$bot" -Method POST -ContentType "application/json" -Body $payload
} catch {
  Fail "POST snapshot falló. Error: $($_.Exception.Message)"
}
if (-not $res.ok) {
  Fail "POST snapshot no devolvió ok=true. Resp: $($res | ConvertTo-Json -Depth 10)"
}
Write-Host "[PASS] POST snapshot" -ForegroundColor Green

# 4) HEALTH refleja snapshot
Start-Sleep -Seconds 2
$health2 = Invoke-RestMethod "$api/health" -Method GET

$age = $health2.lastSnapshotAgeSec.$bot
if ($null -eq $age -or $age -lt 0) {
  Fail "lastSnapshotAgeSec['$bot'] no existe o es inválido. Resp: $($health2 | ConvertTo-Json -Depth 10)"
}

$pos = $health2.positionState.$bot
if ($null -eq $pos) {
  Fail "positionState['$bot'] no existe. Resp: $($health2 | ConvertTo-Json -Depth 10)"
}
if ($pos.symbol -ne "MNQ" -or [int]$pos.qty -ne 10) {
  Fail "positionState no coincide. Esperado MNQ qty=10. Recibido: $($pos | ConvertTo-Json -Depth 10)"
}

Write-Host "[PASS] Health actualizado (age=$age, qty=$($pos.qty))" -ForegroundColor Green
Write-Host "--- TODAS LAS PRUEBAS PASARON ---" -ForegroundColor Green
exit 0