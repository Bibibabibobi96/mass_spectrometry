[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$RuntimeProfileId,
  [string]$EvidenceContractPath = '',
  [string]$RunId = '',
  [string]$RetentionClass = 'compact',
  [string]$RetentionReason = '',
  [string]$PythonExe = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
. (Join-Path $repoRoot 'projects\rf_multipole_ion_optics\runtime\project_transport_launcher_support.ps1')
Invoke-MultipoleProjectFinite3dTransport -Solver comsol `
  -ProjectId 'rf_multipole_ion_optics' -RuntimeProfileId $RuntimeProfileId `
  -RepoRoot $repoRoot -EvidenceContractPath $EvidenceContractPath -RunId $RunId `
  -RetentionClass $RetentionClass -RetentionReason $RetentionReason `
  -PythonExe $PythonExe
