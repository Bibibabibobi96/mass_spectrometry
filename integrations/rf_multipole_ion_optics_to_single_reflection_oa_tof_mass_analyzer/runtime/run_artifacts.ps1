Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')

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

function Get-RfFlightTubePaBuildGeometryIdentity {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)]$Geometry,
    [Parameter(Mandatory)]$Build
  )
  # This PA is a grounded collision shield.  Keep its cache identity exactly
  # to the values passed to build_flight_tube_variant.lua, rather than the
  # larger resolved OATOF document that also carries runtime electrode values.
  return [ordered]@{
    schema_version=1
    geometry_mm=[ordered]@{
      flight_tube_r=[double]$Geometry.flight_tube_r
      flight_tube_wall=[double]$Geometry.flight_tube_wall
      shield_endcap_thickness=[double]$Geometry.shield_endcap_thickness
      shield_outer_z_min=[double]$Geometry.shield_outer_z_min
      flight_length=[double]$Geometry.L_flight
    }
    mesh=[ordered]@{
      cell_axial_mm=[double]$Build.cell_axial_mm
      cell_radial_mm=[double]$Build.cell_radial_mm
      max_gib=[double]$Build.max_gib
    }
  }
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

function Set-RfCachePayloadReadOnly {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$CacheEntry)
  $entry = [IO.Path]::GetFullPath($CacheEntry).TrimEnd(
    [IO.Path]::DirectorySeparatorChar
  )
  $manifest = Get-Content -LiteralPath (Join-Path $entry 'cache_manifest.json') `
    -Raw -Encoding UTF8 | ConvertFrom-Json
  if ([int]$manifest.schema_version -ne 3) {
    throw 'Only schema-v3 cache payloads can be protected as immutable.'
  }
  foreach ($record in @($manifest.files)) {
    $path = [IO.Path]::GetFullPath((Join-Path $entry ([string]$record.name)))
    if (-not (Split-Path -Parent $path).Equals(
        $entry,[StringComparison]::OrdinalIgnoreCase)) {
      throw 'Cache payload path escaped its content-addressed entry.'
    }
    $item = Get-Item -LiteralPath $path -Force
    if ($item.PSIsContainer) { throw 'Cache payload record is not a regular file.' }
    $item.IsReadOnly = $true
  }
}

function Set-RfMaterializedCacheFileWritable {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$Path)
  $item = Get-Item -LiteralPath $Path -Force
  if ($item.PSIsContainer) { throw 'Materialized cache payload is not a regular file.' }
  $item.IsReadOnly = $false
}

function Clear-RfCacheEntryReadOnly {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$CacheEntry)
  foreach ($item in Get-ChildItem -LiteralPath $CacheEntry -File -Force) {
    $item.IsReadOnly = $false
  }
}

function Test-RfCacheManifestPayloadSha256 {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$CacheEntry,
        [Parameter(Mandatory)]$Manifest)
  try {
    $records = @($Manifest.files | ForEach-Object {
      $name = [string]$_.name
      $path = Join-Path $CacheEntry $name
      if ([IO.Path]::GetFileName($name) -ne $name -or
          -not (Test-Path -LiteralPath $path -PathType Leaf) -or
          [int64](Get-Item -LiteralPath $path).Length -ne [int64]$_.bytes -or
          (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -cne
            [string]$_.sha256) {
        throw 'Cache payload file differs from its manifest.'
      }
      [ordered]@{name=$name;bytes=[int64]$_.bytes;sha256=[string]$_.sha256}
    })
    if ($records.Count -eq 0) { return $false }
    $payloadInput = $records | ConvertTo-Json -Depth 8 -Compress
    $payloadSha256 = [Convert]::ToHexString(
      [Security.Cryptography.SHA256]::HashData(
        [Text.Encoding]::UTF8.GetBytes($payloadInput)
      )
    ).ToLowerInvariant()
    return $payloadSha256 -ceq [string]$Manifest.payload_sha256
  } catch {
    return $false
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
    [Parameter(Mandatory)][string]$Role,
    [ValidateSet('remove','preserve')][string]$InvalidEntryAction = 'remove'
  )
  try {
    $entry = Resolve-RfCurrentCacheGeneration -CacheRoot $CacheRoot -CacheKey $CacheKey -Role $Role
  } catch { return $false }
  $manifest = Join-Path $entry 'cache_manifest.json'
  if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { return $false }
  try {
    $manifestDocument = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 |
      ConvertFrom-Json
  } catch { return $false }
  if (-not (Test-RfCacheManifestPayloadSha256 -CacheEntry $entry `
      -Manifest $manifestDocument)) {
    return $false
  }
  $verificationExitCode = 0
  try {
    & $Python (Join-Path $RepoRoot 'common\contracts\verify_artifact_layout.py') `
      (Join-Path $WorkspaceRoot 'artifacts\projects') --cache-entry $entry `
      --expected-cache-role $Role --expected-cache-key $CacheKey `
      --expected-cache-project $ProjectId *> $null
    $verificationExitCode = $LASTEXITCODE
  } catch {
    $verificationExitCode = if ($LASTEXITCODE) { $LASTEXITCODE } else { 1 }
  }
  if ($verificationExitCode -eq 0) {
    Set-RfCachePayloadReadOnly -CacheEntry $entry
    return $true
  }
  $global:LASTEXITCODE = 0
  # A content-addressed generation is evidence even when damaged.  Rebuilders
  # publish a fresh generation and move the pointer; they never erase it.
  $null = Test-Path -LiteralPath $entry
  return $false
}

function Test-RfVerifiedLegacyV2CacheEntry {
  <#
  Verify a schema-v2 cache in place.  Ordinary consumers may reuse this
  immutable payload directly when its physical build identity and every
  manifest-recorded file hash match.  It intentionally does not publish a
  v3 generation or mutate the legacy key directory.
  #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$CacheRoot,
    [Parameter(Mandatory)][string]$CacheKey,
    [Parameter(Mandatory)][string]$Role,
    [Parameter(Mandatory)]$Identity
  )
  if ((Get-RfContentIdentitySha256 -Identity $Identity) -ne $CacheKey) {
    return $false
  }
  $entry = Join-Path $CacheRoot $CacheKey
  Assert-RfCacheEntryPath -CacheRoot $CacheRoot -CacheKey $CacheKey -CacheEntry $entry
  $manifestPath = Join-Path $entry 'cache_manifest.json'
  if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { return $false }
  try {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
  } catch { return $false }
  if ([int]$manifest.schema_version -ne 2 -or $manifest.role -ne $Role -or
      $manifest.cache_key -ne $CacheKey -or
      [string]::IsNullOrWhiteSpace([string]$manifest.provider_run_id) -or
      $null -eq $manifest.identity -or $null -eq $manifest.files) {
    return $false
  }
  # The content-addressed key is the canonical physical-build identity.
  # Do not compare PowerShell's JSON serialization: its property order is an
  # implementation detail and must not turn the same PA into a cache miss.
  if ((Get-RfContentIdentitySha256 -Identity $manifest.identity) -ne $CacheKey) {
    return $false
  }
  try {
    & $Python -m common.contracts.file_identity --root $entry --manifest $manifestPath *> $null
    return $LASTEXITCODE -eq 0
  } catch {
    return $false
  }
}

function Resolve-RfReusableCacheDirectory {
  <# Return a verified v3 generation or a verified schema-v2 key root. #>
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
    [ValidateSet('remove','preserve')][string]$InvalidEntryAction = 'remove'
  )
  if (Test-RfReusableCacheEntry -Python $Python -RepoRoot $RepoRoot `
      -WorkspaceRoot $WorkspaceRoot -ProjectId $ProjectId -CacheRoot $CacheRoot `
      -CacheKey $CacheKey -Role $Role -InvalidEntryAction $InvalidEntryAction) {
    return (Resolve-RfCurrentCacheGeneration -CacheRoot $CacheRoot `
      -CacheKey $CacheKey -Role $Role)
  }
  # A true legacy v2 entry has no generation pointer.  If a pointer is
  # present but cannot be resolved, the cache is a broken partial migration;
  # do not silently fall back to its mutable root files.  Returning a miss
  # lets the caller publish a verified v3 generation alongside the old data.
  $legacyPointer = Join-Path (Join-Path $CacheRoot $CacheKey) 'current_generation.json'
  if (-not (Test-Path -LiteralPath $legacyPointer -PathType Leaf) -and
      (Test-RfVerifiedLegacyV2CacheEntry -Python $Python -RepoRoot $RepoRoot `
      -CacheRoot $CacheRoot -CacheKey $CacheKey `
      -Role $Role -Identity $Identity)) {
    return (Join-Path $CacheRoot $CacheKey)
  }
  return $null
}

function Resolve-RfCurrentCacheGeneration {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$CacheRoot,
    [Parameter(Mandatory)][string]$CacheKey,
    [Parameter(Mandatory)][string]$Role
  )
  $keyDirectory = Join-Path $CacheRoot $CacheKey
  Assert-RfCacheEntryPath -CacheRoot $CacheRoot -CacheKey $CacheKey -CacheEntry $keyDirectory
  $pointerPath = Join-Path $keyDirectory 'current_generation.json'
  if (-not (Test-Path -LiteralPath $pointerPath -PathType Leaf)) {
    throw 'Cache generation pointer is missing.'
  }
  $pointer = Get-Content -LiteralPath $pointerPath -Raw -Encoding UTF8 | ConvertFrom-Json
  $generationKey = [string]$pointer.generation_sha256
  $payloadSha256 = [string]$pointer.payload_sha256
  if ([int]$pointer.schema_version -ne 1 -or $pointer.role -ne $Role -or
      $pointer.cache_key -ne $CacheKey -or $generationKey -notmatch '^[a-f0-9]{64}$' -or
      $payloadSha256 -notmatch '^[A-Fa-f0-9]{64}$' -or
      $pointer.generation_relative_path -ne "generations/$generationKey") {
    throw 'Cache generation pointer is invalid.'
  }
  return Join-Path $keyDirectory "generations\$generationKey"
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

function Enter-RfCacheKeyLock {
  <#
  Serializes the complete verify/build/publish transaction for one cache key.
  The mutex is process-local to this Windows host and leaves no artifact in the
  content-addressed cache tree.
  #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$CacheRoot,
    [Parameter(Mandatory)][string]$CacheKey,
    [ValidateRange(1, 7200)][int]$TimeoutSeconds = 3600
  )
  Assert-RfCacheEntryPath -CacheRoot $CacheRoot -CacheKey $CacheKey `
    -CacheEntry (Join-Path $CacheRoot $CacheKey)
  $root = [IO.Path]::GetFullPath($CacheRoot).TrimEnd(
    [IO.Path]::DirectorySeparatorChar
  ).ToUpperInvariant()
  $seed = "$root|$CacheKey"
  $hash = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData(
      [Text.Encoding]::UTF8.GetBytes($seed)
    )
  ).ToLowerInvariant()
  $mutex = [Threading.Mutex]::new($false, "Local\rf_oatof_cache_$hash")
  try {
    try {
      if (-not $mutex.WaitOne([TimeSpan]::FromSeconds($TimeoutSeconds))) {
        throw "Timed out waiting for cache-key lock: $CacheKey"
      }
    } catch [Threading.AbandonedMutexException] {
      # Windows transfers ownership with this exception after a crashed owner.
    }
    return $mutex
  } catch {
    $mutex.Dispose()
    throw
  }
}

function Exit-RfCacheKeyLock {
  [CmdletBinding()]
  param([Parameter(Mandatory)][Threading.Mutex]$Mutex)
  try {
    $Mutex.ReleaseMutex()
  } finally {
    $Mutex.Dispose()
  }
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
  $keyDirectory = Join-Path $root $CacheKey
  Assert-RfCacheEntryPath -CacheRoot $root -CacheKey $CacheKey -CacheEntry $keyDirectory
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
  $payloadInput = $records | ConvertTo-Json -Depth 8 -Compress
  $payloadSha256 = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($payloadInput))
  ).ToLowerInvariant()
  $generationInput = [ordered]@{
    schema_version=1; cache_key=$CacheKey; payload_sha256=$payloadSha256
    provider_run_id=$ProviderRunId
  } | ConvertTo-Json -Depth 8 -Compress
  $generationSha256 = [Convert]::ToHexString(
    [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($generationInput))
  ).ToLowerInvariant()
  $generationRoot = Join-Path $keyDirectory 'generations'
  $target = Join-Path $generationRoot $generationSha256
  Write-RunJson -Path (Join-Path $staging 'cache_manifest.json') -Depth 14 -Value ([ordered]@{
    schema_version=3; role=$Role; cache_key=$CacheKey; provider_run_id=$ProviderRunId
    cache_key_input=$cacheKeyInput; identity=$Identity; payload_sha256=$payloadSha256
    generation_sha256=$generationSha256; generation_input=$generationInput; files=$records
  })
  New-Item -ItemType Directory -Path $generationRoot -Force | Out-Null
  if (Test-Path -LiteralPath $target) {
    Remove-Item -LiteralPath $staging -Recurse -Force
  } else {
    Move-Item -LiteralPath $staging -Destination $target
  }
  $pointerStage = Join-Path $keyDirectory ('current_generation.' + [guid]::NewGuid().ToString('N') + '.json')
  Write-RunJson -Path $pointerStage -Depth 8 -Value ([ordered]@{
    schema_version=1; role=$Role; cache_key=$CacheKey
    generation_sha256=$generationSha256; payload_sha256=$payloadSha256
    generation_relative_path="generations/$generationSha256"
  })
  $pointer = Join-Path $keyDirectory 'current_generation.json'
  Move-Item -LiteralPath $pointerStage -Destination $pointer -Force
  if (-not (Test-RfReusableCacheEntry -Python $Python -RepoRoot $RepoRoot `
      -WorkspaceRoot $WorkspaceRoot -ProjectId $ProjectId -CacheRoot $root `
      -CacheKey $CacheKey -Role $Role)) {
    throw 'Published cache generation did not pass the shared verifier.'
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
  if (-not (Test-RunFilesIdentical -Left $source -Right $Destination)) {
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
  Write-RunJson -Path $stageBudget -Value ([ordered]@{
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
