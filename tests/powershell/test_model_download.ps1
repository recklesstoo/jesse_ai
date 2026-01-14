# =============================================================================
# test_model_download.ps1
# Verifica la descarga del modelo .joblib
# =============================================================================

$ErrorActionPreference = "Stop"
$BOT_ID = "bot-1"
$API_URL = "http://localhost:8000/api/v1/ml/model/$BOT_ID"
$OUTPUT_FILE = "$BOT_ID-downloaded.joblib"

Write-Host "🧪 TESTING MODEL DOWNLOAD" -ForegroundColor Cyan
Write-Host "========================" -ForegroundColor Cyan

if (Test-Path $OUTPUT_FILE) {
    Remove-Item $OUTPUT_FILE
}

try {
    Write-Host "Descargando modelo desde $API_URL..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri $API_URL -OutFile $OUTPUT_FILE
    
    if (Test-Path $OUTPUT_FILE) {
        $size = (Get-Item $OUTPUT_FILE).Length
        Write-Host "✅ Archivo descargado exitosamente." -ForegroundColor Green
        Write-Host "   Nombre: $OUTPUT_FILE" -ForegroundColor Gray
        Write-Host "   Tamaño: $size bytes" -ForegroundColor Gray
    } else {
        Write-Host "❌ El archivo no se guardó." -ForegroundColor Red
    }
} catch {
    Write-Host "❌ Error en la descarga: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "   (Asegúrate de haber entrenado el modelo primero)" -ForegroundColor DarkGray
}