[CmdletBinding()]
param(
  [double]$MassAmu = 500.0,
  [int]$ChargeState = 1,
  [string]$ParticleCounts = '100,1000,5000',
  [ValidateRange(1,20)]
  [int]$SimionRepeats = 3,
  [int]$Seed = 20260713,
  [string]$RunId = ((Get-Date -Format 'yyyyMMdd_HHmmss') + '__benchmark__cross__particle-scaling__mz500'),
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [switch]$Resume
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Read-KeyValueReport([string]$Path) {
  $values = @{}
  foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
    if ($line -match '^([^=]+)=(.*)$') { $values[$matches[1]] = $matches[2] }
  }
  return $values
}

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\oa_tof'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
$runDir = Join-Path $artifactRoot "runs\$RunId"
$resultDir = Join-Path $runDir 'results'
if ($Resume) {
  foreach ($directory in @($runDir,$resultDir)) {
    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
      throw "Resume directory is absent: $directory"
    }
  }
} else {
  if ((Test-Path -LiteralPath $runDir) -or (Test-Path -LiteralPath $resultDir)) {
    throw "Benchmark run already exists: $RunId"
  }
  New-Item -ItemType Directory -Path $runDir,$resultDir | Out-Null
}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
if (-not $Resume) {
  Initialize-RunRecord -RunDir $runDir -RunId $RunId -Project 'oa_tof' `
    -Mode 'single_mass_scaling_benchmark' -ProjectRoot $projectRoot `
    -RepoRoot $repoRoot -Python $python -ProvisionalSummaryRole 'oa_tof_provisional_run_summary' `
    -TerminalSummaryRole 'oa_tof_terminal_run_summary'
}
$runRecordComplete = $false
trap {
  if (-not $runRecordComplete) {
    Write-TerminalRunRecord -RunDir $runDir -Status failed `
      -Reason $_.Exception.Message -RepoRoot $repoRoot -Python $python `
      -SummaryRole 'oa_tof_terminal_run_summary'
  }
  exit 1
}

$formalMph = Join-Path $artifactRoot 'formal\comsol\oa_tof__model.mph'
$formalSimion = Join-Path $artifactRoot 'formal\simion'
$formalIob = Join-Path $formalSimion 'oatof_ideal_grounded.iob'
$ionGenerator = Join-Path $projectRoot 'simion\workbench\generate_comsol_consistent_ions.ps1'
$simionAnalyzer = Join-Path $projectRoot 'simion\workbench\analyze_ideal_field_log.ps1'
$comsolLauncher = Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1'
$comsolTask = Join-Path $projectRoot 'tests\comsol\test_accelerator_mesh_particle_candidate.m'
foreach ($path in @($formalMph,$formalIob,$ionGenerator,$simionAnalyzer,$comsolLauncher,$comsolTask,$python,$SimionExe)) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required input is absent: $path" }
}
$parsedCounts = [Collections.Generic.List[int]]::new()
foreach ($token in @($ParticleCounts -split ',')) {
  $value = 0
  if (-not [int]::TryParse($token.Trim(),[ref]$value)) {
    throw "ParticleCounts contains a non-integer value: $token"
  }
  $parsedCounts.Add($value)
}
$countValues = @($parsedCounts)
if ($countValues.Count -lt 3 -or @($countValues | Where-Object { $_ -le 0 }).Count -gt 0 -or
    (@($countValues | Sort-Object -Unique).Count -ne $countValues.Count)) {
  throw 'ParticleCounts must contain at least three unique positive integers.'
}

$contract = Get-Content -LiteralPath (Join-Path $projectRoot 'config\resolved_geometry.json') -Raw | ConvertFrom-Json
$source = $contract.particle_source
$samples = [Collections.Generic.List[object]]::new()
$manifestOutputs = [Collections.Generic.List[string]]::new()

foreach ($particleCount in $countValues) {
  $caseDir = Join-Path $runDir ("N{0}" -f $particleCount)
  if (-not (Test-Path -LiteralPath $caseDir)) { New-Item -ItemType Directory -Path $caseDir | Out-Null }
  $ionPath = Join-Path $caseDir ("mz{0:g}_N{1}.ion" -f $MassAmu,$particleCount)
  if (-not (Test-Path -LiteralPath $ionPath -PathType Leaf)) {
    & $ionGenerator -N $particleCount -MassAmu $MassAmu -Charge $ChargeState `
      -EnergyMeanEv 5 -EnergyStdEv 0.4 `
      -HalfWidthXmm ([double]$source.size_x_mm/2) `
      -HalfWidthYmm ([double]$source.size_y_mm/2) `
      -HalfWidthZmm ([double]$source.size_z_mm/2) `
      -CenterXmm ([double]$source.center_x_mm) -CenterYmm ([double]$source.center_y_mm) `
      -CenterZmm ([double]$source.center_z_mm) -Seed $Seed -Output $ionPath `
      -AllowNonstandardDiagnosticCount | Out-Null
  }
  if (@(Get-Content -LiteralPath $ionPath).Count -ne $particleCount) {
    throw "ION row count is incorrect: $ionPath"
  }
  $manifestOutputs.Add($ionPath)

  $comsolCsv = Join-Path $caseDir 'comsol_particles.csv'
  $comsolReport = Join-Path $caseDir 'comsol_report.txt'
  $comsolTiming = Join-Path $caseDir 'comsol_timing.json'
  $comsolComplete = (Test-Path -LiteralPath $comsolTiming -PathType Leaf) -and
    (Test-Path -LiteralPath $comsolReport -PathType Leaf) -and
    (Select-String -LiteralPath $comsolReport -Pattern ("^DETECTED={0}/{0}$" -f $particleCount) -Quiet)
  if (-not ($Resume -and $comsolComplete)) {
    if ($Resume -and (Test-Path -LiteralPath $comsolReport -PathType Leaf)) {
      Move-Item -LiteralPath $comsolReport -Destination ($comsolReport + '.failed.' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
    }
    $old = @{}
    $variables = @{
      OATOF_SOURCE_MODEL_PATH=$formalMph
      OATOF_ION_TABLE=$ionPath
      OATOF_COMSOL_OUTPUT_CSV=$comsolCsv
      OATOF_RUNTIME_DIR=$caseDir
      OATOF_RESULTS_DIR=$resultDir
      OATOF_ACCELERATOR_HMAX_MM='1'
      OATOF_REUSE_EXISTING_FIELD='1'
      OATOF_FINE_TSTEP_NS='0.2'
      OATOF_DRIFT_TSTEP_NS='50'
      OATOF_SEGMENTED_OUTPUT='1'
      OATOF_USE_PARTICLE_STOP_TIME='0'
      OATOF_CLEAR_PARTICLE_SOLUTION_DATA='0'
      OATOF_APPLY_PARTICLE_PROPERTIES='1'
    }
    $watch = [Diagnostics.Stopwatch]::StartNew()
    try {
      foreach ($entry in $variables.GetEnumerator()) {
        $old[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key,'Process')
        [Environment]::SetEnvironmentVariable($entry.Key,$entry.Value,'Process')
      }
      & $comsolLauncher -TaskScript $comsolTask -ReportPath $comsolReport
    } finally {
      $watch.Stop()
      foreach ($entry in $variables.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($entry.Key,$old[$entry.Key],'Process')
      }
    }
    $report = Read-KeyValueReport $comsolReport
    if ($report.STATUS -ne 'PASS' -or $report.DETECTED -ne ("{0}/{0}" -f $particleCount)) {
      throw "COMSOL benchmark failed for N=$particleCount."
    }
    [ordered]@{
      solver = 'COMSOL'
      particle_count = $particleCount
      repeat = 1
      wall_seconds = $watch.Elapsed.TotalSeconds
      particle_seconds = [double]$report.PARTICLE_SECONDS
      mesh_seconds = [double]$report.MESH_SECONDS
      electrostatics_seconds = [double]$report.ELECTROSTATICS_SECONDS
      detected = $particleCount
    } | ConvertTo-Json | Set-Content -LiteralPath $comsolTiming -Encoding UTF8
  }
  $comsolRow = Get-Content -LiteralPath $comsolTiming -Raw | ConvertFrom-Json
  $samples.Add($comsolRow)
  foreach ($path in @($comsolCsv,$comsolReport,$comsolTiming)) { $manifestOutputs.Add($path) }

  for ($repeat = 1; $repeat -le $SimionRepeats; $repeat++) {
    $simionLog = Join-Path $caseDir ("simion_repeat{0}.log" -f $repeat)
    $simionStderr = Join-Path $caseDir ("simion_repeat{0}.stderr.log" -f $repeat)
    $simionCsv = Join-Path $caseDir ("simion_repeat{0}_particles.csv" -f $repeat)
    $simionTiming = Join-Path $caseDir ("simion_repeat{0}_timing.json" -f $repeat)
    if (-not ($Resume -and (Test-Path -LiteralPath $simionTiming -PathType Leaf))) {
      $watch = [Diagnostics.Stopwatch]::StartNew()
      $process = Start-Process -FilePath $SimionExe -WorkingDirectory $formalSimion `
        -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $simionLog `
        -RedirectStandardError $simionStderr -ArgumentList @(
          '--default-num-particles',[string]$particleCount,'--nogui','fly',
          '--trajectory-quality','8','--retain-trajectories','0','--particles',$ionPath,
          '--programs','1','--adjustable','trajectory_quality=8','--adjustable',
          'trajectory_log_enable=1','--adjustable','diagnostic_max_tof_us=90',$formalIob)
      $watch.Stop()
      if ($process.ExitCode -ne 0) { throw "SIMION benchmark failed for N=$particleCount repeat=$repeat."
      }
      $summary = & $simionAnalyzer -Log $simionLog -IonFile $ionPath `
        -Mode 'single_mass_scaling' -Distribution ("fixedN{0}" -f $particleCount) `
        -ParticleCsv $simionCsv
      if ([int]$summary.Hit -ne $particleCount) {
        throw "SIMION detected $($summary.Hit)/$particleCount for repeat $repeat."
      }
      [ordered]@{
        solver = 'SIMION'
        particle_count = $particleCount
        repeat = $repeat
        wall_seconds = $watch.Elapsed.TotalSeconds
        particle_seconds = $null
        mesh_seconds = $null
        electrostatics_seconds = $null
        detected = [int]$summary.Hit
      } | ConvertTo-Json | Set-Content -LiteralPath $simionTiming -Encoding UTF8
    }
    $samples.Add((Get-Content -LiteralPath $simionTiming -Raw | ConvertFrom-Json))
    foreach ($path in @($simionLog,$simionStderr,$simionCsv,$simionTiming)) { $manifestOutputs.Add($path) }
  }
}

$sampleCsv = Join-Path $resultDir 'timing_samples.csv'
$samples | Export-Csv -LiteralPath $sampleCsv -NoTypeInformation -Encoding UTF8
$metricsPath = Join-Path $resultDir 'timing_metrics.json'
& $python (Join-Path $projectRoot 'analysis\solver_diagnostics.py') benchmark-metrics `
  --samples $sampleCsv --output $metricsPath --run-id $RunId --mass-amu $MassAmu `
  --charge-state $ChargeState --simion-repeats $SimionRepeats | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Python timing regression failed.' }
$summaryPath = Join-Path $runDir 'summary.json'
$summary = [ordered]@{ schema_version=1; role='oa_tof_single_mass_scaling_summary'; status='success'; metrics='results/timing_metrics.json'; particle_counts=@($countValues) }
$summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
$runConfigPath = Join-Path $runDir 'run_config.json'
[ordered]@{
  schema_version = 1
  role = 'oa_tof_single_mass_scaling_run_config'
  run_id = $RunId
  project = 'oa_tof'
  formal_eligible = $false
  mass_amu = $MassAmu
  charge_state = $ChargeState
  particle_counts = @($countValues)
  simion_repeats = $SimionRepeats
  seed = $Seed
  formal_comsol_mph = $formalMph
  formal_simion_iob = $formalIob
  timing_scope = [ordered]@{
    comsol_wall = 'MATLAB/LiveLink process launch through task completion'
    comsol_particle = 'std2 particle solve reported by MATLAB tic/toc'
    simion_wall = 'SIMION process launch through Fly completion; log analysis excluded'
  }
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8

$manifestPath = Join-Path $runDir 'run_manifest.json'
$manifestArgs = @(
  (Join-Path $repoRoot 'common\contracts\write_run_manifest.py'),
  '--run-config',$runConfigPath,'--manifest',$manifestPath,'--status','success',
  '--software','SIMION 2020','--software','COMSOL 6.4 via MATLAB R2025b',
  '--output',$sampleCsv,'--output',$metricsPath,'--output',$summaryPath
)
foreach ($output in $manifestOutputs) { $manifestArgs += @('--output',$output) }
& $python @manifestArgs
if ($LASTEXITCODE -ne 0) { throw 'Benchmark manifest creation failed.' }
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $manifestPath --require-status success
if ($LASTEXITCODE -ne 0) { throw 'Benchmark manifest verification failed.' }
$runRecordComplete = $true
Write-Output "SINGLE_MASS_SCALING=PASS RUN_ID=$RunId MASS_AMU=$MassAmu COUNTS=$($countValues -join ',')"
