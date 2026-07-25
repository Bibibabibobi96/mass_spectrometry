[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$ParticleSourcePath,
  [string]$EvidenceContractPath = '',
  [string]$RunId = '',
  [string]$PythonExe = '',
  [ValidateRange(1,9)][int]$MeshAutoLevel = 6,
  [double]$WorkingRegionMaximumElementSizeMm = [double]::NaN,
  [ValidateRange(4,10000)][int]$RfStepsPerPeriod = 80,
  [ValidateRange(0.001,1000000)][double]$MaximumTimeUs = 80.0
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
$arguments = @{
  ProjectId = 'rf_quadrupole_collision_cooling'
  DesignProfileId = 'official_transport'
  ParticleSourcePath = $ParticleSourcePath
  RunId = $RunId
  PythonExe = $python
  MeshAutoLevel = $MeshAutoLevel
  RfStepsPerPeriod = $RfStepsPerPeriod
  MaximumTimeUs = $MaximumTimeUs
}
if ($EvidenceContractPath) { $arguments.EvidenceContractPath = $EvidenceContractPath }
if (-not [double]::IsNaN($WorkingRegionMaximumElementSizeMm)) {
  $arguments.WorkingRegionMaximumElementSizeMm = $WorkingRegionMaximumElementSizeMm
}
& (Join-Path $repoRoot 'common\multipole\run_finite_3d_transport.ps1') @arguments
if ($LASTEXITCODE -ne 0) { throw 'RF quadrupole COMSOL transport failed.' }
