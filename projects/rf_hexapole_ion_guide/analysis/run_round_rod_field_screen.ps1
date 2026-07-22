[CmdletBinding()]
param([string]$RunId = '')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
& (Join-Path $repoRoot 'common\multipole\run_round_rod_field_screen.ps1') `
  -ProjectRoot (Join-Path $PSScriptRoot '..') -RunId $RunId
if ($LASTEXITCODE -ne 0) { throw 'RF hexapole round-rod field screen failed.' }
