Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if($null-eq(Get-Variable -Name MassSpectrometryShortPaCopies -Scope Global -ErrorAction SilentlyContinue)){
  $global:MassSpectrometryShortPaCopies=@{}
}
if($null-eq(Get-Variable -Name MassSpectrometryShortPaSourceGuards -Scope Global -ErrorAction SilentlyContinue)){
  $global:MassSpectrometryShortPaSourceGuards=@{}
}
if($null-eq(Get-Variable -Name MassSpectrometryImmutablePaSourceGuards -Scope Global -ErrorAction SilentlyContinue)){
  $global:MassSpectrometryImmutablePaSourceGuards=@{}
}
if($null-eq(Get-Variable -Name MassSpectrometryShortPaUnbufferedThresholdBytes -Scope Global -ErrorAction SilentlyContinue)){
  $global:MassSpectrometryShortPaUnbufferedThresholdBytes=8MB
}
# Compatibility aliases for direct callers and tests.  The process-global
# registries are intentional: a batch runner invokes child scripts in nested
# script scopes, while the guarded copies and their open handles must remain
# owned by the creating PowerShell process across those scopes.
$script:ShortPaCopies=$global:MassSpectrometryShortPaCopies
$script:ShortPaSourceGuards=$global:MassSpectrometryShortPaSourceGuards
$script:ShortPaUnbufferedThresholdBytes=$global:MassSpectrometryShortPaUnbufferedThresholdBytes

function Copy-StandalonePaBytes {
  param(
    [Parameter(Mandatory)][IO.FileStream]$SourceStream,
    [Parameter(Mandatory)][string]$Destination,
    [Parameter(Mandatory)][int64]$Length
  )
  if($Length-ge$global:MassSpectrometryShortPaUnbufferedThresholdBytes){
    # On this Windows host, buffered FileStream/Copy-Item copies of multi-GB
    # PA files have reproduced same-length single-byte corruption while the
    # source remained stable.  Robocopy /J is the supported unbuffered path
    # and reproduced the frozen SHA on the same source and volume.
    $sourcePath=[IO.Path]::GetFullPath($SourceStream.Name)
    $destinationPath=[IO.Path]::GetFullPath($Destination)
    $destinationParent=Split-Path -Parent $destinationPath
    $stagingDirectory=Join-Path $destinationParent ('.pa_copy_'+[guid]::NewGuid().ToString('N'))
    $stagingPath=Join-Path $stagingDirectory ([IO.Path]::GetFileName($sourcePath))
    $robocopy=Join-Path $env:SystemRoot 'System32\robocopy.exe'
    if(-not(Test-Path -LiteralPath $robocopy -PathType Leaf)){throw "Robocopy is unavailable: $robocopy"}
    [IO.Directory]::CreateDirectory($stagingDirectory)|Out-Null
    try{
      & $robocopy (Split-Path -Parent $sourcePath) $stagingDirectory ([IO.Path]::GetFileName($sourcePath)) `
        /J /R:0 /W:0 /NFL /NDL /NJH /NJS /NP | Out-Null
      $copyExitCode=$LASTEXITCODE
      if($copyExitCode-ge8){throw "Unbuffered PA copy failed with Robocopy exit code $copyExitCode"}
      if(-not(Test-Path -LiteralPath $stagingPath -PathType Leaf)-or
         (Get-Item -LiteralPath $stagingPath).Length-ne$Length){
        throw 'Unbuffered PA staging copy has the wrong length.'
      }
      [IO.File]::Move($stagingPath,$destinationPath)
    }finally{
      if(Test-Path -LiteralPath $stagingPath -PathType Leaf){
        $attributes=[IO.File]::GetAttributes($stagingPath)
        [IO.File]::SetAttributes($stagingPath,$attributes-band(-bnot[IO.FileAttributes]::ReadOnly))
        [IO.File]::Delete($stagingPath)
      }
      if(Test-Path -LiteralPath $stagingDirectory -PathType Container){
        [IO.Directory]::Delete($stagingDirectory,$false)
      }
    }
    return
  }
  $bufferSize=1MB
  $destinationStream=[IO.FileStream]::new(
    $Destination,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None,
    $bufferSize,([IO.FileOptions]::SequentialScan-bor[IO.FileOptions]::WriteThrough)
  )
  try{
    $SourceStream.Position=0
    $SourceStream.CopyTo($destinationStream,$bufferSize)
    $destinationStream.Flush($true)
  }finally{$destinationStream.Dispose()}
}

function Get-OpenPaStreamSha256 {
  param([Parameter(Mandatory)][IO.FileStream]$Stream)
  $hash=[Security.Cryptography.SHA256]::Create()
  try{
    $Stream.Position=0
    ([BitConverter]::ToString($hash.ComputeHash($Stream))).Replace('-','')
  }finally{
    $Stream.Position=0
    $hash.Dispose()
  }
}

function Confirm-OpenPaStreamSha256 {
  param(
    [Parameter(Mandatory)][IO.FileStream]$Stream,
    [Parameter(Mandatory)][string]$ExpectedSha256,
    [ValidateRange(1,10)][int]$VerificationAttempts=3
  )
  $observed=@()
  for($attempt=1;$attempt-le$VerificationAttempts;$attempt++){
    $actual=Get-OpenPaStreamSha256 -Stream $Stream
    $observed+=$actual
    if($actual-eq$ExpectedSha256){return $true}
    if($attempt-lt$VerificationAttempts){Start-Sleep -Milliseconds 200}
  }
  throw "Open PA source SHA256 did not return to its frozen identity after $VerificationAttempts attempts: expected=$ExpectedSha256 observed=$($observed-join',')"
}

function Get-ImmutablePaSourceVerificationSha256 {
  param(
    [Parameter(Mandatory)][IO.FileStream]$Stream,
    [Parameter(Mandatory)][int64]$Length
  )
  if($Length-lt$global:MassSpectrometryShortPaUnbufferedThresholdBytes){
    return Get-OpenPaStreamSha256 -Stream $Stream
  }
  # A large PA can have a stale buffered source view even while an unbuffered
  # /J copy reproduces the manifest bytes.  Keep the source handle open only as
  # the no-write/no-delete lock and verify one private unbuffered projection.
  $directory=Join-Path ([IO.Path]::GetTempPath()) ('immutable_pa_source_probe_'+[guid]::NewGuid().ToString('N'))
  $probe=Join-Path $directory 'source_probe.pa'
  [IO.Directory]::CreateDirectory($directory)|Out-Null
  try{
    Copy-StandalonePaBytes -SourceStream $Stream -Destination $probe -Length $Length
    $item=Get-Item -LiteralPath $probe -Force
    if([int64]$item.Length-ne$Length){throw 'Immutable PA source probe has the wrong length.'}
    return (Get-FileHash -LiteralPath $probe -Algorithm SHA256).Hash
  }finally{
    if(Test-Path -LiteralPath $probe -PathType Leaf){
      $attributes=[IO.File]::GetAttributes($probe)
      [IO.File]::SetAttributes($probe,$attributes-band(-bnot[IO.FileAttributes]::ReadOnly))
      [IO.File]::Delete($probe)
    }
    if(Test-Path -LiteralPath $directory -PathType Container){
      [IO.Directory]::Delete($directory,$false)
    }
  }
}

function Assert-PublishedPaManifestRecord {
  param(
    [Parameter(Mandatory)][string]$Manifest,
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][int64]$ExpectedBytes,
    [Parameter(Mandatory)][string]$ExpectedSha256
  )
  $document=Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8|ConvertFrom-Json
  $name=[IO.Path]::GetFileName($Source)
  $records=@($document.files|Where-Object{[string]$_.name-ceq$name})
  if($records.Count-ne1){throw "Published PA cache manifest does not uniquely bind source: $Source"}
  if([int64]$records[0].bytes-ne$ExpectedBytes-or
     -not[string]::Equals([string]$records[0].sha256,$ExpectedSha256,[StringComparison]::OrdinalIgnoreCase)){
    throw "Published PA cache manifest identity differs from caller expectation: $Source"
  }
}

function Protect-ImmutablePaSource {
  <# Verify and hold one immutable PA source for this PowerShell process.
     The same read-only handle is used for SHA-256 verification and retained
     with FileShare.Read, so Windows rejects writers, deletion, and replacement
     until an explicit Unprotect call.  Repeating the same request is idempotent. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][int64]$ExpectedBytes,
    [Parameter(Mandatory)][ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$ExpectedSha256
  )
  if($ExpectedBytes-lt0){throw 'Expected immutable PA source byte length must be non-negative.'}
  $sourcePath=(Resolve-Path -LiteralPath $Source).Path
  $expectedHash=$ExpectedSha256.ToUpperInvariant()
  if($global:MassSpectrometryImmutablePaSourceGuards.ContainsKey($sourcePath)){
    $record=$global:MassSpectrometryImmutablePaSourceGuards[$sourcePath]
    if($null-eq$record.stream-or-not$record.stream.CanRead){
      throw "Immutable PA source protection is not live: $sourcePath"
    }
    if([int64]$record.bytes-ne$ExpectedBytes-or
       -not[string]::Equals([string]$record.sha256,$expectedHash,[StringComparison]::Ordinal)){
      throw "Immutable PA source is already protected under a different identity: $sourcePath"
    }
    return [pscustomobject]@{
      path=$sourcePath;bytes=[int64]$record.bytes;sha256=[string]$record.sha256
      write_delete_guarded=$true;already_protected=$true
    }
  }
  $stream=$null
  try{
    $stream=[IO.File]::Open(
      $sourcePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read
    )
    if([int64]$stream.Length-ne$ExpectedBytes){
      throw "Immutable PA source byte length differs from its frozen identity: $sourcePath"
    }
    $actualHash=Get-ImmutablePaSourceVerificationSha256 -Stream $stream -Length $ExpectedBytes
    if(-not[string]::Equals($actualHash,$expectedHash,[StringComparison]::Ordinal)){
      throw "Immutable PA source SHA256 differs from its frozen identity: $sourcePath"
    }
    $global:MassSpectrometryImmutablePaSourceGuards[$sourcePath]=[pscustomobject]@{
      stream=$stream;bytes=[int64]$stream.Length;sha256=$actualHash
    }
    $stream=$null
    [pscustomobject]@{
      path=$sourcePath;bytes=$ExpectedBytes;sha256=$actualHash
      write_delete_guarded=$true;already_protected=$false
    }
  }finally{
    if($null-ne$stream){$stream.Dispose()}
  }
}

function Unprotect-ImmutablePaSource {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$Source)
  $sourcePath=[IO.Path]::GetFullPath($Source)
  if(-not$global:MassSpectrometryImmutablePaSourceGuards.ContainsKey($sourcePath)){
    throw "Immutable PA source is not protected: $sourcePath"
  }
  $record=$global:MassSpectrometryImmutablePaSourceGuards[$sourcePath]
  try{$record.stream.Dispose()}
  finally{$global:MassSpectrometryImmutablePaSourceGuards.Remove($sourcePath)}
  [pscustomobject]@{
    path=$sourcePath;bytes=[int64]$record.bytes;sha256=[string]$record.sha256
    write_delete_guarded=$false
  }
}

function Unprotect-ImmutablePaSourcesUnderDirectory {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$Path)
  $directory=[IO.Path]::GetFullPath($Path).TrimEnd(
    [IO.Path]::DirectorySeparatorChar,[IO.Path]::AltDirectorySeparatorChar
  )
  $prefix=$directory+[IO.Path]::DirectorySeparatorChar
  $sources=@($global:MassSpectrometryImmutablePaSourceGuards.Keys|Where-Object{
    $_.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)
  }|Sort-Object)
  foreach($source in $sources){Unprotect-ImmutablePaSource -Source $source|Out-Null}
  return $sources.Count
}

function Unprotect-AllImmutablePaSources {
  [CmdletBinding()]
  param()
  $sources=@($global:MassSpectrometryImmutablePaSourceGuards.Keys|Sort-Object)
  foreach($source in $sources){Unprotect-ImmutablePaSource -Source $source|Out-Null}
  return $sources.Count
}

function New-ShortPaCopy {
  <#
    Expose a verified PA input to legacy SIMION through a short same-volume
    path using a disposable standalone copy.  SIMION may write a PA after the
    invoking process appears to have finished, so a hard link is not an
    isolation boundary.  The caller owns full family integrity checks and
    must remove the copy directory before publishing a run.
  #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$Destination,
    [int64]$ExpectedBytes=-1,
    [string]$ExpectedSha256='',
    [switch]$MarkDestinationReadOnly,
    [switch]$GuardDestinationReadOnly,
    [ValidateRange(1,10)][int]$VerificationAttempts=3
  )
  if([IO.Path]::GetFileName($Source)-match '\.pa[1-9][0-9]*$'){
    throw "PA-family response members cannot be projected as standalone short PA inputs; publish a freshly constructed standalone response during the disposable family build instead: $Source"
  }
  $expectedHash=''
  if(-not[string]::IsNullOrWhiteSpace($ExpectedSha256)){
    if($ExpectedSha256-notmatch '^[A-Fa-f0-9]{64}$'){throw 'Expected short PA source SHA256 is invalid.'}
    $expectedHash=$ExpectedSha256.ToUpperInvariant()
  }
  $sourcePath=(Resolve-Path -LiteralPath $Source).Path
  if(-not(Test-Path -LiteralPath $sourcePath -PathType Leaf)){
    throw "Short PA source is missing: $sourcePath"
  }
  # A published PA-family generation is never an ambient file source.  Its
  # manifest is the sole byte authority, so forgetting either half of the
  # identity is a programming error rather than a permissive legacy mode.
  $sourceManifest=Join-Path (Split-Path -Parent $sourcePath) 'cache_manifest.json'
  if(Test-Path -LiteralPath $sourceManifest -PathType Leaf){
    if($ExpectedBytes-lt0-or[string]::IsNullOrWhiteSpace($expectedHash)){
      throw "Published PA cache inputs require manifest ExpectedBytes and ExpectedSha256: $sourcePath"
    }
    Assert-PublishedPaManifestRecord -Manifest $sourceManifest -Source $sourcePath `
      -ExpectedBytes $ExpectedBytes -ExpectedSha256 $expectedHash
  }
  $destinationPath=[IO.Path]::GetFullPath($Destination)
  if(Test-Path -LiteralPath $destinationPath){
    throw "Short PA destination already exists: $destinationPath"
  }
  $parent=Split-Path -Parent $destinationPath
  if(-not(Test-Path -LiteralPath $parent -PathType Container)){
    New-Item -ItemType Directory -Path $parent|Out-Null
  }
  # A batch campaign can need many private copies of the same multi-gigabyte
  # PA.  Share one no-write/no-delete source guard and one frozen source hash
  # across those copies.  Each destination is still a distinct verified file;
  # only redundant source hashing is removed.
  $newSourceGuard=$false
  if($global:MassSpectrometryShortPaSourceGuards.ContainsKey($sourcePath)){
    $sourceGuardRecord=$global:MassSpectrometryShortPaSourceGuards[$sourcePath]
  }else{
    $sourceGuard=[IO.File]::Open(
      $sourcePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read
    )
    try{
      $manifestBackedUnbuffered=($ExpectedBytes-ge0-and
        -not[string]::IsNullOrWhiteSpace($expectedHash)-and
        [int64]$sourceGuard.Length-ge$global:MassSpectrometryShortPaUnbufferedThresholdBytes)
      # A manifest is an identity contract, not evidence that the bytes still
      # satisfy it.  Large PA payloads on this host have experienced stable,
      # same-length single-bit changes without a useful timestamp change.  An
      # expected hash therefore must be confirmed from the locked source on
      # first use in this process; trusting the manifest here only discovers a
      # bad source after several multi-gigabyte destination copies.
      $verifiedSourceHash=if($manifestBackedUnbuffered){
        $actual=Get-ImmutablePaSourceVerificationSha256 -Stream $sourceGuard -Length ([int64]$sourceGuard.Length)
        if(-not[string]::Equals($actual,$expectedHash,[StringComparison]::Ordinal)){
          throw "Locked immutable PA source differs from its manifest: expected=$expectedHash actual=$actual"
        }
        $actual
      }else{
        Get-OpenPaStreamSha256 -Stream $sourceGuard
      }
      $sourceGuardRecord=[pscustomobject]@{
        stream=$sourceGuard
        length=[int64]$sourceGuard.Length
        sha256=$verifiedSourceHash
        verification_kind=if($manifestBackedUnbuffered){'locked_unbuffered_manifest_snapshot'}else{'locked_source_stream'}
        reference_count=0
      }
      $global:MassSpectrometryShortPaSourceGuards[$sourcePath]=$sourceGuardRecord
      $newSourceGuard=$true
    }catch{$sourceGuard.Dispose();throw}
  }
  $sourceGuard=$sourceGuardRecord.stream
  $sourceLength=[int64]$sourceGuardRecord.length
  $sourceHash=[string]$sourceGuardRecord.sha256
  if($ExpectedBytes-ge 0 -and $sourceLength-ne$ExpectedBytes){
    if($newSourceGuard){$sourceGuard.Dispose();$global:MassSpectrometryShortPaSourceGuards.Remove($sourcePath)}
    throw "Short PA source byte length differs from its frozen identity: $sourcePath"
  }
  if(-not[string]::IsNullOrWhiteSpace($expectedHash)){
    if($sourceHash-ne$expectedHash){
      if($newSourceGuard){$sourceGuard.Dispose();$global:MassSpectrometryShortPaSourceGuards.Remove($sourcePath)}
      throw "Short PA source SHA256 differs from its frozen identity: $sourcePath"
    }
  }
  try {
    $verified=$false
    $lastFailure='verification did not run'
    for($attempt=1;$attempt-le$VerificationAttempts;$attempt++){
      if(Test-Path -LiteralPath $destinationPath -PathType Leaf){
        $attributes=[IO.File]::GetAttributes($destinationPath)
        [IO.File]::SetAttributes($destinationPath,$attributes-band(-bnot[IO.FileAttributes]::ReadOnly))
        [IO.File]::Delete($destinationPath)
      }
      Copy-StandalonePaBytes -SourceStream $sourceGuard -Destination $destinationPath -Length $sourceLength
      $destinationAttributes=[IO.File]::GetAttributes($destinationPath)
      [IO.File]::SetAttributes($destinationPath,$destinationAttributes-band(-bnot[IO.FileAttributes]::ReadOnly))
      # File.Copy closes its managed handle synchronously, but large PA copies
      # can still sit behind a filesystem/filter-driver write cache.  Force the
      # completed standalone copy through that boundary before hashing it;
      # otherwise a byte-equal source can intermittently compare unequal in a
      # long sequence of several-hundred-megabyte PA projections.
      $flushStream=[IO.File]::Open(
        $destinationPath,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::Read
      )
      try{$flushStream.Flush($true)}finally{$flushStream.Dispose()}
      $destinationItem=Get-Item -LiteralPath $destinationPath -Force
      $destinationHash=(Get-FileHash -LiteralPath $destinationPath -Algorithm SHA256).Hash
      if([int64]$destinationItem.Length-eq$sourceLength -and
         [int64]$sourceGuard.Length-eq$sourceLength -and
         $destinationHash-eq$sourceHash){
        $verified=$true
        break
      }
      $lastFailure="attempt=$attempt source_bytes=$($sourceGuard.Length) destination_bytes=$($destinationItem.Length) destination_matches=$($destinationHash-eq$sourceHash) source_sha256=$sourceHash destination_sha256=$destinationHash"
      if($attempt-lt$VerificationAttempts){Start-Sleep -Milliseconds 200}
    }
    if(-not$verified){
      throw "Short PA copy verification failed after $VerificationAttempts attempts: $destinationPath ($lastFailure)"
    }
  } catch {
    if($newSourceGuard-and[int]$sourceGuardRecord.reference_count-eq0){
      $sourceGuard.Dispose()
      $global:MassSpectrometryShortPaSourceGuards.Remove($sourcePath)
    }
    if(Test-Path -LiteralPath $destinationPath -PathType Leaf){
      $attributes=[IO.File]::GetAttributes($destinationPath)
      [IO.File]::SetAttributes($destinationPath,$attributes-band(-bnot[IO.FileAttributes]::ReadOnly))
      [IO.File]::Delete($destinationPath)
    }
    throw
  }
  $destinationGuard=$null
  try{
    if($MarkDestinationReadOnly-or$GuardDestinationReadOnly){
      $attributes=[IO.File]::GetAttributes($destinationPath)
      [IO.File]::SetAttributes($destinationPath,$attributes-bor[IO.FileAttributes]::ReadOnly)
    }
    if($GuardDestinationReadOnly){
      # A live read-only handle shared only for reads is a stronger invariant
      # than a filesystem attribute: no solver process can reopen this PA for
      # writing or deletion until the owning runner releases the guard.
      $destinationGuard=[IO.File]::Open(
        $destinationPath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read
      )
    }
    $sourceGuardRecord.reference_count=[int]$sourceGuardRecord.reference_count+1
    $global:MassSpectrometryShortPaCopies[$destinationPath]=[pscustomobject]@{
      source=$sourcePath
      source_sha256=$sourceHash
      source_bytes=$sourceLength
      source_guard_key=$sourcePath
      destination_guard=$destinationGuard
      destination_write_guarded=[bool]$GuardDestinationReadOnly
      destination_marked_read_only=[bool]($MarkDestinationReadOnly-or$GuardDestinationReadOnly)
    }
  }catch{
    if($null-ne$destinationGuard){$destinationGuard.Dispose()}
    if($newSourceGuard-and[int]$sourceGuardRecord.reference_count-eq0){
      $sourceGuard.Dispose();$global:MassSpectrometryShortPaSourceGuards.Remove($sourcePath)
    }
    throw
  }
  $destinationPath
}

function Import-ExistingShortPaCopy {
  <# Re-establish process-local read guards for a copy created by a trusted
     parent batch.  This never creates or changes bytes: both source and
     destination are independently opened read-only and hashed before the
     destination is registered in the current PowerShell process. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$Destination,
    [Parameter(Mandatory)][int64]$ExpectedBytes,
    [Parameter(Mandatory)][ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$ExpectedSha256,
    [switch]$TrustLiveOwnerGuard
  )
  $sourcePath=(Resolve-Path -LiteralPath $Source).Path
  $destinationPath=(Resolve-Path -LiteralPath $Destination).Path
  if($global:MassSpectrometryShortPaCopies.ContainsKey($destinationPath)){
    $identity=Confirm-ShortPaCopyIdentity -Path $destinationPath
    if([int64]$identity.bytes-ne$ExpectedBytes-or
       -not[string]::Equals([string]$identity.sha256,$ExpectedSha256,[StringComparison]::OrdinalIgnoreCase)){
      throw "Imported short PA identity differs from the requested identity: $destinationPath"
    }
    return $identity
  }
  $newSourceGuard=$false;$destinationGuard=$null
  try{
    if($global:MassSpectrometryShortPaSourceGuards.ContainsKey($sourcePath)){
      $sourceGuardRecord=$global:MassSpectrometryShortPaSourceGuards[$sourcePath]
    }else{
      $sourceGuard=[IO.File]::Open($sourcePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
      $sourceGuardRecord=[pscustomobject]@{
        stream=$sourceGuard;length=[int64]$sourceGuard.Length
        sha256=if($TrustLiveOwnerGuard){$ExpectedSha256}else{
          Get-ImmutablePaSourceVerificationSha256 -Stream $sourceGuard -Length ([int64]$sourceGuard.Length)
        }
        reference_count=0
      }
      $global:MassSpectrometryShortPaSourceGuards[$sourcePath]=$sourceGuardRecord
      $newSourceGuard=$true
    }
    if([int64]$sourceGuardRecord.length-ne$ExpectedBytes-or
       -not[string]::Equals([string]$sourceGuardRecord.sha256,$ExpectedSha256,[StringComparison]::OrdinalIgnoreCase)){
      throw "Imported short PA source differs from its frozen identity: $sourcePath"
    }
    $attributes=[IO.File]::GetAttributes($destinationPath)
    if(-not[bool]($attributes-band[IO.FileAttributes]::ReadOnly)){
      throw "Imported short PA destination is not read-only: $destinationPath"
    }
    if($TrustLiveOwnerGuard){
      $writeBlocked=$false
      try{
        $writer=[IO.File]::Open(
          $destinationPath,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite
        )
        $writer.Dispose()
      }catch [IO.IOException]{$writeBlocked=$true}
      catch [UnauthorizedAccessException]{$writeBlocked=$true}
      if(-not$writeBlocked){throw "Live owner does not guard imported short PA destination: $destinationPath"}
    }
    $destinationGuard=[IO.File]::Open(
      $destinationPath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read
    )
    $destinationHash=if($TrustLiveOwnerGuard){$ExpectedSha256}else{
      Get-ImmutablePaSourceVerificationSha256 -Stream $destinationGuard -Length ([int64]$destinationGuard.Length)
    }
    if([int64]$destinationGuard.Length-ne$ExpectedBytes-or
       -not[string]::Equals($destinationHash,$ExpectedSha256,[StringComparison]::OrdinalIgnoreCase)){
      throw "Imported short PA destination differs from its frozen identity: $destinationPath"
    }
    $sourceGuardRecord.reference_count=[int]$sourceGuardRecord.reference_count+1
    $global:MassSpectrometryShortPaCopies[$destinationPath]=[pscustomobject]@{
      source=$sourcePath;source_sha256=[string]$sourceGuardRecord.sha256
      source_bytes=[int64]$sourceGuardRecord.length;source_guard_key=$sourcePath
      destination_guard=$destinationGuard;destination_write_guarded=$true
      destination_marked_read_only=$true;imported_existing_copy=$true
    }
    $destinationGuard=$null
    Confirm-ShortPaCopyIdentity -Path $destinationPath
  }catch{
    if($null-ne$destinationGuard){$destinationGuard.Dispose()}
    if($newSourceGuard-and[int]$sourceGuardRecord.reference_count-eq0){
      $sourceGuardRecord.stream.Dispose();$global:MassSpectrometryShortPaSourceGuards.Remove($sourcePath)
    }
    throw
  }
}

function Get-ShortPaCopyIdentity {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$Path)
  $destination=[IO.Path]::GetFullPath($Path)
  if(-not$global:MassSpectrometryShortPaCopies.ContainsKey($destination)){
    throw "Short PA copy is not registered: $destination"
  }
  $record=$global:MassSpectrometryShortPaCopies[$destination]
  $attributes=[IO.File]::GetAttributes($destination)
  $attributeReadOnly=[bool]($attributes-band[IO.FileAttributes]::ReadOnly)
  if([bool]$record.destination_marked_read_only-and-not$attributeReadOnly){
    throw "Short PA destination lost its read-only attribute: $destination"
  }
  if([bool]$record.destination_write_guarded){
    if($null-eq$record.destination_guard-or-not$record.destination_guard.CanRead){
      throw "Short PA destination write guard is not live: $destination"
    }
    if([int64]$record.destination_guard.Length-ne[int64]$record.source_bytes){
      throw "Guarded short PA length changed: $destination"
    }
  }
  [pscustomobject]@{
    path=$destination
    bytes=[int64]$record.source_bytes
    sha256=[string]$record.source_sha256
    destination_read_only=$attributeReadOnly
    destination_write_guarded=[bool]$record.destination_write_guarded
  }
}

function Confirm-ShortPaCopyIdentity {
  <# Verify the disposable copy through one read handle.  A mismatch must be
     followed by two consecutive matching full reads before it is accepted;
     persistent or alternating bytes remain fail-closed. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Path,
    [ValidateRange(1,10)][int]$VerificationAttempts=3
  )
  $destination=[IO.Path]::GetFullPath($Path)
  if(-not$global:MassSpectrometryShortPaCopies.ContainsKey($destination)){
    throw "Short PA copy is not registered: $destination"
  }
  $record=$global:MassSpectrometryShortPaCopies[$destination]
  $identity=Get-ShortPaCopyIdentity -Path $destination
  $ownedStream=$false
  $stream=$record.destination_guard
  if($null-eq$stream){
    $stream=[IO.File]::Open(
      $destination,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read
    )
    $ownedStream=$true
  }
  try{
    $observed=@();$mismatchSeen=$false;$consecutiveMatches=0
    for($attempt=1;$attempt-le$VerificationAttempts;$attempt++){
      $actual=Get-ImmutablePaSourceVerificationSha256 -Stream $stream -Length ([int64]$stream.Length)
      $observed+=$actual
      $matches=([int64]$stream.Length-eq[int64]$record.source_bytes-and
        [string]::Equals($actual,[string]$record.source_sha256,[StringComparison]::OrdinalIgnoreCase))
      if($matches){
        $consecutiveMatches++
        $required=if($mismatchSeen){2}else{1}
        if($consecutiveMatches-ge$required){return $identity}
      }else{
        $mismatchSeen=$true
        $consecutiveMatches=0
      }
      if($attempt-lt$VerificationAttempts){Start-Sleep -Milliseconds 200}
    }
    throw "Short PA destination SHA256 did not reproduce its frozen identity after $VerificationAttempts attempts: expected=$($record.source_sha256) observed=$($observed-join',')"
  }finally{
    if($ownedStream){$stream.Dispose()}
  }
}

function Protect-ShortPaCopyDestination {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$Path)
  $destination=[IO.Path]::GetFullPath($Path)
  if(-not$global:MassSpectrometryShortPaCopies.ContainsKey($destination)){
    throw "Short PA copy is not registered: $destination"
  }
  $record=$global:MassSpectrometryShortPaCopies[$destination]
  if($null-ne$record.destination_guard){
    throw "Short PA destination is already write guarded: $destination"
  }
  $attributes=[IO.File]::GetAttributes($destination)
  [IO.File]::SetAttributes($destination,$attributes-bor[IO.FileAttributes]::ReadOnly)
  $guard=[IO.File]::Open(
    $destination,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read
  )
  $record.destination_guard=$guard
  $record.destination_write_guarded=$true
  $record.destination_marked_read_only=$true
  Get-ShortPaCopyIdentity -Path $destination
}

function Publish-ShortPaCopyDestination {
  <# Convert one verified private PA copy into a persistent read-only artifact.
     The copy remains byte-independent from its cache source.  This closes the
     live no-write handles only after re-reading both sides, unregisters the
     disposable-copy bookkeeping, and deliberately leaves the destination in
     place for a manifest to bind. #>
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$Path)
  $destination=[IO.Path]::GetFullPath($Path)
  if(-not$global:MassSpectrometryShortPaCopies.ContainsKey($destination)){
    throw "Short PA copy is not registered: $destination"
  }
  $record=$global:MassSpectrometryShortPaCopies[$destination]
  if(-not$global:MassSpectrometryShortPaSourceGuards.ContainsKey([string]$record.source_guard_key)){
    throw "Short PA source guard is missing: $($record.source_guard_key)"
  }
  $sourceGuardRecord=$global:MassSpectrometryShortPaSourceGuards[[string]$record.source_guard_key]
  $identity=Confirm-ShortPaCopyIdentity -Path $destination
  $sourceActual=Get-ImmutablePaSourceVerificationSha256 -Stream $sourceGuardRecord.stream `
    -Length ([int64]$sourceGuardRecord.length)
  if(-not[string]::Equals($sourceActual,[string]$record.source_sha256,[StringComparison]::OrdinalIgnoreCase)){
    throw "Short PA source differs from its frozen identity before publication: $($record.source)"
  }
  if($null-ne$record.destination_guard){$record.destination_guard.Dispose();$record.destination_guard=$null}
  $attributes=[IO.File]::GetAttributes($destination)
  [IO.File]::SetAttributes($destination,$attributes-bor[IO.FileAttributes]::ReadOnly)
  $global:MassSpectrometryShortPaCopies.Remove($destination)
  $sourceGuardRecord.reference_count=[int]$sourceGuardRecord.reference_count-1
  if([int]$sourceGuardRecord.reference_count-lt0){throw "Short PA source guard reference count became negative: $($record.source)"}
  if([int]$sourceGuardRecord.reference_count-eq0){
    $sourceGuardRecord.stream.Dispose()
    $global:MassSpectrometryShortPaSourceGuards.Remove([string]$record.source_guard_key)
  }
  [pscustomobject]@{
    path=$destination;bytes=[int64]$identity.bytes;sha256=[string]$identity.sha256
    destination_read_only=$true;published_persistent_copy=$true
  }
}

function Remove-ShortPaCopy {
  <# Remove one registered disposable copy and release its live no-write guards. #>
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$Path)
  $destination=[IO.Path]::GetFullPath($Path)
  if(-not$global:MassSpectrometryShortPaCopies.ContainsKey($destination)){
    throw "Short PA copy is not registered: $destination"
  }
  $record=$global:MassSpectrometryShortPaCopies[$destination]
  if(-not$global:MassSpectrometryShortPaSourceGuards.ContainsKey([string]$record.source_guard_key)){
    throw "Short PA source guard is missing: $($record.source_guard_key)"
  }
  $sourceGuardRecord=$global:MassSpectrometryShortPaSourceGuards[[string]$record.source_guard_key]
  try {
    if($null-ne$record.destination_guard){
      $record.destination_guard.Dispose()
      $record.destination_guard=$null
    }
    if(Test-Path -LiteralPath $destination -PathType Leaf){
      $attributes=[IO.File]::GetAttributes($destination)
      [IO.File]::SetAttributes($destination,$attributes-band(-bnot[IO.FileAttributes]::ReadOnly))
      [IO.File]::Delete($destination)
    }
  } finally {
    try {
      $global:MassSpectrometryShortPaCopies.Remove($destination)
      $sourceGuardRecord.reference_count=[int]$sourceGuardRecord.reference_count-1
      if([int]$sourceGuardRecord.reference_count-lt0){
        throw "Short PA source guard reference count became negative: $($record.source)"
      }
      if([int]$sourceGuardRecord.reference_count-eq0){
        $sourceGuardRecord.stream.Dispose()
        $global:MassSpectrometryShortPaSourceGuards.Remove([string]$record.source_guard_key)
      }
    } finally {}
  }
}

function Remove-ShortPaCopiesUnderDirectory {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Path,
    [string]$ExpectedNamePrefix='simion_pa_links_'
  )
  $directory=[IO.Path]::GetFullPath($Path)
  $temporaryRoot=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar)
  if(-not $directory.StartsWith($temporaryRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -or
     -not([IO.Path]::GetFileName($directory).StartsWith($ExpectedNamePrefix,[StringComparison]::Ordinal))){
    throw "Refusing to remove unverified short-PA link directory: $directory"
  }
  foreach($destination in @($global:MassSpectrometryShortPaCopies.Keys)){
    if(-not $destination.StartsWith($directory+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){continue}
    Remove-ShortPaCopy -Path $destination
  }
}

function Remove-ShortPaCopyDirectory {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Path,
    [string]$ExpectedNamePrefix='simion_pa_links_'
  )
  $directory=[IO.Path]::GetFullPath($Path)
  Remove-ShortPaCopiesUnderDirectory -Path $directory -ExpectedNamePrefix $ExpectedNamePrefix
  if(Test-Path -LiteralPath $directory -PathType Container){
    if((Get-ChildItem -LiteralPath $directory -Force|Measure-Object).Count-ne0){
      throw "Short-PA link directory contains an unregistered entry: $directory"
    }
    [IO.Directory]::Delete($directory,$false)
  }
}

function Remove-PrivatePaFamilyDirectory {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Path,
    [string]$ExpectedNamePrefix='simion_pa_family_'
  )
  $directory=[IO.Path]::GetFullPath($Path)
  $temporaryRoot=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([IO.Path]::DirectorySeparatorChar)
  if(-not $directory.StartsWith($temporaryRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -or
     -not([IO.Path]::GetFileName($directory).StartsWith($ExpectedNamePrefix,[StringComparison]::Ordinal))){
    throw "Refusing to remove unverified private PA-family directory: $directory"
  }
  if(Test-Path -LiteralPath $directory -PathType Container){
    Remove-Item -LiteralPath $directory -Recurse -Force
  }
}

function Remove-IobSeedPlaceholderCompanions {
  <#
    Remove only the canonical PA companions that SIMION needs while loading
    an IOB instance seed.  A saved IOB contains the replacement PA filenames,
    so callers invoke this only after inspecting both the execution-path and
    relocated IOB.  The seed IOB itself is retained as provenance.
  #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Directory,
    [ValidateRange(1,10)][int]$Count
  )
  $resolvedDirectory=(Resolve-Path -LiteralPath $Directory).Path
  $removed=@()
  for($index=1;$index-le$Count;$index++){
    $name='iob_seed_placeholder_{0:D2}.pa0'-f$index
    $path=Join-Path $resolvedDirectory $name
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){
      throw "IOB seed placeholder companion is missing before cleanup: $path"
    }
    $item=Get-Item -LiteralPath $path -Force
    $removed+=[pscustomobject]@{name=$name;bytes=[int64]$item.Length}
  }
  foreach($record in $removed){
    $path=Join-Path $resolvedDirectory $record.name
    $attributes=[IO.File]::GetAttributes($path)
    [IO.File]::SetAttributes($path,$attributes-band(-bnot[IO.FileAttributes]::ReadOnly))
    [IO.File]::Delete($path)
  }
  foreach($record in $removed){
    $path=Join-Path $resolvedDirectory $record.name
    if(Test-Path -LiteralPath $path){throw "IOB seed placeholder cleanup did not remove: $path"}
  }
  [pscustomobject]@{
    removed_count=$removed.Count
    removed_bytes=[int64](@($removed|ForEach-Object{$_.bytes})|Measure-Object -Sum).Sum
    retained_seed_iob=$true
  }
}

# Compatibility names for already-frozen project runners.  Despite the legacy
# names these delegate to isolated copies; they never create hard links.
function New-ShortPaHardLink {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$Destination
  )
  New-ShortPaCopy -Source $Source -Destination $Destination
}

function Remove-ShortPaHardLinkDirectory {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Path,
    [string]$ExpectedNamePrefix='simion_pa_links_'
  )
  Remove-ShortPaCopyDirectory -Path $Path -ExpectedNamePrefix $ExpectedNamePrefix
}
