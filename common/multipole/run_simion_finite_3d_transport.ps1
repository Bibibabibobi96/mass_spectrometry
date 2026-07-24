[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$ProjectId,
  [Parameter(Mandatory=$true)][string]$DesignProfileId,
  [Parameter(Mandatory=$true)][string]$ParticleSourcePath,
  [string]$EvidenceContractPath='',
  [string]$RunId='',
  [string]$ReferenceComsolRunId='',
  [ValidateRange(0.001,100)][double]$CellMm=0.4,
  [string]$SimionExe='',
  [string]$TemplateIob='',
  [string]$PythonExe='',
  [ValidateRange(4,10000)][int]$RfStepsPerPeriod=80,
  [ValidateRange(0,100)][int]$TrajectoryQuality=10,
  [ValidateRange(0.001,1000000)][double]$MaximumTimeUs=80.0,
  [string]$SourceFamilyPath='',
  [string]$OperatingPointId=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$particleSourceInput=(Resolve-Path -LiteralPath $ParticleSourcePath).Path
$hasSourceFamily=-not[string]::IsNullOrWhiteSpace($SourceFamilyPath)
$hasOperatingPoint=-not[string]::IsNullOrWhiteSpace($OperatingPointId)
if($hasSourceFamily-ne$hasOperatingPoint){
  throw 'SourceFamilyPath and OperatingPointId must be supplied together.'
}
$sourceFamilyInput=if($hasSourceFamily){(Resolve-Path -LiteralPath $SourceFamilyPath).Path}else{$null}
$registryPreflight=Get-Content -LiteralPath (Join-Path $repoRoot 'config\project_registry.json') -Raw -Encoding UTF8|ConvertFrom-Json
$projectMatches=@($registryPreflight.projects|Where-Object{[string]$_.project_id-eq$ProjectId})
if($projectMatches.Count-ne 1){throw "ProjectId is not unique in the canonical project registry: $ProjectId"}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
$template=if($TemplateIob){[IO.Path]::GetFullPath($TemplateIob)}else{Join-Path $env:ProgramFiles 'SIMION-2020\examples\quad\quad_monolithic.iob'}
if(-not(Test-Path -LiteralPath $simion -PathType Leaf)){throw "SIMION executable is missing: $simion"}
if(-not(Test-Path -LiteralPath $template -PathType Leaf)){throw "SIMION template IOB is missing: $template"}
if([string]::IsNullOrWhiteSpace($RunId)){
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+"__sim__simion__$($ProjectId.Replace('_','-'))-$DesignProfileId__resolved-l3"
}
$package=New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$ProjectId") -RunId $RunId `
  -Project $ProjectId -Mode 'resolved_design_transport' -Software @('SIMION 2020','Python 3.11') `
  -AdditionalDirectories @('simion')
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$logDir=$package.log_dir;$solverDir=Join-Path $runDir 'simion'
$runConfig=$package.run_config;$summary=$package.summary;$manifestRepoRoot=$repoRoot

try{
  $codeRoot=Join-Path $inputDir 'code'
  foreach($area in @('contracts','multipole','simion')){
    $sourceRoot=Join-Path $repoRoot "common\$area";$destinationRoot=Join-Path $codeRoot "common\$area"
    Get-ChildItem -LiteralPath $sourceRoot -Recurse -File|Where-Object{
      $_.Extension -in @('.py','.json','.ps1','.lua')
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
  $registry=Join-Path $inputDir 'project_registry.json';$descriptor=Join-Path $inputDir 'project.json'
  $profiles=Join-Path $inputDir 'design_profiles.json';$request=Join-Path $inputDir 'multipole_design_request.json'
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
  $referenceComsolManifest=$null;$referenceComsolManifestSha=$null;$referenceComsolSourceRunId=$null
  if(-not[string]::IsNullOrWhiteSpace($ReferenceComsolRunId)){
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      $referenceIdValidation=& $python -m common.contracts.artifact_naming run $ReferenceComsolRunId
      if($LASTEXITCODE-ne 0 -or -not($referenceIdValidation-match '^ARTIFACT_ID=PASS ')){
        throw "Invalid ReferenceComsolRunId: $ReferenceComsolRunId"
      }
      $projectRunsRoot=[IO.Path]::GetFullPath((Join-Path $workspaceRoot "artifacts\projects\$ProjectId\runs"))
      $referenceRunDir=[IO.Path]::GetFullPath((Join-Path $projectRunsRoot $ReferenceComsolRunId))
      if(-not $referenceRunDir.StartsWith(
        $projectRunsRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase
      )){throw "Reference COMSOL run escapes the same-project artifact root: $ReferenceComsolRunId"}
      $referenceManifestOriginal=Join-Path $referenceRunDir 'run_manifest.json'
      if(-not(Test-Path -LiteralPath $referenceManifestOriginal -PathType Leaf)){
        throw "Reference COMSOL run manifest is missing: $referenceManifestOriginal"
      }
      & $python -m common.contracts.verify_run_manifest $referenceManifestOriginal `
        --require-status success --require-local-run-config `
        --require-run-id $ReferenceComsolRunId --require-project $ProjectId `
        --require-mode resolved_design_transport --require-design-profile-id $DesignProfileId `
        --require-parent-resolved-design-sha256 $resolvedHash `
        --require-particle-source-sha256 ([string]$sourceMeta.source_sha256)|Out-Null
      if($LASTEXITCODE-ne 0){throw "Reference COMSOL run verification failed: $ReferenceComsolRunId"}
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    $referenceComsolManifest=Join-Path $inputDir 'reference_comsol_run_manifest.json'
    Copy-Item -LiteralPath $referenceManifestOriginal -Destination $referenceComsolManifest
    $referenceComsolManifestSha=(Get-FileHash -LiteralPath $referenceComsolManifest -Algorithm SHA256).Hash
    $referenceComsolSourceRunId=$ReferenceComsolRunId
  }
  $numerics=Join-Path $inputDir 'solver_numerics.json'
  [ordered]@{schema_version=1;role='multipole_simion_solver_numerics';cell_mm=$CellMm;
    trajectory_quality=$TrajectoryQuality;
    trajectory=[ordered]@{rf_steps_per_period=$RfStepsPerPeriod;maximum_global_time_us=$MaximumTimeUs}}|
    ConvertTo-Json -Depth 5|Set-Content -LiteralPath $numerics -Encoding UTF8
  $evidence=$null
  if(-not[string]::IsNullOrWhiteSpace($EvidenceContractPath)){
    $evidence=Join-Path $inputDir 'evidence_contract.json'
    Copy-Item -LiteralPath ([IO.Path]::GetFullPath($EvidenceContractPath)) -Destination $evidence
  }

  $gem=Join-Path $solverDir 'quad_monolithic.gem';$fly2=Join-Path $solverDir 'quad_monolithic.fly2'
  $states=Join-Path $inputDir 'source_states.lua'
  Push-Location $codeRoot
  try{
    $env:PYTHONPATH=$codeRoot
    & $python -m common.multipole.simion_geometry --resolved-design $resolved --cell-mm $CellMm --output $gem
    if($LASTEXITCODE-ne 0){throw 'SIMION GEM projection failed.'}
    $sourceProjectionArguments=@('-m','common.multipole.simion_particle_source',
      '--particles',$particleSource,'--resolved-design',$resolved,
      '--fly2',$fly2,'--source-states-lua',$states)
    if($sourceFamily){
      $sourceProjectionArguments+=@('--source-family',$sourceFamily,
        '--operating-point',$OperatingPointId,
        '--expected-source-family-sha256',$sourceFamilySha)
    }
    & $python @sourceProjectionArguments
    if($LASTEXITCODE-ne 0){throw 'SIMION particle projection failed.'}
  }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
  Copy-Item -LiteralPath $template -Destination (Join-Path $solverDir 'quad_monolithic.iob')
  Copy-Item -LiteralPath (Join-Path $codeRoot 'common\multipole\simion_transport.lua') `
    -Destination (Join-Path $solverDir 'quad_monolithic.lua')

  $drive=$design.drive;$geometry=$design.geometry_mm;$enclosure=$geometry.enclosure
  $static=$design.static_electrodes_V
  $interfaces=$design.interfaces_mm
  $axialTopology=[string]$design.axial_drive.topology
  $segmented=($axialTopology-eq'segmented_rod_axial_acceleration')
  $endplate=($axialTopology-eq'endplate_potential_step')
  $handoffPlaneMm=[double]$interfaces.exit.connector_z_max_mm
  $detectorPlaneMm=[double]$interfaces.exit.particle_plane_z_mm
  $detectorRadius=if($enclosure.PSObject.Properties.Name-contains'detector_radius_mm'){
    [double]$enclosure.detector_radius_mm
  }else{[double]$interfaces.exit.aperture_radius_mm}
  $rectangular=([string]$enclosure.model-eq'rectangular_reference_enclosure_v1')
  $origin=if($rectangular){0}else{[double]$enclosure.shield_outer_radius_mm}
  $zShift=if($rectangular){0}else{-[double]$enclosure.vacuum_z_min_mm}
  if($rectangular){
    $entranceVoltage=[double]$static.entrance_plate_and_connector
    $exitVoltage=[double]$static.exit_enclosure_and_connector
    $detectorVoltage=[double]$static.detector
  }else{
    $entranceVoltage=[double]$static.shield_and_entrance_endcap_and_connector
    $exitVoltage=[double]$static.exit_endcap_and_connector
    $detectorVoltage=$exitVoltage
  }
  $segmentedLua='';$groundElectrodeId=3;$outputElectrodeId=4
  $detectorElectrodeId=if($rectangular){5}else{0}
  if($segmented){
    $segments=$design.segmentation.segmented_rod_array
    $entries=@($segments.electrodes|ForEach-Object{
      "{electrode_id=$([int]$_.electrode_id),electrode_group=$([int]$_.electrode_group),common_mode_v=$([double]$_.common_mode_V)}"
    })
    $segmentedLua="segmented_rod_electrodes={$($entries -join ',')},"
    $groundElectrodeId=2*[int]$segments.segment_count+1;$outputElectrodeId=$groundElectrodeId+1
    if($rectangular){$detectorElectrodeId=$outputElectrodeId+1}
  }
  $provenance=[ordered]@{parent_resolved_design_sha256=$resolvedHash;particle_source_sha256=$sourceMeta.source_sha256;
    source_family_sha256=$sourceFamilySha;operating_point_id=$(if($sourceFamily){$OperatingPointId}else{$null});
    particle_source_operating_point_binding=$sourceMeta.operating_point_binding}
  $runInputs=[ordered]@{project_registry=$registry;project_descriptor=$descriptor;design_profiles=$profiles;
    design_profile_resolution=$profileResolution;design_request=$request;design_variables=$variables;
    optimization_envelope=$envelope;multipole_resolved_design=$resolved;particle_source=$particleSource;
    particle_source_metadata=$sourceMetadata;particle_source_family=$sourceFamily;
    solver_numerics=$numerics;code_inventory=$codeInventory;
    evidence_contract=$evidence;simion_gem=$gem;simion_fly2=$fly2}
  if($referenceComsolManifest){
    $provenance.reference_comsol_run_manifest_sha256=$referenceComsolManifestSha
    $provenance.reference_comsol_source_run_id=$referenceComsolSourceRunId
    $runInputs.reference_comsol_run_manifest=$referenceComsolManifest
  }
  [ordered]@{schema_version=1;role='multipole_resolved_simion_run_config';run_id=$RunId;project=$ProjectId;
    mode='resolved_design_transport';project_root=$profile.project_root;
    provenance=$provenance;inputs=$runInputs;
    parameters=[ordered]@{model_level='L3';design_profile_id=$DesignProfileId;
      operating_point_id=$(if($sourceFamily){$OperatingPointId}else{$null});
      reference_comsol_run_id=$ReferenceComsolRunId};
    formal_gate_passed=$false}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $runConfig -Encoding UTF8

  function Invoke-SimionStep([string]$name,[string[]]$arguments){
    $stdout=Join-Path $logDir "simion_stdout__$name.txt";$stderr=Join-Path $logDir "simion_stderr__$name.txt"
    $process=Start-Process -FilePath $simion -ArgumentList $arguments -WorkingDirectory $solverDir `
      -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    if($process.ExitCode-ne 0){throw "SIMION $name failed with exit code $($process.ExitCode)."}
  }
  Invoke-SimionStep 'gem2pa' @('--nogui','--noprompt','gem2pa','quad_monolithic.gem','quad_monolithic.pa#')
  Invoke-SimionStep 'refine' @('--nogui','--noprompt','refine','quad_monolithic.pa#')
  Start-Sleep -Milliseconds 500

  function Invoke-TransportCase([string]$name,[int]$rfScale,[int]$axialScale){
    $caseState=Join-Path $resultDir "particle_states__$name.csv"
    $caseTrajectory=Join-Path $resultDir "trajectory_samples__$name.csv"
    $caseSummary=Join-Path $resultDir "simion_summary__$name.json"
    $luaConfig=Join-Path $inputDir "simion_config__$name.lua"
    $surfaceToleranceMm=[Math]::Max(1e-6*$CellMm,1e-9)
    $phaseDeg=[double]$drive.phase_rad*180/[Math]::PI
    @"
return {iob=[[$(Join-Path $solverDir 'quad_monolithic.iob')]], fly2=[[$fly2]], source_states=dofile([[$states]]),
trajectory_csv=[[$caseTrajectory]], particle_state_csv=[[$caseState]], summary_json=[[$caseSummary]],
mode="resolved_design_transport", operating_point="$name", parent_resolved_design_sha256="$resolvedHash",
trajectory_quality=$TrajectoryQuality, rf_steps_per_period=$RfStepsPerPeriod, waveform="$($drive.waveform)",
rf_peak_v=$($drive.rf_amplitude_V_zero_to_peak_per_group), rf_scale=$rfScale, axial_scale=$axialScale,
scale_static_boundaries=$($endplate.ToString().ToLowerInvariant()),
dc_amplitude_v=$($drive.dc_amplitude_V_per_group), frequency_hz=$($drive.frequency_Hz), phase_deg=$phaseDeg,
axis_voltage_v=$($drive.common_mode_offset_V), entrance_voltage_v=$entranceVoltage,
exit_voltage_v=$exitVoltage, detector_voltage_v=$detectorVoltage,
has_electrode_4=true, has_electrode_5=$($rectangular.ToString().ToLowerInvariant()),
$segmentedLua ground_electrode_id=$groundElectrodeId, ground_reference_v=$entranceVoltage,
output_electrode_id=$outputElectrodeId, output_reference_v=$exitVoltage,
detector_electrode_id=$detectorElectrodeId,
maximum_time_us=$MaximumTimeUs, trajectory_plane_step_mm=$CellMm,
rod_z_min_mm=$($geometry.rod_z_min), rod_z_max_mm=$($geometry.rod_z_max),
rod_exit_plane_mm=$($geometry.rod_z_max), handoff_plane_mm=$handoffPlaneMm,
    detector_crossing_threshold_mm=$($detectorPlaneMm-2*$CellMm-$surfaceToleranceMm),
detector_radius_mm=$detectorRadius, radial_escape_radius_mm=$($enclosure.working_region_radius_mm),
detector_is_handoff=false, axial_axis="x", origin_x_mm=$zShift, origin_y_mm=$(-$origin),
origin_z_mm=$origin, backward_escape_plane_mm=$($enclosure.vacuum_z_min_mm)}
"@|Set-Content -LiteralPath $luaConfig -Encoding ASCII
    $env:MULTIPOLE_SIMION_RUN_CONFIG_LUA=$luaConfig
    try{
      Invoke-SimionStep "fly__$name" @('--nogui','--noprompt','fly','--remove-pas=3',
        '--trajectory-quality',[string]$TrajectoryQuality,'--particles',$fly2,'--programs','1',
        '--retain-trajectories','0','--adjustable',"transport_rf_steps_per_period=$RfStepsPerPeriod",
        (Join-Path $solverDir 'quad_monolithic.iob'))
    }finally{Remove-Item Env:MULTIPOLE_SIMION_RUN_CONFIG_LUA -ErrorAction SilentlyContinue}
    $stateReport=Join-Path $resultDir "particle_state_contract__$name.json"
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      & $python -m common.contracts.particle_state --state $caseState --particles $particleSource `
        --source-format canonical --frequency-hz $drive.frequency_Hz --phase-rad $drive.phase_rad `
        --rod-exit-mm $geometry.rod_z_max --handoff-mm $handoffPlaneMm `
        --solver 'SIMION 2020' --output $stateReport|Out-Null
      if($LASTEXITCODE-ne 0){throw "SIMION $name particle-state contract failed."}
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    return Get-Content -LiteralPath $caseSummary -Raw -Encoding UTF8|ConvertFrom-Json
  }

  if($segmented -or $endplate){
    if($endplate){
      $primaryName='endplate_acceleration_rf_on';$controlName='zero_endplate_drop_rf_on'
    }else{
      $primaryName='axial_acceleration_rf_on';$controlName='zero_axial_drop_rf_on'
    }
    $primary=Invoke-TransportCase $primaryName 1 1;$control=Invoke-TransportCase $controlName 1 0
    $metrics=Join-Path $resultDir $(if($endplate){'endplate_acceleration_metrics.json'}else{'axial_acceleration_metrics.json'})
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      & $python -m common.multipole.analyze_simion_axial_acceleration `
        --accelerated-state (Join-Path $resultDir "particle_states__$primaryName.csv") `
        --control-state (Join-Path $resultDir "particle_states__$controlName.csv") `
        --resolved-contract $resolved --output $metrics
      if($LASTEXITCODE-ne 0){throw 'SIMION axial-drive metrics analysis failed.'}
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    $metricsDoc=Get-Content -LiteralPath $metrics -Raw -Encoding UTF8|ConvertFrom-Json
    if(
      [Math]::Abs([double]$metricsDoc.accelerated_transmission-[double]$primary.transmission)-gt 1e-12 -or
      [Math]::Abs([double]$metricsDoc.control_transmission-[double]$control.transmission)-gt 1e-12
    ){throw 'SIMION paired metrics transmission differs from the raw case summaries.'}
  }else{
    $primaryName='rf_on';$controlName='zero_rf_control'
    $primary=Invoke-TransportCase $primaryName 1 0;$control=Invoke-TransportCase $controlName 0 0
    $metrics=Join-Path $resultDir 'finite_3d_transport_metrics.json'
    [ordered]@{schema_version=1;role='multipole_simion_finite_3d_transport_metrics';status='UNQUALIFIED';
      project_id=$ProjectId;parent_resolved_design_sha256=$resolvedHash;model_level='L3';
      primary_case_id=$primaryName;control_case_id=$controlName;
      cases=[ordered]@{rf_on=$primary;zero_rf_control=$control};
      rf_minus_zero_transmission=($primary.transmission-$control.transmission);
      claim_limit='Resolved-design SIMION metrics only; no evidence claim.'}|
      ConvertTo-Json -Depth 8|Set-Content -LiteralPath $metrics -Encoding UTF8
  }
  $qualification='UNQUALIFIED';$evaluation=Join-Path $resultDir 'evidence_evaluation.json'
  if($evidence){
    Push-Location $codeRoot
    try{
      $env:PYTHONPATH=$codeRoot
      & $python -m common.multipole.evaluate_transport_evidence --metrics $metrics --evidence $evidence `
        --project-id $ProjectId --design-profile-id $DesignProfileId --output $evaluation
      $evidenceExit=$LASTEXITCODE
    }finally{Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue;Pop-Location}
    if($evidenceExit-ne 0){throw 'SIMION evidence contract gate failed.'}
    $qualification='PASS'
  }
  [ordered]@{schema_version=1;role='multipole_simion_finite_3d_transport_summary';status='success';
    qualification_status=$qualification;project_id=$ProjectId;design_profile_id=$DesignProfileId;
    parent_resolved_design_sha256=$resolvedHash;primary_transmission=$primary.transmission;
    control_transmission=$control.transmission;model_level='L3';formal_gate_passed=$false}|
    ConvertTo-Json -Depth 5|Set-Content -LiteralPath $summary -Encoding UTF8
  $outputs=@($summary,$metrics,(Join-Path $solverDir 'quad_monolithic.pa0'),
    (Join-Path $solverDir 'quad_monolithic.iob'),$gem,$fly2,
    (Join-Path $resultDir "simion_summary__$primaryName.json"),
    (Join-Path $resultDir "simion_summary__$controlName.json"),
    (Join-Path $resultDir "particle_states__$primaryName.csv"),
    (Join-Path $resultDir "particle_states__$controlName.csv"),
    (Join-Path $resultDir "trajectory_samples__$primaryName.csv"),
    (Join-Path $resultDir "trajectory_samples__$controlName.csv"),
    (Join-Path $resultDir "particle_state_contract__$primaryName.json"),
    (Join-Path $resultDir "particle_state_contract__$controlName.json"))
  $outputs+=@(Get-ChildItem -LiteralPath $logDir -Recurse -File|Select-Object -ExpandProperty FullName)
  if(Test-Path -LiteralPath $evaluation){$outputs+=$evaluation}
  Write-VerifiedRunManifest -Python $python -RepoRoot $manifestRepoRoot -RunConfig $runConfig `
    -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  Write-Output "MULTIPOLE_SIMION_RESOLVED=PASS PROJECT=$ProjectId PROFILE=$DesignProfileId RUN_ID=$RunId PARENT_SHA256=$resolvedHash QUALIFICATION=$qualification"
}catch{
  Complete-FailedRun -Python $python -RepoRoot $manifestRepoRoot -RunConfig $runConfig -Summary $summary `
    -SummaryRole 'multipole_simion_finite_3d_transport_summary' -Reason $_.Exception.Message `
    -Software @('SIMION 2020','Python 3.11')
  throw
}
