[CmdletBinding()]
param(
  [string]$MirrorRunManifest = '',
  [string]$ExactKRunManifest = '',
  [string]$ExistingOperatingSeedManifest = '',
  [string]$ContractPath = '',
  [string]$RunId = '',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectId = 'parallel_mirror_dual_stripe_mr_tof'
$authorityOnly = -not [string]::IsNullOrWhiteSpace($ExistingOperatingSeedManifest)
$exactKMode = -not [string]::IsNullOrWhiteSpace($ExactKRunManifest)
$inputModeCount = [int]$authorityOnly +
  [int](-not [string]::IsNullOrWhiteSpace($MirrorRunManifest)) +
  [int]$exactKMode
if ($inputModeCount -ne 1) { throw 'Specify exactly one input: -MirrorRunManifest, -ExactKRunManifest, or -ExistingOperatingSeedManifest.' }
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python 3.11 environment is missing: $python" }
$contract = if ($ContractPath) { (Resolve-Path -LiteralPath $ContractPath).Path } else { Join-Path $PSScriptRoot '..\config\simion_candidate_two_zone.json' }
$parentManifest = if ($authorityOnly) {
  (Resolve-Path -LiteralPath $ExistingOperatingSeedManifest).Path
} elseif ($exactKMode) {
  (Resolve-Path -LiteralPath $ExactKRunManifest).Path
} else {
  (Resolve-Path -LiteralPath $MirrorRunManifest).Path
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $suffix = if ($authorityOnly) { 'fixed-stripe-parameter-authority' } elseif ($exactKMode) { 'dual-stripe-exact-k-operating-seed' } else { 'dual-stripe-operating-seed' }
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__analysis__python__' + $suffix
}
$runMode = if ($authorityOnly) { 'fixed_stripe_parameter_authority' } elseif ($exactKMode) { 'dual_stripe_exact_k_downstream_seed' } else { 'dual_stripe_paper_theory_instance_seed' }
$qualification = if ($authorityOnly) {
  'solver_neutral_parameter_authority__not_an_operating_point'
} elseif ($exactKMode) {
  'solver_neutral_nominal_initialization__P1_P2_and_finite_3d_pending'
} else {
  'analytic_manufactured_basis_voltage_inverse__finite_3d_tuning_pending'
}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$package = New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode $runMode `
  -Software @('Python 3.11', 'SciPy') -RetentionContractEnabled -RetentionClass compact
$inputDir = $package.input_dir
$resultDir = $package.result_dir
$logDir = $package.log_dir
$runConfig = $package.run_config
$summary = $package.summary
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
    if ($LASTEXITCODE -ne 0) { throw "MR-TOF Python stage failed: $($Arguments -join ' ')" }
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
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -ProtectedPaths @($package.artifact_run_dir) `
    -RequiredHeadroomBytes 1048576
  $startupPath = Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startupPath -Depth 14 -Value $startup

  $failureStage = 'freeze_inputs'
  if ($authorityOnly) {
    $frozenParentManifest = Copy-VerifiedRunInput -Source $parentManifest -Destination (Join-Path $inputDir 'parent_operating_seed_run_manifest.json')
    $frozenContract = $null
  } elseif ($exactKMode) {
    $frozenContract = Copy-VerifiedRunInput -Source $contract -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
    $frozenParentManifest = Copy-VerifiedRunInput -Source $parentManifest -Destination (Join-Path $inputDir 'parent_exact_k_run_manifest.json')
  } else {
    $frozenContract = Copy-VerifiedRunInput -Source $contract -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
    $frozenParentManifest = Copy-VerifiedRunInput -Source $parentManifest -Destination (Join-Path $inputDir 'parent_mirror_run_manifest.json')
  }
  $sourceDir = Join-Path $inputDir 'source'
  New-Item -ItemType Directory -Path $sourceDir -Force | Out-Null
  $sourcePaths = @(
    'common\contracts\file_identity.py',
    'common\contracts\verify_run_manifest.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\dual_stripe_l0.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\dual_stripe_operating_seed.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\joint_mirror_stripe_l0.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_candidate_receipt.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_exact_k_operating_point.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_geometry_parameters.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_l0.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_l1.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\resolved_geometry.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\simion_candidate_reference.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\two_prism_handoff.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\run_dual_stripe_operating_seed.ps1'
  )
  $sourceInputs = [ordered]@{}
  $sourceChecks = @()
  for ($index = 0; $index -lt $sourcePaths.Count; $index++) {
    $source = Join-Path $repoRoot $sourcePaths[$index]
    $destination = Join-Path $sourceDir (('source_{0:D2}' -f ($index + 1)) + [IO.Path]::GetExtension($source))
    $sourceInputs[('analytic_source_{0:D2}' -f ($index + 1))] = Copy-VerifiedRunInput -Source $source -Destination $destination
    $sourceChecks += [pscustomobject]@{ source = $source; frozen = $destination }
  }
  $configuration = Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
  $configuration.inputs = [ordered]@{}
  if ($authorityOnly) {
    $configuration.inputs.parent_operating_seed_run_manifest = $frozenParentManifest
  } elseif ($exactKMode) {
    $configuration.inputs.downstream_contract = $frozenContract
    $configuration.inputs.parent_exact_k_run_manifest = $frozenParentManifest
  } else {
    $configuration.inputs.downstream_contract = $frozenContract
    $configuration.inputs.parent_mirror_run_manifest = $frozenParentManifest
  }
  foreach ($entry in $sourceInputs.GetEnumerator()) { $configuration.inputs[$entry.Key] = $entry.Value }
  $configuration.parameters = [ordered]@{
    lifecycle_stage = $runMode
    solver_execution = 'none'
    qualification = $qualification
  }
  Write-RunJson -Path $runConfig -Value $configuration
  foreach ($pair in $sourceChecks) {
    if (-not (Test-RunFilesIdentical -Left $pair.source -Right $pair.frozen)) { throw "Frozen analytic source differs before execution: $($pair.source)" }
  }

  $failureStage = if ($authorityOnly) { 'parameter_authority_derivation' } elseif ($exactKMode) { 'exact_k_analytic_basis_voltage_inverse' } else { 'analytic_basis_voltage_inverse' }
  $logPath = Join-Path $logDir 'dual_stripe_operating_seed.log'
  $pythonArguments = if ($authorityOnly) {
    @(
      '-m', 'projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_operating_seed',
      '--source-operating-seed-manifest', $frozenParentManifest,
      '--output', $summary
    )
  } elseif ($exactKMode) {
    @(
      '-m', 'projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_operating_seed',
      '--exact-k-manifest', $frozenParentManifest,
      '--downstream-contract', $frozenContract,
      '--output', $summary
    )
  } else {
    @(
      '-m', 'projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_operating_seed',
      '--mirror-manifest', $frozenParentManifest,
      '--downstream-contract', $frozenContract,
      '--output', $summary
    )
  }
  Invoke-ProjectPython -LogPath $logPath -Arguments $pythonArguments
  foreach ($pair in $sourceChecks) {
    if (-not (Test-RunFilesIdentical -Left $pair.source -Right $pair.frozen)) { throw "Analytic source changed during execution: $($pair.source)" }
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
    -Software @('Python 3.11', 'SciPy') -Outputs @($summary, $startupPath, $terminalPath, $retention, $logPath)
  $terminalized = $true
  $marker = if ($authorityOnly) { 'MRTOF_FIXED_STRIPE_PARAMETER_AUTHORITY' } elseif ($exactKMode) { 'MRTOF_DUAL_STRIPE_EXACT_K_OPERATING_SEED' } else { 'MRTOF_DUAL_STRIPE_OPERATING_SEED' }
  Write-Host "$marker=PASS RUN_ID=$RunId SUMMARY=$summary"
} catch {
  if (-not $terminalized) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole $(if ($authorityOnly) { 'mrtof_fixed_stripe_geometry_parameter_authority' } else { 'mrtof_dual_stripe_paper_theory_instance_specific_operating_seed' }) `
      -Reason $_.Exception.Message -Software @('Python 3.11', 'SciPy') -Status failed -FailureStage $failureStage
    $terminalized = $true
  }
  throw
} finally {
  if (-not $terminalized -and (Test-Path -LiteralPath $runConfig -PathType Leaf)) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole $(if ($authorityOnly) { 'mrtof_fixed_stripe_geometry_parameter_authority' } else { 'mrtof_dual_stripe_paper_theory_instance_specific_operating_seed' }) `
      -Reason 'Runner stopped before terminal seed publication.' `
      -Software @('Python 3.11', 'SciPy') -Status interrupted -FailureStage $failureStage
  }
}
