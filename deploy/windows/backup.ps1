# PostgreSQL backup: never silently fall back to the unrelated 'postgres' DB.
[CmdletBinding()] param([string]$OutputDir="backups",[switch]$DryRun)
. "$PSScriptRoot/common.ps1"
$db = Get-Setting "DATABASE_URL"
if (-not $db) {
  if ($DryRun) {
    Write-Host "DRY-RUN: DATABASE_URL must be configured before a real backup."
  } else {
    throw "DATABASE_URL / SOYMUTDB_DATABASE_URL is required: refusing to back up an unknown database."
  }
}
$stamp = Get-Date -Format yyyyMMdd-HHmmss
$out = Join-Path $Script:DeployRoot (Join-Path $OutputDir "db-$stamp.sql")
Invoke-Step "Back up configured PostgreSQL database to $out" {
  if (-not (Get-Command pg_dump -ErrorAction SilentlyContinue)) { throw "pg_dump is required" }
  New-Item (Split-Path $out) -ItemType Directory -Force | Out-Null
  & pg_dump $db --file=$out
  if ($LASTEXITCODE -ne 0) {
    Remove-Item $out -ErrorAction SilentlyContinue
    throw "pg_dump failed (exit $LASTEXITCODE); incomplete backup removed"
  }
  if (-not (Test-Path $out)) { throw "pg_dump reported success but wrote no output" }
} -DryRun:$DryRun
