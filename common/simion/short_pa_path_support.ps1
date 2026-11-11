# Legacy repository context only; byte copying and OS guards have one installed owner.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$script:LegacyPaIdentityRepoRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
function Invoke-LegacyPaUnbufferedIdentity {
  param([string]$Source,[int64]$Length)
  $identityRepoRoot=$script:LegacyPaIdentityRepoRoot
  # Select only when a large identity is actually requested, preserving old callers.
  $identityPython=if($env:SIMULATION_PYTHON_EXE){$env:SIMULATION_PYTHON_EXE}else{
    Join-Path $identityRepoRoot '.venv\Scripts\python.exe'
  }
  if(-not(Test-Path -LiteralPath $identityPython -PathType Leaf)){throw "Repository Python is unavailable: $identityPython"}
  $identityModule=Join-Path $identityRepoRoot 'src/msplatform/io/file_identity.py'
  if(-not(Test-Path -LiteralPath $identityModule -PathType Leaf)){throw "Frozen file identity module is unavailable: $identityModule"}
  Push-Location -LiteralPath $identityRepoRoot
  try{
    $digest=@(& $identityPython -I -S -B -X utf8 $identityModule --unbuffered $Source)
    if($LASTEXITCODE-ne0){throw 'Unbuffered immutable PA source verification failed.'}
    return $digest
  }finally{Pop-Location}
}
$payloadResource=Join-Path $script:LegacyPaIdentityRepoRoot 'src/msplatform/execution/resources/payload_file_support.ps1'
if(-not(Test-Path -LiteralPath $payloadResource -PathType Leaf)){throw 'Frozen payload byte resource is unavailable.'}
. $payloadResource -UnbufferedIdentityReader {
  param($Source,$Length)
  Invoke-LegacyPaUnbufferedIdentity -Source $Source -Length $Length
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

function New-ShortPaCopy {
  <#
    Expose a verified PA input to legacy SIMION through a short same-volume
    path using a disposable standalone copy.  Use this only when the specific
    consumer performs a confirmed write-capable operation, such as saving a
    Workbench after Fast Adjust; ordinary IOB load or Fly does not by itself
    imply a PA write.  A hard link is not isolation for a confirmed writer.
    The caller owns family integrity checks and removes the copy before publish.
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
  $sourcePath=[IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Source).Path)
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
      # A manifest is an identity contract, not a live byte observation.
      # Buffered reads of large payloads on this host have returned a false
      # same-length single-byte-different view without a useful timestamp
      # change.  Confirm the first locked source through the unbuffered reader
      # before making several large destination copies.
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
        verification_kind=if($manifestBackedUnbuffered){'locked_unbuffered_manifest_hash'}else{'locked_source_stream'}
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
  $destinationGuard=$null
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
      # Flush the completed standalone destination before checking it.  The
      # historical failure was a buffered reader returning a false unequal
      # view; it was not evidence that the persistent destination was damaged.
      $flushStream=[IO.File]::Open(
        $destinationPath,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::Read
      )
      try{$flushStream.Flush($true)}finally{$flushStream.Dispose()}
      if($MarkDestinationReadOnly-or$GuardDestinationReadOnly){
        $attributes=[IO.File]::GetAttributes($destinationPath)
        [IO.File]::SetAttributes($destinationPath,$attributes-bor[IO.FileAttributes]::ReadOnly)
      }
      $verificationStream=[IO.File]::Open(
        $destinationPath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read
      )
      try{
        $destinationLength=[int64]$verificationStream.Length
        $destinationHash=Get-ImmutablePaSourceVerificationSha256 -Stream $verificationStream -Length $destinationLength
        if($destinationLength-eq$sourceLength -and
         [int64]$sourceGuard.Length-eq$sourceLength -and
         $destinationHash-eq$sourceHash){
          $verified=$true
          if($GuardDestinationReadOnly){
            # Retain the exact handle used by the first identity verification.
            $destinationGuard=$verificationStream;$verificationStream=$null
          }
        }
      }finally{if($null-ne$verificationStream){$verificationStream.Dispose()}}
      if($verified){break}
      $lastFailure="attempt=$attempt source_bytes=$($sourceGuard.Length) destination_bytes=$destinationLength destination_matches=$($destinationHash-eq$sourceHash) source_sha256=$sourceHash destination_sha256=$destinationHash"
      if($attempt-lt$VerificationAttempts){Start-Sleep -Milliseconds 200}
    }
    if(-not$verified){
      throw "Short PA copy verification failed after $VerificationAttempts attempts: $destinationPath ($lastFailure)"
    }
  } catch {
    if($null-ne$destinationGuard){$destinationGuard.Dispose()}
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
  try{
    $sourceGuardRecord.reference_count=[int]$sourceGuardRecord.reference_count+1
    $global:MassSpectrometryShortPaCopies[$destinationPath]=[pscustomobject]@{
      source=$sourcePath
      source_sha256=$sourceHash
      source_bytes=$sourceLength
      source_guard_key=$sourcePath
      destination_guard=$destinationGuard
      verified_destination_guard=$destinationGuard
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
  $sourcePath=[IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Source).Path)
  $destinationPath=[IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Destination).Path)
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
    identity_guarded=($null-ne$record.PSObject.Properties['verified_destination_guard']-and
      $null-ne$record.destination_guard-and
      [object]::ReferenceEquals($record.verified_destination_guard,$record.destination_guard))
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
     The copy remains byte-independent from its cache source. The disposable
     bookkeeping ends here. Only an identity verified under the
     same continuously held handle can avoid another payload read. #>
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$Path,[switch]$KeepDestinationGuard)
  $destination=[IO.Path]::GetFullPath($Path)
  if(-not$global:MassSpectrometryShortPaCopies.ContainsKey($destination)){
    throw "Short PA copy is not registered: $destination"
  }
  $record=$global:MassSpectrometryShortPaCopies[$destination]
  if(-not$global:MassSpectrometryShortPaSourceGuards.ContainsKey([string]$record.source_guard_key)){
    throw "Short PA source guard is missing: $($record.source_guard_key)"
  }
  $sourceGuardRecord=$global:MassSpectrometryShortPaSourceGuards[[string]$record.source_guard_key]
  $identity=Get-ShortPaCopyIdentity -Path $destination
  if(-not$identity.identity_guarded){$identity=Confirm-ShortPaCopyIdentity -Path $destination}
  $sourceCanReuse=($null-ne$sourceGuardRecord.PSObject.Properties['verification_kind']-and
    ($sourceGuardRecord.verification_kind-eq'locked_unbuffered_manifest_hash'-or
     ($sourceGuardRecord.verification_kind-eq'locked_source_stream'-and
      [long]$sourceGuardRecord.length-lt$global:MassSpectrometryShortPaUnbufferedThresholdBytes))-and
    $sourceGuardRecord.stream.CanRead-and
    [long]$sourceGuardRecord.stream.Length-eq[long]$record.source_bytes-and
    $sourceGuardRecord.sha256-eq$record.source_sha256)
  $sourceActual=if($sourceCanReuse){[string]$sourceGuardRecord.sha256}else{
    Get-ImmutablePaSourceVerificationSha256 -Stream $sourceGuardRecord.stream `
      -Length ([int64]$sourceGuardRecord.length)
  }
  if(-not[string]::Equals($sourceActual,[string]$record.source_sha256,[StringComparison]::OrdinalIgnoreCase)){
    throw "Short PA source differs from its frozen identity before publication: $($record.source)"
  }
  if([int]$sourceGuardRecord.reference_count-lt1){throw 'Short PA source has no live copy reference.'}
  $attributes=[IO.File]::GetAttributes($destination)
  [IO.File]::SetAttributes($destination,$attributes-bor[IO.FileAttributes]::ReadOnly)
  if($KeepDestinationGuard){
    if(-not$identity.identity_guarded){
      throw 'Persistent guard handoff requires a continuously verified destination guard.'
    }
    if($global:MassSpectrometryImmutablePaSourceGuards.ContainsKey($destination)){
      throw "Persistent PA destination already has an immutable owner: $destination"
    }
    $global:MassSpectrometryImmutablePaSourceGuards[$destination]=[pscustomobject]@{
      stream=$record.destination_guard;bytes=[int64]$identity.bytes;sha256=[string]$identity.sha256
    }
    $record.destination_guard=$null
  }elseif($null-ne$record.destination_guard){$record.destination_guard.Dispose();$record.destination_guard=$null}
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
