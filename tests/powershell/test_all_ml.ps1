# =============================================================================
# test_all_ml.ps1
# Ejecuta secuencialmente todos los scripts de prueba ML para validación completa.
# =============================================================================

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Run-Test($scriptName, $cmd) {
    Write-Host "`n🚀 EJECUTANDO: $scriptName" -ForegroundColor Cyan
    Write-Host "----------------------------------------" -ForegroundColor Gray
    try {
        Invoke-Expression $cmd
        if ($LASTEXITCODE -ne 0) {
            throw "El script devolvió código de error $LASTEXITCODE"
        }
        Write-Host "✅ $scriptName PASÓ" -ForegroundColor Green
    } catch {
        Write-Host "❌ $scriptName FALLÓ" -ForegroundColor Red
        Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

Write-Host "🧪 INICIANDO SUITE DE PRUEBAS ML COMPLETA" -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta

# 1. Entrenamiento Básico
Run-Test "test_ml_train.ps1" ".\test_ml_train.ps1"

# 2. Métricas Detalladas
Run-Test "test_ml_metrics.ps1" ".\test_ml_metrics.ps1"

# 3. Importancia de Features
Run-Test "test_feature_importance.ps1" ".\test_feature_importance.ps1"

# 4. Descarga de Modelo
Run-Test "test_model_download.ps1" ".\test_model_download.ps1"

# 5. Subida de Modelo (Python)
if (Test-Path "test_model_upload.py") {
    Run-Test "test_model_upload.py" "python test_model_upload.py"
} else {
    Write-Host "⚠️ test_model_upload.py no encontrado, saltando..." -ForegroundColor Yellow
}

# 6. Restauración de Backup
Run-Test "test_restore.ps1" ".\test_restore.ps1"

# 7. Limpieza (Cleanup)
# Nota: test_cleanup.ps1 pide confirmación, le pasamos 'y' via pipe
Write-Host "`n🚀 EJECUTANDO: test_cleanup.ps1 (Auto-confirm)" -ForegroundColor Cyan
Write-Host "----------------------------------------" -ForegroundColor Gray
try {
    "y" | .\test_cleanup.ps1
    Write-Host "✅ test_cleanup.ps1 PASÓ" -ForegroundColor Green
} catch {
    Write-Host "❌ test_cleanup.ps1 FALLÓ" -ForegroundColor Red
    exit 1
}

Write-Host "`n🎉🎉🎉 TODAS LAS PRUEBAS ML COMPLETADAS EXITOSAMENTE 🎉🎉🎉" -ForegroundColor Green
Write-Host "El sistema ML está completamente operativo." -ForegroundColor Gray