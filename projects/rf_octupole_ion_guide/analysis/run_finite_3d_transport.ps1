[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$FieldScreenRunId,
  [string]$RunId = '',
  [double]$EntranceConnectorLengthMm = [double]::NaN,
  [double]$ExitConnectorLengthMm = [double]::NaN,
  [switch]$AxialAcceleration,
  [switch]$EndplateAcceleration
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
& (Join-Path $repoRoot 'common\multipole\run_finite_3d_transport.ps1') `
  -ProjectRoot (Join-Path $PSScriptRoot '..') -FieldScreenRunId $FieldScreenRunId -RunId $RunId `
  -EntranceConnectorLengthMm $EntranceConnectorLengthMm -ExitConnectorLengthMm $ExitConnectorLengthMm `
  -AxialAcceleration:$AxialAcceleration -EndplateAcceleration:$EndplateAcceleration
if ($LASTEXITCODE -ne 0) { throw 'RF octupole finite 3D L3 transport failed.' }
