# =============================================================================
# test_ml_stress.ps1
# Lanza 10 entrenamientos consecutivos para probar la estabilidad del backend.
# =============================================================================

$ErrorActionPreference = "Stop"
$BOT_ID = "bot-1"
$API_URL = "http://localhost:8000/api/v1/ml/train"
$ITERATIONS = 10

Write-Host "🔥 INICIANDO STRESS TEST ML ($ITERATIONS iteraciones)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

$body = @{
    botId = $BOT_ID
    force = $true
    n_estimators = 10 # Keep it light for speed
    max_depth = 3
} | ConvertTo-Json

$successCount = 0
$failCount = 0

for ($i = 1; $i -le $ITERATIONS; $i++) {
    Write-Host "`n[$i/$ITERATIONS] Iniciando entrenamiento..." -NoNewline
    $start = Get-Date

    try {
        $response = Invoke-RestMethod -Uri $API_URL -Method Post -Body $body -ContentType "application/json"
        $duration = ((Get-Date) - $start).TotalSeconds

        if ($response.trained) {
            Write-Host " [OK] (${duration}s)" -ForegroundColor Green
            $successCount++
        } else {
            Write-Host " [FAIL] No entrenado: $($response.details.error)" -ForegroundColor Red
            $failCount++
        }
    } catch {
        Write-Host " [ERROR] $($_.Exception.Message)" -ForegroundColor Red
        $failCount++
    }
    
    Start-Sleep -Milliseconds 200
}

Write-Host "`n==================================================" -ForegroundColor Cyan
Write-Host "RESULTADOS:" -ForegroundColor Gray
Write-Host "✅ Exitosos: $successCount" -ForegroundColor Green
Write-Host "❌ Fallidos: $failCount" -ForegroundColor Red

if ($failCount -eq 0) { Write-Host "`n✅ STRESS TEST PASADO" -ForegroundColor Green } 
else { Write-Host "`n⚠️ STRESS TEST CON ERRORES" -ForegroundColor Yellow }