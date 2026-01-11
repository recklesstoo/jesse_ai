# resstart.ps1 - one file: free ports and start backend + frontend
$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
Set-Location $root

$backendPort  = 8000
$frontendPort = 3001
$backendBind  = "127.0.0.1"
$backendApp   = "backend.app:app"

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$venvPip    = Join-Path $root ".venv\Scripts\pip.exe"

function Step($msg) { Write-Host ""; Write-Host ("==> " + $msg) -ForegroundColor Cyan }

function Get-PidsOnPort([int]$port) {
    $pids = @()
    try {
        $pids = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty OwningProcess -Unique
        if ($pids) { return $pids }
    } catch {}

    $lines = netstat -ano | Select-String (":$port\s+.*LISTENING")
    foreach ($m in $lines) {
        $tokens = ($m.Line -split '\s+')
        $procId = $tokens[-1]
        if ($procId -match '^\d+$') { $pids += [int]$procId }
    }
    return ($pids | Sort-Object -Unique)
}

function Free-Port([int]$port) {
    $pids = Get-PidsOnPort $port
    if (-not $pids -or $pids.Count -eq 0) {
        Write-Host ("[OK] Port " + $port + " is free.") -ForegroundColor Green
        return
    }

    foreach ($procId in $pids) {
        $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($p) {
            Write-Host ("[WARN] Port " + $port + " used by PID " + $procId + " (" + $p.ProcessName + "). Killing...") -ForegroundColor Yellow
        } else {
            Write-Host ("[WARN] Port " + $port + " used by PID " + $procId + ". Killing...") -ForegroundColor Yellow
        }
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }

    Start-Sleep -Milliseconds 400

    $left = Get-PidsOnPort $port
    if ($left -and $left.Count -gt 0) {
        throw ("Could not free port " + $port + ". PIDs still alive: " + ($left -join ", "))
    }
    Write-Host ("[OK] Port " + $port + " freed.") -ForegroundColor Green
}

function Ensure-Venv() {
    if (Test-Path $venvPython) {
        Write-Host "[OK] .venv exists." -ForegroundColor Green
        return
    }
    Step "Creating .venv"
    python -m venv .venv
    if (-not (Test-Path $venvPython)) { throw "Failed to create .venv" }
}

function Install-ReqIfExists([string]$reqPath) {
    if (Test-Path $reqPath) {
        Write-Host ("[INFO] Installing deps: " + $reqPath) -ForegroundColor Gray
        & $venvPip install -r $reqPath
    } else {
        Write-Host ("[INFO] No requirements at: " + $reqPath) -ForegroundColor DarkGray
    }
}

function Start-Backend() {
    Step "Starting backend"
    $cmd = "& `"$venvPython`" -m uvicorn $backendApp --host $backendBind --port $backendPort --reload"
    Start-Process powershell -ArgumentList "-NoExit","-Command","Set-Location `"$root`"; $cmd"
}

function Start-Frontend() {
    $frontendDir = Join-Path $root "frontend"
    if (-not (Test-Path $frontendDir)) {
        Write-Host "[WARN] frontend/ not found. Skipping frontend." -ForegroundColor Yellow
        return
    }
    Step "Starting frontend"
    Start-Process powershell -ArgumentList "-NoExit","-Command","Set-Location `"$frontendDir`"; npm start"
}

function Wait-Http([string]$url, [int]$seconds = 15) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $url
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { return $true }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    return $false
}

# ---------------- RUN ----------------
Step "Preparing environment"
Ensure-Venv
Install-ReqIfExists (Join-Path $root "requirements.txt")
Install-ReqIfExists (Join-Path $root "backend\requirements.txt")

Step "Freeing ports"
Free-Port $backendPort
Free-Port $frontendPort

Start-Backend
Start-Frontend

Step "Quick checks"
$backendOk = Wait-Http ("http://" + $backendBind + ":" + $backendPort + "/api/v1/health") 20
if ($backendOk) {
    Write-Host ("[OK] Backend up: http://" + $backendBind + ":" + $backendPort) -ForegroundColor Green
} else {
    Write-Host "[WARN] Backend not responding yet. Check backend console for import errors." -ForegroundColor Yellow
}

$frontendOk = Wait-Http ("http://localhost:" + $frontendPort) 20
if ($frontendOk) {
    Write-Host ("[OK] Frontend up: http://localhost:" + $frontendPort) -ForegroundColor Green
} else {
    Write-Host "[WARN] Frontend not responding yet. Check frontend console." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done. If something fails, the error will show in the backend/frontend terminals." -ForegroundColor Cyan
