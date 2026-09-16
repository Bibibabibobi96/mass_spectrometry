[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$ExactKRunManifest,
  [Parameter(Mandatory)][string]$AcceleratorExitRunManifest,
  [double]$PreviousCumulativeCorrectionV = 0.0,
  [string]$ContractPath = '',
  [string]$RunId = '',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectId = 'parallel_mirror_dual_stripe_mr_tof'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot "artifacts\projects\$projectId"
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python 3.11 environment is missing: $python" }
$contract = if ($ContractPath) {
  (Resolve-Path -LiteralPath $ContractPath).Path
} else {
  (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\config\simion_candidate_two_zone.json')).Path
}
$exactManifest = (Resolve-Path -LiteralPath $ExactKRunManifest).Path
$exitManifest = (Resolve-Path -LiteralPath $AcceleratorExitRunManifest).Path
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__analysis__python__mrtof-accelerator-exit-energy-calibration'
}
if (-not [double]::IsFinite($PreviousCumulativeCorrectionV)) {
  throw 'Previous cumulative correction must be finite.'
}

. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$package = New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project $projectId -Mode 'accelerator_finite_3d_exit_energy_calibration' `
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
    if ($LASTEXITCODE -ne 0) { throw "MR-TOF accelerator energy calibration failed: $($Arguments -join ' ')" }
  } finally {
    $env:PYTHONPATH = $savedPythonPath
    $env:OPENBLAS_NUM_THREADS = $savedOpenBlasThreads
    $env:OMP_NUM_THREADS = $savedOmpThreads
    $env:MKL_NUM_THREADS = $savedMklThreads
    $env:NUMEXPR_NUM_THREADS = $savedNumExprThreads
    Pop-Location
  }
}

function Assert-FrozenHash {
  param(
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][string]$ExpectedSha256,
    [Parameter(Mandatory)][string]$Label
  )
  $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
  if ($actual -ne $ExpectedSha256.ToUpperInvariant()) {
    throw "Frozen $Label differs from its verified source identity."
  }
}

try {
  $failureStage = 'capacity_startup'
  $startup = Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') `
    -ProtectedPaths @($package.artifact_run_dir, (Split-Path -Parent $exactManifest), (Split-Path -Parent $exitManifest)) `
    -RequiredHeadroomBytes 1048576
  $startupPath = Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startupPath -Depth 14 -Value $startup

  $failureStage = 'verify_parent_manifests'
  $exactVerifyLog = Join-Path $logDir 'exact_k_manifest_verification.log'
  Invoke-ProjectPython -Arguments @(
    '-m', 'common.contracts.verify_run_manifest', $exactManifest,
    '--require-status', 'success', '--require-project', $projectId
  ) -LogPath $exactVerifyLog
  $exitVerifyLog = Join-Path $logDir 'accelerator_exit_manifest_verification.log'
  Invoke-ProjectPython -Arguments @(
    '-m', 'common.contracts.verify_run_manifest', $exitManifest,
    '--require-status', 'success', '--require-project', $projectId
  ) -LogPath $exitVerifyLog

  $exactRun = Get-Content -LiteralPath $exactManifest -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
  if ($exactRun.mode -ne 'analytic_mirror_exact_k_operating_point' -or $exactRun.status -ne 'success') {
    throw 'Exact-K parent must be a successful analytic_mirror_exact_k_operating_point run.'
  }
  $exactSummaryRecords = @(
    $exactRun.outputs | Where-Object {
      $_.exists -and [IO.Path]::GetFileName([string]$_.path) -eq 'summary.json'
    }
  )
  if ($exactSummaryRecords.Count -ne 1 -or [string]::IsNullOrWhiteSpace([string]$exactSummaryRecords[0].sha256)) {
    throw 'Exact-K manifest must publish exactly one SHA-256-bound summary.json.'
  }
  $exactSummaryRecord = $exactSummaryRecords[0]
  $exitRun = Get-Content -LiteralPath $exitManifest -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
  if ($exitRun.mode -ne 'accelerator_source_to_safe_exit' -or $exitRun.status -ne 'success') {
    throw 'Accelerator-exit parent must be a successful accelerator_source_to_safe_exit run.'
  }
  $observationRecords = @(
    $exitRun.outputs | Where-Object {
      $_.exists -and [IO.Path]::GetFileName([string]$_.path) -eq 'accelerator_exit_observation.json'
    }
  )
  if ($observationRecords.Count -ne 1) {
    throw 'Accelerator-exit manifest must publish exactly one existing accelerator_exit_observation.json.'
  }
  $observationRecord = $observationRecords[0]
  if ([string]::IsNullOrWhiteSpace([string]$observationRecord.sha256)) {
    throw 'Accelerator-exit observation record lacks SHA-256 identity.'
  }

  $failureStage = 'freeze_inputs'
  $exactManifestSha = (Get-FileHash -LiteralPath $exactManifest -Algorithm SHA256).Hash
  $exitManifestSha = (Get-FileHash -LiteralPath $exitManifest -Algorithm SHA256).Hash
  $contractSha = (Get-FileHash -LiteralPath $contract -Algorithm SHA256).Hash
  $frozenContract = Copy-VerifiedRunInput -Source $contract -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
  $frozenExact = Copy-VerifiedRunInput -Source $exactManifest -Destination (Join-Path $inputDir 'parent_exact_k_run_manifest.json')
  $frozenExactSummary = Copy-VerifiedRunInput -Source ([string]$exactSummaryRecord.path) -Destination (Join-Path $inputDir 'parent_exact_k_summary.json')
  $frozenExit = Copy-VerifiedRunInput -Source $exitManifest -Destination (Join-Path $inputDir 'parent_accelerator_exit_run_manifest.json')
  $frozenObservation = Copy-VerifiedRunInput -Source ([string]$observationRecord.path) -Destination (Join-Path $inputDir 'accelerator_exit_observation.json')
  Assert-FrozenHash -Path $frozenContract -ExpectedSha256 $contractSha -Label 'candidate contract'
  Assert-FrozenHash -Path $frozenExact -ExpectedSha256 $exactManifestSha -Label 'exact-K manifest'
  Assert-FrozenHash -Path $frozenExactSummary -ExpectedSha256 ([string]$exactSummaryRecord.sha256) -Label 'exact-K summary'
  Assert-FrozenHash -Path $frozenExit -ExpectedSha256 $exitManifestSha -Label 'accelerator-exit manifest'
  Assert-FrozenHash -Path $frozenObservation -ExpectedSha256 ([string]$observationRecord.sha256) -Label 'accelerator-exit observation'
  $inputChecks = @(
    [pscustomobject]@{ source = $contract; frozen = $frozenContract; label = 'candidate contract' },
    [pscustomobject]@{ source = $exactManifest; frozen = $frozenExact; label = 'exact-K manifest' },
    [pscustomobject]@{ source = [string]$exactSummaryRecord.path; frozen = $frozenExactSummary; label = 'exact-K summary' },
    [pscustomobject]@{ source = $exitManifest; frozen = $frozenExit; label = 'accelerator-exit manifest' },
    [pscustomobject]@{ source = [string]$observationRecord.path; frozen = $frozenObservation; label = 'accelerator-exit observation' }
  )

  $sourceDir = Join-Path $inputDir 'source'
  New-Item -ItemType Directory -Path $sourceDir -Force | Out-Null
  $sourcePaths = @(
    'common\contracts\file_identity.py',
    'common\contracts\verify_run_manifest.py',
    'common\host_execution_lease.ps1',
    'common\host_resource_python.py',
    'common\host_resource_python.ps1',
    'common\host_resource_scheduler.py',
    'common\host_resource_policy.json',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\accelerator_exit_energy_calibration.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_exact_k_operating_point.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\drift_phase_contract.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_candidate_receipt.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_geometry_parameters.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_l0.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_l1.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\dual_stripe_l0.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\joint_mirror_stripe_l0.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\native_stripe_shape_adapter.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\resolved_geometry.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\simion_candidate_reference.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\run_accelerator_exit_energy_calibration.ps1'
  )
  $sourceInputs = [ordered]@{}
  $sourceChecks = @()
  for ($index = 0; $index -lt $sourcePaths.Count; $index++) {
    $source = Join-Path $repoRoot $sourcePaths[$index]
    $destination = Join-Path $sourceDir (('source_{0:D2}' -f ($index + 1)) + [IO.Path]::GetExtension($sourcePaths[$index]))
    $sourceInputs[('analytic_source_{0:D2}' -f ($index + 1))] = Copy-VerifiedRunInput -Source $source -Destination $destination
    $sourceChecks += [pscustomobject]@{ source = $source; frozen = $destination }
  }

  $configuration = Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
  $configuration.inputs = [ordered]@{
    candidate_contract = $frozenContract
    parent_exact_k_run_manifest = $frozenExact
    parent_exact_k_summary = $frozenExactSummary
    parent_accelerator_exit_run_manifest = $frozenExit
    accelerator_exit_observation = $frozenObservation
  }
  foreach ($entry in $sourceInputs.GetEnumerator()) { $configuration.inputs[$entry.Key] = $entry.Value }
  $configuration.parameters = [ordered]@{
    previous_cumulative_correction_v = $PreviousCumulativeCorrectionV
    response_model = 'unity_first_response'
    solver_execution = 'none'
    qualification = 'finite_3d_energy_command_proposal_only__new_real_simion_exit_required'
    geometry_change = 'none'
    refine_performed = $false
  }
  Write-RunJson -Path $runConfig -Depth 18 -Value $configuration

  $failureStage = 'finite_3d_energy_calibration'
  $proposalPath = Join-Path $resultDir 'accelerator_exit_energy_calibration_proposal.json'
  $analysisLog = Join-Path $logDir 'accelerator_exit_energy_calibration.log'
  $culture = [Globalization.CultureInfo]::InvariantCulture
  $arguments = @(
    '-m', 'projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_exit_energy_calibration',
    '--contract', $frozenContract,
    '--exact-k-manifest', $frozenExact,
    '--accelerator-exit-observation', $frozenObservation,
    '--previous-cumulative-correction-v', $PreviousCumulativeCorrectionV.ToString('R', $culture),
    '--output', $proposalPath
  )
  $lease = $null
  try {
    $lease = Enter-HostExecutionLease -Role GATE -Stage theory_compute -RunId $RunId
    Invoke-ProjectPython -Arguments $arguments -LogPath $analysisLog
  } finally {
    if ($lease) { Exit-HostExecutionLease -Lease $lease }
  }
  foreach ($pair in $sourceChecks) {
    if (-not (Test-RunFilesIdentical -Left $pair.source -Right $pair.frozen)) {
      throw "Frozen analytic source changed during execution: $($pair.source)"
    }
  }
  foreach ($pair in $inputChecks) {
    if (-not (Test-RunFilesIdentical -Left $pair.source -Right $pair.frozen)) {
      throw "Frozen $($pair.label) changed during execution: $($pair.source)"
    }
  }

  $proposal = Get-Content -LiteralPath $proposalPath -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
  if (
    $proposal.schema_version -ne 1 -or
    $proposal.role -ne 'mrtof_accelerator_finite_3d_energy_correction_proposal' -or
    $proposal.status -ne 'derived' -or
    $proposal.qualification -ne 'unity_response_first_correction_only__real_simion_exit_required'
  ) {
    throw 'Energy-calibration analysis did not publish the required proposal identity.'
  }
  if (
    [string]$proposal.inputs.contract_sha256 -ne $contractSha.ToLowerInvariant() -or
    [string]$proposal.inputs.exact_k_manifest_sha256 -ne $exactManifestSha.ToLowerInvariant() -or
    [string]$proposal.inputs.accelerator_exit_observation_sha256 -ne ([string]$observationRecord.sha256).ToLowerInvariant()
  ) {
    throw 'Energy-calibration proposal input identity differs from the frozen run inputs.'
  }
  Write-RunJson -Path $summary -Depth 14 -Value ([ordered]@{
    schema_version = 1
    role = 'mrtof_accelerator_finite_3d_energy_calibration'
    status = 'success'
    qualification = 'unity_response_first_correction_only__real_simion_exit_required'
    target_axial_energy_per_charge_v = [double]$proposal.target_axial_energy_per_charge_v
    measured_axial_hamiltonian_per_charge_v = [double]$proposal.measured_axial_hamiltonian_per_charge_v
    measured_minus_target_axial_energy_v = [double]$proposal.measured_minus_target_axial_energy_v
    previous_cumulative_correction_v = [double]$proposal.previous_cumulative_correction_v
    correction_increment_v = [double]$proposal.correction_increment_v
    proposed_cumulative_correction_v = [double]$proposal.proposed_cumulative_correction_v
    required_next_action = [string]$proposal.required_next_action
  })

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
    -Outputs @($summary, $proposalPath, $startupPath, $terminalPath, $retention, $exactVerifyLog, $exitVerifyLog, $analysisLog)
  $terminalized = $true
  Write-Host "MRTOF_ACCELERATOR_EXIT_ENERGY_CALIBRATION=PASS RUN_ID=$RunId PROPOSAL=$proposalPath"
} catch {
  if (-not $terminalized) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_accelerator_finite_3d_energy_calibration' -Reason $_.Exception.Message `
      -Software @('Python 3.11', 'SciPy') -Status failed -FailureStage $failureStage
    $terminalized = $true
  }
  throw
} finally {
  if (-not $terminalized -and (Test-Path -LiteralPath $runConfig -PathType Leaf)) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_accelerator_finite_3d_energy_calibration' `
      -Reason 'Runner stopped before terminal energy-calibration publication.' `
      -Software @('Python 3.11', 'SciPy') -Status interrupted -FailureStage $failureStage
  }
}
