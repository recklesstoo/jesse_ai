# =============================================================================
# start-frontend.ps1
# Arranque del frontend React (Windows PowerShell)
# =============================================================================

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Fail($msg, $code = 1) {
  Write-Host "[ERROR] $msg" -ForegroundColor Red
  exit $code
}

# --- Función para liberar puertos ---
function Free-Port($port) {
    Write-Host "Verificando puerto $port..." -ForegroundColor Gray
    $pids = netstat -ano | Select-String ":$port\s+.*LISTENING" | ForEach-Object {
        $tokens = $_.Line.Trim() -split '\s+'
        $tokens[-1]
    } | Select-Object -Unique

    if ($pids) {
        foreach ($pidVal in $pids) {
            if ($pidVal -match '^\d+$') {
                $proc = Get-Process -Id $pidVal -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Host "[WARN] Puerto $port ocupado por PID $($proc.Id) ($($proc.ProcessName)). Deteniendo..." -ForegroundColor Yellow
                    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                }
            }
        }
    } else {
        Write-Host "[INFO] Puerto $port está libre." -ForegroundColor Green
    }
}

Write-Host "[INFO] Root: $root" -ForegroundColor Cyan

# --- Verificar directorio frontend ---
$frontendDir = Join-Path $root "frontend"
if (-not (Test-Path $frontendDir)) {
  Fail "No existe el directorio '$frontendDir'." 10
}

# --- Verificar npm ---
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  Fail "npm no está instalado o no está en el PATH." 11
}

# --- Liberar puerto 3001 ---
Free-Port 3001

# --- Arrancar ---
Write-Host "[INFO] Iniciando frontend (npm run dev)..." -ForegroundColor Cyan
Set-Location $frontendDir
try {
    npm run dev -- --port 3001
    if ($LASTEXITCODE -ne 0) {
        throw "npm run dev exited with code $LASTEXITCODE"
    }
} catch {
    Write-Host "[ERROR] Frontend failed to start: $_" -ForegroundColor Red
    Write-Host "Press any key to exit..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}