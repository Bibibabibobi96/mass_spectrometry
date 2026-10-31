[CmdletBinding(DefaultParameterSetName="Run")]
param(
  [Parameter(Mandatory,ParameterSetName="Run")][string]$Request,
  [Parameter(Mandatory,ParameterSetName='Resume')][switch]$ResumeFinalization,
  [string]$ResultPath='',
  [switch]$DryRun,
  [switch]$SolverAuthorized,
  [string]$ExecutionBudgetPath='',
  [string]$PredecessorManifest='',
  [string]$RunId='',
  [string]$SimionExe='',
  [string]$Python='',
  [string]$ArtifactRoot='',
  [string]$RepoRoot=(Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$RepoRoot=(Resolve-Path -LiteralPath $RepoRoot).Path
. (Join-Path $RepoRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $RepoRoot 'common/contracts/run_artifact_workflow.ps1') -ResultPath $ResultPath -ResumeFinalization:$ResumeFinalization
if($ResumeFinalization){
  if(-not$ResultPath){throw 'ResumeFinalization requires the original ResultPath.'}
  $prior=Get-Content -LiteralPath $ResultPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($RunId-and(Split-Path -Leaf $prior.run_directory)-ne$RunId){throw 'Result belongs to a different run.'}
  $result=Invoke-RunArtifactWorkflow -RequestPath (Join-Path $prior.run_directory 'inputs/execution_request.json') -ResultPath $ResultPath -ResumeFinalization
  Write-Output $result
  if($result.status-ne'success'){throw 'Paired finalization remains incomplete; inspect Result recovery_action.'}
  return
}
$Request=(Resolve-Path -LiteralPath $Request).Path
if(-not$DryRun-and(-not$SolverAuthorized-or-not$ExecutionBudgetPath)){
  throw 'Native paired pulse execution requires SolverAuthorized and an explicit ExecutionBudgetPath.'
}
. (Join-Path $RepoRoot 'common/require_powershell7.ps1')
. (Join-Path $RepoRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $RepoRoot 'common/host_execution_lease.ps1')
. (Join-Path $RepoRoot 'common/resource_budget_support.ps1')
. (Join-Path $RepoRoot 'common/simion/short_pa_path_support.ps1')
. (Join-Path $RepoRoot 'integrations/runtime/dependencies.ps1')
. (Join-Path $RepoRoot 'integrations/runtime/frontend_flight_support.ps1')
if(-not$Python){$Python=Join-Path $RepoRoot '.venv/Scripts/python.exe'}
. (Join-Path $RepoRoot 'common/paths/workspace_paths.ps1')
$pathArguments=@{SourceRoot=$RepoRoot;Python=$Python}
if($ArtifactRoot){$pathArguments.ArtifactRoot=$ArtifactRoot}
$pathContext=Resolve-WorkspacePaths @pathArguments
$ArtifactRoot=[string]$pathContext.artifact_root
if(-not$RunId){$RunId=(Get-Date -Format yyyyMMdd_HHmmss)+$(if($DryRun){'__test__python__paired-accelerator-pulse'}else{'__sim__cross__paired-accelerator-pulse'})}
$project='instrument_assembly';$consumer='paired_accelerator_pulse'
$reason='Recorded OA finite pulse; preserve original sources, shared fields, raw particle solutions and negative evidence; no numerical or Formal qualification.'
$software=@('Python 3.11','PowerShell 7')
if(-not$DryRun){$software+=@('SIMION 2020','COMSOL 6.4','MATLAB R2025b')}
$package=$null;$capacity=$null;$lease=$null;$paGuards=@();$frozen=$null;$terminalized=$false;$writerUnknown=$false
$failure=$null;$stage='initialization';$reusedParticleSolution=$false;$reusedBaseline=$false;$reusedReplay=$false;$reusedParticleExports=$false;$nativeExecuted=$false
$plan=$null;$ownerContext=$null;$writersStopped=$true;$hostReleaseUnknown=$false
$nativeOperations=[Collections.Generic.List[object]]::new();$resourceReleases=[Collections.Generic.List[object]]::new()
$phaseTimings=[ordered]@{};$runClock=[Diagnostics.Stopwatch]::StartNew();$stageClock=[Diagnostics.Stopwatch]::StartNew()
$header="import json,sys; from pathlib import Path; from integrations.workflows.paired_accelerator_pulse.prepare import prepare; from integrations.workflows.paired_accelerator_pulse.runtime import *; "
function Close-PairedHostStage {
  if(-not$lease){return}
  $token=[string]$lease.token
  try{$released=Exit-HostResourceStage -Lease $lease -PassThru}catch{$script:writerUnknown=$true;$script:hostReleaseUnknown=$true;throw}
  # Inherited stages restore their environment without releasing the parent grant.
  if(-not$lease.inherited-and($null-eq$released-or$released.status-ne'released'-or$released.token-ne$token)){$script:writerUnknown=$true;$script:hostReleaseUnknown=$true;throw 'Paired host release is unconfirmed.'}
  if(@($nativeOperations|Where-Object resource_release_id -eq $token).Count){
    Add-RunArtifactResourceRelease -ResourceReleases $resourceReleases -ReleaseId $token -Receipt @{host_release=@{inherited=[bool]$lease.inherited;token=$token;result=$released;error=$null}}
  }
  $script:lease=$null
}
function Set-PairedStage([string]$Name){
  if($stage){$phaseTimings[$stage]=[double]$stageClock.Elapsed.TotalSeconds}
  $script:stage=$Name;$stageClock.Restart()
}

function Invoke-PulsePython {
  param([string]$Code,[string[]]$Arguments=@())
  Invoke-RunToolRootContext -RepoRoot $frozen.execution_root -Operation {
    $stdout=Join-Path $package.log_dir ($stage+'.python.stdout.json')
    $stderr=Join-Path $package.log_dir ($stage+'.python.stderr.log')
    &$Python -B -c ($header+$Code) @Arguments 1>$stdout 2>$stderr
    if($LASTEXITCODE-ne0){throw ("Paired pulse Python stage failed: "+(Get-Content -LiteralPath $stderr -Raw))}
    return Get-Content -LiteralPath $stdout -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  }
}
function Register-PulseInputs {
  $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  foreach($file in Get-ChildItem -LiteralPath $package.input_dir -Recurse -File){
    $relative=[IO.Path]::GetRelativePath($package.input_dir,$file.FullName)
    $config.inputs[$relative]=Join-Path (Join-Path $package.artifact_run_dir 'inputs') $relative
  }
  Write-RunJson -Path $package.run_config -Depth 100 -Value $config
}
function Confirm-PulseIobVerification {
  param([ValidateSet('after_build','after_first_fly')][string]$Operation,$Case,$BuildResult,
    [string]$Phase,[string]$RunDirectory,[string]$SimionExe,$Limits,[string]$Python,[string]$RepoRoot)
  $context=@{Python=$Python;RepoRoot=$RepoRoot;RunDirectory=$RunDirectory}
  $name=[string]$Case.case_id
  if($Operation-eq'after_first_fly'){
    $null=Invoke-FrontendRuntimePython @context -Name "$Phase.$name.controls-after" -Arguments @('-c',
      'import json,sys;from common.contracts.verify_run_manifest import verify_record;[verify_record("saved pulse control",r) for r in json.loads(sys.argv[1])]',
      (ConvertTo-Json -InputObject @($Case.control_records) -Depth 100 -Compress))
    return
  }
  $buildLog=Join-Path $RunDirectory "logs/$Phase.$name.assembly.stdout.log"
  if(-not(Get-Content -LiteralPath $buildLog -Raw).Contains('PAIRED_ACCELERATOR_PULSE_IOB_BUILD=PASS')){
    throw 'Pulse IOB build completion marker missing.'
  }
  $reopenLog=Join-Path $RunDirectory "logs/$Phase.$name.reopen.stdout.log"
  $reopenPaths=@([string]$Case.working_directory,[string]$Case.iob_path)+@($Case.reopen_arguments|Where-Object{[IO.Path]::IsPathFullyQualified([string]$_)})
  $reopenContext=Get-RunNativeExecutionContext -Package $package -Paths $reopenPaths -Tool SIMION
  $reopenProjected=Project-RunPath -Paths (@([string]$Case.working_directory)+[string[]]$Case.reopen_arguments) -ArtifactRunDir $package.artifact_run_dir -RunDir $reopenContext.run_dir -Python $Python
  $script:writersStopped=$false
  try{
  $checked=Invoke-ResourceBudgetedProcess -Limits $Limits -RunDir $RunDirectory -FilePath $SimionExe `
    -ArgumentList ([string[]]$reopenProjected[1..($reopenProjected.Count-1)]) -WorkingDirectory $reopenProjected[0] -Environment $reopenContext.environment `
    -UsagePath (Join-Path $RunDirectory "logs/$Phase.$name.reopen.usage.json") `
    -RedirectStandardOutput $reopenLog -RedirectStandardError (Join-Path $RunDirectory "logs/$Phase.$name.reopen.stderr.log")
    Add-FrontendNativeOperation -NativeOperations $nativeOperations -NativeResourceReleaseId ([string]$lease.token) -OperationId "$Phase.$name.reopen" -ProcessRecord $checked
    $script:writersStopped=$true
  }catch{
    Add-FrontendNativeOperation -NativeOperations $nativeOperations -NativeResourceReleaseId ([string]$lease.token) -OperationId "$Phase.$name.reopen" -ExceptionData $_.Exception.Data
    $script:writersStopped=($_.Exception.Data.Contains('observed_process_exit_confirmed')-and[bool]$_.Exception.Data['observed_process_exit_confirmed'])
    if(-not$writersStopped){$script:writerUnknown=$true}
    throw
  }
  if($checked.resource_budget_exceeded-or$checked.exit_code-ne0-or
      -not(Get-Content -LiteralPath $reopenLog -Raw).Contains('PAIRED_ACCELERATOR_PULSE_IOB_VERIFY=PASS')){
    throw 'Saved pulse IOB independent reopen failed.'
  }
  $binding=Invoke-FrontendRuntimePython @context -Name "$Phase.$name.bind-controls" -Json -Arguments @('-c',
    'import json,sys;from pathlib import Path;from common.contracts.verify_run_manifest import verify_record;from common.contracts.write_run_manifest import file_record;records=json.loads(sys.argv[1]);[verify_record("prepared pulse control",r) for r in records];print(json.dumps(dict(control_records=records+[file_record(Path(sys.argv[2]))],iob_reopen_record=file_record(Path(sys.argv[3])))))',
    (ConvertTo-Json -InputObject @($Case.control_records) -Depth 100 -Compress),$Case.iob_path,$reopenLog)
  $Case|Add-Member -NotePropertyName control_records -NotePropertyValue @($binding.control_records) -Force
  $Case|Add-Member -NotePropertyName iob_reopen_record -NotePropertyValue $binding.iob_reopen_record -Force
  Write-RunJson -Path $Case.receipt_path -Value $Case -Depth 100
}
$pathEnvironmentNames=@('MASS_SPECTROMETRY_ARTIFACT_ROOT','MASS_SPECTROMETRY_EXECUTION_ROOT','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH','MASS_SPECTROMETRY_RUN_DIRECTORY','MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY')
$savedPathEnvironment=Save-RunEnvironment -Names $pathEnvironmentNames
try{
  $destination=Join-Path $ArtifactRoot ('projects/instrument_assembly/runs/'+$RunId)
  $parentEnvironment=@{MASS_SPECTROMETRY_ARTIFACT_ROOT=$ArtifactRoot;MASS_SPECTROMETRY_EXECUTION_ROOT=$pathContext.execution_root;
    MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=$pathContext.host_resource_state_path;MASS_SPECTROMETRY_RUN_DIRECTORY=$destination;MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY=$destination}
  foreach($key in $parentEnvironment.Keys){[Environment]::SetEnvironmentVariable([string]$key,[string]$parentEnvironment[$key],'Process')}
  $lease=Enter-HostResourceStage -StatePath $pathContext.host_resource_state_path -Role GATE -Stage prepare -Budget (Get-HostResourceBudget -Role GATE -Stage prepare) -RunId $RunId
  $package=New-RunPackage -Python $Python -RepoRoot $RepoRoot -ArtifactRoot (Join-Path $ArtifactRoot 'projects/instrument_assembly') `
    -RunId $RunId -Project $project -Mode $consumer -Software $software -RetentionContractEnabled -RetentionClass solver_review `
    -RetentionReason $reason -CapacityLedgerLifecycleEnabled -CapacityLedgerArtifactRoot $ArtifactRoot -PathContext $pathContext `
    -UseShortExecutionPath -AdditionalDirectories @('simion','comsol')
  $capacity=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -ArtifactRoot $ArtifactRoot `
    -RunDirectory $package.artifact_run_dir -CommittedNewBytes 0 -Owner ("run-artifact-workflow:{0}:{1}"-f$project,$RunId)
  Set-PairedStage 'freeze_inputs'
  $requestPath=Copy-VerifiedRunInput -Source $Request -Destination (Join-Path $package.input_dir 'request.json')
  $commitmentInputs=@($requestPath)
  if(-not$DryRun){$budgetPath=Copy-VerifiedRunInput -Source $ExecutionBudgetPath -Destination (Join-Path $package.input_dir 'execution_budget.json');$commitmentInputs+=@($budgetPath)}
  $ownerEntrypoint=Copy-VerifiedRunInput -Source $PSCommandPath -Destination (Join-Path $package.input_dir 'owner.ps1')
  $bootstrapConfig=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  $bootstrapConfig.inputs.request=$requestPath;$bootstrapConfig.inputs.owner_entrypoint=$ownerEntrypoint
  if(-not$DryRun){$bootstrapConfig.inputs.execution_budget=$budgetPath}
  Write-RunJson -Path $package.run_config -Value $bootstrapConfig -Depth 100
  $ownerContext=Initialize-RunArtifactPowerShellOwner -Python $Python -RepoRoot $RepoRoot -Package $package -CapacitySession $capacity `
    -ResultPath $ResultPath -EntrypointPath $ownerEntrypoint `
    -CommitmentInputPaths $commitmentInputs -Software $software
  $ResultPath=$ownerContext.result_path
  $frozen=Freeze-ConsumerDependencies -RepoRoot $RepoRoot -ContractPath (Join-Path $RepoRoot 'integrations/config/runtime_dependencies.json') `
    -InputDir $package.input_dir -OwnerId $project -ConsumerId $consumer
  $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  $config.inputs.code_inventory=Convert-WorkflowOwnerPath $ownerContext $frozen.code_inventory_path
  $config.inputs.dependency_contract=Convert-WorkflowOwnerPath $ownerContext $frozen.dependency_contract_path
  $config.parameters=@{workflow=$consumer;request_source_path=$Request;dry_run=[bool]$DryRun;solver_authorized=[bool]$SolverAuthorized}
  Write-RunJson -Path $package.run_config -Depth 100 -Value $config
  $planPath=Join-Path $package.artifact_run_dir 'inputs/pulse/paired_accelerator_pulse_plan.json'
  Set-PairedStage 'prepare_pulse'
  $plan=Invoke-PulsePython 'print(json.dumps(prepare(Path(sys.argv[1]),Path(sys.argv[2]),source_base_dir=Path(sys.argv[3]))))' `
    @($requestPath,(Join-Path $package.artifact_run_dir 'inputs/pulse'),(Split-Path -Parent $Request))
  Write-RunJson -Path (Join-Path $package.result_dir 'preparation_receipt.json') -Depth 100 -Value @{
    schema_version=1;role='paired_accelerator_pulse_preparation';status='success';native_executed=$false;plan=$planPath;particle_count=$plan.particle_count}
  if(-not$DryRun){
    Set-PairedStage 'execution_budget'
    $budget=Get-Content -LiteralPath $budgetPath -Raw|ConvertFrom-Json -AsHashtable -Depth 100
    if([long]$budget.committed_new_bytes-le0){throw 'Positive explicit committed_new_bytes required.'}
    foreach($name in @('wall_clock_seconds','transient_run_directory_bytes','process_tree_working_set_bytes','minimum_system_available_memory_bytes','compact_final_retained_bytes')){
      if([long]$budget.limits[$name]-le0){throw "Positive public process limit required: $name"}
    }
    $savedParticle=''
    $completed=@{particle_model=$null;particle_exports=$null;simion_baseline=$null;simion_replay=$null}
    if($PredecessorManifest){
      Set-PairedStage 'consume_completed_stages'
      $sourcePath=(Resolve-Path -LiteralPath $PredecessorManifest).Path
      $snapshot=Copy-VerifiedRunInput -Source $sourcePath -Destination (Join-Path $package.input_dir 'predecessor_manifest.json')
      $completed=Invoke-PulsePython 'print(json.dumps(load_completed_pulse_stages(*map(Path,sys.argv[1:]))))' @($planPath,$sourcePath,$snapshot)
      $reusedParticleSolution=($null-ne$completed.particle_model)
      $reusedBaseline=($null-ne$completed.simion_baseline)
      $reusedReplay=($null-ne$completed.simion_replay)
      $reusedParticleExports=($null-ne$completed.particle_exports)
      $stagesPath=Join-Path $package.input_dir 'completed_pulse_stages.json'
      Write-RunJson -Path $stagesPath -Value $completed -Depth 100
      if($reusedParticleSolution){$savedParticle=[string]$completed.particle_model.path}
      $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable -Depth 100
      $index=0
      foreach($name in @('simion_baseline','simion_replay')){
        $done=$completed[$name]
        if($null-eq$done){continue}
        foreach($key in @('collection','comparison','samples','workbench','dispatch')){
          if($done.ContainsKey($key)){$config.inputs["completed_parent_$index"]=$done[$key].path;$index++}
        }
        foreach($record in $done.logs){$config.inputs["completed_parent_$index"]=$record.path;$index++}
        if($done.ContainsKey('completion_facts')){foreach($record in $done.completion_facts){$config.inputs["completed_parent_$index"]=$record.path;$index++}}
      }
      if($reusedParticleExports){$config.inputs.completed_particle_export_plan=$completed.particle_exports.plan.path}
      Write-RunJson -Path $package.run_config -Depth 100 -Value $config
    }
    $protected=@([string]$plan.model.path)
    if($reusedParticleSolution){$protected+=@($savedParticle)}
    if($PredecessorManifest){$protected+=Split-Path -Parent $sourcePath}
    $update=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity `
      -RemainingCommittedNewBytes ([long]$budget.committed_new_bytes) -ProtectedPaths $protected
    $capacity=$update.session
    $workbenchPath=Join-Path $package.result_dir 'pulse_workbench.json'
    $dispatchPath=Join-Path $package.result_dir 'pulse.dispatch_plan.json'
    if($reusedBaseline){
      $null=Copy-VerifiedRunInput -Source $completed.simion_baseline.collection.path -Destination (Join-Path $package.result_dir 'simion_pulse_baseline.json')
      $null=Copy-VerifiedRunInput -Source $completed.simion_baseline.samples.path -Destination (Join-Path $package.result_dir 'simion_pulse_baseline.csv')
      $workbench=Get-Content -LiteralPath $completed.simion_baseline.workbench.path -Raw|ConvertFrom-Json -Depth 100
      $null=Copy-VerifiedRunInput -Source $completed.simion_baseline.dispatch.path -Destination $dispatchPath
      Write-RunJson -Path $workbenchPath -Value $workbench -Depth 100
      $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable -Depth 100
      $index=0
      foreach($case in $workbench.batches){
        foreach($record in @($case.control_records)+@($case.iob_reopen_record)){
          $config.inputs["borrowed_control_$index"]=$record.path;$index++
        }
      }
      Write-RunJson -Path $package.run_config -Depth 100 -Value $config
    }
    if($reusedReplay){
      $null=Copy-VerifiedRunInput -Source $completed.simion_replay.comparison.path -Destination (Join-Path $package.result_dir 'simion_pulse_replay_comparison.json')
      $null=Copy-VerifiedRunInput -Source $completed.simion_replay.samples.path -Destination (Join-Path $package.result_dir 'simion_pulse_default_replay.csv')
    }
    if(-not$reusedBaseline-or-not$reusedReplay){
      if($reusedBaseline){
        $fieldPa=[string]$completed.simion_baseline.field.path
        $generation=[string]$completed.simion_baseline.field.generation_directory
        $fieldKey=[string]$completed.simion_baseline.field.cache_key
      }else{
        $publication=Get-Content -LiteralPath $plan.input_records.simion_field_publication.path -Raw|ConvertFrom-Json -AsHashtable -Depth 100
        $generation=(Resolve-Path -LiteralPath $publication.generation_directory).Path
        $fieldPa=Join-Path $generation 'paired_static_on.pa';$fieldKey=[string]$publication.cache_key
      }
      Set-PairedStage 'published_field_metadata'
      $cacheManifest=Invoke-PulsePython 'from common.simion.pa_family_cache import validate_pa_family_cache_generation;print(json.dumps(validate_pa_family_cache_generation(Path(sys.argv[1]),expected_cache_key=sys.argv[2],expected_filenames=["paired_static_on.pa"],verify_payload=False)))' `
        @($generation,$fieldKey)
      $members=@($cacheManifest.files|Where-Object name -eq 'paired_static_on.pa')
      if($members.Count-ne1){throw 'Published OA field must bind one paired_static_on.pa member.'}
      $protected+=@($generation)
      $update=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity `
        -RemainingCommittedNewBytes ([long]$budget.committed_new_bytes) -ProtectedPaths $protected -ProtectedCacheKeys @($fieldKey)
      $capacity=$update.session
      Set-PairedStage 'protect_published_field'
      $guard=Protect-ImmutablePaSource -Source $fieldPa -ExpectedBytes $members[0].bytes -ExpectedSha256 $members[0].sha256
      $paGuards+=@([string]$guard.path)
      if(-not$SimionExe){$SimionExe=Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe'}
      $SimionExe=(Resolve-Path -LiteralPath $SimionExe).Path
      Register-PulseInputs
      Close-PairedHostStage
      $lease=Enter-HostResourceStage -StatePath $pathContext.host_resource_state_path -Role SIMION -Stage flight -Budget $budget.host_budgets.simion_flight -RunId $RunId
      if(-not$reusedBaseline){
        $seed=Join-Path $frozen.execution_root 'common/simion/assets/iob_instance_seeds/1_instance_seed.iob'
        $runtimeInputs=@('--plan',$planPath,'--code-root',$frozen.execution_root,'--field-pa',$fieldPa,'--seed-iob',$seed)
        $continuationArguments=@{}
        if($PredecessorManifest){
          Set-PairedStage 'simion_unit_continuation'
          $continuation=Invoke-PulsePython 'print(json.dumps(materialize_simion_continuation(Path(sys.argv[1]),Path(sys.argv[2]),json.loads(Path(sys.argv[3]).read_text(encoding="utf-8-sig")),code_root=Path(sys.argv[4]),field_pa=Path(sys.argv[5]),seed_iob=Path(sys.argv[6]))))' `
            @($planPath,$package.artifact_run_dir,$stagesPath,$frozen.execution_root,$fieldPa,$seed)
          if($null-ne$continuation){
            $null=Copy-VerifiedRunInput -Source $continuation.fixed_dispatch_plan_path -Destination $dispatchPath
            $continuationArguments=@{FixedDispatchPlanPath=$dispatchPath;ContinuationPlanPath=$continuation.continuation_plan_path;ContinuationWorkbench=$continuation.workbench}
            $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable -Depth 100
            $config.inputs.simion_whole_unit_continuation=$continuation.continuation_record.path
            $reuseIndex=0
            foreach($unit in $continuation.workbench.batches){
              # Bind the actual reused ancestor outputs through this direct parent.
              if(($unit-is[Collections.IDictionary]-and$unit.Contains('continuation_source'))-or
                 $unit.PSObject.Properties.Name-contains'continuation_source'){
                foreach($record in $unit.continuation_source.terminal_outputs){$config.inputs["reused_baseline_$reuseIndex"]=$record.path;$reuseIndex++}
              }
            }
            Write-RunJson -Path $package.run_config -Value $config -Depth 100
            if($continuation.field.path-ne$fieldPa){
              $oldField=$continuation.field
              $protected+=@([string]$oldField.generation_directory)
              $update=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity `
                -RemainingCommittedNewBytes ([long]$budget.committed_new_bytes) -ProtectedPaths $protected -ProtectedCacheKeys @($fieldKey,[string]$oldField.cache_key)
              $capacity=$update.session
              $oldGuard=Protect-ImmutablePaSource -Source $oldField.path -ExpectedBytes $oldField.bytes -ExpectedSha256 $oldField.sha256
              $paGuards+=@([string]$oldGuard.path)
            }
          }
        }
        Set-PairedStage 'simion_flight'
        $workbench=Invoke-FrontendFlightPhase -Package $package -RunDirectory $package.artifact_run_dir -ProjectRunsRoot (Split-Path -Parent $package.artifact_run_dir) `
          -RepoRoot $frozen.execution_root -Python $Python -RuntimeModule integrations.workflows.paired_accelerator_pulse.runtime `
          -SimionExe $SimionExe -Limits ([pscustomobject]$budget.limits) -Phase pulse -RuntimeInputArguments $runtimeInputs -WorkbenchReceiptPath $workbenchPath `
          -IobVerification ${function:Confirm-PulseIobVerification} -NativeOperations $nativeOperations -NativeResourceReleaseId ([string]$lease.token) `
          -OnProcessCompleted {param($record) Write-FrontendBatchCheckpoint -Record $record -Phase 'pulse' -RunDirectory $package.artifact_run_dir `
            -RunConfig $package.run_config -WorkbenchReceiptPath $workbenchPath -DispatchPlanPath $dispatchPath -Python $Python -RepoRoot $RepoRoot} @continuationArguments
        if(@($workbench.native_process_records).Count){$nativeExecuted=$true}
        Write-RunJson -Path $workbenchPath -Depth 100 -Value $workbench
        $lease=Update-HostResourceStage -Lease $lease -Stage postprocess -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
        Set-PairedStage 'collect_baseline'
        $null=Invoke-PulsePython 'print(json.dumps(collect_simion_batches(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]),phase="baseline")))' `
          @($planPath,$workbenchPath,$package.artifact_run_dir)
      }
      if(-not$reusedReplay){
        Set-PairedStage 'default_replay'
        $replayContinuation=$null;$replayUnits=@{}
        if($PredecessorManifest){
          $replayContinuation=Invoke-PulsePython 'print(json.dumps(plan_simion_replay_continuation(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig")),Path(sys.argv[2]))))' @($stagesPath,$package.artifact_run_dir)
          if($null-ne$replayContinuation){
            $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable -Depth 100
            $config.inputs.pulse_replay_continuation=$replayContinuation.plan_record.path
            $index=0
            foreach($unit in $replayContinuation.plan.units){
              $replayUnits[[string]$unit.key]=$unit
              if($unit.action-eq'reuse'){foreach($record in $unit.terminal_outputs){$config.inputs["reused_replay_$index"]=$record.path;$index++}}
            }
            Write-RunJson -Path $package.run_config -Value $config -Depth 100
          }
        }
        $specifications=@(foreach($case in $workbench.batches){
          $unit=$replayUnits[[string]$case.case_id]
          if($null-ne$unit-and$unit.action-eq'reuse'){
            $case|Add-Member -NotePropertyName default_replay_stdout -NotePropertyValue ([string]$unit.terminal_outputs[0].path) -Force
            $case|Add-Member -NotePropertyName replay_continuation_source -NotePropertyValue $unit -Force
            continue
          }
          $case|Add-Member -NotePropertyName default_replay_stdout -NotePropertyValue (Join-Path $package.artifact_run_dir ('logs/'+$case.case_id+'.replay.stdout.log')) -Force
          $case|Add-Member -NotePropertyName default_replay_stderr -NotePropertyValue (Join-Path $package.artifact_run_dir ('logs/'+$case.case_id+'.replay.stderr.log')) -Force
          $replayCase=$case|ConvertTo-Json -Depth 100|ConvertFrom-Json -AsHashtable -Depth 100
          $replayCase.stdout=$case.default_replay_stdout;$replayCase.stderr=$case.default_replay_stderr
          New-FrontendFlightSpecification -Package $package -Case ([pscustomobject]$replayCase) -SimionExe $SimionExe
        })
        Write-RunJson -Path $workbenchPath -Value $workbench -Depth 100
        if($specifications.Count){$lease=Update-HostResourceStage -Lease $lease -Stage flight -Budget $budget.host_budgets.simion_flight -RetainedMemoryBytes 0}
        $replay=if($specifications.Count){Invoke-ResourceBudgetedProcesses -DispatchPlanPath $dispatchPath `
          -RunDir $package.artifact_run_dir -UsagePath (Join-Path $package.result_dir 'pulse_replay.resource_usage.json') -ProcessSpecifications $specifications `
          -OnProcessCompleted {param($record) Add-FrontendNativeOperation -NativeOperations $nativeOperations -NativeResourceReleaseId ([string]$lease.token) -OperationId 'pulse.default_replay' -ProcessRecord $record;Write-FrontendBatchCheckpoint -Record $record -Phase 'pulse_replay' -RunDirectory $package.artifact_run_dir `
            -RunConfig $package.run_config -WorkbenchReceiptPath $workbenchPath -DispatchPlanPath $dispatchPath -Python $Python -RepoRoot $RepoRoot}}else{@{resource_budget_exceeded=$false;processes=@()}}
        if($replay.resource_budget_exceeded){
          try{throw 'Pulse saved-default replay exceeded the resource budget; writer completion is unconfirmed.'}catch{
            $_.Exception.Data['simion_wave_writer_completion_confirmed']=$false;throw
          }
        }
        if($replay.resource_budget_exceeded-or@($replay.processes|Where-Object exit_code -ne 0).Count){throw 'Pulse saved-default replay failed.'}
        if($specifications.Count){$nativeExecuted=$true}
        if($specifications.Count){Complete-ResourceUsage -RunDir $package.artifact_run_dir -UsagePath (Join-Path $package.result_dir 'pulse_replay.resource_usage.json')|Out-Null}
        if($specifications.Count){$lease=Update-HostResourceStage -Lease $lease -Stage postprocess -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0}
        Set-PairedStage 'collect_replay'
        $null=Invoke-PulsePython 'print(json.dumps(collect_simion_batches(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]),phase="default_replay")))' `
          @($planPath,$workbenchPath,$package.artifact_run_dir)
      }
    }
    if($reusedParticleExports){
      foreach($name in @('particles','initial','native_facts')){
        $filename=@{particles='paired_pulse_particles.csv';initial='paired_pulse_initial.csv';native_facts='paired_pulse_native_facts.json'}[$name]
        $null=Copy-VerifiedRunInput -Source $completed.particle_exports[$name].path -Destination (Join-Path $package.artifact_run_dir "comsol/$filename")
      }
    }else{
      Set-PairedStage 'comsol_particle_task'
      $tasks=Invoke-PulsePython 'print(json.dumps(materialize_comsol_task(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]),saved_particle_model=Path(sys.argv[4]) if sys.argv[4] else None)))' `
        @($planPath,(Join-Path $package.artifact_run_dir 'comsol'),$frozen.execution_root,$savedParticle)
      Set-PairedStage 'verify_native_model'
      $model=if($savedParticle){$completed.particle_model}else{$plan.model}
      $null=Invoke-PulsePython 'from common.contracts.verify_run_manifest import verify_record; verify_record("native pulse model",json.loads(sys.argv[1]));print("{}")' `
        @(($model|ConvertTo-Json -Depth 100 -Compress))
      Register-PulseInputs
      Close-PairedHostStage
      Set-PairedStage 'comsol_particles';$nativeExecuted=$true
      $comsolCompletion=Join-Path $package.artifact_run_dir 'logs/comsol_completion.json';$writersStopped=$false;$comsolFailure=$null
      try{
      & (Join-Path $RepoRoot 'common/comsol/run_comsol_r2025b.ps1') -TaskScript $tasks.matlab `
        -ReportPath (Join-Path $package.artifact_run_dir 'logs/comsol_bootstrap.txt') -ResourceBudgets $budget.host_budgets.comsol -RunId $RunId `
        -Limits ([pscustomobject]$budget.limits) -RunDir $package.artifact_run_dir -UsagePath (Join-Path $package.artifact_run_dir 'logs/comsol.resource_usage.json') -CompletionPath $comsolCompletion
      }catch{$comsolFailure=$_}finally{
        try{
          if(-not(Test-Path -LiteralPath $comsolCompletion)){throw 'COMSOL completion receipt is missing.'}
          $observed=Get-Content -LiteralPath $comsolCompletion -Raw|ConvertFrom-Json -AsHashtable
          $releaseId=[string]$observed.host_release.token
          foreach($operation in $observed.operations){$operation.resource_release_id=$releaseId;$nativeOperations.Add($operation)}
          if($observed.operations.Count){Add-RunArtifactResourceRelease -ResourceReleases $resourceReleases -ReleaseId $releaseId -Receipt $observed}
          $writersStopped=(@($observed.operations|Where-Object{-not$_.observation.exit_confirmed}).Count-eq0)
          if($observed.host_release.error-or(-not$observed.host_release.inherited-and($null-eq$observed.host_release.result-or$observed.host_release.result.status-ne'released'-or$observed.host_release.result.token-ne$observed.host_release.token))){$writerUnknown=$true;$hostReleaseUnknown=$true}
        }catch{$writerUnknown=$true;if($comsolFailure){$comsolFailure.Exception.Data['completion_receipt_error']=$_}else{$comsolFailure=$_}}
      }
      if($comsolFailure){throw $comsolFailure}
      if($LASTEXITCODE-ne0){throw 'COMSOL particle execution/export failed; raw saved particle model and native facts are retained.'}
    }
    Set-PairedStage 'diagnostic_comparison'
    $null=Invoke-PulsePython 'from integrations.analysis.compare_paired_accelerator_pulse import compare_paired_accelerator_pulse;print(json.dumps(compare_paired_accelerator_pulse(*map(Path,sys.argv[1:]))))' `
      @($planPath,(Join-Path $package.artifact_run_dir 'comsol/paired_pulse_particles.csv'),(Join-Path $package.result_dir 'simion_pulse_baseline.csv'),(Join-Path $package.result_dir 'comparison'))
  }
  Set-PairedStage 'terminal_publication'
  if($lease){Close-PairedHostStage}
  Register-PulseInputs
}catch{
  $failure=$_
  $data=$failure.Exception.Data
  $writerUnknown=$writerUnknown-or[bool]$data['simion_first_batch_writer_unknown']-or[bool]$data['simion_first_batch_drain_error']-or
    ($data.Contains('simion_wave_writer_completion_confirmed')-and-not[bool]$data['simion_wave_writer_completion_confirmed'])-or
    ($data.Contains('observed_process_exit_confirmed')-and-not[bool]$data['observed_process_exit_confirmed'])
 }finally{
  try{
  if(-not$writersStopped){$writerUnknown=$true}
  if(-not$writerUnknown){
    try{if($lease){Close-PairedHostStage}}catch{if($failure){$failure.Exception.Data['host_release_error']=$_}else{$failure=$_};$writerUnknown=$true}
    if(-not$writerUnknown){
      try{foreach($source in $paGuards){Unprotect-ImmutablePaSource -Source $source};$paGuards=@()}catch{if($failure){$failure.Exception.Data['asset_release_error']=$_}else{$failure=$_}}
    }
  }
  if(-not$ownerContext-and-not$writerUnknown){
    try{if($capacity){$null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity};if($package){Remove-RunPackageExecutionAlias -Package $package}}catch{if($failure){$failure.Exception.Data['bootstrap_cleanup_error']=$_}else{$failure=$_}}
  }
  if($ownerContext-and-not$ownerContext.completion_written){
    if(-not$writerUnknown){try{Register-PulseInputs}catch{if($failure){$failure.Exception.Data['input_binding_error']=$_}else{$failure=$_}}}
    $phaseTimings[$stage]=[double]$stageClock.Elapsed.TotalSeconds
    $status=if($failure){'failed'}else{'success'}
    $summary=@{native_path_preparation=$package.native_path_preparation;schema_version=1;role='paired_accelerator_pulse_summary';execution_status=$(if($hostReleaseUnknown){'host_release_unconfirmed'}elseif($writerUnknown){'writer_completion_unknown'}elseif($failure){'failed'}else{'completed'});
      data_validity=$(if($failure){'incomplete'}else{'valid'});scientific_result=$(if($failure){'NOT_EVALUATED'}elseif($DryRun){'preparation_only'}else{'diagnostic_only'});qualification='no_numerical_equivalence_GUI_or_Formal_qualification';dry_run=[bool]$DryRun;
      particle_count=$(if($plan){$plan.particle_count}else{$null});native_executed=($nativeOperations.Count-gt0);reused_particle_solution=$reusedParticleSolution;reused_simion_baseline=$reusedBaseline;reused_simion_replay=$reusedReplay;reused_particle_exports=$reusedParticleExports;
      failure_stage=$(if($failure){$stage}else{$null});failure_reason=$(if($failure){$failure.Exception.Message}else{$null});
      recovery_action=$(if($hostReleaseUnknown){'inspect_host_release'}elseif($writerUnknown){'inspect_writer_completion'}elseif($failure){'inspect_preserved_stage_evidence_or_resume_finalization'}else{'none'});
      secondary_errors=@(if($failure){foreach($key in @('host_release_error','asset_release_error','bootstrap_cleanup_error','completion_receipt_error','comsol_closeout_error')){if($failure.Exception.Data.Contains($key)){[string]$failure.Exception.Data[$key]}}});result_path=$ResultPath;phase_timings_seconds=$phaseTimings;total_elapsed_seconds=$runClock.Elapsed.TotalSeconds}
    $outputs=@(Get-ChildItem $package.result_dir,$package.log_dir,(Join-Path $package.artifact_run_dir 'comsol'),(Join-Path $package.artifact_run_dir 'simion') -Recurse -File|ForEach-Object FullName)
    $ownerContext.session=$capacity
    try{$outcome=Complete-RunArtifactPowerShellOwner -Context $ownerContext -Status $status -Summary $summary -OutputPaths $outputs `
      -WriterCompletion @{operations=@($nativeOperations|ForEach-Object{$_});resource_releases=@($resourceReleases|ForEach-Object{$_})} `
      -WritersStopped (-not$writerUnknown) -OriginalFailure $failure;Write-Output $outcome}catch{if($failure){$failure.Exception.Data['finalization_error']=$_}else{$failure=$_}}
  }
  }finally{Restore-RunEnvironment -Names $pathEnvironmentNames -Snapshot $savedPathEnvironment}
}
if($failure){throw $failure}
