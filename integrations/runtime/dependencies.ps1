Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-DependencyIntegrationRoot {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$OwnerId
  )
  $registry = Get-Content -LiteralPath (Join-Path $RepoRoot 'integrations/registry.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  $entries = @($registry.integrations | Where-Object { $_.integration_id -ceq $OwnerId })
  if ($entries.Count -ne 1) {
    throw "Dependency integration owner must be registered exactly once: $OwnerId"
  }
  return [string]$entries[0].root
}

function Test-DependencyPathWithin {
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

function Assert-DependencyProviderIdentity {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RepoRoot,
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
    $registeredRoot = Get-DependencyIntegrationRoot -RepoRoot $RepoRoot -OwnerId $Provider
    if ($normalized -ne $registeredRoot) {
      throw "Dependency $DependencyId provider root differs from integration $Provider."
    }
  } else {
    throw "Dependency $DependencyId has unsupported provider scope: $Scope"
  }
}

function Copy-FrozenDependency {
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
  Assert-DependencyProviderIdentity -RepoRoot $RepoRoot -DependencyId $Dependency.id `
    -Scope $scope -Provider $provider -ProviderRelative $providerRelative

  $repo = [IO.Path]::GetFullPath($RepoRoot)
  $inputs = [IO.Path]::GetFullPath($InputDir)
  $providerRoot = [IO.Path]::GetFullPath((Join-Path $repo $providerRelative))
  if (-not (Test-DependencyPathWithin -Path $providerRoot -Root $repo)) {
    throw "Dependency $($Dependency.id) provider root escapes the repository."
  }
  $sourceRelative = [string]$Dependency.source_repo_path
  if ([IO.Path]::IsPathRooted($sourceRelative)) {
    throw "Dependency $($Dependency.id) source path must be repository-relative."
  }
  $source = [IO.Path]::GetFullPath((Join-Path $repo $sourceRelative))
  if (-not (Test-DependencyPathWithin -Path $source -Root $providerRoot)) {
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
  if (-not (Test-DependencyPathWithin -Path $destination -Root $inputs)) {
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
  return [pscustomobject]@{
    id = [string]$Dependency.id
    provider_scope = $scope
    provider_project = $provider
    provider_repo_path = $providerRelative.Replace('\','/')
    source_repo_path = $sourceRelative.Replace('\','/')
    frozen_input_name = [string]$Dependency.run_input_name
    consumers = @($Dependency.consumers)
    frozen_path = $destination
    snapshot_path = $destination
    sha256 = $sourceHash
  }
}

function Publish-DependencyInventory {
  <# Publish the explicit selected inventory and freeze its authoring contract. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$ContractPath,
    [Parameter(Mandatory)][string]$InputDir,
    [Parameter(Mandatory)][string]$OwnerId,
    [Parameter(Mandatory)][psobject]$ResolvedDependencies
  )
  $dependencies = @($ResolvedDependencies.dependencies)
  if ($dependencies.Count -lt 1) {
    throw 'Resolved code inventory contains no dependencies.'
  }
  foreach ($field in @('id', 'run_input_name', 'frozen_filename')) {
    $values = @($dependencies | ForEach-Object { [string]$_.$field })
    if (@($values | Where-Object { [string]::IsNullOrWhiteSpace($_) }).Count -ne 0 -or
        @($values | Select-Object -Unique).Count -ne $dependencies.Count) {
      throw "Resolved code inventory contains empty or duplicate $field values."
    }
  }
  $relative = [IO.Path]::GetRelativePath([IO.Path]::GetFullPath($RepoRoot), [IO.Path]::GetFullPath($ContractPath)).Replace('\','/')
  $contractDependency = [pscustomobject]@{
    id = 'dependency_contract'
    provider_scope = 'integration'
    provider_project = $OwnerId
    provider_repo_path = Get-DependencyIntegrationRoot -RepoRoot $RepoRoot -OwnerId $OwnerId
    source_repo_path = $relative
    frozen_filename = 'runtime_snapshot/' + $relative
    run_input_name = 'dependency_contract'
    consumers = @($ResolvedDependencies.consumer_ids)
  }
  $contractIdentity = Copy-FrozenDependency -RepoRoot $RepoRoot -InputDir $InputDir -Dependency $contractDependency
  $inventory = [ordered]@{
    schema_version = 1
    role = 'integration_resolved_code_inventory'
    owner_id = $OwnerId
    consumer_ids = @($ResolvedDependencies.consumer_ids)
    dependencies = $dependencies
    authority = [ordered]@{ path = $relative; sha256 = $contractIdentity.sha256 }
  }
  $inventoryPath = Join-Path $InputDir 'code_inventory.json'
  [IO.File]::WriteAllText($inventoryPath, ($inventory | ConvertTo-Json -Depth 20) + "`n", [Text.UTF8Encoding]::new($false))
  return [pscustomobject]@{
    dependency_contract_path = $contractIdentity.snapshot_path
    code_inventory_path = $inventoryPath
    dependency_contract_identity = $contractIdentity
  }
}

function Freeze-ConsumerDependencies {
  <# Root authors declare provider groups; expand once into the shared flat
     publication/copy contract still used by the existing family workflows. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$ContractPath,
    [Parameter(Mandatory)][string]$InputDir,
    [Parameter(Mandatory)][string]$OwnerId,
    [Parameter(Mandatory)][string]$ConsumerId
  )
  $contract = Get-Content -LiteralPath $ContractPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
  if (@(Compare-Object @('schema_version','role','owner_id','consumer_ids','providers') @($contract.PSObject.Properties.Name)).Count -ne 0 -or
      $contract.schema_version -ne 2 -or $contract.role -cne 'integration_runtime_dependencies' -or
      $contract.owner_id -cne $OwnerId) {
    throw 'Integration runtime dependency contract identity or fields differ from schema 2.'
  }
  $consumers = @($contract.consumer_ids)
  if (-not $consumers.Count -or @($consumers | Where-Object { [string]::IsNullOrWhiteSpace($_) }).Count -or
      @($consumers | Select-Object -Unique).Count -ne $consumers.Count -or $consumers -cnotcontains $ConsumerId) {
    throw "Unregistered or invalid runtime dependency consumer: $ConsumerId"
  }
  $repo = [IO.Path]::GetFullPath($RepoRoot)
  $ownerRoot = Get-DependencyIntegrationRoot -RepoRoot $repo -OwnerId $OwnerId
  $contractRelative = [IO.Path]::GetRelativePath($repo, [IO.Path]::GetFullPath($ContractPath)).Replace('\','/')
  if (-not (Test-DependencyPathWithin -Path $ContractPath -Root (Join-Path $repo $ownerRoot))) {
    throw 'Dependency contract escapes its registered integration owner.'
  }
  $ids = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
  $sources = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
  $providers = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
  $selected = [Collections.Generic.List[object]]::new()
  foreach ($group in $contract.providers) {
    if (@(Compare-Object @('provider_scope','provider_project','files') @($group.PSObject.Properties.Name)).Count -ne 0) {
      throw 'Dependency provider group fields differ.'
    }
    $scope = [string]$group.provider_scope
    $provider = [string]$group.provider_project
    if ([string]::IsNullOrWhiteSpace($provider) -or -not $providers.Add("$scope/$provider")) {
      throw "Dependency provider is empty or duplicated: $scope/$provider"
    }
    $providerRelative = switch ($scope) {
      'repository_common' { if ($provider -cne 'common') { throw "Invalid repository-common provider: $provider" }; 'common' }
      'project' { "projects/$provider" }
      'integration' { Get-DependencyIntegrationRoot -RepoRoot $repo -OwnerId $provider }
      default { throw "Unsupported dependency provider scope: $scope" }
    }
    $providerRoot = [IO.Path]::GetFullPath((Join-Path $repo $providerRelative))
    if (-not (Test-DependencyPathWithin -Path $providerRoot -Root $repo)) {
      throw "Dependency provider root escapes the repository: $provider"
    }
    if (-not @($group.files).Count) { throw "Dependency provider has no files: $provider" }
    foreach ($file in $group.files) {
      if (@(Compare-Object @('id','source_repo_path','consumers') @($file.PSObject.Properties.Name)).Count -ne 0) {
        throw "Dependency file fields differ for provider: $provider"
      }
      $id = [string]$file.id
      $relative = ([string]$file.source_repo_path).Replace('\','/')
      if ([string]::IsNullOrWhiteSpace($id) -or $id -in @('dependency_contract','code_inventory') -or -not $ids.Add($id)) {
        throw "Empty, reserved or duplicate dependency id: $id"
      }
      if ([string]::IsNullOrWhiteSpace($relative) -or [IO.Path]::IsPathRooted($relative) -or $relative -match '(^|/)\.\.(/|$)') {
        throw "Dependency $id source path is empty, absolute or escapes its provider."
      }
      $source = [IO.Path]::GetFullPath((Join-Path $repo $relative))
      if (-not (Test-DependencyPathWithin -Path $source -Root $providerRoot)) {
        throw "Dependency $id escapes provider $provider."
      }
      if ($relative -ieq $contractRelative -or -not $sources.Add($source)) {
        throw "Duplicate dependency source path: $relative"
      }
      $fileConsumers = @($file.consumers)
      if (-not $fileConsumers.Count -or @($fileConsumers | Select-Object -Unique).Count -ne $fileConsumers.Count -or
          @($fileConsumers | Where-Object { $consumers -cnotcontains $_ }).Count) {
        throw "Dependency $id declares invalid consumers."
      }
      if ($fileConsumers -cnotcontains $ConsumerId) { continue }
      if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Dependency $id is missing: $source" }
      $destination = Join-Path $InputDir ('runtime_snapshot/' + $relative)
      if (Test-Path -LiteralPath $destination) { throw "Dependency $id frozen destination already exists: $destination" }
      $selected.Add([pscustomobject]@{
        id=$id; provider_scope=$scope; provider_project=$provider; provider_repo_path=$providerRelative
        source_repo_path=$relative; frozen_filename=('runtime_snapshot/' + $relative); run_input_name=$id; consumers=$fileConsumers
      })
    }
  }
  if (-not $selected.Count) { throw "Runtime dependency consumer has no declared files: $ConsumerId" }
  $ResolvedDependencies = [pscustomobject]@{ consumer_ids=@($ConsumerId); dependencies=@($selected.ToArray()) }
  $publication = Publish-DependencyInventory -RepoRoot $RepoRoot -ContractPath $ContractPath `
    -InputDir $InputDir -OwnerId $OwnerId -ResolvedDependencies $ResolvedDependencies
  $identities = @(foreach ($dependency in $ResolvedDependencies.dependencies) {
    Copy-FrozenDependency -RepoRoot $RepoRoot -InputDir $InputDir -Dependency $dependency
  })
  return [pscustomobject]@{
    execution_root = Join-Path $InputDir 'runtime_snapshot'
    code_inventory_path = $publication.code_inventory_path
    dependency_contract_path = $publication.dependency_contract_path
    identities = $identities
  }
}
