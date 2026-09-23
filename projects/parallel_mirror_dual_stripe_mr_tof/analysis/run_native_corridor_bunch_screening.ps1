[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$WorkpointRunPath,
  [Parameter(Mandatory)][string]$NativeCorridorBankRunPath,
  [Parameter(Mandatory)][string]$BunchSourceReceiptPath,
  [string]$InitialPilotRunPath='',
  [string]$RecoveryPlanPath='',
  [switch]$RecoverTransport,
  [switch]$StopAfterPilot,
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$PythonExe=''
)

# Candidate continuation only.  It reuses one checkpointed native Fast Adjust
# family for the N=100 static pilot and N=1000 fixed-clock cohort; no PA is
# rebuilt, copied, Refined, or materialized by this workflow.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$workpointRun=(Resolve-Path -LiteralPath $WorkpointRunPath).Path
$bankRun=(Resolve-Path -LiteralPath $NativeCorridorBankRunPath).Path
$sourceReceipt=(Resolve-Path -LiteralPath $BunchSourceReceiptPath).Path
$initialPilotRun=if([string]::IsNullOrWhiteSpace($InitialPilotRunPath)){$null}else{(Resolve-Path -LiteralPath $InitialPilotRunPath).Path}
$resumeRecoveryPlan=if([string]::IsNullOrWhiteSpace($RecoveryPlanPath)){$null}else{(Resolve-Path -LiteralPath $RecoveryPlanPath).Path}
if([string]::IsNullOrWhiteSpace($RunId)){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__simion__mrtof-native-corridor-bunch-screening'}

. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1')
. (Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\native_corridor_runtime_support.ps1')

function Get-VerifiedManifestOutput {
  param([Parameter(Mandatory)][string]$ManifestPath,[Parameter(Mandatory)][string]$Name)
  $manifest=Get-Content -LiteralPath $ManifestPath -Raw|ConvertFrom-Json -Depth 40
  $records=@($manifest.outputs|Where-Object{[IO.Path]::GetFileName([string]$_.path)-eq$Name})
  if($records.Count-ne1){throw "Manifest must bind exactly one ${Name}: $ManifestPath"}
  $path=[IO.Path]::GetFullPath([string]$records[0].path)
  if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "Manifest output is missing: $path"}
  if((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash-ne([string]$records[0].sha256).ToUpperInvariant()){
    throw "Manifest output identity differs: $path"
  }
  return $path
}

function Get-DeclaredManifestOutputPath {
  param([Parameter(Mandatory)][string]$ManifestPath,[Parameter(Mandatory)][string]$Name)
  $manifest=Get-Content -LiteralPath $ManifestPath -Raw|ConvertFrom-Json -Depth 40
  $records=@($manifest.outputs|Where-Object{[IO.Path]::GetFileName([string]$_.path)-eq$Name})
  if($records.Count-ne1){throw "Manifest must declare exactly one ${Name}: $ManifestPath"}
  return [IO.Path]::GetFullPath([string]$records[0].path)
}

function Assert-VerifiedManifest {
  param([Parameter(Mandatory)][string]$ManifestPath,[Parameter(Mandatory)][string]$Status,[Parameter(Mandatory)][string]$Mode)
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $ManifestPath --require-status $Status --require-project $projectId --require-mode $Mode|Out-Host
  if($LASTEXITCODE-ne0){throw "Manifest verification failed: $ManifestPath"}
}

function Invoke-ProjectPython {
  param([Parameter(Mandatory)][string[]]$Arguments)
  Push-Location -LiteralPath $repoRoot
  $savedPythonPath=$env:PYTHONPATH
  try{
    $env:PYTHONPATH=$repoRoot
    & $python @Arguments
    if($LASTEXITCODE-ne0){throw "Python stage failed: $($Arguments -join ' ')"}
  }finally{
    $env:PYTHONPATH=$savedPythonPath
    Pop-Location
  }
}

function New-RecoveryCandidateRunId {
  param([Parameter(Mandatory)][string]$ParentRunId,[Parameter(Mandatory)][string]$Purpose)
  $token=($Purpose -replace '[^a-z0-9]+','-').Trim('-')
  if([string]::IsNullOrWhiteSpace($token)){throw 'Recovery candidate purpose cannot form a valid run-id token.'}
  $prefix='-recovery-';$available=96-$ParentRunId.Length-$prefix.Length
  if($available-lt10){throw 'Parent run id leaves no safe recovery candidate token space.'}
  if($token.Length-gt$available){
    $sha=[Security.Cryptography.SHA256]::Create()
    try{$digest=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($token))).Replace('-','').ToLowerInvariant()).Substring(0,8)}finally{$sha.Dispose()}
    $token=$token.Substring(0,$available-9).TrimEnd('-')+'-'+$digest
  }
  return $ParentRunId+$prefix+$token
}

function Invoke-BunchTransportRecoveryStage {
  param(
    [Parameter(Mandatory)][ValidateSet('theory','reverse_axis')][string]$Stage,
    [Parameter(Mandatory)][string]$PlanPath,
    [string]$ExistingPlanPath='',
    [Parameter(Mandatory)][string]$HandoffPath,
    [Parameter(Mandatory)][string]$TheorySummaryPath,
    [Parameter(Mandatory)][double[]]$AcceptedVoltages,
    [Parameter(Mandatory)][hashtable]$BaseTrialArguments,
    [Parameter(Mandatory)][string]$CandidateRunBase,
    [Parameter(Mandatory)][object]$Package
  )
  if($ExistingPlanPath){
    Copy-VerifiedRunInput -Source $ExistingPlanPath -Destination $PlanPath|Out-Null
  }else{
    Invoke-ProjectPython -Arguments @('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_transport_recovery','plan',
      '--workpoint',$HandoffPath,'--theory',$TheorySummaryPath,'--stage',$Stage,'--output',$PlanPath)
  }
  $planData=Get-Content -LiteralPath $PlanPath -Raw|ConvertFrom-Json -AsHashtable
  if([string]$planData.stage-ne$Stage){throw "Recovery plan stage differs from requested stage: $PlanPath"}
  $plannedAnchor=@($planData.accepted_anchor_voltages_v|ForEach-Object{[double]$_})
  if($plannedAnchor.Count-ne$AcceptedVoltages.Count-or@(0..3|Where-Object{[math]::Abs($plannedAnchor[$_]-$AcceptedVoltages[$_])-gt1e-12}).Count){
    throw 'Recovery plan anchor differs from the current accepted workpoint.'
  }
  $observationPaths=@();$probeManifests=@()
  foreach($candidate in @($planData.candidates)){
    $candidateVoltages=@($candidate.voltages_v|ForEach-Object{[double]$_})
    $candidateRunId=New-RecoveryCandidateRunId -ParentRunId $CandidateRunBase -Purpose ([string]$candidate.purpose)
    $candidateArguments=@{}
    foreach($key in $BaseTrialArguments.Keys){$candidateArguments[$key]=$BaseTrialArguments[$key]}
    $candidateArguments.Stripe1VoltageV=$candidateVoltages[0];$candidateArguments.Stripe2VoltageV=$candidateVoltages[1]
    $candidateArguments.Prism1VoltageV=$candidateVoltages[2];$candidateArguments.Prism2VoltageV=$candidateVoltages[3]
    $candidateArguments.RunId=$candidateRunId
    $candidateRun=Join-Path $artifactProjectRoot "runs\$candidateRunId";$candidateManifest=Join-Path $candidateRun 'run_manifest.json'
    if(-not(Test-Path -LiteralPath $candidateManifest -PathType Leaf)){& $trialRunner @candidateArguments}
    Assert-VerifiedManifest -ManifestPath $candidateManifest -Status 'success' -Mode 'finite_3d_two_prism_voltage_trial'
    $candidateObservation=Get-VerifiedManifestOutput -ManifestPath $candidateManifest -Name 'two_prism_trial_observation.json'
    $candidateObservationData=Get-Content -LiteralPath $candidateObservation -Raw|ConvertFrom-Json -AsHashtable
    $rankObservation=Join-Path $Package.result_dir ('bunch_transport_recovery_'+$Stage+'_'+[string]$candidate.purpose+'.json')
    Write-RunJson -Path $rankObservation -Depth 20 -Value ([ordered]@{stage=$Stage;purpose=[string]$candidate.purpose;cohort_analysis=$candidateObservationData.cohort_analysis;trial_manifest=$candidateManifest;observation=$candidateObservation})
    $observationPaths+=@($rankObservation);$probeManifests+=@($candidateManifest)
  }
  $selectionName=if($Stage-eq'theory'){'bunch_transport_recovery_selection.json'}else{'bunch_transport_recovery_reverse_axis_selection.json'}
  $selectionPath=Join-Path $Package.result_dir $selectionName
  $rankArguments=@('-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.bunch_transport_recovery','rank','--plan',$PlanPath,'--output',$selectionPath)
  foreach($path in $observationPaths){$rankArguments+=@('--observation',$path)}
  Invoke-ProjectPython -Arguments $rankArguments
  return [pscustomobject]@{stage=$Stage;plan_path=$PlanPath;selection_path=$selectionPath;observation_paths=@($observationPaths);probe_manifests=@($probeManifests);selection=(Get-Content -LiteralPath $selectionPath -Raw|ConvertFrom-Json -AsHashtable)}
}

$workpointManifest=Join-Path $workpointRun 'run_manifest.json'
$bankManifest=Join-Path $bankRun 'run_manifest.json'
$sourceRun=Split-Path -Parent (Split-Path -Parent $sourceReceipt)
$sourceManifest=Join-Path $sourceRun 'run_manifest.json'
$trialRunner=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\run_two_prism_trial.ps1'
$freezeRunner=Join-Path $PSScriptRoot 'run_freeze_bunch_pulse_schedule.ps1'
$artifactProjectRoot=Join-Path $workspaceRoot "artifacts\projects\$projectId"
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactProjectRoot `
  -RunId $RunId -Project $projectId -Mode 'native_corridor_candidate_bunch_screening' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled
$terminalized=$false;$failureStage='preflight';$capacitySession=$null;$nativeRuntimeSession=$null
$recoveryPlan=$null;$recoverySelection=$null;$recoveryObservationPaths=@();$recoveryProbeManifests=@();$recoveryStages=@()
try{
  $failureStage='verify_inputs'
  $handoff=Get-DeclaredManifestOutputPath -ManifestPath $workpointManifest -Name 'best_physical_workpoint_handoff.json'
  # A resumed workpoint can legitimately retain its family in its original
  # owner run.  Consume the manifest-declared checkpoint instead of assuming
  # a same-directory copy exists.
  $checkpoint=Get-DeclaredManifestOutputPath -ManifestPath $workpointManifest -Name 'native_corridor_runtime_checkpoint.json'
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $workpointManifest --require-status checkpoint --require-project $projectId --require-mode downstream_fixed_grid_workpoint_iteration `
    --consumer-projection-id mrtof_native_bunch_workpoint_consumer_v1 --consumed-output $handoff --consumed-output $checkpoint|Out-Host
  if($LASTEXITCODE-ne0){throw 'Workpoint handoff/checkpoint projection failed verification.'}
  $bankPublication=Join-Path $bankRun 'results\pa_family_cache_publication.json'
  & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $bankManifest --require-status success --require-project $projectId --require-mode native_corridor_detached_response_bank `
    --consumer-projection-id mrtof_native_bunch_bank_consumer_v1 --consumed-output $bankPublication|Out-Host
  if($LASTEXITCODE-ne0){throw 'Native bank publication projection failed verification.'}
  Assert-VerifiedManifest -ManifestPath $sourceManifest -Status 'success' -Mode 'deterministic_bunch_source_materialization'
  $handoff=Get-VerifiedManifestOutput -ManifestPath $workpointManifest -Name 'best_physical_workpoint_handoff.json'
  $checkpoint=Get-VerifiedManifestOutput -ManifestPath $workpointManifest -Name 'native_corridor_runtime_checkpoint.json'
  $handoffData=Get-Content -LiteralPath $handoff -Raw|ConvertFrom-Json -AsHashtable
  if($handoffData.role-ne'mrtof_best_physical_workpoint_handoff'-or$handoffData.status-notin@('success','warning') -or
     $handoffData.qualification-ne'candidate_bunch_screening_authorized'){
    throw 'Workpoint handoff does not authorize Candidate bunch screening.'
  }
  $voltages=@($handoffData.selected_workpoint.voltages_v|ForEach-Object{[double]$_})
  if($voltages.Count-ne4-or@($voltages|Where-Object{-not[double]::IsFinite($_)}).Count){throw 'Handoff voltage vector is invalid.'}
  $workpointConfig=Get-Content -LiteralPath (Join-Path $workpointRun 'run_config.json') -Raw|ConvertFrom-Json -AsHashtable
  $problem=$workpointConfig.parameters.native_recovery_problem
  if($null-eq$problem){throw 'Workpoint has no native physical-problem identity.'}
  if([string]::IsNullOrWhiteSpace([string]$problem.accelerator_provider_receipt)){
    throw 'Workpoint must bind an OA accelerator provider receipt.'
  }
  $providerReceipt=(Resolve-Path -LiteralPath ([string]$problem.accelerator_provider_receipt)).Path
  if([string]::IsNullOrWhiteSpace([string]$problem.native_system_runtime_bundle)){throw 'Workpoint has no native system runtime bundle identity.'}
  $nativeSystemRuntimeBundlePath=(Resolve-Path -LiteralPath ([string]$problem.native_system_runtime_bundle)).Path
  $sourceData=Get-Content -LiteralPath $sourceReceipt -Raw|ConvertFrom-Json -AsHashtable
  if([int]$sourceData.particle_count-ne1000){throw 'Candidate screening requires the frozen N=1000 mother cohort.'}
  $sourceReceiptBound=Get-VerifiedManifestOutput -ManifestPath $sourceManifest -Name 'bunch_source_receipt.json'
  if([IO.Path]::GetFullPath($sourceReceiptBound)-ne$sourceReceipt){throw 'Requested source receipt is not the source manifest receipt.'}

  $failureStage='capacity_startup'
  $capacitySession=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes 52428800 -ProtectedPaths @($package.artifact_run_dir,$workpointRun,$bankRun,$sourceRun,$nativeSystemRuntimeBundlePath) `
    -Owner "mrtof-native-corridor-bunch-screening:$RunId"
  $startup=Join-Path $package.result_dir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startup -Depth 20 -Value $capacitySession

  $failureStage='open_native_runtime'
  $bank=Get-Content -LiteralPath (Join-Path $bankRun 'results\pa_family_cache_publication.json') -Raw|ConvertFrom-Json -AsHashtable
  $checkpointData=Get-Content -LiteralPath $checkpoint -Raw|ConvertFrom-Json -AsHashtable
  $runtimeDirectory=[IO.Path]::GetFullPath([string]$checkpointData.directory)
  $runtimeOwner=Split-Path (Split-Path $runtimeDirectory -Parent) -Parent
  $nativeRuntimeSession=[pscustomobject]@{
    lease_id=$capacitySession.lease_id;directory=$runtimeDirectory;runtime=$null;resident_bytes=[int64]0
    owner_run_directory=$runtimeOwner;owner_run_config=(Join-Path $runtimeOwner 'run_config.json');checkpoint_path=$checkpoint
  }
  $runtimeSimion=if($SimionExe){$SimionExe}else{Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'}
  Open-NativeCorridorRuntimeCheckpoint -Session $nativeRuntimeSession -CapacityWorkflowSession $capacitySession `
    -BankGenerationDirectory $bank.generation_directory -CacheKey $bank.cache_key -GenerationSha256 $bank.generation_sha256 `
    -Python $python -RepoRoot $repoRoot -SimionExe $runtimeSimion

  $failureStage='pilot_n100'
  $pilotRunId=$RunId+'__n100-static'
  $pilotArguments=@{
    GeometryReviewRunPath=[string]$problem.geometry;MirrorRunPath=[string]$problem.mirror;StripeRunPath=[string]$problem.stripe
    NativeSystemRuntimeBundlePath=$nativeSystemRuntimeBundlePath
    NativeCorridorBankRunPath=$bankRun;NativeCorridorRuntimeSession=$nativeRuntimeSession;CapacityWorkflowSession=$capacitySession
    BunchSourceReceiptPath=$sourceReceipt;BunchParticleIdMin=1;BunchParticleIdMax=100
    Stripe1VoltageV=$voltages[0];Stripe2VoltageV=$voltages[1];Prism1VoltageV=$voltages[2];Prism2VoltageV=$voltages[3]
    TrajectoryProfileId=[string]$problem.trajectory_profile;TrajectoryStepScale=[double]$problem.trajectory_step_scale
    AcceleratorSourceYOffsetMm=[double]$problem.source_y_offset_mm;RunId=$pilotRunId;PythonExe=$python
  }
  $pilotArguments.AcceleratorProviderReceiptPath=$providerReceipt
  if($SimionExe){$pilotArguments.SimionExe=$SimionExe}
  if($null-ne$initialPilotRun){
    $pilotRun=$initialPilotRun;$pilotManifest=Join-Path $pilotRun 'run_manifest.json'
  }else{
    & $trialRunner @pilotArguments
    $pilotRun=Join-Path $artifactProjectRoot "runs\$pilotRunId";$pilotManifest=Join-Path $pilotRun 'run_manifest.json'
  }
  Assert-VerifiedManifest -ManifestPath $pilotManifest -Status 'success' -Mode 'finite_3d_two_prism_voltage_trial'
  $pilotGate=Get-VerifiedManifestOutput -ManifestPath $pilotManifest -Name 'bunch_collection_gate.json'
  $pilotReceipt=Get-VerifiedManifestOutput -ManifestPath $pilotManifest -Name 'two_prism_trial_materialization.json'
  $pilotLog=Get-VerifiedManifestOutput -ManifestPath $pilotManifest -Name 'native_two_prism_flight.log'
  $pilotGateData=Get-Content -LiteralPath $pilotGate -Raw|ConvertFrom-Json -AsHashtable
  if($null-ne$initialPilotRun){
    $pilotSummary=Get-Content -LiteralPath (Join-Path $pilotRun 'summary.json') -Raw|ConvertFrom-Json -AsHashtable
    if([int]$pilotSummary.source_particle_count-ne100-or
       [int]$pilotSummary.source_cohort.mother_particle_count-ne[int]$sourceData.particle_count-or
       [string]$pilotSummary.source_cohort.selection.parent_particle_states_sha256-ne[string]$sourceData.particle_states_sha256){
      throw 'Initial pilot does not bind the requested frozen N=1000 source prefix.'
    }
  }
  if([bool]$pilotGateData.hard_stop-and$RecoverTransport){
    # This is a bounded controller transition, not an operator-selected retry.
    # It uses the theory seed published by the Stripe input already bound to the
    # workpoint, holds P1/P2 fixed, and keeps the opened native family alive.
    $failureStage='plan_bunch_transport_recovery'
    $theoryManifest=Join-Path ([string]$problem.stripe) 'run_manifest.json'
    & $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') $theoryManifest --require-status success --require-project $projectId|Out-Host
    if($LASTEXITCODE-ne0){throw 'Theory Stripe seed manifest is not verified success.'}
    $theorySummary=Join-Path ([string]$problem.stripe) 'summary.json'
    if(-not(Test-Path -LiteralPath $theorySummary -PathType Leaf)){throw 'Theory Stripe seed summary is missing.'}
    $recoveryCandidateRunBase=$RunId
    $existingTheoryPlan=''
    if($null-ne$resumeRecoveryPlan){
      $priorRecoveryRun=Split-Path -Parent (Split-Path -Parent $resumeRecoveryPlan)
      $priorRecoveryManifest=Join-Path $priorRecoveryRun 'run_manifest.json'
      $verifiedPriorPlan=Get-VerifiedManifestOutput -ManifestPath $priorRecoveryManifest -Name 'bunch_transport_recovery_plan.json'
      if([IO.Path]::GetFullPath($verifiedPriorPlan)-ne$resumeRecoveryPlan){throw 'Requested recovery plan is not the prior manifest-bound recovery plan.'}
      $existingTheoryPlan=$resumeRecoveryPlan;$recoveryCandidateRunBase=Split-Path -Leaf $priorRecoveryRun
    }
    $failureStage='run_bunch_transport_recovery_probes'
    $failureStage='select_bunch_transport_recovery'
    $theoryStage=Invoke-BunchTransportRecoveryStage -Stage theory -PlanPath (Join-Path $package.result_dir 'bunch_transport_recovery_plan.json') -ExistingPlanPath $existingTheoryPlan `
      -HandoffPath $handoff -TheorySummaryPath $theorySummary -AcceptedVoltages $voltages -BaseTrialArguments $pilotArguments -CandidateRunBase $recoveryCandidateRunBase -Package $package
    $recoveryStages+=@($theoryStage);$recoveryPlan=$theoryStage.plan_path;$recoverySelection=$theoryStage.selection_path
    $recoveryObservationPaths+=@($theoryStage.observation_paths);$recoveryProbeManifests+=@($theoryStage.probe_manifests)
    $selectedRecovery=$theoryStage.selection
    if($selectedRecovery.status-ne'selected'){
      $failureStage='run_bunch_transport_reverse_axis_probes'
      $reverseStage=Invoke-BunchTransportRecoveryStage -Stage reverse_axis -PlanPath (Join-Path $package.result_dir 'bunch_transport_recovery_reverse_axis_plan.json') `
        -HandoffPath $handoff -TheorySummaryPath $theorySummary -AcceptedVoltages $voltages -BaseTrialArguments $pilotArguments -CandidateRunBase $recoveryCandidateRunBase -Package $package
      $recoveryStages+=@($reverseStage);$recoveryObservationPaths+=@($reverseStage.observation_paths);$recoveryProbeManifests+=@($reverseStage.probe_manifests)
      $selectedRecovery=$reverseStage.selection
    }
    if($selectedRecovery.status-eq'selected'){
      $voltages=@($selectedRecovery.selected.voltages_v|ForEach-Object{[double]$_})
      $pilotManifest=[string]$selectedRecovery.selected.observation.trial_manifest
      $pilotRun=Split-Path -Parent $pilotManifest
      $pilotGate=Get-VerifiedManifestOutput -ManifestPath $pilotManifest -Name 'bunch_collection_gate.json'
      $pilotReceipt=Get-VerifiedManifestOutput -ManifestPath $pilotManifest -Name 'two_prism_trial_materialization.json'
      $pilotLog=Get-VerifiedManifestOutput -ManifestPath $pilotManifest -Name 'native_two_prism_flight.log'
      $pilotGateData=Get-Content -LiteralPath $pilotGate -Raw|ConvertFrom-Json -AsHashtable
      Write-Host "MRTOF_BUNCH_TRANSPORT_RECOVERY=SELECTED PURPOSE=$($selectedRecovery.selected.purpose) RATE=$($selectedRecovery.selected.detection_rate)"
    }else{
      Write-Host 'MRTOF_BUNCH_TRANSPORT_RECOVERY=UNRECOVERABLE'
    }
  }
  if([bool]$pilotGateData.hard_stop){
    $result=Join-Path $package.result_dir 'bunch_screening_result.json'
    $recoveryStageEvidence=@($recoveryStages|ForEach-Object{[ordered]@{stage=$_.stage;plan_path=$_.plan_path;selection_path=$_.selection_path;observation_paths=@($_.observation_paths);probe_manifests=@($_.probe_manifests)}})
    Write-RunJson -Path $result -Depth 20 -Value ([ordered]@{schema_version=1;role='mrtof_native_corridor_bunch_screening';status='hard_stop';pilot_run_manifest=$pilotManifest;pilot_collection_gate=$pilotGate;recovery_requested=[bool]$RecoverTransport;recovery_plan=$(if($RecoverTransport){$recoveryPlan}else{$null});recovery_selection=$(if($RecoverTransport){$recoverySelection}else{$null});recovery_stages=$recoveryStageEvidence;recovery_probe_manifests=$(if($RecoverTransport){@($recoveryProbeManifests)}else{@()});next_action='stop_below_collection_hard_minimum'})
    Write-RunJson -Path $package.summary -Depth 20 -Value ([ordered]@{schema_version=1;role='mrtof_native_corridor_bunch_screening_summary';status='hard_stop';pilot_collection_gate=$pilotGateData;reason='N100 collection or event integrity did not meet the hard continuation gate.'})
    $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession -RemainingCommittedNewBytes 0
    $capacitySession=$terminal.session;$terminalPath=Join-Path $package.result_dir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
    $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
    $hardStopOutputs=@($package.summary,$result,$startup,$terminalPath,$retention)
    foreach($stageResult in $recoveryStages){foreach($path in @($stageResult.plan_path,$stageResult.selection_path)+@($stageResult.observation_paths)){if($null-ne$path-and(Test-Path -LiteralPath $path -PathType Leaf)){$hardStopOutputs+=@($path)}}}
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $hardStopOutputs
    $terminalized=$true;Write-Host "MRTOF_NATIVE_BUNCH_SCREENING=HARD_STOP RUN_ID=$RunId";return
  }

  if($StopAfterPilot){
    $failureStage='publish_pilot_only'
    $result=Join-Path $package.result_dir 'bunch_screening_result.json'
    Write-RunJson -Path $result -Depth 20 -Value ([ordered]@{
      schema_version=1;role='mrtof_native_corridor_bunch_screening';status='pilot_complete'
      pa_reuse='one_checkpointed_native_fast_adjust_family__no_pa_copy_or_refine'
      pilot_run_manifest=$pilotManifest;pilot_collection_gate=$pilotGate
      next_action='paused_before_global_pulse_freeze_and_n1000_at_user_request'
    })
    Write-RunJson -Path $package.summary -Depth 20 -Value ([ordered]@{
      schema_version=1;role='mrtof_native_corridor_bunch_screening_summary';status='pilot_complete'
      pilot_collection_gate=$pilotGateData;pa_reuse='shared_checkpointed_native_runtime'
    })
    $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
    $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession -RemainingCommittedNewBytes 0
    $capacitySession=$terminal.session;$terminalPath=Join-Path $package.result_dir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
    Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success -Software @('SIMION 2020','Python 3.11') -Outputs @($package.summary,$result,$startup,$terminalPath,$retention)
    $terminalized=$true;Write-Host "MRTOF_NATIVE_BUNCH_SCREENING=PILOT_COMPLETE RUN_ID=$RunId";return
  }

  $failureStage='freeze_global_pulse'
  $pilotData=Get-Content -LiteralPath $pilotReceipt -Raw|ConvertFrom-Json -AsHashtable
  $guardUs=[double]$pilotData.trajectory_profile.maximum_step_us
  if(-not[double]::IsFinite($guardUs)-or$guardUs-le0){throw 'Pilot maximum trajectory step is invalid for automatic global-pulse guard.'}
  $scheduleRunId=$RunId+'__pulse-schedule'
  & $freezeRunner -BunchSourceRunManifest $sourceManifest -StaticPilotRunManifest $pilotManifest `
    -PilotTrialReceiptPath $pilotReceipt -PilotLogPath $pilotLog -GuardUs $guardUs -RunId $scheduleRunId -PythonExe $python
  $scheduleRun=Join-Path $artifactProjectRoot "runs\$scheduleRunId";$scheduleManifest=Join-Path $scheduleRun 'run_manifest.json'
  Assert-VerifiedManifest -ManifestPath $scheduleManifest -Status 'success' -Mode 'bunch_global_pulse_schedule_freeze'
  $schedule=Get-VerifiedManifestOutput -ManifestPath $scheduleManifest -Name 'bunch_global_pulse_schedule.json'

  $failureStage='cohort_n1000'
  $cohortRunId=$RunId+'__n1000-fixed-clock'
  $cohortArguments=@{
    GeometryReviewRunPath=[string]$problem.geometry;MirrorRunPath=[string]$problem.mirror;StripeRunPath=[string]$problem.stripe
    NativeSystemRuntimeBundlePath=$nativeSystemRuntimeBundlePath
    NativeCorridorBankRunPath=$bankRun;NativeCorridorRuntimeSession=$nativeRuntimeSession;CapacityWorkflowSession=$capacitySession
    BunchSourceReceiptPath=$sourceReceipt;AcceleratorPulseSchedulePath=$schedule
    Stripe1VoltageV=$voltages[0];Stripe2VoltageV=$voltages[1];Prism1VoltageV=$voltages[2];Prism2VoltageV=$voltages[3]
    TrajectoryProfileId=[string]$problem.trajectory_profile;TrajectoryStepScale=[double]$problem.trajectory_step_scale
    AcceleratorSourceYOffsetMm=[double]$problem.source_y_offset_mm;RunId=$cohortRunId;PythonExe=$python
  }
  $cohortArguments.AcceleratorProviderReceiptPath=$providerReceipt
  if($SimionExe){$cohortArguments.SimionExe=$SimionExe}
  & $trialRunner @cohortArguments
  $cohortRun=Join-Path $artifactProjectRoot "runs\$cohortRunId";$cohortManifest=Join-Path $cohortRun 'run_manifest.json'
  Assert-VerifiedManifest -ManifestPath $cohortManifest -Status 'success' -Mode 'finite_3d_two_prism_voltage_trial'
  $cohortGate=Get-VerifiedManifestOutput -ManifestPath $cohortManifest -Name 'bunch_collection_gate.json'
  $cohortGateData=Get-Content -LiteralPath $cohortGate -Raw|ConvertFrom-Json -AsHashtable

  $failureStage='publish'
  $result=Join-Path $package.result_dir 'bunch_screening_result.json'
  Write-RunJson -Path $result -Depth 20 -Value ([ordered]@{
    schema_version=1;role='mrtof_native_corridor_bunch_screening';status=$(if([bool]$cohortGateData.hard_stop){'hard_stop'}else{'complete'})
    pa_reuse='one_checkpointed_native_fast_adjust_family__no_pa_copy_or_refine';pilot_run_manifest=$pilotManifest
    pilot_collection_gate=$pilotGate;schedule_run_manifest=$scheduleManifest;schedule=$schedule
    recovery_stages=@($recoveryStages|ForEach-Object{[ordered]@{stage=$_.stage;plan_path=$_.plan_path;selection_path=$_.selection_path;observation_paths=@($_.observation_paths);probe_manifests=@($_.probe_manifests)}})
    cohort_run_manifest=$cohortManifest;cohort_collection_gate=$cohortGate
    next_action=$(if([bool]$cohortGateData.hard_stop){'stop_below_collection_hard_minimum'}else{'analyze_complete_n1000_candidate_resolution'})
  })
  Write-RunJson -Path $package.summary -Depth 20 -Value ([ordered]@{schema_version=1;role='mrtof_native_corridor_bunch_screening_summary';status='success';pilot_collection_gate=$pilotGateData;cohort_collection_gate=$cohortGateData;pa_reuse='shared_checkpointed_native_runtime'})
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession -RemainingCommittedNewBytes 0
  $capacitySession=$terminal.session;$terminalPath=Join-Path $package.result_dir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $completeOutputs=@($package.summary,$result,$startup,$terminalPath,$retention)
  foreach($stageResult in $recoveryStages){foreach($path in @($stageResult.plan_path,$stageResult.selection_path)+@($stageResult.observation_paths)){if($null-ne$path-and(Test-Path -LiteralPath $path -PathType Leaf)){$completeOutputs+=@($path)}}}
  Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success -Software @('SIMION 2020','Python 3.11') -Outputs $completeOutputs
  $terminalized=$true;Write-Host "MRTOF_NATIVE_BUNCH_SCREENING=PASS RUN_ID=$RunId"
}catch{
  if(-not$terminalized){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary -SummaryRole 'mrtof_native_corridor_bunch_screening_summary' -Reason $_.Exception.Message -Software @('SIMION 2020','Python 3.11') -Status failed -FailureStage $failureStage;$terminalized=$true}
  throw
}finally{
  if($null-ne$nativeRuntimeSession){Suspend-NativeCorridorRuntimeSession -Session $nativeRuntimeSession}
  if(-not$terminalized-and(Test-Path -LiteralPath $package.run_config)){Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary -SummaryRole 'mrtof_native_corridor_bunch_screening_summary' -Reason 'Native corridor bunch screening stopped before terminal publication.' -Software @('SIMION 2020','Python 3.11') -Status interrupted -FailureStage $failureStage}
  if($null-ne$capacitySession){$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession}
}
