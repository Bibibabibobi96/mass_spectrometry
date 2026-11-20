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
  [ValidateSet('rf_ip','rf_ip_mr')][string]$ExpectedComponentScope='rf_ip',
  [string]$Python='',
  [string]$RepoRoot=(Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$RepoRoot=(Resolve-Path -LiteralPath $RepoRoot).Path
$ReleaseRequest=(Resolve-Path -LiteralPath $ReleaseRequest).Path
$FieldsReference=(Resolve-Path -LiteralPath $FieldsReference).Path
$Propagation=(Resolve-Path -LiteralPath $Propagation).Path
$Observations=(Resolve-Path -LiteralPath $Observations).Path
$Numerics=(Resolve-Path -LiteralPath $Numerics).Path
$Hs1Request=(Resolve-Path -LiteralPath $Hs1Request).Path
$Environment=(Resolve-Path -LiteralPath $Environment).Path
$Workspace=(Resolve-Path -LiteralPath $Workspace).Path
if($RecoveryReference){$RecoveryReference=(Resolve-Path -LiteralPath $RecoveryReference).Path}
if($DispatchProfiles){$DispatchProfiles=(Resolve-Path -LiteralPath $DispatchProfiles).Path}
. (Join-Path $RepoRoot 'src/msplatform/execution/resources/require_powershell7.ps1')
. (Join-Path $RepoRoot 'src/msplatform/execution/resources/run_artifact_support.ps1')
if(-not $Python){
  $Python=if($env:SIMULATION_PYTHON_EXE){$env:SIMULATION_PYTHON_EXE}else{throw 'Explicit Python or SIMULATION_PYTHON_EXE is required'}
}
$Python=(Resolve-Path -LiteralPath $Python).Path
$arguments=@('-B','-X','utf8','-m','msplatform.workflows.multipole_ip.continuous',
  '--release-request',$ReleaseRequest,'--fields-reference',$FieldsReference,
  '--propagation',$Propagation,'--observations',$Observations,'--numerics',$Numerics,
  '--hs1-request',$Hs1Request,'--environment',$Environment,'--workspace',$Workspace,'--profile',$Profile,
  '--expected-component-scope',$ExpectedComponentScope)
if($RecoveryReference){$arguments+=@('--recovery-reference',$RecoveryReference)}
if($DispatchProfiles){$arguments+=@('--dispatch-profiles',$DispatchProfiles)}
if($PSBoundParameters.ContainsKey('UnitSize')){$arguments+=@('--unit-size',"$UnitSize")}
Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
  & $Python @arguments
  if($LASTEXITCODE -ne 0){throw "Continuous RF-IP tracking failed (exit $LASTEXITCODE)."}
}
