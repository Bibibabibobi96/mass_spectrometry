Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'common/contracts/run_artifact_support.ps1')

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
  } elseif ($Scope -eq 'repository_core') {
    if ($Provider -ne 'msplatform' -or $normalized -ne 'src/msplatform') {
      throw "Dependency $DependencyId has an invalid scientific-core provider."
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
  $identity = $null
  try {
    $null = Copy-VerifiedRunInput -Source $source -Destination $destination -VerifiedIdentity ([ref]$identity)
  } catch {
    $details = $_.Exception.Data
    if ($details.Contains('source_sha256') -and $details.Contains('frozen_sha256')) {
      $message = "Dependency changed while frozen: $source; destination=$destination; source_sha256=$($details['source_sha256']); frozen_sha256=$($details['frozen_sha256'])"
      throw [InvalidOperationException]::new($message, $_.Exception)
    }
    throw
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
    sha256 = $identity.sha256
    bytes = [long]$identity.bytes
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
    [Parameter(Mandatory)][string]$ConsumerId,
    [Parameter(Mandatory)][string]$Python
  )
  $contract = Get-Content -LiteralPath $ContractPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
  if (@(Compare-Object @('schema_version','role','owner_id','consumer_ids','providers') @($contract.PSObject.Properties.Name)).Count -ne 0 -or
      $contract.schema_version -ne 3 -or $contract.role -cne 'integration_runtime_dependencies' -or
      $contract.owner_id -cne $OwnerId) {
    throw 'Integration runtime dependency contract identity or fields differ from schema 3.'
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
  $packageGroups = [Collections.Generic.List[object]]::new()
  foreach ($group in $contract.providers) {
    if (@(Compare-Object @('provider_scope','provider_project','files','python_packages','python_modules') @($group.PSObject.Properties.Name)).Count -ne 0) {
      throw 'Dependency provider group fields differ.'
    }
    $scope = [string]$group.provider_scope
    $provider = [string]$group.provider_project
    if ([string]::IsNullOrWhiteSpace($provider) -or -not $providers.Add("$scope/$provider")) {
      throw "Dependency provider is empty or duplicated: $scope/$provider"
    }
    $providerRelative = switch ($scope) {
      'repository_common' { if ($provider -cne 'common') { throw "Invalid repository-common provider: $provider" }; 'common' }
      'repository_core' { if ($provider -cne 'msplatform') { throw "Invalid scientific-core provider: $provider" }; 'src/msplatform' }
      'project' { "projects/$provider" }
      'integration' { Get-DependencyIntegrationRoot -RepoRoot $repo -OwnerId $provider }
      default { throw "Unsupported dependency provider scope: $scope" }
    }
    $providerRoot = [IO.Path]::GetFullPath((Join-Path $repo $providerRelative))
    if (-not (Test-DependencyPathWithin -Path $providerRoot -Root $repo)) {
      throw "Dependency provider root escapes the repository: $provider"
    }
    if (-not (@($group.files).Count + @($group.python_packages).Count + @($group.python_modules).Count)) {
      throw "Dependency provider has no source declarations: $provider"
    }
    foreach ($selection in @($group.python_packages) + @($group.python_modules)) {
      $fields=@($selection.PSObject.Properties.Name)
      if (@($fields | Where-Object {$_ -notin @('source_repo_path','consumers','resource_suffixes')}).Count -or
          @(@('source_repo_path','consumers') | Where-Object {$_ -notin $fields}).Count -or
          ($fields -contains 'resource_suffixes' -and $group.python_modules -contains $selection)) {
        throw "Python source selection fields differ for provider: $provider"
      }
      $selectionPath = [string]$selection.source_repo_path
      $selectionAbsolute=[IO.Path]::GetFullPath((Join-Path $repo $selectionPath))
      if ([string]::IsNullOrWhiteSpace($selectionPath) -or $selectionPath.Contains('\') -or
          [IO.Path]::IsPathRooted($selectionPath) -or $selectionPath -match '(^|/)\.\.?(/|$)' -or
          (-not $selectionAbsolute.Equals($providerRoot,[StringComparison]::OrdinalIgnoreCase) -and
           -not (Test-DependencyPathWithin -Path $selectionAbsolute -Root $providerRoot))) {
        throw "Python source selection must stay within its declared provider: $selectionPath"
      }
      $selectionConsumers = @($selection.consumers)
      if (-not $selectionConsumers.Count -or @($selectionConsumers | Select-Object -Unique).Count -ne $selectionConsumers.Count -or
          @($selectionConsumers | Where-Object { $consumers -cnotcontains $_ }).Count) {
        throw "Python source selection declares invalid consumers: $provider"
      }
    }
    $packageGroups.Add([ordered]@{
      provider_scope=$scope; provider_project=$provider; provider_repo_path=$providerRelative
      python_packages=@($group.python_packages | Where-Object { @($_.consumers) -ccontains $ConsumerId })
      python_modules=@($group.python_modules | Where-Object { @($_.consumers) -ccontains $ConsumerId })
    })
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
      if ([IO.Path]::GetExtension($relative) -ieq '.py') {
        throw "Python source must use a package or module declaration: $relative"
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
  # Enumeration is one interpreter call; verified copying keeps its existing owner.
  $enumerator = @'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path[:0] = [str(root / "src"), str(root)] if (root / "src").is_dir() else [str(root)]
from msplatform.execution.inputs import enumerate_python_sources
request = json.load(sys.stdin)
records = []
for group in request["providers"]:
    packages, modules = group["python_packages"], group["python_modules"]
    if not packages and not modules:
        continue
    paths = set(enumerate_python_sources(pathlib.Path(request["source_root"]),
        package_roots=[row["source_repo_path"] for row in packages],
        module_paths=[row["source_repo_path"] for row in modules],
        provider_root=group["provider_repo_path"]))
    for row in packages:
        if "resource_suffixes" in row:
            paths.update(enumerate_python_sources(pathlib.Path(request["source_root"]),
                package_roots=[row["source_repo_path"]], provider_root=group["provider_repo_path"],
                resource_suffixes=row["resource_suffixes"]))
    for path in sorted(paths):
        consumers = set()
        source = pathlib.PurePosixPath(path)
        for row in packages + modules:
            selected = pathlib.PurePosixPath(row["source_repo_path"])
            if (source == selected or selected in source.parents
                    or (source.name == "__init__.py" and source.parent in (selected, *selected.parents))):
                consumers.update(row["consumers"])
        if not consumers:
            raise ValueError(f"Python source has no declaring consumer: {path}")
        records.append({**{key: group[key] for key in
            ("provider_scope", "provider_project", "provider_repo_path")},
            "id": ("python:" if path.endswith(".py") else "resource:") + path,
            "source_repo_path": path, "consumers": sorted(consumers)})
print(json.dumps(records, ensure_ascii=False))
'@
  $enumerationRequest = @{source_root=$repo; providers=@($packageGroups.ToArray())} | ConvertTo-Json -Depth 30 -Compress
  $priorEncoding = $OutputEncoding
  $PSNativeCommandUseErrorActionPreference = $false
  try {
    $OutputEncoding = [Text.UTF8Encoding]::new($false)
    $enumeratedJson = @($enumerationRequest | & $Python -X utf8 -I -B -c $enumerator $repo 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Python package enumeration failed: $($enumeratedJson -join [Environment]::NewLine)" }
  } finally { $OutputEncoding = $priorEncoding }
  $enumerated = @((($enumeratedJson | ForEach-Object { [string]$_ }) -join "`n") | ConvertFrom-Json -Depth 30)
  foreach ($dependency in $enumerated) {
    $relative = [string]$dependency.source_repo_path
    $id = [string]$dependency.id
    $source = [IO.Path]::GetFullPath((Join-Path $repo $relative))
    if (-not $ids.Add($id) -or -not $sources.Add($source)) { throw "Duplicate derived Python source: $relative" }
    if (@($dependency.consumers) -cnotcontains $ConsumerId) { continue }
    $selected.Add([pscustomobject]@{
      id=$id; provider_scope=$dependency.provider_scope; provider_project=$dependency.provider_project
      provider_repo_path=$dependency.provider_repo_path; source_repo_path=$relative
      frozen_filename=('runtime_snapshot/' + $relative); run_input_name=$id; consumers=@($dependency.consumers)
    })
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
    import_roots = @(Get-RunPythonImportRoots -RepoRoot (Join-Path $InputDir 'runtime_snapshot'))
    code_inventory_path = $publication.code_inventory_path
    dependency_contract_path = $publication.dependency_contract_path
    identities = $identities
    source_count = $identities.Count
    source_bytes = [long](($identities | Measure-Object -Property bytes -Sum).Sum)
  }
}
