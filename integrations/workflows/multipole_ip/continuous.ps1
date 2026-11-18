<# Track original births against an explicit complete RF-IP FieldBundle. #>
[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$ReleaseRequest,
  [Parameter(Mandatory)][string]$FieldsReference,
  [Parameter(Mandatory)][string]$Propagation,
  [Parameter(Mandatory)][string]$Observations,
  [Parameter(Mandatory)][string]$Numerics,
  [Parameter(Mandatory)][string]$Hs1Request,
  [Parameter(Mandatory)][string]$Environment,
  [Parameter(Mandatory)][string]$Workspace,
  [Parameter(Mandatory)][string]$Profile,
  [string]$RecoveryReference='',
  [string]$DispatchProfiles='',
  [int]$UnitSize=0,
  [string]$Python='',
  [string]$RepoRoot=(Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$RepoRoot=(Resolve-Path -LiteralPath $RepoRoot).Path
. (Join-Path $RepoRoot 'common/require_powershell7.ps1')
. (Join-Path $RepoRoot 'common/contracts/run_artifact_support.ps1')
if(-not $Python){
  $Python=if($env:SIMULATION_PYTHON_EXE){$env:SIMULATION_PYTHON_EXE}else{Join-Path $RepoRoot '.venv/Scripts/python.exe'}
}
$Python=(Resolve-Path -LiteralPath $Python).Path
$arguments=@('-B','-X','utf8','-m','msplatform.workflows.multipole_ip.continuous',
  '--release-request',$ReleaseRequest,'--fields-reference',$FieldsReference,
  '--propagation',$Propagation,'--observations',$Observations,'--numerics',$Numerics,
  '--hs1-request',$Hs1Request,'--environment',$Environment,'--workspace',$Workspace,'--profile',$Profile)
if($RecoveryReference){$arguments+=@('--recovery-reference',$RecoveryReference)}
if($DispatchProfiles){$arguments+=@('--dispatch-profiles',$DispatchProfiles)}
if($PSBoundParameters.ContainsKey('UnitSize')){$arguments+=@('--unit-size',"$UnitSize")}
Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
  & $Python @arguments
  if($LASTEXITCODE -ne 0){throw "Continuous RF-IP tracking failed (exit $LASTEXITCODE)."}
}
