function Get-ListeningProcesses {
    param(
        [Parameter(Mandatory)]
        [int]$Port
    )

    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
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
        if (-not $listeners) {
            Write-Host "Port $Port is free."
            return $true
        }

        foreach ($listener in $listeners) {
            if (-not $listener.OwningProcess) {
                continue
            }
            $processId = [int]$listener.OwningProcess
            $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
            if (-not $process) { continue }

            Stop-ProcessTree -ProcessId $processId
            Write-Host "Stopped process tree for PID $processId holding port $Port (attempt $attempt)."
        }

        Start-Sleep -Milliseconds $DelayMs
    }

    $stillListening = Get-ListeningProcesses -Port $Port
    if ($stillListening) {
        Write-Warning "Port $Port remains busy after $MaxAttempts attempts."
        return $false
    }

    return $true
}
