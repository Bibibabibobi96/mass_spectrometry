[CmdletBinding()]
param(
  [ValidateSet('baseline_finite_3d','endplate_acceleration_reference')]
  [string]$DesignProfileId = 'baseline_finite_3d',
  [Parameter(Mandatory=$true)][string]$ParticleSourcePath,
  [string]$EvidenceContractPath = '',
  [string]$RunId = '',
  [ValidateRange(1,9)][int]$MeshAutoLevel = 6,
  [double]$WorkingRegionMaximumElementSizeMm = [double]::NaN,
  [ValidateRange(4,10000)][int]$RfStepsPerPeriod = 80,
  [ValidateRange(0.001,1000000)][double]$MaximumTimeUs = 80.0
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$arguments = @{
  ProjectId = 'rf_hexapole_ion_guide'
  DesignProfileId = $DesignProfileId
  ParticleSourcePath = $ParticleSourcePath
  RunId = $RunId
  MeshAutoLevel = $MeshAutoLevel
  RfStepsPerPeriod = $RfStepsPerPeriod
  MaximumTimeUs = $MaximumTimeUs
}
if ($EvidenceContractPath) { $arguments.EvidenceContractPath = $EvidenceContractPath }
if (-not [double]::IsNaN($WorkingRegionMaximumElementSizeMm)) {
  $arguments.WorkingRegionMaximumElementSizeMm = $WorkingRegionMaximumElementSizeMm
}
& (Join-Path $repoRoot 'common\multipole\run_finite_3d_transport.ps1') @arguments
if ($LASTEXITCODE -ne 0) { throw 'RF hexapole COMSOL transport failed.' }
