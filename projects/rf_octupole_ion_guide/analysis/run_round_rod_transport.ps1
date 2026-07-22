[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$FieldScreenRunId,
  [string]$RunId = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$arguments = @('-m', 'common.multipole.run_round_rod_transport', '--project-root', $projectRoot, '--field-screen-run-id', $FieldScreenRunId)
if (-not [string]::IsNullOrWhiteSpace($RunId)) { $arguments += @('--run-id', $RunId) }
Push-Location $repoRoot
try {
  & $python @arguments
  if ($LASTEXITCODE -ne 0) { throw 'RF octupole round-rod L2 transport failed.' }
} finally { Pop-Location }
