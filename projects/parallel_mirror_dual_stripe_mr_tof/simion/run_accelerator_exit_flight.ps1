[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$CalibratedFocusRunPath,
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Invoke-ProjectPython {
  param([Parameter(Mandatory)][string[]]$Arguments)
  Push-Location -LiteralPath $repoRoot
  $savedPythonPath=$env:PYTHONPATH
  try{
    $env:PYTHONPATH=$repoRoot
    & $python @Arguments
    if($LASTEXITCODE-ne0){throw "Python failed: $($Arguments -join ' ')"}
  }finally{$env:PYTHONPATH=$savedPythonPath;Pop-Location}
}
function Invoke-SimionStage {
  param([Parameter(Mandatory)][string]$Stage,[Parameter(Mandatory)][string[]]$Arguments)
  Push-Location -LiteralPath $solverDir
  try{
    & $simion @Arguments 2>&1|Tee-Object -FilePath (Join-Path $logDir "$Stage.log")
    if($LASTEXITCODE-ne0){throw "SIMION stage failed: $Stage"}
  }finally{Pop-Location}
}
function Get-PublishedFocusInput {
  param([Parameter(Mandatory)][string]$Name,[switch]$RequirePublishedOutput)
  $property=$focusManifest.inputs.PSObject.Properties[$Name]
  if($null-eq$property){throw "calibrated focus manifest lacks input: $Name"}
  $record=$property.Value
  $path=[IO.Path]::GetFullPath([string]$record.path)
  if($RequirePublishedOutput){
    $outputs=@($focusManifest.outputs|Where-Object{
      [string]::Equals([IO.Path]::GetFullPath([string]$_.path),$path,[StringComparison]::OrdinalIgnoreCase)
    })
    if($outputs.Count-ne1-or[string]$outputs[0].sha256-ne[string]$record.sha256-or
        [int64]$outputs[0].bytes-ne[int64]$record.bytes){
      throw "calibrated focus input is not a uniquely published output: $Name"
    }
  }
  return $record
}
function Assert-FileIdentity {
  param([Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)]$Record,[Parameter(Mandatory)][string]$Label)
  if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){throw "$Label is missing: $Path"}
  $item=Get-Item -LiteralPath $Path
  $hash=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
  if([int64]$item.Length-ne[int64]$Record.bytes-or$hash-ne[string]$Record.sha256){
    throw "$Label differs from its calibrated-focus manifest identity: $Path"
  }
}
function Copy-FrozenInput {
  param([Parameter(Mandatory)][string]$Source,[Parameter(Mandatory)][string]$Destination,[Parameter(Mandatory)][string]$Label)
  if(-not(Test-Path -LiteralPath $Source -PathType Leaf)){throw "$Label is missing: $Source"}
  Copy-VerifiedRunInput -Source $Source -Destination $Destination -VerificationAttempts 3
}
function Get-ArtifactPath {
  param([Parameter(Mandatory)][string]$Path)
  $full=[IO.Path]::GetFullPath($Path)
  $execution=[IO.Path]::GetFullPath([string]$package.run_dir).TrimEnd([char[]]@(92,47))
  $artifact=[IO.Path]::GetFullPath([string]$package.artifact_run_dir).TrimEnd([char[]]@(92,47))
  if($full.Equals($execution,[StringComparison]::OrdinalIgnoreCase)){return $artifact}
  if($full.StartsWith($execution+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){
    return $artifact+$full.Substring($execution.Length)
  }
  return $full
}

$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
if(-not(Test-Path -LiteralPath $python -PathType Leaf)){throw "Python executable is missing: $python"}
if(-not(Test-Path -LiteralPath $simion -PathType Leaf)){throw "SIMION executable is missing: $simion"}
$focusRun=(Resolve-Path -LiteralPath $CalibratedFocusRunPath).Path
$focusManifestPath=Join-Path $focusRun 'run_manifest.json'
$focusConfigPath=Join-Path $focusRun 'run_config.json'
$focusSummaryPath=Join-Path $focusRun 'summary.json'
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__simion__mrtof-accelerator-exit-n1'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\simion\short_pa_path_support.ps1')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") -RunId $RunId `
  -Project $projectId -Mode 'accelerator_source_to_safe_exit' -Software @('SIMION 2020','Python 3.11') `
  -RetentionContractEnabled -RetentionClass solver_review `
  -RetentionReason 'N=1 real 5-eV slow source through the first negative-z accelerator exit, with GUI-reviewable unchanged standalone PAs.' `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$logDir=$package.log_dir;$solverDir=Join-Path $runDir 'simion';$runConfig=$package.run_config
$summary=$package.summary;$artifactRoot=Join-Path $workspaceRoot 'artifacts'
$terminalized=$false;$failureStage='preflight';$hostExecutionOutcome='failed';$lease=$null
$paLinkDir=$null
try{
  $lease=Enter-HostExecutionLease -Role SIMION -Stage prepare -RunId $RunId
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $focusManifestPath `
    --require-status success --require-project $projectId --require-mode two_zone_accelerator_first_time_focus `
    --require-local-run-config
  if($LASTEXITCODE-ne0){throw 'calibrated focus run manifest verification failed'}
  $focusManifest=Get-Content -LiteralPath $focusManifestPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 40
  $focusConfig=Get-Content -LiteralPath $focusConfigPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 40
  $focusSummary=Get-Content -LiteralPath $focusSummaryPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 40
  if($focusSummary.status-ne'success'-or$focusSummary.qualification-ne'candidate_prototype_numeric_focus_only'-or
      [int]$focusSummary.particle_count-le0-or[int]$focusSummary.focus_particle_count-ne[int]$focusSummary.particle_count){
    throw 'exit flight requires a complete verified calibrated-focus result'
  }
  if($null-eq$focusSummary.timing.first_order_focus_plane_residual_z_mm){
    throw 'calibrated focus result lacks its finite focus-plane residual'
  }
  $focusResidual=[double]$focusSummary.timing.first_order_focus_plane_residual_z_mm
  if(-not[double]::IsFinite($focusResidual)){throw 'calibrated focus residual must be finite'}

  $paRecords=[ordered]@{
    analyzer=Get-PublishedFocusInput 'standalone_analyzer_pa' -RequirePublishedOutput
    accelerator=Get-PublishedFocusInput 'standalone_accelerator_pa' -RequirePublishedOutput
    detector=Get-PublishedFocusInput 'standalone_detector_pa' -RequirePublishedOutput
  }
  foreach($record in $paRecords.Values){
    if([IO.Path]::GetExtension([string]$record.path)-ine'.pa'){throw 'exit flight accepts direct standalone .pa inputs only'}
    Assert-FileIdentity -Path ([string]$record.path) -Record $record -Label 'upstream standalone PA'
  }
  $baselineRecord=Get-PublishedFocusInput 'baseline_contract'
  $trialRecord=Get-PublishedFocusInput 'trial_contract'
  $reviewedRecord=Get-PublishedFocusInput 'reviewed_contract'
  $operatingPointRecord=Get-PublishedFocusInput 'operating_point' -RequirePublishedOutput
  $voltageMapRecord=Get-PublishedFocusInput 'voltage_map' -RequirePublishedOutput
  $poseRecord=Get-PublishedFocusInput 'resolved_iob_pose' -RequirePublishedOutput
  $focusMaterializationRecord=Get-PublishedFocusInput 'focus_operating_point_materialization' -RequirePublishedOutput
  $upstreamAdapterProperty=$focusManifest.inputs.PSObject.Properties['operating_point_adapter']
  $upstreamAdapterRecord=if($null-ne$upstreamAdapterProperty){$upstreamAdapterProperty.Value}else{$null}
  $calibrationProperty=$focusManifest.inputs.PSObject.Properties['focus_calibration_manifest']
  $calibrationEvidenceRecord=if($null-ne$calibrationProperty){$calibrationProperty.Value}else{$null}

  $analysisSource=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\accelerator_exit_simion_analysis.py'
  $operatingAdapterSource=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\simion_operating_point_variation.py'
  $dependencySources=[ordered]@{
    two_prism_simion_trial=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_simion_trial.py'
    simion_event_analysis=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\simion_event_analysis.py'
    simion_candidate_reference=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\simion_candidate_reference.py'
    accelerator_focus_voltage_trial=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\analysis\accelerator_focus_voltage_trial.py'
    particle_physics=Join-Path $repoRoot 'common\contracts\particle_physics.py'
  }
  $programSource=Join-Path $PSScriptRoot 'mrtof_accelerator_exit.lua'
  $counterSource=Join-Path $PSScriptRoot 'mirror_cycle_counter.lua'
  $builderSource=Join-Path $PSScriptRoot 'build_three_component_iob.lua'
  $launcherSource=Join-Path $PSScriptRoot 'run_iob_flight.lua'
  $particlePolicySource=Join-Path $repoRoot 'common\contracts\particle_count_policy.py'
  $seedSource=Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\3_instance_seed.iob'
  $placeholderSources=1..3|ForEach-Object{Join-Path $repoRoot ('common\simion\assets\iob_instance_seeds\iob_seed_placeholder_{0:D2}.pa0'-f$_)}
  $lightSources=@($focusManifestPath,$focusConfigPath,$focusSummaryPath,$analysisSource,$operatingAdapterSource,$programSource,$counterSource,
    $builderSource,$launcherSource,$particlePolicySource,$seedSource)+$placeholderSources+@([string]$baselineRecord.path,[string]$trialRecord.path,
    [string]$reviewedRecord.path,[string]$operatingPointRecord.path,[string]$voltageMapRecord.path,[string]$poseRecord.path,
    [string]$focusMaterializationRecord.path)+@($dependencySources.Values)
  if($null-ne$calibrationEvidenceRecord){$lightSources+=[string]$calibrationEvidenceRecord.path}
  [int64]$requiredBytes=0
  foreach($path in $lightSources){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "exit-flight input is missing: $path"};$requiredBytes+=(Get-Item -LiteralPath $path).Length}
  # One retained GUI-review copy and one disposable guarded projection coexist
  # until the solver closes, so capacity must cover both byte-identical sets.
  foreach($record in $paRecords.Values){$requiredBytes+=2*[int64]$record.bytes}
  $failureStage='capacity_preflight'
  $startup=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -RequiredHeadroomBytes $requiredBytes -ProtectedPaths @($package.artifact_run_dir,$focusRun)
  $startupPath=Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startupPath -Depth 14 -Value $startup

  $failureStage='freeze_verified_focus_inputs'
  $frozenFocusManifest=Copy-FrozenInput $focusManifestPath (Join-Path $inputDir 'calibrated_focus_run_manifest.json') 'focus manifest'
  $frozenFocusConfig=Copy-FrozenInput $focusConfigPath (Join-Path $inputDir 'calibrated_focus_run_config.json') 'focus config'
  $frozenFocusSummary=Copy-FrozenInput $focusSummaryPath (Join-Path $inputDir 'calibrated_focus_summary.json') 'focus summary'
  $currentContract=Copy-FrozenInput ([string]$baselineRecord.path) (Join-Path $inputDir 'current_contract.json') 'current contract'
  $trialContract=Copy-FrozenInput ([string]$trialRecord.path) (Join-Path $inputDir 'voltage_trial.json') 'voltage trial'
  $reviewedContract=Copy-FrozenInput ([string]$reviewedRecord.path) (Join-Path $inputDir 'reviewed_geometry_contract.json') 'reviewed contract'
  $posePath=Copy-FrozenInput ([string]$poseRecord.path) (Join-Path $inputDir 'resolved_iob_pose.json') 'resolved IOB pose'
  $focusMaterialization=Copy-FrozenInput ([string]$focusMaterializationRecord.path) (Join-Path $inputDir 'focus_operating_point_materialization.json') 'focus operating-point materialization'
  $operatingAdapter=Copy-FrozenInput $operatingAdapterSource (Join-Path $inputDir 'simion_operating_point_variation.py') 'operating-point parser'
  $calibrationEvidence=$null
  if($null-ne$calibrationEvidenceRecord){
    $calibrationEvidence=Copy-FrozenInput ([string]$calibrationEvidenceRecord.path) (Join-Path $inputDir 'focus_calibration_manifest.json') 'optional focus calibration evidence'
  }
  $particlePolicy=Copy-FrozenInput $particlePolicySource (Join-Path $inputDir 'particle_count_policy.py') 'particle-count policy'
  $frozenDependencies=[ordered]@{}
  foreach($name in $dependencySources.Keys){
    $frozenDependencies[$name]=Copy-FrozenInput $dependencySources[$name] (Join-Path $inputDir "$name.py") "$name direct dependency"
  }
  $frozenAnalysis=Copy-FrozenInput $analysisSource (Join-Path $inputDir 'accelerator_exit_simion_analysis.py') 'exit analysis'
  $program=Copy-FrozenInput $programSource (Join-Path $solverDir 'mrtof_accelerator_exit.lua') 'exit flight program'
  $counter=Copy-FrozenInput $counterSource (Join-Path $solverDir 'mrtof_accelerator_exit.mirror_cycle_counter.lua') 'cycle-counter companion'
  $operatingPoint=Copy-FrozenInput ([string]$operatingPointRecord.path) (Join-Path $solverDir 'mrtof_accelerator_exit.operating_point.lua') 'operating sidecar'
  $voltageMap=Copy-FrozenInput ([string]$voltageMapRecord.path) (Join-Path $solverDir 'mrtof_accelerator_exit.voltage_map.lua') 'voltage map'
  $builder=Copy-FrozenInput $builderSource (Join-Path $solverDir 'build_three_component_iob.lua') 'IOB builder'
  $launcher=Copy-FrozenInput $launcherSource (Join-Path $solverDir 'run_iob_flight.lua') 'flight launcher'
  $seed=Copy-FrozenInput $seedSource (Join-Path $solverDir '3_instance_seed.iob') 'IOB seed'
  foreach($index in 1..3){Copy-FrozenInput $placeholderSources[$index-1] (Join-Path $solverDir ('iob_seed_placeholder_{0:D2}.pa0'-f$index)) 'IOB placeholder'|Out-Null}

  $failureStage='validate_diagnostic_particle_count'
  $particleCountCode=@'
import importlib.util,sys
spec=importlib.util.spec_from_file_location("frozen_particle_count_policy",sys.argv[1])
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.validate_positive_particle_count(int(sys.argv[2]))
'@
  Invoke-ProjectPython -Arguments @('-c',$particleCountCode,$particlePolicy,'1')
  $paLinkDir=Join-Path ([IO.Path]::GetTempPath()) ('simion_pa_links_'+[guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $paLinkDir|Out-Null
  $localPas=[ordered]@{}
  foreach($name in @('analyzer','accelerator','detector')){
    $shortPa=New-ShortPaCopy -Source ([string]$paRecords[$name].path) `
      -Destination (Join-Path $paLinkDir "iob_input_$name.pa") -ExpectedBytes ([int64]$paRecords[$name].bytes) `
      -ExpectedSha256 ([string]$paRecords[$name].sha256)
    $destination=Join-Path $solverDir "iob_input_$name.pa"
    $localPas[$name]=Copy-FrozenInput $shortPa $destination "$name standalone PA"
    Assert-FileIdentity -Path $destination -Record $paRecords[$name] -Label "$name run-local standalone PA"
  }

  $sourceFly2Input=Join-Path $inputDir 'accelerator_exit_source.fly2'
  $sourceReceipt=Join-Path $resultDir 'accelerator_exit_source_receipt.json'
  $failureStage='materialize_real_exit_source'
  foreach($name in $dependencySources.Keys){
    if(-not(Test-RunFilesIdentical -Left $dependencySources[$name] -Right $frozenDependencies[$name])){throw "$name changed after its run-local freeze"}
  }
  Invoke-ProjectPython -Arguments @($frozenAnalysis,'materialize','--contract',$currentContract,
    '--reviewed-contract',$reviewedContract,'--voltage-trial',$trialContract,'--fly2',$sourceFly2Input,
    '--receipt',$sourceReceipt)
  $sourceIdentity=Get-Content -LiteralPath $sourceReceipt -Raw -Encoding UTF8|ConvertFrom-Json -Depth 20
  $currentValue=Get-Content -LiteralPath $currentContract -Raw -Encoding UTF8|ConvertFrom-Json -Depth 40
  $contractSlowEnergy=[double]$currentValue.prism_transport.energy_partition.drift_kinetic_energy_ev
  if(-not[double]::IsFinite($contractSlowEnergy)-or$contractSlowEnergy-le0-or
      $sourceIdentity.status-ne'materialized'-or$sourceIdentity.source_particle_count-ne1-or
      [double]$sourceIdentity.source_slow_kinetic_energy_per_charge_v-ne$contractSlowEnergy){
    throw 'exit source must be the one-particle real +y source at the contract slow energy'
  }
  if(@($sourceIdentity.source_direction_project).Count-ne3-or
      [double]$sourceIdentity.source_direction_project[0]-ne0.0-or
      [double]$sourceIdentity.source_direction_project[1]-ne1.0-or
      [double]$sourceIdentity.source_direction_project[2]-ne0.0){
    throw 'exit source direction must be exactly positive project y'
  }
  if([double]$sourceIdentity.selected_axial_energy_per_charge_v-ne[double]$focusSummary.selected_net_gain_center_v){
    throw 'exit source axial energy differs from the calibrated focus result'
  }

  $pose=Get-Content -LiteralPath $posePath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 10
  $origins=@()
  foreach($name in @('analyzer','accelerator','detector')){
    $values=@($pose.origins_mm.$name)
    if($values.Count-ne3){throw "resolved IOB pose lacks the $name origin"}
    foreach($value in $values){
      $numeric=[double]$value
      if(-not[double]::IsFinite($numeric)){throw "resolved $name origin is not finite"}
      $origins+=$numeric.ToString('R',[Globalization.CultureInfo]::InvariantCulture)
    }
  }
  $iob=Join-Path $solverDir 'mrtof_accelerator_exit.iob'
  $failureStage='build_read_only_exit_iob'
  Invoke-SimionStage -Stage 'build_read_only_exit_iob' -Arguments (@('--nogui','--noprompt','lua',$builder,'--',$seed,
    $localPas.analyzer,$localPas.accelerator,$localPas.detector,$iob,$program,$sourceFly2Input)+$origins+@('read_only_voltageized'))
  Write-Host "MRTOF_ACCELERATOR_EXIT_IOB=READY PATH=$(Get-ArtifactPath $iob)"
  $consumedFly2=Join-Path $solverDir 'mrtof_accelerator_exit.fly2'
  if(-not(Test-RunFilesIdentical -Left $sourceFly2Input -Right $consumedFly2)){throw 'IOB companion Fly2 differs from the frozen exit source'}
  $placeholderReceipt=Remove-IobSeedPlaceholderCompanions -Directory $solverDir -Count 3
  $placeholderReceiptPath=Join-Path $resultDir 'iob_placeholder_cleanup.json'
  Write-RunJson -Path $placeholderReceiptPath -Value $placeholderReceipt

  $operatingIdentityPath=Join-Path $resultDir 'operating_point_identity.json'
  $operatingIdentityCode=@'
import importlib.util,json,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location("frozen_simion_operating_point_variation",sys.argv[1])
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Path(sys.argv[3]).write_text(json.dumps(module.load_operating_point(Path(sys.argv[2])),indent=2,sort_keys=True)+"\n",encoding="utf-8")
'@
  Invoke-ProjectPython -Arguments @('-c',$operatingIdentityCode,$operatingAdapter,$operatingPoint,$operatingIdentityPath)
  $operatingIdentity=Get-Content -LiteralPath $operatingIdentityPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 10
  $fullTimeout=[double]$operatingIdentity.full_path_timeout_us
  if(-not[double]::IsFinite($fullTimeout)-or$fullTimeout-le0-or
      [double]$operatingIdentity.trajectory_quality-ne[double]$focusConfig.parameters.trajectory_quality-or
      [double]$operatingIdentity.maximum_step_us-ne[double]$focusConfig.parameters.maximum_step_us){
    throw 'frozen operating sidecar numerics differ from the verified focus profile'
  }
  $config=Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $config.inputs=[ordered]@{
    calibrated_focus_run_manifest=Get-ArtifactPath $frozenFocusManifest
    calibrated_focus_run_config=Get-ArtifactPath $frozenFocusConfig
    calibrated_focus_summary=Get-ArtifactPath $frozenFocusSummary
    standalone_analyzer_pa=Get-ArtifactPath $localPas.analyzer
    standalone_accelerator_pa=Get-ArtifactPath $localPas.accelerator
    standalone_detector_pa=Get-ArtifactPath $localPas.detector
    current_contract=Get-ArtifactPath $currentContract
    voltage_trial=Get-ArtifactPath $trialContract
    reviewed_geometry_contract=Get-ArtifactPath $reviewedContract
    resolved_iob_pose=Get-ArtifactPath $posePath
    focus_operating_point_materialization=Get-ArtifactPath $focusMaterialization
    operating_point_parser=Get-ArtifactPath $operatingAdapter
    particle_count_policy=Get-ArtifactPath $particlePolicy
    operating_point_identity=Get-ArtifactPath $operatingIdentityPath
    operating_point=Get-ArtifactPath $operatingPoint
    voltage_map=Get-ArtifactPath $voltageMap
    source_fly2=Get-ArtifactPath $consumedFly2
    source_receipt=Get-ArtifactPath $sourceReceipt
    flight_program=Get-ArtifactPath $program
    cycle_counter=Get-ArtifactPath $counter
    exit_analysis=Get-ArtifactPath $frozenAnalysis
    iob_builder=Get-ArtifactPath $builder
    flight_launcher=Get-ArtifactPath $launcher
    operating_iob=Get-ArtifactPath $iob
  }
  if($null-ne$calibrationEvidence){$config.inputs.focus_calibration_manifest=Get-ArtifactPath $calibrationEvidence}
  foreach($name in $frozenDependencies.Keys){$config.inputs["direct_dependency_$name"]=Get-ArtifactPath $frozenDependencies[$name]}
  $executedAdapterSha=(Get-FileHash -LiteralPath $operatingAdapter -Algorithm SHA256).Hash
  $upstreamAdapterSha=if($null-ne$upstreamAdapterRecord){[string]$upstreamAdapterRecord.sha256}else{$null}
  $config.parameters=[ordered]@{
    lifecycle_stage='accelerator_source_to_safe_exit'
    particle_count=1
    source_direction_project='+y'
    source_slow_kinetic_energy_per_charge_v=[double]$sourceIdentity.source_slow_kinetic_energy_per_charge_v
    selected_axial_energy_per_charge_v=[double]$sourceIdentity.selected_axial_energy_per_charge_v
    field_and_grid_identity=[ordered]@{
      analyzer=[ordered]@{bytes=[int64]$paRecords.analyzer.bytes;sha256=[string]$paRecords.analyzer.sha256}
      accelerator=[ordered]@{bytes=[int64]$paRecords.accelerator.bytes;sha256=[string]$paRecords.accelerator.sha256}
      detector=[ordered]@{bytes=[int64]$paRecords.detector.bytes;sha256=[string]$paRecords.detector.sha256}
    }
    geometry_identity=[ordered]@{
      reviewed_contract_sha256=[string]$reviewedRecord.sha256
      resolved_iob_pose_sha256=[string]$poseRecord.sha256
    }
    numerics_identity=[ordered]@{
      trajectory_profile_id=[string]$focusConfig.parameters.trajectory_profile_id
      trajectory_quality=[double]$focusConfig.parameters.trajectory_quality
      maximum_step_us=[double]$focusConfig.parameters.maximum_step_us
      full_path_timeout_us=$fullTimeout
      operating_point_sha256=[string]$operatingPointRecord.sha256
      executed_operating_point_parser_sha256=$executedAdapterSha
      upstream_focus_parser_sha256=$upstreamAdapterSha
      parser_matches_upstream_focus=($null-ne$upstreamAdapterSha-and$executedAdapterSha-eq$upstreamAdapterSha)
    }
    voltage_trial_sha256=[string]$trialRecord.sha256
    source_fly2_sha256=[string]$sourceIdentity.inputs.fly2_sha256
    geometry_change='none'
    voltage_change='none'
    refine_performed=$false
  }
  Write-RunJson -Path $runConfig -Depth 20 -Value $config

  foreach($name in @('analyzer','accelerator','detector')){Assert-FileIdentity -Path $localPas[$name] -Record $paRecords[$name] -Label "$name PA before flight"}
  $failureStage='native_accelerator_exit_flight'
  $lease=Update-HostResourceStage -Lease $lease -Stage flight `
    -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
  Invoke-SimionStage -Stage 'native_accelerator_exit_flight' -Arguments @('--nogui','--noprompt','lua',$launcher,$iob)
  $lease=Update-HostResourceStage -Lease $lease -Stage postprocess `
    -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
  foreach($name in @('analyzer','accelerator','detector')){
    Assert-FileIdentity -Path $localPas[$name] -Record $paRecords[$name] -Label "$name PA after flight"
    Assert-FileIdentity -Path ([string]$paRecords[$name].path) -Record $paRecords[$name] -Label "$name upstream PA after flight"
  }
  Remove-ShortPaCopyDirectory -Path $paLinkDir
  $paLinkDir=$null
  $rawLog=Join-Path $logDir 'native_accelerator_exit_flight.log'
  $observationPath=Join-Path $resultDir 'accelerator_exit_observation.json'
  $failureStage='analyze_accelerator_exit'
  foreach($name in $dependencySources.Keys){
    if(-not(Test-RunFilesIdentical -Left $dependencySources[$name] -Right $frozenDependencies[$name])){throw "$name changed before exit analysis"}
  }
  Invoke-ProjectPython -Arguments @($frozenAnalysis,'analyze','--log',$rawLog,'--source-receipt',$sourceReceipt,
    '--output',$observationPath)
  foreach($name in $dependencySources.Keys){
    if(-not(Test-RunFilesIdentical -Left $dependencySources[$name] -Right $frozenDependencies[$name])){throw "$name changed during exit analysis"}
  }
  $observation=Get-Content -LiteralPath $observationPath -Raw -Encoding UTF8|ConvertFrom-Json -Depth 20
  if($observation.status-ne'observed'-or$observation.qualification-ne'source_to_accelerator_exit_diagnostic_only'){
    throw 'accelerator exit analysis did not publish the required observation'
  }
  Write-RunJson -Path $summary -Depth 20 -Value ([ordered]@{
    schema_version=1;role='mrtof_accelerator_source_to_safe_exit';status='success'
    qualification='source_to_accelerator_exit_diagnostic_only';particle_count=1
    accelerator_layout=$observation.accelerator_layout;source_release_state=$observation.source_release_state
    safe_exit_state=$observation.safe_exit_state
    reason='One real +y 5-eV centre ion reached its first measured negative-z accelerator PA exit; no downstream transport claim is made.'
  })
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig (Get-ArtifactPath $runConfig)
  $failureStage='capacity_terminal'
  $maximum=[int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File|Measure-Object Length -Sum).Sum
  $terminal=Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -ProtectedPaths @($package.artifact_run_dir,$focusRun) -KnownMeasuredBytes ([int64]$startup.measured_after_bytes) `
    -MaximumNewArtifactBytes $maximum
  $terminalPath=Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $outputs=@($summary,$rawLog,$observationPath,$sourceReceipt,$operatingIdentityPath,$placeholderReceiptPath,$startupPath,$terminalPath,$retention,
    $iob,$program,$operatingPoint,$voltageMap,$counter,$consumedFly2,$localPas.analyzer,$localPas.accelerator,$localPas.detector)|ForEach-Object{Get-ArtifactPath $_}
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig (Get-ArtifactPath $runConfig) `
    -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  $terminalized=$true;$hostExecutionOutcome='success'
  Write-Host "MRTOF_ACCELERATOR_EXIT_FLIGHT=PASS RUN_ID=$RunId IOB=$(Get-ArtifactPath $iob)"
}catch{
  if(-not$terminalized){
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig (Get-ArtifactPath $runConfig) `
      -Summary (Get-ArtifactPath $summary) -SummaryRole 'mrtof_accelerator_source_to_safe_exit' `
      -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage
    $terminalized=$true
  }
  throw
}finally{
  if($null-ne$paLinkDir-and(Test-Path -LiteralPath $paLinkDir -PathType Container)){
    Remove-ShortPaCopyDirectory -Path $paLinkDir
  }
  if(-not$terminalized-and(Test-Path -LiteralPath $runConfig -PathType Leaf)){
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig (Get-ArtifactPath $runConfig) `
      -Summary (Get-ArtifactPath $summary) -SummaryRole 'mrtof_accelerator_source_to_safe_exit' `
      -Reason 'Runner stopped before terminal evidence publication.' -Software @('SIMION 2020','Python 3.11') `
      -Status interrupted -FailureStage $failureStage
    $hostExecutionOutcome='interrupted'
  }
  if($null-ne$lease){Exit-HostExecutionLease -Lease $lease -Outcome $hostExecutionOutcome -RunId $RunId}
  Remove-RunPackageExecutionAlias -Package $package
}
