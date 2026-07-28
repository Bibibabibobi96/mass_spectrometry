param(
  [string]$RunId='',
  [Parameter(Mandatory=$true)][string]$SourceIonPath,
  [Parameter(Mandatory=$true)][string]$SolverNumericsContractPath,
  [Parameter(Mandatory=$true)][string]$SolverNumericsProfileId,
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot=Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot=Split-Path -Parent $repoRoot
$artifactRoot=Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_ion_optics'
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
. (Join-Path $projectRoot 'runtime\run_artifacts.ps1')
. (Join-Path $projectRoot 'runtime\comsol_solver_numerics.ps1')
if([string]::IsNullOrWhiteSpace($RunId)){
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__comsol__mass-filter__rf-dc-scan'
}
$software=@('COMSOL 6.4','MATLAB R2025b','Python 3.11')
$package=New-RfRunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RunId $RunId `
  -Project 'rf_quadrupole_ion_optics' -Mode 'mass_filter_reference' -Software $software `
  -AdditionalDirectories @('comsol','runtime')
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir;$logDir=$package.log_dir
$report=Join-Path $logDir 'comsol_mass_filter_scan.txt'
$scanConfig=Join-Path $inputDir 'comsol_mass_scan_cases.json'
$massScanTask=Join-Path $projectRoot 'comsol\mass_filter_reference\run_scan.m'

try {
  $officialNumerics=Join-Path $projectRoot 'config\comsol_solver_numerics.json'
  $requestedNumerics=if([IO.Path]::IsPathRooted($SolverNumericsContractPath)){
    [IO.Path]::GetFullPath($SolverNumericsContractPath)
  }else{
    [IO.Path]::GetFullPath((Join-Path $repoRoot $SolverNumericsContractPath))
  }
  $requestedSource=if([IO.Path]::IsPathRooted($SourceIonPath)){
    [IO.Path]::GetFullPath($SourceIonPath)
  }else{
    [IO.Path]::GetFullPath((Join-Path $repoRoot $SourceIonPath))
  }
  if(-not(Test-Path -LiteralPath $requestedSource -PathType Leaf)){
    throw "Mass-filter source ION11 table is missing: $requestedSource"
  }
  $sources=@{
    baseline=Join-Path $projectRoot 'config\baseline.json'
    mode=Join-Path $projectRoot 'config\modes\mass_filter_reference.json'
    resolved_design=Join-Path $projectRoot 'config\resolved_design_mass_filter.json'
    interface_contract=Join-Path $projectRoot 'config\interface_contract.json'
    comsol_solver_numerics=$officialNumerics
    particles=$requestedSource
  }
  foreach($key in @($sources.Keys)){
    $destination=Join-Path $inputDir (Split-Path -Leaf $sources[$key])
    Copy-Item -LiteralPath $sources[$key] -Destination $destination
    $sources[$key]=$destination
  }
  $numericsCompilation=Compile-RfComsolSolverNumerics `
    -OfficialContractPath $sources.comsol_solver_numerics `
    -RequestedContractPath $requestedNumerics `
    -ProfileId $SolverNumericsProfileId
  $compiledNumerics=$numericsCompilation.compiled
  $sourceParticleCount=@(Get-Content -LiteralPath $sources.particles -Encoding UTF8|Where-Object{-not[string]::IsNullOrWhiteSpace($_)}).Count
  & $package.python (Join-Path $repoRoot `
    'common\contracts\particle_count_policy.py') --count $sourceParticleCount
  if($LASTEXITCODE-ne 0){throw 'Mass-filter source violates the repository N=100/N=1000 policy.'}
  $codeInputs=[ordered]@{}
  $codeSources=[ordered]@{
    runner=$PSCommandPath
    matlab_task=$massScanTask
    comsol_builder=(Join-Path $projectRoot `
      'comsol\solve_deterministic_rf_quadrupole_particles.m')
    contract_loader=(Join-Path $projectRoot 'load_rf_quadrupole_contract.m')
    case_preparer=(Join-Path $PSScriptRoot 'prepare_comsol_scan.py')
    result_analyzer=(Join-Path $PSScriptRoot 'evaluate_comsol.py')
    paired_mass_library=(Join-Path $repoRoot 'common\multipole\paired_mass_scan.py')
  }
  foreach($key in $codeSources.Keys){
    $extension=[IO.Path]::GetExtension($codeSources[$key]);$destination=Join-Path $inputDir "$key$extension.txt"
    Copy-Item -LiteralPath $codeSources[$key] -Destination $destination;$codeInputs[$key]=$destination
  }
  $caseTableDir=Join-Path $inputDir 'particle_cases'
  $caseMetadata=Join-Path $inputDir 'particle_cases.json'
  & $package.python -m `
    projects.rf_quadrupole_ion_optics.workflows.mass_filter_reference.prepare_comsol_scan `
    --source $sources.particles --mode $sources.mode --output-dir $caseTableDir --metadata $caseMetadata
  if($LASTEXITCODE-ne 0){throw 'COMSOL mass-case preparation failed.'}
  $prepared=Get-Content -LiteralPath $caseMetadata -Raw -Encoding UTF8|ConvertFrom-Json
  $massCount=@($prepared.cases).Count
  $particlesPerMass=[int]$prepared.cases[0].particles
  $totalParticles=[int](($prepared.cases|Measure-Object -Property particles -Sum).Sum)
  $centerMass=[double]$prepared.cases[[math]::Floor($massCount/2)].mass_Th
  $cases=@()
  foreach($case in $prepared.cases){
    $mass=[double]$case.mass_Th;$token=('{0:g}' -f $mass).Replace('.','p')
    $caseResultDir=Join-Path $resultDir "mass_$token`_Th"
    $caseComsolDir=Join-Path $runDir "comsol\mass_$token`_Th"
    $caseRuntimeDir=Join-Path $runDir "runtime\mass_$token`_Th"
    New-Item -ItemType Directory -Force -Path $caseResultDir,$caseComsolDir,$caseRuntimeDir|Out-Null
    $caseConfigPath=Join-Path $inputDir "case_mass_$token`_Th.json"
    $caseConfig=[ordered]@{
      schema_version=1;role='rf_quadrupole_comsol_mass_filter_case';run_id="${RunId}--mass-${token}-Th"
      project='rf_quadrupole_ion_optics';mode='mass_filter_reference'
      workflow_id='mass_filter_reference';operating_point="mass_$token`_Th"
      inputs=[ordered]@{
        resolved_design=$sources.resolved_design
        scientific_mode=$sources.mode
        interface_contract=$sources.interface_contract
        comsol_solver_numerics=$sources.comsol_solver_numerics
        particle_table=[string]$case.particle_table
      }
      compiled_scientific_spec=[ordered]@{
        role='rf_quadrupole_comsol_mass_filter_scientific_spec'
        workflow_id='mass_filter_reference'
        source_axial_offset_mm=0.0
      }
      compiled_solver_numerics=$compiledNumerics
      solver_numerics_contract_id=$compiledNumerics.authority.contract_id
      solver_numerics_contract_logical_sha256=$compiledNumerics.authority.logical_sha256
      solver_numerics_profile_id=$compiledNumerics.selection.profile_id
      numerical_experiment_id=$compiledNumerics.selection.numerical_experiment_id
      particles=[int]$case.particles
      results_dir=$caseResultDir;comsol_dir=$caseComsolDir;runtime_dir=$caseRuntimeDir
      comsol_rf_steps_per_period=$compiledNumerics.trajectory.rf_steps_per_period
      comsol_mesh_auto_level=$compiledNumerics.mesh.global_auto_level
      maximum_time_us=$compiledNumerics.trajectory.maximum_time_us
      output_policy=[ordered]@{
        save_model=($mass-eq $centerMass)
        write_detailed_outputs=$false
      }
    }
    Write-RfJson -Value $caseConfig -Path $caseConfigPath
    $cases+=,[ordered]@{mass_Th=$mass;run_config=$caseConfigPath;solver_summary=(Join-Path $caseResultDir 'solver_summary.json');particle_state=(Join-Path $caseResultDir 'particle_state.csv')}
  }
  Write-RfJson -Value ([ordered]@{schema_version=1;role='rf_quadrupole_comsol_mass_filter_scan_execution';cases=$cases}) -Path $scanConfig
  $runConfiguration=[ordered]@{
    schema_version=1;role='rf_quadrupole_comsol_mass_filter_run_config'
    run_id=$RunId;project='rf_quadrupole_ion_optics';mode='mass_filter_reference';project_root=$repoRoot
    inputs=[ordered]@{
      baseline=$sources.baseline
      mode=$sources.mode
      resolved_design=$sources.resolved_design
      interface_contract=$sources.interface_contract
      comsol_solver_numerics=$sources.comsol_solver_numerics
      source_ion11=$sources.particles
      particle_cases=$caseMetadata
      scan_execution=$scanConfig
      code=$codeInputs
    }
    compiled_solver_numerics=$compiledNumerics
    solver_numerics_contract_id=$compiledNumerics.authority.contract_id
    solver_numerics_contract_logical_sha256=$compiledNumerics.authority.logical_sha256
    solver_numerics_profile_id=$compiledNumerics.selection.profile_id
    numerical_experiment_id=$compiledNumerics.selection.numerical_experiment_id
    parameters=[ordered]@{particles_per_mass=$particlesPerMass;masses=$massCount;total_particles=$totalParticles;rf_steps_per_period=$compiledNumerics.trajectory.rf_steps_per_period;mesh_auto_level=$compiledNumerics.mesh.global_auto_level;compact_outputs=$true;saved_model_mass_Th=$centerMass;lifecycle_stage='inputs_frozen'}
    formal_gate_passed=$false
  }
  Write-RfJson -Value $runConfiguration -Path $package.run_config

  $environment=Save-RfEnvironment -Names @('RFQUAD_SCAN_CONFIG','COMSOL_BOOTSTRAP_REPORT')
  try {
    $env:RFQUAD_SCAN_CONFIG=$scanConfig;$env:COMSOL_BOOTSTRAP_REPORT=$report
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
      -TaskScript $massScanTask -ReportPath $report `
      -StartupAttempts 1 -StartupReportTimeoutSeconds 1200
    if($LASTEXITCODE-ne 0){throw 'COMSOL RF+DC mass-filter scan failed.'}
  } finally { Restore-RfEnvironment -Names @('RFQUAD_SCAN_CONFIG','COMSOL_BOOTSTRAP_REPORT') -Snapshot $environment }

  foreach($case in $cases){
    foreach($path in @($case.solver_summary,$case.particle_state)){
      if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Mass-case output is missing: $path"}
    }
  }
  $response=Join-Path $resultDir 'mass-response__comsol.csv'
  $metrics=Join-Path $resultDir 'mass-filter__comsol-functional-metrics.json'
  & $package.python -m `
    projects.rf_quadrupole_ion_optics.workflows.mass_filter_reference.evaluate_comsol `
    --scan-config $scanConfig --mode $sources.mode `
    --response $response --metrics $metrics
  if($LASTEXITCODE-ne 0){throw 'COMSOL mass-filter functional analysis failed.'}
  $metricDocument=Get-Content -LiteralPath $metrics -Raw -Encoding UTF8|ConvertFrom-Json
  Write-RfJson -Path $package.summary -Value ([ordered]@{
    schema_version=1;role='rf_quadrupole_comsol_mass_filter_summary';status='success';mode='mass_filter_reference'
    particles=$totalParticles;masses=$massCount;functional_gate=$metricDocument.status;response='results/mass-response__comsol.csv'
    metrics='results/mass-filter__comsol-functional-metrics.json'
    claim_limit=$metricDocument.claim_limit
  })
  $outputs=@($report,$response,$metrics,$package.summary)
  foreach($case in $cases){$outputs+=@($case.solver_summary,$case.particle_state)}
  $centerToken=('{0:g}' -f $centerMass).Replace('.','p')
  $centerModel=Join-Path $runDir "comsol\mass_$centerToken`_Th\rf_quadrupole_ion_optics__model.mph"
  if(Test-Path -LiteralPath $centerModel -PathType Leaf){$outputs+=$centerModel}
  Write-RfRunManifest -Python $package.python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Status success -Software $software -Outputs $outputs
  "STATUS=PASS RUN_ID=$RunId FUNCTIONAL_GATE=$($metricDocument.status)"
} catch {
  Complete-RfFailedRun -Python $package.python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Summary $package.summary -SummaryRole 'rf_quadrupole_comsol_mass_filter_summary' -Reason $_.Exception.Message -Software $software
  throw
}
