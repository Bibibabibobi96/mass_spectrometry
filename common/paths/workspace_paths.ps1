Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Invoke-WorkspacePathRequest {
  [CmdletBinding()]
  param([Parameter(Mandatory)][hashtable]$Request,[string]$Python='')
  if(-not$Python){
    $Python=if($env:SIMULATION_PYTHON_EXE){$env:SIMULATION_PYTHON_EXE}else{
      Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) '.venv/Scripts/python.exe'
    }
  }
  if(-not(Test-Path -LiteralPath $Python -PathType Leaf)){throw "Workspace paths require the repository Python runtime: $Python"}
  $start=[Diagnostics.ProcessStartInfo]::new()
  $start.FileName=$Python;$start.WorkingDirectory=$PSScriptRoot
  $start.UseShellExecute=$false;$start.CreateNoWindow=$true
  $start.RedirectStandardInput=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
  $start.StandardInputEncoding=[Text.UTF8Encoding]::new($false)
  $start.StandardOutputEncoding=[Text.UTF8Encoding]::new($false)
  $start.StandardErrorEncoding=[Text.UTF8Encoding]::new($false)
  foreach($argument in @('-B',(Join-Path $PSScriptRoot 'workspace_paths.py'))){$start.ArgumentList.Add($argument)}
  $process=[Diagnostics.Process]::Start($start)
  try{
    $outputTask=$process.StandardOutput.ReadToEndAsync();$errorTask=$process.StandardError.ReadToEndAsync()
    $process.StandardInput.WriteLine(($Request|ConvertTo-Json -Depth 12 -Compress));$process.StandardInput.Close()
    $process.WaitForExit()
    $output=$outputTask.GetAwaiter().GetResult();$errorText=$errorTask.GetAwaiter().GetResult()
    if($process.ExitCode-ne0){throw "Workspace path resolution failed: $errorText"}
    return ,($output|ConvertFrom-Json -Depth 12 -NoEnumerate)
  }finally{$process.Dispose()}
}

function Resolve-WorkspacePaths {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$SourceRoot,[string]$ArtifactRoot='',
    [string]$ExecutionRoot='',[string]$HostResourceStatePath='',$FrozenContext=$null,[string]$Python='')
  $arguments=@{source_root=$SourceRoot}
  if($PSBoundParameters.ContainsKey('ArtifactRoot')){$arguments.artifact_root=$ArtifactRoot}
  if($PSBoundParameters.ContainsKey('ExecutionRoot')){$arguments.execution_root=$ExecutionRoot}
  if($PSBoundParameters.ContainsKey('HostResourceStatePath')){$arguments.host_resource_state_path=$HostResourceStatePath}
  if($null-ne$FrozenContext){$arguments.frozen_context=$FrozenContext}
  Invoke-WorkspacePathRequest -Request @{operation='resolve';arguments=$arguments} -Python $Python
}

function Project-RunPath {
  [CmdletBinding(DefaultParameterSetName='Single')]
  param([Parameter(Mandatory,ParameterSetName='Single')][string]$Path,
    [Parameter(Mandatory,ParameterSetName='Many')][AllowEmptyCollection()][string[]]$Paths,
    [Parameter(Mandatory)][string]$ArtifactRunDir,[Parameter(Mandatory)][string]$RunDir,[string]$Python='')
  $selected=@($Path)
  if($PSCmdlet.ParameterSetName-eq'Many'){$selected=@($Paths)}
  $result=Invoke-WorkspacePathRequest -Request @{operation='project';arguments=@{
    paths=@($selected);artifact_run_dir=$ArtifactRunDir;run_dir=$RunDir}} -Python $Python
  if($PSCmdlet.ParameterSetName-eq'Single'){return $result[0]}
  return ,@($result)
}
