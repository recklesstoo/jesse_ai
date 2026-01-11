# =============================================================================
# restart-all.ps1
# Reinicia el ecosistema completo (backend + frontend) de forma segura.
#
# USO:
#   .\restart-all.ps1
#
# LÓGICA:
#   1. Define los puertos para backend (8000) y frontend (3001).
#   2. Busca y detiene cualquier proceso que esté usando esos puertos.
#   3. Lanza 'start-backend.ps1' en una nueva ventana de terminal.
#   4. Lanza 'npm start' para el frontend en otra nueva ventana.
# =============================================================================

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# --- Configuración de Puertos ---
$backendPort = 8000
$frontendPort = 3001 # El puerto estándar de Vite/React es 3000 o 3001

# --- Función para liberar puertos ---
function Free-Port($port) {
    Write-Host "Verificando puerto $port..." -ForegroundColor Gray
    $proc = netstat -ano | Select-String ":$port\s+.*LISTENING" | ForEach-Object {
        # La salida de netstat puede tener espacios extra
        $tokens = $_.Line -split '\s+'
        $pid = $tokens[-1]
        if ($pid -match '^\d+$') {
            return Get-Process -Id $pid -ErrorAction SilentlyContinue
        }
    }

    if ($proc) {
        Write-Host "[WARN] Puerto $port está ocupado por PID $($proc.Id) ($($proc.ProcessName))." -ForegroundColor Yellow
        try {
            Stop-Process -Id $proc.Id -Force
            Write-Host "[OK] Proceso $($proc.Id) detenido." -ForegroundColor Green
        } catch {
            Write-Host "[ERROR] No se pudo detener el proceso PID $($proc.Id). Inténtalo manualmente." -ForegroundColor Red
            # No continuamos si no podemos liberar el puerto
            exit 1
        }
    } else {
        Write-Host "[INFO] Puerto $port está libre." -ForegroundColor Green
    }
}

# --- Liberar puertos ---
Write-Host "--- Liberando puertos ---" -ForegroundColor Cyan
Free-Port $backendPort
Free-Port $frontendPort

# --- Verificar scripts y directorios necesarios ---
$backendScript = Join-Path $root "start-backend.ps1"
$frontendDir = Join-Path $root "frontend"

if (-not (Test-Path $backendScript)) {
    Write-Host "[ERROR] No se encuentra '$backendScript'. Abortando." -ForegroundColor Red
    exit 10
}
if (-not (Test-Path $frontendDir)) {
    Write-Host "[ERROR] No se encuentra el directorio '$frontendDir'. Abortando." -ForegroundColor Red
    exit 11
}

# --- Iniciar Backend y Frontend en paralelo ---
Write-Host "--- Lanzando aplicaciones ---" -ForegroundColor Cyan

# Iniciar Backend
Write-Host "[INFO] Lanzando backend en una nueva terminal..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "& `"$backendScript`""

# Iniciar Frontend
Write-Host "[INFO] Lanzando frontend en una nueva terminal..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location `"$frontendDir`"; Write-Host 'Lanzando frontend (npm start)...'; npm start"

Write-Host "[SUCCESS] Scripts de arranque lanzados en nuevas terminales." -ForegroundColor Green