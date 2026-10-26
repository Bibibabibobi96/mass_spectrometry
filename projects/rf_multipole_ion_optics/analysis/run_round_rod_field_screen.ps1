[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$DesignProfileId,
  [string]$RunId = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
& (Join-Path $repoRoot 'projects\rf_multipole_ion_optics\runtime\run_round_rod_field_screen.ps1') `
  -ProjectId 'rf_multipole_ion_optics' -DesignProfileId $DesignProfileId -RunId $RunId
if ($LASTEXITCODE -ne 0) { throw 'RF hexapole round-rod field screen failed.' }
