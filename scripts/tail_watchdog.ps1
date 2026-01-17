$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $root
$log = Join-Path $repo "logs\\ws_watchdog.jsonl"

if (!(Test-Path $log)) {
  Write-Host "Waiting for watchdog log to appear: $log"
  while (!(Test-Path $log)) { Start-Sleep -Milliseconds 500 }
}

Write-Host "Tailing: $log"
Get-Content -Path $log -Wait

