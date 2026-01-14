# =============================================================================
# test_history_chart.ps1
# Verifica que el endpoint de historial devuelve datos válidos para el gráfico.
# =============================================================================

$ErrorActionPreference = "Stop"
$BOT_ID = "bot-1"
$API_URL = "http://localhost:8000/api/v1/ml/history/$BOT_ID"

Write-Host "🧪 TESTING HISTORY CHART DATA" -ForegroundColor Cyan
Write-Host "=============================" -ForegroundColor Cyan

try {
    Write-Host "Solicitando historial para $BOT_ID..." -ForegroundColor Yellow
    $response = Invoke-RestMethod -Uri $API_URL -Method Get

    if ($response.history) {
        $count = $response.history.Count
        Write-Host "✅ Historial recibido. Entradas: $count" -ForegroundColor Green
        
        if ($count -gt 0) {
            $last = $response.history[$count-1]
            
            # Validar campos requeridos para el gráfico (accuracy, f1)
            # Nota: PowerShell convierte JSON a PSCustomObject
            $props = $last.PSObject.Properties.Name
            
            $hasAccuracy = $props -contains "accuracy"
            $hasF1 = $props -contains "f1"
            
            if ($hasAccuracy -and $hasF1) {
                Write-Host "✅ Datos válidos para gráfico encontrados." -ForegroundColor Green
                Write-Host "   Última entrada:" -ForegroundColor Gray
                Write-Host "   - TS: $($last.ts)" -ForegroundColor Gray
                Write-Host "   - Accuracy: $($last.accuracy)" -ForegroundColor Gray
                Write-Host "   - F1-Score: $($last.f1)" -ForegroundColor Gray
            } else {
                Write-Host "❌ Faltan campos requeridos (accuracy, f1)." -ForegroundColor Red
                Write-Host "   Campos encontrados: $($props -join ', ')" -ForegroundColor Gray
                exit 1
            }
        } else {
            Write-Host "⚠️ El historial está vacío. Entrena el modelo para generar datos." -ForegroundColor Yellow
        }
    } else {
        Write-Host "❌ La respuesta no contiene 'history'." -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "❌ Error de conexión: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}