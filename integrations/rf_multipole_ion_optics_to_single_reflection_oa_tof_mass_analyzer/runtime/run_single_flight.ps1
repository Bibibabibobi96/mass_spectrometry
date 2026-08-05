[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$RunId,
  [Parameter(Mandatory)][string]$ConnectionProfileId,
  [Parameter(Mandatory)][string]$ResolvedConnection,
  [Parameter(Mandatory)][string]$ResolvedEngineeringBudget,
  [Parameter(Mandatory)][string]$RuntimeBinding,
  [Parameter(Mandatory)][ValidateSet('simion')][string]$SourceBranchId,
  [Parameter(Mandatory)][string]$ResolvedSourceContract,
  [Parameter(Mandatory)][string]$ResolvedSourceContractSha256,
  [Parameter(Mandatory)][string]$UpstreamResolvedDesign,
  [Parameter(Mandatory)][string]$UpstreamResolvedDesignSha256,
  [string]$OatofResolvedGeometry = '',
  [string]$PulseSchedule = '',
  [string]$LayoutProfileId = '',
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$integrationRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot = (Resolve-Path (Join-Path $integrationRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
. (Join-Path $PSScriptRoot 'runtime_binding.ps1')
. (Join-Path $PSScriptRoot 'single_flight_assets.ps1')
$runtime = Resolve-RfOatofRuntimeBinding -RepoRoot $repoRoot `
  -ResolvedConnection $ResolvedConnection -RuntimeBinding $RuntimeBinding `
  -ExpectedConnectionProfileId $ConnectionProfileId -SourceBranchId $SourceBranchId `
  -ResolvedSourceContract $ResolvedSourceContract `
  -ResolvedSourceContractSha256 $ResolvedSourceContractSha256 `
  -UpstreamResolvedDesign $UpstreamResolvedDesign `
  -UpstreamResolvedDesignSha256 $UpstreamResolvedDesignSha256
. $runtime.run_artifact_support
. (Join-Path $repoRoot 'common\multipole\resource_budget_support.ps1')

function Invoke-SingleFlightPython {
  param([Parameter(Mandatory)][object[]]$Arguments,[Parameter(Mandatory)][string]$Failure)
  $saved = Save-RfEnvironment -Names @('PYTHONPATH','PYTHONNOUSERSITE')
  try {
    $env:PYTHONPATH = $repoRoot; $env:PYTHONNOUSERSITE = '1'
    Push-Location -LiteralPath $repoRoot
    try { & $python @Arguments; if ($LASTEXITCODE -ne 0) { throw $Failure } } finally { Pop-Location }
  } finally { Restore-RfEnvironment -Names @('PYTHONPATH','PYTHONNOUSERSITE') -Snapshot $saved }
}

if (-not (Test-Path -LiteralPath $SimionExe -PathType Leaf)) { throw "SIMION is missing: $SimionExe" }
$artifactRoot = Join-Path $workspaceRoot "artifacts\projects\$($runtime.upstream_project_id)"
$package = New-RfRunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project $runtime.upstream_project_id -Mode 'rf_to_oatof_simion_single_flight' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -AdditionalDirectories @('simion')
$resourceBudgetExceeded = $false
$snapshotReady = $false
$summaryRole = 'rf_oatof_simion_single_flight_summary'
$resourceUsage = Join-Path $package.log_dir 'resource_usage.json'

try {
  $budget = Initialize-RfIntegrationStageBudget -ResolvedBudget $ResolvedEngineeringBudget `
    -InputDir $package.input_dir -ExpectedIntegrationId `
    'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' `
    -ExpectedConnectionProfileId $ConnectionProfileId -StageId 'single_flight_transport' -Solver simion
  $configurationSource = Join-Path $integrationRoot 'config\simion_single_flight.json'
  $configuration = Join-Path $package.input_dir 'simion_single_flight.json'
  Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $configurationSource -Destination $configuration -Role 'single-flight configuration' | Out-Null
  $settings = Get-Content -LiteralPath $configuration -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($settings.role -ne 'rf_oatof_simion_single_flight_configuration' -or [double]$settings.cell_mm -le 0) {
    throw 'Single-flight numerical configuration is invalid.'
  }
  $hasGovernedLayout = -not [string]::IsNullOrWhiteSpace($LayoutProfileId)
  if ($hasGovernedLayout -ne (
      -not [string]::IsNullOrWhiteSpace($OatofResolvedGeometry) -and
      -not [string]::IsNullOrWhiteSpace($PulseSchedule))) {
    throw 'Single-flight layout profile, resolved geometry and pulse schedule must be supplied together.'
  }
  $resolvedFrozen = Join-Path $package.input_dir 'resolved_connection.json'
  $upstreamFrozen = Join-Path $package.input_dir 'upstream_resolved_design.json'
  $sourceContractFrozen = Join-Path $package.input_dir 'resolved_source_contract.json'
  $runtimeBindingFrozen = Join-Path $package.input_dir 'runtime_binding.json'
  $oatofGeometry = Join-Path $package.input_dir 'oatof_resolved_geometry.json'
  Copy-Item -LiteralPath $runtime.resolved_connection_path -Destination $resolvedFrozen
  Copy-Item -LiteralPath $runtime.contracts.upstream_resolved_design -Destination $upstreamFrozen
  Copy-Item -LiteralPath $runtime.contracts.resolved_source_contract -Destination $sourceContractFrozen
  Copy-Item -LiteralPath $runtime.binding_path -Destination $runtimeBindingFrozen
  $oatofGeometrySource = if ($hasGovernedLayout) {
    [IO.Path]::GetFullPath($OatofResolvedGeometry)
  } else {
    Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\config\resolved_geometry.json'
  }
  Copy-RfStableFile -SourceRunRoot $(if ($hasGovernedLayout) {$workspaceRoot} else {$repoRoot}) `
    -SourcePath $oatofGeometrySource `
    -Destination $oatofGeometry -Role 'oaTOF resolved geometry' | Out-Null
  $pulseScheduleFrozen = $null
  $pulseTimeUs = [double]$settings.pulse_time_us
  $pulseWidthUs = [double]$settings.pulse_width_us
  if ($hasGovernedLayout) {
    $pulseScheduleFrozen = Join-Path $package.input_dir 'resolved_single_flight_pulse_schedule.json'
    Copy-RfStableFile -SourceRunRoot $workspaceRoot -SourcePath $PulseSchedule `
      -Destination $pulseScheduleFrozen -Role 'single-flight pulse schedule' | Out-Null
    $pulseScheduleDocument = Get-Content -LiteralPath $pulseScheduleFrozen -Raw -Encoding UTF8 |
      ConvertFrom-Json
    if ($pulseScheduleDocument.role -ne 'rf_oatof_single_flight_multipole_handoff_pulse_schedule' -or
        $pulseScheduleDocument.layout_profile_id -ne $LayoutProfileId -or
        [double]$pulseScheduleDocument.derived_pulse_time_us -le 0 -or
        [double]$pulseScheduleDocument.pulse_width_us -le 0) {
      throw 'Governed single-flight pulse schedule identity differs.'
    }
    $pulseTimeUs = [double]$pulseScheduleDocument.derived_pulse_time_us
    $pulseWidthUs = [double]$pulseScheduleDocument.pulse_width_us
  }

  $motherSource = Join-Path $package.input_dir 'mother_particle_source.csv'
  Copy-RfStableFile -SourceRunRoot $workspaceRoot -SourcePath $runtime.source_particle_source `
    -Destination $motherSource -Role 'N1000 mother particle source' | Out-Null
  $launched = [int]$runtime.source_record.launched_particle_count
  if (@(Import-Csv -LiteralPath $motherSource).Count -ne $launched) {
    throw 'Single-flight mother sample count differs from source authority.'
  }

  $frontendGem = Join-Path $package.input_dir 'single_flight_frontend.gem'
  $frontendContract = Join-Path $package.input_dir 'single_flight_frontend_contract.json'
  Invoke-SingleFlightPython -Arguments @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_frontend',
    '--upstream',$upstreamFrozen,'--oatof',$oatofGeometry,
    '--connection',$resolvedFrozen,'--gem',$frontendGem,'--contract',$frontendContract,
    '--cell-mm',([string]$settings.cell_mm)) -Failure 'Single-flight frontend compilation failed.'
  $frontendGeometry = Get-Content -LiteralPath $frontendContract -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $apertureWidthMm = [double]$frontendGeometry.aperture.width_mm
  $apertureHeightMm = [double]$frontendGeometry.aperture.height_mm
  $apertureDiscretization = $frontendGeometry.junction_enclosure.aperture_discretization
  if (-not $apertureDiscretization.compiled_pa_open_column_check_required -or
      [double]$apertureDiscretization.mechanical_width_mm -ne $apertureWidthMm -or
      [double]$apertureDiscretization.mechanical_height_mm -ne $apertureHeightMm) {
    throw 'Single-flight aperture discretization contract is incomplete or inconsistent.'
  }
  $apertureGridWarnings = @($apertureDiscretization.grid_alignment.warnings)
  foreach ($warningCode in $apertureGridWarnings) {
    Write-Warning "SIMION aperture discretization warning: $warningCode"
  }
  $apertureVerifier = Join-Path $package.input_dir 'verify_simion_aperture_topology.lua'
  Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath (Join-Path $repoRoot 'common\simion\verify_aperture_topology.lua') `
    -Destination $apertureVerifier -Role 'compiled PA aperture topology verifier' | Out-Null
  $apertureTopologySupport = Join-Path $package.input_dir 'simion_aperture_topology_support.ps1'
  Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath (Join-Path $repoRoot 'common\simion\aperture_topology_support.ps1') `
    -Destination $apertureTopologySupport -Role 'shared SIMION aperture topology entry' | Out-Null
  . $apertureTopologySupport
  $apertureTopologyReport = Join-Path $package.result_dir 'frontend_aperture_topology_check.json'
  $frontendHash = (Get-FileHash -LiteralPath $frontendGem -Algorithm SHA256).Hash
  $cacheRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\cache\simion_single_flight_frontend'
  $cacheDir = Join-Path $cacheRoot $frontendHash.ToLowerInvariant()
  New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null
  $cacheGem = Join-Path $cacheDir 'frontend.gem'; $cachePaSharp = Join-Path $cacheDir 'frontend.pa#'; $cachePa0 = Join-Path $cacheDir 'frontend.pa0'
  $frontendRefineRequired = -not (Test-Path -LiteralPath $cachePa0 -PathType Leaf)
  if ($frontendRefineRequired) {
    Copy-Item -LiteralPath $frontendGem -Destination $cacheGem -Force
    $gem2pa = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
      -UsagePath (Join-Path $package.log_dir 'frontend_gem2pa_resource_usage.json') -FilePath $SimionExe `
      -WorkingDirectory $cacheDir -RedirectStandardOutput (Join-Path $package.log_dir 'frontend_gem2pa.stdout.log') `
      -RedirectStandardError (Join-Path $package.log_dir 'frontend_gem2pa.stderr.log') `
      -ArgumentList @('--nogui','--noprompt','gem2pa',$cacheGem,$cachePaSharp)
    if ($gem2pa.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Frontend GEM conversion exceeded its resource budget.' }
    if ($gem2pa.exit_code -ne 0) { throw 'Frontend GEM conversion failed.' }
  }

  if ($frontendRefineRequired) {
    $refine = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
      -UsagePath (Join-Path $package.log_dir 'frontend_refine_resource_usage.json') -FilePath $SimionExe `
      -WorkingDirectory $cacheDir -RedirectStandardOutput (Join-Path $package.log_dir 'frontend_refine.stdout.log') `
      -RedirectStandardError (Join-Path $package.log_dir 'frontend_refine.stderr.log') `
      -ArgumentList @('--nogui','--noprompt','refine',$cachePaSharp)
    if ($refine.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Frontend refinement exceeded its resource budget.' }
    if ($refine.exit_code -ne 0 -or -not (Test-Path -LiteralPath $cachePa0 -PathType Leaf)) { throw 'Frontend PA refinement failed.' }
  }

  $topologyResult = Invoke-SimionCompiledApertureTopologyCheck `
    -PaPath $cachePa0 -ReportPath $apertureTopologyReport -VerifierPath $apertureVerifier `
    -OriginXmm ([double]$frontendGeometry.instance_origin_mm.x) `
    -OriginYmm ([double]$frontendGeometry.instance_origin_mm.y) `
    -OriginZmm ([double]$frontendGeometry.instance_origin_mm.z) `
    -CellMm ([double]$frontendGeometry.cell_mm_xyz.x) `
    -FlangeXMinMm ([double]$apertureDiscretization.flange_x_min_mm) `
    -FlangeXMaxMm ([double]$apertureDiscretization.flange_x_max_mm) `
    -CenterYmm ([double]$frontendGeometry.source_exit_center_mm.y) `
    -CenterZmm ([double]$frontendGeometry.source_exit_center_mm.z) `
    -MechanicalWidthMm $apertureWidthMm -MechanicalHeightMm $apertureHeightMm `
    -BooleanBoundaryPolicy ([string]$apertureDiscretization.boolean_boundary_policy) `
    -InvokeVerifier {
      param($verifierPath)
      Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
        -UsagePath (Join-Path $package.log_dir 'frontend_aperture_topology_resource_usage.json') -FilePath $SimionExe `
        -WorkingDirectory $cacheDir -RedirectStandardOutput (Join-Path $package.log_dir 'frontend_aperture_topology.stdout.log') `
        -RedirectStandardError (Join-Path $package.log_dir 'frontend_aperture_topology.stderr.log') `
        -ArgumentList @('--nogui','--noprompt','lua',$verifierPath)
    }
  $apertureTopology = $topologyResult.audit

  $ion = Join-Path $package.input_dir 'single_flight_mother_sample.ion'
  $globalSource = Join-Path $package.input_dir 'single_flight_initial_global_state.csv'
  Invoke-SingleFlightPython -Arguments @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source',
    '--source',$motherSource,'--connection',$resolvedFrozen,'--ion',$ion,'--global-state',$globalSource) `
    -Failure 'Single-flight source materialization failed.'

  $runtimeDir = Join-Path $package.run_dir 'simion'
  $formalDir = Join-Path $workspaceRoot 'artifacts\projects\single_reflection_oa_tof_mass_analyzer\formal\simion'
  Copy-RfOatofFormalPaSet -FormalDir $formalDir -Destination $runtimeDir
  $formalLua = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\formal\oatof_ideal_grounded.lua'
  $pulseLua = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\candidates\oatof_handoff_pulse.lua'
  $program = Join-Path $runtimeDir 'oatof_ideal_grounded.lua'
  $programMetadata = Join-Path $package.input_dir 'single_flight_program_build.json'
  Invoke-SingleFlightPython -Arguments @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.build_single_flight_program',
    '--formal',$formalLua,'--pulse-extension',$pulseLua,'--upstream',$upstreamFrozen,
    '--frontend-contract',$frontendContract,'--output',$program,'--metadata',$programMetadata) `
    -Failure 'Single-flight Program build failed.'

  $runConfiguration = [ordered]@{
    schema_version=2; run_id=$RunId; project=$runtime.upstream_project_id; mode='rf_to_oatof_simion_single_flight'; project_root=$repoRoot
    inputs=[ordered]@{ configuration=$configuration; runtime_binding=$runtimeBindingFrozen; resolved_connection=$resolvedFrozen; resolved_source_contract=$sourceContractFrozen; upstream_resolved_design=$upstreamFrozen; oatof_resolved_geometry=$oatofGeometry; pulse_schedule=$pulseScheduleFrozen; resolved_integration_engineering_budget=$budget.frozen_budget; resolved_stage_resource_budget=$budget.stage_budget; mother_particle_source=$motherSource; initial_global_state=$globalSource; ion=$ion; frontend_gem=$frontendGem; frontend_contract=$frontendContract; frontend_aperture_topology_support=$apertureTopologySupport; frontend_aperture_topology_verifier=$apertureVerifier; program_metadata=$programMetadata }
    upstream_source_identity=$runtime.source_identity
    parameters=[ordered]@{ connection_profile_id=$ConnectionProfileId; source_branch_id=$SourceBranchId; layout_profile_id=$(if($hasGovernedLayout){$LayoutProfileId}else{$null}); launched_particle_count=$launched; particle_count=$launched; aperture_width_mm=$apertureWidthMm; aperture_height_mm=$apertureHeightMm; aperture_boolean_boundary_policy=[string]$apertureDiscretization.boolean_boundary_policy; aperture_grid_warnings=$apertureGridWarnings; frontend_open_aperture_column_count=[int]$apertureTopology.open_column_count; frontend_aperture_guard_electrode_check_passed=[bool]$apertureTopology.guard_electrode_check_passed; frontend_aperture_topology_report_sha256=(Get-FileHash -LiteralPath $apertureTopologyReport -Algorithm SHA256).Hash; rod_end_to_accelerator_shield_mm=1.0; surrounded_transition=$true; accelerator_axis_x_mm=[double]((Get-Content -LiteralPath $oatofGeometry -Raw -Encoding UTF8 | ConvertFrom-Json).coordinate_convention.accelerator_axis_x); pulse_time_us=$pulseTimeUs; pulse_width_us=$pulseWidthUs; frontend_gem_sha256=$frontendHash; frontend_pa0_sha256=(Get-FileHash -LiteralPath $cachePa0 -Algorithm SHA256).Hash }
    artifact_retention=[ordered]@{policy_version=1;class='compact';reason=$null}; formal_gate_passed=$false
  }
  Write-RfJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  Write-RfJson -Path $package.summary -Value ([ordered]@{schema_version=1;role=$summaryRole;status='interrupted';reason='Frozen inputs recorded; SIMION flight not complete.'})
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $repoRoot -RunConfig $package.run_config -Status interrupted -Software @('SIMION 2020','Python 3.11')
  $snapshotReady = $true

  $stdout = Join-Path $package.log_dir 'simion.stdout.log'; $stderr = Join-Path $package.log_dir 'simion.stderr.log'
  $oldOverride = $env:OATOF_ACCELERATOR_PA_OVERRIDE
  try {
    $env:OATOF_ACCELERATOR_PA_OVERRIDE = $cachePa0
    $fly = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
      -UsagePath $resourceUsage -FilePath $SimionExe -WorkingDirectory $runtimeDir `
      -RedirectStandardOutput $stdout -RedirectStandardError $stderr -ArgumentList @(
      '--default-num-particles',([string][Math]::Max(100,$launched)),'--nogui','--noprompt','fly',
      '--trajectory-quality',([string]$settings.trajectory_quality),'--retain-trajectories','0','--particles',$ion,'--programs','1',
      '--adjustable',("trajectory_quality={0}" -f $settings.trajectory_quality),'--adjustable','trajectory_log_enable=1',
      '--adjustable',("diagnostic_max_tof_us={0:R}" -f [double]$settings.maximum_time_of_flight_us),
      '--adjustable','handoff_pulse_mode=1','--adjustable',("handoff_pulse_time_us={0:R}" -f $pulseTimeUs),
      '--adjustable',("handoff_pulse_width_us={0:R}" -f $pulseWidthUs),
      '--adjustable',("accelerator_axis_x_mm={0:R}" -f [double]$runConfiguration.parameters.accelerator_axis_x_mm),
      '--adjustable',("single_flight_rf_steps={0}" -f [int]$settings.rf_steps_per_period),
      (Join-Path $runtimeDir 'oatof_ideal_grounded.iob'))
  } finally { $env:OATOF_ACCELERATOR_PA_OVERRIDE = $oldOverride }
  if ($fly.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Single-flight SIMION run exceeded its resource budget.' }
  if ($fly.exit_code -ne 0) { throw "Single-flight SIMION run failed: $stderr" }

  $checkpoints = Join-Path $package.result_dir 'single_flight_particle_checkpoints.csv'
  Invoke-SingleFlightPython -Arguments @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight',
    '--log',$stdout,'--launched',([string]$launched),'--mass-amu','100','--checkpoints',$checkpoints,'--summary',$package.summary) `
    -Failure 'Single-flight log analysis failed.'
  $sixPanel = Join-Path $package.result_dir 'single_flight_spatial_six_panel.png'
  $sixPanelMetadata = Join-Path $package.result_dir 'single_flight_spatial_six_panel_metadata.json'
  Invoke-SingleFlightPython -Arguments @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_single_flight_spatial_six_panel',
    '--initial',$globalSource,'--checkpoints',$checkpoints,'--upstream',$upstreamFrozen,
    '--frontend',$frontendContract,'--oatof',$oatofGeometry,'--output',$sixPanel,
    '--metadata',$sixPanelMetadata) -Failure 'Single-flight six-panel spatial diagnostic failed.'
  $result = Get-Content -LiteralPath $package.summary -Raw -Encoding UTF8 | ConvertFrom-Json
  $runConfiguration.parameters.multipole_handoff_count = [int]$result.census.multipole_handoff
  $runConfiguration.parameters.local_accelerator_exit_count = [int]$result.census.local_accelerator_exit
  $runConfiguration.parameters.detector_crossing_count = [int]$result.census.detector_crossing
  Write-RfJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  $retentionActions = Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $outputs = @($checkpoints,$sixPanel,$sixPanelMetadata,$stdout,$stderr,$resourceUsage,$package.summary,$retentionActions) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
  if (-not (Complete-ResourceUsage -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir -UsagePath $resourceUsage)) { $resourceBudgetExceeded=$true; throw 'Single-flight compact retained-byte budget exceeded.' }
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $repoRoot -RunConfig $package.run_config -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  Write-Output "SIMION_SINGLE_FLIGHT=PASS RUN_ID=$RunId DETECTOR=$($result.census.detector_crossing)/$launched"
} catch {
  if ($snapshotReady) {
    Complete-RfFrozenFailedRun -Python $python -FrozenRepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary -SummaryRole $summaryRole -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status $(if ($resourceBudgetExceeded) {'interrupted'} else {'failed'}) -FailureClass $(if ($resourceBudgetExceeded) {'resource_budget_exceeded'} else {''}) -ResourceUsagePath $(if ($resourceBudgetExceeded) {$resourceUsage} else {''})
  } else {
    Write-RfJson -Path $package.summary -Value ([ordered]@{schema_version=1;role=$summaryRole;status='failed';reason=$_.Exception.Message;manifest_written=$false})
  }
  throw
}
