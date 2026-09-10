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
    [Parameter(Mandatory)][string]$Destination
  )
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
  $sourceHash=(Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
  try {
    [IO.File]::Copy($sourcePath,$destinationPath,$false)
    $destinationAttributes=[IO.File]::GetAttributes($destinationPath)
    [IO.File]::SetAttributes($destinationPath,$destinationAttributes-band(-bnot[IO.FileAttributes]::ReadOnly))
    $destinationItem=Get-Item -LiteralPath $destinationPath -Force
    $destinationHash=(Get-FileHash -LiteralPath $destinationPath -Algorithm SHA256).Hash
    $sourceHashAfter=(Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
    if($destinationItem.Length-ne$sourceItem.Length -or $destinationHash-ne$sourceHash -or $sourceHashAfter-ne$sourceHash){
      throw "Short PA copy verification failed: $destinationPath"
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
  if(Test-Path -LiteralPath $directory -PathType Container){
    if((Get-ChildItem -LiteralPath $directory -Force|Measure-Object).Count-ne0){
      throw "Short-PA link directory contains an unregistered entry: $directory"
    }
    [IO.Directory]::Delete($directory,$false)
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
