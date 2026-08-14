[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$RunId,
  [Parameter(Mandatory)][string]$BaselineRunId,
  [Parameter(Mandatory)][string]$IdealRunId,
  [string]$FrontendRunId = '',
  [string[]]$ArmId = @(),
  [string]$ReferenceArmId = '',
  [ValidateRange(0,1000)][int]$DiagnosticParticleLimit = 0,
  [string]$BaselineAggregateRoot = '',
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$integrationRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $integrationRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$runtimeRoot = Join-Path $integrationRoot 'runtime'
$python = if ($PythonExe) {
  [IO.Path]::GetFullPath($PythonExe)
} else {
  Join-Path $repoRoot '.venv\Scripts\python.exe'
}
. (Join-Path $runtimeRoot 'run_artifacts.ps1')
. (Join-Path $runtimeRoot 'single_flight_assets.ps1')
. (Join-Path $repoRoot 'common\multipole\resource_budget_support.ps1')

function Invoke-AttributionPython {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][object[]]$Arguments,
    [Parameter(Mandatory)][string]$Failure
  )
  $saved = Save-RfEnvironment -Names @('PYTHONPATH','PYTHONNOUSERSITE')
  try {
    $env:PYTHONPATH = $repoRoot
    $env:PYTHONNOUSERSITE = '1'
    Push-Location -LiteralPath $repoRoot
    try {
      & $python @Arguments
      if ($LASTEXITCODE -ne 0) { throw $Failure }
    } finally {
      Pop-Location
    }
  } finally {
    Restore-RfEnvironment -Names @('PYTHONPATH','PYTHONNOUSERSITE') `
      -Snapshot $saved
  }
}

function Assert-VerifiedSourceRun {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RunRoot,
    [Parameter(Mandatory)][string]$ExpectedRunId,
    [Parameter(Mandatory)][string]$ExpectedProject,
    [Parameter(Mandatory)][string]$ExpectedMode
  )
  $manifest = Join-Path $RunRoot 'run_manifest.json'
  Invoke-AttributionPython -Arguments @(
    'common/contracts/verify_run_manifest.py', $manifest,
    '--require-status','success',
    '--require-local-run-config',
    '--require-run-id',$ExpectedRunId,
    '--require-project',$ExpectedProject,
    '--require-mode',$ExpectedMode
  ) -Failure "Source run manifest verification failed: $ExpectedRunId"
}

function Copy-AttributionPaFamily {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$SourceDirectory,
    [Parameter(Mandatory)][string]$DestinationDirectory,
    [Parameter(Mandatory)][string]$BaseName
  )
  $sources = @(Get-ChildItem -LiteralPath $SourceDirectory `
    -Filter "$BaseName.pa*" -File)
  if ($sources.Count -lt 2) {
    throw "$BaseName PA family is incomplete."
  }
  Get-ChildItem -LiteralPath $DestinationDirectory -Filter "$BaseName.pa*" `
    -File | Remove-Item -Force
  foreach ($source in $sources) {
    Copy-Item -LiteralPath $source.FullName `
      -Destination (Join-Path $DestinationDirectory $source.Name)
  }
}

if (-not (Test-Path -LiteralPath $SimionExe -PathType Leaf)) {
  throw "SIMION is missing: $SimionExe"
}
$baselineRoot = Join-Path $workspaceRoot (
  "artifacts\projects\rf_octupole_ion_optics\runs\$BaselineRunId"
)
$selectedFrontendRunId = if ($FrontendRunId) { $FrontendRunId } else { $BaselineRunId }
$frontendRoot = Join-Path $workspaceRoot (
  "artifacts\projects\rf_octupole_ion_optics\runs\$selectedFrontendRunId"
)
$formalArtifactRoot = Join-Path $workspaceRoot `
  'artifacts\projects\single_reflection_oa_tof_mass_analyzer\formal'
$formalValidationSource = Join-Path $repoRoot `
  'projects\single_reflection_oa_tof_mass_analyzer\config\formal_validation.json'
Assert-VerifiedSourceRun -RunRoot $baselineRoot -ExpectedRunId $BaselineRunId `
  -ExpectedProject 'rf_octupole_ion_optics' `
  -ExpectedMode 'rf_to_oatof_simion_single_flight'
Assert-VerifiedSourceRun -RunRoot $frontendRoot -ExpectedRunId $selectedFrontendRunId `
  -ExpectedProject 'rf_octupole_ion_optics' `
  -ExpectedMode 'rf_to_oatof_simion_single_flight'
$formalValidation = Get-Content -LiteralPath $formalValidationSource `
  -Raw -Encoding UTF8 | ConvertFrom-Json
$formalIdealSource = Join-Path $formalArtifactRoot 'results\simion_particles.csv'
$formalGeometrySource = Join-Path $formalArtifactRoot `
  'simion\resolved_geometry.json'
$formalDeliveryManifest = Join-Path $formalArtifactRoot 'simion\run_manifest.json'
if ($formalValidation.run_id -ne $IdealRunId -or
    $formalValidation.status -ne 'formal_cross_solver_validation' -or
    (Get-FileHash -LiteralPath $formalIdealSource -Algorithm SHA256).Hash -ne
      [string]$formalValidation.simion.particle_csv_sha256 -or
    (Get-FileHash -LiteralPath $formalDeliveryManifest -Algorithm SHA256).Hash -ne
      [string]$formalValidation.simion.delivery_manifest_sha256) {
  throw 'Published Formal ideal-source identity differs.'
}
$formalDelivery = Get-Content -LiteralPath $formalDeliveryManifest `
  -Raw -Encoding UTF8 | ConvertFrom-Json
$formalGeometryRecords = @($formalDelivery.assets.PSObject.Properties | Where-Object {
  $_.Value.path -eq 'resolved_geometry.json'
})
if ($formalDelivery.release_id -ne $IdealRunId -or
    $formalDelivery.status -ne 'success' -or
    $formalGeometryRecords.Count -ne 1 -or
    (Get-FileHash -LiteralPath $formalGeometrySource -Algorithm SHA256).Hash -ne
      [string]$formalGeometryRecords[0].Value.sha256) {
  throw 'Published Formal resolved-geometry identity differs.'
}

$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_octupole_ion_optics'
$package = New-RfRunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot $artifactRoot -RunId $RunId -Project 'rf_octupole_ion_optics' `
  -Mode 'rf_oatof_resolution_attribution_counterfactual' `
  -Software @('SIMION 2020','Python 3.11') `
  -RetentionContractEnabled -RetentionClass compact `
  -AdditionalDirectories @('simion')
$summaryRole = 'rf_oatof_resolution_attribution_counterfactual_summary'
$snapshotReady = $false
$resourceBudgetExceeded = $false

try {
  $baselineConfig = Get-Content -LiteralPath (
    Join-Path $baselineRoot 'run_config.json'
  ) -Raw -Encoding UTF8 | ConvertFrom-Json
  $frontendConfig = Get-Content -LiteralPath (
    Join-Path $frontendRoot 'run_config.json'
  ) -Raw -Encoding UTF8 | ConvertFrom-Json
  $frontendOverlayEnabled = (
    $frontendConfig.parameters.PSObject.Properties.Name -contains
      'accelerator_overlay_enabled'
  ) -and [bool]$frontendConfig.parameters.accelerator_overlay_enabled
  if (-not ($baselineConfig.parameters.PSObject.Properties.Name -contains
      'resolved_region_field_semantic_sha256')) {
    throw 'Baseline lacks the sole resolved region field authority.'
  }
  foreach ($name in @(
      'upstream_resolved_design.json',
      'oatof_resolved_geometry.json'
  )) {
    $baselineIdentity = (Get-FileHash -LiteralPath (
      Join-Path $baselineRoot "inputs\$name"
    ) -Algorithm SHA256).Hash
    $frontendIdentity = (Get-FileHash -LiteralPath (
      Join-Path $frontendRoot "inputs\$name"
    ) -Algorithm SHA256).Hash
    if ($baselineIdentity -ne $frontendIdentity) {
      throw "Frontend source run changes frozen physical input: $name"
    }
  }
  $baselineConnection = Get-Content -LiteralPath (
    Join-Path $baselineRoot 'inputs\resolved_connection.json'
  ) -Raw -Encoding UTF8 | ConvertFrom-Json
  $frontendConnection = Get-Content -LiteralPath (
    Join-Path $frontendRoot 'inputs\resolved_connection.json'
  ) -Raw -Encoding UTF8 | ConvertFrom-Json
  $baselineConnection.PSObject.Properties.Remove('sources')
  $frontendConnection.PSObject.Properties.Remove('sources')
  $baselinePhysicalConnection = $baselineConnection | ConvertTo-Json `
    -Depth 100 -Compress
  $frontendPhysicalConnection = $frontendConnection | ConvertTo-Json `
    -Depth 100 -Compress
  if ($baselinePhysicalConnection -cne $frontendPhysicalConnection) {
    throw 'Frontend source run changes frozen physical input: resolved_connection.json'
  }
  $baselineCheckpointsSource = Join-Path $baselineRoot `
    'results\single_flight_particle_checkpoints.csv'
  $baselineCheckpointRoot = $baselineRoot
  $motherSampleParticleCount = [int]$baselineConfig.parameters.launched_particle_count
  $baselineAggregate = $null
  if ($BaselineAggregateRoot) {
    $aggregateRoot = (Resolve-Path -LiteralPath $BaselineAggregateRoot).Path
    $baselineCheckpointRoot = $aggregateRoot
    $aggregateSummaryPath = Join-Path $aggregateRoot 'summary.json'
    $baselineCheckpointsSource = Join-Path $aggregateRoot 'particle_checkpoints.csv'
    $baselineAggregate = Get-Content -LiteralPath $aggregateSummaryPath `
      -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($baselineAggregate.status -ne 'success' -or
        $baselineAggregate.role -ne 'rf_oatof_batched_single_flight_aggregate' -or
        $baselineAggregate.census.launched -ne 1000 -or
        $baselineAggregate.batching.batch_count -ne 5 -or
        $baselineAggregate.detector_time_basis -ne 'instrument_time_us' -or
        (Get-FileHash -LiteralPath $baselineCheckpointsSource -Algorithm SHA256).Hash -ne
          [string]$baselineAggregate.checkpoints_sha256) {
      throw 'Baseline aggregate identity or checkpoint hash differs.'
    }
    $baselineGeometryHash = (Get-FileHash -LiteralPath (
      Join-Path $baselineRoot 'inputs\oatof_resolved_geometry.json'
    ) -Algorithm SHA256).Hash
    if ($baselineGeometryHash -ne [string]$baselineAggregate.batching.same_geometry_sha256) {
      throw 'Baseline template geometry differs from the five-batch aggregate.'
    }
    $motherSampleParticleCount = 1000
  }
  if ($baselineConfig.parameters.launched_particle_count -notin @(100,200,1000) -or
      $baselineConfig.parameters.aperture_width_mm -ne 1.0 -or
      $baselineConfig.parameters.aperture_height_mm -ne 0.9 -or
      -not $baselineConfig.parameters.surrounded_transition) {
    throw 'Baseline run is not a frozen N=100/N=200 screening or N=1000, 1.0 x 0.9 mm closed-connector case.'
  }
  $profileSource = Join-Path $integrationRoot `
    'config\resolution_attribution_counterfactual.json'
  $profile = Join-Path $package.input_dir `
    'resolution_attribution_counterfactual.json'
  Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $profileSource `
    -Destination $profile -Role 'resolution-attribution profile' | Out-Null
  $baselineCheckpoints = Join-Path $package.input_dir `
    'baseline_single_flight_particle_checkpoints.csv'
  Copy-RfStableFile -SourceRunRoot $baselineCheckpointRoot `
    -SourcePath $baselineCheckpointsSource `
    -Destination $baselineCheckpoints -Role 'baseline particle checkpoints' | Out-Null
  $idealSource = Join-Path $package.input_dir 'ideal_source_mapping_particles.csv'
  Copy-RfStableFile -SourceRunRoot $formalArtifactRoot `
    -SourcePath $formalIdealSource `
    -Destination $idealSource -Role 'ideal source mapping' | Out-Null
  $formalGeometry = Join-Path $package.input_dir `
    'formal_oatof_resolved_geometry.json'
  Copy-RfStableFile -SourceRunRoot $formalArtifactRoot `
    -SourcePath $formalGeometrySource `
    -Destination $formalGeometry -Role 'formal oaTOF resolved geometry' | Out-Null
  $formalValidationInput = Join-Path $package.input_dir 'formal_validation.json'
  Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath $formalValidationSource -Destination $formalValidationInput `
    -Role 'published Formal validation binding' | Out-Null
  foreach ($name in @(
      'upstream_resolved_design.json',
      'resolved_connection.json',
      'oatof_resolved_geometry.json',
      'resolved_region_field_contract.json'
  )) {
    Copy-RfStableFile -SourceRunRoot $baselineRoot `
      -SourcePath (Join-Path $baselineRoot "inputs\$name") `
      -Destination (Join-Path $package.input_dir $name) `
      -Role "baseline frozen $name" | Out-Null
  }
  Copy-RfStableFile -SourceRunRoot $frontendRoot `
    -SourcePath (Join-Path $frontendRoot `
      'inputs\single_flight_frontend_contract.json') `
    -Destination (Join-Path $package.input_dir `
      'single_flight_frontend_contract.json') `
    -Role 'selected frontend frozen contract' | Out-Null
  $upstream = Get-Content -LiteralPath (
    Join-Path $package.input_dir 'upstream_resolved_design.json'
  ) -Raw -Encoding UTF8 | ConvertFrom-Json
  $budget = Initialize-RfIntegrationStageBudget `
    -ResolvedBudget (Join-Path $baselineRoot `
      'inputs\resolved_integration_engineering_budget.json') `
    -InputDir $package.input_dir `
    -ExpectedIntegrationId `
      'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' `
    -ExpectedConnectionProfileId `
      'rf_octupole_oatof_shield_terminal_direct_mating_gap_0mm' `
    -StageId 'single_flight_transport' -Solver simion

  $preparedDir = Join-Path $package.input_dir 'counterfactual_arms'
  $singleFlightConfiguration = Join-Path $package.input_dir `
    'simion_single_flight.json'
  Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath (Join-Path $integrationRoot 'config\simion_single_flight.json') `
    -Destination $singleFlightConfiguration `
    -Role 'single-flight execution configuration' | Out-Null
  $singleFlightSettings = Get-Content -LiteralPath $singleFlightConfiguration `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $executionBatchCount = [int]$singleFlightSettings.batching_policy.default_batch_count
  if ($executionBatchCount -ne 5 -or
      -not $singleFlightSettings.batching_policy.parallel_after_cache_warmup) {
    throw 'N=1000 attribution requires the governed five-batch parallel policy.'
  }
  $frontendGridProfileId = if (
    $frontendConfig.parameters.PSObject.Properties.Name -contains
      'frontend_grid_profile_id'
  ) {
    [string]$frontendConfig.parameters.frontend_grid_profile_id
  } else {
    [string]$singleFlightSettings.default_frontend_grid_profile_id
  }
  $frontendGridProfiles = @(
    $singleFlightSettings.frontend_grid_profiles | Where-Object {
      $_.profile_id -eq $frontendGridProfileId
    }
  )
  if ($frontendGridProfiles.Count -ne 1) {
    throw 'Selected frontend grid profile cannot be resolved uniquely.'
  }
  $maxParallelBatches = [int]$frontendGridProfiles[0].max_parallel_batches
  if ($maxParallelBatches -lt 1 -or $maxParallelBatches -gt $executionBatchCount) {
    throw 'Frontend grid profile parallel-batch limit differs.'
  }
  $initialPaInstance = if ($frontendOverlayEnabled) { 5 } else { 3 }
  $solverBirthTimeUs = if ($frontendOverlayEnabled) { 0.0 } else { $null }
  $prepareArguments = @(
    '-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.resolution_attribution_counterfactual',
    'prepare','--profile',$profile,'--checkpoints',$baselineCheckpoints,
    '--ideal-source',$idealSource,'--formal-geometry',$formalGeometry,
    '--target-geometry',(Join-Path $package.input_dir `
      'oatof_resolved_geometry.json'),'--output-dir',$preparedDir,
    '--mass-amu','100','--charge-state','1',
    '--rf-frequency-hz',([string][double]$upstream.drive.frequency_Hz),
    '--execution-batch-count',([string]$executionBatchCount),
    '--initial-pa-instance',([string]$initialPaInstance)
  )
  foreach ($selectedArmId in $ArmId) {
    $prepareArguments += @('--arm-id',$selectedArmId)
  }
  if ($DiagnosticParticleLimit -gt 0) {
    $prepareArguments += @('--diagnostic-particle-limit',([string]$DiagnosticParticleLimit))
  }
  if ($null -ne $solverBirthTimeUs) {
    $prepareArguments += @('--solver-birth-time-us',([string]$solverBirthTimeUs))
  }
  Invoke-AttributionPython -Arguments $prepareArguments `
    -Failure 'Counterfactual arm preparation failed.'
  $prepared = Get-Content -LiteralPath (
    Join-Path $preparedDir 'prepared_arms.json'
  ) -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($prepared.paired_cohort_particles -lt 3) {
    throw 'Prepared counterfactual cohort identity differs.'
  }
  if ($prepared.mother_sample_particle_count -ne $motherSampleParticleCount) {
    throw 'Prepared mother-sample count differs from the governed baseline.'
  }
  if ($ReferenceArmId -and
      @($prepared.arms.arm_id) -notcontains $ReferenceArmId) {
    throw "Reference arm was not prepared: $ReferenceArmId"
  }
  $runtimeDir = Join-Path $package.run_dir 'simion'
  $formalDir = Join-Path $workspaceRoot `
    'artifacts\projects\single_reflection_oa_tof_mass_analyzer\formal\simion'
  Copy-RfOatofFormalPaSet -FormalDir $formalDir -Destination $runtimeDir
  # Geometry-changing baselines must replay the exact downstream flight tube
  # selected by run_single_flight.ps1.  The compact source run intentionally
  # does not retain PA files, so resolve its immutable content-addressed cache
  # identity from the same frozen geometry/builder/GEM tuple.
  $downstreamCacheRoot = Join-Path $workspaceRoot `
    'artifacts\projects\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\cache\simion_oatof_downstream_pa'
  $baselineRebuildsFlightTube = (
    $baselineConfig.parameters.PSObject.Properties.Name -contains
      'design_compilation'
  ) -and $null -ne $baselineConfig.parameters.design_compilation -and
    [bool]$baselineConfig.parameters.design_compilation.simion_rebuild_plan.flight_tube_pa
  if ($baselineRebuildsFlightTube) {
    $baselineOatofGeometry = Join-Path $package.input_dir `
      'oatof_resolved_geometry.json'
    $flightTubeBuilderSource = Join-Path $repoRoot `
      'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\build_flight_tube_variant.lua'
    $flightTubeGemSource = Join-Path $repoRoot `
      'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\oatof_flight_tube_ground.gem'
    $flightTubeCacheIdentity = @(
      (Get-FileHash -LiteralPath $baselineOatofGeometry -Algorithm SHA256).Hash,
      (Get-FileHash -LiteralPath $flightTubeBuilderSource -Algorithm SHA256).Hash,
      (Get-FileHash -LiteralPath $flightTubeGemSource -Algorithm SHA256).Hash,
      ''
    ) -join '|'
    $flightTubeCacheKey = [Convert]::ToHexString(
      [Security.Cryptography.SHA256]::HashData(
        [Text.Encoding]::UTF8.GetBytes($flightTubeCacheIdentity)
      )
    ).ToLowerInvariant()
    $currentFlightTubeDir = Join-Path $downstreamCacheRoot $flightTubeCacheKey
    if (-not (Test-Path -LiteralPath (Join-Path $currentFlightTubeDir `
        'flight_tube_ground.pa0') -PathType Leaf)) {
      throw 'Baseline flight-tube PA cache identity differs.'
    }
    Copy-AttributionPaFamily -SourceDirectory $currentFlightTubeDir `
      -DestinationDirectory $runtimeDir -BaseName 'flight_tube_ground'
  }
  $expectedReflectronHash = [string]$baselineConfig.parameters.reflectron_pa0_sha256
  $runtimeReflectronPa0 = Join-Path $runtimeDir 'reflectron.pa0'
  if ((Get-FileHash -LiteralPath $runtimeReflectronPa0 `
      -Algorithm SHA256).Hash -eq $expectedReflectronHash) {
    $currentReflectronDir = $runtimeDir
  } else {
    $cachedReflectronPa0 = Get-ChildItem -LiteralPath $downstreamCacheRoot `
      -Recurse -Filter 'reflectron.pa0' -File | Where-Object {
        (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash -eq
          $expectedReflectronHash
      } | Select-Object -First 1
    if ($null -eq $cachedReflectronPa0) {
      throw 'Baseline reflectron PA cache identity differs.'
    }
    $currentReflectronDir = $cachedReflectronPa0.DirectoryName
  }
  Copy-AttributionPaFamily -SourceDirectory $currentReflectronDir `
    -DestinationDirectory $runtimeDir -BaseName 'reflectron'
  $program = Join-Path $runtimeDir 'oatof_ideal_grounded.lua'
  $programMetadata = Join-Path $package.input_dir `
    'single_flight_program_build.json'
  $resolvedRegionFieldContract = Join-Path $package.input_dir `
    'resolved_region_field_contract.json'
  $replayClockState = Join-Path $preparedDir ([string]$prepared.arms[0].state_file)
  $overlayContract = $null
  $overlayPa0Hash = $null
  $overlayIobHash = $null
  $overlayProgramHash = $null
  if ($frontendOverlayEnabled) {
    $overlayContract = Join-Path $package.input_dir `
      'accelerator_overlay_contract.json'
    Copy-RfStableFile -SourceRunRoot $frontendRoot `
      -SourcePath (Join-Path $frontendRoot `
        'inputs\accelerator_overlay_contract.json') `
      -Destination $overlayContract `
      -Role 'selected accelerator-overlay contract' | Out-Null
    $runtimeIob = Join-Path $runtimeDir 'oatof_ideal_grounded.iob'
    Copy-Item -LiteralPath (Join-Path $frontendRoot `
      'simion\oatof_ideal_grounded.iob') -Destination $runtimeIob -Force
    Invoke-AttributionPython -Arguments @(
      '-m',
      'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.build_single_flight_program',
      '--formal',(Join-Path $repoRoot `
        'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\formal\oatof_ideal_grounded.lua'),
      '--pulse-extension',(Join-Path $repoRoot `
        'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\candidates\oatof_handoff_pulse.lua'),
      '--upstream',(Join-Path $package.input_dir 'upstream_resolved_design.json'),
      '--frontend-contract',(Join-Path $package.input_dir `
        'single_flight_frontend_contract.json'),
      '--accelerator-overlay-contract',$overlayContract,
      '--oatof',(Join-Path $package.input_dir 'oatof_resolved_geometry.json'),
      '--initial-global-state',$replayClockState,
      '--resolved-region-field-contract',$resolvedRegionFieldContract,
      '--output',$program,'--metadata',$programMetadata
    ) -Failure 'Accelerator-overlay replay Program build failed.'
    $overlayCacheRoot = Join-Path $workspaceRoot (
      'artifacts\projects\' +
      'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\' +
      'cache\simion_accelerator_overlay'
    )
    $expectedOverlayPa0Hash = (
      [string]$frontendConfig.parameters.accelerator_overlay_pa0_sha256
    ).ToUpperInvariant()
    $cachedOverlayPa0 = @(Get-ChildItem -LiteralPath $overlayCacheRoot `
      -Recurse -Filter 'accelerator_overlay.pa0' -File | Where-Object {
        $cacheManifestPath = Join-Path $_.DirectoryName 'cache_manifest.json'
        if (-not (Test-Path -LiteralPath $cacheManifestPath -PathType Leaf)) {
          return $false
        }
        $cacheManifest = Get-Content -LiteralPath $cacheManifestPath `
          -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([int]$cacheManifest.schema_version -ne 2) { return $false }
        $cacheKey = [IO.Path]::GetFileName($_.DirectoryName)
        & $python (Join-Path $repoRoot 'common\contracts\verify_artifact_layout.py') `
          (Join-Path $workspaceRoot 'artifacts\projects') `
          --cache-entry $_.DirectoryName `
          --expected-cache-role 'simion_accelerator_overlay_pa_cache' `
          --expected-cache-key $cacheKey `
          --expected-cache-project `
          'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' *> $null
        if ($LASTEXITCODE -ne 0) { return $false }
        $cacheInputs = $cacheManifest.identity.inputs
        (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash -eq
          $expectedOverlayPa0Hash -and
        [string]$cacheInputs.frontend_pa0_sha256 -eq
          [string]$frontendConfig.parameters.frontend_pa0_sha256 -and
        [string]$cacheInputs.overlay_gem_sha256 -eq
          (Get-FileHash -LiteralPath (Join-Path $frontendRoot `
            'inputs\accelerator_overlay.gem') -Algorithm SHA256).Hash
      })
    if ($cachedOverlayPa0.Count -ne 1) {
      throw 'Selected accelerator-overlay PA cache identity differs.'
    }
    Copy-AttributionPaFamily `
      -SourceDirectory $cachedOverlayPa0[0].DirectoryName `
      -DestinationDirectory $runtimeDir -BaseName 'accelerator_overlay'
    $overlayPa0Hash = $expectedOverlayPa0Hash
    $overlayIobHash = (Get-FileHash -LiteralPath $runtimeIob `
      -Algorithm SHA256).Hash
    $overlayProgramHash = (Get-FileHash -LiteralPath $program `
      -Algorithm SHA256).Hash
  } else {
    Invoke-AttributionPython -Arguments @(
      '-m',
      'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.build_single_flight_program',
      '--formal',(Join-Path $repoRoot `
        'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\formal\oatof_ideal_grounded.lua'),
      '--pulse-extension',(Join-Path $repoRoot `
        'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\candidates\oatof_handoff_pulse.lua'),
      '--upstream',(Join-Path $package.input_dir 'upstream_resolved_design.json'),
      '--frontend-contract',(Join-Path $package.input_dir `
        'single_flight_frontend_contract.json'),
      '--oatof',(Join-Path $package.input_dir 'oatof_resolved_geometry.json'),
      '--initial-global-state',$replayClockState,
      '--resolved-region-field-contract',$resolvedRegionFieldContract,
      '--output',$program,'--metadata',$programMetadata
    ) -Failure 'Counterfactual single-flight Program build failed.'
  }
  $frontendHash = ([string]$frontendConfig.parameters.frontend_gem_sha256).ToLowerInvariant()
  $frontendPa0 = Join-Path $workspaceRoot (
    'artifacts\projects\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' +
    "\cache\simion_single_flight_frontend\$frontendHash\frontend.pa0"
  )
  if (-not (Test-Path -LiteralPath $frontendPa0 -PathType Leaf) -or
      (Get-FileHash -LiteralPath $frontendPa0 -Algorithm SHA256).Hash -ne
      ([string]$frontendConfig.parameters.frontend_pa0_sha256).ToUpperInvariant()) {
    throw 'Selected frontend PA cache identity differs.'
  }
  $runConfiguration = [ordered]@{
    schema_version = 2
    run_id = $RunId
    project = 'rf_octupole_ion_optics'
    mode = 'rf_oatof_resolution_attribution_counterfactual'
    project_root = $repoRoot
    inputs = [ordered]@{
      profile = $profile
      single_flight_configuration = $singleFlightConfiguration
      baseline_checkpoints = $baselineCheckpoints
      ideal_source = $idealSource
      formal_oatof_resolved_geometry = $formalGeometry
      formal_validation = $formalValidationInput
      prepared_arms = Join-Path $preparedDir 'prepared_arms.json'
      upstream_resolved_design = Join-Path $package.input_dir `
        'upstream_resolved_design.json'
      single_flight_frontend_contract = Join-Path $package.input_dir `
        'single_flight_frontend_contract.json'
      resolved_connection = Join-Path $package.input_dir 'resolved_connection.json'
      oatof_resolved_geometry = Join-Path $package.input_dir `
        'oatof_resolved_geometry.json'
      resolved_region_field_contract = $resolvedRegionFieldContract
      resolved_integration_engineering_budget = $budget.frozen_budget
      resolved_stage_resource_budget = $budget.stage_budget
      program_metadata = $programMetadata
      accelerator_overlay_contract = $overlayContract
      replay_clock_state = $replayClockState
    }
    source_runs = [ordered]@{
      continuous_baseline_run_id = $BaselineRunId
      frontend_run_id = $selectedFrontendRunId
      ideal_reference_run_id = $IdealRunId
    }
    parameters = [ordered]@{
      mother_sample_particle_count = $motherSampleParticleCount
      paired_cohort_particles = [int]$prepared.paired_cohort_particles
      diagnostic_particle_limit = $(if ($DiagnosticParticleLimit -gt 0) {
        $DiagnosticParticleLimit
      } else {$null})
      initial_pa_instance = $initialPaInstance
      solver_birth_time_us = $solverBirthTimeUs
      arm_count = @($prepared.arms).Count
      execution_batch_count = $executionBatchCount
      execution_batches_parallel = ($maxParallelBatches -gt 1)
      max_parallel_batches = $maxParallelBatches
      frontend_grid_profile_id = $frontendGridProfileId
      pulse_time_us = [double]$prepared.pulse_time_us
      trajectory_quality = 8
      maximum_time_of_flight_us = 90.0
      rf_steps_per_period = 160
      frontend_gem_sha256 = ([string]$frontendConfig.parameters.frontend_gem_sha256)
      frontend_pa0_sha256 = ([string]$frontendConfig.parameters.frontend_pa0_sha256)
      accelerator_overlay_enabled = $frontendOverlayEnabled
      accelerator_overlay_pa0_sha256 = $overlayPa0Hash
      accelerator_overlay_iob_sha256 = $overlayIobHash
      accelerator_overlay_program_sha256 = $overlayProgramHash
      resolved_region_field_contract_inherited = $true
      resolved_region_field_semantic_sha256 =
        [string]$baselineConfig.parameters.resolved_region_field_semantic_sha256
    }
    artifact_retention = [ordered]@{
      policy_version = 1
      class = 'compact'
      reason = $null
    }
    formal_gate_passed = $false
  }
  Write-RfJson -Path $package.run_config -Depth 12 -Value $runConfiguration
  Write-RfJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1
    role = $summaryRole
    status = 'interrupted'
    reason = 'Frozen counterfactual inputs recorded; SIMION arms not complete.'
  })
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $repoRoot `
    -RunConfig $package.run_config -Status interrupted `
    -Software @('SIMION 2020','Python 3.11')
  $snapshotReady = $true

  $oldOverride = $env:OATOF_ACCELERATOR_PA_OVERRIDE
  try {
    $env:OATOF_ACCELERATOR_PA_OVERRIDE = $frontendPa0
    $resourceSupport = Join-Path $repoRoot `
      'common\multipole\resource_budget_support.ps1'
    $frontendOverrides = @(
      '--adjustable','single_flight_rf_steps=160'
    )
    foreach ($arm in $prepared.arms) {
      $currentArmId = [string]$arm.arm_id
      $batches = @($arm.execution_batches)
      for ($offset = 0; $offset -lt $batches.Count; `
          $offset += $maxParallelBatches) {
        $jobs = @()
        foreach ($batch in @($batches | Select-Object `
            -Skip $offset -First $maxParallelBatches)) {
          $batchIndex = [int]$batch.batch_index
          $stem = '{0}__batch{1:D2}' -f $currentArmId,$batchIndex
          # SIMION's particle-file loader still fails on otherwise valid long
          # Windows paths.  Give every batch a short run-local alias; the
          # governed source remains frozen under inputs/counterfactual_arms.
          $runtimeIon = Join-Path $runtimeDir `
            ('cf_b{0:D2}.ion' -f $batchIndex)
          Copy-Item -LiteralPath (Join-Path $preparedDir `
            ([string]$batch.ion_file)) -Destination $runtimeIon -Force
          $payload = [pscustomobject]@{
            support = $resourceSupport
            budget = $budget.stage_budget
            run_dir = $package.run_dir
            usage = Join-Path $package.log_dir "$stem.resource_usage.json"
            executable = $SimionExe
            working_directory = $runtimeDir
            stdout = Join-Path $package.log_dir "$stem.stdout.log"
            stderr = Join-Path $package.log_dir "$stem.stderr.log"
            arguments = [string[]](@(
              '--default-num-particles',([string][Math]::Max(100,[int]$batch.particles)),
              '--nogui','--noprompt','fly','--trajectory-quality','8',
              '--retain-trajectories','0',
              '--particles',$runtimeIon,
              '--programs','1','--adjustable','trajectory_quality=8',
              '--adjustable','trajectory_log_enable=1',
              '--adjustable','diagnostic_max_tof_us=90',
            '--adjustable','handoff_pulse_mode=1',
            '--adjustable',(
                'handoff_pulse_time_us={0:R}' -f [double]$arm.pulse_time_us
              ),
              '--adjustable','handoff_pulse_width_us=1'
            ) + $frontendOverrides + @(
              (Join-Path $runtimeDir 'oatof_ideal_grounded.iob')
            ))
          }
          $jobs += Start-Job -ArgumentList $payload -ScriptBlock {
            param($item)
            . $item.support
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
              throw "Counterfactual SIMION batch job failed: $currentArmId"
            }
            if ($fly.resource_budget_exceeded) {
              $resourceBudgetExceeded = $true
              throw "Counterfactual SIMION batch exceeded its resource budget: $currentArmId"
            }
            if ($fly.exit_code -ne 0) {
              throw "Counterfactual SIMION batch failed: $currentArmId"
            }
          }
        } finally {
          $jobs | Remove-Job -Force -ErrorAction SilentlyContinue
        }
      }
      Write-Output (
        "RESOLUTION_ATTRIBUTION_ARM=PASS ARM=$currentArmId " +
        "BATCHES=$executionBatchCount MAX_PARALLEL=$maxParallelBatches"
      )
    }
  } finally {
    $env:OATOF_ACCELERATOR_PA_OVERRIDE = $oldOverride
  }

  $analysisDir = Join-Path $package.result_dir 'resolution_attribution'
  $selectedReferenceArmId = if ($ReferenceArmId) {
    $ReferenceArmId
  } elseif (@($prepared.arms.arm_id) -contains 'observed_restart_control') {
    'observed_restart_control'
  } else {
    [string]$prepared.arms[0].arm_id
  }
  Invoke-AttributionPython -Arguments @(
    '-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.resolution_attribution_counterfactual',
    'summarize','--profile',$profile,
    '--prepared',(Join-Path $preparedDir 'prepared_arms.json'),
    '--baseline-checkpoints',$baselineCheckpoints,
    '--logs-dir',$package.log_dir,'--output-dir',$analysisDir,
    '--reference-arm-id',$selectedReferenceArmId
  ) -Failure 'Counterfactual result analysis failed.'
  Copy-Item -LiteralPath (Join-Path $analysisDir `
    'resolution_attribution.json') -Destination $package.summary -Force
  $retentionActions = Apply-RunArtifactRetention -Python $python `
    -RepoRoot $repoRoot -RunConfig $package.run_config
  $outputs = @(
    $package.summary,
    (Join-Path $analysisDir 'resolution_attribution.json'),
    (Join-Path $analysisDir 'counterfactual_particle_checkpoints.csv'),
    $retentionActions
  )
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $repoRoot `
    -RunConfig $package.run_config -Status success `
    -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  Write-Output (
    "RESOLUTION_ATTRIBUTION=PASS RUN_ID=$RunId " +
    "ARMS=$(@($prepared.arms).Count) PARTICLES=$($prepared.paired_cohort_particles)"
  )
} catch {
  if ($snapshotReady) {
    Complete-RfFrozenFailedRun -Python $python -FrozenRepoRoot $repoRoot `
      -RunConfig $package.run_config -Summary $package.summary `
      -SummaryRole $summaryRole -Reason $_.Exception.Message `
      -Software @('SIMION 2020','Python 3.11') `
      -Status $(if ($resourceBudgetExceeded) {'interrupted'} else {'failed'}) `
      -FailureClass $(if ($resourceBudgetExceeded) {
        'resource_budget_exceeded'
      } else {''})
  } else {
    Write-RfJson -Path $package.summary -Value ([ordered]@{
      schema_version = 1
      role = $summaryRole
      status = 'failed'
      reason = $_.Exception.Message
      manifest_written = $false
    })
  }
  throw
}
