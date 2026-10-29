param(
  [Parameter(Mandatory = $true)][string]$SimionExe,
  [Parameter(Mandatory = $true)][string]$IobPath,
  [Parameter(Mandatory = $true)][string]$IonPath,
  [Parameter(Mandatory = $true)][string]$LogPath,
  [Parameter(Mandatory = $true)][string]$ErrorPath,
  [Parameter(Mandatory = $true)][string]$DiagnosticsPath,
  [Parameter(Mandatory = $true)][string]$ParticleCsv,
  [Parameter(Mandatory = $true)][string]$SummaryPath,
  [Parameter(Mandatory = $true)][string]$AnalyzerScript,
  [Parameter(Mandatory = $true)][string]$ResolvedContractPath,
  [Parameter(Mandatory)][string]$RuntimeReceiptPath,
  [Parameter(Mandatory)][string]$CapacitySessionPath,
  [Parameter(Mandatory)][string]$CompletionPath,
  [Parameter(Mandatory)][string]$ContextSha256,
  [Parameter(Mandatory)][string]$RunId,
  [Parameter(Mandatory)][string]$PythonExe,
  [int]$ExpectedParticleCount = 100,
  [int]$ExpectedTrajectoryQuality = 8,
  [double]$DetectorRadiusMm = 40
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')

if ($ExpectedParticleCount -ne 100) {
  throw 'This shared OA-TOF transport helper is the fixed N=100 functional tier.'
}
if ($ExpectedTrajectoryQuality -ne 8) {
  throw 'This shared OA-TOF transport helper requires trajectory quality 8.'
}
foreach ($path in @($SimionExe, $IobPath, $IonPath, $AnalyzerScript, $ResolvedContractPath)) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
    throw "Required SIMION transport input is missing: $path"
  }
}
foreach ($path in @($LogPath, $ErrorPath, $DiagnosticsPath, $ParticleCsv, $SummaryPath)) {
  $parent = Split-Path -Parent $path
  if ([string]::IsNullOrWhiteSpace($parent)) { throw "Output path has no parent directory: $path" }
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
  if (Test-Path -LiteralPath $path) { throw "Refusing to overwrite SIMION transport output: $path" }
}

$iob = (Resolve-Path -LiteralPath $IobPath).Path
$ion = (Resolve-Path -LiteralPath $IonPath).Path
$analyzer = (Resolve-Path -LiteralPath $AnalyzerScript).Path
$resolvedContract = (Resolve-Path -LiteralPath $ResolvedContractPath).Path

$nativeArguments = @(
  '--default-num-particles', [string]$ExpectedParticleCount, '--nogui', 'fly',
  '--trajectory-quality', [string]$ExpectedTrajectoryQuality, '--retain-trajectories', '0',
  '--particles', $ion,
  '--adjustable', "trajectory_quality=$ExpectedTrajectoryQuality",
  '--adjustable', 'trajectory_log_enable=1',
  $iob
)
$flightRequestPath=Join-Path (Split-Path -Parent $CompletionPath) 'candidate_n100_flight_request.json'
if(Test-Path -LiteralPath $flightRequestPath){throw 'Candidate N100 flight request already exists.'}
Write-RunJson -Path $flightRequestPath -Value @{
  schema_version=1;role='oatof_candidate_flight_request';executable=[IO.Path]::GetFullPath($SimionExe);
  argv=$nativeArguments;cwd=(Split-Path -Parent $iob);stdout=[IO.Path]::GetFullPath($LogPath);
  stderr=[IO.Path]::GetFullPath($ErrorPath);result_receipt=[IO.Path]::GetFullPath($CompletionPath);
  warning_seconds=1800;context_sha256=$ContextSha256;run_id=$RunId;case_id='design_candidate';mode='native'
}
& (Join-Path $PSScriptRoot 'run_candidate_flight.ps1') -ExecutionRequestPath $flightRequestPath `
  -RuntimeReceiptPath $RuntimeReceiptPath -CapacitySessionPath $CapacitySessionPath -PythonExe $PythonExe -RepositoryRoot $repoRoot

$diagnostics = & $analyzer -Log $LogPath -IonFile $ion -Mode 'candidate_n100_transport' `
  -Distribution 'fixedN100' -DetectorRadiusMm $DetectorRadiusMm -ParticleCsv $ParticleCsv
if ($LASTEXITCODE -ne 0) { throw 'SIMION N=100 transport diagnostics failed.' }
if ([int]$diagnostics.Emitted -ne $ExpectedParticleCount -or
    [int]$diagnostics.Crossed -ne $ExpectedParticleCount -or
    [int]$diagnostics.Hit -ne $ExpectedParticleCount) {
  throw "SIMION N=100 transport census failed: $($diagnostics | ConvertTo-Json -Compress)"
}
if (-not (Test-Path -LiteralPath $ParticleCsv -PathType Leaf)) {
  throw "SIMION N=100 particle state CSV is missing: $ParticleCsv"
}
$csvRows = @(Import-Csv -LiteralPath $ParticleCsv)
if ($csvRows.Count -ne $ExpectedParticleCount -or
    @($csvRows | Select-Object -ExpandProperty Ion -Unique).Count -ne $ExpectedParticleCount) {
  throw 'SIMION N=100 particle state CSV does not contain exactly one row per ion.'
}

$diagnostics | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $DiagnosticsPath -Encoding UTF8
$summary = [ordered]@{
  schema_version = 1
  role = 'oa_tof_simion_n100_transport_summary'
  status = 'success'
  expected_particle_count = $ExpectedParticleCount
  trajectory_quality = $ExpectedTrajectoryQuality
  detector_radius_mm = $DetectorRadiusMm
  emitted = [int]$diagnostics.Emitted
  crossed = [int]$diagnostics.Crossed
  hit = [int]$diagnostics.Hit
  iob = [ordered]@{ path = $iob; sha256 = (Get-FileHash -LiteralPath $iob -Algorithm SHA256).Hash }
  ion = [ordered]@{ path = $ion; sha256 = (Get-FileHash -LiteralPath $ion -Algorithm SHA256).Hash }
  resolved_contract = [ordered]@{ path = $resolvedContract; sha256 = (Get-FileHash -LiteralPath $resolvedContract -Algorithm SHA256).Hash }
  particle_csv = [ordered]@{ path = [IO.Path]::GetFullPath($ParticleCsv); sha256 = (Get-FileHash -LiteralPath $ParticleCsv -Algorithm SHA256).Hash }
  diagnostics = [ordered]@{ path = [IO.Path]::GetFullPath($DiagnosticsPath); sha256 = (Get-FileHash -LiteralPath $DiagnosticsPath -Algorithm SHA256).Hash }
}
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $SummaryPath -Encoding UTF8
"OATOF_SIMION_N100_TRANSPORT=PASS IONS=$ExpectedParticleCount SUMMARY=$SummaryPath"
