[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$SeedRunManifest,
  [Parameter(Mandatory)][string]$Prism1PerturbationRunManifest,
  [Parameter(Mandatory)][string]$Prism2PerturbationRunManifest,
  [Parameter(Mandatory)][string[]]$IterationRunManifest,
  [string]$ContractPath = '',
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
$contract = if ($ContractPath) { (Resolve-Path -LiteralPath $ContractPath).Path } else {
  Join-Path $PSScriptRoot '..\config\simion_candidate_two_zone.json'
}
$seedManifest = (Resolve-Path -LiteralPath $SeedRunManifest).Path
$p1Manifest = (Resolve-Path -LiteralPath $Prism1PerturbationRunManifest).Path
$p2Manifest = (Resolve-Path -LiteralPath $Prism2PerturbationRunManifest).Path
$iterationManifests = @($IterationRunManifest | ForEach-Object { (Resolve-Path -LiteralPath $_).Path })
if ($iterationManifests.Count -lt 1) { throw 'At least one post-Jacobian P1/P2 iteration manifest is required.' }
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__analysis__python__two-prism-operating-point'
}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$package = New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'finite_3d_two_prism_operating_point_audit' `
  -Software @('Python 3.11', 'NumPy') -RetentionContractEnabled -RetentionClass compact
$inputDir = $package.input_dir
$resultDir = $package.result_dir
$logDir = $package.log_dir
$runConfig = $package.run_config
$summary = $package.summary
$terminalized = $false
$failureStage = 'preflight'

try {
  $allManifests = @($seedManifest, $p1Manifest, $p2Manifest) + $iterationManifests
  foreach ($manifest in $allManifests) {
    & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $manifest --require-status success `
      --require-project $projectId --require-mode finite_3d_two_prism_voltage_trial
    if ($LASTEXITCODE -ne 0) { throw "Upstream P1/P2 trial manifest failed verification: $manifest" }
  }

  $failureStage = 'capacity_startup'
  $startup = Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -ProtectedPaths @($package.artifact_run_dir) `
    -RequiredHeadroomBytes 2097152
  $startupPath = Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $startupPath -Depth 14 -Value $startup

  $failureStage = 'freeze_inputs'
  $frozenContract = Copy-VerifiedRunInput -Source $contract -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
  $configuration = Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
  $configuration.inputs = [ordered]@{ candidate_contract = $frozenContract }
  $configuration.parameters = [ordered]@{
    lifecycle_stage = 'single_center_two_prism_phase_space_handoff_audit'
    solver_execution = 'none__consume_verified_SIMION_trials'
    voltage_authority = 'derived_from_trial_observations__not_user_entered'
    downstream_claim = 'K25_pending'
  }
  for ($index = 0; $index -lt $allManifests.Count; $index++) {
    $manifest = $allManifests[$index]
    $label = 'trial_{0:D2}' -f ($index + 1)
    $configuration.inputs[($label + '_manifest')] = Copy-VerifiedRunInput -Source $manifest `
      -Destination (Join-Path $inputDir ($label + '_run_manifest.json'))
    $sourceRun = Split-Path -Parent $manifest
    foreach ($filename in @('two_prism_trial_observation.json', 'two_prism_trial_materialization.json')) {
      $source = Join-Path (Join-Path $sourceRun 'results') $filename
      $stem = [IO.Path]::GetFileNameWithoutExtension($filename)
      $configuration.inputs[($label + '_' + $stem)] = Copy-VerifiedRunInput -Source $source `
        -Destination (Join-Path $inputDir ($label + '_' + $filename))
    }
  }
  Write-RunJson -Path $runConfig -Value $configuration

  $failureStage = 'audit_operating_point'
  $arguments = @(
    '-m', 'projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_operating_point',
    '--contract', $frozenContract,
    '--seed-manifest', $seedManifest,
    '--prism-1-perturbation-manifest', $p1Manifest,
    '--prism-2-perturbation-manifest', $p2Manifest
  )
  foreach ($manifest in $iterationManifests) { $arguments += @('--iteration-manifest', $manifest) }
  $arguments += @('--output', $summary)
  Push-Location -LiteralPath $repoRoot
  $savedPythonPath = $env:PYTHONPATH
  try {
    $env:PYTHONPATH = $repoRoot
    & $python @arguments 2>&1 | Tee-Object -FilePath (Join-Path $logDir 'two_prism_operating_point.log')
    if ($LASTEXITCODE -ne 0) { throw 'P1/P2 operating-point audit failed.' }
  } finally {
    $env:PYTHONPATH = $savedPythonPath
    Pop-Location
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
    -Software @('Python 3.11', 'NumPy') `
    -Outputs @($summary, $startupPath, $terminalPath, $retention, (Join-Path $logDir 'two_prism_operating_point.log'))
  $terminalized = $true
  Write-Host "MRTOF_TWO_PRISM_OPERATING_POINT=PASS RUN_ID=$RunId SUMMARY=$summary"
} catch {
  if (-not $terminalized) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_finite_3d_two_prism_operating_point_audit' -Reason $_.Exception.Message `
      -Software @('Python 3.11', 'NumPy') -Status failed -FailureStage $failureStage
    $terminalized = $true
  }
  throw
} finally {
  if (-not $terminalized -and (Test-Path -LiteralPath $runConfig -PathType Leaf)) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_finite_3d_two_prism_operating_point_audit' `
      -Reason 'Runner stopped before terminal P1/P2 evidence publication.' `
      -Software @('Python 3.11', 'NumPy') -Status interrupted -FailureStage $failureStage
  }
}
