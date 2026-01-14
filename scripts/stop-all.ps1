# =============================================================================
# stop-all.ps1
# Detiene los procesos de backend y frontend liberando sus puertos.
# =============================================================================

$ErrorActionPreference = "SilentlyContinue"

# --- Configuración de Puertos ---
$backendPort = 8000
$frontendPort = 3001

function Free-Port($port, $name) {
    Write-Host "Verificando $name (Puerto $port)..." -NoNewline

    # Obtener líneas con el puerto escuchando
    $lines = netstat -ano | Select-String ":$port\s+.*LISTENING"
    $processIds = @()

    if ($lines) {
        foreach ($line in $lines) {
            $tokens = $line.Line.Trim() -split '\s+'
            $processId = $tokens[-1]
            if ($processId -match '^\d+$') {
                $processIds += $processId
            }
        }
        $processIds = $processIds | Select-Object -Unique
    }

    if ($processIds.Count -gt 0) {
        Write-Host " ACTIVO" -ForegroundColor Yellow
        foreach ($id in $processIds) {
            if ($id -match '^\d+$') {
                try {
                    $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
                    $procName = if ($proc) { $proc.ProcessName } else { "Unknown" }

                    Stop-Process -Id $id -Force -ErrorAction Stop
                    Write-Host "   -> [OK] Detenido PID $id ($procName)" -ForegroundColor Green
                } catch {
                    Write-Host "   -> [ERROR] No se pudo detener PID $id" -ForegroundColor Red
                }
            }
        }
    } else {
        Write-Host " INACTIVO" -ForegroundColor Gray
    }
}

Write-Host "`n🛑 DETENIENDO SERVICIOS JESSE AI" -ForegroundColor Cyan
Write-Host "=================================" -ForegroundColor Cyan

Free-Port $backendPort "Backend API"
Free-Port $frontendPort "Frontend UI"

Write-Host "`n✅ Procesos detenidos." -ForegroundColor Green