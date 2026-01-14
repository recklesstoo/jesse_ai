# =============================================================================
# monitor_resources.ps1
# Registra el uso de CPU y RAM de los procesos del backend y frontend.
# =============================================================================

$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LOG_FILE = Join-Path $root "resource_usage.csv"

# Escribir cabecera si el archivo no existe
if (-not (Test-Path $LOG_FILE)) {
    "Timestamp,Component,ProcessName,Id,WorkingSet_MB,CPU_Seconds" | Out-File -FilePath $LOG_FILE -Encoding utf8
}

Write-Host "📊 MONITOR DE RECURSOS (Backend/Frontend)" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Guardando datos en: $LOG_FILE" -ForegroundColor Gray
Write-Host "Presiona Ctrl+C para detener.`n" -ForegroundColor Yellow

while ($true) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    
    # Identificar procesos
    # Backend: python.exe o uvicorn.exe
    $beProcs = Get-Process | Where-Object { $_.ProcessName -match "python|uvicorn" }
    
    # Frontend: node.exe
    $feProcs = Get-Process | Where-Object { $_.ProcessName -eq "node" }

    $totalBeRam = 0
    $totalFeRam = 0
    $foundAny = $false

    # Registrar Backend
    if ($beProcs) {
        $foundAny = $true
        foreach ($p in $beProcs) {
            $ram = [math]::Round($p.WorkingSet / 1MB, 2)
            $cpu = [math]::Round($p.CPU, 2)
            $totalBeRam += $ram
            
            "$ts,Backend,$($p.ProcessName),$($p.Id),$ram,$cpu" | Out-File -FilePath $LOG_FILE -Append -Encoding utf8
        }
    }

    # Registrar Frontend
    if ($feProcs) {
        $foundAny = $true
        foreach ($p in $feProcs) {
            $ram = [math]::Round($p.WorkingSet / 1MB, 2)
            $cpu = [math]::Round($p.CPU, 2)
            $totalFeRam += $ram
            
            "$ts,Frontend,$($p.ProcessName),$($p.Id),$ram,$cpu" | Out-File -FilePath $LOG_FILE -Append -Encoding utf8
        }
    }

    # Mostrar resumen en consola
    if ($foundAny) {
        Write-Host -NoNewline "`r[$ts] Backend RAM: $([math]::Round($totalBeRam, 0)) MB | Frontend RAM: $([math]::Round($totalFeRam, 0)) MB    "
    } else {
        Write-Host -NoNewline "`r[$ts] Esperando procesos...                                      "
    }
    
    Start-Sleep -Seconds 2
}