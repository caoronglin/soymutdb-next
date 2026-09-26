Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Script:DeployRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$Script:EnvFile = Join-Path $Script:DeployRoot ".env"
$Script:ServiceName = if ($env:WEB_SERVICE_NAME) { $env:WEB_SERVICE_NAME } else { "SoyMutDB-API" }
$Script:ApiHost = if ($env:WEB_API_HOST) { $env:WEB_API_HOST } else { "127.0.0.1" }
$Script:ApiPort = if ($env:WEB_API_PORT) { $env:WEB_API_PORT } else { "8010" }
$Script:WinSW = Join-Path $PSScriptRoot "winsw.exe"

function Test-DryRun([switch]$DryRun) { return [bool]$DryRun }
function Invoke-Step([string]$Description, [scriptblock]$Action, [switch]$DryRun) {
  Write-Host "==> $Description"
  if ($DryRun) { Write-Host "DRY-RUN: skipped"; return }
  & $Action
}
function Assert-Admin {
  $p=[Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
  if (-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw "Run PowerShell as Administrator." }
}
function Get-Setting([string]$Name, [string]$Default="") {
  $names = @($Name)
  if ($Name -notmatch "^SOYMUTDB_") { $names += "SOYMUTDB_$Name" }
  foreach ($candidate in $names) {
    $v=[Environment]::GetEnvironmentVariable($candidate)
    if ($v) { return $v }
    if (Test-Path $Script:EnvFile) {
      foreach($line in Get-Content $Script:EnvFile) {
        if ($line -match "^\s*$candidate\s*=\s*(.*)\s*$") { return $Matches[1].Trim().Trim('"').Trim("'") }
      }
    }
  }
  return $Default
}
function Invoke-Repo([string]$Command, [string[]]$Arguments=@(), [switch]$DryRun) {
  $display="$Command $($Arguments -join ' ')"; Write-Host $display
  if (-not $DryRun) { Push-Location $Script:DeployRoot; try { & $Command @Arguments; if ($LASTEXITCODE -ne 0) { throw "Command failed: $display" } } finally { Pop-Location } }
}
function Get-Python { if (Get-Command py -ErrorAction SilentlyContinue) { return "py" }; if (Get-Command python -ErrorAction SilentlyContinue) { return "python" }; throw "Python is required." }
