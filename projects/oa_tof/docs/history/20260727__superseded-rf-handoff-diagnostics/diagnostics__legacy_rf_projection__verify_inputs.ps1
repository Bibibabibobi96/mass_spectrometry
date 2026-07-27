[CmdletBinding()]
param(
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python 3.11 runtime missing: $python" }

$modes = @(
  'rf_handoff_projection.json',
  'rf_hybrid_mesh_projection.json',
  'rf_handoff_pulse.json'
)
foreach ($mode in $modes) {
  & $python -m projects.oa_tof.analysis.prepare_rf_handoff_projection `
    --mode (Join-Path $projectRoot "config\modes\$mode") --check-historical-inputs
  if ($LASTEXITCODE -ne 0) { throw "Legacy RF projection input check failed: $mode" }
}
"LEGACY_RF_PROJECTION_INPUTS=PASS MODES=$($modes.Count)"
