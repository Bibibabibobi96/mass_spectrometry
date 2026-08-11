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
  [string]$FrontendGridProfileId = '',
  [string]$AcceleratorFieldProfileId = '',
  [string]$MotherParticleSource = '',
  [string]$MotherParticleSourceSha256 = '',
  [int]$MotherParticleCount = 0,
  [ValidateSet('governed_upstream_source','steady_candidate_pool','pulse_eligible_conditional')][string]$SamplingMode = 'governed_upstream_source',
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
  $selectedGridProfileId = if ([string]::IsNullOrWhiteSpace($FrontendGridProfileId)) {
    [string]$settings.default_frontend_grid_profile_id
  } else { $FrontendGridProfileId }
  $gridProfiles = @($settings.frontend_grid_profiles | Where-Object {
    [string]$_.profile_id -eq $selectedGridProfileId
  })
  if ($settings.role -ne 'rf_oatof_simion_single_flight_configuration' -or
      $gridProfiles.Count -ne 1 -or
      @($gridProfiles[0].cell_mm_xyz.PSObject.Properties.Name).Count -ne 3 -or
      @($gridProfiles[0].cell_mm_xyz.PSObject.Properties.Name | Where-Object {
        $_ -notin @('x','y','z')
      }).Count -ne 0 -or
      [double]$gridProfiles[0].cell_mm_xyz.x -le 0 -or
      [double]$gridProfiles[0].cell_mm_xyz.y -le 0 -or
      [double]$gridProfiles[0].cell_mm_xyz.z -le 0 -or
      [int]$gridProfiles[0].max_parallel_batches -lt 1 -or
      [int]$gridProfiles[0].max_parallel_batches -gt 5 -or
      [string]$settings.clock_basis -notin @('legacy_relative_time','absolute_birth_time')) {
    throw 'Single-flight numerical configuration is invalid.'
  }
  $frontendCellMmX = [double]$gridProfiles[0].cell_mm_xyz.x
  $frontendCellMmY = [double]$gridProfiles[0].cell_mm_xyz.y
  $frontendCellMmZ = [double]$gridProfiles[0].cell_mm_xyz.z
  $maxParallelBatches = [int]$gridProfiles[0].max_parallel_batches
  $selectedFieldProfileId = if ([string]::IsNullOrWhiteSpace($AcceleratorFieldProfileId)) {
    [string]$settings.default_accelerator_field_profile_id
  } else { $AcceleratorFieldProfileId }
  $fieldProfiles = @($settings.accelerator_field_profiles | Where-Object {
    [string]$_.profile_id -eq $selectedFieldProfileId
  })
  if ($fieldProfiles.Count -ne 1 -or
      [int]$fieldProfiles[0].single_flight_ideal_accel_enable -notin @(0,1)) {
    throw 'Single-flight accelerator field profile is invalid.'
  }
  $idealAcceleratorEnable = [int]$fieldProfiles[0].single_flight_ideal_accel_enable
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
  $oatofGeometryDocument = Get-Content -LiteralPath $oatofGeometry -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $layoutDerivation = if ($hasGovernedLayout) {
    $oatofGeometryDocument.single_flight_layout_derivation
  } else { $null }
  $hasReflectronRebuild = (
    $SamplingMode -ne 'steady_candidate_pool' -and
    $null -ne $layoutDerivation -and
    $null -ne $layoutDerivation.PSObject.Properties['design_compilation'] -and
    [bool]$layoutDerivation.design_compilation.simion_rebuild_plan.reflectron_pa
  )
  $hasFlightTubeRebuild = (
    $SamplingMode -ne 'steady_candidate_pool' -and
    $null -ne $layoutDerivation -and
    $null -ne $layoutDerivation.PSObject.Properties['design_compilation'] -and
    [bool]$layoutDerivation.design_compilation.simion_rebuild_plan.flight_tube_pa
  )
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
  $hasMotherOverride = -not [string]::IsNullOrWhiteSpace($MotherParticleSource)
  if ($hasMotherOverride -ne (-not [string]::IsNullOrWhiteSpace($MotherParticleSourceSha256) -and $MotherParticleCount -gt 0)) {
    throw 'Single-flight mother-source override identity is incomplete.'
  }
  $sourceToCopy = if ($hasMotherOverride) { [IO.Path]::GetFullPath($MotherParticleSource) } else { $runtime.source_particle_source }
  Copy-RfStableFile -SourceRunRoot $(if ($hasMotherOverride) {$repoRoot} else {$workspaceRoot}) -SourcePath $sourceToCopy `
    -Destination $motherSource -Role 'single-flight mother particle source' | Out-Null
  if ($hasMotherOverride -and (Get-FileHash -LiteralPath $motherSource -Algorithm SHA256).Hash -ne $MotherParticleSourceSha256) {
    throw 'Single-flight mother-source override hash differs.'
  }
  $launched = if ($hasMotherOverride) { $MotherParticleCount } else { [int]$runtime.source_record.launched_particle_count }
  if (@(Import-Csv -LiteralPath $motherSource).Count -ne $launched) {
    throw 'Single-flight mother sample count differs from source authority.'
  }

  $frontendGem = Join-Path $package.input_dir 'single_flight_frontend.gem'
  $frontendContract = Join-Path $package.input_dir 'single_flight_frontend_contract.json'
  Invoke-SingleFlightPython -Arguments @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_frontend',
    '--upstream',$upstreamFrozen,'--oatof',$oatofGeometry,
    '--connection',$resolvedFrozen,'--gem',$frontendGem,'--contract',$frontendContract,
    '--cell-mm-x',([string]$frontendCellMmX),
    '--cell-mm-y',([string]$frontendCellMmY),
    '--cell-mm-z',([string]$frontendCellMmZ)) `
    -Failure 'Single-flight frontend compilation failed.'
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
    -CellMmX ([double]$frontendGeometry.cell_mm_xyz.x) `
    -CellMmY ([double]$frontendGeometry.cell_mm_xyz.y) `
    -CellMmZ ([double]$frontendGeometry.cell_mm_xyz.z) `
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
  $reflectronBuilderFrozen = $null
  $reflectronGemFrozen = $null
  $reflectronRefinerFrozen = $null
  $reflectronPa0 = Join-Path $runtimeDir 'reflectron.pa0'
  $reflectronBuildStdout = $null
  $reflectronBuildStderr = $null
  $flightTubeBuilderFrozen = $null
  $flightTubeGemFrozen = $null
  $flightTubeBuildStdout = $null
  $flightTubeBuildStderr = $null
  $downstreamCacheRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\cache\simion_oatof_downstream_pa'
  $geometryHash = (Get-FileHash -LiteralPath $oatofGeometry -Algorithm SHA256).Hash
  $flightTubeBuilderSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\build_flight_tube_variant.lua'
  $flightTubeGemSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\oatof_flight_tube_ground.gem'
  $reflectronBuilderSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\reflectron\build_reflectron_variant.lua'
  $reflectronGemSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\reflectron\oatof_reflectron_ideal_10_5.gem'
  $reflectronRefinerSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\reflectron\refine_single_pa.lua'
  function Get-ContentAddressedPaPath {
    param([Parameter(Mandatory)][string]$Kind,[Parameter(Mandatory)][string]$Builder,[Parameter(Mandatory)][string]$Gem,[string]$Additional='')
    $additionalHash = if ([string]::IsNullOrWhiteSpace($Additional)) { '' } else { (Get-FileHash -LiteralPath $Additional -Algorithm SHA256).Hash }
    $identity = "$geometryHash|$((Get-FileHash -LiteralPath $Builder -Algorithm SHA256).Hash)|$((Get-FileHash -LiteralPath $Gem -Algorithm SHA256).Hash)|$additionalHash"
    $key = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($identity))).ToLowerInvariant()
    return Join-Path (Join-Path $downstreamCacheRoot $key) "$Kind.pa0"
  }
  $flightTubeCachePa0 = Get-ContentAddressedPaPath -Kind 'flight_tube_ground' -Builder $flightTubeBuilderSource -Gem $flightTubeGemSource
  $reflectronCachePa0 = Get-ContentAddressedPaPath -Kind 'reflectron' -Builder $reflectronBuilderSource -Gem $reflectronGemSource -Additional $reflectronRefinerSource
  $flightTubeCacheDir = Split-Path -Parent $flightTubeCachePa0
  $reflectronCacheDir = Split-Path -Parent $reflectronCachePa0
  function Use-ReadOnlyPaCacheFamily {
    param([Parameter(Mandatory)][string]$CacheDirectory,[Parameter(Mandatory)][string]$Pattern)
    foreach ($source in Get-ChildItem -LiteralPath $CacheDirectory -Filter $Pattern -File) {
      $target = Join-Path $runtimeDir $source.Name
      if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Force }
      try {
        New-Item -ItemType HardLink -Path $target -Target $source.FullName -ErrorAction Stop | Out-Null
      } catch {
        Copy-Item -LiteralPath $source.FullName -Destination $target -Force
      }
    }
  }
  if ($hasFlightTubeRebuild -and (Test-Path -LiteralPath $flightTubeCachePa0 -PathType Leaf)) {
    Use-ReadOnlyPaCacheFamily -CacheDirectory $flightTubeCacheDir -Pattern 'flight_tube_ground.pa*'
    $hasFlightTubeRebuild = $false
  }
  if ($hasReflectronRebuild -and
      (Test-Path -LiteralPath $reflectronCachePa0 -PathType Leaf) -and
      (Test-Path -LiteralPath (Join-Path $reflectronCacheDir 'reflectron.pa1') -PathType Leaf)) {
    Use-ReadOnlyPaCacheFamily -CacheDirectory $reflectronCacheDir -Pattern 'reflectron.pa*'
    $hasReflectronRebuild = $false
  }
  if ($hasFlightTubeRebuild) {
    $flightTubeBuilderFrozen = Join-Path $package.input_dir 'build_flight_tube_variant.lua'
    $flightTubeGemFrozen = Join-Path $package.input_dir 'oatof_flight_tube_ground.gem'
    Copy-RfStableFile -SourceRunRoot $repoRoot `
      -SourcePath $flightTubeBuilderSource `
      -Destination $flightTubeBuilderFrozen -Role 'candidate flight-tube SIMION builder' | Out-Null
    Copy-RfStableFile -SourceRunRoot $repoRoot `
      -SourcePath $flightTubeGemSource `
      -Destination $flightTubeGemFrozen -Role 'candidate flight-tube SIMION GEM' | Out-Null
    $flightTubeBuildStdout = Join-Path $package.log_dir 'flight_tube_build.stdout.log'
    $flightTubeBuildStderr = Join-Path $package.log_dir 'flight_tube_build.stderr.log'
    $geometry = $oatofGeometryDocument.geometry_mm
    $build = $oatofGeometryDocument.simion_geometry_build.flight_tube
    $flightTubeBuild = Invoke-ResourceBudgetedProcess `
      -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
      -UsagePath (Join-Path $package.log_dir 'flight_tube_build_resource_usage.json') `
      -FilePath $SimionExe -WorkingDirectory $runtimeDir `
      -RedirectStandardOutput $flightTubeBuildStdout `
      -RedirectStandardError $flightTubeBuildStderr -ArgumentList @(
        '--nogui','--noprompt','lua',$flightTubeBuilderFrozen,$flightTubeGemFrozen,
        (Join-Path $runtimeDir 'flight_tube_ground.pa#'),
        ([string]$build.cell_axial_mm),([string]$build.cell_radial_mm),
        ([string]$build.max_gib),([string]$geometry.flight_tube_r),
        ([string]$geometry.flight_tube_wall),
        ([string]$geometry.shield_endcap_thickness),
        ([string]$geometry.shield_outer_z_min),([string]$geometry.L_flight))
    if ($flightTubeBuild.resource_budget_exceeded) {
      $resourceBudgetExceeded=$true
      throw 'Candidate flight-tube PA build exceeded its resource budget.'
    }
    if ($flightTubeBuild.exit_code -ne 0 -or
        -not (Test-Path -LiteralPath (Join-Path $runtimeDir 'flight_tube_ground.pa0') -PathType Leaf)) {
      throw 'Candidate flight-tube PA build failed.'
    }
    New-Item -ItemType Directory -Path $flightTubeCacheDir -Force | Out-Null
    Get-ChildItem -LiteralPath $runtimeDir -Filter 'flight_tube_ground.pa*' -File | Copy-Item -Destination $flightTubeCacheDir -Force
  }
  if ($hasReflectronRebuild) {
    $reflectronBuilderFrozen = Join-Path $package.input_dir 'build_reflectron_variant.lua'
    $reflectronGemFrozen = Join-Path $package.input_dir 'oatof_reflectron_ideal_10_5.gem'
    Copy-RfStableFile -SourceRunRoot $repoRoot `
      -SourcePath $reflectronBuilderSource `
      -Destination $reflectronBuilderFrozen -Role 'candidate reflectron SIMION builder' | Out-Null
    Copy-RfStableFile -SourceRunRoot $repoRoot `
      -SourcePath $reflectronGemSource `
      -Destination $reflectronGemFrozen -Role 'candidate reflectron SIMION GEM' | Out-Null
    $reflectronRefinerFrozen = Join-Path $package.input_dir 'refine_single_pa.lua'
    Copy-RfStableFile -SourceRunRoot $repoRoot `
      -SourcePath $reflectronRefinerSource `
      -Destination $reflectronRefinerFrozen -Role 'candidate reflectron segmented refiner' | Out-Null
    $reflectronBuildStdout = Join-Path $package.log_dir 'reflectron_build.stdout.log'
    $reflectronBuildStderr = Join-Path $package.log_dir 'reflectron_build.stderr.log'
    $geometry = $oatofGeometryDocument.geometry_mm
    $build = $oatofGeometryDocument.simion_geometry_build.reflectron
    $rings = $oatofGeometryDocument.rings
    $voltage = $oatofGeometryDocument.electrodes_V
    $reflectronBuild = Invoke-ResourceBudgetedProcess `
      -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
      -UsagePath (Join-Path $package.log_dir 'reflectron_build_resource_usage.json') `
      -FilePath $SimionExe -WorkingDirectory $runtimeDir `
      -RedirectStandardOutput $reflectronBuildStdout `
      -RedirectStandardError $reflectronBuildStderr -ArgumentList @(
        '--nogui','--noprompt','lua',$reflectronBuilderFrozen,$reflectronGemFrozen,
        (Join-Path $runtimeDir 'reflectron.pa#'),
        ([string]$build.cell_axial_mm),([string]$build.cell_radial_mm),
        ([string]$build.max_gib),([string]$geometry.flight_tube_r),
        ([string]$geometry.flight_tube_wall),([string]$geometry.L_reflectron),
        ([string]$geometry.ring_thickness),([string]$geometry.shield_axial_gap),
        ([string]$geometry.shield_endcap_thickness),([string]$geometry.L_stage1),
        ([string]$geometry.L_stage2),([string]$geometry.bore_r),
        ([string]$geometry.ring_outer_r),([string]$rings.stage1_count),
        ([string]$rings.stage2_count),([string]$voltage.midgrid),
        ([string]$voltage.backplate),'initialize-only')
    if ($reflectronBuild.resource_budget_exceeded) {
      $resourceBudgetExceeded=$true
      throw 'Candidate reflectron PA build exceeded its resource budget.'
    }
    if ($reflectronBuild.exit_code -ne 0) {
      throw 'Candidate reflectron PA initialization failed.'
    }
    $maximumReflectronElectrode = 4 + [int]$rings.stage1_count + [int]$rings.stage2_count
    foreach ($electrode in 0..$maximumReflectronElectrode) {
      $singlePa = Join-Path $runtimeDir "reflectron.pa$electrode"
      $singleRefine = Invoke-ResourceBudgetedProcess `
        -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
        -UsagePath (Join-Path $package.log_dir "reflectron_refine_pa${electrode}_resource_usage.json") `
        -FilePath $SimionExe -WorkingDirectory $runtimeDir `
        -RedirectStandardOutput (Join-Path $package.log_dir "reflectron_refine_pa${electrode}.stdout.log") `
        -RedirectStandardError (Join-Path $package.log_dir "reflectron_refine_pa${electrode}.stderr.log") `
        -ArgumentList @('--nogui','--noprompt','lua',$reflectronRefinerFrozen,$singlePa,'5e-7')
      if ($singleRefine.resource_budget_exceeded) {
        $resourceBudgetExceeded=$true
        throw "Candidate reflectron pa$electrode refine exceeded its resource budget."
      }
      if ($singleRefine.exit_code -ne 0) {
        throw "Candidate reflectron pa$electrode segmented refine failed."
      }
    }
    $assignments = @('1=0')
    foreach ($ringIndex in 1..([int]$rings.stage1_count)) {
      $assignments += "$(1+$ringIndex)=$($voltage.midgrid*$ringIndex/([int]$rings.stage1_count+1))"
    }
    $midgridElectrode = 2 + [int]$rings.stage1_count
    $assignments += "$midgridElectrode=$($voltage.midgrid)"
    foreach ($ringIndex in 1..([int]$rings.stage2_count)) {
      $electrode = $midgridElectrode + $ringIndex
      $ringVoltage = $voltage.midgrid + ($voltage.backplate-$voltage.midgrid)*$ringIndex/([int]$rings.stage2_count+1)
      $assignments += "$electrode=$ringVoltage"
    }
    $assignments += "$(3+[int]$rings.stage1_count+[int]$rings.stage2_count)=$($voltage.backplate)"
    $assignments += "$maximumReflectronElectrode=0"
    $fastAdjust = Invoke-ResourceBudgetedProcess `
      -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
      -UsagePath (Join-Path $package.log_dir 'reflectron_fast_adjust_resource_usage.json') `
      -FilePath $SimionExe -WorkingDirectory $runtimeDir `
      -RedirectStandardOutput (Join-Path $package.log_dir 'reflectron_fast_adjust.stdout.log') `
      -RedirectStandardError (Join-Path $package.log_dir 'reflectron_fast_adjust.stderr.log') `
      -ArgumentList @('--nogui','--noprompt','fastadj',$reflectronPa0,($assignments -join ','))
    if ($fastAdjust.resource_budget_exceeded) {
      $resourceBudgetExceeded=$true
      throw 'Candidate reflectron fast-adjust exceeded its resource budget.'
    }
    if ($fastAdjust.exit_code -ne 0 -or
        -not (Test-Path -LiteralPath $reflectronPa0 -PathType Leaf)) {
      throw 'Candidate reflectron fast-adjust failed.'
    }
    New-Item -ItemType Directory -Path $reflectronCacheDir -Force | Out-Null
    Get-ChildItem -LiteralPath $runtimeDir -Filter 'reflectron.pa*' -File | Copy-Item -Destination $reflectronCacheDir -Force
  }
  $formalLua = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\formal\oatof_ideal_grounded.lua'
  $pulseLua = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\candidates\oatof_handoff_pulse.lua'
  $program = Join-Path $runtimeDir 'oatof_ideal_grounded.lua'
  $programMetadata = Join-Path $package.input_dir 'single_flight_program_build.json'
  $programArguments = @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.build_single_flight_program',
    '--formal',$formalLua,'--pulse-extension',$pulseLua,'--upstream',$upstreamFrozen,
    '--frontend-contract',$frontendContract,'--oatof',$oatofGeometry,
    '--initial-global-state',$globalSource,'--clock-basis',([string]$settings.clock_basis),
    '--output',$program,'--metadata',$programMetadata)
  if ($SamplingMode -eq 'steady_candidate_pool') { $programArguments += '--terminate-after-pulse' }
  Invoke-SingleFlightPython -Arguments $programArguments `
    -Failure 'Single-flight Program build failed.'

  $runConfiguration = [ordered]@{
    schema_version=2; run_id=$RunId; project=$runtime.upstream_project_id; mode='rf_to_oatof_simion_single_flight'; project_root=$repoRoot
    inputs=[ordered]@{ configuration=$configuration; runtime_binding=$runtimeBindingFrozen; resolved_connection=$resolvedFrozen; resolved_source_contract=$sourceContractFrozen; upstream_resolved_design=$upstreamFrozen; oatof_resolved_geometry=$oatofGeometry; pulse_schedule=$pulseScheduleFrozen; resolved_integration_engineering_budget=$budget.frozen_budget; resolved_stage_resource_budget=$budget.stage_budget; mother_particle_source=$motherSource; initial_global_state=$globalSource; ion=$ion; frontend_gem=$frontendGem; frontend_contract=$frontendContract; frontend_aperture_topology_support=$apertureTopologySupport; frontend_aperture_topology_verifier=$apertureVerifier; program_metadata=$programMetadata; candidate_flight_tube_builder=$flightTubeBuilderFrozen; candidate_flight_tube_gem=$flightTubeGemFrozen; candidate_reflectron_builder=$reflectronBuilderFrozen; candidate_reflectron_gem=$reflectronGemFrozen; candidate_reflectron_refiner=$reflectronRefinerFrozen }
    upstream_source_identity=$runtime.source_identity
    parameters=[ordered]@{ connection_profile_id=$ConnectionProfileId; source_branch_id=$SourceBranchId; layout_profile_id=$(if($hasGovernedLayout){$LayoutProfileId}else{$null}); frontend_grid_profile_id=$selectedGridProfileId; frontend_cell_mm_xyz=[ordered]@{x=$frontendCellMmX;y=$frontendCellMmY;z=$frontendCellMmZ}; accelerator_field_profile_id=$selectedFieldProfileId; single_flight_ideal_accel_enable=$idealAcceleratorEnable; max_parallel_batches=$maxParallelBatches; clock_basis=[string]$settings.clock_basis; launched_particle_count=$launched; particle_count=$launched; execution_batch_count=$(if($launched -ge [int]$settings.batching_policy.enabled_at_particle_count){[int]$settings.batching_policy.default_batch_count}else{1}); execution_batches_parallel=$(if($launched -ge [int]$settings.batching_policy.enabled_at_particle_count){[bool]$settings.batching_policy.parallel_after_cache_warmup}else{$false}); aperture_width_mm=$apertureWidthMm; aperture_height_mm=$apertureHeightMm; aperture_boolean_boundary_policy=[string]$apertureDiscretization.boolean_boundary_policy; aperture_grid_warnings=$apertureGridWarnings; frontend_open_aperture_column_count=[int]$apertureTopology.open_column_count; frontend_aperture_guard_electrode_check_passed=[bool]$apertureTopology.guard_electrode_check_passed; frontend_aperture_topology_report_sha256=(Get-FileHash -LiteralPath $apertureTopologyReport -Algorithm SHA256).Hash; rod_end_to_accelerator_shield_mm=1.0; surrounded_transition=$true; accelerator_axis_x_mm=[double]$oatofGeometryDocument.coordinate_convention.accelerator_axis_x; pulse_time_us=$pulseTimeUs; pulse_width_us=$pulseWidthUs; design_compilation=$(if($null -ne $layoutDerivation){$layoutDerivation.design_compilation}else{$null}); source_release_full_width_mm=[double]$oatofGeometryDocument.particle_source.size_z_mm; reflectron_stage2_length_mm=[double]$oatofGeometryDocument.geometry_mm.L_stage2; reflectron_midgrid_voltage_V=[double]$oatofGeometryDocument.electrodes_V.midgrid; reflectron_backplate_voltage_V=[double]$oatofGeometryDocument.electrodes_V.backplate; reflectron_pa0_sha256=(Get-FileHash -LiteralPath $reflectronPa0 -Algorithm SHA256).Hash; frontend_gem_sha256=$frontendHash; frontend_pa0_sha256=(Get-FileHash -LiteralPath $cachePa0 -Algorithm SHA256).Hash }
    artifact_retention=[ordered]@{policy_version=1;class='compact';reason=$null}; formal_gate_passed=$false
  }
  Write-RfJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  Write-RfJson -Path $package.summary -Value ([ordered]@{schema_version=1;role=$summaryRole;status='interrupted';reason='Frozen inputs recorded; SIMION flight not complete.'})
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $repoRoot -RunConfig $package.run_config -Status interrupted -Software @('SIMION 2020','Python 3.11')
  $snapshotReady = $true

  $batchCount = [int]$runConfiguration.parameters.execution_batch_count
  if ($batchCount -gt 1 -and (
      $batchCount -ne 5 -or
      -not [bool]$runConfiguration.parameters.execution_batches_parallel)) {
    throw 'N=1000 single flight requires five parallel execution batches.'
  }
  $ionLines = @(Get-Content -LiteralPath $ion -Encoding UTF8)
  if ($ionLines.Count -ne $launched) {
    throw 'Single-flight ion row count differs from the launched mother sample.'
  }
  $batchRecords = @()
  $quotient = [Math]::Floor($launched / $batchCount)
  $remainder = $launched % $batchCount
  $offset = 0
  foreach ($batchIndex in 1..$batchCount) {
    $count = $quotient + $(if ($batchIndex -le $remainder) { 1 } else { 0 })
    $batchIon = Join-Path $package.input_dir (
      'single_flight_mother_sample__batch{0:D2}.ion' -f $batchIndex
    )
    [IO.File]::WriteAllLines(
      $batchIon,
      [string[]]$ionLines[$offset..($offset + $count - 1)],
      [Text.UTF8Encoding]::new($false)
    )
    $batchRecords += [pscustomobject]@{
      index = $batchIndex
      count = $count
      offset = $offset
      ion = $batchIon
      stdout = Join-Path $package.log_dir (
        'simion__batch{0:D2}.stdout.log' -f $batchIndex
      )
      stderr = Join-Path $package.log_dir (
        'simion__batch{0:D2}.stderr.log' -f $batchIndex
      )
      usage = Join-Path $package.log_dir (
        'resource_usage__batch{0:D2}.json' -f $batchIndex
      )
    }
    $offset += $count
  }
  $stdoutFiles = @($batchRecords | ForEach-Object { $_.stdout })
  $stderrFiles = @($batchRecords | ForEach-Object { $_.stderr })
  $resourceUsageFiles = @($batchRecords | ForEach-Object { $_.usage })
  $oldOverride = $env:OATOF_ACCELERATOR_PA_OVERRIDE
  try {
    $env:OATOF_ACCELERATOR_PA_OVERRIDE = $cachePa0
    for ($waveStart = 0; $waveStart -lt $batchRecords.Count; $waveStart += $maxParallelBatches) {
      $waveEnd = [Math]::Min($waveStart + $maxParallelBatches - 1,$batchRecords.Count - 1)
      $jobs = @()
      foreach ($batch in @($batchRecords[$waveStart..$waveEnd])) {
        $payload = [pscustomobject]@{
        support = Join-Path $repoRoot 'common\multipole\resource_budget_support.ps1'
        budget = $budget.stage_budget
        run_dir = $package.run_dir
        usage = $batch.usage
        executable = $SimionExe
        working_directory = $runtimeDir
        stdout = $batch.stdout
        stderr = $batch.stderr
        accelerator_pa = $cachePa0
        particle_id_offset = [int]$batch.offset
        arguments = [string[]]@(
          '--default-num-particles',([string][Math]::Max(100,[int]$batch.count)),
          '--nogui','--noprompt','fly',
          '--trajectory-quality',([string]$settings.trajectory_quality),
          '--retain-trajectories','0','--particles',$batch.ion,'--programs','1',
          '--adjustable',("trajectory_quality={0}" -f $settings.trajectory_quality),
          '--adjustable','trajectory_log_enable=1',
          '--adjustable',("diagnostic_max_tof_us={0:R}" -f [double]$settings.maximum_time_of_flight_us),
          '--adjustable','handoff_pulse_mode=1',
          '--adjustable',("sf_ideal_accel_enable={0}" -f $idealAcceleratorEnable),
          '--adjustable',("handoff_pulse_time_us={0:R}" -f $pulseTimeUs),
          '--adjustable',("handoff_pulse_width_us={0:R}" -f $pulseWidthUs),
          '--adjustable',("single_flight_rf_steps={0}" -f [int]$settings.rf_steps_per_period),
          (Join-Path $runtimeDir 'oatof_ideal_grounded.iob')
        )
      }
        $jobs += Start-Job -ArgumentList $payload -ScriptBlock {
          param($item)
          . $item.support
          $env:OATOF_ACCELERATOR_PA_OVERRIDE = $item.accelerator_pa
          $env:OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET = [string]$item.particle_id_offset
          Invoke-ResourceBudgetedProcess `
            -ResolvedBudgetPath $item.budget -RunDir $item.run_dir `
            -UsagePath $item.usage -FilePath $item.executable `
            -WorkingDirectory $item.working_directory `
            -RedirectStandardOutput $item.stdout `
            -RedirectStandardError $item.stderr `
            -ArgumentList ([string[]]$item.arguments)
        }
      }
      try {
        foreach ($job in $jobs) {
          $fly = Receive-Job -Job $job -Wait
          if ($job.State -ne 'Completed' -or $null -eq $fly) {
            throw 'Single-flight SIMION batch job failed.'
          }
          if ($fly.resource_budget_exceeded) {
            $resourceBudgetExceeded = $true
            throw 'Single-flight SIMION batch exceeded its resource budget.'
          }
          if ($fly.exit_code -ne 0) {
            throw 'Single-flight SIMION batch failed.'
          }
        }
      } finally {
        $jobs | Remove-Job -Force -ErrorAction SilentlyContinue
      }
    }
  } finally { $env:OATOF_ACCELERATOR_PA_OVERRIDE = $oldOverride }

  $checkpoints = Join-Path $package.result_dir 'single_flight_particle_checkpoints.csv'
  $analysisArguments = @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight',
    '--launched',([string]$launched),'--mass-amu','100',
    '--geometry',$oatofGeometry,'--pulse-time-us',([string]$pulseTimeUs),
    '--clock-basis',([string]$settings.clock_basis),
    '--initial-global-state',$globalSource,
    '--checkpoints',$checkpoints,'--summary',$package.summary)
  foreach ($batch in $batchRecords) {
    $analysisArguments += @(
      '--log',$batch.stdout,
      '--batch-particle-count',([string]$batch.count)
    )
  }
  Invoke-SingleFlightPython -Arguments $analysisArguments `
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
  $outputs = @($checkpoints,$sixPanel,$sixPanelMetadata) + $stdoutFiles + $stderrFiles + $resourceUsageFiles + @($flightTubeBuildStdout,$flightTubeBuildStderr,$reflectronBuildStdout,$reflectronBuildStderr,$package.summary,$retentionActions) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
  foreach ($usage in $resourceUsageFiles) {
    if (-not (Complete-ResourceUsage -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir -UsagePath $usage)) { $resourceBudgetExceeded=$true; throw 'Single-flight compact retained-byte budget exceeded.' }
  }
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
