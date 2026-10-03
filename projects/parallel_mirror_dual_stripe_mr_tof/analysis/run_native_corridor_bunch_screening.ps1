[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$WorkpointRunPath,
  [Parameter(Mandatory)][string]$NativeCorridorBankRunPath,
  [Parameter(Mandatory)][string]$BunchSourceReceiptPath,
  [string]$MirrorVoltageVariationPath='',
  [string]$InitialCohortRunPath='',
  [string]$CohortBatchContinuationRunPath='',
  [ValidateSet(3,13,100,1000)][int]$CohortParticleCount=1000,
  [switch]$FocusDiagnosticOnly,
  [ValidateSet('','focus_z','slow_energy','controlled_aberration')][string]$DiagnosticPurpose='',
  [Nullable[double]]$TrajectoryStepScaleOverride=$null,
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$PythonExe=''
)

# Candidate continuation only.  It runs one static cohort from the checkpointed
# native Fast Adjust family; no PA is rebuilt, copied, Refined, or materialized.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$projectId='parallel_mirror_dual_stripe_mr_tof'
$repoRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
$python=if($PythonExe){[IO.Path]::GetFullPath($PythonExe)}else{Join-Path $repoRoot '.venv\Scripts\python.exe'}
$workpointRun=(Resolve-Path -LiteralPath $WorkpointRunPath).Path
$bankRun=(Resolve-Path -LiteralPath $NativeCorridorBankRunPath).Path
$sourceReceipt=(Resolve-Path -LiteralPath $BunchSourceReceiptPath).Path
$mirrorVoltageVariation=if([string]::IsNullOrWhiteSpace($MirrorVoltageVariationPath)){$null}else{(Resolve-Path -LiteralPath $MirrorVoltageVariationPath).Path}
$initialCohortRun=if([string]::IsNullOrWhiteSpace($InitialCohortRunPath)){$null}else{(Resolve-Path -LiteralPath $InitialCohortRunPath).Path}
if($null-ne$initialCohortRun-and$null-ne$mirrorVoltageVariation){throw 'An existing static cohort cannot be rebound to a new mirror-voltage variation.'}
if($FocusDiagnosticOnly){
  if($DiagnosticPurpose-and$DiagnosticPurpose-ne'focus_z'){
    throw 'FocusDiagnosticOnly cannot be combined with a different DiagnosticPurpose.'
  }
  $DiagnosticPurpose='focus_z'
}
$diagnosticOnly=-not[string]::IsNullOrWhiteSpace($DiagnosticPurpose)
$trajectoryStepScale=if($null-eq$TrajectoryStepScaleOverride){$null}else{[double]$TrajectoryStepScaleOverride}
if($null-ne$trajectoryStepScale-and(-not[double]::IsFinite($trajectoryStepScale)-or$trajectoryStepScale-le0-or$trajectoryStepScale-gt1)){
  throw 'TrajectoryStepScaleOverride must be in (0,1].'
}
$requiredDiagnosticCount = if($DiagnosticPurpose -eq 'controlled_aberration'){13}elseif($diagnosticOnly){3}else{0}
if(($requiredDiagnosticCount -eq 0 -and $CohortParticleCount -notin @(100,1000))-or
   ($requiredDiagnosticCount -ne 0 -and $CohortParticleCount -ne $requiredDiagnosticCount)){
  throw 'DiagnosticPurpose requires its controlled cohort size: focus_z/slow_energy use N=3 and controlled_aberration uses N=13.'
}
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

function New-CohortRunId {
  if($RunId-notmatch'^(?<stamp>\d{8}_\d{6})__(?:sim|analysis)__(?:simion|python)__(?<subject>[a-z0-9]+(?:-[a-z0-9]+)*)(?:__[a-z0-9]+(?:-[a-z0-9]+)*)?(?:__r\d{2})?$'){
    throw 'Screening run_id cannot derive a cohort identity.'
  }
  $stamp=[string]$Matches.stamp;$subject=[string]$Matches.subject
  $revision=if($RunId-match'__r(?<retry>\d{2})$'){"__r$($Matches.retry)"}else{''}
  return "$stamp`__sim`__simion`__$subject-n$CohortParticleCount-static$revision"
}

$workpointManifest=Join-Path $workpointRun 'run_manifest.json'
$bankManifest=Join-Path $bankRun 'run_manifest.json'
$sourceRun=Split-Path -Parent (Split-Path -Parent $sourceReceipt)
$sourceManifest=Join-Path $sourceRun 'run_manifest.json'
$trialRunner=Join-Path $repoRoot 'projects\parallel_mirror_dual_stripe_mr_tof\simion\run_two_prism_trial.ps1'
$artifactProjectRoot=Join-Path $workspaceRoot "artifacts\projects\$projectId"
$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactProjectRoot `
  -RunId $RunId -Project $projectId -Mode 'native_corridor_candidate_bunch_screening' `
  -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass compact `
  -CapacityLedgerLifecycleEnabled
$terminalized=$false;$failureStage='preflight';$capacitySession=$null;$nativeRuntimeSession=$null
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
  if($handoffData.status-ne'within_tolerance'){
    $history=Get-VerifiedManifestOutput -ManifestPath $workpointManifest -Name 'iteration_history.json'
    $handoff=Join-Path $package.input_dir 'qualified_workpoint_handoff.json'
    Invoke-ProjectPython -Arguments @(
      '-m','projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration',
      '--select-best-physical-workpoint','--history',$history,'--output',$handoff
    )
    $handoffData=Get-Content -LiteralPath $handoff -Raw|ConvertFrom-Json -AsHashtable
  }
  if($handoffData.role-ne'mrtof_best_physical_workpoint_handoff'-or$handoffData.status-ne'within_tolerance' -or
     $handoffData.qualification-ne'candidate_bunch_screening_authorized'){
    throw 'Workpoint handoff does not authorize Candidate bunch screening.'
  }
  $voltages=@($handoffData.selected_workpoint.voltages_v|ForEach-Object{[double]$_})
  if($voltages.Count-ne4-or@($voltages|Where-Object{-not[double]::IsFinite($_)}).Count){throw 'Handoff voltage vector is invalid.'}
  $workpointConfig=Get-Content -LiteralPath (Join-Path $workpointRun 'run_config.json') -Raw|ConvertFrom-Json -AsHashtable
  $problem=$workpointConfig.parameters.native_recovery_problem
  if($null-eq$problem){throw 'Workpoint has no native physical-problem identity.'}
  if($null-eq$mirrorVoltageVariation-and$workpointConfig.inputs.ContainsKey('terminal_time_mirror_voltage_variation')){
    $inheritedMirrorVariation=[string]$workpointConfig.inputs.terminal_time_mirror_voltage_variation
    if(-not[string]::IsNullOrWhiteSpace($inheritedMirrorVariation)){
      $mirrorVoltageVariation=(Resolve-Path -LiteralPath $inheritedMirrorVariation).Path
    }
  }
  if([string]::IsNullOrWhiteSpace([string]$problem.accelerator_provider_receipt)){
    throw 'Workpoint must bind an OA accelerator provider receipt.'
  }
  $providerReceipt=(Resolve-Path -LiteralPath ([string]$problem.accelerator_provider_receipt)).Path
  if([string]::IsNullOrWhiteSpace([string]$problem.native_system_runtime_bundle)){throw 'Workpoint has no native system runtime bundle identity.'}
  $nativeSystemRuntimeBundlePath=(Resolve-Path -LiteralPath ([string]$problem.native_system_runtime_bundle)).Path
  $workpointContract=(Resolve-Path -LiteralPath (Join-Path $workpointRun 'inputs\contract.json')).Path
  if((Get-FileHash -LiteralPath $workpointContract -Algorithm SHA256).Hash-ne[string]$problem.contract_sha256){
    throw 'Workpoint frozen contract identity differs from its physical-problem identity.'
  }
  $sourceData=Get-Content -LiteralPath $sourceReceipt -Raw|ConvertFrom-Json -AsHashtable
  if([int]$sourceData.particle_count-lt$CohortParticleCount){throw 'Candidate screening source is smaller than the requested cohort.'}
  $expectedCohortRole=if($diagnosticOnly){'controlled_diagnostic'}else{'formal_volume'}
  if([string]$sourceData.cohort_role-ne$expectedCohortRole){
    throw "Candidate screening requires a $expectedCohortRole source."
  }
  $contractData=Get-Content -LiteralPath $workpointContract -Raw|ConvertFrom-Json -AsHashtable
  $expectedSourceY=[double]$contractData.accelerator.focus_y_anchor.project_y_mm+[double]$sourceData.source_y_offset_mm
  $sourceCenterY=[double]$sourceData.nominal_center_state.position_workbench_mm[1]
  if([math]::Abs($sourceCenterY-$expectedSourceY)-gt1e-9){
    throw 'Candidate screening source centre does not match the workpoint accelerator y pose.'
  }
  $sourceReceiptBound=Get-VerifiedManifestOutput -ManifestPath $sourceManifest -Name 'bunch_source_receipt.json'
  if([IO.Path]::GetFullPath($sourceReceiptBound)-ne$sourceReceipt){throw 'Requested source receipt is not the source manifest receipt.'}

  $failureStage='capacity_startup'
  $capacitySession=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot `
    -ArtifactRoot (Join-Path $workspaceRoot 'artifacts') -RunDirectory $package.artifact_run_dir `
    -CommittedNewBytes 52428800 -ProtectedPaths @($package.artifact_run_dir,$workpointRun,$bankRun,$sourceRun,$nativeSystemRuntimeBundlePath) `
    -Owner "mrtof-native-corridor-bunch-screening:$RunId"
  $startup=Join-Path $package.result_dir 'artifact_capacity_gate_startup.json';Write-RunJson -Path $startup -Depth 20 -Value $capacitySession

  $failureStage="cohort_n$CohortParticleCount"
  $cohortRunId=New-CohortRunId
  $cohortArguments=@{
    GeometryReviewRunPath=[string]$problem.geometry;MirrorRunPath=[string]$problem.mirror;StripeRunPath=[string]$problem.stripe
    NativeSystemRuntimeBundlePath=$nativeSystemRuntimeBundlePath
    NativeCorridorBankRunPath=$bankRun;CapacityWorkflowSession=$capacitySession
    BunchSourceReceiptPath=$sourceReceipt;BunchParticleIdMin=1;BunchParticleIdMax=$CohortParticleCount;ContractPath=$workpointContract
    RetainGuiWorkbench=$true
    Stripe1VoltageV=$voltages[0];Stripe2VoltageV=$voltages[1];Prism1VoltageV=$voltages[2];Prism2VoltageV=$voltages[3]
    TrajectoryProfileId=[string]$problem.trajectory_profile;TrajectoryStepScale=$(if($null-eq$trajectoryStepScale){[double]$problem.trajectory_step_scale}else{$trajectoryStepScale})
    AcceleratorSourceYOffsetMm=[double]$problem.source_y_offset_mm;RunId=$cohortRunId;PythonExe=$python
  }
  $cohortArguments.AcceleratorProviderReceiptPath=$providerReceipt
  if($null-ne$mirrorVoltageVariation){$cohortArguments.MirrorVoltageVariationPath=$mirrorVoltageVariation}
  if(-not[string]::IsNullOrWhiteSpace($CohortBatchContinuationRunPath)){$cohortArguments.BatchContinuationRunPath=$CohortBatchContinuationRunPath}
  if($SimionExe){$cohortArguments.SimionExe=$SimionExe}
  if($null-ne$initialCohortRun){
    $cohortRun=$initialCohortRun;$cohortManifest=Join-Path $cohortRun 'run_manifest.json'
  }else{
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
    $cohortArguments.NativeCorridorRuntimeSession=$nativeRuntimeSession
    $failureStage="cohort_n$CohortParticleCount"
    & $trialRunner @cohortArguments
    $cohortRun=Join-Path $artifactProjectRoot "runs\$cohortRunId";$cohortManifest=Join-Path $cohortRun 'run_manifest.json'
  }
  Assert-VerifiedManifest -ManifestPath $cohortManifest -Status 'success' -Mode 'finite_3d_two_prism_voltage_trial'
  $cohortGate=Get-VerifiedManifestOutput -ManifestPath $cohortManifest -Name 'bunch_collection_gate.json'
  $cohortGateData=Get-Content -LiteralPath $cohortGate -Raw|ConvertFrom-Json -AsHashtable
  $cohortSummary=Get-Content -LiteralPath (Join-Path $cohortRun 'summary.json') -Raw|ConvertFrom-Json -AsHashtable
  $cohortVoltages=@($cohortSummary.stripe_biases_v)+@($cohortSummary.prism_voltages_v)
  if([int]$cohortSummary.source_particle_count-ne$CohortParticleCount-or
     [int]$cohortSummary.source_cohort.mother_particle_count-ne[int]$sourceData.mother_particle_count-or
     [string]$cohortSummary.source_cohort.selection.parent_particle_states_sha256-ne[string]$sourceData.particle_states_sha256-or
     $cohortVoltages.Count-ne4-or(@(0..3|Where-Object{[double]$cohortVoltages[$_]-ne[double]$voltages[$_]}).Count-ne0)-or
     [string]$cohortSummary.accelerator_pulse.mode-ne'static'){
    throw 'Cohort run does not bind the requested source, workpoint voltages, and static accelerator mode.'
  }

  $failureStage='publish'
  $result=Join-Path $package.result_dir 'bunch_screening_result.json'
  Write-RunJson -Path $result -Depth 20 -Value ([ordered]@{
    schema_version=1;role='mrtof_native_corridor_bunch_screening';status=$(if([bool]$cohortGateData.hard_stop){'hard_stop'}else{'complete'})
    purpose=$(if($diagnosticOnly){$DiagnosticPurpose}else{'candidate_bunch_metrics'})
    pa_reuse='one_checkpointed_native_fast_adjust_family__no_pa_copy_or_refine';accelerator_field_mode='static'
    cohort_run_manifest=$cohortManifest;cohort_collection_gate=$cohortGate
    next_action=$(if($diagnosticOnly){"analyze_controlled_${DiagnosticPurpose}_response_only"}elseif([bool]$cohortGateData.hard_stop){'stop_below_collection_hard_minimum'}else{"analyze_complete_n${CohortParticleCount}_candidate_resolution"})
  })
  Write-RunJson -Path $package.summary -Depth 20 -Value ([ordered]@{schema_version=1;role='mrtof_native_corridor_bunch_screening_summary';status='success';purpose=$(if($diagnosticOnly){$DiagnosticPurpose}else{'candidate_bunch_metrics'});cohort_collection_gate=$cohortGateData;accelerator_field_mode='static';pa_reuse='shared_checkpointed_native_runtime'})
  $retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config
  $terminal=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacitySession -RemainingCommittedNewBytes 0
  $capacitySession=$terminal.session;$terminalPath=Join-Path $package.result_dir 'artifact_capacity_gate_terminal.json';Write-RunJson -Path $terminalPath -Depth 14 -Value $terminal
  $completeOutputs=@($package.summary,$result,$startup,$terminalPath,$retention)
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
