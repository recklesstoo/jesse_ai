$ErrorActionPreference = "Continue"
Write-Host "=== JESSE AI DIAGNOSTIC ===" -ForegroundColor Cyan

# 1. Port Check
function Check-Port($port, $name) {
    $conn = Test-NetConnection -ComputerName localhost -Port $port -InformationLevel Quiet
    if ($conn) {
        Write-Host "[OK] $name Port $port is LISTENING" -ForegroundColor Green
    }
    else {
        Write-Host "[FAIL] $name Port $port is NOT LISTENING" -ForegroundColor Red
    }
    return $conn
}

$be = Check-Port 8000 "Backend"
$fe = Check-Port 3001 "Frontend"

# 2. Backend Health Check
if ($be) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/health" -ErrorAction Stop
        if ($health.ok -eq $true) {
            Write-Host "[OK] Backend API /health is RESPONDING: $($health | ConvertTo-Json -Depth 1 -Compress)" -ForegroundColor Green
        }
        else {
            Write-Host "[FAIL] Backend API responded but 'ok' is not true." -ForegroundColor Yellow
        }
    }
    catch {
        Write-Host "[FAIL] Backend API Request Failed: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# 3. Frontend Integrity
$index = "frontend\index.html"
if (Test-Path $index) {
    Write-Host "[OK] frontend/index.html EXISTS" -ForegroundColor Green
    $content = Get-Content $index
    if ($content -match 'src="/src/main.jsx"') {
        Write-Host "[OK] index.html points to /src/main.jsx" -ForegroundColor Green
    }
    else {
        Write-Host "[FAIL] index.html does NOT point to /src/main.jsx. Content sample:" -ForegroundColor Red
        $content | Select-Object -First 5 | Write-Host
    }
}
else {
    Write-Host "[FAIL] frontend/index.html is MISSING at $index" -ForegroundColor Red
}

# 4. Check main.jsx
$main = "frontend\src\main.jsx"
if (Test-Path $main) {
    Write-Host "[OK] frontend/src/main.jsx EXISTS" -ForegroundColor Green
    $content = Get-Content $main -Raw
    if ($content -match "ErrorBoundary") {
        Write-Host "[OK] main.jsx contains ErrorBoundary" -ForegroundColor Green
    }
    else {
        Write-Host "[WARN] main.jsx might be missing ErrorBoundary." -ForegroundColor Yellow
    }
}
else {
    Write-Host "[FAIL] frontend/src/main.jsx is MISSING" -ForegroundColor Red
}

Write-Host "=== END DIAGNOSTIC ===" -ForegroundColor Cyan
