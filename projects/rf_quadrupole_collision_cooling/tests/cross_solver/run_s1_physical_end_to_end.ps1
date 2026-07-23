[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$SourceRunId,
  [Parameter(Mandatory = $true)][string]$RunId,
  [double]$PulseTimeUs = 54.45242561132196,
  [double]$PulseWidthUs = 1.0,
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$source = Join-Path $artifactRoot "runs\$SourceRunId"
$sourceManifest = Get-Content -LiteralPath (Join-Path $source 'run_manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($sourceManifest.status -ne 'success') {
  throw 'S1 downstream runtime requires a successful physical-port source.'
}
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
  (Join-Path $source 'run_manifest.json') --require-status success
if ($LASTEXITCODE -ne 0) { throw 'S1 source manifest verification failed.' }
$directJointSource = $sourceManifest.mode -eq 'rf_to_oatof_s1_local_joint_field'
if (-not $directJointSource -and $sourceManifest.mode -ne 's1_physical_port_analysis_only') {
  throw 'S1 downstream runtime requires a successful joint-field or analysis-only physical-port source.'
}
if ($directJointSource) {
  $sourceConfig = Get-Content -LiteralPath (Join-Path $source 'run_config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  $parameters = $sourceConfig.parameters
  if (-not [bool]$parameters.particle_tracking -or [int]$parameters.particle_count -ne 100 -or
      $parameters.geometry_state -ne 'opened_port' -or [math]::Abs([double]$parameters.port_full_width_y_mm-1.0) -gt 1e-12 -or
      [math]::Abs([double]$parameters.pulse_time_us-$PulseTimeUs) -gt 1e-9 -or
      [math]::Abs([double]$parameters.pulse_width_us-$PulseWidthUs) -gt 1e-12) {
    throw 'Direct joint-field source does not match the N=100 physical-port pulse request.'
  }
}
$runDir = Join-Path $artifactRoot "runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Run already exists: $runDir" }
$inputDir = Join-Path $runDir 'inputs'; $resultDir = Join-Path $runDir 'results'
$logDir = Join-Path $runDir 'logs'; $runtimeDir = Join-Path $runDir 'simion'
New-Item -ItemType Directory -Force -Path $inputDir,$resultDir,$logDir,$runtimeDir | Out-Null
$entry = Join-Path $inputDir 'canonical_rf_exit_at_oatof_entry.csv'
$local = Join-Path $inputDir 's1_physical_port_particles.csv'
Copy-Item -LiteralPath (Join-Path $source 'inputs\canonical_rf_exit_at_oatof_entry.csv') -Destination $entry
$sourceLocal = if ($directJointSource) {
  Join-Path $source 'results\s1_physical_port_particles.csv'
} else {
  Join-Path $source 'inputs\s1_physical_port_particles.csv'
}
Copy-Item -LiteralPath $sourceLocal -Destination $local
$converter = Join-Path $inputDir 'build_s1_downstream_handoff.py'
$handoffLibrary = Join-Path $inputDir 'build_oatof_handoff.py'
$analyzer = Join-Path $inputDir 'analyze_s1_end_to_end.py'
$stateAuditor = Join-Path $inputDir 'audit_s1_state_chain.py'
$handoffAdapter = Join-Path $inputDir 'rf_handoff_adapter.py'
Copy-Item -LiteralPath (Join-Path $projectRoot 'analysis\build_s1_downstream_handoff.py') -Destination $converter
Copy-Item -LiteralPath (Join-Path $projectRoot 'analysis\build_oatof_handoff.py') -Destination $handoffLibrary
Copy-Item -LiteralPath (Join-Path $projectRoot 'analysis\analyze_s1_end_to_end.py') -Destination $analyzer
Copy-Item -LiteralPath (Join-Path $projectRoot 'analysis\audit_s1_state_chain.py') -Destination $stateAuditor
Copy-Item -LiteralPath (Join-Path $repoRoot 'projects\oa_tof\analysis\rf_handoff_adapter.py') -Destination $handoffAdapter
$peakMetrics = Join-Path $inputDir 'peak_metrics.py'
$analysisContract = Join-Path $inputDir 'oatof_analysis_contract.json'
$geometryContract = Join-Path $inputDir 'oatof_resolved_geometry.json'
Copy-Item -LiteralPath (Join-Path $repoRoot 'projects\oa_tof\analysis\peak_metrics.py') -Destination $peakMetrics
Copy-Item -LiteralPath (Join-Path $repoRoot 'projects\oa_tof\config\analysis_contract.json') -Destination $analysisContract
Copy-Item -LiteralPath (Join-Path $repoRoot 'projects\oa_tof\config\resolved_geometry.json') -Destination $geometryContract
$canonical = Join-Path $inputDir 'canonical_local_joint_exit.csv'
$ion = Join-Path $inputDir 'local_joint_exit_instrument_clock.ion'
$rowMap = Join-Path $inputDir 'row_map.csv'
$handoffMetadata = Join-Path $inputDir 'handoff_metadata.json'
& $python $converter --events $local --entry-canonical $entry --canonical-output $canonical `
  --ion-output $ion --row-map-output $rowMap --metadata-output $handoffMetadata
if ($LASTEXITCODE -ne 0) { throw 'S1 no-projection handoff build failed.' }
$particleCount = @(Get-Content -LiteralPath $ion | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count
$frameIds = @(Import-Csv -LiteralPath $canonical | Select-Object -ExpandProperty frame_id -Unique)
if ($frameIds.Count -ne 1) { throw 'S1 downstream handoff must use one explicit authoritative frame.' }
$authoritativeFrameId = [string]$frameIds[0]

$oaProject = Join-Path $repoRoot 'projects\oa_tof'
$formalDir = Join-Path $workspaceRoot 'artifacts\projects\oa_tof\formal\simion'
$formalIob = Join-Path $formalDir 'oatof_ideal_grounded.iob'
foreach ($pa in Get-ChildItem -LiteralPath $formalDir -File | Where-Object { $_.Name -match '\.pa(?:-surf|#|\d+)$' }) {
  New-Item -ItemType HardLink -Path (Join-Path $runtimeDir $pa.Name) -Target $pa.FullName | Out-Null
}
$runtimeIob = Join-Path $runtimeDir 'oatof_ideal_grounded.iob'
Copy-Item -LiteralPath $formalIob -Destination $runtimeIob
$formalCon = Join-Path $formalDir 'oatof_ideal_grounded.con'
if (Test-Path -LiteralPath $formalCon) { Copy-Item -LiteralPath $formalCon -Destination (Join-Path $runtimeDir 'oatof_ideal_grounded.con') }
$programBuilder = Join-Path $oaProject 'analysis\build_handoff_pulse_program.py'
$runtimeProgram = Join-Path $runtimeDir 'oatof_ideal_grounded.lua'
$programMetadata = Join-Path $inputDir 'pulse_program_build.json'
& $python $programBuilder --formal (Join-Path $oaProject 'simion\workbench\formal\oatof_ideal_grounded.lua') `
  --extension (Join-Path $oaProject 'simion\workbench\candidates\oatof_handoff_pulse.lua') `
  --output $runtimeProgram --metadata $programMetadata
if ($LASTEXITCODE -ne 0) { throw 'S1 downstream pulse Program build failed.' }

$stdout = Join-Path $logDir 'simion.stdout.log'; $stderr = Join-Path $logDir 'simion.stderr.log'
# SIMION accepts only its supported defaults here; the ION table row count controls
# the actual number of particles emitted by this run.
$simionDefaultParticleCount = 100
$process = Start-Process -FilePath $SimionExe -WorkingDirectory $runtimeDir -WindowStyle Hidden -Wait -PassThru `
  -RedirectStandardOutput $stdout -RedirectStandardError $stderr -ArgumentList @(
    '--default-num-particles',([string]$simionDefaultParticleCount),'--nogui','fly','--trajectory-quality','8',
    '--retain-trajectories','0','--particles',$ion,'--programs','1',
    '--adjustable','trajectory_quality=8','--adjustable','trajectory_log_enable=1',
    '--adjustable','diagnostic_max_tof_us=90',
    '--adjustable','handoff_pulse_mode=1',
    '--adjustable',("handoff_pulse_time_us={0:R}" -f $PulseTimeUs),
    '--adjustable',("handoff_pulse_width_us={0:R}" -f $PulseWidthUs),$runtimeIob)
if ($process.ExitCode -ne 0) { throw "SIMION S1 downstream runtime failed: $stderr" }
$downstream = Join-Path $resultDir 'simion_downstream_particles.csv'
& (Join-Path $oaProject 'simion\workbench\analyze_ideal_field_log.ps1') -Log $stdout -IonFile $ion `
  -Mode 'rf_oatof_s1_physical_end_to_end' -Distribution 'physical_port_pulse' `
  -ParticleCsv $downstream -AllowIncompleteCensus | Out-Null
$metrics = Join-Path $resultDir 's1_end_to_end_metrics.json'
$events = Join-Path $resultDir 's1_end_to_end_events.csv'
$figure = Join-Path $resultDir 's1_end_to_end_funnel.png'
$resolutionFigure = Join-Path $resultDir 's1_downstream_resolution_diagnostic.png'
& $python $analyzer --entry $entry --local $local --downstream $downstream --row-map $rowMap `
  --events-output $events --figure $figure --resolution-figure $resolutionFigure `
  --pulse-time-us $PulseTimeUs --pulse-width-us $PulseWidthUs `
  --analysis-contract $analysisContract --geometry-contract $geometryContract --output $metrics
if ($LASTEXITCODE -ne 0) { throw 'S1 end-to-end function gate failed.' }
$result = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 | ConvertFrom-Json
$runConfig = Join-Path $runDir 'run_config.json'
[ordered]@{schema_version=1;run_id=$RunId;project='rf_quadrupole_collision_cooling';mode='rf_oatof_s1_physical_end_to_end';project_root=$repoRoot;inputs=[ordered]@{source_run_manifest=(Join-Path $source 'run_manifest.json');formal_simion_iob=$formalIob;local_joint_events=$local;entry_canonical=$entry;converter=$converter;handoff_library=$handoffLibrary;analyzer=$analyzer;state_chain_auditor=$stateAuditor;oa_shared_handoff_adapter=$handoffAdapter;peak_metrics=$peakMetrics;analysis_contract=$analysisContract;geometry_contract=$geometryContract};parameters=[ordered]@{particle_count=$particleCount;ion_table_rows=$particleCount;simion_default_num_particles=$simionDefaultParticleCount;source_mode=$sourceManifest.mode;authoritative_frame_id=$authoritativeFrameId;position_projection_applied=$false;solver_clock='instrument_time';pulse_time_us=$PulseTimeUs;pulse_width_us=$PulseWidthUs;downstream_time_origin='shared_pulse_onset';dense_trajectories_saved=$false};formal_gate_passed=$false} | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $runConfig -Encoding UTF8
$stateAudit = Join-Path $resultDir 's1_state_chain_audit.json'
& $python $stateAuditor --entry $entry --local-events $local --canonical $canonical --ion $ion `
  --row-map $rowMap --downstream $downstream --handoff-metadata $handoffMetadata `
  --run-config $runConfig --source-run-config (Join-Path $source 'run_config.json') `
  --simion-stdout $stdout --output $stateAudit
if ($LASTEXITCODE -ne 0) { throw 'S1 state-chain physics audit failed.' }
$stateAuditResult = Get-Content -LiteralPath $stateAudit -Raw -Encoding UTF8 | ConvertFrom-Json
$summary = Join-Path $runDir 'summary.json'
[ordered]@{schema_version=1;role='rf_oatof_s1_physical_end_to_end_summary';status='success';candidate_decision=$result.status;state_chain_audit=$stateAuditResult.status;detector_hits=$result.detector_hits;rf_exit_particles=100;local_joint_exit=$result.local_joint_exit;resolution_diagnostic=$result.resolution_diagnostic;physical_link_claim_allowed=$false;resolution_claim_allowed=$false} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summary -Encoding UTF8
$writer = Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
$args = @($writer,'--run-config',$runConfig,'--status','success','--software','COMSOL 6.4','--software','SIMION 2020','--software','Python 3.11')
foreach ($output in @($canonical,$ion,$rowMap,$handoffMetadata,$programMetadata,$runtimeProgram,$downstream,$metrics,$stateAudit,$events,$figure,$resolutionFigure,$stdout,$stderr,$summary)) { $args += @('--output',$output) }
& $python @args
if ($LASTEXITCODE -ne 0) { throw 'S1 end-to-end manifest failed.' }
Write-Output "S1_PHYSICAL_END_TO_END=PASS RUN_ID=$RunId HITS=$($result.detector_hits)/100 LOCAL_EXIT=$($result.local_joint_exit)/100"
