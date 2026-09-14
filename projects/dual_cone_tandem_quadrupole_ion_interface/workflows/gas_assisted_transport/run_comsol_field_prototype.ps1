[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$ComsolRunDirectory,
  [Parameter(Mandatory=$true)][string]$RunId,
  [string]$SimionExe='C:\Program Files\SIMION-2020\simion.exe',
  [string]$PythonExe='',
  [string]$PaCacheRoot=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path
$python=if($PythonExe){(Resolve-Path -LiteralPath $PythonExe).Path}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$comsolRun=(Resolve-Path -LiteralPath $ComsolRunDirectory).Path

$gasOutput=Join-Path ([IO.Path]::GetTempPath()) ("dual-cone-comsol-field-"+[guid]::NewGuid().ToString('N'))
try{
  & (Join-Path $PSScriptRoot 'build_gas_runtime.ps1') -ComsolRunDirectory $comsolRun `
    -OutputDir $gasOutput -PythonExe $python
  & (Join-Path $PSScriptRoot 'run_gas_field_prototype.ps1') -RunId $RunId `
    -GasFieldManifest (Join-Path $gasOutput 'gas_field_manifest.json') -SimionExe $SimionExe `
    -PythonExe $python -PaCacheRoot $PaCacheRoot
}finally{
  if(Test-Path -LiteralPath $gasOutput -PathType Container){Remove-Item -LiteralPath $gasOutput -Recurse -Force}
}
