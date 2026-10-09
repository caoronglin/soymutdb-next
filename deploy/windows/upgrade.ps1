# Back up first; never re-register an existing service during an upgrade.
[CmdletBinding()] param([string]$Ref="",[switch]$DryRun)
. "$PSScriptRoot/common.ps1"
& (Join-Path $PSScriptRoot "backup.ps1") -DryRun:$DryRun
Invoke-Step "Stop API service" {
  & (Join-Path $PSScriptRoot "service.ps1") -Stop
} $DryRun
if ($Ref) {
  Invoke-Repo "git" @("fetch","--all","--tags") -DryRun:$DryRun
  Invoke-Repo "git" @("checkout",$Ref) -DryRun:$DryRun
}
# Idempotently upgrade API + local packages + database, but keep service
# registration intact. No destructive virtualenv recreation on every deploy.
Invoke-Step "Install packages and migrate" {
  & (Join-Path $PSScriptRoot "install.ps1") -SkipService -NoStart
} $DryRun
Invoke-Step "Restart API service" {
  & (Join-Path $PSScriptRoot "service.ps1") -Start
} $DryRun
Invoke-Step "Check API health" {
  & (Join-Path $PSScriptRoot "health.ps1")
  if (-not $?) { throw "API health check failed after upgrade" }
} $DryRun
