[CmdletBinding()]
param(
  [string]$ConnectorCaseId = 'nominal_gap_1mm',
  [string]$Stamp = '',
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling\runs'
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
. (Join-Path $projectRoot 'tests\support\rf_run_artifact_support.ps1')
if ([string]::IsNullOrWhiteSpace($Stamp)) { $Stamp = Get-Date -Format 'yyyyMMdd_HHmmss' }
if ($Stamp -notmatch '^\d{8}_\d{6}$') { throw 'Stamp must use yyyyMMdd_HHmmss.' }

$casesPath = Join-Path $projectRoot 'config\rf_to_oatof_connector_cases.json'
$cases = Get-Content -LiteralPath $casesPath -Raw -Encoding UTF8 | ConvertFrom-Json
$selected = @($cases.cases | Where-Object { $_.case_id -eq $ConnectorCaseId })
if ($selected.Count -ne 1) { throw "Connector case must resolve uniquely: $ConnectorCaseId" }
$gapMm = [double]$selected[0].connector_gap_mm
$gapLabel = ('{0:g}' -f $gapMm).Replace('.','p')
$s2RunId = "${Stamp}__sim__comsol__rf-oatof-s2-connector-gap${gapLabel}__n100"
$s3RunId = "${Stamp}__sim__comsol__rf-oatof-s3-pulse-gap${gapLabel}__n100"
$endToEndRunId = "${Stamp}__sim__cross__rf-oatof-s3-end-to-end-gap${gapLabel}__n100"

& (Join-Path $projectRoot 'tests\comsol\run_s2_passive_connector_field.ps1') `
  -RunId $s2RunId -Particles -ConnectorCaseId $ConnectorCaseId -PythonExe $python
if ($LASTEXITCODE -ne 0) { throw 'S3 cumulative chain stopped at the S2 particle stage.' }
& (Join-Path $projectRoot 'tests\comsol\run_s3_pulse_capture.ps1') `
  -SourceRunId $s2RunId -RunId $s3RunId -PythonExe $python
if ($LASTEXITCODE -ne 0) { throw 'S3 cumulative chain stopped at the pulse-capture stage.' }
& (Join-Path $projectRoot 'tests\cross_solver\run_s3_end_to_end.ps1') `
  -SourceRunId $s3RunId -RunId $endToEndRunId -SimionExe $SimionExe -PythonExe $python
if ($LASTEXITCODE -ne 0) { throw 'S3 cumulative chain stopped at the oaTOF analyzer stage.' }

$endToEndRun = Resolve-RfDirectChildDirectory -ParentRoot $artifactRoot `
  -ChildName $endToEndRunId -Role 'end-to-end run id'
$snapshotRoot = Join-Path $endToEndRun 'inputs\runtime_snapshot'
$manifestVerifier = Join-Path $snapshotRoot 'common\contracts\verify_run_manifest.py'
if (-not (Test-Path -LiteralPath $manifestVerifier -PathType Leaf)) {
  throw 'Cumulative-chain frozen manifest verifier is missing.'
}
$verificationCases = @(
  [pscustomobject]@{
    run_id=$s2RunId; mode='rf_to_oatof_s2_passive_connector_n100'
  },
  [pscustomobject]@{
    run_id=$s3RunId; mode='rf_to_oatof_s3_shared_clock_pulse_capture_n100'
  },
  [pscustomobject]@{
    run_id=$endToEndRunId; mode='rf_to_oatof_s3_cumulative_end_to_end'
  }
)
$environmentNames = @('PYTHONPATH','PYTHONNOUSERSITE')
$savedEnvironment = Save-RfEnvironment -Names $environmentNames
try {
  $env:PYTHONPATH = $snapshotRoot
  $env:PYTHONNOUSERSITE = '1'
  Push-Location -LiteralPath $snapshotRoot
  try {
    foreach ($case in $verificationCases) {
      $run = Resolve-RfDirectChildDirectory -ParentRoot $artifactRoot `
        -ChildName $case.run_id -Role 'cumulative stage run id'
      & $python $manifestVerifier (Join-Path $run 'run_manifest.json') `
        --require-status success --require-run-id $case.run_id `
        --require-project rf_quadrupole_collision_cooling `
        --require-mode $case.mode
      if ($LASTEXITCODE -ne 0) {
        throw "Cumulative-chain manifest verification failed: $($case.run_id)"
      }
    }
  } finally {
    Pop-Location
  }
} finally {
  Restore-RfEnvironment -Names $environmentNames -Snapshot $savedEnvironment
}
$summary = Get-Content -LiteralPath (Join-Path $endToEndRun 'summary.json') `
  -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Output ("S3_CUMULATIVE_CHAIN=PASS CASE={0} GAP_MM={1:g} RUN_ID={2} HITS={3}/{4}" -f `
  $ConnectorCaseId,$gapMm,$endToEndRunId,$summary.census.detector_hit,$summary.census.local_accelerator_exit)
