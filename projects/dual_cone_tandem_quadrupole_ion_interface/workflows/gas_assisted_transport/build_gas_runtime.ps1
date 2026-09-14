param(
    [Parameter(Mandatory = $true)]
    [string]$ComsolRunDirectory,
    [Parameter(Mandatory = $true)]
    [string]$OutputDir,
    [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$python = if ($PythonExe) {
    (Resolve-Path -LiteralPath $PythonExe).Path
} else {
    Join-Path $repoRoot '.venv\Scripts\python.exe'
}
$runDirectory = [IO.Path]::GetFullPath($ComsolRunDirectory)
$outputDirectory = [IO.Path]::GetFullPath($OutputDir)
$null = New-Item -ItemType Directory -Path $outputDirectory -Force
$runManifest = Join-Path $runDirectory 'run_manifest.json'
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $runManifest `
    --require-status success --require-local-run-config
if ($LASTEXITCODE -ne 0) {
    throw "COMSOL source run manifest verification failed with exit code $LASTEXITCODE."
}
$csv = Join-Path $runDirectory 'results\gas_field_rz.csv'
$metadata = Join-Path $runDirectory 'results\gas_field_metadata.json'
$runtime = Join-Path $outputDirectory 'gas_field_runtime.lua'
$manifest = Join-Path $outputDirectory 'gas_field_manifest.json'

& $python -m projects.dual_cone_tandem_quadrupole_ion_interface.analysis.export_simion_gas_runtime `
    --csv $csv --metadata $metadata --output-lua $runtime --output-manifest $manifest
if ($LASTEXITCODE -ne 0) {
    throw "COMSOL-to-SIMION gas runtime compilation failed with exit code $LASTEXITCODE."
}
Write-Output "SIMION_GAS_FIELD_MANIFEST=$manifest"
