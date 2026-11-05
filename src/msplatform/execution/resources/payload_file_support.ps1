<# Unique format-independent byte copy/hash and immutable source handles.
   No alias, PA parser, family eligibility, host discovery or scheduler. #>
param([scriptblock]$UnbufferedIdentityReader)
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

if($PSBoundParameters.ContainsKey('UnbufferedIdentityReader')){
  $script:PayloadUnbufferedIdentityReader=$UnbufferedIdentityReader
}elseif($null-eq(Get-Variable -Name PayloadUnbufferedIdentityReader -Scope Script -ErrorAction SilentlyContinue)){
  $script:PayloadUnbufferedIdentityReader=$null
}

function Copy-StandalonePaBytes {
  param(
    [Parameter(Mandatory)][IO.FileStream]$SourceStream,
    [Parameter(Mandatory)][string]$Destination,
    [Parameter(Mandatory)][int64]$Length
  )
  if($Length-ge$global:MassSpectrometryShortPaUnbufferedThresholdBytes){
    # On this Windows host, buffered reads of multi-GB PA copies have returned
    # a false same-length single-byte-different view while an unbuffered read
    # recovered the frozen persistent bytes.  Robocopy /J keeps this staging
    # path independent of that ambiguous buffered view.
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

function Get-ImmutablePaSourceVerificationSha256 {
  param(
    [Parameter(Mandatory)][IO.FileStream]$Stream,
    [Parameter(Mandatory)][int64]$Length
  )
  if($Length-lt$global:MassSpectrometryShortPaUnbufferedThresholdBytes){
    return Get-OpenPaStreamSha256 -Stream $Stream
  }
  # Keep the caller's no-write/no-delete handle throughout the direct
  # unbuffered read. The shared Python API owns Win32 alignment and failure
  # handling; no temporary PA projection or buffered fallback is needed.
  if(-not$Stream.CanRead-or$Stream.Length-ne$Length){throw 'Immutable PA source stream length differs.'}
  if($null-eq$script:PayloadUnbufferedIdentityReader){throw 'An explicit unbuffered identity reader is required.'}
  $digest=@(& $script:PayloadUnbufferedIdentityReader -Source $Stream.Name -Length $Length)
  if($digest.Count-ne1-or[string]$digest[0]-cnotmatch'^[0-9A-F]{64}$'-or$Stream.Length-ne$Length){
    throw 'Unbuffered immutable PA identity output or source length differs.'
  }
  return [string]$digest[0]
}

function Protect-ImmutablePaSource {
  <# Verify and hold one immutable PA source for this PowerShell process.
     The same read-only handle is used for SHA-256 verification and retained
     with FileShare.Read, so Windows rejects writers, deletion, and replacement
     until an explicit Unprotect call. Repeating the same request is idempotent.
     Omit both expected fields only to establish a newly stopped writer's identity. #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$Source,
    [int64]$ExpectedBytes,
    [ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$ExpectedSha256
  )
  $hasExpected=$PSBoundParameters.ContainsKey('ExpectedBytes')
  if($hasExpected-ne$PSBoundParameters.ContainsKey('ExpectedSha256')){throw 'Immutable PA expected byte length and SHA256 must be supplied together.'}
  if($ExpectedBytes-lt0){throw 'Expected immutable PA source byte length must be non-negative.'}
  # Resolve against the PS location, then use the same key spelling as release.
  $sourcePath=[IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Source).Path)
  $expectedHash=if($hasExpected){$ExpectedSha256.ToUpperInvariant()}else{$null}
  if($global:MassSpectrometryImmutablePaSourceGuards.ContainsKey($sourcePath)){
    $record=$global:MassSpectrometryImmutablePaSourceGuards[$sourcePath]
    if($null-eq$record.stream-or-not$record.stream.CanRead){
      throw "Immutable PA source protection is not live: $sourcePath"
    }
    if($hasExpected-and([int64]$record.bytes-ne$ExpectedBytes-or
       -not[string]::Equals([string]$record.sha256,$expectedHash,[StringComparison]::Ordinal))){
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
    if($hasExpected-and[int64]$stream.Length-ne$ExpectedBytes){
      throw "Immutable PA source byte length differs from its frozen identity: $sourcePath"
    }
    if(-not$hasExpected){$ExpectedBytes=[int64]$stream.Length}
    # Open our own handle while the original verified source guard is still
    # live. Ownership remains separate, with no interval permitting a writer.
    $copySource=$global:MassSpectrometryShortPaSourceGuards[$sourcePath]
    $canReuse=($hasExpected-and$null-ne$copySource-and
      $null-ne$copySource.PSObject.Properties['verification_kind']-and
      ($copySource.verification_kind-eq'locked_unbuffered_manifest_hash'-or
       ($copySource.verification_kind-eq'locked_source_stream'-and
        $ExpectedBytes-lt$global:MassSpectrometryShortPaUnbufferedThresholdBytes))-and
      $copySource.stream.CanRead-and[long]$copySource.stream.Length-eq$ExpectedBytes-and
      [long]$copySource.length-eq$ExpectedBytes-and$copySource.sha256-eq$expectedHash)
    $actualHash=if($canReuse){$expectedHash}else{
      Get-ImmutablePaSourceVerificationSha256 -Stream $stream -Length $ExpectedBytes
    }
    if($hasExpected-and-not[string]::Equals($actualHash,$expectedHash,[StringComparison]::Ordinal)){
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
