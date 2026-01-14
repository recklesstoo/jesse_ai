param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3001,
    [int]$MaxAttempts = 20,
    [int]$DelayMs = 400,
    [switch]$BackendOnly,
    [switch]$FrontendOnly
)

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path

. (Join-Path $ScriptRoot "kill-port.ps1")

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
    Release-Port -Port $port -MaxAttempts $MaxAttempts -DelayMs $DelayMs
}

$BackendCommand = @"
Set-Location -Path '$RepoRoot';
`$env:PYTHONPATH = '$RepoRoot';
if (Test-Path '.\\.venv\\Scripts\\python.exe') { } else { Write-Error 'Missing .venv. Run scripts\\doctor.ps1 first.'; exit 1 }
`$env:WYCKOFF_SIM_FEED = '1';
Write-Host 'Backend log: $BackendLog';
& .\\.venv\\Scripts\\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port $BackendPort --reload --reload-dir backend --reload-dir backend/routers --reload-dir backend/services --reload-dir backend/ws 2>&1 | ForEach-Object { `$_.ToString() } | Tee-Object -FilePath '$BackendLog' -Append;
"@

$FrontendCommand = @"
Set-Location -Path '$RepoRoot\frontend';
`$env:VITE_API_BASE = 'http://127.0.0.1:$BackendPort';
`$env:VITE_BOT_ID = 'bot-1';
Write-Host 'Frontend log: $FrontendLog';
npm run dev -- --port $FrontendPort 2>&1 | ForEach-Object { `$_.ToString() } | Tee-Object -FilePath '$FrontendLog' -Append;
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
