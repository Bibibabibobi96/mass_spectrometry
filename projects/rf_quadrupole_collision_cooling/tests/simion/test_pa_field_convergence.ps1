param(
    [double]$CellMm = 0.1,
    [string]$RunId = ''
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__test__simion__pa-field-convergence__cell010'
}
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
$runDir = Join-Path $artifactRoot "runs\$RunId"
$candidateDir = Join-Path $runDir 'simion'
$resultDir = Join-Path $runDir 'results'
$logDir = Join-Path $runDir 'logs'
$simion = 'C:\Program Files\SIMION-2020\simion.exe'
$officialIob = 'C:\Program Files\SIMION-2020\examples\quad\quad_monolithic.iob'
$resolved = Get-Content -LiteralPath (Join-Path $projectRoot 'config\resolved_geometry.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$baselineCellMm = [double]$resolved.geometry_mm.simion_cell_mm
if ($CellMm -le 0 -or $CellMm -gt $baselineCellMm) { throw "CellMm must be in (0, $baselineCellMm]." }

New-Item -ItemType Directory -Path $candidateDir,$resultDir,$runDir,$logDir -Force | Out-Null
$sourceGem = Join-Path $projectRoot 'simion\geometry\quad_monolithic.gem'
$gemText = Get-Content -LiteralPath $sourceGem -Raw -Encoding UTF8
$expected = '# local mmgu = {0:R}' -f $baselineCellMm
if (-not $gemText.Contains($expected)) { throw 'Authority GEM no longer contains the expected mmgu line.' }
$gemText = $gemText.Replace($expected, ('# local mmgu = {0:R}' -f $CellMm))
Set-Content -LiteralPath (Join-Path $candidateDir 'quad_monolithic.gem') -Value $gemText -Encoding ASCII -NoNewline
Copy-Item -LiteralPath (Join-Path $projectRoot 'simion\geometry\quad_include.gem') -Destination $candidateDir -Force
Copy-Item -LiteralPath $officialIob -Destination (Join-Path $candidateDir 'quad_monolithic.iob') -Force

Push-Location $candidateDir
try {
    & $simion --nogui gem2pa quad_monolithic.gem quad_monolithic.pa#
    if ($LASTEXITCODE -ne 0) { throw 'SIMION gem2pa failed.' }
    & $simion --nogui refine quad_monolithic.pa#
    if ($LASTEXITCODE -ne 0) { throw 'SIMION refine failed.' }
    $env:RFQUAD_SIMION_PA_PATH = Join-Path $candidateDir 'quad_monolithic.pa0'
    $env:RFQUAD_SIMION_UNIT_RF_FIELD_CSV = Join-Path $resultDir 'unit_rf_field_pa_grid.csv'
    $env:RFQUAD_SIMION_UNIT_RF_FIELD_REPORT = Join-Path $logDir 'field_export.txt'
    $env:RFQUAD_FIELD_X_MIN_MM = [string](-$resolved.geometry_mm.field_radius_r0/2)
    $env:RFQUAD_FIELD_X_MAX_MM = [string]($resolved.geometry_mm.field_radius_r0/2)
    $env:RFQUAD_FIELD_Y_MIN_MM = [string](-$resolved.geometry_mm.field_radius_r0/2)
    $env:RFQUAD_FIELD_Y_MAX_MM = [string]($resolved.geometry_mm.field_radius_r0/2)
    $env:RFQUAD_FIELD_Z_MIN_MM = [string]$baselineCellMm
    $env:RFQUAD_FIELD_Z_MAX_MM = [string]($resolved.coordinate_convention.detector_plane_z_mm-2*$baselineCellMm)
    $env:RFQUAD_FIELD_STEP_MM = [string]$baselineCellMm
    & $simion --nogui lua (Join-Path $PSScriptRoot 'export_unit_rf_field.lua')
    if ($LASTEXITCODE -ne 0) { throw 'SIMION unit-field export failed.' }
}
finally {
    Remove-Item Env:RFQUAD_SIMION_PA_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_SIMION_UNIT_RF_FIELD_CSV -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_SIMION_UNIT_RF_FIELD_REPORT -ErrorAction SilentlyContinue
    Remove-Item Env:RFQUAD_FIELD_X_MIN_MM,Env:RFQUAD_FIELD_X_MAX_MM,Env:RFQUAD_FIELD_Y_MIN_MM,Env:RFQUAD_FIELD_Y_MAX_MM,Env:RFQUAD_FIELD_Z_MIN_MM,Env:RFQUAD_FIELD_Z_MAX_MM,Env:RFQUAD_FIELD_STEP_MM -ErrorAction SilentlyContinue
    Pop-Location
}

$reportPath = Join-Path $logDir 'field_export.txt'
$report = Get-Content -LiteralPath $reportPath -Raw
if ($report -notmatch 'STATUS=PASS') { throw "SIMION field export gate failed: $report" }
$runConfigPath = Join-Path $runDir 'run_config.json'
[ordered]@{schema_version=1;run_id=$RunId;project='rf_quadrupole_collision_cooling';mode='pa_field_convergence';project_root=$projectRoot;inputs=[ordered]@{resolved_geometry='config/resolved_geometry.json'};formal_gate_passed=$false;cell_mm=$CellMm} |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8
$summaryPath = Join-Path $runDir 'summary.json'
[ordered]@{schema_version=1;role='rf_quadrupole_pa_field_summary';status='success';cell_mm=$CellMm} |
    ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
& $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') --run-config $runConfigPath --status success --software 'SIMION 2020' `
    --output (Join-Path $candidateDir 'quad_monolithic.pa0') --output (Join-Path $resultDir 'unit_rf_field_pa_grid.csv') --output $reportPath --output $summaryPath
if ($LASTEXITCODE -ne 0) { throw 'Run-manifest generation failed.' }
"STATUS=PASS RUN_ID=$RunId CELL_MM=$CellMm"
