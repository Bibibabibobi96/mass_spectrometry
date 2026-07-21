param(
  [double]$PortWidthMm = 1.0,
  [ValidateRange(1,9)]
  [int]$MeshAutoLevel = 6,
  [ValidateRange(0.01,10)]
  [double]$AcceleratorHmaxMm = 1.0,
  [ValidateSet('rf-oa','oa-only-control')]
  [string]$JointScope = 'rf-oa',
  [double]$DownstreamBufferMm = 5.0,
  [string]$ClosedControlRunId = '',
  [string]$RunId = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$jointSource = Join-Path $projectRoot 'config\rf_to_oatof_s1_joint_field.json'
$jointSourceDocument = Get-Content -LiteralPath $jointSource -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not [bool]$jointSourceDocument.permissions.field_solve_allowed) {
  throw 'S1 joint-field solve is not authorized by the candidate contract.'
}
$numerical = $jointSourceDocument.numerical_qualification
$allowedAcceleratorHmax = @(
  [double]$numerical.accelerator_routine_hmax_mm,
  [double]$numerical.accelerator_convergence_hmax_mm,
  [double]$numerical.connector_diagnostic_hmax_mm
  [double]$numerical.conditional_refinement_hmax_mm
)
if (-not ($allowedAcceleratorHmax | Where-Object { [math]::Abs($_-$AcceleratorHmaxMm) -le 1e-12 })) {
  throw "AcceleratorHmaxMm must match a frozen S1 value: $($allowedAcceleratorHmax -join ', ')"
}
$allowedBuffers = @($jointSourceDocument.local_domain.oatof_downstream_buffer_diagnostic_mm | ForEach-Object { [double]$_ })
if (-not ($allowedBuffers | Where-Object { [math]::Abs($_-$DownstreamBufferMm) -le 1e-12 })) {
  throw "DownstreamBufferMm must match a frozen S1 value: $($allowedBuffers -join ', ')"
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $widthLabel = if ([math]::Abs($PortWidthMm) -lt 1e-12) { 'closed' } else { 'w' + ([string]$PortWidthMm).Replace('.','p') }
  $detail = @($widthLabel)
  if ($JointScope -eq 'oa-only-control') { $detail += 'oa-only' }
  if ($MeshAutoLevel -ne 6) { $detail += "mesh${MeshAutoLevel}" }
  if ([math]::Abs($AcceleratorHmaxMm-1.0) -gt 1e-12) { $detail += ('h' + ([string]$AcceleratorHmaxMm).Replace('.','p')) }
  if ([math]::Abs($DownstreamBufferMm-5.0) -gt 1e-12) { $detail += ('buf' + ([string]$DownstreamBufferMm).Replace('.','p')) }
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + "__analysis__comsol__rf-oatof-s1-joint-field__" + ($detail -join '-')
}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
$runDir = Join-Path $artifactRoot "runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Run already exists: $runDir" }
$inputDir = Join-Path $runDir 'inputs'; $resultDir = Join-Path $runDir 'results'; $logDir = Join-Path $runDir 'logs'
New-Item -ItemType Directory -Force -Path $inputDir,$resultDir,$logDir | Out-Null

$task = Join-Path $inputDir 'build_s1_joint_field_candidate.m'
$analysis = Join-Path $inputDir 'analyze_s1_joint_field.py'
$uniformity = Join-Path $inputDir 'analyze_accelerator_transverse_field_uniformity.py'
$oaBuilder = Join-Path $inputDir 'oatof_build_accelerator_geometry.m'
$joint = Join-Path $inputDir 'rf_to_oatof_s1_joint_field.json'
$interface = Join-Path $inputDir 'rf_to_oatof_interface_candidate.json'
$rfResolved = Join-Path $inputDir 'rf_resolved_geometry.json'
$oaBaseline = Join-Path $inputDir 'oatof_baseline.json'
$oaFormalMode = Join-Path $inputDir 'oatof_formal_mode.json'
$runner = Join-Path $inputDir 'run_s1_joint_field_candidate.ps1.txt'
Copy-Item $PSCommandPath $runner
Copy-Item (Join-Path $PSScriptRoot 'build_s1_joint_field_candidate.m') $task
Copy-Item (Join-Path $projectRoot 'analysis\analyze_s1_joint_field.py') $analysis
Copy-Item (Join-Path $repoRoot 'projects\oa_tof\analysis\analyze_accelerator_transverse_field_uniformity.py') $uniformity
Copy-Item (Join-Path $repoRoot 'projects\oa_tof\comsol\oatof_build_accelerator_geometry.m') $oaBuilder
Copy-Item $jointSource $joint
Copy-Item (Join-Path $projectRoot 'config\rf_to_oatof_interface_candidate.json') $interface
Copy-Item (Join-Path $projectRoot 'config\resolved_geometry.json') $rfResolved
Copy-Item (Join-Path $repoRoot 'projects\oa_tof\config\baseline.json') $oaBaseline
Copy-Item (Join-Path $repoRoot 'projects\oa_tof\config\modes\formal.json') $oaFormalMode
$referenceRole = 'formal_closed'
$closedReference = Join-Path $workspaceRoot 'artifacts\projects\oa_tof\runs\20260721_093712__analysis__comsol__accelerator-transverse-field__grid\results\accelerator_transverse_field_samples.csv'
if ([math]::Abs($PortWidthMm) -gt 1e-12) {
  if ([string]::IsNullOrWhiteSpace($ClosedControlRunId)) { throw 'Opened S1 cases require a matched ClosedControlRunId.' }
  $closedRun = Join-Path $artifactRoot "runs\$ClosedControlRunId"
  $closedConfig = Get-Content -LiteralPath (Join-Path $closedRun 'run_config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($closedConfig.parameters.geometry_state -ne 'closed_local_domain_control' -or
      $closedConfig.parameters.joint_scope -ne $JointScope -or
      [int]$closedConfig.parameters.mesh_auto_level -ne $MeshAutoLevel -or
      [math]::Abs([double]$closedConfig.parameters.accelerator_hmax_mm-$AcceleratorHmaxMm) -gt 1e-12 -or
      [math]::Abs([double]$closedConfig.parameters.downstream_buffer_after_grid2_mm-$DownstreamBufferMm) -gt 1e-12 -or
      [bool]$closedConfig.parameters.external_vacuum_included) {
    throw 'ClosedControlRunId does not match the opened-case scope, mesh, buffer and interior-vacuum contract.'
  }
  $closedReference = Join-Path $closedRun 'results\s1_joint_field_samples.csv'
  $referenceRole = 'matched_local_closed'
}
if (-not (Test-Path -LiteralPath $closedReference -PathType Leaf)) { throw 'S1 closed-reference field sample is missing.' }
$fieldCsv = Join-Path $resultDir 's1_joint_field_samples.csv'
$report = Join-Path $logDir 'comsol_joint_field.txt'
$summary = Join-Path $runDir 'summary.json'
$runConfig = Join-Path $runDir 'run_config.json'
$manifestWriter = Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
[ordered]@{
  schema_version=1;run_id=$RunId;project='rf_quadrupole_collision_cooling';mode='rf_to_oatof_s1_local_joint_field'
  project_root=$repoRoot
  inputs=[ordered]@{task=$task;analysis=$analysis;uniformity_analysis=$uniformity;oa_accelerator_builder=$oaBuilder;joint_contract=$joint;interface_contract=$interface;rf_resolved=$rfResolved;oa_baseline=$oaBaseline;oa_formal_mode=$oaFormalMode;closed_reference=$closedReference;runner=$runner}
  parameters=[ordered]@{geometry_state=if([math]::Abs($PortWidthMm) -lt 1e-12){'closed_local_domain_control'}else{'opened_port'};joint_scope=$JointScope;port_full_width_y_mm=$PortWidthMm;port_full_height_z_mm=0.9;downstream_buffer_after_grid2_mm=$DownstreamBufferMm;external_vacuum_included=$false;mesh_auto_level=$MeshAutoLevel;accelerator_hmax_mm=$AcceleratorHmaxMm;release_volume_hmax_mm=0.1;solver_rerun=$true;particle_tracking=$false;model_saved=$false}
  formal_gate_passed=$false
} | ConvertTo-Json -Depth 6 | Set-Content $runConfig -Encoding UTF8
[ordered]@{schema_version=1;role='rf_to_oatof_s1_joint_field_summary';status='interrupted';reason='Run package initialized; final status not yet recorded.'} | ConvertTo-Json | Set-Content $summary -Encoding UTF8
& $python $manifestWriter --run-config $runConfig --status interrupted --software 'COMSOL 6.4' --software 'MATLAB R2025b' --software 'Python 3.11'
if ($LASTEXITCODE -ne 0) { throw 'Initial manifest failed.' }

$names = @('RF_OATOF_S1_FIELD_CSV','RF_OATOF_S1_CONTRACT','RF_OATOF_INTERFACE_CONTRACT','RF_OATOF_RF_RESOLVED','RF_OATOF_OA_BASELINE','RF_OATOF_PORT_WIDTH_MM','RF_OATOF_DOWNSTREAM_BUFFER_MM','RF_OATOF_MESH_AUTO_LEVEL','RF_OATOF_ACCELERATOR_HMAX_MM','RF_OATOF_JOINT_SCOPE','RF_OATOF_OA_COMSOL_DIR')
$old = @{}; foreach($name in $names){$old[$name]=[Environment]::GetEnvironmentVariable($name)}
try {
  try {
    $env:RF_OATOF_S1_FIELD_CSV=$fieldCsv; $env:RF_OATOF_S1_CONTRACT=$joint; $env:RF_OATOF_INTERFACE_CONTRACT=$interface
    $env:RF_OATOF_RF_RESOLVED=$rfResolved; $env:RF_OATOF_OA_BASELINE=$oaBaseline; $env:RF_OATOF_PORT_WIDTH_MM=[string]$PortWidthMm
    $env:RF_OATOF_MESH_AUTO_LEVEL=[string]$MeshAutoLevel
    $env:RF_OATOF_ACCELERATOR_HMAX_MM=[string]$AcceleratorHmaxMm
    $env:RF_OATOF_JOINT_SCOPE=$JointScope
    $env:RF_OATOF_DOWNSTREAM_BUFFER_MM=[string]$DownstreamBufferMm
    $env:RF_OATOF_OA_COMSOL_DIR=$inputDir
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') -TaskScript $task -ReportPath $report
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL S1 joint-field task failed.' }
  } finally {
    foreach($name in $names){[Environment]::SetEnvironmentVariable($name,$old[$name])}
  }
  & $python $analysis --candidate $fieldCsv --closed-reference $closedReference --joint-contract $joint --interface-contract $interface --rf-resolved $rfResolved --reference-role $referenceRole --output-dir $resultDir
  if ($LASTEXITCODE -ne 0) { throw 'S1 joint-field analysis failed.' }
} catch {
  [ordered]@{schema_version=1;role='rf_to_oatof_s1_joint_field_summary';status='failed';reason=$_.Exception.Message} | ConvertTo-Json | Set-Content $summary -Encoding UTF8
  & $python $manifestWriter --run-config $runConfig --status failed --software 'COMSOL 6.4' --software 'MATLAB R2025b' --software 'Python 3.11'
  throw
}
[ordered]@{schema_version=1;role='rf_to_oatof_s1_joint_field_summary';status='success';result='results/s1_joint_field_metrics.json';physical_link=$false;particle_tracking=$false} | ConvertTo-Json | Set-Content $summary -Encoding UTF8
$outputs=@($fieldCsv,(Join-Path $resultDir 's1_joint_field_uniformity_curve.csv'),(Join-Path $resultDir 's1_joint_field_metrics.json'),$report,$summary)
$injectionFigure=Join-Path $resultDir 's1_injection_axis_field.png'; if(Test-Path -LiteralPath $injectionFigure){$outputs+=$injectionFigure}
$args=@($manifestWriter,'--run-config',$runConfig,'--status','success','--software','COMSOL 6.4','--software','MATLAB R2025b','--software','Python 3.11')
foreach($output in $outputs){$args+=@('--output',$output)}
& $python @args
if ($LASTEXITCODE -ne 0) { throw 'Final manifest failed.' }
Write-Output "STATUS=PASS RUN_ID=$RunId"
