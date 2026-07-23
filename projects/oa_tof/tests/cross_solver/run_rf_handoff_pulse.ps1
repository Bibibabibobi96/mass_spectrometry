[CmdletBinding()]
param(
  [string]$RunId = ((Get-Date -Format 'yyyyMMdd_HHmmss') + '__sim__simion__rf-handoff-pulse__n100'),
  [string]$ModePath = '',
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\oa_tof'
$runDir = Join-Path $artifactRoot "runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Pulse run already exists: $runDir" }
$inputDir = Join-Path $runDir 'inputs'
$resultDir = Join-Path $runDir 'results'
$logDir = Join-Path $runDir 'logs'
$runtimeDir = Join-Path $runDir 'simion'
New-Item -ItemType Directory -Path $inputDir,$resultDir,$logDir,$runtimeDir | Out-Null

$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
Initialize-RunRecord -RunDir $runDir -RunId $RunId -Project 'oa_tof' `
  -Mode 'rf_handoff_pulse' -ProjectRoot $projectRoot `
  -RepoRoot $repoRoot -Python $python -ProvisionalSummaryRole 'oa_tof_provisional_run_summary' `
  -TerminalSummaryRole 'oa_tof_terminal_run_summary'
$runRecordComplete = $false
trap {
  if (-not $runRecordComplete) {
    Write-TerminalRunRecord -RunDir $runDir -Status failed `
      -Reason $_.Exception.Message -RepoRoot $repoRoot -Python $python `
      -SummaryRole 'oa_tof_terminal_run_summary'
  }
  exit 1
}
$modePath = if ([string]::IsNullOrWhiteSpace($ModePath)) { Join-Path $projectRoot 'config\modes\rf_handoff_pulse.json' } else { [IO.Path]::GetFullPath($ModePath) }
$prepare = Join-Path $projectRoot 'analysis\prepare_rf_handoff_projection.py'
$analyze = Join-Path $projectRoot 'analysis\analyze_rf_handoff_pulse.py'
$builder = Join-Path $repoRoot 'projects\rf_quadrupole_collision_cooling\analysis\build_oatof_handoff.py'
$formalDir = Join-Path $artifactRoot 'formal\simion'
$formalIob = Join-Path $formalDir 'oatof_ideal_grounded.iob'
$formalProgramSource = Join-Path $projectRoot 'simion\workbench\formal\oatof_ideal_grounded.lua'
$pulseProgram = Join-Path $projectRoot 'simion\workbench\candidates\oatof_handoff_pulse.lua'
$pulseProgramBuilder = Join-Path $projectRoot 'analysis\build_handoff_pulse_program.py'
$simionAnalyzer = Join-Path $projectRoot 'simion\workbench\analyze_ideal_field_log.ps1'

& $python $prepare --mode $modePath --check-mode
if ($LASTEXITCODE -ne 0) { throw 'Pulse mode static validation failed.' }
$mode = Get-Content -LiteralPath $modePath -Raw -Encoding UTF8 | ConvertFrom-Json
$case = $mode.source_cases[0]
$sourceCsv = Join-Path $workspaceRoot $case.particle_state_csv
$sourceManifest = Join-Path $workspaceRoot $case.run_manifest
$contract = Join-Path $repoRoot $mode.handoff_contract
$canonical = Join-Path $inputDir 'canonical_handoff.csv'
$ion = Join-Path $inputDir 'particles_instrument_clock.ion'
$rowMap = Join-Path $inputDir 'row_map.csv'
$metadata = Join-Path $inputDir 'handoff_metadata.json'
$request = Join-Path $inputDir 'consumer_request.json'
$targetOrigin = @($mode.projection.target_origin_mm | ForEach-Object { [double]$_ })
$builderArgs = @($builder,'--contract',$contract,'--convert','--solver-clock','instrument_time',
  '--source-csv',$sourceCsv,'--source-manifest',$sourceManifest,'--canonical-output',$canonical,
  '--ion-output',$ion,'--row-map-output',$rowMap,'--metadata-output',$metadata,
  '--target-origin-mm',[string]$targetOrigin[0],[string]$targetOrigin[1],[string]$targetOrigin[2])
& $python @builderArgs
if ($LASTEXITCODE -ne 0) { throw 'Shared-clock handoff build failed.' }
& $python $prepare --mode $modePath --validate-bundle --canonical $canonical --ion $ion `
  --row-map $rowMap --metadata $metadata --output $request
if ($LASTEXITCODE -ne 0) { throw 'Pulse consumer rejected the handoff bundle.' }

$resolved = Get-Content -LiteralPath (Join-Path $projectRoot 'config\resolved_geometry.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$sourceCenterX = [double]$resolved.coordinate_convention.accelerator_axis_x
$timingJson = & $python (Join-Path $projectRoot 'analysis\solver_diagnostics.py') pulse-timing `
  --canonical $canonical --source-center-x-mm $sourceCenterX --target-origin-x-mm $targetOrigin[0]
if ($LASTEXITCODE -ne 0) { throw 'Pulse timing calculation failed.' }
$timing = $timingJson | ConvertFrom-Json
$entryToCenterMm = [double]$timing.entry_to_source_center_mm
$pulseTimeUs = [double]$timing.pulse_time_us
$pulseWidthUs = [double]$mode.pulse.width_us
$diagnosticMaxUs = $pulseTimeUs + [double]$mode.pulse.maximum_elapsed_after_pulse_us
$runtimeIob = Join-Path $runtimeDir 'oatof_ideal_grounded.iob'
foreach ($pa in Get-ChildItem -LiteralPath $formalDir -File | Where-Object { $_.Name -match '\.pa(?:-surf|#|\d+)$' }) {
  $link = Join-Path $runtimeDir $pa.Name
  if (-not (Test-Path -LiteralPath $link)) {
    New-Item -ItemType HardLink -Path $link -Target $pa.FullName | Out-Null
  }
}
Copy-Item -LiteralPath $formalIob -Destination $runtimeIob
$formalCon = Join-Path $formalDir 'oatof_ideal_grounded.con'
if (Test-Path -LiteralPath $formalCon) { Copy-Item -LiteralPath $formalCon -Destination (Join-Path $runtimeDir 'oatof_ideal_grounded.con') }
$runtimeProgram = Join-Path $runtimeDir 'oatof_ideal_grounded.lua'
$programBuildMetadata = Join-Path $inputDir 'pulse_program_build.json'
& $python $pulseProgramBuilder --formal $formalProgramSource --extension $pulseProgram `
  --output $runtimeProgram --metadata $programBuildMetadata
if ($LASTEXITCODE -ne 0) { throw 'Pulse candidate Program build failed.' }

try {
  $outputs = @{}
  foreach ($pulseCase in @(@{Name='timed';Mode=1},@{Name='held_off';Mode=2})) {
    $stdout = Join-Path $logDir ($pulseCase.Name + '.stdout.log')
    $stderr = Join-Path $logDir ($pulseCase.Name + '.stderr.log')
    $csv = Join-Path $resultDir ($pulseCase.Name + '_particles.csv')
    $process = Start-Process -FilePath $SimionExe -WorkingDirectory $runtimeDir -WindowStyle Hidden `
      -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr -ArgumentList @(
        '--default-num-particles','100','--nogui','fly','--trajectory-quality','8',
        '--retain-trajectories','0','--particles',$ion,'--programs','1',
        '--adjustable','trajectory_quality=8','--adjustable','trajectory_log_enable=1',
        '--adjustable',("diagnostic_max_tof_us={0:R}" -f $diagnosticMaxUs),
        '--adjustable',("handoff_pulse_mode={0}" -f $pulseCase.Mode),
        '--adjustable',("handoff_pulse_time_us={0:R}" -f $pulseTimeUs),
        '--adjustable',("handoff_pulse_width_us={0:R}" -f $pulseWidthUs),$runtimeIob)
    if ($process.ExitCode -ne 0) { throw "SIMION pulse case $($pulseCase.Name) failed: $stderr" }
    & $simionAnalyzer -Log $stdout -IonFile $ion -Mode 'rf_handoff_pulse' `
      -Distribution $pulseCase.Name -ParticleCsv $csv -AllowIncompleteCensus | Out-Null
    $outputs[$pulseCase.Name] = $csv
  }
} finally {
}

$metrics = Join-Path $resultDir 'rf_handoff_pulse_metrics.json'
$events = Join-Path $resultDir 'rf_handoff_pulse_events.csv'
$timeline = Join-Path $resultDir 'rf_handoff_pulse_timeline.png'
$snapshot = Join-Path $resultDir 'rf_handoff_pulse_snapshot.png'
& $python $analyze --timed $outputs.timed --control $outputs.held_off --mode $modePath `
  --canonical $canonical --row-map $rowMap `
  --pulse-log (Join-Path $logDir 'timed.stdout.log') --output $metrics `
  --events-output $events --timeline-output $timeline --snapshot-output $snapshot
if ($LASTEXITCODE -ne 0) { throw 'Shared-clock pulse functional gate failed.' }
$result = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 | ConvertFrom-Json

$runConfig = Join-Path $runDir 'run_config.json'
[ordered]@{schema_version=1;role='oa_tof_rf_handoff_pulse_run_config';run_id=$RunId;project='oa_tof';
  mode='rf_handoff_pulse';inputs=[ordered]@{mode=$modePath;handoff_contract=$contract;formal_simion_iob=$formalIob};
  projection=[ordered]@{target_origin_mm=$targetOrigin;entry_to_source_center_mm=$entryToCenterMm};
  pulse=[ordered]@{instrument_time_us=$pulseTimeUs;width_us=$pulseWidthUs;waveform='ideal_rectangular';control='held_off'};
  execution=[ordered]@{formal_assets_modified=$false;physical_interface_modeled=$false}} |
  ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfig -Encoding UTF8
$summary = Join-Path $runDir 'summary.json'
[ordered]@{schema_version=1;role='oa_tof_rf_handoff_pulse_run_summary';status='success';
  candidate_decision=$result.status;functional_link_status=$result.status;physical_link_status='DEFERRED';
  resolution_claim_allowed=$false;metrics=$metrics} | ConvertTo-Json -Depth 5 |
  Set-Content -LiteralPath $summary -Encoding UTF8
$manifest = Join-Path $runDir 'run_manifest.json'
$manifestArgs = @((Join-Path $repoRoot 'common\contracts\write_run_manifest.py'),'--run-config',$runConfig,
  '--manifest',$manifest,'--status','success','--software','SIMION 2020')
foreach ($path in @($canonical,$ion,$rowMap,$metadata,$request,$programBuildMetadata,$runtimeProgram,$outputs.timed,$outputs.held_off,$metrics,$events,$timeline,$snapshot,
  (Join-Path $logDir 'timed.stdout.log'),(Join-Path $logDir 'timed.stderr.log'),
  (Join-Path $logDir 'held_off.stdout.log'),(Join-Path $logDir 'held_off.stderr.log'),$summary)) {
  $manifestArgs += @('--output',$path)
}
& $python @manifestArgs
if ($LASTEXITCODE -ne 0) { throw 'Pulse run manifest creation failed.' }
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $manifest
if ($LASTEXITCODE -ne 0) { throw 'Pulse run manifest verification failed.' }
$runRecordComplete = $true
Write-Output "RF_HANDOFF_PULSE=$($result.status) RUN_ID=$RunId TIMED=$($result.timed_pulse.hits)/100 CONTROL=$($result.held_off_control.hits)/100"
