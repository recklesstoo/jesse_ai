# =============================================================================
# test_confusion_limit.ps1
# Verifica que el parámetro 'limit' afecta el cálculo de la matriz promediada.
# =============================================================================

$ErrorActionPreference = "Stop"
$BOT_ID = "bot-1"
$API_BASE = "http://localhost:8000/api/v1/ml"

Write-Host "🧪 TESTING CONFUSION MATRIX LIMIT" -ForegroundColor Cyan
Write-Host "=================================" -ForegroundColor Cyan

# 1. Generar historial diverso (2 entrenamientos)
Write-Host "1. Generando historial (Entrenando 2 veces)..." -NoNewline
try {
    # Entrenamiento A
    $bodyA = @{ botId = $BOT_ID; force = $true; n_estimators = 10; max_depth = 2 } | ConvertTo-Json
    Invoke-RestMethod -Uri "$API_BASE/train" -Method Post -Body $bodyA -ContentType "application/json" | Out-Null
    
    # Entrenamiento B (diferente para intentar variar la matriz)
    $bodyB = @{ botId = $BOT_ID; force = $true; n_estimators = 50; max_depth = 5 } | ConvertTo-Json
    Invoke-RestMethod -Uri "$API_BASE/train" -Method Post -Body $bodyB -ContentType "application/json" | Out-Null
    
    Write-Host " [OK]" -ForegroundColor Green
} catch {
    Write-Host " [FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# 2. Consultar con limit=1 (Último)
Write-Host "2. Consultando matriz (limit=1)..." -NoNewline
$res1 = Invoke-RestMethod -Uri "$API_BASE/confusion-matrix/$BOT_ID?limit=1" -Method Get
if ($res1.confusion_matrix) {
    Write-Host " [OK]" -ForegroundColor Green
    # Guardar valor de una celda para comparar (ej: TP en [1][1])
    $val1 = $res1.confusion_matrix[1][1]
} else {
    Write-Host " [FAIL] Respuesta vacía." -ForegroundColor Red
    exit 1
}

# 3. Consultar sin límite (Promedio total)
Write-Host "3. Consultando matriz (limit=null)..." -NoNewline
$resAll = Invoke-RestMethod -Uri "$API_BASE/confusion-matrix/$BOT_ID" -Method Get
if ($resAll.confusion_matrix) {
    Write-Host " [OK]" -ForegroundColor Green
    $valAll = $resAll.confusion_matrix[1][1]
} else {
    Write-Host " [FAIL] Respuesta vacía." -ForegroundColor Red
    exit 1
}

# 4. Comparación (Informativa)
Write-Host "`nComparación de valores (TP):" -ForegroundColor Gray
Write-Host "  Limit=1: $val1" -ForegroundColor Yellow
Write-Host "  Average: $valAll" -ForegroundColor Yellow

if ($val1 -ne $valAll) {
    Write-Host "✅ Las matrices son diferentes, el límite afectó el cálculo." -ForegroundColor Green
} else {
    Write-Host "⚠️ Las matrices son idénticas. (Posible si el modelo es muy estable o determinista)" -ForegroundColor Yellow
}

Write-Host "`n✅ PRUEBA DE LÍMITE COMPLETADA" -ForegroundColor Cyan