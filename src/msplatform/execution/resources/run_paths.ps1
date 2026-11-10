Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Project-RunPath {
  [CmdletBinding(DefaultParameterSetName='Single')]
  param([Parameter(Mandatory,ParameterSetName='Single')][string]$Path,
    [Parameter(Mandatory,ParameterSetName='Many')][AllowEmptyCollection()][string[]]$Paths,
    [Parameter(Mandatory)][string]$ArtifactRunDir,[Parameter(Mandatory)][string]$RunDir,
    [Parameter(Mandatory)][string]$Python)
  if(-not[IO.Path]::IsPathFullyQualified($Python)-or-not(Test-Path -LiteralPath $Python -PathType Leaf)){
    throw 'Run path projection requires an explicit absolute Python executable.'
  }
  $selected=@($Path)
  if($PSCmdlet.ParameterSetName-eq'Many'){$selected=@($Paths)}
  $request=@{operation='project';arguments=@{paths=@($selected);artifact_run_dir=$ArtifactRunDir;run_dir=$RunDir}}
  # This resource belongs to either the selected frozen src tree or ordinary
  # site-packages. Bind its sibling Python owner, never another active install.
  $packageRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
  $bootstrap=@'
import sys
from pathlib import Path
root=Path(sys.argv[1]).resolve()
selected=root/'msplatform/execution/run_paths.py'
if not selected.is_file():raise FileNotFoundError('Selected run-path Python resource is missing: '+str(selected))
sys.path.insert(0,str(root))
from msplatform.execution import run_paths
if Path(run_paths.__file__).resolve()!=selected.resolve():raise ImportError('Run-path Python owner is outside its selected resource package')
run_paths._stdin_project_paths()
'@
  $start=[Diagnostics.ProcessStartInfo]::new()
  $start.FileName=$Python;$start.WorkingDirectory=$PSScriptRoot
  $start.UseShellExecute=$false;$start.CreateNoWindow=$true
  $start.RedirectStandardInput=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
  $start.StandardInputEncoding=[Text.UTF8Encoding]::new($false)
  $start.StandardOutputEncoding=[Text.UTF8Encoding]::new($false)
  $start.StandardErrorEncoding=[Text.UTF8Encoding]::new($false)
  foreach($argument in @('-I','-B','-c',$bootstrap,$packageRoot)){$start.ArgumentList.Add($argument)}
  $process=[Diagnostics.Process]::Start($start)
  try{
    $outputTask=$process.StandardOutput.ReadToEndAsync();$errorTask=$process.StandardError.ReadToEndAsync()
    $process.StandardInput.WriteLine(($request|ConvertTo-Json -Depth 12 -Compress));$process.StandardInput.Close()
    $process.WaitForExit()
    $output=$outputTask.GetAwaiter().GetResult();$errorText=$errorTask.GetAwaiter().GetResult()
    if($process.ExitCode-ne0){throw "Run path projection failed: $errorText"}
    $result=$output|ConvertFrom-Json -Depth 12 -NoEnumerate
    if($PSCmdlet.ParameterSetName-eq'Single'){return $result[0]}
    return ,@($result)
  }finally{$process.Dispose()}
}

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


function Get-RunNativeExecutionContext {
  <# Inspect only the actual native plan; keep persistent identity canonical. #>
  [CmdletBinding()]
  param([Parameter(Mandatory)][pscustomobject]$Package,
    [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$Paths,
    [string]$ExecutionRoot='',[string]$Tool='native tool')
  $watch=[Diagnostics.Stopwatch]::StartNew()
  $persistent=[IO.Path]::GetFullPath([string]$Package.artifact_run_dir).TrimEnd('\','/')
  if($null-ne$Package.execution_alias-and-not(Test-Path -LiteralPath ([string]$Package.execution_alias) -PathType Container)){
    # A persisted package may outlive its disposable execution representation.
    # Re-evaluate this native plan from its unchanged persistent identity.
    $Package.run_dir=$persistent;$Package.execution_alias=$null;$Package.execution_path_capacity=$null
  }
  $execution=[string]$Package.run_dir
  $relativePaths=@();$external=@()
  foreach($path in $Paths){
    if(-not[IO.Path]::IsPathFullyQualified($path)){throw "Native plan path must be absolute: $path"}
    $full=[IO.Path]::GetFullPath($path)
    if($full.Equals($persistent,[StringComparison]::OrdinalIgnoreCase)){$relativePaths+='.'}
    elseif($full.StartsWith($persistent+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){
      $relativePaths+=[IO.Path]::GetRelativePath($persistent,$full)
    }elseif($full.StartsWith($execution.TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){
      $relativePaths+=[IO.Path]::GetRelativePath($execution,$full)
    }else{
      $external+=$full
    }
  }
  $capacity=Get-ExecutionPathCapacity -RunDirectory $execution -ExpectedExecutionRelativePaths $relativePaths
  foreach($path in $external){
    if($path.Length-gt$capacity.legacy_windows_path_limit){
      throw ("NATIVE_PATH_PREPARATION=FAIL TOOL={0} PATH={1} LENGTH={2} REASON=external_input_requires_its_existing_owner_transport REMEDIATION=prepare_the_explicit_input_with_its_supported_private_copy_or_companion_boundary ELAPSED_SECONDS={3}" -f $Tool,$path,$path.Length,$watch.Elapsed.TotalSeconds)
    }
  }
  if($Paths.Count-and-not$capacity.legacy_windows_compatible){
    if($null-ne$Package.execution_alias){$null=Assert-ExecutionPathCapacity -Report $capacity}
    if(-not$ExecutionRoot-and$null-ne$Package.PSObject.Properties['path_context']){$ExecutionRoot=[string]$Package.path_context.execution_root}
    if([string]::IsNullOrWhiteSpace($ExecutionRoot)){throw 'Native execution alias requires an explicit execution root.'}
    $alias=New-ManagedExecutionAlias -TargetDirectory $persistent -ExecutionRoot $ExecutionRoot -ExpectedExecutionRelativePaths $relativePaths
    $execution=[string]$alias.execution_alias
    $Package.run_dir=$execution;$Package.execution_alias=$execution
    $capacity=$alias.execution_path_capacity
  }
  $Package.execution_path_capacity=$capacity
  $projected=if($Paths.Count){Project-RunPath -Paths $Paths -ArtifactRunDir $persistent -RunDir $execution -Python $Package.python}else{@()}
  $environment=@{MASS_SPECTROMETRY_RUN_DIRECTORY=$persistent;MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY=$execution}
  if($null-ne$Package.PSObject.Properties['path_context']){
    $environment.MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=[string]$Package.path_context.host_resource_state_path
    $environment.MASS_SPECTROMETRY_ARTIFACT_ROOT=[string]$Package.path_context.artifact_root
    $environment.MASS_SPECTROMETRY_EXECUTION_ROOT=[string]$Package.path_context.execution_root
  }
  $elapsed=$watch.Elapsed.TotalSeconds
  if($null-eq$Package.PSObject.Properties['native_path_preparation']){
    $Package|Add-Member -NotePropertyName native_path_preparation -NotePropertyValue @{calls=0;elapsed_seconds=0.0;transport_bytes=0L}
  }
  $Package.native_path_preparation.calls++
  $Package.native_path_preparation.elapsed_seconds+=$elapsed
  return [pscustomobject]@{artifact_run_dir=$persistent;run_dir=$execution;execution_alias=$Package.execution_alias;
    projected_paths=@($projected);environment=$environment;execution_path_capacity=$capacity;
    preparation_elapsed_seconds=$elapsed;transport_bytes=0;tool=$Tool}
}
