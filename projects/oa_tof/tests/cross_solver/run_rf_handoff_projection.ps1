[CmdletBinding()]
param(
  [string]$RunId = ((Get-Date -Format 'yyyyMMdd_HHmmss') + '__sim__cross__rf-handoff-projection__n100'),
  [ValidateSet('Both','COMSOL','SIMION')][string]$TargetSolver = 'Both',
  [string]$ModePath = '',
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [switch]$Resume
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\oa_tof'
$runDir = Join-Path $artifactRoot "runs\$RunId"
$inputDir = Join-Path $runDir 'inputs'
$resultDir = Join-Path $runDir 'results'
$logDir = Join-Path $runDir 'logs'
$comsolDir = Join-Path $runDir 'comsol'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$modePath = if ([string]::IsNullOrWhiteSpace($ModePath)) { Join-Path $projectRoot 'config\modes\rf_handoff_projection.json' } else { [IO.Path]::GetFullPath($ModePath) }
$prepare = Join-Path $projectRoot 'analysis\prepare_rf_handoff_projection.py'
$analyze = Join-Path $projectRoot 'analysis\analyze_rf_handoff_projection.py'
$rfBuilder = Join-Path $repoRoot 'projects\rf_quadrupole_collision_cooling\analysis\build_oatof_handoff.py'
$comsolTask = Join-Path $projectRoot 'tests\comsol\test_accelerator_mesh_particle_candidate.m'
$comsolLauncher = Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1'
$simionAnalyzer = Join-Path $projectRoot 'simion\workbench\analyze_ideal_field_log.ps1'
$simionStableGate = Join-Path $projectRoot 'tests\simion\verify_stable_entry.ps1'
$resolvedPath = Join-Path $projectRoot 'config\resolved_geometry.json'
$formalAssetsPath = Join-Path $projectRoot 'config\formal_assets.json'
$formalMph = Join-Path $artifactRoot 'formal\comsol\oa_tof__model.mph'
$formalSimion = Join-Path $artifactRoot 'formal\simion'
$formalIob = Join-Path $formalSimion 'oatof_ideal_grounded.iob'

& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
& $python $prepare --mode $modePath --check-mode
if ($LASTEXITCODE -ne 0) { throw 'RF handoff consumer mode failed its static gate.' }

$required = @($python,$modePath,$prepare,$analyze,$rfBuilder,$resolvedPath,$formalAssetsPath)
if ($TargetSolver -in @('Both','COMSOL')) { $required += @($formalMph,$comsolTask,$comsolLauncher) }
if ($TargetSolver -in @('Both','SIMION')) { $required += @($formalIob,$SimionExe,$simionAnalyzer,$simionStableGate) }
foreach ($path in $required) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required runtime input is absent: $path" }
}
$formalAssets = Get-Content -LiteralPath $formalAssetsPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($TargetSolver -in @('Both','COMSOL')) {
  if ((Get-FileHash -LiteralPath $formalMph -Algorithm SHA256).Hash -ne $formalAssets.comsol.sha256) {
    throw 'Formal COMSOL MPH differs from config/formal_assets.json.'
  }
}
if ($TargetSolver -in @('Both','SIMION')) {
  & $simionStableGate -SimionExe $SimionExe
  if ($LASTEXITCODE -ne 0) { throw 'Formal SIMION stable-entry gate failed.' }
}
if (Test-Path -LiteralPath $runDir) {
  if (-not $Resume) { throw "RF handoff projection run already exists: $runDir" }
} else {
  New-Item -ItemType Directory -Path $runDir,$inputDir,$resultDir,$logDir,$comsolDir | Out-Null
}
foreach ($path in @($inputDir,$resultDir,$logDir,$comsolDir)) {
  if (-not (Test-Path -LiteralPath $path -PathType Container)) { New-Item -ItemType Directory -Path $path | Out-Null }
}

$mode = Get-Content -LiteralPath $modePath -Raw -Encoding UTF8 | ConvertFrom-Json
$handoffContract = Join-Path $repoRoot $mode.handoff_contract
$caseRecords = [Collections.Generic.List[object]]::new()
$allOutputs = [Collections.Generic.List[string]]::new()

foreach ($case in $mode.source_cases) {
  $caseDir = Join-Path $inputDir $case.case_id
  if (-not (Test-Path -LiteralPath $caseDir -PathType Container)) { New-Item -ItemType Directory -Path $caseDir | Out-Null }
  $sourceCsv = Join-Path $workspaceRoot $case.particle_state_csv
  $sourceManifest = Join-Path $workspaceRoot $case.run_manifest
  foreach ($path in @($sourceCsv,$sourceManifest)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Archived RF source evidence is absent: $path" }
  }
  $canonical = Join-Path $caseDir 'canonical_handoff.csv'
  $ion = Join-Path $caseDir 'particles.ion'
  $rowMap = Join-Path $caseDir 'row_map.csv'
  $metadata = Join-Path $caseDir 'handoff_metadata.json'
  $consumerRequest = Join-Path $caseDir 'consumer_request.json'
  $bundlePaths = @($canonical,$ion,$rowMap,$metadata)
  $existingBundle = @($bundlePaths | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
  if ($existingBundle.Count -ne $bundlePaths.Count) {
    if ($existingBundle.Count -gt 0) { throw "Resume bundle is partial for $($case.case_id)." }
    & $python $rfBuilder --contract $handoffContract --convert `
      --source-csv $sourceCsv --source-manifest $sourceManifest `
      --canonical-output $canonical --ion-output $ion `
      --row-map-output $rowMap --metadata-output $metadata
    if ($LASTEXITCODE -ne 0) { throw "RF handoff build failed for $($case.case_id)." }
  }
  & $python $prepare --mode $modePath --validate-bundle `
    --canonical $canonical --ion $ion --row-map $rowMap --metadata $metadata --output $consumerRequest
  if ($LASTEXITCODE -ne 0) { throw "oaTOF consumer rejected $($case.case_id)." }
  $request = Get-Content -LiteralPath $consumerRequest -Raw -Encoding UTF8 | ConvertFrom-Json
  $particleCount = [int]$request.particles
  $downstream = [ordered]@{}

  if ($TargetSolver -in @('Both','COMSOL')) {
    $caseComsolDir = Join-Path $comsolDir $case.case_id
    if (-not (Test-Path -LiteralPath $caseComsolDir -PathType Container)) { New-Item -ItemType Directory -Path $caseComsolDir | Out-Null }
    $comsolCsv = Join-Path $caseComsolDir 'particles.csv'
    $report = Join-Path $logDir ($case.case_id + '__comsol.report.txt')
    $expected = "DETECTED={0}/{0}" -f $particleCount
    $complete = (Test-Path -LiteralPath $comsolCsv -PathType Leaf) -and
      (Test-Path -LiteralPath $report -PathType Leaf) -and
      (Select-String -LiteralPath $report -Pattern ("^" + [regex]::Escape($expected) + '$') -Quiet)
    if (-not $complete) {
      if ($Resume -and (Test-Path -LiteralPath $report -PathType Leaf)) {
        throw "Resume found incomplete COMSOL evidence for $($case.case_id): $report"
      }
      $old = @{}
      $variables = [ordered]@{
        OATOF_SOURCE_MODEL_PATH=$formalMph
        OATOF_ION_TABLE=$ion
        OATOF_COMSOL_OUTPUT_CSV=$comsolCsv
        OATOF_RUNTIME_DIR=$caseComsolDir
        OATOF_RESULTS_DIR=$resultDir
        OATOF_ACCELERATOR_HMAX_MM='1'
        OATOF_REUSE_EXISTING_FIELD='1'
        OATOF_FINE_TSTEP_NS='0.2'
        OATOF_DRIFT_TSTEP_NS='50'
        OATOF_SEGMENTED_OUTPUT='1'
        OATOF_USE_PARTICLE_STOP_TIME='0'
        OATOF_CLEAR_PARTICLE_SOLUTION_DATA='0'
        OATOF_APPLY_PARTICLE_PROPERTIES='1'
      }
      try {
        foreach ($entry in $variables.GetEnumerator()) {
          $old[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key,'Process')
          [Environment]::SetEnvironmentVariable($entry.Key,[string]$entry.Value,'Process')
        }
        & $comsolLauncher -TaskScript $comsolTask -ReportPath $report
      } finally {
        foreach ($entry in $variables.GetEnumerator()) {
          [Environment]::SetEnvironmentVariable($entry.Key,$old[$entry.Key],'Process')
        }
      }
    }
    if (-not (Select-String -LiteralPath $report -Pattern ("^" + [regex]::Escape($expected) + '$') -Quiet)) {
      throw "COMSOL did not report $expected for $($case.case_id)."
    }
    $downstream['COMSOL'] = $comsolCsv
    $allOutputs.Add($comsolCsv); $allOutputs.Add($report)
  }

  if ($TargetSolver -in @('Both','SIMION')) {
    $simionLog = Join-Path $logDir ($case.case_id + '__simion.stdout.log')
    $simionError = Join-Path $logDir ($case.case_id + '__simion.stderr.log')
    $simionCsv = Join-Path $resultDir ($case.case_id + '__simion_particles.csv')
    $simionSummary = Join-Path $resultDir ($case.case_id + '__simion_summary.json')
    $complete = (Test-Path -LiteralPath $simionCsv -PathType Leaf) -and
      (Test-Path -LiteralPath $simionSummary -PathType Leaf)
    if (-not $complete) {
      if ($Resume -and ((Test-Path -LiteralPath $simionCsv) -or (Test-Path -LiteralPath $simionSummary))) {
        throw "Resume found incomplete SIMION evidence for $($case.case_id)."
      }
      if (-not ($Resume -and (Test-Path -LiteralPath $simionLog -PathType Leaf))) {
        $process = Start-Process -FilePath $SimionExe -WorkingDirectory $formalSimion `
          -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $simionLog `
          -RedirectStandardError $simionError -ArgumentList @(
            '--default-num-particles',[string]$particleCount,'--nogui','fly',
            '--trajectory-quality','8','--retain-trajectories','0','--particles',$ion,
            '--programs','1','--adjustable','trajectory_quality=8','--adjustable',
            'trajectory_log_enable=1','--adjustable','diagnostic_max_tof_us=90',$formalIob)
        if ($process.ExitCode -ne 0) { throw "SIMION fly failed for $($case.case_id): $simionError" }
      }
      $summary = & $simionAnalyzer -Log $simionLog -IonFile $ion `
        -Mode 'rf_handoff_projection' -Distribution ([string]$case.case_id) `
        -ParticleCsv $simionCsv -AllowIncompleteCensus
      $summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $simionSummary -Encoding UTF8
    }
    $summary = Get-Content -LiteralPath $simionSummary -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([int]$summary.Emitted -ne $particleCount) {
      throw "SIMION summary emitted count differs for $($case.case_id)."
    }
    $downstream['SIMION'] = $simionCsv
    foreach ($path in @($simionLog,$simionError,$simionCsv,$simionSummary)) { $allOutputs.Add($path) }
  }

  foreach ($path in @($canonical,$ion,$rowMap,$metadata,$consumerRequest)) { $allOutputs.Add($path) }
  $caseRecord = [ordered]@{
    case_id = [string]$case.case_id
    upstream_solver = [string]$case.upstream_solver
    canonical = $canonical
    row_map = $rowMap
    metadata = $metadata
    ion = $ion
    downstream_results = $downstream
  }
  if ($case.PSObject.Properties.Name -contains 'mesh_role') { $caseRecord.mesh_role = [string]$case.mesh_role }
  $caseRecords.Add($caseRecord)
}

$analysisInputs = Join-Path $inputDir 'analysis_inputs.json'
[ordered]@{
  schema_version = 1
  role = 'oa_tof_rf_handoff_projection_analysis_inputs'
  resolved_geometry = $resolvedPath
  cases = $caseRecords
} | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $analysisInputs -Encoding UTF8
$allOutputs.Add($analysisInputs)

& $python $analyze --mode $modePath --input-manifest $analysisInputs --output-dir $resultDir
$metricsPath = Join-Path $resultDir 'rf_handoff_projection_metrics.json'
$detectorCsv = Join-Path $resultDir 'detector_particles.csv'
if (-not (Test-Path -LiteralPath $metricsPath -PathType Leaf)) {
  throw 'RF handoff functional projection did not produce metrics.'
}
$metrics = Get-Content -LiteralPath $metricsPath -Raw -Encoding UTF8 | ConvertFrom-Json
$allOutputs.Add($metricsPath); $allOutputs.Add($detectorCsv)

$runConfigPath = Join-Path $runDir 'run_config.json'
[ordered]@{
  schema_version = 1
  role = 'oa_tof_rf_handoff_projection_run_config'
  run_id = $RunId
  project = 'oa_tof'
  mode = [IO.Path]::GetFileNameWithoutExtension($modePath)
  project_root = $projectRoot
  formal_gate_passed = $false
  inputs = [ordered]@{
    mode = $modePath
    handoff_contract = $handoffContract
    resolved_geometry = $resolvedPath
    formal_comsol_mph = if ($TargetSolver -in @('Both','COMSOL')) { $formalMph } else { $null }
    formal_simion_iob = if ($TargetSolver -in @('Both','SIMION')) { $formalIob } else { $null }
  }
  execution = [ordered]@{
    target_solver = $TargetSolver
    resumed = [bool]$Resume
    formal_assets_modified = $false
    physical_interface_modeled = $false
  }
} | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8

$summaryPath = Join-Path $runDir 'summary.json'
[ordered]@{
  schema_version = 1
  role = 'oa_tof_rf_handoff_projection_run_summary'
  status = 'success'
  candidate_decision = [string]$metrics.status
  strict_rf_interface_status = [string]$metrics.strict_rf_interface_status
  physical_link_status = [string]$metrics.physical_link_status
  resolution_claim_allowed = $false
  formal_assets_modified = $false
  metrics = $metricsPath
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
$allOutputs.Add($summaryPath)

$manifestPath = Join-Path $runDir 'run_manifest.json'
$manifestArgs = @(
  (Join-Path $repoRoot 'common\contracts\write_run_manifest.py'),
  '--run-config',$runConfigPath,'--manifest',$manifestPath,'--status','success'
)
if ($TargetSolver -in @('Both','COMSOL')) { $manifestArgs += @('--software','COMSOL 6.4 via MATLAB R2025b') }
if ($TargetSolver -in @('Both','SIMION')) { $manifestArgs += @('--software','SIMION 2020') }
foreach ($output in ($allOutputs | Select-Object -Unique)) {
  if (Test-Path -LiteralPath $output -PathType Leaf) { $manifestArgs += @('--output',$output) }
}
& $python @manifestArgs
if ($LASTEXITCODE -ne 0) { throw 'RF handoff run manifest creation failed.' }
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $manifestPath
if ($LASTEXITCODE -ne 0) { throw 'RF handoff run manifest verification failed.' }
Write-Output "RF_HANDOFF_PROJECTION=$($metrics.status) RUN_ID=$RunId TARGET=$TargetSolver PHYSICAL_LINK=BLOCKED"
