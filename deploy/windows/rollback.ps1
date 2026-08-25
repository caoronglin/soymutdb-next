[CmdletBinding()] param([Parameter(Mandatory=$true)][string]$Ref,[switch]$DryRun)
. "$PSScriptRoot/common.ps1"; & (Join-Path $PSScriptRoot "backup.ps1") -DryRun:$DryRun
Invoke-Step "Stop service" {& (Join-Path $PSScriptRoot "service.ps1") -Stop} $DryRun
Invoke-Repo "git" @("fetch","--all","--tags") -DryRun:$DryRun; Invoke-Repo "git" @("checkout",$Ref) -DryRun:$DryRun
Invoke-Step "Restore dependencies" {& (Join-Path $PSScriptRoot "install.ps1") -DryRun:$DryRun} $false
Invoke-Step "Start service" {& (Join-Path $PSScriptRoot "service.ps1") -Start} $DryRun
