[CmdletBinding()]
param(
  [string]$RuntimeProfileId = 'no_acceleration_full_length',
  [string]$EvidenceContractPath = '',
  [string]$RunId = '',
  [ValidateSet('compact','qualification','solver_review')][string]$RetentionClass = 'compact',
  [string]$RetentionReason = '',
  [string]$PythonExe = '',
  [string]$ReferenceComsolRunId = '',
  [string]$SimionExe = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
. (Join-Path $repoRoot 'common\multipole\project_transport_launcher_support.ps1')
Invoke-MultipoleProjectFinite3dTransport -Solver simion `
  -ProjectId 'rf_quadrupole_ion_optics' -RuntimeProfileId $RuntimeProfileId `
  -RepoRoot $repoRoot -EvidenceContractPath $EvidenceContractPath -RunId $RunId `
  -RetentionClass $RetentionClass -RetentionReason $RetentionReason `
  -PythonExe $PythonExe -ReferenceComsolRunId $ReferenceComsolRunId `
  -SimionExe $SimionExe
