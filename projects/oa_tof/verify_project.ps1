param(
  [ValidateSet('Static','Candidate','Formal')][string]$Level = 'Static',
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [ValidateSet('SIMION','COMSOL','CAD')][string]$CandidateTarget = 'SIMION',
  [string]$CandidateModelPath,
  [string]$CandidateCadAssemblyPath,
  [string]$CandidateCadReportPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$gateTimer = [Diagnostics.Stopwatch]::StartNew()

& $python (Join-Path $projectRoot 'analysis\resolve_geometry.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Resolved-geometry gate failed.' }
& $python (Join-Path $projectRoot 'analysis\sync_geometry_contract.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Generated-input freshness gate failed.' }
& (Join-Path $projectRoot 'tests\cross_solver\verify_geometry_contract.ps1') -SkipRuntime -SimionExe $SimionExe
if ($LASTEXITCODE -ne 0) { throw 'Static cross-solver geometry gate failed.' }
& $python -m unittest discover -s (Join-Path $projectRoot 'tests\analysis') -p 'test_*.py'
if ($LASTEXITCODE -ne 0) { throw 'Python analysis tests failed.' }

if ($Level -eq 'Candidate') {
  if ($CandidateTarget -eq 'SIMION') {
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $output = Join-Path $workspaceRoot "artifacts\projects\oa_tof\scratch\simion\parameterized_geometry_gate_$stamp"
    & (Join-Path $projectRoot 'tests\simion\test_parameterized_geometry_build.ps1') -SimionExe $SimionExe -OutputDir $output
    if ($LASTEXITCODE -ne 0) { throw 'Candidate SIMION geometry build failed.' }
  }
  elseif ($CandidateTarget -eq 'COMSOL') {
    if (-not $CandidateModelPath) { throw 'COMSOL Candidate requires -CandidateModelPath.' }
    $candidateModel = [IO.Path]::GetFullPath($CandidateModelPath)
    if (-not (Test-Path -LiteralPath $candidateModel -PathType Leaf) -or
        [IO.Path]::GetExtension($candidateModel) -ne '.mph') {
      throw "COMSOL candidate MPH is invalid: $candidateModel"
    }
    $report = Join-Path $workspaceRoot 'artifacts\projects\oa_tof\runs\candidate_gate\comsol_sync_report.txt'
    $oldModelPath = $env:OATOF_COMSOL_MODEL_PATH
    try {
      $env:OATOF_COMSOL_MODEL_PATH = $candidateModel
      & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
        -TaskScript (Join-Path $projectRoot 'tests\comsol\verify_oatof_comsol_sync.m') `
        -ReportPath $report
      if ($LASTEXITCODE -ne 0) { throw 'Candidate COMSOL MPH gate failed.' }
    }
    finally {
      if ($null -eq $oldModelPath) { Remove-Item Env:OATOF_COMSOL_MODEL_PATH -ErrorAction SilentlyContinue }
      else { $env:OATOF_COMSOL_MODEL_PATH = $oldModelPath }
    }
  }
  else {
    if (-not $CandidateCadAssemblyPath -or -not $CandidateCadReportPath) {
      throw 'CAD Candidate requires -CandidateCadAssemblyPath and -CandidateCadReportPath.'
    }
    $assembly = [IO.Path]::GetFullPath($CandidateCadAssemblyPath)
    $reportPath = [IO.Path]::GetFullPath($CandidateCadReportPath)
    if (-not (Test-Path -LiteralPath $assembly -PathType Leaf)) { throw "CAD candidate assembly is missing: $assembly" }
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) { throw "CAD candidate report is missing: $reportPath" }
    $cad = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cad.solidWorks.solidWorksRevision -notmatch '^30\.') { throw 'CAD candidate was not built by SolidWorks 2022.' }
    if ($cad.solidWorks.partCount -ne $cad.solidWorks.assembly.componentCount) { throw 'CAD candidate part/component counts differ.' }
    if ($cad.solidWorks.assembly.saveErrors -ne 0 -or $cad.solidWorks.assembly.saveWarnings -ne 0) {
      throw 'CAD candidate assembly report contains save errors or warnings.'
    }
    if (($cad.solidWorks.parts | Measure-Object -Property saveErrors -Maximum).Maximum -ne 0 -or
        ($cad.solidWorks.parts | Measure-Object -Property saveWarnings -Maximum).Maximum -ne 0) {
      throw 'CAD candidate part report contains save errors or warnings.'
    }
    "CAD_CANDIDATE_STATUS=PASS COMPONENTS=$($cad.solidWorks.assembly.componentCount)"
  }
}
elseif ($Level -eq 'Formal') {
  & (Join-Path $repoRoot 'common\verify_toolchain.ps1')
  if ($LASTEXITCODE -ne 0) { throw 'Toolchain gate failed.' }

  $formalModel = Join-Path $workspaceRoot 'artifacts\projects\oa_tof\models\comsol\formal\MS_oaTOF_TwoStageRingStackReflectron_Final.mph'
  $comsolReport = Join-Path $workspaceRoot 'artifacts\projects\oa_tof\runs\formal_gate\comsol_sync_report.txt'
  $oldModelPath = $env:OATOF_COMSOL_MODEL_PATH
  try {
    $env:OATOF_COMSOL_MODEL_PATH = $formalModel
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
      -TaskScript (Join-Path $projectRoot 'tests\comsol\verify_oatof_comsol_sync.m') `
      -ReportPath $comsolReport
    if ($LASTEXITCODE -ne 0) { throw 'Formal COMSOL GUI-equivalent MPH gate failed.' }
  }
  finally {
    if ($null -eq $oldModelPath) { Remove-Item Env:OATOF_COMSOL_MODEL_PATH -ErrorAction SilentlyContinue }
    else { $env:OATOF_COMSOL_MODEL_PATH = $oldModelPath }
  }

  & (Join-Path $projectRoot 'tests\cross_solver\verify_geometry_contract.ps1') -SimionExe $SimionExe
  if ($LASTEXITCODE -ne 0) { throw 'Formal runtime/CAD/COMSOL gate failed.' }

  & (Join-Path $projectRoot 'analysis\verify_reference_analysis.ps1')
  if ($LASTEXITCODE -ne 0) { throw 'Formal Python reference-analysis gate failed.' }
}

$gateTimer.Stop()
"PROJECT_GATE=PASS PROJECT=oa_tof LEVEL=$Level ELAPSED_SECONDS=$([Math]::Round($gateTimer.Elapsed.TotalSeconds, 3))"
