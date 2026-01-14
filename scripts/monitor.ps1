param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3001,
    [int]$MaxLoops = 10,
    [int]$DelaySeconds = 2
)

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$DoctorScript = Join-Path $ScriptRoot "doctor.ps1"

for ($i = 1; $i -le $MaxLoops; $i++) {
    Write-Host "Monitor loop $i/$MaxLoops..."
    & $DoctorScript -BackendPort $BackendPort -FrontendPort $FrontendPort
    if ($LASTEXITCODE -eq 0) {
        Write-Host "System is OK."
        exit 0
    }
    Write-Warning "Doctor failed (exit $LASTEXITCODE). Retrying in $DelaySeconds seconds..."
    Start-Sleep -Seconds $DelaySeconds
}

Write-Error "Monitor failed to reach OK state after $MaxLoops attempts."
exit 1

