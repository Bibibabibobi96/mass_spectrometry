[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$ProjectRoot,
  [ValidateSet('high-order','quadrupole')]
  [string]$Adapter = 'high-order',
  [string]$FieldScreenRunId = '',
  [string]$ParticleTablePath = '',
  [string]$RunId = '',
  [double]$EntranceConnectorLengthMm = [double]::NaN,
  [double]$ExitConnectorLengthMm = [double]::NaN,
  [switch]$AxialAcceleration,
  [switch]$EndplateAcceleration
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRootPath = (Resolve-Path -LiteralPath $ProjectRoot).Path
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$project = Get-Content -LiteralPath (Join-Path $projectRootPath 'config\project.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$projectId = [string]$project.project_id
if($AxialAcceleration -and $EndplateAcceleration){throw 'Select only one acceleration mode.'}
$accelerationEnabled=$AxialAcceleration -or $EndplateAcceleration
& $python (Join-Path $repoRoot 'common\contracts\artifact_project.py') `
  --artifact-projects-root (Join-Path $workspaceRoot 'artifacts\projects') --project-id $projectId
if ($LASTEXITCODE -ne 0) { throw 'Multipole artifact project initialization failed.' }
if($Adapter -eq 'high-order'){
  if([string]::IsNullOrWhiteSpace($FieldScreenRunId)){throw 'High-order finite 3D transport requires FieldScreenRunId.'}
  & $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $FieldScreenRunId
  if ($LASTEXITCODE -ne 0) { throw "Invalid field-screen run_id: $FieldScreenRunId" }
  $sourceDir = Join-Path $workspaceRoot "artifacts\projects\$projectId\runs\$FieldScreenRunId"
  $sourceManifest = Join-Path $sourceDir 'run_manifest.json'
  $sourceDocument = Get-Content -LiteralPath $sourceManifest -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($sourceDocument.status -ne 'success' -or $sourceDocument.project -ne $projectId) {
    throw 'The finite 3D field-screen source is not a successful run for this project.'
  }
}else{
  if($projectId -ne 'rf_quadrupole_collision_cooling'){throw 'Quadrupole adapter requires the quadrupole project.'}
  if([string]::IsNullOrWhiteSpace($ParticleTablePath)){
    $ParticleTablePath=Join-Path $projectRootPath 'config\particles\official_fixed_100.ion'
  }
  $ParticleTablePath=[IO.Path]::GetFullPath($ParticleTablePath)
  if(-not(Test-Path -LiteralPath $ParticleTablePath -PathType Leaf)){throw 'Quadrupole particle table is missing.'}
  $sourceDir='';$sourceManifest='';$sourceContract='';$sourceSamples=''
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $taskLabel = $projectId.Replace('_','-') + $(if ($AxialAcceleration) {'-axial-acceleration'}elseif($EndplateAcceleration){'-endplate-acceleration'} else {'-finite-3d-interfaces'})
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + "__sim__comsol__${taskLabel}__l3-n100"
}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }

$runDir = Join-Path $workspaceRoot "artifacts\projects\$projectId\runs\$RunId"
if (Test-Path -LiteralPath $runDir) { throw "Run already exists: $runDir" }
$inputDir = Join-Path $runDir 'inputs'
$resultDir = Join-Path $runDir 'results'
$logDir = Join-Path $runDir 'logs'
$runtimeDir = Join-Path $logDir 'runtime'
New-Item -ItemType Directory -Force -Path $inputDir,$resultDir,$logDir,$runtimeDir | Out-Null
$baseline = Join-Path $inputDir 'baseline.json'
$projectBaseline=Join-Path $inputDir 'project_baseline.json'
$projectResolved=Join-Path $inputDir 'project_resolved_geometry.json'
$familyOperating = Join-Path $inputDir 'family_operating_contract.json'
$baseContract = Join-Path $inputDir 'finite_3d_transport_base.json'
$contract = Join-Path $inputDir 'finite_3d_transport.json'
$resolvedContract = Join-Path $inputDir 'finite_3d_transport_resolved.json'
$mode = Join-Path $inputDir 'finite_3d_no_collision.json'
$fieldMetrics = Join-Path $inputDir 'round_rod_field_screen_metrics.json'
$roundRodGeometry = Join-Path $inputDir 'round_rod_geometry.json'
$axialAccelerationBase = Join-Path $inputDir 'axial_acceleration_base.json'
$axialAccelerationResolvedPath = Join-Path $inputDir 'axial_acceleration_resolved.json'
$endplateAccelerationBase=Join-Path $inputDir 'endplate_acceleration_base.json'
$endplateAccelerationResolvedPath=Join-Path $inputDir 'endplate_acceleration_resolved.json'
$particleSource = Join-Path $inputDir 'particle_source.csv'
Copy-Item -LiteralPath (Join-Path $projectRootPath 'config\baseline.json') -Destination $projectBaseline
if($Adapter -eq 'high-order'){
  Copy-Item -LiteralPath $projectBaseline -Destination $baseline
  Copy-Item -LiteralPath (Join-Path $projectRootPath 'config\finite_3d_transport.json') -Destination $baseContract
  Copy-Item -LiteralPath (Join-Path $projectRootPath 'config\modes\finite_3d_no_collision.json') -Destination $mode
}else{
  Copy-Item -LiteralPath (Join-Path $projectRootPath 'config\resolved_geometry.json') -Destination $projectResolved
  Copy-Item -LiteralPath (Join-Path $projectRootPath 'config\modes\transport_no_collision.json') -Destination $mode
}
if ($AxialAcceleration) {
  Copy-Item -LiteralPath (Join-Path $projectRootPath 'config\modes\axial_acceleration_reference.json') -Destination $axialAccelerationBase
}
if($EndplateAcceleration){
  Copy-Item -LiteralPath (Join-Path $projectRootPath 'config\modes\endplate_acceleration_reference.json') -Destination $endplateAccelerationBase
}
Push-Location $repoRoot
try {
  $familyArguments=@('-m','common.multipole.resolve_family_operating_contract','--adapter',$Adapter,
    '--baseline',$projectBaseline,'--output',$familyOperating)
  if($Adapter -eq 'quadrupole'){$familyArguments+=@('--mode',$mode)}
  & $python @familyArguments
  if ($LASTEXITCODE -ne 0) { throw 'Shared multipole operating-contract resolution failed.' }
} finally { Pop-Location }
if($Adapter -eq 'high-order'){
  $resolverArguments = @('-m','common.multipole.resolve_finite_3d_contract','--baseline',$baseline,
    '--contract',$baseContract,'--effective-contract-output',$contract,'--output',$resolvedContract)
  if (-not [double]::IsNaN($EntranceConnectorLengthMm)) {$resolverArguments += @('--entrance-connector-length-mm',[string]$EntranceConnectorLengthMm)}
  if (-not [double]::IsNaN($ExitConnectorLengthMm)) {$resolverArguments += @('--exit-connector-length-mm',[string]$ExitConnectorLengthMm)}
  Push-Location $repoRoot
  try {& $python @resolverArguments;if($LASTEXITCODE-ne 0){throw 'Finite 3D interface contract validation failed.'}}
  finally{Pop-Location}
  $sourceSamples = Join-Path $sourceDir 'results\round_rod_potential_samples.csv'
  $sourceContract = Join-Path $sourceDir 'inputs\round_rod_field_screen.json'
}else{
  Push-Location $repoRoot
  try{
    $adapterArguments=@('-m','common.multipole.prepare_quadrupole_finite_3d_inputs','--resolved',$projectResolved,
      '--operating',$familyOperating,'--particles',$ParticleTablePath,'--baseline-output',$baseline,
      '--contract-output',$resolvedContract,'--field-metrics-output',$fieldMetrics,
      '--round-rod-geometry-output',$roundRodGeometry,'--particle-source-output',$particleSource)
    if(-not [double]::IsNaN($EntranceConnectorLengthMm)){$adapterArguments+=@('--entrance-connector-length-mm',[string]$EntranceConnectorLengthMm)}
    if(-not [double]::IsNaN($ExitConnectorLengthMm)){$adapterArguments+=@('--exit-connector-length-mm',[string]$ExitConnectorLengthMm)}
    & $python @adapterArguments
    if($LASTEXITCODE-ne 0){throw 'Quadrupole shared finite 3D input adaptation failed.'}
  }finally{Pop-Location}
  Copy-Item -LiteralPath $resolvedContract -Destination $baseContract
  Copy-Item -LiteralPath $resolvedContract -Destination $contract
}
$effectiveContract = Get-Content -LiteralPath $contract -Raw -Encoding UTF8 | ConvertFrom-Json
$familyOperatingDocument=Get-Content -LiteralPath $familyOperating -Raw -Encoding UTF8|ConvertFrom-Json
$screenAnalysis = Join-Path $repoRoot 'common\multipole\analyze_round_rod_screen.py'
if($Adapter -eq 'high-order'){
  '{}' | Set-Content -LiteralPath $fieldMetrics -Encoding UTF8
  '{}' | Set-Content -LiteralPath $roundRodGeometry -Encoding UTF8
}
if ($AxialAcceleration) { '{}' | Set-Content -LiteralPath $axialAccelerationResolvedPath -Encoding UTF8 }
if($EndplateAcceleration){'{}'|Set-Content -LiteralPath $endplateAccelerationResolvedPath -Encoding UTF8}
if($Adapter -eq 'high-order'){
  'particle_id,birth_time_s,x_mm,y_mm,z_mm,vx_m_s,vy_m_s,vz_m_s' | Set-Content -LiteralPath $particleSource -Encoding UTF8
}

$events = Join-Path $resultDir 'particle_events.csv'
$trajectories = Join-Path $resultDir 'trajectory_samples.csv'
$metrics = Join-Path $resultDir 'finite_3d_transport_metrics.json'
$plot = Join-Path $resultDir 'finite_3d_transport.png'
$model = Join-Path $resultDir 'finite_3d_transport.mph'
$canonicalState=Join-Path $resultDir 'particle_state.csv'
$report = Join-Path $logDir 'comsol_finite_3d_transport.txt'
$summary = Join-Path $runDir 'summary.json'
$solverSummary=Join-Path $resultDir 'solver_summary.json'
$runConfig = Join-Path $runDir 'run_config.json'
$manifestWriter = Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
$multipoleCodeDir=Join-Path $inputDir 'code\multipole'
$comsolCodeDir=Join-Path $inputDir 'code\comsol'
New-Item -ItemType Directory -Force -Path $multipoleCodeDir,$comsolCodeDir|Out-Null
$multipoleCodeFiles=@('solve_finite_3d_transport.m','configure_comsol_stationary_direct_solver.m',
  'create_comsol_grounded_connector.m')
$comsolCodeFiles=@('configure_comsol_mesh.m','add_comsol_size_feature.m','create_comsol_apertured_plate.m','create_comsol_cylinder.m',
  'create_comsol_cylindrical_shell.m','create_multipole_round_rods.m','create_multipole_segmented_round_rods.m')
foreach($name in $multipoleCodeFiles){Copy-Item -LiteralPath (Join-Path $repoRoot "common\multipole\$name") -Destination $multipoleCodeDir}
foreach($name in $comsolCodeFiles){Copy-Item -LiteralPath (Join-Path $repoRoot "common\comsol\$name") -Destination $comsolCodeDir}
$task = Join-Path $multipoleCodeDir 'solve_finite_3d_transport.m'
[ordered]@{
  schema_version = 1
  role = 'multipole_finite_3d_transport_run_config'
  run_id = $RunId
  project = $projectId
  mode = $(if ($AxialAcceleration) {'axial_acceleration_reference'}elseif($EndplateAcceleration){'endplate_acceleration_reference'}elseif($Adapter -eq 'quadrupole'){'transport_no_collision'}else{'finite_3d_no_collision'})
  project_root = $projectRootPath
  operating_point='official_100amu_2eV'
  rf_peak_v=[double]$familyOperatingDocument.voltage.rf_amplitude_V_zero_to_peak_per_group
  frequency_hz=[double]$familyOperatingDocument.voltage.frequency_Hz
  inputs = [ordered]@{
    baseline = $baseline
    family_operating_contract = $familyOperating
    mode = $mode
    finite_3d_base_contract = $baseContract
    finite_3d_contract = $contract
    finite_3d_resolved_contract = $resolvedContract
    particle_source = $particleSource
    particle_table = $(if($Adapter -eq 'quadrupole'){$ParticleTablePath}else{$null})
    field_screen_metrics = $fieldMetrics
    round_rod_geometry = $roundRodGeometry
    axial_acceleration_base = $(if ($AxialAcceleration) {$axialAccelerationBase} else {$null})
    axial_acceleration_resolved = $(if ($AxialAcceleration) {$axialAccelerationResolvedPath} else {$null})
    endplate_acceleration_base = $(if($EndplateAcceleration){$endplateAccelerationBase}else{$null})
    endplate_acceleration_resolved = $(if($EndplateAcceleration){$endplateAccelerationResolvedPath}else{$null})
    field_screen_manifest = $(if($Adapter -eq 'high-order'){$sourceManifest}else{$null})
    field_screen_contract = $(if($Adapter -eq 'high-order'){$sourceContract}else{$null})
    field_screen_samples = $(if($Adapter -eq 'high-order'){$sourceSamples}else{$null})
    comsol_task = $task
    comsol_stationary_solver = Join-Path $multipoleCodeDir 'configure_comsol_stationary_direct_solver.m'
    comsol_connector_builder = Join-Path $multipoleCodeDir 'create_comsol_grounded_connector.m'
    comsol_mesh_builder = Join-Path $comsolCodeDir 'configure_comsol_mesh.m'
    comsol_mesh_size_builder = Join-Path $comsolCodeDir 'add_comsol_size_feature.m'
    comsol_apertured_plate_builder = Join-Path $comsolCodeDir 'create_comsol_apertured_plate.m'
    comsol_cylinder_builder = Join-Path $comsolCodeDir 'create_comsol_cylinder.m'
    comsol_cylindrical_shell_builder = Join-Path $comsolCodeDir 'create_comsol_cylindrical_shell.m'
    comsol_round_rod_builder = Join-Path $comsolCodeDir 'create_multipole_round_rods.m'
    comsol_segmented_rod_builder = Join-Path $comsolCodeDir 'create_multipole_segmented_round_rods.m'
  }
  parameters = [ordered]@{
    model_level='L3'
    direct_comsol_particle_tracking=$true
    mesh_convergence=$false
    entrance_connector_length_mm=[double]$effectiveContract.geometry_mm.entrance_interface.connector_length_mm
    exit_connector_length_mm=[double]$effectiveContract.geometry_mm.exit_interface.connector_length_mm
    axial_acceleration_enabled=[bool]$AxialAcceleration
    endplate_acceleration_enabled=[bool]$EndplateAcceleration
  }
  formal_gate_passed = $false
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfig -Encoding UTF8
[ordered]@{ schema_version=1; role='multipole_finite_3d_transport_summary'; status='interrupted' } |
  ConvertTo-Json | Set-Content -LiteralPath $summary -Encoding UTF8
& $python $manifestWriter --run-config $runConfig --status interrupted --software 'COMSOL 6.4' --software 'MATLAB R2025b' --software 'Python 3.11' --output $summary
if ($LASTEXITCODE -ne 0) { throw 'Initial finite 3D run manifest failed.' }

$environmentNames = @(
  'MULTIPOLE_L3_BASELINE','MULTIPOLE_L3_FAMILY_OPERATING','MULTIPOLE_L3_CONTRACT','MULTIPOLE_L3_FIELD_METRICS','MULTIPOLE_L3_ROUND_ROD_GEOMETRY',
  'MULTIPOLE_L3_AXIAL_ACCELERATION',
  'MULTIPOLE_L3_ENDPLATE_ACCELERATION',
  'MULTIPOLE_L3_PARTICLE_SOURCE','MULTIPOLE_L3_RUNTIME_DIR','MULTIPOLE_L3_EVENTS',
  'MULTIPOLE_L3_TRAJECTORIES','MULTIPOLE_L3_METRICS','MULTIPOLE_L3_PLOT','MULTIPOLE_L3_MODEL'
  'MULTIPOLE_L3_CANONICAL_STATE'
)
$oldEnvironment = @{}
foreach ($name in $environmentNames) { $oldEnvironment[$name] = [Environment]::GetEnvironmentVariable($name) }
try {
  try {
    if($Adapter -eq 'high-order'){
      & $python $screenAnalysis --samples $sourceSamples --contract $sourceContract --output $fieldMetrics
      if ($LASTEXITCODE -ne 0) { throw 'Could not freeze the selected L2 field-screen geometry.' }
    }
    $baselineDocument=Get-Content -LiteralPath $baseline -Raw -Encoding UTF8|ConvertFrom-Json
    Push-Location $repoRoot
    try {
      if($Adapter -eq 'high-order'){
        & $python -m common.multipole.round_rod_geometry `
          --baseline $baseline --finite-3d $resolvedContract --field-metrics $fieldMetrics --output $roundRodGeometry
        if ($LASTEXITCODE -ne 0) { throw 'Could not freeze the shared round-rod geometry.' }
      }
      if ($AxialAcceleration) {
        & $python -m common.multipole.axial_acceleration --contract $axialAccelerationBase `
          --rod-geometry $roundRodGeometry --source-energy-ev ([double]$baselineDocument.particle_source.kinetic_energy_eV) `
          --charge-state ([int]$baselineDocument.particle_source.charge_state) --output $axialAccelerationResolvedPath
        if ($LASTEXITCODE -ne 0) { throw 'Could not resolve the shared axial-acceleration contract.' }
      }
      if($EndplateAcceleration){
        & $python -m common.multipole.endplate_acceleration --contract $endplateAccelerationBase `
          --source-energy-ev ([double]$baselineDocument.particle_source.kinetic_energy_eV) `
          --charge-state ([int]$baselineDocument.particle_source.charge_state) --output $endplateAccelerationResolvedPath
        if($LASTEXITCODE-ne 0){throw 'Could not resolve the shared endplate-acceleration contract.'}
      }
    } finally { Pop-Location }
    if($Adapter -eq 'high-order'){
      $l3Document = Get-Content -LiteralPath $resolvedContract -Raw -Encoding UTF8 | ConvertFrom-Json
      Push-Location $repoRoot
      try {
        & $python -m common.multipole.generate_particle_source `
          --baseline $baseline --release-z-mm ([double]$l3Document.derived_geometry_mm.source_z) --output $particleSource
        if ($LASTEXITCODE -ne 0) { throw 'Could not freeze the finite 3D particle source.' }
      } finally { Pop-Location }
    }
    $env:MULTIPOLE_L3_BASELINE = $baseline
    $env:MULTIPOLE_L3_FAMILY_OPERATING = $familyOperating
    $env:MULTIPOLE_L3_CONTRACT = $resolvedContract
    $env:MULTIPOLE_L3_FIELD_METRICS = $fieldMetrics
    $env:MULTIPOLE_L3_ROUND_ROD_GEOMETRY = $roundRodGeometry
    $env:MULTIPOLE_L3_AXIAL_ACCELERATION = $(if ($AxialAcceleration) {$axialAccelerationResolvedPath} else {''})
    $env:MULTIPOLE_L3_ENDPLATE_ACCELERATION = $(if($EndplateAcceleration){$endplateAccelerationResolvedPath}else{''})
    $env:MULTIPOLE_L3_PARTICLE_SOURCE = $particleSource
    $env:MULTIPOLE_L3_RUNTIME_DIR = $runtimeDir
    $env:MULTIPOLE_L3_EVENTS = $events
    $env:MULTIPOLE_L3_TRAJECTORIES = $trajectories
    $env:MULTIPOLE_L3_METRICS = $metrics
    $env:MULTIPOLE_L3_PLOT = $plot
    $env:MULTIPOLE_L3_MODEL = $model
    $env:MULTIPOLE_L3_CANONICAL_STATE = $(if($Adapter -eq 'quadrupole'){$canonicalState}else{''})
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') -TaskScript $task -ReportPath $report
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL finite 3D multipole transport failed.' }
    $result = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 | ConvertFrom-Json
    $primaryCase = $result.cases.PSObject.Properties[[string]$result.primary_case_id].Value
    $controlCase = $result.cases.PSObject.Properties[[string]$result.control_case_id].Value
    [ordered]@{
      schema_version = 1
      role = 'multipole_finite_3d_transport_summary'
      status = 'success'
      project_id = $projectId
      source_field_screen_run_id = $FieldScreenRunId
      selected_rod_radius_ratio = $result.selected_geometry.rod_radius_ratio
      entrance_connector_length_mm = [double]$effectiveContract.geometry_mm.entrance_interface.connector_length_mm
      exit_connector_length_mm = [double]$effectiveContract.geometry_mm.exit_interface.connector_length_mm
      rf_transmission = $primaryCase.transmission_fraction
      control_transmission = $controlCase.transmission_fraction
      mean_output_energy_eV = $primaryCase.mean_output_energy_eV
      model_level = 'L3'
      formal_gate_passed = $false
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $summary -Encoding UTF8
    if($Adapter -eq 'quadrupole'){
      [ordered]@{schema_version=1;role='rf_quadrupole_transport_solver_summary';solver='COMSOL';
        mode=$(if($AxialAcceleration){'axial_acceleration_reference'}elseif($EndplateAcceleration){'endplate_acceleration_reference'}else{'transport_no_collision'});
        particles=$primaryCase.particles;hits=$primaryCase.transmitted;transmission=$primaryCase.transmission_fraction;
        mean_output_energy_eV=$primaryCase.mean_output_energy_eV;rf_peak_V=[double]$familyOperatingDocument.voltage.rf_amplitude_V_zero_to_peak_per_group;
        frequency_Hz=[double]$familyOperatingDocument.voltage.frequency_Hz}|
        ConvertTo-Json -Depth 4|Set-Content -LiteralPath $solverSummary -Encoding UTF8
    }
    $outputs = @($events,$trajectories,$metrics,$plot,$model,$report,$summary)
    if($Adapter -eq 'quadrupole'){$outputs+=@($canonicalState,$solverSummary)}
    $manifestArguments = @($manifestWriter,'--run-config',$runConfig,'--status','success',
      '--software','COMSOL 6.4','--software','MATLAB R2025b','--software','Python 3.11')
    foreach ($output in $outputs) { $manifestArguments += @('--output',$output) }
    & $python @manifestArguments
    if ($LASTEXITCODE -ne 0) { throw 'Final finite 3D run manifest failed.' }
    Write-Output "FINITE_3D_L3=PASS PROJECT=$projectId RUN_ID=$RunId PRIMARY=$($primaryCase.transmission_fraction) CONTROL=$($controlCase.transmission_fraction) ENERGY_EV=$($primaryCase.mean_output_energy_eV)"
  } catch {
    [ordered]@{ schema_version=1; role='multipole_finite_3d_transport_summary'; status='failed'; reason=$_.Exception.Message } |
      ConvertTo-Json | Set-Content -LiteralPath $summary -Encoding UTF8
    $failureOutputs = @($summary)
    foreach ($path in @($report,$events,$trajectories,$metrics,$plot,$model,$canonicalState,$solverSummary)) {
      if (Test-Path -LiteralPath $path -PathType Leaf) { $failureOutputs += $path }
    }
    $failureArguments = @($manifestWriter,'--run-config',$runConfig,'--status','failed',
      '--software','COMSOL 6.4','--software','MATLAB R2025b','--software','Python 3.11')
    foreach ($output in $failureOutputs) { $failureArguments += @('--output',$output) }
    & $python @failureArguments
    throw
  }
} finally {
  foreach ($name in $environmentNames) { [Environment]::SetEnvironmentVariable($name, $oldEnvironment[$name]) }
}
