[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$FieldScreenRunId,[string]$RunId='',[string]$ReferenceComsolRunId='',[double]$CellMm=0.4)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
& (Join-Path $repoRoot 'common\multipole\run_simion_finite_3d_transport.ps1') -ProjectRoot (Join-Path $PSScriptRoot '..') -FieldScreenRunId $FieldScreenRunId -RunId $RunId -ReferenceComsolRunId $ReferenceComsolRunId -CellMm $CellMm
if($LASTEXITCODE-ne 0){throw 'RF hexapole SIMION L3 transport failed.'}
