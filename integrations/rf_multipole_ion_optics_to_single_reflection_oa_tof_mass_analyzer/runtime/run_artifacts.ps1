Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')

Set-Alias -Name New-RfRunPackage -Value New-RunPackage
Set-Alias -Name Write-RfJson -Value Write-RunJson
Set-Alias -Name Write-RfRunManifest -Value Write-RunManifest
Set-Alias -Name Save-RfEnvironment -Value Save-RunEnvironment
Set-Alias -Name Restore-RfEnvironment -Value Restore-RunEnvironment
Set-Alias -Name Complete-RfFailedRun -Value Complete-FailedRun

function Write-RfFrozenRunManifest {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$FrozenRepoRoot,
    [Parameter(Mandatory)][string]$RunConfig,
    [Parameter(Mandatory)]
    [ValidateSet('success','failed','interrupted','superseded')]
    [string]$Status,
    [string[]]$Software = @(),
    [string[]]$Outputs = @()
  )
  $environmentNames = @('PYTHONPATH','PYTHONNOUSERSITE')
  $savedEnvironment = Save-RfEnvironment -Names $environmentNames
  try {
    $env:PYTHONPATH = $FrozenRepoRoot
    $env:PYTHONNOUSERSITE = '1'
    Push-Location -LiteralPath $FrozenRepoRoot
    try {
      Write-RfRunManifest -Python $Python -RepoRoot $FrozenRepoRoot `
        -RunConfig $RunConfig -Status $Status -Software $Software -Outputs $Outputs
    } finally {
      Pop-Location
    }
  } finally {
    Restore-RfEnvironment -Names $environmentNames -Snapshot $savedEnvironment
  }
}

function Complete-RfFrozenFailedRun {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$FrozenRepoRoot,
    [Parameter(Mandatory)][string]$RunConfig,
    [Parameter(Mandatory)][string]$Summary,
    [Parameter(Mandatory)][string]$SummaryRole,
    [Parameter(Mandatory)][string]$Reason,
    [Parameter(Mandatory)][string[]]$Software,
    [ValidateSet('failed','interrupted')][string]$Status = 'failed',
    [string]$FailureClass = '',
    [string]$ResourceUsagePath = ''
  )
  $environmentNames = @('PYTHONPATH','PYTHONNOUSERSITE')
  $savedEnvironment = Save-RfEnvironment -Names $environmentNames
  try {
    $env:PYTHONPATH = $FrozenRepoRoot
    $env:PYTHONNOUSERSITE = '1'
    Push-Location -LiteralPath $FrozenRepoRoot
    try {
      Complete-RfFailedRun -Python $Python -RepoRoot $FrozenRepoRoot `
        -RunConfig $RunConfig -Summary $Summary -SummaryRole $SummaryRole `
        -Reason $Reason -Software $Software -Status $Status `
        -FailureClass $FailureClass -ResourceUsagePath $ResourceUsagePath
    } finally {
      Pop-Location
    }
  } finally {
    Restore-RfEnvironment -Names $environmentNames -Snapshot $savedEnvironment
  }
}

function Resolve-RfDirectChildDirectory {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$ParentRoot,
    [Parameter(Mandatory)][string]$ChildName,
    [Parameter(Mandatory)][string]$Role
  )
  if ([string]::IsNullOrWhiteSpace($ChildName) -or
      [IO.Path]::IsPathRooted($ChildName) -or
      $ChildName.IndexOfAny([char[]]@('\','/')) -ge 0 -or
      $ChildName -in @('.','..')) {
    throw "$Role must be a direct-child name."
  }
  $parent = [IO.Path]::GetFullPath($ParentRoot).TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
  )
  $child = [IO.Path]::GetFullPath((Join-Path $parent $ChildName))
  if (-not (Split-Path -Parent $child).Equals(
      $parent, [StringComparison]::OrdinalIgnoreCase)) {
    throw "$Role escapes its parent directory."
  }
  if (-not (Test-Path -LiteralPath $child -PathType Container)) {
    throw "$Role directory is missing: $child"
  }
  return $child
}

function Get-RfManifestInputRecord {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][pscustomobject]$Manifest,
    [Parameter(Mandatory)][string]$Role
  )
  if ($Manifest.PSObject.Properties.Name -notcontains 'inputs') {
    throw 'Source manifest has no inputs object.'
  }
  $property = $Manifest.inputs.PSObject.Properties[$Role]
  if ($null -eq $property) {
    throw "Source manifest has no input record for $Role."
  }
  return $property.Value
}

function Get-RfManifestOutputRecord {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][pscustomobject]$Manifest,
    [Parameter(Mandatory)][string]$ExpectedPath,
    [Parameter(Mandatory)][string]$Role
  )
  if ($Manifest.PSObject.Properties.Name -notcontains 'outputs') {
    throw 'Source manifest has no outputs array.'
  }
  $expected = [IO.Path]::GetFullPath($ExpectedPath)
  $matches = @(
    $Manifest.outputs | Where-Object {
      $_.PSObject.Properties.Name -contains 'path' -and
      [IO.Path]::GetFullPath([string]$_.path).Equals(
        $expected, [StringComparison]::OrdinalIgnoreCase)
    }
  )
  if ($matches.Count -ne 1) {
    throw "Source manifest must contain exactly one $Role output record."
  }
  return $matches[0]
}

function Copy-RfStableFile {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$SourceRunRoot,
    [Parameter(Mandatory)][string]$SourcePath,
    [Parameter(Mandatory)][string]$Destination,
    [Parameter(Mandatory)][string]$Role
  )
  $sourceRoot = [IO.Path]::GetFullPath($SourceRunRoot)
  $source = [IO.Path]::GetFullPath($SourcePath)
  if (-not (Test-RfDependencyPathWithin -Path $source -Root $sourceRoot) -or
      -not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "Source $Role is missing or escapes its run: $source"
  }
  $destinationPath = [IO.Path]::GetFullPath($Destination)
  if (Test-Path -LiteralPath $destinationPath) {
    throw "Source $Role destination already exists: $destinationPath"
  }
  $sourceItem = Get-Item -LiteralPath $source
  $sourceBytes = $sourceItem.Length
  $sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
  New-Item -ItemType Directory -Path (Split-Path -Parent $destinationPath) -Force |
    Out-Null
  Copy-Item -LiteralPath $source -Destination $destinationPath
  if ((Get-Item -LiteralPath $source).Length -ne $sourceBytes -or
      (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $sourceHash -or
      (Get-Item -LiteralPath $destinationPath).Length -ne $sourceBytes -or
      (Get-FileHash -LiteralPath $destinationPath -Algorithm SHA256).Hash -ne $sourceHash) {
    throw "Source $Role identity changed while frozen."
  }
  return [pscustomobject]@{
    role = $Role
    source_path = $source
    frozen_path = $destinationPath
    bytes = $sourceBytes
    sha256 = $sourceHash
  }
}

function Get-RfSimionSolverCacheIdentity {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$SimionExe)
  $executable = (Resolve-Path -LiteralPath $SimionExe).Path
  $version = [Diagnostics.FileVersionInfo]::GetVersionInfo($executable)
  $productVersion = [string]$version.ProductVersion
  if ([string]::IsNullOrWhiteSpace($productVersion)) {
    $productVersion = [string]$version.FileVersion
  }
  if ([string]::IsNullOrWhiteSpace($productVersion)) {
    throw 'SIMION executable has no product or file version identity.'
  }
  return [ordered]@{
    name = 'SIMION'
    product_version = $productVersion
    executable_sha256 = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash
  }
}

function Get-RfContentIdentitySha256 {
  [CmdletBinding()]
  param([Parameter(Mandatory)]$Identity)
  $json = $Identity | ConvertTo-Json -Depth 12 -Compress
  return [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($json))
  ).ToLowerInvariant()
}

function Assert-RfCacheEntryPath {
  param(
    [Parameter(Mandatory)][string]$CacheRoot,
    [Parameter(Mandatory)][string]$CacheKey,
    [Parameter(Mandatory)][string]$CacheEntry
  )
  if ($CacheKey -notmatch '^[a-f0-9]{64}$') { throw 'Cache key is not a lowercase SHA-256.' }
  $root = [IO.Path]::GetFullPath($CacheRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
  $expected = [IO.Path]::GetFullPath((Join-Path $root $CacheKey))
  if (-not $expected.Equals([IO.Path]::GetFullPath($CacheEntry), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Cache entry path differs from its content key.'
  }
}

function Test-RfReusableCacheEntry {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$WorkspaceRoot,
    [Parameter(Mandatory)][string]$ProjectId,
    [Parameter(Mandatory)][string]$CacheRoot,
    [Parameter(Mandatory)][string]$CacheKey,
    [Parameter(Mandatory)][string]$Role
  )
  $entry = Join-Path $CacheRoot $CacheKey
  Assert-RfCacheEntryPath -CacheRoot $CacheRoot -CacheKey $CacheKey -CacheEntry $entry
  $manifest = Join-Path $entry 'cache_manifest.json'
  if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { return $false }
  & $Python (Join-Path $RepoRoot 'common\contracts\verify_artifact_layout.py') `
    (Join-Path $WorkspaceRoot 'artifacts\projects') --cache-entry $entry `
    --expected-cache-role $Role --expected-cache-key $CacheKey `
    --expected-cache-project $ProjectId *> $null
  if ($LASTEXITCODE -eq 0) { return $true }
  $document = $null
  try {
    $document = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
  } catch {
    $document = $null
  }
  if ($null -ne $document -and [int]$document.schema_version -eq 2) {
    Remove-Item -LiteralPath $entry -Recurse -Force
    return $false
  }
  return $false
}

function New-RfCacheStagingDirectory {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$CacheRoot)
  $root = [IO.Path]::GetFullPath($CacheRoot)
  New-Item -ItemType Directory -Path $root -Force | Out-Null
  $staging = Join-Path $root ('b-' + [guid]::NewGuid().ToString('N').Substring(0,12))
  New-Item -ItemType Directory -Path $staging | Out-Null
  if (-not (Split-Path -Parent ([IO.Path]::GetFullPath($staging))).Equals(
      $root.TrimEnd([IO.Path]::DirectorySeparatorChar),
      [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Cache staging directory escaped its registered root.'
  }
  return $staging
}

function Publish-RfVerifiedCacheEntry {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$WorkspaceRoot,
    [Parameter(Mandatory)][string]$ProjectId,
    [Parameter(Mandatory)][string]$CacheRoot,
    [Parameter(Mandatory)][string]$CacheKey,
    [Parameter(Mandatory)][string]$Role,
    [Parameter(Mandatory)]$Identity,
    [Parameter(Mandatory)][string]$StagingDirectory,
    [Parameter(Mandatory)][string]$ProviderRunId
  )
  $root = [IO.Path]::GetFullPath($CacheRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
  $staging = [IO.Path]::GetFullPath($StagingDirectory)
  if (-not (Split-Path -Parent $staging).Equals($root, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Cache publication staging directory escaped its registered root.'
  }
  $target = Join-Path $root $CacheKey
  Assert-RfCacheEntryPath -CacheRoot $root -CacheKey $CacheKey -CacheEntry $target
  $files = @(Get-ChildItem -LiteralPath $staging -File | Where-Object {
    $_.Name -ne 'cache_manifest.json'
  } | Sort-Object Name)
  if ($files.Count -eq 0) { throw 'Cache publication has no files.' }
  $records = @($files | ForEach-Object {
    [ordered]@{name=$_.Name;bytes=$_.Length;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
  })
  $cacheKeyInput = $Identity | ConvertTo-Json -Depth 12 -Compress
  $derivedKey = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($cacheKeyInput))
  ).ToLowerInvariant()
  if ($derivedKey -ne $CacheKey) { throw 'Cache identity changed before publication.' }
  Write-RfJson -Path (Join-Path $staging 'cache_manifest.json') -Depth 14 -Value ([ordered]@{
    schema_version=2; role=$Role; cache_key=$CacheKey; provider_run_id=$ProviderRunId
    cache_key_input=$cacheKeyInput; identity=$Identity; files=$records
  })
  if (Test-Path -LiteralPath $target) {
    if (Test-RfReusableCacheEntry -Python $Python -RepoRoot $RepoRoot `
        -WorkspaceRoot $WorkspaceRoot -ProjectId $ProjectId -CacheRoot $root `
        -CacheKey $CacheKey -Role $Role) {
      Remove-Item -LiteralPath $staging -Recurse -Force
      return $target
    }
    if (Test-Path -LiteralPath $target) {
      throw 'Legacy cache entry unexpectedly collides with the current content key.'
    }
  }
  Move-Item -LiteralPath $staging -Destination $target
  if (-not (Test-RfReusableCacheEntry -Python $Python -RepoRoot $RepoRoot `
      -WorkspaceRoot $WorkspaceRoot -ProjectId $ProjectId -CacheRoot $root `
      -CacheKey $CacheKey -Role $Role)) {
    throw 'Published cache entry did not pass the shared verifier.'
  }
  return $target
}

function Copy-RfCacheManifestInput {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$CacheEntry,
    [Parameter(Mandatory)][string]$Destination
  )
  $source = Join-Path $CacheEntry 'cache_manifest.json'
  if (Test-Path -LiteralPath $Destination) { throw 'Frozen cache manifest destination exists.' }
  Copy-Item -LiteralPath $source -Destination $Destination
  if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne
      (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash) {
    throw 'Cache manifest changed while frozen into run inputs.'
  }
  return $Destination
}

function Resolve-RfMaterializedMotherSourceRunRoot {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$WorkspaceRoot,
    [Parameter(Mandatory)][string]$SourcePath,
    [Parameter(Mandatory)][string]$ReceiptPath
  )
  $workspace = [IO.Path]::GetFullPath($WorkspaceRoot)
  $source = [IO.Path]::GetFullPath($SourcePath)
  $receipt = [IO.Path]::GetFullPath($ReceiptPath)
  $inputs = Split-Path -Parent $receipt
  $runRoot = Split-Path -Parent $inputs
  $integrationRunsRoot = [IO.Path]::GetFullPath((Join-Path $workspace (
    'artifacts\projects\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\runs'
  )))
  if ((Split-Path -Parent $runRoot) -ne $integrationRunsRoot -or
      (Split-Path -Leaf $inputs) -ne 'inputs' -or
      -not $source.Equals(
        (Join-Path $inputs 'single_flight_materialized_particle_source.csv'),
        [StringComparison]::OrdinalIgnoreCase
      ) -or
      -not $receipt.Equals(
        (Join-Path $inputs 'single_flight_source_materialization_receipt.json'),
        [StringComparison]::OrdinalIgnoreCase
      )) {
    throw 'Materialized mother source is outside its canonical integration parent run.'
  }
  return $runRoot
}

function Initialize-RfIntegrationStageBudget {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$ResolvedBudget,
    [Parameter(Mandatory)][string]$InputDir,
    [Parameter(Mandatory)][string]$ExpectedIntegrationId,
    [Parameter(Mandatory)][string]$ExpectedConnectionProfileId,
    [Parameter(Mandatory)][string]$StageId,
    [Parameter(Mandatory)][ValidateSet('comsol','simion')][string]$Solver
  )
  $frozen = Join-Path $InputDir 'resolved_integration_engineering_budget.json'
  $identity = Copy-RfStableFile `
    -SourceRunRoot (Split-Path -Parent ([IO.Path]::GetFullPath($ResolvedBudget))) `
    -SourcePath $ResolvedBudget -Destination $frozen `
    -Role 'resolved integration engineering budget'
  $document = Get-Content -LiteralPath $frozen -Raw -Encoding UTF8 |
    ConvertFrom-Json
  if ($document.schema_version -ne 1 -or
      $document.role -ne 'integration_resolved_engineering_budget' -or
      $document.integration_id -ne $ExpectedIntegrationId -or
      $document.connection_profile_id -ne $ExpectedConnectionProfileId -or
      $document.retention_class -ne 'compact' -or
      [int]$document.particle_count -lt 1) {
    throw 'Resolved integration engineering-budget identity differs.'
  }
  if ($document.stage_limits.PSObject.Properties.Name -notcontains $StageId) {
    throw "Resolved integration engineering budget omits stage: $StageId"
  }
  $limits = $document.stage_limits.$StageId
  if ($limits.solver -ne $Solver -or
      [int]$limits.automatic_retry_count -ne 0) {
    throw "Resolved integration engineering-budget stage differs: $StageId"
  }
  foreach ($limitName in @(
      'wall_clock_seconds',
      'transient_run_directory_bytes',
      'process_tree_working_set_bytes',
      'minimum_system_available_memory_bytes',
      'compact_final_retained_bytes'
    )) {
    if ($limits.PSObject.Properties.Name -notcontains $limitName -or
        [long]$limits.$limitName -le 0) {
      throw "Resolved integration engineering-budget stage has no positive ${limitName}: $StageId"
    }
  }
  $stageBudget = Join-Path $InputDir "resolved_resource_budget__$StageId.json"
  Write-RfJson -Path $stageBudget -Value ([ordered]@{
    schema_version = 1
    role = 'integration_resolved_stage_resource_budget'
    integration_id = $ExpectedIntegrationId
    connection_profile_id = $ExpectedConnectionProfileId
    stage_id = $StageId
    solver = $Solver
    source_identity = $document.source_identity
    retention_class = 'compact'
    limits = [ordered]@{
      wall_clock_seconds = [int]$limits.wall_clock_seconds
      transient_run_directory_bytes = [long]$limits.transient_run_directory_bytes
      process_tree_working_set_bytes = [long]$limits.process_tree_working_set_bytes
      minimum_system_available_memory_bytes =
        [long]$limits.minimum_system_available_memory_bytes
      compact_final_retained_bytes = [long]$limits.compact_final_retained_bytes
      automatic_retry_count = 0
    }
  })
  $stageBudgetSha256 = (
    Get-FileHash -LiteralPath $stageBudget -Algorithm SHA256
  ).Hash
  return [pscustomobject]@{
    frozen_budget = $frozen
    stage_budget = $stageBudget
    resolved_budget_sha256 = $identity.sha256
    stage_budget_sha256 = $stageBudgetSha256
  }
}

function Copy-RfManifestBoundFile {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$SourceRunRoot,
    [Parameter(Mandatory)][string]$SourcePath,
    [Parameter(Mandatory)][string]$Destination,
    [Parameter(Mandatory)][pscustomobject]$ManifestRecord,
    [Parameter(Mandatory)][string]$Role
  )
  foreach ($name in @('path','exists','bytes','sha256')) {
    if ($ManifestRecord.PSObject.Properties.Name -notcontains $name) {
      throw "Source manifest $Role record is missing field: $name"
    }
  }
  $sourceRoot = [IO.Path]::GetFullPath($SourceRunRoot)
  $source = [IO.Path]::GetFullPath($SourcePath)
  $recordPath = [IO.Path]::GetFullPath([string]$ManifestRecord.path)
  if (-not (Test-RfDependencyPathWithin -Path $source -Root $sourceRoot)) {
    throw "Source manifest $Role path escapes its run: $source"
  }
  if (-not $source.Equals($recordPath, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Source manifest $Role path differs from run_config: $source"
  }
  if (-not [bool]$ManifestRecord.exists -or
      -not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "Source manifest $Role file is missing: $source"
  }
  $expectedHash = ([string]$ManifestRecord.sha256).ToUpperInvariant()
  if ($expectedHash -notmatch '^[0-9A-F]{64}$') {
    throw "Source manifest $Role SHA-256 is invalid."
  }
  if ((Get-Item -LiteralPath $source).Length -ne [long]$ManifestRecord.bytes -or
      (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $expectedHash) {
    throw "Source manifest $Role identity changed before freeze."
  }
  $destinationPath = [IO.Path]::GetFullPath($Destination)
  if (Test-Path -LiteralPath $destinationPath) {
    throw "Source manifest $Role destination already exists: $destinationPath"
  }
  New-Item -ItemType Directory -Path (Split-Path -Parent $destinationPath) -Force |
    Out-Null
  Copy-Item -LiteralPath $source -Destination $destinationPath
  if ((Get-Item -LiteralPath $source).Length -ne [long]$ManifestRecord.bytes -or
      (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $expectedHash -or
      (Get-Item -LiteralPath $destinationPath).Length -ne [long]$ManifestRecord.bytes -or
      (Get-FileHash -LiteralPath $destinationPath -Algorithm SHA256).Hash -ne $expectedHash) {
    throw "Source manifest $Role identity changed while frozen."
  }
  return [pscustomobject]@{
    role = $Role
    source_path = $source
    frozen_path = $destinationPath
    bytes = [long]$ManifestRecord.bytes
    sha256 = $expectedHash
  }
}

function Test-RfDependencyPathWithin {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][string]$Root
  )
  $fullPath = [IO.Path]::GetFullPath($Path)
  $fullRoot = [IO.Path]::GetFullPath($Root).TrimEnd(
    [IO.Path]::DirectorySeparatorChar,
    [IO.Path]::AltDirectorySeparatorChar
  )
  return $fullPath.StartsWith(
    $fullRoot + [IO.Path]::DirectorySeparatorChar,
    [StringComparison]::OrdinalIgnoreCase
  )
}

function Assert-RfDependencyProviderIdentity {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$DependencyId,
    [Parameter(Mandatory)][string]$Scope,
    [Parameter(Mandatory)][string]$Provider,
    [Parameter(Mandatory)][string]$ProviderRelative
  )
  $normalized = $ProviderRelative.Replace('\','/')
  if ($Scope -eq 'project') {
    if ($normalized -ne "projects/$Provider") {
      throw "Dependency $DependencyId provider root differs from project $Provider."
    }
  } elseif ($Scope -eq 'repository_common') {
    if ($Provider -ne 'common' -or $normalized -ne 'common') {
      throw "Dependency $DependencyId has an invalid repository-common provider."
    }
  } elseif ($Scope -eq 'integration') {
    if ($normalized -ne "integrations/$Provider") {
      throw "Dependency $DependencyId provider root differs from integration $Provider."
    }
  } else {
    throw "Dependency $DependencyId has unsupported provider scope: $Scope"
  }
}

function Copy-RfFrozenDependency {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$InputDir,
    [Parameter(Mandatory)][pscustomobject]$Dependency
  )
  $required = @(
    'id','provider_scope','provider_project','provider_repo_path',
    'source_repo_path','frozen_filename','run_input_name','consumers'
  )
  foreach ($name in $required) {
    if ($Dependency.PSObject.Properties.Name -notcontains $name) {
      throw "Dependency is missing required field: $name"
    }
  }
  if ([string]::IsNullOrWhiteSpace([string]$Dependency.id)) {
    throw 'Dependency id must be non-empty.'
  }
  $scope = [string]$Dependency.provider_scope
  $provider = [string]$Dependency.provider_project
  $providerRelative = [string]$Dependency.provider_repo_path
  Assert-RfDependencyProviderIdentity -DependencyId $Dependency.id `
    -Scope $scope -Provider $provider -ProviderRelative $providerRelative

  $repo = [IO.Path]::GetFullPath($RepoRoot)
  $inputs = [IO.Path]::GetFullPath($InputDir)
  $providerRoot = [IO.Path]::GetFullPath((Join-Path $repo $providerRelative))
  if (-not (Test-RfDependencyPathWithin -Path $providerRoot -Root $repo)) {
    throw "Dependency $($Dependency.id) provider root escapes the repository."
  }
  $sourceRelative = [string]$Dependency.source_repo_path
  if ([IO.Path]::IsPathRooted($sourceRelative)) {
    throw "Dependency $($Dependency.id) source path must be repository-relative."
  }
  $source = [IO.Path]::GetFullPath((Join-Path $repo $sourceRelative))
  if (-not (Test-RfDependencyPathWithin -Path $source -Root $providerRoot)) {
    throw "Dependency $($Dependency.id) escapes provider $provider."
  }
  if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "Dependency $($Dependency.id) is missing: $source"
  }

  $frozenRelative = [string]$Dependency.frozen_filename
  if ([IO.Path]::IsPathRooted($frozenRelative)) {
    throw "Dependency $($Dependency.id) frozen filename must be input-relative."
  }
  $destination = [IO.Path]::GetFullPath((Join-Path $inputs $frozenRelative))
  if (-not (Test-RfDependencyPathWithin -Path $destination -Root $inputs)) {
    throw "Dependency $($Dependency.id) frozen destination escapes the run inputs."
  }
  if (Test-Path -LiteralPath $destination) {
    throw "Dependency $($Dependency.id) frozen destination already exists: $destination"
  }
  $destinationParent = Split-Path -Parent $destination
  New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
  Copy-Item -LiteralPath $source -Destination $destination
  $sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
  $frozenHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
  if ($sourceHash -ne $frozenHash) {
    throw "Dependency changed while frozen: $source"
  }
  $runtimePath = $destination
  $compatibilityPath = $null
  if ($Dependency.PSObject.Properties.Name -contains 'compatibility_frozen_filename') {
    $compatibilityRelative = [string]$Dependency.compatibility_frozen_filename
    if ([IO.Path]::IsPathRooted($compatibilityRelative)) {
      throw "Dependency $($Dependency.id) compatibility filename must be input-relative."
    }
    $compatibilityPath = [IO.Path]::GetFullPath((Join-Path $inputs $compatibilityRelative))
    if (-not (Test-RfDependencyPathWithin -Path $compatibilityPath -Root $inputs)) {
      throw "Dependency $($Dependency.id) compatibility destination escapes the run inputs."
    }
    if ($compatibilityPath -eq $destination -or (Test-Path -LiteralPath $compatibilityPath)) {
      throw "Dependency $($Dependency.id) compatibility destination is not unique."
    }
    $compatibilityParent = Split-Path -Parent $compatibilityPath
    New-Item -ItemType Directory -Path $compatibilityParent -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $compatibilityPath
    if ($sourceHash -ne (Get-FileHash -LiteralPath $compatibilityPath -Algorithm SHA256).Hash) {
      throw "Dependency changed while compatibility copy was frozen: $source"
    }
    $runtimePath = $compatibilityPath
  }
  return [pscustomobject]@{
    id = [string]$Dependency.id
    provider_scope = $scope
    provider_project = $provider
    provider_repo_path = $providerRelative.Replace('\','/')
    source_repo_path = $sourceRelative.Replace('\','/')
    frozen_input_name = [string]$Dependency.run_input_name
    consumers = @($Dependency.consumers)
    frozen_path = $runtimePath
    snapshot_path = $destination
    compatibility_path = $compatibilityPath
    sha256 = $sourceHash
  }
}
