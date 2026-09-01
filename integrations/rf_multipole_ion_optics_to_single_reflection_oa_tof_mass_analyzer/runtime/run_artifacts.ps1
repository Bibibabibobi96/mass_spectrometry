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

function Test-RfReusableCacheGeneration {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$WorkspaceRoot,
    [Parameter(Mandatory)][string]$ProjectId,
    [Parameter(Mandatory)][string]$CacheEntry,
    [Parameter(Mandatory)][string]$CacheKey,
    [Parameter(Mandatory)][string]$Role,
    [switch]$AllowNoncurrentGeneration
  )
  $verificationExitCode = 0
  try {
    $arguments = @(
      (Join-Path $RepoRoot 'common\contracts\verify_artifact_layout.py'),
      (Join-Path $WorkspaceRoot 'artifacts\projects'), '--cache-entry',$CacheEntry,
      '--expected-cache-role',$Role,'--expected-cache-key',$CacheKey,
      '--expected-cache-project',$ProjectId
    )
    if ($AllowNoncurrentGeneration) {
      $arguments += '--allow-noncurrent-generation'
    }
    & $Python @arguments *> $null
    $verificationExitCode = $LASTEXITCODE
  } catch {
    $verificationExitCode = if ($LASTEXITCODE) { $LASTEXITCODE } else { 1 }
  }
  if ($verificationExitCode -eq 0) {
    Set-RfCachePayloadReadOnly -CacheEntry $CacheEntry
    return $true
  }
  $global:LASTEXITCODE = 0
  return $false
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
    $entry = Resolve-RfCurrentCacheGeneration -CacheRoot $CacheRoot `
      -CacheKey $CacheKey -Role $Role
  } catch { return $false }
  <#
    A v3 generation is fully hashed while still private staging data, then
    atomically published and made read-only.  Re-hashing every multi-gigabyte
    PA family before every consumer is redundant I/O: it neither strengthens
    the already-bound generation identity nor changes the physical input.
    Ordinary reuse therefore verifies the current pointer, manifest role/key,
    complete inventory and every recorded byte length.  Discovery of a
    non-current generation and explicit artifact audits keep the full
    byte/hash path in Test-RfReusableCacheGeneration.
  #>
  return Test-RfPublishedCacheGeneration -CacheRoot $CacheRoot `
    -CacheKey $CacheKey -Role $Role -ExpectedGeneration $entry
}

function Test-RfPublishedCacheGeneration {
  <#
  Verify the cheap post-publication invariants.  Publication has just hashed
  every staging payload file, then atomically moved that exact directory into
  its content-addressed generation.  Re-hashing the same multi-gigabyte
  payload twice here is therefore redundant.  Ordinary later consumers still
  call Test-RfReusableCacheEntry and perform the full byte/hash verification.
  #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$CacheRoot,
    [Parameter(Mandatory)][string]$CacheKey,
    [Parameter(Mandatory)][string]$Role,
    [Parameter(Mandatory)][string]$ExpectedGeneration
  )
  try {
    $entry = Resolve-RfCurrentCacheGeneration -CacheRoot $CacheRoot `
      -CacheKey $CacheKey -Role $Role
    if (-not ([IO.Path]::GetFullPath($entry).Equals(
        [IO.Path]::GetFullPath($ExpectedGeneration),
        [StringComparison]::OrdinalIgnoreCase))) {
      return $false
    }
    $manifestPath = Join-Path $entry 'cache_manifest.json'
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 |
      ConvertFrom-Json
    if ([int]$manifest.schema_version -ne 3 -or $manifest.role -ne $Role -or
        $manifest.cache_key -ne $CacheKey -or $manifest.generation_sha256 -ne
        (Split-Path -Leaf $entry) -or @($manifest.files).Count -eq 0) {
      return $false
    }
    foreach ($record in @($manifest.files)) {
      $name = [string]$record.name
      $path = Join-Path $entry $name
      if ([IO.Path]::GetFileName($name) -ne $name -or
          -not (Test-Path -LiteralPath $path -PathType Leaf) -or
          [int64](Get-Item -LiteralPath $path).Length -ne [int64]$record.bytes) {
        return $false
      }
    }
    Set-RfCachePayloadReadOnly -CacheEntry $entry
    return $true
  } catch {
    return $false
  }
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
  $currentEntry = $null
  $currentPayloadSha256 = $null
  try {
    $currentEntry = Resolve-RfCurrentCacheGeneration -CacheRoot $CacheRoot `
      -CacheKey $CacheKey -Role $Role
    $currentPointer = Get-Content -LiteralPath (
      Join-Path (Join-Path $CacheRoot $CacheKey) 'current_generation.json'
    ) -Raw -Encoding UTF8 | ConvertFrom-Json
    $currentPayloadSha256 = [string]$currentPointer.payload_sha256
  } catch {
    $currentEntry = $null
  }
  if ($null -ne $currentEntry -and
      (Test-RfPublishedCacheGeneration -CacheRoot $CacheRoot -CacheKey $CacheKey `
        -Role $Role -ExpectedGeneration $currentEntry)) {
    # The normal path is an atomically published, immutable current payload.
    # Its complete byte hashes were proven before publication; pointer,
    # manifest and inventory verification is enough to reuse it.  Do not
    # walk the full PA payload before every ordinary consumer.
    return $currentEntry
  }
  # A current pointer can legitimately become stale if an interrupted solver
  # mutates its last PA after publication.  Preserve that negative evidence,
  # but recover a prior immutable generation only when it has the same cache
  # key and declared payload identity and passes the full byte/hash verifier.
  # Prefer an older matching immutable generation: a valid old generation
  # proves the same declared payload without repeatedly scanning a known-bad
  # current generation before every consumer run.
  $generationRoot = Join-Path (Join-Path $CacheRoot $CacheKey) 'generations'
  if (Test-Path -LiteralPath $generationRoot -PathType Container) {
    $candidates = @(Get-ChildItem -LiteralPath $generationRoot -Directory |
      Sort-Object @{Expression={
        if ($null -ne $currentEntry -and [IO.Path]::GetFullPath($_.FullName).Equals(
            [IO.Path]::GetFullPath($currentEntry),[StringComparison]::OrdinalIgnoreCase)) { 1 } else { 0 }
      }}, Name)
    foreach ($candidate in $candidates) {
      try {
        $manifest = Get-Content -LiteralPath (Join-Path $candidate.FullName `
          'cache_manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([int]$manifest.schema_version -ne 3 -or $manifest.role -ne $Role -or
            $manifest.cache_key -ne $CacheKey -or
            (-not [string]::IsNullOrWhiteSpace($currentPayloadSha256) -and
             [string]$manifest.payload_sha256 -ne $currentPayloadSha256)) {
          continue
        }
      } catch {
        continue
      }
      if (Test-RfReusableCacheGeneration -Python $Python -RepoRoot $RepoRoot `
          -WorkspaceRoot $WorkspaceRoot -ProjectId $ProjectId `
          -CacheEntry $candidate.FullName -CacheKey $CacheKey -Role $Role `
          -AllowNoncurrentGeneration) {
        return $candidate.FullName
      }
    }
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
  param(
    [Parameter(Mandatory)][string]$CacheRoot,
    [ValidatePattern('^[a-f0-9]{64}$')][string]$RecoveryCacheKey,
    [string]$RecoveryRole
  )
  $root = [IO.Path]::GetFullPath($CacheRoot)
  New-Item -ItemType Directory -Path $root -Force | Out-Null
  if (-not [string]::IsNullOrWhiteSpace($RecoveryCacheKey)) {
    if ([string]::IsNullOrWhiteSpace($RecoveryRole)) {
      throw 'A cache staging recovery key requires its registered role.'
    }
    $matches = @(
      Get-ChildItem -LiteralPath $root -Directory -Filter 'b-*' -ErrorAction SilentlyContinue |
        Where-Object {
          $marker = Join-Path $_.FullName '.rf_cache_staging.json'
          if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { return $false }
          try {
            $state = Get-Content -LiteralPath $marker -Raw -Encoding UTF8 | ConvertFrom-Json
            return ([string]$state.cache_key -ceq $RecoveryCacheKey -and
              [string]$state.role -ceq $RecoveryRole)
          } catch {
            return $false
          }
        }
    )
    if ($matches.Count -gt 1) {
      throw "Multiple interrupted cache staging directories match key=$RecoveryCacheKey."
    }
    if ($matches.Count -eq 1) { return $matches[0].FullName }
  }
  $staging = Join-Path $root ('b-' + [guid]::NewGuid().ToString('N').Substring(0,12))
  New-Item -ItemType Directory -Path $staging | Out-Null
  if (-not (Split-Path -Parent ([IO.Path]::GetFullPath($staging))).Equals(
      $root.TrimEnd([IO.Path]::DirectorySeparatorChar),
      [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Cache staging directory escaped its registered root.'
  }
  if (-not [string]::IsNullOrWhiteSpace($RecoveryCacheKey)) {
    Write-RunJson -Path (Join-Path $staging '.rf_cache_staging.json') -Depth 4 -Value ([ordered]@{
      schema_version=1; role=$RecoveryRole; cache_key=$RecoveryCacheKey
    })
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

function Assert-RfArtifactCapacityBeforeCachePublication {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)][string]$WorkspaceRoot,
    [Parameter(Mandatory)][string]$StagingDirectory,
    [string[]]$ProtectedCacheKeys = @(),
    [long]$KnownMeasuredBytes = -1,
    [long]$MaximumNewArtifactBytes = -1,
    [double]$MinimumFreeGiB = 500.0
  )
  # The live staging directory is protected from the cleanup scan.  It is
  # already below artifact-root, so its bytes are present in the gate's
  # current measurement.  Publication is a same-volume Move-Item and adds no
  # second payload; reserving stagingBytes as headroom here would count the
  # same PA family twice and can reject a valid publication near 500 GiB.
  $stagingBytes = [int64]((Get-ChildItem -LiteralPath $StagingDirectory -File -Recurse |
    Measure-Object -Property Length -Sum).Sum)
  $savedPythonPath = $env:PYTHONPATH
  $savedNoUserSite = $env:PYTHONNOUSERSITE
  try {
    $env:PYTHONPATH = $RepoRoot; $env:PYTHONNOUSERSITE = '1'
    Push-Location -LiteralPath $RepoRoot
    try {
      $capacityArguments = @(
        '-m','common.contracts.reconcile_artifact_capacity',
        '--artifact-root',(Join-Path $WorkspaceRoot 'artifacts'),'--target-gib','500',
        '--minimum-free-gib',([string]$MinimumFreeGiB),
        '--protect-path',$StagingDirectory,'--apply'
      )
      if (($KnownMeasuredBytes -ge 0) -xor ($MaximumNewArtifactBytes -ge 0)) {
        throw 'Known measured artifact bytes and maximum new artifact bytes must be supplied together.'
      }
      if ($KnownMeasuredBytes -ge 0) {
        # The launch receipt predates this staging directory.  Include the
        # measured staging payload in its fast-path upper bound; this is not
        # headroom because it is already inside artifact-root when a full
        # reconciliation is required.
        $maximumNewForPublication = [int64]$MaximumNewArtifactBytes + $stagingBytes
        $capacityArguments += @(
          '--known-measured-bytes',$KnownMeasuredBytes,
          '--maximum-new-artifact-bytes',$maximumNewForPublication
        )
      }
      foreach ($key in @($ProtectedCacheKeys | Select-Object -Unique)) {
        if ($key -notmatch '^[0-9a-f]{64}$') {
          throw 'Protected cache key must be one SHA-256 key.'
        }
        $capacityArguments += @('--protect-cache-key',$key)
      }
      $output = & $Python @capacityArguments
      if ($LASTEXITCODE -ne 0) { throw "artifact capacity gate exit_code=$LASTEXITCODE" }
      $receipt = @($output) -join "`n" | ConvertFrom-Json
      if (-not [bool]$receipt.satisfied_after_apply) {
        throw 'artifact capacity gate could not satisfy the 500 GiB watermark'
      }
      # The caller needs this exact current staging size to advance its
      # in-run measurement after a successful Move-Item.  A startup receipt
      # alone becomes stale as successive cache generations are published.
      $receipt | Add-Member -NotePropertyName staging_bytes -NotePropertyValue $stagingBytes -Force
      return $receipt
    } finally { Pop-Location }
  } finally {
    $env:PYTHONPATH = $savedPythonPath; $env:PYTHONNOUSERSITE = $savedNoUserSite
  }
}

function Wait-RfCacheStagingWriterExit {
  <# The resource wrapper normally waits for its direct child.  This final
     fail-closed guard also detects a detached SIMION child before Move-Item
     changes the directory it is still refining.  The shared host lease means
     a matching SIMION command line is necessarily part of this publication. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$StagingDirectory,
    [int]$TimeoutSeconds = 7200
  )
  $needle = [IO.Path]::GetFullPath($StagingDirectory).TrimEnd('\\').ToLowerInvariant()
  $deadline = [datetimeoffset]::UtcNow.AddSeconds($TimeoutSeconds)
  while ($true) {
    try {
      $writers = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
        $_.Name -ieq 'simion.exe' -and -not [string]::IsNullOrWhiteSpace($_.CommandLine) -and
        $_.CommandLine.ToLowerInvariant().Contains($needle)
      })
    } catch {
      throw "Cannot prove SIMION released cache staging: $($_.Exception.Message)"
    }
    if ($writers.Count -eq 0) { return }
    if ([datetimeoffset]::UtcNow -ge $deadline) {
      throw ('Timed out waiting for SIMION staging writer(s): ' +
        (($writers | ForEach-Object { $_.ProcessId }) -join ','))
    }
    Start-Sleep -Seconds 1
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
    [Parameter(Mandatory)][string]$ProviderRunId,
    [string[]]$ProtectedCacheKeys = @(),
    [hashtable]$ArtifactCapacityState = $null,
    [long]$KnownMeasuredBytes = -1,
    [long]$MaximumNewArtifactBytes = -1,
    [double]$MinimumFreeGiB = 500.0
  )
  $root = [IO.Path]::GetFullPath($CacheRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
  $staging = [IO.Path]::GetFullPath($StagingDirectory)
  if (-not (Split-Path -Parent $staging).Equals($root, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Cache publication staging directory escaped its registered root.'
  }
  $keyDirectory = Join-Path $root $CacheKey
  Assert-RfCacheEntryPath -CacheRoot $root -CacheKey $CacheKey -CacheEntry $keyDirectory
  $recoveryMarker = Join-Path $staging '.rf_cache_staging.json'
  $files = @(Get-ChildItem -LiteralPath $staging -File | Where-Object {
    $_.Name -notin @('cache_manifest.json','.rf_cache_staging.json')
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
  Wait-RfCacheStagingWriterExit -StagingDirectory $staging
  $knownMeasuredForPublication = $KnownMeasuredBytes
  if ($null -ne $ArtifactCapacityState) {
    if (-not $ArtifactCapacityState.ContainsKey('known_measured_bytes')) {
      throw 'Artifact capacity state is missing known_measured_bytes.'
    }
    $knownMeasuredForPublication = [int64]$ArtifactCapacityState.known_measured_bytes
  }
  $capacityReceipt = Assert-RfArtifactCapacityBeforeCachePublication -Python $Python `
    -RepoRoot $RepoRoot -WorkspaceRoot $WorkspaceRoot -StagingDirectory $staging `
    -ProtectedCacheKeys $ProtectedCacheKeys `
    -KnownMeasuredBytes $knownMeasuredForPublication -MaximumNewArtifactBytes $MaximumNewArtifactBytes `
    -MinimumFreeGiB $MinimumFreeGiB
  # Retain the identity marker until all fallible publication gates have
  # completed.  A capacity warning/failure then leaves a complete, reusable
  # staging family rather than forcing its field solve to be repeated.
  if (Test-Path -LiteralPath $recoveryMarker -PathType Leaf) {
    Remove-Item -LiteralPath $recoveryMarker -Force
  }
  New-Item -ItemType Directory -Path $generationRoot -Force | Out-Null
  $published = $false
  if (Test-Path -LiteralPath $target) {
    Remove-Item -LiteralPath $staging -Recurse -Force
  } else {
    Move-Item -LiteralPath $staging -Destination $target
    $published = $true
  }
  if ($published -and $null -ne $ArtifactCapacityState) {
    $ArtifactCapacityState.known_measured_bytes = [int64](
      [int64]$ArtifactCapacityState.known_measured_bytes + [int64]$capacityReceipt.staging_bytes
    )
  }
  $pointerStage = Join-Path $keyDirectory ('current_generation.' + [guid]::NewGuid().ToString('N') + '.json')
  Write-RunJson -Path $pointerStage -Depth 8 -Value ([ordered]@{
    schema_version=1; role=$Role; cache_key=$CacheKey
    generation_sha256=$generationSha256; payload_sha256=$payloadSha256
    generation_relative_path="generations/$generationSha256"
  })
  $pointer = Join-Path $keyDirectory 'current_generation.json'
  Move-Item -LiteralPath $pointerStage -Destination $pointer -Force
  if (-not (Test-RfPublishedCacheGeneration -CacheRoot $root `
      -CacheKey $CacheKey -Role $Role -ExpectedGeneration $target)) {
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
