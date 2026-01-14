param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3001,
    [int]$HealthRetries = 20,
    [int]$HealthDelayMs = 500,
    [int]$MonitorRestarts = 3,
    [int]$LogTailLines = 20,
    [int]$PortWaitDelayMs = 500,
    [int]$MaxPortWaitAttempts = 30
)

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
$ArranqueScript = Join-Path $ScriptRoot "arranque.ps1"
. (Join-Path $ScriptRoot "kill-port.ps1")

$LogsRoot = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogsRoot | Out-Null

$LatestMetaPath = Join-Path $LogsRoot "latest.json"

function Throw-DoctorError {
    param([string]$Message)
    Write-Error $Message
    exit 1
}

function Read-LatestMeta {
    if (-not (Test-Path $LatestMetaPath)) {
        return $null
    }
    try {
        return (Get-Content -Path $LatestMetaPath -Raw | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Stop-RecordedProcess {
    param(
        [string]$PidFile,
        [string]$Label
    )

    if (-not (Test-Path $PidFile)) {
        return
    }

    $content = Get-Content -Path $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $content) {
        return
    }

    $processId = 0
    if (-not [int]::TryParse($content, [ref]$processId)) {
        return
    }
    $target = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($target) {
        Write-Host "Stopping $Label process tree (PID $processId)..."
        Stop-ProcessTree -ProcessId $processId
    }
    Remove-Item -Path $PidFile -ErrorAction SilentlyContinue
}

function Stop-Services {
    Stop-RecordedProcess -PidFile (Join-Path $LogsRoot "backend_pid.txt") -Label "backend"
    Stop-RecordedProcess -PidFile (Join-Path $LogsRoot "frontend_pid.txt") -Label "frontend"
}

$GlobalPython = Get-Command python -ErrorAction SilentlyContinue
if (-not $GlobalPython) {
    Throw-DoctorError("System Python is not available in PATH.")
}

$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating .venv at $VenvDir..."
    & $GlobalPython.Source -m venv $VenvDir
}

if (-not (Test-Path $VenvPython)) {
    Throw-DoctorError("python executable not found at $VenvPython after venv creation.")
}

Write-Host "Using venv python at $VenvPython"
& $VenvPython --version | Out-Null
& $VenvPython -m pip --version | Out-Null

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Throw-DoctorError("Node runtime not found in PATH.")
}
& node --version | Out-Null

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Throw-DoctorError("npm not found in PATH.")
}
& npm --version | Out-Null

Write-Host "Installing Python dependencies..."
& $VenvPython -m pip install -r (Join-Path $RepoRoot "requirements.txt")

Write-Host "Validating Python packages..."
& $VenvPython -m pip check

Write-Host "Compiling backend modules..."
& $VenvPython -m compileall (Join-Path $RepoRoot "backend")

Write-Host "Installing frontend packages..."
Push-Location (Join-Path $RepoRoot "frontend")
try {
    & npm install
} finally {
    Pop-Location
}

$BackendPortName = "backend"
$FrontendPortName = "frontend"

function Wait-ForPortListening {
    param(
        [int]$Port,
        [int]$Attempts = $MaxPortWaitAttempts,
        [int]$DelayMs = $PortWaitDelayMs
    )

    for ($i = 1; $i -le $Attempts; $i++) {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($connection) {
            return $true
        }
        Start-Sleep -Milliseconds $DelayMs
    }
    return $false
}

function Invoke-HealthCheck {
    for ($i = 1; $i -le $HealthRetries; $i++) {
        try {
            $response = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/api/v1/health" -Method Get -TimeoutSec 5 -UseBasicParsing
            if ($response.ok -eq $true -or $response.status -eq "ok") {
                Write-Host "Health check succeeded on attempt $i."
                return $true
            }
            Write-Warning "Health endpoint returned unexpected payload on attempt $i."
        } catch {
            Write-Warning "Health attempt $i failed: $_"
        }
        Start-Sleep -Milliseconds $HealthDelayMs
    }
    return $false
}

function Invoke-WebSocket {
    $tempScript = Join-Path $env:TEMP "doctor_ws.py"
    $content = @"
import asyncio
import websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:$BackendPort/ws/test-bot"):
        pass

asyncio.run(main())
"@
    Set-Content -Path $tempScript -Value $content -Encoding UTF8
    try {
        & $VenvPython $tempScript
        Write-Host "WebSocket handshake succeeded."
        return $true
    } catch {
        Write-Warning "WebSocket handshake failed: $_"
        return $false
    } finally {
        Remove-Item -Path $tempScript -ErrorAction SilentlyContinue
    }
}

function Invoke-FrontendCheck {
    param([int]$Retries = 20, [int]$DelayMs = 500)

    for ($i = 1; $i -le $Retries; $i++) {
        try {
            $res = Invoke-WebRequest -Uri "http://127.0.0.1:$FrontendPort/" -TimeoutSec 5 -UseBasicParsing
            if ($res.StatusCode -eq 200 -and ($res.Content -match "WYCKOFF AI LAB" -or $res.Content -match 'id="root"')) {
                Write-Host "Frontend check succeeded on attempt $i."
                return $true
            }
            Write-Warning "Frontend returned unexpected content on attempt $i (status $($res.StatusCode))."
        } catch {
            Write-Warning "Frontend attempt $i failed: $_"
        }
        Start-Sleep -Milliseconds $DelayMs
    }
    return $false
}

function Invoke-FeedStatusCheck {
    param(
        [int]$Retries = 10,
        [int]$DelayMs = 500,
        [double]$MaxLiveBarAgeSec = 3.0
    )

    for ($i = 1; $i -le $Retries; $i++) {
        try {
            $state = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/api/v1/state?botId=bot-1" -Method Get -TimeoutSec 5 -UseBasicParsing
            $status = ($state.feed_status | ForEach-Object { "$_" }).ToUpperInvariant()

            if ($status -eq "NO_FEED") {
                Write-Warning "WS server OK, no Ninja feed yet (feed_status=NO_FEED)."
                return @{ ok = $true; live = $false; state = $state }
            }

            if ($status -eq "LIVE") {
                if ($state.ws_connected -ne $true) {
                    Throw-DoctorError("feed_status=LIVE but ws_connected=false (possible fake feed).")
                }
                $age = $state.bar_age_sec
                if ($age -ne $null -and [double]$age -le $MaxLiveBarAgeSec) {
                    Write-Host "Ninja feed LIVE (bar_age_sec=$age)."
                    return @{ ok = $true; live = $true; state = $state }
                }
                Write-Warning "Feed reported LIVE but stale (attempt $i): bar_age_sec=$age"
            } else {
                Write-Warning "Unknown feed_status='$($state.feed_status)' (attempt $i)."
            }
        } catch {
            Write-Warning "State/feed check attempt $i failed: $_"
        }
        Start-Sleep -Milliseconds $DelayMs
    }

    return @{ ok = $false; live = $true; state = $null }
}

function Has-RecentLogIssues {
    $meta = Read-LatestMeta
    $paths = @()
    if ($meta -and $meta.backend -and $meta.backend.log) { $paths += [string]$meta.backend.log }
    if ($meta -and $meta.frontend -and $meta.frontend.log) { $paths += [string]$meta.frontend.log }
    if (-not $paths) {
        $paths = (Get-ChildItem -Path $LogsRoot -Filter "*.log" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 4 | ForEach-Object FullName)
    }

    foreach ($path in $paths) {
        if (-not (Test-Path $path)) { continue }
        $lines = Get-Content -Path $path -Tail 80 -ErrorAction SilentlyContinue
        foreach ($line in $lines) {
            if ($line -match "(?i)(error|exception|traceback)" -and $line -notmatch "(?i)ignore") {
                Write-Warning "Detected suspicious log entry: $line"
                return $true
            }
        }
    }
    return $false
}

function Start-Attempt {
    Stop-Services
    foreach ($port in @($BackendPort, $FrontendPort)) {
        Release-Port -Port $port -MaxAttempts 20 -DelayMs $PortWaitDelayMs
    }
    Write-Host "Starting backend and frontend via arranque..."
    & $ArranqueScript -BackendPort $BackendPort -FrontendPort $FrontendPort -MaxAttempts 20 -DelayMs $PortWaitDelayMs
}

function Restart-Backend {
    Stop-RecordedProcess -PidFile (Join-Path $LogsRoot "backend_pid.txt") -Label "backend"
    Release-Port -Port $BackendPort -MaxAttempts 20 -DelayMs $PortWaitDelayMs
    Write-Host "Restarting backend via arranque..."
    & $ArranqueScript -BackendPort $BackendPort -FrontendPort $FrontendPort -BackendOnly -MaxAttempts 20 -DelayMs $PortWaitDelayMs
}

function Restart-Frontend {
    Stop-RecordedProcess -PidFile (Join-Path $LogsRoot "frontend_pid.txt") -Label "frontend"
    Release-Port -Port $FrontendPort -MaxAttempts 20 -DelayMs $PortWaitDelayMs
    Write-Host "Restarting frontend via arranque..."
    & $ArranqueScript -BackendPort $BackendPort -FrontendPort $FrontendPort -FrontendOnly -MaxAttempts 20 -DelayMs $PortWaitDelayMs
}

$backendReady = $false
$servicesStarted = $false
for ($cycle = 1; $cycle -le $MonitorRestarts; $cycle++) {
    Write-Host "Monitor cycle $cycle of $MonitorRestarts..."
    if (-not $servicesStarted) {
        Start-Attempt
        $servicesStarted = $true
        Start-Sleep -Seconds 2
    }

    if (-not (Wait-ForPortListening -Port $BackendPort)) {
        Write-Warning "Backend port $BackendPort did not open."
        Restart-Backend
        Start-Sleep -Seconds 2
        continue
    }

    if (-not (Wait-ForPortListening -Port $FrontendPort)) {
        Write-Warning "Frontend port $FrontendPort did not open."
        Restart-Frontend
        Start-Sleep -Seconds 2
        continue
    }

    if (-not (Invoke-HealthCheck)) {
        Write-Warning "Health validation failed."
        Restart-Backend
        Start-Sleep -Seconds 2
        Has-RecentLogIssues | Out-Null
        continue
    }

    if (-not (Invoke-WebSocket)) {
        Restart-Backend
        Start-Sleep -Seconds 2
        continue
    }

    if (-not (Invoke-FrontendCheck)) {
        Restart-Frontend
        Start-Sleep -Seconds 2
        continue
    }

    $feedCheck = Invoke-FeedStatusCheck
    if ($feedCheck.ok -ne $true) {
        Restart-Backend
        Start-Sleep -Seconds 2
        continue
    }

    $backendReady = $true
    break
}

if (-not $backendReady) {
    Throw-DoctorError("Unable to stabilize the services after $MonitorRestarts attempts.")
}

Write-Host "Doctor completed successfully."

$meta = Read-LatestMeta
if ($meta -and $meta.backend -and (Test-Path $meta.backend.log)) {
    Write-Host "Backend log tail ($($meta.backend.log)):"
    Get-Content -Path $meta.backend.log -Tail $LogTailLines -ErrorAction SilentlyContinue
}
if ($meta -and $meta.frontend -and (Test-Path $meta.frontend.log)) {
    Write-Host "Frontend log tail ($($meta.frontend.log)):"
    Get-Content -Path $meta.frontend.log -Tail $LogTailLines -ErrorAction SilentlyContinue
}

exit 0
