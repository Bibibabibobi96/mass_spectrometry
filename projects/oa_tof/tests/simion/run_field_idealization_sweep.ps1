param(
  [int]$N = 100,
  [int]$Seed = 20260713,
  [string]$CaseConfig = '',
  [string]$OutputDir = '',
  [string]$RuntimePackage = '',
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [switch]$AnalyzeOnly,
  [switch]$ValidateConfigOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$projectRoot = Join-Path $repoRoot 'projects\oa_tof'
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\oa_tof'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$formalDir = Join-Path $artifactRoot 'formal\simion'
if (-not $CaseConfig) { $CaseConfig = Join-Path $projectRoot 'config\diagnostics\field_idealization_feasibility.json' }

function Convert-Selector([string]$Selector) {
  $flags = [ordered]@{ A=0; D=0; S1=0; S2=0 }
  if ($Selector -eq 'real') { return [pscustomobject]$flags }
  if (-not $Selector.StartsWith('ideal:')) { throw "Unsupported selector syntax: $Selector" }
  foreach ($term in $Selector.Substring(6).Split('+')) {
    $parts = $term.Split('.')
    if ($parts.Count -ne 2) { throw "Malformed selector term: $term" }
    if ($parts[1].ToLowerInvariant() -ne 'ez') {
      throw "SIMION current PA capability supports composable Ez only; unsupported term: $term"
    }
    $regions = switch ($parts[0].ToLowerInvariant()) {
      'accel' { @('A') }
      'drift' { @('D') }
      'stage1' { @('S1') }
      'stage2' { @('S2') }
      'reflectron' { @('S1','S2') }
      'all' { @('A','D','S1','S2') }
      default { throw "Unsupported SIMION field region: $($parts[0])" }
    }
    foreach ($region in $regions) { $flags[$region] = 1 }
  }
  return [pscustomobject]$flags
}

$configuration = Get-Content -LiteralPath $CaseConfig -Raw -Encoding UTF8 | ConvertFrom-Json
if ($ValidateConfigOnly) {
  foreach ($case in $configuration.cases) { $null = Convert-Selector $case.selector }
  Write-Host "SIMION_FIELD_SELECTOR_CONFIG=PASS cases=$(@($configuration.cases).Count)"
  return
}
if (-not $OutputDir) {
  $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
  $OutputDir = Join-Path $artifactRoot "runs\${stamp}__test__simion__field-idealization__n${N}"
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$OutputDir = (Resolve-Path -LiteralPath $OutputDir).Path
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run (Split-Path -Leaf $OutputDir)
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $(Split-Path -Leaf $OutputDir)" }
$runtimeDir = if ($RuntimePackage) { (Resolve-Path -LiteralPath $RuntimePackage).Path } else { Join-Path $OutputDir 'runtime_package' }
if ($N -ne [int]$configuration.particle_count) {
  Write-Warning "N=$N overrides the feasibility-plan particle_count=$($configuration.particle_count)."
}
$sourceLua = Join-Path $projectRoot 'simion\workbench\formal\oatof_ideal_grounded.lua'
$generator = Join-Path $projectRoot 'simion\workbench\generate_comsol_consistent_ions.ps1'
$analyzer = Join-Path $projectRoot 'simion\workbench\analyze_ideal_field_log.ps1'
$ionFile = Join-Path $OutputDir "oatof_N${N}.ion"
$stableManifestPath = Join-Path $projectRoot 'config\simion_stable_entry.json'
$stableManifest = Get-Content -LiteralPath $stableManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$formalEntry = @($stableManifest.entries | Where-Object { @($_.assets.relative_path) -match '^formal/' })
if ($formalEntry.Count -ne 1) { throw 'Could not identify exactly one formal SIMION stable-entry record.' }
$stableGate = Join-Path $projectRoot 'tests\simion\verify_stable_entry.ps1'
& $stableGate -ManifestPath $stableManifestPath -EntryId $formalEntry[0].id -SimionExe $SimionExe

function Assert-DiagnosticPackage([string]$PackagePath) {
  $pairs = @(
    @((Join-Path $PackagePath 'oatof_ideal_grounded.iob'),(Join-Path $formalDir 'oatof_ideal_grounded.iob')),
    @((Join-Path $PackagePath 'source_formal_run_manifest.json'),(Join-Path $formalDir 'run_manifest.json')),
    @((Join-Path $PackagePath 'source_formal_SHA256SUMS.csv'),(Join-Path $formalDir 'SHA256SUMS.csv')),
    @((Join-Path $PackagePath 'oatof_ideal_grounded.lua'),$sourceLua)
  )
  foreach ($pair in $pairs) {
    if (-not (Test-Path -LiteralPath $pair[0] -PathType Leaf)) { throw "Diagnostic package file is missing: $($pair[0])" }
    if ((Get-FileHash -LiteralPath $pair[0] -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $pair[1] -Algorithm SHA256).Hash) {
      throw "Diagnostic package provenance mismatch: $($pair[0])"
    }
  }
}

if (-not $AnalyzeOnly) {
  if (-not $RuntimePackage) {
    if (Test-Path -LiteralPath $runtimeDir) { throw "Runtime package already exists: $runtimeDir" }
    Copy-Item -LiteralPath $formalDir -Destination $runtimeDir -Recurse
    Move-Item -LiteralPath (Join-Path $runtimeDir 'run_manifest.json') -Destination (Join-Path $runtimeDir 'source_formal_run_manifest.json')
    Move-Item -LiteralPath (Join-Path $runtimeDir 'SHA256SUMS.csv') -Destination (Join-Path $runtimeDir 'source_formal_SHA256SUMS.csv')
    Copy-Item -LiteralPath $sourceLua -Destination (Join-Path $runtimeDir 'oatof_ideal_grounded.lua') -Force
  }
  Assert-DiagnosticPackage $runtimeDir
  & $generator -N $N -Seed $Seed -Output $ionFile | Out-Null
}
$iob = Join-Path $runtimeDir 'oatof_ideal_grounded.iob'
if (-not (Test-Path -LiteralPath $iob)) { throw "Runtime IOB is missing: $iob" }
if (-not (Test-Path -LiteralPath $ionFile)) { throw "ION file is missing: $ionFile" }
Assert-DiagnosticPackage $runtimeDir

$runConfig = [ordered]@{
  schema_version=1; run_id=(Split-Path -Leaf $OutputDir); project='oa_tof'
  mode='simion_field_idealization_feasibility'; purpose='simion_field_idealization_feasibility'
  status='configured'; formal_gate_passed=$false; particle_count=$N; seed=$Seed
  inputs=[ordered]@{
    case_config=(Resolve-Path -LiteralPath $CaseConfig).Path
    source_program=(Resolve-Path -LiteralPath $sourceLua).Path
    formal_iob=(Resolve-Path -LiteralPath (Join-Path $formalDir 'oatof_ideal_grounded.iob')).Path
    stable_entry_manifest=(Resolve-Path -LiteralPath $stableManifestPath).Path
  }
  runtime_package=(Resolve-Path -LiteralPath $runtimeDir).Path
  runtime_package_reused=[bool]$RuntimePackage
  capability_scope='composable Ez by region; Ex/Ey unsupported in current SIMION PA representation'
}
$runConfigPath = Join-Path $OutputDir 'run_config.json'
$runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8

$previousSolveSeconds = @{}
$existingSummaryCsv = Join-Path $OutputDir 'sweep_summary.csv'
if ($AnalyzeOnly -and (Test-Path -LiteralPath $existingSummaryCsv)) {
  foreach ($oldRow in Import-Csv -LiteralPath $existingSummaryCsv) {
    $previousSolveSeconds[[string]$oldRow.case_id] = [double]$oldRow.solve_seconds
  }
}
$rows = [Collections.Generic.List[object]]::new()
foreach ($case in $configuration.cases) {
  $flags = Convert-Selector $case.selector
  $stem = [string]$case.id
  $stdout = Join-Path $OutputDir ($stem + '.log')
  $stderr = Join-Path $OutputDir ($stem + '.stderr.log')
  $particleCsv = Join-Path $OutputDir ($stem + '_particles.csv')
  if (-not $AnalyzeOnly) {
    $arguments = @(
      '--default-num-particles',[string]$N,'--nogui','fly','--retain-trajectories','0',
      '--particles',$ionFile,'--adjustable','trajectory_quality=8',
      '--adjustable','ideal_accel_enable=0','--adjustable','ideal_refl_stage1_enable=0',
      '--adjustable','ideal_refl_stage2_enable=0',
      '--adjustable',("ideal_accel_ez_enable={0}" -f $flags.A),
      '--adjustable',("ideal_drift_ez_enable={0}" -f $flags.D),
      '--adjustable',("ideal_refl_stage1_ez_enable={0}" -f $flags.S1),
      '--adjustable',("ideal_refl_stage2_ez_enable={0}" -f $flags.S2),
      '--adjustable','trajectory_log_enable=1',$iob
    )
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $process = Start-Process -FilePath $SimionExe -ArgumentList $arguments -WorkingDirectory $runtimeDir -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $timer.Stop()
    if ($process.ExitCode -ne 0) { throw "SIMION failed for $stem with exit code $($process.ExitCode)." }
    $solveSeconds = $timer.Elapsed.TotalSeconds
  } else {
    $solveSeconds = if ($previousSolveSeconds.ContainsKey($stem)) { $previousSolveSeconds[$stem] } else { 0.0 }
  }
  $metrics = & $analyzer -Log $stdout -IonFile $ionFile -Mode $stem -Distribution 'shared' -ParticleCsv $particleCsv
  $rows.Add([pscustomobject]@{
    case_id=$stem; selector=[string]$case.selector; detected=[int]$metrics.Hit
    mean_tof_us=[double]$metrics.MeanTofUs; tof_std_ns=[double]$metrics.StdTofNs
    landing_max_mm=[double]$metrics.MaxHitRadiusMm; solve_seconds=$solveSeconds
    particle_csv=$particleCsv
  })
}
$summaryCsv = Join-Path $OutputDir 'sweep_summary.csv'
$rows | Export-Csv -LiteralPath $summaryCsv -NoTypeInformation -Encoding UTF8
$summary = [ordered]@{
  schema_version=1; status='success'; formal_eligible=$false; particle_count=$N
  purpose='method feasibility, not precision agreement'; cases=$rows
  capability_boundary='SIMION validates composable regional Ez interventions only; current PA topology does not expose independent global Ex/Ey.'
}
$summaryPath = Join-Path $OutputDir 'summary.json'
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

$manifestWriter = Join-Path $repoRoot 'common\contracts\write_run_manifest.py'
$manifestVerifier = Join-Path $repoRoot 'common\contracts\verify_run_manifest.py'
$manifestArguments = @($manifestWriter,'--run-config',$runConfigPath,'--manifest',(Join-Path $OutputDir 'run_manifest.json'),'--status','success','--software','SIMION 2020','--output',$summaryPath,'--output',$summaryCsv,'--output',$ionFile,'--output',(Join-Path $runtimeDir 'oatof_ideal_grounded.iob'),'--output',(Join-Path $runtimeDir 'oatof_ideal_grounded.lua'),'--output',(Join-Path $runtimeDir 'source_formal_run_manifest.json'),'--output',(Join-Path $runtimeDir 'source_formal_SHA256SUMS.csv'))
foreach ($row in $rows) {
  $manifestArguments += @('--output',(Join-Path $OutputDir ($row.case_id + '.log')),'--output',(Join-Path $OutputDir ($row.case_id + '.stderr.log')),'--output',$row.particle_csv)
}
& $python @manifestArguments
if ($LASTEXITCODE -ne 0) { throw 'Manifest creation failed.' }
& $python $manifestVerifier (Join-Path $OutputDir 'run_manifest.json')
if ($LASTEXITCODE -ne 0) { throw 'Manifest verification failed.' }
Write-Host "SIMION_FIELD_IDEALIZATION=PASS output=$OutputDir"
