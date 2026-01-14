# =============================================================================
# cleanup_history.ps1
# Borra el historial de entrenamiento de un bot específico.
# =============================================================================

$ErrorActionPreference = "Stop"
$BOT_ID = "bot-1"
$API_URL = "http://localhost:8000/api/v1/ml/history/$BOT_ID"

Write-Host "🧹 LIMPIEZA DE HISTORIAL ML" -ForegroundColor Cyan
Write-Host "===========================" -ForegroundColor Cyan

Write-Host "Bot ID: $BOT_ID" -ForegroundColor Gray
Write-Host "URL: $API_URL" -ForegroundColor Gray

Write-Host "`n¿Estás seguro de que quieres borrar el historial de entrenamiento? (y/n)" -ForegroundColor Yellow -NoNewline
$confirm = Read-Host " "

if ($confirm -ne "y") {
    Write-Host "Operación cancelada." -ForegroundColor Gray
    exit
}

try {
    Write-Host "Enviando solicitud de borrado..." -ForegroundColor Yellow
    $response = Invoke-RestMethod -Uri $API_URL -Method Delete
    
    Write-Host "✅ Historial borrado exitosamente." -ForegroundColor Green
    Write-Host "Respuesta: $($response | ConvertTo-Json -Compress)" -ForegroundColor Gray
} catch {
    Write-Host "❌ Error al borrar historial: $($_.Exception.Message)" -ForegroundColor Red
}