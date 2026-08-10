Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:RfOatofIntegrationId = (
  'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer'
)

function Assert-RfOatofExactProperties {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][psobject]$Object,
    [Parameter(Mandatory)][string[]]$Expected,
    [Parameter(Mandatory)][string]$Role
  )
  $actual = @($Object.PSObject.Properties.Name | Sort-Object)
  $required = @($Expected | Sort-Object)
  if ([string]::Join("`n", $actual) -ne [string]::Join("`n", $required)) {
    throw "$Role fields differ from the closed runtime contract."
  }
}

function Test-RfOatofPathWithin {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][string]$Root
  )
  $candidate = [IO.Path]::GetFullPath($Path)
  $boundary = [IO.Path]::GetFullPath($Root).TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
  )
  return $candidate.Equals($boundary, [StringComparison]::OrdinalIgnoreCase) -or
    $candidate.StartsWith(
      $boundary + [IO.Path]::DirectorySeparatorChar,
      [StringComparison]::OrdinalIgnoreCase
    )
}

function Get-RfOatofRepositoryTextSha256 {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$Path)
  $text = [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($Path))
  $canonical = $text.Replace("`r`n", "`n").Replace("`r", "`n")
  $bytes = [Text.UTF8Encoding]::new($false).GetBytes($canonical)
  $algorithm = [Security.Cryptography.SHA256]::Create()
  try {
    return [Convert]::ToHexString($algorithm.ComputeHash($bytes))
  } finally {
    $algorithm.Dispose()
  }
}

function Resolve-RfOatofBoundFile {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Root,
    [Parameter(Mandatory)][pscustomobject]$Record,
    [Parameter(Mandatory)][string]$Role,
    [switch]$AllowWorkspaceArtifact
  )
  if ($Record.PSObject.Properties.Name -notcontains 'path' -or
      $Record.PSObject.Properties.Name -notcontains 'sha256') {
    throw "$Role must freeze path and sha256."
  }
  $declaredPath = [string]$Record.path
  if ([string]::IsNullOrWhiteSpace($declaredPath) -or
      [IO.Path]::IsPathRooted($declaredPath) -or
      $declaredPath -match '(^|[\\/])\.\.([\\/]|$)') {
    throw "$Role path must be root-relative without parent traversal."
  }
  $rootPath = [IO.Path]::GetFullPath($Root)
  $allowedRoot = if ($AllowWorkspaceArtifact) {
    Split-Path -Parent $rootPath
  } else {
    $rootPath
  }
  $path = [IO.Path]::GetFullPath((Join-Path $allowedRoot $declaredPath))
  if (-not (Test-RfOatofPathWithin -Path $path -Root $allowedRoot) -or
      -not (Test-Path -LiteralPath $path -PathType Leaf)) {
    throw "$Role is missing or escapes its allowed root: $declaredPath"
  }
  $expectedSha256 = ([string]$Record.sha256).ToUpperInvariant()
  $actualSha256 = if ($AllowWorkspaceArtifact) {
    (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
  } else {
    Get-RfOatofRepositoryTextSha256 -Path $path
  }
  if ($expectedSha256 -notmatch '^[0-9A-F]{64}$' -or
      $actualSha256 -ne $expectedSha256) {
    throw "$Role SHA-256 differs: $declaredPath"
  }
  return $path
}

function Resolve-RfOatofDependencyContract {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$ContractPath
  )
  $contract = Get-Content -LiteralPath $ContractPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
  Assert-RfOatofExactProperties -Object $contract `
    -Role 'Family runtime dependency contract' `
    -Expected @(
      'schema_version','role','consumer_project','consumer_ids','dependencies',
      'runtime_policy','consumer_scope'
    )
  if ([int]$contract.schema_version -ne 2 -or
      $contract.role -ne 'rf_multipole_oatof_family_runtime_dependencies' -or
      $contract.consumer_project -ne $script:RfOatofIntegrationId -or
      $contract.consumer_scope -ne 'rf_multipole_registered_handoff_family') {
    throw 'Family runtime dependency identity differs from the closed contract.'
  }
  $expectedBaseIds = @(
    'oatof_baseline','oatof_accelerator_geometry_builder',
    'oatof_rf_handoff_adapter','oatof_resolved_geometry',
    'oatof_formal_validation','oatof_simion_stable_entry',
    'oatof_handoff_pulse_program_builder','oatof_formal_lua',
    'oatof_handoff_pulse_extension_lua','oatof_simion_log_analyzer_wrapper',
    'oatof_solver_diagnostics','oatof_accelerator_simion_builder',
    'oatof_accelerator_simion_gem','oatof_candidate_design_compiler',
    'oatof_design_variable_catalog','oatof_reflectron_simion_builder',
    'oatof_reflectron_simion_gem','oatof_flight_tube_simion_builder',
    'oatof_flight_tube_simion_gem','rf_simion_interface_transport_comparator',
    'rf_simion_grid2_state_materializer',
    'rf_interface_stage_plan',
    'rf_shared_joint_geometry','rf_pulse_capture_pulse_scheduler',
    'rf_pulse_capture_geometry_snapshot_plotter',
    'rf_pulse_capture_pulse_chain_auditor',
    'rf_pulse_capture_local_exit_adapter',
    'rf_analyzer_transport_simion_input_adapter',
    'rf_analyzer_transport_analyzer','rf_oatof_formal_release_validator',
    'common_simion_aperture_discretization_schema',
    'common_simion_aperture_discretizer',
    'common_simion_aperture_topology_support',
    'common_simion_aperture_topology_verifier',
    'common_grounded_shield_connector',
    'common_connection_profile_schema','common_component_port_schema',
    'common_resolved_connection_schema','common_machine_contracts',
    'common_particle_state','common_particle_count_policy',
    'common_multipole_numerical_qualification',
    'common_multipole_numerical_observables',
    'common_multipole_three_mode_dispersion','common_multipole_handoff_publisher',
    'common_rigid_transform','common_particle_physics',
    'common_component_particle_state','common_component_particle_state_schema',
    'common_file_identity','common_artifact_retention',
    'common_artifact_retention_policy','common_resource_budget_support',
    'common_verify_run_manifest','common_artifact_naming',
    'common_write_run_manifest','common_run_artifact_support',
    'common_require_powershell7','common_create_multipole_round_rods',
    'common_comsol_runner','common_comsol_resolver',
    'common_comsol_failure_classifier','common_comsol_environment',
    'common_comsol_startup'
  )
  $dependencyIds = @($contract.dependencies | ForEach-Object { [string]$_.id })
  if ([string]::Join("`n", $dependencyIds) -ne
      [string]::Join("`n", $expectedBaseIds)) {
    throw 'Family runtime dependency set or stable order differs.'
  }
  $allDependencies = @($contract.dependencies)
  $allIds = @($allDependencies | ForEach-Object { [string]$_.id })
  $runInputNames = @(
    $allDependencies | ForEach-Object { [string]$_.run_input_name }
  )
  $frozenFilenames = @(
    $allDependencies | ForEach-Object { [string]$_.frozen_filename }
  )
  if (@($allIds | Select-Object -Unique).Count -ne 64 -or
      @($runInputNames | Select-Object -Unique).Count -ne 64 -or
      @($frozenFilenames | Select-Object -Unique).Count -ne 64) {
    throw 'Resolved family dependency inventory contains duplicate identities or paths.'
  }
  foreach ($dependency in $allDependencies) {
    if ($dependency.PSObject.Properties.Name -notcontains 'source_repo_path' -or
        $dependency.PSObject.Properties.Name -notcontains 'frozen_filename' -or
        [string]::IsNullOrWhiteSpace([string]$dependency.source_repo_path) -or
        [IO.Path]::IsPathRooted([string]$dependency.source_repo_path) -or
        [string]$dependency.source_repo_path -match '(^|[\\/])\.\.([\\/]|$)' -or
        [IO.Path]::IsPathRooted([string]$dependency.frozen_filename) -or
        [string]$dependency.frozen_filename -match '(^|[\\/])\.\.([\\/]|$)') {
      throw "Family dependency path is missing or escapes the repository: $($dependency.id)"
    }
    $sourcePath = [IO.Path]::GetFullPath(
      (Join-Path $RepoRoot ([string]$dependency.source_repo_path))
    )
    if (-not (Test-RfOatofPathWithin -Path $sourcePath -Root $RepoRoot) -or
        -not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
      throw "Family dependency source is missing or escapes the repository: $($dependency.id)"
    }
  }
  return [pscustomobject]@{
    schema_version = 3
    role = 'rf_to_oatof_semantic_transfer_resolved_dependencies'
    consumer_project = [string]$contract.consumer_project
    consumer_ids = @($contract.consumer_ids)
    dependencies = $allDependencies
    runtime_policy = $contract.runtime_policy
    consumer_scope = [string]$contract.consumer_scope
    authority = [pscustomobject]@{
      path = [IO.Path]::GetFullPath($ContractPath)
    }
  }
}

function Publish-RfOatofDependencyInventory {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][psobject]$Runtime,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$InputDir,
    [Parameter(Mandatory)][string]$Role
  )
  $contractRelative = [string]$Runtime.binding.contracts.dependency_contract.path
  $contractFrozen = Join-Path $InputDir ('runtime_snapshot/' + $contractRelative)
  $contractIdentity = Copy-RfStableFile -SourceRunRoot $RepoRoot `
    -SourcePath $Runtime.contracts.dependency_contract `
    -Destination $contractFrozen -Role "$Role dependency contract"
  $inventory = [ordered]@{
    schema_version = 1
    role = 'rf_multipole_oatof_resolved_code_inventory'
    consumer_project = [string]$Runtime.dependency_contract.consumer_project
    consumer_ids = @($Runtime.dependency_contract.consumer_ids)
    dependencies = @($Runtime.dependency_contract.dependencies)
    runtime_policy = $Runtime.dependency_contract.runtime_policy
    consumer_scope = [string]$Runtime.dependency_contract.consumer_scope
    authority = [ordered]@{
      path = $contractRelative
      sha256 = $contractIdentity.sha256
    }
  }
  if (@($inventory.dependencies).Count -ne 58) {
    throw "$Role resolved code inventory must contain exactly 58 dependencies."
  }
  $inventoryPath = Join-Path $InputDir 'code_inventory.json'
  $inventoryJson = $inventory | ConvertTo-Json -Depth 20
  [IO.File]::WriteAllText(
    $inventoryPath,
    $inventoryJson + "`n",
    [Text.UTF8Encoding]::new($false)
  )
  return [pscustomobject]@{
    dependency_contract_path = $contractFrozen
    code_inventory_path = $inventoryPath
    dependency_contract_identity = $contractIdentity
  }
}

function Resolve-RfOatofRuntimeBinding {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$ResolvedConnection,
    [Parameter(Mandatory)][string]$RuntimeBinding,
    [Parameter(Mandatory)][string]$ExpectedConnectionProfileId,
    [Parameter(Mandatory)][ValidateSet('comsol','simion')]
    [string]$SourceBranchId,
    [Parameter(Mandatory)][string]$ResolvedSourceContract,
    [Parameter(Mandatory)][string]$ResolvedSourceContractSha256,
    [Parameter(Mandatory)][string]$UpstreamResolvedDesign,
    [Parameter(Mandatory)][string]$UpstreamResolvedDesignSha256
  )
  $repo = [IO.Path]::GetFullPath($RepoRoot)
  $resolvedPath = [IO.Path]::GetFullPath($ResolvedConnection)
  $bindingPath = [IO.Path]::GetFullPath($RuntimeBinding)
  $parentRunRoot = [IO.Path]::GetFullPath((Split-Path -Parent $resolvedPath))
  $resolvedSourceContractPath = [IO.Path]::GetFullPath($ResolvedSourceContract)
  $upstreamResolvedDesignPath = [IO.Path]::GetFullPath($UpstreamResolvedDesign)
  if (-not (Test-RfOatofPathWithin -Path $resolvedPath -Root $repo) -and
      -not (Test-RfOatofPathWithin -Path $resolvedPath -Root (Split-Path -Parent $repo))) {
    throw 'Resolved connection must remain within the repository workspace.'
  }
  if (-not (Test-RfOatofPathWithin -Path $bindingPath -Root $repo) -or
      -not (Test-Path -LiteralPath $bindingPath -PathType Leaf)) {
    throw 'Runtime binding must be one repository-local file.'
  }
  $runLocalInputs = @(
    [pscustomobject]@{
      path = $resolvedSourceContractPath
      filename = 'resolved_source_contract.json'
      sha256 = $ResolvedSourceContractSha256
      role = 'Resolved source contract'
    },
    [pscustomobject]@{
      path = $upstreamResolvedDesignPath
      filename = 'upstream_resolved_design.json'
      sha256 = $UpstreamResolvedDesignSha256
      role = 'Upstream resolved design'
    }
  )
  foreach ($inputRecord in $runLocalInputs) {
    if (-not (Test-RfOatofPathWithin -Path $inputRecord.path -Root $parentRunRoot) -or
        -not (Test-Path -LiteralPath $inputRecord.path -PathType Leaf) -or
        [IO.Path]::GetFileName($inputRecord.path) -ne $inputRecord.filename -or
        [string]$inputRecord.sha256 -notmatch '^[A-F0-9]{64}$' -or
        (Get-FileHash -LiteralPath $inputRecord.path -Algorithm SHA256).Hash -ne
          [string]$inputRecord.sha256) {
      throw "$($inputRecord.role) must be one current parent-run input with its raw SHA-256."
    }
  }
  $resolved = Get-Content -LiteralPath $resolvedPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $binding = Get-Content -LiteralPath $bindingPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
  Assert-RfOatofExactProperties -Object $binding -Role 'Runtime binding' `
    -Expected @(
      'schema_version','role','integration_id','connection_profile_id',
      'upstream_project_id','contracts','implementation_binding'
    )
  if ($resolved.role -ne 'resolved_connection_do_not_edit' -or
      $resolved.compatibility.status -ne 'pass' -or
      $resolved.selection.connection_profile_id -ne
        $ExpectedConnectionProfileId) {
    throw 'Runtime binding requires the selected compatible resolved connection.'
  }
  if ([int]$binding.schema_version -ne 3 -or
      $binding.role -ne 'rf_multipole_oatof_runtime_binding' -or
      $binding.integration_id -ne $script:RfOatofIntegrationId -or
      $binding.connection_profile_id -ne $ExpectedConnectionProfileId) {
    throw 'Runtime binding identity differs from the selected integration profile.'
  }
  $upstreamProjectId = [string]$resolved.selection.upstream_project_id
  if ($upstreamProjectId -notmatch '^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$' -or
      $binding.upstream_project_id -ne $upstreamProjectId) {
    throw 'Runtime binding upstream project differs from the resolved connection.'
  }

  $requiredContracts = @(
    'dependency_contract',
    'pre_pulse_contract',
    'pulse_capture_contract',
    'pulse_timing_contract',
    'handoff_contract',
    'handoff_publication_contract',
    'source_adapter_contract',
    'execution_policy_contract'
  )
  Assert-RfOatofExactProperties -Object $binding.contracts `
    -Expected $requiredContracts -Role 'Runtime binding contracts'
  $contractPaths = [ordered]@{}
  foreach ($name in @($requiredContracts | Where-Object { $_ -ne 'dependency_contract' })) {
    if ($binding.contracts.PSObject.Properties.Name -notcontains $name) {
      throw "Runtime binding is missing required contract: $name"
    }
    $contractPaths[$name] = Resolve-RfOatofBoundFile -Root $repo `
      -Record $binding.contracts.$name -Role "runtime $name"
  }
  $contractPaths.resolved_source_contract = $resolvedSourceContractPath
  $contractPaths.upstream_resolved_design = $upstreamResolvedDesignPath
  $contractPaths.dependency_contract = Resolve-RfOatofBoundFile `
    -Root $repo -Record $binding.contracts.dependency_contract `
    -Role 'runtime dependency contract'
  $dependencyContract = Resolve-RfOatofDependencyContract -RepoRoot $repo `
    -ContractPath $contractPaths.dependency_contract
  $authority = $resolved.sources.upstream_authority
  if (([string]$authority.sha256).ToUpperInvariant() -ne
      $UpstreamResolvedDesignSha256.ToUpperInvariant()) {
    throw 'Runtime resolved design differs from the upstream port authority.'
  }
  $upstreamDesign = Get-Content -LiteralPath $upstreamResolvedDesignPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($upstreamDesign.PSObject.Properties.Name -notcontains 'identity' -or
      [string]$upstreamDesign.identity.project_id -ne $upstreamProjectId) {
    throw 'Run-local upstream resolved design project identity differs.'
  }

  $implementationBindingPath = Resolve-RfOatofBoundFile -Root $repo `
    -Record $binding.implementation_binding -Role 'runtime implementation binding'
  $implementationBinding = Get-Content -LiteralPath $implementationBindingPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  Assert-RfOatofExactProperties -Object $implementationBinding `
    -Expected @('schema_version','role','integration_id','implementation') `
    -Role 'Runtime implementation registry'
  if ([int]$implementationBinding.schema_version -ne 1 -or
      $implementationBinding.role -ne
        'rf_multipole_oatof_family_runtime_implementation' -or
      $implementationBinding.integration_id -ne $script:RfOatofIntegrationId) {
    throw 'Runtime implementation registry identity differs.'
  }
  $integrationRelativeRoot = (
    'integrations/' + $script:RfOatofIntegrationId + '/'
  )
  $implementationRecords = @(
    $implementationBinding.implementation.PSObject.Properties
  )
  $requiredImplementationRoles = @(
    'run_artifact_support','runtime_binding_support','transfer_runner',
    'single_flight_runner','pre_pulse_runner','pulse_capture_runner',
    'analyzer_transport_runner'
  )
  $availableImplementationRoles = @(
    $implementationRecords | ForEach-Object { [string]$_.Name }
  )
  foreach ($name in $requiredImplementationRoles) {
    if ($availableImplementationRoles -notcontains $name) {
      throw "Runtime implementation binding is missing required role: $name"
    }
  }
  $implementation = [ordered]@{}
  foreach ($property in $implementationRecords) {
    $name = [string]$property.Name
    $record = $property.Value
    Assert-RfOatofExactProperties -Object $record -Expected @('path','sha256') `
      -Role "Runtime implementation $name"
    if ($name -notmatch '^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$' -or
        -not ([string]$record.path).StartsWith(
          $integrationRelativeRoot,
          [StringComparison]::Ordinal
        )) {
      throw "Runtime implementation role or integration-local path differs: $name"
    }
    $implementation[$name] = Resolve-RfOatofBoundFile -Root $repo `
      -Record $record -Role "runtime implementation $name"
  }
  $runArtifactSupport = $implementation.run_artifact_support

  $sourceContract = Get-Content -LiteralPath $contractPaths.resolved_source_contract `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ([int]$sourceContract.schema_version -ne 2 -or
      $sourceContract.role -ne 'rf_multipole_oatof_source_contract' -or
      $sourceContract.upstream_project_id -ne $upstreamProjectId) {
    throw 'Runtime source contract identity differs from the upstream project.'
  }
  $expectedSourceContractFields = @(
    'schema_version','role','upstream_project_id','selector','adapter',
    'canonical_state','source_branches'
  )
  if ($sourceContract.PSObject.Properties.Name -contains 'design_reference') {
    $expectedSourceContractFields += 'design_reference'
  }
  Assert-RfOatofExactProperties -Object $sourceContract `
    -Expected $expectedSourceContractFields `
    -Role 'Runtime resolved source contract'
  if ($sourceContract.source_branches.PSObject.Properties.Name -notcontains
      $SourceBranchId) {
    throw 'Resolved source contract omits the selected comsol or simion branch.'
  }
  $sourceBranch = $sourceContract.source_branches.PSObject.Properties[
    $SourceBranchId
  ].Value
  Assert-RfOatofExactProperties -Object $sourceBranch `
    -Expected @('solver_id','recorded_project_id','source') `
    -Role 'Runtime source branch'
  $sourceBranchSolverId = [string]$sourceBranch.solver_id
  $recordedProjectId = [string]$sourceBranch.recorded_project_id
  $sourceRecord = $sourceBranch.source
  if ($sourceBranchSolverId -ne $SourceBranchId) {
    throw 'Runtime source branch solver identity differs from SourceBranchId.'
  }
  if ([string]::IsNullOrWhiteSpace($recordedProjectId)) {
    throw 'Runtime source contract recorded project identity is empty.'
  }
  Assert-RfOatofExactProperties -Object $sourceContract.selector `
    -Expected @('event','status') -Role 'Runtime source selector'
  Assert-RfOatofExactProperties -Object $sourceContract.canonical_state `
    -Expected @(
      'frame_id','clock_epoch_id','lineage_policy','species_policy'
    ) -Role 'Runtime source canonical state'
  if ($sourceContract.selector.event -ne 'handoff' -or
      $sourceContract.selector.status -ne 'transmitted') {
    throw 'Runtime source selector must freeze transmitted handoff rows.'
  }
  if ($sourceContract.adapter.callable -ne 'publish_family_source_bundle' -or
      $sourceContract.adapter.output_schema -ne 'component_particle_state_v1') {
    throw 'Runtime source adapter identity or canonical output schema differs.'
  }
  Assert-RfOatofExactProperties -Object $sourceContract.adapter `
    -Expected @('path','sha256','callable','output_schema','dependencies') `
    -Role 'Runtime source adapter'
  $stableSourceAdapter = Get-Content `
    -LiteralPath $contractPaths.source_adapter_contract -Raw -Encoding UTF8 |
    ConvertFrom-Json
  Assert-RfOatofExactProperties -Object $stableSourceAdapter `
    -Expected @(
      'schema_version','role','integration_id','selector','adapter','canonical_state'
    ) -Role 'Stable source adapter contract'
  if ([int]$stableSourceAdapter.schema_version -ne 1 -or
      $stableSourceAdapter.role -ne 'rf_multipole_oatof_source_adapter' -or
      $stableSourceAdapter.integration_id -ne $script:RfOatofIntegrationId -or
      [string]$stableSourceAdapter.selector.event -ne
        [string]$sourceContract.selector.event -or
      [string]$stableSourceAdapter.selector.status -ne
        [string]$sourceContract.selector.status) {
    throw 'Resolved source selector differs from the stable source adapter contract.'
  }
  foreach ($name in @('path','sha256','callable','output_schema')) {
    if ([string]$sourceContract.adapter.$name -ne
        [string]$stableSourceAdapter.adapter.$name) {
      throw "Resolved source adapter differs from its stable contract: $name"
    }
  }
  foreach ($name in @(
      'frame_id','clock_epoch_id','lineage_policy','species_policy'
    )) {
    if ([string]$sourceContract.canonical_state.$name -ne
        [string]$stableSourceAdapter.canonical_state.$name) {
      throw "Resolved source canonical state differs from its stable contract: $name"
    }
  }
  $sourceAdapter = Resolve-RfOatofBoundFile -Root $repo `
    -Record $sourceContract.adapter -Role 'runtime source adapter'
  Assert-RfOatofExactProperties -Object $sourceContract.adapter.dependencies `
    -Expected @('handoff_publication_contract') `
    -Role 'Runtime family source adapter dependencies'
  $publicationRecord =
    $sourceContract.adapter.dependencies.handoff_publication_contract
  $selectedPublicationContract = Resolve-RfOatofBoundFile -Root $repo `
    -Record $publicationRecord -Role 'runtime handoff publication contract'
  $publicationContract = Get-Content -LiteralPath $selectedPublicationContract `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ([int]$publicationContract.schema_version -ne 1 -or
      [string]$publicationContract.role -ne
        'multipole_handoff_publication_contract' -or
      [int]$publicationContract.population.expected_source_particle_count -ne
        [int]$sourceRecord.launched_particle_count -or
      [string]$publicationContract.canonical_state.source_component_id -ne
        $upstreamProjectId) {
    throw 'Resolved source handoff publication contract differs from the selected source population.'
  }
  $sourceAdapterDependencies = [ordered]@{
    handoff_publication_contract = $selectedPublicationContract
  }
  $expectedCanonicalFrameId =
    [string]$resolved.port_geometry.upstream.coordinate_frame.frame_id
  if ($sourceContract.canonical_state.frame_id -ne
        $expectedCanonicalFrameId -or
      $sourceContract.canonical_state.clock_epoch_id -ne
        $resolved.port_geometry.downstream.clock.origin_id -or
      $sourceContract.canonical_state.lineage_policy -ne
        'preserve_root_birth_time_and_component_elapsed_time' -or
      $sourceContract.canonical_state.species_policy -ne
        'frozen_particle_source_mass_and_charge') {
    throw 'Runtime source canonical frame, clock, species or lineage policy differs.'
  }
  $sourceManifest = Resolve-RfOatofBoundFile -Root $repo `
    -Record $sourceRecord.manifest -Role 'runtime source manifest' `
    -AllowWorkspaceArtifact
  $sourceState = Resolve-RfOatofBoundFile -Root $repo `
    -Record $sourceRecord.state -Role 'runtime source state' `
    -AllowWorkspaceArtifact
  $sourceParticleSource = Resolve-RfOatofBoundFile -Root $repo `
    -Record $sourceRecord.particle_source `
    -Role 'runtime source particle source' -AllowWorkspaceArtifact
  $sourceMetadata = $null
  if ($sourceRecord.PSObject.Properties.Name -contains 'metadata') {
    $sourceMetadata = Resolve-RfOatofBoundFile -Root $repo `
      -Record $sourceRecord.metadata -Role 'runtime source metadata' `
      -AllowWorkspaceArtifact
  }
  $expectedSourceFields = @(
    'run_id','particle_count','particle_source_manifest_input_role',
    'manifest','state','particle_source'
  )
  if ($sourceRecord.PSObject.Properties.Name -contains 'metadata') {
    $expectedSourceFields += 'metadata'
  }
  if ($sourceRecord.PSObject.Properties.Name -contains
      'launched_particle_count') {
    $expectedSourceFields += 'launched_particle_count'
  }
  Assert-RfOatofExactProperties -Object $sourceRecord `
    -Expected $expectedSourceFields -Role 'Runtime source run'
  if ([string]::IsNullOrWhiteSpace([string]$sourceRecord.run_id) -or
      [int]$sourceRecord.particle_count -lt 1 -or
      [string]::IsNullOrWhiteSpace(
        [string]$sourceRecord.particle_source_manifest_input_role
      )) {
    throw 'Runtime source run identity or particle-source binding differs.'
  }
  $launchedParticleCount = if (
    $sourceRecord.PSObject.Properties.Name -contains 'launched_particle_count'
  ) {
    [int]$sourceRecord.launched_particle_count
  } else {
    [int]$sourceRecord.particle_count
  }
  $particleSourceRowCount = @(Import-Csv -LiteralPath $sourceParticleSource).Count
  if ($launchedParticleCount -lt [int]$sourceRecord.particle_count -or
      $particleSourceRowCount -ne $launchedParticleCount) {
    throw 'Runtime launched and selected particle populations differ from their frozen files.'
  }
  $sourceManifestDocument = Get-Content -LiteralPath $sourceManifest `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $particleSourceRole = [string](
    $sourceRecord.particle_source_manifest_input_role
  )
  if ($sourceManifestDocument.inputs.PSObject.Properties.Name -notcontains
      $particleSourceRole -or
      $sourceManifestDocument.PSObject.Properties.Name -notcontains 'outputs') {
    throw 'Runtime source manifest omits its particle source or outputs.'
  }
  $manifestParticleSource = $sourceManifestDocument.inputs.$particleSourceRole
  $designManifestDocument = $sourceManifestDocument
  if ($sourceContract.PSObject.Properties.Name -contains 'design_reference') {
    Assert-RfOatofExactProperties -Object $sourceContract.design_reference `
      -Expected @('run_id','manifest') -Role 'Runtime design reference'
    $designManifestPath = Resolve-RfOatofBoundFile -Root $repo `
      -Record $sourceContract.design_reference.manifest `
      -Role 'runtime design-reference manifest' -AllowWorkspaceArtifact
    $designManifestDocument = Get-Content -LiteralPath $designManifestPath `
      -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($designManifestDocument.role -ne 'simulation_run_manifest' -or
        $designManifestDocument.status -ne 'success' -or
        $designManifestDocument.project -ne $recordedProjectId -or
        $designManifestDocument.run_id -ne
          $sourceContract.design_reference.run_id) {
      throw 'Runtime design-reference manifest identity differs.'
    }
  }
  $manifestResolvedDesign =
    $designManifestDocument.inputs.PSObject.Properties['multipole_resolved_design']
  if ($null -eq $manifestResolvedDesign -or
      -not [bool]$manifestResolvedDesign.Value.exists -or
      ([string]$manifestResolvedDesign.Value.sha256).ToUpperInvariant() -ne
        $UpstreamResolvedDesignSha256.ToUpperInvariant()) {
    throw 'Runtime design authority does not freeze the selected upstream resolved design.'
  }
  $manifestStateMatches = @(
    $sourceManifestDocument.outputs | Where-Object {
      $_.PSObject.Properties.Name -contains 'path' -and
      [IO.Path]::GetFullPath([string]$_.path).Equals(
        [IO.Path]::GetFullPath($sourceState),
        [StringComparison]::OrdinalIgnoreCase
      )
    }
  )
  if ($sourceManifestDocument.role -ne 'simulation_run_manifest' -or
      $sourceManifestDocument.status -ne 'success' -or
      $sourceManifestDocument.project -ne $recordedProjectId -or
      $sourceManifestDocument.run_id -ne $sourceRecord.run_id -or
      -not [bool]$manifestParticleSource.exists -or
      -not [IO.Path]::GetFullPath([string]$manifestParticleSource.path).Equals(
        [IO.Path]::GetFullPath($sourceParticleSource),
        [StringComparison]::OrdinalIgnoreCase
      ) -or
      ([string]$manifestParticleSource.sha256).ToUpperInvariant() -ne
        ([string]$sourceRecord.particle_source.sha256).ToUpperInvariant() -or
      $manifestStateMatches.Count -ne 1 -or
      -not [bool]$manifestStateMatches[0].exists -or
      ([string]$manifestStateMatches[0].sha256).ToUpperInvariant() -ne
        ([string]$sourceRecord.state.sha256).ToUpperInvariant()) {
    throw 'Runtime source manifest does not prove the frozen successful source run.'
  }
  $selectedStateRows = @(
    Import-Csv -LiteralPath $sourceState | Where-Object {
      [string]$_.event -eq [string]$sourceContract.selector.event -and
      [string]$_.status -eq [string]$sourceContract.selector.status
    }
  )
  if ($selectedStateRows.Count -ne
      [int]$sourceRecord.particle_count) {
    throw 'Runtime source state does not contain the declared selected handoff population.'
  }

  $sourceIdentity = [ordered]@{
    source_branch_id = $SourceBranchId
    solver_id = $sourceBranchSolverId
    run_id = [string]$sourceRecord.run_id
    project_id = $recordedProjectId
    manifest_sha256 = (
      [string]$sourceRecord.manifest.sha256
    ).ToUpperInvariant()
    event_sha256 = (
      [string]$sourceRecord.state.sha256
    ).ToUpperInvariant()
    particle_source_sha256 = (
      [string]$sourceRecord.particle_source.sha256
    ).ToUpperInvariant()
    metadata_sha256 = if ($null -ne $sourceMetadata) {
      ([string]$sourceRecord.metadata.sha256).ToUpperInvariant()
    } else {
      ''
    }
  }

  return [pscustomobject]@{
    binding_path = $bindingPath
    binding = $binding
    resolved_connection = $resolved
    resolved_connection_path = $resolvedPath
    upstream_project_id = $upstreamProjectId
    recorded_project_id = $recordedProjectId
    source_branch_id = $SourceBranchId
    source_solver_id = $sourceBranchSolverId
    contracts = [pscustomobject]$contractPaths
    dependency_contract = $dependencyContract
    implementation_binding = $implementationBindingPath
    implementation = [pscustomobject]$implementation
    run_artifact_support = $runArtifactSupport
    resolved_source_contract = $sourceContract
    source_record = $sourceRecord
    source_adapter = $sourceAdapter
    source_adapter_dependencies = [pscustomobject]$sourceAdapterDependencies
    source_manifest = $sourceManifest
    source_state = $sourceState
    source_particle_source = $sourceParticleSource
    source_metadata = $sourceMetadata
    source_identity = [pscustomobject]$sourceIdentity
  }
}

function Assert-RfOatofSourceIdentityMatches {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][psobject]$Actual,
    [Parameter(Mandatory)][psobject]$Expected,
    [Parameter(Mandatory)][string]$Role
  )
  $required = @(
    'run_id',
    'project_id',
    'manifest_sha256',
    'event_sha256',
    'metadata_sha256'
  )
  if ($Expected.PSObject.Properties.Name -contains 'source_branch_id') {
    $required = @(
      'source_branch_id',
      'solver_id',
      'run_id',
      'project_id',
      'manifest_sha256',
      'event_sha256',
      'particle_source_sha256',
      'metadata_sha256'
    )
  }
  foreach ($name in $required) {
    if ($Actual.PSObject.Properties.Name -notcontains $name -or
        [string]$Actual.$name -ne [string]$Expected.$name) {
      throw "$Role differs from the runtime source identity: $name"
    }
  }
}
