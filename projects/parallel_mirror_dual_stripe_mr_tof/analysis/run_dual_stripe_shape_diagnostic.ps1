[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$MirrorRunManifest,
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
$contract = if ($ContractPath) {
  (Resolve-Path -LiteralPath $ContractPath).Path
} else {
  Join-Path $PSScriptRoot '..\config\simion_candidate_two_zone.json'
}
$parentManifest = (Resolve-Path -LiteralPath $MirrorRunManifest).Path
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__analysis__python__dual-stripe-shape-structure'
}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$artifactProjectRoot = Join-Path $workspaceRoot "artifacts\projects\$projectId"
$package = New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactProjectRoot `
  -RunId $RunId -Project $projectId -Mode 'dual_stripe_shape_structure_diagnostic' `
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
  try {
    $env:PYTHONPATH = $repoRoot
    & $python @Arguments 2>&1 | Tee-Object -FilePath $LogPath
    if ($LASTEXITCODE -ne 0) { throw "MR-TOF Python stage failed: $($Arguments -join ' ')" }
  } finally {
    $env:PYTHONPATH = $savedPythonPath
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
  $frozenContract = Copy-VerifiedRunInput -Source $contract -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
  $frozenParentManifest = Copy-VerifiedRunInput -Source $parentManifest -Destination (Join-Path $inputDir 'parent_mirror_run_manifest.json')
  $sourceDir = Join-Path $inputDir 'source'
  New-Item -ItemType Directory -Path $sourceDir -Force | Out-Null
  $sourcePaths = @(
    'common\contracts\file_identity.py',
    'common\contracts\verify_run_manifest.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\dual_stripe_l0.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\dual_stripe_shape_diagnostic.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_candidate_receipt.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_geometry_parameters.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\mirror_l0.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\resolved_geometry.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\simion_candidate_reference.py',
    'projects\parallel_mirror_dual_stripe_mr_tof\analysis\run_dual_stripe_shape_diagnostic.ps1'
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
  $configuration.inputs = [ordered]@{
    downstream_contract = $frozenContract
    parent_mirror_run_manifest = $frozenParentManifest
  }
  foreach ($entry in $sourceInputs.GetEnumerator()) { $configuration.inputs[$entry.Key] = $entry.Value }
  $configuration.parameters = [ordered]@{
    lifecycle_stage = 'fixed_cad_shape_structure_diagnostic'
    solver_execution = 'none'
    voltage_optimization = 'none'
  }
  Write-RunJson -Path $runConfig -Value $configuration

  foreach ($pair in $sourceChecks) {
    if (-not (Test-RunFilesIdentical -Left $pair.source -Right $pair.frozen)) {
      throw "Frozen analytic source differs before execution: $($pair.source)"
    }
  }

  $failureStage = 'shape_structure_diagnostic'
  Invoke-ProjectPython -LogPath (Join-Path $logDir 'shape_structure_diagnostic.log') -Arguments @(
    '-m', 'projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_shape_diagnostic',
    '--mirror-manifest', $frozenParentManifest,
    '--downstream-contract', $frozenContract,
    '--output', $summary
  )
  foreach ($pair in $sourceChecks) {
    if (-not (Test-RunFilesIdentical -Left $pair.source -Right $pair.frozen)) {
      throw "Analytic source changed during execution: $($pair.source)"
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
    -Outputs @($summary, $startupPath, $terminalPath, $retention, (Join-Path $logDir 'shape_structure_diagnostic.log'))
  $terminalized = $true
  Write-Host "MRTOF_DUAL_STRIPE_SHAPE_DIAGNOSTIC=PASS RUN_ID=$RunId SUMMARY=$summary"
} catch {
  if (-not $terminalized) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_fixed_cad_dual_stripe_structure_diagnostic' -Reason $_.Exception.Message `
      -Software @('Python 3.11', 'SciPy') -Status failed -FailureStage $failureStage
    $terminalized = $true
  }
  throw
} finally {
  if (-not $terminalized -and (Test-Path -LiteralPath $runConfig -PathType Leaf)) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_fixed_cad_dual_stripe_structure_diagnostic' `
      -Reason 'Runner stopped before terminal diagnostic publication.' `
      -Software @('Python 3.11', 'SciPy') -Status interrupted -FailureStage $failureStage
  }
}
