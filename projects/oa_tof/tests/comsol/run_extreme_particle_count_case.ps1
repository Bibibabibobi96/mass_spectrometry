[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [ValidateRange(1,100)]
  [int]$ParticleCount,
  [double]$MassAmu = 500.0,
  [int]$Seed = 20260713,
  [string]$RunId = 'extreme_n_threshold_20260719'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\oa_tof'
$caseDir = Join-Path $artifactRoot ("runs\candidate_gate\{0}\N{1}" -f $RunId,$ParticleCount)
if (Test-Path -LiteralPath $caseDir) {
  throw "Extreme-N case already exists: $caseDir"
}
New-Item -ItemType Directory -Path $caseDir -Force | Out-Null

$ionGenerator = Join-Path $projectRoot 'simion\workbench\generate_comsol_consistent_ions.ps1'
$launcher = Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1'
$task = Join-Path $projectRoot 'tests\comsol\test_accelerator_mesh_particle_candidate.m'
$formalMph = Join-Path $artifactRoot 'models\comsol\formal\MS_oaTOF_TwoStageRingStackReflectron_Final.mph'
$geometryPath = Join-Path $projectRoot 'config\resolved_geometry.json'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
foreach ($path in @($ionGenerator,$launcher,$task,$formalMph,$geometryPath,$python)) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    throw "Required input is absent: $path"
  }
}

$geometry = Get-Content -LiteralPath $geometryPath -Raw -Encoding UTF8 | ConvertFrom-Json
$source = $geometry.particle_source
$ionPath = Join-Path $caseDir ("mz{0:g}_N{1}.ion" -f $MassAmu,$ParticleCount)
$csvPath = Join-Path $caseDir 'comsol_particles.csv'
$reportPath = Join-Path $caseDir 'comsol_report.txt'
$summaryPath = Join-Path $caseDir 'case_summary.json'
if (-not (Test-Path -LiteralPath $ionPath -PathType Leaf)) {
  & $ionGenerator -N $ParticleCount -MassAmu $MassAmu -Charge 1 `
    -EnergyMeanEv 5 -EnergyStdEv 0.4 `
    -HalfWidthXmm ([double]$source.size_x_mm/2) `
    -HalfWidthYmm ([double]$source.size_y_mm/2) `
    -HalfWidthZmm ([double]$source.size_z_mm/2) `
    -CenterXmm ([double]$source.center_x_mm) `
    -CenterYmm ([double]$source.center_y_mm) `
    -CenterZmm ([double]$source.center_z_mm) `
    -Seed $Seed -Output $ionPath | Out-Null
}
if (@(Get-Content -LiteralPath $ionPath).Count -ne $ParticleCount) {
  throw "ION row count is incorrect: $ionPath"
}

$variables = @{
  OATOF_SOURCE_MODEL_PATH=$formalMph
  OATOF_ION_TABLE=$ionPath
  OATOF_COMSOL_OUTPUT_CSV=$csvPath
  OATOF_ACCELERATOR_HMAX_MM='1'
  OATOF_REUSE_EXISTING_FIELD='1'
  OATOF_FINE_TSTEP_NS='0.2'
  OATOF_DRIFT_TSTEP_NS='50'
  OATOF_SEGMENTED_OUTPUT='1'
  OATOF_USE_PARTICLE_STOP_TIME='0'
  OATOF_CLEAR_PARTICLE_SOLUTION_DATA='0'
  OATOF_APPLY_PARTICLE_PROPERTIES='1'
}
$old = @{}
$knownCrashLogs = @(Get-ChildItem -LiteralPath $repoRoot -File -Filter 'hs_err_pid*.log' |
  ForEach-Object { $_.FullName })
$watch = [Diagnostics.Stopwatch]::StartNew()
$failure = $null
Write-Output "EXTREME_N_CASE=START N=$ParticleCount MASS_AMU=$MassAmu PATH=$caseDir"
try {
  foreach ($entry in $variables.GetEnumerator()) {
    $old[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key,'Process')
    [Environment]::SetEnvironmentVariable($entry.Key,$entry.Value,'Process')
  }
  & $launcher -TaskScript $task -ReportPath $reportPath
} catch {
  $failure = $_.Exception.Message
} finally {
  $watch.Stop()
  foreach ($entry in $variables.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key,$old[$entry.Key],'Process')
  }
}

$newCrashLogs = [Collections.Generic.List[string]]::new()
foreach ($log in @(Get-ChildItem -LiteralPath $repoRoot -File -Filter 'hs_err_pid*.log')) {
  if ($knownCrashLogs -notcontains $log.FullName) {
    $destination = Join-Path $caseDir $log.Name
    Move-Item -LiteralPath $log.FullName -Destination $destination
    $newCrashLogs.Add($destination)
  }
}
$launcherLogs = @(Get-ChildItem -LiteralPath $caseDir -File -Filter 'comsol_report.txt.launcher.attempt*.log' |
  ForEach-Object { $_.FullName })

$reportText = if (Test-Path -LiteralPath $reportPath -PathType Leaf) {
  Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8
} else { '' }
$expectedDetection = "DETECTED={0}/{0}" -f $ParticleCount
$passed = ($reportText -match '(?m)^STATUS=PASS$') -and
  ($reportText -match ("(?m)^" + [regex]::Escape($expectedDetection) + '$'))
$reportCreated = [bool](Test-Path -LiteralPath $reportPath -PathType Leaf)
$studyStarted = $reportText -match '(?m)^(?:STUDY_STARTED=1|PARTICLE_SOLUTION_DATA_CLEARED=)'
$studyCompleted = $reportText -match '(?m)^(?:STUDY_COMPLETED=1|SOLUTION_SIZES=)'
$initialReleaseRead = $reportText -match '(?m)^INITIAL_RELEASE_READ=PASS$'
$failureStage = if ($passed) {
  $null
} elseif (-not $reportCreated) {
  'launcher_startup'
} elseif (-not $studyStarted) {
  'task_configuration'
} elseif (-not $studyCompleted) {
  'study_compute'
} elseif (-not $initialReleaseRead) {
  'result_extraction'
} else {
  'task_postprocess'
}
$summary = [ordered]@{
  schema_version = 1
  role = 'oa_tof_comsol_extreme_particle_count_case'
  status = if ($passed) { 'PASS' } else { 'FAIL' }
  particle_count = $ParticleCount
  mass_amu = $MassAmu
  seed = $Seed
  wall_seconds = $watch.Elapsed.TotalSeconds
  launcher_failure = $failure
  failure_stage = $failureStage
  threshold_result_eligible = $studyStarted
  study_started = $studyStarted
  study_completed = $studyCompleted
  initial_release_read_completed = $initialReleaseRead
  report_created = $reportCreated
  output_csv_created = [bool](Test-Path -LiteralPath $csvPath -PathType Leaf)
  expected_detection = $expectedDetection
  ion_file = $ionPath
  report_file = $reportPath
  output_csv = $csvPath
  crash_logs = @($newCrashLogs)
  launcher_logs = @($launcherLogs)
}
$summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
$runConfigPath = Join-Path $caseDir 'run_config.json'
$manifestPath = Join-Path $caseDir 'run_manifest.json'
[ordered]@{
  schema_version = 1
  role = 'oa_tof_comsol_extreme_particle_count_run_config'
  run_id = "$RunId-N$ParticleCount"
  project = 'oa_tof'
  project_root = $projectRoot
  mode = 'comsol_extreme_particle_count_threshold'
  formal_gate_passed = $false
  inputs = [ordered]@{
    resolved_geometry = $geometryPath
    formal_comsol_mph = $formalMph
    ion_table = $ionPath
    task_script = $task
  }
  variables = [ordered]@{ particle_count=$ParticleCount; mass_amu=$MassAmu; seed=$Seed }
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8
$outputs = @($ionPath,$summaryPath)
foreach ($path in @($reportPath,$csvPath) + @($newCrashLogs) + @($launcherLogs)) {
  if (Test-Path -LiteralPath $path -PathType Leaf) { $outputs += $path }
}
$outputs += @(Get-ChildItem -LiteralPath $caseDir -File -Filter '*_selected_release_from_data_file.txt' |
  ForEach-Object { $_.FullName })
$manifestStatus = if ($passed) { 'success' } else { 'failed' }
$manifestArgs = @((Join-Path $repoRoot 'common\contracts\write_run_manifest.py'),
  '--run-config',$runConfigPath,'--manifest',$manifestPath,'--status',$manifestStatus,
  '--software','COMSOL 6.4 build 293 via MATLAB R2025b')
foreach ($path in $outputs) { $manifestArgs += @('--output',$path) }
& $python @manifestArgs
if ($LASTEXITCODE -ne 0) { throw 'Extreme-N manifest creation failed.' }
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $manifestPath `
  --require-status $manifestStatus
if ($LASTEXITCODE -ne 0) { throw 'Extreme-N manifest verification failed.' }
Write-Output ("EXTREME_N_CASE={0} N={1} WALL_SECONDS={2:F3} SUMMARY={3}" -f `
  $summary.status,$ParticleCount,$watch.Elapsed.TotalSeconds,$summaryPath)
