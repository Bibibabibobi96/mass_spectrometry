[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$OutputDir,
  [Parameter(Mandatory=$true)][string]$GasFieldManifest,
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
$manifestPath=(Resolve-Path -LiteralPath $GasFieldManifest).Path
$simionOutput=Join-Path $output 'simion'
$solver=Join-Path $simionOutput 'solver\simion'
$results=Join-Path $simionOutput 'results'
$log=Join-Path $simionOutput 'simion_fly.log'
if(-not(Test-Path -LiteralPath $SimionExe -PathType Leaf)){throw "SIMION executable is missing: $SimionExe"}

& (Join-Path $PSScriptRoot 'run_c0_gem_smoke.ps1') -OutputDir $simionOutput `
  -SimionExe $SimionExe -PythonExe $python -PaCacheRoot $PaCacheRoot
& (Join-Path $PSScriptRoot 'prepare.ps1') -OutputDir $simionOutput -Mode gas_assisted_transport `
  -GasFieldManifest $manifestPath -SimionExe $SimionExe -PythonExe $python

Copy-Item -LiteralPath (Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\1_instance_seed.iob') `
  -Destination (Join-Path $solver 'dual_cone_tandem.iob') -Force
Copy-Item -LiteralPath (Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\iob_seed_placeholder_01.pa0') `
  -Destination (Join-Path $solver 'iob_seed_placeholder_01.pa0') -Force
Copy-Item -LiteralPath (Join-Path $repoRoot 'common\multipole\build_simion_runtime_iob.lua') `
  -Destination (Join-Path $solver 'build_simion_runtime_iob.lua') -Force

$science=Get-Content -LiteralPath (Join-Path $projectRoot 'config\ion_transport_science.json') -Raw | ConvertFrom-Json
$numerics=Get-Content -LiteralPath (Join-Path $projectRoot 'config\simion_solver_numerics.json') -Raw | ConvertFrom-Json
$resolved=Get-Content -LiteralPath (Join-Path $projectRoot 'config\resolved_geometry.json') -Raw | ConvertFrom-Json
$env:DUAL_CONE_SIMION_RUN_CONFIG_LUA=Join-Path $solver 'run_config.lua'
Push-Location $solver
try{
  & $SimionExe --nogui --noprompt lua build_simion_runtime_iob.lua dual_cone_tandem.iob `
    gas_assisted_transport.lua gas_source.fly2
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
$sourceSpec=Get-Content -LiteralPath (Join-Path $projectRoot 'config\cylindrical_ion_source.json') -Raw | ConvertFrom-Json
$transportMetrics=Join-Path $results 'terminal_plane_metrics.json'
$transmittedStates=Join-Path $results 'terminal_plane_transmitted.csv'
& $python (Join-Path $repoRoot 'common\simion\analyze_terminal_plane.py') `
  --final-state $finalState --source-count ([int]$sourceSpec.particle_count) --pass-code 1 `
  --axis-center-x-mm 25.5 --axis-center-y-mm 25.5 `
  --output $transportMetrics --transmitted-output $transmittedStates
if($LASTEXITCODE-ne 0){throw 'SIMION terminal-plane analysis failed.'}
$metrics=Get-Content -LiteralPath $transportMetrics -Raw | ConvertFrom-Json
$trajectoryPlot=Join-Path $results 'trajectory_rz_projection.png'
& $python (Join-Path $projectRoot 'analysis\plot_simion_trajectory_projection.py') `
  --trajectory $trajectory --final-state $finalState --output $trajectoryPlot
if($LASTEXITCODE-ne 0){throw 'SIMION trajectory projection failed.'}
$gasManifest=Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$report=[ordered]@{
  schema_version=1
  role='dual_cone_gas_field_simion_prototype_report'
  status='PASS'
  claim_scope='n100_cylindrical_source_qualitative_prototype_only'
  trajectory_authority='SIMION'
  collision_model='SIMION official collision_sds'
  gas_field=[ordered]@{
    role=$gasManifest.role
    source=$gasManifest.source
    manifest_path=$manifestPath
    runtime_lua_sha256=$gasManifest.runtime_lua.sha256
  }
  particle_source=[ordered]@{
    role=$sourceSpec.role
    model=$sourceSpec.source_region_model
    particle_count=[int]$sourceSpec.particle_count
    seed=[int]$sourceSpec.seed
    geometry_mm=$sourceSpec.geometry_mm
    velocity_distribution=$sourceSpec.velocity_distribution
  }
  downstream_aperture_plate=$resolved.geometry_mm.downstream_aperture_plate
  terminal_plane_device_z_mm=([double]$resolved.geometry_mm.downstream_aperture_plate.downstream_observation_end_z_mm-0.5*[double]$numerics.pa.cell_mm_xyz.z)
  transport_metrics=$metrics
  trajectory_csv=[IO.Path]::GetFullPath($trajectory)
  final_state_csv=[IO.Path]::GetFullPath($finalState)
  terminal_plane_metrics_json=[IO.Path]::GetFullPath($transportMetrics)
  terminal_plane_transmitted_csv=[IO.Path]::GetFullPath($transmittedStates)
  trajectory_rz_projection_png=[IO.Path]::GetFullPath($trajectoryPlot)
  fly_log=[IO.Path]::GetFullPath($log)
}
$reportPath=Join-Path $output 'prototype_run_report.json'
$report|ConvertTo-Json -Depth 6|Set-Content -LiteralPath $reportPath -Encoding UTF8
Write-Output "DUAL_CONE_GAS_FIELD_PROTOTYPE=PASS REPORT=$reportPath"
