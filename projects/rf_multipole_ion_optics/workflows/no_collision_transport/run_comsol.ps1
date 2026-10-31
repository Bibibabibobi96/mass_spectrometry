[CmdletBinding(DefaultParameterSetName='RuntimeProfile')]
param(
  [Parameter(ParameterSetName='RuntimeProfile')][string]$RuntimeProfileId='',
  [Parameter(Mandatory=$true,ParameterSetName='CampaignExperiment')][string]$CampaignPath,
  [Parameter(Mandatory=$true,ParameterSetName='CampaignExperiment')][string]$ExperimentId,
  [string]$EvidenceContractPath = '',
  [Parameter(Mandatory,ParameterSetName='Recovery')][Parameter(ParameterSetName='Analyze')][Parameter(ParameterSetName='RuntimeProfile')][Parameter(ParameterSetName='CampaignExperiment')][string]$RunId = '',
  [Parameter(Mandatory,ParameterSetName='Recovery')][switch]$ResumeFinalization,
  [Parameter(Mandatory,ParameterSetName='Analyze')][switch]$AnalyzeOnly,
  [Parameter(ParameterSetName='Analyze')][switch]$ReextractFromModel,
  [Parameter(Mandatory,ParameterSetName='Analyze')][string]$ParentManifestPath,
  [Parameter(ParameterSetName='Analyze')][string]$EngineeringBudgetPath='',
  [string]$ResultPath='',
  [Parameter(ParameterSetName='Recovery')][string]$ArtifactRootPath='',
  [string]$RetentionClass = 'compact',
  [string]$RetentionReason = '',
  [string]$PythonExe = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
if($ResumeFinalization){
  $resumeArguments=@{ResumeFinalization=$true;RunId=$RunId;PythonExe=$PythonExe}
  if($ResultPath){$resumeArguments.ResultPath=$ResultPath}
  if($ArtifactRootPath){$resumeArguments.ArtifactRootPath=$ArtifactRootPath}
  & (Join-Path $repoRoot 'projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1') @resumeArguments
  return
}
if($AnalyzeOnly){
  if([string]::IsNullOrWhiteSpace($EngineeringBudgetPath)){throw 'AnalyzeOnly requires an explicit EngineeringBudgetPath for new analysis payload; parent native budget is not a fallback.'}
  if($EvidenceContractPath){throw 'AnalyzeOnly uses parent frozen scientific authority; scientific overrides are not accepted.'}
  & (Join-Path $repoRoot 'projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1') -AnalyzeOnly `
    -ReextractFromModel:$ReextractFromModel -ParentManifestPath $ParentManifestPath -EngineeringBudgetPath $EngineeringBudgetPath -RunId $RunId -ResultPath $ResultPath -PythonExe $PythonExe `
    -RetentionClass $RetentionClass -RetentionReason $RetentionReason
  return
}
. (Join-Path $repoRoot 'projects\rf_multipole_ion_optics\runtime\project_transport_launcher_support.ps1')
$selection=@{}
if($PSCmdlet.ParameterSetName-eq'CampaignExperiment'){
  $selection.CampaignPath=$CampaignPath;$selection.ExperimentId=$ExperimentId
}else{$selection.RuntimeProfileId=$RuntimeProfileId}
if($PSCmdlet.ParameterSetName-eq'RuntimeProfile'-or$PSBoundParameters.ContainsKey('RetentionClass')){$selection.RetentionClass=$RetentionClass}
Invoke-MultipoleProjectFinite3dTransport -Solver comsol @selection `
  -ProjectId 'rf_multipole_ion_optics' `
  -RepoRoot $repoRoot -EvidenceContractPath $EvidenceContractPath -RunId $RunId `
  -RetentionReason $RetentionReason `
  -PythonExe $PythonExe -ResultPath $ResultPath
