[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$WorkspaceRoot,
  [Parameter(Mandatory = $true)][string]$ArtifactRootPath,
  [Parameter(Mandatory = $true)][string]$ScienceRoot,
  [string]$PythonExe
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$workspaceRoot = (Resolve-Path -LiteralPath $WorkspaceRoot).Path
$artifactRootPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ArtifactRootPath)
$projectRoot = (Resolve-Path -LiteralPath $ScienceRoot).Path
$packageRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $packageRoot 'execution/resources/workspace_paths.ps1')
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) }
  elseif ($env:SIMULATION_PYTHON_EXE) { [IO.Path]::GetFullPath($env:SIMULATION_PYTHON_EXE) }
  else { throw 'Explicit PythonExe or SIMULATION_PYTHON_EXE is required' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Formal Python environment is missing: $python. See analysis/README.md."
}
$artifactRoot = Resolve-RunArtifactRoot -ArtifactRoot $artifactRootPath -OwnerKind component -OwnerId single_reflection_oa_tof_mass_analyzer -Python $python
$version = & $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or $version.Trim() -ne '3.11') {
    throw "Formal analysis requires Python 3.11; detected '$version'."
}
& $python -c "import numpy, scipy, pandas, matplotlib, openpyxl"
if ($LASTEXITCODE -ne 0) { throw 'Formal Python dependencies are incomplete.' }
& $python -I -B -c "import sys; from pathlib import Path; from msplatform.results.cross_solver_history import read_cross_solver_record; read_cross_solver_record(Path(sys.argv[1]), Path(sys.argv[2])); print('CROSS_SOLVER_RECORD_VALID=PASS')" `
  (Join-Path $projectRoot 'config/formal_validation.json') $artifactRoot
if ($LASTEXITCODE -ne 0) {
    throw "Formal cross-solver validation gate failed with exit code $LASTEXITCODE."
}
Write-Host 'REFERENCE_ANALYSIS_STATUS=PASS'
