param(
    [int]$Port = 8000,
    [string]$HostAddress = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

function Resolve-Python {
    $candidates = @("python", "py")
    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($null -eq $command) {
            continue
        }
        try {
            & $candidate --version *> $null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        }
        catch {
            continue
        }
    }
    throw "Python is not installed or not available on PATH. Install Python 3.12, then rerun this script."
}

$python = Resolve-Python

if (-not (Test-Path ".venv")) {
    & $python -m venv .venv
}

$venvPython = Join-Path ".venv" "Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt

$env:DASHBOARD_HOST = $HostAddress
$env:DASHBOARD_PORT = "$Port"

Write-Host "Starting dashboard at http://$HostAddress`:$Port"
& $venvPython -m app.dashboard.server
