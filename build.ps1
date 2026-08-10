$ErrorActionPreference = "Stop"

if (-not (Get-Command gcc -ErrorAction SilentlyContinue)) {
    Write-Host "gcc not found."
    exit 1
}

gcc -shared -o c_core\monitor_core.dll memory_leak_detector\monitor_core.c -lm

if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed."
    exit 1
}

Write-Host "Done. monitor_core.dll created."
