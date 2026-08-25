[CmdletBinding()] param([string]$OutputDir="backups",[switch]$DryRun)
. "$PSScriptRoot/common.ps1"; $db=Get-Setting "DATABASE_URL"; $stamp=Get-Date -Format yyyyMMdd-HHmmss; $out=Join-Path $Script:DeployRoot (Join-Path $OutputDir "db-$stamp.sql")
if(-not $db){Write-Host "DATABASE_URL is not set; using local PostgreSQL defaults."; $db="postgresql://localhost/postgres"}
Invoke-Step "Backup PostgreSQL to $out" {New-Item (Split-Path $out) -ItemType Directory -Force|Out-Null; & pg_dump $db --file=$out; if($LASTEXITCODE){throw "pg_dump failed"}} $DryRun
