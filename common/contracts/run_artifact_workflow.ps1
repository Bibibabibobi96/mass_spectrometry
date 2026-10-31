<# Internal lifecycle adapter called by project workflow CLIs. #>
[CmdletBinding()]
param([string]$RequestPath='',[string]$ResultPath='',[switch]$ResumeFinalization)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$OutputEncoding=[Console]::OutputEncoding
. (Join-Path $PSScriptRoot 'run_artifact_support.ps1')
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'resource_budget_support.ps1')

function Assert-WorkflowFields {
  param($Value,[string[]]$Fields,[string]$Label)
  if($Value-isnot[Collections.IDictionary]-or
     @($Value.Keys|Where-Object{$_-notin$Fields}).Count-or
     @($Fields|Where-Object{-not$Value.Contains($_)}).Count){throw "$Label fields differ."}
}

function Assert-WorkflowFileRecord {
  param($Record,[string]$ExpectedPath='')
  Assert-WorkflowFields $Record @('path','exists','bytes','sha256') 'Workflow file record'
  if($Record.path-isnot[string]-or-not[IO.Path]::IsPathFullyQualified($Record.path)-or
     $Record.exists-isnot[bool]-or-not$Record.exists-or
     ($Record.bytes-isnot[long]-and$Record.bytes-isnot[int])-or$Record.bytes-lt0-or
     $Record.sha256-isnot[string]-or$Record.sha256-notmatch'^[0-9a-fA-F]{64}$'){
    throw 'Workflow file record is invalid.'
  }
  $path=[IO.Path]::GetFullPath($Record.path)
  if($ExpectedPath-and-not$path.Equals([IO.Path]::GetFullPath($ExpectedPath),[StringComparison]::OrdinalIgnoreCase)){
    throw 'Workflow file record path differs.'
  }
  $item=Get-Item -LiteralPath $path
  if($item.PSIsContainer-or$item.Length-ne$Record.bytes-or
     (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash-ine$Record.sha256){
    throw "Workflow file identity differs: $path"
  }
}

function Test-WorkflowPathWithin {
  param([string]$Path,[string]$Root)
  $rootPath=[IO.Path]::GetFullPath($Root).TrimEnd('\','/')
  $pathValue=[IO.Path]::GetFullPath($Path)
  return $pathValue.Equals($rootPath,[StringComparison]::OrdinalIgnoreCase)-or
    $pathValue.StartsWith($rootPath+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)
}

function New-WorkflowOwnerFileRecord {
  param([Parameter(Mandatory)][string]$Path)
  $actual=[IO.Path]::GetFullPath($Path);$item=Get-Item -LiteralPath $actual
  if($item.PSIsContainer){throw 'PowerShell owner evidence must be a file.'}
  return @{path=$actual;exists=$true;bytes=[long]$item.Length;sha256=(Get-FileHash -LiteralPath $actual -Algorithm SHA256).Hash}
}

function Convert-WorkflowOwnerPath {
  param([Collections.IDictionary]$Context,[string]$Path)
  $actual=[IO.Path]::GetFullPath($Path)
  $execution=[string]$Context.execution_run_directory
  if($execution-and(Test-WorkflowPathWithin $actual $execution)){
    return [IO.Path]::GetFullPath((Join-Path $Context.run_directory ([IO.Path]::GetRelativePath($execution,$actual))))
  }
  return $actual
}

function Initialize-RunArtifactPowerShellOwner {
  <# Bind an existing package/session to the public finalizer before native work.
     This does not create a second run, lease, executor or recovery state. #>
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RepoRoot,
    [Parameter(Mandatory)]$Package,[Parameter(Mandatory)]$CapacitySession,
    [string]$ResultPath='',[Parameter(Mandatory)][string]$EntrypointPath,
    $EntrypointRecord=$null,
    [Parameter(Mandatory)][string[]]$CommitmentInputPaths,[string[]]$Software=@(),
    [bool]$OwnCapacitySession=$true)
  $config=Get-Content -LiteralPath $Package.run_config -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $projectRoot=Join-Path (Join-Path ([string]$CapacitySession.artifact_root) 'projects') ([string]$config.project)
  $runRoot=[IO.Path]::GetFullPath((Join-Path $projectRoot ('runs/'+$config.run_id)))
  if(-not(Test-Path -LiteralPath $runRoot -PathType Container)){throw 'PowerShell owner package directory is missing.'}
  $paths=@{execution_run_directory=[IO.Path]::GetFullPath([string]$Package.run_dir);run_directory=$runRoot}
  $entry=Convert-WorkflowOwnerPath $paths $EntrypointPath
  if(-not(Test-WorkflowPathWithin $entry (Join-Path $runRoot 'inputs'))){throw 'PowerShell owner entrypoint must be frozen inside its inputs.'}
  $entryRecord=if($null-ne$EntrypointRecord){@{path=(Convert-WorkflowOwnerPath $paths $EntrypointRecord.path);
    exists=$EntrypointRecord.exists;bytes=$EntrypointRecord.bytes;sha256=$EntrypointRecord.sha256}}else{New-WorkflowOwnerFileRecord $entry}
  if([IO.Path]::GetFullPath([string]$entryRecord.path)-ine$entry-or-not$entryRecord.exists-or
     [long]$entryRecord.bytes-ne(Get-Item -LiteralPath $entry).Length-or[string]$entryRecord.sha256-notmatch'^[A-Fa-f0-9]{64}$'){
    throw 'Frozen PowerShell owner entrypoint record differs.'
  }
  $expectedOwner="run-artifact-workflow:{0}:{1}"-f$config.project,$config.run_id
  if($OwnCapacitySession-and[string]$CapacitySession.owner-cne$expectedOwner){throw 'PowerShell owner capacity session has another owner.'}
  if([string]$CapacitySession.status-cne'active'){throw 'PowerShell owner requires its actual active capacity session.'}
  if(-not$ResultPath){$ResultPath=Join-Path $projectRoot ('scratch/workflow_results/'+$config.run_id+'/result.json')}
  $ResultPath=[IO.Path]::GetFullPath($ResultPath)
  if(Test-WorkflowPathWithin $ResultPath $runRoot){throw 'PowerShell owner Result must remain outside its run.'}
  if(Test-Path -LiteralPath $ResultPath){throw 'PowerShell owner Result already exists; resume its original run.'}
  [IO.Directory]::CreateDirectory((Split-Path -Parent $ResultPath))|Out-Null
  $budgetInputs=@($CommitmentInputPaths|ForEach-Object{New-WorkflowOwnerFileRecord (Convert-WorkflowOwnerPath $paths $_)})
  if(-not$budgetInputs.Count){throw 'PowerShell owner requires its frozen budget authority.'}
  $request=[ordered]@{schema_version=1;role='run_artifact_workflow_request';repository_root=$RepoRoot;python_executable=$Python;
    package=[ordered]@{project=$config.project;run_id=$config.run_id;mode=$config.mode;artifact_project_root=$projectRoot;
      software=@($Software);retention_class=$config.artifact_retention.class;retention_reason=$config.artifact_retention.reason};
    capacity=[ordered]@{committed_new_bytes=[long]$CapacitySession.committed_new_bytes;commitment_inputs=$budgetInputs;
      protected_paths=@($CapacitySession.protected_paths);protected_cache_keys=@($CapacitySession.protected_cache_keys);
      ownership=$(if($OwnCapacitySession){'owned'}else{'inherited'});session_owner=[string]$CapacitySession.owner};
    prepared=[ordered]@{owner_kind='powershell';entrypoint=$entryRecord};payload=@{}}
  $requestPath=Join-Path $runRoot 'inputs/execution_request.json'
  if(Test-Path -LiteralPath $requestPath){throw 'PowerShell owner execution request already exists.'}
  Write-RunJson -Atomic -Path $requestPath -Value $request -Depth 64
  Write-RunJson -Atomic -Path (Join-Path $runRoot 'logs/capacity_session.json') -Value $CapacitySession -Depth 64
  foreach($name in @($config.inputs.Keys)){
    if($config.inputs[$name]-is[string]){
      $inputPath=[string]$config.inputs[$name]
      if(-not[IO.Path]::IsPathFullyQualified($inputPath)){$inputPath=Join-Path $paths.execution_run_directory $inputPath}
      $config.inputs[$name]=Convert-WorkflowOwnerPath $paths $inputPath
    }
  }
  $config.inputs.execution_request=$requestPath
  Write-RunJson -Atomic -Path (Join-Path $runRoot 'run_config.json') -Value $config -Depth 64
  Write-RunJson -Atomic -Path $ResultPath -Value @{schema_version=1;role='run_artifact_workflow_result';status='pending';
    stage='prepared';run_directory=$runRoot;execution_request=$requestPath;resume_action='inspect_writer_completion'} -Depth 64
  return @{python=$Python;repo_root=$RepoRoot;request_path=$requestPath;result_path=$ResultPath;
    run_directory=$runRoot;execution_run_directory=$paths.execution_run_directory;session=$CapacitySession;package=$Package;
    native_path_preparation=$Package.native_path_preparation;
    own_capacity_session=$OwnCapacitySession;completion_written=$false;finalized=$false;finalization_started=$false}
}

function Complete-RunArtifactPowerShellOwner {
  <# Persist actual stopped-writer facts, then invoke the existing finalizer. #>
  [CmdletBinding()]
  param([Parameter(Mandatory)][Collections.IDictionary]$Context,
    [Parameter(Mandatory)][ValidateSet('success','failed','interrupted')][string]$Status,
    [Parameter(Mandatory)][Collections.IDictionary]$Summary,
    [string[]]$OutputPaths=@(),[string[]]$RequiredOutputPaths=@(),[string[]]$RetentionPreservePaths=@(),
    [Parameter(Mandatory)][Collections.IDictionary]$WriterCompletion,
    [Parameter(Mandatory)][bool]$WritersStopped,$OriginalFailure=$null,
    [object[]]$ResourceUsagePaths=@(),$ResourceProfile=$null)
  $root=[string]$Context.run_directory
  # Native preparation may create or replace an execution alias after Initialize.
  if($Context.Contains('package')){$Context.execution_run_directory=[string]$Context.package.run_dir}
  $Summary.native_path_preparation=$Context.native_path_preparation
  if($Context.completion_written){throw 'PowerShell owner completion is already persisted; resume its original Result.'}
  $exception=if($null-ne$OriginalFailure){@{type=$OriginalFailure.Exception.GetType().FullName;message=$OriginalFailure.Exception.Message;notes=@()}}else{$null}
  Write-RunJson -Atomic -Path (Join-Path $root 'logs/capacity_session.json') -Value $Context.session -Depth 64
  if(-not$WritersStopped){
    $unknownReason=if($Summary.Contains('failure_reason')){$Summary.failure_reason}elseif($null-ne$OriginalFailure){$OriginalFailure.Exception.Message}else{'Native writer completion is unknown.'}
    $unknownRecovery=if($Summary.Contains('recovery_action')){$Summary.recovery_action}else{'inspect_writer_completion'}
    Write-RunJson -Atomic -Path $Context.result_path -Value @{schema_version=1;role='run_artifact_workflow_result';status='failed';
      stage='writer_completion';run_directory=$root;writers_confirmed=$false;resume_action=$unknownRecovery;
      execution_status=$(if($Summary.Contains('execution_status')){$Summary.execution_status}else{'writer_completion_unknown'});
      data_validity=$(if($Summary.Contains('data_validity')){$Summary.data_validity}else{'unknown'});
      scientific_result=$(if($Summary.Contains('scientific_result')){$Summary.scientific_result}elseif($Summary.Contains('science_status')){$Summary.science_status}else{'NOT_EVALUATED'});
      failure_stage=$(if($Summary.Contains('failure_stage')){$Summary.failure_stage}else{'writer_completion'});
      failure_reason=$unknownReason;recovery_action=$unknownRecovery;result_path=[string]$Context.result_path;
      exception=$exception;secondary_errors=@(if($Summary.Contains('secondary_errors')){$Summary.secondary_errors|ForEach-Object{[string]$_}});
      phase_timings_seconds=$(if($Summary.Contains('phase_timings_seconds')){$Summary.phase_timings_seconds}elseif($Summary.Contains('phase_durations_seconds')){$Summary.phase_durations_seconds}else{@{}});
      total_elapsed_seconds=$(if($Summary.Contains('total_elapsed_seconds')){$Summary.total_elapsed_seconds}else{$null})} -Depth 64
    throw 'PowerShell owner native writer completion is unknown; retain its resources.'
  }
  Assert-WorkflowWriterCompletion $WriterCompletion -PowerShellOwner
  $preserve=@($RetentionPreservePaths|ForEach-Object{Convert-WorkflowOwnerPath $Context $_})
  if($Status-ne'success'){
    # Keep only the existing retention owner's recognized, completed batch
    # logs. Incomplete logs retain their original failed-run policy. This
    # reads bounded log tails, never PA payloads or scientific trajectories.
    $ownerRunRoot=$root
    $completedLogs=Invoke-RunToolRootContext -RepoRoot $Context.repo_root -Operation {
      & $Context.python -B -c 'import json,sys;from pathlib import Path;from common.simion.native_completion import recoverable_batch_logs,has_recoverable_batch_completion;print(json.dumps([str(p) for p in sorted(recoverable_batch_logs(Path(sys.argv[1]))) if has_recoverable_batch_completion(p)]))' $ownerRunRoot
      if($LASTEXITCODE-ne0){throw 'Completed batch log retention selection failed.'}
    }
    $preserve+=@(($completedLogs-join"`n")|ConvertFrom-Json)
  }
  $configPath=Join-Path $root 'run_config.json'
  $config=Get-Content -LiteralPath $configPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $summaryDocument=[ordered]@{};foreach($name in $Summary.Keys){$summaryDocument[$name]=$Summary[$name]}
  $summaryDocument.run_id=$config.run_id;$summaryDocument.status=$Status
  $waitPath=Join-Path $root 'logs/prepared_wait.json'
  $completionPath=Join-Path $root 'results/execution_completion.json'
  Write-RunJson -Atomic -Path $waitPath -Value @{schema_version=1;role='run_artifact_powershell_owner_wait';owner_pid=$PID;
    owner_start_utc_ticks=(Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks;
    native_writers_confirmed=$true;exception=$exception;observation_error=$null} -Depth 64
  $completion=[ordered]@{schema_version=1;role='run_artifact_workflow_completion';run_id=$config.run_id;project=$config.project;
    execution_request=(New-WorkflowOwnerFileRecord $Context.request_path);run_config=(New-WorkflowOwnerFileRecord $configPath);
    status=$Status;summary=$summaryDocument;output_paths=@($OutputPaths|ForEach-Object{Convert-WorkflowOwnerPath $Context $_});
    required_output_paths=@($RequiredOutputPaths|ForEach-Object{Convert-WorkflowOwnerPath $Context $_});
    retention_preserve_paths=@($preserve|Sort-Object -Unique);manifest_extra_fields=@{};writer_completion=$WriterCompletion;exception=$exception;
    resource_usage_paths=@($ResourceUsagePaths|ForEach-Object{@{path=(Convert-WorkflowOwnerPath $Context $_.path);case_name=$_.case_name}});
    resource_profile=$(if($null-ne$ResourceProfile){@{dispatch_plan=(Convert-WorkflowOwnerPath $Context $ResourceProfile.dispatch_plan);
      output=(Convert-WorkflowOwnerPath $Context $ResourceProfile.output);usage_path=(Convert-WorkflowOwnerPath $Context $ResourceProfile.usage_path)}}else{$null})}
  $executionAlias=$null
  if($Context.Contains('package')){
    $ownerPackage=$Context.package
    if(($ownerPackage-is[Collections.IDictionary]-and$ownerPackage.Contains('execution_alias'))-or
       ($ownerPackage-isnot[Collections.IDictionary]-and$null-ne$ownerPackage.PSObject.Properties['execution_alias'])){
      $executionAlias=$ownerPackage.execution_alias
    }
  }
  if($null-ne$executionAlias){
    $completion.execution_alias=@{path=[string]$executionAlias;target_directory=$root}
  }
  Write-RunJson -Atomic -Path $completionPath -Value $completion -Depth 64
  $Context.completion_written=$true
  Write-RunJson -Atomic -Path $Context.result_path -Value @{schema_version=1;role='run_artifact_workflow_result';status='pending';
    stage='completion';run_directory=$root;execution_request=$Context.request_path;writers_confirmed=$true;
    exception=$exception;resume_action='resume_finalization'} -Depth 64
  $Context.finalization_started=$true
  $outcome=Invoke-RunArtifactWorkflow -RequestPath $Context.request_path -ResultPath $Context.result_path -ResumeFinalization
  $Context.finalized=$true;$Context.finalization_started=$false
  return $outcome
}

function Add-RunArtifactResourceRelease {
  param([Parameter(Mandatory)][AllowEmptyCollection()][Collections.Generic.List[object]]$ResourceReleases,
    [Parameter(Mandatory)][string]$ReleaseId,[Parameter(Mandatory)]$Receipt)
  # Direct Exit-HostResourceStage returns a PSCustomObject; JSON bridges return
  # a dictionary. Preserve every actual field while adapting that representation.
  if($Receipt-is[Collections.IDictionary]-and$Receipt.Contains('host_release')-and
     $Receipt.host_release-is[Collections.IDictionary]-and$Receipt.host_release.Contains('result')-and
     $null-ne$Receipt.host_release.result-and$Receipt.host_release.result-is[pscustomobject]){
    $transaction=@{}
    foreach($property in $Receipt.host_release.result.PSObject.Properties){$transaction[$property.Name]=$property.Value}
    $Receipt.host_release.result=$transaction
  }
  $existing=@($ResourceReleases|Where-Object release_id -eq $ReleaseId)
  if($existing.Count){
    $prior=$existing[0].completion_receipt.host_release
    $current=$Receipt.host_release
    if($existing.Count-ne1-or-not$prior.inherited-or-not$current.inherited-or
       $prior.token-cne$current.token-or$current.token-cne$ReleaseId-or
       $null-ne$prior.result-or$null-ne$current.result-or$null-ne$prior.error-or$null-ne$current.error){
      throw 'Resource completion conflicts with an existing release receipt.'
    }
    return
  }
  $ResourceReleases.Add(@{release_id=$ReleaseId;completion_receipt=$Receipt})
}

function Assert-WorkflowWriterCompletion {
  param($Completion,[switch]$PowerShellOwner)
  Assert-WorkflowFields $Completion @('operations','resource_releases') 'Writer completion'
  if($Completion.operations-isnot[array]-or$Completion.resource_releases-isnot[array]){
    throw 'Writer completion collections must be arrays.'
  }
  $releases=@{}
  $tokens=@{}
  foreach($release in $Completion.resource_releases){
    Assert-WorkflowFields $release @('release_id','completion_receipt') 'Resource release'
    if($release.release_id-isnot[string]-or[string]::IsNullOrWhiteSpace($release.release_id)-or
       $releases.ContainsKey($release.release_id)){throw 'Resource release identity is missing or duplicated.'}
    $receipt=$release.completion_receipt
    if($receipt-isnot[Collections.IDictionary]-or-not$receipt.Contains('host_release')){
      throw 'Resource release lacks the actual owner receipt.'
    }
    # Python bridge facts exist only for that transport. Direct PS owners
    # (including COMSOL) expose their original release without inventing them.
    if(($receipt.Contains('bridge_process_exit_confirmed')-or$receipt.Contains('bridge_process_returncode'))-and
       (-not$receipt.Contains('bridge_process_exit_confirmed')-or
        $receipt.bridge_process_exit_confirmed-isnot[bool]-or-not$receipt.bridge_process_exit_confirmed-or
        -not$receipt.Contains('bridge_process_returncode')-or
        $receipt.bridge_process_returncode-isnot[long]-and$receipt.bridge_process_returncode-isnot[int])){
      throw 'Resource bridge completion is unconfirmed.'
    }
    if($receipt.Contains('host_release_confirmed')-and
       ($receipt.host_release_confirmed-isnot[bool]-or-not$receipt.host_release_confirmed)){
      throw 'Resource completion contradicts its owner release.'
    }
    $hostRelease=$receipt.host_release
    Assert-WorkflowFields $hostRelease @('inherited','token','result','error') 'Host release'
    if($hostRelease.inherited-isnot[bool]-or($hostRelease.inherited-and-not$PowerShellOwner)-or
       $hostRelease.token-isnot[string]-or[string]::IsNullOrWhiteSpace($hostRelease.token)-or
       $null-ne$hostRelease.error){throw 'Resource owner release is unconfirmed or inherited.'}
    if($hostRelease.inherited){
      # Exit-HostResourceStage makes no transaction for an inherited grant.
      # The actual parent grant is rechecked before terminal publication below.
      if($null-ne$hostRelease.result){throw 'Inherited stage must preserve its actual null release result.'}
    }else{
      Assert-WorkflowFields $hostRelease.result @('status','token') 'Released transaction'
      if($hostRelease.result.status-cne'released'-or$hostRelease.result.token-cne$hostRelease.token){
        throw 'Resource owner release identity or terminal state differs.'
      }
    }
    if($tokens.ContainsKey($hostRelease.token)){throw 'Resource release token is duplicated.'}
    $tokens[$hostRelease.token]=$true
    $releases[$release.release_id]=$false
  }
  $operations=@{}
  foreach($operation in $Completion.operations){
    Assert-WorkflowFields $operation @('operation_id','observation','resource_release_id') 'Writer operation'
    if($operation.operation_id-isnot[string]-or[string]::IsNullOrWhiteSpace($operation.operation_id)-or
       $operations.ContainsKey($operation.operation_id)){throw 'Writer operation identity is missing or duplicated.'}
    if($PowerShellOwner){
      Assert-WorkflowFields $operation.observation @('exit_confirmed','returncode','process_id','process_started_at_utc_ticks') 'PowerShell native observation'
      if(($operation.observation.process_id-isnot[int]-and$operation.observation.process_id-isnot[long])-or
         [long]$operation.observation.process_id-le0-or
         ($operation.observation.process_started_at_utc_ticks-isnot[int]-and$operation.observation.process_started_at_utc_ticks-isnot[long])-or
         [long]$operation.observation.process_started_at_utc_ticks-le0){throw 'PowerShell native process identity is invalid.'}
    }else{Assert-WorkflowFields $operation.observation @('exit_confirmed','returncode') 'Native observation'}
    if($operation.observation.exit_confirmed-isnot[bool]-or-not$operation.observation.exit_confirmed-or
       $operation.observation.returncode-isnot[long]-and$operation.observation.returncode-isnot[int]){
      throw 'Native writer completion is unconfirmed.'
    }
    if($operation.resource_release_id-isnot[string]-or-not$releases.ContainsKey($operation.resource_release_id)){
      throw 'Writer operation has no bound owner release.'
    }
    $operations[$operation.operation_id]=$true
    $releases[$operation.resource_release_id]=$true
  }
  if(@($releases.Values|Where-Object{-not$_}).Count){throw 'Resource release has no corresponding started operation.'}
}

function Invoke-PreparedWorkflowProcess {
  param([string]$Python,[string]$ExecutionRequest,[string]$RunConfig,
    [string]$SessionPath,[string]$CompletionPath,[string]$WaitPath,[string]$LogRoot,[string]$HostStatePath,
    [Parameter(Mandatory)][pscustomobject]$Package)
  # The public handshake owns the actual Python worker handle, including when
  # a venv launcher exits first. It adds no host grant or private process tree.
  $runner=@'
import os, sys
# Import only from the validated frozen root, never the execution cwd.
sys.path[0] = os.environ['PYTHONPATH']
from common.host_resource_python import await_managed_process_start
await_managed_process_start()
import importlib, json, sys
from pathlib import Path
from common.contracts.recorded_file_removal import write_json_atomic
request_path, config, session, completion, wait_path = (Path(value).resolve() for value in sys.argv[1:])
request = json.loads(request_path.read_text(encoding="utf-8-sig"))
prepared = request["prepared"]
try:
    module = importlib.import_module(prepared["module"])
    if Path(module.__file__).resolve() != Path(prepared["entrypoint"]["path"]).resolve():
        raise ValueError("prepared module identity differs")
    module.execute_prepared_run(config, session, request_path, completion)
except BaseException as error:
    failure = {"type": type(error).__name__, "module": type(error).__module__, "message": str(error),
               "notes": list(getattr(error, "__notes__", []))}
    try: write_json_atomic(wait_path, {"exception": failure})
    except BaseException as secondary: error.add_note(f"Prepared wait publication failed: {secondary}")
    raise
'@
  $request=Get-Content -LiteralPath $ExecutionRequest -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  $config=Get-Content -LiteralPath $RunConfig -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
  # CPython can import the persistent long frozen source; Windows CreateProcess
  # still needs a compatible cwd. Only this run's actual process paths use the
  # existing native execution view. No source copy or source-owner alias.
  $stdout=Join-Path $LogRoot 'prepared_stdout.log';$stderr=Join-Path $LogRoot 'prepared_stderr.log'
  $native=Get-RunNativeExecutionContext -Package $Package -Tool 'prepared Python worker' `
    -Paths @($ExecutionRequest,$RunConfig,$SessionPath,$CompletionPath,$WaitPath,$stdout,$stderr,$Package.artifact_run_dir)
  $environment=@{};foreach($name in $native.environment.Keys){$environment[$name]=$native.environment[$name]}
  $environment.PYTHONPATH=$request.prepared.import_root;$environment.PYTHONNOUSERSITE='1';$environment.PYTHONDONTWRITEBYTECODE='1'
  $environment.MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=$HostStatePath
  if($config.Contains('paths')){
    $environment.MASS_SPECTROMETRY_ARTIFACT_ROOT=[string]$config.paths.artifact_root
    $environment.MASS_SPECTROMETRY_EXECUTION_ROOT=[string]$config.paths.execution_root
    $environment.MASS_SPECTROMETRY_RUN_DIRECTORY=[string](Split-Path -Parent $RunConfig)
    $environment.MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY=$native.run_dir
  }
  $receipt=$null;$failure=$null;$childFailure=$null
  try{
    $receipt=Invoke-RepositoryManagedPythonProcess -Python $Python `
      -ArgumentList @('-B','-c',$runner,$native.projected_paths[0],$native.projected_paths[1],$native.projected_paths[2],$native.projected_paths[3],$native.projected_paths[4]) `
      -WorkingDirectory $native.projected_paths[7] `
      -StandardOutputPath $native.projected_paths[5] -StandardErrorPath $native.projected_paths[6] `
      -Environment $environment
  }catch{
    $failure=$_
    if($_.Exception.Data.Contains('managed_python_completion')){$receipt=$_.Exception.Data['managed_python_completion']}
  }
  try{
    if(Test-Path -LiteralPath $WaitPath -PathType Leaf){
      $childFailure=(Get-Content -LiteralPath $WaitPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable).exception
    }
  }catch{if($null-eq$failure){$failure=$_}else{$failure.Exception.Data['prepared_exception_read_error']=$_.Exception.Message}}
  $wait=[ordered]@{schema_version=1;role='run_artifact_prepared_wait';managed_process=$receipt;exception=$childFailure;
    observation_error=$(if($null-ne$failure){$failure.Exception.Message}else{$null})}
  try{Write-RunJson -Path $WaitPath -Value $wait -Depth 64}
  catch{if($null-eq$failure){$failure=$_}else{$failure.Exception.Data['prepared_wait_publication_error']=$_.Exception.Message}}
  if($null-ne$failure){
    if($null-ne$childFailure){$failure.Exception.Data['prepared_exception']=$childFailure}
    throw $failure
  }
  if(Test-Path -LiteralPath $CompletionPath -PathType Leaf){
    $completed=Get-Content -LiteralPath $CompletionPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    if($completed.summary-isnot[Collections.IDictionary]){throw 'Prepared completion summary must be an object.'}
    $completed.summary.native_path_preparation=$Package.native_path_preparation
    if($null-ne$Package.execution_alias){
      if($completed.Contains('execution_alias')){throw 'Prepared callback cannot supply the public owner execution alias.'}
      $completed.execution_alias=@{path=[string]$Package.execution_alias;target_directory=[string]$Package.artifact_run_dir}
    }
    Write-RunJson -Atomic -Path $CompletionPath -Value $completed -Depth 64
  }
  return [pscustomobject]$wait
}

function Publish-WorkflowTerminal {
  param([string]$Python,[string]$RepoRoot,[string]$CompletionPath,[string]$SessionPath,[string]$WaitPath,
    [Nullable[long]]$MaximumRunBytes=$null)
  # Project status/summary/outputs are data. The existing journal remains the
  # sole publisher; the glue contains no project decision or manifest builder.
  $publisher=@'
import json, sys
from pathlib import Path
from common.contracts.write_run_manifest import build_run_manifest, publish_terminal_state, replay_terminal_publication, TERMINAL_JOURNAL_NAME
completion_path, session_path, wait_path = map(Path, sys.argv[1:4])
ceiling = int(sys.argv[4]) if sys.argv[4] else None
completion = json.loads(completion_path.read_text(encoding="utf-8-sig"))
config_path = Path(completion["run_config"]["path"])
root = config_path.parent
config = json.loads(config_path.read_text(encoding="utf-8-sig"))
request = json.loads(Path(config["inputs"]["execution_request"]).read_text(encoding="utf-8-sig"))
retention_path = root / "retention_actions.json"
retention = json.loads(retention_path.read_text(encoding="utf-8-sig"))
removed = {(root / item["path"]).resolve() for item in retention["removed"]}
required = [Path(value) for value in completion["required_output_paths"]]
if any(not path.is_file() for path in required): raise ValueError("retention removed required workflow evidence")
outputs = []
for value in completion["output_paths"]:
    path = Path(value)
    if path.is_file(): outputs.append(path)
    elif path.resolve() not in removed: raise ValueError(f"workflow output disappeared without retention evidence: {path}")
summary = dict(completion["summary"], writers_stopped=True)
summary_path = root / "summary.json"
logs = [] if request["prepared"].get("owner_kind") == "powershell" else [root / "logs/prepared_stdout.log", root / "logs/prepared_stderr.log"]
outputs = list(dict.fromkeys([*outputs, summary_path, completion_path, session_path, wait_path, retention_path, *logs]))
manifest = build_run_manifest(config_path, completion["status"], software=request["package"]["software"],
    output_paths=outputs, virtual_documents={summary_path: summary}, extra_fields=completion["manifest_extra_fields"])
if any(not item["exists"] for item in manifest["outputs"]): raise ValueError("workflow terminal output is missing")
journal_path = root / TERMINAL_JOURNAL_NAME
journal = json.loads(journal_path.read_text(encoding="utf-8-sig")) if journal_path.exists() else None
existing = (journal["documents"] if journal is not None else
            {"summary.json": json.loads(summary_path.read_text(encoding="utf-8-sig")),
             "run_manifest.json": json.loads((root / "run_manifest.json").read_text(encoding="utf-8-sig"))})
terminal_exists = existing["run_manifest.json"].get("status") in {"success", "failed", "interrupted"}
if journal is not None or terminal_exists:
    old = existing["run_manifest.json"]
    for field in ("recorded_at_utc", "host", "python"):
        if not isinstance(old.get(field), str): raise ValueError("terminal metadata identity differs")
        manifest[field] = old[field]
    if existing != {"summary.json": summary, "run_manifest.json": manifest}:
        raise ValueError("existing terminal publication differs from frozen workflow completion")
    if journal is None:
        print("WORKFLOW_TERMINAL=REUSED")
        sys.exit(0)
def size(value): return len((json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
if ceiling is not None:
    current = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    intent = journal or {"schema_version": 1, "role": "run_terminal_publication_journal", "run_id": manifest["run_id"],
                         "documents": {"summary.json": summary, "run_manifest.json": manifest}}
    # Conservatively retain all old targets, all new targets, and the largest
    # atomic temporary at once. This bounds the aggregate, not each JSON alone.
    sizes = [size(summary), size(manifest)] + ([] if journal is not None else [size(intent)])
    if current + sum(sizes) + max(sizes) > ceiling:
        raise ValueError("workflow terminal metadata exceeds admitted run byte ceiling")
if journal is not None: replay_terminal_publication(root)
else: publish_terminal_state(root, summary, manifest)
'@
  Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    $PSNativeCommandUseErrorActionPreference=$false
    & $Python -B -c $publisher $CompletionPath $SessionPath $WaitPath ([string]$MaximumRunBytes) | Out-Host
    if($LASTEXITCODE-ne0){throw "Workflow terminal publication failed; exit_code=$LASTEXITCODE; retain the existing journal for recovery."}
  }
}

function Get-WorkflowRecoveryState {
  param([string]$Python,[string]$RepoRoot,[string]$ArtifactRoot,[string]$RunRoot,[string]$LeaseId,[string]$Owner)
  $inspect=@'
import json, sys
from pathlib import Path
from common.contracts.capacity_ledger import load_capacity_ledger
from common.contracts.capacity_protection import load_capacity_protection_leases
root, run = map(lambda x: Path(x).resolve(), sys.argv[1:3])
lease_id, owner = sys.argv[3:]
ledger = load_capacity_ledger(root)
if ledger is None: raise ValueError("workflow recovery requires a valid capacity ledger")
entries = [entry for entry in ledger["objects"] if entry["path"] == run.relative_to(root).as_posix()]
if len(entries) != 1 or entries[0]["owner"] != owner or entries[0]["status"] not in {"writing", "ready"}:
    raise ValueError("workflow recovery exact owner range differs")
leases = load_capacity_protection_leases(root)
audit = next((item for item in leases["audit"] if item["lease_id"] == lease_id), None)
lease = json.loads(Path(audit["path"]).read_text(encoding="utf-8-sig")) if audit and audit["status"] == "active" else None
print(json.dumps({"entry": entries[0], "lease_status": audit["status"] if audit else "missing", "lease": lease}))
'@
  Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    $PSNativeCommandUseErrorActionPreference=$false
    $text=& $Python -B -c $inspect $ArtifactRoot $RunRoot $LeaseId $Owner
    if($LASTEXITCODE-ne0){throw 'Workflow recovery ledger inspection failed.'}
    return (($text-join"`n")|ConvertFrom-Json -AsHashtable)
  }
}

function Invoke-RunArtifactWorkflow {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$RequestPath,[Parameter(Mandatory)][string]$ResultPath,[switch]$ResumeFinalization)
  $contextEnvironmentNames=@('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH','MASS_SPECTROMETRY_ARTIFACT_ROOT',
    'MASS_SPECTROMETRY_EXECUTION_ROOT','MASS_SPECTROMETRY_RUN_DIRECTORY','MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY')
  $callerEnvironment=Save-RunEnvironment -Names $contextEnvironmentNames
  $result=[ordered]@{schema_version=1;role='run_artifact_workflow_result';status='failed';stage='validate';
    run_directory=$null;prepared_exit_code=$null;terminal_published=$false;capacity_finalized=$false;
    lease_released=$false;exception=$null;secondary_errors=@();elapsed_seconds=0.0;
    timing=[ordered]@{};last_completed_stage=$null;resume_action=$null}
  $timingClock=[Diagnostics.Stopwatch]::StartNew();$timingBoundary=@{seconds=0.0}
  function Set-WorkflowStage {
    param([string]$NextStage='')
    $now=$timingClock.Elapsed.TotalSeconds;$previous=[string]$result.stage
    if(-not$result.timing.Contains($previous)){$result.timing[$previous]=0.0}
    $result.timing[$previous]+=$now-$timingBoundary.seconds
    $timingBoundary.seconds=$now
    if($NextStage){$result.last_completed_stage=$previous;$result.stage=$NextStage}
  }
  $session=$null;$package=$null;$writersConfirmed=$false;$preparedStarted=[bool]$ResumeFinalization;$failure=$null
  $maximumRunBytes=$null;$python=$null;$repo=$null;$powershellOwner=$false;$completion=$null
  $inheritedCapacity=$false;$inheritedAlreadyReady=$false;$requiresParentOwner=$false
  $capacityAccountingDeferred=$false;$capacityAccountingDeferredReason=$null
  $sourceExecutionContext=$null;$nativeInputPaths=@()
  try{
    $requestFile=(Resolve-Path -LiteralPath $RequestPath).Path
    $requestHash=(Get-FileHash -LiteralPath $requestFile -Algorithm SHA256).Hash
    $request=Get-Content -LiteralPath $requestFile -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    Assert-WorkflowFields $request @('schema_version','role','repository_root','python_executable','package','capacity','prepared','payload') 'Workflow request'
    if($request.schema_version-ne1-or$request.role-cne'run_artifact_workflow_request'){throw 'Workflow request identity differs.'}
    $packageFields=@('project','run_id','mode','artifact_project_root','software','retention_class','retention_reason')
    if($request.package-is[Collections.IDictionary]-and$request.package.Contains('expected_execution_relative_paths')){$packageFields+='expected_execution_relative_paths'}
    Assert-WorkflowFields $request.package $packageFields 'Workflow package'
    $expectedExecutionRelativePaths=@()
    if($request.package.Contains('expected_execution_relative_paths')){
      if($request.package.expected_execution_relative_paths-isnot[array]){throw 'Expected native execution paths must be an array.'}
      foreach($path in $request.package.expected_execution_relative_paths){
        if($path-isnot[string]){throw 'Expected native execution paths must contain strings.'}
      }
      $expectedExecutionRelativePaths=@($request.package.expected_execution_relative_paths)
    }
    $capacityFields=@('committed_new_bytes','commitment_inputs','protected_paths','protected_cache_keys')
    if($request.capacity.Contains('source_references')){$capacityFields+='source_references'}
    if($request.capacity.Contains('ownership')-or$request.capacity.Contains('session_owner')){$capacityFields+=@('ownership','session_owner')}
    Assert-WorkflowFields $request.capacity $capacityFields 'Workflow capacity'
    $powershellOwner=$request.prepared-is[Collections.IDictionary]-and$request.prepared.Contains('owner_kind')-and
      $request.prepared.owner_kind-ceq'powershell'
    if($powershellOwner){
      if($request.prepared.Contains('native_input_paths')){throw 'Native source input transport is supported only for Python prepared calls.'}
      Assert-WorkflowFields $request.prepared @('owner_kind','entrypoint') 'PowerShell owner'
      if(-not$ResumeFinalization){throw 'PowerShell owner finalization requires its existing run.'}
    }else{
      $preparedFields=@('module','function','import_root','entrypoint')
      if($request.prepared.Contains('native_input_paths')){$preparedFields+='native_input_paths'}
      Assert-WorkflowFields $request.prepared $preparedFields 'Prepared call'
    }
    if($request.prepared.Contains('native_input_paths')){
      if($powershellOwner){throw 'Native source input transport is supported only for Python prepared calls.'}
      if($request.prepared.native_input_paths-isnot[array]){throw 'Prepared native_input_paths must be an array.'}
      foreach($path in $request.prepared.native_input_paths){
        if($path-isnot[string]-or-not[IO.Path]::IsPathFullyQualified($path)){throw 'Prepared native input must be an absolute file path.'}
      }
      $nativeInputPaths=@($request.prepared.native_input_paths)
      if(@($nativeInputPaths|Select-Object -Unique).Count-ne$nativeInputPaths.Count){throw 'Prepared native input declarations are duplicated.'}
    }
    if($request.capacity.Contains('ownership')){
      if(-not$powershellOwner-or$request.capacity.ownership-notin@('owned','inherited')-or
         $request.capacity.session_owner-isnot[string]-or[string]::IsNullOrWhiteSpace($request.capacity.session_owner)){
        throw 'Workflow capacity ownership is invalid.'
      }
      $inheritedCapacity=$request.capacity.ownership-ceq'inherited'
    }
    $budget=$request.capacity.committed_new_bytes
    if($budget-isnot[long]-and$budget-isnot[int]-or$budget-lt0){throw 'Workflow capacity requires a known nonnegative integer commitment.'}
    foreach($name in @('commitment_inputs','protected_paths','protected_cache_keys')){
      if($request.capacity[$name]-isnot[array]){throw "Workflow capacity $name must be an array."}
    }
    $sourceReferences=@()
    if($request.capacity.Contains('source_references')){
      if($request.capacity.source_references-isnot[array]){throw 'Workflow capacity source_references must be an array.'}
      $sourceReferences=$request.capacity.source_references
    }
    if(-not$request.capacity.commitment_inputs.Count){throw 'Workflow capacity requires its budget authority inputs.'}
    if(-not$ResumeFinalization){foreach($record in $request.capacity.commitment_inputs){Assert-WorkflowFileRecord $record}}
    $call=$request.prepared
    if(-not$powershellOwner-and($call.module-isnot[string]-or$call.module-notmatch'^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$'-or
       $call.module-eq'__main__'-or$call.function-cne'execute_prepared_run')){throw 'Workflow prepared call is invalid.'}
    if(-not$ResumeFinalization){
      $importRoot=(Resolve-Path -LiteralPath $call.import_root).Path
      Assert-WorkflowFileRecord $call.entrypoint (Join-Path $importRoot ($call.module.Replace('.','/')+'.py'))
    }
    $repo=(Resolve-Path -LiteralPath $request.repository_root).Path
    $python=(Resolve-Path -LiteralPath $request.python_executable).Path
    # Resolve from the live public owner before any frozen source is imported.
    # This is control-plane context, not a scientific input or a new reservation.
    $projectRoot=[IO.Path]::GetFullPath($request.package.artifact_project_root)
    $artifactRoot=Split-Path -Parent (Split-Path -Parent $projectRoot)
    . (Join-Path $PSScriptRoot '../paths/workspace_paths.ps1')
    $runRoot=Join-Path (Join-Path $projectRoot 'runs') $request.package.run_id
    $null=Get-RunPackagePathCapacity -RunDirectory $runRoot -ExpectedExecutionRelativePaths $expectedExecutionRelativePaths
    $recoveryConfig=$null
    if($ResumeFinalization-and(Test-Path -LiteralPath (Join-Path $runRoot 'run_config.json') -PathType Leaf)){
      $recoveryConfig=Get-Content -LiteralPath (Join-Path $runRoot 'run_config.json') -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    }
    if($null-ne$recoveryConfig-and$recoveryConfig.Contains('paths')){
      $pathContext=Resolve-WorkspacePaths -SourceRoot $repo -FrozenContext $recoveryConfig.paths -Python $python
    }else{
      $hostStatePath=Resolve-HostResourceStatePath
      $pathContext=Resolve-WorkspacePaths -SourceRoot $repo -ArtifactRoot $artifactRoot -HostResourceStatePath $hostStatePath -Python $python
    }
    $hostStatePath=[string]$pathContext.host_resource_state_path
    $result.execution_context=$pathContext
    $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=[string]$pathContext.host_resource_state_path
    $env:MASS_SPECTROMETRY_ARTIFACT_ROOT=[string]$pathContext.artifact_root
    $env:MASS_SPECTROMETRY_EXECUTION_ROOT=[string]$pathContext.execution_root
    $env:MASS_SPECTROMETRY_RUN_DIRECTORY=$runRoot
    $env:MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY=$runRoot
    if(-not([IO.Path]::GetFullPath((Split-Path -Parent $runRoot))).Equals(
        (Join-Path $projectRoot 'runs'),[StringComparison]::OrdinalIgnoreCase)){
      throw 'Workflow run must be a direct child of its runs directory.'
    }
    if((Test-Path -LiteralPath $runRoot)-and-not$ResumeFinalization){throw 'Workflow requires a new run directory.'}
    if($ResumeFinalization-and-not(Test-Path -LiteralPath $runRoot -PathType Container)){throw 'Workflow recovery requires its existing run.'}
    if(Test-WorkflowPathWithin $ResultPath $runRoot){throw 'Workflow result transport must be outside the sealed run.'}
    $result.run_directory=$runRoot
    if($ResumeFinalization){
      $package=@{run_config=(Join-Path $runRoot 'run_config.json');input_dir=(Join-Path $runRoot 'inputs')}
      $frozenRequest=Join-Path $package.input_dir 'execution_request.json'
      if((Get-FileHash -LiteralPath $frozenRequest -Algorithm SHA256).Hash-ine$requestHash){throw 'Workflow recovery request differs from its frozen request.'}
      $initial=$recoveryConfig
      $sessionPath=Join-Path $runRoot 'logs/capacity_session.json'
      $session=Get-Content -LiteralPath $sessionPath -Raw -Encoding UTF8|ConvertFrom-Json
      # The stopped-stage accounting owner is the only authority that can
      # reconcile this marker. A recovery Result cannot erase the original hold.
      if($session.PSObject.Properties.Name-contains'defer_capacity_finalization'){
        $capacityAccountingDeferredReason=if($session.defer_capacity_finalization-is[string]-and
          -not[string]::IsNullOrWhiteSpace($session.defer_capacity_finalization)){
          $session.defer_capacity_finalization
        }else{'Stopped-stage capacity accounting has an invalid unresolved deferral marker.'}
      }
      $expectedOwner=if($request.capacity.Contains('session_owner')){[string]$request.capacity.session_owner}else{"run-artifact-workflow:{0}:{1}"-f$request.package.project,$request.package.run_id}
      if($session.role-cne'artifact_workflow_capacity_session'-or$session.owner-cne$expectedOwner-or
         [IO.Path]::GetFullPath($session.artifact_root)-ine$artifactRoot){throw 'Workflow recovery session identity differs.'}
      if(Test-Path -LiteralPath $ResultPath -PathType Leaf){
        $prior=Get-Content -LiteralPath $ResultPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
        if($prior.Contains('recovery_session')){
          if($prior.role-cne'run_artifact_workflow_result'-or$prior.run_directory-ine$runRoot-or
             $prior.execution_request_sha256-ine$requestHash){throw 'Workflow prior recovery transport differs.'}
          $session=[pscustomobject]$prior.recovery_session
          if($session.role-cne'artifact_workflow_capacity_session'-or$session.owner-cne$expectedOwner-or
             [IO.Path]::GetFullPath($session.artifact_root)-ine$artifactRoot){throw 'Workflow recovery session identity differs.'}
          $result.recovery_session=$session
          $result.execution_request_sha256=$requestHash
        }
      }
      if($nativeInputPaths.Count){
        if(-not(Test-Path -LiteralPath $ResultPath -PathType Leaf)-or-not$prior.Contains('source_execution_context')-or
           $prior.execution_request_sha256-ine$requestHash){throw 'Workflow source execution context requires its original Result.'}
        $sourceExecutionContext=$prior.source_execution_context
        $originalSession=Get-Content -LiteralPath $sessionPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
        if(-not$originalSession.Contains('source_execution_context')-or
           ($originalSession.source_execution_context|ConvertTo-Json -Depth 64 -Compress)-cne
           ($sourceExecutionContext|ConvertTo-Json -Depth 64 -Compress)){throw 'Workflow source execution context differs from its owner record.'}
        $result.source_execution_context=$sourceExecutionContext;$result.execution_request_sha256=$requestHash
      }
      $completionPath=Join-Path $runRoot 'results/execution_completion.json'
      $waitPath=Join-Path $runRoot 'logs/prepared_wait.json'
      if($powershellOwner){
        if(-not(Test-WorkflowPathWithin $call.entrypoint.path $package.input_dir)){throw 'PowerShell owner source is outside frozen inputs.'}
        Assert-WorkflowFileRecord $call.entrypoint
      }
    }else{
    Set-WorkflowStage admission
    $session=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repo -ArtifactRoot $artifactRoot `
      -RunDirectory $runRoot -CommittedNewBytes $budget -ProtectedPaths $request.capacity.protected_paths `
      -ProtectedCacheKeys $request.capacity.protected_cache_keys -SourceReferences $sourceReferences -Owner ("run-artifact-workflow:{0}:{1}"-f$request.package.project,$request.package.run_id)
    Set-WorkflowStage initialize
    $package=New-RunPackage -Python $python -RepoRoot $repo -ArtifactRoot $projectRoot `
      -RunId $request.package.run_id -Project $request.package.project -Mode $request.package.mode `
      -Software $request.package.software -RetentionContractEnabled -RetentionClass $request.package.retention_class `
      -RetentionReason $request.package.retention_reason -CapacityLedgerLifecycleEnabled -CapacityLedgerArtifactRoot $artifactRoot -PathContext $pathContext `
      -ExpectedExecutionRelativePaths $expectedExecutionRelativePaths
    # The owner persists identities beyond disposal of the execution view.
    foreach($entry in @{input_dir='inputs';result_dir='results';log_dir='logs';run_config='run_config.json';summary='summary.json'}.GetEnumerator()){
      $package.($entry.Key)=Join-Path $package.artifact_run_dir $entry.Value
    }
    $result.execution_context=$pathContext
    $frozenRequest=Join-Path $package.input_dir 'execution_request.json'
    $copyIdentity=$null
    $null=Copy-VerifiedRunInput -Source $requestFile -Destination $frozenRequest -VerifiedIdentity ([ref]$copyIdentity)
    if($copyIdentity.sha256-ine$requestHash){throw 'Workflow request changed after admission.'}
    $initial=Get-Content -LiteralPath $package.run_config -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    $initial.inputs.execution_request=$frozenRequest
    Write-RunJson -Path $package.run_config -Value $initial
    $null=Write-VerifiedRunManifest -Python $python -RepoRoot $repo -RunConfig $package.run_config `
      -Status checkpoint -Software $request.package.software -Outputs @($package.summary)
    $sessionPath=Join-Path $runRoot 'logs/capacity_session.json'
    if($nativeInputPaths.Count){
      $sourceExecutionContext=New-RunSourceExecutionContext -Python $python -RepoRoot $repo -Package $package -Session $session `
        -SourceReferences $sourceReferences -NativeInputPaths $nativeInputPaths -RequestSha256 $requestHash
      $session|Add-Member -NotePropertyName source_execution_context -NotePropertyValue $sourceExecutionContext
      $result.source_execution_context=$sourceExecutionContext;$result.execution_request_sha256=$requestHash
      Write-RunJson -Path $ResultPath -Value $result -Depth 64 -Atomic
    }
    Write-RunJson -Path $sessionPath -Value $session -Depth 64
    $completionPath=Join-Path $runRoot 'results/execution_completion.json'
    $waitPath=Join-Path $runRoot 'logs/prepared_wait.json'
    Set-WorkflowStage prepared
    Assert-WorkflowFileRecord $call.entrypoint
    foreach($record in $request.capacity.commitment_inputs){Assert-WorkflowFileRecord $record}
    $preparedStarted=$true
    $null=Invoke-PreparedWorkflowProcess -Python $python `
      -ExecutionRequest $frozenRequest -RunConfig $package.run_config -SessionPath $sessionPath `
      -CompletionPath $completionPath -WaitPath $waitPath -LogRoot (Join-Path $runRoot 'logs') -HostStatePath $hostStatePath -Package $package
    }
    Set-WorkflowStage completion
    $wait=Get-Content -LiteralPath $waitPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    $result.exception=$wait.exception
    if($powershellOwner){
      Assert-WorkflowFields $wait @('schema_version','role','owner_pid','owner_start_utc_ticks','native_writers_confirmed','exception','observation_error') 'PowerShell owner wait'
      if($wait.schema_version-ne1-or$wait.role-cne'run_artifact_powershell_owner_wait'-or
         $wait.native_writers_confirmed-isnot[bool]-or-not$wait.native_writers_confirmed-or$null-ne$wait.observation_error-or
         $wait.owner_pid-isnot[int]-and$wait.owner_pid-isnot[long]-or$wait.owner_start_utc_ticks-isnot[long]-and$wait.owner_start_utc_ticks-isnot[int]){
        throw 'PowerShell native writer completion is unconfirmed.'
      }
      if([int]$wait.owner_pid-eq$PID){
        if((Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks-ne[long]$wait.owner_start_utc_ticks){throw 'PowerShell owner start identity differs.'}
      }else{
        $owner=Get-Process -Id ([int]$wait.owner_pid) -ErrorAction SilentlyContinue
        if($null-ne$owner-and$owner.StartTime.ToUniversalTime().Ticks-eq[long]$wait.owner_start_utc_ticks){throw 'PowerShell owner is still active.'}
      }
    }else{
      $process=$wait.managed_process
      if($wait.role-cne'run_artifact_prepared_wait'-or$null-ne$wait.observation_error-or
         $process.role-cne'repository_managed_python_completion'-or
         ($process.exit_code-isnot[int]-and$process.exit_code-isnot[long])){throw 'Prepared process completion is unconfirmed.'}
      foreach($fact in @('ownership_confirmed','worker_exit_confirmed','launcher_exit_confirmed','stdout_drained','stderr_drained')){
        if($process[$fact]-isnot[bool]-or-not$process[$fact]){throw "Prepared process $fact is unconfirmed."}
      }
      $result.prepared_exit_code=$process.exit_code
    }
    $completion=Get-Content -LiteralPath $completionPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    $completionFields=@('schema_version','role','run_id','project','execution_request','run_config',
      'status','summary','output_paths','required_output_paths','retention_preserve_paths',
      'manifest_extra_fields','writer_completion','exception')
    if($powershellOwner){
      $completionFields+=@('resource_usage_paths','resource_profile')
    }
    if($completion.Contains('execution_alias')){$completionFields+='execution_alias'}
    Assert-WorkflowFields $completion $completionFields 'Workflow completion'
    if($null-ne$completion.exception){$result.exception=$completion.exception}
    if($completion.schema_version-ne1-or$completion.role-cne'run_artifact_workflow_completion'-or
       $completion.run_id-cne$request.package.run_id-or$completion.project-cne$request.package.project-or
       $completion.status-notin@('success','failed','interrupted')){throw 'Workflow completion identity or status differs.'}
    Assert-WorkflowFileRecord $completion.execution_request $frozenRequest
    Assert-WorkflowFileRecord $completion.run_config $package.run_config
    Assert-WorkflowWriterCompletion $completion.writer_completion -PowerShellOwner:$powershellOwner
    if($powershellOwner){
      if($inheritedCapacity){
        $existingManifest=Get-Content -LiteralPath (Join-Path $runRoot 'run_manifest.json') -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
        if($existingManifest.status-in@('success','failed','interrupted')-and-not(Test-Path -LiteralPath (Join-Path $runRoot '.run_terminal_publication.json'))){
          $existingCapacity=Get-WorkflowRecoveryState -Python $python -RepoRoot $repo -ArtifactRoot $artifactRoot `
            -RunRoot $runRoot -LeaseId $session.lease_id -Owner $request.package.project
          $inheritedAlreadyReady=$existingCapacity.entry.status-ceq'ready'
        }
      }
      foreach($release in $completion.writer_completion.resource_releases){
        if($release.completion_receipt.host_release.inherited){
          $token=[string]$release.completion_receipt.host_release.token
          if(-not$inheritedAlreadyReady){
            $grant=Invoke-HostResourceTransaction -StatePath $hostStatePath -Request @{operation='inherit';token=$token}
            if($grant.status-cne'acquired'-or$grant.token-cne$token){$requiresParentOwner=$true;throw 'Inherited PowerShell host grant is unconfirmed; return to its parent owner.'}
          }
        }
      }
    }
    if($completion.summary-isnot[Collections.IDictionary]-or$completion.summary.status-cne$completion.status-or
       $completion.summary.run_id-cne$completion.run_id){throw 'Workflow scientific summary identity differs.'}
    if($completion.status-eq'success'-and($null-ne$result.exception-or(-not$powershellOwner-and$result.prepared_exit_code-ne0)-or
       ($powershellOwner-and@($completion.writer_completion.operations|Where-Object{[int]$_.observation.returncode-ne0}).Count))){
      throw 'Successful completion contradicts the prepared process result.'
    }
    if($completion.manifest_extra_fields-isnot[Collections.IDictionary]){throw 'Workflow manifest extras must be an object.'}
    if($powershellOwner){
      if($completion.resource_usage_paths-isnot[array]){throw 'PowerShell resource usage paths must be an array.'}
      foreach($item in $completion.resource_usage_paths){
        Assert-WorkflowFields $item @('case_name','path') 'PowerShell resource usage'
        if($item.case_name-isnot[string]-or-not(Test-WorkflowPathWithin $item.path $runRoot)-or
           -not(Test-Path -LiteralPath $item.path -PathType Leaf)){throw 'PowerShell resource usage path differs.'}
      }
      if($null-ne$completion.resource_profile){
        Assert-WorkflowFields $completion.resource_profile @('dispatch_plan','output','usage_path') 'PowerShell resource profile'
        if(-not(Test-WorkflowPathWithin $completion.resource_profile.dispatch_plan $runRoot)-or
           -not(Test-Path -LiteralPath $completion.resource_profile.dispatch_plan -PathType Leaf)-or
           -not(Test-WorkflowPathWithin $completion.resource_profile.output $runRoot)-or
           $completion.resource_profile.usage_path-notin@($completion.resource_usage_paths.path)){
          throw 'PowerShell resource profile paths differ.'
        }
      }
    }
    $reserved=@('schema_version','role','run_id','project','mode','status','recorded_at_utc','host','python','software','run_config','inputs','outputs','artifact_retention','formal_eligible')
    if(@($completion.manifest_extra_fields.Keys|Where-Object{$_-in$reserved}).Count){throw 'Workflow manifest extras override public fields.'}
    foreach($name in @('output_paths','required_output_paths','retention_preserve_paths')){
      if($completion[$name]-isnot[array]){throw "Workflow $name must be an array."}
      foreach($path in $completion[$name]){
        $removedByRetention=$false
        if($ResumeFinalization-and$name-eq'output_paths'-and$path-is[string]-and
           (Test-Path -LiteralPath (Join-Path $runRoot 'retention_actions.json') -PathType Leaf)){
          $action=Get-Content -LiteralPath (Join-Path $runRoot 'retention_actions.json') -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
          if($action.Contains('removed')-and$action.removed-is[array]){
            $removedByRetention=@($action.removed|Where-Object{(Join-Path $runRoot $_.path)-ieq$path}).Count-eq1
          }
        }
        $deferredProfile=$powershellOwner-and$null-ne$completion.resource_profile-and$name-eq'output_paths'-and
          $path-ieq$completion.resource_profile.output
        if($path-isnot[string]-or-not[IO.Path]::IsPathFullyQualified($path)-or
           (-not(Test-Path -LiteralPath $path -PathType Leaf)-and-not$removedByRetention-and-not$deferredProfile)){
          throw "Workflow declared output is missing: $path"
        }
        if($name-ne'required_output_paths'-and-not(Test-WorkflowPathWithin $path $runRoot)){throw 'Workflow output escapes the run.'}
        if($name-eq'required_output_paths'-and-not(Test-WorkflowPathWithin $path $runRoot)-and
           -not@($session.protected_paths|Where-Object{Test-WorkflowPathWithin $path $_}).Count){
          throw 'Required predecessor evidence is outside the protected dependency scope.'
        }
      }
    }
    $finalConfig=Get-Content -LiteralPath $package.run_config -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    foreach($key in @('artifact_retention','capacity_ledger_lifecycle')){
      Assert-WorkflowFields $finalConfig[$key] @($initial[$key].Keys) "Package $key"
      foreach($field in $initial[$key].Keys){
        if($finalConfig[$key][$field]-cne$initial[$key][$field]){throw 'Prepared callback changed public package lifecycle metadata.'}
      }
    }
    if($finalConfig.schema_version-ne2-or$finalConfig.run_id-cne$initial.run_id-or
       $finalConfig.project-cne$initial.project-or$finalConfig.mode-cne$initial.mode-or
       $finalConfig.inputs.execution_request-cne$frozenRequest){throw 'Prepared callback changed public package lifecycle metadata.'}
    if($finalConfig.run_id-cne$request.package.run_id-or$finalConfig.project-cne$request.package.project-or
       $finalConfig.mode-cne$request.package.mode-or$finalConfig.artifact_retention.policy_version-ne1-or
       $finalConfig.artifact_retention.class-cne$request.package.retention_class-or
       $finalConfig.capacity_ledger_lifecycle.schema_version-ne1-or$finalConfig.capacity_ledger_lifecycle.enabled-isnot[bool]-or
       -not$finalConfig.capacity_ledger_lifecycle.enabled-or$finalConfig.capacity_ledger_lifecycle.artifact_root-ine$artifactRoot-or
       $finalConfig.capacity_ledger_lifecycle.light_evidence_budget_bytes-le0){throw 'Workflow public lifecycle identity differs.'}
    $expectedReason=if($request.package.retention_class-eq'compact'){$null}else{$request.package.retention_reason}
    if($finalConfig.artifact_retention.reason-cne$expectedReason){throw 'Workflow frozen retention reason differs.'}
    if($null-ne$sourceExecutionContext){
      $recordedSession=Get-Content -LiteralPath $sessionPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
      if(-not$recordedSession.Contains('source_execution_context')-or
         ($recordedSession.source_execution_context|ConvertTo-Json -Depth 64 -Compress)-cne
         ($sourceExecutionContext|ConvertTo-Json -Depth 64 -Compress)){throw 'Prepared callback changed the public source execution context.'}
    }
    $writersConfirmed=$true
    if($null-ne$capacityAccountingDeferredReason){
      $capacityAccountingDeferred=$true
      Set-WorkflowStage capacity_accounting
      $result.capacity_accounting_deferred_reason=$capacityAccountingDeferredReason
      throw ('Capacity accounting is deferred; return to the original capacity/cache accounting owner: '+$capacityAccountingDeferredReason)
    }
    if($null-ne$sourceExecutionContext){
      Set-WorkflowStage source_execution_alias_cleanup
      Remove-RunSourceExecutionContext -Python $python -RepoRoot $repo -Session $session -SourceReferences $sourceReferences `
        -NativeInputPaths $nativeInputPaths -RunDirectory $runRoot -ExecutionRoot $pathContext.execution_root -RequestSha256 $requestHash -Context $sourceExecutionContext
      $result.source_execution_aliases_removed=$true
    }
    if($completion.Contains('execution_alias')){
      $alias=$completion.execution_alias
      Assert-WorkflowFields $alias @('path','target_directory') 'Execution alias cleanup'
      if($alias.path-isnot[string]-or$alias.target_directory-isnot[string]-or
         -not[IO.Path]::IsPathFullyQualified($alias.path)-or
         [IO.Path]::GetFullPath($alias.target_directory)-ine[IO.Path]::GetFullPath($runRoot)-or
         [IO.Path]::GetFullPath((Split-Path -Parent $alias.path))-ine[IO.Path]::GetFullPath([string]$pathContext.execution_root)){
        throw 'Execution alias cleanup owner or frozen root differs.'
      }
      Set-WorkflowStage execution_alias_cleanup
      Remove-RunExecutionAlias -ExecutionAlias $alias.path -TargetDirectory $runRoot
      $result.execution_alias_removed=$true
    }
    $recoveryInputs=@($frozenRequest,$completionPath,$waitPath,$sessionPath)
    $terminalWithoutJournal=$false
    if($ResumeFinalization){
      $actionPath=Join-Path $runRoot 'retention_actions.json'
      if(Test-Path -LiteralPath $actionPath -PathType Leaf){
        $action=Get-Content -LiteralPath $actionPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
        if($action.status-eq'preflight_pending'){throw 'Retention preflight_pending must return to its original reconciliation owner.'}
        $boundPaths=@($recoveryInputs)+@($package.run_config)
        if(-not$action.Contains('recovery_inputs')-or$action.recovery_inputs-isnot[array]-or
           $action.recovery_inputs.Count-ne$boundPaths.Count){throw 'Retention recovery input binding is missing.'}
        foreach($record in $action.recovery_inputs){
          Assert-WorkflowFileRecord $record
          if($record.path-notin$boundPaths){throw 'Retention recovery input binding differs.'}
        }
        if(@($action.recovery_inputs.path|Select-Object -Unique).Count-ne$boundPaths.Count){throw 'Retention recovery input binding is duplicated.'}
      }
      $currentManifest=Get-Content -LiteralPath (Join-Path $runRoot 'run_manifest.json') -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
      $terminalWithoutJournal=$currentManifest.status-in@('success','failed','interrupted')-and
        -not(Test-Path -LiteralPath (Join-Path $runRoot '.run_terminal_publication.json'))
      $recovery=Get-WorkflowRecoveryState -Python $python -RepoRoot $repo -ArtifactRoot $artifactRoot `
        -RunRoot $runRoot -LeaseId $session.lease_id -Owner $request.package.project
      if(-not$terminalWithoutJournal-and$recovery.entry.status-cne'writing'){throw 'Workflow recovery cannot reopen a sealed run.'}
      if($recovery.lease_status-eq'active'){
        if($recovery.lease.owner-cne$session.owner){throw 'Workflow recovery live lease owner differs.'}
        $session.status='active'
        if($result.Contains('recovery_session')){
          $maximumRunBytes=[long]$recovery.entry.bytes+[long]$recovery.lease.committed_new_bytes
          $result.recovery_maximum_run_bytes=$maximumRunBytes
        }
      }elseif($inheritedCapacity){
        if(-not$inheritedAlreadyReady){$requiresParentOwner=$true;throw 'Inherited capacity owner is no longer active; return to its parent owner for finalization.'}
        $session.status='released'
      }elseif($terminalWithoutJournal){
        # A fully published terminal run needs no further run writes. The
        # lifecycle owner's fresh protection check still governs sealing.
        $session.status='released'
        $result.lease_released=$true
      }else{
        Set-WorkflowStage recovery_admission
        $accounting=Invoke-RunCapacityLifecycleAdapter -Python $python -RepoRoot $repo -Action register-writing `
          -ArtifactRoot $artifactRoot -RunConfig $package.run_config
        $policy=Get-Content -LiteralPath (Join-Path $repo 'common/contracts/artifact_capacity_policy.json') -Raw|ConvertFrom-Json
        [long]$metadataBudget=$policy.light_evidence_budget_bytes
        if($metadataBudget-le0){throw 'Workflow recovery metadata budget is invalid.'}
        $maximumRunBytes=[long]$accounting.bytes+$metadataBudget
        $session=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repo -ArtifactRoot $artifactRoot `
          -RunDirectory $runRoot -CommittedNewBytes $metadataBudget -ProtectedPaths $request.capacity.protected_paths `
          -ProtectedCacheKeys $request.capacity.protected_cache_keys -SourceReferences $sourceReferences -Owner $expectedOwner
        if($null-ne$sourceExecutionContext){$session|Add-Member -NotePropertyName source_execution_context -NotePropertyValue $sourceExecutionContext -Force}
        $result.recovery_session=$session
        $result.execution_request_sha256=$requestHash
        $result.recovery_maximum_run_bytes=$maximumRunBytes
        # Persist the fresh session outside the run before any recovery write.
        Write-RunJson -Path $ResultPath -Value $result -Depth 64 -Atomic
      }
    }
    if(-not$terminalWithoutJournal-and-not$inheritedCapacity){
      $null=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repo -Session $session
    }
    Set-WorkflowStage retention
    $hasRetention=Test-Path -LiteralPath (Join-Path $runRoot 'retention_actions.json') -PathType Leaf
    if($terminalWithoutJournal-and-not$hasRetention){throw 'Published workflow has no completed retention evidence.'}
    $null=Apply-RunArtifactRetention -Python $python -RepoRoot $repo -RunConfig $package.run_config `
      -PreservePaths $completion.retention_preserve_paths -FailedRun:($completion.status-ne'success') `
      -RecoveryInputs $recoveryInputs -Resume:($ResumeFinalization-and$hasRetention) -MaximumRunBytes $maximumRunBytes
    if($powershellOwner-and-not$terminalWithoutJournal-and-not(Test-Path -LiteralPath (Join-Path $runRoot '.run_terminal_publication.json'))){
      Set-WorkflowStage resource_finalization
      foreach($item in $completion.resource_usage_paths){
        $usage=Get-Content -LiteralPath $item.path -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
        $usage.case_name=$item.case_name;$usage.measurement_scope='single_transport_case_not_all_run_cases'
        Write-ResourceUsage -Usage $usage -Path $item.path
        if(-not(Complete-ResourceUsage -RunDir $runRoot -UsagePath $item.path)){throw 'PowerShell resource usage finalization failed.'}
      }
      if($null-ne$completion.resource_profile){
        Push-Location $repo
        try{& $python -m common.simion.resource_profile publish --run-id $completion.run_id `
          --resource-usage $completion.resource_profile.usage_path --dispatch-plan $completion.resource_profile.dispatch_plan `
          --output $completion.resource_profile.output | Out-Null
          if($LASTEXITCODE-ne0){throw 'PowerShell resource profile publication failed.'}}
        finally{Pop-Location}
      }
    }
    Set-WorkflowStage publication
    Publish-WorkflowTerminal -Python $python -RepoRoot $repo -CompletionPath $completionPath -SessionPath $sessionPath -WaitPath $waitPath `
      -MaximumRunBytes $maximumRunBytes
    $result.terminal_published=$true
    if($inheritedCapacity){
      $result.capacity_ownership='inherited'
      if($request.package.retention_class-eq'compact'-and-not$inheritedAlreadyReady){
        Set-WorkflowStage capacity_finalization
        $null=Invoke-RunCapacityLifecycleAdapter -Python $python -RepoRoot $repo -Action finalize-ready -ArtifactRoot $artifactRoot -RunConfig $package.run_config
        $result.capacity_finalized=$true
      }else{$result.capacity_finalized=$inheritedAlreadyReady}
      $result.resume_action=if($result.capacity_finalized){$null}else{'parent_capacity_owner_finalize'}
      $result.status=$completion.status
      Set-WorkflowStage complete
    }else{
    if($request.package.retention_class-eq'compact'){
      Set-WorkflowStage capacity_finalization
      $null=Invoke-RunCapacityLifecycleAdapter -Python $python -RepoRoot $repo -Action finalize-ready -ArtifactRoot $artifactRoot -RunConfig $package.run_config
    }else{
      # The existing heavy sealing owner rejects every active protection,
      # including ours. All run writes are closed before releasing this lease;
      # a failed seal leaves the registered writing range for owner recovery.
      if(-not$result.lease_released){
        Set-WorkflowStage release
        $null=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repo -Session $session -RemainingCommittedNewBytes 0
        $null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repo -Session $session
        $result.lease_released=$true
      }
      Set-WorkflowStage capacity_finalization
      $sealOutput=Invoke-RunCapacityCommand -Python $python -RepoRoot $repo -Arguments @('-m','common.contracts.run_capacity_lifecycle',
        '--action','seal-stopped-payload','--artifact-root',$artifactRoot,'--run-config',$package.run_config,
        '--owner',$request.package.project,'--confirm-writing-stopped','--retention-reason',$request.package.retention_reason) `
        -FailureLabel 'Workflow stopped payload sealing failed'
      $result.stopped_payload_receipt=(@($sealOutput)-join"`n")|ConvertFrom-Json -AsHashtable
    }
    $result.capacity_finalized=$true
    if(-not$result.lease_released){
      Set-WorkflowStage release
      $null=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repo -Session $session -RemainingCommittedNewBytes 0
      $null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repo -Session $session
      $result.lease_released=$true
    }
    $result.status=$completion.status
    Set-WorkflowStage complete
    }
  }catch{
    $failure=$_
    if($null-eq$sourceExecutionContext-and$_.Exception.Data.Contains('source_execution_context')){
      $result.source_execution_context=$_.Exception.Data['source_execution_context'];$result.execution_request_sha256=$requestHash
      if($_.Exception.Data.Contains('source_execution_aliases_rolled_back')-and$_.Exception.Data['source_execution_aliases_rolled_back']){
        $result.source_execution_aliases_removed=$true
      }else{$sourceExecutionContext=$_.Exception.Data['source_execution_context']}
    }
    if($null-eq$result.exception-and$_.Exception.Data.Contains('prepared_exception')){
      $result.exception=$_.Exception.Data['prepared_exception']
    }
    if($null-eq$result.exception){$result.exception=@{type=$_.Exception.GetType().FullName;message=$_.Exception.Message;notes=@()}}
    else{$result.secondary_errors+=@($_.Exception.Message)}
    $result.resume_action=if($capacityAccountingDeferred){'return_to_capacity_accounting_owner'}elseif($requiresParentOwner){'parent_capacity_owner_finalize'}elseif($writersConfirmed){'resume_finalization'}elseif($preparedStarted){'inspect_writer_completion'}else{'correct_request_and_use_new_run'}
    # No writer was launched before package/preparation setup failed. Once a
    # writer starts, unknown completion must retain the existing protection.
    if($null-ne$session-and-not$preparedStarted-and-not$capacityAccountingDeferred){
      if($null-ne$sourceExecutionContext){
        try{
          Remove-RunSourceExecutionContext -Python $python -RepoRoot $repo -Session $session -SourceReferences $sourceReferences `
            -NativeInputPaths $nativeInputPaths -RunDirectory $runRoot -ExecutionRoot $pathContext.execution_root -RequestSha256 $requestHash -Context $sourceExecutionContext
          $result.source_execution_aliases_removed=$true
        }catch{$result.secondary_errors+=@("Source execution alias cleanup failed: "+$_.Exception.Message)}
      }
      if($null-ne$package){
        try{Remove-RunPackageExecutionAlias -Package $package;$result.execution_alias_removed=$true}
        catch{$result.secondary_errors+=@('Initialization execution alias cleanup failed: '+$_.Exception.Message)}
      }
      try{$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repo -Session $session;$result.lease_released=$true}
      catch{$result.secondary_errors+=@("Capacity lease cleanup failed: $($_.Exception.Message)")}
    }
  }
  finally{Restore-RunEnvironment -Names $contextEnvironmentNames -Snapshot $callerEnvironment}
  if($null-ne$session){$result.lease_id=$session.lease_id}
  $result.writers_confirmed=$writersConfirmed
  Set-WorkflowStage
  $result.elapsed_seconds=$timingBoundary.seconds
  if($null-ne$completion-and$completion.Contains('summary')-and$completion.summary-is[Collections.IDictionary]-and
     $completion.summary.Contains('native_path_preparation')){
    $result.native_path_preparation=$completion.summary.native_path_preparation
  }elseif($null-ne$package-and$null-ne$package.PSObject.Properties['native_path_preparation']){
    $result.native_path_preparation=$package.native_path_preparation
  }
  if($powershellOwner){
    $summaryFields=if($null-ne$completion-and$completion.Contains('summary')-and$completion.summary-is[Collections.IDictionary]){$completion.summary}else{@{}}
    $result.execution_status=if($capacityAccountingDeferred){'capacity_accounting_deferred'}elseif($null-ne$failure){'finalization_failed'}elseif($summaryFields.Contains('execution_status')){$summaryFields.execution_status}else{$result.status}
    $result.data_validity=if($summaryFields.Contains('data_validity')){$summaryFields.data_validity}else{'unknown'}
    $result.scientific_result=if($summaryFields.Contains('scientific_result')){$summaryFields.scientific_result}elseif($summaryFields.Contains('science_status')){$summaryFields.science_status}else{'NOT_EVALUATED'}
    $result.failure_stage=if($null-ne$failure){$result.stage}elseif($summaryFields.Contains('failure_stage')){$summaryFields.failure_stage}else{$null}
    $result.failure_reason=if($null-ne$failure){$failure.Exception.Message}elseif($summaryFields.Contains('failure_reason')){$summaryFields.failure_reason}else{$null}
    $result.recovery_action=if($null-ne$failure-or($inheritedCapacity-and-not$result.capacity_finalized)){$result.resume_action}elseif($summaryFields.Contains('recovery_action')){$summaryFields.recovery_action}else{$null}
    $result.result_path=[IO.Path]::GetFullPath($ResultPath)
    $result.phase_timings_seconds=if($summaryFields.Contains('phase_timings_seconds')){$summaryFields.phase_timings_seconds}elseif($summaryFields.Contains('phase_durations_seconds')){$summaryFields.phase_durations_seconds}else{@{}}
    $priorElapsed=if($summaryFields.Contains('elapsed_before_finalization_seconds')){[double]$summaryFields.elapsed_before_finalization_seconds}elseif($summaryFields.Contains('total_elapsed_seconds')){[double]$summaryFields.total_elapsed_seconds}else{0.0}
    $result.total_elapsed_seconds=$priorElapsed+$result.elapsed_seconds
  }
  try{Write-RunJson -Path $ResultPath -Value $result -Depth 64 -Atomic}
  catch{
    if($null-eq$failure){throw}
    $failure.Exception.Data['workflow_result_publication_error']=$_.Exception.Message
  }
  if($null-ne$failure){$failure.Exception.Data['workflow_result']=$result;throw $failure}
  return [pscustomobject]$result
}

if($MyInvocation.InvocationName-ne'.'){
  if(-not$RequestPath-or-not$ResultPath){throw 'Internal workflow adapter requires RequestPath and ResultPath.'}
  try{
    $outcome=Invoke-RunArtifactWorkflow -RequestPath $RequestPath -ResultPath $ResultPath -ResumeFinalization:$ResumeFinalization
    if($outcome.status-eq'success'){exit 0}
    if($outcome.status-eq'interrupted'){exit 130}
    exit 1
  }catch{Write-Error -ErrorRecord $_ -ErrorAction Continue;exit 1}
}
