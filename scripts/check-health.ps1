# =============================================================================
# check-health.ps1
# Verifica la disponibilidad de los servicios Backend y Frontend.
# =============================================================================

$ErrorActionPreference = "SilentlyContinue"

$backendUrl = "http://localhost:8000/api/v1/health"
$frontendUrl = "http://localhost:3001"

Write-Host "`n🔍 INICIANDO TEST DE SALUD DEL SISTEMA" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan

# --- Backend Check ---
Write-Host "1. Backend API ($backendUrl)" -NoNewline
try {
    $beResponse = Invoke-RestMethod -Uri $backendUrl -Method Get -ErrorAction Stop
    if ($beResponse.ok -eq $true) {
        Write-Host "`t[✅ OK]" -ForegroundColor Green
        Write-Host "   Status: Healthy" -ForegroundColor Gray
        Write-Host "   Shadow Mode: $($beResponse.shadow_mode)" -ForegroundColor Gray
    } else {
        Write-Host "`t[⚠️ WARN]" -ForegroundColor Yellow
        Write-Host "   Respuesta recibida pero 'ok' no es true." -ForegroundColor Gray
    }
} catch {
    Write-Host "`t[❌ FAIL]" -ForegroundColor Red
    Write-Host "   Error: $($_.Exception.Message)" -ForegroundColor Gray
    Write-Host "   -> Asegúrate de haber ejecutado 'start-backend.ps1' o 'restart-all.ps1'" -ForegroundColor DarkGray
}

# --- Frontend Check ---
Write-Host "`n2. Frontend UI ($frontendUrl)" -NoNewline
try {
    $feResponse = Invoke-WebRequest -Uri $frontendUrl -Method Get -ErrorAction Stop
    if ($feResponse.StatusCode -eq 200) {
        Write-Host "`t[✅ OK]" -ForegroundColor Green
        Write-Host "   Status: 200 OK" -ForegroundColor Gray
    } else {
        Write-Host "`t[❌ FAIL]" -ForegroundColor Red
        Write-Host "   Status: $($feResponse.StatusCode)" -ForegroundColor Gray
    }
} catch {
    Write-Host "`t[❌ FAIL]" -ForegroundColor Red
    Write-Host "   Error: $($_.Exception.Message)" -ForegroundColor Gray
    Write-Host "   -> Asegúrate de que el frontend esté corriendo en el puerto 3001" -ForegroundColor DarkGray
}

Write-Host "`n======================================" -ForegroundColor Cyan