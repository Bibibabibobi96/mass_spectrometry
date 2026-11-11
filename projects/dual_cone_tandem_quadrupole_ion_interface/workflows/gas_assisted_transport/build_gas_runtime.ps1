[CmdletBinding(DefaultParameterSetName='Run')]
param(
  [Parameter(Mandatory=$true,ParameterSetName='Run')][string]$ComsolRunDirectory,
  [Parameter(Mandatory=$true,ParameterSetName='Reference')][string]$SourceReferencePath,
  [Parameter(Mandatory=$true)][string]$InterfacePath,
  [Parameter(Mandatory=$true)][string]$OutputDir,
  [Parameter(Mandatory=$true)][string]$PythonExe
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$sourceArgs=if($PSCmdlet.ParameterSetName-eq'Reference'){@('--source-reference',$SourceReferencePath)}else{@('--comsol-run-directory',$ComsolRunDirectory)}
& $PythonExe -I -B -X utf8 -m msplatform.workflows.dual_cone_transport @sourceArgs --interface $InterfacePath --output-dir $OutputDir
if($LASTEXITCODE-ne0){throw "Published gas runtime compilation failed with exit code $LASTEXITCODE."}
