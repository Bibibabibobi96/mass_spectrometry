[CmdletBinding()]
param(
    [string]$PythonExe,
    [string]$ManifestPath,
    [string]$OutputDir
)

$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectDir)
$artifactRoot = Join-Path (Split-Path -Parent $repoRoot) 'artifacts\projects\oa_tof'
if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $PythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
}
if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $ManifestPath = Join-Path $projectDir 'config\analysis_baselines.json'
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Formal Python environment is missing: $PythonExe. See analysis/README.md."
}
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $runId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__gate__python__reference-analysis__baselines'
    $runDir = Join-Path $artifactRoot "runs\$runId"
    $OutputDir = Join-Path $runDir 'results'
} else {
    $OutputDir = [IO.Path]::GetFullPath($OutputDir)
    $runDir = Split-Path -Parent $OutputDir
    $runId = Split-Path -Leaf $runDir
}
& $PythonExe (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $runId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $runId" }
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$version = & $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or $version.Trim() -ne '3.11') {
    throw "Formal analysis requires Python 3.11; detected '$version'."
}

& $PythonExe -c "import numpy, scipy, pandas, matplotlib, openpyxl"
if ($LASTEXITCODE -ne 0) {
    throw 'Formal Python dependencies are incomplete. See analysis/README.md.'
}

$arguments = @(
    (Join-Path $PSScriptRoot 'reference_analysis.py'),
    'verify-baselines',
    '--manifest', $ManifestPath
)
$arguments += @('--output', $OutputDir)

& $PythonExe @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Reference analysis gate failed with exit code $LASTEXITCODE."
}
& $PythonExe (Join-Path $PSScriptRoot 'verify_formal_validation.py')
if ($LASTEXITCODE -ne 0) {
    throw "Formal cross-solver validation gate failed with exit code $LASTEXITCODE."
}
$runConfig = Join-Path $runDir 'run_config.json'
[ordered]@{schema_version=1;run_id=$runId;project='oa_tof';mode='reference_analysis_baseline_gate';project_root=$projectDir;inputs=[ordered]@{analysis_baselines=$ManifestPath;formal_validation='config/formal_validation.json'};formal_gate_passed=$false} |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $runConfig -Encoding UTF8
$summary = Join-Path $runDir 'summary.json'
[ordered]@{schema_version=1;role='oa_tof_reference_analysis_summary';status='success';results='results/baseline_verification.json'} |
    ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $summary -Encoding UTF8
$manifestArgs = @((Join-Path $repoRoot 'common\contracts\write_run_manifest.py'),'--run-config',$runConfig,'--status','success','--software','Python 3.11','--output',$summary)
foreach ($file in Get-ChildItem -LiteralPath $OutputDir -Recurse -File) { $manifestArgs += @('--output',$file.FullName) }
& $PythonExe @manifestArgs
if ($LASTEXITCODE -ne 0) { throw 'Reference-analysis manifest creation failed.' }
Write-Host 'REFERENCE_ANALYSIS_STATUS=PASS'
