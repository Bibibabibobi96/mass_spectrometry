[CmdletBinding(DefaultParameterSetName="Run")]
param(
 [Parameter(Mandatory,ParameterSetName="Run")][string]$Request,
 [Parameter(Mandatory,ParameterSetName="Resume")][switch]$ResumeFinalization,
 [string]$ResultPath='',
 [string]$RepoRoot=(Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))),
 [string]$Python='',
 [switch]$ValidateOnly,
 [switch]$PrepareOnly,
 [switch]$SolverAuthorized,
 [string]$OutputDirectory='',
 [string]$ExecutionBudgetPath=''
)
# Public local bare-guide/OA workflow; ownership is independent of source paths.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if(-not$ResumeFinalization){
if(([int][bool]$ValidateOnly+[int][bool]$PrepareOnly+[int][bool]$SolverAuthorized)-ne1){throw 'Select exactly one local frontend execution mode.'}
if($PrepareOnly-and-not$OutputDirectory){throw 'PrepareOnly requires a caller-owned managed OutputDirectory.'}
if(-not$PrepareOnly-and$OutputDirectory){throw 'OutputDirectory is accepted only for PrepareOnly; native runs always receive a fresh identity.'}
if($SolverAuthorized-and-not$ExecutionBudgetPath){throw 'SolverAuthorized requires ExecutionBudgetPath.'}
}
$RepoRoot=(Resolve-Path -LiteralPath $RepoRoot).Path
. (Join-Path $RepoRoot 'common/contracts/run_artifact_workflow.ps1') -ResultPath $ResultPath -ResumeFinalization:$ResumeFinalization
if($ResumeFinalization){
 $resumeOverrides=@('Python','ValidateOnly','PrepareOnly','SolverAuthorized','OutputDirectory','ExecutionBudgetPath')
 if(@($resumeOverrides|Where-Object{$PSBoundParameters.ContainsKey($_)}).Count){throw 'ResumeFinalization uses the original frozen operation; new input or execution-scope arguments are not accepted.'}
 if(-not$ResultPath){throw 'ResumeFinalization requires the original ResultPath.'}
 $prior=Get-Content -LiteralPath $ResultPath -Raw -Encoding UTF8|ConvertFrom-Json -AsHashtable
 $result=Invoke-RunArtifactWorkflow -RequestPath (Join-Path $prior.run_directory 'inputs/execution_request.json') -ResultPath $ResultPath -ResumeFinalization
 Write-Output $result
 if($result.status-ne'success'){
  if($result.stage-eq'complete'){throw ("Local finalization completed; original terminal status is {0}. Inspect Result for the original failure."-f[string]$result.status)}
  throw 'Local finalization remains incomplete; inspect Result recovery_action.'
 }
 return
}
$Request=(Resolve-Path -LiteralPath $Request).Path
if(-not$Python){$Python=Join-Path $RepoRoot '.venv/Scripts/python.exe'}
$Python=(Resolve-Path -LiteralPath $Python).Path
. (Join-Path $RepoRoot 'common/require_powershell7.ps1')
. (Join-Path $RepoRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $RepoRoot 'common/paths/workspace_paths.ps1')
$pathContext=Resolve-WorkspacePaths -SourceRoot $RepoRoot -Python $Python
. (Join-Path $RepoRoot 'integrations/runtime/engineering_budget.ps1')
. (Join-Path $RepoRoot 'common/resource_budget_support.ps1')
. (Join-Path $RepoRoot 'common/simion/short_pa_path_support.ps1')
$integration='instrument_assembly'
$sharedRuntime='integrations/runtime'
$workflowModule='integrations.workflows.local_frontend'
. (Join-Path $RepoRoot 'integrations/runtime/dependencies.ps1')
$workspace=Split-Path -Parent $RepoRoot
$artifacts=[string]$pathContext.artifact_root
$projectArtifacts=Join-Path $artifacts ('projects/'+$integration)
$script:pythonRoot=$RepoRoot
$script:run=$null;$script:sequence=0

function Invoke-LocalWorkflowPython {
 param([string[]]$Arguments,[switch]$Json,[switch]$NoCapture)
 $script:sequence++
 if($script:run-and-not$NoCapture){
  $stdout=Join-Path $script:run ('logs/python_{0:D3}.stdout.log'-f$script:sequence)
  $stderr=Join-Path $script:run ('logs/python_{0:D3}.stderr.log'-f$script:sequence)
  Invoke-RunToolRootContext -RepoRoot $script:pythonRoot -Operation {
   &$Python -B @Arguments 1>$stdout 2>$stderr
   if($LASTEXITCODE-ne0){throw "Local workflow Python failed: $($Arguments -join ' '); see $stderr"}
  }
  if($Json){return Get-Content -LiteralPath $stdout -Raw|ConvertFrom-Json -Depth 100}
  Get-Content -LiteralPath $stdout|Write-Host
 }else{
  Invoke-RunToolRootContext -RepoRoot $script:pythonRoot -Operation {
   &$Python -B @Arguments
   if($LASTEXITCODE-ne0){throw 'Local frontend validation/preparation failed.'}
  }
 }
}

function Invoke-LocalFlightPhase {
 param([ValidateSet('discovery','extraction')][string]$Phase,[double]$PulseTime,[string]$SharedTimesPath)
 return Invoke-FrontendFlightPhase -RunDirectory $script:run -ProjectRunsRoot (Join-Path $projectArtifacts 'runs') `
  -RepoRoot $script:pythonRoot -Python $Python -RuntimeModule ($workflowModule+'.runtime') `
  -SimionExe $simion -Limits $budget.limits -Phase $Phase -PulseTimeUs $PulseTime -SharedTimesPath $SharedTimesPath `
  -NativeOperations $nativeOperations -NativeResourceReleaseId ([string]$lease.token)
}

function Invoke-LocalRecordedAnalysis {
 param($Materialized,[string]$Phase,[string]$Times,[double]$PulseTime)
 $logs=Join-Path $script:run "inputs/$Phase.native_logs.json"
 Write-RunJson -Path $logs -Value @($Materialized.batches|ForEach-Object{[string]$_.stdout})
 $code=@'
import json,sys
from pathlib import Path
from integrations.workflows.local_frontend.analyze import analyze_local_frontend
run,logs,times=map(Path,sys.argv[1:4]);phase=sys.argv[4]
print(json.dumps(analyze_local_frontend(run,[Path(p) for p in json.loads(logs.read_text())],phase=phase,shared_times_us=json.loads(times.read_text()),pulse_time_us=float(sys.argv[5]) if phase=='extraction' else None),allow_nan=False))
'@
 return Invoke-LocalWorkflowPython -Arguments @('-c',$code,$script:run,$logs,$Times,$Phase,$PulseTime.ToString('G17',[Globalization.CultureInfo]::InvariantCulture)) -Json
}

function Close-LocalHostStage {
 if(-not$lease){return}
 $token=[string]$lease.token
 try{$released=Exit-HostResourceStage -Lease $lease -PassThru}catch{$script:writerUnknown=$true;$script:hostReleaseUnknown=$true;throw}
 if(-not$lease.inherited-and($null-eq$released-or$released.status-ne'released'-or$released.token-ne$token)){
  $script:writerUnknown=$true;$script:hostReleaseUnknown=$true;throw 'Local host release is unconfirmed.'
 }
 if(@($nativeOperations|Where-Object resource_release_id -eq $token).Count){
  Add-RunArtifactResourceRelease -ResourceReleases $resourceReleases -ReleaseId $token -Receipt @{host_release=@{inherited=[bool]$lease.inherited;token=$token;result=$released;error=$null}}
 }
 $script:lease=$null
}
function Register-LocalInputs {
 $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable -Depth 100
 foreach($file in Get-ChildItem -LiteralPath $package.input_dir -Recurse -File){
  $relative=[IO.Path]::GetRelativePath($package.input_dir,$file.FullName)
  $config.inputs[$relative]=Join-Path (Join-Path $package.artifact_run_dir 'inputs') $relative
 }
 $config.parameters=@{workflow='local_frontend';scientific_request=(Join-Path $package.artifact_run_dir 'inputs/request.json');execution_budget=$(if($budget){Convert-WorkflowOwnerPath $ownerContext $budget.frozen_budget}else{$ExecutionBudgetPath});stage=$stage;gui_executed=$false;full_analyzer_flight_executed=$false}
 Write-RunJson -Path $package.run_config -Value $config -Depth 100
}
function Set-LocalStage([string]$Name){
 if($stage){$phaseTimings[$stage]=[double]$stageClock.Elapsed.TotalSeconds}
 $script:stage=$Name;$stageClock.Restart()
}

$compilerArgs=@('-m',($workflowModule+'.prepare'),'--request',$Request,'--workspace-root',$workspace)
if($ValidateOnly){Invoke-LocalWorkflowPython -Arguments ($compilerArgs+@('--validate-only'));return}
if($PrepareOnly){
 if(-not(Test-Path -LiteralPath (Join-Path $OutputDirectory 'run_config.json'))){throw 'PrepareOnly output must already be owned by a managed run.'}
 $owner=Get-Content -LiteralPath (Join-Path $OutputDirectory 'run_config.json') -Raw|ConvertFrom-Json
 if($owner.project-ne$integration){throw 'PrepareOnly managed run owner must be instrument_assembly.'}
 Invoke-LocalWorkflowPython -Arguments ($compilerArgs+@('--output-directory',[IO.Path]::GetFullPath($OutputDirectory),'--run-id',[string]$owner.run_id))
 return
}
$ExecutionBudgetPath=(Resolve-Path -LiteralPath $ExecutionBudgetPath).Path
$rawBudget=Get-Content -LiteralPath $ExecutionBudgetPath -Raw|ConvertFrom-Json -Depth 80
$commitment=[long]$rawBudget.stage_limits.single_flight_transport.transient_run_directory_bytes
if($commitment-le0){throw 'Positive existing single-flight stage disk commitment required.'}
$runId=(Get-Date -Format yyyyMMdd_HHmmss)+'__sim__simion__local-bare-guide-oa'
$destination=Join-Path $projectArtifacts ('runs/'+$runId)
$author=Get-Content -LiteralPath $Request -Raw|ConvertFrom-Json -Depth 100
# Capacity disposal owns artifact paths; repository author inputs are frozen by
# preparation and must not be submitted as artifact-retirement protections.
$artifactPrefix=[IO.Path]::GetFullPath($artifacts)+[IO.Path]::DirectorySeparatorChar
$protected=@(@($Request,$ExecutionBudgetPath,[IO.Path]::GetFullPath([string]$author.composition_plan.path,(Split-Path -Parent $Request)))+@($author.source.PSObject.Properties.Value|ForEach-Object{Join-Path $workspace ([string]$_.path)})|Where-Object{[IO.Path]::GetFullPath($_).StartsWith($artifactPrefix,[StringComparison]::OrdinalIgnoreCase)})
$capacity=$null;$package=$null;$lease=$null;$budget=$null;$stage='capacity_startup';$failure=$null
$workingFieldGuards=[Collections.Generic.List[string]]::new()
$writerUnknown=$false;$hostReleaseUnknown=$false;$ownerContext=$null;$scientificSummary=$null
$nativeOperations=[Collections.Generic.List[object]]::new();$resourceReleases=[Collections.Generic.List[object]]::new()
$phaseTimings=[ordered]@{};$stageClock=[Diagnostics.Stopwatch]::StartNew();$runClock=[Diagnostics.Stopwatch]::StartNew()
$oldEnvironment=Save-RunEnvironment -Names @('PYTHONPATH','PYTHONNOUSERSITE','SIMULATION_PYTHON_EXE','MASS_SPECTROMETRY_ARTIFACT_ROOT','MASS_SPECTROMETRY_EXECUTION_ROOT','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH','MASS_SPECTROMETRY_RUN_DIRECTORY','MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY')
$env:SIMULATION_PYTHON_EXE=$Python
try {
 $capacity=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -ArtifactRoot $artifacts -RunDirectory $destination -CommittedNewBytes $commitment -ProtectedPaths $protected -Owner ("run-artifact-workflow:{0}:{1}"-f$integration,$runId)
 $package=New-RunPackage -Python $Python -RepoRoot $RepoRoot -ArtifactRoot $projectArtifacts -RunId $runId -Project $integration -Mode local_frontend -Software @('SIMION 2020','Python 3.11') `
  -RetentionContractEnabled -RetentionClass solver_review -RetentionReason 'Retain local RF/OA fields, complete source and losses, actual occupancy pulse selection, automatic diagnostics and independent GUI loading files' -CapacityLedgerLifecycleEnabled -PathContext $pathContext
 $script:run=[string]$package.artifact_run_dir
 $parentEnvironment=(Get-RunNativeExecutionContext -Package $package -Paths @()).environment
 foreach($key in $parentEnvironment.Keys){[Environment]::SetEnvironmentVariable([string]$key,[string]$parentEnvironment[$key],'Process')}
 Copy-VerifiedRunInput -Source $PSCommandPath -Destination (Join-Path $package.input_dir 'execute_local_frontend.ps1')|Out-Null
 Set-LocalStage 'engineering_budget'
 $budget=Initialize-IntegrationStageBudget -ResolvedBudget $ExecutionBudgetPath -InputDir $package.input_dir -ExpectedIntegrationId $integration -ExpectedWorkflowId local_frontend -StageId single_flight_transport -Solver simion -ExpectedRetentionClass solver_review
 $ownerContext=Initialize-RunArtifactPowerShellOwner -Python $Python -RepoRoot $RepoRoot -Package $package -CapacitySession $capacity `
  -EntrypointPath (Join-Path $package.input_dir 'execute_local_frontend.ps1') -CommitmentInputPaths @($budget.frozen_budget) -ResultPath $ResultPath -Software @('SIMION 2020','Python 3.11','PowerShell 7')
 $ResultPath=[string]$ownerContext.result_path
 $lease=Enter-HostExecutionLease -StatePath $pathContext.host_resource_state_path -Role SIMION -Stage prepare
 Set-LocalStage 'prepare_complete_source_geometry'
 Invoke-LocalWorkflowPython -Arguments ($compilerArgs+@('--output-directory',$script:run,'--run-id',$runId))
 $source=Get-Content -LiteralPath (Join-Path $package.input_dir 'source_identity.json') -Raw|ConvertFrom-Json
 if([int]$source.particle_count-ne[int]$rawBudget.particle_count){throw 'Budget population differs from the complete frozen source.'}
 $forecast=@'
import json,math,sys
from pathlib import Path
run=Path(sys.argv[1]);f=json.loads((run/'inputs/frontend_contract.json').read_text());n=json.loads((run/'inputs/numerics.json').read_text());count=int(sys.argv[3])
nodes=math.prod(f['dimensions'][a] for a in ('nx','ny','nz'));one=8*nodes
cache_arrays=2+2*f['pa_plus_solution_model']['mode_count']
temporary_arrays=f['pa_plus_solution_model']['mode_count']
value={'role':'local_frontend_physical_disk_forecast','grid_node_count':nodes,'float64_node_payload_bytes_per_array':one,
 'cache_array_count':cache_arrays,'new_working_point_array_count':3,'temporary_response_copy_count':temporary_arrays,
 'cold_cache_node_payload_floor_bytes':(cache_arrays+3+temporary_arrays)*one,
 'cache_hit_new_node_payload_floor_bytes':(3+temporary_arrays)*one,'author_workflow_commitment_bytes':int(sys.argv[2]),
 'source_count':count,'maximum_particle_age_us':n['maximum_flight_us'],'trajectory_sample_interval_us':n['trajectory_sample_interval_us'],
 'trajectory_rows_per_phase_ceiling_before_additional_events':count*(math.ceil(n['maximum_flight_us']/n['trajectory_sample_interval_us'])+1),
 'scope':'Conservative simultaneous node payload floors, not disk upper bounds. Includes one temporary public protected copy per response, reused by all three compositions and removed before flight. Headers/controller metadata, native logs, full raw-line analysis CSVs, images and frozen source need author headroom. Two complete phases are retained; no parity copies.'}
(run/'results/physical_disk_forecast.json').write_text(json.dumps(value,indent=2)+'\n',newline='\n')
'@
 Invoke-LocalWorkflowPython -Arguments @('-c',$forecast,$script:run,([string]$commitment),([string]$source.particle_count))
 $simion=(Resolve-Path -LiteralPath (Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe')).Path
 Write-RunJson -Path (Join-Path $package.input_dir 'native_discovery.json') -Value @{path=$simion;bytes=(Get-Item -LiteralPath $simion).Length;sha256=(Get-FileHash -LiteralPath $simion -Algorithm SHA256).Hash;file_version=(Get-Item -LiteralPath $simion).VersionInfo.FileVersion}
 Set-LocalStage 'freeze_executable_source_closure'
 $dependencyPath=Join-Path $RepoRoot 'integrations/config/runtime_dependencies.json'
 $frozen=Freeze-ConsumerDependencies -RepoRoot $RepoRoot -ContractPath $dependencyPath -InputDir $package.input_dir -OwnerId $integration -ConsumerId local_frontend
 $script:pythonRoot=[string]$frozen.execution_root
 . (Join-Path $script:pythonRoot ($sharedRuntime+'/local_frontend_field_support.ps1'))
 . (Join-Path $script:pythonRoot ($sharedRuntime+'/frontend_flight_support.ps1'))
 $frontend=Get-Content -LiteralPath (Join-Path $package.input_dir 'frontend_contract.json') -Raw|ConvertFrom-Json -Depth 100
 foreach($warningCode in @($frontend.accelerator_local_region.accelerator_port_aperture_discretization.grid_alignment.warnings)){
  Write-Warning "SIMION authoritative aperture discretization warning: $warningCode"
 }
 Set-LocalStage 'build_or_reuse_fields'
 $field=Invoke-LocalFrontendFieldStage -Package $package -Python $Python -RepoRoot $script:pythonRoot -RunDirectory $script:run -PreparedDirectory $script:run -SimionExe $simion `
  -HostLease ([ref]$lease) -CapacitySession ([ref]$capacity) -Limits $budget.limits -CacheRoot (Join-Path $artifacts 'common/simion/pa_family_cache') `
  -NativeOperations $nativeOperations -NativeResourceReleaseId ([string]$lease.token)
 # These standalone arrays are owned by this run. Hold the public no-write /
 # no-delete handles across topology, all batch flights and saved-default replay.
 $fieldReceipt=Get-Content -LiteralPath $field.cache_receipt -Raw|ConvertFrom-Json -Depth 30
 foreach($record in $fieldReceipt.working_points){
  $null=Protect-ImmutablePaSource -Source ([string]$record.path) -ExpectedBytes ([long]$record.bytes) -ExpectedSha256 ([string]$record.sha256)
  $workingFieldGuards.Add([string]$record.path)
 }
 Set-LocalStage 'compiled_aperture_topology'
 # Project only the compiler's actual native port/grid scalars to the shared
 # axis-aware topology API. No observer/display transform is involved.
 . (Join-Path $script:pythonRoot 'common/simion/aperture_topology_support.ps1')
 $port=$frontend.accelerator_local_region.port;$origin=$frontend.instance_origin_mm;$cell=$frontend.cell_mm_xyz
 $topology=@{NormalAxis=[string]$port.normal_axis;FlangeMinimumMm=[double]$port.flange_min_mm;FlangeMaximumMm=[double]$port.flange_max_mm;
  ApertureCenterMm=[double[]]$port.center_mm;OriginXmm=[double]$origin.x;OriginYmm=[double]$origin.y;OriginZmm=[double]$origin.z;
  CellMmX=[double]$cell.x;CellMmY=[double]$cell.y;CellMmZ=[double]$cell.z;
  MechanicalWidthMm=[double]$port.width_mm;MechanicalHeightMm=[double]$port.height_mm;BooleanBoundaryPolicy=[string]$port.boolean_boundary_policy}
 $topology.PaPath=[string]$field.field_paths[0]
 $topology.ReportPath=Join-Path $package.result_dir 'compiled_aperture_topology.json'
 $topology.VerifierPath=Join-Path $script:pythonRoot 'common/simion/verify_aperture_topology.lua'
 $topology.InvokeVerifier={param($VerifierPath) try{$record=Invoke-ResourceBudgetedProcess -Limits $budget.limits -RunDir $script:run -FilePath $simion -WorkingDirectory $script:run -ArgumentList @('--nogui','--noprompt','lua',$VerifierPath) -UsagePath (Join-Path $package.log_dir 'aperture_topology.resource_usage.json') -RedirectStandardOutput (Join-Path $package.log_dir 'aperture_topology.stdout.log') -RedirectStandardError (Join-Path $package.log_dir 'aperture_topology.stderr.log')
  Add-FrontendNativeOperation -NativeOperations $nativeOperations -NativeResourceReleaseId ([string]$lease.token) -OperationId aperture_topology -ProcessRecord $record
  return $record
 }catch{Add-FrontendNativeOperation -NativeOperations $nativeOperations -NativeResourceReleaseId ([string]$lease.token) -OperationId aperture_topology -ExceptionData $_.Exception.Data;throw}}
 $null=Invoke-SimionCompiledApertureTopologyCheck @topology
 $lease=Update-HostResourceStage -Lease $lease -Stage flight -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
 Set-LocalStage 'phase_diagnostic_inputs'
 $discoveryTimes=Join-Path $package.input_dir 'discovery_shared_times.json'
 $schedule=@'
import json,math,sys
from pathlib import Path
run=Path(sys.argv[1]);pulse=json.loads((run/'inputs/pulse_plan.json').read_text());n=json.loads((run/'inputs/numerics.json').read_text())
(run/'inputs/discovery_shared_times.json').write_text(json.dumps(pulse['candidate_times_us'])+'\n',newline='\n')
print(json.dumps({'held_off_pulse_time_us':math.nextafter(max(pulse['source_birth_time_range_us'])+n['maximum_flight_us'],math.inf)}))
'@
 $phaseInputs=Invoke-LocalWorkflowPython -Arguments @('-c',$schedule,$script:run) -Json
 Set-LocalStage 'held_off_discovery_flight'
 $discovery=Invoke-LocalFlightPhase -Phase discovery -PulseTime ([double]$phaseInputs.held_off_pulse_time_us) -SharedTimesPath $discoveryTimes
 $lease=Update-HostResourceStage -Lease $lease -Stage postprocess -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
 Set-LocalStage 'actual_occupancy_analysis'
 $discoveryResult=Invoke-LocalRecordedAnalysis -Materialized $discovery -Phase discovery -Times $discoveryTimes -PulseTime ([double]$phaseInputs.held_off_pulse_time_us)
 $selected=Get-Content -LiteralPath (Join-Path $package.result_dir 'local_frontend/discovery/pulse_selection.json') -Raw|ConvertFrom-Json
 if($selected.status-ne'selected'-or$null-eq$selected.selected_time_us){throw 'Physical discovery produced no supported eligible actual-occupancy pulse candidate; all mother evidence retained.'}
 Set-LocalStage 'resolve_applied_pulse_decision'
 $pulseDecisionCode=@'
import json,sys
from pathlib import Path
from common.contracts.write_run_manifest import file_record
from integrations.workflows.local_frontend.prepare import resolve_pulse_decision
run=Path(sys.argv[1]);read=lambda path:json.loads(path.read_text(encoding='utf-8-sig'))
recommendation=run/'results/local_frontend/discovery/pulse_selection.json'
plan=run/'inputs/pulse_plan.json';numerics=run/'inputs/numerics.json'
decision=resolve_pulse_decision({'pulse_plan':read(plan),'numerics':read(numerics)},read(recommendation))
decision['input_records']={name:file_record(path) for name,path in [('recommendation',recommendation),('pulse_plan',plan),('numerics',numerics)]}
(run/'inputs/pulse_decision.json').write_text(json.dumps(decision,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(decision,allow_nan=False))
'@
 $pulseDecision=Invoke-LocalWorkflowPython -Arguments @('-c',$pulseDecisionCode,$script:run) -Json
 if($pulseDecision.status-ne'ready'){throw ('Applied pulse lacks a supported recorded target snapshot: '+$pulseDecision.status+'; recommendation and decision retained, no replacement time selected.')}
 $actualPulseTime=[double]$pulseDecision.actual_pulse_time_us
 $extractionTimes=Join-Path $package.input_dir 'extraction_shared_times.json'
 $extractionSchedule=@'
import json,sys
from pathlib import Path
from integrations.workflows.local_frontend.prepare import extraction_shared_times
run=Path(sys.argv[1]);read=lambda name:json.loads((run/'inputs'/name).read_text())
prepared={'frontend_contract':read('frontend_contract.json'),'numerics':read('numerics.json'),'pulse_plan':read('pulse_plan.json'),'guide_contract':read('guide_contract.json')}
times=extraction_shared_times(prepared,float(sys.argv[2]));(run/'inputs/extraction_shared_times.json').write_text(json.dumps(times)+'\n',newline='\n')
print(json.dumps({'count':len(times)}))
'@
 $null=Invoke-LocalWorkflowPython -Arguments @('-c',$extractionSchedule,$script:run,$actualPulseTime.ToString('G17',[Globalization.CultureInfo]::InvariantCulture)) -Json
 $lease=Update-HostResourceStage -Lease $lease -Stage flight -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
 Set-LocalStage 'actual_pulse_extraction_flight'
 $extraction=Invoke-LocalFlightPhase -Phase extraction -PulseTime $actualPulseTime -SharedTimesPath $extractionTimes
 $lease=Update-HostResourceStage -Lease $lease -Stage postprocess -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
 Set-LocalStage 'automatic_complete_population_diagnostics'
 $extractionResult=Invoke-LocalRecordedAnalysis -Materialized $extraction -Phase extraction -Times $extractionTimes -PulseTime $actualPulseTime
 Set-LocalStage 'saved_workbench_verification'
 $defaultReplay=Invoke-FrontendDefaultReplay -Materialized $extraction -HostLease ([ref]$lease) -RunDirectory $script:run `
  -RepoRoot $script:pythonRoot -Python $Python -SimionExe $simion -Limits $budget.limits `
  -NativeOperations $nativeOperations -NativeResourceReleaseId ([string]$lease.token)
 $scientificSummary=@{native_path_preparation=$package.native_path_preparation;schema_version=1;role='rf_oatof_local_frontend_summary';status='success';mother_count=[int]$source.particle_count;discovery=$discoveryResult;extraction=$extractionResult;recommended_pulse_time_us=[double]$selected.selected_time_us;actual_pulse_time_us=$actualPulseTime;pulse_decision=(Join-Path $package.input_dir 'pulse_decision.json');default_load_iob=$extraction.default_load_iob;default_replay=$defaultReplay;gui_executed=$false;full_analyzer_flight_executed=$false;qualification='local_functional_evidence_only__no_MR_acceptance_or_resolution_claim'}
}catch{
 $failure=$_
 if(($_.Exception.Data.Contains('observed_process_exit_confirmed')-and-not[bool]$_.Exception.Data['observed_process_exit_confirmed'])-or
    ($_.Exception.Data.Contains('simion_wave_writer_completion_confirmed')-and-not[bool]$_.Exception.Data['simion_wave_writer_completion_confirmed'])){$writerUnknown=$true}
}finally{
 try{
  if(@($nativeOperations|Where-Object{-not$_.observation.exit_confirmed}).Count){$writerUnknown=$true}
  if(-not$writerUnknown){
   try{if($lease){Close-LocalHostStage}}catch{if($failure){$failure.Exception.Data['host_release_error']=$_}else{$failure=$_};$writerUnknown=$true}
   if(-not$writerUnknown){
    try{foreach($path in $workingFieldGuards){$null=Unprotect-ImmutablePaSource -Source $path};$workingFieldGuards.Clear()}catch{if($failure){$failure.Exception.Data['asset_release_error']=$_}else{$failure=$_}}
   }
  }
  if(-not$ownerContext-and-not$writerUnknown){
   try{if($capacity){$null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity};if($package){Remove-RunPackageExecutionAlias -Package $package}}catch{if($failure){$failure.Exception.Data['bootstrap_cleanup_error']=$_}else{$failure=$_}}
  }
  if($ownerContext-and-not$ownerContext.completion_written){
   if(-not$writerUnknown){try{Register-LocalInputs}catch{if($failure){$failure.Exception.Data['input_binding_error']=$_}else{$failure=$_}}}
   $phaseTimings[$stage]=[double]$stageClock.Elapsed.TotalSeconds
   $summary=if($null-ne$scientificSummary){$scientificSummary}else{@{schema_version=1;role='rf_oatof_local_frontend_summary';gui_executed=$false;full_analyzer_flight_executed=$false}}
   $summary.execution_status=if($hostReleaseUnknown){'host_release_unconfirmed'}elseif($writerUnknown){'writer_completion_unknown'}elseif($failure){'failed'}else{'completed'}
   $summary.data_validity=if($failure){'incomplete'}else{'valid'}
   $summary.scientific_result=if($failure){'NOT_EVALUATED'}else{'local_functional_evidence_only__no_MR_acceptance_or_resolution_claim'}
   $summary.failure_stage=if($failure){$stage}else{$null};$summary.failure_reason=if($failure){$failure.Exception.Message}else{$null}
   $summary.recovery_action=if($hostReleaseUnknown){'inspect_host_release'}elseif($writerUnknown){'inspect_writer_completion'}elseif($failure){'inspect_preserved_stage_evidence_or_resume_finalization'}else{'none'}
   $summary.secondary_errors=@(if($failure){foreach($key in @('host_release_error','asset_release_error','bootstrap_cleanup_error','input_binding_error')){if($failure.Exception.Data.Contains($key)){[string]$failure.Exception.Data[$key]}}})
   $summary.result_path=$ResultPath;$summary.phase_timings_seconds=$phaseTimings;$summary.total_elapsed_seconds=$runClock.Elapsed.TotalSeconds
   $outputs=@(Get-ChildItem -LiteralPath $script:run -Recurse -File|Where-Object{-not$_.FullName.StartsWith($package.input_dir+[IO.Path]::DirectorySeparatorChar)-and$_.Name-notin@('run_config.json','run_manifest.json')}|ForEach-Object FullName)
   $ownerContext.session=$capacity
   try{$outcome=Complete-RunArtifactPowerShellOwner -Context $ownerContext -Status $(if($failure){'failed'}else{'success'}) -Summary $summary -OutputPaths $outputs `
    -WriterCompletion @{operations=@($nativeOperations.ToArray());resource_releases=@($resourceReleases.ToArray())} -WritersStopped (-not$writerUnknown) -OriginalFailure $failure;Write-Output $outcome}catch{if($failure){$failure.Exception.Data['finalization_error']=$_}else{$failure=$_}}
  }
 }finally{
  Restore-RunEnvironment -Names @('PYTHONPATH','PYTHONNOUSERSITE','SIMULATION_PYTHON_EXE','MASS_SPECTROMETRY_ARTIFACT_ROOT','MASS_SPECTROMETRY_EXECUTION_ROOT','MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH','MASS_SPECTROMETRY_RUN_DIRECTORY','MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY') -Snapshot $oldEnvironment
 }
}
if($failure){throw $failure}
Write-Output "LOCAL_FRONTEND=PASS RUN=$($package.artifact_run_dir) RESULT=$ResultPath GUI=False FULL_ANALYZER=False"
