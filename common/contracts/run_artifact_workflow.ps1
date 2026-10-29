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

function Assert-WorkflowWriterCompletion {
  param($Completion)
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
    if($hostRelease.inherited-isnot[bool]-or$hostRelease.inherited-or
       $hostRelease.token-isnot[string]-or[string]::IsNullOrWhiteSpace($hostRelease.token)-or
       $null-ne$hostRelease.error){throw 'Resource owner release is unconfirmed or inherited.'}
    Assert-WorkflowFields $hostRelease.result @('status','token') 'Released transaction'
    if($hostRelease.result.status-cne'released'-or$hostRelease.result.token-cne$hostRelease.token){
      throw 'Resource owner release identity or terminal state differs.'
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
    Assert-WorkflowFields $operation.observation @('exit_confirmed','returncode') 'Native observation'
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
    [string]$SessionPath,[string]$CompletionPath,[string]$WaitPath,[string]$LogRoot,[string]$HostStatePath)
  # The public handshake owns the actual Python worker handle, including when
  # a venv launcher exits first. It adds no host grant or private process tree.
  $runner=@'
from common.host_resource_python import await_managed_process_start
await_managed_process_start()
import importlib, json, sys
from pathlib import Path
from common.contracts.recorded_file_removal import write_json_atomic
request_path, config, session, completion, wait_path = map(Path, sys.argv[1:])
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
  $receipt=$null;$failure=$null;$childFailure=$null
  try{
    $receipt=Invoke-RepositoryManagedPythonProcess -Python $Python `
      -ArgumentList @('-B','-c',$runner,$ExecutionRequest,$RunConfig,$SessionPath,$CompletionPath,$WaitPath) `
      -WorkingDirectory $request.prepared.import_root `
      -StandardOutputPath (Join-Path $LogRoot 'prepared_stdout.log') -StandardErrorPath (Join-Path $LogRoot 'prepared_stderr.log') `
      -Environment @{PYTHONPATH=$request.prepared.import_root;PYTHONNOUSERSITE='1';PYTHONDONTWRITEBYTECODE='1';
        MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=$HostStatePath}
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
outputs = list(dict.fromkeys([*outputs, summary_path, completion_path, session_path, wait_path, retention_path,
                            root / "logs/prepared_stdout.log", root / "logs/prepared_stderr.log"]))
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
    & $Python -B -c $publisher $CompletionPath $SessionPath $WaitPath ([string]$MaximumRunBytes)
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
  $maximumRunBytes=$null;$python=$null;$repo=$null
  try{
    $requestFile=(Resolve-Path -LiteralPath $RequestPath).Path
    $requestHash=(Get-FileHash -LiteralPath $requestFile -Algorithm SHA256).Hash
    $request=Get-Content -LiteralPath $requestFile -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    Assert-WorkflowFields $request @('schema_version','role','repository_root','python_executable','package','capacity','prepared','payload') 'Workflow request'
    if($request.schema_version-ne1-or$request.role-cne'run_artifact_workflow_request'){throw 'Workflow request identity differs.'}
    Assert-WorkflowFields $request.package @('project','run_id','mode','artifact_project_root','software','retention_class','retention_reason') 'Workflow package'
    Assert-WorkflowFields $request.capacity @('committed_new_bytes','commitment_inputs','protected_paths','protected_cache_keys') 'Workflow capacity'
    Assert-WorkflowFields $request.prepared @('module','function','import_root','entrypoint') 'Prepared call'
    $budget=$request.capacity.committed_new_bytes
    if($budget-isnot[long]-and$budget-isnot[int]-or$budget-lt0){throw 'Workflow capacity requires a known nonnegative integer commitment.'}
    foreach($name in @('commitment_inputs','protected_paths','protected_cache_keys')){
      if($request.capacity[$name]-isnot[array]){throw "Workflow capacity $name must be an array."}
    }
    if(-not$request.capacity.commitment_inputs.Count){throw 'Workflow capacity requires its budget authority inputs.'}
    if(-not$ResumeFinalization){foreach($record in $request.capacity.commitment_inputs){Assert-WorkflowFileRecord $record}}
    $call=$request.prepared
    if($call.module-isnot[string]-or$call.module-notmatch'^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$'-or
       $call.module-eq'__main__'-or$call.function-cne'execute_prepared_run'){throw 'Workflow prepared call is invalid.'}
    if(-not$ResumeFinalization){
      $importRoot=(Resolve-Path -LiteralPath $call.import_root).Path
      Assert-WorkflowFileRecord $call.entrypoint (Join-Path $importRoot ($call.module.Replace('.','/')+'.py'))
    }
    $repo=(Resolve-Path -LiteralPath $request.repository_root).Path
    $python=(Resolve-Path -LiteralPath $request.python_executable).Path
    # Resolve from the live public owner before any frozen source is imported.
    # This is control-plane context, not a scientific input or a new reservation.
    $hostStatePath=Resolve-HostResourceStatePath
    $result.execution_context=@{host_resource_state_path=$hostStatePath}
    $projectRoot=[IO.Path]::GetFullPath($request.package.artifact_project_root)
    $artifactRoot=Split-Path -Parent (Split-Path -Parent $projectRoot)
    $runRoot=Join-Path (Join-Path $projectRoot 'runs') $request.package.run_id
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
      $initial=Get-Content -LiteralPath $package.run_config -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
      $sessionPath=Join-Path $runRoot 'logs/capacity_session.json'
      $session=Get-Content -LiteralPath $sessionPath -Raw -Encoding UTF8|ConvertFrom-Json
      $expectedOwner="run-artifact-workflow:{0}:{1}"-f$request.package.project,$request.package.run_id
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
      $completionPath=Join-Path $runRoot 'results/execution_completion.json'
      $waitPath=Join-Path $runRoot 'logs/prepared_wait.json'
    }else{
    Set-WorkflowStage admission
    $session=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repo -ArtifactRoot $artifactRoot `
      -RunDirectory $runRoot -CommittedNewBytes $budget -ProtectedPaths $request.capacity.protected_paths `
      -ProtectedCacheKeys $request.capacity.protected_cache_keys -Owner ("run-artifact-workflow:{0}:{1}"-f$request.package.project,$request.package.run_id)
    Set-WorkflowStage initialize
    $package=New-RunPackage -Python $python -RepoRoot $repo -ArtifactRoot $projectRoot `
      -RunId $request.package.run_id -Project $request.package.project -Mode $request.package.mode `
      -Software $request.package.software -RetentionContractEnabled -RetentionClass $request.package.retention_class `
      -RetentionReason $request.package.retention_reason -CapacityLedgerLifecycleEnabled -CapacityLedgerArtifactRoot $artifactRoot
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
    Write-RunJson -Path $sessionPath -Value $session -Depth 64
    $completionPath=Join-Path $runRoot 'results/execution_completion.json'
    $waitPath=Join-Path $runRoot 'logs/prepared_wait.json'
    Set-WorkflowStage prepared
    Assert-WorkflowFileRecord $call.entrypoint
    foreach($record in $request.capacity.commitment_inputs){Assert-WorkflowFileRecord $record}
    $preparedStarted=$true
    $null=Invoke-PreparedWorkflowProcess -Python $python `
      -ExecutionRequest $frozenRequest -RunConfig $package.run_config -SessionPath $sessionPath `
      -CompletionPath $completionPath -WaitPath $waitPath -LogRoot (Join-Path $runRoot 'logs') -HostStatePath $hostStatePath
    }
    Set-WorkflowStage completion
    $wait=Get-Content -LiteralPath $waitPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    $result.exception=$wait.exception
    $process=$wait.managed_process
    if($wait.role-cne'run_artifact_prepared_wait'-or$null-ne$wait.observation_error-or
       $process.role-cne'repository_managed_python_completion'-or
       ($process.exit_code-isnot[int]-and$process.exit_code-isnot[long])){throw 'Prepared process completion is unconfirmed.'}
    foreach($fact in @('ownership_confirmed','worker_exit_confirmed','launcher_exit_confirmed','stdout_drained','stderr_drained')){
      if($process[$fact]-isnot[bool]-or-not$process[$fact]){throw "Prepared process $fact is unconfirmed."}
    }
    $result.prepared_exit_code=$process.exit_code
    $completion=Get-Content -LiteralPath $completionPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
    Assert-WorkflowFields $completion @('schema_version','role','run_id','project','execution_request','run_config',
      'status','summary','output_paths','required_output_paths','retention_preserve_paths',
      'manifest_extra_fields','writer_completion','exception') 'Workflow completion'
    if($null-ne$completion.exception){$result.exception=$completion.exception}
    if($completion.schema_version-ne1-or$completion.role-cne'run_artifact_workflow_completion'-or
       $completion.run_id-cne$request.package.run_id-or$completion.project-cne$request.package.project-or
       $completion.status-notin@('success','failed','interrupted')){throw 'Workflow completion identity or status differs.'}
    Assert-WorkflowFileRecord $completion.execution_request $frozenRequest
    Assert-WorkflowFileRecord $completion.run_config $package.run_config
    Assert-WorkflowWriterCompletion $completion.writer_completion
    if($completion.summary-isnot[Collections.IDictionary]-or$completion.summary.status-cne$completion.status-or
       $completion.summary.run_id-cne$completion.run_id){throw 'Workflow scientific summary identity differs.'}
    if($completion.status-eq'success'-and($null-ne$result.exception-or$result.prepared_exit_code-ne0)){
      throw 'Successful completion contradicts the prepared process result.'
    }
    if($completion.manifest_extra_fields-isnot[Collections.IDictionary]){throw 'Workflow manifest extras must be an object.'}
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
        if($path-isnot[string]-or-not[IO.Path]::IsPathFullyQualified($path)-or
           (-not(Test-Path -LiteralPath $path -PathType Leaf)-and-not$removedByRetention)){
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
    $writersConfirmed=$true
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
          -ProtectedCacheKeys $request.capacity.protected_cache_keys -Owner $expectedOwner
        $result.recovery_session=$session
        $result.execution_request_sha256=$requestHash
        $result.recovery_maximum_run_bytes=$maximumRunBytes
        # Persist the fresh session outside the run before any recovery write.
        Write-RunJson -Path $ResultPath -Value $result -Depth 64 -Atomic
      }
    }
    if(-not$terminalWithoutJournal){
      $null=Update-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repo -Session $session
    }
    Set-WorkflowStage retention
    $hasRetention=Test-Path -LiteralPath (Join-Path $runRoot 'retention_actions.json') -PathType Leaf
    if($terminalWithoutJournal-and-not$hasRetention){throw 'Published workflow has no completed retention evidence.'}
    $null=Apply-RunArtifactRetention -Python $python -RepoRoot $repo -RunConfig $package.run_config `
      -PreservePaths $completion.retention_preserve_paths -FailedRun:($completion.status-ne'success') `
      -RecoveryInputs $recoveryInputs -Resume:($ResumeFinalization-and$hasRetention) -MaximumRunBytes $maximumRunBytes
    Set-WorkflowStage publication
    Publish-WorkflowTerminal -Python $python -RepoRoot $repo -CompletionPath $completionPath -SessionPath $sessionPath -WaitPath $waitPath `
      -MaximumRunBytes $maximumRunBytes
    $result.terminal_published=$true
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
  }catch{
    $failure=$_
    if($null-eq$result.exception-and$_.Exception.Data.Contains('prepared_exception')){
      $result.exception=$_.Exception.Data['prepared_exception']
    }
    if($null-eq$result.exception){$result.exception=@{type=$_.Exception.GetType().FullName;message=$_.Exception.Message;notes=@()}}
    else{$result.secondary_errors+=@($_.Exception.Message)}
    $result.resume_action=if($writersConfirmed){'resume_finalization'}elseif($preparedStarted){'inspect_writer_completion'}else{'correct_request_and_use_new_run'}
    # No writer was launched before package/preparation setup failed. Once a
    # writer starts, unknown completion must retain the existing protection.
    if($null-ne$session-and-not$preparedStarted){
      try{$null=Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repo -Session $session;$result.lease_released=$true}
      catch{$result.secondary_errors+=@("Capacity lease cleanup failed: $($_.Exception.Message)")}
    }
  }
  if($null-ne$session){$result.lease_id=$session.lease_id}
  $result.writers_confirmed=$writersConfirmed
  Set-WorkflowStage
  $result.elapsed_seconds=$timingBoundary.seconds
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
