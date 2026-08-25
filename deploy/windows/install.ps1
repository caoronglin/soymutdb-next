[CmdletBinding()] param([switch]$DryRun,[switch]$SkipDatabase)
. "$PSScriptRoot/common.ps1"; if(-not $DryRun){Assert-Admin}
$py=Get-Python
$apiRoot=Join-Path $Script:DeployRoot "apps\api"
$venvPython=Join-Path $apiRoot ".venv\Scripts\python.exe"
Invoke-Step "Create API virtual environment" { & $py -m venv (Join-Path $apiRoot ".venv") } $DryRun
Invoke-Step "Install API dependencies" { & $venvPython -m pip install --upgrade pip; & $venvPython -m pip install -e $apiRoot } $DryRun
if(-not $SkipDatabase){
  $db=Get-Setting "DATABASE_URL"
  if($db){Write-Host "Using remote/external DATABASE_URL."} else {Write-Host "PostgreSQL must be installed locally and running as a Windows service (commonly postgresql-x64-*). Set DATABASE_URL for remote PostgreSQL."}
}
Invoke-Step "Run PostgreSQL migrations" { $alembic=Join-Path $apiRoot "alembic.ini"; if(Test-Path $alembic){ Push-Location $apiRoot; try { & $venvPython -m alembic upgrade head } finally { Pop-Location } } else { throw "apps/api/alembic.ini not found" } } $DryRun
Invoke-Step "Install Windows service" { & (Join-Path $PSScriptRoot "service.ps1") -Install -DryRun:$DryRun } $false
