[CmdletBinding()]
param([Parameter(Mandatory)][string]$RunId,[Parameter(Mandatory)][string]$PABuildRunPath,[Parameter(Mandatory)][string]$RuntimeControllerPath,[Parameter(Mandatory)][string]$CampaignPath,[Parameter(Mandatory)][string]$ReleaseSpecPath,[ValidateSet('native','zone1_ideal','zone2_ideal','full_ideal')][string]$FieldMode='native',[string]$SimionExe='')
Set-StrictMode -Version Latest;$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path;$repoRoot=(Resolve-Path (Join-Path $projectRoot '..\..')).Path;$workspaceRoot=(Resolve-Path (Join-Path $repoRoot '..')).Path
. (Join-Path $repoRoot 'common\require_powershell7.ps1');. (Join-Path $repoRoot 'common\contracts\run_artifact_support.ps1');. (Join-Path $repoRoot 'common\host_execution_lease.ps1')
$python=Join-Path $repoRoot '.venv\Scripts\python.exe';if(-not$SimionExe){$SimionExe=Join-Path $env:ProgramFiles 'SIMION-2020\simion.exe'};if(-not(Test-Path $SimionExe)){throw 'SIMION executable is missing'}

function Invoke-FocusFrozenPython {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$CodeRoot,
    [Parameter(Mandatory)][string]$OriginsPath,[string]$Module='',[string[]]$Arguments=@())
  # -I ignores cwd/PYTHONPATH. All project/common imports use this one snapshot.
  $bootstrap=@'
import importlib,importlib.util,json,runpy,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve()
origins=Path(sys.argv[2])
module=sys.argv[3]
arguments=sys.argv[4:]
sys.path[:0]=[str(root/'src'),str(root)] if (root/'src').is_dir() else [str(root)]
entry_origin=None
try:
    if module:
        entry_origin=Path(importlib.util.find_spec(module).origin).resolve()
        if not entry_origin.is_relative_to(root):
            raise RuntimeError("Focus Python entry is outside its frozen package")
        sys.argv=[module,*arguments]
        runpy.run_module(module,run_name="__main__",alter_sys=True)
    else:
        for name in ("msplatform.ion_release.cylinder","projects.orthogonal_accelerator.analysis.component_focus_simion_source","projects.orthogonal_accelerator.analysis.component_focus_analysis"):
            importlib.import_module(name)
        campaign=json.loads(Path(arguments[0]).read_text(encoding="utf-8-sig"))
        from projects.orthogonal_accelerator.analysis.two_zone_geometry import load_geometry_profile
        load_geometry_profile(campaign["geometry_profile_id"])
finally:
    paths={name:str(Path(value.__file__).resolve()) for name,value in sys.modules.items()
           if name.split('.')[0] in ("common","projects","msplatform") and getattr(value,"__file__",None)}
    if entry_origin is not None:
        paths[module]=str(entry_origin)
    if any(not Path(path).is_relative_to(root) for path in paths.values()):
        raise RuntimeError("Focus Python imported code outside its frozen package")
    fact={"module":module or "preflight","code_root":str(root),"module_paths":paths,
          "geometry_contract_path":str(root/"projects/orthogonal_accelerator/config/component_contract.json")}
    facts=json.loads(origins.read_text(encoding="utf-8")) if origins.exists() else []
    facts.append(fact)
    origins.write_text(json.dumps(facts,indent=2)+"\n",encoding="utf-8")
'@
  & $Python -I -B -c $bootstrap $CodeRoot $OriginsPath $Module @Arguments
}

function Initialize-FocusFrozenPython {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$RepoRoot,[Parameter(Mandatory)][string]$RunConfig,
    [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$CampaignPath)
  $config=Get-Content -LiteralPath $RunConfig -Raw -Encoding utf8|ConvertFrom-Json -AsHashtable
  $root=Split-Path -Parent $RunConfig
  $code=Join-Path $root 'inputs/code'
  $origins=Join-Path $root 'results/python_execution.json'
  $groups=@('common/contracts','common/simion','projects/orthogonal_accelerator/analysis')
  $enumerate=@'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve()
sys.path[:0]=[str(root/'src'),str(root)] if (root/'src').is_dir() else [str(root)]
from msplatform.execution.inputs import enumerate_python_sources
request=json.load(sys.stdin)
paths=enumerate_python_sources(Path(request["source_root"]),package_roots=request["package_roots"])
paths=sorted(set(paths)|set(enumerate_python_sources(root,package_roots=['src/msplatform'],
    provider_root='src/msplatform',resource_suffixes=('.schema.json',))))
print(json.dumps(paths))
'@
  $request=@{source_root=$RepoRoot;package_roots=$groups}|ConvertTo-Json -Depth 10 -Compress
  $savedOutputEncoding=$OutputEncoding
  try{
    $OutputEncoding=[Text.UTF8Encoding]::new($false)
    $selection=($request|& $Python -X utf8 -I -B -c $enumerate $RepoRoot)-join"`n"
  }finally{$OutputEncoding=$savedOutputEncoding}
  if($LASTEXITCODE-ne0){throw 'Focus Python package enumeration failed'}
  $files=@($selection|ConvertFrom-Json)
  $files+='projects/orthogonal_accelerator/config/component_contract.json'
  foreach($relative in @($files|Sort-Object)){
    $destination=Join-Path $code $relative
    Copy-VerifiedRunInput (Join-Path $RepoRoot $relative) $destination|Out-Null
    $config.inputs['python_code__'+$relative.Replace('/','__')]=$destination
  }
  $config.parameters.python_package_groups=$groups
  $config.parameters.python_code_root=$code
  foreach($name in @('campaign_template.json','campaign.json','component_focus_pa_plan.json','release_spec.json','resolved_projection.json')){
    $config.inputs[$name]=Join-Path $root ('inputs/'+$name)
  }
  $config|ConvertTo-Json -Depth 100|Set-Content -LiteralPath $RunConfig -Encoding utf8
  Invoke-FocusFrozenPython -Python $Python -CodeRoot $code -OriginsPath $origins -Arguments @($CampaignPath)
  if($LASTEXITCODE-ne0){throw 'Frozen focus Python import or geometry resource preflight failed'}
  return @{code_root=$code;origins_path=$origins}
}

$previousPythonPath=$env:PYTHONPATH;$env:PYTHONPATH=$repoRoot
$family=(Resolve-Path $PABuildRunPath).Path;$paManifest=Get-Content -LiteralPath (Join-Path $family 'run_manifest.json') -Raw -Encoding UTF8|ConvertFrom-Json;$paStatus=[string]$paManifest.status;if($paStatus-notin@('success','checkpoint')){throw 'Provider focus-PA manifest is neither reusable success nor retained runtime checkpoint'};& $python (Join-Path $repoRoot 'common\contracts\verify_run_manifest.py') (Join-Path $family 'run_manifest.json') --require-status $paStatus --require-project orthogonal_accelerator --require-mode component_focus_pa_build;if($LASTEXITCODE-ne0){throw 'Provider focus-PA manifest verification failed'}
$result=Get-Content -Raw (Join-Path $family 'results\component_focus_pa_result.json')|ConvertFrom-Json;$disposition=if($null-ne$result.PSObject.Properties['disposition']){[string]$result.disposition}else{''};$published=(@('published','hit')-contains$disposition)-or($result.status-eq'published'-and$result.action_required-eq'complete');if(-not$published){throw 'Focus PA is not a published cache generation'}
 $plan=Join-Path $family 'results\component_focus_pa_plan.json';if(-not(Test-Path $plan)){throw 'Provider focus PA plan is missing'};$planDocument=Get-Content -Raw $plan|ConvertFrom-Json -Depth 30;$electrodeCount=[int]$planDocument.electrode_count;$generation=(Resolve-Path $result.generation_directory).Path;$manifest=Get-Content -Raw (Join-Path $generation 'cache_manifest.json')|ConvertFrom-Json;$expectedNames=@('orthogonal_accelerator_focus.pa#')+@(0..$electrodeCount|ForEach-Object{"orthogonal_accelerator_focus.pa$_"})+@(1..$electrodeCount|ForEach-Object{"orthogonal_accelerator_focus.response$_.pa"})+@('orthogonal_accelerator_focus.standalone_responses.json');$expectedNames=@($expectedNames|Sort-Object);if((@($manifest.files|ForEach-Object{$_.name})-join ',')-ne($expectedNames-join ',')){throw 'Published provider cache inventory lacks its exact standalone response bank'};$controller=(Resolve-Path -LiteralPath $RuntimeControllerPath).Path;if([IO.Path]::GetFullPath($controller).StartsWith([IO.Path]::GetFullPath($generation)+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Flight refuses a controller inside the published cache generation'};$runtimeDirectory=Split-Path -Parent $controller;$runtimeNames=@(Get-ChildItem -LiteralPath $runtimeDirectory -File|ForEach-Object{$_.Name}|Sort-Object);$expectedRuntimeNames=@(0..$electrodeCount|ForEach-Object{"orthogonal_accelerator_focus.pa$_"});if(($runtimeNames-join ',')-ne(($expectedRuntimeNames|Sort-Object)-join ',')){throw 'Private runtime family inventory differs from the provider electrode namespace'}
$campaign=(Resolve-Path -LiteralPath $CampaignPath).Path;$package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot (Join-Path $workspaceRoot 'artifacts\projects\orthogonal_accelerator') -RunId $RunId -Project orthogonal_accelerator -Mode component_focus_flight -Software @('SIMION 2020','Python 3.11') -RetentionContractEnabled -RetentionClass solver_review -RetentionReason 'Independent closed-two-zone component focus flight.' -AdditionalDirectories @('simion') -CapacityLedgerLifecycleEnabled
$lease=$null;$done=$false;$failureDetail='';try{$lease=Enter-HostExecutionLease -Role SIMION -Stage flight -RunId $RunId;$run=$package.run_dir;$inputs=$package.input_dir;$solver=Join-Path $run 'simion';$results=$package.result_dir;$logs=$package.log_dir
 $campaignTemplate=Join-Path $inputs 'campaign_template.json';$runCampaign=Join-Path $inputs 'campaign.json';Copy-VerifiedRunInput $campaign $campaignTemplate|Out-Null;Copy-VerifiedRunInput $plan (Join-Path $inputs 'component_focus_pa_plan.json')|Out-Null;Copy-VerifiedRunInput (Join-Path $repoRoot 'src/msplatform/backends/simion/resources/scientific_event_csv.lua') (Join-Path $solver 'component_focus.scientific_event_csv.lua')|Out-Null;Copy-VerifiedRunInput (Join-Path $projectRoot 'simion\component_focus.lua') (Join-Path $solver 'component_focus.lua')|Out-Null;Copy-VerifiedRunInput (Join-Path $projectRoot 'simion\build_component_focus_iob.lua') (Join-Path $solver 'build_component_focus_iob.lua')|Out-Null
 $releaseSpec=Join-Path $inputs 'release_spec.json';$c=Get-Content -Raw $campaignTemplate|ConvertFrom-Json;Copy-VerifiedRunInput (Resolve-Path -LiteralPath $ReleaseSpecPath).Path $releaseSpec|Out-Null;$c.release_spec=(Get-Content -Raw $releaseSpec|ConvertFrom-Json);$c|ConvertTo-Json -Depth 12|Set-Content $runCampaign -Encoding utf8;$p=Get-Content -Raw (Join-Path $inputs 'component_focus_pa_plan.json')|ConvertFrom-Json;$paSpan=@($p.numerical_domain.span_mm);$storedSpan=@($p.numerical_domain.stored_span_mm);if($paSpan.Count-ne3-or$storedSpan.Count-ne3){throw 'Provider PA span metadata is invalid'};for($i=0;$i-lt3;$i++){if([double]$paSpan[$i]-ne[double]$manifest.identity.grid_phase.pa_span_mm[$i]-or[double]$storedSpan[$i]-ne[double]$manifest.identity.grid_phase.stored_span_mm[$i]){throw 'Published PA span differs from provider plan'}};$resolvedProjection=$c.simion_projection.PSObject.Copy();$resolvedProjection.local_pa_span_mm=@($paSpan);$resolvedProjection.local_exit_z_mm=[double]$p.numerical_domain.local_exit_z_mm;$projectionPath=Join-Path $inputs 'resolved_projection.json';$resolvedProjection|ConvertTo-Json -Depth 12|Set-Content $projectionPath -Encoding utf8;$originX=[double]$p.numerical_domain.iob_origin_mm[0];$originY=[double]$p.numerical_domain.iob_origin_mm[1]+[double]$c.operating_point.instance_center_y_mm;$originZ=[double]$p.numerical_domain.iob_origin_mm[2];$focusPython=Initialize-FocusFrozenPython -RepoRoot $repoRoot -RunConfig $package.run_config -Python $python -CampaignPath $runCampaign;$release=Join-Path $inputs 'release.csv';$releaseReceipt=Join-Path $inputs 'release_receipt.json';Invoke-FocusFrozenPython -Python $python -CodeRoot $focusPython.code_root -OriginsPath $focusPython.origins_path -Module msplatform.ion_release.cylinder -Arguments @('--materialize',$releaseSpec,'--state-table',$release,'--receipt',$releaseReceipt);if($LASTEXITCODE-ne0){throw 'Common ion release failed'}
 $fly=Join-Path $solver 'component_focus_input.fly2';$sourceStates=Join-Path $solver 'component_focus.source_states.lua';$sourceReceipt=Join-Path $results 'source_projection.json';Invoke-FocusFrozenPython -Python $python -CodeRoot $focusPython.code_root -OriginsPath $focusPython.origins_path -Module projects.orthogonal_accelerator.analysis.component_focus_simion_source -Arguments @('--release-receipt',$releaseReceipt,'--campaign',$runCampaign,'--provider-plan',(Join-Path $inputs 'component_focus_pa_plan.json'),'--resolved-projection',$projectionPath,'--fly2',$fly,'--source-states',$sourceStates,'--receipt',$sourceReceipt);if($LASTEXITCODE-ne0){throw 'SIMION source projection failed'}
 $frozenConfig=Get-Content -LiteralPath $package.run_config -Raw -Encoding utf8|ConvertFrom-Json -AsHashtable;$frozenConfig.inputs['release.csv']=Join-Path (Split-Path -Parent $package.run_config) 'inputs/release.csv';$frozenConfig|ConvertTo-Json -Depth 100|Set-Content -LiteralPath $package.run_config -Encoding utf8
 $testPlaneLibrary=Join-Path (Split-Path -Parent $SimionExe) 'examples\test_plane\testplanelib.lua';if(-not(Test-Path -LiteralPath $testPlaneLibrary -PathType Leaf)){throw 'SIMION official test_plane library is required'};Copy-VerifiedRunInput $testPlaneLibrary (Join-Path $solver 'testplanelib.lua')|Out-Null
 $op=Join-Path $solver 'component_focus.operating_point.lua';$volts=($c.operating_point.electrode_voltages_v|ForEach-Object{[string]$_}) -join ',';@("return { voltages={ $volts }, field_mode='$FieldMode', trajectory_quality=$($c.numerics.trajectory_quality), maximum_step_us=$($c.numerics.maximum_step_us), particle_count=$($c.release_spec.particle_count), focus_plane_tolerance_mm=$($c.acceptance.focus_plane_tolerance_mm), local_exit_z_mm=$($p.numerical_domain.local_exit_z_mm), focus_plane_offset_from_exit_mm=$($c.operating_point.focus_plane_offset_from_exit_mm), focus_plane_local_z_mm=$($p.numerical_domain.focus_plane_local_z_mm), grid1_local_z_mm=$($p.layout.local_exit_z_mm + $p.layout.gap_2_mm), repeller_local_z_mm=$($p.layout.local_repeller_z_mm) }")|Set-Content $op -Encoding ascii
 $seed=Join-Path $repoRoot 'src\msplatform\backends\simion\resources\1_instance_seed.iob';$iob=Join-Path $solver 'component_focus.iob';&$SimionExe --nogui --noprompt lua (Join-Path $solver 'build_component_focus_iob.lua') -- $seed $controller $iob (Join-Path $solver 'component_focus.lua') $fly $originX $originY $originZ 2>&1|Tee-Object (Join-Path $logs 'iob_build.log');if($LASTEXITCODE-ne0){throw 'IOB build failed'}
 Push-Location $solver;try{&$SimionExe --nogui --noprompt fly --trajectory-quality $($c.numerics.trajectory_quality) --particles $fly --programs 1 --retain-trajectories 0 $iob 2>&1|Tee-Object (Join-Path $logs 'focus.log');if($LASTEXITCODE-ne0){throw 'SIMION flight failed'}}finally{Pop-Location}
 $events=Join-Path $solver 'component_focus.events.csv';if(-not(Test-Path -LiteralPath $events) -or (Get-Item -LiteralPath $events).Length -le 0){throw 'SIMION did not produce component-focus event CSV'}
 $analysis=Join-Path $results 'focus_analysis.json';Invoke-FocusFrozenPython -Python $python -CodeRoot $focusPython.code_root -OriginsPath $focusPython.origins_path -Module projects.orthogonal_accelerator.analysis.component_focus_analysis -Arguments @('--events',$events,'--release-receipt',$releaseReceipt,'--campaign',$runCampaign,'--output',$analysis);$analysisExit=$LASTEXITCODE;if($analysisExit-ne0-and-not(Test-Path -LiteralPath $analysis)){throw 'Component focus analysis did not produce evidence'};$analysisResult=Get-Content -Raw $analysis|ConvertFrom-Json;if($analysisResult.status-notin@('candidate_complete','candidate_incomplete')){throw 'Component focus analysis status is invalid'}
 $summary=Join-Path $run 'summary.json';@{schema_version=1;role='orthogonal_accelerator_component_focus';status=[string]$analysisResult.status;qualification='candidate_prototype_numeric_component_focus_only';cache_key=$result.cache_key;generation_sha256=$result.generation_sha256;pa_build_run_manifest_sha256=(Get-FileHash (Join-Path $family 'run_manifest.json') -Algorithm SHA256).Hash;cache_manifest_sha256=(Get-FileHash (Join-Path $generation 'cache_manifest.json') -Algorithm SHA256).Hash;runtime_controller_path=$controller;runtime_controller_bytes=(Get-Item -LiteralPath $controller).Length;pa_cache_policy='published_standalone_responses__shared_private_native_fast_adjust_family'}|ConvertTo-Json|Set-Content $summary -Encoding utf8;$retention=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config;Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Status success -Software @('SIMION 2020','Python 3.11') -Outputs @($summary,$retention,$analysis,$focusPython.origins_path,$sourceReceipt,$releaseReceipt,$fly,$sourceStates,$iob,$events,(Join-Path $logs 'focus.log'),(Join-Path $solver 'component_focus.lua'),(Join-Path $solver 'component_focus.scientific_event_csv.lua'),(Join-Path $solver 'component_focus.operating_point.lua'),(Join-Path $solver 'testplanelib.lua'));$done=$true
}catch{$failureDetail=$_.Exception.Message;throw
}finally{if(-not$done){$reason='Focus runner failed.';if(-not[string]::IsNullOrWhiteSpace($failureDetail)){$reason+=" $failureDetail"};Complete-FailedRun -Python $python -RepoRoot $repoRoot -RunConfig $package.run_config -Summary $package.summary -SummaryRole orthogonal_accelerator_component_focus -Reason $reason -Software @('SIMION 2020','Python 3.11') -Status failed};if($lease){Exit-HostExecutionLease -Lease $lease -Outcome $(if($done){'success'}else{'failed'}) -RunId $RunId};Remove-RunPackageExecutionAlias -Package $package;$env:PYTHONPATH=$previousPythonPath}
