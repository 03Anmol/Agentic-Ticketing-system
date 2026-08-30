<#
    Starts the Train Ticket Agent backend (which also serves the web UI).

    Exists because "WinError 10013: An attempt was made to access a socket in a
    way forbidden by its access permissions" is the standard Windows symptom of
    a port that is already taken - usually by a previous run of this very app
    that didn't shut down cleanly. The error text never says that, which sends
    you looking at firewalls and permissions instead of at the stale process.

    So: find a stale listener, offer to clear it, and fall forward to the next
    free port if anything else is in the way.

    Usage:
      .\run.ps1                 # port 8000, auto-resolve conflicts
      .\run.ps1 -Port 8080      # start from a specific port
      .\run.ps1 -NoReload       # disable --reload
      .\run.ps1 -Force          # kill a stale listener without asking
#>
param(
    [int]$Port = 8000,
    [switch]$NoReload,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$Root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Python = Join-Path (Split-Path -Parent $Root) "venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "Python venv not found at: $Python" -ForegroundColor Red
    Write-Host "Create it, then: $Python -m pip install -r backend\requirements.txt"
    exit 1
}

function Get-PortOwnerId([int]$p) {
    $conn = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $conn) { return $null }
    return [int]$conn.OwningProcess
}

function Get-PortHolder([int]$p) {
    $id = Get-PortOwnerId $p
    if ($null -eq $id) { return $null }
    return Get-Process -Id $id -ErrorAction SilentlyContinue
}

<#
    The nastiest version of this problem, and the reason this function exists:

    `uvicorn --reload` runs a parent reloader that spawns the actual server as
    a multiprocessing child, handing it the listening socket. Kill the parent
    and the child is orphaned but keeps the socket open - while Windows still
    reports the socket's owner as the now-DEAD parent PID.

    The result is a port that looks held by a process that doesn't exist:
    Stop-Process on the reported PID does nothing, the socket is never
    released, and every retry fails with WinError 10013 forever. Waiting
    doesn't help either - this is not TIME_WAIT, it's a live orphan.

    So when the reported owner is dead, hunt for orphaned multiprocessing
    children and kill those instead.
#>
function Remove-OrphanedListeners([int]$p) {
    $ownerId = Get-PortOwnerId $p
    if ($null -eq $ownerId) { return $false }
    if (Get-Process -Id $ownerId -ErrorAction SilentlyContinue) { return $false }  # owner alive; not this case

    Write-Host "Port $p is held by PID $ownerId, which no longer exists - looking for an orphaned child..." -ForegroundColor Yellow

    $orphans = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.ParentProcessId -eq $ownerId -or $_.CommandLine -like '*multiprocessing-fork*' } |
        Where-Object { -not (Get-Process -Id $_.ParentProcessId -ErrorAction SilentlyContinue) }

    $killed = $false
    foreach ($o in $orphans) {
        Write-Host "  killing orphaned child PID $($o.ProcessId)" -ForegroundColor Yellow
        Stop-Process -Id $o.ProcessId -Force -ErrorAction SilentlyContinue
        $killed = $true
    }
    if ($killed) { Start-Sleep -Milliseconds 900 }
    return $killed
}

# Windows (Hyper-V/WSL) silently reserves port blocks; a bind inside one fails
# with the same 10013 even though nothing is listening. Worth naming explicitly,
# because no amount of killing processes will free such a port.
function Test-PortExcluded([int]$p) {
    $ranges = netsh interface ipv4 show excludedportrange protocol=tcp 2>$null |
        Select-String -Pattern '^\s*(\d+)\s+(\d+)'
    foreach ($r in $ranges) {
        $start = [int]$r.Matches[0].Groups[1].Value
        $end   = [int]$r.Matches[0].Groups[2].Value
        if ($p -ge $start -and $p -le $end) { return "$start-$end" }
    }
    return $null
}

$maxTries = 10
for ($i = 0; $i -lt $maxTries; $i++) {
    $excluded = Test-PortExcluded $Port
    if ($excluded) {
        Write-Host "Port $Port is inside a Windows reserved range ($excluded) - skipping." -ForegroundColor Yellow
        $Port++
        continue
    }

    # Dead-owner case first: no live process to prompt about, so just clear it.
    if (Remove-OrphanedListeners $Port) {
        if (-not (Get-PortOwnerId $Port)) {
            Write-Host "Freed port $Port." -ForegroundColor Green
            break
        }
    }

    $holder = Get-PortHolder $Port
    if (-not (Get-PortOwnerId $Port)) { break }
    if (-not $holder) {
        Write-Host "Port $Port held by a process that can't be identified - trying the next port." -ForegroundColor Yellow
        $Port++
        continue
    }

    $isOurs = $holder.ProcessName -eq "python"
    Write-Host "Port $Port is held by PID $($holder.Id) ($($holder.ProcessName))." -ForegroundColor Yellow

    if ($isOurs -and ($Force -or $(Read-Host "Looks like a stale server. Kill it? [Y/n]") -notmatch '^[Nn]')) {
        Stop-Process -Id $holder.Id -Force
        Start-Sleep -Milliseconds 700
        if (-not (Get-PortHolder $Port)) {
            Write-Host "Freed port $Port." -ForegroundColor Green
            break
        }
    }

    $Port++
    Write-Host "Trying port $Port instead..." -ForegroundColor Yellow
}

if (Get-PortHolder $Port) {
    Write-Host "Could not find a free port after $maxTries attempts." -ForegroundColor Red
    exit 1
}

$uvicornArgs = @("-m", "uvicorn", "app.main:app", "--port", "$Port")
if (-not $NoReload) { $uvicornArgs += "--reload" }

Write-Host ""
Write-Host "  Train Ticket Agent  ->  http://127.0.0.1:$Port/" -ForegroundColor Cyan
Write-Host "  Launch Pad lives on the Scheduled Jobs tab. Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host ""

Push-Location $Backend
try { & $Python @uvicornArgs } finally { Pop-Location }
