[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$CoarseRefinementRunPath,
  [Parameter(Mandatory)][string]$FixedGridRunPath,
  [string]$NativeL1RunPath = '',
  [string]$GammaGradientSourceRunPath = '',
  [string]$SourceCorrectionRunPath = '',
  [string]$SecantFixedGridRunPath = '',
  [string]$RunId = '',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectId = 'parallel_mirror_dual_stripe_mr_tof'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$python = if ($PythonExe) { [IO.Path]::GetFullPath($PythonExe) } else { Join-Path $repoRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Python 3.11 environment is missing: $python" }
if ([string]::IsNullOrWhiteSpace($RunId)) {
  $RunId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__analysis__python__mrtof-fixed-grid-voltage-correction'
}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$coarse = (Resolve-Path -LiteralPath $CoarseRefinementRunPath).Path
$fixed = (Resolve-Path -LiteralPath $FixedGridRunPath).Path
$nativeL1 = if ([string]::IsNullOrWhiteSpace($NativeL1RunPath)) { $null } else { (Resolve-Path -LiteralPath $NativeL1RunPath).Path }
$gradientSource = if ([string]::IsNullOrWhiteSpace($GammaGradientSourceRunPath)) { $null } else { (Resolve-Path -LiteralPath $GammaGradientSourceRunPath).Path }
$sourceCorrection = if ([string]::IsNullOrWhiteSpace($SourceCorrectionRunPath)) { $null } else { (Resolve-Path -LiteralPath $SourceCorrectionRunPath).Path }
$secantFixed = if ([string]::IsNullOrWhiteSpace($SecantFixedGridRunPath)) { $null } else { (Resolve-Path -LiteralPath $SecantFixedGridRunPath).Path }
if (($null -eq $sourceCorrection) -ne ($null -eq $secantFixed)) {
  throw 'SourceCorrectionRunPath and SecantFixedGridRunPath are required together.'
}
if ($sourceCorrection -and $gradientSource) {
  throw 'GammaGradientSourceRunPath is only valid for the one-point correction workflow.'
}
if ($nativeL1 -and ($gradientSource -or $sourceCorrection)) {
  throw 'NativeL1RunPath is only valid for a fresh one-point native-selector correction.'
}
$inputRoots = @($coarse, $fixed) + $(if ($nativeL1) { @($nativeL1) } else { @() }) + $(if ($gradientSource) { @($gradientSource) } else { @() }) + $(if ($sourceCorrection) { @($sourceCorrection, $secantFixed) } else { @() })
foreach ($root in $inputRoots) {
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
    (Join-Path $root 'run_manifest.json') --require-status success
  if ($LASTEXITCODE -ne 0) { throw "Input manifest failed: $root" }
}
$package = New-RunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot (Join-Path $workspaceRoot "artifacts\projects\$projectId") `
  -RunId $RunId -Project $projectId -Mode 'fixed_grid_multifidelity_voltage_correction' `
  -Software @('Python 3.11') -RetentionContractEnabled -RetentionClass compact
$runDir = $package.run_dir
$inputDir = $package.input_dir
$resultDir = $package.result_dir
$logDir = $package.log_dir
$runConfig = $package.run_config
$summary = $package.summary
$terminalized = $false
$lease = $null
try {
  $contract = Copy-VerifiedRunInput `
    -Source (Join-Path $repoRoot "projects\$projectId\config\simion_candidate_two_zone.json") `
    -Destination (Join-Path $inputDir 'simion_candidate_two_zone.json')
  $result = Join-Path $resultDir 'fixed_grid_multifidelity_voltage_correction.json'
  Push-Location -LiteralPath $repoRoot
  $savedPythonPath = $env:PYTHONPATH
  try {
    $env:PYTHONPATH = $repoRoot
    $arguments = @('-m', 'projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_fixed_grid_voltage_correction',
      '--refinement', (Join-Path $coarse 'results\real_3d_mirror_l1_continuous_refinement.json'),
      '--family', (Join-Path $coarse 'inputs\real_3d_mirror_l0_voltage_family.json'),
      '--axis-basis', (Join-Path $coarse 'inputs\real_3d_mirror_axis_response_basis.csv'),
      '--l1-basis', (Join-Path $coarse 'inputs\real_3d_mirror_l1_response_basis.csv'),
      '--sampling-plan', (Join-Path $coarse 'inputs\mirror_l1_response_sampling_plan.json'),
      '--fixed-probe-contract', (Join-Path $fixed 'results\mirror_period_probe_contract.json'),
      '--fixed-period', (Join-Path $fixed 'results\mirror_real_field_period_comparison.json'),
      '--fixed-l1', (Join-Path $fixed 'results\fixed_operating_field_l1.json'),
      '--fixed-project-contract', (Join-Path $fixed 'inputs\simion_candidate_two_zone.json'),
      '--project-contract', $contract, '--output', $result)
    if ($gradientSource) {
      $arguments += @('--gamma-gradient-source', (Join-Path $gradientSource 'results\fixed_grid_multifidelity_voltage_correction.json'))
    }
    if ($nativeL1) {
      $arguments += @(
        '--native-l1', (Join-Path $nativeL1 'results\native_transverse_l1.json'),
        '--native-l1-probe', (Join-Path $nativeL1 'results\native_transverse_l1_probe_contract.json')
      )
    }
    if ($sourceCorrection) {
      $arguments += @(
        '--source-correction', (Join-Path $sourceCorrection 'results\fixed_grid_multifidelity_voltage_correction.json'),
        '--secant-point', (Join-Path $secantFixed 'results\fixed_grid_voltage_point.json'),
        '--secant-probe-contract', (Join-Path $secantFixed 'results\mirror_period_probe_contract.json'),
        '--secant-period', (Join-Path $secantFixed 'results\mirror_real_field_period_comparison.json'),
        '--secant-l1', (Join-Path $secantFixed 'results\fixed_operating_field_l1.json'),
        '--secant-project-contract', (Join-Path $secantFixed 'inputs\simion_candidate_two_zone.json')
      )
    }
    $lease = Enter-HostExecutionLease -Role GATE -Stage theory_compute -RunId $RunId
    $analysisLog = Join-Path $logDir 'analysis_python.log'
    & $python @arguments *>&1 | Tee-Object -FilePath $analysisLog
    $pythonExitCode = $LASTEXITCODE
    if ($pythonExitCode -ne 0) { throw "Fixed-grid voltage correction analysis failed; see $analysisLog" }
    Exit-HostExecutionLease -Lease $lease -Outcome success -RunId $RunId
    $lease = $null
  } finally {
    $env:PYTHONPATH = $savedPythonPath
    Pop-Location
  }
  $value = Get-Content -LiteralPath $result -Raw | ConvertFrom-Json -Depth 40
  Write-RunJson -Path $summary -Depth 20 -Value ([ordered]@{
    schema_version = 1
    role = 'mrtof_fixed_grid_multifidelity_voltage_correction'
    status = [string]$value.status
    qualification = [string]$value.qualification
    source_mirror_voltages_v = @($value.source_mirror_voltages_v)
    proposed_mirror_voltages_v = if ($value.PSObject.Properties['proposed_mirror_voltages_v'] -and $null -ne $value.proposed_mirror_voltages_v) { @($value.proposed_mirror_voltages_v) } else { $null }
    voltage_correction_v = if ($value.PSObject.Properties['voltage_correction_v'] -and $null -ne $value.voltage_correction_v) { @($value.voltage_correction_v) } else { $null }
    predicted_corrected_normalized_period_slopes_per_v = if ($value.PSObject.Properties['predicted_corrected_normalized_period_slopes_per_v'] -and $null -ne $value.predicted_corrected_normalized_period_slopes_per_v) { @($value.predicted_corrected_normalized_period_slopes_per_v) } else { $null }
    fixed_grid_mean_directional_trace_half = [double]$value.fixed_grid_mean_directional_trace_half
  })
  $config = Get-Content -LiteralPath $runConfig -Raw | ConvertFrom-Json -AsHashtable
  $config.inputs = [ordered]@{
    coarse_refinement_manifest = Join-Path $coarse 'run_manifest.json'
    fixed_grid_validation_manifest = Join-Path $fixed 'run_manifest.json'
    native_l1_manifest = if ($nativeL1) { Join-Path $nativeL1 'run_manifest.json' } else { $null }
    gamma_gradient_source_manifest = if ($gradientSource) { Join-Path $gradientSource 'run_manifest.json' } else { $null }
    source_correction_manifest = if ($sourceCorrection) { Join-Path $sourceCorrection 'run_manifest.json' } else { $null }
    secant_fixed_grid_validation_manifest = if ($secantFixed) { Join-Path $secantFixed 'run_manifest.json' } else { $null }
    project_contract = $contract
  }
  $config.parameters = [ordered]@{
    correction_model = if ($sourceCorrection) { 'rank_one_fixed_minus_coarse_secant_discrepancy' } else { 'local_constant_fixed_minus_coarse_discrepancy' }
    l0_equation_count = 3
    mirror_voltage_coordinate_count = 4
    family_nullity = 1
    gamma_role = if ($nativeL1) { 'native_SIMION_L1_family_member_selector' } else { 'L1_family_member_selector' }
  }
  Write-RunJson -Path $runConfig -Depth 20 -Value $config
  $retention = Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig `
    -Status success -Software @('Python 3.11') -Outputs @($summary, $result, $retention) | Out-Null
  $terminalized = $true
  Write-Host "MRTOF_FIXED_GRID_VOLTAGE_CORRECTION=PASS RUN_ID=$RunId"
} catch {
  if ($null -ne $lease) {
    Exit-HostExecutionLease -Lease $lease -Outcome failed -RunId $RunId
    $lease = $null
  }
  if (-not $terminalized) {
    Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig `
      -Summary $summary -SummaryRole 'mrtof_fixed_grid_multifidelity_voltage_correction' `
      -Reason $_.Exception.Message -Software @('Python 3.11') -FailureStage 'analysis'
    $terminalized = $true
  }
  throw
}
