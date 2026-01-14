# =============================================================================
# test_ml_metrics.ps1
# Verifica que el endpoint de entrenamiento devuelva métricas detalladas.
# =============================================================================

$ErrorActionPreference = "Stop"
$API_URL = "http://localhost:8000/api/v1/ml/train"
$BOT_ID = "bot-1"

Write-Host "🧪 TESTING ML METRICS" -ForegroundColor Cyan
Write-Host "=====================" -ForegroundColor Cyan

$body = @{
    botId = $BOT_ID
    force = $true
} | ConvertTo-Json

try {
    Write-Host "Solicitando entrenamiento..." -ForegroundColor Yellow
    $response = Invoke-RestMethod -Uri $API_URL -Method Post -Body $body -ContentType "application/json"

    if ($response.trained) {
        Write-Host "✅ Entrenamiento completado." -ForegroundColor Green
        
        $details = $response.details
        
        # Verificar Confusion Matrix
        if ($details.confusion_matrix) {
            Write-Host "✅ Matriz de Confusión recibida." -ForegroundColor Green
            Write-Host ($details.confusion_matrix | ConvertTo-Json -Compress) -ForegroundColor Gray
        } else {
            Write-Host "❌ Falta Matriz de Confusión." -ForegroundColor Red
        }

        # Verificar Classification Report
        if ($details.classification_report) {
            Write-Host "✅ Reporte de Clasificación recibido." -ForegroundColor Green
            $f1 = $details.classification_report."weighted avg"."f1-score"
            Write-Host "   Weighted F1-Score: $f1" -ForegroundColor Gray
        } else {
            Write-Host "❌ Falta Reporte de Clasificación." -ForegroundColor Red
        }

    } else {
        Write-Host "⚠️ Entrenamiento falló: $($response.details.error)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "❌ Error de conexión: $($_.Exception.Message)" -ForegroundColor Red
}