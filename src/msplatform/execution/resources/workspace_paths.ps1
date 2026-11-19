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
  foreach($argument in @('-B','-c','import sys,runpy;from pathlib import Path;p=Path(sys.argv[1]);sys.path.insert(0,str(p.parents[2]/''src''));runpy.run_path(str(p),run_name=''__main__'')',(Join-Path $PSScriptRoot 'workspace_paths.py'))){$start.ArgumentList.Add($argument)}
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
