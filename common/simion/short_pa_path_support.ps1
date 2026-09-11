Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$script:ShortPaCopies=@{}

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
  $sourceItem=Get-Item -LiteralPath $sourcePath -Force
  $sourceLength=[int64]$sourceItem.Length
  $sourceHash=(Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
  if($ExpectedBytes-ge 0 -and $sourceLength-ne$ExpectedBytes){
    throw "Short PA source byte length differs from its frozen identity: $sourcePath"
  }
  if(-not[string]::IsNullOrWhiteSpace($ExpectedSha256)){
    if($ExpectedSha256-notmatch '^[A-Fa-f0-9]{64}$'){
      throw 'Expected short PA source SHA256 is invalid.'
    }
    if($sourceHash-ne$ExpectedSha256){
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
      [IO.File]::Copy($sourcePath,$destinationPath,$false)
      $destinationAttributes=[IO.File]::GetAttributes($destinationPath)
      [IO.File]::SetAttributes($destinationPath,$destinationAttributes-band(-bnot[IO.FileAttributes]::ReadOnly))
      $destinationItem=Get-Item -LiteralPath $destinationPath -Force
      $destinationHash=(Get-FileHash -LiteralPath $destinationPath -Algorithm SHA256).Hash
      $sourceItemAfter=Get-Item -LiteralPath $sourcePath -Force
      $sourceHashAfter=(Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
      if([int64]$destinationItem.Length-eq$sourceLength -and
         [int64]$sourceItemAfter.Length-eq$sourceLength -and
         $destinationHash-eq$sourceHash -and $sourceHashAfter-eq$sourceHash){
        $verified=$true
        break
      }
      $lastFailure="attempt=$attempt source_bytes=$($sourceItemAfter.Length) destination_bytes=$($destinationItem.Length) source_stable=$($sourceHashAfter-eq$sourceHash) destination_matches=$($destinationHash-eq$sourceHash)"
      if($attempt-lt$VerificationAttempts){Start-Sleep -Milliseconds 200}
    }
    if(-not$verified){
      throw "Short PA copy verification failed after $VerificationAttempts attempts: $destinationPath ($lastFailure)"
    }
  } catch {
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
    if(Test-Path -LiteralPath $record.source -PathType Leaf){
      $sourceHashAfter=(Get-FileHash -LiteralPath $record.source -Algorithm SHA256).Hash
      if($sourceHashAfter-ne$record.source_sha256){
        throw "Short PA source changed while a disposable copy was in use: $($record.source)"
      }
    }
    $script:ShortPaCopies.Remove($destination)
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
