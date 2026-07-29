[CmdletBinding()]
param(
  [string]$RuntimeProfileId = 'segmented_rod_axial_acceleration',
  [string]$EvidenceContractPath = '',
  [string]$RunId = '',
  [string]$RetentionClass = 'compact',
  [string]$RetentionReason = '',
  [string]$PythonExe = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
. (Join-Path $repoRoot 'common\multipole\project_transport_launcher_support.ps1')
Invoke-MultipoleProjectFinite3dTransport -Solver comsol `
  -ProjectId 'rf_hexapole_ion_optics' -RuntimeProfileId $RuntimeProfileId `
  -RepoRoot $repoRoot -EvidenceContractPath $EvidenceContractPath -RunId $RunId `
  -RetentionClass $RetentionClass -RetentionReason $RetentionReason `
  -PythonExe $PythonExe
