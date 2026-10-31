<# Private process/lifecycle adapter; scientific input and analysis stay in Python. #>
[CmdletBinding(DefaultParameterSetName='Run')]
param(
  [Parameter(ParameterSetName='Run')][string]$CaseDirectory='',
  [Parameter(ParameterSetName='Run')][string]$SimionExe='',
  [Parameter(ParameterSetName='Run')][string]$NumericsPath='',
  [Parameter(ParameterSetName='Run')][int]$TrajectoryQuality=8,
  [Parameter(ParameterSetName='Run')][double]$Regularization=0.0001,
  [Parameter(ParameterSetName='Run')][string]$ContinuationPredecessorManifestPath='',
  [Parameter(ParameterSetName='Run')][int]$ParticleCount=1000,
  [string]$RunId='', [string]$ResultPath='', [string]$PythonExe='',
  [Parameter(Mandatory,ParameterSetName='Resume')][switch]$ResumeFinalization
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repoRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../..'))
$project='single_reflection_oa_tof_mass_analyzer'
$python=if($PythonExe){(Resolve-Path -LiteralPath $PythonExe).Path}elseif($env:SIMULATION_PYTHON_EXE){
  (Resolve-Path -LiteralPath $env:SIMULATION_PYTHON_EXE).Path
}else{Join-Path $repoRoot '.venv/Scripts/python.exe'}
. (Join-Path $repoRoot 'common/paths/workspace_paths.ps1')
$pathContext=$null;$artifactRoot='';$projectArtifacts=''
if(-not($ResumeFinalization-and$ResultPath)){
  $pathContext=Resolve-WorkspacePaths -SourceRoot $repoRoot -Python $python
  $artifactRoot=[string]$pathContext.artifact_root
  $projectArtifacts=Join-Path $artifactRoot ('projects/'+$project)
}
$environmentNames=@('SIMULATION_PYTHON_EXE','PYTHONDONTWRITEBYTECODE','MASS_SPECTROMETRY_ARTIFACT_ROOT','MASS_SPECTROMETRY_EXECUTION_ROOT','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH')
$originalEnvironment=@{}
foreach($name in $environmentNames){$originalEnvironment[$name]=[Environment]::GetEnvironmentVariable($name,'Process')}
try {
if($null-ne$pathContext){
  $env:MASS_SPECTROMETRY_ARTIFACT_ROOT=[string]$pathContext.artifact_root
  $env:MASS_SPECTROMETRY_EXECUTION_ROOT=[string]$pathContext.execution_root
  $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=[string]$pathContext.host_resource_state_path
}
$env:SIMULATION_PYTHON_EXE=$python
# Every child imports the immutable frozen tree; it must not add bytecode files.
$env:PYTHONDONTWRITEBYTECODE='1'
. (Join-Path $repoRoot 'common/contracts/run_artifact_workflow.ps1') `
  -ResultPath $ResultPath -ResumeFinalization:$ResumeFinalization
$module='projects.single_reflection_oa_tof_mass_analyzer.workflows.reflectron_voltage_compensation.run_compensation'
if($ResumeFinalization){
  if(-not$RunId){throw 'ResumeFinalization requires the original RunId.'}
  if(-not$ResultPath){$ResultPath=Join-Path $projectArtifacts ('scratch/workflow_results/'+$RunId+'/result.json')}
  $prior=Get-Content -LiteralPath $ResultPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($prior.role-cne'run_artifact_workflow_result'-or-not$prior.run_directory-or
      -not[IO.Path]::IsPathFullyQualified([string]$prior.run_directory)-or
      (Split-Path -Leaf ([string]$prior.run_directory))-cne$RunId){throw 'Compensation Result RunId binding differs.'}
  $request=Join-Path ([string]$prior.run_directory) 'inputs/execution_request.json'
  $frozenRequest=Get-Content -LiteralPath $request -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  if($frozenRequest.package.run_id-cne$RunId-or$frozenRequest.package.project-cne$project-or
      $frozenRequest.package.mode-cne'reflectron_voltage_compensation'){throw 'Compensation Result owner binding differs.'}
  $outcome=Invoke-RunArtifactWorkflow -RequestPath $request -ResultPath $ResultPath -ResumeFinalization
  if($outcome.status-ne'success'){throw "Compensation finalization status: $($outcome.status)"}
  return
}
if(-not$CaseDirectory){throw 'CaseDirectory is required.'}
if(-not$RunId){$RunId=(Get-Date -Format 'yyyyMMdd_HHmmss')+'__sim__simion__reflectron-compensation'}
if(-not$SimionExe){$SimionExe=Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe'}
$script:run='';$script:codeRoot=$repoRoot;$script:owner=$null;$script:capacity=$null;$script:lease=$null
$script:materialized=$false;$script:iobReady=$false;$script:writersStopped=$true;$script:stage='inspect'
$script:releaseAttempted=$false;$script:releaseConfirmed=$false
$script:operations=[ordered]@{}
$script:readers=[Collections.Generic.List[object]]::new();$script:controlGuards=[Collections.Generic.List[object]]::new()
$clock=[Diagnostics.Stopwatch]::StartNew();$phaseClock=[Diagnostics.Stopwatch]::StartNew();$timings=[ordered]@{}
$failure=$null;$finalizationFailure=$null;$package=$null;$science=@{}
function Set-CompensationStage([string]$Name){
  if(-not$timings.Contains($script:stage)){$timings[$script:stage]=0.0}
  $timings[$script:stage]+=$phaseClock.Elapsed.TotalSeconds;$phaseClock.Restart();$script:stage=$Name
  Write-Host "COMPENSATION_STAGE=$Name RUN=$($script:run)"
}
function Invoke-CompensationAction([string]$Action,[string[]]$Arguments=@()){
  $argsForPython=@('-B','-m',$module,'--action',$Action)
  if($Action-ne'inspect'){$argsForPython+=@('--run',$script:run)}
  $output=Invoke-RunToolRootContext -RepoRoot $script:codeRoot -Operation {
    & $python @argsForPython @Arguments
    if($LASTEXITCODE-ne0){throw "Compensation $Action failed (exit $LASTEXITCODE)."}
  }
  return (($output-join"`n")|ConvertFrom-Json -Depth 100)
}
function Register-CompensationInputs {
  $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
  foreach($name in @('compensation_plan.json','source_closure.json','source_manifest.json',
      'source_runtime_receipt.json','source_runtime_geometry.json','source_build_completion.json',
      'source.ion','source_case_resolved_geometry.json','candidate_resolved_geometry.json',
      'candidate_baseline.json','candidate_science_mode.json','candidate_solver_numerics.json',
      'component_pa_plan.json','source_template.iob','source_template.con','flight_identity.json',
      'oatof_ideal_grounded.lua','reflectron_voltage_profile.lua')){
    $path=Join-Path $package.input_dir $name
    if(Test-Path -LiteralPath $path -PathType Leaf){$config.inputs[$name.Replace('.','_')]=$path}
  }
  foreach($name in @('source_closure','derivation')){
    $path=Join-Path $package.input_dir ('predecessor_source_closure/'+$name+'.json')
    if(Test-Path -LiteralPath $path -PathType Leaf){$config.inputs['predecessor_'+$name]=$path}
  }
  Write-RunJson -Path $package.run_config -Value $config -Depth 100
}
function Add-CompensationOperation([string]$Name,$Record){
  if($null-eq$Record.exit_code-or-not$Record.root_process_id-or-not$Record.root_process_started_at_utc_ticks){
    throw 'Native process completion lacks its observed identity.'
  }
  $fact=@{operation_id=$Name;observation=@{exit_confirmed=$true;returncode=[int]$Record.exit_code;
    process_id=[int]$Record.root_process_id;process_started_at_utc_ticks=[long]$Record.root_process_started_at_utc_ticks};
    resource_release_id='simion'}
  if($script:operations.Contains($Name)){
    if(($script:operations[$Name]|ConvertTo-Json -Compress)-cne($fact|ConvertTo-Json -Compress)){
      throw 'Native operation has conflicting observed completion.'
    }
  }else{$script:operations[$Name]=$fact}
}
function Add-CompensationProducerCompletion($Completion){
  $confirmed=$Completion.writers_stopped-eq$true
  $script:writersStopped=$false
  if(-not$confirmed){throw 'Component producer writer completion is unconfirmed.'}
  $writer=$Completion.writer_completion
  foreach($release in $writer.resource_releases){
    $hostRelease=$release.completion_receipt.host_release
    if($hostRelease.inherited-ne$true-or$hostRelease.token-cne$script:lease.token-or
       $null-ne$hostRelease.result-or
       $null-ne$hostRelease.error){throw 'Component producer did not return the inherited SIMION token.'}
  }
  foreach($operation in $writer.operations){
    if($operation.observation.exit_confirmed-ne$true){
      $script:writersStopped=$false;throw 'Component producer operation completion is unconfirmed.'
    }
    if(@($writer.resource_releases|Where-Object{$_.release_id-ceq$operation.resource_release_id}).Count-ne1){
      throw 'Component producer operation lacks its exact inherited release receipt.'
    }
    Add-CompensationOperation ('producer.'+$operation.operation_id) ([pscustomobject]@{
      exit_code=$operation.observation.returncode;root_process_id=$operation.observation.process_id;
      root_process_started_at_utc_ticks=$operation.observation.process_started_at_utc_ticks})
  }
  $script:writersStopped=$true
  # The child only returned an inherited grant. Its worker facts use our one
  # outer release ID; publishing that same token twice would invent a release.
}
function Invoke-CompensationSafeProducer {
  Set-CompensationStage field_provider
  $script:lease=Enter-HostExecutionLease -Role SIMION -Stage pa_refine -StatePath $pathContext.host_resource_state_path
  $capacityPath=Join-Path $script:run 'results/producer_capacity_session.json'
  Write-RunJson -Path $capacityPath -Value $script:capacity -Depth 100
  $context=(Get-FileHash -LiteralPath $script:owner.request_path -Algorithm SHA256).Hash.ToLowerInvariant()
  $specification=Invoke-CompensationAction producer-spec @('--capacity-session',$capacityPath,'--context-sha256',$context)
  $parameters=@{};foreach($property in $specification.parameters.PSObject.Properties){$parameters[$property.Name]=$property.Value}
  $previousEnvironment=@{}
  foreach($property in $specification.environment.PSObject.Properties){
    $previousEnvironment[$property.Name]=[Environment]::GetEnvironmentVariable($property.Name,'Process')
    [Environment]::SetEnvironmentVariable($property.Name,[string]$property.Value,'Process')
  }
  $producerFailure=$null;$receiptFailure=$null;$completion=$null
  $script:writersStopped=$false
  try{
    Invoke-RunToolRootContext -RepoRoot $script:codeRoot -Operation {
      & ([string]$specification.script_path) @parameters|Out-Host
    }
  }catch{$producerFailure=$_}finally{
    foreach($name in $previousEnvironment.Keys){[Environment]::SetEnvironmentVariable($name,$previousEnvironment[$name],'Process')}
    try{
      $completion=Invoke-CompensationAction producer-complete @('--context-sha256',$context)
      Add-CompensationProducerCompletion $completion
    }catch{$receiptFailure=$_}
  }
  if($null-ne$producerFailure){
    if($null-ne$receiptFailure){$producerFailure.Exception.Data['compensation_producer_completion_error']=[string]$receiptFailure}
    throw $producerFailure
  }
  if($null-ne$receiptFailure){throw $receiptFailure}
  if($completion.failure_reason){throw ('Component producer failed: '+$completion.failure_reason)}
  if(-not$completion.runtime_prepared-or-not$completion.iob_ready){throw 'Component producer did not verify its private runtime and IOB.'}
  $expectedControls=@{iob_path=(Join-Path $script:run 'simion/oatof_ideal_grounded.iob');
    program_path=(Join-Path $script:run 'simion/oatof_ideal_grounded.lua');
    source_ion_path=(Join-Path $script:run 'inputs/source.ion')}
  foreach($name in $expectedControls.Keys){
    $actual=[string]$completion.control_binding.$name
    if(-not$actual-or[IO.Path]::GetFullPath($actual)-ine$expectedControls[$name]-or
       -not(Test-Path -LiteralPath $actual -PathType Leaf)){throw 'Component producer IOB/Program/source binding differs.'}
  }
  $script:materialized=$true;$script:iobReady=$true
  Register-CompensationInputs
  $script:lease=Update-HostResourceStage -Lease $script:lease -Stage prepare `
    -Budget (Get-HostResourceBudget -Role SIMION -Stage prepare) -RetainedMemoryBytes 0
}
function Initialize-CompensationRuntime {
  if($script:materialized){return}
  Set-CompensationStage materialize
  if($null-eq$plan.producer){
    throw 'Compensation native execution requires an explicit safe producer intent; supply NumericsPath and manifest-bound standalone response providers through the existing producer.'
  }
  Invoke-CompensationSafeProducer
}
function Invoke-CompensationNative($Specification){
  $paths=@([string]$Specification.working_directory,[string]$Specification.stdout_path,[string]$Specification.stderr_path)+@($Specification.argument_list|Where-Object{[IO.Path]::IsPathFullyQualified([string]$_)})
  $native=Get-RunNativeExecutionContext -Package $package -Paths $paths -Tool SIMION
  $nativeArguments=Project-RunPath -Paths ([string[]]$Specification.argument_list) -ArtifactRunDir $package.artifact_run_dir -RunDir $native.run_dir -Python $python
  $script:writersStopped=$false
  try{
    $record=Invoke-ResourceBudgetedProcess -Limits $null -RunDir $script:run `
      -UsagePath (Join-Path $script:run ('results/'+$Specification.name+'.usage.json')) `
      -FilePath $Specification.file_path -ArgumentList $nativeArguments `
      -WorkingDirectory $native.projected_paths[0] -Environment $native.environment `
      -RedirectStandardOutput $native.projected_paths[1] -RedirectStandardError $native.projected_paths[2]
    $script:writersStopped=$true;Add-CompensationOperation $Specification.name $record
    if($record.resource_budget_exceeded-or[int]$record.exit_code-ne0){throw "Native $($Specification.name) failed."}
  }catch{
    $data=$_.Exception.Data
    if($data.Contains('observed_process_exit_confirmed')){
      $script:writersStopped=[bool]$data['observed_process_exit_confirmed']
      if($script:writersStopped){Add-CompensationOperation $Specification.name ([pscustomobject]@{
        exit_code=$data['observed_process_returncode'];root_process_id=$data['observed_process_id'];
        root_process_started_at_utc_ticks=$data['observed_process_started_at_utc_ticks']})}
    }
    throw
  }
}
function Convert-CompensationBatch($Batch){
  $paths=@([string]$Batch.working_directory,[string]$Batch.stdout_path,[string]$Batch.stderr_path)+@($Batch.argument_list|Where-Object{[IO.Path]::IsPathFullyQualified([string]$_)})
  $native=Get-RunNativeExecutionContext -Package $package -Paths $paths -Tool SIMION
  $environment=@{};foreach($property in $Batch.environment.PSObject.Properties){$environment[$property.Name]=[string]$property.Value}
  foreach($name in $native.environment.Keys){$environment[$name]=$native.environment[$name]}
  return [pscustomobject]@{name=$Batch.name;file_path=$Batch.file_path;
    argument_list=(Project-RunPath -Paths ([string[]]$Batch.argument_list) -ArtifactRunDir $package.artifact_run_dir -RunDir $native.run_dir -Python $python);
    working_directory=$native.projected_paths[0];stdout=$native.projected_paths[1];stderr=$native.projected_paths[2];
    environment=$environment;scheduler_batch=$Batch.batch}
}
try{
  $inspect=@('--case-dir',$CaseDirectory,'--simion-exe',$SimionExe,'--trajectory-quality',[string]$TrajectoryQuality,
    '--regularization',$Regularization.ToString('R',[Globalization.CultureInfo]::InvariantCulture),
    '--particle-count',[string]$ParticleCount)
  if($ContinuationPredecessorManifestPath){$inspect+=@('--resume-from',$ContinuationPredecessorManifestPath)}
  if($NumericsPath){$inspect+=@('--numerics-path',$NumericsPath)}
  $plan=Invoke-CompensationAction inspect $inspect
  $parents=@([string]$plan.source_run)
  if($null-ne$plan.predecessor_manifest){$parents+=Split-Path -Parent $plan.predecessor_manifest.path}
  foreach($parent in @($parents|Sort-Object -Unique)){
    $script:readers.Add((Enter-RunTerminalConsumptionGuard -RunDirectory $parent))
  }
  Set-CompensationStage capacity
  $canonicalRun=Join-Path $projectArtifacts ('runs/'+$RunId)
  $script:capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifactRoot `
    -RunDirectory $canonicalRun -CommittedNewBytes ([long]$plan.committed_new_bytes) -ProtectedPaths $parents `
    -ProtectedCacheKeys @($plan.protected_cache_keys) -Owner ('run-artifact-workflow:'+ $project+':'+$RunId)
  $package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $projectArtifacts -RunId $RunId `
    -Project $project -Mode reflectron_voltage_compensation -Software @('SIMION 2020','Python 3.11') `
    -RetentionContractEnabled -RetentionClass solver_review -RetentionReason 'Retain fixed-source three-arm compensation and complete batch recovery evidence.' `
    -CapacityLedgerLifecycleEnabled -AdditionalDirectories @('simion') -PathContext $pathContext
  $script:run=[IO.Path]::GetFullPath($package.artifact_run_dir)
  $planPath=Join-Path $package.input_dir 'compensation_plan.json'
  Write-RunJson -Path $planPath -Value $plan -Depth 100
  $entry=Join-Path $package.input_dir 'execute_compensation.ps1';$entryIdentity=$null
  Copy-VerifiedRunInput -Source $PSCommandPath -Destination $entry -VerifiedIdentity ([ref]$entryIdentity)|Out-Null
  $script:owner=Initialize-RunArtifactPowerShellOwner -Python $python -RepoRoot $repoRoot -Package $package `
    -CapacitySession $script:capacity -ResultPath $ResultPath -EntrypointPath $entry `
    -EntrypointRecord @{path=$entryIdentity.path;exists=$true;bytes=$entryIdentity.bytes;sha256=$entryIdentity.sha256} `
    -CommitmentInputPaths @($planPath) -Software @('SIMION 2020','Python 3.11')
  Set-CompensationStage freeze
  $frozen=Invoke-CompensationAction freeze
  $script:codeRoot=[string]$frozen.frozen_code_root;Register-CompensationInputs
  if($frozen.basis_export_required){
    Initialize-CompensationRuntime
    Set-CompensationStage basis_export
    Invoke-CompensationNative (Invoke-CompensationAction export-spec)
  }
  Set-CompensationStage fit
  $fitted=Invoke-CompensationAction fit;Register-CompensationInputs
  if($fitted.native_fly_required){
    Initialize-CompensationRuntime
    if(-not$script:iobReady){throw 'The safe producer must verify its private IOB before Fly.'}
    # The workbench builder saves its Program sidecar. Freeze controls only
    # after that writer has exited, before any of the three Fly arms starts.
    foreach($name in @('oatof_ideal_grounded.lua','reflectron_voltage_profile.lua')){
      $script:controlGuards.Add([IO.File]::Open((Join-Path $script:run ('simion/'+$name)),
        [IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read))
    }
    $script:lease=Update-HostResourceStage -Lease $script:lease -Stage flight `
      -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes ([Diagnostics.Process]::GetCurrentProcess().WorkingSet64)
  }
  foreach($mode in $fitted.modes){
    $label=[string]$mode.label;$dispatch=[string]$mode.dispatch_plan
    Set-CompensationStage ('fly_'+$label)
    $initial=Invoke-CompensationAction materialize-batches @('--label',$label,'--dispatch-plan',$dispatch)
    if($mode.all_reused){continue}
    $preparedPlan=Get-Content -LiteralPath $dispatch -Raw|ConvertFrom-Json -Depth 100
    $missing=@($initial.batches|Where-Object{-not$_.reused})
    $formalIndex=$null;$first=$null;$replan=$null
    $recovered=$null-ne$preparedPlan.estimation.PSObject.Properties['recovered_missing_observation']-and
      [bool]$preparedPlan.estimation.recovered_missing_observation
    if($preparedPlan.estimation.kind-eq'formal_first_batch_observation'-or$recovered){
      $formalIndex=if($recovered){[int]$preparedPlan.estimation.observed_missing_batch_index}else{[int]$missing[0].batch.index}
      $selected=@($missing|Where-Object{[int]$_.batch.index-eq$formalIndex})
      if($selected.Count-ne1){throw 'Observed formal unit differs from the fixed missing partition.'}
      $first=Convert-CompensationBatch $selected[0]
      $replan={param($formal)
        $arguments=@('-B','-m','common.simion.resource_scheduler',$(if($recovered){'--recovered-missing-plan'}else{'--prepared-plan'}),$dispatch,
          '--output',$dispatch,'--observed-formal-peak-bytes',[string]$formal.observed_peak_process_tree_working_set_bytes,
          '--observed-formal-cpu-percent',[string]$formal.observed_process_cpu_percent,
          '--observed-background-cpu-percent',[string]$formal.observed_background_cpu_percent,
          '--available-memory-bytes',[string]$formal.available_memory_bytes,
          '--total-physical-memory-bytes',[string]$formal.total_physical_memory_bytes)
        if($formal.process_record.completed){$arguments+='--first-batch-completed'}
        Invoke-RunToolRootContext -RepoRoot $script:codeRoot -Operation {
          & $python @arguments|Out-Host;if($LASTEXITCODE-ne0){throw 'Compensation dispatch observation failed.'}
        }
      }
    }
    $prepareRemaining={param($formal)
      $materialized=Invoke-CompensationAction materialize-batches @('--label',$label,'--dispatch-plan',$dispatch)
      $pending=@($materialized.batches|Where-Object{-not$_.reused-and($null-eq$formalIndex-or[int]$_.batch.index-ne$formalIndex)}|
        ForEach-Object{Convert-CompensationBatch $_})
      [pscustomobject]@{pending=$pending}
    }
    $onCompleted={param($record)
      Add-CompensationOperation $record.name $record
      $processPath=Join-Path $script:run ('logs/'+$record.name+'.process.json')
      Write-RunJson -Path $processPath -Value @{completed=[bool]$record.completed;exit_code=$record.exit_code;
        root_process_id=$record.root_process_id;root_process_started_at_utc_ticks=$record.root_process_started_at_utc_ticks}
      $null=Invoke-CompensationAction complete-batch @('--label',$label,'--index',[string]$record.specification.scheduler_batch.index,'--process-record',$processPath)
    }
    $usage=Join-Path $script:run ('results/'+$label+'.resource_usage.json')
    $script:writersStopped=$false
    try{
      $wave=Invoke-SimionBatchPhase -DispatchPlanPath $dispatch -RunDir $script:run -UsagePath $usage `
        -FirstSpecification $first -Replan $replan -PrepareRemaining $prepareRemaining -OnProcessCompleted $onCompleted
      $script:writersStopped=-not[bool]$wave.resource_budget_exceeded
      if(-not$script:writersStopped-or@($wave.processes|Where-Object{[int]$_.exit_code-ne0}).Count){throw 'Compensation native Fly wave failed.'}
      Complete-ResourceUsage -RunDir $script:run -UsagePath $usage|Out-Null
      Invoke-RunToolRootContext -RepoRoot $script:codeRoot -Operation {
        & $python -B -m common.simion.resource_profile publish --run-id $RunId --resource-usage $usage `
          --dispatch-plan $dispatch --resource-usage-relative-path ('results/'+$label+'.resource_usage.json') `
          --dispatch-plan-relative-path ('results/'+$label+'.dispatch_plan.json') `
          --output (Join-Path $script:run ('results/'+$label+'.resource_profile.json'))|Out-Host
        if($LASTEXITCODE-ne0){throw 'Compensation resource profile publication failed.'}
      }
    }catch{
      if($_.Exception.Data.Contains('simion_wave_writer_completion_confirmed')){
        $script:writersStopped=[bool]$_.Exception.Data['simion_wave_writer_completion_confirmed']
      }
      throw
    }
  }
  Set-CompensationStage analyze
  $science=Invoke-CompensationAction analyze|ConvertTo-Json -Depth 100|ConvertFrom-Json -AsHashtable
}catch{$failure=$_;$failureStage=$script:stage}finally{
  if($null-ne$script:owner){
    try{
      Set-CompensationStage finalization
      $releases=[Collections.Generic.List[object]]::new()
      if($script:writersStopped-and$null-ne$script:lease){
        $lease=$script:lease;$token=[string]$lease.token
        $script:releaseAttempted=$true
        $release=Exit-HostResourceStage -Lease $lease -PassThru
        if($lease.inherited){
          if($null-ne$release){throw 'Inherited SIMION release returned an unexpected independent transaction.'}
        }elseif($null-eq$release-or$release.status-cne'released'-or$release.token-cne$token){
          throw 'SIMION release is unconfirmed.'
        }
        $script:releaseConfirmed=$true
        if($script:operations.Count){Add-RunArtifactResourceRelease -ResourceReleases $releases -ReleaseId 'simion' -Receipt @{host_release=@{
          inherited=[bool]$lease.inherited;token=$token;result=$release;error=$null}}}
        $script:lease=$null
      }
      $summary=@{};foreach($key in $science.Keys){$summary[$key]=$science[$key]}
      $summary.execution_status=if($null-ne$failure){'failed'}else{'completed'}
      $summary.data_validity=if($null-ne$failure){'incomplete'}else{'valid'}
      if(-not$summary.ContainsKey('scientific_result')){$summary.scientific_result='NOT_EVALUATED'}
      $summary.failure_stage=if($null-ne$failure){$failureStage}else{$null}
      $summary.failure_reason=if($null-ne$failure){$failure.Exception.Message}else{$null}
      $summary.recovery_action=if(-not$script:writersStopped){'inspect_writer_completion'}elseif($null-ne$failure){'new_run_with_explicit_predecessor'}else{'none'}
      $summary.phase_timings_seconds=$timings;$summary.total_elapsed_seconds=$clock.Elapsed.TotalSeconds
      $outputs=@(Get-ChildItem -LiteralPath $script:run -File -Recurse|Where-Object{
        $_.Name-notin@('run_config.json','run_manifest.json')-and-not$_.Name.StartsWith('.')
      }|ForEach-Object{$_.FullName})
      $null=Complete-RunArtifactPowerShellOwner -Context $script:owner -Status $(if($null-ne$failure){'failed'}else{'success'}) `
        -Summary $summary -OutputPaths $outputs -WriterCompletion @{operations=@($script:operations.Values);resource_releases=@($releases.ToArray())} `
        -WritersStopped $script:writersStopped -OriginalFailure $failure
      $script:capacity=$null
      Write-Host "COMPENSATION_RESULT=$($script:owner.result_path) TOTAL_SECONDS=$($clock.Elapsed.TotalSeconds)"
    }catch{
      $finalizationFailure=$_
      if($null-ne$failure){$failure.Exception.Data['compensation_finalization_error']=[string]$_;Write-Warning "Compensation finalization also failed: $_"}
      # The retained Result is the original CLI's recovery transport. Keep the
      # primary exception there and append the distinct finalization error.
      try{
        if(Test-Path -LiteralPath $script:owner.result_path -PathType Leaf){
          $retained=Get-Content -LiteralPath $script:owner.result_path -Raw|ConvertFrom-Json -AsHashtable
          if($retained.role-cne'run_artifact_workflow_result'){throw 'Unexpected compensation Result role.'}
          $secondary=if($retained.ContainsKey('secondary_errors')){@($retained.secondary_errors)}else{@()}
          if($null-ne$failure){$retained.exception=@{type=$failure.Exception.GetType().FullName;message=$failure.Exception.Message;notes=@()}}
          elseif($null-eq$retained.exception){$retained.exception=@{type=$finalizationFailure.Exception.GetType().FullName;message=$finalizationFailure.Exception.Message;notes=@()}}
          if($script:releaseAttempted-and-not$script:releaseConfirmed){
            $retained.execution_status='finalization_failed';$retained.failure_stage='host_release'
            $retained.recovery_action='inspect_release_without_refly'
          }elseif(-not$retained.ContainsKey('execution_status')){
            $retained.execution_status='finalization_failed';$retained.failure_stage='finalization'
            $retained.recovery_action='resume_finalization'
          }
          $retained.secondary_errors=@($secondary)+@($finalizationFailure.Exception.Message)
          Write-RunJson -Atomic -Path $script:owner.result_path -Value $retained -Depth 100
        }
      }catch{Write-Warning "Could not retain compensation finalization error: $_"}
    }
  }
  $cleanupErrors=[Collections.Generic.List[string]]::new()
  if($script:writersStopped-and(-not$script:releaseAttempted-or$script:releaseConfirmed)){
    foreach($guard in $script:controlGuards){try{$guard.Dispose()}catch{$cleanupErrors.Add('Control guard release: '+[string]$_)}}
    foreach($reader in $script:readers){try{$reader.Dispose()}catch{$cleanupErrors.Add('Source guard release: '+[string]$_)}}
    if($null-ne$script:lease-and-not$script:releaseAttempted){
      $script:releaseAttempted=$true
      try{Exit-HostResourceStage -Lease $script:lease|Out-Null}catch{$cleanupErrors.Add('Host release: '+[string]$_)}
    }
    if($null-ne$script:capacity-and$null-eq$script:owner){
      try{Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $script:capacity|Out-Null}
      catch{$cleanupErrors.Add('Capacity release: '+[string]$_)}
    }
  }
  if($cleanupErrors.Count){
    if($null-ne$failure){$failure.Exception.Data['compensation_cleanup_errors']=@($cleanupErrors.ToArray())}
    if($null-eq$finalizationFailure){$finalizationFailure=[Management.Automation.ErrorRecord]::new([Exception]::new($cleanupErrors[0]),'CompensationCleanupFailed',[Management.Automation.ErrorCategory]::CloseError,$null)}
    try{
      if($null-ne$script:owner-and(Test-Path -LiteralPath $script:owner.result_path -PathType Leaf)){
        $retained=Get-Content -LiteralPath $script:owner.result_path -Raw|ConvertFrom-Json -AsHashtable
        if($retained.role-cne'run_artifact_workflow_result'){throw 'Unexpected compensation Result role.'}
        if($null-ne$failure){$retained.exception=@{type=$failure.Exception.GetType().FullName;message=$failure.Exception.Message;notes=@()}}
          elseif($null-eq$retained.exception){$retained.exception=@{type=$finalizationFailure.Exception.GetType().FullName;message=$finalizationFailure.Exception.Message;notes=@()}}
          if($script:releaseAttempted-and-not$script:releaseConfirmed){
            $retained.execution_status='finalization_failed';$retained.failure_stage='host_release'
            $retained.recovery_action='inspect_release_without_refly'
          }elseif(-not$retained.ContainsKey('execution_status')){
            $retained.execution_status='finalization_failed';$retained.failure_stage='finalization'
            $retained.recovery_action='resume_finalization'
          }
        $secondary=if($retained.ContainsKey('secondary_errors')){@($retained.secondary_errors)}else{@()}
        $retained.secondary_errors=@($secondary)+@($cleanupErrors.ToArray())
        Write-RunJson -Atomic -Path $script:owner.result_path -Value $retained -Depth 100
      }
    }catch{Write-Warning "Could not retain compensation cleanup error: $_"}
  }
}
if($null-ne$failure){throw $failure}
if($null-ne$finalizationFailure){throw $finalizationFailure}

}finally{
  foreach($name in $environmentNames){[Environment]::SetEnvironmentVariable($name,$originalEnvironment[$name],'Process')}
}
