[CmdletBinding(DefaultParameterSetName = 'RuntimeProfile')]
param(
  [Parameter(ParameterSetName = 'RuntimeProfile')]
  [string]$RuntimeProfileId='',
  [Parameter(ParameterSetName = 'RuntimeProfile')]
  [Parameter(ParameterSetName = 'CampaignExperiment')]
  [string]$ResolvedRuntimeProfilePath='',
  [Parameter(Mandatory = $true, ParameterSetName = 'CampaignExperiment')]
  [string]$CampaignPath,
  [Parameter(Mandatory = $true, ParameterSetName = 'CampaignExperiment')]
  [string]$ExperimentId,
  [string]$EvidenceContractPath = '',
  [Parameter(Mandatory = $true, ParameterSetName = 'Recovery')]
  [Parameter(ParameterSetName = 'RuntimeProfile')]
  [Parameter(ParameterSetName = 'CampaignExperiment')]
  [string]$RunId = '',
  [string]$RetentionClass = 'solver_review',
  [string]$RetentionReason = 'Producer-owned fractional field/IOB and complete batch evidence retained for explicit stage reuse.',
  [string]$PythonExe = '',
  [string]$ReferenceComsolRunId = '',
  [string]$SimionExe = '',
  [string]$ContinuationPredecessorManifestPath = '',
  [string]$NativeFieldRunPath = '',
  [string]$ResultPath = '',
  [Parameter(Mandatory = $true, ParameterSetName = 'Recovery')]
  [switch]$ResumeFinalization
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
if ($ResumeFinalization) {
  $python = if ($PythonExe) {[IO.Path]::GetFullPath($PythonExe)} else {Join-Path $repoRoot '.venv\Scripts\python.exe'}
  Push-Location $repoRoot
  try {& $python -m common.contracts.artifact_naming run $RunId | Out-Null
    if ($LASTEXITCODE -ne 0) {throw 'Recovery requires a valid existing RunId.'}}
  finally {Pop-Location}
  $projectArtifacts=Join-Path (Split-Path -Parent $repoRoot) 'artifacts\projects\rf_multipole_ion_optics'
  $runRoot=Join-Path $projectArtifacts "runs\$RunId"
  if (-not $ResultPath) {$ResultPath=Join-Path $projectArtifacts "scratch\workflow_results\$RunId\result.json"}
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent ([IO.Path]::GetFullPath($ResultPath)))|Out-Null
  . (Join-Path $repoRoot 'common\contracts\run_artifact_workflow.ps1') -ResultPath $ResultPath -ResumeFinalization
  $recovery=Invoke-RunArtifactWorkflow -RequestPath (Join-Path $runRoot 'inputs/execution_request.json') `
    -ResultPath $ResultPath -ResumeFinalization
  Write-Output "MULTIPOLE_SIMION_FINALIZATION=$($recovery.status) RUN_ID=$RunId RESULT=$ResultPath"
  if ($recovery.status -ne 'success') {exit 1}
  return
}
. (Join-Path $repoRoot 'projects\rf_multipole_ion_optics\runtime\project_transport_launcher_support.ps1')
 $arguments = @{
  RepoRoot = $repoRoot
  EvidenceContractPath = $EvidenceContractPath
  RunId = $RunId
  RetentionClass = $RetentionClass
  RetentionReason = $RetentionReason
  PythonExe = $PythonExe
  ReferenceComsolRunId = $ReferenceComsolRunId
  SimionExe = $SimionExe
  ContinuationPredecessorManifestPath = $ContinuationPredecessorManifestPath
  ResolvedRuntimeProfilePath = $ResolvedRuntimeProfilePath
  NativeFieldRunPath = $NativeFieldRunPath
  ResultPath = $ResultPath
}
if ($PSCmdlet.ParameterSetName -eq 'CampaignExperiment') {
  if (-not $PSBoundParameters.ContainsKey('RetentionClass')) {$arguments.Remove('RetentionClass')}
  $arguments.CampaignPath = $CampaignPath
  $arguments.ExperimentId = $ExperimentId
} else {
  $arguments.RuntimeProfileId = $RuntimeProfileId
}
Invoke-MultipoleProjectFinite3dTransport -Solver simion `
  -ProjectId 'rf_multipole_ion_optics' @arguments
