[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$OutputDir,
  [ValidateSet('c0_gem_smoke','gas_assisted_transport')][string]$Mode='gas_assisted_transport',
  [string]$GasFieldManifest='',
  [string]$SimionExe='C:\Program Files\SIMION-2020\simion.exe',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path
$python=if($PythonExe){(Resolve-Path -LiteralPath $PythonExe).Path}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$arguments=@('-m','projects.dual_cone_tandem_quadrupole_ion_interface.simion.prepare','--output-dir',[IO.Path]::GetFullPath($OutputDir),'--mode',$Mode)
if(Test-Path -LiteralPath $SimionExe -PathType Leaf){$arguments+=@('--simion-exe',[IO.Path]::GetFullPath($SimionExe))}
if($Mode -eq 'gas_assisted_transport'){
  if(-not(Test-Path -LiteralPath $SimionExe -PathType Leaf)){throw "SIMION executable is missing: $SimionExe"}
  if([string]::IsNullOrWhiteSpace($GasFieldManifest)){throw 'Gas-assisted preparation requires -GasFieldManifest.'}
  $sdsDir=Join-Path (Split-Path -Parent (Split-Path -Parent $SimionExe)) 'SIMION-2020\examples\collision_sds'
  if(-not(Test-Path -LiteralPath $sdsDir -PathType Container)){
    $sdsDir=Join-Path (Split-Path -Parent $SimionExe) 'examples\collision_sds'
  }
  $arguments+=@('--gas-field-manifest',[IO.Path]::GetFullPath($GasFieldManifest),'--collision-sds-dir',$sdsDir)
}
Push-Location $repoRoot
try{
  & $python @arguments
  if($LASTEXITCODE-ne 0){throw "Dual-cone SIMION preparation failed for mode '$Mode'."}
}finally{Pop-Location}
