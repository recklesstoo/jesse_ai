# =============================================================================
# test_feature_importance.ps1
# Verifica que el endpoint de entrenamiento devuelva feature_importances (Feature Importance).
# =============================================================================

$ErrorActionPreference = "Stop"
$API_URL = "http://localhost:8000/api/v1/ml/train"
$BOT_ID = "bot-1"

Write-Host "🧪 TESTING FEATURE IMPORTANCE" -ForegroundColor Cyan
Write-Host "=============================" -ForegroundColor Cyan

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
        
        # Verificar Feature Importances
        if ($details.feature_importances) {
            Write-Host "✅ Feature Importances recibidas." -ForegroundColor Green
            
            $importances = $details.feature_importances
            # En PowerShell, un objeto JSON se convierte en PSCustomObject
            $props = $importances.PSObject.Properties
            $count = $props.Count
            
            if ($count -gt 0) {
                Write-Host "   Features encontradas ($count):" -ForegroundColor Gray
                # Mostrar las top 5
                $i = 0
                foreach ($prop in $props) {
                    if ($i -lt 5) {
                        # Formatear valor si es numérico
                        $val = $prop.Value
                        try { $val = "{0:P2}" -f [double]$val } catch { }
                        Write-Host "   - $($prop.Name): $val" -ForegroundColor Gray
                    }
                    $i++
                }
            } else {
                Write-Host "⚠️ El objeto feature_importances está vacío." -ForegroundColor Yellow
            }
        } else {
            Write-Host "❌ Falta feature_importances en la respuesta." -ForegroundColor Red
            exit 1
        }

    } else {
        Write-Host "⚠️ Entrenamiento falló: $($response.details.error)" -ForegroundColor Yellow
        exit 1
    }
} catch {
    Write-Host "❌ Error de conexión o ejecución: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}