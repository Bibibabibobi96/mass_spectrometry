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
$python=if($PythonExe){(Resolve-Path -LiteralPath $PythonExe).Path}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$output=[IO.Path]::GetFullPath($OutputDir)
$simionOutput=Join-Path $output 'simion'
$gasOutput=Join-Path $output 'gas'
$solver=Join-Path $simionOutput 'solver\simion'
$results=Join-Path $simionOutput 'results'
$log=Join-Path $simionOutput 'simion_fly.log'
if(-not(Test-Path -LiteralPath $SimionExe -PathType Leaf)){throw "SIMION executable is missing: $SimionExe"}

& (Join-Path $PSScriptRoot 'run_c0_gem_smoke.ps1') -OutputDir $simionOutput `
  -SimionExe $SimionExe -PythonExe $python -PaCacheRoot $PaCacheRoot
& (Join-Path $PSScriptRoot 'build_uniform_rear_gas_runtime.ps1') -OutputDir $gasOutput -PythonExe $python
& (Join-Path $PSScriptRoot 'prepare.ps1') -OutputDir $simionOutput -Mode gas_assisted_transport `
  -GasFieldManifest (Join-Path $gasOutput 'gas_field_manifest.json') -SimionExe $SimionExe -PythonExe $python

Copy-Item -LiteralPath (Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\1_instance_seed.iob') `
  -Destination (Join-Path $solver 'dual_cone_tandem.iob') -Force
Copy-Item -LiteralPath (Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\iob_seed_placeholder_01.pa0') `
  -Destination (Join-Path $solver 'iob_seed_placeholder_01.pa0') -Force
Copy-Item -LiteralPath (Join-Path $repoRoot 'common\multipole\build_simion_runtime_iob.lua') `
  -Destination (Join-Path $solver 'build_simion_runtime_iob.lua') -Force

$science=Get-Content -LiteralPath (Join-Path $projectRoot 'config\ion_transport_science.json') -Raw | ConvertFrom-Json
$numerics=Get-Content -LiteralPath (Join-Path $projectRoot 'config\simion_solver_numerics.json') -Raw | ConvertFrom-Json
$env:DUAL_CONE_SIMION_RUN_CONFIG_LUA=Join-Path $solver 'run_config.lua'
Push-Location $solver
try{
  & $SimionExe --nogui --noprompt lua build_simion_runtime_iob.lua dual_cone_tandem.iob `
    gas_assisted_transport.lua c0_smoke.fly2
  if($LASTEXITCODE-ne 0){throw 'SIMION runtime IOB build failed.'}
  $flyOutput=& $SimionExe --nogui --noprompt fly `
    --trajectory-quality ([string]$numerics.trajectory.trajectory_quality) `
    --particles dual_cone_tandem.fly2 --programs 1 --retain-trajectories 0 `
    --adjustable "SDS_collision_gas_mass_amu=$($science.gas.collision_gas_mass_amu)" `
    --adjustable "SDS_collision_gas_diameter_nm=$($science.gas.collision_gas_diameter_nm)" `
    --adjustable "SDS_diffusion=$([int][bool]$science.gas.diffusion_enabled)" `
    dual_cone_tandem.iob 2>&1
  $exitCode=$LASTEXITCODE
  $flyOutput | Set-Content -LiteralPath $log -Encoding UTF8
  $flyOutput | Write-Host
  if($exitCode-ne 0){throw "SIMION gas-assisted Fly failed with exit code $exitCode."}
}finally{
  Remove-Item Env:DUAL_CONE_SIMION_RUN_CONFIG_LUA -ErrorAction SilentlyContinue
  Pop-Location
}

$trajectory=Join-Path $results 'trajectory_samples.csv'
$finalState=Join-Path $results 'particle_final_state.csv'
if(-not(Test-Path -LiteralPath $trajectory -PathType Leaf) -or
   -not(Test-Path -LiteralPath $finalState -PathType Leaf)){
  throw 'SIMION Fly completed without the governed trajectory outputs.'
}
$final=Import-Csv -LiteralPath $finalState
if(@($final).Count-ne 1 -or [int]$final[0].splat-ne 1){
  throw 'The prototype ion did not reach the downstream acceptance plane.'
}
$report=[ordered]@{
  schema_version=1
  role='dual_cone_uniform_400pa_simion_prototype_report'
  status='PASS'
  claim_scope='single_ion_qualitative_prototype_only'
  pressure_pa=400.0
  temperature_k=300.0
  prescribed_axial_gas_velocity_m_per_s=100.0
  trajectory_authority='SIMION'
  collision_model='SIMION official collision_sds'
  final_state=$final[0]
  trajectory_csv=[IO.Path]::GetFullPath($trajectory)
  final_state_csv=[IO.Path]::GetFullPath($finalState)
  fly_log=[IO.Path]::GetFullPath($log)
}
$reportPath=Join-Path $output 'prototype_run_report.json'
$report|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $reportPath -Encoding UTF8
Write-Output "DUAL_CONE_UNIFORM_400PA_PROTOTYPE=PASS REPORT=$reportPath"
