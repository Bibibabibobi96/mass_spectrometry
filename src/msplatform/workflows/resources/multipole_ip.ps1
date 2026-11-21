[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Request,
  [Parameter(Mandatory)][string]$EnvironmentPath,
  [Parameter(Mandatory)][string]$Workspace,
  [Parameter(Mandatory)][string]$EngineeringProfile,
  [Parameter(Mandatory)][string]$PythonExe,
  [string]$RunId=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if($PSVersionTable.PSEdition-ne'Core'-or$PSVersionTable.PSVersion.Major-ne7){throw 'PowerShell Core 7 is required.'}
$python=(Resolve-Path -LiteralPath $PythonExe).Path
$arguments=@('-B','-m','msplatform.workflows.multipole_ip.prepare','--request',(Resolve-Path -LiteralPath $Request).Path,
  '--environment',(Resolve-Path -LiteralPath $EnvironmentPath).Path,'--workspace',[IO.Path]::GetFullPath($Workspace),
  '--profile',$EngineeringProfile)
if($RunId){$arguments+=@('--run-id',$RunId)}
& $python @arguments
if($LASTEXITCODE-ne0){throw 'Managed multipole/IP preparation failed; inspect its original Result and exception.'}
