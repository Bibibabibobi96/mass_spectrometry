[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$ComsolRunDirectory,
  [Parameter(Mandatory=$true)][string]$OutputDir,
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

& (Join-Path $PSScriptRoot 'build_gas_runtime.ps1') -ComsolRunDirectory $comsolRun -PythonExe $python
& (Join-Path $PSScriptRoot 'run_gas_field_prototype.ps1') -OutputDir ([IO.Path]::GetFullPath($OutputDir)) `
  -GasFieldManifest (Join-Path $comsolRun 'gas_field_manifest.json') -SimionExe $SimionExe `
  -PythonExe $python -PaCacheRoot $PaCacheRoot
