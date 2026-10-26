[CmdletBinding()]
param(
 [Parameter(Mandatory)][string]$Request,
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
if(([int][bool]$ValidateOnly+[int][bool]$PrepareOnly+[int][bool]$SolverAuthorized)-ne1){throw 'Select exactly one local frontend execution mode.'}
if($PrepareOnly-and-not$OutputDirectory){throw 'PrepareOnly requires a caller-owned managed OutputDirectory.'}
if(-not$PrepareOnly-and$OutputDirectory){throw 'OutputDirectory is accepted only for PrepareOnly; native runs always receive a fresh identity.'}
if($SolverAuthorized-and-not$ExecutionBudgetPath){throw 'SolverAuthorized requires ExecutionBudgetPath.'}
$RepoRoot=(Resolve-Path -LiteralPath $RepoRoot).Path
$Request=(Resolve-Path -LiteralPath $Request).Path
if(-not$Python){$Python=Join-Path $RepoRoot '.venv/Scripts/python.exe'}
$Python=(Resolve-Path -LiteralPath $Python).Path
. (Join-Path $RepoRoot 'common/require_powershell7.ps1')
. (Join-Path $RepoRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $RepoRoot 'integrations/runtime/engineering_budget.ps1')
. (Join-Path $RepoRoot 'common/resource_budget_support.ps1')
. (Join-Path $RepoRoot 'common/simion/short_pa_path_support.ps1')
$integration='instrument_assembly'
$sharedRuntime='integrations/runtime'
$workflowModule='integrations.workflows.local_frontend'
. (Join-Path $RepoRoot 'integrations/runtime/dependencies.ps1')
$workspace=Split-Path -Parent $RepoRoot
$artifacts=Join-Path $workspace 'artifacts'
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
  -SimionExe $simion -Limits $budget.limits -Phase $Phase -PulseTimeUs $PulseTime -SharedTimesPath $SharedTimesPath
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
$capacity=$null;$package=$null;$lease=$null;$budget=$null;$okay=$false;$stage='capacity_startup';$failure=$null
$workingFieldGuards=[Collections.Generic.List[string]]::new()
$nativeWritersStopped=$false
$oldEnvironment=Save-RunEnvironment -Names @('PYTHONPATH','PYTHONNOUSERSITE','SIMULATION_PYTHON_EXE')
$env:SIMULATION_PYTHON_EXE=$Python
$controllerTicks=[Diagnostics.Process]::GetCurrentProcess().StartTime.ToUniversalTime().Ticks
try {
 $capacity=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -ArtifactRoot $artifacts -RunDirectory $destination -CommittedNewBytes $commitment -ProtectedPaths $protected
 $package=New-RunPackage -Python $Python -RepoRoot $RepoRoot -ArtifactRoot $projectArtifacts -RunId $runId -Project $integration -Mode local_frontend -Software @('SIMION 2020','Python 3.11') `
  -RetentionContractEnabled -RetentionClass solver_review -RetentionReason 'Retain local RF/OA fields, complete source and losses, actual occupancy pulse selection, automatic diagnostics and independent GUI loading files' -CapacityLedgerLifecycleEnabled
 $script:run=[string]$package.run_dir
 Copy-VerifiedRunInput -Source $PSCommandPath -Destination (Join-Path $package.input_dir 'execute_local_frontend.ps1')|Out-Null
 $stage='engineering_budget'
 $budget=Initialize-IntegrationStageBudget -ResolvedBudget $ExecutionBudgetPath -InputDir $package.input_dir -ExpectedIntegrationId $integration -ExpectedWorkflowId local_frontend -StageId single_flight_transport -Solver simion -ExpectedRetentionClass solver_review
 $lease=Enter-HostExecutionLease -Role SIMION -Stage prepare
 $stage='prepare_complete_source_geometry'
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
 $stage='freeze_executable_source_closure'
 $dependencyPath=Join-Path $RepoRoot 'integrations/config/runtime_dependencies.json'
 $frozen=Freeze-ConsumerDependencies -RepoRoot $RepoRoot -ContractPath $dependencyPath -InputDir $package.input_dir -OwnerId $integration -ConsumerId local_frontend
 $script:pythonRoot=[string]$frozen.execution_root
 . (Join-Path $script:pythonRoot ($sharedRuntime+'/local_frontend_field_support.ps1'))
 . (Join-Path $script:pythonRoot ($sharedRuntime+'/frontend_flight_support.ps1'))
 $frontend=Get-Content -LiteralPath (Join-Path $package.input_dir 'frontend_contract.json') -Raw|ConvertFrom-Json -Depth 100
 foreach($warningCode in @($frontend.accelerator_local_region.accelerator_port_aperture_discretization.grid_alignment.warnings)){
  Write-Warning "SIMION authoritative aperture discretization warning: $warningCode"
 }
 $stage='build_or_reuse_fields'
 $field=Invoke-LocalFrontendFieldStage -Python $Python -RepoRoot $script:pythonRoot -RunDirectory $script:run -PreparedDirectory $script:run -SimionExe $simion `
  -HostLease ([ref]$lease) -CapacitySession ([ref]$capacity) -Limits $budget.limits -CacheRoot (Join-Path $artifacts 'common/simion/pa_family_cache')
 # These standalone arrays are owned by this run. Hold the public no-write /
 # no-delete handles across topology, all batch flights and saved-default replay.
 $fieldReceipt=Get-Content -LiteralPath $field.cache_receipt -Raw|ConvertFrom-Json -Depth 30
 foreach($record in $fieldReceipt.working_points){
  $null=Protect-ImmutablePaSource -Source ([string]$record.path) -ExpectedBytes ([long]$record.bytes) -ExpectedSha256 ([string]$record.sha256)
  $workingFieldGuards.Add([string]$record.path)
 }
 $stage='compiled_aperture_topology'
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
 $topology.InvokeVerifier={param($VerifierPath) Invoke-ResourceBudgetedProcess -Limits $budget.limits -RunDir $script:run -FilePath $simion -WorkingDirectory $script:run -ArgumentList @('--nogui','--noprompt','lua',$VerifierPath) -UsagePath (Join-Path $package.log_dir 'aperture_topology.resource_usage.json') -RedirectStandardOutput (Join-Path $package.log_dir 'aperture_topology.stdout.log') -RedirectStandardError (Join-Path $package.log_dir 'aperture_topology.stderr.log')}
 $null=Invoke-SimionCompiledApertureTopologyCheck @topology
 $lease=Update-HostResourceStage -Lease $lease -Stage flight -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
 $stage='phase_diagnostic_inputs'
 $discoveryTimes=Join-Path $package.input_dir 'discovery_shared_times.json'
 $schedule=@'
import json,math,sys
from pathlib import Path
run=Path(sys.argv[1]);pulse=json.loads((run/'inputs/pulse_plan.json').read_text());n=json.loads((run/'inputs/numerics.json').read_text())
(run/'inputs/discovery_shared_times.json').write_text(json.dumps(pulse['candidate_times_us'])+'\n',newline='\n')
print(json.dumps({'held_off_pulse_time_us':math.nextafter(max(pulse['source_birth_time_range_us'])+n['maximum_flight_us'],math.inf)}))
'@
 $phaseInputs=Invoke-LocalWorkflowPython -Arguments @('-c',$schedule,$script:run) -Json
 $stage='held_off_discovery_flight'
 $discovery=Invoke-LocalFlightPhase -Phase discovery -PulseTime ([double]$phaseInputs.held_off_pulse_time_us) -SharedTimesPath $discoveryTimes
 $lease=Update-HostResourceStage -Lease $lease -Stage postprocess -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
 $stage='actual_occupancy_analysis'
 $discoveryResult=Invoke-LocalRecordedAnalysis -Materialized $discovery -Phase discovery -Times $discoveryTimes -PulseTime ([double]$phaseInputs.held_off_pulse_time_us)
 $selected=Get-Content -LiteralPath (Join-Path $package.result_dir 'local_frontend/discovery/pulse_selection.json') -Raw|ConvertFrom-Json
 if($selected.status-ne'selected'-or$null-eq$selected.selected_time_us){throw 'Physical discovery produced no supported eligible actual-occupancy pulse candidate; all mother evidence retained.'}
 $stage='resolve_applied_pulse_decision'
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
 $stage='actual_pulse_extraction_flight'
 $extraction=Invoke-LocalFlightPhase -Phase extraction -PulseTime $actualPulseTime -SharedTimesPath $extractionTimes
 $lease=Update-HostResourceStage -Lease $lease -Stage postprocess -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
 $stage='automatic_complete_population_diagnostics'
 $extractionResult=Invoke-LocalRecordedAnalysis -Materialized $extraction -Phase extraction -Times $extractionTimes -PulseTime $actualPulseTime
 $stage='saved_default_fresh_process_replay'
 $defaultReplay=Invoke-FrontendDefaultReplay -Materialized $extraction -HostLease ([ref]$lease) -RunDirectory $script:run `
  -RepoRoot $script:pythonRoot -Python $Python -SimionExe $simion -Limits $budget.limits
 Write-RunJson -Path $package.summary -Depth 100 -Value @{schema_version=1;role='rf_oatof_local_frontend_summary';status='success';mother_count=[int]$source.particle_count;discovery=$discoveryResult;extraction=$extractionResult;recommended_pulse_time_us=[double]$selected.selected_time_us;actual_pulse_time_us=$actualPulseTime;pulse_decision=(Join-Path $package.input_dir 'pulse_decision.json');default_load_iob=$extraction.default_load_iob;default_replay=$defaultReplay;gui_executed=$false;full_analyzer_flight_executed=$false;qualification='local_functional_evidence_only__no_MR_acceptance_or_resolution_claim'}
 $okay=$true
}catch{
 $failure=$_
 if($package){Write-RunJson -Path $package.summary -Depth 20 -Value @{schema_version=1;role='rf_oatof_local_frontend_summary';status='failed';stage=$stage;reason=$_.Exception.Message;gui_executed=$false;full_analyzer_flight_executed=$false}}
}finally{
 try{
  if($package){
   # Terminal publication is forbidden while any child from this controller's
   # birth-identified process family can still write the run.
   $sample=Get-ManagedSolverProcessSample -RootProcessIds @($PID) -RootProcessStartedAtUtcTicks @{([string]$PID)=$controllerTicks}
   $writers=@($sample.active_process_ids|Where-Object{$_-ne$PID-and$_-notin@($sample.system_console_host_process_ids)})
   if($writers.Count){Write-Warning 'RUN_FINALIZATION_WAITING_FOR_MANAGED_SOLVER_WRITERS'}
   do{$sample=Get-ManagedSolverProcessSample -RootProcessIds @($PID) -RootProcessStartedAtUtcTicks @{([string]$PID)=$controllerTicks};$writers=@($sample.active_process_ids|Where-Object{$_-ne$PID-and$_-notin@($sample.system_console_host_process_ids)});if($writers.Count){Start-Sleep -Milliseconds 500}}while($writers.Count)
  }
  $nativeWritersStopped=$true
  foreach($path in $workingFieldGuards){$null=Unprotect-ImmutablePaSource -Source $path}
  $workingFieldGuards.Clear()
  if($lease){Exit-HostExecutionLease -Lease $lease -Outcome $(if($okay){'success'}else{'failed'}) -RunId $runId;$lease=$null}
  if($package){
   $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
   foreach($file in Get-ChildItem -LiteralPath $package.input_dir -Recurse -File){$config.inputs[$file.FullName]=$file.FullName}
   $config.parameters=@{workflow='local_frontend';scientific_request=(Join-Path $package.input_dir 'request.json');execution_budget=$(if($budget){$budget.frozen_budget}else{$ExecutionBudgetPath});stage=$stage;gui_executed=$false;full_analyzer_flight_executed=$false}
   Write-RunJson -Path $package.run_config -Value $config -Depth 100
   $null=Apply-RunArtifactRetention -Python $Python -RepoRoot $script:pythonRoot -RunConfig $package.run_config
   $outputs=@(Get-ChildItem -LiteralPath $script:run -Recurse -File|Where-Object{-not$_.FullName.StartsWith($package.input_dir+[IO.Path]::DirectorySeparatorChar)-and$_.Name-notin@('run_config.json','run_manifest.json')}|ForEach-Object{$_.FullName})
   Write-VerifiedRunManifest -Python $Python -RepoRoot $script:pythonRoot -RunConfig $package.run_config -Manifest (Join-Path $script:run 'run_manifest.json') -Status $(if($okay){'success'}else{'failed'}) -Software @('SIMION 2020','Python 3.11','PowerShell 7') -Outputs $outputs -DeferCapacityFinalization
  }
  if($capacity){Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $script:pythonRoot -Session $capacity|Out-Null;$capacity=$null}
  if($package){Invoke-LocalWorkflowPython -Arguments @('-m','common.contracts.run_capacity_lifecycle','--action','seal-stopped-payload','--artifact-root',$artifacts,'--run-config',$package.run_config,'--owner',$integration,'--confirm-writing-stopped','--retention-reason','Retain local fields, complete native mother evidence and GUI assets for review') -NoCapture}
 }finally{
  if($nativeWritersStopped){foreach($path in $workingFieldGuards){$null=Unprotect-ImmutablePaSource -Source $path}}
  if($lease){Exit-HostExecutionLease -Lease $lease -Outcome failed -RunId $runId}
  if($capacity){Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity|Out-Null}
  Restore-RunEnvironment -Names @('PYTHONPATH','PYTHONNOUSERSITE','SIMULATION_PYTHON_EXE') -Snapshot $oldEnvironment
 }
}
if($failure){throw $failure}
Write-Output "LOCAL_FRONTEND=PASS RUN=$($package.run_dir) GUI=False FULL_ANALYZER=False"
