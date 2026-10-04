<#
Monster Job32 frontend/backend launcher.

Usage:
  .\m32.ps1 start    Start backend and frontend, then stream backend logs
  .\m32.ps1 stop     Stop backend and frontend
  .\m32.ps1 restart  Stop, start, then stream backend logs
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Command = "start"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeDir = Join-Path $ProjectRoot "runtime\m32"
$BackendPidFile = Join-Path $RuntimeDir "backend.pid"
$FrontendPidFile = Join-Path $RuntimeDir "frontend.pid"
$BackendLog = Join-Path $RuntimeDir "backend.log"
$FrontendLog = Join-Path $RuntimeDir "frontend.log"
$Python = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$BackendScript = Join-Path $ProjectRoot "tools\window_workbench.py"

function Initialize-Console {
    chcp 65001 > $null
    [Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $script:OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
}

function Ensure-RuntimeDir {
    if (-not (Test-Path $RuntimeDir)) {
        New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null
    }
}

function Test-RunningPid {
    param([string]$PidFile)

    if (-not (Test-Path $PidFile)) {
        return $false
    }

    $raw = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $raw) {
        return $false
    }

    $processId = 0
    if (-not [int]::TryParse($raw.Trim(), [ref]$processId)) {
        return $false
    }

    return $null -ne (Get-Process -Id $processId -ErrorAction SilentlyContinue)
}

function Get-SavedPid {
    param([string]$PidFile)

    if (-not (Test-Path $PidFile)) {
        return $null
    }

    $raw = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $raw) {
        return $null
    }

    $processId = 0
    if ([int]::TryParse($raw.Trim(), [ref]$processId)) {
        return $processId
    }

    return $null
}

function Stop-ProcessTree {
    param([int]$ProcessId)

    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue)
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId)
    }

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Stop-One {
    param(
        [string]$Name,
        [string]$PidFile
    )

    $processId = Get-SavedPid $PidFile
    if ($null -eq $processId) {
        Write-Host "$Name not running (no pid file)."
        return
    }

    if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
        Write-Host "Stopping $Name (PID $processId)..."
        Stop-ProcessTree -ProcessId $processId
    }
    else {
        Write-Host "$Name not running (stale PID $processId)."
    }

    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

function Start-Backend {
    if (Test-RunningPid $BackendPidFile) {
        $processId = Get-SavedPid $BackendPidFile
        Write-Host "Backend already running (PID $processId)."
        return
    }

    if (-not (Test-Path $Python)) {
        throw "Python executable not found: $Python"
    }
    if (-not (Test-Path $BackendScript)) {
        throw "Backend script not found: $BackendScript"
    }

    Remove-Item $BackendLog -Force -ErrorAction SilentlyContinue
    New-Item -ItemType File -Path $BackendLog -Force | Out-Null

    $backendCommand = @"
@echo off
chcp 65001 > nul
cd /d "$ProjectRoot"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
"$Python" -u "$BackendScript" --api-only --no-browser --port 8765 >> "$BackendLog" 2>&1
"@
    $backendCmdFile = Join-Path $RuntimeDir "backend.cmd"
    Set-Content -Path $backendCmdFile -Value $backendCommand -Encoding ascii
    $process = Start-Process -FilePath "cmd.exe" -ArgumentList @("/d", "/c", $backendCmdFile) -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
    Set-Content -Path $BackendPidFile -Value $process.Id -Encoding ascii
    Write-Host "Backend started: PID $($process.Id), http://127.0.0.1:8765"
}

function Start-Frontend {
    if (Test-RunningPid $FrontendPidFile) {
        $processId = Get-SavedPid $FrontendPidFile
        Write-Host "Frontend already running (PID $processId)."
        return
    }

    Remove-Item $FrontendLog -Force -ErrorAction SilentlyContinue
    New-Item -ItemType File -Path $FrontendLog -Force | Out-Null

    $corepack = Get-Command "corepack.cmd" -ErrorAction SilentlyContinue
    if (-not $corepack) {
        $corepack = Get-Command "corepack" -ErrorAction SilentlyContinue
    }
    if (-not $corepack) {
        throw "corepack was not found in PATH. Install/enable Node.js Corepack, then retry."
    }

    $frontendCommand = @"
@echo off
cd /d "$ProjectRoot"
"$($corepack.Source)" yarn dev >> "$FrontendLog" 2>&1
"@
    $frontendCmdFile = Join-Path $RuntimeDir "frontend.cmd"
    Set-Content -Path $frontendCmdFile -Value $frontendCommand -Encoding ascii
    $process = Start-Process -FilePath "cmd.exe" -ArgumentList @("/d", "/c", $frontendCmdFile) -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
    Set-Content -Path $FrontendPidFile -Value $process.Id -Encoding ascii
    Write-Host "Frontend started: PID $($process.Id), http://127.0.0.1:5173"
}

function Start-All {
    Ensure-RuntimeDir
    Start-Backend
    Start-Frontend
    Write-Host ""
    Write-Host "Backend log: $BackendLog"
    Write-Host "Frontend log: $FrontendLog"
    Write-Host "Use 'm32 stop' in another terminal to stop both services. Press Ctrl+C here to stop viewing logs only."
    Write-Host ""
    Write-Host "--- backend log ---"
    Get-Content -Path $BackendLog -Wait -Encoding UTF8
}

function Stop-All {
    Ensure-RuntimeDir
    Stop-One -Name "frontend" -PidFile $FrontendPidFile
    Stop-One -Name "backend" -PidFile $BackendPidFile
}

function Show-Status {
    Ensure-RuntimeDir
    if (Test-RunningPid $BackendPidFile) {
        Write-Host "Backend:  running (PID $(Get-SavedPid $BackendPidFile))"
    }
    else {
        Write-Host "Backend:  stopped"
    }

    if (Test-RunningPid $FrontendPidFile) {
        Write-Host "Frontend: running (PID $(Get-SavedPid $FrontendPidFile))"
    }
    else {
        Write-Host "Frontend: stopped"
    }
}

Initialize-Console

switch ($Command) {
    "start" { Start-All }
    "stop" { Stop-All }
    "restart" {
        Stop-All
        Start-Sleep -Milliseconds 500
        Start-All
    }
    "status" { Show-Status }
}
