[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$OutputDir,
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path
$python=if($PythonExe){(Resolve-Path -LiteralPath $PythonExe).Path}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$output=[IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Path $output -Force | Out-Null
Push-Location $repoRoot
try{
  & $python -m projects.dual_cone_tandem_quadrupole_ion_interface.analysis.export_uniform_rear_gas_runtime `
    --output-lua (Join-Path $output 'gas_field_runtime.lua') `
    --output-manifest (Join-Path $output 'gas_field_manifest.json')
  if($LASTEXITCODE-ne 0){throw 'Uniform rear-gas runtime compilation failed.'}
}finally{Pop-Location}
