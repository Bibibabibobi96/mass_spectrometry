[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$MirrorReceiptPath,
  [Parameter(Mandatory)][string]$AnalyzerGemPath,
  [Parameter(Mandatory)][string]$AnalyzerPa0Path,
  [Parameter(Mandatory)][string]$AcceleratorGemPath,
  [Parameter(Mandatory)][string]$AcceleratorPa0Path,
  [Parameter(Mandatory)][string]$DetectorPaPath,
  [string]$ContractPath = '',
  [string]$RunId = '',
  [string]$SimionExe = '',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# This runner deliberately stops after native IOB construction and reload
# inspection.  It never invokes Fly: a separately approved flight runner must
# consume this run-local, inspected package and its frozen source manifest.
function Invoke-MrtofPython {
  param([Parameter(Mandatory)][string[]]$Arguments)
  Push-Location -LiteralPath $repoRoot
  $savedPythonPath = $env:PYTHONPATH
  try {
    $env:PYTHONPATH = $repoRoot
    & $python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "MR-TOF Python invocation failed: $($Arguments -join ' ')" }
  } finally {
    $env:PYTHONPATH = $savedPythonPath
    Pop-Location
  }
}

function Copy-RequiredRunInput {
  param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$Destination,
    [Parameter(Mandatory)][string]$Label
  )
  if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
    throw "$Label is missing: $Source"
  }
  Copy-VerifiedRunInput -Source $Source -Destination $Destination
}

function Invoke-MrtofSimionStep {
  param([Parameter(Mandatory)][string]$Stage, [Parameter(Mandatory)][string[]]$Arguments)
  Push-Location -LiteralPath $solverDir
  try {
    & $simion @Arguments 2>&1 | Tee-Object -FilePath (Join-Path $logDir "$Stage.log")
    if ($LASTEXITCODE -ne 0) { throw "SIMION stage failed: $Stage" }
  } finally {
    Pop-Location
  }
}

$projectId = 'parallel_mirror_dual_stripe_mr_tof'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$projectRoot = Join-Path $repoRoot "projects\$projectId"
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
$simion = if ($SimionExe) { [IO.Path]::GetFullPath($SimionExe) } else { Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe' }
$contractInput = if ($ContractPath) { (Resolve-Path -LiteralPath $ContractPath).Path } else { Join-Path $projectRoot 'config\simion_candidate_two_zone.json' }
$mirrorReceiptInput = (Resolve-Path -LiteralPath $MirrorReceiptPath).Path
$analyzerGemInput = (Resolve-Path -LiteralPath $AnalyzerGemPath).Path
$analyzerPaInput = (Resolve-Path -LiteralPath $AnalyzerPa0Path).Path
$acceleratorGemInput = (Resolve-Path -LiteralPath $AcceleratorGemPath).Path
$acceleratorPaInput = (Resolve-Path -LiteralPath $AcceleratorPa0Path).Path
$detectorPaInput = (Resolve-Path -LiteralPath $DetectorPaPath).Path

if ([IO.Path]::GetExtension($analyzerPaInput) -cne '.pa0' -or
    [IO.Path]::GetExtension($acceleratorPaInput) -cne '.pa0' -or
    [IO.Path]::GetExtension($detectorPaInput) -cne '.pa#') {
  throw 'Runner requires solved analyzer/accelerator .pa0 inputs and a raw detector .pa# input.'
}
if ([IO.Path]::GetExtension($analyzerGemInput) -cne '.gem' -or
    [IO.Path]::GetExtension($acceleratorGemInput) -cne '.gem') {
  throw 'Runner requires the exact analyzer and accelerator .gem sources that built its PA families.'
}
if (-not (Test-Path -LiteralPath $simion -PathType Leaf)) { throw "SIMION executable is missing: $simion" }
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__build__simion__mrtof-three-component-iob'
}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$seedDirectory = Join-Path $repoRoot 'common\simion\assets\iob_instance_seeds'
$package = New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'three_component_candidate_iob_assembly' `
  -Software @('SIMION 2020', 'Python 3.11') -RetentionContractEnabled -RetentionClass solver_review `
  -RetentionReason 'Native PA family and IOB are required for SIMION GUI geometry and voltage review.' `
  -AdditionalDirectories @('simion') -UseShortExecutionPath
$runDir = $package.run_dir
$inputDir = $package.input_dir
$resultDir = $package.result_dir
$logDir = $package.log_dir
$solverDir = Join-Path $runDir 'simion'
$runConfig = $package.run_config
$summary = $package.summary
$artifactCapacityRoot = Join-Path $workspaceRoot 'artifacts'
$artifactCapacityStartup = $null
$terminalized = $false
$failureStage = 'preflight'
$hostExecutionOutcome = 'failed'
$hostExecutionLease = $null

# Solver invocations may use a short-lived junction, but the persisted run
# contract must never point at that alias: it is removed in finally and would
# make an otherwise valid interrupted-run manifest unverifiable.
function ConvertTo-ArtifactRunPath {
  param([Parameter(Mandatory)][string]$Path)
  $full = [IO.Path]::GetFullPath($Path)
  $executionRoot = [IO.Path]::GetFullPath([string]$package.run_dir).TrimEnd([char[]]@(92, 47))
  $artifactRoot = [IO.Path]::GetFullPath([string]$package.artifact_run_dir).TrimEnd([char[]]@(92, 47))
  if ($full.Equals($executionRoot, [StringComparison]::OrdinalIgnoreCase)) { return $artifactRoot }
  if ($full.StartsWith($executionRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    return $artifactRoot + $full.Substring($executionRoot.Length)
  }
  return $full
}

try {
  $failureStage = 'capacity_preflight'
  # This run-local review package copies the two complete solved PA families.
  # Reserve their actual frozen source bytes rather than a stale size budget;
  # the capacity gate owns eviction order and protects the new run package.
  $paSources = @(
    $analyzerPaInput, ($analyzerPaInput -replace '\.pa0$', '.pa#'),
    $acceleratorPaInput, ($acceleratorPaInput -replace '\.pa0$', '.pa#'), $detectorPaInput
  )
  foreach ($index in 1..20) { $paSources += ($analyzerPaInput -replace '\.pa0$', ".pa$index") }
  foreach ($index in 1..9) { $paSources += ($acceleratorPaInput -replace '\.pa0$', ".pa$index") }
  $frozenInputSources = @(
    $paSources + @(
      $contractInput, $mirrorReceiptInput, $analyzerGemInput, $acceleratorGemInput,
      (Join-Path $seedDirectory '3_instance_seed.iob'),
      (Join-Path $projectRoot 'simion\build_three_component_iob.lua'),
      (Join-Path $projectRoot 'simion\inspect_three_component_iob.lua'),
      (Join-Path $projectRoot 'analysis\three_component_simion_run_manifest.py')
    )
  )
  foreach ($index in 1..10) {
    $frozenInputSources += (Join-Path $seedDirectory ('iob_seed_placeholder_{0:D2}.pa0' -f $index))
  }
  [int64]$inputCopyBytes = 0
  foreach ($source in $frozenInputSources) {
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Required frozen input source is missing: $source" }
    $inputCopyBytes += [int64](Get-Item -LiteralPath $source).Length
  }
  $artifactCapacityStartup = Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot $artifactCapacityRoot -RequiredHeadroomBytes $inputCopyBytes `
    -ProtectedPaths @($package.artifact_run_dir)
  $artifactCapacityStartupPath = Join-Path $resultDir 'artifact_capacity_gate_startup.json'
  Write-RunJson -Path $artifactCapacityStartupPath -Depth 14 -Value $artifactCapacityStartup

  $failureStage = 'freeze_inputs'
  $frozenContract = Copy-RequiredRunInput -Source $contractInput -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json') -Label 'candidate contract'
  $frozenMirrorReceipt = Copy-RequiredRunInput -Source $mirrorReceiptInput -Destination (Join-Path $inputDir 'mirror_l0_l1_receipt.json') -Label 'mirror receipt'
  $frozenAnalyzerGem = Copy-RequiredRunInput -Source $analyzerGemInput -Destination (Join-Path $solverDir 'mrtof_analyzer.gem') -Label 'analyzer GEM source'
  $frozenAnalyzerPa = Copy-RequiredRunInput -Source $analyzerPaInput -Destination (Join-Path $solverDir 'mrtof_analyzer.pa0') -Label 'analyzer PA0'
  $frozenAcceleratorGem = Copy-RequiredRunInput -Source $acceleratorGemInput -Destination (Join-Path $solverDir 'mrtof_accelerator.gem') -Label 'accelerator GEM source'
  $frozenAcceleratorPa = Copy-RequiredRunInput -Source $acceleratorPaInput -Destination (Join-Path $solverDir 'mrtof_accelerator.pa0') -Label 'accelerator PA0'
  $frozenDetectorPa = Copy-RequiredRunInput -Source $detectorPaInput -Destination (Join-Path $solverDir 'mrtof_detector.pa#') -Label 'detector PA#'
  $analyzerRawSource = $analyzerPaInput -replace '\.pa0$', '.pa#'
  $acceleratorRawSource = $acceleratorPaInput -replace '\.pa0$', '.pa#'
  $frozenAnalyzerRawPa = Copy-RequiredRunInput -Source $analyzerRawSource -Destination (Join-Path $solverDir 'mrtof_analyzer.pa#') -Label 'analyzer raw PA# companion'
  $frozenAcceleratorRawPa = Copy-RequiredRunInput -Source $acceleratorRawSource -Destination (Join-Path $solverDir 'mrtof_accelerator.pa#') -Label 'accelerator raw PA# companion'
  foreach ($index in 1..20) {
    Copy-RequiredRunInput -Source ($analyzerPaInput -replace '\.pa0$', ".pa$index") `
      -Destination (Join-Path $solverDir "mrtof_analyzer.pa$index") -Label "analyzer basis PA$index" | Out-Null
  }
  foreach ($index in 1..9) {
    Copy-RequiredRunInput -Source ($acceleratorPaInput -replace '\.pa0$', ".pa$index") `
      -Destination (Join-Path $solverDir "mrtof_accelerator.pa$index") -Label "accelerator basis PA$index" | Out-Null
  }
  $seed = Copy-RequiredRunInput -Source (Join-Path $seedDirectory '3_instance_seed.iob') -Destination (Join-Path $solverDir '3_instance_seed.iob') -Label 'three-instance IOB seed'
  foreach ($index in 1..10) {
    $name = 'iob_seed_placeholder_{0:D2}.pa0' -f $index
    Copy-RequiredRunInput -Source (Join-Path $seedDirectory $name) -Destination (Join-Path $solverDir $name) -Label "three-instance seed companion $index" | Out-Null
  }
  $builder = Copy-RequiredRunInput -Source (Join-Path $projectRoot 'simion\build_three_component_iob.lua') -Destination (Join-Path $solverDir 'build_three_component_iob.lua') -Label 'IOB builder'
  $inspector = Copy-RequiredRunInput -Source (Join-Path $projectRoot 'simion\inspect_three_component_iob.lua') -Destination (Join-Path $solverDir 'inspect_three_component_iob.lua') -Label 'IOB inspector'
  $geometryManifestWriter = Copy-RequiredRunInput -Source (Join-Path $projectRoot 'analysis\three_component_simion_run_manifest.py') -Destination (Join-Path $solverDir 'three_component_simion_run_manifest.py') -Label 'geometry-review manifest writer'
  $runConfigDocument = Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
  $runConfigDocument.inputs = [ordered]@{
    candidate_contract = ConvertTo-ArtifactRunPath $frozenContract; mirror_receipt = ConvertTo-ArtifactRunPath $frozenMirrorReceipt
    analyzer_gem = ConvertTo-ArtifactRunPath $frozenAnalyzerGem; analyzer_pa0 = ConvertTo-ArtifactRunPath $frozenAnalyzerPa; analyzer_raw_pa = ConvertTo-ArtifactRunPath $frozenAnalyzerRawPa
    accelerator_gem = ConvertTo-ArtifactRunPath $frozenAcceleratorGem; accelerator_pa0 = ConvertTo-ArtifactRunPath $frozenAcceleratorPa; accelerator_raw_pa = ConvertTo-ArtifactRunPath $frozenAcceleratorRawPa; detector_pa = ConvertTo-ArtifactRunPath $frozenDetectorPa
    three_instance_seed = ConvertTo-ArtifactRunPath $seed; iob_builder = ConvertTo-ArtifactRunPath $builder; iob_inspector = ConvertTo-ArtifactRunPath $inspector
    geometry_review_manifest_writer = ConvertTo-ArtifactRunPath $geometryManifestWriter
  }
  Write-RunJson -Path $runConfig -Value $runConfigDocument

  $failureStage = 'materialize_prototype'
  Invoke-MrtofPython -Arguments @('-m', 'projects.parallel_mirror_dual_stripe_mr_tof.analysis.materialize_simion_prototype',
    '--contract', $frozenContract, '--mirror-receipt', $frozenMirrorReceipt, '--output-directory', $solverDir)
  $resolvedContract = Join-Path $solverDir 'simion_prototype_contract.json'
  $program = Join-Path $solverDir 'mrtof_candidate.lua'
  $fly2 = Join-Path $solverDir 'mrtof_candidate_center.fly2'
  foreach ($required in @($resolvedContract, $program, $fly2, (Join-Path $solverDir 'prototype_input_manifest.json'))) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Materializer omitted required run-local input: $required" }
  }
  $runConfigDocument = Get-Content -LiteralPath $runConfig -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
  $runConfigDocument.inputs.prototype_input_manifest = ConvertTo-ArtifactRunPath (Join-Path $solverDir 'prototype_input_manifest.json')
  $runConfigDocument.inputs.resolved_prototype_contract = ConvertTo-ArtifactRunPath $resolvedContract
  $runConfigDocument.inputs.center_fly2 = ConvertTo-ArtifactRunPath $fly2
  Write-RunJson -Path $runConfig -Value $runConfigDocument

  $failureStage = 'derive_iob_pose'
  $posePath = Join-Path $resultDir 'resolved_iob_pose.json'
  $poseProgram = "import json,sys; from pathlib import Path; from projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry import resolve_split_iob_origins; p=Path(sys.argv[1]); c=json.loads(p.read_text(encoding='utf-8')); o=resolve_split_iob_origins(p); json.dump({'origins_mm':o,'mesh_mm_per_gu':c['simion']['component_mesh_mm_per_gu']},open(sys.argv[2],'w',encoding='utf-8'),indent=2)"
  Invoke-MrtofPython -Arguments @('-c', $poseProgram, $resolvedContract, $posePath)
  $pose = Get-Content -LiteralPath $posePath -Raw -Encoding UTF8 | ConvertFrom-Json
  foreach ($role in @('analyzer', 'accelerator', 'detector')) {
    if ($null -eq $pose.origins_mm.$role -or $null -eq $pose.mesh_mm_per_gu.$role) { throw "Resolved IOB pose omits $role" }
  }
  $origins = @('analyzer', 'accelerator', 'detector') | ForEach-Object { @($pose.origins_mm.$_) } | ForEach-Object { $_ }
  $mesh = @('analyzer', 'accelerator', 'detector') | ForEach-Object { @($pose.mesh_mm_per_gu.$_) } | ForEach-Object { $_ }
  $iob = Join-Path $solverDir 'mrtof_three_component_candidate.iob'
  $structureReport = Join-Path $resultDir 'iob_structure_report.txt'

  $failureStage = 'simion_iob_assembly'
  $hostExecutionLease = Enter-HostExecutionLease -Role SIMION -RunId $RunId
  Invoke-MrtofSimionStep -Stage 'build_three_component_iob' -Arguments (@('--nogui', '--noprompt', 'lua', $builder, '--',
    $seed, $frozenAnalyzerPa, $frozenAcceleratorPa, $frozenDetectorPa, $iob, $program, $fly2) + $origins)
  $failureStage = 'simion_iob_inspection'
  Invoke-MrtofSimionStep -Stage 'inspect_three_component_iob' -Arguments (@('--nogui', '--noprompt', 'lua', $inspector, '--',
    $iob, $structureReport) + $origins + $mesh)
  if (-not (Select-String -LiteralPath $structureReport -SimpleMatch 'STATUS=PASS' -Quiet)) { throw 'IOB inspector did not emit STATUS=PASS.' }

  $failureStage = 'write_geometry_review_receipt'
  # The receipt is deliberately colocated with the IOB and its Lua/PA family:
  # record_artifact uses local filenames, so a results/ copy would be unable to
  # verify the exact Workbench companions when a later flight receipt is bound.
  $geometryReviewManifest = Join-Path $solverDir 'three_component_geometry_review.json'
  Invoke-MrtofPython -Arguments @($geometryManifestWriter,
    '--contract', $frozenContract, '--run', $solverDir, '--iob', $iob,
    '--structure-report', $structureReport, '--output', $geometryReviewManifest)

  $failureStage = 'publish_geometry_review'
  $summaryObject = [ordered]@{
    schema_version = 1; role = 'mrtof_three_component_candidate_iob_assembly'; status = 'success'
    qualification = 'prototype_geometry_review_only'; particle_fly_executed = $false
    reason = 'Assembled and reloaded a run-local three-component IOB; no particle flight was started.'
  }
  Write-RunJson -Path $summary -Value $summaryObject
  $retention = Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  $iobCompanions = @(
    $iob,
    ($iob -replace '\.iob$', '.lua'),
    ($iob -replace '\.iob$', '.fly2'),
    ($iob -replace '\.iob$', '.operating_point.lua'),
    ($iob -replace '\.iob$', '.voltage_map.lua'),
    $geometryReviewManifest
  )
  foreach ($companion in $iobCompanions) {
    if (-not (Test-Path -LiteralPath $companion -PathType Leaf)) { throw "IOB build omitted companion: $companion" }
  }
  $failureStage = 'capacity_terminal'
  $terminalCapacityMaximumNewArtifactBytes = [int64](
    (Get-ChildItem -LiteralPath $package.artifact_run_dir -File -Recurse | Measure-Object -Property Length -Sum).Sum
  )
  $artifactCapacityTerminal = Invoke-ArtifactCapacityGate -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot $artifactCapacityRoot -ProtectedPaths @($package.artifact_run_dir) `
    -KnownMeasuredBytes ([int64]$artifactCapacityStartup.measured_after_bytes) `
    -MaximumNewArtifactBytes $terminalCapacityMaximumNewArtifactBytes
  $artifactCapacityTerminalPath = Join-Path $resultDir 'artifact_capacity_gate_terminal.json'
  Write-RunJson -Path $artifactCapacityTerminalPath -Depth 14 -Value $artifactCapacityTerminal
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('SIMION 2020', 'Python 3.11') -Outputs (@($summary, $posePath, $structureReport, $retention, $artifactCapacityStartupPath, $artifactCapacityTerminalPath) + $iobCompanions)
  $terminalized = $true
  $hostExecutionOutcome = 'success'
  Write-Host "MRTOF_THREE_COMPONENT_IOB=PASS RUN_ID=$RunId IOB=$iob"
} catch {
  $reason = $_.Exception.Message
  if (-not $terminalized) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_three_component_candidate_iob_assembly' -Reason $reason `
      -Software @('SIMION 2020', 'Python 3.11') -Status failed -FailureStage $failureStage `
      -PreserveRawOutputs
    $terminalized = $true
  }
  throw
} finally {
  if (-not $terminalized -and (Test-Path -LiteralPath $runConfig -PathType Leaf)) {
    # PowerShell reaches finally after an external stop that bypasses the
    # ordinary catch path; preserve the incomplete package as interrupted.
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
      -SummaryRole 'mrtof_three_component_candidate_iob_assembly' `
      -Reason 'Runner stopped before a terminal IOB assembly record was published.' `
      -Software @('SIMION 2020', 'Python 3.11') -Status interrupted -FailureStage $failureStage `
      -PreserveRawOutputs
    $hostExecutionOutcome = 'interrupted'
  }
  if ($null -ne $hostExecutionLease) {
    Exit-HostExecutionLease -Lease $hostExecutionLease -Outcome $hostExecutionOutcome -RunId $RunId
  }
  Remove-RunPackageExecutionAlias -Package $package
}
