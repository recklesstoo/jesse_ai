# =============================================================================
# test_restore.ps1
# Verifica el endpoint de restauración de modelos ML (/api/v1/ml/restore)
# =============================================================================

$ErrorActionPreference = "Stop"
$API_URL = "http://localhost:8000/api/v1/ml/restore"
$BOT_ID = "bot-1"
$ROOT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$BACKUPS_DIR = Join-Path $ROOT_DIR "backups"
$TEST_FOLDER = "models_TEST_RESTORE"
$TEST_FILE = "$BOT_ID.joblib"
$FULL_TEST_DIR = Join-Path $BACKUPS_DIR $TEST_FOLDER
$FULL_TEST_FILE = Join-Path $FULL_TEST_DIR $TEST_FILE

Write-Host "🧪 TESTING ML RESTORE ENDPOINT" -ForegroundColor Cyan
Write-Host "==============================" -ForegroundColor Cyan

# 1. Crear backup simulado
Write-Host "1. Creando backup simulado en $FULL_TEST_DIR..." -NoNewline
try {
    if (-not (Test-Path $BACKUPS_DIR)) {
        New-Item -ItemType Directory -Force -Path $BACKUPS_DIR | Out-Null
    }
    if (-not (Test-Path $FULL_TEST_DIR)) {
        New-Item -ItemType Directory -Force -Path $FULL_TEST_DIR | Out-Null
    }
    # Crear un archivo dummy
    "DUMMY_MODEL_CONTENT_FOR_RESTORE_TEST" | Set-Content -Path $FULL_TEST_FILE
    Write-Host " [OK]" -ForegroundColor Green
} catch {
    Write-Host " [FAIL]" -ForegroundColor Red
    Write-Host "Error creando archivo de prueba: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# 2. Enviar solicitud de restauración
$body = @{
    botId = $BOT_ID
    folder = $TEST_FOLDER
    filename = $TEST_FILE
} | ConvertTo-Json

Write-Host "2. Enviando solicitud de restauración..." -ForegroundColor Yellow
Write-Host "Payload: $body" -ForegroundColor Gray

try {
    $response = Invoke-RestMethod -Uri $API_URL -Method Post -Body $body -ContentType "application/json"
    
    Write-Host "`nRespuesta recibida:" -ForegroundColor Green
    $response | ConvertTo-Json -Depth 5 | Write-Host

    if ($response.ok -eq $true) {
        Write-Host "`n✅ RESTAURACIÓN EXITOSA" -ForegroundColor Green
    } else {
        Write-Host "`n⚠️ RESTAURACIÓN FALLIDA" -ForegroundColor Yellow
        Write-Host "Error: $($response.error)" -ForegroundColor Gray
    }

} catch {
    Write-Host "`n❌ ERROR EN LA SOLICITUD" -ForegroundColor Red
    if ($_.Exception.Response) {
        Write-Host "Status Code: $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Red
    }
    Write-Host "Message: $($_.Exception.Message)" -ForegroundColor Red
} finally {
    # 3. Limpieza
    Write-Host "`n3. Limpiando archivos de prueba..." -NoNewline
    if (Test-Path $FULL_TEST_DIR) {
        Remove-Item -Recurse -Force $FULL_TEST_DIR
        Write-Host " [OK]" -ForegroundColor Green
    } else {
        Write-Host " [SKIP]" -ForegroundColor Gray
    }
}