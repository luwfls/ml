# UTF-8 backend launcher for Windows PowerShell.
# Starts the Monster Job workbench API backend with console/Python encodings aligned.

$ErrorActionPreference = "Stop"

# Make the current console use UTF-8 so Chinese log output is displayed correctly.
chcp 65001 > $null
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

# Make Python parent/child process stdio use UTF-8.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$Backend = Join-Path $ProjectRoot "tools\window_workbench.py"

if (-not (Test-Path $Python)) {
    throw "Python executable not found: $Python"
}
if (-not (Test-Path $Backend)) {
    throw "Backend script not found: $Backend"
}

Write-Host "Starting Monster Job backend with UTF-8 console..." -ForegroundColor Green
Write-Host "Project: $ProjectRoot"
Write-Host "Python:  $Python"
Write-Host "Backend: $Backend"
Write-Host "URL:     http://127.0.0.1:8765"
Write-Host ""

& $Python $Backend --api-only --no-browser --port 8765
