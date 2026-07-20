param(
  [ValidateSet('Static','Candidate','Formal')][string]$Level = 'Static',
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$PythonExe = '',
  [ValidateSet('SIMION','COMSOL','CAD')][string]$CandidateTarget = 'SIMION',
  [string]$CandidateModelPath,
  [string]$CandidateContractPath,
  [string]$CandidateCadAssemblyPath,
  [string]$CandidateCadReportPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python 3.11 runtime missing: $python" }
$gateTimer = [Diagnostics.Stopwatch]::StartNew()

& $python (Join-Path $projectRoot 'analysis\resolve_geometry.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Resolved-geometry gate failed.' }
& $python (Join-Path $projectRoot 'analysis\sync_geometry_contract.py') --check
if ($LASTEXITCODE -ne 0) { throw 'Generated-input freshness gate failed.' }
& $python (Join-Path $projectRoot 'analysis\prepare_rf_handoff_projection.py') --check-mode
if ($LASTEXITCODE -ne 0) { throw 'RF handoff consumer-mode gate failed.' }
& $python (Join-Path $projectRoot 'analysis\accelerator_time_focus.py') --self-test
if ($LASTEXITCODE -ne 0) { throw 'Accelerator theory self-test failed.' }
& $python (Join-Path $projectRoot 'analysis\reflectron_dual_stage_solver.py') --self-test
if ($LASTEXITCODE -ne 0) { throw 'Reflectron theory self-test failed.' }
& $python (Join-Path $projectRoot 'analysis\oatof_oaaccelerator_coupling.py') --self-test
if ($LASTEXITCODE -ne 0) { throw 'Coupled longitudinal theory self-test failed.' }
& $python (Join-Path $projectRoot 'analysis\accelerator_time_focus.py') `
  (Join-Path $projectRoot 'config\candidates\accelerator_grid_aligned_strict_focus.json') | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Accelerator theory contract gate failed.' }
& $python (Join-Path $projectRoot 'analysis\oatof_oaaccelerator_coupling.py') `
  (Join-Path $projectRoot 'config\candidates\oatof_longitudinal_coupled_reference.json') | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Coupled longitudinal theory contract gate failed.' }
& (Join-Path $projectRoot 'tests\cross_solver\verify_geometry_contract.ps1') -SkipRuntime -SimionExe $SimionExe -PythonExe $python
if ($LASTEXITCODE -ne 0) { throw 'Static cross-solver geometry gate failed.' }
& $python -m unittest discover -s (Join-Path $projectRoot 'tests\analysis') -p 'test_*.py'
if ($LASTEXITCODE -ne 0) { throw 'Python analysis tests failed.' }

if ($Level -eq 'Candidate') {
  if ($CandidateTarget -eq 'SIMION') {
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $runId = "${stamp}__gate__simion__parameterized-geometry__smoke"
    $output = Join-Path $workspaceRoot "artifacts\projects\oa_tof\runs\$runId\simion"
    & (Join-Path $projectRoot 'tests\simion\test_parameterized_geometry_build.ps1') -SimionExe $SimionExe -OutputDir $output -RunId $runId
    if ($LASTEXITCODE -ne 0) { throw 'Candidate SIMION geometry build failed.' }
  }
  elseif ($CandidateTarget -eq 'COMSOL') {
    if (-not $CandidateModelPath) { throw 'COMSOL Candidate requires -CandidateModelPath.' }
    $candidateModel = [IO.Path]::GetFullPath($CandidateModelPath)
    if (-not (Test-Path -LiteralPath $candidateModel -PathType Leaf) -or
        [IO.Path]::GetExtension($candidateModel) -ne '.mph') {
      throw "COMSOL candidate MPH is invalid: $candidateModel"
    }
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $runId = "${stamp}__gate__comsol__candidate-sync"
    $runDir = Join-Path $workspaceRoot "artifacts\projects\oa_tof\runs\$runId"
    $logDir = Join-Path $runDir 'logs'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $report = Join-Path $logDir 'comsol_sync_report.txt'
    $oldModelPath = $env:OATOF_COMSOL_MODEL_PATH
    $oldContractPath = $env:OATOF_CONTRACT_PATH
    try {
      $env:OATOF_COMSOL_MODEL_PATH = $candidateModel
      if ($CandidateContractPath) {
        $candidateContract = [IO.Path]::GetFullPath($CandidateContractPath)
        if (-not (Test-Path -LiteralPath $candidateContract -PathType Leaf)) {
          throw "COMSOL candidate contract is invalid: $candidateContract"
        }
        $env:OATOF_CONTRACT_PATH = $candidateContract
      }
      else {
        Remove-Item Env:OATOF_CONTRACT_PATH -ErrorAction SilentlyContinue
      }
      & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
        -TaskScript (Join-Path $projectRoot 'tests\comsol\verify_oatof_comsol_sync.m') `
        -ReportPath $report
      if ($LASTEXITCODE -ne 0) { throw 'Candidate COMSOL MPH gate failed.' }
    }
    finally {
      if ($null -eq $oldModelPath) { Remove-Item Env:OATOF_COMSOL_MODEL_PATH -ErrorAction SilentlyContinue }
      else { $env:OATOF_COMSOL_MODEL_PATH = $oldModelPath }
      if ($null -eq $oldContractPath) { Remove-Item Env:OATOF_CONTRACT_PATH -ErrorAction SilentlyContinue }
      else { $env:OATOF_CONTRACT_PATH = $oldContractPath }
    }
    $runConfig = Join-Path $runDir 'run_config.json'
    [ordered]@{schema_version=1;run_id=$runId;project='oa_tof';mode='comsol_candidate_sync_gate';project_root=$projectRoot;inputs=[ordered]@{candidate_model=$candidateModel};formal_gate_passed=$false} |
      ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $runConfig -Encoding UTF8
    $summary = Join-Path $runDir 'summary.json'
    [ordered]@{schema_version=1;role='oa_tof_comsol_candidate_gate_summary';status='success'} |
      ConvertTo-Json | Set-Content -LiteralPath $summary -Encoding UTF8
    & $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') --run-config $runConfig --status success --software 'COMSOL 6.4 via MATLAB R2025b' --output $report --output $summary
    if ($LASTEXITCODE -ne 0) { throw 'COMSOL candidate gate manifest failed.' }
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
  & $python (Join-Path $repoRoot 'common\contracts\verify_artifact_layout.py') `
    (Join-Path $workspaceRoot 'artifacts\projects') --formal-only --repository-root $repoRoot
  if ($LASTEXITCODE -ne 0) { throw 'Formal asset-manifest structure gate failed.' }
  & (Join-Path $repoRoot 'common\verify_toolchain.ps1')
  if ($LASTEXITCODE -ne 0) { throw 'Toolchain gate failed.' }

  $formalModel = Join-Path $workspaceRoot 'artifacts\projects\oa_tof\formal\comsol\oa_tof__model.mph'
  $formalStamp = Get-Date -Format 'yyyyMMdd_HHmmss'
  $formalRunId = "${formalStamp}__gate__comsol__formal-sync"
  $formalRunDir = Join-Path $workspaceRoot "artifacts\projects\oa_tof\runs\$formalRunId"
  $formalLogDir = Join-Path $formalRunDir 'logs'
  New-Item -ItemType Directory -Path $formalLogDir -Force | Out-Null
  $comsolReport = Join-Path $formalLogDir 'comsol_sync_report.txt'
  $oldModelPath = $env:OATOF_COMSOL_MODEL_PATH
  $oldContractPath = $env:OATOF_CONTRACT_PATH
  try {
    $env:OATOF_COMSOL_MODEL_PATH = $formalModel
    Remove-Item Env:OATOF_CONTRACT_PATH -ErrorAction SilentlyContinue
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
      -TaskScript (Join-Path $projectRoot 'tests\comsol\verify_oatof_comsol_sync.m') `
      -ReportPath $comsolReport
    if ($LASTEXITCODE -ne 0) { throw 'Formal COMSOL GUI-equivalent MPH gate failed.' }
  }
  finally {
    if ($null -eq $oldModelPath) { Remove-Item Env:OATOF_COMSOL_MODEL_PATH -ErrorAction SilentlyContinue }
    else { $env:OATOF_COMSOL_MODEL_PATH = $oldModelPath }
    if ($null -eq $oldContractPath) { Remove-Item Env:OATOF_CONTRACT_PATH -ErrorAction SilentlyContinue }
    else { $env:OATOF_CONTRACT_PATH = $oldContractPath }
  }
  $formalRunConfig = Join-Path $formalRunDir 'run_config.json'
  [ordered]@{schema_version=1;run_id=$formalRunId;project='oa_tof';mode='comsol_formal_sync_gate';project_root=$projectRoot;inputs=[ordered]@{formal_model=$formalModel};formal_gate_passed=$true} |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $formalRunConfig -Encoding UTF8
  $formalSummary = Join-Path $formalRunDir 'summary.json'
  [ordered]@{schema_version=1;role='oa_tof_comsol_formal_gate_summary';status='success'} |
    ConvertTo-Json | Set-Content -LiteralPath $formalSummary -Encoding UTF8
  & $python (Join-Path $repoRoot 'common\contracts\write_run_manifest.py') --run-config $formalRunConfig --status success --software 'COMSOL 6.4 via MATLAB R2025b' --output $comsolReport --output $formalSummary
  if ($LASTEXITCODE -ne 0) { throw 'COMSOL formal gate manifest failed.' }

  & (Join-Path $projectRoot 'tests\cross_solver\verify_geometry_contract.ps1') -SimionExe $SimionExe
  if ($LASTEXITCODE -ne 0) { throw 'Formal runtime/CAD/COMSOL gate failed.' }

  & (Join-Path $projectRoot 'analysis\verify_reference_analysis.ps1')
  if ($LASTEXITCODE -ne 0) { throw 'Formal Python reference-analysis gate failed.' }
}

$gateTimer.Stop()
"PROJECT_GATE=PASS PROJECT=oa_tof LEVEL=$Level ELAPSED_SECONDS=$([Math]::Round($gateTimer.Elapsed.TotalSeconds, 3))"
