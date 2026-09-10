Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$script:ShortPaHardLinks=@{}

function New-ShortPaHardLink {
  <#
    Expose a verified PA input to legacy SIMION through a short same-volume
    path without copying its bytes. The caller owns source integrity checks
    and must remove the link directory before publishing a run.
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
  if([IO.Path]::GetPathRoot($sourcePath)-ne[IO.Path]::GetPathRoot($destinationPath)){
    throw 'Short PA hard links require source and destination on the same volume.'
  }
  $parent=Split-Path -Parent $destinationPath
  if(-not(Test-Path -LiteralPath $parent -PathType Container)){
    New-Item -ItemType Directory -Path $parent|Out-Null
  }
  $hardLinkTarget=if($sourcePath.StartsWith('\\?\')){$sourcePath}else{'\\?\'+$sourcePath}
  $sourceAttributes=[IO.File]::GetAttributes($sourcePath)
  try {
    $link=New-Item -ItemType HardLink -Path $destinationPath -Target $hardLinkTarget
    if($link.LinkType-ne'HardLink' -or $link.Length-ne(Get-Item -LiteralPath $sourcePath).Length){
      throw "Short PA hard-link verification failed: $destinationPath"
    }
  } catch {
    if(Test-Path -LiteralPath $destinationPath -PathType Leaf){
      $attributes=[IO.File]::GetAttributes($destinationPath)
      [IO.File]::SetAttributes($destinationPath,$attributes-band(-bnot[IO.FileAttributes]::ReadOnly))
      [IO.File]::Delete($destinationPath)
      [IO.File]::SetAttributes($sourcePath,$sourceAttributes)
    }
    throw
  }
  $script:ShortPaHardLinks[$destinationPath]=[pscustomobject]@{
    source=$sourcePath
    source_attributes=$sourceAttributes
  }
  $destinationPath
}

function Remove-ShortPaHardLinkDirectory {
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
  foreach($destination in @($script:ShortPaHardLinks.Keys)){
    if(-not $destination.StartsWith($directory+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){continue}
    $record=$script:ShortPaHardLinks[$destination]
    try {
      if(Test-Path -LiteralPath $destination -PathType Leaf){
        $attributes=[IO.File]::GetAttributes($destination)
        [IO.File]::SetAttributes($destination,$attributes-band(-bnot[IO.FileAttributes]::ReadOnly))
        [IO.File]::Delete($destination)
      }
    } finally {
      if(Test-Path -LiteralPath $record.source -PathType Leaf){
        [IO.File]::SetAttributes($record.source,[IO.FileAttributes]$record.source_attributes)
      }
      $script:ShortPaHardLinks.Remove($destination)
    }
  }
  if(Test-Path -LiteralPath $directory -PathType Container){
    if((Get-ChildItem -LiteralPath $directory -Force|Measure-Object).Count-ne0){
      throw "Short-PA link directory contains an unregistered entry: $directory"
    }
    [IO.Directory]::Delete($directory,$false)
  }
}
