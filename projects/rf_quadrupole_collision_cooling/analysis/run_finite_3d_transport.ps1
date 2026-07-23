[CmdletBinding()]
param(
  [string]$RunId = '',
  [string]$ParticleTablePath = '',
  [double]$EntranceConnectorLengthMm = [double]::NaN,
  [double]$ExitConnectorLengthMm = [double]::NaN,
  [string]$AxialAccelerationContractPath = '',
  [switch]$AxialAcceleration,
  [switch]$EndplateAcceleration
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
& (Join-Path $repoRoot 'common\multipole\run_finite_3d_transport.ps1') `
  -ProjectRoot (Join-Path $PSScriptRoot '..') -Adapter quadrupole -RunId $RunId `
  -ParticleTablePath $ParticleTablePath -EntranceConnectorLengthMm $EntranceConnectorLengthMm `
  -ExitConnectorLengthMm $ExitConnectorLengthMm -AxialAccelerationContractPath $AxialAccelerationContractPath `
  -AxialAcceleration:$AxialAcceleration `
  -EndplateAcceleration:$EndplateAcceleration
if ($LASTEXITCODE -ne 0) { throw 'RF quadrupole shared finite 3D COMSOL transport failed.' }
