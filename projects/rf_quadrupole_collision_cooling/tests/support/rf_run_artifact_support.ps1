Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
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
    [Parameter(Mandatory)][string[]]$Software
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
        -Reason $Reason -Software $Software
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

function Confirm-RfFrozenDependencyIdentity {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$InputDir,
    [Parameter(Mandatory)][pscustomobject]$Dependency,
    [Parameter(Mandatory)][string]$ExpectedSourcePath,
    [Parameter(Mandatory)][string]$ExistingSnapshotPath,
    [Parameter(Mandatory)][string]$ExpectedSha256
  )
  $required = @(
    'id','provider_scope','provider_project','provider_repo_path',
    'source_repo_path','frozen_filename','run_input_name','consumers'
  )
  foreach ($name in $required) {
    if ($Dependency.PSObject.Properties.Name -notcontains $name) {
      throw "Frozen dependency identity is missing required field: $name"
    }
  }
  $repo = [IO.Path]::GetFullPath($RepoRoot)
  $inputs = [IO.Path]::GetFullPath($InputDir)
  $source = [IO.Path]::GetFullPath($ExpectedSourcePath)
  $snapshot = [IO.Path]::GetFullPath($ExistingSnapshotPath)
  if (-not (Test-RfDependencyPathWithin -Path $source -Root $repo)) {
    throw "Frozen dependency $($Dependency.id) source escapes the repository."
  }
  if (-not (Test-RfDependencyPathWithin -Path $snapshot -Root $inputs)) {
    throw "Frozen dependency $($Dependency.id) snapshot escapes the run inputs."
  }
  $scope = [string]$Dependency.provider_scope
  $provider = [string]$Dependency.provider_project
  $providerRelative = ([string]$Dependency.provider_repo_path).Replace('\','/')
  if ($scope -eq 'project') {
    if ($providerRelative -ne "projects/$provider") {
      throw "Frozen dependency $($Dependency.id) provider identity differs."
    }
  } elseif ($scope -eq 'repository_common') {
    if ($provider -ne 'common' -or $providerRelative -ne 'common') {
      throw "Frozen dependency $($Dependency.id) common provider identity differs."
    }
  } else {
    throw "Frozen dependency $($Dependency.id) provider scope is invalid."
  }
  $providerRoot = [IO.Path]::GetFullPath((Join-Path $repo $providerRelative))
  if (-not (Test-RfDependencyPathWithin -Path $source -Root $providerRoot)) {
    throw "Frozen dependency $($Dependency.id) source escapes its provider."
  }
  $declaredSource = ([string]$Dependency.source_repo_path).Replace('\','/')
  $expectedSource = [IO.Path]::GetRelativePath($repo, $source).Replace('\','/')
  if ($declaredSource -ne $expectedSource) {
    throw "Frozen dependency $($Dependency.id) source identity differs."
  }
  $declaredSnapshot = [IO.Path]::GetFullPath(
    (Join-Path $inputs ([string]$Dependency.frozen_filename))
  )
  if (-not $declaredSnapshot.Equals(
      $snapshot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Frozen dependency $($Dependency.id) snapshot identity differs."
  }
  $expectedHash = $ExpectedSha256.ToUpperInvariant()
  if ($expectedHash -notmatch '^[0-9A-F]{64}$' -or
      -not (Test-Path -LiteralPath $snapshot -PathType Leaf) -or
      (Get-FileHash -LiteralPath $snapshot -Algorithm SHA256).Hash -ne $expectedHash) {
    throw "Frozen dependency $($Dependency.id) snapshot SHA-256 differs."
  }
  return [pscustomobject]@{
    id = [string]$Dependency.id
    provider_scope = $scope
    provider_project = $provider
    provider_repo_path = $providerRelative
    source_repo_path = $declaredSource
    frozen_input_name = [string]$Dependency.run_input_name
    consumers = @($Dependency.consumers)
    frozen_path = $snapshot
    snapshot_path = $snapshot
    compatibility_path = $null
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
  if ($scope -eq 'project') {
    $expectedProvider = "projects/$provider"
    if ($providerRelative.Replace('\','/') -ne $expectedProvider) {
      throw "Dependency $($Dependency.id) provider root differs from project $provider."
    }
  } elseif ($scope -eq 'repository_common') {
    if ($provider -ne 'common' -or $providerRelative.Replace('\','/') -ne 'common') {
      throw "Dependency $($Dependency.id) has an invalid repository-common provider."
    }
  } else {
    throw "Dependency $($Dependency.id) has unsupported provider scope: $scope"
  }

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
