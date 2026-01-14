# =============================================================================
# test_ml_train.ps1
# Verifica el endpoint de entrenamiento ML (/api/v1/ml/train)
# =============================================================================

$ErrorActionPreference = "Stop"
$API_URL = "http://localhost:8000/api/v1/ml/train"
$BOT_ID = "bot-1"

Write-Host "🧪 TESTING ML TRAINING ENDPOINT" -ForegroundColor Cyan
Write-Host "===============================" -ForegroundColor Cyan

# Payload para forzar entrenamiento (o intentar)
$body = @{
    botId = $BOT_ID
    force = $true
} | ConvertTo-Json

Write-Host "Enviando solicitud de entrenamiento para $BOT_ID..." -ForegroundColor Yellow
Write-Host "Payload: $body" -ForegroundColor Gray

try {
    $response = Invoke-RestMethod -Uri $API_URL -Method Post -Body $body -ContentType "application/json"
    
    Write-Host "`nRespuesta recibida:" -ForegroundColor Green
    $response | ConvertTo-Json -Depth 5 | Write-Host

    if ($response.trained -eq $true) {
        Write-Host "`n✅ ENTRENAMIENTO EXITOSO" -ForegroundColor Green
        Write-Host "Accuracy: $($response.details.accuracy)" -ForegroundColor Gray
        Write-Host "Model Path: $($response.details.model_path)" -ForegroundColor Gray
    } else {
        Write-Host "`n⚠️ ENTRENAMIENTO NO COMPLETADO (Esperado si faltan datos)" -ForegroundColor Yellow
        Write-Host "Razón: $($response.details.error)" -ForegroundColor Gray
        
        if ($response.details.error -match "Not enough data") {
            Write-Host "-> Necesitas más barras en la DB. Usa NinjaTrader o un script para insertar barras." -ForegroundColor DarkGray
        }
    }

} catch {
    Write-Host "`n❌ ERROR EN LA SOLICITUD" -ForegroundColor Red
    if ($_.Exception.Response) {
        Write-Host "Status Code: $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
    }
    Write-Host "Message: $($_.Exception.Message)" -ForegroundColor Red
    # Intenta leer el cuerpo del error si existe
}