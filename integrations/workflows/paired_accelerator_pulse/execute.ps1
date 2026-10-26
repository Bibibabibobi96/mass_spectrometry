[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Request,
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
if(-not$ArtifactRoot){$ArtifactRoot=Join-Path (Split-Path -Parent $RepoRoot) 'artifacts'}
if(-not$RunId){$RunId=(Get-Date -Format yyyyMMdd_HHmmss)+$(if($DryRun){'__test__python__paired-accelerator-pulse'}else{'__sim__cross__paired-accelerator-pulse'})}
$project='instrument_assembly';$consumer='paired_accelerator_pulse'
$reason='Recorded OA finite pulse; preserve original sources, shared fields, raw particle solutions and negative evidence; no numerical or Formal qualification.'
$software=@('Python 3.11','PowerShell 7')
if(-not$DryRun){$software+=@('SIMION 2020','COMSOL 6.4','MATLAB R2025b')}
$package=$null;$capacity=$null;$lease=$null;$paGuards=@();$frozen=$null;$terminalized=$false
$failure=$null;$stage='initialization';$reusedParticleSolution=$false;$reusedBaseline=$false;$reusedReplay=$false;$reusedParticleExports=$false;$nativeExecuted=$false
$header="import json,sys; from pathlib import Path; from integrations.workflows.paired_accelerator_pulse.prepare import prepare; from integrations.workflows.paired_accelerator_pulse.runtime import *; "
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
    $config.inputs[[IO.Path]::GetRelativePath($package.input_dir,$file.FullName)]=$file.FullName
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
  $checked=Invoke-ResourceBudgetedProcess -Limits $Limits -RunDir $RunDirectory -FilePath $SimionExe `
    -ArgumentList ([string[]]$Case.reopen_arguments) -WorkingDirectory $Case.working_directory `
    -UsagePath (Join-Path $RunDirectory "logs/$Phase.$name.reopen.usage.json") `
    -RedirectStandardOutput $reopenLog -RedirectStandardError (Join-Path $RunDirectory "logs/$Phase.$name.reopen.stderr.log")
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
try{
  $lease=Enter-HostResourceStage -Role GATE -Stage prepare -Budget (Get-HostResourceBudget -Role GATE -Stage prepare) -RunId $RunId
  $package=New-RunPackage -Python $Python -RepoRoot $RepoRoot -ArtifactRoot (Join-Path $ArtifactRoot 'projects/instrument_assembly') `
    -RunId $RunId -Project $project -Mode $consumer -Software $software -RetentionContractEnabled -RetentionClass solver_review `
    -RetentionReason $reason -CapacityLedgerLifecycleEnabled -CapacityLedgerArtifactRoot $ArtifactRoot `
    -UseShortExecutionPath -AdditionalDirectories @('simion','comsol')
  $capacity=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -ArtifactRoot $ArtifactRoot `
    -RunDirectory $package.artifact_run_dir -CommittedNewBytes 0 -Owner ('paired-pulse:'+$RunId)
  $stage='freeze_inputs'
  $requestPath=Copy-VerifiedRunInput -Source $Request -Destination (Join-Path $package.input_dir 'request.json')
  $frozen=Freeze-ConsumerDependencies -RepoRoot $RepoRoot -ContractPath (Join-Path $RepoRoot 'integrations/config/runtime_dependencies.json') `
    -InputDir $package.input_dir -OwnerId $project -ConsumerId $consumer
  $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  $config.inputs.code_inventory=$frozen.code_inventory_path;$config.inputs.dependency_contract=$frozen.dependency_contract_path
  $config.parameters=@{workflow=$consumer;request_source_path=$Request;dry_run=[bool]$DryRun;solver_authorized=[bool]$SolverAuthorized}
  Write-RunJson -Path $package.run_config -Depth 100 -Value $config
  $planPath=Join-Path $package.artifact_run_dir 'inputs/pulse/paired_accelerator_pulse_plan.json'
  $stage='prepare_pulse'
  $plan=Invoke-PulsePython 'print(json.dumps(prepare(Path(sys.argv[1]),Path(sys.argv[2]),source_base_dir=Path(sys.argv[3]))))' `
    @($requestPath,(Join-Path $package.artifact_run_dir 'inputs/pulse'),(Split-Path -Parent $Request))
  Write-RunJson -Path (Join-Path $package.result_dir 'preparation_receipt.json') -Depth 100 -Value @{
    schema_version=1;role='paired_accelerator_pulse_preparation';status='success';native_executed=$false;plan=$planPath;particle_count=$plan.particle_count}
  if(-not$DryRun){
    $stage='execution_budget'
    $budgetPath=Copy-VerifiedRunInput -Source $ExecutionBudgetPath -Destination (Join-Path $package.input_dir 'execution_budget.json')
    $budget=Get-Content -LiteralPath $budgetPath -Raw|ConvertFrom-Json -AsHashtable -Depth 100
    if([long]$budget.committed_new_bytes-le0){throw 'Positive explicit committed_new_bytes required.'}
    foreach($name in @('wall_clock_seconds','transient_run_directory_bytes','process_tree_working_set_bytes','minimum_system_available_memory_bytes','compact_final_retained_bytes')){
      if([long]$budget.limits[$name]-le0){throw "Positive public process limit required: $name"}
    }
    $savedParticle=''
    $completed=@{particle_model=$null;particle_exports=$null;simion_baseline=$null;simion_replay=$null}
    if($PredecessorManifest){
      $stage='consume_completed_stages'
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
      $stage='published_field_metadata'
      $cacheManifest=Invoke-PulsePython 'from common.simion.pa_family_cache import validate_pa_family_cache_generation;print(json.dumps(validate_pa_family_cache_generation(Path(sys.argv[1]),expected_cache_key=sys.argv[2],expected_filenames=["paired_static_on.pa"],verify_payload=False)))' `
        @($generation,$fieldKey)
      $members=@($cacheManifest.files|Where-Object name -eq 'paired_static_on.pa')
      if($members.Count-ne1){throw 'Published OA field must bind one paired_static_on.pa member.'}
      $protected+=@($generation)
      $update=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity `
        -RemainingCommittedNewBytes ([long]$budget.committed_new_bytes) -ProtectedPaths $protected -ProtectedCacheKeys @($fieldKey)
      $capacity=$update.session
      $stage='protect_published_field'
      $guard=Protect-ImmutablePaSource -Source $fieldPa -ExpectedBytes $members[0].bytes -ExpectedSha256 $members[0].sha256
      $paGuards+=@([string]$guard.path)
      if(-not$SimionExe){$SimionExe=Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe'}
      $SimionExe=(Resolve-Path -LiteralPath $SimionExe).Path
      Register-PulseInputs
      Exit-HostResourceStage -Lease $lease;$lease=$null
      $lease=Enter-HostResourceStage -Role SIMION -Stage flight -Budget $budget.host_budgets.simion_flight -RunId $RunId
      if(-not$reusedBaseline){
        $seed=Join-Path $frozen.execution_root 'common/simion/assets/iob_instance_seeds/1_instance_seed.iob'
        $runtimeInputs=@('--plan',$planPath,'--code-root',$frozen.execution_root,'--field-pa',$fieldPa,'--seed-iob',$seed)
        $continuationArguments=@{}
        if($PredecessorManifest){
          $stage='simion_unit_continuation'
          $continuation=Invoke-PulsePython 'print(json.dumps(materialize_simion_continuation(Path(sys.argv[1]),Path(sys.argv[2]),json.loads(Path(sys.argv[3]).read_text(encoding="utf-8-sig")),code_root=Path(sys.argv[4]),field_pa=Path(sys.argv[5]),seed_iob=Path(sys.argv[6]))))' `
            @($planPath,$package.artifact_run_dir,$stagesPath,$frozen.execution_root,$fieldPa,$seed)
          if($null-ne$continuation){
            $continuationArguments=@{FixedDispatchPlanPath=$continuation.fixed_dispatch_plan_path;ContinuationPlanPath=$continuation.continuation_plan_path;ContinuationWorkbench=$continuation.workbench}
            $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable -Depth 100
            $config.inputs.simion_whole_unit_continuation=$continuation.continuation_record.path
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
        $stage='simion_flight'
        $workbench=Invoke-FrontendFlightPhase -RunDirectory $package.artifact_run_dir -ProjectRunsRoot (Split-Path -Parent $package.artifact_run_dir) `
          -RepoRoot $frozen.execution_root -Python $Python -RuntimeModule integrations.workflows.paired_accelerator_pulse.runtime `
          -SimionExe $SimionExe -Limits ([pscustomobject]$budget.limits) -Phase pulse -RuntimeInputArguments $runtimeInputs -WorkbenchReceiptPath $workbenchPath `
          -IobVerification ${function:Confirm-PulseIobVerification} @continuationArguments
        if(@($workbench.native_process_records).Count){$nativeExecuted=$true}
        Write-RunJson -Path $workbenchPath -Depth 100 -Value $workbench
        $lease=Update-HostResourceStage -Lease $lease -Stage postprocess -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
        $stage='collect_baseline'
        $null=Invoke-PulsePython 'print(json.dumps(collect_simion_batches(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]),phase="baseline")))' `
          @($planPath,$workbenchPath,$package.artifact_run_dir)
      }
      if(-not$reusedReplay){
        $stage='default_replay'
        $specifications=@(foreach($case in $workbench.batches){
          $case|Add-Member -NotePropertyName default_replay_stdout -NotePropertyValue (Join-Path $package.artifact_run_dir ('logs/'+$case.case_id+'.replay.stdout.log')) -Force
          $case|Add-Member -NotePropertyName default_replay_stderr -NotePropertyValue (Join-Path $package.artifact_run_dir ('logs/'+$case.case_id+'.replay.stderr.log')) -Force
          $replayCase=$case|ConvertTo-Json -Depth 100|ConvertFrom-Json -AsHashtable -Depth 100
          $replayCase.stdout=$case.default_replay_stdout;$replayCase.stderr=$case.default_replay_stderr
          New-FrontendFlightSpecification -Case ([pscustomobject]$replayCase) -SimionExe $SimionExe
        })
        Write-RunJson -Path $workbenchPath -Value $workbench -Depth 100
        $lease=Update-HostResourceStage -Lease $lease -Stage flight -Budget $budget.host_budgets.simion_flight -RetainedMemoryBytes 0
        $replay=Invoke-ResourceBudgetedProcesses -DispatchPlanPath $dispatchPath `
          -RunDir $package.artifact_run_dir -UsagePath (Join-Path $package.result_dir 'pulse_replay.resource_usage.json') -ProcessSpecifications $specifications
        if($replay.resource_budget_exceeded-or@($replay.processes|Where-Object exit_code -ne 0).Count){throw 'Pulse saved-default replay failed.'}
        if($specifications.Count){$nativeExecuted=$true}
        Complete-ResourceUsage -RunDir $package.artifact_run_dir -UsagePath (Join-Path $package.result_dir 'pulse_replay.resource_usage.json')|Out-Null
        $lease=Update-HostResourceStage -Lease $lease -Stage postprocess -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
        $stage='collect_replay'
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
      $stage='comsol_particle_task'
      $tasks=Invoke-PulsePython 'print(json.dumps(materialize_comsol_task(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]),saved_particle_model=Path(sys.argv[4]) if sys.argv[4] else None)))' `
        @($planPath,(Join-Path $package.artifact_run_dir 'comsol'),$frozen.execution_root,$savedParticle)
      $stage='verify_native_model'
      $model=if($savedParticle){$completed.particle_model}else{$plan.model}
      $null=Invoke-PulsePython 'from common.contracts.verify_run_manifest import verify_record; verify_record("native pulse model",json.loads(sys.argv[1]));print("{}")' `
        @(($model|ConvertTo-Json -Depth 100 -Compress))
      Register-PulseInputs
      Exit-HostResourceStage -Lease $lease;$lease=$null
      $stage='comsol_particles';$nativeExecuted=$true
      & (Join-Path $RepoRoot 'common/comsol/run_comsol_r2025b.ps1') -TaskScript $tasks.matlab `
        -ReportPath (Join-Path $package.artifact_run_dir 'logs/comsol_bootstrap.txt') -ResourceBudgets $budget.host_budgets.comsol -RunId $RunId `
        -Limits ([pscustomobject]$budget.limits) -RunDir $package.artifact_run_dir -UsagePath (Join-Path $package.artifact_run_dir 'logs/comsol.resource_usage.json')
      if($LASTEXITCODE-ne0){throw 'COMSOL particle execution/export failed; raw saved particle model and native facts are retained.'}
    }
    $stage='diagnostic_comparison'
    $null=Invoke-PulsePython 'from integrations.analysis.compare_paired_accelerator_pulse import compare_paired_accelerator_pulse;print(json.dumps(compare_paired_accelerator_pulse(*map(Path,sys.argv[1:]))))' `
      @($planPath,(Join-Path $package.artifact_run_dir 'comsol/paired_pulse_particles.csv'),(Join-Path $package.result_dir 'simion_pulse_baseline.csv'),(Join-Path $package.result_dir 'comparison'))
  }
  $stage='terminal_publication'
  if($lease){Exit-HostResourceStage -Lease $lease;$lease=$null}
  Register-PulseInputs
  Write-RunJson -Path $package.summary -Value @{
    schema_version=1;role='paired_accelerator_pulse_summary';status='success';dry_run=[bool]$DryRun
    native_executed=$nativeExecuted;particle_count=$plan.particle_count;reused_particle_solution=$reusedParticleSolution;reused_simion_baseline=$reusedBaseline;reused_simion_replay=$reusedReplay;reused_particle_exports=$reusedParticleExports
    qualification='declared_OA_scope_only__no_numerical_equivalence_GUI_or_Formal_qualification'}
  $null=Apply-RunArtifactRetention -Python $Python -RepoRoot $RepoRoot -RunConfig $package.run_config
  $outputs=@(Get-ChildItem $package.result_dir,$package.log_dir,(Join-Path $package.artifact_run_dir 'comsol'),(Join-Path $package.artifact_run_dir 'simion') -Recurse -File|ForEach-Object FullName)+@($package.summary)
  Write-VerifiedRunManifest -Python $Python -RepoRoot $RepoRoot -RunConfig $package.run_config -Status success -Outputs $outputs -Software $software -DeferCapacityFinalization
  $terminalized=$true
}catch{
  $failure=$_
  if($lease){try{Exit-HostResourceStage -Lease $lease}catch{Write-Warning "Pulse stage release failed: $_"};$lease=$null}
  if($package-and-not$terminalized){
    $nativeOutputs=@(Get-ChildItem (Join-Path $package.artifact_run_dir 'comsol'),(Join-Path $package.artifact_run_dir 'simion') -Recurse -File|ForEach-Object FullName)
    Complete-FailedRun -Python $Python -RepoRoot $RepoRoot -RunConfig $package.run_config -Summary $package.summary `
      -SummaryRole paired_accelerator_pulse_summary -Reason $failure.Exception.Message -FailureStage $stage `
      -Software $software -AdditionalOutputs $nativeOutputs -DeferCapacityFinalization
    $terminalized=$true
  }
  throw $failure
}finally{
  $cleanupFailure=$null
  foreach($source in $paGuards){try{Unprotect-ImmutablePaSource -Source $source}catch{$cleanupFailure=$_;Write-Warning "Pulse PA guard release failed: $_"}}
  if($capacity){try{$null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity}catch{$cleanupFailure=$_;Write-Warning "Pulse capacity release failed: $_"}}
  if($package-and$terminalized){
    try{
      &$Python -B -m common.contracts.run_capacity_lifecycle --action seal-stopped-payload --artifact-root $ArtifactRoot `
        --run-config $package.run_config --owner $project --confirm-writing-stopped --retention-reason $reason
      if($LASTEXITCODE-ne0){throw 'Pulse stopped-payload sealing failed; published scientific terminal retained.'}
    }catch{$cleanupFailure=$_;Write-Warning "Pulse stopped payload sealing failed: $_"}
  }
  if($package){try{Remove-RunPackageExecutionAlias -Package $package}catch{$cleanupFailure=$_;Write-Warning "Pulse alias cleanup failed: $_"}}
  if($cleanupFailure-and-not$failure){throw $cleanupFailure}
}
