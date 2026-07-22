[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$FieldScreenRunId,
  [string]$RunId = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
& (Join-Path $repoRoot 'common\multipole\run_finite_3d_transport.ps1') `
  -ProjectRoot (Join-Path $PSScriptRoot '..') -FieldScreenRunId $FieldScreenRunId -RunId $RunId
if ($LASTEXITCODE -ne 0) { throw 'RF hexapole finite 3D L3 transport failed.' }
