# =============================================================================
# start-backend.ps1
# Arranque canónico del backend FastAPI (Windows PowerShell)
# =============================================================================

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Fail($msg, $code = 1) {
  Write-Host "[ERROR] $msg" -ForegroundColor Red
  exit $code
}

Write-Host "[INFO] Root: $root" -ForegroundColor Cyan

# --- Verificar venv ---
$venvActivate = Join-Path $root ".venv\Scripts\Activate.ps1"
if (-not (Test-Path $venvActivate)) {
  Fail "No existe $venvActivate. Activa/crea el venv antes." 10
}

# --- Verificar backend/app.py ---
$appPath = Join-Path $root "backend\app.py"
if (-not (Test-Path $appPath)) {
  Fail "No existe $appPath. El entrypoint requerido falta." 11
}

# --- Activar venv ---
Write-Host "[INFO] Activando venv..." -ForegroundColor Yellow
. $venvActivate

# --- Verificar uvicorn en venv ---
$uv = Get-Command uvicorn -ErrorAction SilentlyContinue
if (-not $uv) {
  Fail "uvicorn no está disponible en el venv. Ejecuta: pip install uvicorn fastapi" 12
}
Write-Host "[OK] uvicorn: $($uv.Source)" -ForegroundColor Green

# --- Verificar puerto 8000 libre (SIN matar PID fijo) ---
$port = 8000
$inUse = netstat -ano | Select-String ":$port\s+.*LISTENING"
if ($inUse) {
  Write-Host "[ERROR] Puerto $port está ocupado:" -ForegroundColor Red
  $inUse | ForEach-Object { "  " + $_.Line } | Write-Host
  Write-Host "Sugerencia (elige una):" -ForegroundColor Yellow
  Write-Host "  1) Identificar PID y proceso:" -ForegroundColor Yellow
  Write-Host "     netstat -ano | findstr :$port" -ForegroundColor Yellow
  Write-Host "     tasklist /FI `"PID eq <PID>`"" -ForegroundColor Yellow
  Write-Host "  2) Parar con PowerShell (reemplaza PID):" -ForegroundColor Yellow
  Write-Host "     Stop-Process -Id <PID> -Force" -ForegroundColor Yellow
  exit 20
}

# --- Arranque canónico ---
Write-Host "[INFO] Iniciando backend en http://localhost:$port" -ForegroundColor Cyan
Write-Host "[INFO] Ctrl+C para detener" -ForegroundColor Cyan
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
