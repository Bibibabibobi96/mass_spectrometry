[CmdletBinding()]
param(
  [string]$RunId='',
  [string]$ParticleTablePath='',
  [double]$CellMm=0.4,
  [double]$EntranceConnectorLengthMm=[double]::NaN,
  [double]$ExitConnectorLengthMm=[double]::NaN,
  [string]$SimionExe='',
  [string]$TemplateIob='',
  [string]$AxialAccelerationContractPath='',
  [switch]$AxialAcceleration,
  [switch]$EndplateAcceleration
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path
$arguments=@{
  ProjectRoot=$projectRoot
  Adapter='quadrupole'
  RunId=$RunId
  ParticleTablePath=$ParticleTablePath
  CellMm=$CellMm
  EntranceConnectorLengthMm=$EntranceConnectorLengthMm
  ExitConnectorLengthMm=$ExitConnectorLengthMm
  SimionExe=$SimionExe
  TemplateIob=$TemplateIob
  AxialAccelerationContractPath=$AxialAccelerationContractPath
  AxialAcceleration=$AxialAcceleration
  EndplateAcceleration=$EndplateAcceleration
}
& (Join-Path $repoRoot 'common\multipole\run_simion_finite_3d_transport.ps1') @arguments
exit $LASTEXITCODE
