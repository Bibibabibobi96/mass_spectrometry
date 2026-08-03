[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$ConnectionProfileId,
  [Parameter(Mandatory)][string]$ResolvedConnection,
  [Parameter(Mandatory)][string]$ResolvedEngineeringBudget,
  [Parameter(Mandatory)][string]$RuntimeBinding,
  [Parameter(Mandatory)][ValidateSet('comsol','simion')]
  [string]$SourceBranchId,
  [Parameter(Mandatory)][string]$ResolvedSourceContract,
  [Parameter(Mandatory)][string]$ResolvedSourceContractSha256,
  [Parameter(Mandatory)][string]$UpstreamResolvedDesign,
  [Parameter(Mandatory)][string]$UpstreamResolvedDesignSha256,
  [string]$Stamp = '',
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$integrationRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot = (Resolve-Path (Join-Path $integrationRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
. (Join-Path $PSScriptRoot 'runtime_binding.ps1')
if ([string]::IsNullOrWhiteSpace($Stamp)) { $Stamp = Get-Date -Format 'yyyyMMdd_HHmmss' }
if ($Stamp -notmatch '^\d{8}_\d{6}$') { throw 'Stamp must use yyyyMMdd_HHmmss.' }

$runtime = Resolve-RfOatofRuntimeBinding -RepoRoot $repoRoot `
  -ResolvedConnection $ResolvedConnection -RuntimeBinding $RuntimeBinding `
  -ExpectedConnectionProfileId $ConnectionProfileId `
  -SourceBranchId $SourceBranchId `
  -ResolvedSourceContract $ResolvedSourceContract `
  -ResolvedSourceContractSha256 $ResolvedSourceContractSha256 `
  -UpstreamResolvedDesign $UpstreamResolvedDesign `
  -UpstreamResolvedDesignSha256 $UpstreamResolvedDesignSha256
$upstreamProjectId = $runtime.upstream_project_id
$artifactRoot = Join-Path $workspaceRoot "artifacts\projects\$upstreamProjectId\runs"
. $runtime.run_artifact_support
$resolved = $runtime.resolved_connection
$gapMm = [double]$resolved.connector.length_mm
$gapLabel = ('{0:g}' -f $gapMm).Replace('.','p')
$particleCount = [int]$runtime.source_record.particle_count
$populationLabel = "n$particleCount"
$prePulseRunId = "${Stamp}__sim__comsol__rf-oatof-pre-pulse-interface-gap${gapLabel}__${populationLabel}"
$pulseCaptureRunId = "${Stamp}__sim__comsol__rf-oatof-pulse-capture-gap${gapLabel}__${populationLabel}"
$analyzerRunId = "${Stamp}__sim__cross__rf-oatof-analyzer-transport-gap${gapLabel}__${populationLabel}"

& $runtime.implementation.pre_pulse_runner `
  -RunId $prePulseRunId -Particles -ConnectionProfileId $ConnectionProfileId `
  -ResolvedConnection $ResolvedConnection `
  -ResolvedEngineeringBudget $ResolvedEngineeringBudget `
  -RuntimeBinding $RuntimeBinding -SourceBranchId $SourceBranchId `
  -ResolvedSourceContract $ResolvedSourceContract `
  -ResolvedSourceContractSha256 $ResolvedSourceContractSha256 `
  -UpstreamResolvedDesign $UpstreamResolvedDesign `
  -UpstreamResolvedDesignSha256 $UpstreamResolvedDesignSha256 `
  -PythonExe $python
if ($LASTEXITCODE -ne 0) { throw 'RF-to-oaTOF transfer stopped at pre_pulse_interface_transport.' }
& $runtime.implementation.pulse_capture_runner `
  -SourceRunId $prePulseRunId -RunId $pulseCaptureRunId `
  -ExpectedConnectionProfileId $ConnectionProfileId `
  -ResolvedConnection $ResolvedConnection `
  -ResolvedEngineeringBudget $ResolvedEngineeringBudget `
  -RuntimeBinding $RuntimeBinding -SourceBranchId $SourceBranchId `
  -ResolvedSourceContract $ResolvedSourceContract `
  -ResolvedSourceContractSha256 $ResolvedSourceContractSha256 `
  -UpstreamResolvedDesign $UpstreamResolvedDesign `
  -UpstreamResolvedDesignSha256 $UpstreamResolvedDesignSha256 `
  -PythonExe $python
if ($LASTEXITCODE -ne 0) { throw 'RF-to-oaTOF transfer stopped at pulse_capture.' }
& $runtime.implementation.analyzer_transport_runner `
  -SourceRunId $pulseCaptureRunId -RunId $analyzerRunId `
  -ExpectedConnectionProfileId $ConnectionProfileId `
  -ResolvedConnection $ResolvedConnection `
  -ResolvedEngineeringBudget $ResolvedEngineeringBudget `
  -RuntimeBinding $RuntimeBinding -SourceBranchId $SourceBranchId `
  -ResolvedSourceContract $ResolvedSourceContract `
  -ResolvedSourceContractSha256 $ResolvedSourceContractSha256 `
  -UpstreamResolvedDesign $UpstreamResolvedDesign `
  -UpstreamResolvedDesignSha256 $UpstreamResolvedDesignSha256 `
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
    run_id=$prePulseRunId; mode='rf_to_oatof_pre_pulse_interface_transport'
  },
  [pscustomobject]@{
    run_id=$pulseCaptureRunId; mode='rf_to_oatof_pulse_capture'
  },
  [pscustomobject]@{
    run_id=$analyzerRunId; mode='rf_to_oatof_analyzer_transport'
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
        --require-project $upstreamProjectId `
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
