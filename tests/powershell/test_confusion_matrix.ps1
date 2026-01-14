# =============================================================================
# test_confusion_matrix.ps1
# Verifica el endpoint de matriz de confusión histórica promediada.
# =============================================================================

$ErrorActionPreference = "Stop"
$BOT_ID = "bot-1"
$API_BASE = "http://localhost:8000/api/v1/ml"

Write-Host "🧪 TESTING CONFUSION MATRIX ENDPOINT" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan

# 1. Asegurar que hay datos recientes con matriz (Entrenar)
Write-Host "1. Entrenando modelo para generar historial..." -NoNewline
try {
    $body = @{ botId = $BOT_ID; force = $true; n_estimators = 10 } | ConvertTo-Json
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

# 2. Consultar Matriz Promediada
Write-Host "2. Consultando matriz promediada..." -NoNewline
try {
    $res = Invoke-RestMethod -Uri "$API_BASE/confusion-matrix/$BOT_ID" -Method Get
    
    if ($res.confusion_matrix) {
        Write-Host " [OK]" -ForegroundColor Green
        Write-Host "`nMatriz Recibida:" -ForegroundColor Gray
        $cm = $res.confusion_matrix
        
        # Mostrar formato simple
        foreach ($row in $cm) {
            Write-Host "  [ $($row -join ', ') ]" -ForegroundColor Yellow
        }
        Write-Host "`n(Valores promediados de todo el historial disponible)" -ForegroundColor DarkGray
    } else {
        Write-Host " [WARN] Respuesta vacía (null). Puede que el historial antiguo no tenga matrices guardadas." -ForegroundColor Yellow
    }
} catch {
    Write-Host " [FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "`n✅ PRUEBA COMPLETADA" -ForegroundColor Cyan