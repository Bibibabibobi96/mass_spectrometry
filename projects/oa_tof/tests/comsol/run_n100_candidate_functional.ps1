param(
  [string]$RunId = "$(Get-Date -Format 'yyyyMMdd_HHmmss')__test__comsol__oatof-candidate-functional__n100",
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\oa_tof'
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
$launcher = Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1'
$task = Join-Path $PSScriptRoot 'run_candidate_contract_build.m'
$contract = Join-Path $projectRoot 'config\resolved_geometry.json'
$ion = Join-Path $artifactRoot 'formal\simion\oatof_comsol_524amu_gaussian_N100.ion'
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')

$software = @('COMSOL 6.4', 'MATLAB R2025b', 'Python 3.11')
$package = New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project 'oa_tof' -Mode 'comsol_n100_candidate_functional' `
  -Software $software -AdditionalDirectories @('comsol')
$model = Join-Path $package.run_dir 'comsol\oa_tof_candidate_n100.mph'
$report = Join-Path $package.log_dir 'comsol_candidate_report.txt'

$frozen = [ordered]@{}
foreach ($item in @(
  @{Name='resolved_geometry'; Path=$contract; File='resolved_geometry.json'},
  @{Name='particle_table'; Path=$ion; File='particles_n100.ion'},
  @{Name='stable_entry'; Path=(Join-Path $projectRoot 'comsol\run_oatof_model.m'); File='run_oatof_model.m'},
  @{Name='model_core'; Path=(Join-Path $projectRoot 'comsol\oatof_build_model_core.m'); File='oatof_build_model_core.m'},
  @{Name='detector_extractor'; Path=(Join-Path $projectRoot 'comsol\oatof_extract_detector_arrivals.m'); File='oatof_extract_detector_arrivals.m'},
  @{Name='task'; Path=$task; File='run_candidate_contract_build.m'}
)) {
  if (-not (Test-Path -LiteralPath $item.Path -PathType Leaf)) {
    throw "Required input is missing: $($item.Path)"
  }
  $destination = Join-Path $package.input_dir $item.File
  Copy-Item -LiteralPath $item.Path -Destination $destination
  $frozen[$item.Name] = $destination
}

$config = Get-Content -LiteralPath $package.run_config -Raw -Encoding UTF8 |
  ConvertFrom-Json -AsHashtable
$config.inputs = $frozen
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
  'OATOF_CANDIDATE_ION_PATH',
  'OATOF_RESULTS_DIR',
  'OATOF_RUNTIME_DIR'
)
$snapshot = Save-RunEnvironment -Names $names
try {
  $env:OATOF_CANDIDATE_CONTRACT_PATH = $frozen.resolved_geometry
  $env:OATOF_CANDIDATE_MODEL_PATH = $model
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
  $meanTof = [double]([regex]::Match($text, 'MEAN_TOF_US=([0-9.eE+-]+)').Groups[1].Value)
  Write-RunJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1
    role = 'oa_tof_comsol_n100_candidate_functional_summary'
    status = 'success'
    particles = 100
    detector_hits = 100
    detector_extraction = 'one_detector_hit_classification_per_particle'
    parameterized_ring_counts = 'contract_verified'
    segmented_time_window = 'six_required_tokens_verified'
    mean_tof_us = $meanTof
    formal_modified = $false
  })
  $outputs = @($model, $report, $package.summary)
  $outputs += @(Get-ChildItem -LiteralPath $package.result_dir -File |
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
}
