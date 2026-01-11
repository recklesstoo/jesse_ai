# arranque.ps1 (simple)
# Ejecutar desde D:\jesse_ai con:  .\arranque.ps1

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$BackendPort  = 8000
$FrontendPort = 5173

function Kill-Port($port) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conns) {
        $pids = $conns.OwningProcess | Sort-Object -Unique
        foreach ($pid in $pids) {
            try {
                Write-Host "Killing PID $pid on port $port"
                Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            } catch {}
        }
        Start-Sleep -Milliseconds 300
    } else {
        Write-Host "Port $port is free"
    }
}

# 1) Reiniciar puertos
Kill-Port $BackendPort
Kill-Port $FrontendPort

# 2) Virtual env
$VenvPy = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Host "No .venv found. Creating..."
    python -m venv .venv
}

# 3) Backend dependencies (mínimo: si falta uvicorn/fastapi)
$VenvPip = Join-Path $ProjectRoot ".venv\Scripts\pip.exe"
& $VenvPip install -q -r (Join-Path $ProjectRoot "requirements.txt") 2>$null

# 4) Arrancar backend en ventana nueva
$BackendCmd = @"
Set-Location '$ProjectRoot'
& '$VenvPy' -m uvicorn backend.app:app --host 127.0.0.1 --port $BackendPort --reload
"@
Start-Process powershell -ArgumentList "-NoExit", "-Command", $BackendCmd | Out-Null
Write-Host "Backend started: http://127.0.0.1:$BackendPort"

# 5) Arrancar frontend (asume carpeta frontend\ y npm instalado)
$FrontendDir = Join-Path $ProjectRoot "frontend"
if (Test-Path $FrontendDir) {
    $FrontendCmd = @"
Set-Location '$FrontendDir'
npm install
npm run dev -- --host 127.0.0.1 --port $FrontendPort
"@
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $FrontendCmd | Out-Null
    Write-Host "Frontend started: http://127.0.0.1:$FrontendPort"
} else {
    Write-Host "No frontend folder found at: $FrontendDir (skipping frontend)"
}

Write-Host "Done."
