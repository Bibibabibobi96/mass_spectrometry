param(
  [ValidateSet(19.776,26.368)]
  [double]$ShieldInnerRadiusMm = 19.776,
  [ValidateSet(0.25,0.5)]
  [double]$MeshHmaxMm = 0.5,
  [ValidateSet(2,3,4,5,6)]
  [int]$GlobalMeshAutoLevel = 6,
  [switch]$ParticleDiagnostic,
  [string]$ParticleTablePath = '',
  [string]$RunId = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$contractSource = Join-Path $projectRoot 'config\rf_continuous_grounded_shield_candidate.json'
& $python (Join-Path $projectRoot 'analysis\validate_rf_continuous_shield.py')
if ($LASTEXITCODE -ne 0) { throw 'RF continuous shield contract failed.' }
$contractDocument = Get-Content -LiteralPath $contractSource -Raw -Encoding UTF8 | ConvertFrom-Json
$screen = $contractDocument.three_dimensional_fringe_field_screen
$allowedRadii = @($screen.inner_radius_mm | ForEach-Object { [double]$_ })
$allowedHmax = @($screen.local_maximum_element_size_mm | ForEach-Object { [double]$_ })
$allowedGlobalLevels = @($screen.global_mesh_auto_level_particle_stability_sequence | ForEach-Object { [int]$_ })
if (-not ($allowedRadii | Where-Object { [math]::Abs($_-$ShieldInnerRadiusMm) -le 1e-12 })) { throw 'ShieldInnerRadiusMm is outside the retained 3D candidates.' }
if (-not ($allowedHmax | Where-Object { [math]::Abs($_-$MeshHmaxMm) -le 1e-12 })) { throw 'MeshHmaxMm is outside the frozen 3D sequence.' }
if ($GlobalMeshAutoLevel -notin $allowedGlobalLevels) { throw 'GlobalMeshAutoLevel is outside the frozen sequence.' }
if ($ParticleDiagnostic -and [math]::Abs($ShieldInnerRadiusMm-19.776) -gt 1e-12) { throw 'N=100 diagnostic is currently authorized only for R=19.776 mm.' }
if ($ParticleDiagnostic -and $GlobalMeshAutoLevel -eq 2) { throw 'Auto 2 is currently authorized for field-only diagnosis, not particle tracking.' }
$sourceMetadataPath = Join-Path $artifactRoot 'archive\20260719_212436__migration-snapshot__repo__pre-v2-layout\legacy-layout\runs\interface_sources\official_100amu_n100_20260718\particle_source_metadata.json'
if ($ParticleDiagnostic) {
  if ([string]::IsNullOrWhiteSpace($ParticleTablePath)) { $ParticleTablePath = Join-Path (Split-Path -Parent $sourceMetadataPath) 'particles.ion' }
  $ParticleTablePath = [IO.Path]::GetFullPath($ParticleTablePath)
  foreach ($sourcePath in @($ParticleTablePath,$sourceMetadataPath)) { if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) { throw "Frozen N=100 source evidence is missing: $sourcePath" } }
  $actualHash = (Get-FileHash -LiteralPath $ParticleTablePath -Algorithm SHA256).Hash
  if ($actualHash -ne $contractDocument.n100_transport_screen.source_particle_table_sha256) { throw 'Frozen N=100 particle table hash mismatch.' }
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $radiusLabel = ([string]$ShieldInnerRadiusMm).Replace('.','p')
  $meshLabel = ([string]$MeshHmaxMm).Replace('.','p')
  $purpose = if ($ParticleDiagnostic) { 'rf-continuous-shield-n100' } else { 'rf-continuous-shield-3d' }
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + "__analysis__comsol__${purpose}__r${radiusLabel}-a${GlobalMeshAutoLevel}-h${meshLabel}"
}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
$runDir = Join-Path $artifactRoot "runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Run already exists: $runDir" }
$inputDir = Join-Path $runDir 'inputs'; $resultDir = Join-Path $runDir 'results'; $logDir = Join-Path $runDir 'logs'
New-Item -ItemType Directory -Force -Path $inputDir,$resultDir,$logDir | Out-Null
$task = Join-Path $inputDir 'build_rf_continuous_shield_3d.m'
$analysis = Join-Path $inputDir 'analyze_rf_continuous_shield_3d.py'
$contract = Join-Path $inputDir 'rf_continuous_grounded_shield_candidate.json'
$resolved = Join-Path $inputDir 'rf_resolved_geometry.json'
$runner = Join-Path $inputDir 'run_rf_continuous_shield_3d.ps1.txt'
Copy-Item $PSCommandPath $runner
Copy-Item (Join-Path $PSScriptRoot 'build_rf_continuous_shield_3d.m') $task
Copy-Item (Join-Path $projectRoot 'analysis\analyze_rf_continuous_shield_3d.py') $analysis
Copy-Item $contractSource $contract
Copy-Item (Join-Path $projectRoot 'config\resolved_geometry.json') $resolved
$particleTable = ''; $sourceMetadata = ''
if ($ParticleDiagnostic) {
  $particleTable = Join-Path $inputDir 'particles.ion'; $sourceMetadata = Join-Path $inputDir 'particle_source_metadata.json'
  Copy-Item $ParticleTablePath $particleTable; Copy-Item $sourceMetadataPath $sourceMetadata
}
$fieldCsv = Join-Path $resultDir 'rf_continuous_shield_3d_samples.csv'
$particleEventsCsv = Join-Path $resultDir 'rf_continuous_shield_n100_events.csv'
$particleSummaryJson = Join-Path $resultDir 'rf_continuous_shield_n100_metrics.json'
$particleRuntimeDir = Join-Path $runDir 'runtime\particle_release_files'
$report = Join-Path $logDir 'comsol_rf_continuous_shield_3d.txt'
$summary = Join-Path $runDir 'summary.json'; $runConfig = Join-Path $runDir 'run_config.json'
$manifestWriter = Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
$inputContract=[ordered]@{task=$task;analysis=$analysis;shield_contract=$contract;rf_resolved=$resolved;runner=$runner}
if($ParticleDiagnostic){$inputContract.particle_table=$particleTable;$inputContract.particle_source_metadata=$sourceMetadata}
$runMode=if($ParticleDiagnostic){'rf_continuous_grounded_shield_n100_mesh_sensitivity'}else{'rf_continuous_grounded_shield_3d_fringe_field_screen'}
$particleCount=if($ParticleDiagnostic){100}else{0}
[ordered]@{
  schema_version=1;run_id=$RunId;project='rf_quadrupole_collision_cooling';mode=$runMode;project_root=$repoRoot
  inputs=$inputContract
  parameters=[ordered]@{shield_inner_radius_mm=$ShieldInnerRadiusMm;local_mesh_hmax_mm=$MeshHmaxMm;global_mesh_auto_level=$GlobalMeshAutoLevel;particle_tracking=[bool]$ParticleDiagnostic;particle_count=$particleCount;model_saved=$false;external_vacuum=$false}
  formal_gate_passed=$false
} | ConvertTo-Json -Depth 6 | Set-Content $runConfig -Encoding UTF8
[ordered]@{schema_version=1;role='rf_continuous_shield_3d_summary';status='interrupted';reason='Run package initialized; final status not yet recorded.'} | ConvertTo-Json | Set-Content $summary -Encoding UTF8
& $python $manifestWriter --run-config $runConfig --status interrupted --software 'COMSOL 6.4' --software 'MATLAB R2025b' --software 'Python 3.11'
if ($LASTEXITCODE -ne 0) { throw 'Initial manifest failed.' }
$names=@('RF_SHIELD_3D_FIELD_CSV','RF_SHIELD_CONTRACT','RF_SHIELD_RF_RESOLVED','RF_SHIELD_INNER_RADIUS_MM','RF_SHIELD_MESH_HMAX_MM','RF_SHIELD_GLOBAL_MESH_AUTO_LEVEL','RF_SHIELD_PARTICLE_TABLE','RF_SHIELD_PARTICLE_EVENTS_CSV','RF_SHIELD_PARTICLE_SUMMARY_JSON','RF_SHIELD_PARTICLE_RUNTIME_DIR')
$old=@{}; foreach($name in $names){$old[$name]=[Environment]::GetEnvironmentVariable($name)}
try {
  try {
    $env:RF_SHIELD_3D_FIELD_CSV=$fieldCsv; $env:RF_SHIELD_CONTRACT=$contract; $env:RF_SHIELD_RF_RESOLVED=$resolved
    $env:RF_SHIELD_INNER_RADIUS_MM=[string]$ShieldInnerRadiusMm; $env:RF_SHIELD_MESH_HMAX_MM=[string]$MeshHmaxMm
    $env:RF_SHIELD_GLOBAL_MESH_AUTO_LEVEL=[string]$GlobalMeshAutoLevel
    if($ParticleDiagnostic){$env:RF_SHIELD_PARTICLE_TABLE=$particleTable;$env:RF_SHIELD_PARTICLE_EVENTS_CSV=$particleEventsCsv;$env:RF_SHIELD_PARTICLE_SUMMARY_JSON=$particleSummaryJson;$env:RF_SHIELD_PARTICLE_RUNTIME_DIR=$particleRuntimeDir}else{$env:RF_SHIELD_PARTICLE_TABLE=''}
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') -TaskScript $task -ReportPath $report
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL RF shield 3D task failed.' }
  } finally {
    foreach($name in $names){[Environment]::SetEnvironmentVariable($name,$old[$name])}
  }
  & $python $analysis --input $fieldCsv --output-dir $resultDir
  if ($LASTEXITCODE -ne 0) { throw 'RF shield 3D analysis failed.' }
} catch {
  [ordered]@{schema_version=1;role='rf_continuous_shield_3d_summary';status='failed';reason=$_.Exception.Message} | ConvertTo-Json | Set-Content $summary -Encoding UTF8
  & $python $manifestWriter --run-config $runConfig --status failed --software 'COMSOL 6.4' --software 'MATLAB R2025b' --software 'Python 3.11'
  throw
}
[ordered]@{schema_version=1;role='rf_continuous_shield_3d_summary';status='success';result='results/rf_continuous_shield_3d_metrics.json';physical_shield_selected=$false;particle_tracking=[bool]$ParticleDiagnostic;n100_diagnostic_completed=[bool]$ParticleDiagnostic;selection_allowed=$false} | ConvertTo-Json | Set-Content $summary -Encoding UTF8
$outputs=@($fieldCsv,(Join-Path $resultDir 'rf_continuous_shield_3d_harmonics.csv'),(Join-Path $resultDir 'rf_continuous_shield_3d_metrics.json'),$report,$summary)
if($ParticleDiagnostic){$outputs+=@($particleEventsCsv,$particleSummaryJson)}
$args=@($manifestWriter,'--run-config',$runConfig,'--status','success','--software','COMSOL 6.4','--software','MATLAB R2025b','--software','Python 3.11')
foreach($output in $outputs){$args+=@('--output',$output)}
& $python @args
if ($LASTEXITCODE -ne 0) { throw 'Final manifest failed.' }
Write-Output "STATUS=PASS RUN_ID=$RunId SHIELD_SELECTED=false PARTICLE_DIAGNOSTIC=$([bool]$ParticleDiagnostic)"
