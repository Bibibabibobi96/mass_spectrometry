[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$SourceRunId,
  [Parameter(Mandatory)][string]$RunId,
  [Parameter(Mandatory)][string]$ExpectedConnectionProfileId,
  [Parameter(Mandatory)][string]$ResolvedConnection,
  [Parameter(Mandatory)][string]$ResolvedEngineeringBudget,
  [Parameter(Mandatory)][string]$RuntimeBinding,
  [Parameter(Mandatory)][ValidateSet('comsol','simion')]
  [string]$SourceBranchId,
  [Parameter(Mandatory)][string]$ResolvedSourceContract,
  [Parameter(Mandatory)][string]$ResolvedSourceContractSha256,
  [Parameter(Mandatory)][string]$UpstreamResolvedDesign,
  [Parameter(Mandatory)][string]$UpstreamResolvedDesignSha256,
  [ValidateSet('local_accelerator_exit','simion_local_accelerator_exit','oatof_entry')]
  [string]$SourceEvent = 'local_accelerator_exit',
  [string]$ReferencePulseCaptureRunId = '',
  [string]$InterfacePaSourceRunId = '',
  [string]$InterfacePaDirectory = '',
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$integrationRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $integrationRoot '..\..')).Path
. (Join-Path $integrationRoot 'runtime\runtime_binding.ps1')
$runtime = Resolve-RfOatofRuntimeBinding -RepoRoot $repoRoot `
  -ResolvedConnection $ResolvedConnection -RuntimeBinding $RuntimeBinding `
  -ExpectedConnectionProfileId $ExpectedConnectionProfileId `
  -SourceBranchId $SourceBranchId `
  -ResolvedSourceContract $ResolvedSourceContract `
  -ResolvedSourceContractSha256 $ResolvedSourceContractSha256 `
  -UpstreamResolvedDesign $UpstreamResolvedDesign `
  -UpstreamResolvedDesignSha256 $UpstreamResolvedDesignSha256
$upstreamProjectId = $runtime.upstream_project_id
$python = if ($PythonExe) {
  [IO.Path]::GetFullPath($PythonExe)
} else {
  Join-Path $repoRoot '.venv\Scripts\python.exe'
}
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot "artifacts\projects\$upstreamProjectId"
$supportSource = $runtime.run_artifact_support
. $supportSource

function Invoke-AnalyzerTransportSnapshotPython {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$SnapshotRoot,
    [Parameter(Mandatory)][object[]]$Arguments,
    [Parameter(Mandatory)][string]$FailureMessage
  )
  $environmentNames = @('PYTHONPATH','PYTHONNOUSERSITE')
  $savedEnvironment = Save-RfEnvironment -Names $environmentNames
  try {
    $env:PYTHONPATH = $SnapshotRoot
    $env:PYTHONNOUSERSITE = '1'
    Push-Location -LiteralPath $SnapshotRoot
    try {
      & $Python @Arguments
      if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
    } finally {
      Pop-Location
    }
  } finally {
    Restore-RfEnvironment -Names $environmentNames -Snapshot $savedEnvironment
  }
}

function Get-AnalyzerTransportFormalAssetRecords {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$ChecksumPath,
    [Parameter(Mandatory)][string]$FormalRoot
  )
  $rows = @(Import-Csv -LiteralPath $ChecksumPath)
  if ($rows.Count -eq 0) {
    throw 'oaTOF Formal checksum inventory is empty.'
  }
  $assetPattern =
    '^(accelerator|detector_ground|flight_tube_ground|reflectron)\.pa(?:-surf|#|\d+)$'
  $assets = @(
    $rows | Where-Object {
      $_.file -in @('oatof_ideal_grounded.iob','oatof_ideal_grounded.con') -or
      $_.file -match $assetPattern
    }
  )
  if (@($assets.file | Select-Object -Unique).Count -ne $assets.Count) {
    throw 'oaTOF Formal asset inventory contains duplicate filenames.'
  }
  foreach ($required in @(
      'oatof_ideal_grounded.iob','oatof_ideal_grounded.con'
    )) {
    if (@($assets | Where-Object { $_.file -eq $required }).Count -ne 1) {
      throw "oaTOF Formal asset inventory requires exactly one $required."
    }
  }
  $expectedGroups = @(
    'accelerator','detector_ground','flight_tube_ground','reflectron'
  )
  $actualGroups = @(
    $assets |
      Where-Object { $_.file -match $assetPattern } |
      ForEach-Object {
        [regex]::Match($_.file, $assetPattern).Groups[1].Value
      } |
      Sort-Object -Unique
  )
  if (($actualGroups -join ',') -ne ($expectedGroups -join ',')) {
    throw 'oaTOF Formal PA group identity is incomplete or mixed.'
  }
  foreach ($group in $expectedGroups) {
    $groupNames = @(
      $assets | Where-Object { $_.file -match "^$group\.pa(?:-surf|#|\d+)$" } |
        Select-Object -ExpandProperty file
    )
    foreach ($suffix in @('-surf','#','0')) {
      if ($groupNames -notcontains "$group.pa$suffix") {
        throw "oaTOF Formal PA group $group is incomplete."
      }
    }
    $indices = @(
      $groupNames |
        Where-Object { $_ -match "^$group\.pa(\d+)$" } |
        ForEach-Object { [int]$Matches[1] } |
        Sort-Object -Unique
    )
    if ($indices.Count -eq 0 -or
        ($indices -join ',') -ne ((0..$indices[-1]) -join ',')) {
      throw "oaTOF Formal PA group $group has a non-contiguous index set."
    }
  }
  $formal = [IO.Path]::GetFullPath($FormalRoot)
  foreach ($asset in $assets) {
    $name = [string]$asset.file
    if ([IO.Path]::IsPathRooted($name) -or
        $name.IndexOfAny([char[]]@('\','/')) -ge 0) {
      throw 'oaTOF Formal asset filename must be a direct-child name.'
    }
    $expectedHash = ([string]$asset.sha256).ToUpperInvariant()
    if ($expectedHash -notmatch '^[0-9A-F]{64}$') {
      throw "oaTOF Formal asset SHA-256 is invalid: $name"
    }
    $path = [IO.Path]::GetFullPath((Join-Path $formal $name))
    if (-not (Split-Path -Parent $path).Equals(
        $formal, [StringComparison]::OrdinalIgnoreCase
      ) -or -not (Test-Path -LiteralPath $path -PathType Leaf)) {
      throw "oaTOF Formal asset is missing or escapes its release: $name"
    }
    if ((Get-Item -LiteralPath $path).Length -ne [long]$asset.bytes -or
        (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne
          $expectedHash) {
      throw "oaTOF Formal asset identity differs from SHA256SUMS: $name"
    }
  }
  return $assets
}

function Get-AnalyzerTransportReleaseAssetRecord {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][pscustomobject]$Manifest,
    [Parameter(Mandatory)][string]$ExpectedRelativePath,
    [Parameter(Mandatory)][string]$FormalProjectRoot
  )
  if ($Manifest.PSObject.Properties.Name -notcontains 'assets') {
    throw 'oaTOF Formal asset manifest has no assets object.'
  }
  $matches = @(
    $Manifest.assets.PSObject.Properties |
      ForEach-Object { $_.Value } |
      Where-Object { [string]$_.path -eq $ExpectedRelativePath }
  )
  if ($matches.Count -ne 1) {
    throw "oaTOF Formal release requires exactly one $ExpectedRelativePath record."
  }
  $record = $matches[0]
  $sourcePath = [IO.Path]::GetFullPath(
    (Join-Path $FormalProjectRoot $ExpectedRelativePath.Replace('/','\'))
  )
  $formalProject = [IO.Path]::GetFullPath($FormalProjectRoot)
  $expectedHash = ([string]$record.sha256).ToUpperInvariant()
  if (-not (Test-RfDependencyPathWithin -Path $sourcePath -Root $formalProject) -or
      -not (Test-Path -LiteralPath $sourcePath -PathType Leaf) -or
      $expectedHash -notmatch '^[0-9A-F]{64}$' -or
      (Get-Item -LiteralPath $sourcePath).Length -ne [long]$record.bytes -or
      (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash -ne
        $expectedHash) {
    throw "oaTOF Formal release asset identity differs: $ExpectedRelativePath"
  }
  return [pscustomobject]@{
    path = $sourcePath
    exists = $true
    bytes = [long]$record.bytes
    sha256 = $expectedHash
  }
}

$interfaceDiagnostic = $SourceEvent -eq 'oatof_entry'
$simionGrid2Replay = $SourceEvent -eq 'simion_local_accelerator_exit'
$expectedSourceMode = if ($interfaceDiagnostic) {
  'rf_to_oatof_pre_pulse_interface_transport'
} elseif ($simionGrid2Replay) {
  'rf_to_oatof_simion_interface_transport'
} else {
  'rf_to_oatof_pulse_capture'
}
if ($interfaceDiagnostic -and [string]::IsNullOrWhiteSpace($ReferencePulseCaptureRunId)) {
  throw 'oatof_entry source requires one reference COMSOL PulseCapture run.'
}
$runMode = if ($interfaceDiagnostic) {
  'rf_to_oatof_simion_interface_transport'
} else { 'rf_to_oatof_analyzer_transport' }
$software = @('COMSOL 6.4','SIMION 2020','Python 3.11')
$package = New-RfRunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot $artifactRoot -RunId $RunId `
  -Project $upstreamProjectId `
  -Mode $runMode -Software $software `
  -RetentionContractEnabled -RetentionClass compact `
  -AdditionalDirectories @('simion')
$python = $package.python
$runsRoot = Join-Path $artifactRoot 'runs'
$resourceBudgetExceeded = $false
$snapshotRoot = Join-Path $package.input_dir 'runtime_snapshot'
$manifestToolRoot = $snapshotRoot
$snapshotReady = $false
$stageTimingPath = Join-Path $package.log_dir 'stage_timings.json'
$stageTimings = [ordered]@{}
$stageTimer = [Diagnostics.Stopwatch]::StartNew()
$totalTimer = [Diagnostics.Stopwatch]::StartNew()

function Complete-AnalyzerTransportStageTiming {
  param([Parameter(Mandatory)][string]$Name)
  $stageTimings[$Name] = [math]::Round($stageTimer.Elapsed.TotalSeconds, 3)
  $stageTimer.Restart()
}

try {
  if (-not (Test-Path -LiteralPath $SimionExe -PathType Leaf)) {
    throw "SIMION is missing: $SimionExe"
  }

  $runner = Join-Path $package.input_dir 'run_analyzer_transport.ps1.txt'
  $support = Join-Path $package.input_dir 'run_artifacts.ps1.txt'
  $runtimeBindingFrozen = Join-Path $package.input_dir 'runtime_binding.json'
  $resolvedConnectionFrozen =
    Join-Path $package.input_dir 'resolved_connection.json'
  $resolvedSourceContractFrozen =
    Join-Path $package.input_dir 'resolved_source_contract.json'
  $upstreamResolvedDesignFrozen =
    Join-Path $package.input_dir 'upstream_resolved_design.json'
  $runnerIdentity = Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath $PSCommandPath -Destination $runner -Role 'end-to-end runner'
  $supportIdentity = Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath $supportSource -Destination $support -Role 'run artifact support'
  Copy-Item -LiteralPath $runtime.binding_path -Destination $runtimeBindingFrozen
  Copy-Item -LiteralPath $runtime.resolved_connection_path `
    -Destination $resolvedConnectionFrozen
  Copy-Item -LiteralPath $runtime.contracts.resolved_source_contract `
    -Destination $resolvedSourceContractFrozen
  Copy-Item -LiteralPath $runtime.contracts.upstream_resolved_design `
    -Destination $upstreamResolvedDesignFrozen

  $dependencyPublication = Publish-RfOatofDependencyInventory `
    -Runtime $runtime -RepoRoot $repoRoot -InputDir $package.input_dir `
    -Role 'AnalyzerTransport'
  $dependencyContract = $dependencyPublication.code_inventory_path
  $dependencyDocument = Get-Content -LiteralPath $dependencyContract `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $dependencyConsumer = 'analyzer_transport'
  if (@($dependencyDocument.consumer_ids) -notcontains $dependencyConsumer) {
    throw "PulseCapture dependency consumer is not declared: $dependencyConsumer"
  }
  $selectedDependencies = @(
    $dependencyDocument.dependencies |
      Where-Object { @($_.consumers) -contains $dependencyConsumer }
  )
  if ($selectedDependencies.Count -eq 0 -or
      @($selectedDependencies.id | Select-Object -Unique).Count -ne
        $selectedDependencies.Count) {
    throw 'PulseCapture end-to-end dependency subset is empty or has duplicate identities.'
  }
  $dependencyIdentities = [ordered]@{}
  $dependencySnapshotPaths = @{}
  $dependencyCompatibilityPaths = @{}
  foreach ($dependency in $selectedDependencies) {
    $identity = Copy-RfFrozenDependency -RepoRoot $repoRoot `
      -InputDir $package.input_dir -Dependency $dependency
    if ((Get-FileHash -LiteralPath $identity.snapshot_path -Algorithm SHA256).Hash -ne
        $identity.sha256) {
      throw "PulseCapture end-to-end dependency snapshot identity differs: $($identity.id)"
    }
    $dependencyIdentities[$identity.id] = [ordered]@{
      provider_scope = $identity.provider_scope
      provider_project = $identity.provider_project
      provider_repo_path = $identity.provider_repo_path
      source_repo_path = $identity.source_repo_path
      frozen_input_name = $identity.frozen_input_name
      consumers = @($identity.consumers)
      snapshot_path = $identity.snapshot_path
      compatibility_path = $identity.compatibility_path
      sha256 = $identity.sha256
    }
    $dependencySnapshotPaths[$identity.id] = $identity.snapshot_path
    $dependencyCompatibilityPaths[$identity.id] = $identity.compatibility_path
  }
  $requiredSnapshotIds = @(
    'rf_analyzer_transport_simion_input_adapter','rf_analyzer_transport_analyzer',
    'rf_oatof_formal_release_validator',
    'oatof_rf_handoff_adapter',
    'oatof_baseline','oatof_resolved_geometry','oatof_formal_validation',
    'oatof_simion_stable_entry',
    'oatof_handoff_pulse_program_builder',
    'oatof_formal_lua','oatof_handoff_pulse_extension_lua',
    'oatof_simion_log_analyzer_wrapper','oatof_solver_diagnostics',
    'oatof_accelerator_simion_builder','oatof_accelerator_simion_gem',
    'rf_simion_interface_transport_comparator',
    'rf_simion_grid2_state_materializer','rf_shared_joint_geometry',
    'common_rigid_transform','common_particle_physics',
    'common_component_particle_state','common_component_particle_state_schema',
    'common_file_identity','common_artifact_retention',
    'common_artifact_retention_policy','common_resource_budget_support',
    'common_verify_run_manifest',
    'common_artifact_naming','common_write_run_manifest',
    'common_run_artifact_support','common_require_powershell7'
  )
  foreach ($requiredId in $requiredSnapshotIds) {
    if ([string]::IsNullOrWhiteSpace(
        [string]$dependencySnapshotPaths[$requiredId])) {
      throw "PulseCapture end-to-end dependency consumer is missing required identity: $requiredId"
    }
  }
  $frozenArtifactNaming =
    $dependencySnapshotPaths['common_artifact_naming']
  $frozenManifestVerifier =
    $dependencySnapshotPaths['common_verify_run_manifest']
  $frozenAdapter = $dependencySnapshotPaths['rf_analyzer_transport_simion_input_adapter']
  $frozenGrid2Materializer =
    $dependencySnapshotPaths['rf_simion_grid2_state_materializer']
  $frozenAnalyzer = $dependencySnapshotPaths['rf_analyzer_transport_analyzer']
  $frozenFormalReleaseValidator =
    $dependencySnapshotPaths['rf_oatof_formal_release_validator']
  $frozenGeometry = $dependencySnapshotPaths['oatof_resolved_geometry']
  $frozenBaseline = $dependencySnapshotPaths['oatof_baseline']
  $frozenFormalValidation =
    $dependencySnapshotPaths['oatof_formal_validation']
  $frozenStableEntry =
    $dependencySnapshotPaths['oatof_simion_stable_entry']
  $frozenProgramBuilder =
    $dependencySnapshotPaths['oatof_handoff_pulse_program_builder']
  $frozenFormalLua = $dependencySnapshotPaths['oatof_formal_lua']
  $frozenPulseExtension =
    $dependencySnapshotPaths['oatof_handoff_pulse_extension_lua']
  $frozenSolverDiagnostics =
    $dependencySnapshotPaths['oatof_solver_diagnostics']
  $frozenAcceleratorBuilder =
    $dependencyCompatibilityPaths['oatof_accelerator_simion_builder']
  $frozenAcceleratorGem =
    $dependencyCompatibilityPaths['oatof_accelerator_simion_gem']
  if ([string]::IsNullOrWhiteSpace($frozenAcceleratorBuilder) -or
      [string]::IsNullOrWhiteSpace($frozenAcceleratorGem)) {
    throw 'SIMION accelerator builder compatibility paths are missing.'
  }
  $frozenInterfaceComparator =
    $dependencySnapshotPaths['rf_simion_interface_transport_comparator']
  $frozenSharedJoint = $dependencySnapshotPaths['rf_shared_joint_geometry']
  . $dependencySnapshotPaths['common_resource_budget_support']
  $snapshotReady = $true
  Invoke-AnalyzerTransportSnapshotPython -Python $python -SnapshotRoot $snapshotRoot `
    -Arguments @($frozenArtifactNaming,'run',$RunId) `
    -FailureMessage 'PulseCapture end-to-end RunId failed frozen artifact naming.'

  $source = Resolve-RfDirectChildDirectory -ParentRoot $runsRoot `
    -ChildName $SourceRunId -Role 'SourceRunId'
  $sourceManifestOriginal = Join-Path $source 'run_manifest.json'
  $sourceManifestPath = Join-Path $package.input_dir 'source_run_manifest.json'
  $sourceManifestIdentity = Copy-RfStableFile -SourceRunRoot $source `
    -SourcePath $sourceManifestOriginal -Destination $sourceManifestPath `
    -Role 'source run manifest'
  Invoke-AnalyzerTransportSnapshotPython -Python $python -SnapshotRoot $snapshotRoot `
    -Arguments @(
      $frozenManifestVerifier,$sourceManifestPath,
      '--require-status','success','--require-run-id',$SourceRunId,
      '--require-project',$upstreamProjectId,
      '--require-mode',$expectedSourceMode
    ) -FailureMessage 'The frozen PulseCapture source run manifest is invalid.'
  $sourceManifest = Get-Content -LiteralPath $sourceManifestPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($sourceManifest.role -ne 'simulation_run_manifest' -or
      $sourceManifest.status -ne 'success' -or
      $sourceManifest.project -ne $upstreamProjectId -or
      $sourceManifest.mode -ne $expectedSourceMode -or
      $sourceManifest.run_id -ne $SourceRunId) {
    throw 'PulseCapture source manifest identity or role is invalid.'
  }

  $sourceConfigPath = Join-Path $package.input_dir 'source_run_config.json'
  $sourceConfigIdentity = Copy-RfManifestBoundFile -SourceRunRoot $source `
    -SourcePath ([string]$sourceManifest.run_config.path) `
    -Destination $sourceConfigPath -ManifestRecord $sourceManifest.run_config `
    -Role 'source run_config'
  $sourceConfig = Get-Content -LiteralPath $sourceConfigPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($sourceConfig.run_id -ne $SourceRunId -or
      $sourceConfig.project -ne $upstreamProjectId -or
      $sourceConfig.mode -ne $expectedSourceMode) {
    throw 'Downstream continuation requires the frozen PulseCapture shared-clock source.'
  }
  Assert-RfOatofSourceIdentityMatches `
    -Actual $(if ($interfaceDiagnostic) {
      $sourceConfig.source_particle_identity
    } else { $sourceConfig.upstream_source_identity }) `
    -Expected $runtime.source_identity `
    -Role 'Analyzer upstream particle source'
  $referencePulseRun = $null
  if ($interfaceDiagnostic) {
    $referencePulseRun = Resolve-RfDirectChildDirectory -ParentRoot $runsRoot `
      -ChildName $ReferencePulseCaptureRunId -Role 'ReferencePulseCaptureRunId'
    $referencePulseConfig = Get-Content -LiteralPath `
      (Join-Path $referencePulseRun 'run_config.json') -Raw -Encoding UTF8 |
      ConvertFrom-Json
    if ($referencePulseConfig.mode -ne 'rf_to_oatof_pulse_capture' -or
        $referencePulseConfig.parameters.connection_profile_id -ne
          $ExpectedConnectionProfileId) {
      throw 'Reference PulseCapture run identity differs.'
    }
    $pulseTimeUs = [double]$referencePulseConfig.parameters.pulse_time_us
    $pulseWidthUs = [double]$referencePulseConfig.parameters.pulse_width_us
  } else {
    $pulseTimeUs = [double]$sourceConfig.parameters.pulse_time_us
    $pulseWidthUs = [double]$sourceConfig.parameters.pulse_width_us
  }
  if (-not $interfaceDiagnostic -and
      [bool]$sourceConfig.parameters.pulse_capture_stage_passed) {
    throw 'Functional PulseCapture source must not claim qualified PulseCapture PASS.'
  }
  $connectionProfileId = [string]$sourceConfig.parameters.connection_profile_id
  if ($connectionProfileId -ne $ExpectedConnectionProfileId) {
    throw 'Analyzer source profile differs from the runtime binding.'
  }
  $budgetBinding = Initialize-RfIntegrationStageBudget `
    -ResolvedBudget $ResolvedEngineeringBudget -InputDir $package.input_dir `
    -ExpectedIntegrationId `
      'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' `
    -ExpectedConnectionProfileId $connectionProfileId `
    -StageId 'analyzer_transport' -Solver simion
  $resourceUsage = Join-Path $package.log_dir 'resource_usage.json'

  $sourceSummaryOriginal = Join-Path $source 'summary.json'
  $sourceSummaryRecord = Get-RfManifestOutputRecord -Manifest $sourceManifest `
    -ExpectedPath $sourceSummaryOriginal -Role 'source summary'
  $sourceSummary = Join-Path $package.input_dir 'source_summary.json'
  $sourceSummaryIdentity = Copy-RfManifestBoundFile -SourceRunRoot $source `
    -SourcePath $sourceSummaryOriginal -Destination $sourceSummary `
    -ManifestRecord $sourceSummaryRecord -Role 'source summary'
  $analysisSourceSummary = $sourceSummary
  if ($simionGrid2Replay) {
    $analysisSourceSummary = Join-Path $package.input_dir `
      'analyzer_source_summary.json'
    $simionSourceSummary = Get-Content -LiteralPath $sourceSummary `
      -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($simionSourceSummary.status -ne 'success' -or
        [int]$simionSourceSummary.census.local_accelerator_exit -le 0) {
      throw 'SIMION grid2 replay requires a successful non-empty interface result.'
    }
    Write-RfJson -Path $analysisSourceSummary -Value ([ordered]@{
      schema_version = 1
      role = 'rf_to_oatof_grid2_replay_source_summary'
      status = 'success'
      source_particles = [int]$simionSourceSummary.census.oatof_entry
      oatof_entry_crossings = [int]$simionSourceSummary.census.oatof_entry
      active_at_pulse = [int]$simionSourceSummary.census.local_accelerator_exit
      local_accelerator_exit = [int]$simionSourceSummary.census.local_accelerator_exit
      source_run_id = $SourceRunId
      source_solver = 'simion'
    })
  }
  $sourceCanonicalOriginal = Join-Path $source $(if ($interfaceDiagnostic) {
    'inputs\canonical_rf_exit_at_pre_pulse_connector.csv'
  } elseif ($simionGrid2Replay) {
    'results\simion_local_accelerator_exit.csv'
  } else { 'results\pulse_capture_local_accelerator_exit.csv' })
  $sourceCanonicalRecord = if ($interfaceDiagnostic) {
    $sourceManifest.inputs.particle_source
  } else {
    Get-RfManifestOutputRecord -Manifest $sourceManifest `
      -ExpectedPath $sourceCanonicalOriginal -Role "canonical $SourceEvent"
  }
  $sourceCanonical = Join-Path $package.input_dir 'source_canonical.csv'
  $sourceCanonicalIdentity = Copy-RfManifestBoundFile -SourceRunRoot $source `
    -SourcePath $sourceCanonicalOriginal -Destination $sourceCanonical `
    -ManifestRecord $sourceCanonicalRecord -Role "canonical $SourceEvent"
  $adapterSourceCanonical = $sourceCanonical
  $sourceCanonicalTemplate = $null
  if ($simionGrid2Replay) {
    $sourceCanonicalTemplateOriginal = Join-Path $source `
      'inputs\canonical_oatof_entry.csv'
    $sourceCanonicalTemplateRecord = Get-RfManifestOutputRecord `
      -Manifest $sourceManifest -ExpectedPath $sourceCanonicalTemplateOriginal `
      -Role 'SIMION grid2 canonical template'
    $sourceCanonicalTemplate = Join-Path $package.input_dir `
      'source_canonical_template.csv'
    Copy-RfManifestBoundFile -SourceRunRoot $source `
      -SourcePath $sourceCanonicalTemplateOriginal `
      -Destination $sourceCanonicalTemplate `
      -ManifestRecord $sourceCanonicalTemplateRecord `
      -Role 'SIMION grid2 canonical template' | Out-Null
    $adapterSourceCanonical = Join-Path $package.input_dir `
      'materialized_simion_local_accelerator_exit.csv'
    Invoke-AnalyzerTransportSnapshotPython -Python $python `
      -SnapshotRoot $snapshotRoot -Arguments @(
        $frozenGrid2Materializer,'--template',$sourceCanonicalTemplate,
        '--trace',$sourceCanonical,'--output',$adapterSourceCanonical
      ) -FailureMessage 'SIMION grid2 canonical materialization failed.'
  }

  $comsolReferenceExit = $null
  $referencePulseManifestPath = $null
  if ($interfaceDiagnostic) {
    $referenceManifestOriginal = Join-Path $referencePulseRun 'run_manifest.json'
    $referencePulseManifestPath = Join-Path $package.input_dir `
      'reference_pulse_capture_manifest.json'
    $referenceManifest = Get-Content -LiteralPath $referenceManifestOriginal `
      -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($referenceManifest.status -ne 'success' -or
        $referenceManifest.mode -ne 'rf_to_oatof_pulse_capture') {
      throw 'Reference PulseCapture manifest is not a successful current run.'
    }
    Copy-RfStableFile -SourceRunRoot $referencePulseRun `
      -SourcePath $referenceManifestOriginal `
      -Destination $referencePulseManifestPath `
      -Role 'reference PulseCapture manifest' | Out-Null
    $referenceExitOriginal = Join-Path $referencePulseRun `
      'results\pulse_capture_local_accelerator_exit.csv'
    $referenceExitRecord = Get-RfManifestOutputRecord -Manifest $referenceManifest `
      -ExpectedPath $referenceExitOriginal -Role 'reference COMSOL local exit'
    $comsolReferenceExit = Join-Path $package.input_dir `
      'reference_comsol_local_accelerator_exit.csv'
    Copy-RfManifestBoundFile -SourceRunRoot $referencePulseRun `
      -SourcePath $referenceExitOriginal -Destination $comsolReferenceExit `
      -ManifestRecord $referenceExitRecord -Role 'reference COMSOL local exit' |
      Out-Null
  }

  $runtimeDir = Join-Path $package.run_dir 'simion'
  $canonical = Join-Path $package.input_dir `
    "canonical_${SourceEvent}.csv"
  $ion = Join-Path $package.input_dir `
    "${SourceEvent}_instrument_clock.ion"
  $rowMap = Join-Path $package.input_dir 'row_map.csv'
  $adapterMetadata = Join-Path $package.input_dir `
    'simion_adapter_metadata.json'
  Invoke-AnalyzerTransportSnapshotPython -Python $python -SnapshotRoot $snapshotRoot `
    -Arguments @(
      $frozenAdapter,'--source',$adapterSourceCanonical,
      '--canonical-output',$canonical,'--ion-output',$ion,
      '--row-map-output',$rowMap,'--metadata-output',$adapterMetadata
    ) -FailureMessage 'Canonical-to-SIMION adapter failed.'
  $analyzerParticleCount = @(Import-Csv -LiteralPath $canonical).Count
  if ($analyzerParticleCount -lt 1) {
    throw 'Canonical analyzer input contains no particles.'
  }
  Complete-AnalyzerTransportStageTiming -Name 'runtime_snapshot_source_freeze_and_adapter'
  # SIMION 2020 constrains this UI default to at least 100. The explicit ION
  # file remains authoritative for the actual number of particles flown.
  $simionDefaultParticleCount = [Math]::Max(100, $analyzerParticleCount)

  $formalProjectRoot = Join-Path $workspaceRoot 'artifacts\projects\single_reflection_oa_tof_mass_analyzer'
  $formalRoot = Join-Path $formalProjectRoot 'formal'
  $formalDir = Join-Path $formalRoot 'simion'
  $formalAssetManifestOriginal = Join-Path $formalRoot 'asset_manifest.json'
  $formalAssetManifestPath = Join-Path $package.input_dir `
    'oatof_formal_asset_manifest.json'
  $formalAssetManifestIdentity = Copy-RfStableFile `
    -SourceRunRoot $formalProjectRoot `
    -SourcePath $formalAssetManifestOriginal `
    -Destination $formalAssetManifestPath `
    -Role 'oaTOF Formal asset manifest'
  $formalManifestOriginal = Join-Path $formalDir 'run_manifest.json'
  $formalManifestPath = Join-Path $package.input_dir `
    'oatof_formal_release_manifest.json'
  $formalManifestIdentity = Copy-RfStableFile -SourceRunRoot $formalDir `
    -SourcePath $formalManifestOriginal -Destination $formalManifestPath `
    -Role 'oaTOF Formal release manifest'
  Invoke-AnalyzerTransportSnapshotPython -Python $python -SnapshotRoot $snapshotRoot `
    -Arguments @(
      $frozenFormalReleaseValidator,
      '--asset-manifest',$formalAssetManifestPath,
      '--validation-contract',$frozenFormalValidation,
      '--delivery-manifest',$formalManifestPath,
      '--formal-root',$formalDir,
      '--stable-entry',$frozenStableEntry,
      '--baseline',$frozenBaseline,
      '--resolved-geometry',$frozenGeometry,
      '--formal-lua',$frozenFormalLua
    ) -FailureMessage 'The current oaTOF Formal analyzer release is invalid.'
  $formalAssetManifest = Get-Content -LiteralPath $formalAssetManifestPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $checksumOriginal = Join-Path $formalDir 'SHA256SUMS.csv'
  $checksumRecord = Get-AnalyzerTransportReleaseAssetRecord `
    -Manifest $formalAssetManifest `
    -ExpectedRelativePath 'simion/SHA256SUMS.csv' `
    -FormalProjectRoot $formalRoot
  $checksumPath = Join-Path $package.input_dir 'oatof_formal_SHA256SUMS.csv'
  $checksumIdentity = Copy-RfManifestBoundFile -SourceRunRoot $formalDir `
    -SourcePath $checksumOriginal -Destination $checksumPath `
    -ManifestRecord $checksumRecord -Role 'Formal SHA256SUMS'
  $formalAssetRecords = @(
    Get-AnalyzerTransportFormalAssetRecords -ChecksumPath $checksumPath `
      -FormalRoot $formalDir
  )
  $manifestIobRecord = Get-AnalyzerTransportReleaseAssetRecord `
    -Manifest $formalAssetManifest `
    -ExpectedRelativePath 'simion/oatof_ideal_grounded.iob' `
    -FormalProjectRoot $formalRoot
  $checksumIobRecord = @(
    $formalAssetRecords |
      Where-Object { $_.file -eq 'oatof_ideal_grounded.iob' }
  )[0]
  if ([long]$manifestIobRecord.bytes -ne [long]$checksumIobRecord.bytes -or
      [string]$manifestIobRecord.sha256 -ne [string]$checksumIobRecord.sha256) {
    throw 'oaTOF Formal IOB manifest and checksum identities differ.'
  }
  $formalAssetIdentities = @()
  foreach ($asset in $formalAssetRecords) {
    $assetPath = Join-Path $formalDir ([string]$asset.file)
    $assetRecord = Get-AnalyzerTransportReleaseAssetRecord `
      -Manifest $formalAssetManifest `
      -ExpectedRelativePath "simion/$([string]$asset.file)" `
      -FormalProjectRoot $formalRoot
    if ([long]$assetRecord.bytes -ne [long]$asset.bytes -or
        [string]$assetRecord.sha256 -ne
          ([string]$asset.sha256).ToUpperInvariant()) {
      throw "oaTOF Formal asset manifest and SHA256SUMS differ: $($asset.file)"
    }
    $formalAssetIdentities += Copy-RfManifestBoundFile `
      -SourceRunRoot $formalDir -SourcePath $assetPath `
      -Destination (Join-Path $runtimeDir ([string]$asset.file)) `
      -ManifestRecord $assetRecord `
      -Role "oaTOF compiled asset $($asset.file)"
  }
  $runtimeIob = Join-Path $runtimeDir 'oatof_ideal_grounded.iob'
  if (-not (Test-Path -LiteralPath $runtimeIob -PathType Leaf)) {
    throw 'Frozen oaTOF compiled IOB is missing.'
  }
  $runtimeProgram = Join-Path $runtimeDir 'oatof_ideal_grounded.lua'
  $programMetadata = Join-Path $package.input_dir 'pulse_program_build.json'
  Invoke-AnalyzerTransportSnapshotPython -Python $python -SnapshotRoot $snapshotRoot `
    -Arguments @(
      $frozenProgramBuilder,'--formal',$frozenFormalLua,
      '--extension',$frozenPulseExtension,'--output',$runtimeProgram,
      '--metadata',$programMetadata
    ) -FailureMessage 'Shared-clock oaTOF pulse program build failed.'
  Complete-AnalyzerTransportStageTiming -Name 'formal_release_validation_copy_and_program_build'

  $interfacePa0 = $null
  $interfacePaOutputs = @()
  if ($interfaceDiagnostic) {
    if ([string]::IsNullOrWhiteSpace($InterfacePaSourceRunId)) {
      $baselineDocument = Get-Content -LiteralPath $frozenGeometry -Raw -Encoding UTF8 |
        ConvertFrom-Json
      $jointDocument = Get-Content -LiteralPath $frozenSharedJoint -Raw -Encoding UTF8 |
        ConvertFrom-Json
      $geometry = $baselineDocument.geometry_mm
      $build = $baselineDocument.simion_geometry_build.accelerator
      $accelerator = $baselineDocument.geometry_derivation.accelerator
      $voltage = $baselineDocument.electrodes_V
      $port = $jointDocument.port_sweep
      $interfacePaRoot = if ([string]::IsNullOrWhiteSpace($InterfacePaDirectory)) {
        $runtimeDir
      } else {
        [IO.Path]::GetFullPath($InterfacePaDirectory)
      }
      New-Item -ItemType Directory -Path $interfacePaRoot -Force | Out-Null
      $interfacePaSharp = Join-Path $interfacePaRoot 'interface_accelerator.pa#'
      $interfaceBuildUsage = Join-Path $package.log_dir 'interface_pa_resource_usage.json'
      $interfaceBuildStdout = Join-Path $package.log_dir 'interface_pa.stdout.log'
      $interfaceBuildStderr = Join-Path $package.log_dir 'interface_pa.stderr.log'
      $interfacePa0 = Join-Path $interfacePaRoot 'interface_accelerator.pa0'
      if (-not (Test-Path -LiteralPath $interfacePa0 -PathType Leaf)) {
        $buildResult = Invoke-ResourceBudgetedProcess `
          -ResolvedBudgetPath $budgetBinding.stage_budget -RunDir $package.run_dir `
          -UsagePath $interfaceBuildUsage -FilePath $SimionExe `
          -WorkingDirectory $interfacePaRoot -RedirectStandardOutput $interfaceBuildStdout `
          -RedirectStandardError $interfaceBuildStderr -ArgumentList @(
          '--nogui','lua',$frozenAcceleratorBuilder,$frozenAcceleratorGem,
          $interfacePaSharp,([string]$build.cell_xy_mm),([string]$build.cell_z_mm),
          ([string]$geometry.accelerator_bore_half),
          ([string]$geometry.accelerator_ring_width),
          ([string]$geometry.accelerator_insulation_gap),
          ([string]$geometry.accelerator_rear_clearance),
          ([string]$geometry.accelerator_shield_wall),'0.5',
          ([string]$build.max_gib),([string]$build.back_domain_margin_mm),
          ([string]$build.front_domain_margin_mm),([string]$build.grid_phase_z_mm),
          ([string]$accelerator.d1_mm),([string]$accelerator.d2_mm),
          ([string]$baselineDocument.rings.accelerator_count),
          ([string]$geometry.accelerator_repeller_thickness),
          ([string]$geometry.accelerator_ring_thickness),
          ([string]$geometry.accelerator_front_vacuum_margin),
          ([string]$voltage.repeller),([string]$voltage.grid1),'1',
          ([string]$port.selected_n100_candidate_full_width_y_mm),
          ([string]$port.full_height_z_mm),
          ([string]($accelerator.d1_mm / 2.0))
          )
        if ($buildResult.exit_code -ne 0) {
          throw "SIMION interface PA build failed: $interfaceBuildStderr"
        }
      }
      $interfacePaOutputs = @(Get-ChildItem -LiteralPath $interfacePaRoot -File |
        Where-Object { $_.Name -like 'interface_accelerator.pa*' } |
        ForEach-Object { $_.FullName })
    } else {
      $paRun = Resolve-RfDirectChildDirectory -ParentRoot $runsRoot `
        -ChildName $InterfacePaSourceRunId -Role 'InterfacePaSourceRunId'
      $paManifest = Get-Content -LiteralPath (Join-Path $paRun 'run_manifest.json') `
        -Raw -Encoding UTF8 | ConvertFrom-Json
      $records = @($paManifest.outputs | Where-Object {
        [IO.Path]::GetFileName([string]$_.path) -like 'interface_accelerator.pa*'
      })
      if ($paManifest.status -ne 'success' -or $records.Count -lt 3) {
        throw 'Reusable interface PA run is unsuccessful or incomplete.'
      }
      foreach ($record in $records) {
        $sourcePa = [IO.Path]::GetFullPath([string]$record.path)
        $targetPa = Join-Path $runtimeDir ([IO.Path]::GetFileName($sourcePa))
        Copy-RfManifestBoundFile -SourceRunRoot $paRun -SourcePath $sourcePa `
          -Destination $targetPa -ManifestRecord $record -Role 'reused interface PA' |
          Out-Null
        $interfacePaOutputs += $targetPa
      }
      $interfacePa0 = Join-Path $runtimeDir 'interface_accelerator.pa0'
    }
    if (-not (Test-Path -LiteralPath $interfacePa0 -PathType Leaf)) {
      throw 'SIMION interface accelerator PA0 is absent.'
    }
  }
  Complete-AnalyzerTransportStageTiming -Name 'interface_pa_prepare'

  $sourceIdentity = [ordered]@{
    run_id = $SourceRunId
    manifest_sha256 = $sourceManifestIdentity.sha256
    run_config_sha256 = $sourceConfigIdentity.sha256
    summary_sha256 = $sourceSummaryIdentity.sha256
    canonical_local_exit_sha256 = $sourceCanonicalIdentity.sha256
  }
  $runConfiguration = [ordered]@{
    schema_version = 2
    run_id = $RunId
    project = $upstreamProjectId
    mode = $runMode
    project_root = $repoRoot
    inputs = [ordered]@{
      runner = $runner
      run_artifact_support = $support
      runtime_binding = $runtimeBindingFrozen
      resolved_connection = $resolvedConnectionFrozen
      resolved_source_contract = $resolvedSourceContractFrozen
      upstream_resolved_design = $upstreamResolvedDesignFrozen
      code_inventory = $dependencyContract
      dependency_contract = $dependencyPublication.dependency_contract_path
      source_run_manifest = $sourceManifestPath
      source_run_config = $sourceConfigPath
      resolved_integration_engineering_budget = $budgetBinding.frozen_budget
      resolved_stage_resource_budget = $budgetBinding.stage_budget
      source_summary = $sourceSummary
      analyzer_source_summary = $analysisSourceSummary
      source_canonical = $sourceCanonical
      analyzer_source_canonical = $adapterSourceCanonical
      canonical = $canonical
      ion = $ion
      row_map = $rowMap
      adapter_metadata = $adapterMetadata
      oatof_resolved_geometry = $frozenGeometry
      oatof_baseline = $frozenBaseline
      pulse_program = $runtimeProgram
      pulse_program_metadata = $programMetadata
      oatof_formal_asset_manifest = $formalAssetManifestPath
      oatof_formal_validation = $frozenFormalValidation
      oatof_simion_stable_entry = $frozenStableEntry
      oatof_formal_release_manifest = $formalManifestPath
      oatof_formal_sha256sums = $checksumPath
    }
    dependency_identities = $dependencyIdentities
    resource_budget_identity = [ordered]@{
      resolved_budget_sha256 = $budgetBinding.resolved_budget_sha256
      stage_budget_sha256 = $budgetBinding.stage_budget_sha256
    }
    source_run_identity = $sourceIdentity
    upstream_source_identity = $runtime.source_identity
    run_local_identity = [ordered]@{
      runner_sha256 = $runnerIdentity.sha256
      support_sha256 = $supportIdentity.sha256
      formal_asset_manifest_sha256 = $formalAssetManifestIdentity.sha256
      formal_manifest_sha256 = $formalManifestIdentity.sha256
      formal_checksum_sha256 = $checksumIdentity.sha256
    }
    compiled_asset_identities = @(
      $formalAssetIdentities | ForEach-Object {
        [ordered]@{
          role = $_.role
          frozen_path = $_.frozen_path
          bytes = $_.bytes
          sha256 = $_.sha256
        }
      }
    )
    parameters = [ordered]@{
      source_run_id = $SourceRunId
      source_event = $SourceEvent
      reference_pulse_capture_run_id = $ReferencePulseCaptureRunId
      connection_profile_id = $connectionProfileId
      source_branch_id = $runtime.source_branch_id
      authoritative_frame_id = 'oatof_global'
      solver_clock = 'instrument_time'
      position_projection_applied = $false
      pulse_time_us = $pulseTimeUs
      pulse_width_us = $pulseWidthUs
      analyzer_particle_count = $analyzerParticleCount
      simion_default_particle_count = $simionDefaultParticleCount
      dense_trajectories_saved = $false
      pulse_capture_stage_passed = $false
    }
    artifact_retention = [ordered]@{
      policy_version = 1
      class = 'compact'
      reason = $null
    }
    formal_gate_passed = $false
  }
  if ($interfaceDiagnostic) {
    $runConfiguration.inputs.reference_pulse_capture_manifest =
      $referencePulseManifestPath
    $runConfiguration.inputs.reference_comsol_local_accelerator_exit =
      $comsolReferenceExit
    $runConfiguration.parameters.interface_pa_source_run_id =
      $InterfacePaSourceRunId
    $runConfiguration.parameters.interface_pa_sha256 =
      (Get-FileHash -LiteralPath $interfacePa0 -Algorithm SHA256).Hash
    $runConfiguration.parameters.interface_port_mode =
      'real_rectangular_side_port'
  } elseif ($simionGrid2Replay) {
    $runConfiguration.inputs.source_canonical_template =
      $sourceCanonicalTemplate
    $runConfiguration.parameters.grid2_source_solver = 'simion'
  }
  Write-RfJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  Write-RfJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1
    role = if ($interfaceDiagnostic) {
      'rf_to_oatof_simion_interface_transport_summary'
    } else { 'rf_to_oatof_analyzer_transport_summary' }
    status = 'interrupted'
    reason = 'Frozen inputs recorded; SIMION continuation not yet complete.'
  })
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $manifestToolRoot `
    -RunConfig $package.run_config -Status interrupted -Software $software
  Complete-AnalyzerTransportStageTiming -Name 'run_configuration_publication'

  $stdout = Join-Path $package.log_dir 'simion.stdout.log'
  $stderr = Join-Path $package.log_dir 'simion.stderr.log'
  $oldAcceleratorOverride = $env:OATOF_ACCELERATOR_PA_OVERRIDE
  try {
    if ($interfaceDiagnostic) {
      $env:OATOF_ACCELERATOR_PA_OVERRIDE = $interfacePa0
    }
    $processResult = Invoke-ResourceBudgetedProcess `
      -ResolvedBudgetPath $budgetBinding.stage_budget `
      -RunDir $package.run_dir -UsagePath $resourceUsage `
      -FilePath $SimionExe -WorkingDirectory $runtimeDir `
      -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
      -ArgumentList @(
      '--default-num-particles',([string]$simionDefaultParticleCount),'--nogui','fly',
      '--trajectory-quality','8','--retain-trajectories','0',
      '--particles',$ion,'--programs','1',
      '--adjustable','trajectory_quality=8',
      '--adjustable','trajectory_log_enable=1',
      '--adjustable','diagnostic_max_tof_us=90',
      '--adjustable','handoff_pulse_mode=1',
      '--adjustable',("handoff_pulse_time_us={0:R}" -f $pulseTimeUs),
      '--adjustable',("handoff_pulse_width_us={0:R}" -f $pulseWidthUs),
        $runtimeIob
      )
  } finally {
    $env:OATOF_ACCELERATOR_PA_OVERRIDE = $oldAcceleratorOverride
  }
  if ($processResult.resource_budget_exceeded) {
    $resourceBudgetExceeded = $true
    throw "SIMION downstream resource budget exceeded: $($processResult.limit_name)"
  }
  if ($processResult.exit_code -ne 0) {
    throw "SIMION downstream continuation failed: $stderr"
  }
  Complete-AnalyzerTransportStageTiming -Name 'simion_particle_flight'
  $downstream = Join-Path $package.result_dir `
    'simion_downstream_particles.csv'
  Invoke-AnalyzerTransportSnapshotPython -Python $python -SnapshotRoot $snapshotRoot `
    -Arguments @(
      $frozenSolverDiagnostics,'analyze-simion-log',
      '--log',$stdout,'--ion-file',$ion,
      '--mode','rf_oatof_analyzer_transport',
      '--distribution','pulse_capture_local_accelerator_exit',
      '--particle-csv',$downstream,'--allow-incomplete-census'
    ) -FailureMessage 'Frozen SIMION log analysis failed.'

  $metrics = Join-Path $package.result_dir $(if ($interfaceDiagnostic) {
    'simion_comsol_interface_transport_comparison.json'
  } else { 'analyzer_transport_metrics.json' })
  $figure = $null
  $simionExit = $null
  if ($interfaceDiagnostic) {
    $simionExit = Join-Path $package.result_dir `
      'simion_local_accelerator_exit.csv'
    Invoke-AnalyzerTransportSnapshotPython -Python $python `
      -SnapshotRoot $snapshotRoot -Arguments @(
        $frozenInterfaceComparator,'--log',$stdout,'--row-map',$rowMap,
        '--canonical-input',$canonical,'--comsol-exit',$comsolReferenceExit,
        '--output',$metrics,'--simion-exit',$simionExit
      ) -FailureMessage 'SIMION/COMSOL interface transport comparison failed.'
  } else {
    $figure = Join-Path $package.result_dir `
      'analyzer_transport_functional_chain.png'
    Invoke-AnalyzerTransportSnapshotPython -Python $python -SnapshotRoot $snapshotRoot `
      -Arguments @(
        $frozenAnalyzer,'--source-summary',$analysisSourceSummary,
        '--canonical',$canonical,'--ion',$ion,'--row-map',$rowMap,
        '--downstream',$downstream,'--stdout',$stdout,
        '--pulse-time-us',([string]$pulseTimeUs),
        '--pulse-width-us',([string]$pulseWidthUs),
        '--geometry-contract',$frozenGeometry,
        '--output',$metrics,'--figure',$figure
      ) -FailureMessage 'PulseCapture end-to-end functional audit failed.'
  }
  $result = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $runConfiguration.parameters.particle_count = if ($interfaceDiagnostic) {
    [int]$result.simion.particles
  } else { [int]$result.census.local_accelerator_exit }
  Write-RfJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  Write-RfJson -Path $package.summary -Depth 8 -Value ([ordered]@{
    schema_version = 1
    role = if ($interfaceDiagnostic) {
      'rf_to_oatof_simion_interface_transport_summary'
    } else { 'rf_to_oatof_analyzer_transport_summary' }
    status = 'success'
    functional_audit = $result.status
    census = if ($interfaceDiagnostic) { [ordered]@{
      oatof_entry = [int]$result.source_particles
      local_accelerator_exit = [int]$result.simion.particles
    } } else { $result.census }
    source_run_id = $SourceRunId
    figure = if ($interfaceDiagnostic) { $null } else {
      'results/analyzer_transport_functional_chain.png'
    }
    pulse_capture_stage_passed = $false
    resolution_claim_allowed = $false
    formal_gate_passed = $false
  })
  Complete-AnalyzerTransportStageTiming -Name 'solver_log_analysis_and_comparison'
  $stageTimings.total_through_results =
    [math]::Round($totalTimer.Elapsed.TotalSeconds, 3)
  Write-RfJson -Path $stageTimingPath -Depth 4 -Value ([ordered]@{
    schema_version = 1
    role = 'rf_to_oatof_analyzer_transport_stage_timings'
    units = 'seconds'
    stages = $stageTimings
  })
  $outputs = @(
    $canonical,$ion,$rowMap,$adapterMetadata,$programMetadata,$runtimeProgram,
    $downstream,$metrics,$figure,$simionExit,$stdout,$stderr,$resourceUsage,
    $stageTimingPath,$package.summary
  )
  $retentionActions = Apply-RunArtifactRetention -Python $python `
    -RepoRoot $manifestToolRoot -RunConfig $package.run_config
  $outputs = @($outputs | Where-Object {
    -not [string]::IsNullOrWhiteSpace([string]$_) -and
    (Test-Path -LiteralPath $_ -PathType Leaf)
  })
  $outputs += $retentionActions
  if (-not (Complete-ResourceUsage `
      -ResolvedBudgetPath $budgetBinding.stage_budget `
      -RunDir $package.run_dir -UsagePath $resourceUsage)) {
    $resourceBudgetExceeded = $true
    throw 'SIMION analyzer compact final retained-byte budget exceeded.'
  }
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $manifestToolRoot `
    -RunConfig $package.run_config -Status success -Software $software `
    -Outputs $outputs
  if ($interfaceDiagnostic) {
    Write-Output (
      "SIMION_INTERFACE_TRANSPORT=PASS RUN_ID=$RunId " +
      "LOCAL_EXIT=$($result.simion.particles)/$($result.source_particles)"
    )
  } else {
    Write-Output (
      "ANALYZER_TRANSPORT=PASS RUN_ID=$RunId " +
      "HITS=$($result.census.detector_hit)/" +
      "$($result.census.local_accelerator_exit)"
    )
  }
} catch {
  if ($snapshotReady) {
    Complete-RfFrozenFailedRun -Python $python `
      -FrozenRepoRoot $manifestToolRoot `
      -RunConfig $package.run_config -Summary $package.summary `
      -SummaryRole $(if ($interfaceDiagnostic) {
        'rf_to_oatof_simion_interface_transport_summary'
      } else { 'rf_to_oatof_analyzer_transport_summary' }) `
      -Reason $_.Exception.Message -Software $software `
      -Status $(if ($resourceBudgetExceeded) { 'interrupted' } else { 'failed' }) `
      -FailureClass $(if ($resourceBudgetExceeded) {
        'resource_budget_exceeded'
      } else { '' }) `
      -ResourceUsagePath $(if ($resourceBudgetExceeded) {
        $resourceUsage
      } else { '' })
  } else {
    Write-RfJson -Path $package.summary -Value ([ordered]@{
      schema_version = 1
      role = if ($interfaceDiagnostic) {
        'rf_to_oatof_simion_interface_transport_summary'
      } else { 'rf_to_oatof_analyzer_transport_summary' }
      status = 'failed'
      reason = $_.Exception.Message
      manifest_written = $false
    })
  }
  throw
}
