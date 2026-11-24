[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$MirrorRunManifest,
  [string]$ContractPath = '',
  [string]$RunId = '',
  [Parameter(Mandatory)][string]$WorkspaceRoot,
  [Parameter(Mandatory)][string]$ArtifactRoot,
  [Parameter(Mandatory)][string]$PythonExe
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectId = 'parallel_mirror_dual_stripe_mr_tof'
$workspaceRoot = (Resolve-Path -LiteralPath $WorkspaceRoot).Path
$repoRoot = $workspaceRoot
$artifactRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ArtifactRoot)
$python = [IO.Path]::GetFullPath($PythonExe)
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python 3.11 environment is missing: $python" }
$packageRootText = & $python -I -B -c 'from pathlib import Path;import msplatform;print(Path(msplatform.__file__).resolve().parent)'
if ($LASTEXITCODE -ne 0) { throw 'Installed msplatform package is unavailable.' }
$packageRoot = (Resolve-Path -LiteralPath $packageRootText).Path
$contract = if ($ContractPath) {
  (Resolve-Path -LiteralPath $ContractPath).Path
} else {
  Join-Path $packageRoot 'components\parallel_mirror_dual_stripe_mr_tof\simion_candidate_two_zone.json'
}
$parentManifest = (Resolve-Path -LiteralPath $MirrorRunManifest).Path
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__analysis__python__mirror-exact-k-operating-point'
}

$executionResources = Join-Path $packageRoot 'execution/resources'
$hostState = if ($env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH) { $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH } else { Join-Path $workspaceRoot 'artifacts/common/host_resources.sqlite3' }
$hostContext = @{workspace=$workspaceRoot;python_executable=$python;host_state_path=$hostState;policy_path=(Join-Path $executionResources 'host_resource_policy.json')}
. (Join-Path $executionResources 'host_execution_lease.ps1') -HostContext $hostContext
. (Join-Path $executionResources 'run_artifact_support.ps1')
$package = New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $artifactRoot "projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'analytic_mirror_exact_k_operating_point' `
  -Software @('Python 3.11', 'SciPy') -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled
$inputDir = $package.input_dir
$resultDir = $package.result_dir
$logDir = $package.log_dir
$runConfig = $package.run_config
$summary = $package.summary
$terminalized = $false
$failureStage = 'preflight'
$capacitySession = $null

function Invoke-ProjectPython {
  param([Parameter(Mandatory)][string[]]$Arguments, [Parameter(Mandatory)][string]$LogPath)
  Push-Location -LiteralPath $workspaceRoot
  $savedOpenBlasThreads = $env:OPENBLAS_NUM_THREADS
  $savedOmpThreads = $env:OMP_NUM_THREADS
  $savedMklThreads = $env:MKL_NUM_THREADS
  $savedNumExprThreads = $env:NUMEXPR_NUM_THREADS
  try {
    # The outer energy-node pool owns CPU parallelism.  Keep numerical kernels
    # single-threaded so each worker does not create a nested BLAS/OpenMP pool.
    $env:OPENBLAS_NUM_THREADS = '1'
    $env:OMP_NUM_THREADS = '1'
    $env:MKL_NUM_THREADS = '1'
    $env:NUMEXPR_NUM_THREADS = '1'
    & $python -I -B @Arguments 2>&1 | Tee-Object -FilePath $LogPath
    if ($LASTEXITCODE -ne 0) { throw "MR-TOF Python stage failed: $($Arguments -join ' ')" }
  } finally {
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
    -ArtifactRoot ($artifactRoot) -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes 2097152 -ProtectedPaths @($package.artifact_run_dir) `
    -Owner "mrtof-mirror-exact-k-operating-point:$RunId"
  $startupPath = Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startupPath -Depth 14 -Value $capacitySession

  $failureStage = 'freeze_inputs'
  $frozenContract = Copy-VerifiedRunInput -Source $contract `
    -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
  $frozenParentManifest = Copy-VerifiedRunInput -Source $parentManifest `
    -Destination (Join-Path $inputDir 'parent_mirror_run_manifest.json')
  $sourcePaths = @(
    'src\msplatform\execution\manifest_verification.py',
    # Current record-validation provenance; execution still uses the selected current package.
    'src\msplatform\__init__.py',
    'src\msplatform\io\__init__.py',
    'src\msplatform\execution\__init__.py',
    'src\msplatform\io\file_identity.py',
    'src\msplatform\io\manifest_records.py',
    'src\msplatform\execution\retention.py',
    'src\msplatform\execution\context.py',
    'src\msplatform\execution\recovery.py',
    'src\msplatform\contracts\__init__.py',
    'src\msplatform\contracts\machine_contracts.py',
    'src\msplatform\execution\artifact_retention.py',
    'src\msplatform\execution\manifest_publication.py',
    'src\msplatform\execution\recorded_file_removal.py',
    'src\msplatform\execution\file_lock.py',
    'src\msplatform\execution\terminal_publication.py',
    'src\msplatform\execution\artifact_naming.py',
    'src\msplatform\execution\resources\__init__.py',
    'src\msplatform\execution\resources\artifact_retention.json',
    'src\msplatform\execution\resources\host_execution_lease.ps1',
    'src\msplatform\execution\host_resource_scheduler.py',
    'src\msplatform\execution\resources\host_resource_policy.json',
    'src\msplatform\components\parallel_mirror_dual_stripe_mr_tof\dual_stripe_l0.py',
    'src\msplatform\workflows\mr_design\dual_stripe_operating_seed.py',
    'src\msplatform\components\parallel_mirror_dual_stripe_mr_tof\drift_phase_contract.py',
    'src\msplatform\workflows\prepared_joint\joint_mirror_stripe_l0.py',
    'src\msplatform\components\parallel_mirror_dual_stripe_mr_tof\mirror_candidate_receipt.py',
    'src\msplatform\workflows\mr_design\mirror_exact_k_operating_point.py',
    'src\msplatform\backends\simion\native_stripe_shape_adapter.py',
    'src\msplatform\components\parallel_mirror_dual_stripe_mr_tof\mirror_geometry_parameters.py',
    'src\msplatform\components\parallel_mirror_dual_stripe_mr_tof\mirror_l0.py',
    'src\msplatform\workflows\mr_design\mirror_l1.py',
    'src\msplatform\components\parallel_mirror_dual_stripe_mr_tof\resolved_geometry.py',
    'src\msplatform\components\parallel_mirror_dual_stripe_mr_tof\accelerator_requirements.py',
    'src\msplatform\components\orthogonal_accelerator\two_zone_geometry.py',
    'src\msplatform\components\orthogonal_accelerator\accelerator_time_focus.py',
    'src\msplatform\components\parallel_mirror_dual_stripe_mr_tof\geometry_contract.py',
    'src\msplatform\contracts\rigid_transform.py',
    'src\msplatform\backends\simion\mr_geometry.py',
    'src\msplatform\backends\simion\two_zone_candidate.py',
    'src\msplatform\backends\simion\rectangular_accelerator.py',
    'src\msplatform\backends\simion\bare_three_zone_component.py',
    'src\msplatform\components\parallel_mirror_dual_stripe_mr_tof\candidate_contract.py',
    'src\msplatform\workflows\resources\run_mirror_exact_k_operating_point.ps1',
    'src\msplatform\workflows\mr_design\__init__.py'
  )
  $configuration = Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
  $configuration.inputs = [ordered]@{
    candidate_contract = $frozenContract
    parent_mirror_run_manifest = $frozenParentManifest
  }
  $sourceChecks = @()
  for ($index = 0; $index -lt $sourcePaths.Count; $index++) {
    $source = Join-Path $packageRoot ($sourcePaths[$index] -replace '^src\\msplatform\\', '')
    $destination = Join-Path $inputDir (Join-Path 'source' $sourcePaths[$index])
    $frozen = Copy-VerifiedRunInput -Source $source -Destination $destination
    $configuration.inputs[('analytic_source_{0:D2}' -f ($index + 1))] = $frozen
    $sourceChecks += [pscustomobject]@{ source = $source; frozen = $frozen }
  }
  $configuration.parameters = [ordered]@{
    lifecycle_stage = 'solver_neutral_stripe_on_exact_k_energy_selection'
    governing_equation = 'T_D_stripe_on(E_z,v1(E_z),v2(E_z))/T_0=K after analytic 5-eV-turn and kappa-prime elimination'
    solver_execution = 'none'
    geometry_change = 'none'
    voltage_publication = 'receipt_only__not_simion_authority'
  }
  Write-RunJson -Path $runConfig -Value $configuration
  foreach ($pair in $sourceChecks) {
    if (-not (Test-RunFilesIdentical -Left $pair.source -Right $pair.frozen)) {
      throw "Frozen analytic source differs before execution: $($pair.source)"
    }
  }

  $failureStage = 'exact_k_operating_point'
  $theoryLease = $null
  try {
    $theoryLease = Enter-HostExecutionLease -Role GATE -Stage theory_compute -RunId $RunId
    Invoke-ProjectPython -LogPath (Join-Path $logDir 'exact_k_operating_point.log') -Arguments @(
      '-m', 'msplatform.workflows.mr_design.mirror_exact_k_operating_point',
      '--mirror-manifest', $frozenParentManifest,
      '--contract', $frozenContract,
      '--output', $summary
    )
  } finally {
    if ($theoryLease) { Exit-HostExecutionLease -Lease $theoryLease }
  }
  foreach ($pair in $sourceChecks) {
    if (-not (Test-RunFilesIdentical -Left $pair.source -Right $pair.frozen)) {
      throw "Analytic source changed during execution: $($pair.source)"
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
    -Outputs @($summary, $startupPath, $terminalPath, $retention, (Join-Path $logDir 'exact_k_operating_point.log'))
  $terminalized = $true
  Write-Host "MRTOF_MIRROR_EXACT_K_OPERATING_POINT=PASS RUN_ID=$RunId SUMMARY=$summary"
} catch {
  if (-not $terminalized) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_exact_k_mirror_energy_operating_point' -Reason $_.Exception.Message `
      -Software @('Python 3.11', 'SciPy') -Status failed -FailureStage $failureStage
    $terminalized = $true
  }
  throw
} finally {
  try {
    if (-not $terminalized -and (Test-Path -LiteralPath $runConfig -PathType Leaf)) {
      Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
        -SummaryRole 'mrtof_exact_k_mirror_energy_operating_point' `
        -Reason 'Runner stopped before terminal exact-K evidence publication.' `
        -Software @('Python 3.11', 'SciPy') -Status interrupted -FailureStage $failureStage
    }
  } finally {
    if ($null -ne $capacitySession) { $null = Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession }
  }
}
