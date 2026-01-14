function Get-ListeningProcesses {
    param(
        [Parameter(Mandatory)]
        [int]$Port
    )

    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
}

function Get-NetstatListeningPids {
    param(
        [Parameter(Mandatory)]
        [int]$Port
    )

    $pids = @()
    try {
        $lines = netstat -ano | Select-String -Pattern (":$Port\\s+.*LISTENING\\s+\\d+")
        foreach ($line in $lines) {
            $parts = ($line.ToString() -split "\\s+") | Where-Object { $_ -ne "" }
            if ($parts.Count -ge 5) {
                $pidValue = $parts[-1]
                if ($pidValue -match "^\\d+$") {
                    $pids += [int]$pidValue
                }
            }
        }
    } catch {
        # ignore
    }

    return ($pids | Select-Object -Unique)
}

function Stop-ProcessTree {
    param(
        [Parameter(Mandatory)]
        [int]$ProcessId
    )

    try {
        # taskkill handles process trees reliably on Windows.
        taskkill.exe /PID $ProcessId /T /F | Out-Null
        return
    } catch {
        # Fall back to manual recursion.
    }

    try {
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
        foreach ($child in ($children | Select-Object -ExpandProperty ProcessId -ErrorAction SilentlyContinue)) {
            Stop-ProcessTree -ProcessId ([int]$child)
        }
    } catch {
        # Ignore enumeration failures.
    }

    try {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    } catch {
        # Ignore stop failures.
    }
}

function Release-Port {
    param(
        [Parameter(Mandatory)]
        [int]$Port,
        [int]$MaxAttempts = 20,
        [int]$DelayMs = 400
    )

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        $listeners = Get-ListeningProcesses -Port $Port
        $netstatPids = Get-NetstatListeningPids -Port $Port
        if (-not $listeners -and (-not $netstatPids -or $netstatPids.Count -eq 0)) {
            Write-Host "Port $Port is free."
            return $true
        }

        foreach ($listener in $listeners) {
            if (-not $listener.OwningProcess) {
                continue
            }
            $processId = [int]$listener.OwningProcess
            Stop-ProcessTree -ProcessId $processId
            Write-Host "Stopped process tree for PID $processId holding port $Port (attempt $attempt)."
        }

        foreach ($netPid in $netstatPids) {
            if (-not $netPid) { continue }
            Stop-ProcessTree -ProcessId ([int]$netPid)
            Write-Host "Stopped netstat PID $netPid holding port $Port (attempt $attempt)."
        }

        # Targeted fallback for known dev processes (handles uvicorn reload trees).
        try {
            if ($Port -eq 8000) {
                $uvicorn = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
                    Where-Object { $_.CommandLine -match "uvicorn\\s+backend\\.app:app" }
                foreach ($row in $uvicorn) {
                    Stop-ProcessTree -ProcessId ([int]$row.ProcessId)
                    Write-Host "Stopped uvicorn PID $($row.ProcessId) (attempt $attempt)."
                }
            } elseif ($Port -eq 3001) {
                $node = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
                    Where-Object { $_.CommandLine -match "vite|scripts\\\\dev\\.mjs|--port\\s+3001|\\s3001\\s*$" }
                foreach ($row in $node) {
                    Stop-ProcessTree -ProcessId ([int]$row.ProcessId)
                    Write-Host "Stopped node PID $($row.ProcessId) (attempt $attempt)."
                }
            }
        } catch {
            # ignore
        }

        Start-Sleep -Milliseconds $DelayMs
    }

    $stillListening = Get-ListeningProcesses -Port $Port
    $stillNetstat = Get-NetstatListeningPids -Port $Port
    if ($stillListening -or ($stillNetstat -and $stillNetstat.Count -gt 0)) {
        Write-Warning "Port $Port remains busy after $MaxAttempts attempts."
        return $false
    }

    return $true
}
