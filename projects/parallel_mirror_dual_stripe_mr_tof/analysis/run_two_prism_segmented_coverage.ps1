[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$ExactKRunManifest,
  [Parameter(Mandatory)][string]$StripeSeedRunManifest,
  [Parameter(Mandatory)][string]$AcceleratorExitRunManifest,
  [Parameter(Mandatory)][double]$P1MinimumV,
  [Parameter(Mandatory)][double]$P1MaximumV,
  [Parameter(Mandatory)][double]$P2MinimumV,
  [Parameter(Mandatory)][double]$P2MaximumV,
  [Parameter(Mandatory)][int]$SobolSampleCount,
  [Parameter(Mandatory)][double[]]$LocalP1ValuesV,
  [Parameter(Mandatory)][double[]]$LocalP2ValuesV,
  [Parameter(Mandatory)][int]$WorkerCount,
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
  [string]$ContractPath = '', [string]$RunId = '', [string]$PythonExe = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectId = 'parallel_mirror_dual_stripe_mr_tof'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python 3.11 environment is missing: $python" }
$contract = if ($ContractPath) { (Resolve-Path -LiteralPath $ContractPath).Path } else { Join-Path $PSScriptRoot '..\config\simion_candidate_two_zone.json' }
$exactManifest = (Resolve-Path -LiteralPath $ExactKRunManifest).Path
$stripeManifest = (Resolve-Path -LiteralPath $StripeSeedRunManifest).Path
$exitManifest = (Resolve-Path -LiteralPath $AcceleratorExitRunManifest).Path
if ([string]::IsNullOrWhiteSpace($RunId)) { $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__analysis__python__mrtof-two-prism-segmented-coverage' }

. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$package = New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'two_prism_segmented_voltage_branch_coverage' `
  -Software @('Python 3.11', 'SciPy') -RetentionContractEnabled -RetentionClass compact
$runConfig = $package.run_config; $summary = $package.summary; $inputDir = $package.input_dir
$resultDir = $package.result_dir; $logDir = $package.log_dir; $terminalized = $false; $failureStage = 'preflight'

function Invoke-ProjectPython {
  param([Parameter(Mandatory)][string[]]$Arguments, [Parameter(Mandatory)][string]$LogPath)
  Push-Location -LiteralPath $repoRoot
  $savedPythonPath = $env:PYTHONPATH
  $savedOpenBlasThreads = $env:OPENBLAS_NUM_THREADS
  $savedOmpThreads = $env:OMP_NUM_THREADS
  $savedMklThreads = $env:MKL_NUM_THREADS
  $savedNumExprThreads = $env:NUMEXPR_NUM_THREADS
  try {
    $env:PYTHONPATH = $repoRoot; $env:OPENBLAS_NUM_THREADS = '1'; $env:OMP_NUM_THREADS = '1'; $env:MKL_NUM_THREADS = '1'; $env:NUMEXPR_NUM_THREADS = '1'
    & $python @Arguments 2>&1 | Tee-Object -FilePath $LogPath
    if ($LASTEXITCODE -ne 0) { throw "MR-TOF coverage stage failed: $($Arguments -join ' ')" }
  } finally {
    $env:PYTHONPATH = $savedPythonPath; $env:OPENBLAS_NUM_THREADS = $savedOpenBlasThreads; $env:OMP_NUM_THREADS = $savedOmpThreads
    $env:MKL_NUM_THREADS = $savedMklThreads; $env:NUMEXPR_NUM_THREADS = $savedNumExprThreads; Pop-Location
  }
}

try {
  $failureStage = 'capacity_startup'
  $startup = Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') `
    -ProtectedPaths @($package.artifact_run_dir) -RequiredHeadroomBytes 1048576
  $startupPath = Join-Path $resultDir 'artifact_capacity_gate_startup.json'; Write-RunJson -Path $startupPath -Depth 14 -Value $startup

  $failureStage = 'verify_inputs'
  $verifyLog = Join-Path $logDir 'accelerator_exit_manifest_verification.log'
  Invoke-ProjectPython -Arguments @('-m','common.contracts.verify_run_manifest',$exitManifest,'--require-status','success','--require-project',$projectId) -LogPath $verifyLog
  $exit = Get-Content -LiteralPath $exitManifest -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
  $observationRecords = @($exit.outputs | Where-Object { [IO.Path]::GetFileName([string]$_.path) -eq 'accelerator_exit_observation.json' })
  if ($observationRecords.Count -ne 1) { throw 'Accelerator-exit manifest must declare exactly one accelerator_exit_observation.json output.' }
  $sourceReceiptRecords = @($exit.outputs | Where-Object { [IO.Path]::GetFileName([string]$_.path) -eq 'accelerator_exit_source_receipt.json' })
  if ($sourceReceiptRecords.Count -ne 1) { throw 'Accelerator-exit manifest must declare exactly one accelerator_exit_source_receipt.json output.' }
  $observation = (Resolve-Path -LiteralPath ([string]$observationRecords[0].path)).Path
  $exitSourceReceipt = (Resolve-Path -LiteralPath ([string]$sourceReceiptRecords[0].path)).Path
  $expectedObservationSha = ([string]$observationRecords[0].sha256).ToLowerInvariant()

  $failureStage = 'freeze_inputs'
  $frozenContract = Copy-VerifiedRunInput -Source $contract -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
  $frozenExact = Copy-VerifiedRunInput -Source $exactManifest -Destination (Join-Path $inputDir 'parent_exact_k_run_manifest.json')
  $frozenStripe = Copy-VerifiedRunInput -Source $stripeManifest -Destination (Join-Path $inputDir 'parent_stripe_seed_run_manifest.json')
  $frozenExit = Copy-VerifiedRunInput -Source $exitManifest -Destination (Join-Path $inputDir 'parent_accelerator_exit_run_manifest.json')
  $frozenObservation = Copy-VerifiedRunInput -Source $observation -Destination (Join-Path $inputDir 'accelerator_exit_observation.json')
  $frozenExitSourceReceipt = Copy-VerifiedRunInput -Source $exitSourceReceipt -Destination (Join-Path $inputDir 'accelerator_exit_source_receipt.json')
  $sourceDir = Join-Path $inputDir 'source'; New-Item -ItemType Directory -Path $sourceDir -Force | Out-Null
  $sourcePaths = @(
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_segmented_coverage.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_segmented_transport.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_segmented_voltage_seed.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\accelerator_exit_transport_source.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_simion_trial.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\drift_phase_contract.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_operating_point.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_handoff.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\prism_mirror_transport.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_exact_k_operating_point.py',
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
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\run_two_prism_segmented_coverage.ps1'
  )
  $sourceInputs = [ordered]@{}
  $sourceChecks = @()
  for ($i = 0; $i -lt $sourcePaths.Count; $i++) {
    $source = Join-Path $repoRoot $sourcePaths[$i]
    $destination = Join-Path $sourceDir (('source_{0:D2}' -f ($i + 1)) + [IO.Path]::GetExtension($sourcePaths[$i]))
    $sourceInputs[('analytic_source_{0:D2}' -f ($i + 1))] = Copy-VerifiedRunInput -Source $source -Destination $destination
    $sourceChecks += [pscustomobject]@{ source=$source; frozen=$destination }
  }
  $configuration = Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
  $configuration.inputs = [ordered]@{ downstream_contract=$frozenContract; parent_exact_k_run_manifest=$frozenExact; parent_stripe_seed_run_manifest=$frozenStripe; parent_accelerator_exit_run_manifest=$frozenExit; accelerator_exit_observation=$frozenObservation; accelerator_exit_source_receipt=$frozenExitSourceReceipt }
  foreach ($entry in $sourceInputs.GetEnumerator()) { $configuration.inputs[$entry.Key] = $entry.Value }
  $configuration.parameters = [ordered]@{
    p1_bounds_v=@($P1MinimumV,$P1MaximumV); p2_bounds_v=@($P2MinimumV,$P2MaximumV); sobol_sample_count=$SobolSampleCount
    local_p1_values_v=$LocalP1ValuesV; local_p2_values_v=$LocalP2ValuesV; worker_count=$WorkerCount
    transport_numerics=[ordered]@{ relative_tolerance=$RelativeTolerance; absolute_tolerance=$AbsoluteTolerance; maximum_step_mm_per_sqrt_v=$MaximumStepMmPerSqrtV; event_samples_per_step=$EventSamplesPerStep; root_time_tolerance_mm_per_sqrt_v=$RootTimeToleranceMmPerSqrtV; boundary_root_tolerance_mm=$BoundaryRootToleranceMm; momentum_tolerance_sqrt_v=$MomentumToleranceSqrtV; normal_energy_tolerance_v=$NormalEnergyToleranceV; maximum_steps=$MaximumSteps }
    stage_a_maximum_reduced_time_mm_per_sqrt_v=$StageAMaximumReducedTimeMmPerSqrtV; stage_b_maximum_reduced_time_mm_per_sqrt_v=$StageBMaximumReducedTimeMmPerSqrtV
    solver_execution='none'; qualification='solver_neutral_topology_coverage_only__not_a_voltage_solution'
  }
  Write-RunJson -Path $runConfig -Depth 18 -Value $configuration

  $failureStage = 'segmented_transport_coverage'
  $sourceReceipt = Join-Path $resultDir 'accelerator_exit_transport_source.json'
  $logPath = Join-Path $logDir 'two_prism_segmented_coverage.log'
  $culture = [Globalization.CultureInfo]::InvariantCulture
  $localP1 = ($LocalP1ValuesV | ForEach-Object { $_.ToString('R',$culture) }) -join ','
  $localP2 = ($LocalP2ValuesV | ForEach-Object { $_.ToString('R',$culture) }) -join ','
  $args = @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_coverage',
    '--contract',$frozenContract,'--exact-k-manifest',$frozenExact,'--stripe-seed-manifest',$frozenStripe,
    '--accelerator-exit-observation',$frozenObservation,'--expected-observation-sha256',$expectedObservationSha,
    '--accelerator-exit-source-receipt',$frozenExitSourceReceipt,
    '--source-receipt-output',$sourceReceipt,'--output',$summary,
    '--p1-min-v',$P1MinimumV.ToString('R',$culture),'--p1-max-v',$P1MaximumV.ToString('R',$culture),
    '--p2-min-v',$P2MinimumV.ToString('R',$culture),'--p2-max-v',$P2MaximumV.ToString('R',$culture),
    '--sobol-sample-count',[string]$SobolSampleCount,"--local-p1-values-v=$localP1","--local-p2-values-v=$localP2",'--worker-count',[string]$WorkerCount,
    '--relative-tolerance',$RelativeTolerance.ToString('R',$culture),'--absolute-tolerance',$AbsoluteTolerance.ToString('R',$culture),
    '--max-step',$MaximumStepMmPerSqrtV.ToString('R',$culture),'--event-samples-per-step',[string]$EventSamplesPerStep,
    '--root-time-tolerance',$RootTimeToleranceMmPerSqrtV.ToString('R',$culture),'--boundary-root-tolerance',$BoundaryRootToleranceMm.ToString('R',$culture),
    '--momentum-tolerance',$MomentumToleranceSqrtV.ToString('R',$culture),'--normal-energy-tolerance',$NormalEnergyToleranceV.ToString('R',$culture),
    '--maximum-steps',[string]$MaximumSteps,'--stage-a-maximum-reduced-time',$StageAMaximumReducedTimeMmPerSqrtV.ToString('R',$culture),
    '--stage-b-maximum-reduced-time',$StageBMaximumReducedTimeMmPerSqrtV.ToString('R',$culture))
  $lease = $null
  try { $lease = Enter-HostExecutionLease -Role GATE -Stage theory_compute -RunId $RunId; Invoke-ProjectPython -Arguments $args -LogPath $logPath }
  finally { if ($lease) { Exit-HostExecutionLease -Lease $lease } }
  foreach ($pair in $sourceChecks) {
    if (-not (Test-RunFilesIdentical -Left $pair.source -Right $pair.frozen)) { throw "Frozen analytic source changed during execution: $($pair.source)" }
  }

  $failureStage = 'retention'; $retention = Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage = 'capacity_terminal'
  $maximumBytes = [int64]((Get-ChildItem -LiteralPath $package.artifact_run_dir -Recurse -File | Measure-Object Length -Sum).Sum)
  $terminal = Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') `
    -ProtectedPaths @($package.artifact_run_dir) -KnownMeasuredBytes ([int64]$startup.measured_after_bytes) -MaximumNewArtifactBytes $maximumBytes
  $terminalPath = Join-Path $resultDir 'artifact_capacity_gate_terminal.json'; Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success -Software @('Python 3.11','SciPy') `
    -Outputs @($summary,$sourceReceipt,$startupPath,$terminalPath,$retention,$verifyLog,$logPath)
  $terminalized = $true; Write-Host "MRTOF_TWO_PRISM_SEGMENTED_COVERAGE=PASS RUN_ID=$RunId SUMMARY=$summary"
} catch {
  if (-not $terminalized) { Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_two_prism_segmented_voltage_branch_coverage' -Reason $_.Exception.Message -Software @('Python 3.11','SciPy') -Status failed -FailureStage $failureStage; $terminalized = $true }
  throw
} finally {
  if (-not $terminalized -and (Test-Path -LiteralPath $runConfig -PathType Leaf)) { Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary -SummaryRole 'mrtof_two_prism_segmented_voltage_branch_coverage' -Reason 'Runner stopped before terminal coverage publication.' -Software @('Python 3.11','SciPy') -Status interrupted -FailureStage $failureStage }
}
