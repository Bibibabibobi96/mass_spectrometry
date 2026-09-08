[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$TwoPrismOperatingPointRunPath,
  [string]$RunId = '',
  [string]$SimionExe = '',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Copy-RequiredRunInput {
  param([Parameter(Mandatory)][string]$Source,[Parameter(Mandatory)][string]$Destination,[Parameter(Mandatory)][string]$Label)
  if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) { throw "$Label is missing: $Source" }
  Copy-VerifiedRunInput -Source $Source -Destination $Destination
}
function Invoke-MrtofPython {
  param([Parameter(Mandatory)][string[]]$Arguments)
  Push-Location -LiteralPath $repoRoot
  $savedPythonPath = $env:PYTHONPATH
  try {
    $env:PYTHONPATH = $repoRoot
    & $python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "MR-TOF Python failed: $($Arguments -join ' ')" }
  } finally { $env:PYTHONPATH = $savedPythonPath; Pop-Location }
}
function Invoke-MrtofSimionStep {
  param([Parameter(Mandatory)][string]$Stage,[Parameter(Mandatory)][string[]]$Arguments)
  Push-Location -LiteralPath $solverDir
  try {
    & $simion @Arguments 2>&1 | Tee-Object -FilePath (Join-Path $logDir "$Stage.log")
    if ($LASTEXITCODE -ne 0) { throw "SIMION stage failed: $Stage" }
  } finally { Pop-Location }
}

$projectId = 'parallel_mirror_dual_stripe_mr_tof'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
$simion = if ($SimionExe) { [IO.Path]::GetFullPath($SimionExe) } else { Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python executable is missing: $python" }
if (-not (Test-Path -LiteralPath $simion -PathType Leaf)) { throw "SIMION executable is missing: $simion" }

$operatingRun = (Resolve-Path -LiteralPath $TwoPrismOperatingPointRunPath).Path
$operatingManifest = Join-Path $operatingRun 'run_manifest.json'
$operatingSummary = Join-Path $operatingRun 'summary.json'
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $operatingManifest --require-status success `
  --require-project $projectId --require-mode finite_3d_two_prism_operating_point_audit
if ($LASTEXITCODE -ne 0) { throw 'The two-prism operating-point run failed manifest verification.' }
$operating = Get-Content -LiteralPath $operatingSummary -Raw -Encoding UTF8 | ConvertFrom-Json
if ($operating.qualification -ne 'single_center_phase_space_handoff_candidate__K25_pending') {
  throw 'Center flight requires the audited single-center P1/P2 phase-space hand-off candidate.'
}
$finalIteration = @($operating.iterations)[-1]
$finalTrialManifest = (Resolve-Path -LiteralPath ([string]$finalIteration.run_manifest_path).Trim()).Path
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $finalTrialManifest --require-status success `
  --require-project $projectId --require-mode finite_3d_two_prism_voltage_trial
if ($LASTEXITCODE -ne 0) { throw 'The selected final P1/P2 trial failed manifest verification.' }
$finalTrialRun = Split-Path -Parent $finalTrialManifest
$finalTrialSimion = Join-Path $finalTrialRun 'simion'
$finalTrialResults = Join-Path $finalTrialRun 'results'

if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__sim__simion__mrtof-three-component-center-n1'
}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$package = New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'three_component_candidate_center_flight' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass solver_review `
  -RetentionReason 'N=1 complete MR-TOF event-chain evidence; PA0 payloads are reproducible from reviewed families and frozen voltages.' `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir = $package.run_dir
$resultDir = $package.result_dir
$logDir = $package.log_dir
$solverDir = Join-Path $runDir 'simion'
$runConfig = $package.run_config
$summary = $package.summary
$artifactRoot = Join-Path $workspaceRoot 'artifacts'
$terminalized = $false
$failureStage = 'preflight'
$hostExecutionOutcome = 'failed'
$hostExecutionLease = $null

try {
  $sourceFiles = @{
    analyzer = Join-Path $finalTrialSimion 'mrtof_analyzer.pa0'
    accelerator = Join-Path $finalTrialSimion 'mrtof_accelerator.pa0'
    detector = Join-Path $finalTrialSimion 'mrtof_detector.pa#'
    program = Join-Path $PSScriptRoot 'mrtof_candidate.lua'
    counter = Join-Path $PSScriptRoot 'mirror_cycle_counter.lua'
    voltage_map = Join-Path $PSScriptRoot 'candidate_voltage_map.lua'
    fly2 = Join-Path $finalTrialSimion 'mrtof_three_component_candidate.fly2'
    sidecar = Join-Path $finalTrialSimion 'mrtof_three_component_candidate.operating_point.lua'
    selected_contract = Join-Path $finalTrialSimion 'accelerator_focus_voltage_trial.json'
    reviewed_contract = Join-Path $finalTrialSimion 'simion_prototype_contract.json'
    trial_materialization = Join-Path $finalTrialResults 'two_prism_trial_materialization.json'
    iob_builder = Join-Path $PSScriptRoot 'build_three_component_iob.lua'
    iob_seed = Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\3_instance_seed.iob'
    placeholder_1 = Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\iob_seed_placeholder_01.pa0'
    placeholder_2 = Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\iob_seed_placeholder_02.pa0'
    placeholder_3 = Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds\iob_seed_placeholder_03.pa0'
  }
  foreach ($entry in $sourceFiles.GetEnumerator()) {
    if (-not (Test-Path -LiteralPath $entry.Value -PathType Leaf)) { throw "Selected P1/P2 trial lacks $($entry.Key): $($entry.Value)" }
  }
  $failureStage = 'capacity_preflight'
  [int64]$copyBytes = 0
  foreach ($key in @('program','counter','voltage_map','fly2','sidecar','selected_contract','reviewed_contract',
      'trial_materialization','iob_builder','iob_seed','placeholder_1','placeholder_2','placeholder_3')) {
    $copyBytes += [int64](Get-Item -LiteralPath $sourceFiles[$key]).Length
  }
  $startup = Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -RequiredHeadroomBytes $copyBytes -ProtectedPaths @($package.artifact_run_dir)
  $startupPath = Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startupPath -Depth 14 -Value $startup

  $failureStage = 'freeze_operating_assembly'
  foreach ($copy in @(
    @($sourceFiles.program, 'mrtof_three_component_candidate.lua'),
    @($sourceFiles.counter, 'mrtof_three_component_candidate.mirror_cycle_counter.lua'),
    @($sourceFiles.voltage_map, 'mrtof_three_component_candidate.voltage_map.lua'),
    @($sourceFiles.iob_builder, 'build_three_component_iob.lua'),
    @($sourceFiles.iob_seed, '3_instance_seed.iob'),
    @($sourceFiles.placeholder_1, 'iob_seed_placeholder_01.pa0'),
    @($sourceFiles.placeholder_2, 'iob_seed_placeholder_02.pa0'),
    @($sourceFiles.placeholder_3, 'iob_seed_placeholder_03.pa0')
  )) {
    Copy-RequiredRunInput -Source $copy[0] -Destination (Join-Path $solverDir $copy[1]) -Label $copy[1] | Out-Null
  }
  $frozenOperatingSummary = Copy-RequiredRunInput -Source $operatingSummary `
    -Destination (Join-Path $solverDir 'two_prism_operating_point_summary.json') -Label 'two-prism operating-point summary'
  $frozenTrialMaterialization = Copy-RequiredRunInput -Source $sourceFiles.trial_materialization `
    -Destination (Join-Path $solverDir 'two_prism_trial_materialization.json') -Label 'selected P1/P2 trial materialization'
  $frozenSelectedContract = Copy-RequiredRunInput -Source $sourceFiles.selected_contract `
    -Destination (Join-Path $solverDir 'selected_energy_contract.json') -Label 'selected-energy contract'
  $frozenReviewedContract = Copy-RequiredRunInput -Source $sourceFiles.reviewed_contract `
    -Destination (Join-Path $solverDir 'simion_prototype_contract.json') -Label 'reviewed geometry contract'
  $frozenTrialFly2 = Copy-RequiredRunInput -Source $sourceFiles.fly2 `
    -Destination (Join-Path $solverDir 'selected_phase_origin_trial.fly2') -Label 'selected P1/P2 source'
  $frozenTrialSidecar = Copy-RequiredRunInput -Source $sourceFiles.sidecar `
    -Destination (Join-Path $solverDir 'selected_phase_origin_trial.operating_point.lua') -Label 'selected P1/P2 sidecar'
  $launcher = Copy-RequiredRunInput -Source (Join-Path $PSScriptRoot 'run_iob_flight.lua') `
    -Destination (Join-Path $solverDir 'run_iob_flight.lua') -Label 'IOB flight launcher'

  $sourceManifest = Join-Path $solverDir 'prototype_input_manifest.json'
  $fullContract = Join-Path $solverDir 'full_center_contract.json'
  $fullFly2Input = Join-Path $solverDir 'full_center_source.input.fly2'
  $fullFly2 = Join-Path $solverDir 'mrtof_three_component_candidate.fly2'
  $fullSidecar = Join-Path $solverDir 'mrtof_three_component_candidate.operating_point.lua'
  $sourceReceipt = Join-Path $resultDir 'full_center_source_materialization.json'
  $failureStage = 'materialize_full_center_source'
  Invoke-MrtofPython -Arguments @(
    '-m', 'projects.parallel_mirror_dual_stripe_mr_tof.analysis.full_center_source',
    '--operating-point-summary', $frozenOperatingSummary,
    '--selected-contract', $frozenSelectedContract,
    '--trial-materialization', $frozenTrialMaterialization,
    '--trial-fly2', $frozenTrialFly2,
    '--trial-sidecar', $frozenTrialSidecar,
    '--output-contract', $fullContract,
    '--output-fly2', $fullFly2Input,
    '--output-sidecar', $fullSidecar,
    '--output-manifest', $sourceManifest,
    '--output-receipt', $sourceReceipt
  )

  $posePath = Join-Path $resultDir 'resolved_iob_pose.json'
  $poseCode = "import json,sys; from pathlib import Path; from projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry import resolve_split_iob_origins; p=Path(sys.argv[1]); c=json.loads(p.read_text(encoding='utf-8')); Path(sys.argv[2]).write_text(json.dumps({'origins_mm':resolve_split_iob_origins(p),'mesh_mm_per_gu':c['simion']['component_mesh_mm_per_gu']},indent=2)+'\n',encoding='utf-8')"
  Invoke-MrtofPython -Arguments @('-c', $poseCode, $frozenReviewedContract, $posePath)
  $pose = Get-Content -LiteralPath $posePath -Raw -Encoding UTF8 | ConvertFrom-Json
  $originArguments = @()
  foreach ($name in @('analyzer','accelerator','detector')) {
    foreach ($value in @($pose.origins_mm.$name)) {
      $originArguments += [string]::Format([Globalization.CultureInfo]::InvariantCulture, '{0:R}', [double]$value)
    }
  }
  $iob = Join-Path $solverDir 'mrtof_three_component_candidate.iob'
  $upstreamPaHashes = @($sourceFiles.analyzer,$sourceFiles.accelerator,$sourceFiles.detector) | ForEach-Object {
    (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash
  }
  $failureStage = 'build_read_only_iob'
  $hostExecutionLease = Enter-HostExecutionLease -Role SIMION -RunId $RunId
  $buildArguments = @(
    '--nogui','--noprompt','lua',(Join-Path $solverDir 'build_three_component_iob.lua'),'--',
    (Join-Path $solverDir '3_instance_seed.iob'),$sourceFiles.analyzer,$sourceFiles.accelerator,
    $sourceFiles.detector,$iob,(Join-Path $solverDir 'mrtof_three_component_candidate.lua'),$fullFly2Input
  ) + $originArguments + @('read_only_voltageized')
  Invoke-MrtofSimionStep -Stage 'build_read_only_iob' -Arguments $buildArguments
  if (-not (Test-RunFilesIdentical -Left $fullFly2Input -Right $fullFly2)) {
    throw 'IOB companion Fly2 differs from the frozen full-center source.'
  }
  $afterBuildHashes = @($sourceFiles.analyzer,$sourceFiles.accelerator,$sourceFiles.detector) | ForEach-Object {
    (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash
  }
  if (@(Compare-Object $upstreamPaHashes $afterBuildHashes).Count -ne 0) {
    throw 'Read-only IOB binding changed an upstream PA.'
  }

  $configuration = Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
  $configuration.inputs = [ordered]@{
    two_prism_operating_point_run_manifest = $operatingManifest
    selected_final_trial_run_manifest = $finalTrialManifest
    operating_iob = Join-Path $package.artifact_run_dir 'simion\mrtof_three_component_candidate.iob'
    voltageized_analyzer_pa0 = $sourceFiles.analyzer
    calibrated_accelerator_pa0 = $sourceFiles.accelerator
    detector_pa = $sourceFiles.detector
    source_manifest = Join-Path $package.artifact_run_dir 'simion\prototype_input_manifest.json'
    frozen_source_fly2 = Join-Path $package.artifact_run_dir 'simion\full_center_source.input.fly2'
    consumed_fly2 = Join-Path $package.artifact_run_dir 'simion\mrtof_three_component_candidate.fly2'
    flight_program = Join-Path $package.artifact_run_dir 'simion\mrtof_three_component_candidate.lua'
    mirror_cycle_counter = Join-Path $package.artifact_run_dir 'simion\mrtof_three_component_candidate.mirror_cycle_counter.lua'
    voltage_map = Join-Path $package.artifact_run_dir 'simion\mrtof_three_component_candidate.voltage_map.lua'
    iob_builder = Join-Path $package.artifact_run_dir 'simion\build_three_component_iob.lua'
    reviewed_geometry_contract = Join-Path $package.artifact_run_dir 'simion\simion_prototype_contract.json'
    full_center_contract = Join-Path $package.artifact_run_dir 'simion\full_center_contract.json'
  }
  $configuration.parameters = [ordered]@{
    lifecycle_stage = 'single_center_complete_K25_event_chain'
    particle_count = 1
    geometry_change = 'none'
    voltage_change = 'none_from_selected_P1_P2_trial'
    only_execution_change = 'continue_past_drift_phase_origin'
    event_semantics = 'integer_K_same-side-turn_y_samples; coordinate_y0_return_is_diagnostic_only'
    pa_binding_mode = 'read_only_voltageized'
    source_key = 'full_mrtof_center_fly2'
  }
  Write-RunJson -Path $runConfig -Value $configuration

  $failureStage = 'native_center_flight'
  Invoke-MrtofSimionStep -Stage 'native_center_flight' -Arguments @(
    '--nogui','--noprompt','lua',$launcher,(Join-Path $solverDir 'mrtof_three_component_candidate.iob')
  )
  $afterFlightHashes = @($sourceFiles.analyzer,$sourceFiles.accelerator,$sourceFiles.detector) | ForEach-Object {
    (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash
  }
  if (@(Compare-Object $upstreamPaHashes $afterFlightHashes).Count -ne 0) {
    throw 'Center flight changed a read-only upstream PA.'
  }
  $rawLog = Join-Path $logDir 'native_center_flight.log'
  $eventAnalysis = Join-Path $resultDir 'center_event_analysis.json'
  $failureStage = 'event_analysis'
  Invoke-MrtofPython -Arguments @(
    '-m', 'projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis',
    $rawLog, $eventAnalysis, '--input-manifest', $sourceManifest, '--source-key', 'full_mrtof_center_fly2'
  )
  $observed = Get-Content -LiteralPath $eventAnalysis -Raw -Encoding UTF8 | ConvertFrom-Json
  Write-RunJson -Path $summary -Depth 14 -Value ([ordered]@{
    schema_version = 1
    role = 'mrtof_three_component_candidate_center_flight'
    status = 'success'
    qualification = 'candidate_prototype_event_chain_only'
    particle_count = 1
    event_integrity_passed = [bool]$observed.event_integrity_passed
    detector_hit_count = $observed.detector_hit_count
    target_k = $observed.target_k
    target_k_count = $observed.target_k_count
    target_k_phase_sample_count = $observed.target_k_phase_sample_count
    target_k_phase_y_residuals_mm = $observed.target_k_phase_y_residuals_mm
    overtone_histogram = $observed.overtone_histogram
    slow_drift_abs_lengths_from_y0_mm = $observed.slow_drift_abs_lengths_from_y0_mm
    drift_phase_candidate_count = $observed.drift_phase_candidate_count
    drift_coordinate_return_diagnostics = $observed.drift_coordinate_return_diagnostics
    electrode_collision_count = $observed.electrode_collision_count
    full_path_timeout_count = $observed.full_path_timeout_count
    reason = 'One P1/P2-audited center source was continued through its complete terminal event chain; no bundle or resolution claim is made.'
  })
  $retention = Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage = 'capacity_terminal'
  $maximum = [int64](Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File | Measure-Object Length -Sum).Sum
  $terminal = Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -ProtectedPaths @($package.artifact_run_dir) -KnownMeasuredBytes ([int64]$startup.measured_after_bytes) `
    -MaximumNewArtifactBytes $maximum
  $terminalPath = Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('SIMION 2020','Python 3.11') `
    -Outputs @($summary,$rawLog,$eventAnalysis,$sourceReceipt,$startupPath,$terminalPath,$retention)
  $terminalized = $true
  $hostExecutionOutcome = 'success'
  Write-Host "MRTOF_THREE_COMPONENT_CENTER_FLIGHT=PASS RUN_ID=$RunId TARGET_K_COUNT=$($observed.target_k_count) DETECTOR=$($observed.detector_hit_count)"
} catch {
  if (-not $terminalized) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_three_component_candidate_center_flight' -Reason $_.Exception.Message `
      -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage
    $terminalized = $true
  }
  throw
} finally {
  if (-not $terminalized -and (Test-Path -LiteralPath $runConfig -PathType Leaf)) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_three_component_candidate_center_flight' `
      -Reason 'Runner stopped before terminal evidence publication.' -Software @('SIMION 2020','Python 3.11') `
      -Status interrupted -FailureStage $failureStage
    $hostExecutionOutcome = 'interrupted'
  }
  if ($null -ne $hostExecutionLease) {
    Exit-HostExecutionLease -Lease $hostExecutionLease -Outcome $hostExecutionOutcome -RunId $RunId
  }
  Remove-RunPackageExecutionAlias -Package $package
}
