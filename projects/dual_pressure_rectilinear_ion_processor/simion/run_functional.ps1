[CmdletBinding()]
param([Parameter(Mandatory)][string]$RunId,[string]$SimionExe='',[string]$NativeFieldRun='',[string]$ContinuationPredecessorManifestPath='',
 [string]$ConfigurationDirectory='',[string]$InjectedSource='',
 [ValidateSet('functional','exploration')][string]$SourceProfile='functional',
 [string]$ResultPath='',[switch]$ResumeFinalization)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
function Enter-IonProcessorNativeFlightGuards {
 param($ResolvedModel,$Pa0Record,$Context,[switch]$FreshBuild)
 # The frozen electrode namespace is the authority for numbered responses;
 # controller/geometry/surface names follow the same native controller root.
 $controller=[IO.Path]::GetFullPath($Pa0Record.path)
 $prefix=$controller.Substring(0,$controller.Length-1)
 $paths=@(($prefix+'#'),$controller)+@($ResolvedModel.native_projection.electrode_ids|ForEach-Object{$prefix+[string]$_})+@($prefix+'-surf')
 try {
  if($FreshBuild){
   # Only this run's newly built writable family: all Refine/IOB producers
   # have exited. Commit their delayed pages before persistent-byte identity.
   # Never flush or open an immutable external source for writing.
   foreach($path in $paths){
    $buildStream=$null
    try {
     $buildStream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
     $buildStream.Flush($true)
    } finally {if($null-ne$buildStream){$buildStream.Dispose()}}
   }
  }
  foreach($path in $paths){
   $identity=@{Source=$path}
   if($path-eq$controller-and$Pa0Record.Contains('sha256')){$identity.ExpectedBytes=[long]$Pa0Record.bytes;$identity.ExpectedSha256=[string]$Pa0Record.sha256}
   $guard=Protect-ImmutablePaSource @identity
   $entry=[pscustomobject]@{path=$path;bytes=$guard.bytes;before_sha256=$guard.sha256;after_sha256=$null;
    owns_guard=(-not$guard.already_protected);guard_acquired=$true;verified=$false;error=$null;
    stream=$global:MassSpectrometryImmutablePaSourceGuards[[IO.Path]::GetFullPath($path)].stream}
   $Context.records.Add($entry)
  }
  $Context.status='protected'
 } catch {$Context.error=$_.Exception.Message;throw}
}
function Complete-IonProcessorNativeFlightGuards {
 param($Context,[string]$VerificationPath)
 $errors=[Collections.Generic.List[string]]::new()
 if($Context.status-ne'protected'){$errors.Add('native family guard acquisition incomplete: '+$Context.error)}
 try {
  foreach($entry in $Context.records){
   if(-not$entry.guard_acquired){continue}
   try {
    $live=$global:MassSpectrometryImmutablePaSourceGuards[[IO.Path]::GetFullPath($entry.path)]
    if($null-eq$live-or-not[object]::ReferenceEquals($live.stream,$entry.stream)){throw 'Native family identity protection interrupted during flight'}
    $null=Protect-ImmutablePaSource -Source $entry.path -ExpectedBytes $entry.bytes -ExpectedSha256 $entry.before_sha256
    $entry.after_sha256=$entry.before_sha256
    $entry.verified=$true
   } catch {$entry.error=$_.Exception.Message;$errors.Add($entry.path+': '+$entry.error)}
  }
  $Context.status=$(if($errors.Count){'failed'}else{'verified'})
  Write-RunJson -Path $VerificationPath -Value @{schema_version=1;role='native_flight_family_identity';status=$Context.status;hash_policy='one_identity_read_under_continuous_public_guard';records=@($Context.records|Select-Object -Property * -ExcludeProperty stream);errors=@($errors.ToArray())}
 } finally {
  foreach($entry in $Context.records){
   if(-not$entry.owns_guard){continue}
   $live=$global:MassSpectrometryImmutablePaSourceGuards[[IO.Path]::GetFullPath($entry.path)]
   if($null-ne$live-and[object]::ReferenceEquals($live.stream,$entry.stream)){
    Unprotect-ImmutablePaSource -Source $entry.path|Out-Null
   }
  }
 }
 if($errors.Count){throw ($errors -join '; ')}
}
function Set-IonProcessorAnalysisConclusion {
 param([hashtable]$Summary,[int]$AnalysisExit,[bool]$NativeCompleted)
 $Summary.execution_status=if($AnalysisExit-in@(0,2)){'completed'}else{'analysis_failed'}
 $Summary.data_validity=if($NativeCompleted-and$AnalysisExit-in@(0,2)){'valid'}else{'unknown'}
 $Summary.science_status=if($AnalysisExit-eq0){'passed'}elseif($AnalysisExit-eq2){'not_passed'}else{'unknown'}
 $Summary.analysis_exit_code=$AnalysisExit
 $Summary.diagnostics_complete=$AnalysisExit-in@(0,2)
 $Summary.native_completed=$NativeCompleted
}
function Set-IonProcessorRunStage {
 param([hashtable]$Context,[string]$Stage)
 $elapsed=$Context.timer.Elapsed.TotalSeconds
 $previous=[string]$Context.stage
 $duration=$elapsed-[double]$Context.stage_started_seconds
 if($Context.phase_durations_seconds.Contains($previous)){$Context.phase_durations_seconds[$previous]+=$duration}
 else{$Context.phase_durations_seconds[$previous]=$duration}
 $Context.stage=$Stage;$Context.stage_started_seconds=$elapsed
}
function Set-IonProcessorRunObservation {
 param([hashtable]$Summary,[hashtable]$Context,[string]$Run,[bool]$NativeCompleted,
       [bool]$WritersStopped,[string]$FailureStage='',[string]$FailureReason='')
 $Summary.result_path=Join-Path $Run 'run_manifest.json'
 $Summary.summary_path=Join-Path $Run 'summary.json'
 $Summary.phase_durations_seconds=[ordered]@{}
 foreach($key in $Context.phase_durations_seconds.Keys){$Summary.phase_durations_seconds[$key]=[double]$Context.phase_durations_seconds[$key]}
 $Summary.phase_durations_seconds[$Context.stage]=$Context.timer.Elapsed.TotalSeconds-[double]$Context.stage_started_seconds
 $Summary.total_elapsed_seconds=$Context.timer.Elapsed.TotalSeconds
 $Summary.timing_scope='through_result_observation; final owner total includes publication and release in stdout'
 $Summary.failure_stage=if($FailureStage){$FailureStage}else{$null}
 $Summary.failure_reason=if($FailureReason){$FailureReason}else{$null}
 $Summary.recovery_action=if(-not$WritersStopped){'confirm native writer completion before recovery; preserve protected assets'}
  elseif($FailureStage){'create a new run with -ContinuationPredecessorManifestPath after terminal publication; reuse complete batches and rerun only missing units'}
  else{'none'}
 if(-not$Summary.ContainsKey('execution_status')){$Summary.execution_status=if($FailureStage){'failed'}else{'completed'}}
 if(-not$Summary.ContainsKey('data_validity')){$Summary.data_validity=if($NativeCompleted){'valid'}else{'unknown'}}
 if(-not$Summary.ContainsKey('science_status')){$Summary.science_status='unknown'}
}
function Protect-IonProcessorPreviousField {
 param([string]$FieldRun,$ResolvedModel,$Context)
 $manifestPath=Join-Path $FieldRun 'run_manifest.json'
 try {
 $Context.publication_guard=Enter-RunTerminalConsumptionGuard -RunDirectory $FieldRun
 $Context.manifest_stream=[IO.File]::Open($manifestPath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
 $Context.run_config_stream=[IO.File]::Open((Join-Path $FieldRun 'run_config.json'),[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
 $manifest=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
 if($manifest.project-ne'dual_pressure_rectilinear_ion_processor'-or$manifest.status-notin@('success','failed')){throw 'Prior field requires a terminal project owner'}
 if($null-ne$ResolvedModel.PSObject.Properties['native_field']-and
    $null-ne$ResolvedModel.native_field.PSObject.Properties['source_manifest_sha256']-and
    (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash-ne[string]$ResolvedModel.native_field.source_manifest_sha256){throw 'Prior field manifest changed after input binding'}
 $prefix=Join-Path $FieldRun 'simion/processor.pa'
 $paths=@(($prefix+'#'),($prefix+'0'))+@($ResolvedModel.native_projection.electrode_ids|ForEach-Object{$prefix+[string]$_})+@($prefix+'-surf')
 $records=@($manifest.outputs)+@($manifest.inputs.PSObject.Properties|ForEach-Object{$_.Value})
  foreach($path in $paths){
   $full=[IO.Path]::GetFullPath($path)
   $matches=@($records|Where-Object{
    $value=[string]$_.path
    $candidate=if([IO.Path]::IsPathRooted($value)){$value}else{Join-Path $FieldRun $value}
    [IO.Path]::GetFullPath($candidate)-eq$full
   })
   if($matches.Count-ne1){throw "Prior field manifest does not uniquely bind $full"}
   $guard=Protect-ImmutablePaSource -Source $full -ExpectedBytes ([long]$matches[0].bytes) -ExpectedSha256 ([string]$matches[0].sha256)
   $Context.records.Add([pscustomobject]@{path=$full;owns_guard=(-not$guard.already_protected)})
  }
 } catch {
  foreach($entry in $Context.records){if($entry.owns_guard){Unprotect-ImmutablePaSource -Source $entry.path|Out-Null}}
  $Context.records.Clear()
  foreach($key in @('manifest_stream','run_config_stream','publication_guard')){
   if($Context.ContainsKey($key)-and$null-ne$Context[$key]){$Context[$key].Dispose();$Context[$key]=$null}
  }
  throw
 }
}
function Protect-IonProcessorContinuationInputs {
 param([string]$Predecessor,$Context)
 $manifestPath=Join-Path $Predecessor 'run_manifest.json'
 $manifestIdentity=(Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash
 $manifest=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
 $records=@($manifest.outputs)+@($manifest.inputs.PSObject.Properties|ForEach-Object{$_.Value})+@($manifest.run_config)
 $paths=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
 $null=$paths.Add([IO.Path]::GetFullPath($manifestPath))
 $null=$paths.Add([IO.Path]::GetFullPath((Join-Path $Predecessor 'run_config.json')))
 foreach($record in $records){
  $value=[string]$record.path
  $candidate=if([IO.Path]::IsPathRooted($value)){$value}else{Join-Path $Predecessor $value}
  $full=[IO.Path]::GetFullPath($candidate)
  if((Test-Path -LiteralPath $full -PathType Leaf)-and$full-match'[\\/](inputs[\\/](resolved_model\.json|runtime_profiles\.json|execution_profiles\.json|release\.csv|release_receipt\.json|source\.json|injected_states\.csv)|simion_batch_\d+[\\/](.*\.csv|batch_input\.json)|simion[\\/](processor\.gem|runtime\.lua|collision_hs1\.lua|native_drive\.lua|simion_rf_drive\.lua|voltage_waveforms\.lua|extraction_force_audit\.lua|processor\.fly2|source_states\.lua|(events|samples|collision_rng_seeds|hs1_bound_parameters|extraction_steps|extraction_impulses|native_field_samples)\.csv)|logs[\\/]flight.*\.log|results[\\/](merged_worker_csv_batch_\d+.*|native_batch_completion_\d+\.json|simion_execution_batch_plan\.json|batch_merge_receipt\.json|batch_input_validation_receipt\.json|simion_batch_resource_usage\.json))$'){$null=$paths.Add($full)}
 }
 try {
  foreach($path in $paths){
   $stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
   $Context.streams.Add($stream)
  }
  if((Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash-ne$manifestIdentity){throw 'Continuation manifest changed while acquiring source guards'}
 } catch {
  foreach($stream in $Context.streams){$stream.Dispose()}
  $Context.streams.Clear()
  throw
 }
}
function Invoke-IonProcessorCompletedContinuation {
 param([Parameter(Mandatory)]$Package,[string]$Python,[string]$Run,[string]$Predecessor,[string]$RepoRoot)
 $pythonContext=Get-RunNativeExecutionContext -Package $Package -Paths @((Join-Path $Run 'inputs/code'),$Run) -Tool Python
 $env:PYTHONPATH=$pythonContext.projected_paths[0]
 Push-Location $pythonContext.projected_paths[1]
 try {
  & $Python -m projects.dual_pressure_rectilinear_ion_processor.analysis.functional prepare-continuation --run $Run --baseline-run $Predecessor | Out-Host
  if($LASTEXITCODE-ne0){throw 'IP continuation requires a complete compatible native population'}
 } finally {Pop-Location;$env:PYTHONPATH=$RepoRoot}
 return Enter-HostExecutionLease -StatePath $pathContext.host_resource_state_path -Role SIMION -Stage postprocess
}
function Write-IonProcessorBatchCompletion {
 param($Record,[string]$ResultDirectory,$NativeOperations=$null)
 $batch=$Record.specification.scheduler_batch
 if($null-eq$batch-or-not$Record.completed-or$null-eq$Record.exit_code){throw 'IP completed worker lacks its native owner or batch exit fact'}
 $path=Join-Path $ResultDirectory ('native_batch_completion_{0:D4}.json'-f[int]$batch.index)
 if($null-ne$NativeOperations){
  $NativeOperations.Add(@{operation_id=('fly_batch_'+$batch.index);observation=@{exit_confirmed=$true;returncode=[int]$Record.exit_code;
    process_id=[int]$Record.root_process_id;process_started_at_utc_ticks=[long]$Record.root_process_started_at_utc_ticks};resource_release_id='simion'})|Out-Null
 }
 Write-RunJson -Path $path -Value @{schema_version=1;role='ion_processor_native_batch_completion';batch=$batch;process_name=[string]$Record.name;exit_code=[int]$Record.exit_code;completed=$true}
}
function Add-IonProcessorFailedOperation {
 param([Collections.IDictionary]$Data,[string]$OperationId,$NativeOperations)
 $id=$Data['observed_process_id'];$started=$Data['observed_process_started_at_utc_ticks'];$code=$Data['observed_process_returncode']
 if($Data['observed_process_exit_confirmed']-isnot[bool]-or-not$Data['observed_process_exit_confirmed']-or
    ($id-isnot[int]-and$id-isnot[long])-or[long]$id-le0-or
    ($started-isnot[int]-and$started-isnot[long])-or[long]$started-le0-or
    ($code-isnot[int]-and$code-isnot[long])){return $false}
 $NativeOperations.Add(@{operation_id=$OperationId;observation=@{exit_confirmed=$true;returncode=[int]$code;
   process_id=[int]$id;process_started_at_utc_ticks=[long]$started};resource_release_id='simion'})|Out-Null
 return $true
}
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path
$workspaceRoot=Split-Path -Parent $repoRoot
. (Join-Path $repoRoot 'common/require_powershell7.ps1')
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $repoRoot 'common/resource_budget_support.ps1')
. (Join-Path $repoRoot 'common/simion/short_pa_path_support.ps1')
$python=Join-Path $repoRoot '.venv/Scripts/python.exe'
. (Join-Path $repoRoot 'common/paths/workspace_paths.ps1')
$pathContext=Resolve-WorkspacePaths -SourceRoot $repoRoot -Python $python
if($ResumeFinalization){
 $projectArtifacts=Join-Path $pathContext.artifact_root 'projects/dual_pressure_rectilinear_ion_processor'
 $recoveryRun=Join-Path $projectArtifacts ('runs/'+$RunId)
 if($ResultPath-and(Test-Path -LiteralPath $ResultPath -PathType Leaf)){
  $transport=Get-Content -LiteralPath $ResultPath -Raw|ConvertFrom-Json -AsHashtable
  if($transport.role-ne'run_artifact_workflow_result'-or(Split-Path -Leaf ([string]$transport.run_directory))-cne$RunId){throw 'IP recovery Result identity differs.'}
  $recoveryRun=[string]$transport.run_directory
 }
 if(-not$ResultPath){$ResultPath=Join-Path $projectArtifacts ('scratch/workflow_results/'+$RunId+'/result.json')}
 $requestPath=Join-Path $recoveryRun 'inputs/execution_request.json'
 $request=Get-Content -LiteralPath $requestPath -Raw|ConvertFrom-Json -AsHashtable
 if($request.package.project-cne'dual_pressure_rectilinear_ion_processor'-or$request.package.mode-cne'native_electrode_functional'-or$request.package.run_id-cne$RunId){throw 'IP recovery request identity differs.'}
 . (Join-Path $repoRoot 'common/contracts/run_artifact_workflow.ps1') -RequestPath $requestPath -ResultPath $ResultPath -ResumeFinalization
 $outcome=Invoke-RunArtifactWorkflow -RequestPath $requestPath -ResultPath $ResultPath -ResumeFinalization
 Write-Output "ION_PROCESSOR_FINALIZATION=$($outcome.status) RUN_ID=$RunId RESULT=$ResultPath"
 if($outcome.status-ne'success'){exit 1}
 return
}
. (Join-Path $repoRoot 'common/contracts/run_artifact_workflow.ps1') -ResultPath $ResultPath
if(-not $SimionExe){$SimionExe=Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe'}
if(-not(Test-Path -LiteralPath $SimionExe)){throw 'SIMION 2020 executable missing'}
if($ContinuationPredecessorManifestPath-and$NativeFieldRun){throw 'Completed-population continuation obtains its field identity from the explicit predecessor; do not supply a second field source'}
$runtimeRegistry=Get-Content (Join-Path $projectRoot 'config/runtime_profiles.json') -Raw|ConvertFrom-Json
if($runtimeRegistry.role-ne'ion_processor_runtime_profiles'-or$runtimeRegistry.project_id-ne'dual_pressure_rectilinear_ion_processor'-or$runtimeRegistry.schema_version-ne1){throw 'Runtime profile identity differs'}
$profiles=@($runtimeRegistry.profiles|Where-Object{$_.profile_id-eq'native_functional'})
if($profiles.Count-ne1){throw 'Exactly one native_functional runtime profile is required'}
$profile=$profiles[0]
$configurationRoot=if($ConfigurationDirectory){(Resolve-Path -LiteralPath $ConfigurationDirectory).Path}else{Join-Path $projectRoot 'config'}
if($profile.retain_batch_trajectories-isnot[bool]){throw 'Runtime profile retain_batch_trajectories must be boolean'}
if($profile.native_field_query_memory_bytes-isnot[long]-and$profile.native_field_query_memory_bytes-isnot[int]){throw 'Native query memory declaration must be integer bytes'}
if($profile.native_field_query_memory_bytes-le0){throw 'Native query memory declaration must be positive'}
$retainBatchTrajectories=[int]$profile.retain_batch_trajectories
$committedNewBytes=[long]$profile.committed_new_bytes
if($NativeFieldRun){
 $sourceFile=$(if($SourceProfile-eq'exploration'){'source_exploration.json'}else{'source.json'})
 $count=(Get-Content (Join-Path $configurationRoot $sourceFile) -Raw|ConvertFrom-Json).particle_count
 $committedNewBytes=[long][Math]::Max(2GB,([long]$count*50MB+256MB))
}
$artifacts=[string]$pathContext.artifact_root
$projectArtifacts=Join-Path $artifacts 'projects/dual_pressure_rectilinear_ion_processor'
$capacity=$null;$package=$null;$lease=$null;$finished=$false;$runSucceeded=$false;$writersStopped=$true;$nativeCompleted=$false;$nativeContext=$null
$primaryRunFailure=$null
$ownerContext=$null;$nativeOperations=[Collections.Generic.List[object]]::new();$hostRelease=$null
$runObservation=@{timer=[Diagnostics.Stopwatch]::StartNew();stage='startup';stage_started_seconds=0.0;phase_durations_seconds=[ordered]@{}}
$failureStage='';$failureReason=''
$partialContinuation=$false;$partialReplayCount=0;$continuationFieldRun=$null;$continuationFieldGuards=@{records=[Collections.Generic.List[object]]::new();manifest_stream=$null;run_config_stream=$null;publication_guard=$null}
$continuationReadGuards=@{streams=[Collections.Generic.List[object]]::new()}
$pathEnvironmentNames=@('MASS_SPECTROMETRY_ARTIFACT_ROOT','MASS_SPECTROMETRY_EXECUTION_ROOT','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH','MASS_SPECTROMETRY_RUN_DIRECTORY','MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY')
$savedPathEnvironment=Save-RunEnvironment -Names $pathEnvironmentNames
$savedPythonPath=$env:PYTHONPATH;$env:PYTHONPATH=$repoRoot
Push-Location $repoRoot
try {
 $artifactPrefix=[IO.Path]::GetFullPath($artifacts).TrimEnd([IO.Path]::DirectorySeparatorChar)+[IO.Path]::DirectorySeparatorChar
 $protected=@();$sourceReferences=@();$injectedAuthorities=@();$continuationAuthorities=@()
 if([IO.Path]::GetFullPath($configurationRoot).StartsWith($artifactPrefix,[StringComparison]::OrdinalIgnoreCase)){$protected+=@($configurationRoot)}
 if($InjectedSource){
  $InjectedSource=(Resolve-Path -LiteralPath $InjectedSource).Path
  $projection=& $python -c 'import json,sys;from pathlib import Path;from projects.dual_pressure_rectilinear_ion_processor.analysis.upstream_admission import injected_source_protection_paths;print(json.dumps([str(p) for p in injected_source_protection_paths(Path(sys.argv[1]))]))' $InjectedSource
  if($LASTEXITCODE-ne0){throw 'Injected source protection projection failed'}
  $injectedAuthorities=@(($projection|ConvertFrom-Json))
  foreach($path in $injectedAuthorities){if([IO.Path]::GetFullPath($path).StartsWith($artifactPrefix,[StringComparison]::OrdinalIgnoreCase)){$protected+=@($path)}}
  $referenceCode=@'
import json,sys
from pathlib import Path
from common.contracts.verify_run_manifest import record_path
source=Path(sys.argv[1]);contract=json.loads(source.read_text(encoding='utf-8-sig'))
paths=[Path(p).resolve() for p in json.loads(sys.argv[2])];refs=[];covered=set()
for name in ('producer_manifest','preparation_manifest'):
    record=contract.get(name)
    if record is None: continue
    manifest=record_path(record,base_dir=source.parent)
    if manifest.name!='run_manifest.json': raise ValueError(name+' is not an explicit run manifest')
    selected=[p for p in paths if p==manifest.parent or manifest.parent in p.parents]
    if selected:
        refs.append(dict(manifest_record={**record,'path':str(manifest)},protected_paths=list(map(str,selected)),protected_cache_keys=[]));covered.update(selected)
root=Path(sys.argv[3]).resolve()
unbound=[str(p) for p in paths if not p.is_relative_to(root) and p not in covered]
if unbound: raise ValueError('Injected source lacks explicit producer/preparation manifest coverage: '+repr(unbound))
print(json.dumps(refs))
'@
  $references=& $python -c $referenceCode $InjectedSource (ConvertTo-Json -InputObject @($injectedAuthorities) -Compress) $artifacts
  if($LASTEXITCODE-ne0){throw 'Injected source protection requires explicit original-owner producer/preparation manifest evidence.'}
  $sourceReferences+=@(($references|ConvertFrom-Json -AsHashtable -Depth 100))
 }
 if($NativeFieldRun){
  $NativeFieldRun=(Resolve-Path -LiteralPath $NativeFieldRun).Path
  $record=& $python -c 'import json,sys;from pathlib import Path;from common.contracts.write_run_manifest import file_record;print(json.dumps(file_record(Path(sys.argv[1])/"run_manifest.json")))' $NativeFieldRun
  if($LASTEXITCODE-ne0){throw 'Native field requires explicit original-owner manifest evidence.'}
  $sourceReferences+=@{manifest_record=($record|ConvertFrom-Json -AsHashtable);protected_paths=@($NativeFieldRun);protected_cache_keys=@()}
 }
 if($ContinuationPredecessorManifestPath){
  $ContinuationPredecessorManifestPath=(Resolve-Path -LiteralPath $ContinuationPredecessorManifestPath).Path
  if([IO.Path]::GetFileName($ContinuationPredecessorManifestPath)-cne'run_manifest.json'){throw 'Continuation requires an explicit predecessor manifest'}
  $predecessor=Split-Path -Parent $ContinuationPredecessorManifestPath
  $projection=& $python -c 'import json,sys;from pathlib import Path;from projects.dual_pressure_rectilinear_ion_processor.analysis.batching import continuation_protection_paths;print(json.dumps([str(p) for p in continuation_protection_paths(Path(sys.argv[1]))]))' $predecessor
  if($LASTEXITCODE-ne0){throw 'IP continuation ancestry protection projection failed'}
  $continuationAuthorities=@(($projection|ConvertFrom-Json))
  $records=& $python -c 'import json,sys;from pathlib import Path;from common.contracts.write_run_manifest import file_record;print(json.dumps([dict(manifest_record=file_record(Path(p)/"run_manifest.json"),protected_paths=[p],protected_cache_keys=[]) for p in json.loads(sys.argv[1])]))' (ConvertTo-Json -InputObject @($continuationAuthorities) -Compress)
  if($LASTEXITCODE-ne0){throw 'IP continuation lacks explicit original-owner manifest evidence.'}
  $sourceReferences+=@(($records|ConvertFrom-Json -AsHashtable -Depth 100))
  $required=@('results/batch_merge_receipt.json','results/batch_input_validation_receipt.json','results/simion_execution_batch_plan.json','results/simion_batch_resource_usage.json','simion/events.csv','simion/samples.csv','simion/collision_rng_seeds.csv','simion/hs1_bound_parameters.csv','simion/extraction_steps.csv','simion/extraction_impulses.csv','simion/native_field_samples.csv','logs/flight.log')
  $partialContinuation=@($required|Where-Object{-not(Test-Path -LiteralPath (Join-Path $predecessor $_) -PathType Leaf)-and-not($_-eq'simion/native_field_samples.csv'-and(Test-Path -LiteralPath (Join-Path $predecessor 'inputs/partial_batch_replay/field_source.json') -PathType Leaf))}).Count-gt0
  if($partialContinuation){
   $sourceModel=Get-Content (Join-Path $predecessor 'inputs/resolved_model.json') -Raw|ConvertFrom-Json
   $continuationFieldRun=if($sourceModel.native_field.source_manifest){Split-Path -Parent ([string]$sourceModel.native_field.source_manifest)}else{Split-Path -Parent ([string]$sourceModel.native_field.directory)}
   $continuationFieldRun=(Resolve-Path -LiteralPath $continuationFieldRun).Path
   $record=& $python -c 'import json,sys;from pathlib import Path;from common.contracts.write_run_manifest import file_record;print(json.dumps(file_record(Path(sys.argv[1])/"run_manifest.json")))' $continuationFieldRun
   if($LASTEXITCODE-ne0){throw 'Continuation field requires explicit original-owner manifest evidence.'}
   $sourceReferences+=@{manifest_record=($record|ConvertFrom-Json -AsHashtable);protected_paths=@($continuationFieldRun);protected_cache_keys=@()}
  }
 }
 $capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifacts -RunDirectory (Join-Path $projectArtifacts "runs/$RunId") -CommittedNewBytes $committedNewBytes -ProtectedPaths $protected -SourceReferences $sourceReferences -Owner ("run-artifact-workflow:dual_pressure_rectilinear_ion_processor:{0}"-f$RunId)
 $package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $projectArtifacts -RunId $RunId -Project dual_pressure_rectilinear_ion_processor -Mode native_electrode_functional -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass $profile.retention_class -RetentionReason $profile.retention_reason -CapacityLedgerLifecycleEnabled -PathContext $pathContext -AdditionalDirectories @('simion')
 $run=$package.artifact_run_dir;$solver=Join-Path $run 'simion'
 $parentEnvironment=(Get-RunNativeExecutionContext -Package $package -Paths @()).environment
 foreach($key in $parentEnvironment.Keys){[Environment]::SetEnvironmentVariable([string]$key,[string]$parentEnvironment[$key],'Process')}

 $ownerPath=Join-Path $package.input_dir 'run_functional.ps1';$ownerIdentity=$null
 Copy-VerifiedRunInput -Source $PSCommandPath -Destination $ownerPath -VerifiedIdentity ([ref]$ownerIdentity)|Out-Null
 $budgetInput=Join-Path $package.input_dir 'runtime_profiles.json'
 Copy-VerifiedRunInput (Join-Path $projectRoot 'config/runtime_profiles.json') $budgetInput|Out-Null
 $ownerContext=Initialize-RunArtifactPowerShellOwner -Python $python -RepoRoot $repoRoot -Package $package -CapacitySession $capacity `
  -ResultPath $ResultPath -EntrypointPath $ownerPath -EntrypointRecord @{path=$ownerIdentity.path;exists=$true;bytes=$ownerIdentity.bytes;sha256=$ownerIdentity.sha256} `
  -CommitmentInputPaths @($budgetInput) -Software @('SIMION 2020','Python 3.11')
 $ResultPath=$ownerContext.result_path
 Set-IonProcessorRunStage -Context $runObservation -Stage prepare
 $prepareArguments=@('-m','projects.dual_pressure_rectilinear_ion_processor.analysis.functional','prepare','--run',$run,'--simion-dir',(Split-Path -Parent $SimionExe),'--source-profile',$SourceProfile)
 if($ConfigurationDirectory){$prepareArguments+=@('--configuration-directory',$configurationRoot)}
 if($NativeFieldRun){$prepareArguments+=@('--native-field-run',$NativeFieldRun)}
 if($InjectedSource){$prepareArguments+=@('--injected-source',$InjectedSource)}
 foreach($path in $injectedAuthorities){$prepareArguments+=@('--protected-injected-path',[string]$path)}
 & $python @prepareArguments
 if($LASTEXITCODE-ne0){throw 'Input preparation failed'}
 $profile.limits.transient_run_directory_bytes=$committedNewBytes
 $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
 $config.inputs.runtime_profiles=Join-Path $package.input_dir 'runtime_profiles.json'
 $config.inputs.execution_request=$ownerContext.request_path
 Write-RunJson -Path $package.run_config -Value $config
 $resolvedSource=(Get-Content (Join-Path $package.input_dir 'resolved_model.json') -Raw|ConvertFrom-Json).source
 if($InjectedSource-and$resolvedSource.particle_count-eq0){
  & $python -m projects.dual_pressure_rectilinear_ion_processor.analysis.functional analyze --run $run
  if($LASTEXITCODE-ne0){throw 'Empty upstream admission publication failed'}
  $finished=$true;$runSucceeded=$true
  Write-Output "ION_PROCESSOR_RESULT=empty_upstream_admission RUN=$run SOLVER_EXECUTED=false"
  return
 }
 if($NativeFieldRun-and-not$partialContinuation){
  $model=Get-Content (Join-Path $package.input_dir 'resolved_model.json') -Raw|ConvertFrom-Json
  Protect-IonProcessorPreviousField -FieldRun $NativeFieldRun -ResolvedModel $model -Context $continuationFieldGuards
 }
 if($ContinuationPredecessorManifestPath){
  $projection=& $python -c 'import json,sys;from pathlib import Path;from projects.dual_pressure_rectilinear_ion_processor.analysis.batching import continuation_protection_paths;print(json.dumps([str(p) for p in continuation_protection_paths(Path(sys.argv[1]))]))' $predecessor
  if($LASTEXITCODE-ne0-or($projection|ConvertFrom-Json|ConvertTo-Json -Compress)-cne($continuationAuthorities|ConvertTo-Json -Compress)){throw 'IP continuation ancestry changed after capacity admission'}
  foreach($source in $continuationAuthorities){Protect-IonProcessorContinuationInputs -Predecessor $source -Context $continuationReadGuards}
 }
 if($partialContinuation){
  Set-IonProcessorRunStage -Context $runObservation -Stage continuation_plan
  $pythonContext=Get-RunNativeExecutionContext -Package $package -Paths @((Join-Path $run 'inputs/code'),$run) -Tool Python
  $env:PYTHONPATH=$pythonContext.projected_paths[0];Push-Location $pythonContext.projected_paths[1]
  try {
   & $python -m projects.dual_pressure_rectilinear_ion_processor.analysis.functional prepare-partial-continuation --run $run --baseline-run $predecessor | Out-Host
   if($LASTEXITCODE-ne0){throw 'IP partial continuation planning failed'}
   $partialPlan=Get-Content (Join-Path $run 'inputs/partial_batch_replay/simion_whole_unit_replay_plan.json') -Raw|ConvertFrom-Json
   $partialReplayCount=[int]$partialPlan.replay_unit_count
   Copy-Item -LiteralPath (Join-Path $run 'inputs/partial_batch_replay/batch_plan.json') -Destination (Join-Path $package.result_dir 'simion_execution_batch_plan.json')
   & $python -m projects.dual_pressure_rectilinear_ion_processor.analysis.functional restore-partial-batches --run $run | Out-Host
   if($LASTEXITCODE-ne0){throw 'IP partial continuation materialization failed'}
   if($partialReplayCount-gt0){
    $model=Get-Content (Join-Path $run 'inputs/resolved_model.json') -Raw|ConvertFrom-Json
    $expectedFieldRun=if($model.native_field.source_manifest){Split-Path -Parent ([string]$model.native_field.source_manifest)}else{Split-Path -Parent ([string]$model.native_field.directory)}
    if([IO.Path]::GetFullPath($expectedFieldRun)-ne[IO.Path]::GetFullPath($continuationFieldRun)){throw 'Continuation field authority changed after capacity admission'}
    Protect-IonProcessorPreviousField -FieldRun $continuationFieldRun -ResolvedModel $model -Context $continuationFieldGuards
    & $python -m projects.dual_pressure_rectilinear_ion_processor.analysis.functional adopt-native-field --run $run --native-field-run $continuationFieldRun | Out-Host
    if($LASTEXITCODE-ne0){throw 'IP continuation field binding failed'}
    $NativeFieldRun=$continuationFieldRun
   }
  } finally {Pop-Location;$env:PYTHONPATH=$repoRoot}
 }
 if($ContinuationPredecessorManifestPath-and-not$partialContinuation){
  $lease=Invoke-IonProcessorCompletedContinuation -Package $package -Python $python -Run $run -Predecessor $predecessor -RepoRoot $repoRoot
  $nativeCompleted=$true
  Write-Output "ION_PROCESSOR_CONTINUATION=REANALYZE PREDECESSOR=$predecessor RUN=$run NATIVE_STARTS=0"
 } elseif($partialContinuation-and$partialReplayCount-eq0){
  $lease=Enter-HostExecutionLease -StatePath $pathContext.host_resource_state_path -Role SIMION -Stage postprocess
  $pythonContext=Get-RunNativeExecutionContext -Package $package -Paths @((Join-Path $run 'inputs/code'),$run) -Tool Python
  $env:PYTHONPATH=$pythonContext.projected_paths[0];Push-Location $pythonContext.projected_paths[1]
  try {
   & $python -m projects.dual_pressure_rectilinear_ion_processor.analysis.functional merge-batches --run $run --batch-plan (Join-Path $run 'inputs/partial_batch_replay/batch_plan.json') | Out-Host
   if($LASTEXITCODE-ne0){throw 'IP reused batch merge failed'}
   $count=@($partialPlan.units|Where-Object{$_.action-eq'reuse'}).Count
   Write-RunJson -Path (Join-Path $package.result_dir 'simion_batch_resource_usage.json') -Value @{schema_version=2;role='multipole_resource_usage';status='completed';failure_class=$null;limit_name=$null;execution_wave=@{process_count=0;reused_batch_count=$count}}
  } finally {Pop-Location;$env:PYTHONPATH=$repoRoot}
  $nativeCompleted=$true
  Write-Output "ION_PROCESSOR_CONTINUATION=REUSE_BATCHES PREDECESSOR=$predecessor RUN=$run NATIVE_STARTS=0"
 } else {
 Set-IonProcessorRunStage -Context $runObservation -Stage native_preparation
 $lease=Enter-HostExecutionLease -StatePath $pathContext.host_resource_state_path -Role SIMION -Stage prepare
 $numerics=Get-Content (Join-Path $package.input_dir 'numerics.json') -Raw|ConvertFrom-Json
 $commands=@(
  @{name='gem';stage='prepare';arguments=@('--nogui','--noprompt','gem2pa','processor.gem','processor.pa#')},
  @{name='refine';stage='pa_refine';arguments=@('--nogui','--noprompt','refine',"--convergence=$($numerics.refine_convergence_v)",'processor.pa#')},
  @{name='workbench';stage='prepare';arguments=@('--nogui','--noprompt','lua',(Join-Path $solver 'build_workbench.lua'))},
  @{name='potential_audit';stage='prepare';arguments=@('--nogui','--noprompt','lua',(Join-Path $solver 'probe_native_field.lua'))}
 )
 if($NativeFieldRun){$commands=@($commands|Where-Object{$_.name-notin@('gem','refine')})}
 Copy-VerifiedRunInput (Join-Path $solver 'runtime.lua') (Join-Path $solver 'processor.lua')|Out-Null
 $nativeModel=Get-Content (Join-Path $package.input_dir 'resolved_model.json') -Raw|ConvertFrom-Json
 $nativePaths=@($solver,(Join-Path $solver 'processor.gem'),(Join-Path $solver 'processor.pa#'),
  (Join-Path $solver 'processor.pa0'),(Join-Path $solver 'processor.iob'),(Join-Path $solver 'processor.lua'),
  (Join-Path $solver 'processor.fly2'),(Join-Path $solver 'build_workbench.lua'),(Join-Path $solver 'probe_native_field.lua'),
  [string]$nativeModel.workbench_seed_path)
 $nativeContext=Get-RunNativeExecutionContext -Package $package -Paths $nativePaths
 foreach($command in $commands){
  Set-IonProcessorRunStage -Context $runObservation -Stage $command.name
  $stageBudget=Get-HostResourceBudget -Role SIMION -Stage $command.stage
  if($command.name-eq'potential_audit'){$stageBudget.memory_bytes=[long]$profile.native_field_query_memory_bytes}
  $lease=Update-HostResourceStage -Lease $lease -Stage $command.stage -Budget $stageBudget -RetainedMemoryBytes 0
  Write-Output "ION_PROCESSOR_STAGE=$($command.name) RUN=$RunId"
  $writersStopped=$false
  try {
   $result=Invoke-ResourceBudgetedProcess -Limits $profile.limits -RunDir $run -UsagePath (Join-Path $package.result_dir "$($command.name)_resource_usage.json") -FilePath $SimionExe -ArgumentList (Project-RunPath -Paths $command.arguments -ArtifactRunDir $package.artifact_run_dir -RunDir $nativeContext.run_dir -Python $python) -WorkingDirectory $nativeContext.projected_paths[0] -Environment $nativeContext.environment -RedirectStandardOutput (Join-Path $package.log_dir "$($command.name).log") -RedirectStandardError (Join-Path $package.log_dir "$($command.name).stderr.log")
   $writersStopped=$true
   $nativeOperations.Add(@{operation_id=[string]$command.name;observation=@{exit_confirmed=$true;returncode=[int]$result.exit_code;
     process_id=[int]$result.root_process_id;process_started_at_utc_ticks=[long]$result.root_process_started_at_utc_ticks};resource_release_id='simion'})|Out-Null
  } catch {
   $writersStopped=Add-IonProcessorFailedOperation -Data $_.Exception.Data -OperationId ([string]$command.name) -NativeOperations $nativeOperations
   throw
  }
  if($result.exit_code-ne0){throw "SIMION $($command.name) failed: $($result.exit_code)"}
 }
 # Public dispatch controls every native particle flight. Use only the frozen
 # Python closure, and keep the original heavy permission through all workers.
 $nativeFlightGuardContext=$null
 Set-IonProcessorRunStage -Context $runObservation -Stage flight
 $pythonContext=Get-RunNativeExecutionContext -Package $package -Paths @((Join-Path $run 'inputs/code'),$run) -Tool Python
 $env:PYTHONPATH=$pythonContext.projected_paths[0]
 Push-Location $pythonContext.projected_paths[1]
 try {
  function Invoke-PreparedPython {
   param([string[]]$Arguments)
   $execution=Get-RunNativeExecutionContext -Package $package -Paths @((Join-Path $run 'inputs/code')) -Tool Python
   Invoke-RunToolRootContext -RepoRoot $execution.projected_paths[0] -Environment $execution.environment -Operation {
    & $python @Arguments | Out-Host
    if($LASTEXITCODE-ne0){throw "Prepared Python boundary failed: $($Arguments -join ' ')"}
   }
  }
  $resolvedModel=Get-Content (Join-Path $run 'inputs/resolved_model.json') -Raw|ConvertFrom-Json -AsHashtable
  $dispatchArguments=@('-m','projects.dual_pressure_rectilinear_ion_processor.analysis.functional','prepare-dispatch','--run',$run)
  if(-not$resolvedModel.native_field.source_manifest){
   $nativeFlightGuardContext=@{records=[Collections.Generic.List[object]]::new();status='acquiring';error=$null}
   $controller=Join-Path $resolvedModel.native_field.directory 'processor.pa0'
   Enter-IonProcessorNativeFlightGuards -ResolvedModel $resolvedModel -Pa0Record @{path=$controller} -Context $nativeFlightGuardContext -FreshBuild
   $controllerIdentity=Protect-ImmutablePaSource -Source $controller
   $dispatchArguments+=@('--native-pa0-record',($controllerIdentity|Select-Object path,bytes,sha256|ConvertTo-Json -Compress))
  }
  Invoke-PreparedPython -Arguments $dispatchArguments
  $iobPreparation=Get-Content (Join-Path $run 'inputs/batch_iob_preparation.json') -Raw|ConvertFrom-Json
  if($iobPreparation.requires_vendor_templates){
   $paRecord=$iobPreparation.native_pa0_record
   $nativeContext=Get-RunNativeExecutionContext -Package $package -Paths @($solver,[string]$iobPreparation.script,[string]$paRecord.path)
   $guard=Protect-ImmutablePaSource -Source $paRecord.path -ExpectedBytes $paRecord.bytes -ExpectedSha256 $paRecord.sha256
   try {
    $writersStopped=$false
    try {
     $build=Invoke-ResourceBudgetedProcess -Limits $profile.limits -RunDir $run -UsagePath (Join-Path $package.result_dir 'batch_iob_template_resource_usage.json') -FilePath $SimionExe -ArgumentList @('--nogui','--noprompt','lua',(Project-RunPath -Path $iobPreparation.script -ArtifactRunDir $package.artifact_run_dir -RunDir $nativeContext.run_dir -Python $python)) -WorkingDirectory $nativeContext.projected_paths[0] -Environment $nativeContext.environment -RedirectStandardOutput (Join-Path $package.log_dir 'batch_iob_templates.log') -RedirectStandardError (Join-Path $package.log_dir 'batch_iob_templates.stderr.log')
     $writersStopped=$true
     $nativeOperations.Add(@{operation_id='batch_iob_templates';observation=@{exit_confirmed=$true;returncode=[int]$build.exit_code;
       process_id=[int]$build.root_process_id;process_started_at_utc_ticks=[long]$build.root_process_started_at_utc_ticks};resource_release_id='simion'})|Out-Null
    } catch {
     $writersStopped=Add-IonProcessorFailedOperation -Data $_.Exception.Data -OperationId batch_iob_templates -NativeOperations $nativeOperations
     throw
    }
    if($build.exit_code-ne0){throw 'Native batch IOB template preparation failed'}
    $null=Protect-ImmutablePaSource -Source $paRecord.path -ExpectedBytes $paRecord.bytes -ExpectedSha256 $paRecord.sha256
   } finally {if($writersStopped-and-not$guard.already_protected){Unprotect-ImmutablePaSource -Source $paRecord.path|Out-Null}}
  }
  $requestPath=Join-Path $run 'inputs/simion_dispatch_request.json'
  $profilesPath=Join-Path $run 'results/simion_resource_profiles.json'
  $dispatchPath=Join-Path $run 'results/simion_repository_dispatch_plan.json'
  $batchPlanPath=Join-Path $run 'results/simion_execution_batch_plan.json'
  $usagePath=Join-Path $run 'results/simion_batch_resource_usage.json'
  Invoke-PreparedPython -Arguments @('-m','common.simion.resource_profile','discover','--runs-root',(Join-Path $projectArtifacts 'runs'),'--output',$profilesPath)
  Invoke-PreparedPython -Arguments @('-m','common.simion.resource_scheduler','--request',$requestPath,'--profiles',$profilesPath,'--output',$dispatchPath)
  Invoke-PreparedPython -Arguments @('-m','common.simion.particle_batching','--from-dispatch-plan',$dispatchPath,'--output',$batchPlanPath)
  if($partialContinuation){
   $oldPlanPath=Join-Path $run 'inputs/partial_batch_replay/batch_plan.json'
   $oldPlan=Get-Content $oldPlanPath -Raw|ConvertFrom-Json
   $replayKeys=@($partialPlan.units|Where-Object{$_.action-eq'replay'}|ForEach-Object{$_.key})
   $fixedArguments=@('-m','common.simion.resource_scheduler','--prepare-fixed-recovery-plan',$dispatchPath,'--fixed-batch-plan',$oldPlanPath,'--profiles',$profilesPath,'--output',$dispatchPath)
   foreach($batch in $oldPlan.batches){if(('batch_{0:D4}'-f[int]$batch.index)-in$replayKeys){$fixedArguments+=@('--replay-batch-index',[string]$batch.index)}}
   Invoke-PreparedPython -Arguments $fixedArguments
   Copy-Item -LiteralPath $oldPlanPath -Destination $batchPlanPath -Force
  }
  Invoke-PreparedPython -Arguments @('-m','projects.dual_pressure_rectilinear_ion_processor.analysis.functional','materialize-batches','--run',$run,'--batch-plan',$batchPlanPath)
  function New-IonProcessorProcessSpecification {
   param($Batch)
   $folder=Join-Path $run ('simion_batch_{0:D4}'-f[int]$Batch.index)
   $paths=@($folder,(Join-Path $folder 'processor.iob'),(Join-Path $folder 'processor.lua'),(Join-Path $folder 'processor.fly2'))
   $batchExecution=Get-RunNativeExecutionContext -Package $package -Paths $paths
   return [pscustomobject]@{
    name=('ion_processor_batch_{0:D4}'-f[int]$Batch.index);scheduler_batch=$Batch
    file_path=$SimionExe;working_directory=$batchExecution.projected_paths[0];environment=$batchExecution.environment
    stdout=(Join-Path $package.log_dir ('flight_batch_{0:D4}.log'-f[int]$Batch.index))
    stderr=(Join-Path $package.log_dir ('flight_batch_{0:D4}.stderr.log'-f[int]$Batch.index))
    argument_list=[string[]]@('--nogui','--noprompt','fly','--trajectory-quality',"$($numerics.trajectory_quality)",'--particles','processor.fly2','--programs','1','--retain-trajectories',"$retainBatchTrajectories",'processor.iob')
   }
  }
  $dispatch=Get-Content $dispatchPath -Raw|ConvertFrom-Json
  $initial=Get-Content $batchPlanPath -Raw|ConvertFrom-Json
  $unknown=$dispatch.estimation.kind-eq'formal_first_batch_observation'
  $formalIndex=$null
  $lease=Update-HostResourceStage -Lease $lease -Stage flight -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
  $writersStopped=$false
  try {
   $firstSpecification=$null;$replan=$null
   if($unknown){
    $first=if($partialContinuation){
     @($initial.batches|Where-Object{[int]$_.index-eq[int]$dispatch.estimation.observed_missing_batch_index})[0]
    }else{$initial.batches[0]}
    $formalIndex=[int]$first.index
    $replan={
    param($formal)
    $sourceArguments=if($partialContinuation){@('--recovered-missing-plan',$dispatchPath)}else{@('--request',$requestPath,'--profiles',$profilesPath)}
    $adaptive=@('-m','common.simion.resource_scheduler')+$sourceArguments+@('--output',$dispatchPath,'--observed-formal-peak-bytes',"$($formal.observed_peak_process_tree_working_set_bytes)",'--observed-formal-cpu-percent',"$($formal.observed_process_cpu_percent)",'--observed-background-cpu-percent',"$($formal.observed_background_cpu_percent)",'--available-memory-bytes',"$($formal.available_memory_bytes)",'--total-physical-memory-bytes',"$($formal.total_physical_memory_bytes)")
    if($formal.process_record.completed){$adaptive+='--first-batch-completed'}
    Invoke-PreparedPython -Arguments $adaptive
    if(-not$partialContinuation){
     Invoke-PreparedPython -Arguments @('-m','common.simion.particle_batching','--from-dispatch-plan',$dispatchPath,'--output',$batchPlanPath)
     Invoke-PreparedPython -Arguments @('-m','projects.dual_pressure_rectilinear_ion_processor.analysis.functional','materialize-batches','--run',$run,'--batch-plan',$batchPlanPath)
    }
    }
    $firstSpecification=New-IonProcessorProcessSpecification $first
   }
   # Persist each owner's natural exit as it is observed, including successful
   # siblings when a later worker fails.  A log sentinel alone cannot prove
   # that the native process subsequently exited successfully.
   $checkpoint={param($record) Write-IonProcessorBatchCompletion -Record $record -ResultDirectory $package.result_dir -NativeOperations $nativeOperations}
   $prepareRemaining={param($formal)
    $final=Get-Content $batchPlanPath -Raw|ConvertFrom-Json
    $pending=@($final.batches|Where-Object{($null-eq$formalIndex-or[int]$_.index-ne$formalIndex)-and(-not$partialContinuation-or('batch_{0:D4}'-f[int]$_.index)-in$replayKeys)}|ForEach-Object{New-IonProcessorProcessSpecification $_})
    [pscustomobject]@{pending=$pending}
   }
   $wave=Invoke-SimionBatchPhase -DispatchPlanPath $dispatchPath -RunDir $run -UsagePath $usagePath -FirstSpecification $firstSpecification -Replan $replan -PrepareRemaining $prepareRemaining -OnProcessCompleted $checkpoint
   $writersStopped=-not[bool]$wave.resource_budget_exceeded
   if($wave.resource_budget_exceeded-or@($wave.processes|Where-Object{[int]$_.exit_code-ne0}).Count){throw 'Native particle dispatch failed or exceeded public resources'}
  } catch {
   $primaryFailure=$_
   if($primaryFailure.Exception.Data['simion_wave_writer_completion_confirmed']){$writersStopped=$true}
   throw $primaryFailure
  }
  Complete-ResourceUsage -RunDir $run -UsagePath $usagePath|Out-Null
  if($partialContinuation){
   $usage=Get-Content $usagePath -Raw|ConvertFrom-Json -AsHashtable
   $usage.execution_wave.reused_batch_count=@($partialPlan.units|Where-Object{$_.action-eq'reuse'}).Count
   Write-RunJson -Path $usagePath -Value $usage
  }
  if($unknown){Invoke-PreparedPython -Arguments @('-m','common.simion.resource_profile','publish','--run-id',$RunId,'--resource-usage',$usagePath,'--resource-usage-relative-path','results/simion_batch_resource_usage.json','--dispatch-plan',$dispatchPath,'--dispatch-plan-relative-path','results/simion_repository_dispatch_plan.json','--output',(Join-Path $run 'results/simion_resource_profile.json'))}
  Invoke-PreparedPython -Arguments @('-m','projects.dual_pressure_rectilinear_ion_processor.analysis.functional','merge-batches','--run',$run,'--batch-plan',$batchPlanPath)
  $nativeCompleted=$true
 } finally {
  try {
   if($writersStopped-and$null-ne$nativeFlightGuardContext){Complete-IonProcessorNativeFlightGuards -Context $nativeFlightGuardContext -VerificationPath (Join-Path $run 'results/native_flight_family_verification.json')}
  } finally {Pop-Location;$env:PYTHONPATH=$repoRoot}
 }
 }
 $lease=Update-HostResourceStage -Lease $lease -Stage postprocess -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
 Set-IonProcessorRunStage -Context $runObservation -Stage analysis
 # Run the prepared source closure from the run directory so an editable repo
 # cannot shadow it through Python's current-directory import precedence.
 $pythonContext=Get-RunNativeExecutionContext -Package $package -Paths @((Join-Path $run 'inputs/code'),$run) -Tool Python
 $env:PYTHONPATH=$pythonContext.projected_paths[0]
 Push-Location $pythonContext.projected_paths[1]
 try {
  & $python -m projects.dual_pressure_rectilinear_ion_processor.analysis.functional analyze --run $run
  $analysisExit=$LASTEXITCODE
 } finally {Pop-Location;$env:PYTHONPATH=$repoRoot}
 if($analysisExit-ne0-and-not(Test-Path -LiteralPath $package.summary)){throw 'Analysis did not publish measured summary'}
 $summary=Get-Content $package.summary -Raw|ConvertFrom-Json -AsHashtable
 if($summary.role-ne'ion_processor_functional_summary'){throw 'Missing physical summary'}
 Set-IonProcessorAnalysisConclusion -Summary $summary -AnalysisExit $analysisExit -NativeCompleted $nativeCompleted
 $summary.native_path_preparation=$package.native_path_preparation
 Write-RunJson -Path $package.summary -Value $summary
 $finished=$true
 $runSucceeded=$analysisExit-eq0
 Write-Output "ION_PROCESSOR_RESULT=$($summary.status) RUN=$run"
 if($analysisExit-ne0){throw 'Analysis or required diagnostics incomplete; see frozen summary and logs'}
} catch {
 $primaryRunFailure=$_
 if(-not$finished){$failureStage=[string]$runObservation.stage;$failureReason=$_.Exception.Message}
 if($null-ne$package-and-not$finished){
  $failed=@{schema_version=1;role='ion_processor_failed_run';status=$(if($writersStopped){'failed'}else{'writer_completion_unknown'});reason=$_.Exception.Message;drain_error=$_.Exception.Data['simion_first_batch_drain_error'];verification_error=$_.Exception.Data['simion_first_batch_verification_error'];wait_error=$_.Exception.Data['ion_processor_formal_wait_error']}
  Set-IonProcessorRunObservation -Summary $failed -Context $runObservation -Run $package.artifact_run_dir -NativeCompleted $nativeCompleted -WritersStopped $writersStopped -FailureStage $failureStage -FailureReason $failureReason
  $failed.native_path_preparation=$package.native_path_preparation
 Write-RunJson -Path $package.summary -Value $failed
 }
 throw
} finally {
 try {
  Set-IonProcessorRunStage -Context $runObservation -Stage finalization
  if($null-ne$ownerContext){
   if(-not$writersStopped){
    Complete-RunArtifactPowerShellOwner -Context $ownerContext -Status failed -Summary @{} `
     -WriterCompletion @{operations=@();resource_releases=@()} -WritersStopped $false -OriginalFailure $primaryRunFailure|Out-Null
   }
   $releases=@()
   if($null-ne$lease){
    $token=[string]$lease.token;$wasInherited=[bool]$lease.inherited
    if($wasInherited){
     $release=Invoke-HostResourceTransaction -StatePath $lease.state_path -Request @{operation='inherit';token=$token}
     if($release.status-cne'acquired'-or$release.token-cne$token){throw 'IP inherited host grant is unconfirmed.'}
     Exit-HostResourceStage -Lease $lease
    }else{
     $release=Exit-HostResourceStage -Lease $lease -PassThru
     if($null-eq$release-or$release.status-cne'released'-or$release.token-cne$token){throw 'IP host release is unconfirmed.'}
    }
    if($nativeOperations.Count){$releases+=@{release_id='simion';completion_receipt=@{host_release=@{
      inherited=$wasInherited;token=$token;result=@{status=[string]$release.status;token=$token};error=$null}}}}
    $lease=$null
   }elseif($nativeOperations.Count){throw 'IP native operations lack their actual host release.'}
   $observed=Get-Content -LiteralPath $package.summary -Raw|ConvertFrom-Json -AsHashtable
   Set-IonProcessorRunObservation -Summary $observed -Context $runObservation -Run $package.artifact_run_dir -NativeCompleted $nativeCompleted -WritersStopped $writersStopped -FailureStage $failureStage -FailureReason $failureReason
   $observed.native_path_preparation=$package.native_path_preparation
 Write-RunJson -Path $package.summary -Value $observed
   $status=$(if($runSucceeded){'success'}else{'failed'})
   $configuration=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
   $inputPaths=@($configuration.inputs.Values|Where-Object{$_-is[string]}|ForEach-Object{[IO.Path]::GetFullPath($_)})
   $outputs=@(Get-ChildItem -LiteralPath $run -File -Recurse|Where-Object{
     $_.FullName-notin$inputPaths-and$_.Name-notin@('run_config.json','run_manifest.json')-and-not$_.Name.StartsWith('.')
   }|ForEach-Object{$_.FullName})
   $outcome=Complete-RunArtifactPowerShellOwner -Context $ownerContext -Status $status -Summary $observed -OutputPaths $outputs `
    -WriterCompletion @{operations=@($nativeOperations.ToArray());resource_releases=@($releases)} -WritersStopped $writersStopped -OriginalFailure $primaryRunFailure
   $capacity=$null
   Write-Output "ION_PROCESSOR_WORKFLOW_RESULT=$($ownerContext.result_path) FINALIZATION=$($outcome.status)"
  }
 } catch {
  if($null-ne$primaryRunFailure){
   $primaryRunFailure.Exception.Data['ion_processor_finalization_error']=[string]$_
   Write-Warning "IP finalization also failed: $_"
  } else {throw}
 } finally {
  Write-Output "ION_PROCESSOR_OBSERVATION STAGE=$($runObservation.stage) FAILURE_STAGE=$failureStage FAILURE_REASON=$failureReason TOTAL_SECONDS=$($runObservation.timer.Elapsed.TotalSeconds)"
  if($null-ne$package){Write-Output "ION_PROCESSOR_PATHS MANIFEST=$($package.artifact_run_dir)/run_manifest.json SUMMARY=$($package.summary)"}
  if($writersStopped){foreach($stream in $continuationReadGuards.streams){$stream.Dispose()}}
  if($writersStopped){foreach($entry in $continuationFieldGuards.records){if($entry.owns_guard){Unprotect-ImmutablePaSource -Source $entry.path|Out-Null}}}
  if($writersStopped){foreach($key in @('manifest_stream','run_config_stream','publication_guard')){
   if($continuationFieldGuards.ContainsKey($key)-and$null-ne$continuationFieldGuards[$key]){$continuationFieldGuards[$key].Dispose()}
  }}
  if($writersStopped-and$null-ne$capacity-and$null-eq$ownerContext){Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -Session $capacity|Out-Null}
  if($writersStopped-and$null-ne$package){Remove-RunPackageExecutionAlias -Package $package}
  Restore-RunEnvironment -Names $pathEnvironmentNames -Snapshot $savedPathEnvironment
  $env:PYTHONPATH=$savedPythonPath
  Pop-Location
 }
}
