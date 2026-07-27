[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$ParticleSourcePath,
  [string]$EvidenceContractPath = '',
  [string]$RunId = '',
  [string]$PythonExe = '',
  [string]$ReferenceComsolRunId = '',
  [ValidateRange(0.001,100)][double]$CellMm = 0.2,
  [string]$SimionExe = '',
  [ValidateRange(4,10000)][int]$RfStepsPerPeriod = 40,
  [ValidateRange(0,100)][int]$TrajectoryQuality = 10,
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
  ReferenceComsolRunId = $ReferenceComsolRunId
  CellMm = $CellMm
  RfStepsPerPeriod = $RfStepsPerPeriod
  TrajectoryQuality = $TrajectoryQuality
  MaximumTimeUs = $MaximumTimeUs
}
if ($EvidenceContractPath) { $arguments.EvidenceContractPath = $EvidenceContractPath }
if ($SimionExe) { $arguments.SimionExe = $SimionExe }
& (Join-Path $repoRoot 'common\multipole\run_simion_finite_3d_transport.ps1') @arguments
if ($LASTEXITCODE -ne 0) { throw 'RF quadrupole SIMION transport failed.' }
