# Production C0 native static working point or pure-axis response; no optimizer or Fly.
#Requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$RequestPath,
    [Parameter(Mandatory)][string]$RunDirectory,
    [switch]$Approved
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repo=Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent
. (Join-Path $repo 'common/require_powershell7.ps1')
. (Join-Path $repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $repo 'common/host_execution_lease.ps1')
. (Join-Path $repo 'common/resource_budget_support.ps1')
$python=Join-Path $repo '.venv/Scripts/python.exe'
$module='projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_static_field_provider'
function Exit-NativeProviderHostStage {
    param([Parameter(Mandatory)]$Lease)
    $released=Exit-HostResourceStage -Lease $Lease -PassThru
    if($Lease.inherited-or$null-eq$released-or$released.status-ne'released'-or$released.token-ne$Lease.token){
        throw 'Native provider host owner release is unconfirmed; preserve the run and capacity protection.'
    }
}
$RequestPath=(Resolve-Path -LiteralPath $RequestPath).Path
$RunDirectory=$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($RunDirectory)
$compiled=Invoke-RunToolRootContext -RepoRoot $repo -Operation {
    & $python -B -m $module --request $RequestPath
    if($LASTEXITCODE-ne0){throw 'Native static request compilation failed.'}
}
$plan=($compiled-join"`n")|ConvertFrom-Json -AsHashtable
if($null-ne$plan.run_id-and$plan.run_id-ne(Split-Path -Leaf $RunDirectory)){throw 'Request run_id differs from RunDirectory identity.'}
# An unapproved call performs only a pure request check, no run/PA creation.
if(-not$Approved){$compiled;return}
if($env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN){throw 'Release caller host stage before static field production.'}
if(Test-Path -LiteralPath $RunDirectory){throw 'New provider run identity required; no retry or overwrite.'}
$runs=Split-Path -Parent $RunDirectory
if((Split-Path -Leaf $runs)-ne'runs'){throw 'Provider RunDirectory must be a project runs child.'}
$projectRoot=Split-Path -Parent $runs
$artifacts=Split-Path (Split-Path $projectRoot -Parent) -Parent
$runId=Split-Path -Leaf $RunDirectory
$software=@('Python 3.11','SIMION 2020')
$isComposition=$plan.operation-eq'compose'
$isConsumerView=$plan.operation-eq'crop_view'
$isCollisionOverlay=$plan.operation-eq'collision_overlay'
$occupancyNames=@('collision','ip_collision','detector','analyzer_collision_patch')
$isResponse=$plan.ContainsKey('response_basis')-and$null-ne$plan.response_basis
$reason=if($isResponse){'Pure-axis native response retained for voltage composition; not authorized for direct trajectory consumption.'}else{'Production ordinary-static C0 parent/local fields retained for downstream native trajectory consumption.'}
if($isCollisionOverlay){$reason='Same-CSG local collision-only numerical overlay; all sealed source fields, geometry and voltages retained.'}
$newLevels=@($plan.execution_order|Where-Object{-not$plan.levels[$_].ContainsKey('reuse_source')})
$directories=@($newLevels|ForEach-Object{'simion/'+$_})
$surfacePaths=@($newLevels|ForEach-Object{'simion/'+$_+'/'+$(if($_-eq'parent'){'c0_static'}else{'c0_local'})+'.pa-surf'})
foreach($occupancyName in $occupancyNames){if($plan.ContainsKey($occupancyName+'_build')){$directories+=@('simion/'+$occupancyName);$surfacePaths+=@('simion/'+$occupancyName+'/'+$occupancyName+'.pa-surf')}}
$pkg=New-RunPackage -Python $python -RepoRoot $repo -ArtifactRoot $projectRoot -RunId $runId -Project $plan.project -Mode 'native_static_field_provider' -Software $software -RetentionContractEnabled -RetentionClass solver_review -RetentionReason $reason -CapacityLedgerLifecycleEnabled -AdditionalDirectories $directories -UseShortExecutionPath -ExpectedExecutionRelativePaths $surfacePaths
$capacity=$null;$lease=$null;$parentGuard=$null
$overlayGuards=[Collections.Generic.List[IDisposable]]::new()
$status='failed';$stage='capacity_startup';$failure=$null;$failureRecord=$null;$parentDone=$false;$windowDone=$false
$fieldBinding=$null;$responseBasis=$null;$watch=[Diagnostics.Stopwatch]::StartNew();$timings=[ordered]@{}
$levelStatus=[ordered]@{}
try{
    $capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repo -ArtifactRoot $artifacts -RunDirectory $RunDirectory -Owner $plan.project -CommittedNewBytes ([int64]$plan.committed_new_bytes) -ProtectedPaths @($plan.protected_paths)
    $copies=[ordered]@{request=$RequestPath;launcher=$PSCommandPath;compiler=(Join-Path $repo 'projects/parallel_mirror_dual_stripe_mr_tof/analysis/native_static_field_provider.py');geometry_emitter=(Join-Path $repo 'projects/parallel_mirror_dual_stripe_mr_tof/analysis/native_system_geometry.py');analyzer_shapes=(Join-Path $repo 'projects/parallel_mirror_dual_stripe_mr_tof/analysis/analyzer_candidate_geometry.py');candidate_authority=(Join-Path $repo 'projects/parallel_mirror_dual_stripe_mr_tof/analysis/corridor_field_provider.py');binding_loader=(Join-Path $repo 'projects/parallel_mirror_dual_stripe_mr_tof/analysis/static_field_binding.py');builder=(Join-Path $repo 'common/simion/build_dirichlet_patch_basis.lua');executor=(Join-Path $repo 'common/resource_budget_support.ps1')}
    foreach($key in $plan.inputs.Keys){$copies[$key]=$plan.inputs[$key]}
    if($plan.ContainsKey('collision_build')){
        $copies.geometry_resolver=Join-Path $repo 'projects/parallel_mirror_dual_stripe_mr_tof/analysis/resolved_geometry.py'
        $copies.geometry_contract_loader=Join-Path $repo 'projects/parallel_mirror_dual_stripe_mr_tof/analysis/simion_candidate_reference.py'
    }
    $copies.crop_adapter=Join-Path $PSScriptRoot 'crop_native_static_field.lua'
    if($isComposition){$copies.composer=Join-Path $repo 'projects/parallel_mirror_dual_stripe_mr_tof/analysis/standalone_pa_composition.py'}
    $frozen=[ordered]@{}
    foreach($key in $copies.Keys){
        $destination=Join-Path $RunDirectory ('inputs/'+$key+[IO.Path]::GetExtension($copies[$key]))
        Copy-VerifiedRunInput -Source $copies[$key] -Destination $destination
        $frozen[$key]=$destination
    }
    $planPath=Join-Path $RunDirectory 'inputs/plan.json'
    Write-RunJson -Path $planPath -Value $plan -Depth 40
    $frozen.plan=$planPath
    $stage='prepare_native_field'
    Invoke-RunToolRootContext -RepoRoot $repo -Operation {
        & $python -B -m $module --plan $planPath --run-directory $RunDirectory --prepare
        if($LASTEXITCODE-ne0){throw 'Target native field preparation failed.'}
    }
    $plan=Get-Content -LiteralPath $planPath -Raw|ConvertFrom-Json -AsHashtable
    $nativeInputs=Invoke-RunToolRootContext -RepoRoot $repo -Operation {
        $text=& $python -B -c 'import json,sys;from pathlib import Path;from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_static_field_provider import native_input_binding,read;print(json.dumps(native_input_binding(read(Path(sys.argv[1])),Path(sys.argv[2]))))' $planPath $RunDirectory
        if($LASTEXITCODE-ne0){throw 'Native input metadata selection failed.'}
        ($text-join"`n")|ConvertFrom-Json -Depth 50
    }
    $nativePaths=@($nativeInputs.instances|ForEach-Object{$_.pa_path})
    foreach($level in @($nativeInputs)+@($nativeInputs.refinement_windows)){
        foreach($property in $level.sources.PSObject.Properties){$nativePaths+=@([string]$property.Value)}
    }
    foreach($path in @($nativePaths|Select-Object -Unique)){
        $overlayGuards.Add([IO.File]::Open([string]$path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read))
    }
    if(-not$isComposition){
        Invoke-RunToolRootContext -RepoRoot $repo -Operation {
            & $python -B -c 'import sys;from pathlib import Path;from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_static_field_provider import read,verify_native_provider_inputs;verify_native_provider_inputs(read(Path(sys.argv[1])),Path(sys.argv[2]));print("NATIVE_INPUT_ASSETS=PASS")' $planPath $RunDirectory
            if($LASTEXITCODE-ne0){throw 'Native input asset verification failed before vendor use.'}
        }
    }
    foreach($name in @('frozen_input','resolved_geometry')){
        $frozen[$name]=Join-Path $RunDirectory ('inputs/'+$name+'.json')
    }
    if($isResponse-or$isComposition){$frozen.source_authority=Join-Path $RunDirectory 'inputs/source_authority.json'}
    foreach($label in $plan.execution_order){
        if($plan.levels[$label].ContainsKey('reuse_source')){continue}
        $frozen[$label+'_plan']=Join-Path $RunDirectory ('inputs/'+$label+'_plan.json')
        if($plan.levels[$label].ContainsKey('crop')){
            $frozen[$label+'_consumer_plan']=Join-Path $RunDirectory ('inputs/'+$label+'_consumer_plan.json')
        }
    }
    foreach($occupancyName in $occupancyNames){if($plan.ContainsKey($occupancyName+'_build')){$frozen[$occupancyName+'_plan']=Join-Path $RunDirectory ('inputs/'+$occupancyName+'_plan.json')}}
    $cfg=Get-Content -LiteralPath $pkg.run_config -Raw|ConvertFrom-Json -AsHashtable
    $cfg.inputs=$frozen
    $cfg.parameters=@{workflow='native_static_field_provider';operation=$plan.operation;refine_stopping=$plan.refine_stopping;automatic_retry_count=0;fly_performed=$false;qualification_passed=$false;collision_role1='new C0 parent; other three sealed collision roles unchanged';resource_limit_semantics='Resource measurements warning-only; public artifact capacity hard.'}
    if(-not$isCollisionOverlay-and$plan.levels.parent.ContainsKey('reuse_source')){
        $cfg.parameters.collision_role1='unchanged sealed C0 parent; all collision roles unchanged'
        $cfg.parameters.reused_source_levels=@($plan.execution_order|Where-Object{$plan.levels[$_].ContainsKey('reuse_source')})
    }
    if($plan.ContainsKey('collision_build')){$cfg.parameters.collision_role1='new C0 parent';$cfg.parameters.collision_role2='same new resolved analyzer; ordinary occupancy PA; gem2pa only, no Refine/Fast Adjust'}
    if(-not$isComposition-and-not$isConsumerView-and-not$isCollisionOverlay){$cfg.parameters.refine_options=$plan.refine_options}
    if($isCollisionOverlay){$cfg.parameters.collision_role1='unchanged source fields and original four collision instances';$cfg.parameters.collision_role5='same complete analyzer CSG, finer occupancy only; gem2pa; no Refine/Fast Adjust'}
    if($plan.ContainsKey('consumer_view')){$cfg.parameters.collision_role1='unchanged full source collision PA';$cfg.parameters.consumer_view=$plan.consumer_view}
    if($isResponse){$cfg.parameters.response_basis=$plan.response_basis;$cfg.parameters.fly_authorized=$false}
    Write-RunJson -Path $pkg.run_config -Value $cfg -Depth 40
    if($isComposition){
        $budget=Get-HostResourceBudget -Role GATE -Stage prepare
        $budget.io_slots=1 # Bulk sequential PA reads/writes; still a light, bounded-memory stage.
        $lease=Enter-HostResourceStage -Role GATE -Stage prepare -Budget $budget -RunId $runId
        $limits=@{};foreach($key in $plan.levels.parent.resource_limits.Keys){$limits[$key]=$plan.levels.parent.resource_limits[$key]}
        $limits.transient_run_directory_bytes=[int64]$plan.committed_new_bytes
        $limits.compact_final_retained_bytes=[int64]$plan.final_retained_estimate_bytes
        $stage='compose_static_fields';$timer=[Diagnostics.Stopwatch]::StartNew()
        # Bounded Python blocks do not invoke SIMION or require its heavy lease.
        $step=Invoke-ResourceBudgetedProcess -Limits ([pscustomobject]$limits) -RunDir $RunDirectory -UsagePath (Join-Path $RunDirectory 'results/composition_resource_usage.json') -FilePath $python -WorkingDirectory $repo -ArgumentList @('-B','-m',$module,'--plan',$planPath,'--run-directory',$RunDirectory,'--compose') -RedirectStandardOutput (Join-Path $RunDirectory 'logs/composition.log') -RedirectStandardError (Join-Path $RunDirectory 'logs/composition.stderr.log')
        $timings[$stage]=$timer.Elapsed.TotalSeconds
        if($step.exit_code-ne0){throw 'Native response materialization failed.'}
        foreach($label in $plan.execution_order){
            if(-not(Test-Path -LiteralPath $plan.materialization.receipts[$label] -PathType Leaf)){throw "Missing materialization receipt: $label"}
            $levelStatus[$label]=@{refine_completed=$false;crop_completed=$false;completed=$true;materialized=$true}
        }
        Exit-NativeProviderHostStage -Lease $lease;$lease=$null
    }else{
    $exe=Join-Path $env:ProgramFiles 'SIMION-2020/simion.exe'
    if(-not(Test-Path -LiteralPath $exe -PathType Leaf)){throw 'Installed SIMION2020 missing.'}
    foreach($occupancyName in $occupancyNames){
      if($plan.ContainsKey($occupancyName+'_build')){
        $collision=$plan[$occupancyName+'_build']
        $levelStatus[$occupancyName]=@{refine_completed=$false;crop_completed=$false;completed=$false}
        $budget=Get-HostResourceBudget -Role SIMION -Stage prepare
        $budget.memory_bytes=[Math]::Max([int64]$budget.memory_bytes,2*[int64]$collision.pa_bytes)
        $lease=Enter-HostResourceStage -Role SIMION -Stage prepare -Budget $budget -RunId $runId
        $sourceLimits=if($isCollisionOverlay){$plan.resource_limits}else{$plan.levels.parent.resource_limits}
        $limits=@{};foreach($key in $sourceLimits.Keys){$limits[$key]=$sourceLimits[$key]}
        $limits.wall_clock_seconds=[double]$sourceLimits.wall_clock_seconds_by_solver.simion
        $limits.process_tree_working_set_bytes=[Math]::Max([int64]$limits.process_tree_working_set_bytes,2*[int64]$collision.pa_bytes)
        $limits.transient_run_directory_bytes=[int64]$plan.committed_new_bytes
        $limits.compact_final_retained_bytes=[int64]$plan.final_retained_estimate_bytes
        $stage=$occupancyName+'_gem2pa';$timer=[Diagnostics.Stopwatch]::StartNew()
        $step=Invoke-ResourceBudgetedProcess -Limits ([pscustomobject]$limits) -RunDir $RunDirectory -UsagePath (Join-Path $RunDirectory ('results/'+$occupancyName+'_resource_usage.json')) -FilePath $exe -WorkingDirectory (Join-Path $pkg.run_dir ('simion/'+$occupancyName)) -ArgumentList @('--nogui','--noprompt','gem2pa',($occupancyName+'.gem'),($occupancyName+'.pa')) -RedirectStandardOutput (Join-Path $RunDirectory ('logs/'+$occupancyName+'_gem2pa.log')) -RedirectStandardError (Join-Path $RunDirectory ('logs/'+$occupancyName+'_gem2pa.stderr.log'))
        $timings[$stage]=$timer.Elapsed.TotalSeconds
        $collisionPa=Join-Path $RunDirectory ('simion/'+$occupancyName+'/'+$occupancyName+'.pa')
        if($step.exit_code-ne0-or-not(Test-Path -LiteralPath $collisionPa)-or(Get-Item -LiteralPath $collisionPa).Length-ne[int64]$collision.pa_bytes){throw 'Ordinary collision gem2pa failed or grid payload length differs.'}
        if($isCollisionOverlay-and(-not(Test-Path -LiteralPath ($collisionPa+'-surf'))-or(Get-Item -LiteralPath ($collisionPa+'-surf')).Length-le0)){throw 'Collision overlay fractional surface is absent or empty.'}
        $levelStatus[$occupancyName].completed=$true
        Exit-NativeProviderHostStage -Lease $lease;$lease=$null
    }
    }
    foreach($label in $plan.execution_order){
        $level=$plan.levels[$label]
        if($level.ContainsKey('reuse_source')){
            $levelStatus[$label]=@{refine_completed=$false;crop_completed=$false;completed=$true;reused=$true}
            continue
        }
        $levelStatus[$label]=@{refine_completed=$false;crop_completed=$false;completed=$false}
        $budget=Get-HostResourceBudget -Role SIMION -Stage prepare
        foreach($key in $level.resource_budget.Keys){$budget[$key]=$level.resource_budget[$key]}
        $lease=Enter-HostResourceStage -Role SIMION -Stage prepare -Budget $budget -RunId $runId
        $limits=@{};foreach($key in $level.resource_limits.Keys){$limits[$key]=$level.resource_limits[$key]}
        $limits.wall_clock_seconds=[double]$level.resource_limits.wall_clock_seconds_by_solver.simion
        $limits.transient_run_directory_bytes=[int64]$plan.committed_new_bytes
        $limits.compact_final_retained_bytes=[int64]$plan.final_retained_estimate_bytes
        $working=Join-Path $pkg.run_dir ('simion/'+$label)
        $basename=if($label-eq'parent'){'c0_static'}else{'c0_local'}
        $pa=Join-Path $RunDirectory ('simion/'+$label+'/'+$basename+'.pa')
        $usage=Join-Path $RunDirectory ('results/'+$label+'_resource_usage.json')
        $processArgs=@{Limits=([pscustomobject]$limits);RunDir=$RunDirectory;UsagePath=$usage;FilePath=$exe;WorkingDirectory=$working}
        if(-not$isConsumerView){
        $stage=$label+'_gem2pa';$timer=[Diagnostics.Stopwatch]::StartNew()
        $step=Invoke-ResourceBudgetedProcess @processArgs -ArgumentList @('--nogui','--noprompt','gem2pa',($basename+'.gem'),($basename+'.pa')) -RedirectStandardOutput (Join-Path $RunDirectory ('logs/'+$stage+'.log')) -RedirectStandardError (Join-Path $RunDirectory ('logs/'+$stage+'.stderr.log'))
        $timings[$stage]=$timer.Elapsed.TotalSeconds
        if($step.exit_code-ne0-or-not(Test-Path -LiteralPath $pa)-or-not(Test-Path -LiteralPath ($pa+'-surf'))){throw 'gem2pa failed or PA/fractional companion absent.'}
        $heavy=Get-HostResourceBudget -Role SIMION -Stage pa_refine
        foreach($key in $level.resource_budget.Keys){$heavy[$key]=$level.resource_budget[$key]}
        $lease=Update-HostResourceStage -Lease $lease -Stage pa_refine -Budget $heavy -RetainedMemoryBytes 0
        $stage=$label+'_refine';$timer=[Diagnostics.Stopwatch]::StartNew()
        $convergenceText=([double]$plan.refine_options.convergence).ToString('R',[Globalization.CultureInfo]::InvariantCulture)
        if($label-eq'parent'){
            $arguments=@('--nogui','--noprompt','refine',('--convergence='+$convergenceText),($basename+'.pa'))
        }else{
            $parentLabel=$level.parent_label
            if(-not$levelStatus.Contains($parentLabel)-or-not$levelStatus[$parentLabel].completed){throw 'Local boundary requires completed declared parent Refine.'}
            if($plan.levels[$parentLabel].ContainsKey('crop')){throw 'A cropped consumer cannot supply a full solve boundary.'}
            $parentName=if($parentLabel-eq'parent'){'c0_static.pa'}else{'c0_local.pa'}
            $parentPa=if($plan.levels[$parentLabel].ContainsKey('reuse_source')){$plan.levels[$parentLabel].reuse_source.pa_path}else{Join-Path $RunDirectory ('simion/'+$parentLabel+'/'+$parentName)}
            $parentGuard=[IO.File]::Open($parentPa,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
            $arguments=@('--nogui','--noprompt','lua',$frozen.builder,$pa,$parentPa,($plan.levels[$parentLabel].box_mm[0..2]-join','),($level.box_mm[0..2]-join','),'x_mirror_five_faces',$convergenceText)
        }
        if($plan.refine_options.ContainsKey('skipped_point')){
            if($plan.refine_options.skipped_point-isnot[bool]){throw 'Refine skipped_point must be Boolean.'}
            $skippedPointText=if($plan.refine_options.skipped_point){'1'}else{'0'}
            if($label-eq'parent'){$arguments=@($arguments[0..3])+@('--skipped-point='+$skippedPointText)+@($arguments[4])}
            else{$arguments+=@($skippedPointText)}
        }
        $step=Invoke-ResourceBudgetedProcess @processArgs -ArgumentList $arguments -RedirectStandardOutput (Join-Path $RunDirectory ('logs/'+$stage+'.log')) -RedirectStandardError (Join-Path $RunDirectory ('logs/'+$stage+'.stderr.log'))
        $timings[$stage]=$timer.Elapsed.TotalSeconds
        if($null-ne$parentGuard){$parentGuard.Dispose();$parentGuard=$null}
        if($step.exit_code-ne0-or-not(Test-Path -LiteralPath ($pa+'-surf'))){throw 'Native Refine failed or fractional companion lost.'}
        $levelStatus[$label].refine_completed=$true
        if($label-eq'parent'){$parentDone=$true}
        $observed=Get-Content -LiteralPath $usage -Raw|ConvertFrom-Json
        if([double]$observed.wall_clock_seconds-gt[double]$limits.wall_clock_seconds_by_solver.simion){Write-Warning "$label wall warning exceeded; no solver stop."}
        if([int64]$observed.peak_process_tree_working_set_bytes-gt[int64]$limits.process_tree_working_set_bytes){Write-Warning "$label memory warning exceeded; no solver stop."}
        }
        if($level.ContainsKey('crop')-or$isConsumerView){
            $crop=if($isConsumerView){@{method='pa:crop';persist=$false;overwrite_private_working_pa=$true;refine_after_crop=$false;start_grid=@(0,0,0);width_grid=@($level.dimensions|ForEach-Object{$_-1});consumer_dimensions=$level.dimensions;expected_consumer_pa_bytes=([int64]$level.dimensions[0]*$level.dimensions[1]*$level.dimensions[2]*8+56)}}else{$level.crop}
            if($crop.method-ne'pa:crop'-or$crop.persist-or-not$crop.overwrite_private_working_pa-or$crop.refine_after_crop){throw 'Unsupported post-Refine crop contract.'}
            $lease=Update-HostResourceStage -Lease $lease -Stage prepare -Budget $budget -RetainedMemoryBytes 0
            $stage=$label+'_crop';$timer=[Diagnostics.Stopwatch]::StartNew()
            $receipt=Join-Path $RunDirectory ('results/'+$label+'_crop_receipt.json')
            $csv=Join-Path $RunDirectory ('results/'+$label+'_crop_samples.csv')
            $cropArgs=$processArgs.Clone()
            $cropArgs.UsagePath=Join-Path $RunDirectory ('results/'+$label+'_crop_resource_usage.json')
            $cropSource=if($isConsumerView){[string]$level.consumer_view_source.pa_path}else{$pa}
            $cropDimensions=if($isConsumerView){$level.consumer_view_source.grid.dimensions}else{$level.dimensions}
            if($isConsumerView){$parentGuard=[IO.File]::Open($cropSource,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)}
            $arguments=@('--nogui','--noprompt','lua',$frozen.crop_adapter,$cropSource,$csv,$receipt,($cropDimensions-join','),($level.pitch_mm-join','),($crop.start_grid-join','),($crop.width_grid-join','))
            if($isConsumerView){$arguments+=@($pa)}
            $step=Invoke-ResourceBudgetedProcess @cropArgs -ArgumentList $arguments -RedirectStandardOutput (Join-Path $RunDirectory ('logs/'+$stage+'.log')) -RedirectStandardError (Join-Path $RunDirectory ('logs/'+$stage+'.stderr.log'))
            if($null-ne$parentGuard){$parentGuard.Dispose();$parentGuard=$null}
            $timings[$stage]=$timer.Elapsed.TotalSeconds
            if($step.exit_code-ne0-or-not(Test-Path -LiteralPath $receipt)-or-not(Test-Path -LiteralPath ($pa+'-surf'))){throw 'Official crop/save/reload failed or fractional companion lost.'}
            $checked=Get-Content -LiteralPath $receipt -Raw|ConvertFrom-Json -AsHashtable
            if($checked.status-ne'PASS'-or$checked.refine_after_crop-or($checked.consumer_dimensions-join',')-ne($crop.consumer_dimensions-join',')-or(Get-Item -LiteralPath $pa).Length-ne[int64]$crop.expected_consumer_pa_bytes){throw 'Crop receipt or consumer output dimensions/bytes differ.'}
            $levelStatus[$label].crop_completed=$true
        }
        $levelStatus[$label].completed=$true
        Exit-NativeProviderHostStage -Lease $lease;$lease=$null
    }
    $windowDone=(-not$isConsumerView-and-not$isCollisionOverlay)-and(@($plan.window_labels|Where-Object{-not$levelStatus[$_].completed}).Count-eq0)
    }
    $stage='binding_publication'
    if($isResponse){$responseBasis=Join-Path $RunDirectory 'results/response_basis.json'}else{$fieldBinding=Join-Path $RunDirectory 'results/field_binding.json'}
    Invoke-RunToolRootContext -RepoRoot $repo -Operation {
        & $python -B -m $module --plan $planPath --run-directory $RunDirectory --binding
        if($LASTEXITCODE-ne0){throw 'Native binding metadata failed.'}
    }
    $status='success'
}catch [Management.Automation.PipelineStoppedException]{
    $status='interrupted';$failure=$_.Exception.Message;$failureRecord=$_
}catch{
    $failure=$_.Exception.Message;$failureRecord=$_
}finally{
    $writersStopped=($null-eq$lease)
    if($null-ne$lease){
        try{
            Exit-NativeProviderHostStage -Lease $lease
            $lease=$null;$writersStopped=$true
        }catch{
            if($null-eq$failureRecord){$failureRecord=$_}else{$failureRecord.Exception.Data['host_release_error']=$_.Exception.Message}
        }
    }
    if($writersStopped){
    foreach($guard in @($overlayGuards)+@($parentGuard)){
        if($null-eq$guard){continue}
        try{$guard.Dispose()}catch{
            if($null-eq$failureRecord){$failureRecord=$_}else{
                $failureRecord.Exception.Data['input_guard_errors']=@($failureRecord.Exception.Data['input_guard_errors'])+@($_.Exception.Message)
            }
        }
    }
    try{
        Write-RunJson -Path $pkg.summary -Value @{status=$status;failure_stage=$(if($status-eq'success'){$null}else{$stage});error=$failure;parent_refine_completed=$parentDone;local_refine_completed=$windowDone;levels=$levelStatus;execution_order=$plan.execution_order;field_binding=$(if($status-eq'success'){$fieldBinding}else{$null});field_binding_path=$(if($status-eq'success'){$fieldBinding}else{$null});response_basis_path=$(if($status-eq'success'){$responseBasis}else{$null});wall_seconds=$watch.Elapsed.TotalSeconds;stage_seconds=$timings;fly_performed=$false;qualification_passed=$false} -Depth 20
        $null=Apply-RunArtifactRetention -Python $python -RepoRoot $repo -RunConfig $pkg.run_config
        $outputs=@(Get-ChildItem -LiteralPath $RunDirectory -File -Recurse|Where-Object{$_.FullName-notin@((Join-Path $RunDirectory 'run_config.json'),(Join-Path $RunDirectory 'run_manifest.json'))}|ForEach-Object FullName)
        Write-RunManifest -Python $python -RepoRoot $repo -RunConfig $pkg.run_config -Status $status -Software $software -Outputs $outputs
        # The same producer just recorded all payloads and read back its atomic manifest.
        $published=Get-Content -LiteralPath (Join-Path $RunDirectory 'run_manifest.json') -Raw|ConvertFrom-Json
        if($published.status-cne$status){throw 'Native provider manifest status differs.'}
        if($null-ne$capacity){Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repo -Session $capacity;$capacity=$null}
        Invoke-RunToolRootContext -RepoRoot $repo -Operation {
            & $python -m common.contracts.run_capacity_lifecycle --action seal-stopped-payload --artifact-root $artifacts --run-config $pkg.run_config --owner $plan.project --confirm-writing-stopped --retention-reason $reason
            if($LASTEXITCODE-ne0){throw 'Native provider heavy payload sealing failed.'}
        }
    }catch{
        if($null-eq$failureRecord){$failureRecord=$_}else{$failureRecord.Exception.Data['failure_closure_error']=$_.Exception.Message}
    }finally{
        if($null-ne$capacity){
            try{Exit-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repo -Session $capacity}catch{
                if($null-eq$failureRecord){$failureRecord=$_}else{$failureRecord.Exception.Data['capacity_release_error']=$_.Exception.Message}
            }
        }
        try{Remove-RunPackageExecutionAlias -Package $pkg}catch{
            if($null-eq$failureRecord){$failureRecord=$_}else{$failureRecord.Exception.Data['execution_alias_error']=$_.Exception.Message}
        }
    }
    }else{$failureRecord.Exception.Data['writers_stopped']=$false}
    if($null-ne$failureRecord){throw $failureRecord}
}
Write-Output "RUN=$RunDirectory STATUS=$status FIELD_BINDING=$fieldBinding RESPONSE_BASIS=$responseBasis"
