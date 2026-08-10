$ErrorActionPreference = "Stop"

if (-not (Get-Command gcc -ErrorAction SilentlyContinue)) {
    Write-Host "gcc not found."
    exit 1
}

gcc -shared -o monitor_core.dll monitor_core.c -lm

if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed."
    exit 1
}

Write-Host "Done. monitor_core.dll created."
