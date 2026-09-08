[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$OutputDir,
  [string]$SimionExe='C:\Program Files\SIMION-2020\simion.exe',
  [string]$PythonExe='',
  [string]$PaCacheRoot=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path
if(-not(Test-Path -LiteralPath $SimionExe -PathType Leaf)){throw "SIMION executable is missing: $SimionExe"}
$python=if($PythonExe){(Resolve-Path -LiteralPath $PythonExe).Path}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$cacheRoot=if($PaCacheRoot){[IO.Path]::GetFullPath($PaCacheRoot)}else{Join-Path (Split-Path -Parent $repoRoot) 'artifacts\common\simion\pa_family_cache'}
$output=[IO.Path]::GetFullPath($OutputDir)
& (Join-Path $PSScriptRoot 'prepare.ps1') -OutputDir $output -Mode c0_gem_smoke -SimionExe $SimionExe -PythonExe $python
if($LASTEXITCODE-ne 0){throw 'C0 input preparation failed.'}
$solverDir=Join-Path $output 'solver\simion'
$required=@('dual_cone_tandem.pa#','dual_cone_tandem.pa0','dual_cone_tandem.pa1','dual_cone_tandem.pa2','dual_cone_tandem.pa11','dual_cone_tandem.pa12','dual_cone_tandem.pa21','dual_cone_tandem.pa22')
$inventory=($required+@('dual_cone_tandem.pa-surf')) -join ','
$identity=Join-Path $output 'input\pa_cache_identity.json'
Push-Location $repoRoot
try{
  $probeText=& $python -m common.simion.pa_family_cache --action probe --cache-root $cacheRoot --identity $identity --filenames $inventory
  if($LASTEXITCODE-ne 0){throw 'SIMION PA cache probe failed.'}
  $probe=($probeText -join "`n")|ConvertFrom-Json
  if($probe.disposition -eq 'hit'){
    & $python -m common.simion.pa_family_cache --action materialize --cache-root $cacheRoot --identity $identity --filenames $inventory --destination-directory $solverDir | Out-Null
    if($LASTEXITCODE-ne 0){throw 'SIMION PA cache materialization failed.'}
  }else{
    Push-Location $solverDir
    try{
      & $SimionExe --nogui --noprompt gem2pa dual_cone_tandem.gem dual_cone_tandem.pa#
      if($LASTEXITCODE-ne 0){throw 'SIMION gem2pa failed.'}
      & $SimionExe --nogui --noprompt refine dual_cone_tandem.pa#
      if($LASTEXITCODE-ne 0){throw 'SIMION refine failed.'}
    }finally{Pop-Location}
    & $python -m common.simion.pa_family_cache --action publish --cache-root $cacheRoot --identity $identity --filenames $inventory --source-directory $solverDir | Out-Null
    if($LASTEXITCODE-ne 0){throw 'SIMION PA cache publication failed.'}
  }
}finally{Pop-Location}
$missing=@($required|Where-Object{-not(Test-Path -LiteralPath (Join-Path $solverDir $_) -PathType Leaf)})
if($missing.Count-gt 0){throw "C0 PA family is incomplete: $($missing -join ', ')"}
Write-Output "DUAL_CONE_SIMION_C0_GEM_SMOKE=PASS OUTPUT=$output"
