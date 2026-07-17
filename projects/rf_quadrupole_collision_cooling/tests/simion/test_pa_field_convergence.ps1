param(
    [double]$CellMm = 0.1,
    [string]$RunLabel = 'cell010'
)

$ErrorActionPreference = 'Stop'
if ($CellMm -le 0 -or $CellMm -gt 0.2) { throw 'CellMm must be in (0, 0.2].' }
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$candidateDir = Join-Path $artifactRoot "models\simion\candidates\quad_field_$RunLabel"
$resultDir = Join-Path $artifactRoot 'results\simion'
$runDir = Join-Path $artifactRoot "runs\pa_field_convergence\$RunLabel"
$simion = 'C:\Program Files\SIMION-2020\simion.exe'
$officialIob = 'C:\Program Files\SIMION-2020\examples\quad\quad_monolithic.iob'

New-Item -ItemType Directory -Path $candidateDir,$resultDir,$runDir -Force | Out-Null
$sourceGem = Join-Path $projectRoot 'simion\geometry\quad_monolithic.gem'
$gemText = Get-Content -LiteralPath $sourceGem -Raw -Encoding UTF8
$expected = '# local mmgu = 0.2'
if (-not $gemText.Contains($expected)) { throw 'Authority GEM no longer contains the expected mmgu line.' }
$gemText = $gemText.Replace($expected, ('# local mmgu = {0:R}' -f $CellMm))
Set-Content -LiteralPath (Join-Path $candidateDir 'quad_monolithic.gem') -Value $gemText -Encoding UTF8 -NoNewline
Copy-Item -LiteralPath (Join-Path $projectRoot 'simion\geometry\quad_include.gem') -Destination $candidateDir -Force
Copy-Item -LiteralPath $officialIob -Destination (Join-Path $candidateDir 'quad_monolithic.iob') -Force

Push-Location $candidateDir
try {
    & $simion --nogui gem2pa quad_monolithic.gem quad_monolithic.pa#
    if ($LASTEXITCODE -ne 0) { throw 'SIMION gem2pa failed.' }
    & $simion --nogui refine quad_monolithic.pa#
    if ($LASTEXITCODE -ne 0) { throw 'SIMION refine failed.' }
    $env:RFQUAD_SIMION_PA_PATH = Join-Path $candidateDir 'quad_monolithic.pa0'
    $env:RFQUAD_SIMION_UNIT_RF_FIELD_CSV = Join-Path $resultDir "unit_rf_field_pa_grid_$RunLabel.csv"
    $env:RFQUAD_SIMION_UNIT_RF_FIELD_REPORT = Join-Path $runDir 'field_export.txt'
    & $simion --nogui lua (Join-Path $PSScriptRoot 'export_unit_rf_field.lua')
    if ($LASTEXITCODE -ne 0) { throw 'SIMION unit-field export failed.' }
}
finally {
    Remove-Item Env:RFQUAD_SIMION_PA_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_SIMION_UNIT_RF_FIELD_CSV -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_SIMION_UNIT_RF_FIELD_REPORT -ErrorAction SilentlyContinue
    Pop-Location
}

$report = Get-Content -LiteralPath (Join-Path $runDir 'field_export.txt') -Raw
if ($report -notmatch 'STATUS=PASS') { throw "SIMION field export gate failed: $report" }
"STATUS=PASS LABEL=$RunLabel CELL_MM=$CellMm"
