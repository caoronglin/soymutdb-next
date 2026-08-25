[CmdletBinding()] param([string]$Ref="",[switch]$DryRun)
. "$PSScriptRoot/common.ps1"; & (Join-Path $PSScriptRoot "backup.ps1") -DryRun:$DryRun
Invoke-Step "Stop service" {& (Join-Path $PSScriptRoot "service.ps1") -Stop} $DryRun
if($Ref){Invoke-Repo "git" @("fetch","--all","--tags"); Invoke-Repo "git" @("checkout",$Ref) -DryRun:$DryRun}
Invoke-Step "Install dependencies and migrate" {& (Join-Path $PSScriptRoot "install.ps1") -SkipDatabase:$false -DryRun:$DryRun} $false
Invoke-Step "Start service" {& (Join-Path $PSScriptRoot "service.ps1") -Start} $DryRun
