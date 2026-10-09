# Resolve the configured local listener rather than hard-coding port 8010.
[CmdletBinding()] param([string]$Url="",[int]$TimeoutSec=10,[switch]$DryRun)
. "$PSScriptRoot/common.ps1"
if (-not $Url) { $Url = "http://127.0.0.1:$($Script:ApiPort)/health" }
if ($DryRun) { Write-Host "DRY-RUN: would check $Url"; return }
try {
  $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
  if ($r.StatusCode -lt 200 -or $r.StatusCode -ge 400) { throw "HTTP $($r.StatusCode)" }
  Write-Host "Healthy: HTTP $($r.StatusCode)"
} catch {
  throw "Health check failed for $($Url): $($_.Exception.Message)"
}
