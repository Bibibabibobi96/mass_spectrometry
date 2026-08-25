[CmdletBinding(DefaultParameterSetName = 'RuntimeProfile')]
param(
  [Parameter(Mandatory = $true, ParameterSetName = 'RuntimeProfile')]
  [string]$RuntimeProfileId = 'no_acceleration_full_length',
  [Parameter(Mandatory = $true, ParameterSetName = 'CampaignExperiment')]
  [string]$CampaignPath,
  [Parameter(Mandatory = $true, ParameterSetName = 'CampaignExperiment')]
  [string]$ExperimentId,
  [string]$EvidenceContractPath = '',
  [string]$RunId = '',
  [string]$RetentionClass = 'compact',
  [string]$RetentionReason = '',
  [string]$PythonExe = '',
  [string]$ReferenceComsolRunId = '',
  [string]$SimionExe = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
. (Join-Path $repoRoot 'common\multipole\project_transport_launcher_support.ps1')
 $arguments = @{
  RepoRoot = $repoRoot
  EvidenceContractPath = $EvidenceContractPath
  RunId = $RunId
  RetentionClass = $RetentionClass
  RetentionReason = $RetentionReason
  PythonExe = $PythonExe
  ReferenceComsolRunId = $ReferenceComsolRunId
  SimionExe = $SimionExe
}
if ($PSCmdlet.ParameterSetName -eq 'CampaignExperiment') {
  $arguments.CampaignPath = $CampaignPath
  $arguments.ExperimentId = $ExperimentId
} else {
  $arguments.RuntimeProfileId = $RuntimeProfileId
}
Invoke-MultipoleProjectFinite3dTransport -Solver simion `
  -ProjectId 'rf_octupole_ion_optics' @arguments
