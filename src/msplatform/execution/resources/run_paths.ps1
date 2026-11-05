Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Get-ExecutionPathCapacity {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RunDirectory,
    [string[]]$AdditionalDirectories=@(),
    [string[]]$ExpectedExecutionRelativePaths=@()
  )
  # 259 is the largest path accepted by legacy Win32 callers (MAX_PATH minus
  # the terminating NUL).  This is deliberately a compatibility diagnostic,
  # not a claim about a particular solver's own path limit.
  $legacyWindowsPathLimit=259
  $relativePaths=@(
    'inputs','results','logs','run_config.json','summary.json','run_manifest.json'
  )
  $relativePaths+=$AdditionalDirectories
  $relativePaths+=$ExpectedExecutionRelativePaths
  $entries=foreach($relative in $relativePaths|Sort-Object -Unique){
    if([string]::IsNullOrWhiteSpace($relative)){
      throw 'Execution path capacity entries must not be empty.'
    }
    if([IO.Path]::IsPathRooted($relative)-or
       $relative.Split([IO.Path]::DirectorySeparatorChar,[IO.Path]::AltDirectorySeparatorChar)-contains'..'){
      throw "Execution path capacity entry must be a contained relative path: $relative"
    }
    $path=[IO.Path]::GetFullPath((Join-Path $RunDirectory $relative))
    [pscustomobject]@{
      relative_path=$relative.Replace('\','/');path=$path;length=$path.Length
      legacy_windows_path_limit=$legacyWindowsPathLimit
      remaining_legacy_windows_characters=$legacyWindowsPathLimit-$path.Length
      legacy_windows_compatible=($path.Length-le$legacyWindowsPathLimit)
    }
  }
  $longest=@($entries|Sort-Object length -Descending|Select-Object -First 1)
  return [pscustomobject]@{
    schema_version=1;role='run_package_execution_path_capacity'
    run_directory=[IO.Path]::GetFullPath($RunDirectory)
    legacy_windows_path_limit=$legacyWindowsPathLimit
    entries=@($entries);longest_path=$longest[0]
    legacy_windows_compatible=(@($entries|Where-Object{-not$_.legacy_windows_compatible}).Count-eq 0)
  }
}

function Assert-ExecutionPathCapacity {
  [CmdletBinding()]
  param([Parameter(Mandatory)][pscustomobject]$Report)
  if($Report.legacy_windows_compatible){return $Report}
  $overLimit=@($Report.entries|Where-Object{-not$_.legacy_windows_compatible}|Select-Object -First 1)[0]
  $message=('EXECUTION_PATH_CAPACITY=FAIL PATH={0} LENGTH={1} LEGACY_WINDOWS_LIMIT={2} '+
    'REMEDIATION=choose a shorter MASS_SPECTROMETRY_EXECUTION_ROOT or shorten the declared relative path.') -f
    $overLimit.path,$overLimit.length,$overLimit.legacy_windows_path_limit
  throw $message
}

function New-ManagedExecutionAlias {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$TargetDirectory,
    [string[]]$AdditionalDirectories=@(),
    [string[]]$ExpectedExecutionRelativePaths=@(),
    [Parameter(Mandatory)][string]$ExecutionRoot,
    [string]$AliasName=''
  )
  $target=[IO.Path]::GetFullPath($TargetDirectory)
  if(-not(Test-Path -LiteralPath $target -PathType Container)){
    throw "Execution alias target directory is missing: $target"
  }

  $executionRootPath=[IO.Path]::GetFullPath($ExecutionRoot)
  if($AliasName-and$AliasName-notmatch'^source_[a-f0-9]{64}_[1-9][0-9]*$'){throw 'Explicit source alias name must bind its request identity and ordinal.'}
  $alias=Join-Path $executionRootPath $(if($AliasName){$AliasName}else{'run_'+[guid]::NewGuid().ToString('N')})
  if(Test-Path -LiteralPath $alias){
    $existing=Get-Item -LiteralPath $alias -Force
    if($existing.LinkType-ne'Junction'-or
       [IO.Path]::GetFullPath([string]@($existing.Target)[0])-ine$target){throw 'Existing execution alias target or owner differs.'}
    throw 'Same-owner execution alias already exists; retain it and return to its original owner context.'
  }
  $pathCapacity=Get-ExecutionPathCapacity -RunDirectory $alias `
    -AdditionalDirectories $AdditionalDirectories `
    -ExpectedExecutionRelativePaths $ExpectedExecutionRelativePaths
  $null=Assert-ExecutionPathCapacity -Report $pathCapacity
  New-Item -ItemType Directory -Force -Path $executionRootPath|Out-Null
  try{
    New-Item -ItemType Junction -Path $alias -Target $target|Out-Null
  }catch{
    throw "Could not create short execution alias $alias for target ${target}: $($_.Exception.Message)"
  }
  return [pscustomobject]@{
    target_directory=$target;execution_alias=$alias;execution_path_capacity=$pathCapacity
  }
}

function Remove-ManagedExecutionAlias {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$ExecutionAlias,
    [Parameter(Mandatory)][string]$TargetDirectory
  )
  $alias=[IO.Path]::GetFullPath($ExecutionAlias)
  $targetDirectory=[IO.Path]::GetFullPath($TargetDirectory)
  if(-not(Test-Path -LiteralPath $alias -PathType Container)){return}
  $item=Get-Item -LiteralPath $alias -Force
  if($item.LinkType-ne'Junction'){
    throw "Execution alias is not a junction: $alias"
  }
  $target=[IO.Path]::GetFullPath([string]@($item.Target)[0])
  if(-not $target.Equals($targetDirectory,[StringComparison]::OrdinalIgnoreCase)){
    throw "Execution alias target differs from expected target: $alias"
  }
  [IO.Directory]::Delete($alias)
}
