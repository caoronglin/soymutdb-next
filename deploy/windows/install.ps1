# One-command, repeatable Windows API setup; database and service are separate gates.
[CmdletBinding()]
param(
  [switch]$DryRun,
  [switch]$SkipDatabase,
  [switch]$SkipService,
  [switch]$NoStart
)
. "$PSScriptRoot/common.ps1"
if (-not $DryRun -and -not $SkipService) { Assert-Admin }

$python = Get-Python
$apiRoot = Join-Path $Script:DeployRoot "apps\api"
$venvPython = Join-Path $apiRoot ".venv\Scripts\python.exe"
$workspaceInstaller = Join-Path $Script:DeployRoot "scripts\install_python_workspace.py"

# Use the canonical repo installer: it installs the two unpublished local Python
# distributions before the API. pip install -e apps/api alone cannot resolve them.
Invoke-Step "Install API + shared Python packages (Python 3.14)" {
  Push-Location $Script:DeployRoot
  try {
    & $python $workspaceInstaller --venv "apps/api/.venv" --upgrade-pip --expect-version "3.14" "apps/api"
    if ($LASTEXITCODE -ne 0) { throw "Workspace Python installation failed (exit $LASTEXITCODE)" }
    if (-not (Test-Path $venvPython)) { throw "API Python virtual environment was not created" }
  } finally { Pop-Location }
} -DryRun:$DryRun

if (-not $SkipDatabase) {
  Invoke-Step "Apply PostgreSQL migrations" {
    $alembic = Join-Path $apiRoot "alembic.ini"
    if (-not (Test-Path $alembic)) { throw "Missing apps/api/alembic.ini" }
    Push-Location $apiRoot
    try {
      & $venvPython -m alembic upgrade head
      if ($LASTEXITCODE -ne 0) { throw "Database migration failed (exit $LASTEXITCODE)" }
    } finally { Pop-Location }
  } -DryRun:$DryRun
} else {
  Write-Host "Database migrations explicitly skipped; do not use this mode for production upgrades."
}

if (-not $SkipService) {
  Invoke-Step "Register API Windows service if not already installed" {
    if (-not (Get-Service -Name $Script:ServiceName -ErrorAction SilentlyContinue)) {
      & (Join-Path $PSScriptRoot "service.ps1") -Install
      if (-not (Get-Service -Name $Script:ServiceName -ErrorAction SilentlyContinue)) {
        throw "Windows API service registration failed"
      }
    }
  } -DryRun:$DryRun
  if (-not $NoStart) {
    Invoke-Step "Start API Windows service" {
      $service = Get-Service -Name $Script:ServiceName -ErrorAction Stop
      if ($service.Status -ne "Running") { & (Join-Path $PSScriptRoot "service.ps1") -Start }
    } -DryRun:$DryRun
    Invoke-Step "Verify local API health" {
      & (Join-Path $PSScriptRoot "health.ps1")
      if (-not $?) { throw "Local API health check failed" }
    } -DryRun:$DryRun
  }
}
