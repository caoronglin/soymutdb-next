# Code rollback only. Database schema downgrade/restore requires a separate
# verified compatibility plan; never silently run an Alembic downgrade.
[CmdletBinding()] param([Parameter(Mandatory=$true)][string]$Ref,[switch]$DryRun)
. "$PSScriptRoot/common.ps1"
& (Join-Path $PSScriptRoot "backup.ps1") -DryRun:$DryRun
Invoke-Step "Stop API service" { & (Join-Path $PSScriptRoot "service.ps1") -Stop } $DryRun
Invoke-Repo "git" @("fetch","--all","--tags") -DryRun:$DryRun
Invoke-Repo "git" @("checkout",$Ref) -DryRun:$DryRun
Invoke-Step "Restore API dependencies without altering PostgreSQL schema" {
  & (Join-Path $PSScriptRoot "install.ps1") -SkipService -SkipDatabase -NoStart
} $DryRun
Invoke-Step "Restart API service" { & (Join-Path $PSScriptRoot "service.ps1") -Start } $DryRun
Invoke-Step "Check API health" {
  & (Join-Path $PSScriptRoot "health.ps1")
  if (-not $?) { throw "API health check failed after code rollback" }
} $DryRun
