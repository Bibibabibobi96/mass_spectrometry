[CmdletBinding()]
param(
  [ValidateSet('official_transport','interface_readiness','mass_filter_reference',
    'explicit_axial_reference','endplate_acceleration_reference')]
  [string]$DesignProfileId = 'official_transport',
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
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
$arguments = @{
  ProjectId = 'rf_quadrupole_collision_cooling'
  DesignProfileId = $DesignProfileId
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
