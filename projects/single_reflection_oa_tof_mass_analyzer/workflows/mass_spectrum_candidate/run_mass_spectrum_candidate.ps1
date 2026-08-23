[CmdletBinding()]
param(
  [string]$RunId = ((Get-Date -Format 'yyyyMMdd_HHmmss') + '__sim__cross__mass-spectrum__five-mass'),
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [Alias('Resume')]
  [switch]$ResumeAfterComsol,
  [switch]$ReanalyzeOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\single_reflection_oa_tof_mass_analyzer'
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
. (Join-Path $projectRoot 'oatof_lifecycle_preflight.ps1')
Assert-OaTofFormalAssetsReadable -ProjectRoot $projectRoot
& $python (Join-Path $repoRoot 'common\contracts\artifact_naming.py') run $RunId
if ($LASTEXITCODE -ne 0) { throw "Invalid run_id: $RunId" }
$runDir = Join-Path $artifactRoot "runs\$RunId"
$inputDir = Join-Path $runDir 'inputs'
$resultDir = Join-Path $runDir 'results'
$logDir = Join-Path $runDir 'logs'
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
  if (-not (Test-Path -LiteralPath $inputDir -PathType Container)) {
    throw "Resume requires the existing frozen input directory: $inputDir"
  }
} else {
  if ((Test-Path -LiteralPath $runDir) -or (Test-Path -LiteralPath $resultDir)) {
    throw "Candidate mass-spectrum run already exists: $RunId"
  }
  New-Item -ItemType Directory -Path $runDir,$inputDir,$resultDir,$logDir | Out-Null
  $ionDir = New-Item -ItemType Directory -Path (Join-Path $runDir 'ions')
  $comsolDir = New-Item -ItemType Directory -Path (Join-Path $runDir 'comsol')
}
. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$executionAlias = $null
$runtimeAlias = $null
$runtimeRoot = $null
if (-not $resumeExisting) {
  Initialize-RunRecord -RunDir $runDir -RunId $RunId -Project 'single_reflection_oa_tof_mass_analyzer' `
    -Mode 'mass_spectrum_candidate' -ProjectRoot $projectRoot `
    -RepoRoot $repoRoot -Python $python -ProvisionalSummaryRole 'oa_tof_provisional_run_summary' `
    -TerminalSummaryRole 'oa_tof_terminal_run_summary'
}
$runRecordComplete = $false
trap {
  if ($null -ne $runtimeAlias) {
    try { Remove-RunExecutionAlias -ExecutionAlias $runtimeAlias.execution_alias -TargetDirectory $runtimeRoot }
    catch { Write-Warning "Could not remove short formal-runtime alias: $($_.Exception.Message)" }
  }
  if ($null -ne $runtimeRoot) {
    try { Remove-OaTofFormalSimionRuntime -ArtifactRoot $artifactRoot -RuntimeRoot $runtimeRoot }
    catch { Write-Warning "Could not remove formal SIMION runtime: $($_.Exception.Message)" }
  }
  if ($null -ne $executionAlias) {
    try { Remove-RunExecutionAlias -ExecutionAlias $executionAlias.execution_alias -TargetDirectory $runDir }
    catch { Write-Warning "Could not remove short mass-spectrum execution alias: $($_.Exception.Message)" }
  }
  if (-not $runRecordComplete) {
    Write-TerminalRunRecord -RunDir $runDir -Status failed `
      -Reason $_.Exception.Message -RepoRoot $repoRoot -Python $python `
      -SummaryRole 'oa_tof_terminal_run_summary'
  }
  exit 1
}

$liveModePath = Join-Path $projectRoot 'config\modes\mass_spectrum.json'
$liveResolvedPath = Join-Path $projectRoot 'config\resolved_geometry.json'
$liveParticleCountPolicyPath = Join-Path $repoRoot 'common\contracts\particle_count_policy.json'
$modePath = Join-Path $inputDir 'mass_spectrum.json'
$resolvedPath = Join-Path $inputDir 'resolved_geometry.json'
$particleCountPolicyPath = Join-Path $inputDir 'particle_count_policy.json'
if ($resumeExisting) {
  foreach ($frozenInput in @($modePath,$resolvedPath,$particleCountPolicyPath)) {
    if (-not (Test-Path -LiteralPath $frozenInput -PathType Leaf)) {
      throw "Resume frozen input is absent: $frozenInput"
    }
  }
} else {
  Copy-Item -LiteralPath $liveModePath -Destination $modePath
  Copy-Item -LiteralPath $liveResolvedPath -Destination $resolvedPath
  Copy-Item -LiteralPath $liveParticleCountPolicyPath -Destination $particleCountPolicyPath
}
$mode = Get-Content -LiteralPath $modePath -Raw | ConvertFrom-Json
if ([int]$mode.schema_version -ne 1 -or
    [string]$mode.role -cne 'oa_tof_candidate_mass_spectrum_mode' -or
    [string]$mode.mode -cne 'mass_spectrum_candidate') {
  throw 'Mass-spectrum mode identity is invalid.'
}
$formalMph = Join-Path $artifactRoot 'formal\comsol\single_reflection_oa_tof_mass_analyzer__model.mph'
$formalSimion = Join-Path $artifactRoot 'formal\simion'
$formalIob = Join-Path $formalSimion 'oatof_ideal_grounded.iob'
$ionGenerator = Join-Path $projectRoot 'simion\workbench\generate_comsol_consistent_ions.ps1'
$simionAnalyzer = Join-Path $projectRoot 'simion\workbench\analyze_ideal_field_log.ps1'
$requiredPaths = @($modePath,$resolvedPath,$formalMph,$formalIob,$python,$ionGenerator,
  $simionAnalyzer,$particleCountPolicyPath)
if (-not $ReanalyzeOnly) { $requiredPaths += $SimionExe }
foreach ($path in $requiredPaths) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required input is absent: $path" }
}
$particleCountPolicy = Get-Content -LiteralPath $particleCountPolicyPath -Raw -Encoding UTF8 |
  ConvertFrom-Json
$runConfigPath = Join-Path $runDir 'run_config.json'
$preflightRunConfig = Get-Content -LiteralPath $runConfigPath -Raw -Encoding UTF8 |
  ConvertFrom-Json -AsHashtable
$preflightRunConfig.inputs = [ordered]@{
  mode_config = $modePath
  resolved_geometry = $resolvedPath
  particle_count_policy = $particleCountPolicyPath
}
$preflightRunConfig.particle_source_preflight = @()
$preflightRunConfig.parameters = [ordered]@{
  lifecycle_stage = 'particle_source_preflight'
}
Write-RunJson -Path $runConfigPath -Depth 12 -Value $preflightRunConfig
Write-TerminalRunRecord -RunDir $runDir -Status interrupted `
  -Reason 'Frozen mode, resolved geometry, and particle-count policy are bound.' `
  -RepoRoot $repoRoot -Python $python -SummaryRole 'oa_tof_terminal_run_summary'
$statisticalParticleCount = [int]$particleCountPolicy.statistical_count
& $python -m common.contracts.particle_count_policy --count $statisticalParticleCount
if ($LASTEXITCODE -ne 0) { throw 'Repository statistical particle-count policy is invalid.' }
foreach ($species in $mode.species) {
  & $python -m common.contracts.particle_count_policy --count ([int]$species.particle_count)
  if ($LASTEXITCODE -ne 0) {
    throw "Mass-spectrum species $($species.species_id) has no named standard particle-count contract."
  }
}

$contract = Get-Content -LiteralPath $resolvedPath -Raw | ConvertFrom-Json
$source = $contract.particle_source
$individualIonPaths = [Collections.Generic.List[string]]::new()
$parentIonPaths = [Collections.Generic.List[string]]::new()
$sourceValidationPaths = [Collections.Generic.List[string]]::new()
$sourceProvenance = [Collections.Generic.List[object]]::new()
$totalParticles = 0
foreach ($species in $mode.species) {
  $particleCount = [int]$species.particle_count
  $ionPath = Join-Path $ionDir ("{0}.ion" -f $species.species_id)
  $parentIonPath = Join-Path $ionDir ("{0}__n1000_parent.ion" -f $species.species_id)
  $sourceValidationPath = Join-Path $logDir `
    ("{0}__n1000_parent_validation.json" -f $species.species_id)
  $ionGenerationParameters = @{
    N = $statisticalParticleCount
    MassAmu = [double]$species.mass_amu
    Charge = [int]$species.charge_state
    EnergyMeanEv = [double]$mode.particle_source.initial_energy_mean_ev
    EnergyStdEv = [double]$mode.particle_source.initial_energy_sigma_ev
    HalfWidthXmm = [double]$source.size_x_mm/2
    HalfWidthYmm = [double]$source.size_y_mm/2
    HalfWidthZmm = [double]$source.size_z_mm/2
    CenterXmm = [double]$source.center_x_mm
    CenterYmm = [double]$source.center_y_mm
    CenterZmm = [double]$source.center_z_mm
    Seed = [int]$mode.particle_source.shared_seed
    Output = $parentIonPath
  }
  if ($resumeExisting) {
    foreach ($resumeInput in @($ionPath,$parentIonPath)) {
      if (-not (Test-Path -LiteralPath $resumeInput -PathType Leaf)) {
        throw "Resume input is absent: $resumeInput"
      }
    }
    if (@(Get-Content -LiteralPath $ionPath).Count -ne $particleCount) {
      throw "Resume ION row count is incorrect: $ionPath"
    }
    if (@(Get-Content -LiteralPath $parentIonPath).Count -ne $statisticalParticleCount) {
      throw "Resume N=1000 parent ION row count is incorrect: $parentIonPath"
    }
  } else {
    & $ionGenerator @ionGenerationParameters | Out-Null
    $parentLines = @(Get-Content -LiteralPath $parentIonPath -Encoding ASCII)
    if ($parentLines.Count -ne $statisticalParticleCount) {
      throw "Generated N=1000 parent ION row count is incorrect: $parentIonPath"
    }
    Set-Content -LiteralPath $ionPath -Value @($parentLines | Select-Object -First $particleCount) `
      -Encoding ASCII
  }
  $preflightRecord = [ordered]@{
    species_id = [string]$species.species_id
    status = 'pending_deterministic_parent_validation'
    consumed_source_path = $ionPath
    consumed_source_sha256 = (Get-FileHash -LiteralPath $ionPath -Algorithm SHA256).Hash
    parent_source_path = $parentIonPath
    parent_source_sha256 = (Get-FileHash -LiteralPath $parentIonPath -Algorithm SHA256).Hash
    validation_report_path = $sourceValidationPath
    particle_count = $particleCount
    parent_particle_count = $statisticalParticleCount
    mass_amu = [double]$species.mass_amu
    charge = [int]$species.charge_state
    energy_mean_ev = [double]$mode.particle_source.initial_energy_mean_ev
    energy_std_ev = [double]$mode.particle_source.initial_energy_sigma_ev
    half_width_xyz_mm = @(
      [double]$source.size_x_mm/2,
      [double]$source.size_y_mm/2,
      [double]$source.size_z_mm/2
    )
    center_xyz_mm = @(
      [double]$source.center_x_mm,
      [double]$source.center_y_mm,
      [double]$source.center_z_mm
    )
    seed = [int]$mode.particle_source.shared_seed
  }
  $preflightRunConfig.inputs["particle_source_$($species.species_id)"] = $ionPath
  $preflightRunConfig.inputs["particle_source_parent_$($species.species_id)"] = `
    $parentIonPath
  $preflightRunConfig.particle_source_preflight += $preflightRecord
  Write-RunJson -Path $runConfigPath -Depth 12 -Value $preflightRunConfig
  Write-TerminalRunRecord -RunDir $runDir -Status interrupted `
    -Reason "Deterministic parent validation pending for $($species.species_id)." `
    -RepoRoot $repoRoot -Python $python -SummaryRole 'oa_tof_terminal_run_summary'
  & $ionGenerator @ionGenerationParameters -ValidateExisting `
    -ValidationReport $sourceValidationPath | Out-Null
  if ($LASTEXITCODE -ne 0 -or
      -not (Test-Path -LiteralPath $sourceValidationPath -PathType Leaf)) {
    throw "Deterministic N=1000 parent validation failed: $parentIonPath"
  }
  if ($particleCount -eq [int]$particleCountPolicy.functional_check_count) {
    & $python -m common.contracts.particle_count_policy `
      --prefix-n100 $ionPath --prefix-n1000 $parentIonPath
    if ($LASTEXITCODE -ne 0) {
      throw "N=100 source is not the validated prefix of its N=1000 parent: $ionPath"
    }
  } elseif ($particleCount -eq $statisticalParticleCount) {
    $sourceSha = (Get-FileHash -LiteralPath $ionPath -Algorithm SHA256).Hash
    $parentSha = (Get-FileHash -LiteralPath $parentIonPath -Algorithm SHA256).Hash
    if ($sourceSha -cne $parentSha) {
      throw "N=1000 species source differs from its generated parent: $ionPath"
    }
  } else {
    throw "Mass-spectrum particle count lacks a named source policy: $particleCount"
  }
  $validation = Get-Content -LiteralPath $sourceValidationPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
  $validation | Add-Member -NotePropertyName species_id `
    -NotePropertyValue ([string]$species.species_id)
  $validation | Add-Member -NotePropertyName consumed_source_path `
    -NotePropertyValue $ionPath
  $validation | Add-Member -NotePropertyName consumed_source_sha256 `
    -NotePropertyValue ((Get-FileHash -LiteralPath $ionPath -Algorithm SHA256).Hash)
  $individualIonPaths.Add($ionPath)
  $parentIonPaths.Add($parentIonPath)
  $sourceValidationPaths.Add($sourceValidationPath)
  $sourceProvenance.Add($validation)
  $totalParticles += $particleCount
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

$simionLog = Join-Path $logDir 'simion_stdout.log'
$simionStderr = Join-Path $logDir 'simion_stderr.log'
$simionCsv = Join-Path $resultDir 'simion_particles.csv'
$simionSummary = Join-Path $resultDir 'simion_summary.json'
foreach ($species in $mode.species) {
  $speciesId = [string]$species.species_id
  $ionPath = Join-Path $ionDir "$speciesId.ion"
  $csvPath = Join-Path $comsolDir "$speciesId.csv"
  $reportPath = Join-Path $logDir "$speciesId.report.txt"
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
    OATOF_RUNTIME_DIR=$comsolDir
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
  try {
    foreach ($entry in $variables.GetEnumerator()) {
      $old[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key,'Process')
      [Environment]::SetEnvironmentVariable($entry.Key,$entry.Value,'Process')
    }
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
      -TaskScript (Join-Path $projectRoot 'comsol\run_fixed_particle_retrace.m') `
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
$referenceMassAmu = [double]$contract.validation_target.mass_amu
$simionMaxTofUs = [double](& $python (Join-Path $projectRoot 'analysis\solver_diagnostics.py') `
  mass-spectrum-max-tof --mode $modePath --reference-mass-amu $referenceMassAmu)
if ($LASTEXITCODE -ne 0) { throw 'Mass-spectrum maximum TOF calculation failed.' }
if ($ReanalyzeOnly) {
  foreach ($path in @($simionCsv,$simionSummary)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
      throw "ReanalyzeOnly input is absent: $path"
    }
  }
  $summary = Get-Content -LiteralPath $simionSummary -Raw -Encoding UTF8 | ConvertFrom-Json
} else {
  $runtimeTaskId = (Get-Date -Format 'yyyyMMdd_HHmmss') + '__simion__mass-spectrum-runtime'
  $runtimeRoot = Join-Path $artifactRoot "scratch\$runtimeTaskId"
  $runtimeReceipt = Join-Path $inputDir 'formal_simion_runtime_receipt.json'
  $runtimeRoot = New-OaTofFormalSimionRuntime -ProjectRoot $projectRoot `
    -ArtifactRoot $artifactRoot -PythonExe $python -Destination $runtimeRoot `
    -Receipt $runtimeReceipt
  $executionAlias = New-RunExecutionAlias -TargetDirectory $runDir `
    -ExpectedExecutionRelativePaths @('ions\wide_mz_combined.ion')
  $runtimeAlias = New-RunExecutionAlias -TargetDirectory $runtimeRoot `
    -ExpectedExecutionRelativePaths @('oatof_ideal_grounded.iob')
  $runtimeIob = Join-Path $runtimeAlias.execution_alias 'oatof_ideal_grounded.iob'
  $executionIon = Join-Path $executionAlias.execution_alias 'ions\wide_mz_combined.ion'
  $executionLog = Join-Path $executionAlias.execution_alias 'logs\simion_stdout.log'
  $executionStderr = Join-Path $executionAlias.execution_alias 'logs\simion_stderr.log'
  try {
    $process = Start-Process -FilePath $SimionExe -WorkingDirectory $runtimeAlias.execution_alias `
      -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $executionLog `
      -RedirectStandardError $executionStderr -ArgumentList @(
        '--default-num-particles',[string]$totalParticles,'--nogui','fly',
        '--trajectory-quality','8','--retain-trajectories','0','--particles',$executionIon,
        '--programs','1','--adjustable','trajectory_quality=8','--adjustable',
        'trajectory_log_enable=1','--adjustable',
        ("diagnostic_max_tof_us={0}" -f $simionMaxTofUs),$runtimeIob)
    if ($process.ExitCode -ne 0) { throw "SIMION mixed-species fly failed: $simionStderr" }
  } finally {
    if ($null -ne $runtimeAlias) {
      Remove-RunExecutionAlias -ExecutionAlias $runtimeAlias.execution_alias -TargetDirectory $runtimeRoot
      $runtimeAlias = $null
    }
    Remove-OaTofFormalSimionRuntime -ArtifactRoot $artifactRoot -RuntimeRoot $runtimeRoot
    $runtimeRoot = $null
    if ($null -ne $executionAlias) {
      Remove-RunExecutionAlias -ExecutionAlias $executionAlias.execution_alias -TargetDirectory $runDir
      $executionAlias = $null
    }
  }
  $summary = & $simionAnalyzer -Log $simionLog -IonFile $combinedIon `
    -Mode 'mass_spectrum_candidate' -Distribution 'five_species_shared_source' `
    -ParticleCsv $simionCsv
  $summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $simionSummary -Encoding UTF8
}
if ([int]$summary.Hit -ne $totalParticles) {
  throw "SIMION detected $($summary.Hit)/$totalParticles mixed-species ions."
}

& $python -m projects.single_reflection_oa_tof_mass_analyzer.analysis.mass_spectrum `
  --mode-config $modePath --comsol-dir $comsolDir --simion-csv $simionCsv --output $resultDir
if ($LASTEXITCODE -ne 0) { throw 'Candidate mass-spectrum analysis failed.' }

$runInputs = [ordered]@{
  mode_config = $modePath
  particle_count_policy = $particleCountPolicyPath
  resolved_geometry = $resolvedPath
  formal_comsol_mph = $formalMph
  formal_simion_iob = $formalIob
  formal_simion_runtime_receipt = Join-Path $inputDir 'formal_simion_runtime_receipt.json'
}
$runConfig = [ordered]@{
  schema_version = 1
  role = 'oa_tof_mass_spectrum_run_config'
  run_id = $RunId
  project = 'single_reflection_oa_tof_mass_analyzer'
  project_root = $projectRoot
  mode = 'mass_spectrum_candidate'
  formal_gate_passed = $false
  inputs = $runInputs
  species = $mode.species
  particle_source_provenance = @($sourceProvenance)
  execution = [ordered]@{
    simion = 'one mixed-species fly'
    comsol = 'one particle-tracing solve per species; formal electrostatic solution reused'
    resumed_after_comsol = [bool]$ResumeAfterComsol
    reanalyze_only = [bool]$ReanalyzeOnly
    particle_count_contract = 'repository_standard_with_n100_prefix_of_n1000'
    simion_max_tof_us = $simionMaxTofUs
  }
}
$runConfig | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $runConfigPath -Encoding UTF8
$summaryPath = Join-Path $runDir 'summary.json'
$summaryRecord = Get-Content -LiteralPath (Join-Path $resultDir 'mass_spectrum_metrics.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$summaryRecord | Add-Member -NotePropertyName status -NotePropertyValue 'success' -Force
$summaryRecord | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
$manifestPath = Join-Path $runDir 'run_manifest.json'
$outputs = @($combinedIon,$simionCsv,$simionSummary,$summaryPath)
$outputs += @($individualIonPaths)
$outputs += @($parentIonPaths)
$outputs += @($sourceValidationPaths)
$outputs += @($mode.species | ForEach-Object {
  Join-Path $comsolDir ("{0}.csv" -f $_.species_id)
})
$optionalEvidence = @($simionLog,$simionStderr)
$optionalEvidence += @($mode.species | ForEach-Object {
  Join-Path $logDir ("{0}.report.txt" -f $_.species_id)
})
$optionalEvidence += @(Get-ChildItem -LiteralPath $comsolDir -File -Filter '*_selected_release_from_data_file.txt' |
  ForEach-Object { $_.FullName })
$optionalEvidence += @(Get-ChildItem -LiteralPath $comsolDir -Recurse -File -Filter 'hs_err_pid*.log' |
  ForEach-Object { $_.FullName })
$outputs += @($optionalEvidence | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
$outputs += @(
  (Join-Path $resultDir 'mass_spectrum_particles.csv'),
  (Join-Path $resultDir 'mass_spectrum_summary.csv'),
  (Join-Path $resultDir 'mass_peak_shape_comparison.csv'),
  (Join-Path $resultDir 'mass_spectrum_metrics.json'),
  (Join-Path $resultDir 'mass_spectrum_comparison.png'),
  (Join-Path $resultDir 'mass_detector_landing_comparison.png')
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
$runRecordComplete = $true
Write-Output "MASS_SPECTRUM_CANDIDATE=PASS RUN_ID=$RunId PARTICLES=$totalParticles"
