# =============================================================================
# backup_models.ps1
# Descarga modelos ML (.joblib) de todos los bots activos.
# =============================================================================

$ErrorActionPreference = "Stop"
$API_BASE = "http://localhost:8000"
$TIMESTAMP = Get-Date -Format "yyyyMMdd_HHmmss"
$ROOT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$BACKUP_DIR = Join-Path $ROOT_DIR "backups\models_$TIMESTAMP"

Write-Host "📦 INICIANDO BACKUP DE MODELOS ML" -ForegroundColor Cyan
Write-Host "=================================" -ForegroundColor Cyan

# 1. Crear directorio
if (-not (Test-Path $BACKUP_DIR)) {
    New-Item -ItemType Directory -Force -Path $BACKUP_DIR | Out-Null
}
Write-Host "📂 Directorio: $BACKUP_DIR" -ForegroundColor Gray

# 2. Obtener lista de bots activos desde /health
Write-Host "🔍 Buscando bots activos..." -NoNewline
try {
    $health = Invoke-RestMethod -Uri "$API_BASE/api/v1/health" -Method Get
    # lastSnapshotAgeSec contiene las keys de los bots
    if ($health.lastSnapshotAgeSec) {
        $bots = $health.lastSnapshotAgeSec.PSObject.Properties.Name
    } else {
        $bots = @()
    }
    
    # Si no hay bots en memoria, intentamos al menos bot-1 por defecto
    if ($bots.Count -eq 0) {
        $bots = @("bot-1")
        Write-Host " [WARN] No detectados en memoria. Probando 'bot-1'." -ForegroundColor Yellow
    } else {
        Write-Host " [OK] Encontrados: $($bots -join ', ')" -ForegroundColor Green
    }
} catch {
    Write-Host " [FAIL]" -ForegroundColor Red
    Write-Host "❌ Error conectando al backend: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# 3. Descargar modelos
foreach ($botId in $bots) {
    $url = "$API_BASE/api/v1/ml/model/$botId"
    $outFile = Join-Path $BACKUP_DIR "$botId.joblib"
    
    Write-Host "⬇ Descargando $botId..." -NoNewline
    
    try {
        # Usamos Invoke-WebRequest para guardar el archivo
        $response = Invoke-WebRequest -Uri $url -OutFile $outFile -PassThru
        
        # Si el contenido es JSON, probablemente es un error {"error": "Model not found"}
        if ($response.Headers["Content-Type"] -match "application/json") {
            Write-Host " [SKIP] Modelo no encontrado." -ForegroundColor DarkGray
            Remove-Item $outFile
        } else {
            $size = (Get-Item $outFile).Length
            Write-Host " [OK] Guardado ($size bytes)" -ForegroundColor Green
        }
    } catch {
        Write-Host " [FAIL] $($_.Exception.Message)" -ForegroundColor Red
        if (Test-Path $outFile) { Remove-Item $outFile }
    }
}

Write-Host "`n✅ Proceso finalizado." -ForegroundColor Cyan