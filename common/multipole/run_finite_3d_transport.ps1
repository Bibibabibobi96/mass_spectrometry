[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$ProjectId,
  [Parameter(Mandatory=$true)][string]$DesignProfileId,
  [Parameter(Mandatory=$true)][string]$ParticleSourcePath,
  [string]$EvidenceContractPath='',
  [string]$RunId='',
  [string]$PythonExe='',
  [ValidateRange(1,9)][int]$MeshAutoLevel=6,
  [double]$WorkingRegionMaximumElementSizeMm=[double]::NaN,
  [ValidateRange(4,10000)][int]$RfStepsPerPeriod=80,
  [ValidateRange(0.001,1000000)][double]$MaximumTimeUs=80.0
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if(-not [double]::IsNaN($WorkingRegionMaximumElementSizeMm) -and $WorkingRegionMaximumElementSizeMm-le 0){
  throw 'WorkingRegionMaximumElementSizeMm must be positive when supplied.'
}
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$particleSourceInput=(Resolve-Path -LiteralPath $ParticleSourcePath).Path
$registryPreflight=Get-Content -LiteralPath (Join-Path $repoRoot 'config\project_registry.json') -Raw -Encoding UTF8|ConvertFrom-Json
$projectMatches=@($registryPreflight.projects|Where-Object{[string]$_.project_id-eq$ProjectId})
if($projectMatches.Count-ne 1){throw "ProjectId is not unique in the canonical project registry: $ProjectId"}
if([string]::IsNullOrWhiteSpace($RunId)){
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+"__sim__comsol__$($ProjectId.Replace('_','-'))-$DesignProfileId__resolved-l3"
}
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$ProjectId") -RunId $RunId `
  -Project $ProjectId -Mode 'resolved_design_transport' `
  -Software @('COMSOL 6.4','MATLAB R2025b','Python 3.11')
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$logDir=$package.log_dir;$runConfig=$package.run_config;$summary=$package.summary
$runtimeDir=Join-Path $logDir 'runtime'
$manifestRepoRoot=$repoRoot
New-Item -ItemType Directory -Force -Path $runtimeDir|Out-Null

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
  Copy-Item -LiteralPath $profile.registry_path -Destination $registry
  Copy-Item -LiteralPath $profile.descriptor_path -Destination $descriptor
  Copy-Item -LiteralPath $profile.profiles_path -Destination $profiles
  Copy-Item -LiteralPath $profile.paths.design_request -Destination $request
  Copy-Item -LiteralPath $profile.paths.design_variables -Destination $variables
  Copy-Item -LiteralPath $profile.paths.optimization_envelope -Destination $envelope

  $resolved=Join-Path $inputDir 'multipole_resolved_design.json'
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    & $python -m common.multipole.compile_design_request --request $request `
      --design-variables $variables --optimization-envelope $envelope --output $resolved `
      --provenance-root $inputDir `
      --project-id $ProjectId --radial-order-n ([int]$identity.radial_order_n) `
      --electrode-count ([int]$identity.electrode_count)
    if($LASTEXITCODE-ne 0){throw 'Governed multipole design compilation failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  $design=Get-Content -LiteralPath $resolved -Raw -Encoding UTF8|ConvertFrom-Json
  $resolvedHash=[string]$design.resolved_sha256
  $axialTopology=[string]$design.axial_drive.topology
  $particleSource=Join-Path $inputDir 'particle_source.csv'
  Copy-Item -LiteralPath $particleSourceInput -Destination $particleSource
  $sourceMetadata=Join-Path $inputDir 'particle_source_metadata.json'
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    & $python -m common.multipole.particle_source_preflight --source $particleSource `
      --resolved-design $resolved --output $sourceMetadata
    if($LASTEXITCODE-ne 0){throw 'Canonical particle source preflight failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}

  $numerics=Join-Path $inputDir 'solver_numerics.json'
  [ordered]@{schema_version=1;role='multipole_comsol_solver_numerics';
    mesh=[ordered]@{global_auto_level=$MeshAutoLevel;working_region_maximum_element_size_mm=$(if([double]::IsNaN($WorkingRegionMaximumElementSizeMm)){$null}else{$WorkingRegionMaximumElementSizeMm})};
    trajectory=[ordered]@{rf_steps_per_period=$RfStepsPerPeriod;maximum_global_time_us=$MaximumTimeUs}}|
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
  $model=Join-Path $resultDir 'finite_3d_transport.mph';$canonicalState=Join-Path $resultDir 'particle_state.csv'
  $primaryState=Join-Path $resultDir 'particle_state__primary.csv';$controlState=Join-Path $resultDir 'particle_state__control.csv'
  $primaryTrajectories=Join-Path $resultDir 'trajectory_samples__primary.csv'
  $controlTrajectories=Join-Path $resultDir 'trajectory_samples__control.csv'
  $report=Join-Path $logDir 'comsol_finite_3d_transport.txt';$evaluation=Join-Path $resultDir 'evidence_evaluation.json'
  $task=Join-Path $codeRoot 'common\multipole\solve_finite_3d_transport.m'
  $sourceMeta=Get-Content -LiteralPath $sourceMetadata -Raw -Encoding UTF8|ConvertFrom-Json
  [ordered]@{schema_version=1;role='multipole_resolved_comsol_run_config';run_id=$RunId;project=$ProjectId;
    mode='resolved_design_transport';project_root=$profile.project_root;
    provenance=[ordered]@{parent_resolved_design_sha256=$resolvedHash;particle_source_sha256=$sourceMeta.source_sha256};
    inputs=[ordered]@{project_registry=$registry;project_descriptor=$descriptor;design_profiles=$profiles;
      design_profile_resolution=$profileResolution;design_request=$request;design_variables=$variables;
      optimization_envelope=$envelope;multipole_resolved_design=$resolved;particle_source=$particleSource;
      particle_source_metadata=$sourceMetadata;solver_numerics=$numerics;code_inventory=$codeInventory;
      evidence_contract=$evidence;comsol_task=$task};
    parameters=[ordered]@{model_level='L3';design_profile_id=$DesignProfileId;mesh_convergence=$false};
    formal_gate_passed=$false}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $runConfig -Encoding UTF8

  $environmentNames=@('MULTIPOLE_RESOLVED_DESIGN','MULTIPOLE_SOLVER_NUMERICS','MULTIPOLE_L3_PARTICLE_SOURCE',
    'MULTIPOLE_L3_PARTICLE_SOURCE_METADATA','MULTIPOLE_L3_RUNTIME_DIR','MULTIPOLE_L3_EVENTS',
    'MULTIPOLE_L3_TRAJECTORIES','MULTIPOLE_L3_METRICS','MULTIPOLE_L3_PLOT','MULTIPOLE_L3_MODEL',
    'MULTIPOLE_L3_CANONICAL_STATE','MULTIPOLE_L3_PRIMARY_CANONICAL_STATE',
    'MULTIPOLE_L3_CONTROL_CANONICAL_STATE','MULTIPOLE_L3_PRIMARY_TRAJECTORIES',
    'MULTIPOLE_L3_CONTROL_TRAJECTORIES')
  $oldEnvironment=Save-RunEnvironment -Names $environmentNames
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
    & (Join-Path $codeRoot 'common\comsol\run_comsol_r2025b.ps1') -TaskScript $task -ReportPath $report
    if($LASTEXITCODE-ne 0){throw 'COMSOL finite 3D multipole transport failed.'}
  }finally{Restore-RunEnvironment -Names $environmentNames -Snapshot $oldEnvironment}
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
  $outputs=@($events,$trajectories,$metrics,$plot,$model,$canonicalState,
    $primaryState,$controlState,$primaryTrajectories,$controlTrajectories,$report,$summary)
  if(Test-Path -LiteralPath $pairedMetrics){$outputs+=$pairedMetrics}
  if(Test-Path -LiteralPath $evaluation){$outputs+=$evaluation}
  Write-VerifiedRunManifest -Python $python -RepoRoot $manifestRepoRoot -RunConfig $runConfig `
    -Status success -Software @('COMSOL 6.4','MATLAB R2025b','Python 3.11') -Outputs $outputs
  Write-Output "MULTIPOLE_COMSOL_RESOLVED=PASS PROJECT=$ProjectId PROFILE=$DesignProfileId RUN_ID=$RunId PARENT_SHA256=$resolvedHash QUALIFICATION=$qualification"
}catch{
  Complete-FailedRun -Python $python -RepoRoot $manifestRepoRoot -RunConfig $runConfig -Summary $summary `
    -SummaryRole 'multipole_finite_3d_transport_summary' -Reason $_.Exception.Message `
    -Software @('COMSOL 6.4','MATLAB R2025b','Python 3.11')
  throw
}
