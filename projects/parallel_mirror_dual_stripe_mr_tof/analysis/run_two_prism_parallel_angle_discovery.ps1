[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$CoverageRunManifest,
  [ValidateSet('angle','position','position_adaptive')][string]$PrimaryObjective = 'angle',
  [Parameter(Mandatory)][double]$P1MinimumV,
  [Parameter(Mandatory)][double]$P1MaximumV,
  [Parameter(Mandatory)][double]$P2MinimumV,
  [Parameter(Mandatory)][double]$P2MaximumV,
  [Parameter(Mandatory)][int]$AnchorCount,
  [Parameter(Mandatory)][int]$WorkerCount,
  [Parameter(Mandatory)][double]$AngleRatioRootTolerance,
  [Parameter(Mandatory)][double]$P2RootToleranceV,
  [Parameter(Mandatory)][double]$TopologyBoundaryToleranceV,
  [Parameter(Mandatory)][int]$MaximumSliceEvaluations,
  [double]$PositiveMirrorTurnYToleranceMm = 0.01,
  [double]$P2InitialHalfWidthV = 2.0,
  [double]$P2BracketExpansionFactor = 2.0,
  [int]$P2BracketMaximumExpansions = 8,
  [int]$MaximumInnerIterations = 60,
  [int]$P2ScanCount = 17,
  [int]$AdaptiveRefinementLevels = 6,
  [int]$AdaptiveCandidateCount = 3,
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
$discoveryLabel = switch ($PrimaryObjective) {
  'position' { 'position' }
  'position_adaptive' { 'position-adaptive' }
  default { 'angle' }
}
$artifactMode = "two_prism_parallel_p2_${discoveryLabel}_discovery"
$summaryRole = "mrtof_two_prism_parallel_p2_${discoveryLabel}_discovery"
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + "__analysis__python__mrtof-two-prism-parallel-${discoveryLabel}-discovery"
}

. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$package = New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode $artifactMode `
  -Software @('Python 3.11', 'SciPy') -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled
$runConfig = $package.run_config
$summary = $package.summary
$inputDir = $package.input_dir
$resultDir = $package.result_dir
$logDir = $package.log_dir
$terminalized = $false
$failureStage = 'preflight'
$capacitySession = $null

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
    if ($LASTEXITCODE -ne 0) { throw "MR-TOF parallel $discoveryLabel discovery failed: $($Arguments -join ' ')" }
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
  $capacitySession = Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes 1048576 `
    -ProtectedPaths @($package.artifact_run_dir, (Split-Path -Parent $coverageManifest)) `
    -Owner "mrtof-two-prism-parallel-$discoveryLabel-discovery:$RunId"
  $startupPath = Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startupPath -Depth 14 -Value $capacitySession

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
  ) { throw 'Parent run must be a successful two-prism segmented coverage run.' }
  $contractRecord = Get-VerifiedRunManifestInputRecord -Records $coverageRun.inputs -Name 'downstream_contract' -Label 'contract'
  $exactRecord = Get-VerifiedRunManifestInputRecord -Records $coverageRun.inputs -Name 'parent_exact_k_run_manifest' -Label 'exact-K manifest'
  $stripeRecord = Get-VerifiedRunManifestInputRecord -Records $coverageRun.inputs -Name 'parent_stripe_seed_run_manifest' -Label 'Stripe manifest'
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
  $frozenExact = Copy-VerifiedRunInput -Source ([string]$exactRecord.path) -Destination (Join-Path $inputDir 'parent_exact_k_run_manifest.json')
  $frozenStripe = Copy-VerifiedRunInput -Source ([string]$stripeRecord.path) -Destination (Join-Path $inputDir 'parent_stripe_seed_run_manifest.json')
  $frozenObservation = Copy-VerifiedRunInput -Source ([string]$observationRecord.path) -Destination (Join-Path $inputDir 'accelerator_exit_observation.json')
  $frozenExitSourceReceipt = Copy-VerifiedRunInput -Source ([string]$sourceReceiptRecord.path) -Destination (Join-Path $inputDir 'accelerator_exit_source_receipt.json')
  Assert-VerifiedRunRecordHash -Path $frozenCoverageSummary -Record $coverageSummaryRecords[0] -Label 'coverage summary'
  Assert-VerifiedRunRecordHash -Path $frozenContract -Record $contractRecord -Label 'contract'
  Assert-VerifiedRunRecordHash -Path $frozenExact -Record $exactRecord -Label 'exact-K manifest'
  Assert-VerifiedRunRecordHash -Path $frozenStripe -Record $stripeRecord -Label 'Stripe manifest'
  Assert-VerifiedRunRecordHash -Path $frozenObservation -Record $observationRecord -Label 'accelerator observation'
  Assert-VerifiedRunRecordHash -Path $frozenExitSourceReceipt -Record $sourceReceiptRecord -Label 'accelerator source receipt'

  $sourceDir = Join-Path $inputDir 'source'
  New-Item -ItemType Directory -Path $sourceDir -Force | Out-Null
  $sourcePaths = @(
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_parallel_angle_discovery.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_angle_slice.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_segmented_coverage.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_segmented_transport.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_segmented_voltage_continuation.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\prism_analytic.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\prism_mirror_transport.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\accelerator_exit_transport_source.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_exact_k_operating_point.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_l0.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_l1.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_handoff.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_operating_point.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_segmented_voltage_seed.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_simion_trial.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\dual_stripe_l0.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\joint_mirror_stripe_l0.py',
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
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\run_two_prism_parallel_angle_discovery.ps1'
  )
  $sourceChecks = @()
  $sourceInputs = [ordered]@{}
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
    parent_exact_k_run_manifest = $frozenExact
    parent_stripe_seed_run_manifest = $frozenStripe
    accelerator_exit_observation = $frozenObservation
    accelerator_exit_source_receipt = $frozenExitSourceReceipt
  }
  foreach ($entry in $sourceInputs.GetEnumerator()) { $configuration.inputs[$entry.Key] = $entry.Value }
  $configuration.parameters = [ordered]@{
    primary_objective = $PrimaryObjective
    p1_discovery_bounds_v = @($P1MinimumV, $P1MaximumV)
    p2_discovery_bounds_v = @($P2MinimumV, $P2MaximumV)
    anchor_count = $AnchorCount
    worker_count = $WorkerCount
    angle_ratio_root_tolerance = $AngleRatioRootTolerance
    p2_root_tolerance_v = $P2RootToleranceV
    topology_boundary_tolerance_v = $TopologyBoundaryToleranceV
    maximum_slice_evaluations = $MaximumSliceEvaluations
    positive_mirror_turn_y_tolerance_mm = $PositiveMirrorTurnYToleranceMm
    p2_initial_half_width_v = $P2InitialHalfWidthV
    p2_bracket_expansion_factor = $P2BracketExpansionFactor
    p2_bracket_maximum_expansions = $P2BracketMaximumExpansions
    maximum_inner_iterations = $MaximumInnerIterations
    p2_scan_count = $P2ScanCount
    adaptive_refinement_levels = $AdaptiveRefinementLevels
    adaptive_candidate_count = $AdaptiveCandidateCount
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
    qualification = "solver_neutral_parallel_${discoveryLabel}_branch_discovery_only__not_a_3d_voltage_solution"
  }
  Write-RunJson -Path $runConfig -Depth 18 -Value $configuration

  $failureStage = "parallel_${discoveryLabel}_discovery"
  $sourceReceipt = Join-Path $resultDir 'accelerator_exit_transport_source.json'
  $logPath = Join-Path $logDir 'two_prism_parallel_angle_discovery.log'
  $culture = [Globalization.CultureInfo]::InvariantCulture
  $arguments = @(
    '-m', 'projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_parallel_angle_discovery',
    '--primary-objective', $PrimaryObjective,
    '--contract', $frozenContract,
    '--exact-k-manifest', $frozenExact,
    '--stripe-seed-manifest', $frozenStripe,
    '--accelerator-exit-observation', $frozenObservation,
    '--accelerator-exit-source-receipt', $frozenExitSourceReceipt,
    '--coverage-summary', $frozenCoverageSummary,
    '--source-receipt-output', $sourceReceipt,
    '--output', $summary,
    '--expected-observation-sha256', ([string]$observationRecord.sha256).ToLowerInvariant(),
    '--p1-min-v', $P1MinimumV.ToString('R', $culture),
    '--p1-max-v', $P1MaximumV.ToString('R', $culture),
    '--p2-min-v', $P2MinimumV.ToString('R', $culture),
    '--p2-max-v', $P2MaximumV.ToString('R', $culture),
    '--anchor-count', [string]$AnchorCount,
    '--worker-count', [string]$WorkerCount,
    '--angle-ratio-root-tolerance', $AngleRatioRootTolerance.ToString('R', $culture),
    '--p2-root-tolerance-v', $P2RootToleranceV.ToString('R', $culture),
    '--topology-boundary-tolerance-v', $TopologyBoundaryToleranceV.ToString('R', $culture),
    '--maximum-slice-evaluations', [string]$MaximumSliceEvaluations,
    '--positive-turn-y-tolerance-mm', $PositiveMirrorTurnYToleranceMm.ToString('R', $culture),
    '--p2-initial-half-width-v', $P2InitialHalfWidthV.ToString('R', $culture),
    '--p2-bracket-expansion-factor', $P2BracketExpansionFactor.ToString('R', $culture),
    '--p2-bracket-maximum-expansions', [string]$P2BracketMaximumExpansions,
    '--maximum-inner-iterations', [string]$MaximumInnerIterations,
    '--p2-scan-count', [string]$P2ScanCount,
    '--adaptive-refinement-levels', [string]$AdaptiveRefinementLevels,
    '--adaptive-candidate-count', [string]$AdaptiveCandidateCount,
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
  $terminal = Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -Session $capacitySession -RemainingCommittedNewBytes 0
  $capacitySession = $terminal.session
  $terminalPath = Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('Python 3.11', 'SciPy') `
    -Outputs @($summary, $sourceReceipt, $startupPath, $terminalPath, $retention, $verifyLog, $logPath)
  $terminalized = $true
  Write-Host "MRTOF_TWO_PRISM_PARALLEL_DISCOVERY=PASS OBJECTIVE=$PrimaryObjective RUN_ID=$RunId SUMMARY=$summary"
} catch {
  if (-not $terminalized) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole $summaryRole -Reason $_.Exception.Message `
      -Software @('Python 3.11', 'SciPy') -Status failed -FailureStage $failureStage
    $terminalized = $true
  }
  throw
} finally {
  try {
    if (-not $terminalized -and (Test-Path -LiteralPath $runConfig -PathType Leaf)) {
      Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
        -SummaryRole $summaryRole `
        -Reason "Runner stopped before terminal parallel-$discoveryLabel publication." `
        -Software @('Python 3.11', 'SciPy') -Status interrupted -FailureStage $failureStage
    }
  } finally {
    if ($null -ne $capacitySession) {
      $null = Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession
    }
  }
}
