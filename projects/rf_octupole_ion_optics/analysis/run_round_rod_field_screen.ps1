[CmdletBinding()]
param(
  [ValidateSet('no_acceleration_full_length')]
  [string]$DesignProfileId = 'no_acceleration_full_length',
  [string]$RunId = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
& (Join-Path $repoRoot 'common\multipole\run_round_rod_field_screen.ps1') `
  -ProjectId 'rf_octupole_ion_optics' -DesignProfileId $DesignProfileId -RunId $RunId
if ($LASTEXITCODE -ne 0) { throw 'RF octupole round-rod field screen failed.' }
