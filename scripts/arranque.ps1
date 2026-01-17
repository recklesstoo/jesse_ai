param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3001,
    [int]$MaxAttempts = 20,
    [int]$DelayMs = 400,
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$SmokeTest,
    [switch]$Reload
)

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path

function Get-ListeningPidsForPort {
    param([Parameter(Mandatory = $true)][int]$Port)

    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
        $pids = @($conns | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -gt 0 })
        # Ignore stale PIDs that no longer exist (rare race during shutdown).
        return @($pids | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
    } catch {
        $pids = New-Object System.Collections.Generic.List[int]
        try {
            $lines = netstat -ano -p TCP 2>$null
            foreach ($line in $lines) {
                if ($line -notmatch "LISTENING") { continue }
                if ($line -notmatch ":(?:$Port)\\s") { continue }
                if ($line -match "LISTENING\\s+(\\d+)\\s*$") {
                    $owningPid = [int]$matches[1]
                    if ($owningPid -gt 0 -and -not $pids.Contains($owningPid)) { $pids.Add($owningPid) }
                }
            }
        } catch {
            return @()
        }
        # Ignore stale PIDs that no longer exist (netstat can race).
        return @($pids | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
    }
}

function Stop-ProcessTree {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $visited = New-Object "System.Collections.Generic.HashSet[int]"

    function Stop-Node([int]$NodePid) {
        if ($NodePid -le 0) { return }
        if ($visited.Contains($NodePid)) { return }
        [void]$visited.Add($NodePid)

        $children = @()
        try {
            $children = @(
                Get-CimInstance Win32_Process -Filter "ParentProcessId=$NodePid" -ErrorAction SilentlyContinue |
                    Select-Object -ExpandProperty ProcessId
            )
        } catch { $children = @() }

        foreach ($child in $children) { Stop-Node -NodePid $child }

        try {
            Stop-Process -Id $NodePid -Force -ErrorAction SilentlyContinue
        } catch { }
    }

    Stop-Node -NodePid $ProcessId
}

function Release-Port {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [int]$MaxCycles = 5
    )

    for ($cycle = 1; $cycle -le $MaxCycles; $cycle++) {
        $pids = @(Get-ListeningPidsForPort -Port $Port | Sort-Object -Unique)
        if ($pids.Count -eq 0) {
            Write-Host "Port $Port is free."
            return $true
        }

        $pidLabels = foreach ($owningPid in $pids) {
            $proc = Get-Process -Id $owningPid -ErrorAction SilentlyContinue
            if ($proc) { "$owningPid($($proc.ProcessName))" } else { "$owningPid(<exited>)" }
        }
        Write-Host "Port $Port LISTENING PIDs: $($pidLabels -join ', ')"

        # If all PIDs are already gone, give the OS a moment to drop the socket entry and re-check.
        $livePids = @($pids | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
        if ($livePids.Count -eq 0) {
            Start-Sleep -Milliseconds 250
            continue
        }

        if ($pids -contains 4) {
            Write-Warning "Port $Port is held by SYSTEM/service (PID 4); cannot stop safely."
            break
        }

        foreach ($owningPid in $livePids) {
            $proc = Get-Process -Id $owningPid -ErrorAction SilentlyContinue
            if (-not $proc) { continue }
            Write-Host "Stopping PID $owningPid ($($proc.ProcessName))..."
            Stop-ProcessTree -ProcessId $owningPid
        }

        Start-Sleep -Milliseconds 250
    }

    $remaining = @(Get-ListeningPidsForPort -Port $Port | Sort-Object -Unique)
    if ($remaining.Count -eq 0) {
        Write-Host "Port $Port is free."
        return $true
    }

    $remainingLive = @($remaining | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
    if ($remainingLive.Count -eq 0) {
        Write-Host "Port $Port is free."
        return $true
    }

    Write-Warning "Failed to release port $Port after $MaxCycles cycles."
    Write-Host "Diagnostic: netstat -ano | findstr \":$Port\""
    try { netstat -ano | findstr ":$Port" } catch { }

    if ($remaining.Count -gt 0) {
        Write-Host "Processes still owning LISTENING sockets:"
        foreach ($owningPid in $remainingLive) {
            $proc = Get-Process -Id $owningPid -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host ("- {0} ({1})" -f $owningPid, $proc.ProcessName)
            } else {
                Write-Host ("- {0} (<exited>)" -f $owningPid)
            }
        }
    }

    return $false
}

if ($SmokeTest) {
    $testPort = 18000
    Write-Host "SmokeTest: starting dummy listener on port $testPort..."

    $psExe = Join-Path $env:WINDIR "System32\\WindowsPowerShell\\v1.0\\powershell.exe"
    if (-not (Test-Path $psExe)) { $psExe = "powershell.exe" }

    $listenerCmd = @"
`$ErrorActionPreference = 'Stop'
`$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $testPort)
`$listener.Start()
Start-Sleep -Seconds 60
"@

    $p = Start-Process -FilePath $psExe -ArgumentList @("-NoProfile", "-Command", $listenerCmd) -WindowStyle Hidden -PassThru
    Start-Sleep -Milliseconds 250

    $pids = @(Get-ListeningPidsForPort -Port $testPort)
    if ($pids.Count -eq 0) {
        Write-Host "FAIL: listener did not bind to port $testPort."
        try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch { }
        exit 1
    }

    $ok = Release-Port -Port $testPort -MaxCycles 5
    if (-not $ok) {
        Write-Host "FAIL: Release-Port did not free port $testPort."
        exit 1
    }

    Write-Host "PASS: Release-Port freed port $testPort."
    exit 0
}

$LogsRoot = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogsRoot | Out-Null

$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackendLog = Join-Path $LogsRoot "backend_$Stamp.log"
$FrontendLog = Join-Path $LogsRoot "frontend_$Stamp.log"
$LatestMetaPath = Join-Path $LogsRoot "latest.json"
New-Item -ItemType File -Force -Path $BackendLog | Out-Null
New-Item -ItemType File -Force -Path $FrontendLog | Out-Null

if (-not $BackendOnly -and -not $FrontendOnly) {
    $BackendOnly = $false
    $FrontendOnly = $false
}

$portsToRelease = @()
if (-not $FrontendOnly) { $portsToRelease += $BackendPort }
if (-not $BackendOnly) { $portsToRelease += $FrontendPort }

foreach ($port in $portsToRelease) {
    Write-Host "Releasing port $port..."
    $ok = Release-Port -Port $port -MaxCycles 5
    if (-not $ok) {
        Write-Error "Port $port could not be freed; aborting startup."
        exit 1
    }
}

$reloadFlags = ""
if ($Reload) {
    $reloadFlags = "--reload --reload-dir '$RepoRoot\\backend' --reload-dir '$RepoRoot\\backend\\routers' --reload-dir '$RepoRoot\\backend\\services' --reload-dir '$RepoRoot\\backend\\ws'"
}

$BackendCommand = @"
Set-Location -Path '$RepoRoot';
`$env:PYTHONPATH = '$RepoRoot';
if (Test-Path '.\\.venv\\Scripts\\python.exe') { } else { Write-Error 'Missing .venv. Run scripts\\doctor.ps1 first.'; exit 1 }
Write-Host 'Backend log: $BackendLog';
& .\\.venv\\Scripts\\python.exe -m uvicorn --app-dir '$RepoRoot' backend.app:app --host 0.0.0.0 --port $BackendPort $reloadFlags 2>&1 | ForEach-Object { `$_.ToString() } | Tee-Object -FilePath '$BackendLog' -Append;
"@

$FrontendCommand = @"
Set-Location -Path '$RepoRoot\frontend';
`$env:VITE_API_BASE = 'http://127.0.0.1:$BackendPort';
`$env:VITE_BOT_ID = 'bot-1';
Write-Host 'Frontend log: $FrontendLog';
npm run dev -- $FrontendPort 2>&1 | ForEach-Object { `$_.ToString() } | Tee-Object -FilePath '$FrontendLog' -Append;
"@

$backendPidPath = Join-Path $LogsRoot "backend_pid.txt"
$frontendPidPath = Join-Path $LogsRoot "frontend_pid.txt"

$BackendProcess = $null
$FrontendProcess = $null

if (-not $FrontendOnly) {
    $BackendProcess = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-Command", $BackendCommand) -WorkingDirectory $RepoRoot -WindowStyle Normal -PassThru
    $BackendProcess.Id | Set-Content -Path $backendPidPath
}

if (-not $BackendOnly) {
    $FrontendProcess = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoExit", "-Command", $FrontendCommand) -WorkingDirectory (Join-Path $RepoRoot "frontend") -WindowStyle Normal -PassThru
    $FrontendProcess.Id | Set-Content -Path $frontendPidPath
}

$existing = $null
if (Test-Path $LatestMetaPath) {
    try { $existing = Get-Content -Path $LatestMetaPath -Raw | ConvertFrom-Json } catch { $existing = $null }
}

$meta = @{
    startedAt = (Get-Date).ToString("o")
    backend   = @{
        port = $BackendPort
        log  = $BackendLog
        pid  = if ($BackendProcess) { $BackendProcess.Id } elseif ($existing) { $existing.backend.pid } else { $null }
    }
    frontend  = @{
        port = $FrontendPort
        log  = $FrontendLog
        pid  = if ($FrontendProcess) { $FrontendProcess.Id } elseif ($existing) { $existing.frontend.pid } else { $null }
    }
}
$meta | ConvertTo-Json -Depth 6 | Set-Content -Path $LatestMetaPath -Encoding UTF8

if ($BackendProcess) { Write-Host "Backend console launched with PID $($BackendProcess.Id)." }
if ($FrontendProcess) { Write-Host "Frontend console launched with PID $($FrontendProcess.Id)." }
