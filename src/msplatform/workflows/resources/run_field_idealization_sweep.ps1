param(
  [Parameter(Mandatory = $true)][string]$WorkspaceRoot,
  [Parameter(Mandatory = $true)][string]$ArtifactRootPath,
  [Parameter(Mandatory = $true)][string]$ScienceRoot,
  [int]$N = 100,
  [int]$Seed = 20260713,
  [string]$CaseConfig = '',
  [string]$OutputDir = '',
  [string]$RuntimePackage = '',
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [switch]$ValidateConfigOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path -LiteralPath $WorkspaceRoot).Path
$projectRoot = (Resolve-Path -LiteralPath $ScienceRoot).Path
$artifactRootPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ArtifactRootPath)
$packageRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = if ($env:SIMULATION_PYTHON_EXE) { (Resolve-Path -LiteralPath $env:SIMULATION_PYTHON_EXE).Path } else { throw 'Explicit SIMULATION_PYTHON_EXE is required' }
$executionResources = Join-Path $packageRoot 'execution/resources'
. (Join-Path $executionResources 'workspace_paths.ps1')
$pathContext = Resolve-WorkspacePaths -SourceRoot $repoRoot -ArtifactRoot $artifactRootPath -Python $python
$hostContext = @{workspace=$repoRoot; python_executable=$python; host_state_path=[string]$pathContext.host_resource_state_path; policy_path=(Join-Path $executionResources 'host_resource_policy.json')}
$previousHostContext = [Environment]::GetEnvironmentVariable('MASS_SPECTROMETRY_HOST_CONTEXT_JSON')
$hostExecutionLease = $null
$runRecordComplete = $true
try {
. (Join-Path $executionResources 'host_execution_lease.ps1') -HostContext $hostContext
. (Join-Path $executionResources 'run_artifact_support.ps1')
$artifactRoot = Resolve-RunArtifactRoot -ArtifactRoot $pathContext.artifact_root -OwnerKind component -OwnerId single_reflection_oa_tof_mass_analyzer -Python $python
$hostRole = if ($ValidateConfigOnly) { 'GATE' } else { 'SIMION' }
$hostExecutionLease = Enter-HostExecutionLease -Role $hostRole -Stage prepare -StatePath $pathContext.host_resource_state_path
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

$caseBytes = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $CaseConfig).Path)
$caseText = [Text.Encoding]::UTF8.GetString($caseBytes).TrimStart([char]0xFEFF)
$configuration = $caseText | ConvertFrom-Json
$seenCases = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
if (@($configuration.cases).Count -eq 0) { throw 'At least one diagnostic case is required.' }
foreach ($case in $configuration.cases) {
  if ([string]$case.id -cnotmatch '^[A-Za-z0-9_]+$' -or -not $seenCases.Add([string]$case.id)) {
    throw 'Diagnostic case IDs must be unique ASCII identifiers.'
  }
  $null = Convert-Selector ([string]$case.selector)
}
if ($ValidateConfigOnly) {
  Write-Host "SIMION_FIELD_SELECTOR_CONFIG=PASS cases=$(@($configuration.cases).Count)"
  return
}
if (-not $OutputDir) {
  $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
  $runId = "${stamp}__test__simion__field-idealization__n${N}"
} else {
  $runId = Split-Path -Leaf ([IO.Path]::GetFullPath($OutputDir))
}
& $python -m msplatform.execution.artifact_naming run $runId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $runId" }
$expectedOutputDir = [IO.Path]::GetFullPath((Join-Path $artifactRoot "runs\$runId"))
if ($OutputDir -and [IO.Path]::GetFullPath($OutputDir) -cne $expectedOutputDir) {
  throw 'OutputDir must be the canonical artifacts/runs/run_id directory.'
}
$package = New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $runId -Project 'single_reflection_oa_tof_mass_analyzer' -Mode 'simion_field_idealization_sweep' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled -AdditionalDirectories @('simion') -PathContext $pathContext
$OutputDir = $package.artifact_run_dir
$runRecordComplete = $false
$lifecycleConfig = Get-Content -LiteralPath $package.run_config -Raw -Encoding UTF8 | ConvertFrom-Json
$sourceLua = Join-Path $packageRoot 'backends/simion/resources/oatof_ideal_grounded.lua'
$generator = Join-Path $packageRoot 'backends/simion/resources/generate_comsol_consistent_particles.ps1'
$analyzer = Join-Path $packageRoot 'backends/simion/resources/analyze_ideal_field_log.ps1'
$ionFile = Join-Path $package.artifact_run_dir ("simion/oatof_N${N}.ion")
$frozenCasePath = Join-Path $package.input_dir 'case_config.json'
$runtimeDir = if ($RuntimePackage) { (Resolve-Path -LiteralPath $RuntimePackage).Path } else { Join-Path $OutputDir 'runtime_package' }
[IO.File]::WriteAllBytes($frozenCasePath, $caseBytes)
if ($N -ne [int]$configuration.particle_count) {
  Write-Warning "N=$N overrides the feasibility-plan particle_count=$($configuration.particle_count)."
}
$stableManifestPath = Join-Path $projectRoot 'config\simion_stable_entry.json'
$stableManifest = Get-Content -LiteralPath $stableManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$formalEntry = @($stableManifest.entries)
if ($formalEntry.Count -ne 1) { throw 'Stable-entry contract must identify exactly one Formal SIMION delivery.' }
$stableGate = Join-Path $packageRoot 'workflows/resources/verify_stable_entry.ps1'
& $stableGate -WorkspaceRoot $repoRoot -ArtifactRootPath $artifactRootPath -ScienceRoot $projectRoot -ManifestPath $stableManifestPath -EntryId $formalEntry[0].id -SimionExe $SimionExe -PythonExe $python

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

if (-not $RuntimePackage) {
  if (Test-Path -LiteralPath $runtimeDir) { throw "Runtime package already exists: $runtimeDir" }
  Copy-Item -LiteralPath $formalDir -Destination $runtimeDir -Recurse
  Move-Item -LiteralPath (Join-Path $runtimeDir 'run_manifest.json') -Destination (Join-Path $runtimeDir 'source_formal_run_manifest.json')
  Move-Item -LiteralPath (Join-Path $runtimeDir 'SHA256SUMS.csv') -Destination (Join-Path $runtimeDir 'source_formal_SHA256SUMS.csv')
  Copy-Item -LiteralPath $sourceLua -Destination (Join-Path $runtimeDir 'oatof_ideal_grounded.lua') -Force
  }
  Assert-DiagnosticPackage $runtimeDir
  $generatorArgs = @{}
  if ($N -notin @(100,1000)) { $generatorArgs.AllowNonstandardDiagnosticCount = $true }
  & $generator -N $N -Seed $Seed -Output $ionFile @generatorArgs | Out-Null
$iob = Join-Path $runtimeDir 'oatof_ideal_grounded.iob'
if (-not (Test-Path -LiteralPath $iob)) { throw "Runtime IOB is missing: $iob" }
if (-not (Test-Path -LiteralPath $ionFile)) { throw "ION file is missing: $ionFile" }
Assert-DiagnosticPackage $runtimeDir

$runConfig = Get-Content -LiteralPath $package.run_config -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable -Depth 100
$runConfig['purpose'] = 'simion_field_idealization_feasibility'
$runConfig['particle_count'] = $N
$runConfig['seed'] = $Seed
$runConfig['analysis_only'] = $false
$runConfig['source_run_id'] = $null
$runConfig['inputs'] = [ordered]@{
  case_config = (Resolve-Path -LiteralPath $frozenCasePath).Path
}
$runConfig['runtime_package'] = $runtimeDir
$runConfig['runtime_package_reused'] = [bool]$RuntimePackage
$runConfig['capability_scope'] = 'composable Ez by region; Ex/Ey unsupported in current SIMION PA representation'
$runConfigPath = Join-Path $OutputDir 'run_config.json'
$runConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8

$rows = [Collections.Generic.List[object]]::new()
foreach ($case in $configuration.cases) {
  $flags = Convert-Selector $case.selector
  $stem = [string]$case.id
  $stdout = Join-Path $package.log_dir ($stem + '.log')
  $stderr = Join-Path $package.log_dir ($stem + '.stderr.log')
  $particleCsv = Join-Path $package.result_dir ($stem + '_particles.csv')
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
  $hostExecutionLease = Update-HostResourceStage -Lease $hostExecutionLease -Stage flight `
    -Budget (Get-HostResourceBudget -Role $hostRole -Stage flight) -RetainedMemoryBytes 0
  $process = Start-Process -FilePath $SimionExe -ArgumentList $arguments -WorkingDirectory $runtimeDir -NoNewWindow -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
  $timer.Stop()
  if ($process.ExitCode -ne 0) { throw "SIMION failed for $stem with exit code $($process.ExitCode)." }
  $solveSeconds = $timer.Elapsed.TotalSeconds
  $hostExecutionLease = Update-HostResourceStage -Lease $hostExecutionLease -Stage postprocess `
    -Budget (Get-HostResourceBudget -Role $hostRole -Stage postprocess) -RetainedMemoryBytes 0
  $metrics = & $analyzer -Log $stdout -IonFile $ionFile -Mode $stem -Distribution 'shared' -ParticleCsv $particleCsv
  if ([int]$metrics.Emitted -ne $N) { throw 'Diagnostic source particle count differs from its frozen run control.' }
  $rows.Add([pscustomobject]@{
    case_id=$stem; selector=[string]$case.selector; detected=[int]$metrics.Hit
    mean_tof_us=$metrics.MeanTofUs; tof_std_ns=$metrics.StdTofNs
    landing_max_mm=$metrics.MaxHitRadiusMm; solve_seconds=$solveSeconds
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

$manifestWriter = 'from msplatform.execution.manifest_publication import main; from msplatform.backends.simion.native_completion import retention_api; main(retention_api=retention_api)'
$manifestVerifier = 'from msplatform.execution.manifest_verification import main; from msplatform.backends.simion.native_completion import retention_api; main(retention_api=retention_api)'
$manifestArguments = @($manifestWriter,'--run-config',$runConfigPath,'--manifest',(Join-Path $OutputDir 'run_manifest.json'),'--status','success','--software','SIMION 2020','--output',$summaryPath,'--output',$summaryCsv)
$manifestArguments += @('--output',$ionFile)
foreach ($row in $rows) {
  $manifestArguments += @('--output',$row.particle_csv)
  $manifestArguments += @('--output',(Join-Path $package.log_dir ($row.case_id + '.log')),'--output',(Join-Path $package.log_dir ($row.case_id + '.stderr.log')))
}
& $python -c @manifestArguments
if ($LASTEXITCODE -ne 0) { throw 'Manifest creation failed.' }
& $python -c $manifestVerifier (Join-Path $OutputDir 'run_manifest.json')
if ($LASTEXITCODE -ne 0) { throw 'Manifest verification failed.' }
$runRecordComplete = $true
Write-Host "SIMION_FIELD_IDEALIZATION=PASS output=$OutputDir"

} catch {
  if (-not $runRecordComplete) {
    Write-TerminalRunRecord -RunDir $OutputDir -Status failed `
      -Reason $_.Exception.Message -RepoRoot $repoRoot -Python $python `
      -SummaryRole 'oa_tof_terminal_run_summary'
  }
  throw
} finally {
  if ($null -ne $hostExecutionLease) { Exit-HostExecutionLease -Lease $hostExecutionLease }
  [Environment]::SetEnvironmentVariable('MASS_SPECTROMETRY_HOST_CONTEXT_JSON', $previousHostContext)
}
