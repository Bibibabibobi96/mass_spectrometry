Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Invoke-WorkspacePathRequest {
  [CmdletBinding()]
  param([Parameter(Mandatory)][hashtable]$Request,[string]$Python='')
  if(-not$Python){
    $Python=if($env:SIMULATION_PYTHON_EXE){$env:SIMULATION_PYTHON_EXE}else{throw 'Explicit Python or SIMULATION_PYTHON_EXE is required'}
  }
  if(-not(Test-Path -LiteralPath $Python -PathType Leaf)){throw "Workspace paths require the repository Python runtime: $Python"}
  $start=[Diagnostics.ProcessStartInfo]::new()
  $start.FileName=$Python;$start.WorkingDirectory=$PSScriptRoot
  $start.UseShellExecute=$false;$start.CreateNoWindow=$true
  $start.RedirectStandardInput=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
  $start.StandardInputEncoding=[Text.UTF8Encoding]::new($false)
  $start.StandardOutputEncoding=[Text.UTF8Encoding]::new($false)
  $start.StandardErrorEncoding=[Text.UTF8Encoding]::new($false)
  $bootstrap='import sys,runpy;from pathlib import Path;p=Path(sys.argv[1]).resolve();root=p.parents[3].resolve();sys.path.insert(0,str(root));from msplatform.execution import run_paths;assert Path(run_paths.__file__).resolve()==root/''msplatform''/''execution''/''run_paths.py'',f''selected run_paths={run_paths.__file__}; expected root={root}'';runpy.run_path(str(p),run_name=''__main__'')'
  foreach($argument in @('-I','-B','-c',$bootstrap,(Join-Path $PSScriptRoot 'workspace_paths.py'))){$start.ArgumentList.Add($argument)}
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

function Resolve-RunArtifactRoot {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$ArtifactRoot,[Parameter(Mandatory)][ValidateSet('component','assembly')][string]$OwnerKind,
    [Parameter(Mandatory)][string]$OwnerId,[string]$Python='')
  Invoke-WorkspacePathRequest -Request @{operation='run_root';arguments=@{artifact_root=$ArtifactRoot;owner_kind=$OwnerKind;owner_id=$OwnerId}} -Python $Python
}

function Resolve-PlatformArtifactPath {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$ArtifactRoot,[Parameter(Mandatory)][string[]]$RelativePath,[string]$Python='')
  Invoke-WorkspacePathRequest -Request @{operation='platform';arguments=@{artifact_root=$ArtifactRoot;relative_parts=$RelativePath}} -Python $Python
}
