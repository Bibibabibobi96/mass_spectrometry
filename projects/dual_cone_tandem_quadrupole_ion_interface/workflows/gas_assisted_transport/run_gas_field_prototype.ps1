[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$RunId,
  [Parameter(Mandatory=$true)][string]$GasFieldManifest,
  [string]$SimionExe='C:\Program Files\SIMION-2020\simion.exe',
  [string]$PythonExe='',
  [string]$PaCacheRoot=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='dual_cone_tandem_quadrupole_ion_interface'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$manifestPath=(Resolve-Path -LiteralPath $GasFieldManifest).Path
if(-not(Test-Path -LiteralPath $SimionExe -PathType Leaf)){throw "SIMION executable is missing: $SimionExe"}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'gas_field_driven_simion_transport' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -AdditionalDirectories @('simion') `
  -UseShortExecutionPath
$runDir=$package.run_dir
$resultDir=$package.result_dir
$logDir=$package.log_dir
$simionOutput=Join-Path $runDir 'simion'
$solver=Join-Path $simionOutput 'solver\simion'
$simionResults=Join-Path $simionOutput 'results'
$log=Join-Path $logDir 'simion_fly.log'
$failureStage='freeze_inputs'
$terminalized=$false
$lease=$null
$hostOutcome='failed'

try{
  $failureStage='capacity_preflight'
  $capacityStartup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -ProtectedPaths @($package.artifact_run_dir)
  $capacityStartupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $capacityStartupPath -Value $capacityStartup -Depth 14
  $failureStage='freeze_inputs'
  $sourceGasManifest=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
  $sourceGasRuntime=(Resolve-Path -LiteralPath ([string]$sourceGasManifest.runtime_lua.path)).Path
  $frozenGasRuntime=Copy-VerifiedRunInput -Source $sourceGasRuntime `
    -Destination (Join-Path $package.input_dir 'gas_field_runtime.lua')
  $sourceGasManifest.runtime_lua.path=Join-Path $package.artifact_run_dir 'inputs\gas_field_runtime.lua'
  $frozenGasManifest=Join-Path $package.input_dir 'gas_field_manifest.json'
  Write-RunJson -Path $frozenGasManifest -Value $sourceGasManifest -Depth 12
  $failureStage='simion_geometry_preflight'
  & (Join-Path $PSScriptRoot 'run_c0_gem_smoke.ps1') -OutputDir $simionOutput `
    -SimionExe $SimionExe -PythonExe $python -PaCacheRoot $PaCacheRoot
  $lease=Enter-HostExecutionLease -Role SIMION -Stage prepare -RunId $RunId
  & (Join-Path $PSScriptRoot 'prepare.ps1') -OutputDir $simionOutput -Mode gas_assisted_transport `
    -GasFieldManifest $frozenGasManifest -SimionExe $SimionExe -PythonExe $python

  Copy-VerifiedRunInput -Source (Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\1_instance_seed.iob') `
    -Destination (Join-Path $solver 'dual_cone_tandem.iob')|Out-Null
  Copy-VerifiedRunInput -Source (Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\iob_seed_placeholder_01.pa0') `
    -Destination (Join-Path $solver 'iob_seed_placeholder_01.pa0')|Out-Null
  Copy-VerifiedRunInput -Source (Join-Path $repoRoot 'common\multipole\build_simion_runtime_iob.lua') `
    -Destination (Join-Path $solver 'build_simion_runtime_iob.lua')|Out-Null

  $science=Get-Content -LiteralPath (Join-Path $projectRoot 'config\ion_transport_science.json') -Raw|ConvertFrom-Json
  $numerics=Get-Content -LiteralPath (Join-Path $projectRoot 'config\simion_solver_numerics.json') -Raw|ConvertFrom-Json
  $resolved=Get-Content -LiteralPath (Join-Path $projectRoot 'config\resolved_geometry.json') -Raw|ConvertFrom-Json
  $sourceSpec=Get-Content -LiteralPath (Join-Path $projectRoot 'config\cylindrical_ion_source.json') -Raw|ConvertFrom-Json
  $offsets=$numerics.workbench.coordinate_mapping.device_to_workbench_offset_mm
  $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{
    gas_field_manifest=(Join-Path $package.artifact_run_dir 'inputs\gas_field_manifest.json')
    preparation_receipt=(Join-Path $package.artifact_run_dir 'simion\preparation_receipt.json')
    resolved_geometry=(Join-Path $package.artifact_run_dir 'simion\input\resolved_geometry.json')
    ion_transport_science=(Join-Path $package.artifact_run_dir 'simion\input\ion_transport_science.json')
    simion_solver_numerics=(Join-Path $package.artifact_run_dir 'simion\input\simion_solver_numerics.json')
    particle_source=(Join-Path $package.artifact_run_dir 'simion\input\cylindrical_ion_source.json')
  }
  $configuration.parameters=[ordered]@{
    lifecycle_stage='prepared_for_native_simion_fly'
    evidence_scope='unqualified_qualitative_prototype'
    trajectory_authority='SIMION'
    collision_model='SIMION official collision_sds'
    particle_count=[int]$sourceSpec.particle_count
    default_diagnostic_plot=$true
  }
  Write-RunJson -Path $package.run_config -Value $configuration -Depth 12

  $failureStage='native_simion_fly'
  $env:DUAL_CONE_SIMION_RUN_CONFIG_LUA=Join-Path $solver 'run_config.lua'
  Push-Location $solver
  try{
    & $SimionExe --nogui --noprompt lua build_simion_runtime_iob.lua dual_cone_tandem.iob `
      gas_assisted_transport.lua gas_source.fly2
    if($LASTEXITCODE-ne 0){throw 'SIMION runtime IOB build failed.'}
    $lease=Update-HostResourceStage -Lease $lease -Stage flight `
      -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
    $flyOutput=& $SimionExe --nogui --noprompt fly `
      --trajectory-quality ([string]$numerics.trajectory.trajectory_quality) `
      --particles dual_cone_tandem.fly2 --programs 1 --retain-trajectories 0 `
      --adjustable "SDS_collision_gas_mass_amu=$($science.gas.collision_gas_mass_amu)" `
      --adjustable "SDS_collision_gas_diameter_nm=$($science.gas.collision_gas_diameter_nm)" `
      --adjustable "SDS_diffusion=$([int][bool]$science.gas.diffusion_enabled)" `
      dual_cone_tandem.iob 2>&1
    $exitCode=$LASTEXITCODE
    $flyOutput|Set-Content -LiteralPath $log -Encoding UTF8
    $flyOutput|Write-Host
    if($exitCode-ne 0){throw "SIMION gas-assisted Fly failed with exit code $exitCode."}
  }finally{
    Remove-Item Env:DUAL_CONE_SIMION_RUN_CONFIG_LUA -ErrorAction SilentlyContinue
    Pop-Location
  }

  $lease=Update-HostResourceStage -Lease $lease -Stage postprocess `
    -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
  $trajectory=Join-Path $simionResults 'trajectory_samples.csv'
  $finalState=Join-Path $simionResults 'particle_final_state.csv'
  if(-not(Test-Path -LiteralPath $trajectory -PathType Leaf)-or-not(Test-Path -LiteralPath $finalState -PathType Leaf)){
    throw 'SIMION Fly completed without the governed trajectory outputs.'
  }
  $failureStage='analysis'
  $transportMetrics=Join-Path $resultDir 'terminal_plane_metrics.json'
  $transmittedStates=Join-Path $resultDir 'terminal_plane_transmitted.csv'
  & $python (Join-Path $repoRoot 'common\simion\analyze_terminal_plane.py') `
    --final-state $finalState --source-count ([int]$sourceSpec.particle_count) --pass-code 1 `
    --axis-center-x-mm ([double]$offsets.x) --axis-center-y-mm ([double]$offsets.y) `
    --output $transportMetrics --transmitted-output $transmittedStates
  if($LASTEXITCODE-ne 0){throw 'SIMION terminal-plane analysis failed.'}
  $trajectoryPlot=Join-Path $resultDir 'trajectory_rz_projection.png'
  & $python (Join-Path $projectRoot 'analysis\plot_simion_trajectory_projection.py') `
    --trajectory $trajectory --final-state $finalState --output $trajectoryPlot
  if($LASTEXITCODE-ne 0){throw 'SIMION trajectory projection failed.'}
  $metrics=Get-Content -LiteralPath $transportMetrics -Raw|ConvertFrom-Json
  $gasManifest=Get-Content -LiteralPath $frozenGasManifest -Raw|ConvertFrom-Json
  $reportPath=Join-Path $resultDir 'prototype_run_report.json'
  $report=[ordered]@{
    schema_version=1;role='dual_cone_gas_field_simion_prototype_report';status='PASS'
    claim_scope='n100_cylindrical_source_qualitative_prototype_only'
    trajectory_authority='SIMION';collision_model='SIMION official collision_sds'
    electric_field=$science.electric_field
    gas_field=[ordered]@{role=$gasManifest.role;source=$gasManifest.source;runtime_lua_sha256=$gasManifest.runtime_lua.sha256}
    particle_source=[ordered]@{role=$sourceSpec.role;model=$sourceSpec.source_region_model;particle_count=[int]$sourceSpec.particle_count;seed=[int]$sourceSpec.seed;geometry_mm=$sourceSpec.geometry_mm;velocity_distribution=$sourceSpec.velocity_distribution}
    downstream_aperture_plate=$resolved.geometry_mm.downstream_aperture_plate
    terminal_plane_device_z_mm=([double]$resolved.geometry_mm.downstream_aperture_plate.downstream_observation_end_z_mm-0.5*[double]$numerics.pa.cell_mm_xyz.z)
    terminal_code_definitions=[ordered]@{'0'='SIMION native geometry or otherwise unclassified splat';'1'='reached governed terminal plane';'2'='maximum flight time reached';'3'='left validated gas-field fluid support'}
    transport_metrics=$metrics
  }
  Write-RunJson -Path $reportPath -Value $report -Depth 12
  Write-RunJson -Path $package.summary -Value ([ordered]@{
    schema_version=1;role='dual_cone_gas_field_simion_transport_summary';status='success'
    evidence_scope='unqualified_qualitative_prototype';particle_count=[int]$sourceSpec.particle_count
    transport_metrics=$metrics;gas_source_kind=$gasManifest.source.kind
    default_diagnostic_plot=(Join-Path $package.artifact_run_dir 'results\trajectory_rz_projection.png')
  }) -Depth 12
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot `
    -RunConfig $package.run_config
  $capacityTerminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -ProtectedPaths @($package.artifact_run_dir)
  $capacityTerminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $capacityTerminalPath -Value $capacityTerminal -Depth 14
  $outputs=@($package.summary,$reportPath,$transportMetrics,$transmittedStates,$trajectoryPlot,$log,$retention,$capacityStartupPath,$capacityTerminalPath)
  foreach($optional in @($trajectory,$finalState,(Join-Path $simionOutput 'preparation_receipt.json'))){
    if(Test-Path -LiteralPath $optional -PathType Leaf){$outputs+=$optional}
  }
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  $terminalized=$true
  $hostOutcome='success'
  Write-Output "DUAL_CONE_GAS_FIELD_PROTOTYPE=PASS RUN=$($package.artifact_run_dir)"
}catch{
  if(-not$terminalized){
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config `
      -Summary $package.summary -SummaryRole 'dual_cone_gas_field_simion_transport_summary' `
      -Reason $_.Exception.Message -FailureStage $failureStage `
      -Software @('SIMION 2020','Python 3.11')
    $terminalized=$true
  }
  throw
}finally{
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostOutcome -RunId $RunId}
  Remove-RunPackageExecutionAlias -Package $package
}
