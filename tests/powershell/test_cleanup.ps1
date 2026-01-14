# =============================================================================
# test_cleanup.ps1
# Verifica el borrado de historial de entrenamiento.
# =============================================================================

$ErrorActionPreference = "Stop"
$BOT_ID = "bot-1"
$API_BASE = "http://localhost:8000/api/v1/ml"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "🧪 TESTING HISTORY CLEANUP" -ForegroundColor Cyan
Write-Host "==========================" -ForegroundColor Cyan

# 1. Generar historial (Entrenar rápido)
Write-Host "1. Generando historial (Entrenando)..." -NoNewline
try {
    $body = @{ botId = $BOT_ID; force = $true; n_estimators = 10; max_depth = 2 } | ConvertTo-Json
    $resTrain = Invoke-RestMethod -Uri "$API_BASE/train" -Method Post -Body $body -ContentType "application/json"
    if ($resTrain.trained) {
        Write-Host " [OK]" -ForegroundColor Green
    } else {
        Write-Host " [FAIL] $($resTrain.details.error)" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host " [FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# 2. Verificar que existe historial
Write-Host "2. Verificando historial existente..." -NoNewline
$hist = Invoke-RestMethod -Uri "$API_BASE/history/$BOT_ID" -Method Get
if ($hist.history.Count -gt 0) {
    Write-Host " [OK] ($($hist.history.Count) entradas)" -ForegroundColor Green
} else {
    Write-Host " [FAIL] Historial vacío tras entrenar." -ForegroundColor Red
    exit 1
}

# 3. Borrar historial
Write-Host "3. Borrando historial..." -NoNewline
try {
    $del = Invoke-RestMethod -Uri "$API_BASE/history/$BOT_ID" -Method Delete
    if ($del.ok) {
        Write-Host " [OK]" -ForegroundColor Green
    } else {
        Write-Host " [FAIL] Respuesta no OK" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host " [FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# 4. Verificar que está vacío
Write-Host "4. Verificando que está vacío..." -NoNewline
$histFinal = Invoke-RestMethod -Uri "$API_BASE/history/$BOT_ID" -Method Get
if ($histFinal.history.Count -eq 0) {
    Write-Host " [OK] Historial limpio." -ForegroundColor Green
} else {
    Write-Host " [FAIL] Aún hay $($histFinal.history.Count) entradas." -ForegroundColor Red
    exit 1
}

Write-Host "`n✅ PRUEBA DE LIMPIEZA COMPLETADA" -ForegroundColor Cyan