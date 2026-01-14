# =============================================================================
# test_full_ml_cycle.ps1
# Valida el ciclo de vida completo del modelo ML:
# 1. Entrenar (Train)
# 2. Descargar (Download)
# 3. Subir (Upload)
# 4. Restaurar (Restore)
# =============================================================================

$ErrorActionPreference = "Stop"

# Asegurar que estamos en la raíz del proyecto
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$API_BASE = "http://localhost:8000/api/v1/ml"
$BOT_ID = "bot-1"
$TEMP_FILE = "temp_cycle_model.joblib"
$BACKUP_FOLDER = "models_TEST_CYCLE"

Write-Host "🔄 INICIANDO TEST DE CICLO COMPLETO ML" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan

# --- PASO 1: ENTRENAMIENTO ---
Write-Host "`n1. [TRAIN] Solicitando entrenamiento..." -NoNewline
try {
    $body = @{ botId = $BOT_ID; force = $true; n_estimators = 50; max_depth = 3 } | ConvertTo-Json
    $resTrain = Invoke-RestMethod -Uri "$API_BASE/train" -Method Post -Body $body -ContentType "application/json"
    
    if ($resTrain.trained) {
        Write-Host " ✅ OK (Acc: $($resTrain.details.accuracy))" -ForegroundColor Green
    } else {
        Write-Host " ❌ FAIL" -ForegroundColor Red
        Write-Host "   Error: $($resTrain.details.error)" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host " ❌ FAIL ($($_.Exception.Message))" -ForegroundColor Red
    exit 1
}

# --- PASO 2: DESCARGA ---
Write-Host "2. [DOWNLOAD] Descargando modelo..." -NoNewline
if (Test-Path $TEMP_FILE) { Remove-Item $TEMP_FILE }
try {
    Invoke-WebRequest -Uri "$API_BASE/model/$BOT_ID" -OutFile $TEMP_FILE
    if (Test-Path $TEMP_FILE) {
        $size = (Get-Item $TEMP_FILE).Length
        Write-Host " ✅ OK ($size bytes)" -ForegroundColor Green
    } else {
        throw "Archivo no encontrado tras descarga"
    }
} catch {
    Write-Host " ❌ FAIL ($($_.Exception.Message))" -ForegroundColor Red
    exit 1
}

# --- PASO 3: SUBIDA (UPLOAD) ---
Write-Host "3. [UPLOAD] Subiendo modelo descargado..." -NoNewline
try {
    # PowerShell 5.1 nativo no tiene multipart fácil, usamos .NET
    Add-Type -AssemblyName System.Net.Http
    $client = New-Object System.Net.Http.HttpClient
    $content = New-Object System.Net.Http.MultipartFormDataContent
    
    $fileStream = [System.IO.File]::OpenRead((Resolve-Path $TEMP_FILE).Path)
    $fileContent = New-Object System.Net.Http.StreamContent($fileStream)
    $header = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("application/octet-stream")
    $fileContent.Headers.ContentType = $header
    
    $content.Add($fileContent, "file", "$BOT_ID.joblib")
    
    $task = $client.PostAsync("$API_BASE/upload/$BOT_ID", $content)
    $task.Wait()
    $response = $task.Result
    
    $fileStream.Close()
    $client.Dispose()

    if ($response.IsSuccessStatusCode) {
        Write-Host " ✅ OK" -ForegroundColor Green
    } else {
        Write-Host " ❌ FAIL (Status: $($response.StatusCode))" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host " ❌ FAIL ($($_.Exception.Message))" -ForegroundColor Red
    exit 1
}

# --- PASO 4: RESTAURACIÓN (RESTORE) ---
Write-Host "4. [RESTORE] Simulando backup y restaurando..." -NoNewline
try {
    # Preparar entorno de backup simulado
    $backupDir = Join-Path $root "backups\$BACKUP_FOLDER"
    if (-not (Test-Path $backupDir)) { New-Item -ItemType Directory -Force -Path $backupDir | Out-Null }
    Copy-Item $TEMP_FILE (Join-Path $backupDir "$BOT_ID.joblib") -Force

    # Llamar API restore
    $bodyRestore = @{ botId = $BOT_ID; folder = $BACKUP_FOLDER; filename = "$BOT_ID.joblib" } | ConvertTo-Json
    $resRestore = Invoke-RestMethod -Uri "$API_BASE/restore" -Method Post -Body $bodyRestore -ContentType "application/json"

    if ($resRestore.ok) {
        Write-Host " ✅ OK" -ForegroundColor Green
    } else {
        Write-Host " ❌ FAIL ($($resRestore.error))" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host " ❌ FAIL ($($_.Exception.Message))" -ForegroundColor Red
    exit 1
} finally {
    # Limpieza de backup simulado
    if (Test-Path $backupDir) { Remove-Item -Recurse -Force $backupDir }
}

# --- LIMPIEZA FINAL ---
if (Test-Path $TEMP_FILE) { Remove-Item $TEMP_FILE }

Write-Host "`n🎉 CICLO COMPLETO VALIDADO EXITOSAMENTE" -ForegroundColor Cyan