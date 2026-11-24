param(
  [string]$RunId = "$(Get-Date -Format 'yyyyMMdd_HHmmss')__test__comsol__oatof-candidate-functional__n100",
  [string]$PythonExe = '',
  [string]$IonPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
. (Join-Path $repoRoot 'src/msplatform/execution/resources/workspace_paths.ps1')
$artifactRoot = Resolve-RunArtifactRoot -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -OwnerKind component -OwnerId single_reflection_oa_tof_mass_analyzer -Python $python
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } elseif ($env:SIMULATION_PYTHON_EXE) { [IO.Path]::GetFullPath($env:SIMULATION_PYTHON_EXE) } else { throw 'Explicit PythonExe or SIMULATION_PYTHON_EXE is required' }
$launcher = Join-Path $repoRoot 'src\msplatform\backends\comsol\launcher\run_comsol_r2025b.ps1'
$task = Join-Path $repoRoot 'src\msplatform\backends\comsol\matlab\run_candidate_contract_build.m'
$contract = Join-Path $projectRoot 'config\resolved_geometry.json'
$ion = if ($IonPath) { [IO.Path]::GetFullPath($IonPath) } else { Join-Path $artifactRoot 'formal\simion\oatof_comsol_524amu_gaussian_N100.ion' }
. (Join-Path $repoRoot 'src/msplatform/execution/resources/run_artifact_support.ps1')
$executionResources = Join-Path $repoRoot 'src/msplatform/execution/resources'
$hostState = if ($env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH) { $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH } else { Resolve-PlatformArtifactPath -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RelativePath @('host_resources.sqlite3') -Python $python }
$hostContext = @{workspace=$workspaceRoot;python_executable=$python;host_state_path=$hostState;policy_path=(Join-Path $executionResources 'host_resource_policy.json')}
. (Join-Path $executionResources 'host_execution_lease.ps1') -HostContext $hostContext

$software = @('COMSOL 6.4', 'MATLAB R2025b', 'Python 3.11')
$package = New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project 'single_reflection_oa_tof_mass_analyzer' -Mode 'comsol_n100_candidate_functional' `
  -Software $software -RetentionContractEnabled -RetentionClass solver_review `
  -RetentionReason 'Retain the N100 native model for saved-solution cold extraction and independent review.' `
  -CapacityLedgerLifecycleEnabled -AdditionalDirectories @('comsol') -UseShortExecutionPath
$model = Join-Path $package.artifact_run_dir 'comsol\single_reflection_oa_tof_mass_analyzer__candidate_n100.mph'
$report = Join-Path $package.log_dir 'comsol_candidate_report.txt'

$frozen = [ordered]@{}
foreach ($item in @(
  @{Name='resolved_geometry'; Path=$contract; File='resolved_geometry.json'},
  @{Name='particle_table'; Path=$ion; File='particles_n100.ion'},
  @{Name='stable_entry'; Path=(Join-Path $repoRoot 'src\msplatform\backends\comsol\matlab\run_oatof_model.m'); File='src/msplatform/backends/comsol/matlab/run_oatof_model.m'},
  @{Name='model_core'; Path=(Join-Path $projectRoot 'comsol\oatof_build_model_core.m'); File='oatof_build_model_core.m'},
  @{Name='detector_event_export'; Path=(Join-Path $projectRoot 'comsol\oatof_export_detector_events.m'); File='oatof_export_detector_events.m'},
  @{Name='detector_extractor'; Path=(Join-Path $repoRoot 'src\msplatform\backends\comsol\matlab\oatof_extract_detector_arrivals.m'); File='oatof_extract_detector_arrivals.m'},
  @{Name='python_event_analyzer'; Path=(Join-Path $projectRoot 'analysis\analyze_comsol_detector_events.py'); File='analyze_comsol_detector_events.py'},
  @{Name='task'; Path=$task; File='src/msplatform/backends/comsol/matlab/run_candidate_contract_build.m'}
)) {
  if (-not (Test-Path -LiteralPath $item.Path -PathType Leaf)) {
    throw "Required input is missing: $($item.Path)"
  }
  $destination = Join-Path $package.input_dir $item.File
  $destinationParent = Split-Path -Parent $destination
  if (-not (Test-Path -LiteralPath $destinationParent -PathType Container)) {
    New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
  }
  Copy-Item -LiteralPath $item.Path -Destination $destination
  $frozen[$item.Name] = $destination
}

$config = Get-Content -LiteralPath $package.run_config -Raw -Encoding UTF8 |
  ConvertFrom-Json -AsHashtable
$config.inputs = $frozen
$config.inputs.candidate_particle_table = $frozen.particle_table
$config.run_instance = [ordered]@{
  particle_source_seed = 20260720
  particle_count = 100
}
$config.parameters = [ordered]@{
  particle_count = 100
  lifecycle_stage = 'inputs_frozen'
  claim_limit = 'Functional N=100 candidate validation; no convergence or Formal claim.'
}
Write-RunJson -Value $config -Path $package.run_config
Write-RunManifest -Python $package.python -RepoRoot $repoRoot `
  -RunConfig $package.run_config -Status checkpoint -Software $software

$names = @(
  'OATOF_CANDIDATE_CONTRACT_PATH',
  'OATOF_CANDIDATE_MODEL_PATH',
  'OATOF_CANDIDATE_RUN_CONFIG_PATH',
  'OATOF_CANDIDATE_ARTIFACT_ROOT',
  'OATOF_CANDIDATE_ION_PATH',
  'OATOF_RESULTS_DIR',
  'OATOF_RUNTIME_DIR'
)
$snapshot = Save-RunEnvironment -Names $names
try {
  $env:OATOF_CANDIDATE_CONTRACT_PATH = $frozen.resolved_geometry
  $env:OATOF_CANDIDATE_MODEL_PATH = $model
  $env:OATOF_CANDIDATE_RUN_CONFIG_PATH = $package.run_config
  $env:OATOF_CANDIDATE_ARTIFACT_ROOT = [string]$config.capacity_ledger_lifecycle.artifact_root
  $env:OATOF_CANDIDATE_ION_PATH = $frozen.particle_table
  $env:OATOF_RESULTS_DIR = $package.result_dir
  $env:OATOF_RUNTIME_DIR = Join-Path $package.run_dir 'comsol'
  . (Join-Path (Split-Path -Parent ($launcher)) 'resolve_comsol_64.ps1')
  $comsolLauncherParameters=Get-ComsolLauncherParameters -HostContext $script:HostResourceExecutionContext -WorkingDirectory $script:HostResourceExecutionContext.workspace
  & $launcher @comsolLauncherParameters -TaskScript $task -ReportPath $report -StartupAttempts 1
  if ($LASTEXITCODE -ne 0) { throw 'COMSOL candidate task failed.' }
  $text = Get-Content -LiteralPath $report -Raw -Encoding UTF8
  if ($text -notmatch 'STATUS=PASS' -or
      $text -notmatch 'PARTICLES=100' -or
      $text -notmatch 'DETECTED=100' -or
      $text -notmatch 'DETECTOR_HIT_CLASSIFICATIONS=100') {
    throw 'COMSOL candidate report did not satisfy the N=100 detector contract.'
  }
  $analysisRequest = [regex]::Match($text, 'PYTHON_ANALYSIS_REQUEST=(.+)').Groups[1].Value.Trim()
  if (-not $analysisRequest -or -not (Test-Path -LiteralPath $analysisRequest -PathType Leaf)) {
    throw 'COMSOL candidate did not emit a Python analysis request.'
  }
  & $package.python -m msplatform.workflows.oa_candidate.analyze_comsol_detector_events --request $analysisRequest
  if ($LASTEXITCODE -ne 0) { throw 'Python COMSOL detector-event analysis failed.' }
  $analysisRequestDocument = Get-Content -LiteralPath $analysisRequest -Raw | ConvertFrom-Json
  $analysisDir = [IO.Path]::GetFullPath([string]$analysisRequestDocument.analysis_output_dir)
  $analysisReceipt = Join-Path $analysisDir 'analysis_receipt.json'
  if (-not (Test-Path -LiteralPath $analysisReceipt -PathType Leaf)) {
    throw 'Python COMSOL detector-event analysis receipt is missing.'
  }
  Write-RunJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1
    role = 'oa_tof_comsol_n100_candidate_functional_summary'
    status = 'success'
    particles = 100
    detector_hits = 100
    detector_extraction = 'one_detector_hit_classification_per_particle'
    parameterized_ring_counts = 'contract_verified'
    segmented_time_window = 'six_required_tokens_verified'
    raw_detector_events = [regex]::Match($text, 'RAW_DETECTOR_EVENTS=(.+)').Groups[1].Value.Trim()
    python_analysis_receipt = $analysisReceipt
    aggregate_metrics_owner = 'python_reference_analysis'
    formal_modified = $false
  })
  $outputs = @($model, $report, $package.summary)
  $outputs += @(Get-ChildItem -LiteralPath $package.result_dir -File |
    ForEach-Object { $_.FullName })
  $outputs += @(Get-ChildItem -LiteralPath $analysisDir -File |
    ForEach-Object { $_.FullName })
  $retentionActions=Apply-RunArtifactRetention -Python $package.python -RepoRoot $repoRoot `
    -RunConfig $package.run_config
  Write-VerifiedRunManifest -Python $package.python -RepoRoot $repoRoot `
    -RunConfig $package.run_config -Status success -Software $software `
    -Outputs ($outputs+@($retentionActions)) -DeferCapacityFinalization
  Invoke-RunToolRootContext -RepoRoot $repoRoot -Operation {
    & $package.python -m msplatform.execution.run_capacity_lifecycle --action seal-stopped-payload `
      --artifact-root ([string]$config.capacity_ledger_lifecycle.artifact_root) `
      --run-config $package.run_config --owner 'single_reflection_oa_tof_mass_analyzer' `
      --confirm-writing-stopped --retention-reason 'Retain the N100 native model for saved-solution cold extraction and independent review.'
    if ($LASTEXITCODE -ne 0) { throw 'N100 stopped-payload sealing failed.' }
  }
  Write-Output "OATOF_COMSOL_N100=PASS RUN_ID=$RunId RUN_DIR=$($package.run_dir)"
}
catch {
  $reason = $_.Exception.Message
  Complete-FailedRun -Python $package.python -RepoRoot $repoRoot `
    -RunConfig $package.run_config -Summary $package.summary `
    -SummaryRole 'oa_tof_comsol_n100_candidate_functional_summary' `
    -Reason $reason -Software $software
  throw
}
finally {
  Restore-RunEnvironment -Names $names -Snapshot $snapshot
  try { Remove-RunPackageExecutionAlias -Package $package } catch {
    Write-Warning "Could not remove short execution alias after COMSOL test run: $($_.Exception.Message)"
  }
}
