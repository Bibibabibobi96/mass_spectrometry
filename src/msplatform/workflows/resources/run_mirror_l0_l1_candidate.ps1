[CmdletBinding()]
param(
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
$contractInput = if ($ContractPath) {
  (Resolve-Path -LiteralPath $ContractPath).Path
} else {
  Join-Path $packageRoot 'components\parallel_mirror_dual_stripe_mr_tof\simion_candidate_two_zone.json'
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__analysis__python__mirror-l0-l1-family'
}

. (Join-Path $packageRoot 'execution/resources/run_artifact_support.ps1')
$package = New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Resolve-RunArtifactRoot -ArtifactRoot $artifactRoot -OwnerKind component -OwnerId $projectId -Python $python) `
  -RunId $RunId -Project $projectId -Mode 'analytic_mirror_l0_l1_candidate' `
  -Software @('Python 3.11', 'SciPy') -RetentionContractEnabled `
  -CapacityLedgerLifecycleEnabled
$inputDir = $package.input_dir
$resultDir = $package.result_dir
$logDir = $package.log_dir
$runConfig = $package.run_config
$summary = $package.summary
$artifactCapacityRoot = $artifactRoot
$capacitySession = $null
$terminalized = $false
$failureStage = 'preflight'

function Invoke-MirrorPython {
  param(
    [Parameter(Mandatory)][string]$Stage,
    [Parameter(Mandatory)][string[]]$Arguments
  )
  Push-Location -LiteralPath $workspaceRoot
  try {
      & $python -I -B @Arguments 2>&1 | Tee-Object -FilePath (Join-Path $logDir "$Stage.log")
      if ($LASTEXITCODE -ne 0) { throw "MR-TOF analytic stage failed: $Stage" }
  } finally {
    Pop-Location
  }
}

function Assert-FrozenSourcesUnchanged {
  param([Parameter(Mandatory)][object[]]$Records)
  foreach ($record in $Records) {
    if (-not (Test-RunFilesIdentical -Left ([string]$record.source) -Right ([string]$record.frozen))) {
      throw "Analytic source changed after it was frozen: $($record.source)"
    }
  }
}

try {
  $sourceRelativePaths = @(
    'src\msplatform\execution\resources\host_execution_lease.ps1',
    'src\msplatform\execution\host_resource_scheduler.py',
    'src\msplatform\execution\resources\host_resource_policy.json',
    'src\msplatform\io\file_identity.py',
    'src\msplatform\components\orthogonal_accelerator\accelerator_time_focus.py',
    'src\msplatform\components\orthogonal_accelerator\two_zone_geometry.py',
    'src\msplatform\components\orthogonal_accelerator\two_zone_theory.py',
    'src\msplatform\components\parallel_mirror_dual_stripe_mr_tof\mirror_geometry_parameters.py',
    'src\msplatform\components\parallel_mirror_dual_stripe_mr_tof\mirror_l0.py',
    'src\msplatform\workflows\mr_design\__init__.py',
    'src\msplatform\workflows\mr_design\mirror_l0_hardware_candidate.py',
    'src\msplatform\workflows\mr_design\mirror_l0_l1_hardware_candidate.py',
    'src\msplatform\workflows\mr_design\mirror_l0_l1_run_summary.py',
    'src\msplatform\workflows\mr_design\mirror_l1.py',
    'src\msplatform\workflows\resources\run_mirror_l0_l1_candidate.ps1',
    'src\msplatform\components\parallel_mirror_dual_stripe_mr_tof\candidate_contract.py'
  )
  $sourcePaths = @($sourceRelativePaths | ForEach-Object { Join-Path $packageRoot ($_ -replace '^src\\msplatform\\', '') })
  $inputCopyBytes = [int64](Get-Item -LiteralPath $contractInput).Length
  foreach ($sourcePath in $sourcePaths) {
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) { throw "Analytic source is missing: $sourcePath" }
    $inputCopyBytes += [int64](Get-Item -LiteralPath $sourcePath).Length
  }

  $failureStage = 'capacity_preflight'
  $capacitySession = Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot $artifactCapacityRoot -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes $inputCopyBytes -ProtectedPaths @($package.artifact_run_dir) `
    -Owner "mrtof-mirror-l0-l1-candidate:$RunId"
  $artifactCapacityStartupPath = Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $artifactCapacityStartupPath -Depth 14 -Value $capacitySession

  $failureStage = 'freeze_inputs'
  $frozenContract = Copy-VerifiedRunInput -Source $contractInput `
    -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
  $sourceRecords = @()
  for ($index = 0; $index -lt $sourcePaths.Count; $index++) {
    $destination = Join-Path $inputDir (Join-Path 'source' $sourceRelativePaths[$index])
    $frozen = Copy-VerifiedRunInput -Source $sourcePaths[$index] -Destination $destination
    $sourceRecords += [pscustomobject]@{
      relative_path = $sourceRelativePaths[$index]
      source = $sourcePaths[$index]
      frozen = $frozen
      sha256 = Get-RunFileSha256 -Path $frozen
    }
  }
  Assert-FrozenSourcesUnchanged -Records $sourceRecords
  $sourceIdentityPath = Join-Path $inputDir 'analytic_source_identity.json'
  Write-RunJson -Path $sourceIdentityPath -Depth 6 -Value ([ordered]@{
    schema_version = 1
    role = 'mrtof_mirror_l0_l1_analytic_source_identity'
    files = @($sourceRecords | ForEach-Object {
      [ordered]@{ relative_path = $_.relative_path; sha256 = $_.sha256 }
    })
  })
  $runConfigDocument = Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
  $runConfigDocument.inputs = [ordered]@{
    candidate_contract = $frozenContract
    analytic_source_identity = $sourceIdentityPath
  }
  for ($index = 0; $index -lt $sourceRecords.Count; $index++) {
    $runConfigDocument.inputs[('analytic_source_{0:D2}' -f ($index + 1))] = $sourceRecords[$index].frozen
  }
  $runConfigDocument.parameters = [ordered]@{
    lifecycle_stage = 'frozen_inputs_ready'
    mirror_search = '36 deterministic full-envelope restarts followed by L1 family screening and gamma-target intersection'
    solver_execution = 'none'
  }
  Write-RunJson -Path $runConfig -Value $runConfigDocument

  $l0Receipt = Join-Path $resultDir 'mirror_l0_family_receipt.json'
  $l1Receipt = Join-Path $resultDir 'mirror_l0_l1_candidate_receipt.json'
  $failureStage = 'mirror_l0_family_search'
  Invoke-MirrorPython -Stage 'mirror_l0_family_search' -Arguments @(
    '-m', 'msplatform.workflows.mr_design.mirror_l0_hardware_candidate',
    '--contract', $frozenContract, '--output', $l0Receipt
  )
  Assert-FrozenSourcesUnchanged -Records $sourceRecords

  $failureStage = 'mirror_l1_family_selection'
  Invoke-MirrorPython -Stage 'mirror_l1_family_selection' -Arguments @(
    '-m', 'msplatform.workflows.mr_design.mirror_l0_l1_hardware_candidate',
    '--l0-receipt', $l0Receipt, '--contract', $frozenContract, '--output', $l1Receipt
  )
  Assert-FrozenSourcesUnchanged -Records $sourceRecords

  $failureStage = 'validate_receipt_chain'
  Invoke-MirrorPython -Stage 'validate_receipt_chain' -Arguments @(
    '-m', 'msplatform.workflows.mr_design.mirror_l0_l1_run_summary',
    '--contract', $frozenContract, '--l0-receipt', $l0Receipt, '--l1-receipt', $l1Receipt,
    '--output', $summary
  )
  Assert-FrozenSourcesUnchanged -Records $sourceRecords

  $failureStage = 'retention'
  $retention = Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $failureStage = 'capacity_terminal'
  $artifactCapacityTerminal = Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -Session $capacitySession -RemainingCommittedNewBytes 0
  $capacitySession = $artifactCapacityTerminal.session
  $artifactCapacityTerminalPath = Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $artifactCapacityTerminalPath -Depth 14 -Value $artifactCapacityTerminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('Python 3.11', 'SciPy') `
    -Outputs @($summary, $l0Receipt, $l1Receipt, $sourceIdentityPath, $retention,
      $artifactCapacityStartupPath, $artifactCapacityTerminalPath,
      (Join-Path $logDir 'mirror_l0_family_search.log'),
      (Join-Path $logDir 'mirror_l1_family_selection.log'),
      (Join-Path $logDir 'validate_receipt_chain.log'))
  $terminalized = $true
  Write-Host "MRTOF_MIRROR_L0_L1_CANDIDATE=PASS RUN_ID=$RunId SUMMARY=$summary"
} catch {
  if (-not $terminalized) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_mirror_l0_l1_candidate_summary' -Reason $_.Exception.Message `
      -Software @('Python 3.11', 'SciPy') -Status failed -FailureStage $failureStage
    $terminalized = $true
  }
  throw
} finally {
  try {
    if (-not $terminalized -and (Test-Path -LiteralPath $runConfig -PathType Leaf)) {
      Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
        -SummaryRole 'mrtof_mirror_l0_l1_candidate_summary' `
        -Reason 'Runner stopped before terminal analytic evidence publication.' `
        -Software @('Python 3.11', 'SciPy') -Status interrupted -FailureStage $failureStage
    }
  } finally {
    try {
      if ($null -ne $capacitySession) { $null = Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession }
    } finally {
      Remove-RunPackageExecutionAlias -Package $package
    }
  }
}
