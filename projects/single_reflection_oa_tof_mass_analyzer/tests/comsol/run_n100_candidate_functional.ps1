param(
  [string]$RunId = "$(Get-Date -Format 'yyyyMMdd_HHmmss')__test__comsol__oatof-candidate-functional__n100",
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\single_reflection_oa_tof_mass_analyzer'
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
$launcher = Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1'
$task = Join-Path $projectRoot 'workflows\design_candidate\run_candidate_contract_build.m'
$contract = Join-Path $projectRoot 'config\resolved_geometry.json'
$ion = Join-Path $artifactRoot 'formal\simion\oatof_comsol_524amu_gaussian_N100.ion'
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')

$software = @('COMSOL 6.4', 'MATLAB R2025b', 'Python 3.11')
$package = New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project 'single_reflection_oa_tof_mass_analyzer' -Mode 'comsol_n100_candidate_functional' `
  -Software $software -AdditionalDirectories @('comsol') -UseShortExecutionPath
$model = Join-Path $package.artifact_run_dir 'comsol\single_reflection_oa_tof_mass_analyzer__candidate_n100.mph'
$report = Join-Path $package.log_dir 'comsol_candidate_report.txt'

$frozen = [ordered]@{}
foreach ($item in @(
  @{Name='resolved_geometry'; Path=$contract; File='resolved_geometry.json'},
  @{Name='particle_table'; Path=$ion; File='particles_n100.ion'},
  @{Name='stable_entry'; Path=(Join-Path $projectRoot 'comsol\run_oatof_model.m'); File='run_oatof_model.m'},
  @{Name='model_core'; Path=(Join-Path $projectRoot 'comsol\oatof_build_model_core.m'); File='oatof_build_model_core.m'},
  @{Name='detector_event_export'; Path=(Join-Path $projectRoot 'comsol\oatof_export_detector_events.m'); File='oatof_export_detector_events.m'},
  @{Name='detector_extractor'; Path=(Join-Path $projectRoot 'comsol\oatof_extract_detector_arrivals.m'); File='oatof_extract_detector_arrivals.m'},
  @{Name='python_event_analyzer'; Path=(Join-Path $projectRoot 'analysis\analyze_comsol_detector_events.py'); File='analyze_comsol_detector_events.py'},
  @{Name='task'; Path=$task; File='workflows/design_candidate/run_candidate_contract_build.m'}
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
  -RunConfig $package.run_config -Status interrupted -Software $software

$names = @(
  'OATOF_CANDIDATE_CONTRACT_PATH',
  'OATOF_CANDIDATE_MODEL_PATH',
  'OATOF_CANDIDATE_RUN_CONFIG_PATH',
  'OATOF_CANDIDATE_ION_PATH',
  'OATOF_RESULTS_DIR',
  'OATOF_RUNTIME_DIR'
)
$snapshot = Save-RunEnvironment -Names $names
try {
  $env:OATOF_CANDIDATE_CONTRACT_PATH = $frozen.resolved_geometry
  $env:OATOF_CANDIDATE_MODEL_PATH = $model
  $env:OATOF_CANDIDATE_RUN_CONFIG_PATH = $package.run_config
  $env:OATOF_CANDIDATE_ION_PATH = $frozen.particle_table
  $env:OATOF_RESULTS_DIR = $package.result_dir
  $env:OATOF_RUNTIME_DIR = Join-Path $package.run_dir 'comsol'
  & $launcher -TaskScript $task -ReportPath $report -StartupAttempts 1
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
  & $package.python -m projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_comsol_detector_events --request $analysisRequest
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
  Write-RunManifest -Python $package.python -RepoRoot $repoRoot `
    -RunConfig $package.run_config -Status success -Software $software -Outputs $outputs
  & $package.python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
    (Join-Path $package.run_dir 'run_manifest.json') --require-status success
  if ($LASTEXITCODE -ne 0) { throw 'COMSOL candidate manifest verification failed.' }
  Write-Output "OATOF_COMSOL_N100=PASS RUN_ID=$RunId RUN_DIR=$($package.run_dir)"
}
catch {
  $reason = $_.Exception.Message
  Complete-FailedRun -Python $package.python -RepoRoot $repoRoot `
    -RunConfig $package.run_config -Summary $package.summary `
    -SummaryRole 'oa_tof_comsol_n100_candidate_functional_summary' `
    -Reason $reason -Software $software
  $failedOutputs = @($package.summary)
  if (Test-Path -LiteralPath $report -PathType Leaf) { $failedOutputs += $report }
  Write-RunManifest -Python $package.python -RepoRoot $repoRoot `
    -RunConfig $package.run_config -Status failed -Software $software `
    -Outputs $failedOutputs
  throw
}
finally {
  Restore-RunEnvironment -Names $names -Snapshot $snapshot
  try { Remove-RunPackageExecutionAlias -Package $package } catch {
    Write-Warning "Could not remove short execution alias after COMSOL test run: $($_.Exception.Message)"
  }
}
