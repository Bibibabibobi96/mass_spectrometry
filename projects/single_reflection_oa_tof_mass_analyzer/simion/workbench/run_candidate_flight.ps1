param(
  [Parameter(Mandatory)][string]$ExecutionRequestPath,
  [Parameter(Mandatory)][string]$RuntimeReceiptPath,
  [Parameter(Mandatory)][string]$CapacitySessionPath,
  [Parameter(Mandatory)][string]$PythonExe,
  [Parameter(Mandatory)][string]$RepositoryRoot
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $RepositoryRoot 'common/host_execution_lease.ps1')
. (Join-Path $RepositoryRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $RepositoryRoot 'common/resource_budget_support.ps1')
. (Join-Path $RepositoryRoot 'common/simion/short_pa_path_support.ps1')
$request=Get-Content -LiteralPath $ExecutionRequestPath -Raw|ConvertFrom-Json -Depth 50
$runtime=Get-Content -LiteralPath $RuntimeReceiptPath -Raw|ConvertFrom-Json -Depth 80
$session=Get-Content -LiteralPath $CapacitySessionPath -Raw|ConvertFrom-Json -Depth 80
if($request.schema_version-ne1-or$request.role-ne'oatof_candidate_flight_request'-or
  $runtime.schema_version-ne1-or$runtime.role-ne'oatof_simion_private_runtime'-or$runtime.status-ne'verified'-or
  $request.run_id-ne$runtime.run_id-or$request.context_sha256-ne$runtime.context_sha256-or
  -not$runtime.canonical_iob_verified-or-not$runtime.execution_alias_removed-or$runtime.published_native_members_opened){
  throw 'Flight request does not bind a verified private runtime.'
}
$runtimeDirectory=[IO.Path]::GetFullPath([string]$runtime.output_directory)
if([IO.Path]::GetFullPath([string]$request.cwd)-ne$runtimeDirectory-or
  -not(@($request.argv)-contains'fly')-or
  @($request.argv|Where-Object{[string]$_-eq[string]$runtime.iob.path}).Count-ne1){
  throw 'Flight command must consume its exact verified workbench in its own directory.'
}
$protectedRuns=@($session.protected_paths|Where-Object{
  [IO.Path]::GetFileName([string]$_)-eq[string]$request.run_id-and
  $runtimeDirectory.StartsWith(([IO.Path]::GetFullPath([string]$_)+[IO.Path]::DirectorySeparatorChar),[StringComparison]::OrdinalIgnoreCase)
})
if($session.role-ne'artifact_workflow_capacity_session'-or$session.status-ne'active'-or$protectedRuns.Count-ne1){
  throw 'Flight requires the existing capacity session protecting its exact run.'
}
$runRoot=[IO.Path]::GetFullPath([string]$protectedRuns[0])
foreach($name in @('stdout','stderr','result_receipt')){
  $path=[IO.Path]::GetFullPath([string]$request.$name)
  if(-not$path.StartsWith(($runRoot+[IO.Path]::DirectorySeparatorChar),[StringComparison]::OrdinalIgnoreCase)-or
    (Test-Path -LiteralPath $path)){throw "Flight output is not a fresh run-owned path: $name"}
}
if(-not[string]::Equals((Get-FileHash -LiteralPath ([string]$request.executable) -Algorithm SHA256).Hash,
  [string]$runtime.simion_executable_sha256,[StringComparison]::OrdinalIgnoreCase)){
  throw 'Flight executable differs from the frozen build identity.'
}
$null=Update-ArtifactWorkflowCapacitySession -Python $PythonExe -RepoRoot $RepositoryRoot -Session $session
$lease=$null;$workerCompletion=$null;$hostRelease=$null;$failure=$null
$guards=[Collections.Generic.List[string]]::new()
$operationsStopped=$true
$result=[ordered]@{
  schema_version=1;role='oatof_candidate_flight_process_result';run_id=$request.run_id;case_id=$request.case_id;
  mode=$request.mode;context_sha256=$request.context_sha256;native_returncode=$null;
  native_peak_working_set_bytes=$null;native_elapsed_seconds=$null;native_exit_confirmed=$false;
  managed_process_completion=$null;host_release=$null;exception=$null
}
try{
  $lease=Enter-HostExecutionLease -Role SIMION -Stage flight -RunId ([string]$request.run_id)
  $records=@($runtime.files)+@($runtime.iob)
  foreach($component in $runtime.components){
    if($component.source-ne'published_standalone_responses'){continue}
    $asset=$component.asset
    foreach($record in @($asset.source_raw)+@($asset.source_responses)){
      $records+=@{path=(Join-Path ([string]$asset.generation_directory) ([string]$record.name));bytes=$record.bytes;sha256=$record.sha256}
    }
  }
  $seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
  foreach($record in $records){
    $path=[IO.Path]::GetFullPath([string]$record.path)
    if(-not$seen.Add($path)){throw 'Private runtime inventory contains a duplicate guarded path.'}
    $guard=Protect-ImmutablePaSource -Source $path -ExpectedBytes ([int64]$record.bytes) -ExpectedSha256 ([string]$record.sha256)
    if(-not$guard.already_protected){$guards.Add($path)}
  }
  # SIMION is launched directly. The inner observer waits that native process
  # and measures its root working set; the public outer wait owns the actual
  # Python worker and drains its logs. Neither receipt claims arbitrary forks.
  $code=@'
from common.host_resource_python import await_managed_process_start
await_managed_process_start()
import json,sys,time
from pathlib import Path
from common.simion.process_observation import run_observed_process
from common.contracts.recorded_file_removal import write_json_atomic
request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
result=json.loads(sys.argv[2]);started=time.perf_counter();exit_code=1
try:
    process,peak=run_observed_process([request['executable'],*request['argv']],cwd=Path(request['cwd']),
        stdout=Path(request['stdout']),stderr=Path(request['stderr']),warning_seconds=request['warning_seconds'])
    result.update(native_returncode=process.returncode,native_peak_working_set_bytes=peak,native_exit_confirmed=True)
    exit_code=0 if process.returncode==0 else 1
except BaseException as error:
    result.update(native_returncode=getattr(error,'observed_process_returncode',None),
        native_exit_confirmed=getattr(error,'observed_process_exit_confirmed',False),exception=f'{type(error).__name__}: {error}')
finally:
    result['native_elapsed_seconds']=time.perf_counter()-started
    write_json_atomic(Path(request['result_receipt']),result)
raise SystemExit(exit_code)
'@
  $operationsStopped=$false
  $workerCompletion=Invoke-RepositoryManagedPythonProcess -Python $PythonExe `
    -ArgumentList @('-B','-c',$code,$ExecutionRequestPath,($result|ConvertTo-Json -Depth 20 -Compress)) `
    -WorkingDirectory $RepositoryRoot -StandardOutputPath ([string]$request.result_receipt+'.helper.stdout.log') `
    -StandardErrorPath ([string]$request.result_receipt+'.helper.stderr.log')
  $result=Get-Content -LiteralPath ([string]$request.result_receipt) -Raw|ConvertFrom-Json -AsHashtable -Depth 50
  $operationsStopped=$workerCompletion.ownership_confirmed-and$workerCompletion.worker_exit_confirmed-and
    $workerCompletion.launcher_exit_confirmed-and$workerCompletion.stdout_drained-and$workerCompletion.stderr_drained-and
    $result.native_exit_confirmed
  if(-not$operationsStopped){throw 'Flight helper and native completion are not confirmed.'}
  if($workerCompletion.exit_code-ne0-or$result.native_returncode-ne0){
    throw "Native flight failed: returncode=$($result.native_returncode) exception=$($result.exception)"
  }
}catch{
  $failure=$_
  if($_.Exception.Data.Contains('managed_python_completion')){
    $workerCompletion=$_.Exception.Data['managed_python_completion']
  }
  throw
}finally{
  # FileShare guards last only as long as this owner. Unknown native completion
  # remains a failed, unpublishable run; it is not a durable file-lock promise.
  if(Test-Path -LiteralPath ([string]$request.result_receipt)){
    try{$result=Get-Content -LiteralPath ([string]$request.result_receipt) -Raw|ConvertFrom-Json -AsHashtable -Depth 50}
    catch{if($null-eq$failure){$failure=$_}}
  }
  if($null-ne$workerCompletion){
    $operationsStopped=$workerCompletion.ownership_confirmed-and$workerCompletion.worker_exit_confirmed-and
      $workerCompletion.launcher_exit_confirmed-and$workerCompletion.stdout_drained-and$workerCompletion.stderr_drained-and
      $result.native_exit_confirmed
  }
  if($operationsStopped){
    foreach($path in $guards){
      try{$null=Unprotect-ImmutablePaSource -Source $path}
      catch{if($null-eq$failure){$failure=$_}else{Write-Warning "PA guard validation failed after original error: $_"}}
    }
  }
  if($null-ne$lease){
    $hostRelease=@{inherited=[bool]$lease.inherited;token=[string]$lease.token;result=$null;error=$null}
    try{$hostRelease.result=Exit-HostResourceStage -Lease $lease -PassThru}
    catch{$hostRelease.error=$_.Exception.Message;if($null-eq$failure){$failure=$_}else{Write-Warning "Flight resource release failed after original error: $_"}}
  }
  $result.managed_process_completion=$workerCompletion;$result.host_release=$hostRelease
  if($null-ne$failure){$result.exception=$failure.Exception.Message}
  try{
    Write-RunJson -Path ([string]$request.result_receipt) -Value $result -Depth 80 -Atomic
  }catch{if($null-eq$failure){$failure=$_}else{Write-Warning "Flight receipt publication failed after original error: $_"}}
  if($null-ne$failure){throw $failure}
}
