[CmdletBinding()] param([string]$Url="http://127.0.0.1:8000/health",[int]$TimeoutSec=10,[switch]$DryRun)
. "$PSScriptRoot/common.ps1"
if($DryRun){Write-Host "DRY-RUN: would check $Url"; exit 0}
try {$r=Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec; if($r.StatusCode -lt 200 -or $r.StatusCode -ge 400){throw "HTTP $($r.StatusCode)"}; Write-Host "Healthy: HTTP $($r.StatusCode)"; exit 0} catch {Write-Error "Health check failed: $_"; exit 1}
