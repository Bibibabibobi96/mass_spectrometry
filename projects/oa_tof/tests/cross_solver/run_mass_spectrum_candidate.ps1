[CmdletBinding()]
param(
  [string]$RunId = ('wide_mz_candidate_' + (Get-Date -Format 'yyyyMMdd_HHmmss')),
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [ValidateRange(0,1000000)]
  [int]$ParticleCountOverride = 0,
  [Alias('Resume')]
  [switch]$ResumeAfterComsol,
  [switch]$ReanalyzeOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\oa_tof'
$runDir = Join-Path $artifactRoot "runs\mass_spectrum\$RunId"
$resultDir = Join-Path $artifactRoot "results\cross_solver\mass_spectrum\$RunId"
$resumeExisting = $ResumeAfterComsol -or $ReanalyzeOnly
if ($ResumeAfterComsol -and $ReanalyzeOnly) {
  throw 'ResumeAfterComsol and ReanalyzeOnly are mutually exclusive.'
}
if ($resumeExisting) {
  if (-not (Test-Path -LiteralPath $runDir -PathType Container) -or
      -not (Test-Path -LiteralPath $resultDir -PathType Container)) {
    throw "Resume requires the existing run and result directories: $RunId"
  }
  $ionDir = Get-Item -LiteralPath (Join-Path $runDir 'ions')
  $comsolDir = Get-Item -LiteralPath (Join-Path $runDir 'comsol')
} else {
  if ((Test-Path -LiteralPath $runDir) -or (Test-Path -LiteralPath $resultDir)) {
    throw "Candidate mass-spectrum run already exists: $RunId"
  }
  New-Item -ItemType Directory -Path $runDir,$resultDir | Out-Null
  $ionDir = New-Item -ItemType Directory -Path (Join-Path $runDir 'ions')
  $comsolDir = New-Item -ItemType Directory -Path (Join-Path $runDir 'comsol')
}

$modePath = Join-Path $projectRoot 'config\modes\mass_spectrum.json'
$mode = Get-Content -LiteralPath $modePath -Raw | ConvertFrom-Json
$effectiveModePath = $modePath
if ($ParticleCountOverride -gt 0) {
  foreach ($species in $mode.species) { $species.particle_count = $ParticleCountOverride }
  $effectiveModePath = Join-Path $runDir 'effective_mode.json'
  $mode | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $effectiveModePath -Encoding UTF8
}
$formalMph = Join-Path $artifactRoot 'models\comsol\formal\MS_oaTOF_TwoStageRingStackReflectron_Final.mph'
$formalSimion = Join-Path $artifactRoot 'models\simion\formal\oatof_524amu'
$formalIob = Join-Path $formalSimion 'oatof_ideal_grounded.iob'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$ionGenerator = Join-Path $projectRoot 'simion\workbench\generate_comsol_consistent_ions.ps1'
$simionAnalyzer = Join-Path $projectRoot 'simion\workbench\analyze_ideal_field_log.ps1'
$requiredPaths = @($modePath,$formalMph,$formalIob,$python,$ionGenerator,$simionAnalyzer)
if (-not $ReanalyzeOnly) { $requiredPaths += $SimionExe }
foreach ($path in $requiredPaths) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required input is absent: $path" }
}

$contract = Get-Content -LiteralPath (Join-Path $projectRoot 'config\resolved_geometry.json') -Raw | ConvertFrom-Json
$source = $contract.particle_source
$individualIonPaths = [Collections.Generic.List[string]]::new()
$totalParticles = 0
foreach ($species in $mode.species) {
  $ionPath = Join-Path $ionDir ("{0}.ion" -f $species.species_id)
  if ($resumeExisting) {
    if (-not (Test-Path -LiteralPath $ionPath -PathType Leaf)) {
      throw "Resume input is absent: $ionPath"
    }
    if (@(Get-Content -LiteralPath $ionPath).Count -ne [int]$species.particle_count) {
      throw "Resume ION row count is incorrect: $ionPath"
    }
  } else {
    & $ionGenerator -N ([int]$species.particle_count) -MassAmu ([double]$species.mass_amu) `
      -Charge ([int]$species.charge_state) `
      -EnergyMeanEv ([double]$mode.particle_source.initial_energy_mean_ev) `
      -EnergyStdEv ([double]$mode.particle_source.initial_energy_sigma_ev) `
      -HalfWidthXmm ([double]$source.size_x_mm/2) `
      -HalfWidthYmm ([double]$source.size_y_mm/2) `
      -HalfWidthZmm ([double]$source.size_z_mm/2) `
      -CenterXmm ([double]$source.center_x_mm) -CenterYmm ([double]$source.center_y_mm) `
      -CenterZmm ([double]$source.center_z_mm) -Seed ([int]$mode.particle_source.shared_seed) `
      -Output $ionPath | Out-Null
  }
  $individualIonPaths.Add($ionPath)
  $totalParticles += [int]$species.particle_count
}
$combinedIon = Join-Path $ionDir 'wide_mz_combined.ion'
$combinedLines = [Collections.Generic.List[string]]::new()
foreach ($path in $individualIonPaths) {
  foreach ($line in Get-Content -LiteralPath $path) { $combinedLines.Add($line) }
}
if (-not $resumeExisting) {
  Set-Content -LiteralPath $combinedIon -Value $combinedLines -Encoding ASCII
} elseif (-not (Test-Path -LiteralPath $combinedIon -PathType Leaf)) {
  throw "Resume combined ION is absent: $combinedIon"
}
if ($combinedLines.Count -ne $totalParticles) { throw 'Combined ION row count is incorrect.' }

$simionLog = Join-Path $runDir 'simion_mixed.log'
$simionStderr = Join-Path $runDir 'simion_mixed.stderr.log'
$simionCsv = Join-Path $runDir 'simion_mixed_particles.csv'
$simionSummary = Join-Path $runDir 'simion_mixed_summary.json'
foreach ($species in $mode.species) {
  $speciesId = [string]$species.species_id
  $ionPath = Join-Path $ionDir "$speciesId.ion"
  $csvPath = Join-Path $comsolDir "$speciesId.csv"
  $reportPath = Join-Path $comsolDir "$speciesId.report.txt"
  $expected = "DETECTED={0}/{0}" -f [int]$species.particle_count
  if ($resumeExisting) {
    $complete = (Test-Path -LiteralPath $csvPath -PathType Leaf) -and
      (Test-Path -LiteralPath $reportPath -PathType Leaf) -and
      (Select-String -LiteralPath $reportPath -Pattern ("^" + [regex]::Escape($expected) + '$') -Quiet)
    if ($complete) { continue }
    if ($ReanalyzeOnly) {
      throw "ReanalyzeOnly requires complete COMSOL evidence for $speciesId."
    }
    if (Test-Path -LiteralPath $reportPath -PathType Leaf) {
      $failedReport = $reportPath + '.failed.' + (Get-Date -Format 'yyyyMMdd_HHmmss')
      Move-Item -LiteralPath $reportPath -Destination $failedReport
    }
  }
  $old = @{}
  $variables = @{
    OATOF_SOURCE_MODEL_PATH=$formalMph
    OATOF_ION_TABLE=$ionPath
    OATOF_COMSOL_OUTPUT_CSV=$csvPath
    OATOF_ACCELERATOR_HMAX_MM='1'
    OATOF_REUSE_EXISTING_FIELD='1'
    OATOF_FINE_TSTEP_NS='0.2'
    OATOF_DRIFT_TSTEP_NS='50'
    OATOF_SEGMENTED_OUTPUT='1'
    OATOF_USE_PARTICLE_STOP_TIME='0'
    OATOF_CLEAR_PARTICLE_SOLUTION_DATA='0'
    OATOF_APPLY_PARTICLE_PROPERTIES='1'
  }
  try {
    foreach ($entry in $variables.GetEnumerator()) {
      $old[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key,'Process')
      [Environment]::SetEnvironmentVariable($entry.Key,$entry.Value,'Process')
    }
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
      -TaskScript (Join-Path $projectRoot 'tests\comsol\test_accelerator_mesh_particle_candidate.m') `
      -ReportPath $reportPath
  } finally {
    foreach ($entry in $variables.GetEnumerator()) {
      [Environment]::SetEnvironmentVariable($entry.Key,$old[$entry.Key],'Process')
    }
  }
  if (-not (Select-String -LiteralPath $reportPath -Pattern ("^" + [regex]::Escape($expected) + '$') -Quiet)) {
    throw "COMSOL $speciesId did not report $expected."
  }
}

# Run the inexpensive mixed-species SIMION side only after all five COMSOL
# batches succeed, so a COMSOL failure does not create a misleading half-run.
$maximumMassAmu = [double](($mode.species | Measure-Object -Property mass_amu -Maximum).Maximum)
$referenceMassAmu = [double]$contract.validation_target.mass_amu
$simionMaxTofUs = [Math]::Ceiling(90.0 * [Math]::Sqrt($maximumMassAmu / $referenceMassAmu))
if ($ReanalyzeOnly) {
  foreach ($path in @($simionCsv,$simionSummary)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
      throw "ReanalyzeOnly input is absent: $path"
    }
  }
  $summary = Get-Content -LiteralPath $simionSummary -Raw -Encoding UTF8 | ConvertFrom-Json
} else {
  $process = Start-Process -FilePath $SimionExe -WorkingDirectory $formalSimion `
    -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $simionLog `
    -RedirectStandardError $simionStderr -ArgumentList @(
      '--default-num-particles',[string]$totalParticles,'--nogui','fly',
      '--trajectory-quality','8','--retain-trajectories','0','--particles',$combinedIon,
      '--programs','1','--adjustable','trajectory_quality=8','--adjustable',
      'trajectory_log_enable=1','--adjustable',
      ("diagnostic_max_tof_us={0}" -f $simionMaxTofUs),$formalIob)
  if ($process.ExitCode -ne 0) { throw "SIMION mixed-species fly failed: $simionStderr" }
  $summary = & $simionAnalyzer -Log $simionLog -IonFile $combinedIon `
    -Mode 'mass_spectrum_candidate' -Distribution 'five_species_shared_source' `
    -ParticleCsv $simionCsv
  $summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $simionSummary -Encoding UTF8
}
if ([int]$summary.Hit -ne $totalParticles) {
  throw "SIMION detected $($summary.Hit)/$totalParticles mixed-species ions."
}

& $python (Join-Path $projectRoot 'analysis\mass_spectrum.py') `
  --mode-config $effectiveModePath --comsol-dir $comsolDir --simion-csv $simionCsv --output $resultDir
if ($LASTEXITCODE -ne 0) { throw 'Candidate mass-spectrum analysis failed.' }

$runConfigPath = Join-Path $runDir 'run_config.json'
$runConfig = [ordered]@{
  schema_version = 1
  role = 'oa_tof_mass_spectrum_run_config'
  run_id = $RunId
  project = 'oa_tof'
  project_root = $projectRoot
  mode = 'mass_spectrum_candidate'
  formal_gate_passed = $false
  inputs = [ordered]@{
    base_mode_config = $modePath
    effective_mode_config = $effectiveModePath
    resolved_geometry = (Join-Path $projectRoot 'config\resolved_geometry.json')
    formal_comsol_mph = $formalMph
    formal_simion_iob = $formalIob
  }
  species = $mode.species
  execution = [ordered]@{
    simion = 'one mixed-species fly'
    comsol = 'one particle-tracing solve per species; formal electrostatic solution reused'
    resumed_after_comsol = [bool]$ResumeAfterComsol
    reanalyze_only = [bool]$ReanalyzeOnly
    particle_count_override = $ParticleCountOverride
    simion_max_tof_us = $simionMaxTofUs
  }
}
$runConfig | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8
$manifestPath = Join-Path $runDir 'run_manifest.json'
$outputs = @($combinedIon,$simionCsv,$simionSummary)
$outputs += @($individualIonPaths)
if ($effectiveModePath -ne $modePath) { $outputs += $effectiveModePath }
$outputs += @($mode.species | ForEach-Object {
  Join-Path $comsolDir ("{0}.csv" -f $_.species_id)
})
$optionalEvidence = @($simionLog,$simionStderr)
$optionalEvidence += @($mode.species | ForEach-Object {
  Join-Path $comsolDir ("{0}.report.txt" -f $_.species_id)
})
$optionalEvidence += @(Get-ChildItem -LiteralPath $comsolDir -File -Filter '*_selected_release_from_data_file.txt' |
  ForEach-Object { $_.FullName })
$outputs += @($optionalEvidence | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
$outputs += @(
  (Join-Path $resultDir 'mass_spectrum_particles.csv'),
  (Join-Path $resultDir 'mass_spectrum_summary.csv'),
  (Join-Path $resultDir 'mass_peak_shape_comparison.csv'),
  (Join-Path $resultDir 'mass_spectrum_metrics.json'),
  (Join-Path $resultDir 'mass_spectrum_comparison.png')
)
$manifestArgs = @(
  (Join-Path $repoRoot 'common\contracts\write_run_manifest.py'),
  '--run-config',$runConfigPath,'--manifest',$manifestPath,'--status','success',
  '--software','SIMION 2020','--software','COMSOL 6.4 via MATLAB R2025b'
)
foreach ($output in $outputs) { $manifestArgs += @('--output',$output) }
& $python @manifestArgs
if ($LASTEXITCODE -ne 0) { throw 'Run manifest creation failed.' }
& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $manifestPath
if ($LASTEXITCODE -ne 0) { throw 'Run manifest verification failed.' }
Write-Output "MASS_SPECTRUM_CANDIDATE=PASS RUN_ID=$RunId PARTICLES=$totalParticles"
