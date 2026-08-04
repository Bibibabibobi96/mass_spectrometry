[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$RunId,
  [Parameter(Mandatory)][string]$BaselineRunId,
  [Parameter(Mandatory)][string]$IdealRunId,
  [string]$SimionExe = 'C:\Program Files\SIMION-2020\simion.exe',
  [string]$PythonExe = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$integrationRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$repoRoot = (Resolve-Path (Join-Path $integrationRoot '..\..')).Path
$workspaceRoot = Split-Path -Parent $repoRoot
$runtimeRoot = Join-Path $integrationRoot 'runtime'
$python = if ($PythonExe) {
  [IO.Path]::GetFullPath($PythonExe)
} else {
  Join-Path $repoRoot '.venv\Scripts\python.exe'
}
. (Join-Path $runtimeRoot 'run_artifacts.ps1')
. (Join-Path $runtimeRoot 'single_flight_assets.ps1')
. (Join-Path $repoRoot 'common\multipole\resource_budget_support.ps1')

function Invoke-AttributionPython {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][object[]]$Arguments,
    [Parameter(Mandatory)][string]$Failure
  )
  $saved = Save-RfEnvironment -Names @('PYTHONPATH','PYTHONNOUSERSITE')
  try {
    $env:PYTHONPATH = $repoRoot
    $env:PYTHONNOUSERSITE = '1'
    Push-Location -LiteralPath $repoRoot
    try {
      & $python @Arguments
      if ($LASTEXITCODE -ne 0) { throw $Failure }
    } finally {
      Pop-Location
    }
  } finally {
    Restore-RfEnvironment -Names @('PYTHONPATH','PYTHONNOUSERSITE') `
      -Snapshot $saved
  }
}

function Assert-VerifiedSourceRun {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$RunRoot,
    [Parameter(Mandatory)][string]$ExpectedRunId,
    [Parameter(Mandatory)][string]$ExpectedProject,
    [Parameter(Mandatory)][string]$ExpectedMode
  )
  $manifest = Join-Path $RunRoot 'run_manifest.json'
  Invoke-AttributionPython -Arguments @(
    'common/contracts/verify_run_manifest.py', $manifest,
    '--require-status','success',
    '--require-local-run-config',
    '--require-run-id',$ExpectedRunId,
    '--require-project',$ExpectedProject,
    '--require-mode',$ExpectedMode
  ) -Failure "Source run manifest verification failed: $ExpectedRunId"
}

if (-not (Test-Path -LiteralPath $SimionExe -PathType Leaf)) {
  throw "SIMION is missing: $SimionExe"
}
$baselineRoot = Join-Path $workspaceRoot (
  "artifacts\projects\rf_octupole_ion_optics\runs\$BaselineRunId"
)
$idealRoot = Join-Path $workspaceRoot (
  "artifacts\projects\single_reflection_oa_tof_mass_analyzer\runs\$IdealRunId"
)
Assert-VerifiedSourceRun -RunRoot $baselineRoot -ExpectedRunId $BaselineRunId `
  -ExpectedProject 'rf_octupole_ion_optics' `
  -ExpectedMode 'rf_to_oatof_simion_single_flight'
Assert-VerifiedSourceRun -RunRoot $idealRoot -ExpectedRunId $IdealRunId `
  -ExpectedProject 'single_reflection_oa_tof_mass_analyzer' `
  -ExpectedMode 'formal_vnext_zero_change_validation'

$artifactRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_octupole_ion_optics'
$package = New-RfRunPackage -Python $python -RepoRoot $repoRoot `
  -ArtifactRoot $artifactRoot -RunId $RunId -Project 'rf_octupole_ion_optics' `
  -Mode 'rf_oatof_resolution_attribution_counterfactual' `
  -Software @('SIMION 2020','Python 3.11') `
  -RetentionContractEnabled -RetentionClass compact `
  -AdditionalDirectories @('simion')
$summaryRole = 'rf_oatof_resolution_attribution_counterfactual_summary'
$snapshotReady = $false
$resourceBudgetExceeded = $false

try {
  $baselineConfig = Get-Content -LiteralPath (
    Join-Path $baselineRoot 'run_config.json'
  ) -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($baselineConfig.parameters.launched_particle_count -ne 1000 -or
      $baselineConfig.parameters.aperture_width_mm -ne 1.0 -or
      $baselineConfig.parameters.aperture_height_mm -ne 0.9 -or
      -not $baselineConfig.parameters.surrounded_transition) {
    throw 'Baseline run is not the frozen N=1000, 1.0 x 0.9 mm closed-connector case.'
  }
  $profileSource = Join-Path $integrationRoot `
    'config\resolution_attribution_counterfactual.json'
  $profile = Join-Path $package.input_dir `
    'resolution_attribution_counterfactual.json'
  Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $profileSource `
    -Destination $profile -Role 'resolution-attribution profile' | Out-Null
  $baselineCheckpoints = Join-Path $package.input_dir `
    'baseline_single_flight_particle_checkpoints.csv'
  Copy-RfStableFile -SourceRunRoot $baselineRoot `
    -SourcePath (Join-Path $baselineRoot `
      'results\single_flight_particle_checkpoints.csv') `
    -Destination $baselineCheckpoints -Role 'baseline particle checkpoints' | Out-Null
  $idealSource = Join-Path $package.input_dir 'ideal_source_mapping_particles.csv'
  Copy-RfStableFile -SourceRunRoot $idealRoot `
    -SourcePath (Join-Path $idealRoot 'results\source_mapping_particles.csv') `
    -Destination $idealSource -Role 'ideal source mapping' | Out-Null
  foreach ($name in @(
      'upstream_resolved_design.json',
      'single_flight_frontend_contract.json',
      'resolved_connection.json',
      'oatof_resolved_geometry.json'
    )) {
    Copy-RfStableFile -SourceRunRoot $baselineRoot `
      -SourcePath (Join-Path $baselineRoot "inputs\$name") `
      -Destination (Join-Path $package.input_dir $name) `
      -Role "baseline frozen $name" | Out-Null
  }
  $budget = Initialize-RfIntegrationStageBudget `
    -ResolvedBudget (Join-Path $baselineRoot `
      'inputs\resolved_integration_engineering_budget.json') `
    -InputDir $package.input_dir `
    -ExpectedIntegrationId `
      'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' `
    -ExpectedConnectionProfileId `
      'rf_octupole_oatof_shield_terminal_direct_mating_gap_0mm' `
    -StageId 'single_flight_transport' -Solver simion

  $preparedDir = Join-Path $package.input_dir 'counterfactual_arms'
  Invoke-AttributionPython -Arguments @(
    '-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.resolution_attribution_counterfactual',
    'prepare','--profile',$profile,'--checkpoints',$baselineCheckpoints,
    '--ideal-source',$idealSource,'--output-dir',$preparedDir,
    '--mass-amu','100','--charge-state','1'
  ) -Failure 'Counterfactual arm preparation failed.'
  $prepared = Get-Content -LiteralPath (
    Join-Path $preparedDir 'prepared_arms.json'
  ) -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($prepared.mother_sample_particle_count -ne 1000 -or
      $prepared.paired_cohort_particles -lt 3) {
    throw 'Prepared counterfactual cohort identity differs.'
  }

  $runtimeDir = Join-Path $package.run_dir 'simion'
  $formalDir = Join-Path $workspaceRoot `
    'artifacts\projects\single_reflection_oa_tof_mass_analyzer\formal\simion'
  Copy-RfOatofFormalPaSet -FormalDir $formalDir -Destination $runtimeDir
  $program = Join-Path $runtimeDir 'oatof_ideal_grounded.lua'
  $programMetadata = Join-Path $package.input_dir `
    'single_flight_program_build.json'
  Invoke-AttributionPython -Arguments @(
    '-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.build_single_flight_program',
    '--formal',(Join-Path $repoRoot `
      'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\formal\oatof_ideal_grounded.lua'),
    '--pulse-extension',(Join-Path $repoRoot `
      'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\candidates\oatof_handoff_pulse.lua'),
    '--upstream',(Join-Path $package.input_dir 'upstream_resolved_design.json'),
    '--frontend-contract',(Join-Path $package.input_dir `
      'single_flight_frontend_contract.json'),
    '--output',$program,'--metadata',$programMetadata
  ) -Failure 'Counterfactual single-flight Program build failed.'

  $frontendHash = ([string]$baselineConfig.parameters.frontend_gem_sha256).ToLowerInvariant()
  $frontendPa0 = Join-Path $workspaceRoot (
    'artifacts\projects\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' +
    "\cache\simion_single_flight_frontend\$frontendHash\frontend.pa0"
  )
  if (-not (Test-Path -LiteralPath $frontendPa0 -PathType Leaf) -or
      (Get-FileHash -LiteralPath $frontendPa0 -Algorithm SHA256).Hash -ne
      ([string]$baselineConfig.parameters.frontend_pa0_sha256).ToUpperInvariant()) {
    throw 'Baseline frontend PA cache identity differs.'
  }
  $runConfiguration = [ordered]@{
    schema_version = 2
    run_id = $RunId
    project = 'rf_octupole_ion_optics'
    mode = 'rf_oatof_resolution_attribution_counterfactual'
    project_root = $repoRoot
    inputs = [ordered]@{
      profile = $profile
      baseline_checkpoints = $baselineCheckpoints
      ideal_source = $idealSource
      prepared_arms = Join-Path $preparedDir 'prepared_arms.json'
      upstream_resolved_design = Join-Path $package.input_dir `
        'upstream_resolved_design.json'
      single_flight_frontend_contract = Join-Path $package.input_dir `
        'single_flight_frontend_contract.json'
      resolved_connection = Join-Path $package.input_dir 'resolved_connection.json'
      oatof_resolved_geometry = Join-Path $package.input_dir `
        'oatof_resolved_geometry.json'
      resolved_integration_engineering_budget = $budget.frozen_budget
      resolved_stage_resource_budget = $budget.stage_budget
      program_metadata = $programMetadata
    }
    source_runs = [ordered]@{
      continuous_baseline_run_id = $BaselineRunId
      ideal_reference_run_id = $IdealRunId
    }
    parameters = [ordered]@{
      mother_sample_particle_count = 1000
      paired_cohort_particles = [int]$prepared.paired_cohort_particles
      arm_count = @($prepared.arms).Count
      pulse_time_us = [double]$prepared.pulse_time_us
      trajectory_quality = 8
      maximum_time_of_flight_us = 90.0
      rf_steps_per_period = 160
      frontend_gem_sha256 = ([string]$baselineConfig.parameters.frontend_gem_sha256)
      frontend_pa0_sha256 = ([string]$baselineConfig.parameters.frontend_pa0_sha256)
    }
    artifact_retention = [ordered]@{
      policy_version = 1
      class = 'compact'
      reason = $null
    }
    formal_gate_passed = $false
  }
  Write-RfJson -Path $package.run_config -Depth 12 -Value $runConfiguration
  Write-RfJson -Path $package.summary -Value ([ordered]@{
    schema_version = 1
    role = $summaryRole
    status = 'interrupted'
    reason = 'Frozen counterfactual inputs recorded; SIMION arms not complete.'
  })
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $repoRoot `
    -RunConfig $package.run_config -Status interrupted `
    -Software @('SIMION 2020','Python 3.11')
  $snapshotReady = $true

  $oldOverride = $env:OATOF_ACCELERATOR_PA_OVERRIDE
  try {
    $env:OATOF_ACCELERATOR_PA_OVERRIDE = $frontendPa0
    foreach ($arm in $prepared.arms) {
      $armId = [string]$arm.arm_id
      $stdout = Join-Path $package.log_dir "$armId.stdout.log"
      $stderr = Join-Path $package.log_dir "$armId.stderr.log"
      $usage = Join-Path $package.log_dir "$armId.resource_usage.json"
      $fly = Invoke-ResourceBudgetedProcess `
        -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
        -UsagePath $usage -FilePath $SimionExe -WorkingDirectory $runtimeDir `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
        -ArgumentList @(
          '--default-num-particles',([string][Math]::Max(
            100,[int]$prepared.paired_cohort_particles
          )),
          '--nogui','--noprompt','fly','--trajectory-quality','8',
          '--retain-trajectories','0',
          '--particles',(Join-Path $preparedDir ([string]$arm.ion_file)),
          '--programs','1','--adjustable','trajectory_quality=8',
          '--adjustable','trajectory_log_enable=1',
          '--adjustable','diagnostic_max_tof_us=90',
          '--adjustable','handoff_pulse_mode=1',
          '--adjustable',(
            'handoff_pulse_time_us={0:R}' -f [double]$prepared.pulse_time_us
          ),
          '--adjustable','handoff_pulse_width_us=1',
          '--adjustable','single_flight_rf_steps=160',
          (Join-Path $runtimeDir 'oatof_ideal_grounded.iob')
        )
      if ($fly.resource_budget_exceeded) {
        $resourceBudgetExceeded = $true
        throw "Counterfactual arm exceeded its resource budget: $armId"
      }
      if ($fly.exit_code -ne 0) {
        throw "Counterfactual SIMION arm failed: $armId"
      }
      Write-Output "RESOLUTION_ATTRIBUTION_ARM=PASS ARM=$armId"
    }
  } finally {
    $env:OATOF_ACCELERATOR_PA_OVERRIDE = $oldOverride
  }

  $analysisDir = Join-Path $package.result_dir 'resolution_attribution'
  Invoke-AttributionPython -Arguments @(
    '-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.resolution_attribution_counterfactual',
    'summarize','--profile',$profile,
    '--prepared',(Join-Path $preparedDir 'prepared_arms.json'),
    '--baseline-checkpoints',$baselineCheckpoints,
    '--logs-dir',$package.log_dir,'--output-dir',$analysisDir
  ) -Failure 'Counterfactual result analysis failed.'
  Copy-Item -LiteralPath (Join-Path $analysisDir `
    'resolution_attribution.json') -Destination $package.summary -Force
  $retentionActions = Apply-RunArtifactRetention -Python $python `
    -RepoRoot $repoRoot -RunConfig $package.run_config
  $outputs = @(
    $package.summary,
    (Join-Path $analysisDir 'resolution_attribution.json'),
    (Join-Path $analysisDir 'counterfactual_particle_checkpoints.csv'),
    $retentionActions
  )
  $outputs += @(Get-ChildItem -LiteralPath $package.log_dir -File | ForEach-Object {
    $_.FullName
  })
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $repoRoot `
    -RunConfig $package.run_config -Status success `
    -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  Write-Output (
    "RESOLUTION_ATTRIBUTION=PASS RUN_ID=$RunId " +
    "ARMS=$(@($prepared.arms).Count) PARTICLES=$($prepared.paired_cohort_particles)"
  )
} catch {
  if ($snapshotReady) {
    Complete-RfFrozenFailedRun -Python $python -FrozenRepoRoot $repoRoot `
      -RunConfig $package.run_config -Summary $package.summary `
      -SummaryRole $summaryRole -Reason $_.Exception.Message `
      -Software @('SIMION 2020','Python 3.11') `
      -Status $(if ($resourceBudgetExceeded) {'interrupted'} else {'failed'}) `
      -FailureClass $(if ($resourceBudgetExceeded) {
        'resource_budget_exceeded'
      } else {''})
  } else {
    Write-RfJson -Path $package.summary -Value ([ordered]@{
      schema_version = 1
      role = $summaryRole
      status = 'failed'
      reason = $_.Exception.Message
      manifest_written = $false
    })
  }
  throw
}
