Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'run_artifact_support.ps1')

function Get-DependencyCoreRoot {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RepoRoot,
    [string]$CorePackageRoot=''
  )
  if (-not $CorePackageRoot) {
    return [IO.Path]::GetFullPath((Join-Path $RepoRoot 'src/msplatform'))
  }
  $core = [IO.Path]::GetFullPath($CorePackageRoot)
  if (-not (Test-Path -LiteralPath $core -PathType Container)) {
    throw "Installed dependency core package is missing: $core"
  }
  return $core
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

function Resolve-DependencySourcePath {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$Scope,
    [Parameter(Mandatory)][string]$SourceRelative,
    [string]$CorePackageRoot=''
  )
  if ($Scope -eq 'repository_core' -and $CorePackageRoot) {
    $canonical = $SourceRelative.Replace('\','/')
    $prefix = 'src/msplatform'
    if ($canonical -ne $prefix -and -not $canonical.StartsWith($prefix+'/',[StringComparison]::OrdinalIgnoreCase)) {
      throw "Scientific-core dependency escapes its canonical provider: $SourceRelative"
    }
    $core = Get-DependencyCoreRoot -RepoRoot $RepoRoot -CorePackageRoot $CorePackageRoot
    $packageRelative = $canonical.Substring($prefix.Length).TrimStart('/')
    return [IO.Path]::GetFullPath((Join-Path $core $packageRelative))
  }
  return [IO.Path]::GetFullPath((Join-Path $RepoRoot $SourceRelative))
}

function Assert-DependencyProviderIdentity {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$DependencyId,
    [Parameter(Mandatory)][string]$Scope,
    [Parameter(Mandatory)][string]$Provider,
    [Parameter(Mandatory)][string]$ProviderRelative,
    [string]$CorePackageRoot=''
  )
  $normalized = $ProviderRelative.Replace('\','/')
  if ($Scope -eq 'repository_core') {
    if ($Provider -ne 'msplatform' -or $normalized -ne 'src/msplatform') {
      throw "Dependency $DependencyId has an invalid scientific-core provider."
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
    [Parameter(Mandatory)][pscustomobject]$Dependency,
    [string]$CorePackageRoot=''
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
    -Scope $scope -Provider $provider -ProviderRelative $providerRelative -CorePackageRoot $CorePackageRoot

  $repo = [IO.Path]::GetFullPath($RepoRoot)
  $inputs = [IO.Path]::GetFullPath($InputDir)
  $installedCore = $scope -eq 'repository_core' -and $CorePackageRoot
  $providerRoot = if ($installedCore) {
    Get-DependencyCoreRoot -RepoRoot $repo -CorePackageRoot $CorePackageRoot
  } else {
    [IO.Path]::GetFullPath((Join-Path $repo $providerRelative))
  }
  if (-not $installedCore -and -not (Test-DependencyPathWithin -Path $providerRoot -Root $repo)) {
    throw "Dependency $($Dependency.id) provider root escapes the repository."
  }
  $sourceRelative = [string]$Dependency.source_repo_path
  if ([IO.Path]::IsPathRooted($sourceRelative)) {
    throw "Dependency $($Dependency.id) source path must be repository-relative."
  }
  $source = Resolve-DependencySourcePath -RepoRoot $repo -Scope $scope -SourceRelative $sourceRelative -CorePackageRoot $CorePackageRoot
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
    [Parameter(Mandatory)][psobject]$ResolvedDependencies,
    [string]$CorePackageRoot=''
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
  $core = Get-DependencyCoreRoot -RepoRoot $RepoRoot -CorePackageRoot $CorePackageRoot
  $canonicalContract = [IO.Path]::GetFullPath((Join-Path $core 'workflows/config/runtime_dependencies.json'))
  $isCanonicalContract = [IO.Path]::GetFullPath($ContractPath) -eq $canonicalContract
  $relative = if ($isCanonicalContract) {
    'src/msplatform/workflows/config/runtime_dependencies.json'
  } else {
    [IO.Path]::GetRelativePath([IO.Path]::GetFullPath($RepoRoot), [IO.Path]::GetFullPath($ContractPath)).Replace('\','/')
  }
  $contractDependency = [pscustomobject]@{
    id = 'dependency_contract'
    provider_scope = 'repository_core'
    provider_project = 'msplatform'
    provider_repo_path = 'src/msplatform'
    source_repo_path = $relative
    frozen_filename = 'runtime_snapshot/' + $relative
    run_input_name = 'dependency_contract'
    consumers = @($ResolvedDependencies.consumer_ids)
  }
  $contractIdentity = Copy-FrozenDependency -RepoRoot $RepoRoot -InputDir $InputDir -Dependency $contractDependency -CorePackageRoot $CorePackageRoot
  $inventory = [ordered]@{
    schema_version = 1
    role = 'resolved_code_inventory'
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
    [Parameter(Mandatory)][string]$Python,
    [string]$CorePackageRoot=''
  )
  $contract = Get-Content -LiteralPath $ContractPath -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100
  if (@(Compare-Object @('schema_version','role','owner_id','consumer_ids','providers') @($contract.PSObject.Properties.Name)).Count -ne 0 -or
      $contract.schema_version -ne 3 -or $contract.role -cne 'workflow_runtime_dependencies' -or
      $contract.owner_id -cne $OwnerId) {
    throw 'Workflow runtime dependency contract identity or fields differ from schema 3.'
  }
  $consumers = @($contract.consumer_ids)
  if (-not $consumers.Count -or @($consumers | Where-Object { [string]::IsNullOrWhiteSpace($_) }).Count -or
      @($consumers | Select-Object -Unique).Count -ne $consumers.Count -or $consumers -cnotcontains $ConsumerId) {
    throw "Unregistered or invalid runtime dependency consumer: $ConsumerId"
  }
  $repo = [IO.Path]::GetFullPath($RepoRoot)
  $core = Get-DependencyCoreRoot -RepoRoot $repo -CorePackageRoot $CorePackageRoot
  $canonicalContract=[IO.Path]::GetFullPath((Join-Path $core 'workflows/config/runtime_dependencies.json'))
  $isCanonicalContract=[IO.Path]::GetFullPath($ContractPath)-eq$canonicalContract
  $contractRelative=if($isCanonicalContract){'src/msplatform/workflows/config/runtime_dependencies.json'}else{
    [IO.Path]::GetRelativePath($repo, [IO.Path]::GetFullPath($ContractPath)).Replace('\','/')}
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
      'integration' { Get-DependencyIntegrationRoot -RepoRoot $repo -OwnerId $provider -CorePackageRoot $CorePackageRoot }
      default { throw "Unsupported dependency provider scope: $scope" }
    }
    $installedCore = $scope -eq 'repository_core' -and $CorePackageRoot
    $providerRoot = if ($installedCore) { $core } else { [IO.Path]::GetFullPath((Join-Path $repo $providerRelative)) }
    if (-not $installedCore -and -not (Test-DependencyPathWithin -Path $providerRoot -Root $repo)) {
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
      $selectionAbsolute=Resolve-DependencySourcePath -RepoRoot $repo -Scope $scope -SourceRelative $selectionPath -CorePackageRoot $CorePackageRoot
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
    $canonicalPackages=@($group.python_packages | Where-Object { @($_.consumers) -ccontains $ConsumerId })
    $canonicalModules=@($group.python_modules | Where-Object { @($_.consumers) -ccontains $ConsumerId })
    $enumerationPackages=$canonicalPackages;$enumerationModules=$canonicalModules
    if ($installedCore) {
      $enumerationPackages=@($canonicalPackages | ForEach-Object {$copy=$_|Select-Object *;$copy.source_repo_path=$copy.source_repo_path.Substring(4);$copy})
      $enumerationModules=@($canonicalModules | ForEach-Object {$copy=$_|Select-Object *;$copy.source_repo_path=$copy.source_repo_path.Substring(4);$copy})
    }
    $packageGroups.Add([ordered]@{
      provider_scope=$scope; provider_project=$provider; provider_repo_path=$providerRelative
      python_packages=$enumerationPackages; python_modules=$enumerationModules
      canonical_python_packages=$canonicalPackages; canonical_python_modules=$canonicalModules
      source_root=$(if($installedCore){Split-Path -Parent $core}else{$repo})
      enumeration_provider_root=$(if($installedCore){'msplatform'}else{$providerRelative})
      output_prefix=$(if($installedCore){'src/'}else{''})
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
      $source = Resolve-DependencySourcePath -RepoRoot $repo -Scope $scope -SourceRelative $relative -CorePackageRoot $CorePackageRoot
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
workspace = pathlib.Path(sys.argv[1]).resolve()
core_import_root = pathlib.Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else workspace / "src"
sys.path.insert(0, str(core_import_root))
from msplatform.execution.inputs import enumerate_python_sources
request = json.load(sys.stdin)
records = []
for group in request["providers"]:
    packages, modules = group["python_packages"], group["python_modules"]
    if not packages and not modules:
        continue
    source_root = pathlib.Path(group.get("source_root", request.get("source_root")))
    provider_root = group.get("enumeration_provider_root", group["provider_repo_path"])
    # A sole package can include its declared resources in the same traversal.
    # Mixed package selections retain their individual resource boundaries.
    single_package = len(packages) == 1
    paths = set(enumerate_python_sources(source_root,
        package_roots=[row["source_repo_path"] for row in packages],
        module_paths=[row["source_repo_path"] for row in modules],
        provider_root=provider_root, require_python_source=True,
        resource_suffixes=packages[0].get("resource_suffixes", ()) if single_package else ()))
    for row in (() if single_package else packages):
        if "resource_suffixes" in row:
            paths.update(enumerate_python_sources(source_root,
                package_roots=[row["source_repo_path"]], provider_root=provider_root,
                resource_suffixes=row["resource_suffixes"], require_python_source=True))
    canonical_packages = group.get("canonical_python_packages", packages)
    canonical_modules = group.get("canonical_python_modules", modules)
    for enumerated_path in sorted(paths):
        path = group.get("output_prefix", "") + enumerated_path
        consumers = set()
        source = pathlib.PurePosixPath(path)
        for row in canonical_packages + canonical_modules:
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
  $enumerationRequest = @{providers=@($packageGroups.ToArray())} | ConvertTo-Json -Depth 30 -Compress
  $coreImportRoot = if ($CorePackageRoot) { Split-Path -Parent $core } else { Join-Path $repo 'src' }
  $priorEncoding = $OutputEncoding
  $PSNativeCommandUseErrorActionPreference = $false
  try {
    $OutputEncoding = [Text.UTF8Encoding]::new($false)
    $enumeratedJson = @($enumerationRequest | & $Python -X utf8 -I -B -c $enumerator $repo $coreImportRoot 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Python package enumeration failed: $($enumeratedJson -join [Environment]::NewLine)" }
  } finally { $OutputEncoding = $priorEncoding }
  $enumerated = @((($enumeratedJson | ForEach-Object { [string]$_ }) -join "`n") | ConvertFrom-Json -Depth 30)
  foreach ($dependency in $enumerated) {
    $relative = [string]$dependency.source_repo_path
    $id = [string]$dependency.id
    $source = Resolve-DependencySourcePath -RepoRoot $repo -Scope ([string]$dependency.provider_scope) -SourceRelative $relative -CorePackageRoot $CorePackageRoot
    if (-not $ids.Add($id)) { throw "Duplicate derived Python dependency id: $id" }
    if (-not $sources.Add($source)) {
      continue
    }
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
    -InputDir $InputDir -OwnerId $OwnerId -ResolvedDependencies $ResolvedDependencies -CorePackageRoot $CorePackageRoot
  $identities = @(foreach ($dependency in $ResolvedDependencies.dependencies) {
    Copy-FrozenDependency -RepoRoot $RepoRoot -InputDir $InputDir -Dependency $dependency -CorePackageRoot $CorePackageRoot
  })
  return [pscustomobject]@{
    execution_root = Join-Path $InputDir 'runtime_snapshot'
    import_roots = @(Get-RunPythonImportRoots -RepoRoot (Join-Path $InputDir 'runtime_snapshot'))
    code_inventory_path = $publication.code_inventory_path
    dependency_contract_path = $publication.dependency_contract_path
    dependency_contract_identity = $publication.dependency_contract_identity
    identities = $identities
    source_count = $identities.Count
    source_bytes = [long](($identities | Measure-Object -Property bytes -Sum).Sum)
  }
}
