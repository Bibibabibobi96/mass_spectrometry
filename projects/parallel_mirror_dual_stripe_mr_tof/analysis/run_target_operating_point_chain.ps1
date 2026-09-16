[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$MirrorRunManifest,
  [string]$ContractPath = '',
  [string]$ChainStamp = '',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectId = 'parallel_mirror_dual_stripe_mr_tof'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$contract = if ($ContractPath) {
  (Resolve-Path -LiteralPath $ContractPath).Path
} else {
  Join-Path $PSScriptRoot '..\config\simion_candidate_two_zone.json'
}
$mirrorManifest = (Resolve-Path -LiteralPath $MirrorRunManifest).Path
if ([string]::IsNullOrWhiteSpace($ChainStamp)) {
  $ChainStamp = Get-Date -Format 'yyyyMMdd_HHmmss'
}
if ($ChainStamp -notmatch '^\d{8}_\d{6}(?:-[A-Za-z0-9][A-Za-z0-9_-]*)?$') {
  throw 'ChainStamp must be YYYYMMDD_HHMMSS with an optional safe suffix.'
}

$exactRunId = $ChainStamp + '__analysis__python__mirror-exact-k-operating-point'
$stripeRunId = $ChainStamp + '__analysis__python__dual-stripe-exact-k-operating-seed'
$artifactRoot = Join-Path $workspaceRoot "artifacts\projects\$projectId\runs"
$exactRun = Join-Path $artifactRoot $exactRunId
$stripeRun = Join-Path $artifactRoot $stripeRunId
foreach ($path in @($exactRun, $stripeRun)) {
  if (Test-Path -LiteralPath $path) {
    throw "Target operating-point chain refuses to overwrite an existing run: $path"
  }
}

$exactArguments = @{
  MirrorRunManifest = $mirrorManifest
  ContractPath = $contract
  RunId = $exactRunId
}
if ($PythonExe) { $exactArguments.PythonExe = $PythonExe }
& (Join-Path $PSScriptRoot 'run_mirror_exact_k_operating_point.ps1') @exactArguments
$exactManifest = Join-Path $exactRun 'run_manifest.json'
if (-not (Test-Path -LiteralPath $exactManifest -PathType Leaf)) {
  throw "Exact-K stage did not publish its terminal manifest: $exactManifest"
}

$stripeArguments = @{
  ExactKRunManifest = $exactManifest
  ContractPath = $contract
  RunId = $stripeRunId
}
if ($PythonExe) { $stripeArguments.PythonExe = $PythonExe }
& (Join-Path $PSScriptRoot 'run_dual_stripe_operating_seed.ps1') @stripeArguments
$stripeManifest = Join-Path $stripeRun 'run_manifest.json'
if (-not (Test-Path -LiteralPath $stripeManifest -PathType Leaf)) {
  throw "Dual-Stripe stage did not publish its terminal manifest: $stripeManifest"
}

$exactSummary = Get-Content -LiteralPath (Join-Path $exactRun 'summary.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$stripeSummary = Get-Content -LiteralPath (Join-Path $stripeRun 'summary.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$baseline = Get-Content -LiteralPath $contract -Raw -Encoding UTF8 | ConvertFrom-Json
$declaredTarget = [double]$baseline.nominal.target_drift_period_ratio
[pscustomobject]@{
  status = 'success'
  qualification = [string]$stripeSummary.qualification
  contract = $contract
  target_drift_period_ratio = $declaredTarget
  achieved_drift_period_ratio = [double]$exactSummary.selected_operating_point.calculated_td_over_t0
  target_half_oscillation_count = [int][math]::Round(2.0 * $declaredTarget)
  exact_k_run_manifest = $exactManifest
  stripe_run_manifest = $stripeManifest
  mirror_energy_per_charge_v = [double]$exactSummary.selected_operating_point.energy_per_charge_v
  mirror_voltages_v = @($exactSummary.selected_operating_point.mirror_voltages_v)
  stripe_biases_v = @($stripeSummary.selected_seed.stripe_biases_v)
  next_gate = [string]$stripeSummary.next_gate
} | ConvertTo-Json -Depth 6
