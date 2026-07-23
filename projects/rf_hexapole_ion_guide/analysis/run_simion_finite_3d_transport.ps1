[CmdletBinding()]
param(
  [ValidateSet('baseline_finite_3d','endplate_acceleration_reference')]
  [string]$DesignProfileId = 'baseline_finite_3d',
  [Parameter(Mandatory=$true)][string]$ParticleSourcePath,
  [string]$EvidenceContractPath = '',
  [string]$RunId = '',
  [string]$ReferenceComsolRunId = '',
  [ValidateRange(0.001,100)][double]$CellMm = 0.4,
  [string]$SimionExe = '',
  [string]$TemplateIob = '',
  [ValidateRange(4,10000)][int]$RfStepsPerPeriod = 40,
  [ValidateRange(0,100)][int]$TrajectoryQuality = 10,
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
  ReferenceComsolRunId = $ReferenceComsolRunId
  CellMm = $CellMm
  RfStepsPerPeriod = $RfStepsPerPeriod
  TrajectoryQuality = $TrajectoryQuality
  MaximumTimeUs = $MaximumTimeUs
}
if ($EvidenceContractPath) { $arguments.EvidenceContractPath = $EvidenceContractPath }
if ($SimionExe) { $arguments.SimionExe = $SimionExe }
if ($TemplateIob) { $arguments.TemplateIob = $TemplateIob }
& (Join-Path $repoRoot 'common\multipole\run_simion_finite_3d_transport.ps1') @arguments
if ($LASTEXITCODE -ne 0) { throw 'RF hexapole SIMION transport failed.' }
