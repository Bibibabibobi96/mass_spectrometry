Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$script:ShortPaCopies=@{}
$script:ShortPaUnbufferedThresholdBytes=8MB

function Copy-StandalonePaBytes {
  param(
    [Parameter(Mandatory)][IO.FileStream]$SourceStream,
    [Parameter(Mandatory)][string]$Destination,
    [Parameter(Mandatory)][int64]$Length
  )
  $bufferSize=if($Length-ge$script:ShortPaUnbufferedThresholdBytes){8MB}else{1MB}
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
    [ValidateRange(1,10)][int]$VerificationAttempts=3
  )
  if([IO.Path]::GetFileName($Source)-match '\.pa[1-9][0-9]*$'){
    throw "PA-family response members cannot be projected as standalone short PA inputs; publish a freshly constructed standalone response during the disposable family build instead: $Source"
  }
  $sourcePath=(Resolve-Path -LiteralPath $Source).Path
  if(-not(Test-Path -LiteralPath $sourcePath -PathType Leaf)){
    throw "Short PA source is missing: $sourcePath"
  }
  $destinationPath=[IO.Path]::GetFullPath($Destination)
  if(Test-Path -LiteralPath $destinationPath){
    throw "Short PA destination already exists: $destinationPath"
  }
  $parent=Split-Path -Parent $destinationPath
  if(-not(Test-Path -LiteralPath $parent -PathType Container)){
    New-Item -ItemType Directory -Path $parent|Out-Null
  }
  # Keep a no-write/no-delete sharing handle open for the complete lifetime of
  # the disposable copy.  This proves that a cache payload cannot be changed
  # by another solver or maintenance process between preflight and cleanup.
  $sourceGuard=[IO.File]::Open(
    $sourcePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read
  )
  $sourceLength=[int64]$sourceGuard.Length
  $sourceHash=Get-OpenPaStreamSha256 -Stream $sourceGuard
  if($ExpectedBytes-ge 0 -and $sourceLength-ne$ExpectedBytes){
    $sourceGuard.Dispose()
    throw "Short PA source byte length differs from its frozen identity: $sourcePath"
  }
  if(-not[string]::IsNullOrWhiteSpace($ExpectedSha256)){
    if($ExpectedSha256-notmatch '^[A-Fa-f0-9]{64}$'){
      $sourceGuard.Dispose()
      throw 'Expected short PA source SHA256 is invalid.'
    }
    if($sourceHash-ne$ExpectedSha256){
      $sourceGuard.Dispose()
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
      $sourceLengthAfter=[int64]$sourceGuard.Length
      $sourceHashAfter=Get-OpenPaStreamSha256 -Stream $sourceGuard
      if([int64]$destinationItem.Length-eq$sourceLength -and
         $sourceLengthAfter-eq$sourceLength -and
         $destinationHash-eq$sourceHash -and $sourceHashAfter-eq$sourceHash){
        $verified=$true
        break
      }
      $lastFailure="attempt=$attempt source_bytes=$sourceLengthAfter destination_bytes=$($destinationItem.Length) source_stable=$($sourceHashAfter-eq$sourceHash) destination_matches=$($destinationHash-eq$sourceHash) source_sha256=$sourceHash destination_sha256=$destinationHash"
      if($attempt-lt$VerificationAttempts){Start-Sleep -Milliseconds 200}
    }
    if(-not$verified){
      throw "Short PA copy verification failed after $VerificationAttempts attempts: $destinationPath ($lastFailure)"
    }
  } catch {
    $sourceGuard.Dispose()
    if(Test-Path -LiteralPath $destinationPath -PathType Leaf){
      $attributes=[IO.File]::GetAttributes($destinationPath)
      [IO.File]::SetAttributes($destinationPath,$attributes-band(-bnot[IO.FileAttributes]::ReadOnly))
      [IO.File]::Delete($destinationPath)
    }
    throw
  }
  $script:ShortPaCopies[$destinationPath]=[pscustomobject]@{
    source=$sourcePath
    source_sha256=$sourceHash
    source_guard=$sourceGuard
  }
  $destinationPath
}

function Remove-ShortPaCopy {
  <# Remove one registered disposable copy and prove its immutable source did
     not change while the copy was in use. #>
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$Path)
  $destination=[IO.Path]::GetFullPath($Path)
  if(-not$script:ShortPaCopies.ContainsKey($destination)){
    throw "Short PA copy is not registered: $destination"
  }
  $record=$script:ShortPaCopies[$destination]
  try {
    if(Test-Path -LiteralPath $destination -PathType Leaf){
      $attributes=[IO.File]::GetAttributes($destination)
      [IO.File]::SetAttributes($destination,$attributes-band(-bnot[IO.FileAttributes]::ReadOnly))
      [IO.File]::Delete($destination)
    }
  } finally {
    try {
      if(Test-Path -LiteralPath $record.source -PathType Leaf){
        $sourceHashAfter=Get-OpenPaStreamSha256 -Stream $record.source_guard
        if($sourceHashAfter-ne$record.source_sha256){
          throw "Short PA source changed while a disposable copy was in use: $($record.source)"
        }
      }
    } finally {
      $record.source_guard.Dispose()
      $script:ShortPaCopies.Remove($destination)
    }
  }
}

function Remove-ShortPaCopyDirectory {
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
  foreach($destination in @($script:ShortPaCopies.Keys)){
    if(-not $destination.StartsWith($directory+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){continue}
    Remove-ShortPaCopy -Path $destination
  }
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
