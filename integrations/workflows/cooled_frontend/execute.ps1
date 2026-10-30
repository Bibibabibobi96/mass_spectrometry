[CmdletBinding()]
param(
 [Parameter(Mandatory)][string]$Request,
 [string]$RepoRoot=(Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))),
 [string]$Python='',
 [switch]$ValidateOnly,[switch]$PrepareOnly,[switch]$SolverAuthorized,
 [switch]$FieldDesignOnly,[switch]$ReferenceCalibrationOnly,[string]$OutputDirectory='',[string]$ExecutionBudgetPath=''
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if(([int][bool]$ValidateOnly+[int][bool]$PrepareOnly+[int][bool]$SolverAuthorized)-ne1){throw 'Select exactly one cooled frontend execution mode.'}
if(($FieldDesignOnly-or$ReferenceCalibrationOnly)-and-not$SolverAuthorized){throw 'FieldDesignOnly requires SolverAuthorized; it changes execution scope only.'}
if($PrepareOnly-and-not$OutputDirectory){throw 'PrepareOnly requires a managed OutputDirectory.'}
if(-not$PrepareOnly-and$OutputDirectory){throw 'OutputDirectory belongs to PrepareOnly.'}
if($SolverAuthorized-and-not$ExecutionBudgetPath){throw 'SolverAuthorized requires an execution budget.'}
if($FieldDesignOnly-and$ReferenceCalibrationOnly){throw 'Select one cooled execution scope.'}
$RepoRoot=(Resolve-Path -LiteralPath $RepoRoot).Path
if(-not$Python){$Python=Join-Path $RepoRoot '.venv/Scripts/python.exe'}
$Python=(Resolve-Path -LiteralPath $Python).Path
$Request=(Resolve-Path -LiteralPath $Request).Path
. (Join-Path $RepoRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $RepoRoot 'common/paths/workspace_paths.ps1')
. (Join-Path $RepoRoot 'integrations/runtime/engineering_budget.ps1')
. (Join-Path $RepoRoot 'common/resource_budget_support.ps1')
. (Join-Path $RepoRoot 'common/simion/short_pa_path_support.ps1')
$integration='instrument_assembly'
$relative='integrations'
$module='integrations.workflows.cooled_frontend'
. (Join-Path $RepoRoot ($relative+'/runtime/frontend_flight_support.ps1'))
. (Join-Path $RepoRoot 'integrations/runtime/dependencies.ps1')

function Freeze-CooledRuntime {
 param([Parameter(Mandatory)][string]$InputDir)
 $dependencyPath=Join-Path $RepoRoot 'integrations/config/runtime_dependencies.json'
 return Freeze-ConsumerDependencies -RepoRoot $RepoRoot -ContractPath $dependencyPath -InputDir $InputDir -OwnerId $integration -ConsumerId cooled_frontend
}

function Invoke-CooledNative {
 [CmdletBinding()]
 param(
  [Parameter(Mandatory)][pscustomobject]$Package,
  [Parameter(Mandatory)][string[]]$Arguments,[Parameter(Mandatory)][string]$Name,
  [Parameter(Mandatory)][string]$RunDirectory,[Parameter(Mandatory)][string]$SimionExe,
  [Parameter(Mandatory)]$Limits,[Parameter(Mandatory)][string]$WorkingDirectory
 )
 $RunDirectory=[string]$Package.artifact_run_dir
 $nativePaths=@($WorkingDirectory)+@($Arguments|Where-Object{[IO.Path]::IsPathFullyQualified([string]$_)})
 $execution=Get-RunNativeExecutionContext -Package $Package -Paths $nativePaths -Tool SIMION
 $projected=Project-RunPath -Paths (@($WorkingDirectory)+$Arguments) -ArtifactRunDir $Package.artifact_run_dir -RunDir $execution.run_dir -Python $Package.python
 $result=Invoke-ResourceBudgetedProcess -Limits $Limits -RunDir $RunDirectory -FilePath $SimionExe `
  -ArgumentList @($projected|Select-Object -Skip 1) -WorkingDirectory $projected[0] -Environment $execution.environment `
  -UsagePath (Join-Path $RunDirectory "logs/$Name.resource_usage.json") `
  -RedirectStandardOutput (Join-Path $RunDirectory "logs/$Name.stdout.log") `
  -RedirectStandardError (Join-Path $RunDirectory "logs/$Name.stderr.log")
 if($result.resource_budget_exceeded-or[int]$result.exit_code-ne0){throw "Cooled native stage failed: $Name"}
}

function Invoke-CooledOrdinaryFieldBuild {
 [CmdletBinding()]
 param($Package,[string]$FrozenRepoRoot,[string]$Python,[string]$RuntimeModule,
       [string]$SimionExe,$Limits,[ref]$HostLease,[Parameter(Mandatory)][ref]$CapacitySession)
 $run=[string]$Package.run_dir
 $context=@{RunDirectory=$run;RepoRoot=$FrozenRepoRoot;Python=$Python}
 $advanceCode=@'
import json,sys
from pathlib import Path
from integrations.workflows.cooled_frontend.runtime import field_cache_plan,advance_field_cache
run=Path(sys.argv[1]);plan=field_cache_plan(run)
output=Path(sys.argv[2]) if len(sys.argv)>2 else None
print(json.dumps(dict(plan=plan,progress=advance_field_cache(run,plan,output))))
'@
 $bundle=Invoke-FrontendRuntimePython @context -Name field_cache_plan -Arguments @('-c',$advanceCode,$run) -Json
 $updated=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $FrozenRepoRoot -Session $CapacitySession.Value -ProtectedCacheKeys @([string]$bundle.plan.cache_key)
 $CapacitySession.Value=$updated.session
 $plan=Get-Content -LiteralPath (Join-Path $Package.input_dir 'cooled_field_plan.json') -Raw|ConvertFrom-Json -Depth 100
 $front=Get-Content -LiteralPath (Join-Path $Package.input_dir 'frontend_contract.json') -Raw|ConvertFrom-Json -Depth 100
 $origin=(@('x','y','z')|ForEach-Object{([double]$front.instance_origin_mm.$_).ToString('G17',[Globalization.CultureInfo]::InvariantCulture)})-join','
 while($bundle.progress.action_required-ne'complete'){
  $progress=$bundle.progress
  $build=[string]$progress.scratch_directory
  $native=@{Package=$Package;RunDirectory=$run;SimionExe=$SimionExe;Limits=$Limits;WorkingDirectory=$build}
  if($progress.action_required-eq'build'){
   $raw=Join-Path $build 'frontend.pa#';$working=Join-Path $build 'working.pa0'
   foreach($temporary in @($raw,$working,(Join-Path $build 'pending.pa'))){
    if(Test-Path -LiteralPath $temporary -PathType Leaf){Remove-Item -LiteralPath $temporary -Force}
   }
   Invoke-CooledNative @native -Name field_gem2pa -Arguments @('--nogui','--noprompt','gem2pa',(Join-Path $Package.input_dir 'frontend.gem'),$raw)
   foreach($point in $plan.working_points){
    if($progress.missing_files-notcontains$point.output_basename){continue}
    $ordered=@($point.electrode_voltages_v.PSObject.Properties|Sort-Object{[int]$_.Name})
    for($i=0;$i-lt$ordered.Count;$i++){if([int]$ordered[$i].Name-ne$i+1){throw 'Field endpoint IDs must explicitly cover1..maxID.'}}
    $voltages=($ordered|ForEach-Object{([double]$_.Value).ToString('G17',[Globalization.CultureInfo]::InvariantCulture)})-join','
    $HostLease.Value=Update-HostResourceStage -Lease $HostLease.Value -Stage refine -Budget (Get-HostResourceBudget -Role SIMION -Stage refine) -RetainedMemoryBytes 0
    Invoke-CooledNative @native -Name ('field_refine_'+$point.kind) -Arguments @('--nogui','--noprompt','lua',
     (Join-Path $FrozenRepoRoot 'common/simion/build_dirichlet_patch_operating_pa.lua'),$raw,$working,'zero_dirichlet','0,0,0',$origin,$voltages,
     ([double]$plan.refine_convergence_v).ToString('G17',[Globalization.CultureInfo]::InvariantCulture))
    $HostLease.Value=Update-HostResourceStage -Lease $HostLease.Value -Stage prepare -Budget (Get-HostResourceBudget -Role SIMION -Stage prepare) -RetainedMemoryBytes 0
    $pending=Join-Path $build 'pending.pa'
    Invoke-CooledNative @native -Name ('field_export_'+$point.kind) -Arguments @('--nogui','--noprompt','lua',
     (Join-Path $FrozenRepoRoot 'common/simion/export_detached_standalone_pa.lua'),$working,$pending)
    if(-not(Test-Path -LiteralPath $pending -PathType Leaf)-or(Get-Item -LiteralPath $pending).Length-lt56){throw 'Standalone export is incomplete.'}
    Move-Item -LiteralPath $pending -Destination (Join-Path $progress.build_directory $point.output_basename)
   }
   $bundle=Invoke-FrontendRuntimePython @context -Name field_cache_seal -Arguments @('-c',$advanceCode,$run) -Json
  }elseif($progress.action_required-eq'verify'){
   $native.WorkingDirectory=[string]$progress.build_directory
   $specCode=@'
import json,sys
from pathlib import Path
from integrations.workflows.cooled_frontend.runtime import field_verification_spec
print(json.dumps(dict(path=str(field_verification_spec(Path(sys.argv[1]),Path(sys.argv[2]))))))
'@
   $spec=Invoke-FrontendRuntimePython @context -Name field_verification_spec -Arguments @('-c',$specCode,$run,[string]$progress.build_directory) -Json
   $report=Join-Path $run 'logs/cooled_field_verification.tsv'
   Invoke-CooledNative @native -Name field_verification -Arguments @('--nogui','--noprompt','lua',[string]$bundle.plan.verifier_path,[string]$spec.path,$report)
   $bundle=Invoke-FrontendRuntimePython @context -Name field_cache_publish -Arguments @('-c',$advanceCode,$run,$report) -Json
  }else{throw "Unsupported public field transaction action: $($progress.action_required)"}
 }
 $finalCode=@'
import json,sys
from pathlib import Path
from integrations.workflows.cooled_frontend.runtime import field_cache_plan,advance_field_cache,finalize_field_stage
run=Path(sys.argv[1]);plan=field_cache_plan(run)
print(json.dumps(finalize_field_stage(run,plan,advance_field_cache(run,plan))))
'@
 $stage=Invoke-FrontendRuntimePython @context -Name field_stage_receipt -Arguments @('-c',$finalCode,$run) -Json
 return [pscustomobject]@{receipt=$stage;working_points=@($stage.working_points);field_directory=[string]$bundle.progress.generation_directory;retained_native_build_objects=@()}
}

function Invoke-CooledFieldDesign {
 <# One private raw geometry and one reusable solved staging object. Every
    immutable ordinary output is exported from a fresh private solve; only the
    public short-copy boundary exposes those outputs to the static sampler. #>
 [CmdletBinding()]
 param(
  [Parameter(Mandatory)]$Package,[Parameter(Mandatory)][string]$FrozenRepoRoot,
  [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RuntimeModule,
  [Parameter(Mandatory)][string]$SimionExe,[Parameter(Mandatory)]$Limits,
  [Parameter(Mandatory)][ref]$HostLease,[Parameter(Mandatory)][ref]$CapacitySession
 )
 $run=[string]$Package.run_dir
 $inputs=[string]$Package.input_dir
 $fieldPlan=Get-Content -LiteralPath (Join-Path $inputs 'cooled_field_plan.json') -Raw|ConvertFrom-Json -Depth 100
 $front=Get-Content -LiteralPath (Join-Path $inputs 'frontend_contract.json') -Raw|ConvertFrom-Json -Depth 100
 $probe=Get-Content -LiteralPath (Join-Path $inputs 'cooled_probe_plan.json') -Raw|ConvertFrom-Json -Depth 100
 $directory=Join-Path $run 'simion/cooled_fields'
 $build=Join-Path $run 'simion/cooled_field_build'
 New-Item -ItemType Directory -Path $directory,$build -Force|Out-Null
 $raw=Join-Path $build 'frontend.pa#'
 $working=Join-Path $build 'working.pa0'
 $native=@{Package=$Package;RunDirectory=$run;SimionExe=$SimionExe;Limits=$Limits;WorkingDirectory=$build}
 $context=@{RunDirectory=$run;RepoRoot=$FrozenRepoRoot;Python=$Python}
 $meshCheck=$fieldPlan.role-eq'cooled_frontend_local_dirichlet_mesh_check_plan'
 $origin=(@('x','y','z')|ForEach-Object{([double]$front.instance_origin_mm.$_).ToString('G17',[Globalization.CultureInfo]::InvariantCulture)})-join','
 if($meshCheck){
 Invoke-CooledNative @native -Name field_gem2pa -Arguments @('--nogui','--noprompt','gem2pa',(Join-Path $inputs 'frontend.gem'),$raw)
 if(-not(Test-Path -LiteralPath $raw -PathType Leaf)){throw 'Native geometry PA was not created.'}
 foreach($point in $fieldPlan.working_points){
  $parentTemporary=$null
  try{
  $parent='zero_dirichlet';$parentOrigin='0,0,0'
  if($meshCheck){
   $parentTemporary=Join-Path ([IO.Path]::GetTempPath()) ('simion_pa_links_cooled_mesh_'+[guid]::NewGuid().ToString('N').Substring(0,12))
   $r=$point.source_pa_record
   $parent=New-ShortPaCopy -Source ([string]$r.path) -Destination (Join-Path $parentTemporary 'parent.pa') -ExpectedBytes ([long]$r.bytes) -ExpectedSha256 ([string]$r.sha256)
   $parentOrigin=(@('x','y','z')|ForEach-Object{([double]$fieldPlan.dirichlet_parent.origin_mm.$_).ToString('G17',[Globalization.CultureInfo]::InvariantCulture)})-join','
  }
  $ordered=@($point.electrode_voltages_v.PSObject.Properties|Sort-Object{[int]$_.Name})
  for($index=0;$index-lt$ordered.Count;$index++){if([int]$ordered[$index].Name-ne$index+1){throw 'Field endpoint IDs must explicitly cover1..maxID.'}}
  $voltages=($ordered|ForEach-Object{([double]$_.Value).ToString('G17',[Globalization.CultureInfo]::InvariantCulture)})-join','
  $HostLease.Value=Update-HostResourceStage -Lease $HostLease.Value -Stage refine -Budget (Get-HostResourceBudget -Role SIMION -Stage refine) -RetainedMemoryBytes 0
  Invoke-CooledNative @native -Name ('field_refine_'+$point.kind) -Arguments @('--nogui','--noprompt','lua',
   (Join-Path $FrozenRepoRoot 'common/simion/build_dirichlet_patch_operating_pa.lua'),$raw,$working,[string]$parent,$parentOrigin,$origin,$voltages,
   ([double]$fieldPlan.refine_convergence_v).ToString('G17',[Globalization.CultureInfo]::InvariantCulture))
  $HostLease.Value=Update-HostResourceStage -Lease $HostLease.Value -Stage prepare -Budget (Get-HostResourceBudget -Role SIMION -Stage prepare) -RetainedMemoryBytes 0
  $output=Join-Path $directory ([string]$point.output_basename)
  Invoke-CooledNative @native -Name ('field_export_'+$point.kind) -Arguments @('--nogui','--noprompt','lua',
   (Join-Path $FrozenRepoRoot 'common/simion/export_detached_standalone_pa.lua'),$working,$output)
  if(-not(Test-Path -LiteralPath $output -PathType Leaf)){throw "Standalone field missing: $($point.kind)"}
  (Get-Item -LiteralPath $output).IsReadOnly=$true
  if($meshCheck){
   $parentProbe=Join-Path $Package.result_dir 'cooled_parent_probe'
   New-Item -ItemType Directory -Path $parentProbe -Force|Out-Null
   Invoke-CooledNative @native -Name ('parent_probe_'+$point.kind) -Arguments @('--nogui','--noprompt','lua',
    (Join-Path $FrozenRepoRoot ([string]$probe.sampler_repository_path)),[string]$parent,$parentOrigin,
    (Join-Path $inputs 'cooled_probe_points.csv'),(Join-Path $parentProbe ($point.kind+'.csv')))
   $null=Confirm-ShortPaCopyIdentity -Path ([string]$parent)
  }
  }finally{if($parentTemporary){Remove-ShortPaCopyDirectory -Path $parentTemporary}}
 }
 $recordsPath=Join-Path $inputs 'cooled_working_points.json'
 $recordCode=@'
import json,sys
from pathlib import Path
from common.contracts.write_run_manifest import file_record
run=Path(sys.argv[1]).resolve();plan=json.loads((run/'inputs/cooled_field_plan.json').read_text())
rows=[dict(file_record(run/'simion/cooled_fields'/p['output_basename'],'solver_native_binary'),kind=p['kind'],read_only=True) for p in plan['working_points']]
(run/'inputs/cooled_working_points.json').write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8',newline='\n')
'@
 Invoke-FrontendRuntimePython @context -Name field_records -Arguments @('-c',$recordCode,[string]$Package.artifact_run_dir)
 $stage=$null
 $records=@(Get-Content -LiteralPath $recordsPath -Raw|ConvertFrom-Json -Depth 100)
 }else{
  $cached=Invoke-CooledOrdinaryFieldBuild -Package $Package -FrozenRepoRoot $FrozenRepoRoot -Python $Python -RuntimeModule $RuntimeModule -SimionExe $SimionExe -Limits $Limits -HostLease $HostLease -CapacitySession $CapacitySession
  $stage=$cached.receipt;$records=@($cached.working_points);$directory=$cached.field_directory
 }
 $sampler=Join-Path $FrozenRepoRoot ([string]$probe.sampler_repository_path)
 $samples=Join-Path $inputs 'cooled_probe_points.csv'
 $probeDirectory=Join-Path $Package.result_dir 'cooled_field_probe'
 New-Item -ItemType Directory -Path $probeDirectory -Force|Out-Null
 foreach($record in $records){
  $temporary=Join-Path ([IO.Path]::GetTempPath()) ('simion_pa_links_cooled_probe_'+[guid]::NewGuid().ToString('N').Substring(0,12))
  try{
   $copy=New-ShortPaCopy -Source ([string]$record.path) -Destination (Join-Path $temporary 'field.pa') `
    -ExpectedBytes ([long]$record.bytes) -ExpectedSha256 ([string]$record.sha256)
   Invoke-CooledNative @native -Name ('field_probe_'+$record.kind) -Arguments @('--nogui','--noprompt','lua',$sampler,
    [string]$copy,$origin,$samples,(Join-Path $probeDirectory ($record.kind+'.csv')))
   $null=Confirm-ShortPaCopyIdentity -Path ([string]$copy)
  }finally{Remove-ShortPaCopyDirectory -Path $temporary}
 }
 if($meshCheck){
  Invoke-CooledNative @native -Name mesh_raw_physical_mask -Arguments @('--nogui','--noprompt','lua',$sampler,$raw,$origin,$samples,
   (Join-Path $probeDirectory 'raw_physical_mask.csv'))
 }
 return [pscustomobject]@{receipt=$stage;working_points=$records;probe_directory=$probeDirectory;
  retained_native_build_objects=$(if($meshCheck){@($raw,$working)}else{@()});field_directory=$directory}
}

function Invoke-CooledPopulationClock {
 [CmdletBinding()]
 param([Parameter(Mandatory)]$Package,[string]$RepoRoot=(Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))),
  [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$RuntimeModule)
 $code=@'
import importlib,json,sys
from pathlib import Path
run=Path(sys.argv[1]).resolve();ctx=importlib.import_module(sys.argv[2]).context(run)
decision=ctx['decision'];drive=ctx['cooled_drive'];pulse=decision['actual_pulse_time_us']
close=drive['entrance_close_us'];release=decision['release_start_us'];end=ctx['flight_horizon_us']
births=sorted({float(row['instrument_time_us']) for row in ctx['rows']})
period=1e6/ctx['conditioner']['drive']['frequency_hz']
delta=min(period/16,close/16,(release-close)/16,(pulse-release)/16)
labels=[('birth',t) for t in births]+[('entrance_close_before',close-delta),('entrance_close',close),
 ('entrance_close_after',close+delta),('closed_midpoint',(close+release)/2),
 ('release_before',release-delta),('release_start',release)]
labels += [(f'release_to_oa_{i}',release+(pulse-release)*i/8) for i in range(1,8)]
labels += [('oa_pulse',pulse)]+[(f'post_pulse_{i}',pulse+(end-pulse)*i/8) for i in range(1,8)]+[('flight_horizon',end)]
times=sorted({float(t) for _,t in labels if 0<=t<=end})
path=run/'inputs/extraction_shared_times.json'
path.write_text(json.dumps(times,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
(run/'inputs/cooled_snapshot_clock.json').write_text(json.dumps(dict(schema_version=1,
 role='cooled_frontend_automatic_snapshot_clock',common_decision=ctx['experiment']['common_pulse_decision'],
 actual_pulse_time_us=pulse,release_start_us=release,labels=[dict(name=n,time_us=t) for n,t in labels],
 shared_times_us=times,interpretation='Clock derived from same frozen gate/OA decision and original births, never per-arm occupancy or detector selection'),indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(actual_pulse_time_us=pulse,release_start_us=release,shared_times_path=str(path),
 working_points=list(ctx['fields']['records'].values())),allow_nan=False))
'@
 return Invoke-FrontendRuntimePython -Python $Python -RepoRoot $RepoRoot -RunDirectory $Package.run_dir -Name population_clock `
  -Arguments @('-c',$code,[string]$Package.artifact_run_dir,$RuntimeModule) -Json
}

function Invoke-CooledPopulationAnalysis {
 [CmdletBinding()]
 param([Parameter(Mandatory)]$Package,[string]$RepoRoot=(Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))),
  [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$Module,
  [Parameter(Mandatory)]$Materialized,[Parameter(Mandatory)][string]$Times,[Parameter(Mandatory)][double]$PulseTimeUs)
 $logs=Join-Path $Package.input_dir 'extraction.native_logs.json'
 Write-RunJson -Path $logs -Value @($Materialized.batches|ForEach-Object{[string]$_.stdout})
 $code=@'
import importlib,json,sys
from pathlib import Path
run,logs,times=map(Path,sys.argv[1:4])
result=importlib.import_module(sys.argv[5]).analyze_cooled_frontend(run,
 [Path(p) for p in json.loads(logs.read_text(encoding='utf-8-sig'))],
 shared_times_us=json.loads(times.read_text(encoding='utf-8-sig')),pulse_time_us=float(sys.argv[4]))
print(json.dumps(result,allow_nan=False))
'@
 return Invoke-FrontendRuntimePython -Python $Python -RepoRoot $RepoRoot -RunDirectory $Package.run_dir -Name population_analysis `
  -Arguments @('-c',$code,[string]$Package.artifact_run_dir,$logs,$Times,$PulseTimeUs.ToString('G17',[Globalization.CultureInfo]::InvariantCulture),$Module) -Json
}

function Invoke-CooledCompiledAperture {
 [CmdletBinding()]
 param([Parameter(Mandatory)]$Package,[Parameter(Mandatory)]$Frontend,
  [Parameter(Mandatory)][string]$PaPath,[string]$RepoRoot=(Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))),
  [Parameter(Mandatory)][string]$SimionExe,[Parameter(Mandatory)]$Limits)
 . (Join-Path $RepoRoot 'common/simion/aperture_topology_support.ps1')
 $port=$Frontend.accelerator_local_region.port;$origin=$Frontend.instance_origin_mm;$cell=$Frontend.cell_mm_xyz
 $parameters=@{PaPath=$PaPath;NormalAxis=[string]$port.normal_axis;
  FlangeMinimumMm=[double]$port.flange_min_mm;FlangeMaximumMm=[double]$port.flange_max_mm;
  ApertureCenterMm=[double[]]$port.center_mm;OriginXmm=[double]$origin.x;OriginYmm=[double]$origin.y;OriginZmm=[double]$origin.z;
  CellMmX=[double]$cell.x;CellMmY=[double]$cell.y;CellMmZ=[double]$cell.z;
  MechanicalWidthMm=[double]$port.width_mm;MechanicalHeightMm=[double]$port.height_mm;
  BooleanBoundaryPolicy=[string]$port.boolean_boundary_policy;
  ReportPath=(Join-Path $Package.result_dir 'compiled_aperture_topology.json');
  VerifierPath=(Join-Path $RepoRoot 'common/simion/verify_aperture_topology.lua')}
 $parameters.InvokeVerifier={param($VerifierPath)
  Invoke-ResourceBudgetedProcess -Limits $Limits -RunDir $Package.run_dir -FilePath $SimionExe -WorkingDirectory $Package.run_dir `
   -ArgumentList @('--nogui','--noprompt','lua',$VerifierPath) -UsagePath (Join-Path $Package.log_dir 'aperture_topology.resource_usage.json') `
   -RedirectStandardOutput (Join-Path $Package.log_dir 'aperture_topology.stdout.log') -RedirectStandardError (Join-Path $Package.log_dir 'aperture_topology.stderr.log')
 }
 return Invoke-SimionCompiledApertureTopologyCheck @parameters
}

$workspace=Split-Path -Parent $RepoRoot
$artifacts=Join-Path $workspace 'artifacts'
$project=Join-Path $artifacts ('projects/'+$integration)
$author=Get-Content -LiteralPath $Request -Raw|ConvertFrom-Json -Depth 100
$meshCheckRequest=($author.PSObject.Properties.Name-contains'role')-and$author.role-eq'rf_oatof_cooled_frontend_mesh_check_request'
$simionDirectory=Join-Path $env:ProgramFiles 'SIMION-2020'
$prepare=@('-m',($module+'.prepare'),'--request',$Request,'--repo-root',$RepoRoot,'--workspace-root',$workspace,'--simion-directory',$simionDirectory)
if($meshCheckRequest){
 if($SolverAuthorized-and-not$FieldDesignOnly){throw 'Local mesh check requires FieldDesignOnly; no population flight exists for this request.'}
 $meshPrepare=@'
import json,sys
from pathlib import Path
from integrations.workflows.cooled_frontend.mesh_check import prepare_mesh_check
request,repo,workspace=map(Path,sys.argv[1:4]);args=sys.argv[4:]
if args==['--validate-only']: output=None
elif len(args)==4 and args[0]=='--output-directory' and args[2]=='--run-id': output=Path(args[1])
else: raise ValueError('mesh preparation requires the existing validation or managed-output scope')
print(json.dumps(prepare_mesh_check(request,output,repo,workspace,run_id=args[3] if output else None),allow_nan=False))
'@
 $prepare=@('-c',$meshPrepare,$Request,$RepoRoot,$workspace)
}
if($ValidateOnly){Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {& $Python -B @prepare --validate-only;if($LASTEXITCODE-ne0){throw 'Cooled request validation failed.'}};return}
if($PrepareOnly){
 if(-not(Test-Path -LiteralPath (Join-Path $OutputDirectory 'run_config.json'))){throw 'PrepareOnly output must already belong to a managed run.'}
 $owner=Get-Content -LiteralPath (Join-Path $OutputDirectory 'run_config.json') -Raw|ConvertFrom-Json
 if($owner.project-ne$integration){throw 'PrepareOnly managed run owner must be instrument_assembly.'}
 $frozen=Freeze-CooledRuntime -InputDir (Join-Path $OutputDirectory 'inputs')
 $prepareRoot=[string]$frozen.execution_root
 Invoke-RunToolRootContext -RepoRoot $prepareRoot -Operation {& $Python -B @prepare --output-directory $OutputDirectory --run-id ([string]$owner.run_id);if($LASTEXITCODE-ne0){throw 'Cooled preparation failed.'}}
 return
}
if($FieldDesignOnly-and-not$meshCheckRequest){
 if($null-ne$author.field_source-or$null-ne$author.common_pulse_decision){throw 'Initial FieldDesignOnly requires explicit null field_source and common_pulse_decision.'}
}elseif($ReferenceCalibrationOnly){
 if($meshCheckRequest-or$null-eq$author.field_source-or$null-ne$author.common_pulse_decision-or$author.pressure_scale-ne0){throw 'Reference calibration requires sealed fields, vacuum and no production decision.'}
}elseif(-not$meshCheckRequest-and($null-eq$author.field_source-or$null-eq$author.common_pulse_decision)){throw 'Population flight requires an explicit sealed field source and common actual-field pulse decision.'}
$ExecutionBudgetPath=(Resolve-Path -LiteralPath $ExecutionBudgetPath).Path
$rawBudget=Get-Content -LiteralPath $ExecutionBudgetPath -Raw|ConvertFrom-Json -Depth 100
$commitment=[long]$rawBudget.stage_limits.single_flight_transport.transient_run_directory_bytes
if($commitment-le0){throw 'Positive explicit stage disk commitment required.'}
$scope=if($meshCheckRequest){'local_static_mesh_check'}elseif($FieldDesignOnly){'fielddesign_only'}elseif($ReferenceCalibrationOnly){'cold_reference_calibration'}else{'complete_mother_population'}
$summaryRole=if($meshCheckRequest){'cooled_frontend_local_mesh_check_summary'}elseif($FieldDesignOnly){'cooled_frontend_field_design_summary'}elseif($ReferenceCalibrationOnly){'cooled_frontend_reference_summary'}else{'cooled_frontend_population_summary'}
$retentionReason=if($FieldDesignOnly){'Retain cooled-to-OA field endpoints and native static probes for explicitly bound pressure arms'}elseif($ReferenceCalibrationOnly){'Retain native cold-reference trials and the verified common pulse decision; no original-mother qualification'}else{'Retain complete original mother cooling/OA raw/canonical loss and default-replay evidence; consume sealed shared field endpoints'}
$runId=(Get-Date -Format yyyyMMdd_HHmmss)+$(if($meshCheckRequest){'__build__simion__cooled-frontend-mesh-check'}elseif($FieldDesignOnly){'__build__simion__cooled-frontend-fielddesign'}elseif($ReferenceCalibrationOnly){'__sim__simion__cooled-frontend-reference'}else{'__sim__simion__cooled-frontend-population'})
$destination=Join-Path $project ('runs/'+$runId)
$capacity=$null;$package=$null;$lease=$null;$budget=$null;$field=$null;$failure=$null;$okay=$false;$populationFlightAttempted=$false
$stage='capacity_startup';$frozenRoot=$RepoRoot
$workingFieldGuards=[Collections.Generic.List[string]]::new()
$controllerTicks=[Diagnostics.Process]::GetCurrentProcess().StartTime.ToUniversalTime().Ticks
$saved=Save-RunEnvironment -Names @('PYTHONPATH','PYTHONNOUSERSITE','SIMULATION_PYTHON_EXE')
$env:SIMULATION_PYTHON_EXE=$Python
try{
 $sourceAuthor=$author
 $fieldSource=if($meshCheckRequest){$author.field_source_record}else{$author.field_source}
 if($meshCheckRequest){
  $sourceRequestPath=[string]$author.source_request_record.path
  if(-not[IO.Path]::IsPathRooted($sourceRequestPath)){$sourceRequestPath=Join-Path $workspace $sourceRequestPath}
  $sourceAuthor=Get-Content -LiteralPath $sourceRequestPath -Raw|ConvertFrom-Json -Depth 100
 }
 $candidates=@($Request,$ExecutionBudgetPath)+@($sourceAuthor.source.PSObject.Properties.Value|ForEach-Object{Join-Path $workspace ([string]$_.path)})
 if($fieldSource){
  $fieldEnvelopePath=[string]$fieldSource.path
  if(-not[IO.Path]::IsPathRooted($fieldEnvelopePath)){$fieldEnvelopePath=Join-Path $workspace $fieldEnvelopePath}
  $envelope=Get-Content -LiteralPath $fieldEnvelopePath -Raw|ConvertFrom-Json -Depth 100
  $ownerManifest=[string]$envelope.source_owner_manifest_record.path
  if(-not[IO.Path]::IsPathRooted($ownerManifest)){$ownerManifest=Join-Path $workspace $ownerManifest}
  $candidates+=@($fieldEnvelopePath,(Split-Path -Parent $ownerManifest))
 }
 if($sourceAuthor.common_pulse_decision){
  $decisionPath=[string]$sourceAuthor.common_pulse_decision.path
  if(-not[IO.Path]::IsPathRooted($decisionPath)){$decisionPath=Join-Path $workspace $decisionPath}
  $candidates+=$decisionPath
 }
 $artifactPrefix=[IO.Path]::GetFullPath($artifacts).TrimEnd([IO.Path]::DirectorySeparatorChar)+[IO.Path]::DirectorySeparatorChar
 $protected=@($candidates|ForEach-Object{[IO.Path]::GetFullPath($_)}|Where-Object{$_.StartsWith($artifactPrefix,[StringComparison]::OrdinalIgnoreCase)}|Select-Object -Unique)
 $capacity=Enter-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -ArtifactRoot $artifacts `
  -RunDirectory $destination -CommittedNewBytes $commitment -ProtectedPaths $protected
 $package=New-RunPackage -Python $Python -RepoRoot $RepoRoot -ArtifactRoot $project -RunId $runId -Project $integration `
  -Mode $(if($meshCheckRequest){'cooled_frontend_local_static_mesh_check'}elseif($FieldDesignOnly){'cooled_frontend_field_design'}elseif($ReferenceCalibrationOnly){'cooled_frontend_reference_calibration'}else{'cooled_frontend_population'}) -Software @('SIMION 2020','Python 3.11','PowerShell 7') -RetentionContractEnabled `
  -RetentionClass solver_review -RetentionReason $retentionReason `
  -CapacityLedgerLifecycleEnabled -UseShortExecutionPath -AdditionalDirectories @('simion')
 Copy-VerifiedRunInput -Source $PSCommandPath -Destination (Join-Path $package.input_dir 'execute_cooled_frontend.ps1')|Out-Null
 $budget=Initialize-IntegrationStageBudget -ResolvedBudget $ExecutionBudgetPath -InputDir $package.input_dir `
  -ExpectedIntegrationId $integration -ExpectedWorkflowId cooled_frontend -StageId single_flight_transport -Solver simion -ExpectedRetentionClass solver_review
 $lease=Enter-HostExecutionLease -Role SIMION -Stage prepare -RunId $runId
 $context=@{Python=$Python;RepoRoot=$frozenRoot;RunDirectory=[string]$package.run_dir}
 $stage='freeze_runtime_closure'
 $frozen=Freeze-CooledRuntime -InputDir $package.input_dir
 $frozenRoot=[string]$frozen.execution_root
 . (Join-Path $frozenRoot ($relative+'/runtime/frontend_flight_support.ps1'))
 . (Join-Path $frozenRoot 'integrations/workflows/cooled_frontend/reference_support.ps1')
 $context.RepoRoot=$frozenRoot
 $stage='prepare_complete_source_and_geometry'
 Invoke-FrontendRuntimePython @context -Name prepare -Arguments ($prepare+@('--output-directory',[string]$package.run_dir,'--run-id',$runId))
 if($fieldSource){
  $frozenEnvelope=Get-Content -LiteralPath (Join-Path $package.input_dir 'cooled_field_source.json') -Raw|ConvertFrom-Json -Depth 100
  $stagePath=[string]$frozenEnvelope.field_stage_receipt_record.path
  if(-not[IO.Path]::IsPathRooted($stagePath)){$stagePath=Join-Path $workspace $stagePath}
  $publishedFields=Get-Content -LiteralPath $stagePath -Raw|ConvertFrom-Json -Depth 100
  if($publishedFields.schema_version-ne2){throw 'Current cooled fields require a schema2 published generation receipt.'}
  $updated=Update-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $frozenRoot -Session $capacity -ProtectedCacheKeys @([string]$publishedFields.cache_key)
  $capacity=$updated.session
 }
 $source=Get-Content -LiteralPath (Join-Path $package.input_dir 'source_identity.json') -Raw|ConvertFrom-Json
 if([int]$source.particle_count-ne[int]$rawBudget.particle_count){throw 'Cooled budget must retain the complete frozen source population.'}
 $front=Get-Content -LiteralPath (Join-Path $package.input_dir 'frontend_contract.json') -Raw|ConvertFrom-Json -Depth 100
 $plan=Get-Content -LiteralPath (Join-Path $package.input_dir 'cooled_field_plan.json') -Raw|ConvertFrom-Json -Depth 100
 $minimumPayload=if($FieldDesignOnly){[long]$front.field_storage_forecast.potential_bytes_per_array*(@($plan.working_points).Count+3)}else{0L}
 if($meshCheckRequest){
  $largestParent=($plan.working_points|ForEach-Object{[long]$_.source_pa_record.bytes}|Measure-Object -Maximum).Maximum
  $minimumPayload=[long]$front.field_storage_forecast.potential_bytes_per_array*(@($plan.working_points).Count+2)+[long]$largestParent
 }
 Write-RunJson -Path (Join-Path $package.result_dir 'physical_disk_forecast.json') -Value @{schema_version=1;role='cooled_frontend_storage_forecast';execution_scope=$scope;
  potential_payload_floor_bytes=$minimumPayload;author_commitment_bytes=$commitment;working_points=@($plan.working_points).Count;
  scope=$(if($FieldDesignOnly){'All ordinary endpoints plus one raw geometry, one reusable private solved staging object and one simultaneous public probe copy. Payload floor only; native headers, source, logs and analysis require additional author headroom.'}else{'Immutable source fields shared without materialization; author commitment covers new complete-mother logs, IOB controls, display trajectories, diagnostics and fresh-default replay.'})}
 if($commitment-le$minimumPayload){throw 'Author disk commitment does not exceed the prepared field/probe node payload floor.'}
 $simion=(Resolve-Path -LiteralPath (Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe')).Path
 Write-RunJson -Path (Join-Path $package.input_dir 'native_discovery.json') -Value @{path=$simion;bytes=(Get-Item -LiteralPath $simion).Length;sha256=Get-RunFileSha256 -Path $simion;file_version=(Get-Item -LiteralPath $simion).VersionInfo.FileVersion}
 if($FieldDesignOnly){
 $stage='native_fielddesign_and_static_probe'
 $field=Invoke-CooledFieldDesign -Package $package -FrozenRepoRoot $frozenRoot -Python $Python -RuntimeModule ($module+'.runtime') `
  -SimionExe $simion -Limits $budget.limits -HostLease ([ref]$lease) -CapacitySession ([ref]$capacity)
 $stage='actual_field_theory_proposal'
 if($meshCheckRequest){
  $meshAnalysis="import json,sys;from pathlib import Path;from $module.mesh_check import analyze_mesh_check;print(json.dumps(analyze_mesh_check(Path(sys.argv[1])),allow_nan=False))"
  Invoke-FrontendRuntimePython -Python $Python -RepoRoot $frozenRoot -RunDirectory $package.run_dir -Name local_mesh_analysis `
   -Arguments @('-c',$meshAnalysis,[string]$package.artifact_run_dir)
 }else{
  Invoke-FrontendRuntimePython -Python $Python -RepoRoot $frozenRoot -RunDirectory $package.run_dir -Name field_design_theory `
   -Arguments @('-m',($module+'.field_design'),'--run',[string]$package.artifact_run_dir)
 }
 $profileCode=@'
import json,sys
from pathlib import Path
from common.contracts.write_run_manifest import file_record
run=Path(sys.argv[1]).resolve();root=run/'inputs'
mesh=sys.argv[2]=='local_static_mesh_check'
profile=dict(schema_version=1,role='cooled_frontend_local_mesh_profile' if mesh else 'cooled_frontend_field_design_profile',native_executed=True,fly_executed=False,
 geometry_record=file_record(root/'frontend.gem'),frontend_contract_record=file_record(root/'frontend_contract.json'),
 field_plan_record=file_record(root/'cooled_field_plan.json'),probe_plan_record=file_record(root/'cooled_probe_plan.json'),
 probe_points_record=file_record(root/'cooled_probe_points.csv'),native_discovery_record=file_record(root/'native_discovery.json'),
 boundary_policy='same_kind_actual_parent_on_crop_faces__synthetic_not_physical' if mesh else 'explicit_zero_dirichlet_far_faces_not_mechanical_metal')
(root/'cooled_field_design_profile.json').write_text(json.dumps(profile,indent=2)+'\n',encoding='utf-8',newline='\n')
'@
 Invoke-FrontendRuntimePython -Python $Python -RepoRoot $frozenRoot -RunDirectory $package.run_dir -Name fielddesign_profile `
  -Arguments @('-c',$profileCode,[string]$package.artifact_run_dir,$scope)
 Write-RunJson -Path $package.summary -Depth 30 -Value @{schema_version=1;role=$summaryRole;status='success';execution_scope=$scope;
  source_mother_count=[int]$rawBudget.particle_count;simulated_mother_count=0;field_design_only=$true;fly_executed=$false;gui_executed=$false;full_analyzer_flight_executed=$false;
  field_stage_receipt=$(if($meshCheckRequest){$null}else{Join-Path $package.artifact_run_dir 'inputs/cooled_frontend_field_stage_receipt.json'});
  field_design_profile=(Join-Path $package.artifact_run_dir 'inputs/cooled_field_design_profile.json');
  static_probe_directory=(Join-Path $package.artifact_run_dir 'results/cooled_field_probe');
  qualification='Real native field construction and probes only; no cooling, capture, extraction or focusing result'}
 }elseif($ReferenceCalibrationOnly){
 $stage='actual_field_cold_reference_calibration'
 $reference=Invoke-CooledReferenceCalibration -Package $package -RepoRoot $frozenRoot -Python $Python -SimionExe $simion -Limits $budget.limits -ProjectRunsRoot (Join-Path $project 'runs') -HostLease ([ref]$lease)
 Write-RunJson -Path $package.summary -Depth 100 -Value @{schema_version=1;role=$summaryRole;status='success';execution_scope=$scope;reference=$reference;mother_population_flight=$false;gui_executed=$false;qualification=$reference.qualification}
 }else{
 $stage='verified_shared_fields_and_snapshot_clock'
 $state=Invoke-CooledPopulationClock -Package $package -RepoRoot $frozenRoot -Python $Python -RuntimeModule ($module+'.runtime')
 foreach($record in $state.working_points){
  $null=Protect-ImmutablePaSource -Source ([string]$record.path) -ExpectedBytes ([long]$record.bytes) -ExpectedSha256 ([string]$record.sha256)
  $workingFieldGuards.Add([string]$record.path)
 }
 foreach($warningCode in @($front.accelerator_local_region.accelerator_port_aperture_discretization.grid_alignment.warnings)){
  Write-Warning "SIMION authoritative aperture discretization warning: $warningCode"
 }
 $stage='compiled_aperture_topology'
 $carrier=@($state.working_points|Where-Object{$_.kind-eq'carrier_off'})
 if($carrier.Count-ne1){throw 'Exactly one immutable carrier field required.'}
 $null=Invoke-CooledCompiledAperture -Package $package -Frontend $front -PaPath ([string]$carrier[0].path) `
  -RepoRoot $frozenRoot -SimionExe $simion -Limits $budget.limits
 $lease=Update-HostResourceStage -Lease $lease -Stage flight -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
 $stage='complete_mother_population_flight'
 $populationFlightAttempted=$true
 $materialized=Invoke-FrontendFlightPhase -RunDirectory $package.run_dir -ProjectRunsRoot (Join-Path $project 'runs') `
  -RepoRoot $frozenRoot -Python $Python -RuntimeModule ($module+'.runtime') -SimionExe $simion -Limits $budget.limits `
  -Phase extraction -PulseTimeUs ([double]$state.actual_pulse_time_us) -SharedTimesPath ([string]$state.shared_times_path)
 $lease=Update-HostResourceStage -Lease $lease -Stage postprocess -Budget (Get-HostResourceBudget -Role SIMION -Stage postprocess) -RetainedMemoryBytes 0
 $stage='complete_mother_recorded_diagnostics'
 $analysis=Invoke-CooledPopulationAnalysis -Package $package -RepoRoot $frozenRoot -Python $Python -Module ($module+'.analyze') `
  -Materialized $materialized -Times ([string]$state.shared_times_path) -PulseTimeUs ([double]$state.actual_pulse_time_us)
 $stage='saved_workbench_validation'
 $replay=Invoke-FrontendDefaultReplay -Materialized $materialized -HostLease ([ref]$lease) -RunDirectory $package.run_dir `
  -RepoRoot $frozenRoot -Python $Python -SimionExe $simion -Limits $budget.limits
 Write-RunJson -Path $package.summary -Depth 100 -Value @{schema_version=1;role=$summaryRole;status='success';
  mother_count=[int]$source.particle_count;pressure_scale=[double]$author.pressure_scale;field_design_only=$false;
  fly_executed=$true;gui_executed=$false;full_analyzer_flight_executed=$false;actual_pulse_time_us=[double]$state.actual_pulse_time_us;
  common_pulse_decision=$author.common_pulse_decision;field_source=$author.field_source;extraction=$analysis;
  default_load_iob=$materialized.default_load_iob;default_replay=$replay;
  qualification='Local complete mother pressure-control evidence only; no MR acceptance or resolution claim'}
 }
 $okay=$true
}catch{
 $failure=$_
 if($package){Write-RunJson -Path $package.summary -Value @{schema_version=1;role=$summaryRole;status='failed';stage=$stage;reason=$_.Exception.Message;population_flight_attempted=$populationFlightAttempted;gui_executed=$false}}
}finally{
 try{
  if($package){
   $sample=Get-ManagedSolverProcessSample -RootProcessIds @($PID) -RootProcessStartedAtUtcTicks @{([string]$PID)=$controllerTicks}
   $writers=@($sample.active_process_ids|Where-Object{$_-ne$PID-and$_-notin@($sample.system_console_host_process_ids)})
   if($writers.Count){Write-Warning 'RUN_FINALIZATION_WAITING_FOR_MANAGED_SOLVER_WRITERS'}
   do{$sample=Get-ManagedSolverProcessSample -RootProcessIds @($PID) -RootProcessStartedAtUtcTicks @{([string]$PID)=$controllerTicks};$writers=@($sample.active_process_ids|Where-Object{$_-ne$PID-and$_-notin@($sample.system_console_host_process_ids)});if($writers.Count){Start-Sleep -Milliseconds 500}}while($writers.Count)
   foreach($path in $workingFieldGuards){$null=Unprotect-ImmutablePaSource -Source $path}
   $workingFieldGuards.Clear()
   $config=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
   foreach($file in Get-ChildItem -LiteralPath $package.input_dir -Recurse -File){
    $canonical=Join-Path $package.artifact_run_dir ([IO.Path]::GetRelativePath($package.run_dir,$file.FullName))
    $config.inputs[$canonical]=$canonical
   }
   $config.parameters=@{workflow='cooled_frontend';execution_scope=$scope;scientific_request=(Join-Path $package.artifact_run_dir 'inputs/request.json');stage=$stage;population_flight_attempted=$populationFlightAttempted;gui_executed=$false}
   Write-RunJson -Path $package.run_config -Value $config -Depth 100
   # Native PAs remain manifest-bound. Exact retired build objects must pass
   # the public owner-disposition lifecycle after sealing; TRACE retention is
   # not a native-PA deletion authority.
   $null=Apply-RunArtifactRetention -Python $Python -RepoRoot $frozenRoot -RunConfig $package.run_config
   $outputs=@(Get-ChildItem -LiteralPath $package.run_dir -Recurse -File|Where-Object{-not$_.FullName.StartsWith($package.input_dir+[IO.Path]::DirectorySeparatorChar)-and$_.Name-notin@('run_config.json','run_manifest.json')}|ForEach-Object{$_.FullName})
   Write-VerifiedRunManifest -Python $Python -RepoRoot $frozenRoot -RunConfig $package.run_config -Manifest (Join-Path $package.run_dir 'run_manifest.json') -Status $(if($okay){'success'}else{'failed'}) -Software @('SIMION 2020','Python 3.11','PowerShell 7') -Outputs $outputs -DeferCapacityFinalization
  }
  if($capacity){$null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity;$capacity=$null}
  if($package){Invoke-RunToolRootContext -RepoRoot $frozenRoot -Operation {& $Python -B -m common.contracts.run_capacity_lifecycle --action seal-stopped-payload --artifact-root $artifacts --run-config $package.run_config --owner $integration --confirm-writing-stopped --retention-reason $retentionReason;if($LASTEXITCODE-ne0){throw 'Cooled fielddesign capacity sealing failed.'}}}
 }finally{
  if($lease){Exit-HostExecutionLease -Lease $lease -Outcome $(if($okay){'success'}else{'failed'}) -RunId $runId}
  if($capacity){$null=Exit-ArtifactWorkflowCapacitySession -Python $Python -RepoRoot $RepoRoot -Session $capacity}
  if($package){Remove-RunPackageExecutionAlias -Package $package}
  Restore-RunEnvironment -Names @('PYTHONPATH','PYTHONNOUSERSITE','SIMULATION_PYTHON_EXE') -Snapshot $saved
 }
}
if($failure){throw $failure}
Write-Output "COOLED_FRONTEND=PASS SCOPE=$scope RUN=$($package.artifact_run_dir) GUI=False"
