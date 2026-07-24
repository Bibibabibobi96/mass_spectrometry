[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$SourceRunId,
  [Parameter(Mandatory)][string]$RunId,
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$python = if ($PythonExe) {
  [IO.Path]::GetFullPath($PythonExe)
} else {
  Join-Path $repoRoot '.venv\Scripts\python.exe'
}
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$supportSource = Join-Path $projectRoot 'tests\support\rf_run_artifact_support.ps1'
. $supportSource

function Invoke-S3EndToEndSnapshotPython {
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

function Get-S3FormalAssetRecords {
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

$software = @('COMSOL 6.4','SIMION 2020','Python 3.11')
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
  throw "Run Python environment is missing: $python"
}
if ([string]::IsNullOrWhiteSpace($RunId) -or
    [IO.Path]::IsPathRooted($RunId) -or
    $RunId.IndexOfAny([char[]]@('\','/')) -ge 0 -or
    $RunId -in @('.','..')) {
  throw 'RunId must be a direct-child artifact name.'
}
$runsRoot = Join-Path $artifactRoot 'runs'
$runDir = [IO.Path]::GetFullPath((Join-Path $runsRoot $RunId))
$fullRunsRoot = [IO.Path]::GetFullPath($runsRoot)
if (-not (Split-Path -Parent $runDir).Equals(
    $fullRunsRoot, [StringComparison]::OrdinalIgnoreCase)) {
  throw 'RunId escapes the project run directory.'
}
if (Test-Path -LiteralPath $runDir) {
  throw "Run already exists: $runDir"
}
$package = [pscustomobject]@{
  python = $python
  run_dir = $runDir
  input_dir = Join-Path $runDir 'inputs'
  result_dir = Join-Path $runDir 'results'
  log_dir = Join-Path $runDir 'logs'
  run_config = Join-Path $runDir 'run_config.json'
  summary = Join-Path $runDir 'summary.json'
}
New-Item -ItemType Directory -Force -Path @(
  $package.input_dir,$package.result_dir,$package.log_dir
) | Out-Null
Write-RfJson -Path $package.run_config -Value ([ordered]@{
  schema_version = 1
  run_id = $RunId
  project = 'rf_quadrupole_collision_cooling'
  mode = 'rf_to_oatof_s3_cumulative_end_to_end'
  project_root = $repoRoot
  inputs = [ordered]@{}
  parameters = [ordered]@{ lifecycle_stage = 'bootstrap_before_snapshot' }
  formal_gate_passed = $false
})
Write-RfJson -Path $package.summary -Value ([ordered]@{
  schema_version = 1
  role = 'rf_oatof_s3_cumulative_end_to_end_summary'
  status = 'interrupted'
  reason = 'Run directory initialized; dependency snapshot not yet complete.'
})
$snapshotRoot = Join-Path $package.input_dir 'runtime_snapshot'
$manifestToolRoot = $snapshotRoot
$snapshotReady = $false

try {
  if (-not (Test-Path -LiteralPath $SimionExe -PathType Leaf)) {
    throw "SIMION is missing: $SimionExe"
  }

  $runner = Join-Path $package.input_dir 'run_s3_end_to_end.ps1.txt'
  $support = Join-Path $package.input_dir 'rf_run_artifact_support.ps1.txt'
  $runnerIdentity = Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath $PSCommandPath -Destination $runner -Role 'end-to-end runner'
  $supportIdentity = Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath $supportSource -Destination $support -Role 'run artifact support'

  $dependencyContractSource = Join-Path $projectRoot `
    'config\rf_to_oatof_s2_dependencies.json'
  $dependencyContract = Join-Path $snapshotRoot `
    'projects\rf_quadrupole_collision_cooling\config\rf_to_oatof_s2_dependencies.json'
  $dependencyContractIdentity = Copy-RfStableFile -SourceRunRoot $repoRoot `
    -SourcePath $dependencyContractSource -Destination $dependencyContract `
    -Role 'dependency contract'
  $dependencyDocument = Get-Content -LiteralPath $dependencyContract `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $dependencyConsumer = 's3_end_to_end'
  if (@($dependencyDocument.consumer_ids) -notcontains $dependencyConsumer) {
    throw "S3 dependency consumer is not declared: $dependencyConsumer"
  }
  $selectedDependencies = @(
    $dependencyDocument.dependencies |
      Where-Object { @($_.consumers) -contains $dependencyConsumer }
  )
  if ($selectedDependencies.Count -eq 0 -or
      @($selectedDependencies.id | Select-Object -Unique).Count -ne
        $selectedDependencies.Count) {
    throw 'S3 end-to-end dependency subset is empty or has duplicate identities.'
  }
  $dependencyIdentities = [ordered]@{}
  $dependencySnapshotPaths = @{}
  $dependencyCompatibilityPaths = @{}
  foreach ($dependency in $selectedDependencies) {
    if ([string]$dependency.id -eq 'rf_dependency_contract_snapshot') {
      $expectedSource = (
        'projects/rf_quadrupole_collision_cooling/' +
        'config/rf_to_oatof_s2_dependencies.json'
      )
      $expectedFrozen = (
        'runtime_snapshot/projects/rf_quadrupole_collision_cooling/' +
        'config/rf_to_oatof_s2_dependencies.json'
      )
      $declaredSnapshot = [IO.Path]::GetFullPath(
        (Join-Path $package.input_dir ([string]$dependency.frozen_filename))
      )
      if ([string]$dependency.provider_scope -ne 'project' -or
          [string]$dependency.provider_project -ne
            'rf_quadrupole_collision_cooling' -or
          [string]$dependency.provider_repo_path -ne
            'projects/rf_quadrupole_collision_cooling' -or
          [string]$dependency.source_repo_path -ne $expectedSource -or
          [string]$dependency.frozen_filename -ne $expectedFrozen -or
          -not $declaredSnapshot.Equals(
            [IO.Path]::GetFullPath($dependencyContract),
            [StringComparison]::OrdinalIgnoreCase
          ) -or
          (Get-FileHash -LiteralPath $dependencyContract -Algorithm SHA256).Hash -ne
            $dependencyContractIdentity.sha256) {
        throw 'Frozen S3 dependency-contract self identity differs.'
      }
      $identity = [pscustomobject]@{
        id = [string]$dependency.id
        provider_scope = [string]$dependency.provider_scope
        provider_project = [string]$dependency.provider_project
        provider_repo_path = (
          [string]$dependency.provider_repo_path
        ).Replace('\','/')
        source_repo_path = (
          [string]$dependency.source_repo_path
        ).Replace('\','/')
        frozen_input_name = [string]$dependency.run_input_name
        consumers = @($dependency.consumers)
        frozen_path = $dependencyContract
        snapshot_path = $dependencyContract
        compatibility_path = $null
        sha256 = $dependencyContractIdentity.sha256
      }
    } else {
      $identity = Copy-RfFrozenDependency -RepoRoot $repoRoot `
        -InputDir $package.input_dir -Dependency $dependency
    }
    if ((Get-FileHash -LiteralPath $identity.snapshot_path -Algorithm SHA256).Hash -ne
        $identity.sha256) {
      throw "S3 end-to-end dependency snapshot identity differs: $($identity.id)"
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
    'rf_dependency_contract_snapshot',
    'rf_s3_simion_input_adapter','rf_s3_end_to_end_analyzer',
    'rf_oatof_handoff_builder',
    'oatof_resolved_geometry','oatof_handoff_pulse_program_builder',
    'oatof_formal_lua','oatof_handoff_pulse_extension_lua',
    'oatof_simion_log_analyzer_wrapper','oatof_solver_diagnostics',
    'common_rigid_transform','common_particle_physics',
    'common_component_particle_state','common_component_particle_state_schema',
    'common_file_identity','common_verify_run_manifest',
    'common_artifact_naming','common_write_run_manifest',
    'common_run_artifact_support','common_require_powershell7'
  )
  foreach ($requiredId in $requiredSnapshotIds) {
    if ([string]::IsNullOrWhiteSpace(
        [string]$dependencySnapshotPaths[$requiredId])) {
      throw "S3 end-to-end dependency consumer is missing required identity: $requiredId"
    }
  }
  $frozenArtifactNaming =
    $dependencySnapshotPaths['common_artifact_naming']
  $frozenManifestVerifier =
    $dependencySnapshotPaths['common_verify_run_manifest']
  $frozenAdapter = $dependencySnapshotPaths['rf_s3_simion_input_adapter']
  $frozenAnalyzer = $dependencySnapshotPaths['rf_s3_end_to_end_analyzer']
  $frozenGeometry = $dependencySnapshotPaths['oatof_resolved_geometry']
  $frozenProgramBuilder =
    $dependencySnapshotPaths['oatof_handoff_pulse_program_builder']
  $frozenFormalLua = $dependencySnapshotPaths['oatof_formal_lua']
  $frozenPulseExtension =
    $dependencySnapshotPaths['oatof_handoff_pulse_extension_lua']
  $frozenSolverDiagnostics =
    $dependencySnapshotPaths['oatof_solver_diagnostics']
  $snapshotReady = $true
  Invoke-S3EndToEndSnapshotPython -Python $python -SnapshotRoot $snapshotRoot `
    -Arguments @($frozenArtifactNaming,'run',$RunId) `
    -FailureMessage 'S3 end-to-end RunId failed frozen artifact naming.'

  $source = Resolve-RfDirectChildDirectory -ParentRoot $runsRoot `
    -ChildName $SourceRunId -Role 'SourceRunId'
  $sourceManifestOriginal = Join-Path $source 'run_manifest.json'
  $sourceManifestPath = Join-Path $package.input_dir 'source_run_manifest.json'
  $sourceManifestIdentity = Copy-RfStableFile -SourceRunRoot $source `
    -SourcePath $sourceManifestOriginal -Destination $sourceManifestPath `
    -Role 'source run manifest'
  Invoke-S3EndToEndSnapshotPython -Python $python -SnapshotRoot $snapshotRoot `
    -Arguments @(
      $frozenManifestVerifier,$sourceManifestPath,
      '--require-status','success','--require-run-id',$SourceRunId,
      '--require-project','rf_quadrupole_collision_cooling',
      '--require-mode','rf_to_oatof_s3_shared_clock_pulse_capture_n100'
    ) -FailureMessage 'The frozen S3 source run manifest is invalid.'
  $sourceManifest = Get-Content -LiteralPath $sourceManifestPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($sourceManifest.role -ne 'simulation_run_manifest' -or
      $sourceManifest.status -ne 'success' -or
      $sourceManifest.project -ne 'rf_quadrupole_collision_cooling' -or
      $sourceManifest.mode -ne
        'rf_to_oatof_s3_shared_clock_pulse_capture_n100' -or
      $sourceManifest.run_id -ne $SourceRunId) {
    throw 'S3 source manifest identity or role is invalid.'
  }

  $sourceConfigPath = Join-Path $package.input_dir 'source_run_config.json'
  $sourceConfigIdentity = Copy-RfManifestBoundFile -SourceRunRoot $source `
    -SourcePath ([string]$sourceManifest.run_config.path) `
    -Destination $sourceConfigPath -ManifestRecord $sourceManifest.run_config `
    -Role 'source run_config'
  $sourceConfig = Get-Content -LiteralPath $sourceConfigPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($sourceConfig.run_id -ne $SourceRunId -or
      $sourceConfig.project -ne 'rf_quadrupole_collision_cooling' -or
      $sourceConfig.mode -ne
        'rf_to_oatof_s3_shared_clock_pulse_capture_n100') {
    throw 'Downstream continuation requires the frozen S3 shared-clock source.'
  }
  $pulseTimeUs = [double]$sourceConfig.parameters.pulse_time_us
  $pulseWidthUs = [double]$sourceConfig.parameters.pulse_width_us
  if ([bool]$sourceConfig.parameters.s3_stage_passed) {
    throw 'Functional S3 source must not claim qualified S3 PASS.'
  }

  $sourceSummaryOriginal = Join-Path $source 'summary.json'
  $sourceSummaryRecord = Get-RfManifestOutputRecord -Manifest $sourceManifest `
    -ExpectedPath $sourceSummaryOriginal -Role 'source summary'
  $sourceSummary = Join-Path $package.input_dir 'source_summary.json'
  $sourceSummaryIdentity = Copy-RfManifestBoundFile -SourceRunRoot $source `
    -SourcePath $sourceSummaryOriginal -Destination $sourceSummary `
    -ManifestRecord $sourceSummaryRecord -Role 'source summary'
  $sourceCanonicalOriginal = Join-Path $source `
    'results\s3_local_accelerator_exit.csv'
  $sourceCanonicalRecord = Get-RfManifestOutputRecord -Manifest $sourceManifest `
    -ExpectedPath $sourceCanonicalOriginal -Role 'canonical local exit'
  $sourceCanonical = Join-Path $package.input_dir 'source_canonical.csv'
  $sourceCanonicalIdentity = Copy-RfManifestBoundFile -SourceRunRoot $source `
    -SourcePath $sourceCanonicalOriginal -Destination $sourceCanonical `
    -ManifestRecord $sourceCanonicalRecord -Role 'canonical local exit'

  $runtimeDir = Join-Path $package.run_dir 'simion'
  New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
  $canonical = Join-Path $package.input_dir `
    'canonical_local_accelerator_exit.csv'
  $ion = Join-Path $package.input_dir `
    'local_accelerator_exit_instrument_clock.ion'
  $rowMap = Join-Path $package.input_dir 'row_map.csv'
  $adapterMetadata = Join-Path $package.input_dir `
    'simion_adapter_metadata.json'
  Invoke-S3EndToEndSnapshotPython -Python $python -SnapshotRoot $snapshotRoot `
    -Arguments @(
      $frozenAdapter,'--source',$sourceCanonical,
      '--canonical-output',$canonical,'--ion-output',$ion,
      '--row-map-output',$rowMap,'--metadata-output',$adapterMetadata
    ) -FailureMessage 'Canonical-to-SIMION adapter failed.'

  $formalDir = Join-Path $workspaceRoot `
    'artifacts\projects\oa_tof\formal\simion'
  $formalManifestOriginal = Join-Path $formalDir 'run_manifest.json'
  $formalManifestPath = Join-Path $package.input_dir `
    'oatof_formal_release_manifest.json'
  $formalManifestIdentity = Copy-RfStableFile -SourceRunRoot $formalDir `
    -SourcePath $formalManifestOriginal -Destination $formalManifestPath `
    -Role 'oaTOF Formal release manifest'
  Invoke-S3EndToEndSnapshotPython -Python $python -SnapshotRoot $snapshotRoot `
    -Arguments @(
      $frozenManifestVerifier,$formalManifestPath,
      '--require-status','success',
      '--require-run-id',
      '20260720_204500__build__simion__coupled-formal-delivery__n1000',
      '--require-project','oa_tof','--require-mode','formal_delivery'
    ) -FailureMessage 'The frozen oaTOF Formal release manifest is invalid.'
  $formalManifest = Get-Content -LiteralPath $formalManifestPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  $checksumOriginal = Join-Path $formalDir 'SHA256SUMS.csv'
  $checksumRecord = Get-RfManifestOutputRecord -Manifest $formalManifest `
    -ExpectedPath $checksumOriginal -Role 'Formal SHA256SUMS'
  $checksumPath = Join-Path $package.input_dir 'oatof_formal_SHA256SUMS.csv'
  $checksumIdentity = Copy-RfManifestBoundFile -SourceRunRoot $formalDir `
    -SourcePath $checksumOriginal -Destination $checksumPath `
    -ManifestRecord $checksumRecord -Role 'Formal SHA256SUMS'
  $formalAssetRecords = @(
    Get-S3FormalAssetRecords -ChecksumPath $checksumPath `
      -FormalRoot $formalDir
  )
  $manifestIobRecord = Get-RfManifestOutputRecord -Manifest $formalManifest `
    -ExpectedPath (Join-Path $formalDir 'oatof_ideal_grounded.iob') `
    -Role 'Formal IOB'
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
    $assetRecord = [pscustomobject]@{
      path = $assetPath
      exists = $true
      bytes = [long]$asset.bytes
      sha256 = ([string]$asset.sha256).ToUpperInvariant()
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
  Invoke-S3EndToEndSnapshotPython -Python $python -SnapshotRoot $snapshotRoot `
    -Arguments @(
      $frozenProgramBuilder,'--formal',$frozenFormalLua,
      '--extension',$frozenPulseExtension,'--output',$runtimeProgram,
      '--metadata',$programMetadata
    ) -FailureMessage 'Shared-clock oaTOF pulse program build failed.'

  $sourceIdentity = [ordered]@{
    run_id = $SourceRunId
    manifest_sha256 = $sourceManifestIdentity.sha256
    run_config_sha256 = $sourceConfigIdentity.sha256
    summary_sha256 = $sourceSummaryIdentity.sha256
    canonical_local_exit_sha256 = $sourceCanonicalIdentity.sha256
  }
  $runConfiguration = [ordered]@{
    schema_version = 1
    run_id = $RunId
    project = 'rf_quadrupole_collision_cooling'
    mode = 'rf_to_oatof_s3_cumulative_end_to_end'
    project_root = $repoRoot
    inputs = [ordered]@{
      runner = $runner
      run_artifact_support = $support
      dependency_contract = $dependencyContract
      source_run_manifest = $sourceManifestPath
      source_run_config = $sourceConfigPath
      source_summary = $sourceSummary
      source_canonical = $sourceCanonical
      canonical = $canonical
      ion = $ion
      row_map = $rowMap
      adapter_metadata = $adapterMetadata
      oatof_resolved_geometry = $frozenGeometry
      pulse_program = $runtimeProgram
      pulse_program_metadata = $programMetadata
      oatof_formal_release_manifest = $formalManifestPath
      oatof_formal_sha256sums = $checksumPath
    }
    dependency_identities = $dependencyIdentities
    source_run_identity = $sourceIdentity
    run_local_identity = [ordered]@{
      runner_sha256 = $runnerIdentity.sha256
      support_sha256 = $supportIdentity.sha256
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
      authoritative_frame_id = 'oatof_global'
      solver_clock = 'instrument_time'
      position_projection_applied = $false
      pulse_time_us = $pulseTimeUs
      pulse_width_us = $pulseWidthUs
      dense_trajectories_saved = $false
      s3_stage_passed = $false
    }
    formal_gate_passed = $false
  }
  Write-RfJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  Write-RfJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1
    role = 'rf_oatof_s3_cumulative_end_to_end_summary'
    status = 'interrupted'
    reason = 'Frozen inputs recorded; SIMION continuation not yet complete.'
  })
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $manifestToolRoot `
    -RunConfig $package.run_config -Status interrupted -Software $software

  $stdout = Join-Path $package.log_dir 'simion.stdout.log'
  $stderr = Join-Path $package.log_dir 'simion.stderr.log'
  $process = Start-Process -FilePath $SimionExe `
    -WorkingDirectory $runtimeDir -WindowStyle Hidden -Wait -PassThru `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
    -ArgumentList @(
      '--default-num-particles','100','--nogui','fly',
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
  if ($process.ExitCode -ne 0) {
    throw "SIMION downstream continuation failed: $stderr"
  }
  $downstream = Join-Path $package.result_dir `
    'simion_downstream_particles.csv'
  Invoke-S3EndToEndSnapshotPython -Python $python -SnapshotRoot $snapshotRoot `
    -Arguments @(
      $frozenSolverDiagnostics,'analyze-simion-log',
      '--log',$stdout,'--ion-file',$ion,
      '--mode','rf_oatof_s3_cumulative_end_to_end',
      '--distribution','s3_local_accelerator_exit',
      '--particle-csv',$downstream,'--allow-incomplete-census'
    ) -FailureMessage 'Frozen SIMION log analysis failed.'

  $metrics = Join-Path $package.result_dir 's3_end_to_end_metrics.json'
  $figure = Join-Path $package.result_dir `
    's3_end_to_end_functional_chain.png'
  Invoke-S3EndToEndSnapshotPython -Python $python -SnapshotRoot $snapshotRoot `
    -Arguments @(
      $frozenAnalyzer,'--source-summary',$sourceSummary,
      '--canonical',$canonical,'--ion',$ion,'--row-map',$rowMap,
      '--downstream',$downstream,'--stdout',$stdout,
      '--pulse-time-us',([string]$pulseTimeUs),
      '--pulse-width-us',([string]$pulseWidthUs),
      '--geometry-contract',$frozenGeometry,
      '--output',$metrics,'--figure',$figure
    ) -FailureMessage 'S3 end-to-end functional audit failed.'
  $result = Get-Content -LiteralPath $metrics -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $runConfiguration.parameters.particle_count =
    [int]$result.census.local_accelerator_exit
  Write-RfJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  Write-RfJson -Path $package.summary -Depth 8 -Value ([ordered]@{
    schema_version = 1
    role = 'rf_oatof_s3_cumulative_end_to_end_summary'
    status = 'success'
    functional_audit = $result.status
    census = $result.census
    source_run_id = $SourceRunId
    figure = 'results/s3_end_to_end_functional_chain.png'
    s3_stage_passed = $false
    resolution_claim_allowed = $false
    formal_gate_passed = $false
  })
  $outputs = @(
    $canonical,$ion,$rowMap,$adapterMetadata,$programMetadata,$runtimeProgram,
    $downstream,$metrics,$figure,$stdout,$stderr,$package.summary
  )
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $manifestToolRoot `
    -RunConfig $package.run_config -Status success -Software $software `
    -Outputs $outputs
  Write-Output (
    "S3_END_TO_END=PASS RUN_ID=$RunId " +
    "HITS=$($result.census.detector_hit)/" +
    "$($result.census.local_accelerator_exit)"
  )
} catch {
  if ($snapshotReady) {
    Complete-RfFrozenFailedRun -Python $python `
      -FrozenRepoRoot $manifestToolRoot `
      -RunConfig $package.run_config -Summary $package.summary `
      -SummaryRole 'rf_oatof_s3_cumulative_end_to_end_summary' `
      -Reason $_.Exception.Message -Software $software
  } else {
    Write-RfJson -Path $package.summary -Value ([ordered]@{
      schema_version = 1
      role = 'rf_oatof_s3_cumulative_end_to_end_summary'
      status = 'failed'
      reason = $_.Exception.Message
      manifest_written = $false
    })
  }
  throw
}
