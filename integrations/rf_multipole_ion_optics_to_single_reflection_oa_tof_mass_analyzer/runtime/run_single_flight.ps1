[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$RunId,
  [Parameter(Mandatory)][string]$ConnectionProfileId,
  [Parameter(Mandatory)][string]$ResolvedConnection,
  [Parameter(Mandatory)][string]$ResolvedEngineeringBudget,
  [Parameter(Mandatory)][string]$RuntimeBinding,
  [Parameter(Mandatory)][ValidateSet('simion')][string]$SourceBranchId,
  [Parameter(Mandatory)][string]$ResolvedSourceContract,
  [Parameter(Mandatory)][string]$ResolvedSourceContractSha256,
  [Parameter(Mandatory)][string]$UpstreamResolvedDesign,
  [Parameter(Mandatory)][string]$UpstreamResolvedDesignSha256,
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
$runtime = Resolve-RfOatofRuntimeBinding -RepoRoot $repoRoot `
  -ResolvedConnection $ResolvedConnection -RuntimeBinding $RuntimeBinding `
  -ExpectedConnectionProfileId $ConnectionProfileId -SourceBranchId $SourceBranchId `
  -ResolvedSourceContract $ResolvedSourceContract `
  -ResolvedSourceContractSha256 $ResolvedSourceContractSha256 `
  -UpstreamResolvedDesign $UpstreamResolvedDesign `
  -UpstreamResolvedDesignSha256 $UpstreamResolvedDesignSha256
. $runtime.run_artifact_support
. (Join-Path $repoRoot 'common\multipole\resource_budget_support.ps1')

function Invoke-SingleFlightPython {
  param([Parameter(Mandatory)][object[]]$Arguments,[Parameter(Mandatory)][string]$Failure)
  $saved = Save-RfEnvironment -Names @('PYTHONPATH','PYTHONNOUSERSITE')
  try {
    $env:PYTHONPATH = $repoRoot; $env:PYTHONNOUSERSITE = '1'
    Push-Location -LiteralPath $repoRoot
    try { & $python @Arguments; if ($LASTEXITCODE -ne 0) { throw $Failure } } finally { Pop-Location }
  } finally { Restore-RfEnvironment -Names @('PYTHONPATH','PYTHONNOUSERSITE') -Snapshot $saved }
}

function Copy-FormalPaSet {
  param([Parameter(Mandatory)][string]$FormalDir,[Parameter(Mandatory)][string]$Destination)
  $inventory = Import-Csv -LiteralPath (Join-Path $FormalDir 'SHA256SUMS.csv')
  $pattern = '^(oatof_ideal_grounded\.(iob|con)|(flight_tube_ground|reflectron|accelerator|detector_ground)\.pa(-surf|#|\d+))$'
  $records = @($inventory | Where-Object { $_.file -match $pattern })
  if (@($records | Where-Object { $_.file -eq 'oatof_ideal_grounded.iob' }).Count -ne 1) {
    throw 'Formal oaTOF inventory has no unique IOB.'
  }
  foreach ($record in $records) {
    $source = Join-Path $FormalDir ([string]$record.file)
    if (-not (Test-Path -LiteralPath $source -PathType Leaf) -or
        (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne ([string]$record.sha256).ToUpperInvariant()) {
      throw "Formal oaTOF asset identity differs: $($record.file)"
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $Destination ([string]$record.file))
  }
}

if (-not (Test-Path -LiteralPath $SimionExe -PathType Leaf)) { throw "SIMION is missing: $SimionExe" }
$artifactRoot = Join-Path $workspaceRoot "artifacts\projects\$($runtime.upstream_project_id)"
$package = New-RfRunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project $runtime.upstream_project_id -Mode 'rf_to_oatof_simion_single_flight' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -AdditionalDirectories @('simion')
$resourceBudgetExceeded = $false
$snapshotReady = $false
$summaryRole = 'rf_oatof_simion_single_flight_summary'
$resourceUsage = Join-Path $package.log_dir 'resource_usage.json'

try {
  $budget = Initialize-RfIntegrationStageBudget -ResolvedBudget $ResolvedEngineeringBudget `
    -InputDir $package.input_dir -ExpectedIntegrationId `
    'rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer' `
    -ExpectedConnectionProfileId $ConnectionProfileId -StageId 'single_flight_transport' -Solver simion
  $configurationSource = Join-Path $integrationRoot 'config\simion_single_flight.json'
  $configuration = Join-Path $package.input_dir 'simion_single_flight.json'
  Copy-RfStableFile -SourceRunRoot $repoRoot -SourcePath $configurationSource -Destination $configuration -Role 'single-flight configuration' | Out-Null
  $settings = Get-Content -LiteralPath $configuration -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($settings.role -ne 'rf_oatof_simion_single_flight_configuration' -or [double]$settings.cell_mm -le 0) {
    throw 'Single-flight numerical configuration is invalid.'
  }
  $resolvedFrozen = Join-Path $package.input_dir 'resolved_connection.json'
  $upstreamFrozen = Join-Path $package.input_dir 'upstream_resolved_design.json'
  $sourceContractFrozen = Join-Path $package.input_dir 'resolved_source_contract.json'
  $runtimeBindingFrozen = Join-Path $package.input_dir 'runtime_binding.json'
  Copy-Item -LiteralPath $runtime.resolved_connection_path -Destination $resolvedFrozen
  Copy-Item -LiteralPath $runtime.contracts.upstream_resolved_design -Destination $upstreamFrozen
  Copy-Item -LiteralPath $runtime.contracts.resolved_source_contract -Destination $sourceContractFrozen
  Copy-Item -LiteralPath $runtime.binding_path -Destination $runtimeBindingFrozen

  $motherSource = Join-Path $package.input_dir 'mother_particle_source.csv'
  Copy-RfStableFile -SourceRunRoot $workspaceRoot -SourcePath $runtime.source_particle_source `
    -Destination $motherSource -Role 'N1000 mother particle source' | Out-Null
  $launched = [int]$runtime.source_record.launched_particle_count
  if (@(Import-Csv -LiteralPath $motherSource).Count -ne $launched) {
    throw 'Single-flight mother sample count differs from source authority.'
  }

  $frontendGem = Join-Path $package.input_dir 'single_flight_frontend.gem'
  $frontendContract = Join-Path $package.input_dir 'single_flight_frontend_contract.json'
  Invoke-SingleFlightPython -Arguments @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_frontend',
    '--upstream',$upstreamFrozen,'--oatof',(Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\config\resolved_geometry.json'),
    '--connection',$resolvedFrozen,'--gem',$frontendGem,'--contract',$frontendContract,
    '--cell-mm',([string]$settings.cell_mm)) -Failure 'Single-flight frontend compilation failed.'
  $frontendHash = (Get-FileHash -LiteralPath $frontendGem -Algorithm SHA256).Hash
  $cacheRoot = Join-Path $workspaceRoot 'artifacts\projects\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\cache\simion_single_flight_frontend'
  $cacheDir = Join-Path $cacheRoot $frontendHash.ToLowerInvariant()
  New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null
  $cacheGem = Join-Path $cacheDir 'frontend.gem'; $cachePaSharp = Join-Path $cacheDir 'frontend.pa#'; $cachePa0 = Join-Path $cacheDir 'frontend.pa0'
  if (-not (Test-Path -LiteralPath $cachePa0 -PathType Leaf)) {
    Copy-Item -LiteralPath $frontendGem -Destination $cacheGem -Force
    $gem2pa = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
      -UsagePath (Join-Path $package.log_dir 'frontend_gem2pa_resource_usage.json') -FilePath $SimionExe `
      -WorkingDirectory $cacheDir -RedirectStandardOutput (Join-Path $package.log_dir 'frontend_gem2pa.stdout.log') `
      -RedirectStandardError (Join-Path $package.log_dir 'frontend_gem2pa.stderr.log') `
      -ArgumentList @('--nogui','--noprompt','gem2pa',$cacheGem,$cachePaSharp)
    if ($gem2pa.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Frontend GEM conversion exceeded its resource budget.' }
    if ($gem2pa.exit_code -ne 0) { throw 'Frontend GEM conversion failed.' }
    $refine = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
      -UsagePath (Join-Path $package.log_dir 'frontend_refine_resource_usage.json') -FilePath $SimionExe `
      -WorkingDirectory $cacheDir -RedirectStandardOutput (Join-Path $package.log_dir 'frontend_refine.stdout.log') `
      -RedirectStandardError (Join-Path $package.log_dir 'frontend_refine.stderr.log') `
      -ArgumentList @('--nogui','--noprompt','refine',$cachePaSharp)
    if ($refine.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Frontend refinement exceeded its resource budget.' }
    if ($refine.exit_code -ne 0 -or -not (Test-Path -LiteralPath $cachePa0 -PathType Leaf)) { throw 'Frontend PA refinement failed.' }
  }

  $ion = Join-Path $package.input_dir 'single_flight_mother_sample.ion'
  $globalSource = Join-Path $package.input_dir 'single_flight_initial_global_state.csv'
  Invoke-SingleFlightPython -Arguments @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source',
    '--source',$motherSource,'--connection',$resolvedFrozen,'--ion',$ion,'--global-state',$globalSource) `
    -Failure 'Single-flight source materialization failed.'

  $runtimeDir = Join-Path $package.run_dir 'simion'
  $formalDir = Join-Path $workspaceRoot 'artifacts\projects\single_reflection_oa_tof_mass_analyzer\formal\simion'
  Copy-FormalPaSet -FormalDir $formalDir -Destination $runtimeDir
  $formalLua = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\formal\oatof_ideal_grounded.lua'
  $pulseLua = Join-Path $repoRoot 'projects\single_reflection_oa_tof_mass_analyzer\simion\workbench\candidates\oatof_handoff_pulse.lua'
  $program = Join-Path $runtimeDir 'oatof_ideal_grounded.lua'
  $programMetadata = Join-Path $package.input_dir 'single_flight_program_build.json'
  Invoke-SingleFlightPython -Arguments @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.build_single_flight_program',
    '--formal',$formalLua,'--pulse-extension',$pulseLua,'--upstream',$upstreamFrozen,
    '--frontend-contract',$frontendContract,'--output',$program,'--metadata',$programMetadata) `
    -Failure 'Single-flight Program build failed.'

  $runConfiguration = [ordered]@{
    schema_version=2; run_id=$RunId; project=$runtime.upstream_project_id; mode='rf_to_oatof_simion_single_flight'; project_root=$repoRoot
    inputs=[ordered]@{ configuration=$configuration; runtime_binding=$runtimeBindingFrozen; resolved_connection=$resolvedFrozen; resolved_source_contract=$sourceContractFrozen; upstream_resolved_design=$upstreamFrozen; resolved_integration_engineering_budget=$budget.frozen_budget; resolved_stage_resource_budget=$budget.stage_budget; mother_particle_source=$motherSource; initial_global_state=$globalSource; ion=$ion; frontend_gem=$frontendGem; frontend_contract=$frontendContract; program_metadata=$programMetadata }
    upstream_source_identity=$runtime.source_identity
    parameters=[ordered]@{ connection_profile_id=$ConnectionProfileId; source_branch_id=$SourceBranchId; launched_particle_count=$launched; particle_count=$launched; aperture_width_mm=1.0; aperture_height_mm=0.9; rod_end_to_accelerator_shield_mm=1.0; surrounded_transition=$true; pulse_time_us=[double]$settings.pulse_time_us; pulse_width_us=[double]$settings.pulse_width_us; frontend_gem_sha256=$frontendHash; frontend_pa0_sha256=(Get-FileHash -LiteralPath $cachePa0 -Algorithm SHA256).Hash }
    artifact_retention=[ordered]@{policy_version=1;class='compact';reason=$null}; formal_gate_passed=$false
  }
  Write-RfJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  Write-RfJson -Path $package.summary -Value ([ordered]@{schema_version=1;role=$summaryRole;status='interrupted';reason='Frozen inputs recorded; SIMION flight not complete.'})
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $repoRoot -RunConfig $package.run_config -Status interrupted -Software @('SIMION 2020','Python 3.11')
  $snapshotReady = $true

  $stdout = Join-Path $package.log_dir 'simion.stdout.log'; $stderr = Join-Path $package.log_dir 'simion.stderr.log'
  $oldOverride = $env:OATOF_ACCELERATOR_PA_OVERRIDE
  try {
    $env:OATOF_ACCELERATOR_PA_OVERRIDE = $cachePa0
    $fly = Invoke-ResourceBudgetedProcess -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir `
      -UsagePath $resourceUsage -FilePath $SimionExe -WorkingDirectory $runtimeDir `
      -RedirectStandardOutput $stdout -RedirectStandardError $stderr -ArgumentList @(
      '--default-num-particles',([string][Math]::Max(100,$launched)),'--nogui','--noprompt','fly',
      '--trajectory-quality',([string]$settings.trajectory_quality),'--retain-trajectories','0','--particles',$ion,'--programs','1',
      '--adjustable',("trajectory_quality={0}" -f $settings.trajectory_quality),'--adjustable','trajectory_log_enable=1',
      '--adjustable',("diagnostic_max_tof_us={0:R}" -f [double]$settings.maximum_time_of_flight_us),
      '--adjustable','handoff_pulse_mode=1','--adjustable',("handoff_pulse_time_us={0:R}" -f [double]$settings.pulse_time_us),
      '--adjustable',("handoff_pulse_width_us={0:R}" -f [double]$settings.pulse_width_us),
      '--adjustable',("single_flight_rf_steps={0}" -f [int]$settings.rf_steps_per_period),
      (Join-Path $runtimeDir 'oatof_ideal_grounded.iob'))
  } finally { $env:OATOF_ACCELERATOR_PA_OVERRIDE = $oldOverride }
  if ($fly.resource_budget_exceeded) { $resourceBudgetExceeded=$true; throw 'Single-flight SIMION run exceeded its resource budget.' }
  if ($fly.exit_code -ne 0) { throw "Single-flight SIMION run failed: $stderr" }

  $checkpoints = Join-Path $package.result_dir 'single_flight_particle_checkpoints.csv'
  Invoke-SingleFlightPython -Arguments @('-m',
    'integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight',
    '--log',$stdout,'--launched',([string]$launched),'--mass-amu','100','--checkpoints',$checkpoints,'--summary',$package.summary) `
    -Failure 'Single-flight log analysis failed.'
  $result = Get-Content -LiteralPath $package.summary -Raw -Encoding UTF8 | ConvertFrom-Json
  $runConfiguration.parameters.multipole_handoff_count = [int]$result.census.multipole_handoff
  $runConfiguration.parameters.local_accelerator_exit_count = [int]$result.census.local_accelerator_exit
  $runConfiguration.parameters.detector_crossing_count = [int]$result.census.detector_crossing
  Write-RfJson -Path $package.run_config -Depth 10 -Value $runConfiguration
  $retentionActions = Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $outputs = @($checkpoints,$stdout,$stderr,$resourceUsage,$package.summary,$retentionActions) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }
  if (-not (Complete-ResourceUsage -ResolvedBudgetPath $budget.stage_budget -RunDir $package.run_dir -UsagePath $resourceUsage)) { $resourceBudgetExceeded=$true; throw 'Single-flight compact retained-byte budget exceeded.' }
  Write-RfFrozenRunManifest -Python $python -FrozenRepoRoot $repoRoot -RunConfig $package.run_config -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $outputs
  Write-Output "SIMION_SINGLE_FLIGHT=PASS RUN_ID=$RunId DETECTOR=$($result.census.detector_crossing)/$launched"
} catch {
  if ($snapshotReady) {
    Complete-RfFrozenFailedRun -Python $python -FrozenRepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary -SummaryRole $summaryRole -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status $(if ($resourceBudgetExceeded) {'interrupted'} else {'failed'}) -FailureClass $(if ($resourceBudgetExceeded) {'resource_budget_exceeded'} else {''}) -ResourceUsagePath $(if ($resourceBudgetExceeded) {$resourceUsage} else {''})
  } else {
    Write-RfJson -Path $package.summary -Value ([ordered]@{schema_version=1;role=$summaryRole;status='failed';reason=$_.Exception.Message;manifest_written=$false})
  }
  throw
}
