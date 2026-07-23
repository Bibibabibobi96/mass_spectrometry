[CmdletBinding()]
param(
  [ValidateSet('baseline_finite_3d')][string]$DesignProfileId = 'baseline_finite_3d',
  [string]$RunId = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
& (Join-Path $repoRoot 'common\multipole\run_round_rod_field_screen.ps1') `
  -ProjectId 'rf_octupole_ion_guide' -DesignProfileId $DesignProfileId -RunId $RunId
if ($LASTEXITCODE -ne 0) { throw 'RF octupole round-rod field screen failed.' }
