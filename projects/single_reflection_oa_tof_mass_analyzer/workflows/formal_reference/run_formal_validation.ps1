param(
  [ValidateSet('Validate','Publish','Verify')][string]$Phase = 'Validate',
  [string]$CandidateRunRoot,
  [string]$PromotionRequest,
  [string]$RunId = ((Get-Date -Format 'yyyyMMdd_HHmmss') + '__sim__cross__formal-vnext-zero-change__n1000'),
  [int]$BootstrapResamples = 5000,
  [int]$BootstrapSeed = 20260729,
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\single_reflection_oa_tof_mass_analyzer'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'

if ($Phase -eq 'Publish') {
  if ([string]::IsNullOrWhiteSpace($PromotionRequest)) {
    throw 'Formal Publish requires -PromotionRequest.'
  }
  & $python (Join-Path $projectRoot 'analysis\publish_formal_release.py') `
    --request ([IO.Path]::GetFullPath($PromotionRequest)) --artifact-root $artifactRoot
  if ($LASTEXITCODE -ne 0) { throw 'Formal release publication failed.' }
  & $PSCommandPath -Phase Verify -SimionExe $SimionExe
  if ($LASTEXITCODE -ne 0) { throw 'Published Formal release did not verify.' }
  return
}
if ($Phase -eq 'Verify') {
  . (Join-Path $projectRoot 'oatof_lifecycle_preflight.ps1')
  Assert-OaTofFormalAssetsReadable -ProjectRoot $projectRoot
  & $python (Join-Path $repoRoot 'common\contracts\verify_artifact_layout.py') `
    (Join-Path $workspaceRoot 'artifacts\projects') --formal-only --repository-root $repoRoot
  if ($LASTEXITCODE -ne 0) { throw 'Formal asset-manifest structure gate failed.' }
  & (Join-Path $projectRoot 'workflows\formal_reference\verify_geometry_contract.ps1') `
    -SimionExe $SimionExe -PythonExe $python
  if ($LASTEXITCODE -ne 0) { throw 'Formal geometry/runtime/CAD gate failed.' }
  & (Join-Path $projectRoot 'analysis\verify_reference_analysis.ps1') -PythonExe $python
  if ($LASTEXITCODE -ne 0) { throw 'Formal reference-analysis gate failed.' }
  'FORMAL_RELEASE_VERIFY=PASS'
  return
}
if ([string]::IsNullOrWhiteSpace($CandidateRunRoot)) {
  throw 'Formal Validate requires -CandidateRunRoot.'
}
$candidateRoot = (Resolve-Path -LiteralPath $CandidateRunRoot).Path
$runDir = Join-Path $artifactRoot "runs\$RunId"
$inputDir = Join-Path $runDir 'inputs'
$resultDir = Join-Path $runDir 'results'
$logDir = Join-Path $runDir 'logs'
if (Test-Path -LiteralPath $runDir) { throw "Formal vNext run already exists: $RunId" }
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
New-Item -ItemType Directory -Path $runDir,$inputDir,$resultDir,$logDir | Out-Null
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$runRecordComplete = $false
Initialize-RunRecord -RunDir $runDir -RunId $RunId -Project 'single_reflection_oa_tof_mass_analyzer' `
  -Mode 'formal_vnext_zero_change_validation' -ProjectRoot $projectRoot `
  -RepoRoot $repoRoot -Python $python -ProvisionalSummaryRole 'oa_tof_provisional_run_summary' `
  -TerminalSummaryRole 'oa_tof_terminal_run_summary'
trap {
  if (-not $runRecordComplete) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot `
      -RunConfig (Join-Path $runDir 'run_config.json') -Summary (Join-Path $runDir 'summary.json') `
      -SummaryRole 'oa_tof_terminal_run_summary' -Reason $_.Exception.Message `
      -Software @('COMSOL R2025b','SIMION 2020')
  }
  exit 1
}

$candidateSimionSource = Join-Path $candidateRoot 'simion'
$candidateIonSource = Join-Path $candidateSimionSource 'oatof_comsol_524amu_gaussian_N1000.ion'
$candidateIobSource = Join-Path $candidateSimionSource 'oatof_ideal_grounded.iob'
$candidateManifestSource = Join-Path $candidateRoot 'run_manifest.json'
$candidateSummarySource = Join-Path $candidateRoot 'summary.json'
$candidateConfigSource = Join-Path $candidateRoot 'run_config.json'
$candidateDiffSource = Join-Path $candidateRoot 'inputs\candidate_diff.json'
foreach ($path in @(
    $candidateIonSource,$candidateIobSource,$candidateManifestSource,
    $candidateSummarySource,$candidateConfigSource,$candidateDiffSource,$python,$SimionExe
  )) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required input is absent: $path" }
}
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
  $candidateManifestSource --require-status success --require-local-run-config `
  --require-project single_reflection_oa_tof_mass_analyzer --require-mode design_candidate
if ($LASTEXITCODE -ne 0) { throw 'Candidate source manifest verification failed.' }

$candidateManifest = Copy-VerifiedRunInput -Source $candidateManifestSource `
  -Destination (Join-Path $inputDir 'candidate_run_manifest.json')
$candidateSummaryPath = Copy-VerifiedRunInput -Source $candidateSummarySource `
  -Destination (Join-Path $inputDir 'candidate_run_summary.json')
$candidateConfigPath = Copy-VerifiedRunInput -Source $candidateConfigSource `
  -Destination (Join-Path $inputDir 'candidate_run_config.json')
$candidateDiffPath = Copy-VerifiedRunInput -Source $candidateDiffSource `
  -Destination (Join-Path $inputDir 'candidate_diff.json')
$candidateSummary = Get-Content -LiteralPath $candidateSummaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
$candidateConfig = Get-Content -LiteralPath $candidateConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
$candidateDiff = Get-Content -LiteralPath $candidateDiffPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($candidateSummary.status -ne 'success' -or
    $candidateSummary.candidate_decision -ne 'candidate_accepted_not_promoted') {
  throw 'Formal vNext requires a successful isolated Candidate.'
}
if (-not $candidateDiff.zero_change_reference_reproduction -or
    @($candidateDiff.changed_variables).Count -ne 0 -or
    @($candidateDiff.derived_changes).Count -ne 0) {
  throw 'Formal vNext bootstrap accepts only a zero-physics-change Candidate.'
}

$comsolStage = @($candidateSummary.stages | Where-Object { $_.stage_id -eq 'comsol_candidate' })
if ($comsolStage.Count -ne 1 -or $comsolStage[0].status -ne 'success') {
  throw 'Candidate summary does not bind exactly one successful COMSOL stage.'
}
$candidateMphSource = [IO.Path]::GetFullPath([string]$comsolStage[0].evidence.model)
if (-not (Test-Path -LiteralPath $candidateMphSource -PathType Leaf)) {
  throw "Candidate COMSOL evidence is absent: $candidateMphSource"
}
$reusePath = $null
if ($comsolStage[0].execution -eq 'reused') {
  $reuseSource = [IO.Path]::GetFullPath([string]$candidateConfig.inputs.stage_reuse_provenance)
  $reusePath = Copy-VerifiedRunInput -Source $reuseSource `
    -Destination (Join-Path $inputDir 'candidate_stage_reuse_provenance.json')
  $reuse = Get-Content -LiteralPath $reusePath -Raw -Encoding UTF8 | ConvertFrom-Json
  $reusedComsol = @($reuse.reused_stages | Where-Object { $_.stage_id -eq 'comsol_candidate' })
  if ($reusedComsol.Count -ne 1 -or
      (Get-FileHash -LiteralPath $candidateMphSource -Algorithm SHA256).Hash -ne
        [string]$reusedComsol[0].outputs.model.sha256) {
    throw 'Reused Candidate COMSOL model differs from its frozen reuse provenance.'
  }
}
elseif (-not $candidateMphSource.StartsWith(
    $candidateRoot + [IO.Path]::DirectorySeparatorChar,
    [StringComparison]::OrdinalIgnoreCase
  )) {
  throw 'Executed Candidate COMSOL model must remain inside its source run.'
}

$candidateMph = Copy-VerifiedRunInput -Source $candidateMphSource `
  -Destination (Join-Path $inputDir 'comsol\single_reflection_oa_tof_mass_analyzer__candidate.mph')
$candidateSimion = Join-Path $inputDir 'simion'
$simionInputs = [ordered]@{}
$simionInputIndex = 0
foreach ($source in Get-ChildItem -LiteralPath $candidateSimionSource -Recurse -File | Sort-Object FullName) {
  $relative = [IO.Path]::GetRelativePath($candidateSimionSource,$source.FullName)
  $destination = Copy-VerifiedRunInput -Source $source.FullName `
    -Destination (Join-Path $candidateSimion $relative)
  $simionInputIndex += 1
  $simionInputs[("candidate_simion_bundle_{0:D3}" -f $simionInputIndex)] = $destination
}
$ion = Join-Path $candidateSimion 'oatof_comsol_524amu_gaussian_N1000.ion'
$iob = Join-Path $candidateSimion 'oatof_ideal_grounded.iob'
$comsolCsv = Join-Path $resultDir 'comsol_particles.csv'
$comsolReport = Join-Path $logDir 'comsol_report.txt'
$simionLog = Join-Path $logDir 'simion_stdout.log'
$simionStderr = Join-Path $logDir 'simion_stderr.log'
$simionCsv = Join-Path $resultDir 'simion_particles.csv'
$simionSummary = Join-Path $resultDir 'simion_summary.json'
$ionCount = @(Get-Content -LiteralPath $ion | Where-Object { $_.Trim() }).Count
& $python (Join-Path $repoRoot 'common\contracts\particle_count_policy.py') --count $ionCount
if ($LASTEXITCODE -ne 0 -or $ionCount -ne 1000) {
  throw "Shared particle table is not exact N=1000: $ionCount"
}

$runConfig = Join-Path $runDir 'run_config.json'
$inputs = [ordered]@{
  candidate_run_manifest=$candidateManifest; candidate_run_summary=$candidateSummaryPath
  candidate_run_config=$candidateConfigPath; candidate_diff=$candidateDiffPath
  candidate_mph=$candidateMph; shared_ion_table=$ion; candidate_simion_iob=$iob
}
if ($null -ne $reusePath) { $inputs.candidate_stage_reuse_provenance = $reusePath }
foreach ($entry in $simionInputs.GetEnumerator()) {
  if ($entry.Value -notin @($ion,$iob)) { $inputs[$entry.Key] = $entry.Value }
}
[ordered]@{
  schema_version=1; run_id=$RunId; project='single_reflection_oa_tof_mass_analyzer'
  mode='formal_vnext_zero_change_validation'; project_root=$projectRoot
  formal_gate_passed=$false; promotion_authorized=$false
  inputs=$inputs
  input_sha256=[ordered]@{
    candidate_run_manifest=(Get-FileHash $candidateManifest -Algorithm SHA256).Hash
    candidate_diff=(Get-FileHash $candidateDiffPath -Algorithm SHA256).Hash
    candidate_mph=(Get-FileHash $candidateMph -Algorithm SHA256).Hash
    shared_ion_table=(Get-FileHash $ion -Algorithm SHA256).Hash
    candidate_simion_iob=(Get-FileHash $iob -Algorithm SHA256).Hash
  }
  parameters=[ordered]@{
    mass_amu=524; particles=1000
    particle_source_seed=[int]$candidateConfig.run_instance.particle_source_seed
    bootstrap_resamples=$BootstrapResamples; bootstrap_seed=$BootstrapSeed
  }
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $runConfig -Encoding UTF8

$oldEnvironment = @{}
$environment = @{
  OATOF_SOURCE_MODEL_PATH=$candidateMph; OATOF_ION_TABLE=$ion
  OATOF_COMSOL_OUTPUT_CSV=$comsolCsv; OATOF_RUNTIME_DIR=$resultDir; OATOF_RESULTS_DIR=$resultDir
  OATOF_ACCELERATOR_HMAX_MM='1'; OATOF_REUSE_EXISTING_FIELD='1'; OATOF_FINE_TSTEP_NS='0.2'
  OATOF_DRIFT_TSTEP_NS='50'; OATOF_SEGMENTED_OUTPUT='1'; OATOF_USE_PARTICLE_STOP_TIME='0'
}
try {
  foreach ($entry in $environment.GetEnumerator()) {
    $oldEnvironment[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key, 'Process')
    [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
  }
  & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
    -TaskScript (Join-Path $projectRoot 'comsol\run_fixed_particle_retrace.m') `
    -ReportPath $comsolReport
} finally {
  foreach ($entry in $environment.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($entry.Key,$oldEnvironment[$entry.Key],'Process')
  }
}
if (-not (Select-String -LiteralPath $comsolReport -Pattern '^DETECTED=1000/1000$' -Quiet)) {
  throw 'Formal vNext COMSOL did not detect 1000/1000 particles.'
}

$process = Start-Process -FilePath $SimionExe -WorkingDirectory $candidateSimion -WindowStyle Hidden `
  -Wait -PassThru -RedirectStandardOutput $simionLog -RedirectStandardError $simionStderr `
  -ArgumentList @('--default-num-particles','1000','--nogui','fly','--trajectory-quality','8',
    '--retain-trajectories','0','--particles',$ion,'--programs','1',
    '--adjustable','trajectory_quality=8','--adjustable','trajectory_log_enable=1',$iob)
if ($process.ExitCode -ne 0) { throw "Formal vNext SIMION fly failed: $simionStderr" }
$summary = & (Join-Path $projectRoot 'simion\workbench\analyze_ideal_field_log.ps1') `
  -Log $simionLog -IonFile $ion -Mode 'formal_vnext_candidate_assets' `
  -Distribution 'fixedN1000' -ParticleCsv $simionCsv
$summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $simionSummary -Encoding UTF8
if ([int]$summary.Hit -ne 1000 -or [int]$summary.Emitted -ne 1000) {
  throw "Formal vNext SIMION hit count is $($summary.Hit)/$($summary.Emitted)"
}

& $python -m projects.single_reflection_oa_tof_mass_analyzer.analysis.reference_analysis compare `
  $comsolCsv $simionCsv --mass 524 --output $resultDir --left-label COMSOL --right-label SIMION `
  --require-paired-particle-ids --bootstrap-resamples $BootstrapResamples --bootstrap-seed $BootstrapSeed
if ($LASTEXITCODE -ne 0) { throw 'Formal vNext unified cross-solver analysis failed.' }
$comparison = Join-Path $resultDir 'comparison_metrics.json'
$comparisonRecord = Get-Content $comparison -Raw -Encoding UTF8 | ConvertFrom-Json
if ($comparisonRecord.status -ne 'PASS') { throw 'Formal vNext comparison is not PASS.' }

$summaryPath = Join-Path $runDir 'summary.json'
[ordered]@{
  schema_version=1; role='oa_tof_formal_vnext_validation_summary'; status='success'
  scope='zero_physics_change_current_split_layer_contract'; particles=1000
  shared_particle_table_sha256=(Get-FileHash $ion -Algorithm SHA256).Hash
  comsol_detected='1000/1000'; simion_detected='1000/1000'
  comparison_metrics='results/comparison_metrics.json'
  formal_modified=$false; promotion_authorized=$false
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
$outputs = @(
  Get-ChildItem -LiteralPath $resultDir,$logDir -Recurse -File |
    Sort-Object FullName | Select-Object -ExpandProperty FullName
)
$outputs += $summaryPath
$manifestArgs = @((Join-Path $repoRoot 'common\contracts\write_run_manifest.py'),
  '--run-config',$runConfig,'--manifest',(Join-Path $runDir 'run_manifest.json'),
  '--status','success','--software','COMSOL R2025b','--software','SIMION 2020')
foreach ($output in $outputs) { $manifestArgs += @('--output',$output) }
& $python @manifestArgs
if ($LASTEXITCODE -ne 0) { throw 'Formal vNext manifest creation failed.' }
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
  (Join-Path $runDir 'run_manifest.json') --require-status success
if ($LASTEXITCODE -ne 0) { throw 'Formal vNext manifest verification failed.' }
$runRecordComplete = $true
"FORMAL_VNEXT_VALIDATION=PASS RUN_ID=$RunId"
