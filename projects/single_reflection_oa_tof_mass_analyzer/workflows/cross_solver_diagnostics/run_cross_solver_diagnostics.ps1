[CmdletBinding()]
param(
  [string]$RunId = ((Get-Date -Format 'yyyyMMdd_HHmmss') + '__analysis__cross__formal-diagnostics'),
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\single_reflection_oa_tof_mass_analyzer'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$formalValidationLive = Join-Path $projectRoot 'config\formal_validation.json'
$resolvedGeometryLive = Join-Path $projectRoot 'config\resolved_geometry.json'
$comsolAdapterRoot = Join-Path $PSScriptRoot 'comsol'
$simionAdapterRoot = Join-Path $PSScriptRoot 'simion'
$comsolAxisTask = Join-Path $comsolAdapterRoot 'export_axis_field_profiles.m'
$comsolTrajectoryTask = Join-Path $comsolAdapterRoot 'export_selected_particle_trajectories.m'
$comsolVectorTask = Join-Path $comsolAdapterRoot 'export_accelerator_vector_field_samples.m'
$simionAxisTask = Join-Path $simionAdapterRoot 'export_axis_field_profiles.lua'
$simionVectorTask = Join-Path $simionAdapterRoot 'export_accelerator_vector_field_samples.lua'
$axisAnalysis = Join-Path $projectRoot 'analysis\compare_field_profiles.py'
$trajectoryAnalysis = Join-Path $projectRoot 'analysis\compare_particle_trajectories.py'
$vectorAnalysis = Join-Path $projectRoot 'analysis\compare_vector_field_samples.py'

. (Join-Path $projectRoot 'oatof_lifecycle_preflight.ps1')
Assert-OaTofFormalAssetsReadable -ProjectRoot $projectRoot
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }

$runDir = Join-Path $artifactRoot "runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Run already exists: $runDir" }
$inputDir = Join-Path $runDir 'inputs'
$resultDir = Join-Path $runDir 'results'
$logDir = Join-Path $runDir 'logs'
New-Item -ItemType Directory -Path $runDir,$inputDir,$resultDir,$logDir | Out-Null
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
Initialize-RunRecord -RunDir $runDir -RunId $RunId -Project 'single_reflection_oa_tof_mass_analyzer' `
  -Mode 'formal_cross_solver_diagnostics' -ProjectRoot $projectRoot `
  -RepoRoot $repoRoot -Python $python -ProvisionalSummaryRole 'oa_tof_provisional_run_summary' `
  -TerminalSummaryRole 'oa_tof_terminal_run_summary'
$runRecordComplete = $false
trap {
  if (-not $runRecordComplete) {
    Write-TerminalRunRecord -RunDir $runDir -Status failed -Reason $_.Exception.Message `
      -RepoRoot $repoRoot -Python $python -SummaryRole 'oa_tof_terminal_run_summary'
  }
  exit 1
}

$formalValidationPath = Join-Path $inputDir 'formal_validation.json'
$resolvedGeometryPath = Join-Path $inputDir 'resolved_geometry.json'
Copy-Item -LiteralPath $formalValidationLive -Destination $formalValidationPath
Copy-Item -LiteralPath $resolvedGeometryLive -Destination $resolvedGeometryPath
$formalValidation = Get-Content -LiteralPath $formalValidationPath -Raw -Encoding UTF8 | ConvertFrom-Json
$formalMph = Join-Path $artifactRoot $formalValidation.comsol.formal_mph_artifact_relative_path
$formalIob = Join-Path $artifactRoot $formalValidation.simion.iob_artifact_relative_path
$formalComsolCsv = Join-Path $artifactRoot $formalValidation.comsol.particle_csv_artifact_relative_path
$formalSimionCsv = Join-Path $artifactRoot $formalValidation.simion.particle_csv_artifact_relative_path
$sourceRunRoot = Join-Path $artifactRoot ("runs\{0}" -f $formalValidation.run_id)
$sourceManifest = Join-Path $sourceRunRoot 'run_manifest.json'
$sourceTraceLog = Join-Path $sourceRunRoot 'logs\simion_stdout.log'
$requiredInputs = @(
  $python,$SimionExe,$formalMph,$formalIob,$formalComsolCsv,$formalSimionCsv,
  $sourceManifest,$sourceTraceLog,$comsolAxisTask,$comsolTrajectoryTask,$comsolVectorTask,
  $simionAxisTask,$simionVectorTask,$axisAnalysis,$trajectoryAnalysis,$vectorAnalysis
)
foreach ($path in $requiredInputs) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required input is absent: $path" }
}
foreach ($item in @(
    @($formalMph,$formalValidation.comsol.formal_mph_sha256),
    @($formalIob,$formalValidation.simion.iob_sha256),
    @($formalComsolCsv,$formalValidation.comsol.particle_csv_sha256),
    @($formalSimionCsv,$formalValidation.simion.particle_csv_sha256)
  )) {
  if ((Get-FileHash -LiteralPath $item[0] -Algorithm SHA256).Hash -cne [string]$item[1]) {
    throw "Formal input identity differs from formal_validation.json: $($item[0])"
  }
}
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $sourceManifest `
  --require-status success --require-project single_reflection_oa_tof_mass_analyzer
if ($LASTEXITCODE -ne 0) { throw 'Formal source run manifest verification failed.' }
if (-not (Select-String -LiteralPath $sourceTraceLog -Pattern '^TRACE: \d+,' -Quiet)) {
  throw 'Formal SIMION source log does not contain sparse trajectory TRACE rows.'
}

$pairingDir = Join-Path $resultDir 'particle_pairing'
& $python -m projects.single_reflection_oa_tof_mass_analyzer.analysis.reference_analysis compare `
  $formalComsolCsv $formalSimionCsv --mass 524 --output $pairingDir `
  --left-label COMSOL --right-label SIMION --require-paired-particle-ids
if ($LASTEXITCODE -ne 0) { throw 'Formal particle pairing failed.' }
$pairedArrivals = Join-Path $pairingDir 'source_mapping_particles.csv'
if (-not (Test-Path -LiteralPath $pairedArrivals -PathType Leaf)) {
  throw 'Formal particle pairing did not emit source_mapping_particles.csv.'
}

$comsolAxisCsv = Join-Path $resultDir 'comsol_axis_field.csv'
$comsolTrajectoryCsv = Join-Path $resultDir 'comsol_selected_trajectories.csv'
$comsolVectorCsv = Join-Path $resultDir 'comsol_accelerator_vector_field.csv'
$simionAxisCsv = Join-Path $resultDir 'simion_axis_field.csv'
$simionVectorCsv = Join-Path $resultDir 'simion_accelerator_vector_field.csv'
$comsolAxisReport = Join-Path $logDir 'comsol_axis_field.txt'
$comsolTrajectoryReport = Join-Path $logDir 'comsol_selected_trajectories.txt'
$comsolVectorReport = Join-Path $logDir 'comsol_accelerator_vector_field.txt'
$simionAxisReport = Join-Path $logDir 'simion_axis_field.txt'
$simionVectorReport = Join-Path $logDir 'simion_accelerator_vector_field.txt'

$oldEnvironment = @{}
$environment = @{
  OATOF_PROJECT_ROOT = $projectRoot
  OATOF_COMSOL_MODEL_PATH = $formalMph
  OATOF_RESOLVED_GEOMETRY_JSON = $resolvedGeometryPath
  OATOF_TRAJECTORY_PARTICLE_IDS = '18,52,97'
  OATOF_COMSOL_FIELD_CSV = $comsolAxisCsv
  OATOF_COMSOL_TRAJECTORY_CSV = $comsolTrajectoryCsv
}
try {
  foreach ($entry in $environment.GetEnumerator()) {
    $oldEnvironment[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key,'Process')
    [Environment]::SetEnvironmentVariable($entry.Key,$entry.Value,'Process')
  }
  foreach ($task in @(
      @($comsolAxisTask,$comsolAxisReport),
      @($comsolTrajectoryTask,$comsolTrajectoryReport)
    )) {
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
      -TaskScript $task[0] -ReportPath $task[1]
    if ($LASTEXITCODE -ne 0) { throw "COMSOL diagnostic export failed: $($task[0])" }
  }
} finally {
  foreach ($entry in $environment.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key,$oldEnvironment[$entry.Key],'Process')
  }
}

$contract = Get-Content -LiteralPath $resolvedGeometryPath -Raw -Encoding UTF8 | ConvertFrom-Json
$geometry = $contract.geometry_mm
$source = $contract.particle_source
$simionEnvironment = @{
  OATOF_FORMAL_IOB_PATH = $formalIob
  OATOF_SIMION_FIELD_CSV = $simionAxisCsv
  OATOF_SIMION_FIELD_REPORT = $simionAxisReport
  OATOF_ACCELERATOR_AXIS_X_MM = [string]$contract.coordinate_convention.accelerator_axis_x
  OATOF_REFLECTRON_AXIS_X_MM = [string]$contract.coordinate_convention.reflectron_axis[0]
  OATOF_SOURCE_Z_MIN_MM = [string]($source.center_z_mm-$source.size_z_mm/2)
  OATOF_SOURCE_Z_MAX_MM = [string]($source.center_z_mm+$source.size_z_mm/2)
  OATOF_ACCELERATOR_SAMPLE_Z_MIN_MM = [string]($geometry.accelerator_repeller_z+0.2)
  OATOF_ACCELERATOR_SAMPLE_Z_MAX_MM = [string]($geometry.accelerator_grid2_z-0.2)
  OATOF_REFLECTRON_SAMPLE_Z_MIN_MM = [string]($geometry.L_flight+0.25)
  OATOF_REFLECTRON_SAMPLE_Z_MAX_MM = [string]($geometry.L_flight+$geometry.L_reflectron-0.25)
  OATOF_ACCELERATOR_SAMPLE_CSV = $comsolTrajectoryCsv
  OATOF_SIMION_VECTOR_FIELD_CSV = $simionVectorCsv
  OATOF_SIMION_VECTOR_FIELD_REPORT = $simionVectorReport
}
$oldSimionEnvironment = @{}
$runtimeTaskId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__simion__formal-diagnostics-runtime'
$runtimeReceipt = Join-Path $inputDir 'formal_simion_runtime_receipt.json'
$runtimeRoot = New-OaTofFormalSimionRuntime -ProjectRoot $projectRoot `
  -ArtifactRoot $artifactRoot -PythonExe $python `
  -Destination (Join-Path $artifactRoot "scratch\$runtimeTaskId") `
  -Receipt $runtimeReceipt
$simionEnvironment.OATOF_FORMAL_IOB_PATH = Join-Path $runtimeRoot 'oatof_ideal_grounded.iob'
try {
  foreach ($entry in $simionEnvironment.GetEnumerator()) {
    $oldSimionEnvironment[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key,'Process')
    [Environment]::SetEnvironmentVariable($entry.Key,$entry.Value,'Process')
  }
  foreach ($task in @($simionAxisTask,$simionVectorTask)) {
    & $SimionExe --nogui lua $task
    if ($LASTEXITCODE -ne 0) { throw "SIMION diagnostic export failed: $task" }
  }
} finally {
  foreach ($entry in $simionEnvironment.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key,$oldSimionEnvironment[$entry.Key],'Process')
  }
  Remove-OaTofFormalSimionRuntime -ArtifactRoot $artifactRoot -RuntimeRoot $runtimeRoot
}

$comsolVectorEnvironment = @{
  OATOF_PROJECT_ROOT = $projectRoot
  OATOF_COMSOL_MODEL_PATH = $formalMph
  OATOF_ACCELERATOR_SAMPLE_CSV = $simionVectorCsv
  OATOF_COMSOL_VECTOR_FIELD_CSV = $comsolVectorCsv
}
$oldComsolVectorEnvironment = @{}
try {
  foreach ($entry in $comsolVectorEnvironment.GetEnumerator()) {
    $oldComsolVectorEnvironment[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key,'Process')
    [Environment]::SetEnvironmentVariable($entry.Key,$entry.Value,'Process')
  }
  & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
    -TaskScript $comsolVectorTask -ReportPath $comsolVectorReport
  if ($LASTEXITCODE -ne 0) { throw 'COMSOL vector-field export failed.' }
} finally {
  foreach ($entry in $comsolVectorEnvironment.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key,$oldComsolVectorEnvironment[$entry.Key],'Process')
  }
}

$axisResultDir = Join-Path $resultDir 'axis_field'
$vectorResultDir = Join-Path $resultDir 'accelerator_vector_field'
$trajectoryResultDir = Join-Path $resultDir 'selected_trajectories'
& $python -m projects.single_reflection_oa_tof_mass_analyzer.analysis.compare_field_profiles `
  $comsolAxisCsv $simionAxisCsv --output $axisResultDir `
  --contract $resolvedGeometryPath
if ($LASTEXITCODE -ne 0) { throw 'Axis-field comparison failed.' }
& $python -m projects.single_reflection_oa_tof_mass_analyzer.analysis.compare_vector_field_samples `
  $comsolVectorCsv $simionVectorCsv --output $vectorResultDir
if ($LASTEXITCODE -ne 0) { throw 'Vector-field comparison failed.' }
& $python -m projects.single_reflection_oa_tof_mass_analyzer.analysis.compare_particle_trajectories `
  $comsolTrajectoryCsv $sourceTraceLog --arrivals $pairedArrivals `
  --particle-ids '18,52,97' --output $trajectoryResultDir --contract $resolvedGeometryPath
if ($LASTEXITCODE -ne 0) { throw 'Selected-particle trajectory comparison failed.' }

$summary = Join-Path $runDir 'summary.json'
[ordered]@{
  schema_version=1
  role='oatof_formal_cross_solver_diagnostics_summary'
  status='success'
  source_formal_run_id=$formalValidation.run_id
  particle_ids=@(18,52,97)
  solver_rerun=$false
  formal_modified=$false
  results=[ordered]@{
    axis_field='results/axis_field/axis_field_metrics.json'
    accelerator_vector_field='results/accelerator_vector_field/accelerator_vector_field_metrics.json'
    selected_trajectories='results/selected_trajectories/trajectory_metrics.json'
  }
  claim_limit='Diagnostic comparison of current frozen Formal assets; does not change Formal qualification.'
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summary -Encoding UTF8

$runConfig = Join-Path $runDir 'run_config.json'
[ordered]@{
  schema_version=1;run_id=$RunId;project='single_reflection_oa_tof_mass_analyzer'
  mode='formal_cross_solver_diagnostics';project_root=$projectRoot
  inputs=[ordered]@{
    formal_validation=$formalValidationPath;resolved_geometry=$resolvedGeometryPath
    formal_comsol_model=$formalMph;formal_simion_iob=$formalIob
    formal_simion_runtime_receipt=$runtimeReceipt
    formal_comsol_particles=$formalComsolCsv;formal_simion_particles=$formalSimionCsv
    formal_source_manifest=$sourceManifest;formal_simion_trace_log=$sourceTraceLog
    comsol_axis_adapter=$comsolAxisTask;comsol_trajectory_adapter=$comsolTrajectoryTask
    comsol_vector_adapter=$comsolVectorTask;simion_axis_adapter=$simionAxisTask
    simion_vector_adapter=$simionVectorTask
    axis_analysis=$axisAnalysis;trajectory_analysis=$trajectoryAnalysis;vector_analysis=$vectorAnalysis
  }
  parameters=[ordered]@{particle_ids=@(18,52,97);solver_rerun=$false}
  formal_gate_passed=$false;promotion_authorized=$false
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $runConfig -Encoding UTF8

$outputs = @(
  $comsolAxisCsv,$comsolTrajectoryCsv,$comsolVectorCsv,$simionAxisCsv,$simionVectorCsv,
  $comsolAxisReport,$comsolTrajectoryReport,$comsolVectorReport,$simionAxisReport,$simionVectorReport,
  $pairedArrivals,(Join-Path $axisResultDir 'axis_field_metrics.json'),
  (Join-Path $axisResultDir 'axis_field_comparison.png'),
  (Join-Path $vectorResultDir 'accelerator_vector_field_metrics.json'),
  (Join-Path $vectorResultDir 'accelerator_vector_field_comparison.png'),
  (Join-Path $trajectoryResultDir 'trajectory_metrics.json'),
  (Join-Path $trajectoryResultDir 'representative_trajectory_comparison.png'),$summary
)
$manifestArgs = @(
  (Join-Path $repoRoot 'common\contracts\write_run_manifest.py'),'--run-config',$runConfig,
  '--manifest',(Join-Path $runDir 'run_manifest.json'),'--status','success',
  '--software','COMSOL R2025b saved solution','--software','SIMION 2020','--software','Python 3.11'
)
foreach ($output in $outputs) { $manifestArgs += @('--output',$output) }
& $python @manifestArgs
if ($LASTEXITCODE -ne 0) { throw 'Cross-solver diagnostics manifest creation failed.' }
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
  (Join-Path $runDir 'run_manifest.json') --require-status success `
  --require-project single_reflection_oa_tof_mass_analyzer --require-mode formal_cross_solver_diagnostics
if ($LASTEXITCODE -ne 0) { throw 'Cross-solver diagnostics manifest verification failed.' }
$runRecordComplete = $true
Write-Output "CROSS_SOLVER_DIAGNOSTICS=PASS RUN_ID=$RunId"
