[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$R26RunPath,
  [Parameter(Mandatory)][string]$R27RunPath,
  [Parameter(Mandatory)][string]$R28RunPath,
  [Parameter(Mandatory)][string]$R29RunPath,
  [Parameter(Mandatory)][ValidateRange(1e-12,1e6)][double]$DeltaVoltageV,
  [Parameter(Mandatory)][ValidateNotNullOrEmpty()][string]$MemberRunIdPrefix,
  [switch]$ReuseSuccessfulChildren,
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$PythonExe=''
)

Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Format-InvariantNumber([double]$Value){
  [string]::Format([Globalization.CultureInfo]::InvariantCulture,'{0:R}',$Value)
}
function Invoke-ProjectPython([string[]]$Arguments){
  Push-Location -LiteralPath $repoRoot
  try{
    $saved=$env:PYTHONPATH;$env:PYTHONPATH=$repoRoot
    & $python @Arguments
    if($LASTEXITCODE-ne0){throw "Python command failed: $($Arguments-join' ')"}
  }finally{$env:PYTHONPATH=$saved;Pop-Location}
}
function Assert-SuccessRun([string]$RunPath,[string]$Mode,[string]$Label){
  $root=(Resolve-Path -LiteralPath $RunPath).Path
  $manifest=Join-Path $root 'run_manifest.json'
  $verification=@(& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $manifest `
    --require-status success --require-project $projectId --require-mode $Mode)
  $verificationExitCode=$LASTEXITCODE
  foreach($line in $verification){Write-Host $line}
  if($verificationExitCode-ne0){throw "$Label manifest verification failed."}
  return $manifest
}
function Assert-PrewarmIdentity([string]$RunPath,[double[]]$ExpectedVoltages,[string]$ExpectedWorkbenchManifest){
  $configuration=Get-Content -Raw -LiteralPath (Join-Path $RunPath 'run_config.json')|ConvertFrom-Json -Depth 30
  $actual=@($configuration.parameters.target_voltage_vector_v)
  if($actual.Count-ne$ExpectedVoltages.Count){throw 'Reusable prewarm voltage-vector length differs from the planned state.'}
  for($index=0;$index-lt$actual.Count;$index++){
    if([Math]::Abs(([double]$actual[$index])-$ExpectedVoltages[$index])-gt1e-12){
      throw "Reusable prewarm voltage vector differs at index $index."
    }
  }
  if([IO.Path]::GetFullPath([string]$configuration.inputs.local_workbench_run_manifest)-ne
     [IO.Path]::GetFullPath($ExpectedWorkbenchManifest)){
    throw 'Reusable prewarm belongs to a different local workbench.'
  }
}
function Save-CampaignConfig {
  $configuration=Get-Content -Raw -LiteralPath $runConfig|ConvertFrom-Json -AsHashtable
  $configuration.inputs=[ordered]@{
    r26_run_manifest=$baselineManifests.r26
    r27_run_manifest=$baselineManifests.r27
    r28_run_manifest=$baselineManifests.r28
    r29_run_manifest=$baselineManifests.r29
    sensitivity_definition=$definitionPath
  }
  for($index=0;$index-lt$prewarmManifests.Count;$index++){
    $configuration.inputs[("prewarm_{0:D2}_run_manifest"-f($index+1))]=$prewarmManifests[$index]
  }
  for($index=0;$index-lt$memberManifests.Count;$index++){
    $configuration.inputs[("member_{0:D2}_run_manifest"-f($index+1))]=$memberManifests[$index]
  }
  $configuration.parameters=[ordered]@{
    delta_voltage_v=$DeltaVoltageV
    member_run_id_prefix=$MemberRunIdPrefix
    planned_perturbation_state_count=4
    planned_member_flight_count=8
    completed_prewarm_count=$prewarmManifests.Count
    completed_member_flight_count=$memberManifests.Count
    reused_prewarm_count=$reusedPrewarmCount
    reused_member_flight_count=$reusedMemberCount
    execution_order='freeze_plan__four_state_prewarm__eight_planned_members__analysis'
    resource_policy='delegated_to_existing_managed_entries__no_campaign_worker_override'
    lifecycle_stage=if($memberManifests.Count-eq8){'analysis'}else{'member_execution'}
  }
  Write-RunJson -Path $runConfig -Depth 20 -Value $configuration
}

$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$simion=if($SimionExe){[IO.Path]::GetFullPath($SimionExe)}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
foreach($path in @($python,$simion)){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Executable is missing: $path"}}
$pwshExe=(Get-Process -Id $PID).Path
$baselineRuns=[ordered]@{
  r26=(Resolve-Path -LiteralPath $R26RunPath).Path
  r27=(Resolve-Path -LiteralPath $R27RunPath).Path
  r28=(Resolve-Path -LiteralPath $R28RunPath).Path
  r29=(Resolve-Path -LiteralPath $R29RunPath).Path
}
$baselineManifests=[ordered]@{}
foreach($name in @('r26','r27','r28','r29')){
  $baselineManifests[$name]=Assert-SuccessRun -RunPath $baselineRuns[$name] `
    -Mode finite_3d_two_prism_voltage_trial -Label $name
}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=$MemberRunIdPrefix+'-campaign'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
$artifactRoot=Join-Path $workspaceRoot "artifacts\projects\$projectId"
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
  -RunId $RunId -Project $projectId -Mode 'stripe_return_sensitivity_campaign' `
  -Software @('Python 3.11','SIMION 2020') -RetentionContractEnabled -RetentionClass compact
$runDir=$package.run_dir;$inputDir=$package.input_dir;$resultDir=$package.result_dir
$runConfig=$package.run_config;$summary=$package.summary
$definitionPath=Join-Path $inputDir 'stripe_return_sensitivity_definition.json'
$planPath=Join-Path $resultDir 'stripe_return_sensitivity_plan.json'
$analysisPath=Join-Path $resultDir 'stripe_return_sensitivity_analysis.json'
$terminalized=$false;$failureStage='freeze_definition';$prewarmManifests=@();$memberManifests=@()
$reusedPrewarmCount=0;$reusedMemberCount=0
try{
  Write-RunJson -Path $definitionPath -Depth 10 -Value ([ordered]@{
    schema_version=1
    role='mrtof_stripe_return_sensitivity_definition'
    delta_voltage_v=$DeltaVoltageV
    member_run_id_prefix=$MemberRunIdPrefix
    baseline_runs=$baselineRuns
  })
  $trialRunner=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\run_two_prism_trial.ps1'
  $prewarmRunner=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\run_local_operating_pa_prewarm.ps1'
  $failureStage='generate_frozen_plan'
  Invoke-ProjectPython -Arguments @(
    '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.stripe_return_sensitivity','plan',
    '--definition',$definitionPath,'--runner',$trialRunner,'--output',$planPath
  )|Out-Null
  $plan=Get-Content -Raw -LiteralPath $planPath|ConvertFrom-Json -Depth 40
  $perturbedStates=@($plan.states|Where-Object{$_.state-ne'baseline'})
  if($perturbedStates.Count-ne4-or@($plan.tasks).Count-ne8){throw 'Sensitivity plan must contain four perturbation states and eight member flights.'}
  $localWorkbenchManifest=[string]$plan.frozen.local_workbench_run_manifest
  $localWorkbench=Split-Path -Parent $localWorkbenchManifest
  $p1=[double]$plan.frozen.prism_voltages_v[0];$p2=[double]$plan.frozen.prism_voltages_v[1]
  Save-CampaignConfig
  foreach($state in $perturbedStates){
    $failureStage="prewarm_$($state.state)"
    $stateToken=([string]$state.state).Replace('_','-')
    $prewarmRunId="$MemberRunIdPrefix-prewarm-$stateToken"
    $prewarmPath=Join-Path $artifactRoot "runs\$prewarmRunId"
    if($ReuseSuccessfulChildren-and(Test-Path -LiteralPath (Join-Path $prewarmPath 'run_manifest.json') -PathType Leaf)){
      $expectedVoltages=[double[]]@([double]$state.stripe_biases_v[0],[double]$state.stripe_biases_v[1],$p1,$p2)
      Assert-PrewarmIdentity -RunPath $prewarmPath -ExpectedVoltages $expectedVoltages `
        -ExpectedWorkbenchManifest $localWorkbenchManifest
      $reusedPrewarmCount++
    }else{
      $arguments=@(
        '-NoLogo','-NoProfile','-NonInteractive','-File',$prewarmRunner,
        '-LocalWorkbenchRunPath',$localWorkbench,
        '-Stripe1VoltageV',(Format-InvariantNumber ([double]$state.stripe_biases_v[0])),
        '-Stripe2VoltageV',(Format-InvariantNumber ([double]$state.stripe_biases_v[1])),
        '-Prism1VoltageV',(Format-InvariantNumber $p1),'-Prism2VoltageV',(Format-InvariantNumber $p2),
        '-RunId',$prewarmRunId,'-SimionExe',$simion,'-PythonExe',$python
      )
      & $pwshExe @arguments
      if($LASTEXITCODE-ne0){throw "Local operating PA prewarm failed: $($state.state)"}
    }
    $prewarmManifests+=Assert-SuccessRun -RunPath $prewarmPath -Mode local_operating_pa_cache_prewarm -Label "prewarm $($state.state)"
    Save-CampaignConfig
  }
  foreach($task in @($plan.tasks)){
    $failureStage="member_$($task.run_id)"
    $argv=@($task.argv)
    if($argv.Count-lt4-or[string]$argv[0]-ne'pwsh'-or[string]$argv[2]-ne'-File'-or
       [IO.Path]::GetFullPath([string]$argv[3])-ne[IO.Path]::GetFullPath($trialRunner)){
      throw "Planned member command does not call the authoritative trial runner: $($task.run_id)"
    }
    $memberPath=Join-Path (Split-Path -Parent $baselineRuns.r27) ([string]$task.run_id)
    if($ReuseSuccessfulChildren-and(Test-Path -LiteralPath (Join-Path $memberPath 'run_manifest.json') -PathType Leaf)){
      $reusedMemberCount++
    }else{
      $memberArguments=@($argv[1..($argv.Count-1)])+@('-SimionExe',$simion,'-PythonExe',$python)
      & $pwshExe @memberArguments
      if($LASTEXITCODE-ne0){throw "Sensitivity member flight failed: $($task.run_id)"}
    }
    $memberManifests+=Assert-SuccessRun -RunPath $memberPath -Mode finite_3d_two_prism_voltage_trial -Label ([string]$task.run_id)
    Save-CampaignConfig
  }
  $failureStage='analyze_complete_campaign'
  Invoke-ProjectPython -Arguments @(
    '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.stripe_return_sensitivity','analyze',
    '--plan',$planPath,'--output',$analysisPath
  )|Out-Null
  $analysis=Get-Content -Raw -LiteralPath $analysisPath|ConvertFrom-Json -Depth 40
  if($analysis.status-ne'complete'-or$analysis.role-ne'mrtof_stripe_return_sensitivity_analysis'){
    throw 'Stripe return sensitivity analysis did not publish a complete diagnostic.'
  }
  Save-CampaignConfig
  $configuration=Get-Content -Raw -LiteralPath $runConfig|ConvertFrom-Json -AsHashtable
  $configuration.parameters.lifecycle_stage='terminal'
  Write-RunJson -Path $runConfig -Depth 20 -Value $configuration
  Write-RunJson -Path $summary -Depth 15 -Value ([ordered]@{
    schema_version=1;role='mrtof_stripe_return_sensitivity_campaign';status='success';
    perturbation_state_count=4;member_flight_count=8;baseline_run_count=1;baseline_observation_cohort_count=2;
    prewarm_run_count=4;reused_prewarm_count=$reusedPrewarmCount;reused_member_flight_count=$reusedMemberCount;
    analysis_status=[string]$analysis.status;
    qualification='diagnostic_only__not_an_operating_point'
  })
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $runConfig
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Status success `
    -Software @('Python 3.11','SIMION 2020') -Outputs @($summary,$planPath,$analysisPath,$retention)|Out-Null
  $terminalized=$true
  Write-Host "MRTOF_STRIPE_RETURN_SENSITIVITY_CAMPAIGN=PASS RUN_ID=$RunId MEMBERS=8 PREWARMS=4"
}catch{
  try{Save-CampaignConfig}catch{}
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $runConfig -Summary $summary `
    -SummaryRole 'mrtof_stripe_return_sensitivity_campaign' -Reason $_.Exception.Message `
    -Software @('Python 3.11','SIMION 2020') -FailureStage $failureStage;$terminalized=$true}
  throw
}
