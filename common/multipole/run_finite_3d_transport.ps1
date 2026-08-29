[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$ProjectId,
  [Parameter(Mandatory=$true)][string]$RuntimeProfileId,
  [Parameter(Mandatory=$true)][string]$DesignProfileId,
  [Parameter(Mandatory=$true)][string]$ParticleSourcePath,
  [Parameter(Mandatory=$true)][string]$EngineeringBudgetPath,
  [string]$EvidenceContractPath='',
  [string]$RunId='',
  [string]$PythonExe='',
  [ValidateRange(1,9)][int]$MeshAutoLevel=6,
  [double]$WorkingRegionMaximumElementSizeMm=[double]::NaN,
  [ValidateRange(4,10000)][int]$RfStepsPerPeriod=80,
  [ValidateRange(0.001,1000000)][double]$MaximumTimeUs=80.0,
  [ValidateSet('compact','qualification','solver_review')][string]$RetentionClass='compact',
  [string]$RetentionReason='',
  [string]$SourceFamilyPath='',
  [string]$OperatingPointId='',
  [ValidateSet('transport','mesh_build','field_solve')][string]$StopStage='transport'
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'finite_3d_transport_preflight.ps1')
if(-not [double]::IsNaN($WorkingRegionMaximumElementSizeMm) -and $WorkingRegionMaximumElementSizeMm-le 0){
  throw 'WorkingRegionMaximumElementSizeMm must be positive when supplied.'
}
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\multipole\resource_budget_support.ps1')
$particleSourceInput=(Resolve-Path -LiteralPath $ParticleSourcePath).Path
$engineeringBudgetInput=(Resolve-Path -LiteralPath $EngineeringBudgetPath).Path
$hasSourceFamily=-not[string]::IsNullOrWhiteSpace($SourceFamilyPath)
$hasOperatingPoint=-not[string]::IsNullOrWhiteSpace($OperatingPointId)
if($hasSourceFamily-ne$hasOperatingPoint){
  throw 'SourceFamilyPath and OperatingPointId must be supplied together.'
}
$sourceFamilyInput=if($hasSourceFamily){(Resolve-Path -LiteralPath $SourceFamilyPath).Path}else{$null}
$registryPreflight=Get-Content -LiteralPath (Join-Path $repoRoot 'config\project_registry.json') -Raw -Encoding UTF8|ConvertFrom-Json
$projectMatches=@($registryPreflight.projects|Where-Object{[string]$_.project_id-eq$ProjectId})
if($projectMatches.Count-ne 1){throw "ProjectId is not unique in the canonical project registry: $ProjectId"}
if([string]::IsNullOrWhiteSpace($RunId)){
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+"__sim__comsol__$($ProjectId.Replace('_','-'))-$($DesignProfileId.Replace('_','-'))__resolved-l3"
}
$budgetPreflight=Join-Path ([IO.Path]::GetTempPath()) ("multipole_budget_{0}.json"-f[guid]::NewGuid())
try{
  Push-Location $repoRoot
  try{
    & $python -m common.multipole.resource_budget --repo-root $repoRoot `
      --budget $engineeringBudgetInput --project-id $ProjectId --solver comsol `
      --runtime-profile-id $RuntimeProfileId --design-profile-id $DesignProfileId `
      --particle-source $particleSourceInput --retention-class $RetentionClass `
      --output $budgetPreflight
  }finally{Pop-Location}
  if($LASTEXITCODE-ne 0){throw 'COMSOL resource-budget preflight failed.'}
  $resolvedBudget=Get-Content -LiteralPath $budgetPreflight -Raw -Encoding UTF8|ConvertFrom-Json
  if($resolvedBudget.PSObject.Properties.Name-notcontains'stop_stage'){
    throw 'COMSOL resolved resource budget omits the runtime-profile stop stage.'
  }
  $authorizedStopStage=[string]$resolvedBudget.stop_stage
  if($authorizedStopStage-notin@('transport','mesh_build','field_solve')){
    throw 'COMSOL resolved resource budget has an unsupported runtime-profile stop stage.'
  }
  if($StopStage-ne$authorizedStopStage){
    throw 'COMSOL StopStage differs from the authorized runtime profile.'
  }
  $authorizedNumerics=$resolvedBudget.solver_numerics
  $authorizedBackend=[string]$authorizedNumerics.stationary_linear_solver_backend
  if($authorizedBackend-notin@('mumps','pardiso','cg_amg')){
    throw 'COMSOL runtime profile has an unsupported stationary linear-solver backend.'
  }
  $hasIterativeSolver=$authorizedNumerics.PSObject.Properties.Name-contains'stationary_iterative_solver'
  if($authorizedBackend-eq'cg_amg'){
    if(-not$hasIterativeSolver){
      throw 'CG-AMG runtime profile omits stationary_iterative_solver.'
    }
    $authorizedIterativeSolver=$authorizedNumerics.stationary_iterative_solver
    $iterativeKeys=@($authorizedIterativeSolver.PSObject.Properties.Name|Sort-Object)
    if(($iterativeKeys-join',')-ne'error_check_mode,maximum_iterations,relative_tolerance'){
      throw 'CG-AMG stationary_iterative_solver fields differ.'
    }
    $authorizedRelativeTolerance=[double]$authorizedIterativeSolver.relative_tolerance
    $authorizedMaximumIterations=[double]$authorizedIterativeSolver.maximum_iterations
    $authorizedErrorCheck=[string]$authorizedIterativeSolver.error_check_mode
    if([double]::IsNaN($authorizedRelativeTolerance)-or
      [double]::IsInfinity($authorizedRelativeTolerance)-or
      $authorizedRelativeTolerance-le 0-or$authorizedRelativeTolerance-ge 1-or
      [double]::IsNaN($authorizedMaximumIterations)-or
      [double]::IsInfinity($authorizedMaximumIterations)-or
      $authorizedMaximumIterations-lt 1-or
      $authorizedMaximumIterations-ne[math]::Truncate($authorizedMaximumIterations)-or
      $authorizedErrorCheck-ne'on'){
      throw 'CG-AMG stationary_iterative_solver values are invalid.'
    }
  }else{
    if($hasIterativeSolver){
      throw 'Direct stationary solver profiles forbid stationary_iterative_solver.'
    }
    $authorizedIterativeSolver=$null
  }
  if($authorizedNumerics.PSObject.Properties.Name-notcontains'electric_potential_element_order'){
    throw 'COMSOL runtime profile omits the required electric-potential element order.'
  }
  $authorizedElementOrder=[string]$authorizedNumerics.electric_potential_element_order
  if($authorizedElementOrder-notin@('linear','quadratic')){
    throw 'COMSOL runtime profile has an unsupported electric-potential element order.'
  }
  $maximumMeshCells=$null
  if($resolvedBudget.limits.PSObject.Properties.Name-contains'maximum_mesh_cells'){
    $maximumMeshCells=[int64]$resolvedBudget.limits.maximum_mesh_cells
  }
  $fieldPreregistration=$null
  $fieldSamplingPlanInput=$null
  if($StopStage-eq'field_solve'){
    $fieldPreregistration=Assert-MultipoleFieldPreregistration `
      -Path $EvidenceContractPath -RepoRoot $repoRoot -ProjectId $ProjectId `
      -RunId $RunId -RuntimeProfileId $RuntimeProfileId `
      -DesignProfileId $DesignProfileId `
      -ParticleSourceProfileId ([string]$resolvedBudget.particle_source_profile_id) `
      -SolverNumericsProfileId ([string]$resolvedBudget.solver_numerics_profile_id) `
      -RetentionClass $RetentionClass `
      -ExpectedResolvedSha256 ([string]$resolvedBudget.expected_run_parent_resolved_design_sha256) `
      -EngineeringBudgetPath $engineeringBudgetInput
    $fieldSamplingPlanInput=[IO.Path]::GetFullPath(
      (Join-Path $repoRoot ([string]$fieldPreregistration.field_sampling.plan_path))
    )
  }
  $authorizedHmax=$authorizedNumerics.mesh.working_region_maximum_element_size_mm
  if([int]$authorizedNumerics.mesh.global_auto_level-ne$MeshAutoLevel-or
    [int]$authorizedNumerics.trajectory.rf_steps_per_period-ne$RfStepsPerPeriod-or
    [double]$authorizedNumerics.trajectory.maximum_global_time_us-ne$MaximumTimeUs-or
    ($null-eq$authorizedHmax)-ne[double]::IsNaN($WorkingRegionMaximumElementSizeMm)-or
    ($null-ne$authorizedHmax-and[double]$authorizedHmax-ne$WorkingRegionMaximumElementSizeMm)){
    throw 'COMSOL numerical arguments differ from the authorized runtime profile.'
  }
}catch{
  Remove-Item -LiteralPath $budgetPreflight -Force -ErrorAction SilentlyContinue
  throw
}
$executionCapacityPaths=Get-RunPackageCopiedSourcePaths -RepoRoot $repoRoot `
  -SourceRelativeDirectories @('common/contracts','common/multipole','common/comsol') `
  -Extensions @('.py','.json','.ps1','.m','.lua')
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$ProjectId") -RunId $RunId `
  -Project $ProjectId -Mode 'resolved_design_transport' `
  -RetentionContractEnabled `
  -RetentionClass $RetentionClass -RetentionReason $RetentionReason `
  -Software @('COMSOL 6.4','MATLAB R2025b','Python 3.11') -UseShortExecutionPath `
  -ExpectedExecutionRelativePaths $executionCapacityPaths
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$logDir=$package.log_dir;$runConfig=$package.run_config;$summary=$package.summary
$runtimeDir=Join-Path $logDir 'runtime'
$solverProgressDir=Join-Path $logDir 'solver_progress'
$manifestRepoRoot=$repoRoot
$resourceBudgetExceeded=$false
New-Item -ItemType Directory -Force -Path $runtimeDir|Out-Null
New-Item -ItemType Directory -Force -Path $solverProgressDir|Out-Null
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$hostExecutionOutcome='failed'
$hostExecutionLease=Enter-HostExecutionLease -Role COMSOL -RunId $RunId

try{
  $codeRoot=Join-Path $inputDir 'code'
  foreach($area in @('contracts','multipole','comsol')){
    $sourceRoot=Join-Path $repoRoot "common\$area";$destinationRoot=Join-Path $codeRoot "common\$area"
    Get-ChildItem -LiteralPath $sourceRoot -Recurse -File|Where-Object{
      $_.Extension -in @('.py','.json','.ps1','.m','.lua')
    }|ForEach-Object{
      $relative=$_.FullName.Substring($sourceRoot.Length).TrimStart('\')
      $destination=Join-Path $destinationRoot $relative
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination)|Out-Null
      Copy-Item -LiteralPath $_.FullName -Destination $destination
    }
  }
  $codeInventory=Join-Path $inputDir 'code_inventory.json'
  $inventory=@(Get-ChildItem -LiteralPath $codeRoot -Recurse -File|Sort-Object FullName|ForEach-Object{
    [ordered]@{path=$_.FullName.Substring($codeRoot.Length+1).Replace('\','/');sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
  })
  [ordered]@{schema_version=1;role='frozen_code_inventory';files=$inventory}|
    ConvertTo-Json -Depth 5|Set-Content -LiteralPath $codeInventory -Encoding UTF8
  $manifestRepoRoot=$codeRoot

  $profileResolution=Join-Path $inputDir 'design_profile_resolution.json'
  $engineeringBudget=Join-Path $inputDir 'engineering_budget.json'
  $resolvedResourceBudget=Join-Path $inputDir 'resolved_resource_budget.json'
  Copy-Item -LiteralPath $engineeringBudgetInput -Destination $engineeringBudget
  Move-Item -LiteralPath $budgetPreflight -Destination $resolvedResourceBudget
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    & $python -m common.multipole.design_profile --repo-root $repoRoot --project-id $ProjectId `
      --design-profile-id $DesignProfileId --output $profileResolution
    if($LASTEXITCODE-ne 0){throw 'Governed design profile resolution failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  $profile=Get-Content -LiteralPath $profileResolution -Raw -Encoding UTF8|ConvertFrom-Json
  $identity=$profile.profile.identity
  $registry=Join-Path $inputDir 'project_registry.json'
  $descriptor=Join-Path $inputDir 'project.json';$profiles=Join-Path $inputDir 'design_profiles.json'
  $request=Join-Path $inputDir 'multipole_design_request.json'
  $variables=Join-Path $inputDir 'design_variables.json';$envelope=Join-Path $inputDir 'optimization_envelope.json'
  $modeRegistry=$null;$modeId=$null
  Copy-Item -LiteralPath $profile.registry_path -Destination $registry
  Copy-Item -LiteralPath $profile.descriptor_path -Destination $descriptor
  Copy-Item -LiteralPath $profile.profiles_path -Destination $profiles
  Copy-Item -LiteralPath $profile.paths.design_request -Destination $request
  Copy-Item -LiteralPath $profile.paths.design_variables -Destination $variables
  Copy-Item -LiteralPath $profile.paths.optimization_envelope -Destination $envelope
  if($profile.profile.PSObject.Properties.Name-contains'mode_id'){
    $modeId=[string]$profile.profile.mode_id
    if(-not($profile.paths.PSObject.Properties.Name-contains'operating_mode_registry')){
      throw 'Typed design profile is missing its resolved operating-mode registry path.'
    }
    $modeRegistry=Join-Path $inputDir 'operating_modes.json'
    Copy-Item -LiteralPath $profile.paths.operating_mode_registry -Destination $modeRegistry
  }

  $resolved=Join-Path $inputDir 'multipole_resolved_design.json'
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    $compileArguments=@('-m','common.multipole.compile_design_request',
      '--request',$request,'--design-variables',$variables,
      '--optimization-envelope',$envelope,'--output',$resolved,
      '--provenance-root',$inputDir,'--project-id',$ProjectId,
      '--radial-order-n',([string][int]$identity.radial_order_n),
      '--electrode-count',([string][int]$identity.electrode_count))
    if($modeRegistry){
      $compileArguments+=@('--operating-mode-registry',$modeRegistry,'--mode-id',$modeId)
    }
    & $python @compileArguments
    if($LASTEXITCODE-ne 0){throw 'Governed multipole design compilation failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  $design=Get-Content -LiteralPath $resolved -Raw -Encoding UTF8|ConvertFrom-Json
  $resolvedHash=[string]$design.resolved_sha256
  $expectedResolvedHash=[string]$resolvedBudget.expected_run_parent_resolved_design_sha256
  if($expectedResolvedHash-and$resolvedHash-ne$expectedResolvedHash){
    throw "Compiled resolved design differs from the authorized run identity: expected=$expectedResolvedHash actual=$resolvedHash"
  }
  $fieldSamplingPlan=$null
  $fieldSamplePoints=$null
  if($StopStage-eq'field_solve'){
    $fieldSamplingPlan=Join-Path $inputDir 'stationary_field_sampling_plan.json'
    $fieldSamplePoints=Join-Path $inputDir 'stationary_field_sample_points.csv'
    Copy-Item -LiteralPath $fieldSamplingPlanInput -Destination $fieldSamplingPlan
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      & $python -m common.multipole.stationary_field_sampling generate `
        --resolved-design $resolved --sampling-plan $fieldSamplingPlan `
        --output $fieldSamplePoints
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    if($LASTEXITCODE-ne 0){throw 'Governed stationary-field sample generation failed.'}
    $fieldSamplePointCount=@(Import-Csv -LiteralPath $fieldSamplePoints).Count
    if($fieldSamplePointCount-ne[int64]$fieldPreregistration.field_sampling.expected_point_count){
      throw 'Generated stationary-field sample count differs from preregistration.'
    }
  }
  $axialTopology=[string]$design.axial_drive.topology
  $particleSource=Join-Path $inputDir 'particle_source.csv'
  Copy-Item -LiteralPath $particleSourceInput -Destination $particleSource
  $sourceFamily=$null;$sourceFamilySha=$null
  if($sourceFamilyInput){
    $sourceFamily=Join-Path $inputDir 'particle_source_family.json'
    Copy-Item -LiteralPath $sourceFamilyInput -Destination $sourceFamily
    $sourceFamilySha=(Get-FileHash -LiteralPath $sourceFamily -Algorithm SHA256).Hash
  }
  $sourceMetadata=Join-Path $inputDir 'particle_source_metadata.json'
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    $preflightArguments=@('-m','common.multipole.particle_source_preflight',
      '--source',$particleSource,'--resolved-design',$resolved,'--output',$sourceMetadata)
    if($sourceFamily){
      $preflightArguments+=@('--source-family',$sourceFamily,
        '--operating-point',$OperatingPointId,
        '--expected-source-family-sha256',$sourceFamilySha)
    }
    & $python @preflightArguments
    if($LASTEXITCODE-ne 0){throw 'Canonical particle source preflight failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  $sourceMeta=Get-Content -LiteralPath $sourceMetadata -Raw -Encoding UTF8|ConvertFrom-Json
  if($sourceFamily){
    $binding=$sourceMeta.operating_point_binding
    if($null-eq$binding -or
      [string]$binding.operating_point_id-ne$OperatingPointId -or
      [string]$binding.source_family_sha256-ne$sourceFamilySha
    ){throw 'Canonical particle source operating-point binding differs from the frozen runner input.'}
  }elseif($null-ne$sourceMeta.operating_point_binding){
    throw 'Canonical particle source reported an unexpected operating-point binding.'
  }

  $numerics=Join-Path $inputDir 'solver_numerics.json'
  $solverNumericsDocument=[ordered]@{schema_version=1;role='multipole_comsol_solver_numerics';
    stationary_linear_solver_backend=$authorizedBackend;
    electric_potential_element_order=$authorizedElementOrder;
    mesh=$authorizedNumerics.mesh;
    trajectory=$authorizedNumerics.trajectory}
  if($authorizedBackend-eq'cg_amg'){
    $solverNumericsDocument.stationary_iterative_solver=$authorizedIterativeSolver
  }
  $solverNumericsDocument|
    ConvertTo-Json -Depth 5|Set-Content -LiteralPath $numerics -Encoding UTF8
  $evidence=$null
  if(-not[string]::IsNullOrWhiteSpace($EvidenceContractPath)){
    $evidence=Join-Path $inputDir 'evidence_contract.json'
    Copy-Item -LiteralPath ([IO.Path]::GetFullPath($EvidenceContractPath)) -Destination $evidence
  }

  $events=Join-Path $resultDir 'particle_events.csv';$trajectories=Join-Path $resultDir 'trajectory_samples.csv'
  $metrics=Join-Path $resultDir 'finite_3d_transport_metrics.json'
  $pairedMetrics=Join-Path $resultDir 'paired_axial_drive_metrics.json'
  $plot=Join-Path $resultDir 'finite_3d_transport.png'
  $exitStatePlot=Join-Path $resultDir 'exit_state_diagnostics.png'
  $exitStatePlotManifest=Join-Path $resultDir 'exit_state_diagnostics.json'
  $model=Join-Path $resultDir 'finite_3d_transport.mph';$canonicalState=Join-Path $resultDir 'particle_state.csv'
  $primaryState=Join-Path $resultDir 'particle_state__primary.csv';$controlState=Join-Path $resultDir 'particle_state__control.csv'
  $primaryTrajectories=Join-Path $resultDir 'trajectory_samples__primary.csv'
  $controlTrajectories=Join-Path $resultDir 'trajectory_samples__control.csv'
  $report=Join-Path $logDir 'comsol_finite_3d_transport.txt';$evaluation=Join-Path $resultDir 'evidence_evaluation.json'
  $fieldSamples=Join-Path $resultDir 'stationary_field_samples.csv'
  $fieldSampleValidation=Join-Path $resultDir 'stationary_field_sample_validation.json'
  $task=Join-Path $codeRoot 'common\multipole\solve_finite_3d_transport.m'
  [ordered]@{schema_version=2;role='multipole_resolved_comsol_run_config';run_id=$RunId;project=$ProjectId;
    mode='resolved_design_transport';project_root=$profile.project_root;
    artifact_retention=[ordered]@{policy_version=1;class=$RetentionClass;
      reason=$(if($RetentionClass-eq'compact'){$null}else{$RetentionReason})};
    provenance=[ordered]@{parent_resolved_design_sha256=$resolvedHash;particle_source_sha256=$sourceMeta.source_sha256;
      source_family_sha256=$sourceFamilySha;operating_point_id=$(if($sourceFamily){$OperatingPointId}else{$null});
      particle_source_operating_point_binding=$sourceMeta.operating_point_binding};
    inputs=[ordered]@{project_registry=$registry;project_descriptor=$descriptor;design_profiles=$profiles;
      engineering_budget=$engineeringBudget;resolved_resource_budget=$resolvedResourceBudget;
      design_profile_resolution=$profileResolution;design_request=$request;design_variables=$variables;
      optimization_envelope=$envelope;operating_mode_registry=$modeRegistry;
      multipole_resolved_design=$resolved;particle_source=$particleSource;
      particle_source_metadata=$sourceMetadata;particle_source_family=$sourceFamily;
      solver_numerics=$numerics;code_inventory=$codeInventory;
      evidence_contract=$evidence;stationary_field_sampling_plan=$fieldSamplingPlan;
      stationary_field_sample_points=$fieldSamplePoints;comsol_task=$task};
    parameters=[ordered]@{model_level='L3';runtime_profile_id=$RuntimeProfileId;design_profile_id=$DesignProfileId;
      operating_mode_id=$modeId;
      operating_point_id=$(if($sourceFamily){$OperatingPointId}else{$null});mesh_convergence=$false;
      stop_stage=$StopStage};
    formal_gate_passed=$false}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $runConfig -Encoding UTF8

  $environmentNames=@('MULTIPOLE_RESOLVED_DESIGN','MULTIPOLE_SOLVER_NUMERICS','MULTIPOLE_L3_PARTICLE_SOURCE',
    'MULTIPOLE_L3_PARTICLE_SOURCE_METADATA','MULTIPOLE_L3_RUNTIME_DIR','MULTIPOLE_L3_EVENTS',
    'MULTIPOLE_L3_TRAJECTORIES','MULTIPOLE_L3_METRICS','MULTIPOLE_L3_PLOT','MULTIPOLE_L3_MODEL',
    'MULTIPOLE_L3_CANONICAL_STATE','MULTIPOLE_L3_PRIMARY_CANONICAL_STATE',
    'MULTIPOLE_L3_CONTROL_CANONICAL_STATE','MULTIPOLE_L3_PRIMARY_TRAJECTORIES',
    'MULTIPOLE_L3_CONTROL_TRAJECTORIES','MULTIPOLE_L3_SOLVER_PROGRESS_DIR',
    'MULTIPOLE_L3_STOP_STAGE',
    'MULTIPOLE_L3_FIELD_SAMPLE_POINTS','MULTIPOLE_L3_FIELD_SAMPLES',
    'MULTIPOLE_L3_MAXIMUM_MESH_CELLS')
  $oldEnvironment=Save-RunEnvironment -Names $environmentNames
  $resourceUsage=Join-Path $resultDir 'resource_usage.json'
  try{
    $env:MULTIPOLE_RESOLVED_DESIGN=$resolved;$env:MULTIPOLE_SOLVER_NUMERICS=$numerics
    $env:MULTIPOLE_L3_PARTICLE_SOURCE=$particleSource;$env:MULTIPOLE_L3_PARTICLE_SOURCE_METADATA=$sourceMetadata
    $env:MULTIPOLE_L3_RUNTIME_DIR=$runtimeDir;$env:MULTIPOLE_L3_EVENTS=$events
    $env:MULTIPOLE_L3_TRAJECTORIES=$trajectories;$env:MULTIPOLE_L3_METRICS=$metrics
    $env:MULTIPOLE_L3_PLOT=$plot;$env:MULTIPOLE_L3_MODEL=$model;$env:MULTIPOLE_L3_CANONICAL_STATE=$canonicalState
    $env:MULTIPOLE_L3_PRIMARY_CANONICAL_STATE=$primaryState
    $env:MULTIPOLE_L3_CONTROL_CANONICAL_STATE=$controlState
    $env:MULTIPOLE_L3_PRIMARY_TRAJECTORIES=$primaryTrajectories
    $env:MULTIPOLE_L3_CONTROL_TRAJECTORIES=$controlTrajectories
    $env:MULTIPOLE_L3_SOLVER_PROGRESS_DIR=$solverProgressDir
    $env:MULTIPOLE_L3_STOP_STAGE=$StopStage
    $env:MULTIPOLE_L3_FIELD_SAMPLE_POINTS=if($fieldSamplePoints){$fieldSamplePoints}else{''}
    $env:MULTIPOLE_L3_FIELD_SAMPLES=if($StopStage-eq'field_solve'){$fieldSamples}else{''}
    $env:MULTIPOLE_L3_MAXIMUM_MESH_CELLS=if($null-ne$maximumMeshCells){[string]$maximumMeshCells}else{''}
    $pwsh=(Get-Process -Id $PID).Path
    $solverProcess=Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $resolvedResourceBudget `
      -RunDir $runDir -UsagePath $resourceUsage -FilePath $pwsh -ArgumentList @(
        '-NoProfile','-NonInteractive','-File',(Join-Path $codeRoot 'common\comsol\run_comsol_r2025b.ps1'),
        '-TaskScript',$task,'-ReportPath',$report,'-StartupAttempts','1')
    if($solverProcess.resource_budget_exceeded){
      $resourceBudgetExceeded=$true
      throw 'COMSOL resource budget exceeded.'
    }
    if($null-ne$maximumMeshCells){
      try{
        $meshCells=Assert-MultipoleMeshCellBudgetReport -Path $report `
          -MaximumMeshCells $maximumMeshCells
      }catch{
        if([string]$_.Exception.Data['limit_name']-eq'maximum_mesh_cells'){
          $resourceBudgetExceeded=$true
          $usage=Get-Content -LiteralPath $resourceUsage -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
          $usage.status='resource_budget_exceeded'
          $usage.failure_class='resource_budget_exceeded'
          $usage.limit_name='maximum_mesh_cells'
          $usage.mesh_cells=[int64]$_.Exception.Data['measured_value']
          Write-ResourceUsage -Usage $usage -Path $resourceUsage
        }
        throw
      }
    }
    if($solverProcess.exit_code-ne 0){throw 'COMSOL finite 3D multipole transport failed.'}
  }finally{Restore-RunEnvironment -Names $environmentNames -Snapshot $oldEnvironment}
  if($StopStage-eq'mesh_build'){
    try{
      $meshCells=Assert-MultipoleMeshBuildReport -Path $report
    }catch{
      if([string]$_.Exception.Data['limit_name']-eq'maximum_mesh_cells'){
        $resourceBudgetExceeded=$true
        $usage=Get-Content -LiteralPath $resourceUsage -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
        $usage.status='resource_budget_exceeded'
        $usage.failure_class='resource_budget_exceeded'
        $usage.limit_name='maximum_mesh_cells'
        $usage.mesh_cells=[int64]$_.Exception.Data['measured_value']
        Write-ResourceUsage -Usage $usage -Path $resourceUsage
      }
      throw
    }
    $summaryDocument=[ordered]@{schema_version=1;role='multipole_finite_3d_transport_summary';status='success';
      qualification_status='UNQUALIFIED_MESH_BUILD_DIAGNOSTIC_ONLY';project_id=$ProjectId;
      design_profile_id=$DesignProfileId;parent_resolved_design_sha256=$resolvedHash;
      model_level='L3';stop_stage='mesh_build';field_physics_created=0;field_studies_created=0;
      field_solutions_created=0;particle_physics_created=0;particle_studies_created=0;
      formal_gate_passed=$false}
    if($null-ne$maximumMeshCells){
      $summaryDocument.mesh_cells=$meshCells
      $summaryDocument.maximum_mesh_cells=$maximumMeshCells
    }
    $summaryDocument|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $summary -Encoding UTF8
    $retentionActions=Apply-RunArtifactRetention -Python $python -RepoRoot $manifestRepoRoot `
      -RunConfig $runConfig
    if(-not(Complete-ResourceUsage -ResolvedBudgetPath $resolvedResourceBudget `
      -RunDir $runDir -UsagePath $resourceUsage)){
      $resourceBudgetExceeded=$true
      throw 'COMSOL mesh-build retained-byte budget exceeded.'
    }
    $outputs=@($report,$summary,$resourceUsage)|Where-Object{Test-Path -LiteralPath $_ -PathType Leaf}
    $outputs+=@(Get-ChildItem -LiteralPath $solverProgressDir -File|ForEach-Object{$_.FullName})
    $outputs+=$retentionActions
    Write-VerifiedRunManifest -Python $python -RepoRoot $manifestRepoRoot -RunConfig $runConfig `
      -Status success -Software @('COMSOL 6.4','MATLAB R2025b','Python 3.11') -Outputs $outputs
    $hostExecutionOutcome='success'
    Write-Output "MULTIPOLE_COMSOL_RESOLVED=PASS PROJECT=$ProjectId PROFILE=$DesignProfileId RUN_ID=$RunId STOP_STAGE=mesh_build QUALIFICATION=UNQUALIFIED"
    return
  }
  if($StopStage-eq'field_solve'){
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      & $python -m common.multipole.stationary_field_sampling validate `
        --input $fieldSamples --output $fieldSampleValidation
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    if($LASTEXITCODE-ne 0){throw 'COMSOL stationary-field sample validation failed.'}
    $fieldSampleValidationDocument=Get-Content -LiteralPath $fieldSampleValidation `
      -Raw -Encoding UTF8|ConvertFrom-Json
    if([string]$fieldSampleValidationDocument.status-ne'PASS'-or
      [int64]$fieldSampleValidationDocument.point_count-ne
        [int64]$fieldPreregistration.field_sampling.expected_point_count-or
      [int64]$fieldSampleValidationDocument.row_count-ne
        [int64]$fieldPreregistration.field_sampling.expected_row_count){
      throw 'COMSOL stationary-field sample validation differs from preregistration.'
    }
    $fieldSolve=Assert-MultipoleFieldSolveReport -Path $report
    $fieldReportContent=Get-Content -LiteralPath $report -Raw -Encoding UTF8
    foreach($token in $fieldPreregistration.required_report.tokens){
      if($fieldReportContent-notmatch("(?m)^$([regex]::Escape([string]$token))\r?$")){
        throw "COMSOL field-solve report is missing preregistered token: $token"
      }
    }
    foreach($checkpoint in $fieldPreregistration.required_report.forbidden_checkpoints){
      if($fieldReportContent-match("(?m)^$([regex]::Escape([string]$checkpoint))\r?$")){
        throw "COMSOL field-solve report contains forbidden checkpoint: $checkpoint"
      }
    }
    if($fieldSolve.stationary_linear_solver_backend-ne$authorizedBackend-or
      $fieldSolve.electric_potential_element_order-ne$authorizedElementOrder){
      throw 'COMSOL field-solve report differs from the authorized solver numerics.'
    }
    if($authorizedBackend-eq'cg_amg'){
      $actualConfiguration=$fieldSolve.stationary_solver_configuration
      if([double]$actualConfiguration.relative_tolerance-ne
          [double]$authorizedIterativeSolver.relative_tolerance-or
        [int64]$actualConfiguration.maximum_linear_iterations-ne
          [int64]$authorizedIterativeSolver.maximum_iterations-or
        [string]$actualConfiguration.linear_error_check-ne
          [string]$authorizedIterativeSolver.error_check_mode){
        throw 'COMSOL field-solve convergence settings differ from the authorized solver numerics.'
      }
    }
    $summaryDocument=[ordered]@{schema_version=1;role='multipole_finite_3d_transport_summary';status='success';
      qualification_status='UNQUALIFIED_FIELD_SOLVE_DIAGNOSTIC_ONLY';project_id=$ProjectId;
      design_profile_id=$DesignProfileId;parent_resolved_design_sha256=$resolvedHash;
      model_level='L3';stop_stage='field_solve';
      stationary_linear_solver_backend=$fieldSolve.stationary_linear_solver_backend;
      electric_potential_element_order=$fieldSolve.electric_potential_element_order;
      field_physics_created=$fieldSolve.field_physics_created;
      field_studies_created=$fieldSolve.field_studies_created;
      field_solutions_created=$fieldSolve.field_solutions_created;
      field_dof=$fieldSolve.field_dof;
      field_solver_evidence=$fieldSolve.field_solver_evidence;
      stationary_solver_configuration=$fieldSolve.stationary_solver_configuration;
      field_sample_point_count=[int64]$fieldSampleValidationDocument.point_count;
      field_sample_row_count=[int64]$fieldSampleValidationDocument.row_count;
      particle_physics_created=0;particle_studies_created=0;
      formal_gate_passed=$false}
    if($null-ne$maximumMeshCells){
      $summaryDocument.mesh_cells=$meshCells
      $summaryDocument.maximum_mesh_cells=$maximumMeshCells
    }
    $summaryDocument|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $summary -Encoding UTF8
    $retentionActions=Apply-RunArtifactRetention -Python $python -RepoRoot $manifestRepoRoot `
      -RunConfig $runConfig
    if(-not(Complete-ResourceUsage -ResolvedBudgetPath $resolvedResourceBudget `
      -RunDir $runDir -UsagePath $resourceUsage)){
      $resourceBudgetExceeded=$true
      throw 'COMSOL field-solve retained-byte budget exceeded.'
    }
    $outputs=@($report,$summary,$resourceUsage,$fieldSamples,$fieldSampleValidation)|
      Where-Object{Test-Path -LiteralPath $_ -PathType Leaf}
    $outputs+=@(Get-ChildItem -LiteralPath $solverProgressDir -File|ForEach-Object{$_.FullName})
    $outputs+=$retentionActions
    Write-VerifiedRunManifest -Python $python -RepoRoot $manifestRepoRoot -RunConfig $runConfig `
      -Status success -Software @('COMSOL 6.4','MATLAB R2025b','Python 3.11') -Outputs $outputs
    $hostExecutionOutcome='success'
    Write-Output "MULTIPOLE_COMSOL_RESOLVED=PASS PROJECT=$ProjectId PROFILE=$DesignProfileId RUN_ID=$RunId STOP_STAGE=field_solve QUALIFICATION=UNQUALIFIED"
    return
  }
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    & $python -m common.multipole.analyze_comsol_transport_metrics `
      --events $events --primary-state $primaryState --control-state $controlState `
      --resolved-design $resolved --numerics $numerics --output $metrics
    if($LASTEXITCODE-ne 0){throw 'Python COMSOL transport metrics analysis failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  if(-not(Test-Path -LiteralPath $metrics -PathType Leaf)){
    throw 'Python COMSOL transport metrics did not create finite_3d_transport_metrics.json.'}
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    $exitStatePlotLabel=$ProjectId.Replace('_',' ')
    & $python -m common.multipole.exit_state_plot `
      --series "$exitStatePlotLabel=$primaryState=$RunId" `
      --output $exitStatePlot --manifest $exitStatePlotManifest `
      --title "$exitStatePlotLabel exit-state diagnostic" `
      --purpose 'Regular single-run multipole exit-state diagnostic' `
      --repo-root $repoRoot
    if($LASTEXITCODE-ne 0){throw 'COMSOL exit-state diagnostic plot failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  if($axialTopology-ne'none'){
  Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      & $python -m common.multipole.analyze_simion_axial_acceleration `
        --accelerated-state $primaryState --control-state $controlState `
        --resolved-contract $resolved --output $pairedMetrics
      if($LASTEXITCODE-ne 0){throw 'COMSOL paired axial-drive metrics analysis failed.'}
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  }
  $qualification='UNQUALIFIED'
  if($evidence){
    $evidenceDocument=Get-Content -LiteralPath $evidence -Raw -Encoding UTF8|ConvertFrom-Json
    $evidenceMetrics=if([string]$evidenceDocument.evaluation-eq'axial_drop_vs_zero_drop'){
      if($axialTopology-eq'none'){throw 'Axial-drop evidence requires an axial-drive design profile.'}
      $pairedMetrics
    }else{$metrics}
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      & $python -m common.multipole.evaluate_transport_evidence --metrics $evidenceMetrics --evidence $evidence `
        --project-id $ProjectId --design-profile-id $DesignProfileId --output $evaluation
      $evidenceExit=$LASTEXITCODE
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    if($evidenceExit-ne 0){throw 'COMSOL evidence contract gate failed.'}
    $qualification='PASS'
  }
  $result=Get-Content -LiteralPath $metrics -Raw -Encoding UTF8|ConvertFrom-Json
  $primary=$result.cases.PSObject.Properties[[string]$result.primary_case_id].Value
  $control=$result.cases.PSObject.Properties[[string]$result.control_case_id].Value
  [ordered]@{schema_version=1;role='multipole_finite_3d_transport_summary';status='success';
    qualification_status=$qualification;project_id=$ProjectId;design_profile_id=$DesignProfileId;
    parent_resolved_design_sha256=$resolvedHash;primary_transmission=$primary.transmission_fraction;
    control_transmission=$control.transmission_fraction;model_level='L3';formal_gate_passed=$false}|
    ConvertTo-Json -Depth 5|Set-Content -LiteralPath $summary -Encoding UTF8
  $retentionActions=Apply-RunArtifactRetention -Python $python -RepoRoot $manifestRepoRoot `
    -RunConfig $runConfig
  if(-not(Complete-ResourceUsage -ResolvedBudgetPath $resolvedResourceBudget `
    -RunDir $runDir -UsagePath $resourceUsage)){
    $resourceBudgetExceeded=$true
    throw 'COMSOL compact final retained-byte budget exceeded.'
  }
  $outputs=@($events,$trajectories,$metrics,$plot,$exitStatePlot,$exitStatePlotManifest,
    $model,$canonicalState,$resourceUsage,
    $primaryState,$controlState,$primaryTrajectories,$controlTrajectories,$report,$summary)
  $outputs+=@(Get-ChildItem -LiteralPath $solverProgressDir -File|ForEach-Object{$_.FullName})
  if(Test-Path -LiteralPath $pairedMetrics){$outputs+=$pairedMetrics}
  if(Test-Path -LiteralPath $evaluation){$outputs+=$evaluation}
  $outputs=@($outputs|Where-Object{Test-Path -LiteralPath $_ -PathType Leaf})
  $outputs+=$retentionActions
  Write-VerifiedRunManifest -Python $python -RepoRoot $manifestRepoRoot -RunConfig $runConfig `
    -Status success -Software @('COMSOL 6.4','MATLAB R2025b','Python 3.11') -Outputs $outputs
  $hostExecutionOutcome='success'
  Write-Output "MULTIPOLE_COMSOL_RESOLVED=PASS PROJECT=$ProjectId PROFILE=$DesignProfileId RUN_ID=$RunId PARENT_SHA256=$resolvedHash QUALIFICATION=$qualification"
}catch{
  $hostExecutionOutcome=if($resourceBudgetExceeded){'interrupted'}else{'failed'}
  Complete-FailedRun -Python $python -RepoRoot $manifestRepoRoot -RunConfig $runConfig -Summary $summary `
    -SummaryRole 'multipole_finite_3d_transport_summary' -Reason $_.Exception.Message `
    -Software @('COMSOL 6.4','MATLAB R2025b','Python 3.11') `
    -Status $(if($resourceBudgetExceeded){'interrupted'}else{'failed'}) `
    -FailureClass $(if($resourceBudgetExceeded){'resource_budget_exceeded'}else{''}) `
    -ResourceUsagePath $(if($null-ne(Get-Variable resourceUsage -ErrorAction SilentlyContinue)){$resourceUsage}else{''})
  throw
}finally{
  Remove-Item -LiteralPath $budgetPreflight -Force -ErrorAction SilentlyContinue
  try { Remove-RunPackageExecutionAlias -Package $package } catch {
    Write-Warning "Could not remove short execution alias after COMSOL run: $($_.Exception.Message)"
  }
  Exit-HostExecutionLease -Lease $hostExecutionLease -Outcome $hostExecutionOutcome -RunId $RunId
}
