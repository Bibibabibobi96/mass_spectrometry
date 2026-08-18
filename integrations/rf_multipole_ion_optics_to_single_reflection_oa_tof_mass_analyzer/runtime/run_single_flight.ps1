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
  [Parameter(Mandatory)]
  [ValidateSet('require_existing','build_and_publish_if_missing')]
  [string]$PaCachePolicy,
  [Parameter(Mandatory)]
  [ValidateSet('explicit_campaign_row')]
  [string]$PaCachePolicyProvenance,
  [string]$OatofResolvedGeometry = '',
  [string]$PulseSchedule = '',
  [Parameter(Mandatory)][string]$ResolvedPopulationContract,
  [Parameter(Mandatory)][string]$ResolvedPopulationContractSha256,
  [string]$LayoutProfileId = '',
  [string]$ArchitectureGenerationId = '',
  [string]$ThreeZoneCandidate = '',
  [string]$ThreeZoneCandidateSha256 = '',
  [string]$ThreeZoneTopologyId = '',
  [string]$ThreeZoneGeometryId = '',
  [string]$ThreeZoneFrontendElectrodeTopologyId = '',
  [string]$ThreeZoneFieldId = '',
  [ValidateSet('','n1_smoke_producer','n100_solver_authorized_consumer')]
  [string]$ThreeZoneSolverGateStage = '',
  [string]$ThreeZoneSolverGateId = '',
  [string]$ThreeZoneAuthorizationReceipt = '',
  [string]$ThreeZoneAuthorizationReceiptSha256 = '',
  [string]$ThreeZoneProducerParentManifest = '',
  [string]$ThreeZoneProducerParentManifestSha256 = '',
  [string]$ThreeZoneCampaignId = '',
  [string]$ThreeZoneCampaignSha256 = '',
  [string]$ThreeZoneProducerExperimentId = '',
  [string]$ThreeZoneProducerExperimentRowSha256 = '',
  [string]$ThreeZoneSuccessorExperimentId = '',
  [string]$ThreeZoneSuccessorExperimentRowSha256 = '',
  [string]$ThreeZoneSourceIdentitySha256 = '',
  [int]$ThreeZoneGateParticleCount = 0,
  [double]$ExpectedBoreRadiusMm = 0,
  [double]$ExpectedRingOuterRadiusMm = 0,
  [double]$ExpectedShieldInnerRadiusMm = 0,
  [string]$FrontendGridProfileId = '',
  [string]$OatofNumericalProfileId = '',
  [string]$TrajectoryQualityProfileId = '',
  [string]$TimeIntegrationProfileId = '',
  [string]$SpatialWindowProfileId = '',
  [Parameter(Mandatory)][string]$ResolvedRegionFieldContract,
  [Parameter(Mandatory)][string]$ResolvedRegionFieldContractSha256,
  [Parameter(Mandatory)][string]$ResolvedRegionFieldSemanticSha256,
  [string]$SourceProfileId = '',
  [string]$FieldOverlayId = '',
  [string]$PrePulseSourceState = '',
  [string]$PrePulseSourceStateSha256 = '',
  [int]$PrePulseSourceStateCount = 0,
  [double]$PrePulseRestartPositionToleranceMm = 0,
  [double]$PrePulseRestartVelocityToleranceMPerS = 0,
  [double]$PrePulseRestartClockToleranceUs = 0,
  [double]$PrePulseRestartEnergyToleranceEv = 0,
  [string]$PrePulseRestartValidation = '',
  [string]$PrePulseRestartValidationSha256 = '',
  [string]$StagedGrid2SourceState = '',
  [string]$StagedGrid2SourceStateSha256 = '',
  [int]$StagedGrid2SourceStateCount = 0,
  [ValidateSet(0,3,5)][int]$StagedGrid2StartInstance = 0,
  [string]$StagedGrid2ClockEpochId = '',
  [string]$StagedGrid2ProducerRunId = '',
  [string]$StagedGrid2ProducerManifest = '',
  [string]$StagedGrid2ProducerManifestSha256 = '',
  [string]$StagedGrid2BridgeReceipt = '',
  [string]$StagedGrid2BridgeReceiptSha256 = '',
  [string]$MotherParticleSource = '',
  [string]$MotherParticleSourceSha256 = '',
  [int]$MotherParticleCount = 0,
  [string]$MotherParticleSourceRunRoot = '',
  [string]$MotherParticleSourceReceipt = '',
  [string]$MotherParticleSourceReceiptSha256 = '',
  [switch]$ResolutionQualification,
  [switch]$PulseResolutionN100Screening,
  [string]$PulseResolutionCampaign = '',
  [string]$PulseResolutionCampaignSha256 = '',
  [string]$PulseResolutionExperimentRowSha256 = '',
  [string]$PulseResolutionExperimentId = '',
  [string]$PulseResolutionFieldProfileId = '',
  [string]$PulseResolutionExecutionMode = '',
  [string]$PulseResolutionPrefixPlanRoot = '',
  [string]$PulseResolutionRegistrationAuthority = '',
  [string]$PulseResolutionRegistrationAuthoritySha256 = '',
  [string]$PrePulseTimeSeriesContract = '',
  [string]$PrePulseTimeSeriesContractSha256 = '',
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

function Get-RfSingleFlightParticleLines {
  param(
    [Parameter(Mandatory)][string]$ParticleInput,
    [Parameter(Mandatory)][bool]$RestartFly2
  )
  $lines = @(Get-Content -LiteralPath $ParticleInput -Encoding UTF8)
  if ($RestartFly2) {
    $lines = @($lines | Where-Object { $_ -match '^  standard_beam ' })
  }
  return $lines
}

function Assert-RfStagedLoaderSourceIdentity {
  param(
    [Parameter(Mandatory)][string]$ValidationSourceSha256,
    [Parameter(Mandatory)][string]$DeclaredSourceSha256,
    [Parameter(Mandatory)][string]$PopulationSourceTableSha256
  )
  if ($ValidationSourceSha256 -ne $DeclaredSourceSha256 -or
      $ValidationSourceSha256 -ne $PopulationSourceTableSha256) {
    throw 'Resolved staged loader validation source identity differs.'
  }
}

function Set-RfStagedRunConfigurationIdentity {
  param(
    [Parameter(Mandatory)][System.Collections.IDictionary]$RunConfiguration,
    [Parameter(Mandatory)]$ResolvedBudgetDocument,
    [Parameter(Mandatory)]$ConnectionLineageIdentity
  )
  if (-not ($ResolvedBudgetDocument.PSObject.Properties.Name -contains
      'source_identity') -or
      [string]$ResolvedBudgetDocument.source_identity.authority_role -ne
        'staged_grid2_canonical_source_state') {
    throw 'Resolved engineering budget lacks the staged source identity.'
  }
  $RunConfiguration.Remove('upstream_source_identity')
  $RunConfiguration['source_identity'] = $ResolvedBudgetDocument.source_identity
  $RunConfiguration['connection_lineage'] = [ordered]@{
    authority_scope = 'connection_lineage_only'
    identity = $ConnectionLineageIdentity
  }
}

function Read-RfFrozenResolvedBudgetDocument {
  param([Parameter(Mandatory)]$StageBudgetReceipt)
  if (-not ($StageBudgetReceipt.PSObject.Properties.Name -contains
      'frozen_budget') -or
      [string]::IsNullOrWhiteSpace([string]$StageBudgetReceipt.frozen_budget) -or
      -not (Test-Path -LiteralPath $StageBudgetReceipt.frozen_budget -PathType Leaf)) {
    throw 'Run-local frozen resolved engineering budget is missing.'
  }
  return Get-Content -LiteralPath $StageBudgetReceipt.frozen_budget `
    -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Assert-RfThreeZoneArgumentSet {
  param(
    [Parameter(Mandatory)][string]$LayoutProfileId,
    [string]$Candidate = '',
    [string]$CandidateSha256 = '',
    [string]$TopologyId = '',
    [string]$GeometryId = '',
    [string]$FrontendElectrodeTopologyId = '',
    [string]$FieldId = ''
  )
  $isThreeZoneLayout = $LayoutProfileId -in @(
    'three_zone_t5_primary_v1',
    'three_zone_t5_primary_shaping_rings_1p4_v1'
  )
  $values = @(
    $Candidate,$CandidateSha256,$TopologyId,$GeometryId,
    $FrontendElectrodeTopologyId,$FieldId
  )
  $hasAny = @($values | Where-Object {
    -not [string]::IsNullOrWhiteSpace([string]$_)
  }).Count -gt 0
  $hasAll = @($values | Where-Object {
    [string]::IsNullOrWhiteSpace([string]$_)
  }).Count -eq 0
  if ($isThreeZoneLayout -ne $hasAll -or $hasAny -ne $hasAll) {
    throw 'Three-zone runner arguments and layout identity differ.'
  }
  return $isThreeZoneLayout
}

function Assert-RfThreeZoneRuntimeIdentity {
  param(
    [Parameter(Mandatory)]$Candidate,
    [Parameter(Mandatory)][string]$CandidateSha256,
    [Parameter(Mandatory)]$Geometry,
    [Parameter(Mandatory)][string]$GeometrySha256,
    [Parameter(Mandatory)]$FrontendContract,
    [Parameter(Mandatory)]$FrontendElectrodeTopology,
    [Parameter(Mandatory)]$RegionField,
    [Parameter(Mandatory)]$FieldProfile,
    [Parameter(Mandatory)][string]$LayoutProfileId,
    [Parameter(Mandatory)][string]$ArchitectureGenerationId,
    [Parameter(Mandatory)][string]$TopologyId,
    [Parameter(Mandatory)][string]$GeometryId,
    [Parameter(Mandatory)][string]$FrontendElectrodeTopologyId,
    [Parameter(Mandatory)][string]$FieldId
  )
  if ([int]$Candidate.schema_version -ne 1 -or
      [string]$Candidate.role -ne
      'oatof_three_zone_simion_candidate_resolved' -or
      [string]$Candidate.qualification -ne 'CANDIDATE_ONLY' -or
      [string]$Candidate.compiler_mode -ne
      'T5_FROZEN_PRIMARY_AND_BRANCH_ONLY' -or
      [string]$Candidate.identities.topology_id -ne $TopologyId -or
      [string]$Candidate.identities.geometry_id -ne $GeometryId -or
      [string]$Candidate.identities.field_id -ne
      'three_zone_piecewise_uniform_ideal_field_v1' -or
      [string]$Geometry.single_flight_layout_derivation.layout_profile_id -ne
      $LayoutProfileId -or
      [string]$Geometry.single_flight_layout_derivation.architecture_generation_id -ne
      $ArchitectureGenerationId -or
      [string]$Geometry.single_flight_layout_derivation.design_compilation.candidate.sha256 -ne
      $CandidateSha256 -or
      [string]$Geometry.accelerator_topology.topology_id -ne $TopologyId -or
      [string]$FrontendContract.accelerator_topology_id -ne $TopologyId -or
      [string]$FrontendElectrodeTopology.topology_id -ne
      $FrontendElectrodeTopologyId -or
      [string]$RegionField.layout_geometry.sha256 -ne $GeometrySha256 -or
      [string]$RegionField.semantic.accelerator_topology.topology_id -ne
      $TopologyId -or
      [string]$RegionField.semantic.canonical_profile_id -ne
      [string]$FieldProfile.profile_id -or
      [string]$FieldProfile.topology_id -ne $TopologyId -or
      [string]$FieldProfile.geometry_id -ne $GeometryId -or
      [string]$FieldProfile.frontend_electrode_topology_id -ne
      $FrontendElectrodeTopologyId -or
      [string]$FieldProfile.field_id -ne $FieldId) {
    throw 'Frozen three-zone Candidate/runtime identity differs.'
  }
  foreach ($mappingName in @('planes_global_z_mm','potentials_v')) {
    foreach ($role in @('repeller','intermediate1','intermediate2','exit')) {
      $candidateValue = [double]$Candidate.accelerator_topology.$mappingName.$role
      if ([double]$Geometry.accelerator_topology.$mappingName.$role -ne
          $candidateValue -or
          [double]$RegionField.semantic.accelerator_topology.$mappingName.$role -ne
          $candidateValue) {
        throw 'Frozen three-zone Candidate plane or potential mapping differs.'
      }
    }
  }
}

function Assert-RfThreeZoneCheckpointCensus {
  param(
    [Parameter(Mandatory)][bool]$Required,
    [Parameter(Mandatory)]$Census,
    [Parameter(Mandatory)][int]$LaunchedCount
  )
  if (-not $Required) { return }
  $counts = [ordered]@{}
  foreach ($eventName in @(
      'accelerator_grid1_forward',
      'accelerator_intermediate2_forward',
      'local_accelerator_exit',
      'detector_crossing'
    )) {
    $countProperty = $Census.PSObject.Properties[$eventName]
    if ($null -eq $countProperty) {
      throw 'Three-zone intermediate2 checkpoint census differs.'
    }
    $counts[$eventName] = [int]$countProperty.Value
  }
  if ($LaunchedCount -lt 1 -or
      $counts.accelerator_grid1_forward -lt 1 -or
      $counts.accelerator_intermediate2_forward -lt 1 -or
      $counts.accelerator_grid1_forward -gt $LaunchedCount -or
      $counts.accelerator_intermediate2_forward -gt
        $counts.accelerator_grid1_forward -or
      $counts.local_accelerator_exit -gt
        $counts.accelerator_intermediate2_forward -or
      $counts.detector_crossing -gt $counts.local_accelerator_exit -or
      $counts.local_accelerator_exit -lt 0 -or
      $counts.detector_crossing -lt 0) {
    throw 'Three-zone intermediate2 checkpoint census differs.'
  }
}

function Assert-RfThreeZoneAuthorizationFileBinding {
  param(
    [Parameter(Mandatory)]$Binding,
    [Parameter(Mandatory)][string]$WorkspaceRoot,
    [Parameter(Mandatory)][string]$Role
  )
  $path = [IO.Path]::GetFullPath((Join-Path $WorkspaceRoot ([string]$Binding.path)))
  if (-not $path.StartsWith(
        [IO.Path]::GetFullPath((Join-Path $WorkspaceRoot 'artifacts')) +
          [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
      ) -or
      -not (Test-Path -LiteralPath $path -PathType Leaf) -or
      (Get-Item -LiteralPath $path).Length -ne [long]$Binding.bytes -or
      (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne
        [string]$Binding.sha256) {
    throw "Three-zone N=1 $Role binding is missing or stale."
  }
  return $path
}

function Assert-RfThreeZoneSolverAuthorization {
  param(
    [AllowEmptyString()][Parameter(Mandatory)][string]$Stage,
    [Parameter(Mandatory)][int]$ParticleCount,
    [string]$ReceiptPath = '',
    [string]$ReceiptSha256 = '',
    [string]$ParentManifestPath = '',
    [string]$ParentManifestSha256 = '',
    [string]$GateId = '',
    [string]$CampaignId = '',
    [string]$CampaignSha256 = '',
    [string]$ProducerExperimentId = '',
    [string]$ProducerExperimentRowSha256 = '',
    [string]$SuccessorExperimentId = '',
    [string]$SuccessorExperimentRowSha256 = '',
    [string]$CandidateSha256 = '',
    [string]$LayoutProfileId = '',
    [string]$ArchitectureGenerationId = '',
    [string]$TopologyId = '',
    [string]$GeometryId = '',
    [string]$FrontendElectrodeTopologyId = '',
    [string]$AcceleratorFieldProfileId = '',
    [string]$FieldId = '',
    [string]$RegionFieldSemanticSha256 = '',
    [string]$SourceIdentitySha256 = '',
    [Parameter(Mandatory)][string]$WorkspaceRoot
  )
  $authorizationFiles = @(
    $ReceiptPath,$ReceiptSha256,$ParentManifestPath,$ParentManifestSha256
  )
  $authorizationValues = @(
    $ReceiptPath,$ReceiptSha256,$ParentManifestPath,$ParentManifestSha256,
    $GateId,$CampaignId,$CampaignSha256,$ProducerExperimentId,
    $ProducerExperimentRowSha256,$SuccessorExperimentId,
    $SuccessorExperimentRowSha256,$SourceIdentitySha256
  )
  $hasAuthorization = @($authorizationFiles | Where-Object {
    -not [string]::IsNullOrWhiteSpace([string]$_)
  }).Count -gt 0
  if ($Stage -eq 'n1_smoke_producer') {
    if ($ParticleCount -ne 1 -or $hasAuthorization) {
      throw 'Three-zone N=1 producer must freeze one particle and prohibit authorization input.'
    }
    return
  }
  if ([string]::IsNullOrWhiteSpace($Stage)) {
    if (@($authorizationValues | Where-Object {
          -not [string]::IsNullOrWhiteSpace([string]$_)
        }).Count -gt 0) {
      throw 'Non-gated three-zone run cannot consume N=1 authorization.'
    }
    return
  }
  if ($Stage -ne 'n100_solver_authorized_consumer' -or
      $ParticleCount -ne 100 -or
      @($authorizationValues | Where-Object {
        [string]::IsNullOrWhiteSpace([string]$_)
      }).Count -ne 0) {
    throw 'Three-zone N=100 consumer authorization arguments are incomplete.'
  }
  foreach ($file in @(
      @{Path=$ReceiptPath;Sha=$ReceiptSha256;Role='authorization receipt'},
      @{Path=$ParentManifestPath;Sha=$ParentManifestSha256;Role='producer parent manifest'}
    )) {
    if (-not (Test-Path -LiteralPath $file.Path -PathType Leaf) -or
        (Get-FileHash -LiteralPath $file.Path -Algorithm SHA256).Hash -ne
          $file.Sha) {
      throw "Three-zone N=1 $($file.Role) is missing or stale."
    }
  }
  $parentManifest = Get-Content -LiteralPath $ParentManifestPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $receipt = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
  if ([string]$parentManifest.role -ne 'simulation_run_manifest' -or
      [string]$parentManifest.project -ne
        'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' -or
      [string]$parentManifest.mode -ne 'multipole_family_source_closure' -or
      [string]$parentManifest.status -ne 'success' -or
      [bool]$parentManifest.formal_eligible -or
      [string]$parentManifest.run_id -ne [string]$receipt.producer.integration_run_id) {
    throw 'Three-zone N=1 producer parent manifest identity/status differs.'
  }
  $receiptRecord = Get-RfManifestOutputRecord -Manifest $parentManifest `
    -ExpectedPath $ReceiptPath -Role 'three-zone N=1 authorization receipt'
  if ([long]$receiptRecord.bytes -ne (Get-Item -LiteralPath $ReceiptPath).Length -or
      [string]$receiptRecord.sha256 -ne $ReceiptSha256) {
    throw 'Three-zone N=1 authorization receipt is not the frozen parent output.'
  }
  $expectedSequence = @(
    'source_release','pre_pulse_state',
    'accelerator_grid1_forward','accelerator_intermediate2_forward',
    'local_accelerator_exit','reflectron_entrance_forward',
    'reflectron_turning_point','reflectron_exit_return','detector_crossing'
  )
  $identityDiffers = (
    [int]$receipt.schema_version -ne 1 -or
    [string]$receipt.role -ne
      'rf_oatof_three_zone_n1_solver_authorization_receipt' -or
    [string]$receipt.gate_id -ne $GateId -or
    [string]$receipt.decision -ne 'PASS' -or
    [string]$receipt.authorization_status -ne 'N100_SOLVER_AUTHORIZED' -or
    [bool]$receipt.formal_gate_passed -or
    @($receipt.failure_codes).Count -ne 0 -or
    [string]$receipt.campaign.campaign_id -ne $CampaignId -or
    [string]$receipt.campaign.campaign_sha256 -ne $CampaignSha256 -or
    [string]$receipt.producer.experiment_id -ne $ProducerExperimentId -or
    [string]$receipt.producer.experiment_row_sha256 -ne
      $ProducerExperimentRowSha256 -or
    [string]$receipt.authorized_successor.experiment_id -ne
      $SuccessorExperimentId -or
    [string]$receipt.authorized_successor.experiment_row_sha256 -ne
      $SuccessorExperimentRowSha256 -or
    [int]$receipt.authorized_successor.particle_count -ne 100 -or
    [string]$receipt.identities.candidate_sha256 -ne $CandidateSha256 -or
    [string]$receipt.identities.layout_profile_id -ne $LayoutProfileId -or
    [string]$receipt.identities.architecture_generation_id -ne
      $ArchitectureGenerationId -or
    [string]$receipt.identities.topology_id -ne $TopologyId -or
    [string]$receipt.identities.geometry_id -ne $GeometryId -or
    [string]$receipt.identities.frontend_electrode_topology_id -ne
      $FrontendElectrodeTopologyId -or
    [string]$receipt.identities.accelerator_field_profile_id -ne
      $AcceleratorFieldProfileId -or
    [string]$receipt.identities.field_id -ne $FieldId -or
    [string]$receipt.identities.resolved_region_field_semantic_sha256 -ne
      $RegionFieldSemanticSha256 -or
    [string]$receipt.identities.source_identity_sha256 -ne
      $SourceIdentitySha256 -or
    (@($receipt.evidence.required_event_sequence) -join ',') -ne
      ($expectedSequence -join ',')
  )
  if ($identityDiffers) {
    throw 'Three-zone N=1 authorization receipt identity or decision differs.'
  }
  foreach ($event in $expectedSequence[2..8]) {
    if ([int]$receipt.evidence.census.$event -ne 1) {
      throw 'Three-zone N=1 authorization census differs.'
    }
  }
  if ([int]$receipt.evidence.census.launched -ne 1) {
    throw 'Three-zone N=1 authorization census differs.'
  }
  $transportManifestPath = Assert-RfThreeZoneAuthorizationFileBinding `
    -Binding $receipt.producer.transport_manifest -WorkspaceRoot $WorkspaceRoot `
    -Role 'transport manifest'
  foreach ($binding in @(
      @{Value=$receipt.evidence.summary;Role='summary'},
      @{Value=$receipt.evidence.checkpoints;Role='checkpoints'}
    )) {
    Assert-RfThreeZoneAuthorizationFileBinding -Binding $binding.Value `
      -WorkspaceRoot $WorkspaceRoot -Role $binding.Role | Out-Null
  }
  $transportManifest = Get-Content -LiteralPath $transportManifestPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ([string]$transportManifest.role -ne 'simulation_run_manifest' -or
      [string]$transportManifest.run_id -ne
        [string]$receipt.producer.transport_run_id -or
      [string]$transportManifest.project -ne
        'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' -or
      [string]$transportManifest.mode -ne 'rf_to_oatof_simion_single_flight' -or
      [string]$transportManifest.status -ne 'success' -or
      [bool]$transportManifest.formal_eligible) {
    throw 'Three-zone N=1 transport manifest identity/status differs.'
  }
}

$hasThreeZoneCandidate = Assert-RfThreeZoneArgumentSet -LayoutProfileId $LayoutProfileId -Candidate $ThreeZoneCandidate -CandidateSha256 $ThreeZoneCandidateSha256 -TopologyId $ThreeZoneTopologyId -GeometryId $ThreeZoneGeometryId -FrontendElectrodeTopologyId $ThreeZoneFrontendElectrodeTopologyId -FieldId $ThreeZoneFieldId

if (-not (Test-Path -LiteralPath $SimionExe -PathType Leaf)) { throw "SIMION is missing: $SimionExe" }
$runProjectId = 'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer'
$simionSolverCacheIdentity = Get-RfSimionSolverCacheIdentity -SimionExe $SimionExe
$isPrePulseTimeSeriesScreening = -not [string]::IsNullOrWhiteSpace(
  $PrePulseTimeSeriesContract
)
if ($isPrePulseTimeSeriesScreening -ne (-not [string]::IsNullOrWhiteSpace(
      $PrePulseTimeSeriesContractSha256))) {
  throw 'Pre-pulse time-series contract path/hash identity is incomplete.'
}
if ($isPrePulseTimeSeriesScreening -and (
    $ResolutionQualification -or $PulseResolutionN100Screening -or
    $PaCachePolicy -notin @('require_existing','build_and_publish_if_missing'))) {
  throw 'Pre-pulse time-series screening requires FUNCTIONAL_ONLY cache-governed execution.'
}
if ($PulseResolutionN100Screening) {
  $isBaseline = $PulseResolutionExecutionMode -eq `
    'screening_prefix_n100_baseline_registration'
  $isPaired = $PulseResolutionExecutionMode -eq `
    'screening_prefix_n100_paired_candidate'
  if (-not ($isBaseline -or $isPaired) -or
      $ResolutionQualification -or
      [string]::IsNullOrWhiteSpace($PulseResolutionExperimentId) -or
      [string]::IsNullOrWhiteSpace($PulseResolutionCampaign) -or
      [string]::IsNullOrWhiteSpace($PulseResolutionCampaignSha256) -or
      [string]::IsNullOrWhiteSpace($PulseResolutionExperimentRowSha256)) {
    throw 'Real multipole beam + real accelerator field + real reflectron field deterministic N=100 baseline result contract differs.'
  }
  if (($isBaseline -and $PulseResolutionFieldProfileId -ne 'accelerator_real_pa') -or
      ($isPaired -and $PulseResolutionFieldProfileId -eq 'accelerator_real_pa')) {
    throw 'Pulse-resolution field identity conflicts with execution mode.'
  }
}
$artifactRoot = Join-Path $workspaceRoot "artifacts\projects\$runProjectId"
$package = New-RfRunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project $runProjectId -Mode 'rf_to_oatof_simion_single_flight' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -AdditionalDirectories @('simion')
$resourceBudgetExceeded = $false
$snapshotReady = $false
$summaryRole = 'rf_oatof_simion_single_flight_summary'
$resourceUsage = Join-Path $package.log_dir 'resource_usage.json'
$paCacheDispositions = [ordered]@{
  frontend = [ordered]@{
    role='simion_single_flight_frontend_pa_cache';key=$null
    disposition='pending_cache_decision'
  }
  accelerator_overlay = [ordered]@{
    role='simion_accelerator_overlay_pa_cache';key=$null
    disposition='pending_cache_decision'
  }
  flight_tube = [ordered]@{
    role='simion_oatof_flight_tube_pa_cache';key=$null
    disposition='pending_cache_decision'
  }
  reflectron = [ordered]@{
    role='simion_oatof_reflectron_pa_cache';key=$null
    disposition='pending_cache_decision'
  }
}
$prePulseTimeSeriesContractFrozen = $null
$prePulseTimeSeries = $null
if ($isPrePulseTimeSeriesScreening) {
  $prePulseTimeSeriesContractFrozen = Join-Path $package.input_dir `
    'pre_pulse_time_series_screening_contract.json'
  Copy-RfStableFile -SourceRunRoot $workspaceRoot `
    -SourcePath $PrePulseTimeSeriesContract `
    -Destination $prePulseTimeSeriesContractFrozen `
    -Role 'pre-pulse time-series screening contract' | Out-Null
  if ((Get-FileHash -LiteralPath $prePulseTimeSeriesContractFrozen -Algorithm SHA256).Hash -ne
      $PrePulseTimeSeriesContractSha256) {
    throw 'Pre-pulse time-series screening contract SHA differs.'
  }
  $prePulseTimeSeries = Get-Content -LiteralPath $prePulseTimeSeriesContractFrozen `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ([int]$prePulseTimeSeries.schema_version -notin @(1, 2) -or
      [string]$prePulseTimeSeries.role -ne
        'rf_oatof_pre_pulse_time_series_screening_contract' -or
      [string]$prePulseTimeSeries.mode -ne 'real_pa_rf_pre_pulse_time_series' -or
      [string]$prePulseTimeSeries.active_scope -ne
        'pre_pulse_frontend_accelerator' -or
      -not [bool]$prePulseTimeSeries.pulse_disabled -or
      -not [bool]$prePulseTimeSeries.terminate_at_window_end -or
      [bool]$prePulseTimeSeries.resolution_claim_allowed -or
      (@($prePulseTimeSeries.prohibited_outputs) -join ',') -ne
        'detector_crossing,resolution_metrics,single_flight_spatial_six_panel' -or
      @($prePulseTimeSeries.sample_times_us).Count -lt 1) {
    throw 'Pre-pulse time-series screening contract mode/output policy differs.'
  }
}
$preCacheRunConfiguration = [ordered]@{
  schema_version=2;run_id=$RunId;project=$runProjectId
  mode='rf_to_oatof_simion_single_flight';project_root=$repoRoot
  inputs=[ordered]@{}
  parameters=[ordered]@{
    lifecycle_stage='pa_cache_policy_pending_budget_validation'
    connection_profile_id=$ConnectionProfileId
    source_branch_id=$SourceBranchId
    single_flight_pa_cache_policy=$PaCachePolicy
    single_flight_pa_cache_policy_provenance=$PaCachePolicyProvenance
    pa_cache_dispositions=$paCacheDispositions
  }
  formal_gate_passed=$false
  artifact_retention=[ordered]@{policy_version=1;class='compact';reason=$null}
}
function Write-RfPreCacheRunConfiguration {
  param([Parameter(Mandatory)][string]$LifecycleStage)
  $preCacheRunConfiguration.parameters.lifecycle_stage = $LifecycleStage
  Write-RfJson -Path $package.run_config -Depth 10 -Value $preCacheRunConfiguration
}
Write-RfPreCacheRunConfiguration `
  -LifecycleStage 'pa_cache_policy_pending_budget_validation'

try {
  $budget = Initialize-RfIntegrationStageBudget -ResolvedBudget $ResolvedEngineeringBudget `
    -InputDir $package.input_dir -ExpectedIntegrationId `
    'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' `
    -ExpectedConnectionProfileId $ConnectionProfileId -StageId 'single_flight_transport' -Solver simion
  $resolvedBudgetDocument = Read-RfFrozenResolvedBudgetDocument `
    -StageBudgetReceipt $budget
  if ([string]$resolvedBudgetDocument.single_flight_pa_cache_policy -ne
      $PaCachePolicy -or
      [string]$resolvedBudgetDocument.single_flight_pa_cache_policy_provenance -ne
      $PaCachePolicyProvenance) {
    throw 'Runner PA cache policy differs from the frozen resolved engineering budget.'
  }
  $PaCachePolicy = [string]$resolvedBudgetDocument.single_flight_pa_cache_policy
  $PaCachePolicyProvenance = [string](
    $resolvedBudgetDocument.single_flight_pa_cache_policy_provenance
  )
  $preCacheRunConfiguration.parameters.single_flight_pa_cache_policy =
    [string]$resolvedBudgetDocument.single_flight_pa_cache_policy
  $preCacheRunConfiguration.parameters.single_flight_pa_cache_policy_provenance =
    [string]$resolvedBudgetDocument.single_flight_pa_cache_policy_provenance
  Write-RfPreCacheRunConfiguration `
    -LifecycleStage 'pa_cache_policy_frozen_post_budget_validation'
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
    [string]$settings.clock_basis -ne 'canonical_instrument_time_us') {
    throw 'Single-flight numerical configuration is invalid.'
  }
  $frontendCellMmX = [double]$gridProfiles[0].cell_mm_xyz.x
  $frontendCellMmY = [double]$gridProfiles[0].cell_mm_xyz.y
  $frontendCellMmZ = [double]$gridProfiles[0].cell_mm_xyz.z
  $maxParallelBatches = [int]$gridProfiles[0].max_parallel_batches
  $overlayEnabled = $null -ne $gridProfiles[0].PSObject.Properties['accelerator_overlay'] -and
    [bool]$gridProfiles[0].accelerator_overlay.enabled
  $resolvedFieldOverlayId = [string]$gridProfiles[0].field_overlay_id
  if ($FieldOverlayId -and $FieldOverlayId -ne $resolvedFieldOverlayId) {
    throw 'Single-flight field-overlay identity differs from the selected grid profile.'
  }
  $overlayCellMmX = $null
  $overlayCellMmY = $null
  $overlayCellMmZ = $null
  if ($overlayEnabled) {
    $overlayProfile = $gridProfiles[0].accelerator_overlay
    if (@($overlayProfile.PSObject.Properties.Name | Where-Object {
          $_ -notin @('enabled','cell_mm_xyz','boundary_mode','transient_disk_estimate')
        }).Count -ne 0 -or
        [string]$overlayProfile.boundary_mode -ne 'coarse_electrode_basis_dirichlet_v1' -or
        $frontendCellMmX -ne $frontendCellMmY -or $frontendCellMmY -ne $frontendCellMmZ) {
      throw 'Accelerator overlay requires an isotropic coarse grid and the governed boundary mode.'
    }
    $overlayCellMmX = [double]$overlayProfile.cell_mm_xyz.x
    $overlayCellMmY = [double]$overlayProfile.cell_mm_xyz.y
    $overlayCellMmZ = [double]$overlayProfile.cell_mm_xyz.z
    if ($overlayCellMmX -ne $frontendCellMmX -or
        $overlayCellMmY -ne $frontendCellMmY -or
        $overlayCellMmZ -le 0 -or $overlayCellMmZ -gt $frontendCellMmZ) {
      throw 'Accelerator overlay may only refine z while preserving the coarse x-y grid.'
    }
  }
  $selectedOatofNumericalProfileId = if ([string]::IsNullOrWhiteSpace($OatofNumericalProfileId)) {
    [string]$settings.default_oatof_numerical_profile_id
  } else { $OatofNumericalProfileId }
  $oatofNumericalProfiles = @($settings.oatof_numerical_profiles | Where-Object {
    [string]$_.profile_id -eq $selectedOatofNumericalProfileId
  })
  if ($oatofNumericalProfiles.Count -ne 1 -or
      [double]$oatofNumericalProfiles[0].reflectron_cell_mm.axial -le 0 -or
      [double]$oatofNumericalProfiles[0].reflectron_cell_mm.radial -le 0) {
    throw 'Single-flight oaTOF numerical profile is invalid.'
  }
  $selectedTrajectoryQualityProfileId = if ([string]::IsNullOrWhiteSpace($TrajectoryQualityProfileId)) {
    'tqual_8'
  } else { $TrajectoryQualityProfileId }
  $trajectoryQualityProfiles = @($settings.trajectory_quality_profiles | Where-Object {
    [string]$_.profile_id -eq $selectedTrajectoryQualityProfileId
  })
  if ($trajectoryQualityProfiles.Count -ne 1 -or
      [int]$trajectoryQualityProfiles[0].trajectory_quality -notin @(8,108)) {
    throw 'Single-flight trajectory-quality profile is invalid.'
  }
  $trajectoryQuality = [int]$trajectoryQualityProfiles[0].trajectory_quality
  $selectedTimeIntegrationProfileId = if (
    [string]::IsNullOrWhiteSpace($TimeIntegrationProfileId)
  ) {
    [string]$settings.default_time_integration_profile_id
  } else { $TimeIntegrationProfileId }
  $timeIntegrationProfiles = @($settings.time_integration_profiles | Where-Object {
    [string]$_.profile_id -eq $selectedTimeIntegrationProfileId
  })
  if ($timeIntegrationProfiles.Count -ne 1 -or
      [int]$timeIntegrationProfiles[0].rf_steps_per_period -notin @(160,320)) {
    throw 'Single-flight time-integration profile is invalid.'
  }
  $rfStepsPerPeriod = [int]$timeIntegrationProfiles[0].rf_steps_per_period
  $spatialWindowProfiles = @(if ([string]::IsNullOrWhiteSpace($SpatialWindowProfileId)) {
  } else {
    $settings.spatial_window_profiles | Where-Object {
      [string]$_.profile_id -eq $SpatialWindowProfileId
    }
  })
  if (-not [string]::IsNullOrWhiteSpace($SpatialWindowProfileId) -and
      $spatialWindowProfiles.Count -ne 1) {
    throw 'Single-flight spatial-window profile is invalid.'
  }
  $resolvedRegionFieldContractFrozen = Join-Path $package.input_dir 'resolved_region_field_contract.json'
  Copy-RfStableFile -SourceRunRoot $workspaceRoot -SourcePath $ResolvedRegionFieldContract `
    -Destination $resolvedRegionFieldContractFrozen -Role 'resolved region field contract' | Out-Null
  if ((Get-FileHash -LiteralPath $resolvedRegionFieldContractFrozen -Algorithm SHA256).Hash -ne
      $ResolvedRegionFieldContractSha256) {
    throw 'Resolved region field contract SHA differs.'
  }
  $resolvedRegionField = Get-Content -LiteralPath $resolvedRegionFieldContractFrozen -Raw |
    ConvertFrom-Json
  if ($resolvedRegionField.role -ne 'rf_oatof_resolved_region_field_contract' -or
      [string]$resolvedRegionField.semantic_sha256 -ne $ResolvedRegionFieldSemanticSha256 -or
      [bool]$resolvedRegionField.semantic.real_pa_field_blending_allowed) {
    throw 'Resolved region field semantic authority differs.'
  }
  $selectedFieldProfileId = [string]$resolvedRegionField.semantic.canonical_profile_id
  $selectedFieldProfiles = @($settings.accelerator_field_profiles | Where-Object {
    [string]$_.profile_id -eq $selectedFieldProfileId
  })
  if ($hasThreeZoneCandidate -and $selectedFieldProfiles.Count -ne 1) {
    throw 'Three-zone field profile does not resolve uniquely in the frozen configuration.'
  }
  $selectedFieldProfile = if ($selectedFieldProfiles.Count -eq 1) {
    $selectedFieldProfiles[0]
  } else { $null }
  $threeZoneCandidateFrozen = $null
  $threeZoneCandidateDocument = $null
  if ($hasThreeZoneCandidate) {
    $threeZoneCandidateFrozen = Join-Path $package.input_dir 'three_zone_t5_candidate_resolved.json'
    Copy-RfStableFile -SourceRunRoot $workspaceRoot -SourcePath $ThreeZoneCandidate -Destination $threeZoneCandidateFrozen -Role 'three-zone T5 Candidate resolved input' | Out-Null
    if ((Get-FileHash -LiteralPath $threeZoneCandidateFrozen -Algorithm SHA256).Hash -ne
        $ThreeZoneCandidateSha256) {
      throw 'Three-zone T5 Candidate SHA differs.'
    }
    $threeZoneCandidateDocument = Get-Content -LiteralPath $threeZoneCandidateFrozen -Raw -Encoding UTF8 | ConvertFrom-Json
  }
  Assert-RfThreeZoneSolverAuthorization -Stage $ThreeZoneSolverGateStage `
    -ParticleCount $ThreeZoneGateParticleCount `
    -ReceiptPath $ThreeZoneAuthorizationReceipt `
    -ReceiptSha256 $ThreeZoneAuthorizationReceiptSha256 `
    -ParentManifestPath $ThreeZoneProducerParentManifest `
    -ParentManifestSha256 $ThreeZoneProducerParentManifestSha256 `
    -GateId $ThreeZoneSolverGateId -CampaignId $ThreeZoneCampaignId `
    -CampaignSha256 $ThreeZoneCampaignSha256 `
    -ProducerExperimentId $ThreeZoneProducerExperimentId `
    -ProducerExperimentRowSha256 $ThreeZoneProducerExperimentRowSha256 `
    -SuccessorExperimentId $ThreeZoneSuccessorExperimentId `
    -SuccessorExperimentRowSha256 $ThreeZoneSuccessorExperimentRowSha256 `
    -CandidateSha256 $ThreeZoneCandidateSha256 -LayoutProfileId $LayoutProfileId `
    -ArchitectureGenerationId $ArchitectureGenerationId `
    -TopologyId $ThreeZoneTopologyId -GeometryId $ThreeZoneGeometryId `
    -FrontendElectrodeTopologyId $ThreeZoneFrontendElectrodeTopologyId `
    -AcceleratorFieldProfileId $selectedFieldProfileId `
    -FieldId $ThreeZoneFieldId `
    -RegionFieldSemanticSha256 $ResolvedRegionFieldSemanticSha256 `
    -SourceIdentitySha256 $ThreeZoneSourceIdentitySha256 `
    -WorkspaceRoot $workspaceRoot
  $threeZoneAuthorizationReceiptFrozen = $null
  $threeZoneProducerParentManifestFrozen = $null
  if ($ThreeZoneSolverGateStage -eq 'n100_solver_authorized_consumer') {
    $threeZoneAuthorizationReceiptFrozen = Join-Path $package.input_dir `
      'three_zone_n1_solver_authorization_receipt.json'
    Copy-RfStableFile -SourceRunRoot $workspaceRoot `
      -SourcePath $ThreeZoneAuthorizationReceipt `
      -Destination $threeZoneAuthorizationReceiptFrozen `
      -Role 'three-zone N=1 solver authorization receipt' | Out-Null
    $threeZoneProducerParentManifestFrozen = Join-Path $package.input_dir `
      'three_zone_n1_producer_parent_run_manifest.json'
    Copy-RfStableFile -SourceRunRoot $workspaceRoot `
      -SourcePath $ThreeZoneProducerParentManifest `
      -Destination $threeZoneProducerParentManifestFrozen `
      -Role 'three-zone N=1 producer parent manifest' | Out-Null
  }
  $hasGovernedLayout = -not [string]::IsNullOrWhiteSpace($LayoutProfileId)
  $hasGeometry = -not [string]::IsNullOrWhiteSpace($OatofResolvedGeometry)
  $hasPulseSchedule = -not [string]::IsNullOrWhiteSpace($PulseSchedule)
  $resolvedFrozen = Join-Path $package.input_dir 'resolved_connection.json'
  $upstreamFrozen = Join-Path $package.input_dir 'upstream_resolved_design.json'
  $sourceContractFrozen = Join-Path $package.input_dir 'resolved_source_contract.json'
  $populationContractFrozen = Join-Path $package.input_dir 'resolved_population_contract.json'
  $runtimeBindingFrozen = Join-Path $package.input_dir 'runtime_binding.json'
  $oatofGeometry = Join-Path $package.input_dir 'oatof_resolved_geometry.json'
  Copy-Item -LiteralPath $runtime.resolved_connection_path -Destination $resolvedFrozen
  Copy-Item -LiteralPath $runtime.contracts.upstream_resolved_design -Destination $upstreamFrozen
  Copy-Item -LiteralPath $runtime.contracts.resolved_source_contract -Destination $sourceContractFrozen
  Copy-RfStableFile -SourceRunRoot $workspaceRoot `
    -SourcePath $ResolvedPopulationContract -Destination $populationContractFrozen `
    -Role 'resolved single-flight population contract' | Out-Null
  if ((Get-FileHash -LiteralPath $populationContractFrozen -Algorithm SHA256).Hash -ne
      $ResolvedPopulationContractSha256) {
    throw 'Resolved population contract hash differs.'
  }
  $populationContract = Get-Content -LiteralPath $populationContractFrozen -Raw `
    -Encoding UTF8 | ConvertFrom-Json
  if ($populationContract.role -ne 'rf_oatof_resolved_population_contract') {
    throw 'Resolved population contract identity differs.'
  }
  $launched = [int]$populationContract.execution_population.particle_count
  $pairedCohortProperty =
    $populationContract.PSObject.Properties['paired_cohort_authority']
  $hasPairedCohort =
    $null -ne $pairedCohortProperty -and $null -ne $pairedCohortProperty.Value
  $cohortAuthorityModeProperty =
    $populationContract.PSObject.Properties['cohort_authority_mode']
  $cohortAuthorityMode = if ($null -ne $cohortAuthorityModeProperty) {
    [string]$cohortAuthorityModeProperty.Value
  } else { '' }
  if (($cohortAuthorityMode -eq 'establish_observed_authority' -and
       $hasPairedCohort) -or
      ($cohortAuthorityMode -eq 'require_frozen_baseline_authority' -and
       -not $hasPairedCohort)) {
    throw 'Resolved population cohort authority mode and membership differ.'
  }
  $PopulationDenominatorCount = if ($hasPairedCohort) {
    @($populationContract.paired_cohort_authority.source_release.ordered_particle_ids).Count
  } else { [int]$populationContract.denominators.population_count }
  $EligiblePopulationCount = if ($hasPairedCohort) {
    @($populationContract.paired_cohort_authority.pulse_eligible.ordered_particle_ids).Count
  } else { $null }
  $BootstrapResamples = [int]$populationContract.analysis_randomness.bootstrap_resample_count
  $BootstrapSeed = [int]$populationContract.analysis_randomness.bootstrap_seed
  $populationMode = [string]$populationContract.population_mode
  $sourceReleaseMode = [string]$populationContract.source_release_mode
  $isPrePulseRestart = $sourceReleaseMode -eq 'pre_pulse_restart'
  $isStagedGrid2Restart = $sourceReleaseMode -eq 'staged_grid2_restart'
  $stagedLoaderBudgetFrozen = $null
  if ($isStagedGrid2Restart) {
    if ([int]$populationContract.schema_version -ne 2 -or
        $null -eq $populationContract.PSObject.Properties['source_release_validation']) {
      throw 'Solver-authorized staged grid2 restart requires resolved population v2 validation.'
    }
    $sourceValidation = $populationContract.source_release_validation
    Assert-RfStagedLoaderSourceIdentity `
      -ValidationSourceSha256 ([string]$sourceValidation.canonical_source_sha256) `
      -DeclaredSourceSha256 $StagedGrid2SourceStateSha256 `
      -PopulationSourceTableSha256 ([string]$populationContract.source_authority.table.sha256)
    if ([string]$sourceValidation.role -ne
          'rf_oatof_resolved_source_release_validation' -or
        [string]$sourceValidation.representation -ne
          'standard_beam_direct_velocity_vector' -or
        [string]$sourceValidation.identity_position_clock_policy -ne
          'ordered_id_row_map_position_clock_exact' -or
        [double]$sourceValidation.velocity.relative_bound -ne 2e-8 -or
        [double]$sourceValidation.velocity.absolute_floor_m_per_s -ne 0 -or
        -not [bool]$sourceValidation.velocity.zero_speed_must_be_exact -or
        [double]$sourceValidation.derived_energy.relative_bound -ne 3e-8 -or
        [double]$sourceValidation.derived_energy.absolute_floor_eV -ne 0 -or
        -not [bool]$sourceValidation.derived_energy.zero_energy_must_be_exact -or
        [string]$sourceValidation.native_ion_ke_role -ne 'diagnostic_only' -or
        (Get-FileHash -LiteralPath $SimionExe -Algorithm SHA256).Hash -ne
          [string]$sourceValidation.solver_executable_sha256 -or
        (Get-FileHash -LiteralPath (Join-Path $repoRoot `
          'integrations\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\runtime\single_flight_source.py') `
          -Algorithm SHA256).Hash -ne
          [string]$sourceValidation.production_renderer_sha256) {
      throw 'Resolved staged grid2 loader validation identity or budget differs.'
    }
    $budgetRecord = $sourceValidation.loader_authorization_budget
    $budgetSource = [IO.Path]::GetFullPath((Join-Path $repoRoot $budgetRecord.path))
    $stagedLoaderBudgetFrozen = Join-Path $package.input_dir `
      'staged_grid2_loader_authorization_budget.json'
    Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $budgetSource `
      -Destination $stagedLoaderBudgetFrozen `
      -Role 'staged grid2 loader authorization budget' | Out-Null
    if ((Get-FileHash -LiteralPath $stagedLoaderBudgetFrozen -Algorithm SHA256).Hash -ne
        [string]$budgetRecord.sha256) {
      throw 'Staged grid2 loader authorization budget hash differs.'
    }
  }
  Assert-RfOatofSourceAuthorityScope `
    -SourceContract $runtime.resolved_source_contract `
    -StagedGrid2Mode $isStagedGrid2Restart
  if (-not $hasGovernedLayout -or -not $hasGeometry -or
      ($isStagedGrid2Restart -eq $hasPulseSchedule)) {
    throw 'Governed layout/geometry is required; staged grid2 forbids a pulse schedule and other modes require one.'
  }
  if ([string]$populationContract.execution_strategy -ne 'simion_single_flight') {
    throw 'Resolved population execution strategy is not supported by the single-flight runner.'
  }
  $SamplingMode = switch ($populationMode) {
    'continuous_injection_full_population' { 'continuous_injection_full_population' }
    'resolved_layout_pulse_ideal_linear_z_vz' { 'continuous_injection_full_population' }
    'pulse_eligible_conditional' { 'pulse_eligible_conditional' }
    'pre_pulse_restart' { 'governed_upstream_source' }
    'staged_grid2_restart' { 'staged_grid2_canonical_source' }
    'first_100_rows_in_frozen_file_order' { 'continuous_injection_full_population' }
    'staged_three_stage' {
      throw 'Staged-three-stage population cannot execute in the single-flight runner.'
    }
    default { throw "Unsupported resolved population mode: $populationMode" }
  }
  $sourceRegionDiagnosticProfileId = if (
    $isPrePulseTimeSeriesScreening -eq $false -and
    $SamplingMode -notin @('steady_candidate_pool') -and
    -not $isStagedGrid2Restart
  ) {
    [string]$settings.default_source_region_diagnostic_profile_id
  } else { '' }
  $sourceRegionDiagnosticProfiles = @(
    if (-not [string]::IsNullOrWhiteSpace($sourceRegionDiagnosticProfileId)) {
      $settings.source_region_diagnostic_profiles | Where-Object {
        [string]$_.profile_id -eq $sourceRegionDiagnosticProfileId
      }
    }
  )
  if (-not [string]::IsNullOrWhiteSpace($sourceRegionDiagnosticProfileId) -and
      $sourceRegionDiagnosticProfiles.Count -ne 1) {
    throw 'Default source-region diagnostic profile is invalid.'
  }
  if ($ResolutionQualification -and $BootstrapResamples -ne 5000) {
    throw 'Resolution qualification requires exactly 5000 bootstrap resamples.'
  }
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
  if ([double]$oatofGeometryDocument.simion_geometry_build.reflectron.cell_axial_mm -ne
      [double]$oatofNumericalProfiles[0].reflectron_cell_mm.axial -or
      [double]$oatofGeometryDocument.simion_geometry_build.reflectron.cell_radial_mm -ne
      [double]$oatofNumericalProfiles[0].reflectron_cell_mm.radial) {
    throw 'Frozen oaTOF geometry differs from the selected numerical profile.'
  }
  $layoutDerivation = if ($hasGovernedLayout) {
    $oatofGeometryDocument.single_flight_layout_derivation
  } else { $null }
  if ($hasGovernedLayout -and (
      [string]$layoutDerivation.architecture_generation_id -ne $ArchitectureGenerationId -or
      [double]$oatofGeometryDocument.geometry_mm.bore_r -ne $ExpectedBoreRadiusMm -or
      [double]$oatofGeometryDocument.geometry_mm.ring_outer_r -ne $ExpectedRingOuterRadiusMm -or
      [double]$oatofGeometryDocument.geometry_mm.flight_tube_r -ne $ExpectedShieldInnerRadiusMm)) {
    throw 'Frozen oaTOF architecture generation or radius identity differs.'
  }
  $hasReflectronRebuild = (
    -not $isPrePulseTimeSeriesScreening -and
    $SamplingMode -ne 'steady_candidate_pool' -and
    $null -ne $layoutDerivation -and
    $null -ne $layoutDerivation.PSObject.Properties['design_compilation'] -and
    [bool]$layoutDerivation.design_compilation.simion_rebuild_plan.reflectron_pa
  )
  $hasFlightTubeRebuild = (
    -not $isPrePulseTimeSeriesScreening -and
    $SamplingMode -ne 'steady_candidate_pool' -and
    $null -ne $layoutDerivation -and
    $null -ne $layoutDerivation.PSObject.Properties['design_compilation'] -and
    [bool]$layoutDerivation.design_compilation.simion_rebuild_plan.flight_tube_pa
  )
  if (-not $overlayEnabled) {
    $paCacheDispositions.accelerator_overlay.disposition = 'not_applicable'
  }
  if (-not $hasFlightTubeRebuild) {
    $paCacheDispositions.flight_tube.disposition = 'formal'
  }
  if (-not $hasReflectronRebuild) {
    $paCacheDispositions.reflectron.disposition = 'formal'
  }
  Write-RfPreCacheRunConfiguration -LifecycleStage 'pa_cache_policy_frozen_pre_cache'
  $pulseScheduleFrozen = $null
  $pulseTimeUs = $null
  $pulseWidthUs = $null
  if ($hasPulseSchedule) {
    $pulseScheduleFrozen = Join-Path $package.input_dir 'resolved_single_flight_pulse_schedule.json'
    Copy-RfStableFile -SourceRunRoot $workspaceRoot -SourcePath $PulseSchedule `
      -Destination $pulseScheduleFrozen -Role 'single-flight pulse schedule' | Out-Null
    $pulseScheduleDocument = Get-Content -LiteralPath $pulseScheduleFrozen -Raw -Encoding UTF8 |
      ConvertFrom-Json
    if ($pulseScheduleDocument.role -ne 'rf_oatof_resolved_single_flight_pulse_schedule' -or
        $pulseScheduleDocument.layout_profile_id -ne $LayoutProfileId -or
        $pulseScheduleDocument.population_declaration_sha256 -ne
          $populationContract.population_declaration_sha256 -or
        [double]$pulseScheduleDocument.pulse_effective_time_us -le 0 -or
        [double]$pulseScheduleDocument.pulse_width_us -le 0) {
      throw 'Governed single-flight pulse schedule identity differs.'
    }
    $pulseTimeUs = [double]$pulseScheduleDocument.pulse_effective_time_us
    $pulseWidthUs = [double]$pulseScheduleDocument.pulse_width_us
  }

  if ($isPrePulseRestart -ne ($sourceReleaseMode -eq 'pre_pulse_restart') -or
      $isStagedGrid2Restart -ne ($sourceReleaseMode -eq 'staged_grid2_restart')) {
    throw 'Resolved population source-release mode changed during initialization.'
  }
  if ($isPrePulseRestart -ne (-not [string]::IsNullOrWhiteSpace($PrePulseSourceState) -and
      -not [string]::IsNullOrWhiteSpace($PrePulseSourceStateSha256) -and
      $PrePulseSourceStateCount -gt 0)) {
    throw 'Pre-pulse restart source-state identity is incomplete.'
  }
  $hasRestartValidation = -not [string]::IsNullOrWhiteSpace($PrePulseRestartValidation)
  if ($isPrePulseRestart -and $hasRestartValidation -ne (
      -not [string]::IsNullOrWhiteSpace($PrePulseRestartValidationSha256) -and
      $PrePulseRestartPositionToleranceMm -gt 0 -and
      $PrePulseRestartVelocityToleranceMPerS -gt 0 -and
      $PrePulseRestartClockToleranceUs -gt 0 -and
      $PrePulseRestartEnergyToleranceEv -gt 0)) {
    throw 'Pre-pulse restart validation-contract identity is incomplete.'
  }
  $hasStagedGrid2Identity = (
    -not [string]::IsNullOrWhiteSpace($StagedGrid2SourceState) -and
    -not [string]::IsNullOrWhiteSpace($StagedGrid2SourceStateSha256) -and
    $StagedGrid2SourceStateCount -gt 0 -and
    $StagedGrid2StartInstance -in @(3,5) -and
    -not [string]::IsNullOrWhiteSpace($StagedGrid2ClockEpochId) -and
    -not [string]::IsNullOrWhiteSpace($StagedGrid2ProducerRunId) -and
    -not [string]::IsNullOrWhiteSpace($StagedGrid2ProducerManifest) -and
    -not [string]::IsNullOrWhiteSpace($StagedGrid2ProducerManifestSha256)
  )
  if ($isStagedGrid2Restart -ne $hasStagedGrid2Identity) {
    throw 'Staged grid2 restart source/context identity is incomplete.'
  }
  if ($isStagedGrid2Restart -and
      (($StagedGrid2StartInstance -eq 5) -ne [bool]$overlayEnabled)) {
    throw 'Staged grid2 instance 3 requires no overlay and instance 5 requires overlay.'
  }
  $prePulseValidationFrozen = $null
  if ($hasRestartValidation) {
    $prePulseValidationFrozen = Join-Path $package.input_dir `
      'canonical_pulse_restart_target_state_validation.json'
    Copy-RfStableFile -SourceRunRoot $workspaceRoot `
      -SourcePath $PrePulseRestartValidation -Destination $prePulseValidationFrozen `
      -Role 'pre-pulse restart validation contract' | Out-Null
    if ((Get-FileHash -LiteralPath $prePulseValidationFrozen -Algorithm SHA256).Hash -ne
        $PrePulseRestartValidationSha256) {
      throw 'Pre-pulse restart validation-contract hash differs.'
    }
  }
  $motherSource = Join-Path $package.input_dir 'mother_particle_source.csv'
  $hasMotherOverride = -not [string]::IsNullOrWhiteSpace($MotherParticleSource)
  if ($hasMotherOverride -ne (-not [string]::IsNullOrWhiteSpace($MotherParticleSourceSha256) -and $MotherParticleCount -gt 0)) {
    throw 'Single-flight mother-source override identity is incomplete.'
  }
  $hasMaterializedMotherReceipt = -not [string]::IsNullOrWhiteSpace(
    $MotherParticleSourceReceipt
  )
  if ($hasMaterializedMotherReceipt -ne (-not [string]::IsNullOrWhiteSpace(
        $MotherParticleSourceReceiptSha256))) {
    throw 'Materialized mother-source receipt identity is incomplete.'
  }
  if (($isPrePulseRestart -or $isStagedGrid2Restart) -and
      ($hasMotherOverride -or $hasMaterializedMotherReceipt)) {
    throw 'Restart source modes prohibit an unused mother-source override.'
  }
  $hasMotherSourceRunRoot = -not [string]::IsNullOrWhiteSpace(
    $MotherParticleSourceRunRoot
  )
  if ($hasMotherSourceRunRoot -and (-not $hasMotherOverride -or $hasMaterializedMotherReceipt)) {
    throw 'Explicit mother-source run root requires one non-materialized mother-source override.'
  }
  $sourceToCopy = if ($isPrePulseRestart) {
    [IO.Path]::GetFullPath($PrePulseSourceState)
  } elseif ($isStagedGrid2Restart) {
    [IO.Path]::GetFullPath($StagedGrid2SourceState)
  } elseif ($hasMotherOverride) { [IO.Path]::GetFullPath($MotherParticleSource) } else { $runtime.source_particle_source }
  $motherSourceRoot = if ($PulseResolutionN100Screening) {
    [IO.Path]::GetFullPath($PulseResolutionPrefixPlanRoot)
  } elseif ($hasMotherSourceRunRoot) {
    [IO.Path]::GetFullPath($MotherParticleSourceRunRoot)
  } elseif ($isPrePulseRestart -or $isStagedGrid2Restart) { $workspaceRoot } elseif ($hasMaterializedMotherReceipt) {
    Resolve-RfMaterializedMotherSourceRunRoot `
      -WorkspaceRoot $workspaceRoot `
      -SourcePath $sourceToCopy `
      -ReceiptPath $MotherParticleSourceReceipt
  } elseif ($hasMotherOverride) { $repoRoot } else { $workspaceRoot }
  Copy-RfStableFile -SourceRunRoot $motherSourceRoot -SourcePath $sourceToCopy `
    -Destination $motherSource -Role 'single-flight mother particle source' | Out-Null
  $motherSourceReceiptFrozen = $null
  if ($hasMaterializedMotherReceipt) {
    $motherSourceReceiptFrozen = Join-Path $package.input_dir (
      'single_flight_source_materialization_receipt.json'
    )
    Copy-RfStableFile -SourceRunRoot $motherSourceRoot `
      -SourcePath $MotherParticleSourceReceipt `
      -Destination $motherSourceReceiptFrozen `
      -Role 'single-flight source materialization receipt' | Out-Null
    if ((Get-FileHash -LiteralPath $motherSourceReceiptFrozen -Algorithm SHA256).Hash -ne
        $MotherParticleSourceReceiptSha256) {
      throw 'Single-flight source materialization receipt hash differs.'
    }
  }
  if ($isPrePulseRestart -and (Get-FileHash -LiteralPath $motherSource -Algorithm SHA256).Hash -ne $PrePulseSourceStateSha256) {
    throw 'Pre-pulse restart source-state hash differs.'
  }
  if ($isStagedGrid2Restart -and
      (Get-FileHash -LiteralPath $motherSource -Algorithm SHA256).Hash -ne
        $StagedGrid2SourceStateSha256) {
    throw 'Staged grid2 canonical source-state hash differs.'
  }
  $stagedGrid2ProducerManifestFrozen = $null
  $stagedGrid2BridgeReceiptFrozen = $null
  if ($isStagedGrid2Restart) {
    $stagedGrid2ProducerManifestFrozen = Join-Path $package.input_dir `
      'staged_grid2_producer_run_manifest.json'
    Copy-RfStableFile -SourceRunRoot $workspaceRoot `
      -SourcePath $StagedGrid2ProducerManifest `
      -Destination $stagedGrid2ProducerManifestFrozen `
      -Role 'staged grid2 producer run manifest' | Out-Null
    if ((Get-FileHash -LiteralPath $stagedGrid2ProducerManifestFrozen -Algorithm SHA256).Hash -ne
        $StagedGrid2ProducerManifestSha256) {
      throw 'Staged grid2 producer manifest hash differs.'
    }
    $producerManifest = Get-Content -LiteralPath $stagedGrid2ProducerManifestFrozen `
      -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$producerManifest.run_id -ne $StagedGrid2ProducerRunId -or
        [string]$producerManifest.status -ne 'success') {
      throw 'Staged grid2 producer manifest identity or status differs.'
    }
    if (-not [string]::IsNullOrWhiteSpace($StagedGrid2BridgeReceipt)) {
      $stagedGrid2BridgeReceiptFrozen = Join-Path $package.input_dir `
        'staged_grid2_legacy_bridge_receipt.json'
      Copy-RfStableFile -SourceRunRoot $workspaceRoot `
        -SourcePath $StagedGrid2BridgeReceipt `
        -Destination $stagedGrid2BridgeReceiptFrozen `
        -Role 'staged grid2 legacy bridge receipt' | Out-Null
      if ((Get-FileHash -LiteralPath $stagedGrid2BridgeReceiptFrozen -Algorithm SHA256).Hash -ne
          $StagedGrid2BridgeReceiptSha256) {
        throw 'Staged grid2 bridge receipt hash differs.'
      }
    }
  }
  if ($hasMotherOverride -and -not $isPrePulseRestart -and (Get-FileHash -LiteralPath $motherSource -Algorithm SHA256).Hash -ne $MotherParticleSourceSha256) {
    throw 'Single-flight mother-source override hash differs.'
  }
  if (($isPrePulseRestart -and $PrePulseSourceStateCount -ne $launched) -or
      ($isStagedGrid2Restart -and $StagedGrid2SourceStateCount -ne $launched) -or
      ($hasMotherOverride -and $MotherParticleCount -ne $launched) -or
      (-not $isPrePulseRestart -and -not $isStagedGrid2Restart -and
       -not $hasMotherOverride -and
       [int]$runtime.source_record.launched_particle_count -ne $launched)) {
    throw 'Single-flight source count differs from the resolved population authority.'
  }
  if ($SamplingMode -eq 'pulse_eligible_conditional' -and
      ($PopulationDenominatorCount -lt $EligiblePopulationCount -or
       $EligiblePopulationCount -lt $launched)) {
    throw 'Conditional-source population counts are inconsistent.'
  }
  if (@(Import-Csv -LiteralPath $motherSource).Count -ne $launched) {
    throw 'Single-flight mother sample count differs from source authority.'
  }
  $campaignFrozen = $null
  $sourceIdentity = $null
  $registrationAuthorityFrozen = $null
  if ($PulseResolutionN100Screening) {
    $campaignFrozen = Join-Path $package.input_dir 'pulse_resolution_optimization_campaign.json'
    Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $PulseResolutionCampaign `
      -Destination $campaignFrozen -Role 'pulse-resolution campaign' | Out-Null
    if ((Get-FileHash -LiteralPath $campaignFrozen -Algorithm SHA256).Hash -ne
        $PulseResolutionCampaignSha256) { throw 'Pulse-resolution campaign SHA differs.' }
    $registrationAuthorityFrozen = Join-Path $package.input_dir `
      'pulse_resolution_baseline_registration_authority.json'
    Copy-RfStableFile -SourceRunRoot ([IO.Path]::GetFullPath($PulseResolutionPrefixPlanRoot)) `
      -SourcePath $PulseResolutionRegistrationAuthority `
      -Destination $registrationAuthorityFrozen `
      -Role 'pulse-resolution baseline registration authority' | Out-Null
    if ((Get-FileHash -LiteralPath $registrationAuthorityFrozen -Algorithm SHA256).Hash -ne
        $PulseResolutionRegistrationAuthoritySha256) {
      throw 'Pulse-resolution baseline registration authority SHA differs.'
    }
    $sourceIdentity = Join-Path $package.input_dir 'pulse_resolution_source_identity.json'
    $registrationSourceIdentity = [ordered]@{}
    foreach ($property in $runtime.source_identity.PSObject.Properties) {
      $registrationSourceIdentity[$property.Name] = $property.Value
    }
    $registrationSourceIdentity.mother_particle_source_sha256 =
      [string]$runtime.source_identity.particle_source_sha256
    if ($hasPairedCohort) {
      $registrationSourceIdentity['paired_cohort_authority'] =
        $pairedCohortProperty.Value
    }
    Write-RfJson -Path $sourceIdentity -Depth 10 -Value $registrationSourceIdentity
  }
  $frontendGem = Join-Path $package.input_dir 'single_flight_frontend.gem'
  $frontendContract = Join-Path $package.input_dir 'single_flight_frontend_contract.json'
  $overlayGem = if ($overlayEnabled) { Join-Path $package.input_dir 'accelerator_overlay.gem' } else { $null }
  $overlayContract = if ($overlayEnabled) { Join-Path $package.input_dir 'accelerator_overlay_contract.json' } else { $null }
  $frontendCompileArguments = @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_frontend',
    '--upstream',$upstreamFrozen,'--oatof',$oatofGeometry,
    '--connection',$resolvedFrozen,'--gem',$frontendGem,'--contract',$frontendContract,
    '--cell-mm-x',([string]$frontendCellMmX),
    '--cell-mm-y',([string]$frontendCellMmY),
    '--cell-mm-z',([string]$frontendCellMmZ))
  if ($overlayEnabled) {
    $frontendCompileArguments += @(
      '--overlay-gem',$overlayGem,'--overlay-contract',$overlayContract,
      '--overlay-cell-mm-x',([string]$overlayCellMmX),
      '--overlay-cell-mm-y',([string]$overlayCellMmY),
      '--overlay-cell-mm-z',([string]$overlayCellMmZ))
  }
  Invoke-SingleFlightPython -Arguments $frontendCompileArguments `
    -Failure 'Single-flight frontend compilation failed.'
  $frontendGeometry = Get-Content -LiteralPath $frontendContract -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $frontendElectrodeTopologyContract = Join-Path $package.input_dir 'frontend_electrode_topology.json'
  Invoke-SingleFlightPython -Arguments @(
    '-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_electrode_contract',
    '--frontend-contract',$frontendContract,
    '--output',$frontendElectrodeTopologyContract
  ) -Failure 'Single-flight frontend electrode topology resolution failed.'
  $frontendElectrodeTopology = Get-Content -LiteralPath $frontendElectrodeTopologyContract -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $frontendBasisElectrodeIds = @(
    $frontendElectrodeTopology.basis_electrode_ids | ForEach-Object { [int]$_ }
  )
  $maximumFrontendElectrodeId = [int]$frontendElectrodeTopology.maximum_electrode_id
  $expectedFrontendBasisElectrodeIds = @(0..$maximumFrontendElectrodeId)
  if ([string]$frontendElectrodeTopology.role -ne
      'rf_oatof_single_flight_electrode_topology' -or
      [string]::IsNullOrWhiteSpace([string]$frontendElectrodeTopology.topology_id) -or
      [int]$frontendElectrodeTopology.basis_count -ne
      $frontendBasisElectrodeIds.Count -or
      ($frontendBasisElectrodeIds -join ',') -ne
      ($expectedFrontendBasisElectrodeIds -join ',')) {
    throw 'Resolved frontend electrode topology is invalid or non-contiguous.'
  }
  if ($hasThreeZoneCandidate) {
    $threeZoneRuntimeIdentity = @{
      Candidate = $threeZoneCandidateDocument
      CandidateSha256 = $ThreeZoneCandidateSha256
      Geometry = $oatofGeometryDocument
      GeometrySha256 = (
        Get-FileHash -LiteralPath $oatofGeometry -Algorithm SHA256
      ).Hash
      FrontendContract = $frontendGeometry
      FrontendElectrodeTopology = $frontendElectrodeTopology
      RegionField = $resolvedRegionField
      FieldProfile = $selectedFieldProfile
      LayoutProfileId = $LayoutProfileId
      ArchitectureGenerationId = $ArchitectureGenerationId
      TopologyId = $ThreeZoneTopologyId
      GeometryId = $ThreeZoneGeometryId
      FrontendElectrodeTopologyId = $ThreeZoneFrontendElectrodeTopologyId
      FieldId = $ThreeZoneFieldId
    }
    Assert-RfThreeZoneRuntimeIdentity @threeZoneRuntimeIdentity
  }
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
  $frontendCacheRole = 'simion_single_flight_frontend_pa_cache'
  $frontendCacheIdentity = [ordered]@{
    schema_version=2; role=$frontendCacheRole
    project_id=$runProjectId; solver=$simionSolverCacheIdentity
    inputs=[ordered]@{frontend_gem_sha256=$frontendHash}
    critical_options=[ordered]@{
      gem2pa=@('--nogui','--noprompt','gem2pa','frontend.gem','frontend.pa#')
      refine=@('--nogui','--noprompt','refine','frontend.pa#')
    }
  }
  $frontendCacheKey = Get-RfContentIdentitySha256 -Identity $frontendCacheIdentity
  $paCacheDispositions.frontend.key = $frontendCacheKey
  $cacheRoot = Join-Path $workspaceRoot "artifacts\projects\$runProjectId\cache\simion_single_flight_frontend"
  $cacheDir = Join-Path $cacheRoot $frontendCacheKey
  $frontendCacheHit = Test-RfReusableCacheEntry -Python $python `
    -RepoRoot $repoRoot -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId `
    -CacheRoot $cacheRoot -CacheKey $frontendCacheKey -Role $frontendCacheRole `
    -InvalidEntryAction $(if ($PaCachePolicy -eq 'require_existing') {'preserve'} else {'remove'})
  $frontendRefineRequired = -not $frontendCacheHit
  if ($frontendRefineRequired -and $PaCachePolicy -eq 'require_existing') {
    $paCacheDispositions.frontend.disposition = 'cache_miss_required_existing'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'frontend_pa_cache_miss'
    throw "Required PA cache MISS or damage: role=$frontendCacheRole key=$frontendCacheKey"
  }
  if ($frontendRefineRequired) {
    $paCacheDispositions.frontend.disposition = 'cache_miss_build_authorized'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'frontend_pa_cache_build_authorized'
    $frontendBuildDir = New-RfCacheStagingDirectory -CacheRoot $cacheRoot
    try {
    $cacheGem = Join-Path $frontendBuildDir 'frontend.gem'
    $cachePaSharp = Join-Path $frontendBuildDir 'frontend.pa#'
    Copy-Item -LiteralPath $frontendGem -Destination $cacheGem
    $gem2pa = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
      -UsagePath (Join-Path $package.log_dir 'frontend_gem2pa_resource_usage.json') -FilePath $SimionExe `
      -WorkingDirectory $frontendBuildDir -RedirectStandardOutput (Join-Path $package.log_dir 'frontend_gem2pa.stdout.log') `
      -RedirectStandardError (Join-Path $package.log_dir 'frontend_gem2pa.stderr.log') `
      -ArgumentList @('--nogui','--noprompt','gem2pa',$cacheGem,$cachePaSharp)
    if ($gem2pa.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Frontend GEM conversion exceeded its resource budget.' }
    if ($gem2pa.exit_code -ne 0) { throw 'Frontend GEM conversion failed.' }
    $refine = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
      -UsagePath (Join-Path $package.log_dir 'frontend_refine_resource_usage.json') -FilePath $SimionExe `
      -WorkingDirectory $frontendBuildDir -RedirectStandardOutput (Join-Path $package.log_dir 'frontend_refine.stdout.log') `
      -RedirectStandardError (Join-Path $package.log_dir 'frontend_refine.stderr.log') `
      -ArgumentList @('--nogui','--noprompt','refine',$cachePaSharp)
    if ($refine.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Frontend refinement exceeded its resource budget.' }
    if ($refine.exit_code -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $frontendBuildDir 'frontend.pa0') -PathType Leaf)) { throw 'Frontend PA refinement failed.' }
    $cacheDir = Publish-RfVerifiedCacheEntry -Python $python -RepoRoot $repoRoot `
      -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId -CacheRoot $cacheRoot `
      -CacheKey $frontendCacheKey -Role $frontendCacheRole -Identity $frontendCacheIdentity `
      -StagingDirectory $frontendBuildDir -ProviderRunId $RunId
    $paCacheDispositions.frontend.disposition = 'built_and_published'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'frontend_pa_cache_published'
    } catch {
      if (Test-Path -LiteralPath $frontendBuildDir) {
        Remove-Item -LiteralPath $frontendBuildDir -Recurse -Force
      }
      throw
    }
  }
  if (-not $frontendRefineRequired) {
    $paCacheDispositions.frontend.disposition = 'cache_hit'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'frontend_pa_cache_hit'
  }
  $cacheGem = Join-Path $cacheDir 'frontend.gem'; $cachePaSharp = Join-Path $cacheDir 'frontend.pa#'; $cachePa0 = Join-Path $cacheDir 'frontend.pa0'
  $frontendWorkingDir = Join-Path $package.run_dir 'simion\frontend_cache_copy'
  New-Item -ItemType Directory -Path $frontendWorkingDir -Force | Out-Null
  Get-ChildItem -LiteralPath $cacheDir -Filter 'frontend.pa*' -File |
    Copy-Item -Destination $frontendWorkingDir -Force
  $frontendWorkingPa0 = Join-Path $frontendWorkingDir 'frontend.pa0'

  $overlayGeometry = $null
  $overlayCacheDir = $null
  $overlayCachePa0 = $null
  $overlayBasisBuilderFrozen = $null
  $overlayRefinerFrozen = $null
  $overlayKey = $null
  $overlayBasisReport = $null
  $overlayInterfaceVerifierFrozen = $null
  $overlayInterfaceReport = $null
  if ($overlayEnabled) {
    $overlayGeometry = Get-Content -LiteralPath $overlayContract -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($overlayGeometry.role -ne 'rf_oatof_simion_accelerator_overlay_contract' -or
        [string]$overlayGeometry.boundary_condition.mode -ne
        'coarse_electrode_basis_dirichlet_v1' -or
        (@($overlayGeometry.boundary_condition.basis_electrode_ids |
          ForEach-Object { [int]$_ }) -join ',') -ne
        ($frontendBasisElectrodeIds -join ',')) {
      throw 'Compiled accelerator overlay contract is invalid.'
    }
    $overlayBasisBuilderSource = Join-Path $PSScriptRoot 'build_accelerator_overlay_basis.lua'
    $overlayRefinerSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\reflectron\refine_single_pa.lua'
    $overlayInterfaceVerifierSource = Join-Path $PSScriptRoot 'verify_accelerator_overlay_interface.lua'
    $overlayCacheRole = 'simion_accelerator_overlay_pa_cache'
    $overlayIdentity = [ordered]@{
      schema_version=2; role=$overlayCacheRole
      project_id=$runProjectId; solver=$simionSolverCacheIdentity
      inputs=[ordered]@{
        overlay_gem_sha256=(Get-FileHash -LiteralPath $overlayGem -Algorithm SHA256).Hash
        frontend_pa_cache_key=$frontendCacheKey
        basis_builder_sha256=(Get-FileHash -LiteralPath $overlayBasisBuilderSource -Algorithm SHA256).Hash
        refiner_sha256=(Get-FileHash -LiteralPath $overlayRefinerSource -Algorithm SHA256).Hash
        interface_verifier_sha256=(Get-FileHash -LiteralPath $overlayInterfaceVerifierSource -Algorithm SHA256).Hash
      }
      critical_options=[ordered]@{
        boundary_mode='coarse_electrode_basis_dirichlet_v1'
        electrode_topology_id=[string]$frontendElectrodeTopology.topology_id
        basis_count=$frontendBasisElectrodeIds.Count
        gem2pa=@('--nogui','--noprompt','gem2pa','accelerator_overlay.gem','accelerator_overlay.pa#')
        refinement_convergence='5e-7'
        maximum_electrode_id=$maximumFrontendElectrodeId
      }
    }
    $overlayKey = Get-RfContentIdentitySha256 -Identity $overlayIdentity
    $paCacheDispositions.accelerator_overlay.key = $overlayKey
    $overlayCacheRoot = Join-Path $workspaceRoot "artifacts\projects\$runProjectId\cache\simion_accelerator_overlay"
    $overlayCacheDir = Join-Path $overlayCacheRoot $overlayKey
    $overlayCachePaSharp = Join-Path $overlayCacheDir 'accelerator_overlay.pa#'
    $overlayCachePa0 = Join-Path $overlayCacheDir 'accelerator_overlay.pa0'
    $overlayCacheManifest = Join-Path $overlayCacheDir 'cache_manifest.json'
    $overlayCacheBasisReport = Join-Path $overlayCacheDir 'basis_build.json'
    $overlayFamilyComplete = Test-RfReusableCacheEntry -Python $python `
      -RepoRoot $repoRoot -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId `
      -CacheRoot $overlayCacheRoot -CacheKey $overlayKey -Role $overlayCacheRole `
      -InvalidEntryAction $(if ($PaCachePolicy -eq 'require_existing') {'preserve'} else {'remove'})
    if (-not $overlayFamilyComplete -and $PaCachePolicy -eq 'require_existing') {
      $paCacheDispositions.accelerator_overlay.disposition = 'cache_miss_required_existing'
      Write-RfPreCacheRunConfiguration -LifecycleStage 'accelerator_overlay_pa_cache_miss'
      throw "Required PA cache MISS or damage: role=$overlayCacheRole key=$overlayKey"
    }
    New-Item -ItemType Directory -Path $overlayCacheRoot -Force | Out-Null
    $overlayBasisBuilderFrozen = Join-Path $package.input_dir 'build_accelerator_overlay_basis.lua'
    $overlayRefinerFrozen = Join-Path $package.input_dir 'refine_accelerator_overlay_pa.lua'
    $overlayInterfaceVerifierFrozen = Join-Path $package.input_dir 'verify_accelerator_overlay_interface.lua'
    Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $overlayBasisBuilderSource `
      -Destination $overlayBasisBuilderFrozen -Role 'accelerator overlay basis builder' | Out-Null
    Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $overlayRefinerSource `
      -Destination $overlayRefinerFrozen -Role 'accelerator overlay segmented refiner' | Out-Null
    Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $overlayInterfaceVerifierSource `
      -Destination $overlayInterfaceVerifierFrozen -Role 'accelerator overlay interface verifier' | Out-Null
    $overlayBasisReport = Join-Path $package.result_dir 'accelerator_overlay_basis_build.json'
    if (-not $overlayFamilyComplete) {
      $paCacheDispositions.accelerator_overlay.disposition = 'cache_miss_build_authorized'
      Write-RfPreCacheRunConfiguration -LifecycleStage 'accelerator_overlay_pa_cache_build_authorized'
      # SIMION 2020's GEM compiler on Windows has a legacy path-length limit.
      # Keep staging non-hidden and short; the completed family is still
      # atomically renamed to the full content-hash cache key.
      $overlayBuildDir = Join-Path $overlayCacheRoot (
        'b-' + [guid]::NewGuid().ToString('N').Substring(0,12)
      )
      if ([IO.Path]::GetFullPath((Split-Path -Parent $overlayBuildDir)) -ne [IO.Path]::GetFullPath($overlayCacheRoot)) {
        throw 'Overlay cache staging directory escaped the governed cache root.'
      }
      New-Item -ItemType Directory -Path $overlayBuildDir | Out-Null
      try {
        $overlayBuildPaSharp = Join-Path $overlayBuildDir 'accelerator_overlay.pa#'
        $overlayBuildBasisReport = Join-Path $overlayBuildDir 'basis_build.json'
        $overlayCacheGem = Join-Path $overlayBuildDir 'accelerator_overlay.gem'
        Copy-Item -LiteralPath $overlayGem -Destination $overlayCacheGem
        $overlayGem2Pa = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget `
          -RunDir $package.run_dir -UsagePath (Join-Path $package.log_dir 'overlay_gem2pa_resource_usage.json') `
          -FilePath $SimionExe -WorkingDirectory $overlayBuildDir `
          -RedirectStandardOutput (Join-Path $package.log_dir 'overlay_gem2pa.stdout.log') `
          -RedirectStandardError (Join-Path $package.log_dir 'overlay_gem2pa.stderr.log') `
          -ArgumentList @('--nogui','--noprompt','gem2pa',$overlayCacheGem,$overlayBuildPaSharp)
        if ($overlayGem2Pa.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Overlay GEM conversion exceeded its resource budget.' }
        if ($overlayGem2Pa.exit_code -ne 0) { throw 'Overlay GEM conversion failed.' }
        $overlayBuild = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget `
          -RunDir $package.run_dir -UsagePath (Join-Path $package.log_dir 'overlay_basis_resource_usage.json') `
          -FilePath $SimionExe -WorkingDirectory $overlayBuildDir `
          -RedirectStandardOutput (Join-Path $package.log_dir 'overlay_basis.stdout.log') `
          -RedirectStandardError (Join-Path $package.log_dir 'overlay_basis.stderr.log') `
          -ArgumentList @('--nogui','--noprompt','lua',$overlayBasisBuilderFrozen,$frontendWorkingPa0,$overlayBuildPaSharp,
            ([string]$frontendGeometry.instance_origin_mm.x),([string]$frontendGeometry.instance_origin_mm.y),([string]$frontendGeometry.instance_origin_mm.z),
            ([string]$overlayGeometry.instance_origin_mm.x),([string]$overlayGeometry.instance_origin_mm.y),([string]$overlayGeometry.instance_origin_mm.z),
            ([string]$maximumFrontendElectrodeId),$overlayBuildBasisReport)
        if ($overlayBuild.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Overlay basis transfer exceeded its resource budget.' }
        if ($overlayBuild.exit_code -ne 0) { throw 'Overlay basis transfer failed.' }
        foreach ($electrode in $frontendBasisElectrodeIds) {
          $singleOverlayPa = Join-Path $overlayBuildDir "accelerator_overlay.pa$electrode"
          $singleOverlayRefine = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget `
            -RunDir $package.run_dir -UsagePath (Join-Path $package.log_dir "overlay_refine_pa${electrode}_resource_usage.json") `
            -FilePath $SimionExe -WorkingDirectory $overlayBuildDir `
            -RedirectStandardOutput (Join-Path $package.log_dir "overlay_refine_pa${electrode}.stdout.log") `
            -RedirectStandardError (Join-Path $package.log_dir "overlay_refine_pa${electrode}.stderr.log") `
            -ArgumentList @('--nogui','--noprompt','lua',$overlayRefinerFrozen,$singleOverlayPa,'5e-7')
          if ($singleOverlayRefine.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw "Overlay pa$electrode refine exceeded its resource budget." }
          if ($singleOverlayRefine.exit_code -ne 0) { throw "Overlay pa$electrode refine failed." }
        }
        $overlayCacheDir = Publish-RfVerifiedCacheEntry -Python $python `
          -RepoRoot $repoRoot -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId `
          -CacheRoot $overlayCacheRoot -CacheKey $overlayKey -Role $overlayCacheRole `
          -Identity $overlayIdentity -StagingDirectory $overlayBuildDir -ProviderRunId $RunId
        $paCacheDispositions.accelerator_overlay.disposition = 'built_and_published'
        Write-RfPreCacheRunConfiguration -LifecycleStage 'accelerator_overlay_pa_cache_published'
      } catch {
        if (Test-Path -LiteralPath $overlayBuildDir) {
          if ([IO.Path]::GetFullPath((Split-Path -Parent $overlayBuildDir)) -ne [IO.Path]::GetFullPath($overlayCacheRoot)) {
            throw 'Refusing to clean an overlay cache staging directory outside the governed cache root.'
          }
          Remove-Item -LiteralPath $overlayBuildDir -Recurse -Force
        }
        throw
      }
    }
    if ($overlayFamilyComplete) {
      $paCacheDispositions.accelerator_overlay.disposition = 'cache_hit'
      Write-RfPreCacheRunConfiguration -LifecycleStage 'accelerator_overlay_pa_cache_hit'
    }
    Copy-Item -LiteralPath $overlayCacheBasisReport -Destination $overlayBasisReport
    $overlayInterfaceReport = Join-Path $package.result_dir 'accelerator_overlay_interface_verification.json'
  }

  $isRestartFly2 = $isPrePulseRestart -or $isStagedGrid2Restart
  $particleInput = Join-Path $package.input_dir $(if ($isRestartFly2) {
      'single_flight_mother_sample.fly2'
    } else {
      'single_flight_mother_sample.ion'
    })
  $globalSource = Join-Path $package.input_dir 'single_flight_initial_global_state.csv'
  $particleRowMap = Join-Path $package.input_dir 'single_flight_particle_row_map.csv'
  $sourceArguments = @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source',
    '--source',$motherSource,'--connection',$resolvedFrozen,'--particle-input',$particleInput,'--global-state',$globalSource,
    '--row-map',$particleRowMap,
    '--source-release-mode',$sourceReleaseMode)
  if ($isPrePulseRestart) {
    $sourceArguments += @('--pulse-time-us',([string]$pulseTimeUs))
  }
  Invoke-SingleFlightPython -Arguments $sourceArguments `
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
  $downstreamCacheRoot = Join-Path $workspaceRoot "artifacts\projects\$runProjectId\cache\simion_oatof_downstream_pa"
  $geometryHash = (Get-FileHash -LiteralPath $oatofGeometry -Algorithm SHA256).Hash
  $flightTubeBuilderSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\build_flight_tube_variant.lua'
  $flightTubeGemSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\oatof_flight_tube_ground.gem'
  $reflectronBuilderSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\reflectron\build_reflectron_variant.lua'
  $reflectronGemSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\reflectron\oatof_reflectron_ideal_10_5.gem'
  $reflectronRefinerSource = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\reflectron\refine_single_pa.lua'
  function Get-DownstreamCachePlan {
    param(
      [Parameter(Mandatory)][string]$Kind,
      [Parameter(Mandatory)][string]$Role,
      [Parameter(Mandatory)][string]$Builder,
      [Parameter(Mandatory)][string]$Gem,
      [Parameter(Mandatory)]$CriticalOptions,
      [string]$Additional=''
    )
    $additionalHash = if ([string]::IsNullOrWhiteSpace($Additional)) { '' } else { (Get-FileHash -LiteralPath $Additional -Algorithm SHA256).Hash }
    $identity = [ordered]@{
      schema_version=2; role=$Role
      project_id=$runProjectId; solver=$simionSolverCacheIdentity
      inputs=[ordered]@{
        oatof_geometry_sha256=$geometryHash
        builder_sha256=(Get-FileHash -LiteralPath $Builder -Algorithm SHA256).Hash
        gem_sha256=(Get-FileHash -LiteralPath $Gem -Algorithm SHA256).Hash
        additional_builder_sha256=$additionalHash
      }
      critical_options=$CriticalOptions
    }
    $key = Get-RfContentIdentitySha256 -Identity $identity
    return [pscustomobject]@{
      kind=$Kind;role=$Role;identity=$identity;key=$key
      directory=(Join-Path $downstreamCacheRoot $key)
      pa0=(Join-Path (Join-Path $downstreamCacheRoot $key) "$Kind.pa0")
    }
  }
  $geometry = $oatofGeometryDocument.geometry_mm
  $flightBuild = $oatofGeometryDocument.simion_geometry_build.flight_tube
  $reflectronBuild = $oatofGeometryDocument.simion_geometry_build.reflectron
  $rings = $oatofGeometryDocument.rings
  $voltage = $oatofGeometryDocument.electrodes_V
  $flightTubeCachePlan = Get-DownstreamCachePlan -Kind 'flight_tube_ground' `
    -Role 'simion_oatof_flight_tube_pa_cache' -Builder $flightTubeBuilderSource `
    -Gem $flightTubeGemSource -CriticalOptions ([ordered]@{
      builder_mode='flight_tube_variant';cell_axial_mm=[double]$flightBuild.cell_axial_mm
      cell_radial_mm=[double]$flightBuild.cell_radial_mm;max_gib=[double]$flightBuild.max_gib
      flight_tube_radius_mm=[double]$geometry.flight_tube_r
      flight_tube_wall_mm=[double]$geometry.flight_tube_wall
      shield_endcap_thickness_mm=[double]$geometry.shield_endcap_thickness
      shield_outer_z_min_mm=[double]$geometry.shield_outer_z_min
      flight_length_mm=[double]$geometry.L_flight
      invocation=@('--nogui','--noprompt','lua','build_flight_tube_variant.lua')
    })
  $reflectronCachePlan = Get-DownstreamCachePlan -Kind 'reflectron' `
    -Role 'simion_oatof_reflectron_pa_cache' -Builder $reflectronBuilderSource `
    -Gem $reflectronGemSource -Additional $reflectronRefinerSource `
    -CriticalOptions ([ordered]@{
      builder_mode='initialize-only';cell_axial_mm=[double]$reflectronBuild.cell_axial_mm
      cell_radial_mm=[double]$reflectronBuild.cell_radial_mm;max_gib=[double]$reflectronBuild.max_gib
      stage1_count=[int]$rings.stage1_count;stage2_count=[int]$rings.stage2_count
      refinement_convergence='5e-7';midgrid_voltage_V=[double]$voltage.midgrid
      backplate_voltage_V=[double]$voltage.backplate
      invocation=@('--nogui','--noprompt','lua','build_reflectron_variant.lua')
      fast_adjust_mode='explicit_ring_voltage_assignments'
    })
  $flightTubeCachePa0 = $flightTubeCachePlan.pa0
  $reflectronCachePa0 = $reflectronCachePlan.pa0
  $flightTubeCacheDir = $flightTubeCachePlan.directory
  $reflectronCacheDir = $reflectronCachePlan.directory
  if ($isPrePulseTimeSeriesScreening) {
    $identity = $prePulseTimeSeries.identities
    $cacheKeys = if ([int]$prePulseTimeSeries.schema_version -eq 2) {
      $roles = $prePulseTimeSeries.pa_cache_roles
      if ([string]$roles.identity_source -ne
          'runner_materialized_verified_pa_cache_receipt' -or
          (@($roles.required) -join ',') -ne 'frontend,accelerator_overlay' -or
          (@($roles.prohibited) -join ',') -ne 'flight_tube,reflectron') {
        throw 'Pre-pulse time-series PA cache role policy differs.'
      }
      [ordered]@{
        frontend = $frontendCacheKey
        accelerator_overlay = $overlayKey
        flight_tube = $null
        reflectron = $null
      }
    } else {
      $prePulseTimeSeries.pa_cache_keys
    }
    $rfGrid = $prePulseTimeSeries.rf_time_grid
    $upstreamDocument = Get-Content -LiteralPath $upstreamFrozen -Raw -Encoding UTF8 |
      ConvertFrom-Json
    $motherSourceActualSha256 = (Get-FileHash -LiteralPath $motherSource `
      -Algorithm SHA256).Hash
    $identityChecks = @(
      @([string]$identity.campaign_id,[string]$populationContract.campaign_id),
      @([string]$identity.experiment_id,[string]$populationContract.experiment_id),
      @([string]$identity.connection_profile_id,$ConnectionProfileId),
      @([string]$identity.source_profile_id,$SourceProfileId),
      @([string]$identity.resolved_source_contract_sha256,$ResolvedSourceContractSha256),
      @([string]$identity.resolved_population_contract_sha256,$ResolvedPopulationContractSha256),
      @([string]$identity.mother_particle_source_sha256,$motherSourceActualSha256),
      @([string]$identity.layout_profile_id,$LayoutProfileId),
      @([string]$identity.architecture_generation_id,$ArchitectureGenerationId),
      @([string]$identity.candidate_sha256,$ThreeZoneCandidateSha256),
      @([string]$identity.topology_id,$ThreeZoneTopologyId),
      @([string]$identity.geometry_id,$ThreeZoneGeometryId),
      @([string]$identity.frontend_electrode_topology_id,$ThreeZoneFrontendElectrodeTopologyId),
      @([string]$identity.field_id,$ThreeZoneFieldId),
      @([string]$identity.field_profile_id,$selectedFieldProfileId),
      @([string]$identity.region_field_semantic_sha256,$ResolvedRegionFieldSemanticSha256),
      @([string]$identity.frontend_grid_profile_id,$selectedGridProfileId),
      @([string]$identity.field_overlay_id,$resolvedFieldOverlayId),
      @([string]$identity.oatof_numerical_profile_id,$selectedOatofNumericalProfileId),
      @([string]$identity.trajectory_quality_profile_id,$selectedTrajectoryQualityProfileId),
      @([string]$identity.time_integration_profile_id,$selectedTimeIntegrationProfileId)
    )
    if (@($identityChecks | Where-Object { $_[0] -ne $_[1] }).Count -ne 0 -or
        [string]$cacheKeys.frontend -ne $frontendCacheKey -or
        [string]$cacheKeys.accelerator_overlay -ne [string]$overlayKey -or
        $null -ne $cacheKeys.flight_tube -or
        $null -ne $cacheKeys.reflectron) {
      throw 'Pre-pulse time-series source/layout/field/PA identity differs.'
    }
    $sampleTimes = @($prePulseTimeSeries.sample_times_us | ForEach-Object {
      [double]$_
    })
    $frequencyHz = [double]$upstreamDocument.drive.frequency_Hz
    $periodUs = 1000000.0 / $frequencyHz
    $stepUs = $periodUs / 160.0
    $startIndex = [int]$rfGrid.start_index
    $endIndex = [int]$rfGrid.end_index
    if ([string]$rfGrid.waveform -ne [string]$upstreamDocument.drive.waveform -or
        [double]$rfGrid.frequency_hz -ne $frequencyHz -or
        [double]$rfGrid.phase_rad -ne [double]$upstreamDocument.drive.phase_rad -or
        [int]$rfGrid.rf_steps_per_period -ne 160 -or
        $rfStepsPerPeriod -ne 160 -or
        [Math]::Abs([double]$rfGrid.period_us - $periodUs) -gt 1e-12 -or
        [Math]::Abs([double]$rfGrid.step_us - $stepUs) -gt 1e-12 -or
        $startIndex -lt 0 -or $endIndex -lt $startIndex -or
        $sampleTimes.Count -ne ($endIndex - $startIndex + 1)) {
      throw 'Pre-pulse time-series RF160 time-grid identity differs.'
    }
    for ($index = 0; $index -lt $sampleTimes.Count; $index++) {
      $expectedTime = [double]$rfGrid.grid_origin_us +
        ($startIndex + $index) * $stepUs
      if ([Math]::Abs($sampleTimes[$index] - $expectedTime) -gt
          (1e-12 * [Math]::Max(1.0,[Math]::Abs($expectedTime)))) {
        throw 'Pre-pulse time-series sample time differs from the frozen RF160 grid.'
      }
      if ($index -gt 0 -and $sampleTimes[$index] -le $sampleTimes[$index - 1]) {
        throw 'Pre-pulse time-series sample times are not strictly increasing.'
      }
    }
  }
  function Copy-RfPaCacheFamilyToRuntime {
    param([Parameter(Mandatory)][string]$CacheDirectory,[Parameter(Mandatory)][string]$Pattern)
    foreach ($source in Get-ChildItem -LiteralPath $CacheDirectory -Filter $Pattern -File) {
      $target = Join-Path $runtimeDir $source.Name
      Copy-Item -LiteralPath $source.FullName -Destination $target -Force
    }
  }
  function Publish-DownstreamPaCacheFamily {
    param([Parameter(Mandatory)]$Plan,[Parameter(Mandatory)][string]$Pattern)
    $staging = New-RfCacheStagingDirectory -CacheRoot $downstreamCacheRoot
    try {
      foreach ($source in Get-ChildItem -LiteralPath $runtimeDir -Filter $Pattern -File) {
        $destination = Join-Path $staging $source.Name
        Copy-Item -LiteralPath $source.FullName -Destination $destination
      }
      return Publish-RfVerifiedCacheEntry -Python $python -RepoRoot $repoRoot `
        -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId `
        -CacheRoot $downstreamCacheRoot -CacheKey $Plan.key -Role $Plan.role `
        -Identity $Plan.identity -StagingDirectory $staging -ProviderRunId $RunId
    } catch {
      if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
      throw
    }
  }
  $flightTubeCacheUsed = $false
  $reflectronCacheUsed = $false
  if ($hasFlightTubeRebuild) {
    $paCacheDispositions.flight_tube.key = $flightTubeCachePlan.key
  }
  if ($hasReflectronRebuild) {
    $paCacheDispositions.reflectron.key = $reflectronCachePlan.key
  }
  $flightTubeCacheHit = $hasFlightTubeRebuild -and (Test-RfReusableCacheEntry -Python $python `
      -RepoRoot $repoRoot -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId `
      -CacheRoot $downstreamCacheRoot -CacheKey $flightTubeCachePlan.key `
      -Role $flightTubeCachePlan.role `
      -InvalidEntryAction $(if ($PaCachePolicy -eq 'require_existing') {'preserve'} else {'remove'}))
  if ($hasFlightTubeRebuild -and -not $flightTubeCacheHit -and
      $PaCachePolicy -eq 'require_existing') {
    $paCacheDispositions.flight_tube.disposition = 'cache_miss_required_existing'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'flight_tube_pa_cache_miss'
    throw "Required PA cache MISS or damage: role=$($flightTubeCachePlan.role) key=$($flightTubeCachePlan.key)"
  }
  if ($flightTubeCacheHit) {
    Copy-RfPaCacheFamilyToRuntime -CacheDirectory $flightTubeCacheDir -Pattern 'flight_tube_ground.pa*'
    $flightTubeCacheUsed = $true
    $hasFlightTubeRebuild = $false
    $paCacheDispositions.flight_tube.disposition = 'cache_hit'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'flight_tube_pa_cache_hit'
  }
  $reflectronCacheHit = $hasReflectronRebuild -and (Test-RfReusableCacheEntry -Python $python `
      -RepoRoot $repoRoot -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId `
      -CacheRoot $downstreamCacheRoot -CacheKey $reflectronCachePlan.key `
      -Role $reflectronCachePlan.role `
      -InvalidEntryAction $(if ($PaCachePolicy -eq 'require_existing') {'preserve'} else {'remove'}))
  if ($hasReflectronRebuild -and -not $reflectronCacheHit -and
      $PaCachePolicy -eq 'require_existing') {
    $paCacheDispositions.reflectron.disposition = 'cache_miss_required_existing'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'reflectron_pa_cache_miss'
    throw "Required PA cache MISS or damage: role=$($reflectronCachePlan.role) key=$($reflectronCachePlan.key)"
  }
  if ($reflectronCacheHit) {
    Copy-RfPaCacheFamilyToRuntime -CacheDirectory $reflectronCacheDir -Pattern 'reflectron.pa*'
    $reflectronCacheUsed = $true
    $hasReflectronRebuild = $false
    $paCacheDispositions.reflectron.disposition = 'cache_hit'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'reflectron_pa_cache_hit'
  }
  if ($overlayEnabled) {
    $overlayVerify = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget `
      -RunDir $package.run_dir -UsagePath (Join-Path $package.log_dir 'overlay_interface_verify_resource_usage.json') `
      -FilePath $SimionExe -WorkingDirectory $overlayCacheDir `
      -RedirectStandardOutput (Join-Path $package.log_dir 'overlay_interface_verify.stdout.log') `
      -RedirectStandardError (Join-Path $package.log_dir 'overlay_interface_verify.stderr.log') `
      -ArgumentList @('--nogui','--noprompt','lua',$overlayInterfaceVerifierFrozen,$frontendWorkingPa0,$overlayCachePa0,
        ([string]$frontendGeometry.instance_origin_mm.x),([string]$frontendGeometry.instance_origin_mm.y),([string]$frontendGeometry.instance_origin_mm.z),
        ([string]$overlayGeometry.instance_origin_mm.x),([string]$overlayGeometry.instance_origin_mm.y),([string]$overlayGeometry.instance_origin_mm.z),'19',$overlayInterfaceReport)
    if ($overlayVerify.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Overlay interface verification exceeded its resource budget.' }
    if ($overlayVerify.exit_code -ne 0) { throw 'Overlay interface verification failed.' }
  }
  $topologyResult = Invoke-SimionCompiledApertureTopologyCheck `
    -PaPath $frontendWorkingPa0 -ReportPath $apertureTopologyReport -VerifierPath $apertureVerifier `
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
        -WorkingDirectory $frontendWorkingDir -RedirectStandardOutput (Join-Path $package.log_dir 'frontend_aperture_topology.stdout.log') `
        -RedirectStandardError (Join-Path $package.log_dir 'frontend_aperture_topology.stderr.log') `
        -ArgumentList @('--nogui','--noprompt','lua',$verifierPath)
    }
  $apertureTopology = $topologyResult.audit
  if ($hasFlightTubeRebuild) {
    $paCacheDispositions.flight_tube.disposition = 'cache_miss_build_authorized'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'flight_tube_pa_cache_build_authorized'
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
    $flightTubeCacheDir = Publish-DownstreamPaCacheFamily `
      -Plan $flightTubeCachePlan -Pattern 'flight_tube_ground.pa*'
    $flightTubeCacheUsed = $true
    $paCacheDispositions.flight_tube.disposition = 'built_and_published'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'flight_tube_pa_cache_published'
  }
  if ($hasReflectronRebuild) {
    $paCacheDispositions.reflectron.disposition = 'cache_miss_build_authorized'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'reflectron_pa_cache_build_authorized'
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
    $reflectronCacheDir = Publish-DownstreamPaCacheFamily `
      -Plan $reflectronCachePlan -Pattern 'reflectron.pa*'
    $reflectronCacheUsed = $true
    $paCacheDispositions.reflectron.disposition = 'built_and_published'
    Write-RfPreCacheRunConfiguration -LifecycleStage 'reflectron_pa_cache_published'
  }
  $overlayIobBuilderFrozen = $null
  $overlayIobContainerFrozen = $null
  $overlayIobContainerGemFrozen = @()
  if ($overlayEnabled) {
    Copy-RfPaCacheFamilyToRuntime -CacheDirectory $overlayCacheDir -Pattern 'accelerator_overlay.pa*'
    $overlayIobBuilderSource = Join-Path $PSScriptRoot 'build_single_flight_overlay_iob.lua'
    $overlayIobBuilderFrozen = Join-Path $package.input_dir 'build_single_flight_overlay_iob.lua'
    Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $overlayIobBuilderSource `
      -Destination $overlayIobBuilderFrozen -Role 'single-flight overlay IOB builder' | Out-Null
    $overlayIobContainerSourceDir = Join-Path (Split-Path -Parent $SimionExe) 'examples\magnetic_potential'
    $overlayIobContainerSource = Join-Path $overlayIobContainerSourceDir 'mag_quad_2dp.iob'
    if (-not (Test-Path -LiteralPath $overlayIobContainerSource -PathType Leaf)) {
      throw 'SIMION-distributed five-instance IOB container is missing.'
    }
    $overlayContainerFrozenDir = Join-Path $package.input_dir 'simion_five_instance_container'
    $overlayContainerRuntimeDir = Join-Path $runtimeDir 'simion_five_instance_container'
    New-Item -ItemType Directory -Path $overlayContainerFrozenDir,$overlayContainerRuntimeDir -Force | Out-Null
    $overlayIobContainerFrozen = Join-Path $overlayContainerFrozenDir 'mag_quad_2dp.iob'
    Copy-Item -LiteralPath $overlayIobContainerSource -Destination $overlayIobContainerFrozen
    foreach ($seedName in @('mag_quad_2dp.gem','mag_quad_2dp-Mx.gem','mag_quad_2dp-My.gem','mag_quad_2dp-j.gem','mag_quad_2dp-mu.gem')) {
      $seedFrozen = Join-Path $overlayContainerFrozenDir $seedName
      Copy-Item -LiteralPath (Join-Path $overlayIobContainerSourceDir $seedName) -Destination $seedFrozen
      $overlayIobContainerGemFrozen += $seedFrozen
    }
    Get-ChildItem -LiteralPath $overlayContainerFrozenDir -File | Copy-Item -Destination $overlayContainerRuntimeDir
    $overlayIobContainerRuntime = Join-Path $overlayContainerRuntimeDir 'mag_quad_2dp.iob'
    $overlayIobBuild = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget `
      -RunDir $package.run_dir -UsagePath (Join-Path $package.log_dir 'overlay_iob_build_resource_usage.json') `
      -FilePath $SimionExe -WorkingDirectory $runtimeDir `
      -RedirectStandardOutput (Join-Path $package.log_dir 'overlay_iob_build.stdout.log') `
      -RedirectStandardError (Join-Path $package.log_dir 'overlay_iob_build.stderr.log') `
      -ArgumentList @('--nogui','--noprompt','lua',$overlayIobBuilderFrozen,
        (Join-Path $runtimeDir 'oatof_ideal_grounded.iob'),$overlayIobContainerRuntime,
        (Join-Path $runtimeDir 'oatof_ideal_grounded.iob'),
        (Join-Path $runtimeDir 'flight_tube_ground.pa0'),(Join-Path $runtimeDir 'reflectron.pa0'),
        (Join-Path $runtimeDir 'accelerator.pa0'),(Join-Path $runtimeDir 'detector_ground.pa0'),
        (Join-Path $runtimeDir 'accelerator_overlay.pa0'),
        ([string]$overlayGeometry.instance_origin_mm.x),([string]$overlayGeometry.instance_origin_mm.y),([string]$overlayGeometry.instance_origin_mm.z),
        (Join-Path $runtimeDir 'oatof_ideal_grounded.lua'),(Join-Path $runtimeDir 'oatof_ideal_grounded.fly2'))
    if ($overlayIobBuild.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Overlay IOB build exceeded its resource budget.' }
    if ($overlayIobBuild.exit_code -ne 0) { throw 'Overlay IOB build failed.' }
  }
  if (-not (Test-RfReusableCacheEntry -Python $python -RepoRoot $repoRoot `
      -WorkspaceRoot $workspaceRoot -ProjectId $runProjectId `
      -CacheRoot $cacheRoot -CacheKey $frontendCacheKey -Role $frontendCacheRole `
      -InvalidEntryAction 'preserve')) {
    throw 'Frontend PA cache changed during construction-time SIMION access.'
  }
  $frontendCacheManifestInput = Copy-RfCacheManifestInput -CacheEntry $cacheDir `
    -Destination (Join-Path $package.input_dir 'frontend_pa_cache_manifest.json')
  $flightTubeCacheManifestInput = if ($flightTubeCacheUsed) {
    Copy-RfCacheManifestInput -CacheEntry $flightTubeCacheDir `
      -Destination (Join-Path $package.input_dir 'flight_tube_pa_cache_manifest.json')
  } else { $null }
  $reflectronCacheManifestInput = if ($reflectronCacheUsed) {
    Copy-RfCacheManifestInput -CacheEntry $reflectronCacheDir `
      -Destination (Join-Path $package.input_dir 'reflectron_pa_cache_manifest.json')
  } else { $null }
  $overlayCacheManifestInput = if ($overlayEnabled) {
    Copy-RfCacheManifestInput -CacheEntry $overlayCacheDir `
      -Destination (Join-Path $package.input_dir 'accelerator_overlay_pa_cache_manifest.json')
  } else { $null }
  $program = Join-Path $runtimeDir 'oatof_ideal_grounded.lua'
  $programMetadata = Join-Path $package.input_dir 'single_flight_program_build.json'
  $analyzerComponent = Join-Path $package.input_dir 'oatof_analyzer_component.lua'
  $pulseHook = Join-Path $package.input_dir 'single_flight_pulse_hook.lua'
  $frontendHook = Join-Path $package.input_dir 'single_flight_frontend_hook.lua'
  $rfDriveKernel = Join-Path $package.input_dir 'simion_rf_drive.lua'
  $restartContext = $null
  if ($isStagedGrid2Restart) {
    $restartContext = Join-Path $package.input_dir `
      'staged_grid2_restart_context.json'
    Write-RfJson -Path $restartContext -Depth 5 -Value ([ordered]@{
      schema_version = 1
      role = 'rf_oatof_staged_grid2_restart_context'
      source_release_mode = 'staged_grid2_restart'
      population_mode = 'staged_grid2_restart'
      state_event = 'local_accelerator_exit'
      frame_id = 'oatof_global'
      clock_basis = 'canonical_instrument_time_us'
      clock_epoch_id = $StagedGrid2ClockEpochId
      simion_start_instance = $StagedGrid2StartInstance
      position_projection_applied = $false
      skip_frontend_runtime_writes = $true
      skip_pulse_runtime_writes = $true
      skip_accelerator_runtime_writes = $true
      preserve_analyzer_static_pa_initialization = $true
      preserve_downstream_base_then_override_field_semantics = $true
      preserve_detector_elapsed_semantics = $true
      resolution_claim_allowed = $false
      source_release_validation = $sourceValidation
    })
  }
  Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath (Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\candidates\oatof_analyzer_component.lua') `
    -Destination $analyzerComponent -Role 'single-flight oaTOF analyzer component' | Out-Null
  Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath (Join-Path $PSScriptRoot 'single_flight_pulse_hook.lua') `
    -Destination $pulseHook -Role 'single-flight pulse hook' | Out-Null
  Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath (Join-Path $PSScriptRoot 'single_flight_frontend_hook.lua') `
    -Destination $frontendHook -Role 'single-flight frontend hook' | Out-Null
  Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath (Join-Path $repoRoot 'common\multipole\simion_rf_drive.lua') `
    -Destination $rfDriveKernel -Role 'single-flight RF drive kernel' | Out-Null
  $programArguments = @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.build_single_flight_program',
    '--analyzer-component',$analyzerComponent,
    '--pulse-hook',$pulseHook,
    '--frontend-hook',$frontendHook,
    '--upstream',$upstreamFrozen,
    '--frontend-contract',$frontendContract,'--oatof',$oatofGeometry,
    '--initial-global-state',$globalSource,
    '--particle-row-map',$particleRowMap,
    '--resolved-region-field-contract',$resolvedRegionFieldContractFrozen,
    '--rf-drive-kernel',$rfDriveKernel,
    '--rf-steps-per-period',([string]$rfStepsPerPeriod),
    '--output',$program,'--metadata',$programMetadata)
  if ($null -ne $restartContext) {
    $programArguments += @('--restart-context',$restartContext)
  }
  if ($SamplingMode -eq 'steady_candidate_pool') { $programArguments += '--terminate-after-pulse' }
  if ($isPrePulseTimeSeriesScreening) {
    $programArguments += @(
      '--pre-pulse-time-series-contract',$prePulseTimeSeriesContractFrozen
    )
  }
  if ($null -ne $prePulseValidationFrozen) { $programArguments += '--global-segments' }
  if ($overlayEnabled) { $programArguments += @('--accelerator-overlay-contract',$overlayContract) }
  Invoke-SingleFlightPython -Arguments $programArguments `
    -Failure 'Single-flight Program build failed.'

  $runConfiguration = [ordered]@{
    schema_version=2; run_id=$RunId; project=$runProjectId; mode='rf_to_oatof_simion_single_flight'; project_root=$repoRoot
    upstream_project_id=$runtime.upstream_project_id
    inputs=[ordered]@{ configuration=$configuration; runtime_binding=$runtimeBindingFrozen; resolved_connection=$resolvedFrozen; resolved_source_contract=$sourceContractFrozen; resolved_population_contract=$populationContractFrozen; upstream_resolved_design=$upstreamFrozen; oatof_resolved_geometry=$oatofGeometry; pulse_schedule=$pulseScheduleFrozen; resolved_region_field_contract=$resolvedRegionFieldContractFrozen; analyzer_component=$analyzerComponent; pulse_hook=$pulseHook; frontend_hook=$frontendHook; rf_drive_kernel=$rfDriveKernel; resolved_integration_engineering_budget=$budget.frozen_budget; resolved_stage_resource_budget=$budget.stage_budget; mother_particle_source=$motherSource; mother_particle_source_materialization_receipt=$motherSourceReceiptFrozen; initial_global_state=$globalSource; particle_row_map=$particleRowMap; pre_pulse_restart_validation=$prePulseValidationFrozen; staged_grid2_restart_context=$restartContext; staged_grid2_loader_authorization_budget=$stagedLoaderBudgetFrozen; staged_grid2_producer_manifest=$stagedGrid2ProducerManifestFrozen; staged_grid2_bridge_receipt=$stagedGrid2BridgeReceiptFrozen; particle_input=$particleInput; frontend_gem=$frontendGem; frontend_contract=$frontendContract; frontend_electrode_topology=$frontendElectrodeTopologyContract; frontend_pa_cache_manifest=$frontendCacheManifestInput; accelerator_overlay_gem=$overlayGem; accelerator_overlay_contract=$overlayContract; accelerator_overlay_basis_builder=$overlayBasisBuilderFrozen; accelerator_overlay_refiner=$overlayRefinerFrozen; accelerator_overlay_interface_verifier=$overlayInterfaceVerifierFrozen; accelerator_overlay_pa_cache_manifest=$overlayCacheManifestInput; accelerator_overlay_iob_builder=$overlayIobBuilderFrozen; accelerator_overlay_iob_container=$overlayIobContainerFrozen; accelerator_overlay_iob_container_gems=$overlayIobContainerGemFrozen; accelerator_overlay_basis_report=$overlayBasisReport; accelerator_overlay_interface_report=$overlayInterfaceReport; flight_tube_pa_cache_manifest=$flightTubeCacheManifestInput; reflectron_pa_cache_manifest=$reflectronCacheManifestInput; frontend_aperture_topology_support=$apertureTopologySupport; frontend_aperture_topology_verifier=$apertureVerifier; program_metadata=$programMetadata; candidate_flight_tube_builder=$flightTubeBuilderFrozen; candidate_flight_tube_gem=$flightTubeGemFrozen; candidate_reflectron_builder=$reflectronBuilderFrozen; candidate_reflectron_gem=$reflectronGemFrozen; candidate_reflectron_refiner=$reflectronRefinerFrozen }
    upstream_source_identity=$resolvedBudgetDocument.source_identity
    parameters=[ordered]@{ connection_profile_id=$ConnectionProfileId; source_branch_id=$SourceBranchId; single_flight_pa_cache_policy=$PaCachePolicy; single_flight_pa_cache_policy_provenance=$PaCachePolicyProvenance; pa_cache_dispositions=$paCacheDispositions; layout_profile_id=$(if($hasGovernedLayout){$LayoutProfileId}else{$null}); architecture_generation_id=$(if($hasGovernedLayout){$ArchitectureGenerationId}else{$null}); source_profile_id=$(if($SourceProfileId){$SourceProfileId}else{$null}); field_overlay_id=$resolvedFieldOverlayId; bore_radius_mm=[double]$oatofGeometryDocument.geometry_mm.bore_r; ring_outer_radius_mm=[double]$oatofGeometryDocument.geometry_mm.ring_outer_r; shield_inner_radius_mm=[double]$oatofGeometryDocument.geometry_mm.flight_tube_r; frontend_grid_profile_id=$selectedGridProfileId; frontend_cell_mm_xyz=[ordered]@{x=$frontendCellMmX;y=$frontendCellMmY;z=$frontendCellMmZ}; accelerator_overlay_enabled=$overlayEnabled; accelerator_overlay_cell_mm_xyz=$(if($overlayEnabled){[ordered]@{x=$overlayCellMmX;y=$overlayCellMmY;z=$overlayCellMmZ}}else{$null}); accelerator_overlay_boundary_mode=$(if($overlayEnabled){'coarse_electrode_basis_dirichlet_v1'}else{$null}); oatof_numerical_profile_id=$selectedOatofNumericalProfileId; trajectory_quality_profile_id=$selectedTrajectoryQualityProfileId; trajectory_quality=$trajectoryQuality; time_integration_profile_id=$selectedTimeIntegrationProfileId; rf_steps_per_period=$rfStepsPerPeriod; spatial_window_profile_id=$(if($spatialWindowProfiles.Count -eq 1){$SpatialWindowProfileId}else{$null}); source_region_diagnostic_profile_id=$(if($sourceRegionDiagnosticProfiles.Count -eq 1){$sourceRegionDiagnosticProfileId}else{$null}); accelerator_field_profile_id=$selectedFieldProfileId; resolved_region_field_contract_sha256=$ResolvedRegionFieldContractSha256; resolved_region_field_semantic_sha256=$ResolvedRegionFieldSemanticSha256; resolved_population_contract_sha256=$ResolvedPopulationContractSha256; max_parallel_batches=$maxParallelBatches; clock_basis=[string]$settings.clock_basis; launched_particle_count=$launched; particle_count=$launched; population_denominator_count=$PopulationDenominatorCount; eligible_population_count=$EligiblePopulationCount; population_basis=$(if($SamplingMode -eq 'continuous_injection_full_population'){'candidate_full_population'}elseif($SamplingMode -eq 'pulse_eligible_conditional'){'pulse_eligible_conditional_population'}else{'source_contract_population'}); execution_batch_count=$(if($launched -ge [int]$settings.batching_policy.enabled_at_particle_count){[int]$settings.batching_policy.default_batch_count}else{1}); execution_batches_parallel=$(if($launched -ge [int]$settings.batching_policy.enabled_at_particle_count){[bool]$settings.batching_policy.parallel_after_cache_warmup}else{$false}); aperture_width_mm=$apertureWidthMm; aperture_height_mm=$apertureHeightMm; aperture_boolean_boundary_policy=[string]$apertureDiscretization.boolean_boundary_policy; aperture_grid_warnings=$apertureGridWarnings; frontend_open_aperture_column_count=[int]$apertureTopology.open_column_count; frontend_aperture_guard_electrode_check_passed=[bool]$apertureTopology.guard_electrode_check_passed; frontend_aperture_topology_report_sha256=(Get-FileHash -LiteralPath $apertureTopologyReport -Algorithm SHA256).Hash; rod_end_to_accelerator_shield_mm=[double]$frontendGeometry.junction_enclosure.rod_end_to_accelerator_shield_mm; surrounded_transition=$true; accelerator_axis_x_mm=[double]$oatofGeometryDocument.coordinate_convention.accelerator_axis_x; pulse_time_us=$pulseTimeUs; pulse_width_us=$pulseWidthUs; design_compilation=$(if($null -ne $layoutDerivation){$layoutDerivation.design_compilation}else{$null}); source_release_full_width_mm=[double]$oatofGeometryDocument.particle_source.size_z_mm; reflectron_stage2_length_mm=[double]$oatofGeometryDocument.geometry_mm.L_stage2; reflectron_midgrid_voltage_V=[double]$oatofGeometryDocument.electrodes_V.midgrid; reflectron_backplate_voltage_V=[double]$oatofGeometryDocument.electrodes_V.backplate; reflectron_pa0_sha256=(Get-FileHash -LiteralPath $reflectronPa0 -Algorithm SHA256).Hash; frontend_gem_sha256=$frontendHash; frontend_pa0_sha256=(Get-FileHash -LiteralPath $cachePa0 -Algorithm SHA256).Hash; accelerator_overlay_pa0_sha256=$(if($overlayEnabled){(Get-FileHash -LiteralPath $overlayCachePa0 -Algorithm SHA256).Hash}else{$null}) }
    artifact_retention=[ordered]@{policy_version=1;class='compact';reason=$null}; formal_gate_passed=$false
  }
  if ($isPrePulseTimeSeriesScreening) {
    $runConfiguration.inputs.pre_pulse_time_series_contract =
      $prePulseTimeSeriesContractFrozen
    $runConfiguration.parameters.execution_mode =
      'real_pa_rf_pre_pulse_time_series'
    $runConfiguration.parameters.resolution_claim_allowed = $false
  }
  if ($hasThreeZoneCandidate) {
    $runConfiguration.inputs.three_zone_t5_candidate =
      $threeZoneCandidateFrozen
    $runConfiguration.parameters.three_zone_topology_id =
      $ThreeZoneTopologyId
    $runConfiguration.parameters.three_zone_geometry_id =
      $ThreeZoneGeometryId
    $runConfiguration.parameters.three_zone_frontend_electrode_topology_id =
      $ThreeZoneFrontendElectrodeTopologyId
    $runConfiguration.parameters.three_zone_field_id = $ThreeZoneFieldId
    $runConfiguration.parameters.three_zone_candidate_sha256 =
      $ThreeZoneCandidateSha256
    $runConfiguration.parameters.accelerator_intermediate2_forward_launched_upper_bound =
      $launched
  }
  if ($ThreeZoneSolverGateStage -ne '') {
    $runConfiguration.parameters.three_zone_solver_gate_stage =
      $ThreeZoneSolverGateStage
    $runConfiguration.parameters.three_zone_solver_gate_id =
      $ThreeZoneSolverGateId
  }
  if ($ThreeZoneSolverGateStage -eq 'n100_solver_authorized_consumer') {
    $runConfiguration.inputs.three_zone_n1_solver_authorization_receipt =
      $threeZoneAuthorizationReceiptFrozen
    $runConfiguration.inputs.three_zone_n1_producer_parent_manifest =
      $threeZoneProducerParentManifestFrozen
    $runConfiguration.parameters.three_zone_n1_solver_authorization_receipt_sha256 =
      $ThreeZoneAuthorizationReceiptSha256
    $runConfiguration.parameters.three_zone_n1_producer_parent_manifest_sha256 =
      $ThreeZoneProducerParentManifestSha256
    $runConfiguration.parameters.three_zone_source_identity_sha256 =
      $ThreeZoneSourceIdentitySha256
  }
  if ($isStagedGrid2Restart) {
    $runConfiguration.inputs.Remove('pulse_schedule')
    $runConfiguration.parameters.Remove('pulse_time_us')
    $runConfiguration.parameters.Remove('pulse_width_us')
    Set-RfStagedRunConfigurationIdentity -RunConfiguration $runConfiguration `
      -ResolvedBudgetDocument $resolvedBudgetDocument `
      -ConnectionLineageIdentity $runtime.source_identity
  }
  if ($PulseResolutionN100Screening) {
    $runConfiguration.inputs.pulse_resolution_campaign = $campaignFrozen
    $runConfiguration.inputs.pulse_resolution_source_identity = $sourceIdentity
    $runConfiguration.inputs.pulse_resolution_baseline_registration_authority =
      $registrationAuthorityFrozen
    $runConfiguration.parameters.pulse_resolution_experiment_id =
      $PulseResolutionExperimentId
    $runConfiguration.parameters.pulse_resolution_field_profile_id =
      $PulseResolutionFieldProfileId
    $runConfiguration.parameters.pulse_resolution_screening_prefix_count = $launched
    $runConfiguration.parameters.pulse_resolution_selection_rule =
      [string]$populationContract.execution_population.selection_algorithm
    $runConfiguration.parameters.pulse_resolution_screening_is_random =
      $populationContract.execution_population.selection_algorithm -notlike 'first_*'
  }
  if ($isStagedGrid2Restart) {
    $runConfiguration.parameters.source_release_mode = 'staged_grid2_restart'
    $runConfiguration.parameters.population_mode = 'staged_grid2_restart'
    $runConfiguration.parameters.sampling_authority =
      'staged_grid2_canonical_source'
    $runConfiguration.parameters.restart_state_event =
      'local_accelerator_exit'
    $runConfiguration.parameters.restart_frame_id = 'oatof_global'
    $runConfiguration.parameters.restart_simion_start_instance =
      $StagedGrid2StartInstance
    $runConfiguration.parameters.restart_producer_run_id =
      $StagedGrid2ProducerRunId
    $runConfiguration.parameters.resolution_claim_allowed = $false
  }
  Write-RfJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  Write-RfJson -Path $package.summary -Depth 10 -Value ([ordered]@{schema_version=1;role=$summaryRole;status='interrupted';reason='Frozen inputs recorded; SIMION flight not complete.';single_flight_pa_cache_policy=$PaCachePolicy;single_flight_pa_cache_policy_provenance=$PaCachePolicyProvenance;pa_cache_dispositions=$paCacheDispositions})
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $repoRoot -RunConfig $package.run_config -Status interrupted -Software @('SIMION 2020','Python 3.11')
  $snapshotReady = $true

  $batchCount = [int]$runConfiguration.parameters.execution_batch_count
  if ($batchCount -gt 1 -and (
      $batchCount -ne 5 -or
      -not [bool]$runConfiguration.parameters.execution_batches_parallel)) {
    throw 'N=1000 single flight requires five batches with profile-capped wave dispatch.'
  }
  $particleLines = @(Get-RfSingleFlightParticleLines `
    -ParticleInput $particleInput -RestartFly2 $isRestartFly2)
  if ($particleLines.Count -ne $launched) {
    throw 'Single-flight particle-input row count differs from the launched mother sample.'
  }
  $batchRecords = @()
  $quotient = [Math]::Floor($launched / $batchCount)
  $remainder = $launched % $batchCount
  $offset = 0
  foreach ($batchIndex in 1..$batchCount) {
    $count = $quotient + $(if ($batchIndex -le $remainder) { 1 } else { 0 })
    $batchParticleInput = Join-Path $package.input_dir (
      'single_flight_mother_sample__batch{0:D2}.{1}' -f $batchIndex,$(if ($isRestartFly2) {'fly2'} else {'ion'})
    )
    $batchParticleLines = [string[]]$particleLines[$offset..($offset + $count - 1)]
    if ($isRestartFly2) {
      $batchParticleLines = [string[]](@('particles {','  coordinates = 0,') + $batchParticleLines + @('}'))
    }
    [IO.File]::WriteAllLines(
      $batchParticleInput,
      $batchParticleLines,
      [Text.UTF8Encoding]::new($false)
    )
    $batchRecords += [pscustomobject]@{
      index = $batchIndex
      count = $count
      offset = $offset
      particle_input = $batchParticleInput
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
    $env:OATOF_ACCELERATOR_PA_OVERRIDE = $frontendWorkingPa0
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
        accelerator_pa = $frontendWorkingPa0
        particle_id_offset = [int]$batch.offset
        arguments = [string[]](@(
          '--default-num-particles',([string][Math]::Max(100,[int]$batch.count)),
          '--nogui','--noprompt','fly',
          '--trajectory-quality',([string]$trajectoryQuality),
          '--retain-trajectories','0','--particles',$batch.particle_input,'--programs','1',
          '--adjustable',("trajectory_quality={0}" -f $trajectoryQuality),
          '--adjustable','trajectory_log_enable=1',
          '--adjustable',("diagnostic_max_tof_us={0:R}" -f [double]$settings.maximum_time_of_flight_us)
        ) + $(if ($isPrePulseTimeSeriesScreening) { @(
          '--adjustable','handoff_pulse_mode=2'
        ) } elseif ($isStagedGrid2Restart) { @() } else { @(
          '--adjustable','handoff_pulse_mode=1',
          '--adjustable',("handoff_pulse_time_us={0:R}" -f $pulseTimeUs),
          '--adjustable',("handoff_pulse_width_us={0:R}" -f $pulseWidthUs)
        ) }) + @(
          '--adjustable',("single_flight_rf_steps={0}" -f $rfStepsPerPeriod),
          (Join-Path $runtimeDir 'oatof_ideal_grounded.iob')
        ))
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

  if ($isPrePulseTimeSeriesScreening) {
    $statesCsv = Join-Path $package.result_dir 'pre_pulse_time_series_states.csv'
    $screeningReceipt = Join-Path $package.result_dir `
      'pre_pulse_time_series_screening_receipt.json'
    $tracePattern = '^TRACE: pre_pulse_time_series_state ion=(?<ion>\d+) particle_id=(?<particle_id>\d+) sample_index=(?<sample_index>\d+) instrument_time_us=(?<instrument_time>[-+0-9.eE]+) actual_instrument_time_us=(?<actual_time>[-+0-9.eE]+) x_mm=(?<x>[-+0-9.eE]+) y_mm=(?<y>[-+0-9.eE]+) z_mm=(?<z>[-+0-9.eE]+) vx_mm_per_us=(?<vx>[-+0-9.eE]+) vy_mm_per_us=(?<vy>[-+0-9.eE]+) vz_mm_per_us=(?<vz>[-+0-9.eE]+) kinetic_energy_eV=(?<energy>[-+0-9.eE]+) survival_status=(?<status>\S+)$'
    $rows = @()
    foreach ($log in $stdoutFiles) {
      foreach ($line in Get-Content -LiteralPath $log -Encoding UTF8) {
        if ($line -match '^TRACE: (detector_crossing|diagnostic_return_plane)') {
          throw 'Pre-pulse time-series screening emitted a prohibited downstream event.'
        }
        if ($line -match $tracePattern) {
          $rows += [pscustomobject][ordered]@{
            particle_id = [int]$Matches.particle_id
            event = 'pre_pulse_time_series_state'
            sample_index = [int]$Matches.sample_index
            instrument_time_us = [double]$Matches.instrument_time
            actual_instrument_time_us = [double]$Matches.actual_time
            x_mm = [double]$Matches.x
            y_mm = [double]$Matches.y
            z_mm = [double]$Matches.z
            vx_mm_per_us = [double]$Matches.vx
            vy_mm_per_us = [double]$Matches.vy
            vz_mm_per_us = [double]$Matches.vz
            kinetic_energy_eV = [double]$Matches.energy
            survival_status = [string]$Matches.status
          }
        }
      }
    }
    $sampleTimes = @($prePulseTimeSeries.sample_times_us)
    $rows = @($rows | Sort-Object particle_id,sample_index)
    $frozenParticleIds = @(
      Import-Csv -LiteralPath $particleRowMap | ForEach-Object {
        [int]$_.source_particle_id
      }
    )
    if ($frozenParticleIds.Count -ne $launched -or
        @($frozenParticleIds | Sort-Object -Unique).Count -ne $launched -or
        @($rows | Group-Object particle_id,sample_index | Where-Object {
            $_.Count -ne 1
          }).Count -ne 0 -or
        @($rows | Where-Object {
            $_.particle_id -notin $frozenParticleIds
          }).Count -ne 0) {
      throw 'Pre-pulse time-series TRACE particle identity/uniqueness differs.'
    }
    foreach ($row in $rows) {
      if ($row.sample_index -lt 1 -or $row.sample_index -gt $sampleTimes.Count) {
        throw 'Pre-pulse time-series TRACE sample index is outside the frozen grid.'
      }
      $expectedTime = [double]$sampleTimes[$row.sample_index - 1]
      $tolerance = 1e-12 * [Math]::Max(1.0,[Math]::Abs($expectedTime))
      if ([Math]::Abs($row.instrument_time_us - $expectedTime) -gt $tolerance -or
          [Math]::Abs($row.actual_instrument_time_us - $expectedTime) -gt $tolerance -or
          $row.survival_status -ne 'alive') {
        throw 'Pre-pulse time-series TRACE identity/time landing differs.'
      }
    }
    foreach ($particleId in $frozenParticleIds) {
      $indices = @($rows | Where-Object { $_.particle_id -eq $particleId } |
        ForEach-Object { [int]$_.sample_index })
      for ($index = 0; $index -lt $indices.Count; $index++) {
        if ($indices[$index] -ne ($index + 1)) {
          throw 'Pre-pulse time-series particle state is not one continuous alive prefix.'
        }
      }
    }
    $sampleCensus = @()
    foreach ($sampleIndex in 1..$sampleTimes.Count) {
      $aliveIds = @($rows | Where-Object { $_.sample_index -eq $sampleIndex } |
        ForEach-Object { [int]$_.particle_id } | Sort-Object)
      $missingIds = @($frozenParticleIds | Where-Object { $_ -notin $aliveIds } |
        Sort-Object)
      $sampleCensus += [ordered]@{
        sample_index = $sampleIndex
        instrument_time_us = [double]$sampleTimes[$sampleIndex - 1]
        alive_count = $aliveIds.Count
        alive_particle_ids_sha256 = Get-RfContentIdentitySha256 -Identity ([ordered]@{
          ordered_particle_ids = $aliveIds
        })
        missing_count = $missingIds.Count
        missing_particle_ids = $missingIds
        missing_particle_ids_sha256 = Get-RfContentIdentitySha256 -Identity ([ordered]@{
          ordered_particle_ids = $missingIds
        })
      }
    }
    $rows | Export-Csv -LiteralPath $statesCsv -NoTypeInformation -Encoding utf8
    $statesRecord = [ordered]@{
      path = 'results/pre_pulse_time_series_states.csv'
      sha256 = (Get-FileHash -LiteralPath $statesCsv -Algorithm SHA256).Hash
      bytes = (Get-Item -LiteralPath $statesCsv).Length
      row_count = $rows.Count
    }
    $receipt = [ordered]@{
      schema_version = 1
      role = 'rf_oatof_pre_pulse_time_series_screening_receipt'
      status = 'success'
      qualification = 'FUNCTIONAL_ONLY'
      execution_mode = 'real_pa_rf_pre_pulse_time_series'
      resolution_claim_allowed = $false
      pulse_disabled = $true
      contract_sha256 = $PrePulseTimeSeriesContractSha256
      identities = $prePulseTimeSeries.identities
      pa_cache_keys = $cacheKeys
      rf_time_grid = $prePulseTimeSeries.rf_time_grid
      sample_times_us = $sampleTimes
      particle_count = $launched
      state_row_count = $rows.Count
      sample_census = $sampleCensus
      outputs = [ordered]@{ states = $statesRecord }
      prohibited_outputs = @($prePulseTimeSeries.prohibited_outputs)
    }
    Write-RfJson -Path $screeningReceipt -Depth 10 -Value $receipt
    $summary = [ordered]@{
      schema_version = 1
      role = $summaryRole
      status = 'success'
      execution_mode = 'real_pa_rf_pre_pulse_time_series'
      qualification = 'FUNCTIONAL_ONLY'
      resolution_claim_allowed = $false
      pulse_disabled = $true
      sample_times_us = $sampleTimes
      census = [ordered]@{
        source_release = $launched
        particle_count = $launched
        sample_count = $sampleTimes.Count
        observed_state_rows = $rows.Count
        sample_census = $sampleCensus
      }
      pa_cache_dispositions = $paCacheDispositions
      outputs = [ordered]@{
        states = $statesRecord
        receipt = [ordered]@{
          path = 'results/pre_pulse_time_series_screening_receipt.json'
          sha256 = (Get-FileHash -LiteralPath $screeningReceipt -Algorithm SHA256).Hash
          bytes = (Get-Item -LiteralPath $screeningReceipt).Length
        }
      }
      prohibited_outputs = @($prePulseTimeSeries.prohibited_outputs)
    }
    Write-RfJson -Path $package.summary -Depth 10 -Value $summary
    $runConfiguration.parameters.pre_pulse_time_series_state_row_count = $rows.Count
    Write-RfJson -Path $package.run_config -Depth 10 -Value $runConfiguration
    $retentionActions = Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot `
      -RunConfig $package.run_config
    foreach ($usage in $resourceUsageFiles) {
      if (-not (Complete-ResourceUsage -ResolvedBudgetPath $budget.stage_budget `
            -RunDir $package.run_dir -UsagePath $usage)) {
        $resourceBudgetExceeded = $true
        throw 'Pre-pulse time-series compact retained-byte budget exceeded.'
      }
    }
    $outputs = @($statesCsv,$screeningReceipt,$package.summary,$retentionActions) +
      $stdoutFiles + $stderrFiles + $resourceUsageFiles |
      Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
    Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $repoRoot `
      -RunConfig $package.run_config -Status success `
      -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
    Write-Output "SIMION_PRE_PULSE_TIME_SERIES=PASS RUN_ID=$RunId ROWS=$($rows.Count)"
    return
  }

  $checkpoints = Join-Path $package.result_dir 'single_flight_particle_checkpoints.csv'
  $analysisArguments = @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight',
    '--mass-amu','100',
    '--resolved-population-contract',$populationContractFrozen,
    '--resolved-population-contract-sha256',$ResolvedPopulationContractSha256,
    '--geometry',$oatofGeometry,
    '--clock-basis',([string]$settings.clock_basis),
    '--initial-global-state',$globalSource,
    '--particle-row-map',$particleRowMap,
    '--initial-global-state-sha256',((Get-FileHash -LiteralPath $globalSource -Algorithm SHA256).Hash),
    '--checkpoints',$checkpoints,'--summary',$package.summary)
  if (-not $isStagedGrid2Restart) {
    $analysisArguments += @('--pulse-time-us',([string]$pulseTimeUs))
  }
  if ($sourceReleaseMode -eq 'pre_pulse_restart') {
    if ($PrePulseRestartPositionToleranceMm -le 0 -or
        $PrePulseRestartVelocityToleranceMPerS -le 0 -or
        $PrePulseRestartClockToleranceUs -le 0 -or
        $PrePulseRestartEnergyToleranceEv -le 0) {
      throw 'Pre-pulse restart requires positive frozen source-release tolerances.'
    }
    $analysisArguments += @(
      '--restart-position-tolerance-mm',([string]$PrePulseRestartPositionToleranceMm),
      '--restart-velocity-tolerance-m-per-s',([string]$PrePulseRestartVelocityToleranceMPerS),
      '--restart-clock-tolerance-us',([string]$PrePulseRestartClockToleranceUs),
      '--restart-energy-tolerance-eV',([string]$PrePulseRestartEnergyToleranceEv),
      '--restart-validation-contract-sha256',$PrePulseRestartValidationSha256
    )
  }
  if ($spatialWindowProfiles.Count -eq 1 -or
      $sourceRegionDiagnosticProfiles.Count -eq 1) {
    $analysisArguments += @('--configuration',$configuration)
  }
  if ($spatialWindowProfiles.Count -eq 1) {
    $analysisArguments += @('--spatial-window-profile-id',$SpatialWindowProfileId)
  }
  if ($sourceRegionDiagnosticProfiles.Count -eq 1) {
    $analysisArguments += @(
      '--source-region-diagnostic-profile-id',$sourceRegionDiagnosticProfileId
    )
  }
  foreach ($batch in $batchRecords) {
    $analysisArguments += @(
      '--log',$batch.stdout,
      '--batch-particle-count',([string]$batch.count)
    )
  }
  Invoke-SingleFlightPython -Arguments $analysisArguments `
    -Failure 'Single-flight log analysis failed.'
  if ($ResolutionQualification) {
    $qualificationSummary = Get-Content -LiteralPath $package.summary -Raw -Encoding UTF8 | ConvertFrom-Json
    $bootstrapRecords = @($qualificationSummary.full_pulse_eligible_bootstrap)
    if ($null -ne $qualificationSummary.spatial_window_peak) {
      $bootstrapRecords += @($qualificationSummary.spatial_window_peak.bootstrap)
    }
    if ($bootstrapRecords.Count -lt 2 -or @($bootstrapRecords | Where-Object {
          [string]$_.status -ne 'computed' -or
          [int]$_.resamples_requested -ne 5000 -or
          [int]$_.resamples_valid -lt 4750 -or
          [double]$_.relative_95pct_interval_width -gt 0.10
        }).Count -ne 0) {
      throw 'Resolution qualification bootstrap acceptance failed.'
    }
  }
  $sixPanel = Join-Path $package.result_dir 'single_flight_spatial_six_panel.png'
  $sixPanelMetadata = Join-Path $package.result_dir 'single_flight_spatial_six_panel_metadata.json'
  Invoke-SingleFlightPython -Arguments @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_single_flight_spatial_six_panel',
    '--initial',$globalSource,'--checkpoints',$checkpoints,'--upstream',$upstreamFrozen,
    '--frontend',$frontendContract,'--oatof',$oatofGeometry,'--output',$sixPanel,
    '--metadata',$sixPanelMetadata) -Failure 'Single-flight six-panel spatial diagnostic failed.'
  $result = Get-Content -LiteralPath $package.summary -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-RfThreeZoneCheckpointCensus -Required $hasThreeZoneCandidate `
    -Census $result.census -LaunchedCount $launched
  if ($hasThreeZoneCandidate) {
    $runConfiguration.parameters.accelerator_intermediate2_forward_count =
      [int]$result.census.accelerator_intermediate2_forward
  }
  $result | Add-Member -NotePropertyName single_flight_pa_cache_policy `
    -NotePropertyValue $PaCachePolicy -Force
  $result | Add-Member -NotePropertyName single_flight_pa_cache_policy_provenance `
    -NotePropertyValue $PaCachePolicyProvenance -Force
  $result | Add-Member -NotePropertyName pa_cache_dispositions `
    -NotePropertyValue $paCacheDispositions -Force
  Write-RfJson -Path $package.summary -Depth 10 -Value $result
  $baselineReceipt = $null
  $promotionReceipt = $null
  if ($PulseResolutionN100Screening) {
    $resultName = 'pulse_resolution_' + $PulseResolutionExperimentId + '_result.json'
    $baselineReceipt = Join-Path $package.result_dir $resultName
    $receiptArguments = @('-m',
      'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.register_pulse_resolution_result',
      '--campaign',$campaignFrozen,
      '--campaign-sha256',$PulseResolutionCampaignSha256,
      '--experiment-row-sha256',$PulseResolutionExperimentRowSha256,
      '--experiment-id',$PulseResolutionExperimentId,
      '--execution-mode',$PulseResolutionExecutionMode,
      '--summary',$package.summary,'--checkpoints',$checkpoints,
      '--source-identity',$sourceIdentity,'--prefix',$motherSource,
      '--prefix-plan-path',('inputs/' + [IO.Path]::GetFileName($motherSource)),
      '--prefix-sha256',$MotherParticleSourceSha256,
      '--registration-authority',$registrationAuthorityFrozen,
      '--registration-authority-sha256',$PulseResolutionRegistrationAuthoritySha256,
      '--output',$baselineReceipt)
    if (-not $isBaseline) {
      $promotionReceipt = Join-Path $package.result_dir (
        'pulse_resolution_' + $PulseResolutionExperimentId + '_promotion_receipt.json'
      )
      $receiptArguments += @('--promotion-receipt',$promotionReceipt)
    }
    Invoke-SingleFlightPython -Arguments $receiptArguments `
      -Failure 'N=100 pulse-resolution result receipt failed.'
    $registration = Get-Content -LiteralPath $baselineReceipt -Raw -Encoding UTF8 |
      ConvertFrom-Json
    $expectedStatus = if ($isBaseline) {
      'baseline_registered_not_candidate'
    } else { 'candidate_screening_complete_not_qualified' }
    if ($registration.execution_status -ne $expectedStatus -or
        $registration.formal_gate_passed) {
      throw 'N=100 screening result receipt differs.'
    }
    $result | Add-Member -NotePropertyName pulse_resolution_registration `
      -NotePropertyValue ([ordered]@{
        execution_status=$expectedStatus
        receipt=('results/' + $resultName)
        receipt_sha256=(Get-FileHash -LiteralPath $baselineReceipt -Algorithm SHA256).Hash
      }) -Force
    if ($null -ne $promotionReceipt) {
      $promotion = Get-Content -LiteralPath $promotionReceipt -Raw -Encoding UTF8 |
        ConvertFrom-Json
      $result | Add-Member -NotePropertyName pulse_resolution_promotion `
        -NotePropertyValue ([ordered]@{
          decision=[string]$promotion.decision
          population_count=[int]$promotion.pairing.population_count
          eligible_paired_count=[int]$promotion.pairing.eligible_paired_count
          failure_codes=@($promotion.failure_reasons | ForEach-Object { [string]$_.code })
          receipt=('results/' + [IO.Path]::GetFileName($promotionReceipt))
          receipt_sha256=(Get-FileHash -LiteralPath $promotionReceipt -Algorithm SHA256).Hash
        }) -Force
    }
    Write-RfJson -Path $package.summary -Depth 10 -Value $result
  }
  $runConfiguration.parameters.multipole_handoff_count = [int]$result.census.multipole_handoff
  $runConfiguration.parameters.local_accelerator_exit_count = [int]$result.census.local_accelerator_exit
  $runConfiguration.parameters.detector_crossing_count = [int]$result.census.detector_crossing
  Write-RfJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  $retentionActions = Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $outputs = @($checkpoints,$sixPanel,$sixPanelMetadata,$baselineReceipt,$promotionReceipt) + $stdoutFiles + $stderrFiles + $resourceUsageFiles + @($flightTubeBuildStdout,$flightTubeBuildStderr,$reflectronBuildStdout,$reflectronBuildStderr,$package.summary,$retentionActions) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
  foreach ($usage in $resourceUsageFiles) {
    if (-not (Complete-ResourceUsage -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir -UsagePath $usage)) { $resourceBudgetExceeded=$true; throw 'Single-flight compact retained-byte budget exceeded.' }
  }
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $repoRoot -RunConfig $package.run_config -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  Write-Output "SIMION_SINGLE_FLIGHT=PASS RUN_ID=$RunId DETECTOR=$($result.census.detector_crossing)/$launched"
} catch {
  Complete-RfFrozenFailedRun -Python $python -FrozenRepoRoot $repoRoot `
    -RunConfig $package.run_config -Summary $package.summary `
    -SummaryRole $summaryRole -Reason $_.Exception.Message `
    -Software @('SIMION 2020','Python 3.11') `
    -Status $(if ($resourceBudgetExceeded) {'interrupted'} else {'failed'}) `
    -FailureClass $(if ($resourceBudgetExceeded) {'resource_budget_exceeded'} else {''}) `
    -AdditionalSummaryProperties ([ordered]@{
      single_flight_pa_cache_policy=$PaCachePolicy
      single_flight_pa_cache_policy_provenance=$PaCachePolicyProvenance
      pa_cache_dispositions=$paCacheDispositions
      frozen_input_snapshot_completed=[bool]$snapshotReady
    }) `
    -ResourceUsagePath $(if ($resourceBudgetExceeded) {$resourceUsage} else {''})
  throw
}
