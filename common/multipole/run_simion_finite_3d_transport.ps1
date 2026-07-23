[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$ProjectRoot,
  [ValidateSet('high-order','quadrupole')][string]$Adapter='high-order',
  [string]$FieldScreenRunId='',
  [string]$RunId='',
  [string]$ReferenceComsolRunId='',
  [string]$ParticleTablePath='',
  [double]$CellMm=0.4,
  [double]$EntranceConnectorLengthMm=[double]::NaN,
  [double]$ExitConnectorLengthMm=[double]::NaN,
  [string]$SimionExe='',
  [string]$TemplateIob='',
  [string]$AxialAccelerationContractPath='',
  [switch]$AxialAcceleration,
  [switch]$EndplateAcceleration
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRootPath=(Resolve-Path -LiteralPath $ProjectRoot).Path
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=Join-Path $repoRoot '.venv\Scripts\python.exe'
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
$templateIob=if($TemplateIob){[IO.Path]::GetFullPath($TemplateIob)}else{Join-Path $env:ProgramFiles 'SIMION-2020\examples\quad\quad_monolithic.iob'}
if(-not(Test-Path -LiteralPath $simion -PathType Leaf)){throw "SIMION executable is missing: $simion"}
if(-not(Test-Path -LiteralPath $templateIob -PathType Leaf)){throw "SIMION template IOB is missing: $templateIob"}
$project=Get-Content -LiteralPath (Join-Path $projectRootPath 'config\project.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$projectId=[string]$project.project_id
if($AxialAcceleration -and $EndplateAcceleration){throw 'Select only one acceleration mode.'}
$accelerationEnabled=$AxialAcceleration -or $EndplateAcceleration
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $runLabel=if($AxialAcceleration){'axial-acceleration'}elseif($EndplateAcceleration){'endplate-acceleration'}else{'finite-3d'}
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+"__sim__simion__$($projectId.Replace('_','-'))-$runLabel__l3-n100"
}
$sourceDir='';$sourceManifest='';$sourceSamples='';$sourceContract=''
if($Adapter -eq 'high-order'){
  if([string]::IsNullOrWhiteSpace($FieldScreenRunId)){throw 'High-order SIMION runs require FieldScreenRunId.'}
  $sourceDir=Join-Path $workspaceRoot "artifacts\projects\$projectId\runs\$FieldScreenRunId"
  $sourceManifest=Join-Path $sourceDir 'run_manifest.json'
  $sourceSamples=Join-Path $sourceDir 'results\round_rod_potential_samples.csv'
  $sourceContract=Join-Path $sourceDir 'inputs\round_rod_field_screen.json'
  if (!(Test-Path -LiteralPath $sourceManifest)){throw "Field-screen run is missing: $FieldScreenRunId"}
}elseif([string]::IsNullOrWhiteSpace($ParticleTablePath)){
  $ParticleTablePath=Join-Path $projectRootPath 'config\particles\official_fixed_100.ion'
}
$artifactRoot=Join-Path $workspaceRoot "artifacts\projects\$projectId"
$runMode=if($AxialAcceleration){'axial_acceleration_reference'}elseif($EndplateAcceleration){'endplate_acceleration_reference'}elseif($Adapter-eq'quadrupole'){'transport_no_collision'}else{'finite_3d_no_collision'}
$package=New-RunPackage -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RunId $RunId -Project $projectId `
  -Mode $runMode -Software @('SIMION 2020','Python 3.11') -AdditionalDirectories @('simion')
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir;$logDir=$package.log_dir
$solverDir=Join-Path $runDir 'simion';$runConfig=$package.run_config;$summary=$package.summary
try {
$baseline=Join-Path $inputDir 'baseline.json'; $finite=Join-Path $inputDir 'finite_3d_transport.json'; $resolved=Join-Path $inputDir 'finite_3d_transport_resolved.json'
$operating=Join-Path $inputDir 'family_operating_contract.json'; $fieldMetrics=Join-Path $inputDir 'round_rod_field_screen_metrics.json'; $geometry=Join-Path $inputDir 'round_rod_geometry.json'; $particles=Join-Path $inputDir 'particle_source.csv'
$axialBase=Join-Path $inputDir 'axial_acceleration_base.json'; $axialResolved=Join-Path $inputDir 'axial_acceleration_resolved.json'; $segmentedRods=Join-Path $inputDir 'segmented_round_rods.json'
$endplateBase=Join-Path $inputDir 'endplate_acceleration_base.json';$endplateResolved=Join-Path $inputDir 'endplate_acceleration_resolved.json'
$interfaceContract=Join-Path $inputDir 'interface_contract.json'
$pairingBase=Join-Path $inputDir 'axial_pairing_base.json';$pairingResolved=Join-Path $inputDir 'axial_pairing_resolved.json'
$pairAudit=Join-Path $resultDir 'axial_pairing_audit.json';$pairingEnabled=$false;$pairingResolvedDoc=$null
if($AxialAcceleration){
  $axialContractSource=if($AxialAccelerationContractPath){[IO.Path]::GetFullPath($AxialAccelerationContractPath)}else{Join-Path $projectRootPath 'config\modes\axial_acceleration_reference.json'}
  if(-not(Test-Path -LiteralPath $axialContractSource -PathType Leaf)){throw "Axial-acceleration contract is missing: $axialContractSource"}
  Copy-Item -LiteralPath $axialContractSource -Destination $axialBase
  if($Adapter-eq'quadrupole'){
    $pairingCandidate=Join-Path $projectRootPath 'config\modes\axial_acceleration_explicit_paired_diagnostic.json'
    if(Test-Path -LiteralPath $pairingCandidate -PathType Leaf){
      $pairingCandidateDoc=Get-Content -LiteralPath $pairingCandidate -Raw -Encoding UTF8|ConvertFrom-Json
      if([IO.Path]::GetFileName($axialContractSource)-eq[string]$pairingCandidateDoc.axial_contract_file){
        Copy-Item -LiteralPath $pairingCandidate -Destination $pairingBase
        $pairingEnabled=$true
      }
    }
  }
}
if($EndplateAcceleration){Copy-Item -LiteralPath (Join-Path $projectRootPath 'config\modes\endplate_acceleration_reference.json') -Destination $endplateBase}
if($Adapter-eq'quadrupole'){
  Copy-Item -LiteralPath (Join-Path $projectRootPath 'config\interface_contract.json') -Destination $interfaceContract
}
$projectBaseline=Join-Path $projectRootPath 'config\baseline.json'
Push-Location $repoRoot
try{
  if($Adapter-eq'high-order'){
    Copy-Item -LiteralPath $projectBaseline -Destination $baseline
    Copy-Item -LiteralPath (Join-Path $projectRootPath 'config\finite_3d_transport.json') -Destination $finite
    & $python (Join-Path $repoRoot 'common\multipole\analyze_round_rod_screen.py') --samples $sourceSamples --contract $sourceContract --output $fieldMetrics
    if($LASTEXITCODE-ne 0){throw 'Could not freeze selected round-rod geometry.'}
    & $python -m common.multipole.resolve_family_operating_contract --adapter high-order --baseline $baseline --output $operating
    if($LASTEXITCODE-ne 0){throw 'Operating-contract resolution failed.'}
    $resolverArguments=@('-m','common.multipole.resolve_finite_3d_contract','--baseline',$baseline,'--contract',$finite,'--output',$resolved)
    if(-not [double]::IsNaN($EntranceConnectorLengthMm)){$resolverArguments+=@('--entrance-connector-length-mm',[string]$EntranceConnectorLengthMm)}
    if(-not [double]::IsNaN($ExitConnectorLengthMm)){$resolverArguments+=@('--exit-connector-length-mm',[string]$ExitConnectorLengthMm)}
    & $python @resolverArguments
    if($LASTEXITCODE-ne 0){throw 'Finite-3D contract resolution failed.'}
    & $python -m common.multipole.round_rod_geometry --baseline $baseline --finite-3d $resolved --field-metrics $fieldMetrics --output $geometry
    if($LASTEXITCODE-ne 0){throw 'Round-rod geometry resolution failed.'}
    $resolvedDoc=Get-Content -LiteralPath $resolved -Raw -Encoding UTF8|ConvertFrom-Json
    & $python -m common.multipole.generate_particle_source --baseline $baseline --release-z-mm ([double]$resolvedDoc.derived_geometry_mm.source_z) --output $particles
    if($LASTEXITCODE-ne 0){throw 'Particle-source generation failed.'}
  }else{
    if(-not(Test-Path -LiteralPath $ParticleTablePath -PathType Leaf)){throw "Particle table is missing: $ParticleTablePath"}
    $projectResolved=Join-Path $projectRootPath 'config\resolved_geometry.json'
    $projectMode=Join-Path $projectRootPath 'config\modes\transport_no_collision.json'
    & $python -m common.multipole.resolve_family_operating_contract --adapter quadrupole --baseline $projectBaseline --mode $projectMode --output $operating
    if($LASTEXITCODE-ne 0){throw 'Quadrupole operating-contract resolution failed.'}
    $adapterArguments=@('-m','common.multipole.prepare_quadrupole_finite_3d_inputs','--resolved',$projectResolved,
      '--operating',$operating,'--particles',$ParticleTablePath,'--baseline-output',$baseline,'--contract-output',$resolved,
      '--field-metrics-output',$fieldMetrics,'--round-rod-geometry-output',$geometry,'--particle-source-output',$particles)
    if(-not [double]::IsNaN($EntranceConnectorLengthMm)){$adapterArguments+=@('--entrance-connector-length-mm',[string]$EntranceConnectorLengthMm)}
    if(-not [double]::IsNaN($ExitConnectorLengthMm)){$adapterArguments+=@('--exit-connector-length-mm',[string]$ExitConnectorLengthMm)}
    & $python @adapterArguments
    if($LASTEXITCODE-ne 0){throw 'Quadrupole finite-3D input adaptation failed.'}
    Copy-Item -LiteralPath $resolved -Destination $finite
  }
}finally{Pop-Location}
$resolvedDoc=Get-Content -LiteralPath $resolved -Raw -Encoding UTF8|ConvertFrom-Json
$baselineDoc=Get-Content -LiteralPath $baseline -Raw -Encoding UTF8|ConvertFrom-Json
if($AxialAcceleration){
  & $python -m common.multipole.axial_acceleration --contract $axialBase --rod-geometry $geometry `
    --source-energy-ev ([double]$baselineDoc.particle_source.kinetic_energy_eV) --charge-state ([int]$baselineDoc.particle_source.charge_state) `
    --output $axialResolved --segmented-rods-output $segmentedRods
  if($LASTEXITCODE-ne 0){throw 'Axial-acceleration contract resolution failed.'}
}
if($EndplateAcceleration){
  & $python -m common.multipole.endplate_acceleration --contract $endplateBase `
    --source-energy-ev ([double]$baselineDoc.particle_source.kinetic_energy_eV) --charge-state ([int]$baselineDoc.particle_source.charge_state) `
    --output $endplateResolved
  if($LASTEXITCODE-ne 0){throw 'Endplate-acceleration contract resolution failed.'}
}
$gem=Join-Path $solverDir 'quad_monolithic.gem'; $fly2=Join-Path $solverDir 'quad_monolithic.fly2'; $states=Join-Path $inputDir 'source_states.lua'
$geometryArguments=@('-m','common.multipole.simion_geometry','--geometry',$geometry,'--cell-mm',[string]$CellMm,'--output',$gem)
if($AxialAcceleration){$geometryArguments+=@('--segmented-rods',$segmentedRods)}
if($EndplateAcceleration){$geometryArguments+=@('--separate-output-electrode')}
& $python @geometryArguments
if($LASTEXITCODE-ne 0){throw 'SIMION GEM export failed.'}
if($Adapter-eq'quadrupole'){
  & $python -m common.multipole.simion_particle_source --ion-table $ParticleTablePath --fly2 $fly2 --source-states-lua $states
}else{
  & $python -m common.multipole.simion_particle_source --particles $particles --baseline $baseline --geometry $geometry --fly2 $fly2 --source-states-lua $states
}
if($LASTEXITCODE-ne 0){throw 'SIMION particle export failed.'}
Copy-Item -LiteralPath $templateIob -Destination (Join-Path $solverDir 'quad_monolithic.iob')
Copy-Item -LiteralPath (Join-Path $repoRoot 'common\multipole\simion_transport.lua') -Destination (Join-Path $solverDir 'quad_monolithic.lua')
$geometryDoc=Get-Content -LiteralPath $geometry -Raw -Encoding UTF8|ConvertFrom-Json
$operatingDoc=Get-Content -LiteralPath $operating -Raw -Encoding UTF8|ConvertFrom-Json
$handoffPlaneMm=[double]$resolvedDoc.derived_geometry_mm.exit_plate_z_max
$detectorPlaneMm=[double]$resolvedDoc.derived_geometry_mm.detector_z
if($Adapter-eq'quadrupole'){
  $interfaceDoc=Get-Content -LiteralPath $interfaceContract -Raw -Encoding UTF8|ConvertFrom-Json
  $handoffPlaneMm=[double]$interfaceDoc.planes.handoff.z_mm
  if([Math]::Abs($handoffPlaneMm-[double]$resolvedDoc.derived_geometry_mm.exit_plate_z_max)-gt 1e-12){
    throw 'Versioned quadrupole handoff plane differs from the resolved exit interface.'
  }
}
if([Math]::Abs($handoffPlaneMm-$detectorPlaneMm)-le 1e-12){
  throw 'Physical handoff plane must remain distinct from the standalone detector.'
}
if($pairingEnabled){
  & $python -m common.multipole.axial_pairing --resolve --contract $pairingBase `
    --interface $interfaceContract --resolved-geometry $resolved `
    --selected-axial-contract-name ([IO.Path]::GetFileName($axialContractSource)) `
    --source $particles --source-count ([int]$baselineDoc.particle_source.count) `
    --source-mean-energy-ev ([double]$baselineDoc.particle_source.kinetic_energy_eV) `
    --project-id $projectId --output $pairingResolved
  if($LASTEXITCODE-ne 0){throw 'Axial paired-source contract resolution failed.'}
  $pairingResolvedDoc=Get-Content -LiteralPath $pairingResolved -Raw -Encoding UTF8|ConvertFrom-Json
}
[ordered]@{schema_version=1;role='multipole_simion_finite_3d_run_config';run_id=$RunId;project=$projectId;mode=$runMode;
  operating_point='official_100amu_2eV';rf_peak_v=[double]$operatingDoc.voltage.rf_amplitude_V_zero_to_peak_per_group;
  frequency_hz=[double]$operatingDoc.voltage.frequency_Hz;
  inputs=[ordered]@{baseline=$baseline;finite_3d_resolved=$resolved;family_operating_contract=$operating;round_rod_geometry=$geometry;
    particle_source=$particles;particle_table=$(if($Adapter-eq'quadrupole'){$ParticleTablePath}else{$null});
    field_screen_manifest=$(if($Adapter-eq'high-order'){$sourceManifest}else{$null});
    interface_contract=$(if($Adapter-eq'quadrupole'){$interfaceContract}else{$null});
    axial_acceleration_resolved=$(if($AxialAcceleration){$axialResolved}else{$null});segmented_round_rods=$(if($AxialAcceleration){$segmentedRods}else{$null});endplate_acceleration_resolved=$(if($EndplateAcceleration){$endplateResolved}else{$null});
    axial_pairing_base=$(if($pairingEnabled){$pairingBase}else{$null});axial_pairing_resolved=$(if($pairingEnabled){$pairingResolved}else{$null})};
  parameters=[ordered]@{adapter=$Adapter;simion_cell_mm=$CellMm;physical_handoff_z_mm=$handoffPlaneMm;standalone_detector_z_mm=$detectorPlaneMm;
    paired_rf_zero_control=(-not $accelerationEnabled);paired_axial_zero_control=[bool]$AxialAcceleration;paired_endplate_zero_control=[bool]$EndplateAcceleration;
    pair_id=$(if($pairingEnabled){[string]$pairingResolvedDoc.pair_id}else{$null});reference_comsol_run_id=$ReferenceComsolRunId};
  formal_gate_passed=$false}|ConvertTo-Json -Depth 7|Set-Content -LiteralPath $runConfig -Encoding UTF8
function Invoke-SimionBuildStep([string]$name,[string[]]$commandArguments){
  $stdout=Join-Path $logDir "simion_stdout__$name.txt"
  $stderr=Join-Path $logDir "simion_stderr__$name.txt"
  $process=Start-Process -FilePath $simion -ArgumentList $commandArguments -WorkingDirectory $solverDir `
    -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
  if($process.ExitCode-ne 0){
    Get-Content -LiteralPath $stderr -Encoding UTF8 -ErrorAction SilentlyContinue
    throw "SIMION $name failed with exit code $($process.ExitCode)."
  }
}
Invoke-SimionBuildStep 'gem2pa' @('--nogui','--noprompt','gem2pa','quad_monolithic.gem','quad_monolithic.pa#')
Invoke-SimionBuildStep 'refine' @('--nogui','--noprompt','refine','quad_monolithic.pa#')
# SIMION 2020 can exit its refine command a few tens of milliseconds before
# Windows releases every PA handle.  The measured failure launched Fly'm 40 ms
# later and hit SIMION's internal "potential arrays are locked" guard.
Start-Sleep -Milliseconds 500

$segmentedLua=''; $groundElectrodeId=0; $outputElectrodeId=0; $outputReferenceV=0
if($AxialAcceleration){
  $segmentedDoc=Get-Content -LiteralPath $segmentedRods -Raw -Encoding UTF8|ConvertFrom-Json
  $axialDoc=Get-Content -LiteralPath $axialResolved -Raw -Encoding UTF8|ConvertFrom-Json
  $entries=@($segmentedDoc.electrodes|ForEach-Object{
    "{electrode_id=$([int]$_.electrode_id),electrode_group=$([int]$_.electrode_group),common_mode_v=$([double]$_.common_mode_V)}"
  })
  $segmentedLua="segmented_rod_electrodes={$($entries -join ',')},"
  $groundElectrodeId=2*[int]$segmentedDoc.segment_count+1
  $outputElectrodeId=$groundElectrodeId+1
  $outputReferenceV=[double]$axialDoc.output_reference_V
}

function Invoke-TransportCase([string]$name,[int]$rfScale,[int]$axialScale,[double]$exitVoltage){
  $pairArm=$null
  if($pairingEnabled){
    $armMatches=@($pairingResolvedDoc.arms|Where-Object{[string]$_.case_id-eq$name})
    if($armMatches.Count-ne 1){throw "SIMION paired arm metadata is missing for $name."}
    $pairArm=$armMatches[0]
    if($rfScale-ne[int]$pairArm.rf_scale -or $axialScale-ne[int]$pairArm.axial_scale -or $exitVoltage-ne 0){
      throw "SIMION paired arms may vary only the frozen axial scale: $name."
    }
  }
  $caseState=Join-Path $resultDir "particle_states__$name.csv"; $caseTrajectory=Join-Path $resultDir "trajectory_samples__$name.csv"; $caseSummary=Join-Path $resultDir "simion_summary__$name.json"; $luaConfig=Join-Path $inputDir "simion_config__$name.lua"
  $outer=[double]$geometryDoc.grounded_enclosure_mm.shield_outer_radius
  $rectangular=($geometryDoc.grounded_enclosure_mm.PSObject.Properties.Name -contains 'model') -and
    ($geometryDoc.grounded_enclosure_mm.model -eq 'rectangular_reference_enclosure_v1')
  $zShift=if($rectangular){0}else{-[double]$geometryDoc.grounded_enclosure_mm.vacuum_z_min}
  $transverseOrigin=if($rectangular){0}else{$outer}
  $detectorRadius=if($geometryDoc.interfaces_mm.PSObject.Properties.Name-contains'detector_radius'){[double]$geometryDoc.interfaces_mm.detector_radius}else{[double]$geometryDoc.interfaces_mm.exit_aperture_radius}
  $detectorVoltage=if($rectangular){$exitVoltage}else{0}
  $surfaceToleranceMm=[Math]::Max(1e-6*$CellMm,1e-9)
  $text=@"
return {iob=[[$(Join-Path $solverDir 'quad_monolithic.iob')]], fly2=[[$fly2]], source_states=dofile([[$states]]),
trajectory_csv=[[$caseTrajectory]], particle_state_csv=[[$caseState]], summary_json=[[$caseSummary]],
mode="$runMode", operating_point="$name", trajectory_quality=10, rf_steps_per_period=$($resolvedDoc.trajectory.rf_steps_per_period),
rf_peak_v=$($operatingDoc.voltage.rf_amplitude_V_zero_to_peak_per_group), rf_scale=$rfScale, axial_scale=$axialScale, dc_amplitude_v=$($operatingDoc.voltage.dc_amplitude_V_per_group), frequency_hz=$($operatingDoc.voltage.frequency_Hz), phase_deg=$([double]$operatingDoc.voltage.phase_rad*180/[Math]::PI),
axis_voltage_v=$($operatingDoc.voltage.common_mode_offset_V), entrance_voltage_v=0, exit_voltage_v=$exitVoltage, detector_voltage_v=$detectorVoltage, has_electrode_4=$(if($EndplateAcceleration){'true'}else{'false'}), has_electrode_5=false,
$segmentedLua ground_electrode_id=$groundElectrodeId, output_electrode_id=$outputElectrodeId, output_reference_v=$outputReferenceV,
maximum_time_us=$($resolvedDoc.trajectory.maximum_global_time_us), trajectory_plane_step_mm=$CellMm,
rod_z_min_mm=$($geometryDoc.array_mm.rods[0].z_min_mm), rod_z_max_mm=$($geometryDoc.array_mm.rods[0].z_max_mm),
rod_exit_plane_mm=$($geometryDoc.array_mm.rods[0].z_max_mm), handoff_plane_mm=$handoffPlaneMm,
detector_crossing_threshold_mm=$([double]$geometryDoc.interfaces_mm.detector_z-$CellMm-$surfaceToleranceMm), detector_radius_mm=$detectorRadius, radial_escape_radius_mm=$($geometryDoc.grounded_enclosure_mm.shield_inner_radius),
detector_is_handoff=false,
axial_axis="x", origin_x_mm=$zShift, origin_y_mm=$(-$transverseOrigin), origin_z_mm=$transverseOrigin, backward_escape_plane_mm=$($geometryDoc.grounded_enclosure_mm.vacuum_z_min)}
"@
  $text|Set-Content -LiteralPath $luaConfig -Encoding ASCII
  $env:MULTIPOLE_SIMION_RUN_CONFIG_LUA=$luaConfig
  $stdout=Join-Path $logDir "simion_stdout__$name.txt"; $stderr=Join-Path $logDir "simion_stderr__$name.txt"
  try{
    $flyArguments=@(
      '--nogui','--noprompt','fly','--remove-pas=3','--trajectory-quality','10',
      '--particles',$fly2,'--programs','1','--retain-trajectories','0',
      '--adjustable',"transport_rf_steps_per_period=$($resolvedDoc.trajectory.rf_steps_per_period)",
      (Join-Path $solverDir 'quad_monolithic.iob')
    )
    $process=Start-Process -FilePath $simion -ArgumentList $flyArguments -WorkingDirectory $solverDir `
      -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    if($process.ExitCode-ne 0){Get-Content -LiteralPath $stderr -Encoding UTF8; throw "SIMION $name fly failed."}
  }finally{Remove-Item Env:MULTIPOLE_SIMION_RUN_CONFIG_LUA -ErrorAction SilentlyContinue}
  $stateReport=Join-Path $resultDir "particle_state_contract__$name.json"
  Push-Location $repoRoot
  try{
    if($Adapter-eq'quadrupole'){
      & $python -m common.contracts.particle_state --state $caseState --particles $ParticleTablePath --source-format ion11 `
        --contract (Join-Path $projectRootPath 'config\interface_contract.json') `
        --frequency-hz $operatingDoc.voltage.frequency_Hz --phase-rad $operatingDoc.voltage.phase_rad `
        --solver 'SIMION 2020' --output $stateReport | Out-Null
    }else{
      & $python -m common.contracts.particle_state --state $caseState --particles $particles --source-format canonical `
          --mass-amu $baselineDoc.particle_source.mass_amu `
        --frequency-hz $operatingDoc.voltage.frequency_Hz --phase-rad $operatingDoc.voltage.phase_rad `
        --rod-exit-mm $geometryDoc.array_mm.rods[0].z_max_mm --handoff-mm $handoffPlaneMm `
        --solver 'SIMION 2020' --output $stateReport | Out-Null
    }
    if($LASTEXITCODE-ne 0){throw "SIMION $name particle-state contract failed."}
  }finally{Pop-Location}
  $caseSummaryDoc=Get-Content -LiteralPath $caseSummary -Raw -Encoding UTF8|ConvertFrom-Json
  if($pairingEnabled){
    $pairMetadata=[ordered]@{pair_id=[string]$pairingResolvedDoc.pair_id;arm_id=[string]$pairArm.arm_id;
      source_particle_sha256=[string]$pairingResolvedDoc.source.particle_source_sha256;
      axial_scale=[int]$pairArm.axial_scale;rf_scale=[int]$pairArm.rf_scale;rf_field_on=([int]$pairArm.rf_scale-eq 1);
      physical_handoff_z_mm=$handoffPlaneMm}
    $stateReportDoc=Get-Content -LiteralPath $stateReport -Raw -Encoding UTF8|ConvertFrom-Json
    $stateReportDoc|Add-Member -NotePropertyName pairing -NotePropertyValue $pairMetadata
    $stateReportDoc|ConvertTo-Json -Depth 7|Set-Content -LiteralPath $stateReport -Encoding UTF8
    $caseSummaryDoc|Add-Member -NotePropertyName pairing -NotePropertyValue $pairMetadata
    $caseSummaryDoc|ConvertTo-Json -Depth 7|Set-Content -LiteralPath $caseSummary -Encoding UTF8
  }
  return $caseSummaryDoc
}
$comparison=$null
if($AxialAcceleration){
  $accelerated=Invoke-TransportCase 'axial_acceleration_rf_on' 1 1 0
  $control=Invoke-TransportCase 'zero_axial_drop_rf_on' 1 0 0
  $metrics=Join-Path $resultDir 'axial_acceleration_metrics.json'
  if($pairingEnabled){
    & $python -m common.multipole.axial_pairing --audit --resolved-pair $pairingResolved `
      --field-on-state (Join-Path $resultDir 'particle_states__axial_acceleration_rf_on.csv') `
      --field-off-state (Join-Path $resultDir 'particle_states__zero_axial_drop_rf_on.csv') `
      --output $pairAudit
    if($LASTEXITCODE-ne 0){throw 'SIMION axial paired-source audit failed.'}
  }
  & $python -m common.multipole.analyze_simion_axial_acceleration `
    --accelerated-state (Join-Path $resultDir 'particle_states__axial_acceleration_rf_on.csv') `
    --control-state (Join-Path $resultDir 'particle_states__zero_axial_drop_rf_on.csv') `
    --resolved-contract $axialResolved --output $metrics
  $analysisExit=$LASTEXITCODE
  if($analysisExit-ne 0){throw 'SIMION axial-acceleration functional analysis failed.'}
  $metricsDoc=Get-Content -LiteralPath $metrics -Raw -Encoding UTF8|ConvertFrom-Json
  $status=[string]$metricsDoc.status
  [ordered]@{schema_version=1;role='multipole_simion_axial_acceleration_summary';status=if($status-eq'PASS'){'success'}else{'failed'};project_id=$projectId;particles=$metricsDoc.particles;transmission=$metricsDoc.accelerated_transmission;mean_output_energy_eV=$metricsDoc.mean_accelerated_output_energy_eV;mean_energy_gain_eV=$metricsDoc.mean_energy_gain_eV;predicted_output_energy_eV=$metricsDoc.predicted_output_energy_eV;formal_gate_passed=$false}|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $summary -Encoding UTF8
}elseif($EndplateAcceleration){
  $endplateDoc=Get-Content -LiteralPath $endplateResolved -Raw -Encoding UTF8|ConvertFrom-Json
  $accelerated=Invoke-TransportCase 'endplate_acceleration_rf_on' 1 0 ([double]$endplateDoc.exit_plate_V)
  $control=Invoke-TransportCase 'zero_endplate_drop_rf_on' 1 0 0
  $metrics=Join-Path $resultDir 'endplate_acceleration_metrics.json'
  & $python -m common.multipole.analyze_simion_axial_acceleration `
    --accelerated-state (Join-Path $resultDir 'particle_states__endplate_acceleration_rf_on.csv') `
    --control-state (Join-Path $resultDir 'particle_states__zero_endplate_drop_rf_on.csv') `
    --resolved-contract $endplateResolved --output $metrics
  $analysisExit=$LASTEXITCODE
  if($analysisExit-ne 0){throw 'SIMION endplate-acceleration functional analysis failed.'}
  $metricsDoc=Get-Content -LiteralPath $metrics -Raw -Encoding UTF8|ConvertFrom-Json
  $status=[string]$metricsDoc.status
  [ordered]@{schema_version=1;role='multipole_simion_endplate_acceleration_summary';status=if($status-eq'PASS'){'success'}else{'failed'};project_id=$projectId;particles=$metricsDoc.particles;transmission=$metricsDoc.accelerated_transmission;mean_output_energy_eV=$metricsDoc.mean_accelerated_output_energy_eV;mean_energy_gain_eV=$metricsDoc.mean_energy_gain_eV;predicted_output_energy_eV=$metricsDoc.predicted_output_energy_eV;formal_gate_passed=$false}|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $summary -Encoding UTF8
}else{
  $rf=Invoke-TransportCase 'rf_on' 1 0 0; $zero=Invoke-TransportCase 'zero_rf_control' 0 0 0
  $minimum=[double]$resolvedDoc.functional_acceptance.minimum_rf_transmission; $improvement=[double]$resolvedDoc.functional_acceptance.minimum_improvement_over_zero_rf
  $status=if($rf.transmission-ge $minimum -and ($rf.transmission-$zero.transmission)-ge $improvement){'PASS'}else{'FAIL'}
  $metrics=Join-Path $resultDir 'finite_3d_transport_metrics.json'
  [ordered]@{schema_version=1;role='multipole_simion_finite_3d_transport_metrics';status=$status;project_id=$projectId;model_level='L3';simion_cell_mm=$CellMm;cases=[ordered]@{finite_3d_rf_on=$rf;zero_rf_control=$zero};rf_minus_zero_transmission=($rf.transmission-$zero.transmission);claim_limit='Functional SIMION cross-solver regression only; no mesh convergence or Candidate claim.'}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $metrics -Encoding UTF8
  [ordered]@{schema_version=1;role='multipole_simion_finite_3d_transport_summary';status=if($status-eq'PASS'){'success'}else{'failed'};project_id=$projectId;rf_transmission=$rf.transmission;zero_rf_transmission=$zero.transmission;model_level='L3';formal_gate_passed=$false}|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $summary -Encoding UTF8
}
if(-not $accelerationEnabled -and -not [string]::IsNullOrWhiteSpace($ReferenceComsolRunId)){
  $referenceMetrics=Join-Path $workspaceRoot "artifacts\projects\$projectId\runs\$ReferenceComsolRunId\results\finite_3d_transport_metrics.json"
  $comparison=Join-Path $resultDir 'cross_solver_functional_comparison.json'
  & $python -m common.multipole.compare_simion_comsol_l3 --rf-state (Join-Path $resultDir 'particle_states__rf_on.csv') --zero-state (Join-Path $resultDir 'particle_states__zero_rf_control.csv') --comsol-metrics $referenceMetrics --output $comparison
  if($LASTEXITCODE-ne 0){throw 'SIMION/COMSOL functional comparison failed.'}
}
$caseNames=if($AxialAcceleration){@('axial_acceleration_rf_on','zero_axial_drop_rf_on')}elseif($EndplateAcceleration){@('endplate_acceleration_rf_on','zero_endplate_drop_rf_on')}else{@('rf_on','zero_rf_control')}
$compatibilityState=$null
$compatibilitySummary=$null
if($Adapter -eq 'quadrupole'){
  $primaryCaseName=[string]$caseNames[0]
  $primaryCaseSummary=Get-Content -LiteralPath (Join-Path $resultDir "simion_summary__$primaryCaseName.json") -Raw -Encoding UTF8|ConvertFrom-Json
  $meanOutputEnergy=if($accelerationEnabled){[double]$metricsDoc.mean_accelerated_output_energy_eV}else{$null}
  $compatibilityState=Join-Path $resultDir 'particle_state.csv'
  $compatibilitySummary=Join-Path $resultDir 'solver_summary.json'
  Copy-Item -LiteralPath (Join-Path $resultDir "particle_states__$primaryCaseName.csv") -Destination $compatibilityState
  [ordered]@{schema_version=1;role='rf_quadrupole_transport_solver_summary';solver='SIMION';
    mode=$runMode;particles=$primaryCaseSummary.particles;hits=$primaryCaseSummary.hits;
    transmission=$primaryCaseSummary.transmission;mean_output_energy_eV=$meanOutputEnergy;
    rf_peak_V=[double]$operatingDoc.voltage.rf_amplitude_V_zero_to_peak_per_group;
    frequency_Hz=[double]$operatingDoc.voltage.frequency_Hz}|
    ConvertTo-Json -Depth 4|Set-Content -LiteralPath $compatibilitySummary -Encoding UTF8
}
$outputs=@($summary,$metrics,(Join-Path $solverDir 'quad_monolithic.pa0'),(Join-Path $solverDir 'quad_monolithic.iob'),$gem,$fly2)
$outputs+=@($caseNames|ForEach-Object{Join-Path $resultDir "particle_state_contract__$_.json"})
if($pairingEnabled){
  $outputs+=@($pairingResolved,$pairAudit)
  $outputs+=@($caseNames|ForEach-Object{Join-Path $resultDir "particle_states__$_.csv"})
  $outputs+=@($caseNames|ForEach-Object{Join-Path $resultDir "simion_summary__$_.json"})
}
$outputs+=@(Get-ChildItem -LiteralPath $logDir -File | Select-Object -ExpandProperty FullName)
if($comparison){$outputs+=$comparison}
if($compatibilityState){$outputs+=@($compatibilityState,$compatibilitySummary)}
Write-RunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig `
  -Status $(if($status-eq'PASS'){'success'}else{'failed'}) -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
if($status-ne'PASS'){throw "SIMION $runMode functional gate failed."}
if($accelerationEnabled){
  Write-Output "MULTIPOLE_SIMION_ACCELERATION=PASS MODE=$runMode PROJECT=$projectId RUN_ID=$RunId TRANSMISSION=$($metricsDoc.accelerated_transmission) MEAN_ENERGY_EV=$($metricsDoc.mean_accelerated_output_energy_eV)"
}else{
  Write-Output "MULTIPOLE_SIMION_L3=PASS PROJECT=$projectId RUN_ID=$RunId RF=$($rf.transmission) ZERO=$($zero.transmission)"
}
} catch {
  Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
    -SummaryRole 'multipole_simion_finite_3d_transport_summary' -Reason $_.Exception.Message `
    -Software @('SIMION 2020','Python 3.11')
  throw
}
