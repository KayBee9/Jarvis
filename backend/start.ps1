# Start Jarvis backend with Tailscale HTTPS.
# Run from any directory: .\start.ps1

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Activate the venv if not already active.
if (-not $env:VIRTUAL_ENV) {
    . .\.venv\Scripts\Activate.ps1
}

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 `
    --ssl-keyfile certs/jarvis.key `
    --ssl-certfile certs/jarvis.crt