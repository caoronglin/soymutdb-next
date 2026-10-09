[CmdletBinding()]
param([switch]$Install,[switch]$Uninstall,[switch]$Start,[switch]$Stop,[switch]$Restart,[switch]$DryRun)
. "$PSScriptRoot/common.ps1"
if (-not $DryRun) { Assert-Admin }

$svc = $Script:ServiceName
$apiRoot = Join-Path $Script:DeployRoot "apps\api"
$exe = Join-Path $apiRoot ".venv\Scripts\python.exe"
$app = Get-Setting "WEB_APP_MODULE" "app.main:app"
$args = "-m uvicorn $app --host $Script:ApiHost --port $Script:ApiPort"

if ($Install) {
  Invoke-Step "Install service $svc" {
    if (-not (Test-Path $exe)) { throw "API venv must be installed before service registration" }
    if (Get-Service -Name $svc -ErrorAction SilentlyContinue) {
      throw "Service $svc already exists; use -Start/-Restart, not -Install"
    }
    if (Test-Path $Script:WinSW) {
      $wrapper = Join-Path $Script:DeployRoot "$svc.exe"
      Copy-Item $Script:WinSW $wrapper -Force
      # XML-escape untrusted user paths and settings; never put passwords
      # into service XML. Secrets must come from protected machine settings.
      $escapedSvc = [Security.SecurityElement]::Escape($svc)
      $escapedExe = [Security.SecurityElement]::Escape($exe)
      $escapedArgs = [Security.SecurityElement]::Escape($args)
      $escapedRoot = [Security.SecurityElement]::Escape($apiRoot)
      $xml = "<service><id>$escapedSvc</id><name>$escapedSvc</name><executable>$escapedExe</executable><arguments>$escapedArgs</arguments><workingdirectory>$escapedRoot</workingdirectory><log mode='roll-by-size'/><onfailure action='restart'/></service>"
      Set-Content (Join-Path $Script:DeployRoot "$svc.xml") $xml -Encoding UTF8
      & $wrapper install
      if ($LASTEXITCODE -ne 0) { throw "WinSW install failed (exit $LASTEXITCODE)" }
    } elseif (Get-Command nssm -ErrorAction SilentlyContinue) {
      & nssm install $svc $exe $args
      if ($LASTEXITCODE -ne 0) { throw "NSSM install failed (exit $LASTEXITCODE)" }
      & nssm set $svc AppDirectory $apiRoot
      if ($LASTEXITCODE -ne 0) { throw "NSSM working directory setup failed" }
    } else {
      throw "Place winsw.exe beside deploy/windows/service.ps1 or install NSSM."
    }
  } $DryRun
}
if ($Uninstall) {
  Invoke-Step "Uninstall service $svc" {
    $wrapper = Join-Path $Script:DeployRoot "$svc.exe"
    if (Test-Path $wrapper) { & $wrapper uninstall; if ($LASTEXITCODE -ne 0) { throw "WinSW uninstall failed" } }
    elseif (Get-Command nssm -ErrorAction SilentlyContinue) { & nssm remove $svc confirm; if ($LASTEXITCODE -ne 0) { throw "NSSM uninstall failed" } }
    else { & sc.exe delete $svc; if ($LASTEXITCODE -ne 0) { throw "sc.exe delete failed" } }
  } $DryRun
}
if ($Start) { Invoke-Step "Start service $svc" { Start-Service -Name $svc -ErrorAction Stop } $DryRun }
if ($Stop) { Invoke-Step "Stop service $svc" { Stop-Service -Name $svc -ErrorAction Stop } $DryRun }
if ($Restart) { Invoke-Step "Restart service $svc" { Restart-Service -Name $svc -ErrorAction Stop } $DryRun }
