[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$SourceRunId,
  [Parameter(Mandatory)][string]$RunId,
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
. (Join-Path $projectRoot 'tests\support\rf_run_artifact_support.ps1')
$package = New-RfRunPackage -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RunId $RunId `
  -Project 'rf_quadrupole_collision_cooling' -Mode 'rf_to_oatof_s3_cumulative_end_to_end' `
  -Software @('COMSOL 6.4','SIMION 2020','Python 3.11')

try {
  if (-not (Test-Path -LiteralPath $SimionExe -PathType Leaf)) { throw "SIMION is missing: $SimionExe" }
  $source = Join-Path $artifactRoot "runs\$SourceRunId"
  $sourceManifestPath = Join-Path $source 'run_manifest.json'
  & $package.python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
    $sourceManifestPath --require-status success
  if ($LASTEXITCODE -ne 0) { throw 'S3 source manifest verification failed.' }
  $sourceConfig = Get-Content -LiteralPath (Join-Path $source 'run_config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($sourceConfig.mode -ne 'rf_to_oatof_s3_shared_clock_pulse_capture_n100') {
    throw 'Downstream continuation requires an S3 shared-clock pulse-capture source.'
  }
  $pulseTimeUs = [double]$sourceConfig.parameters.pulse_time_us
  $pulseWidthUs = [double]$sourceConfig.parameters.pulse_width_us
  if ([bool]$sourceConfig.parameters.s3_stage_passed) { throw 'Functional S3 source must not claim qualified S3 PASS.' }

  $runtimeDir = Join-Path $package.run_dir 'simion'
  New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
  $frozen = [ordered]@{}
  $sources = [ordered]@{
    adapter = [pscustomobject]@{path=(Join-Path $projectRoot 'analysis\build_simion_input_from_canonical.py'); filename='build_simion_input_from_canonical.py'}
    handoff_library = [pscustomobject]@{path=(Join-Path $projectRoot 'analysis\build_oatof_handoff.py'); filename='build_oatof_handoff.py'}
    analyzer = [pscustomobject]@{path=(Join-Path $projectRoot 'analysis\analyze_s3_end_to_end.py'); filename='analyze_s3_end_to_end.py'}
    runner = [pscustomobject]@{path=$PSCommandPath; filename='run_s3_end_to_end.ps1.txt'}
    source_summary = [pscustomobject]@{path=(Join-Path $source 'summary.json'); filename='source_summary.json'}
    source_canonical = [pscustomobject]@{path=(Join-Path $source 'results\s3_local_accelerator_exit.csv'); filename='source_canonical.csv'}
    oatof_geometry = [pscustomobject]@{path=(Join-Path $repoRoot 'projects\oa_tof\config\resolved_geometry.json'); filename='oatof_resolved_geometry.json'}
  }
  foreach ($name in $sources.Keys) {
    $destination = Join-Path $package.input_dir ([string]$sources[$name].filename)
    Copy-Item -LiteralPath ([string]$sources[$name].path) -Destination $destination
    $frozen[$name] = $destination
  }
  $canonical = Join-Path $package.input_dir 'canonical_local_accelerator_exit.csv'
  $ion = Join-Path $package.input_dir 'local_accelerator_exit_instrument_clock.ion'
  $rowMap = Join-Path $package.input_dir 'row_map.csv'
  $adapterMetadata = Join-Path $package.input_dir 'simion_adapter_metadata.json'
  & $package.python $frozen.adapter --source $frozen.source_canonical --canonical-output $canonical `
    --ion-output $ion --row-map-output $rowMap --metadata-output $adapterMetadata
  if ($LASTEXITCODE -ne 0) { throw 'Canonical-to-SIMION adapter failed.' }

  $oaProject = Join-Path $repoRoot 'projects\oa_tof'
  $formalDir = Join-Path $workspaceRoot 'artifacts\projects\oa_tof\formal\simion'
  $formalIob = Join-Path $formalDir 'oatof_ideal_grounded.iob'
  foreach ($pa in Get-ChildItem -LiteralPath $formalDir -File | Where-Object { $_.Name -match '\.pa(?:-surf|#|\d+)$' }) {
    New-Item -ItemType HardLink -Path (Join-Path $runtimeDir $pa.Name) -Target $pa.FullName | Out-Null
  }
  $runtimeIob = Join-Path $runtimeDir 'oatof_ideal_grounded.iob'
  Copy-Item -LiteralPath $formalIob -Destination $runtimeIob
  $formalCon = Join-Path $formalDir 'oatof_ideal_grounded.con'
  if (Test-Path -LiteralPath $formalCon) {
    Copy-Item -LiteralPath $formalCon -Destination (Join-Path $runtimeDir 'oatof_ideal_grounded.con')
  }
  $runtimeProgram = Join-Path $runtimeDir 'oatof_ideal_grounded.lua'
  $programMetadata = Join-Path $package.input_dir 'pulse_program_build.json'
  & $package.python (Join-Path $oaProject 'analysis\build_handoff_pulse_program.py') `
    --formal (Join-Path $oaProject 'simion\workbench\formal\oatof_ideal_grounded.lua') `
    --extension (Join-Path $oaProject 'simion\workbench\candidates\oatof_handoff_pulse.lua') `
    --output $runtimeProgram --metadata $programMetadata
  if ($LASTEXITCODE -ne 0) { throw 'Shared-clock oaTOF pulse program build failed.' }

  $stdout = Join-Path $package.log_dir 'simion.stdout.log'
  $stderr = Join-Path $package.log_dir 'simion.stderr.log'
  $process = Start-Process -FilePath $SimionExe -WorkingDirectory $runtimeDir -WindowStyle Hidden `
    -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr -ArgumentList @(
      '--default-num-particles','100','--nogui','fly','--trajectory-quality','8',
      '--retain-trajectories','0','--particles',$ion,'--programs','1',
      '--adjustable','trajectory_quality=8','--adjustable','trajectory_log_enable=1',
      '--adjustable','diagnostic_max_tof_us=90','--adjustable','handoff_pulse_mode=1',
      '--adjustable',("handoff_pulse_time_us={0:R}" -f $pulseTimeUs),
      '--adjustable',("handoff_pulse_width_us={0:R}" -f $pulseWidthUs),$runtimeIob)
  if ($process.ExitCode -ne 0) { throw "SIMION downstream continuation failed: $stderr" }
  $downstream = Join-Path $package.result_dir 'simion_downstream_particles.csv'
  & (Join-Path $oaProject 'simion\workbench\analyze_ideal_field_log.ps1') -Log $stdout -IonFile $ion `
    -Mode 'rf_oatof_s3_cumulative_end_to_end' -Distribution 's3_local_accelerator_exit' `
    -ParticleCsv $downstream -AllowIncompleteCensus | Out-Null
  $metrics = Join-Path $package.result_dir 's3_end_to_end_metrics.json'
  $figure = Join-Path $package.result_dir 's3_end_to_end_functional_chain.png'
  & $package.python $frozen.analyzer --source-summary $frozen.source_summary --canonical $canonical `
    --ion $ion --row-map $rowMap --downstream $downstream --stdout $stdout `
    --pulse-time-us $pulseTimeUs --pulse-width-us $pulseWidthUs `
    --geometry-contract $frozen.oatof_geometry --output $metrics --figure $figure
  if ($LASTEXITCODE -ne 0) { throw 'S3 end-to-end functional audit failed.' }
  $result = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 | ConvertFrom-Json

  Write-RfJson -Path $package.run_config -Depth 8 -Value ([ordered]@{
    schema_version=1; run_id=$RunId; project='rf_quadrupole_collision_cooling'
    mode='rf_to_oatof_s3_cumulative_end_to_end'; project_root=$repoRoot; inputs=$frozen
    parameters=[ordered]@{source_run_id=$SourceRunId; particle_count=$result.census.local_accelerator_exit
      authoritative_frame_id='oatof_global'; solver_clock='instrument_time'; position_projection_applied=$false
      pulse_time_us=$pulseTimeUs; pulse_width_us=$pulseWidthUs; dense_trajectories_saved=$false
      s3_stage_passed=$false}; formal_gate_passed=$false
  })
  Write-RfJson -Path $package.summary -Depth 8 -Value ([ordered]@{
    schema_version=1; role='rf_oatof_s3_cumulative_end_to_end_summary'; status='success'
    functional_audit=$result.status; census=$result.census; source_run_id=$SourceRunId
    figure='results/s3_end_to_end_functional_chain.png'; s3_stage_passed=$false
    resolution_claim_allowed=$false; formal_gate_passed=$false
  })
  $outputs = @($canonical,$ion,$rowMap,$adapterMetadata,$programMetadata,$runtimeProgram,
    $downstream,$metrics,$figure,$stdout,$stderr,$package.summary)
  $manifestOutput = Write-RfRunManifest -Python $package.python -RepoRoot $repoRoot `
    -RunConfig $package.run_config -Status success -Software @('COMSOL 6.4','SIMION 2020','Python 3.11') `
    -Outputs $outputs
  if (-not ($manifestOutput -match '^RUN_MANIFEST=PASS ')) { throw 'Final S3 manifest was not verified.' }
  Write-Output "S3_END_TO_END=PASS RUN_ID=$RunId HITS=$($result.census.detector_hit)/$($result.census.local_accelerator_exit)"
} catch {
  Complete-RfFailedRun -Python $package.python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Summary $package.summary -SummaryRole 'rf_oatof_s3_cumulative_end_to_end_summary' `
    -Reason $_.Exception.Message -Software @('COMSOL 6.4','SIMION 2020','Python 3.11')
  throw
}
