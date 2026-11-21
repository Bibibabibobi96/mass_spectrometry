<# Track a complete original recorded-birth population against an explicit FieldBundle. #>
[CmdletBinding()]
param(
  [string]$PreparationManifest='',
  [string]$ReleaseRequest='',
  [Parameter(Mandatory)][string]$FieldsReference,
  [string]$SpeciesId='',
  [string]$ExpectedParticleIds='',
  [string]$Propagation='',
  [string]$Numerics='',
  [Parameter(Mandatory)][string]$Observations,
  [Parameter(Mandatory)][string]$Environment,
  [Parameter(Mandatory)][string]$Workspace,
  [Parameter(Mandatory)][string]$Profile,
  [string]$ScalarFieldBasis='',
  [string]$RecoveryReference='',
  [string]$DispatchProfiles='',
  [int]$UnitSize=0,
  [string]$Python=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if($PSVersionTable.PSEdition-ne'Core'-or$PSVersionTable.PSVersion.Major-ne7){throw 'PowerShell Core 7 is required.'}
if(-not $Python){
  $Python=if($env:SIMULATION_PYTHON_EXE){$env:SIMULATION_PYTHON_EXE}else{throw 'Explicit Python or SIMULATION_PYTHON_EXE is required'}
}
$Python=(Resolve-Path -LiteralPath $Python).Path
$arguments=@('-I','-B','-X','utf8','-m','msplatform.workflows.single_reflection_flight.recorded_birth',
  '--fields-reference',$FieldsReference,
  '--observations',$Observations,'--environment',$Environment,'--workspace',$Workspace,'--profile',$Profile)
if($PreparationManifest){$arguments+=@('--preparation-manifest',$PreparationManifest)}
if($ReleaseRequest){$arguments+=@('--release-request',$ReleaseRequest)}
if($SpeciesId){$arguments+=@('--species-id',$SpeciesId)}
if($ExpectedParticleIds){$arguments+=@('--expected-particle-ids',$ExpectedParticleIds)}
if($Propagation){$arguments+=@('--propagation',$Propagation)}
if($Numerics){$arguments+=@('--numerics',$Numerics)}
if($ScalarFieldBasis){$arguments+=@('--scalar-field-basis',$ScalarFieldBasis)}
if($RecoveryReference){$arguments+=@('--recovery-reference',$RecoveryReference)}
if($DispatchProfiles){$arguments+=@('--dispatch-profiles',$DispatchProfiles)}
if($PSBoundParameters.ContainsKey('UnitSize')){$arguments+=@('--unit-size',"$UnitSize")}
& $Python @arguments
if($LASTEXITCODE -ne 0){throw "Recorded-birth tracking failed (exit $LASTEXITCODE)."}
