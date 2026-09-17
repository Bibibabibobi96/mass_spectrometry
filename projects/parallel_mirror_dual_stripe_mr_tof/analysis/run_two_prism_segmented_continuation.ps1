[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$CoverageRunManifest,
  [Parameter(Mandatory)][string]$ExpectedTopologySignatureSha256,
  [ValidateSet('angle_then_y','y_then_angle_diagnostic')][string]$SolveMode = 'angle_then_y',
  [Parameter(Mandatory)][double]$InitialP1V,
  [Parameter(Mandatory)][double]$InitialP2LowerV,
  [Parameter(Mandatory)][double]$InitialP2UpperV,
  [Parameter(Mandatory)][double]$P1MinimumV,
  [Parameter(Mandatory)][double]$P1MaximumV,
  [Parameter(Mandatory)][double]$P2MinimumV,
  [Parameter(Mandatory)][double]$P2MaximumV,
  [Parameter(Mandatory)][double]$AngleToleranceDeg,
  [Parameter(Mandatory)][double]$PositiveMirrorTurnYToleranceMm,
  [Parameter(Mandatory)][double]$P2RootToleranceV,
  [Parameter(Mandatory)][double]$InitialP1StepV,
  [Parameter(Mandatory)][double]$MinimumP1StepV,
  [Parameter(Mandatory)][double]$MaximumP1StepV,
  [Parameter(Mandatory)][double]$P1StepGrowthFactor,
  [Parameter(Mandatory)][double]$P2InitialHalfWidthV,
  [Parameter(Mandatory)][double]$P2BracketExpansionFactor,
  [Parameter(Mandatory)][int]$P2BracketMaximumExpansions,
  [Parameter(Mandatory)][int]$MaximumInnerIterations,
  [Parameter(Mandatory)][int]$MaximumOuterIterations,
  [Parameter(Mandatory)][int]$MaximumTransportEvaluations,
  [Parameter(Mandatory)][int]$MaximumNodesPerDirection,
  [Parameter(Mandatory)][double]$RelativeTolerance,
  [Parameter(Mandatory)][double]$AbsoluteTolerance,
  [Parameter(Mandatory)][double]$MaximumStepMmPerSqrtV,
  [Parameter(Mandatory)][int]$EventSamplesPerStep,
  [Parameter(Mandatory)][double]$RootTimeToleranceMmPerSqrtV,
  [Parameter(Mandatory)][double]$BoundaryRootToleranceMm,
  [Parameter(Mandatory)][double]$MomentumToleranceSqrtV,
  [Parameter(Mandatory)][double]$NormalEnergyToleranceV,
  [Parameter(Mandatory)][int]$MaximumSteps,
  [Parameter(Mandatory)][double]$StageAMaximumReducedTimeMmPerSqrtV,
  [Parameter(Mandatory)][double]$StageBMaximumReducedTimeMmPerSqrtV,
  [string]$RunId = '',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectId = 'parallel_mirror_dual_stripe_mr_tof'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python 3.11 environment is missing: $python" }
$coverageManifest = (Resolve-Path -LiteralPath $CoverageRunManifest).Path
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__analysis__python__mrtof-two-prism-segmented-continuation'
}

. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$package = New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'two_prism_segmented_voltage_branch_continuation' `
  -Software @('Python 3.11', 'SciPy') -RetentionContractEnabled -RetentionClass compact
$runConfig = $package.run_config
$summary = $package.summary
$inputDir = $package.input_dir
$resultDir = $package.result_dir
$logDir = $package.log_dir
$terminalized = $false
$failureStage = 'preflight'

function Invoke-ProjectPython {
  param([Parameter(Mandatory)][string[]]$Arguments, [Parameter(Mandatory)][string]$LogPath)
  Push-Location -LiteralPath $repoRoot
  $savedPythonPath = $env:PYTHONPATH
  $savedOpenBlasThreads = $env:OPENBLAS_NUM_THREADS
  $savedOmpThreads = $env:OMP_NUM_THREADS
  $savedMklThreads = $env:MKL_NUM_THREADS
  $savedNumExprThreads = $env:NUMEXPR_NUM_THREADS
  try {
    $env:PYTHONPATH = $repoRoot
    $env:OPENBLAS_NUM_THREADS = '1'
    $env:OMP_NUM_THREADS = '1'
    $env:MKL_NUM_THREADS = '1'
    $env:NUMEXPR_NUM_THREADS = '1'
    & $python @Arguments 2>&1 | Tee-Object -FilePath $LogPath
    if ($LASTEXITCODE -ne 0) { throw "MR-TOF continuation stage failed: $($Arguments -join ' ')" }
  } finally {
    $env:PYTHONPATH = $savedPythonPath
    $env:OPENBLAS_NUM_THREADS = $savedOpenBlasThreads
    $env:OMP_NUM_THREADS = $savedOmpThreads
    $env:MKL_NUM_THREADS = $savedMklThreads
    $env:NUMEXPR_NUM_THREADS = $savedNumExprThreads
    Pop-Location
  }
}

try {
  $failureStage = 'capacity_startup'
  $startup = Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') `
    -ProtectedPaths @($package.artifact_run_dir, (Split-Path -Parent $coverageManifest)) `
    -RequiredHeadroomBytes 1048576
  $startupPath = Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startupPath -Depth 14 -Value $startup

  $failureStage = 'verify_parent_coverage'
  $verifyLog = Join-Path $logDir 'coverage_manifest_verification.log'
  Invoke-ProjectPython -Arguments @(
    '-m', 'common.contracts.verify_run_manifest', $coverageManifest,
    '--require-status', 'success', '--require-project', $projectId
  ) -LogPath $verifyLog
  $coverageRun = Get-Content -LiteralPath $coverageManifest -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
  if (
    $coverageRun.mode -ne 'two_prism_segmented_voltage_branch_coverage' -or
    $coverageRun.status -ne 'success' -or
    -not ($coverageRun.inputs -is [hashtable])
  ) {
    throw 'Parent run must be a successful two-prism segmented coverage run.'
  }
  $contractRecord = Get-VerifiedRunManifestInputRecord -Records $coverageRun.inputs -Name 'downstream_contract' -Label 'contract'
  $fixedMode = $coverageRun.inputs.ContainsKey('parent_fixed_mirror_stripe_run_manifest')
  if ($fixedMode) {
    $fixedMirrorStripeRecord = Get-VerifiedRunManifestInputRecord -Records $coverageRun.inputs -Name 'parent_fixed_mirror_stripe_run_manifest' -Label 'fixed mirror/Stripe manifest'
  } else {
    $exactRecord = Get-VerifiedRunManifestInputRecord -Records $coverageRun.inputs -Name 'parent_exact_k_run_manifest' -Label 'exact-K manifest'
    $stripeRecord = Get-VerifiedRunManifestInputRecord -Records $coverageRun.inputs -Name 'parent_stripe_seed_run_manifest' -Label 'Stripe manifest'
  }
  $observationRecord = Get-VerifiedRunManifestInputRecord -Records $coverageRun.inputs -Name 'accelerator_exit_observation' -Label 'accelerator observation'
  $sourceReceiptRecord = Get-VerifiedRunManifestInputRecord -Records $coverageRun.inputs -Name 'accelerator_exit_source_receipt' -Label 'accelerator source receipt'
  $coverageSummaryRecords = @(
    $coverageRun.outputs | Where-Object { [IO.Path]::GetFileName([string]$_.path) -eq 'summary.json' }
  )
  if ($coverageSummaryRecords.Count -ne 1 -or -not $coverageSummaryRecords[0].exists) {
    throw 'Coverage manifest must declare exactly one existing summary.json output.'
  }

  $failureStage = 'freeze_inputs'
  $frozenCoverageManifest = Copy-VerifiedRunInput -Source $coverageManifest -Destination (Join-Path $inputDir 'parent_coverage_run_manifest.json')
  $frozenCoverageSummary = Copy-VerifiedRunInput -Source ([string]$coverageSummaryRecords[0].path) -Destination (Join-Path $inputDir 'parent_coverage_summary.json')
  $frozenContract = Copy-VerifiedRunInput -Source ([string]$contractRecord.path) -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
  if ($fixedMode) {
    $frozenFixedMirrorStripe = Copy-VerifiedRunInput -Source ([string]$fixedMirrorStripeRecord.path) -Destination (Join-Path $inputDir 'parent_fixed_mirror_stripe_run_manifest.json')
  } else {
    $frozenExact = Copy-VerifiedRunInput -Source ([string]$exactRecord.path) -Destination (Join-Path $inputDir 'parent_exact_k_run_manifest.json')
    $frozenStripe = Copy-VerifiedRunInput -Source ([string]$stripeRecord.path) -Destination (Join-Path $inputDir 'parent_stripe_seed_run_manifest.json')
  }
  $frozenObservation = Copy-VerifiedRunInput -Source ([string]$observationRecord.path) -Destination (Join-Path $inputDir 'accelerator_exit_observation.json')
  $frozenExitSourceReceipt = Copy-VerifiedRunInput -Source ([string]$sourceReceiptRecord.path) -Destination (Join-Path $inputDir 'accelerator_exit_source_receipt.json')
  Assert-VerifiedRunRecordHash -Path $frozenCoverageSummary -Record $coverageSummaryRecords[0] -Label 'coverage summary'
  Assert-VerifiedRunRecordHash -Path $frozenContract -Record $contractRecord -Label 'contract'
  if ($fixedMode) {
    Assert-VerifiedRunRecordHash -Path $frozenFixedMirrorStripe -Record $fixedMirrorStripeRecord -Label 'fixed mirror/Stripe manifest'
  } else {
    Assert-VerifiedRunRecordHash -Path $frozenExact -Record $exactRecord -Label 'exact-K manifest'
    Assert-VerifiedRunRecordHash -Path $frozenStripe -Record $stripeRecord -Label 'Stripe manifest'
  }
  Assert-VerifiedRunRecordHash -Path $frozenObservation -Record $observationRecord -Label 'accelerator observation'
  Assert-VerifiedRunRecordHash -Path $frozenExitSourceReceipt -Record $sourceReceiptRecord -Label 'accelerator source receipt'

  $sourceDir = Join-Path $inputDir 'source'
  New-Item -ItemType Directory -Path $sourceDir -Force | Out-Null
  $sourcePaths = @(
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_segmented_voltage_continuation.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_segmented_coverage.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_segmented_voltage_seed.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_segmented_transport.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\accelerator_exit_transport_source.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_simion_trial.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\drift_phase_contract.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_operating_point.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_handoff.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\prism_mirror_transport.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_exact_k_operating_point.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\fixed_mirror_stripe_operating_point.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\fixed_grid_mirror_stripe_handoff.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\dual_stripe_operating_seed.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\dual_stripe_l0.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\joint_mirror_stripe_l0.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_candidate_receipt.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_geometry_parameters.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_l0.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_l1.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\native_stripe_shape_adapter.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\resolved_geometry.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\simion_candidate_reference.py',
    'common\contracts\particle_physics.py',
    'common\contracts\file_identity.py',
    'common\contracts\verify_run_manifest.py',
    'common\host_resource_python.py',
    'common\host_resource_python.ps1',
    'common\host_execution_lease.ps1',
    'common\host_resource_scheduler.py',
    'common\host_resource_policy.json',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\run_two_prism_segmented_continuation.ps1'
  )
  $sourceInputs = [ordered]@{}
  $sourceChecks = @()
  for ($i = 0; $i -lt $sourcePaths.Count; $i++) {
    $source = Join-Path $repoRoot $sourcePaths[$i]
    $destination = Join-Path $sourceDir (('source_{0:D2}' -f ($i + 1)) + [IO.Path]::GetExtension($sourcePaths[$i]))
    $sourceInputs[('analytic_source_{0:D2}' -f ($i + 1))] = Copy-VerifiedRunInput -Source $source -Destination $destination
    $sourceChecks += [pscustomobject]@{ source = $source; frozen = $destination }
  }

  $configuration = Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
  $configuration.inputs = [ordered]@{
    parent_coverage_run_manifest = $frozenCoverageManifest
    parent_coverage_summary = $frozenCoverageSummary
    downstream_contract = $frozenContract
    accelerator_exit_observation = $frozenObservation
    accelerator_exit_source_receipt = $frozenExitSourceReceipt
  }
  if ($fixedMode) {
    $configuration.inputs.parent_fixed_mirror_stripe_run_manifest = $frozenFixedMirrorStripe
  } else {
    $configuration.inputs.parent_exact_k_run_manifest = $frozenExact
    $configuration.inputs.parent_stripe_seed_run_manifest = $frozenStripe
  }
  foreach ($entry in $sourceInputs.GetEnumerator()) { $configuration.inputs[$entry.Key] = $entry.Value }
  $configuration.parameters = [ordered]@{
    expected_topology_signature_sha256 = $ExpectedTopologySignatureSha256.ToLowerInvariant()
    solve_mode = $SolveMode
    initial_bracket_v = [ordered]@{ p1 = $InitialP1V; p2 = @($InitialP2LowerV, $InitialP2UpperV) }
    p1_bounds_v = @($P1MinimumV, $P1MaximumV)
    p2_bounds_v = @($P2MinimumV, $P2MaximumV)
    continuation = [ordered]@{
    angle_tolerance_deg = $AngleToleranceDeg
      positive_mirror_turn_y_tolerance_mm = $PositiveMirrorTurnYToleranceMm
      p2_root_tolerance_v = $P2RootToleranceV
      initial_p1_step_v = $InitialP1StepV; minimum_p1_step_v = $MinimumP1StepV
      maximum_p1_step_v = $MaximumP1StepV; p1_step_growth_factor = $P1StepGrowthFactor
      p2_initial_half_width_v = $P2InitialHalfWidthV
      p2_bracket_expansion_factor = $P2BracketExpansionFactor
      p2_bracket_maximum_expansions = $P2BracketMaximumExpansions
      maximum_inner_iterations = $MaximumInnerIterations; maximum_outer_iterations = $MaximumOuterIterations
      maximum_transport_evaluations = $MaximumTransportEvaluations
      maximum_nodes_per_direction = $MaximumNodesPerDirection
    }
    transport_numerics = [ordered]@{
      relative_tolerance = $RelativeTolerance; absolute_tolerance = $AbsoluteTolerance
      maximum_step_mm_per_sqrt_v = $MaximumStepMmPerSqrtV; event_samples_per_step = $EventSamplesPerStep
      root_time_tolerance_mm_per_sqrt_v = $RootTimeToleranceMmPerSqrtV
      boundary_root_tolerance_mm = $BoundaryRootToleranceMm
      momentum_tolerance_sqrt_v = $MomentumToleranceSqrtV
      normal_energy_tolerance_v = $NormalEnergyToleranceV; maximum_steps = $MaximumSteps
    }
    stage_a_maximum_reduced_time_mm_per_sqrt_v = $StageAMaximumReducedTimeMmPerSqrtV
    stage_b_maximum_reduced_time_mm_per_sqrt_v = $StageBMaximumReducedTimeMmPerSqrtV
    solver_execution = 'none'
    qualification = 'solver_neutral_single_topology_branch_continuation_only__not_a_3d_voltage_solution'
  }
  Write-RunJson -Path $runConfig -Depth 18 -Value $configuration

  $failureStage = 'segmented_voltage_continuation'
  $sourceReceipt = Join-Path $resultDir 'accelerator_exit_transport_source.json'
  $logPath = Join-Path $logDir 'two_prism_segmented_continuation.log'
  $culture = [Globalization.CultureInfo]::InvariantCulture
  $arguments = @(
    '-m', 'projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_voltage_continuation',
    '--contract', $frozenContract,
    '--accelerator-exit-observation', $frozenObservation,
    '--accelerator-exit-source-receipt', $frozenExitSourceReceipt,
    '--coverage-summary', $frozenCoverageSummary,
    '--source-receipt-output', $sourceReceipt,
    '--output', $summary,
    '--expected-observation-sha256', ([string]$observationRecord.sha256).ToLowerInvariant(),
    '--expected-topology-signature-sha256', $ExpectedTopologySignatureSha256.ToLowerInvariant(),
    '--solve-mode', $SolveMode,
    '--initial-p1-v', $InitialP1V.ToString('R', $culture),
    '--initial-p2-lower-v', $InitialP2LowerV.ToString('R', $culture),
    '--initial-p2-upper-v', $InitialP2UpperV.ToString('R', $culture),
    '--p1-min-v', $P1MinimumV.ToString('R', $culture), '--p1-max-v', $P1MaximumV.ToString('R', $culture),
    '--p2-min-v', $P2MinimumV.ToString('R', $culture), '--p2-max-v', $P2MaximumV.ToString('R', $culture),
    '--angle-tolerance-deg', $AngleToleranceDeg.ToString('R', $culture),
    '--positive-turn-y-tolerance-mm', $PositiveMirrorTurnYToleranceMm.ToString('R', $culture),
    '--p2-root-tolerance-v', $P2RootToleranceV.ToString('R', $culture),
    '--initial-p1-step-v', $InitialP1StepV.ToString('R', $culture),
    '--minimum-p1-step-v', $MinimumP1StepV.ToString('R', $culture),
    '--maximum-p1-step-v', $MaximumP1StepV.ToString('R', $culture),
    '--p1-step-growth-factor', $P1StepGrowthFactor.ToString('R', $culture),
    '--p2-initial-half-width-v', $P2InitialHalfWidthV.ToString('R', $culture),
    '--p2-bracket-expansion-factor', $P2BracketExpansionFactor.ToString('R', $culture),
    '--p2-bracket-maximum-expansions', [string]$P2BracketMaximumExpansions,
    '--maximum-inner-iterations', [string]$MaximumInnerIterations,
    '--maximum-outer-iterations', [string]$MaximumOuterIterations,
    '--maximum-transport-evaluations', [string]$MaximumTransportEvaluations,
    '--maximum-nodes-per-direction', [string]$MaximumNodesPerDirection,
    '--relative-tolerance', $RelativeTolerance.ToString('R', $culture),
    '--absolute-tolerance', $AbsoluteTolerance.ToString('R', $culture),
    '--max-step', $MaximumStepMmPerSqrtV.ToString('R', $culture),
    '--event-samples-per-step', [string]$EventSamplesPerStep,
    '--root-time-tolerance', $RootTimeToleranceMmPerSqrtV.ToString('R', $culture),
    '--boundary-root-tolerance', $BoundaryRootToleranceMm.ToString('R', $culture),
    '--momentum-tolerance', $MomentumToleranceSqrtV.ToString('R', $culture),
    '--normal-energy-tolerance', $NormalEnergyToleranceV.ToString('R', $culture),
    '--maximum-steps', [string]$MaximumSteps,
    '--stage-a-maximum-reduced-time', $StageAMaximumReducedTimeMmPerSqrtV.ToString('R', $culture),
    '--stage-b-maximum-reduced-time', $StageBMaximumReducedTimeMmPerSqrtV.ToString('R', $culture)
  )
  if ($fixedMode) {
    $arguments += @('--fixed-mirror-stripe-manifest', $frozenFixedMirrorStripe)
  } else {
    $arguments += @('--exact-k-manifest', $frozenExact, '--stripe-seed-manifest', $frozenStripe)
  }
  $lease = $null
  try {
    $lease = Enter-HostExecutionLease -Role GATE -Stage theory_compute -RunId $RunId
    Invoke-ProjectPython -Arguments $arguments -LogPath $logPath
  } finally {
    if ($lease) { Exit-HostExecutionLease -Lease $lease }
  }
  foreach ($pair in $sourceChecks) {
    if (-not (Test-RunFilesIdentical -Left $pair.source -Right $pair.frozen)) {
      throw "Frozen analytic source changed during execution: $($pair.source)"
    }
  }

  $failureStage = 'retention'
  $retention = Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage = 'capacity_terminal'
  $maximumBytes = [int64]((Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File | Measure-Object Length -Sum).Sum)
  $terminal = Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -ProtectedPaths @($package.artifact_run_dir) `
    -KnownMeasuredBytes ([int64]$startup.measured_after_bytes) -MaximumNewArtifactBytes $maximumBytes
  $terminalPath = Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('Python 3.11', 'SciPy') `
    -Outputs @($summary, $sourceReceipt, $startupPath, $terminalPath, $retention, $verifyLog, $logPath)
  $terminalized = $true
  Write-Host "MRTOF_TWO_PRISM_SEGMENTED_CONTINUATION=PASS RUN_ID=$RunId SUMMARY=$summary"
} catch {
  if (-not $terminalized) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_two_prism_segmented_voltage_branch_continuation' -Reason $_.Exception.Message `
      -Software @('Python 3.11', 'SciPy') -Status failed -FailureStage $failureStage
    $terminalized = $true
  }
  throw
} finally {
  if (-not $terminalized -and (Test-Path -LiteralPath $runConfig -PathType Leaf)) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_two_prism_segmented_voltage_branch_continuation' `
      -Reason 'Runner stopped before terminal continuation publication.' `
      -Software @('Python 3.11', 'SciPy') -Status interrupted -FailureStage $failureStage
  }
}
