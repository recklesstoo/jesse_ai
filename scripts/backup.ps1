param(
    [string]$Message = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') Backup"
)

$RootPath = Split-Path -Parent $PSCommandPath
if (-not $RootPath) {
    $RootPath = Get-Location
}

Push-Location $RootPath
try {
    $status = git status --porcelain
    if (-not $status) {
        Write-Host "No changes detected; nothing to commit."
        return
    }

    Write-Host "Staging all changes..."
    git add -A

    Write-Host "Committing with message: $Message"
    git commit -m $Message

    Write-Host "Pushing current branch..."
    git push
} finally {
    Pop-Location
}
