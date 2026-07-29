[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$ConnectionProfileId,
  [Parameter(Mandatory)][string]$ResolvedConnection,
  [Parameter(Mandatory)][string]$ResolvedEngineeringBudget,
  [string]$Stamp = '',
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_ion_optics\runs'
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
. (Join-Path $projectRoot 'runtime\run_artifacts.ps1')
if ([string]::IsNullOrWhiteSpace($Stamp)) { $Stamp = Get-Date -Format 'yyyyMMdd_HHmmss' }
if ($Stamp -notmatch '^\d{8}_\d{6}$') { throw 'Stamp must use yyyyMMdd_HHmmss.' }

$resolved = Get-Content -LiteralPath $ResolvedConnection -Raw -Encoding UTF8 | ConvertFrom-Json
if ($resolved.selection.connection_profile_id -ne $ConnectionProfileId) {
  throw 'Resolved connection identity differs from ConnectionProfileId.'
}
$gapMm = [double]$resolved.connector.length_mm
$gapLabel = ('{0:g}' -f $gapMm).Replace('.','p')
$prePulseRunId = "${Stamp}__sim__comsol__rf-oatof-pre-pulse-interface-gap${gapLabel}__n100"
$pulseCaptureRunId = "${Stamp}__sim__comsol__rf-oatof-pulse-capture-gap${gapLabel}__n100"
$analyzerRunId = "${Stamp}__sim__cross__rf-oatof-analyzer-transport-gap${gapLabel}__n100"

& (Join-Path $projectRoot 'workflows\rf_to_oatof_integration\comsol\run_pre_pulse_interface_transport.ps1') `
  -RunId $prePulseRunId -Particles -ConnectionProfileId $ConnectionProfileId `
  -ResolvedConnection $ResolvedConnection `
  -ResolvedEngineeringBudget $ResolvedEngineeringBudget -PythonExe $python
if ($LASTEXITCODE -ne 0) { throw 'RF-to-oaTOF transfer stopped at pre_pulse_interface_transport.' }
& (Join-Path $projectRoot 'workflows\rf_to_oatof_integration\comsol\run_pulse_capture.ps1') `
  -SourceRunId $prePulseRunId -RunId $pulseCaptureRunId `
  -ResolvedEngineeringBudget $ResolvedEngineeringBudget -PythonExe $python
if ($LASTEXITCODE -ne 0) { throw 'RF-to-oaTOF transfer stopped at pulse_capture.' }
& (Join-Path $projectRoot 'workflows\rf_to_oatof_integration\cross_solver\run_analyzer_transport.ps1') `
  -SourceRunId $pulseCaptureRunId -RunId $analyzerRunId `
  -ResolvedEngineeringBudget $ResolvedEngineeringBudget `
  -SimionExe $SimionExe -PythonExe $python
if ($LASTEXITCODE -ne 0) { throw 'RF-to-oaTOF transfer stopped at analyzer_transport.' }

$endToEndRun = Resolve-RfDirectChildDirectory -ParentRoot $artifactRoot `
  -ChildName $analyzerRunId -Role 'analyzer transport run id'
$snapshotRoot = Join-Path $endToEndRun 'inputs\runtime_snapshot'
$manifestVerifier = Join-Path $snapshotRoot 'common\contracts\verify_run_manifest.py'
if (-not (Test-Path -LiteralPath $manifestVerifier -PathType Leaf)) {
  throw 'Cumulative-chain frozen manifest verifier is missing.'
}
$verificationCases = @(
  [pscustomobject]@{
    run_id=$prePulseRunId; mode='rf_to_oatof_pre_pulse_interface_transport_n100'
  },
  [pscustomobject]@{
    run_id=$pulseCaptureRunId; mode='rf_to_oatof_pulse_capture_n100'
  },
  [pscustomobject]@{
    run_id=$analyzerRunId; mode='rf_to_oatof_analyzer_transport_n100'
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
        --require-project rf_quadrupole_ion_optics `
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
Write-Output ("RF_TO_OATOF_TRANSFER=PASS PROFILE={0} GAP_MM={1:g} RUN_ID={2} HITS={3}/{4}" -f `
  $ConnectionProfileId,$gapMm,$analyzerRunId,$summary.census.detector_hit,$summary.census.local_accelerator_exit)
