param(
  [string]$RunId='',
  [int]$RfStepsPerPeriod=80,
  [int]$MeshAutoLevel=1,
  [Parameter(Mandatory=$true)][string]$L1RunId,
  [Parameter(Mandatory=$true)][string]$SimionRunId
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot=Split-Path -Parent (Split-Path -Parent $projectRoot)
$workspaceRoot=Split-Path -Parent $repoRoot
$artifactRoot=Join-Path $workspaceRoot 'artifacts\projects\rf_quadrupole_collision_cooling'
. (Join-Path $projectRoot 'tests\support\rf_run_artifact_support.ps1')
if([string]::IsNullOrWhiteSpace($RunId)){
  $RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__comsol__mass-filter__rf-dc-n700'
}
$software=@('COMSOL 6.4','MATLAB R2025b','Python 3.11')
$package=New-RfRunPackage -RepoRoot $repoRoot -ArtifactRoot $artifactRoot -RunId $RunId `
  -Project 'rf_quadrupole_collision_cooling' -Mode 'mass_filter_reference' -Software $software `
  -AdditionalDirectories @('comsol','runtime')
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir;$logDir=$package.log_dir
$report=Join-Path $logDir 'comsol_mass_filter_scan.txt'
$scanConfig=Join-Path $inputDir 'comsol_mass_scan_cases.json'

try {
  $sources=@{
    baseline=Join-Path $projectRoot 'config\baseline.json'
    mode=Join-Path $projectRoot 'config\modes\mass_filter_reference.json'
    resolved_design=Join-Path $projectRoot 'config\resolved_design_mass_filter.json'
    particles=Join-Path $projectRoot 'config\particles\official_fixed_100.ion'
  }
  foreach($key in @($sources.Keys)){
    $destination=Join-Path $inputDir (Split-Path -Leaf $sources[$key])
    Copy-Item -LiteralPath $sources[$key] -Destination $destination
    $sources[$key]=$destination
  }
  $sourceParticleCount=@(Get-Content -LiteralPath $sources.particles -Encoding UTF8|Where-Object{-not[string]::IsNullOrWhiteSpace($_)}).Count
  & $package.python -m common.contracts.particle_count_policy --count $sourceParticleCount
  if($LASTEXITCODE-ne 0){throw 'Mass-filter source violates the repository N=100/N=1000 policy.'}
  $codeInputs=[ordered]@{}
  $codeSources=[ordered]@{
    runner=$PSCommandPath
    matlab_task=(Join-Path $PSScriptRoot 'run_mass_filter_scan.m')
    comsol_builder=(Join-Path $projectRoot 'comsol\ms_rf_quadrupole_no_collision.m')
    contract_loader=(Join-Path $projectRoot 'load_rf_quadrupole_contract.m')
    case_preparer=(Join-Path $projectRoot 'analysis\prepare_comsol_mass_scan.py')
    result_analyzer=(Join-Path $projectRoot 'analysis\analyze_comsol_mass_scan.py')
    paired_mass_library=(Join-Path $repoRoot 'common\multipole\paired_mass_scan.py')
  }
  foreach($key in $codeSources.Keys){
    $extension=[IO.Path]::GetExtension($codeSources[$key]);$destination=Join-Path $inputDir "$key$extension.txt"
    Copy-Item -LiteralPath $codeSources[$key] -Destination $destination;$codeInputs[$key]=$destination
  }
  $l1Run=Join-Path $artifactRoot "runs\$L1RunId"
  $simionRun=Join-Path $artifactRoot "runs\$SimionRunId"
  foreach($sourceRun in @($l1Run,$simionRun)){
    & $package.python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') `
      (Join-Path $sourceRun 'run_manifest.json') --require-status success
    if($LASTEXITCODE-ne 0){throw "Source run manifest failed: $sourceRun"}
  }
  $l1Response=Join-Path $inputDir 'l1_mass_response.csv'
  $simionResponse=Join-Path $inputDir 'simion_mass_response.csv'
  Copy-Item -LiteralPath (Join-Path $l1Run 'results\mass-response__finite-length.csv') -Destination $l1Response
  Copy-Item -LiteralPath (Join-Path $simionRun 'results\mass-response__simion.csv') -Destination $simionResponse
  Copy-Item -LiteralPath (Join-Path $l1Run 'run_manifest.json') -Destination (Join-Path $inputDir 'l1_run_manifest.json')
  Copy-Item -LiteralPath (Join-Path $simionRun 'run_manifest.json') -Destination (Join-Path $inputDir 'simion_run_manifest.json')

  $caseTableDir=Join-Path $inputDir 'particle_cases'
  $caseMetadata=Join-Path $inputDir 'particle_cases.json'
  & $package.python -m projects.rf_quadrupole_collision_cooling.analysis.prepare_comsol_mass_scan `
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
      project='rf_quadrupole_collision_cooling';mode='mass_filter_reference';operating_point="mass_$token`_Th"
      inputs=[ordered]@{resolved_design=$sources.resolved_design;mode=$sources.mode;particle_table=[string]$case.particle_table}
      particle_table_path=[string]$case.particle_table;particles=[int]$case.particles
      results_dir=$caseResultDir;comsol_dir=$caseComsolDir;runtime_dir=$caseRuntimeDir
      comsol_rf_steps_per_period=$RfStepsPerPeriod;comsol_mesh_auto_level=$MeshAutoLevel
      source_axial_offset_mm=0.0;save_model=($mass-eq $centerMass);write_detailed_outputs=$false
    }
    Write-RfJson -Value $caseConfig -Path $caseConfigPath
    $cases+=,[ordered]@{mass_Th=$mass;run_config=$caseConfigPath;solver_summary=(Join-Path $caseResultDir 'solver_summary.json');particle_state=(Join-Path $caseResultDir 'particle_state.csv')}
  }
  Write-RfJson -Value ([ordered]@{schema_version=1;role='rf_quadrupole_comsol_mass_filter_scan_execution';cases=$cases}) -Path $scanConfig
  $runConfiguration=[ordered]@{
    schema_version=1;run_id=$RunId;project='rf_quadrupole_collision_cooling';mode='mass_filter_reference';project_root=$repoRoot
    inputs=[ordered]@{baseline=$sources.baseline;mode=$sources.mode;resolved_design=$sources.resolved_design;particle_cases=$caseMetadata;scan_execution=$scanConfig;l1_response=$l1Response;simion_response=$simionResponse;l1_run_manifest=(Join-Path $inputDir 'l1_run_manifest.json');simion_run_manifest=(Join-Path $inputDir 'simion_run_manifest.json');code=$codeInputs}
    parameters=[ordered]@{particles_per_mass=$particlesPerMass;masses=$massCount;total_particles=$totalParticles;rf_steps_per_period=$RfStepsPerPeriod;mesh_auto_level=$MeshAutoLevel;compact_outputs=$true;saved_model_mass_Th=$centerMass;lifecycle_stage='inputs_frozen'}
    formal_gate_passed=$false
  }
  Write-RfJson -Value $runConfiguration -Path $package.run_config

  $environment=Save-RfEnvironment -Names @('RFQUAD_SCAN_CONFIG','COMSOL_BOOTSTRAP_REPORT')
  try {
    $env:RFQUAD_SCAN_CONFIG=$scanConfig;$env:COMSOL_BOOTSTRAP_REPORT=$report
    & (Join-Path $repoRoot 'common\comsol\run_comsol_r2025b.ps1') `
      -TaskScript (Join-Path $PSScriptRoot 'run_mass_filter_scan.m') -ReportPath $report `
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
  $comparison=Join-Path $resultDir 'mass-response__l0-l1-simion-comsol.csv'
  $figure=Join-Path $resultDir 'mass-response__l0-l1-simion-comsol.png'
  & $package.python -m projects.rf_quadrupole_collision_cooling.analysis.analyze_comsol_mass_scan `
    --scan-config $scanConfig --baseline $sources.baseline --mode $sources.mode `
    --simion-response $simionResponse --l1-response $l1Response --response $response `
    --metrics $metrics --comparison $comparison --figure $figure
  if($LASTEXITCODE-ne 0){throw 'COMSOL mass-filter functional analysis failed.'}
  $metricDocument=Get-Content -LiteralPath $metrics -Raw -Encoding UTF8|ConvertFrom-Json
  Write-RfJson -Path $package.summary -Value ([ordered]@{
    schema_version=1;role='rf_quadrupole_comsol_mass_filter_summary';status='success';mode='mass_filter_reference'
    particles=$totalParticles;masses=$massCount;functional_gate=$metricDocument.status;response='results/mass-response__comsol.csv'
    comparison='results/mass-response__l0-l1-simion-comsol.csv';figure='results/mass-response__l0-l1-simion-comsol.png'
    claim_limit=$metricDocument.claim_limit
  })
  $runConfiguration.parameters.lifecycle_stage='complete';$runConfiguration.formal_gate_passed=($metricDocument.status-eq 'PASS')
  Write-RfJson -Value $runConfiguration -Path $package.run_config
  $outputs=@($report,$response,$metrics,$comparison,$figure,$package.summary)
  foreach($case in $cases){$outputs+=@($case.solver_summary,$case.particle_state)}
  $centerToken=('{0:g}' -f $centerMass).Replace('.','p')
  $centerModel=Join-Path $runDir "comsol\mass_$centerToken`_Th\rf_quadrupole_collision_cooling__model.mph"
  if(Test-Path -LiteralPath $centerModel -PathType Leaf){$outputs+=$centerModel}
  Write-RfRunManifest -Python $package.python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Status success -Software $software -Outputs $outputs
  "STATUS=PASS RUN_ID=$RunId FUNCTIONAL_GATE=$($metricDocument.status)"
} catch {
  Complete-RfFailedRun -Python $package.python -RepoRoot $repoRoot -RunConfig $package.run_config `
    -Summary $package.summary -SummaryRole 'rf_quadrupole_comsol_mass_filter_summary' -Reason $_.Exception.Message -Software $software
  throw
}
