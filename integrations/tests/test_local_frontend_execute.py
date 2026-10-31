"""Pure PowerShell orchestration contracts; no commercial process is launched."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
INTEGRATION = REPO / "integrations"
EXECUTE = REPO / 'integrations/workflows/local_frontend/execute.ps1'




@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell 7 unavailable')
class LocalFrontendExecuteTests(unittest.TestCase):
    def ps(self, text, *arguments):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'test.ps1'
            script.write_text(text, encoding='utf-8', newline='\n')
            return subprocess.run(['pwsh', '-NoProfile', '-File', str(script), *map(str, arguments)],
                                  cwd=REPO, capture_output=True, text=True, encoding='utf-8', check=False, timeout=60)

    def test_parse_and_mode_guards_precede_any_native_or_owner_creation(self):
        script = """param([string]$Source,[string]$Repo,[string]$Python)
$e=$null;$t=$null;[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)|Out-Null
if($e.Count){throw ($e|Out-String)}
foreach($mode in @('none','two','budget','directory')){
 $args=@{Request='missing-scientific-request.json';RepoRoot=$Repo;Python=$Python}
 switch($mode){two{$args.ValidateOnly=$true;$args.PrepareOnly=$true};budget{$args.SolverAuthorized=$true};directory{$args.PrepareOnly=$true}}
 try{&$Source @args;throw 'invalid mode accepted'}catch{if($_.Exception.Message-notmatch'Select exactly one|requires ExecutionBudgetPath|requires a caller-owned'){throw}}
}
'MODE_GUARDS=PASS'
"""
        result = self.ps(script, EXECUTE, REPO, sys.executable)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('MODE_GUARDS=PASS', result.stdout)

    def test_capacity_protection_selects_only_artifact_inputs_for_repository_authors(self):
        script = """param($Source,$Repo)
$e=$null;$t=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
if($e.Count){throw ($e|Out-String)}
$workspace=Split-Path -Parent $Repo;$artifacts=Join-Path $workspace 'artifacts'
$Request=Join-Path $Repo 'integrations/config/experiments/science.json'
$ExecutionBudgetPath=Join-Path $Repo 'integrations/config/experiments/budget.json'
$author=[pscustomobject]@{composition_plan=@{path='../recipes/parent.json'};source=[pscustomobject]@{manifest=@{path='artifacts/projects/ip/run_manifest.json'};release=@{path='artifacts/projects/ip/inputs/release.csv'}}}
foreach($name in @('$artifactPrefix','$protected')){
 $node=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq$name},$true))
 if($node.Count-ne1){throw 'protection selection missing'}
 Invoke-Expression $node[0].Extent.Text
}
if($protected.Count-ne2-or$protected-contains$Request-or$protected-contains$ExecutionBudgetPath){throw 'capacity protected non-artifact author inputs'}
foreach($path in $protected){if(-not$path.StartsWith($artifactPrefix)){throw 'missing artifact source protection'}}
'CAPACITY_PROTECTION=PASS'
"""
        result = self.ps(script, EXECUTE, REPO)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('CAPACITY_PROTECTION=PASS', result.stdout)

    def test_actual_compiler_warnings_are_visible_and_remain_nonfatal(self):
        script = """param([string]$Source)
$e=$null;$t=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
if($e.Count){throw ($e|Out-String)}
$nodes=@($ast.FindAll({param($n) $n-is[Management.Automation.Language.ForEachStatementAst]-and$n.Condition.Extent.Text-like'*accelerator_port_aperture_discretization.grid_alignment.warnings*'},$true))
if($nodes.Count-ne1){throw 'actual bound warning emission missing'}
$emit=[scriptblock]::Create($nodes[0].Extent.Text)
foreach($codes in @(@(),@('aperture_width_not_integer_cell_multiple','aperture_x_edges_not_on_grid_nodes'))){
 $frontend=[pscustomobject]@{accelerator_local_region=[pscustomobject]@{accelerator_port_aperture_discretization=[pscustomobject]@{grid_alignment=[pscustomobject]@{warnings=$codes}}}}
 $messages=@(& $emit 3>&1)
 if($messages.Count-ne$codes.Count){throw 'warning count differs from frozen compiler metadata'}
 foreach($code in $codes){if(-not@($messages|Where-Object {$_.ToString()-like"*$code"}).Count){throw 'warning silently dropped'}}
}
'APERTURE_WARNINGS=PASS'
"""
        result = self.ps(script, EXECUTE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('APERTURE_WARNINGS=PASS', result.stdout)

    def test_disk_forecast_uses_actual_five_or_six_mode_model(self):
        script = """param([string]$Source,[string]$Python)
$e=$null;$t=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
if($e.Count){throw ($e|Out-String)}
$nodes=@($ast.FindAll({param($n) $n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$forecast'},$true))
if($nodes.Count-ne1){throw 'actual disk forecast assignment missing'}
Invoke-Expression $nodes[0].Extent.Text
$root=Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory (Join-Path $root 'inputs'),(Join-Path $root 'results') -Force|Out-Null
try{
 @{maximum_flight_us=2;trajectory_sample_interval_us=.5}|ConvertTo-Json|Set-Content (Join-Path $root 'inputs/numerics.json')
 foreach($case in @(@{modes=5;arrays=12;cold=3840;hit=1536},@{modes=6;arrays=14;cold=4416;hit=1728})){
  @{dimensions=@{nx=2;ny=3;nz=4};pa_plus_solution_model=@{mode_count=$case.modes}}|ConvertTo-Json|Set-Content (Join-Path $root 'inputs/frontend_contract.json')
  &$Python -B -c $forecast $root 123456 100
  if($LASTEXITCODE-ne0){throw 'actual forecast Python failed'}
  $value=Get-Content (Join-Path $root 'results/physical_disk_forecast.json') -Raw|ConvertFrom-Json
  if($value.cache_array_count-ne$case.arrays-or$value.new_working_point_array_count-ne3-or$value.temporary_response_copy_count-ne$case.modes-or$value.cold_cache_node_payload_floor_bytes-ne$case.cold-or$value.cache_hit_new_node_payload_floor_bytes-ne$case.hit){throw 'model-derived array forecast differs'}
  if($value.source_count-ne100-or$value.maximum_particle_age_us-ne2-or$value.trajectory_rows_per_phase_ceiling_before_additional_events-ne500-or$value.author_workflow_commitment_bytes-ne123456){throw 'source/time/commitment forecast changed'}
 }
 'DISK_FORECAST=PASS'
}finally{Remove-Item -LiteralPath $root -Recurse -Force}
"""
        result = self.ps(script, EXECUTE, sys.executable)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('DISK_FORECAST=PASS', result.stdout)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows file-share semantics')
    def test_actual_working_field_guards_follow_writer_completion_facts(self):
        script = """param([string]$Source,[string]$GuardSupport)
. $GuardSupport
$e=$null;$t=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
if($e.Count){throw ($e|Out-String)}
$acquire=$ast.FindAll({param($n)$n-is[Management.Automation.Language.ForEachStatementAst]-and$n.Condition.Extent.Text-eq'$fieldReceipt.working_points'},$true)
if(@($acquire).Count-ne1){throw 'working-field acquisition missing'}
$outer=$ast.FindAll({param($n)$n-is[Management.Automation.Language.TryStatementAst]-and$null-ne$n.Finally-and$n.Finally.Extent.Text-like'*$workingFieldGuards.Clear()*'},$true)
if(@($outer).Count-ne1){throw 'working-field terminal cleanup missing'}
$normal=[scriptblock]::Create(($outer[0].Finally.Statements.Extent.Text-join"`n"))
function Remove-RunPackageExecutionAlias {param($Package)}
function Restore-RunEnvironment {param($Names,$Snapshot)}
$root=Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $root|Out-Null
try{
 $records=@(foreach($name in @('carrier','rf','pulse')){
  $path=Join-Path $root ($name+'.pa');[IO.File]::WriteAllText($path,$name)
  [pscustomobject]@{path=$path;bytes=(Get-Item $path).Length;sha256=(Get-FileHash $path -Algorithm SHA256).Hash}
 })
 function Assert-Guarded {
  foreach($path in $workingFieldGuards){
   $opened=$null
   try{$opened=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite)}catch [IO.IOException]{}
   if($null-ne$opened){$opened.Dispose();throw 'working field writable before child exit'}
  }
 }
 foreach($scenario in @('complete','partial_acquire','writer_unknown')){
  $workingFieldGuards=[Collections.Generic.List[string]]::new()
  $fieldReceipt=@{working_points=$records|ForEach-Object{[pscustomobject]@{path=$_.path;bytes=$_.bytes;sha256=$_.sha256}}}
  if($scenario-eq'partial_acquire'){$fieldReceipt.working_points[2].sha256='0'*64}
  $package=@{native_path_preparation=@{calls=0;elapsed_seconds=0.;transport_bytes=0};run_dir=$root}
  $lease=$null;$capacity=$null;$ownerContext=$null;$writerUnknown=$false;$hostReleaseUnknown=$false;$oldEnvironment=@{}
  $nativeOperations=[Collections.Generic.List[object]]::new()
  if($scenario-eq'writer_unknown'){$nativeOperations.Add(@{observation=@{exit_confirmed=$false}})}
  $caught=$null
  try{Invoke-Expression $acquire[0].Extent.Text}catch{$caught=$_}
  $expectedCount=if($scenario-eq'partial_acquire'){2}else{3}
  if($workingFieldGuards.Count-ne$expectedCount-or($null-ne$caught)-ne($scenario-eq'partial_acquire')){throw 'partial guard acquisition differs'}
  $failure=$caught
  Assert-Guarded
  . $normal
  if($scenario-eq'writer_unknown'){
   if($workingFieldGuards.Count-ne3){throw 'unknown writer lost PA guards'}
   Assert-Guarded
   foreach($path in @($workingFieldGuards)){$null=Unprotect-ImmutablePaSource -Source $path}
   $workingFieldGuards.Clear()
  }
  if($global:MassSpectrometryImmutablePaSourceGuards.Count){throw 'working-field handle leaked'}
  foreach($record in $records){$handle=[IO.File]::Open($record.path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite);$handle.Dispose()}
 }
 'WORKING_FIELD_GUARDS=PASS'
}finally{
 foreach($path in @($global:MassSpectrometryImmutablePaSourceGuards.Keys)){$null=Unprotect-ImmutablePaSource -Source $path}
 Remove-Item -LiteralPath $root -Recurse -Force
}
"""
        result = self.ps(script, EXECUTE, REPO / 'common/simion/short_pa_path_support.ps1')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('WORKING_FIELD_GUARDS=PASS', result.stdout)


    def test_active_formal_is_replanned_and_drained_on_preparation_failure(self):
        script = """param([string]$Source)
. $Source
$repo=Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $Source))
$helperAst=[Management.Automation.Language.Parser]::ParseFile((Join-Path $repo 'common/resource_budget_support.ps1'),[ref]$null,[ref]$null)
foreach($name in @('Invoke-ObservedPreparationFailureDrain','Invoke-SimionFormalObservation','Invoke-SimionBatchPhase')){
 $helper=$helperAst.Find({param($node) $node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq$name},$true)
 Invoke-Expression $helper.Extent.Text
}
$root=Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'));New-Item -ItemType Directory (Join-Path $root 'results') -Force|Out-Null
$script:worker=$null
try{
 $script:run=$root;$projectArtifacts=$root;$workflowModule='fixture';$runId='fixture';$simion='not-started.exe'
 foreach($scenario in @('active','complete','replan_failure','materialize_failure','build_failure')){
 $script:events=[Collections.Generic.List[string]]::new();$script:materializeCount=0;$script:scenario=$scenario
 $ready=Join-Path $root worker_started;$release=Join-Path $root worker_release
 Remove-Item -LiteralPath $ready,$release -ErrorAction SilentlyContinue
 function MakeCase($index,$ids){return [pscustomobject]@{index=$index;case_id="case_$index";count=$ids.Count;expected_particle_ids=$ids;simion_particle_id_offset=0;merge_offset=0;iob_path=(Join-Path $root "fixture.iob");working_directory=$root;environment=@{OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET='0'};stdout='fixture.log';stderr='fixture.err';fly_arguments=@('fly','fixture.iob')}}
 $script:first=MakeCase 1 @(1);$script:tail=MakeCase 2 @(2,3);$script:gui=MakeCase 99 @(1,2,3)
 $script:first|Add-Member -NotePropertyName iob_verify_arguments -NotePropertyValue @('verify')
 $script:first|Add-Member -NotePropertyName receipt_path -NotePropertyValue 'case_1.json'
 function Invoke-FrontendRuntimePython {
  param([string[]]$Arguments,[switch]$Json,$Python,$RepoRoot,$RunDirectory,$Name)
  if($Arguments-contains'prepare-dispatch'){return @{dispatch_request_path='request.json'}}
  if($Arguments-contains'common.simion.resource_scheduler'){
   $adaptive=$Arguments-contains'--observed-formal-peak-bytes'
   if($adaptive){
    if(($Arguments-contains'--first-batch-completed')-ne($scenario-eq'complete')){throw 'active first batch falsely marked complete'}
    if($scenario-eq'replan_failure'){throw 'planned preparation failure'}
   }
   $script:events.Add($(if($adaptive){'adaptive'}else{'plan'}))
   @{estimation=@{kind='formal_first_batch_observation'}}|ConvertTo-Json|Set-Content (Join-Path $root 'results/discovery.dispatch_plan.json');return
  }
  if($Arguments-contains'materialize-batches'){
   $script:materializeCount++
   if($script:materializeCount-eq1){return @{batches=@($script:first)}}
   if($scenario-eq'materialize_failure'){throw 'planned preparation failure'}
   return @{coverage='complete_population';pending_particle_ids=@();batches=@($script:first,$script:tail);gui_case=$script:gui}
  }
  if($Arguments-contains'--verify-controls'){
   if(-not$script:worker.HasExited-or-not$script:firstRecord.completed){throw 'controls checked before worker termination'}
   $script:events.Add('controls_after');return @{}
  }
 }
 function Invoke-FrontendIobBuild {
  param($Case,[string]$Phase,$RunDirectory,$SimionExe,$Limits,$Python,$RepoRoot)
  if($scenario-eq'build_failure'-and$Case.case_id-eq'case_2'){throw 'planned preparation failure'}
  $script:events.Add('build_'+$Case.case_id)
 }
 function Start-ObservedFormalProcess {
  param($DispatchPlanPath,$ProcessSpecification,[switch]$WaitForNaturalCompletionAfterObservation)
  if($WaitForNaturalCompletionAfterObservation){throw 'formal observation unnecessarily waits for natural completion'}
  $script:events.Add('formal_'+$ProcessSpecification.name)
  $childCode="[IO.File]::WriteAllText('$ready','ready');while(-not[IO.File]::Exists('$release')){Start-Sleep -Milliseconds 10}"
  $info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=(Get-Process -Id $PID).Path;$info.UseShellExecute=$false;$info.CreateNoWindow=$true
  foreach($arg in @('-NoProfile','-EncodedCommand',[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($childCode)))){$info.ArgumentList.Add($arg)}
  $script:worker=[Diagnostics.Process]::Start($info)
  $timer=[Diagnostics.Stopwatch]::StartNew()
  while(-not(Test-Path -LiteralPath $ready)){if($timer.Elapsed.TotalSeconds-gt10){throw 'test worker did not start'};Start-Sleep -Milliseconds 10}
  $completed=$scenario-eq'complete'
  if($completed){[IO.File]::WriteAllText($release,'release');if(-not$script:worker.WaitForExit(10000)){throw 'test worker did not exit'}}
  $script:firstRecord=@{name=$ProcessSpecification.name;completed=$completed;process=$script:worker;exit_code=$(if($completed){0}else{$null})}
  return @{process_record=$script:firstRecord;resource_budget_exceeded=$false;completed_naturally=$completed;exit_code=$(if($completed){0}else{$null});observed_peak_process_tree_working_set_bytes=100;observed_process_cpu_percent=1;observed_background_cpu_percent=0;available_memory_bytes=1000;total_physical_memory_bytes=2000}
 }
 function Invoke-ResourceBudgetedProcesses {
  param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords)
  if(@($ExistingProcessRecords).Count-ne1-or-not[object]::ReferenceEquals($ExistingProcessRecords[0],$script:firstRecord)){throw 'active worker record was replaced'}
  $failure=$scenario-like'*_failure'
  if(@($ProcessSpecifications).Count-ne$(if($failure){0}else{1})){throw 'preparation failure launched a sibling'}
  if(-not$script:firstRecord.completed){
   if($script:worker.HasExited){throw 'active-first test did not exercise a running process'}
   [IO.File]::WriteAllText($release,'release');if(-not$script:worker.WaitForExit(10000)){throw 'public drain did not finish test worker'}
   $script:firstRecord.completed=$true;$script:firstRecord.exit_code=$script:worker.ExitCode
  }
  if($failure){$script:events.Add('drain_case_1')}else{
   if($ProcessSpecifications[0].name-ne'case_2'){throw 'formal result was replayed or GUI scheduled'}
   $script:events.Add('tail_case_2')
  }
  return @{resource_budget_exceeded=$false;processes=@(@{name='case_1';exit_code=0},@{name='case_2';exit_code=0})}
 }
 function Complete-ResourceUsage {param($RunDir,$UsagePath)}
 $caught=$null
 $verification={param($Operation,$Case,$BuildResult,$Phase,$RunDirectory,$SimionExe,$Limits,$Python,$RepoRoot)
  if($Operation-eq'after_first_fly'){
   if(-not$script:worker.HasExited-or-not$script:firstRecord.completed){throw 'controls checked before worker termination'}
   $script:events.Add('controls_after')
  }
 }

function Get-RunNativeExecutionContext {param($Package,$Paths,$Tool) @{run_dir=$Root;projected_paths=@($Paths);environment=@{}}}
function Project-RunPath {param($Paths,$ArtifactRunDir,$RunDir,$Python) return $Paths}
 try{$result=Invoke-FrontendFlightPhase -Package ([pscustomobject]@{artifact_run_dir=$Root;python="unused"}) -RunDirectory $root -ProjectRunsRoot $root -RepoRoot $root -Python fixture -RuntimeModule fixture -SimionExe $simion -Limits @{} -Phase discovery -PulseTimeUs 12 -SharedTimesPath 'times.json' -IobVerification $verification}catch{$caught=$_}
 if($scenario-like'*_failure'){
  if($null-eq$caught-or$caught.Exception.Message-ne'planned preparation failure'){throw "original preparation failure lost: $caught"}
  if(($script:events-join',')-notlike'*,drain_case_1,controls_after'){throw ($script:events-join',')}
 }else{
  if($caught){throw $caught}
  if(($script:events-join',')-ne'plan,build_case_1,formal_case_1,adaptive,build_case_2,build_case_99,tail_case_2,controls_after'){throw ($script:events-join',')}
  if($result.batches.Count-ne2){throw 'full source materialization lost'}
 }
 if(-not$script:worker.HasExited){throw 'orphaned first worker'}
 $script:worker.Dispose()
 $script:worker=$null
 }
 'FORMAL_TAIL_GUI=PASS'
}finally{
 if($null-ne$script:worker-and-not$script:worker.HasExited){[IO.File]::WriteAllText($release,'release');$script:worker.WaitForExit(10000)|Out-Null}
 Remove-Item -LiteralPath $root -Recurse -Force
}
"""
        result = self.ps(script, INTEGRATION / "runtime/frontend_flight_support.ps1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('FORMAL_TAIL_GUI=PASS', result.stdout)

    def test_default_replay_uses_fresh_process_without_flight_overrides_and_rejects_difference(self):
        script = """param([string]$Source)
$e=$null;$t=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
if($e.Count){throw ($e|Out-String)}
$node=$ast.FindAll({param($a)$a-is[Management.Automation.Language.FunctionDefinitionAst]-and$a.Name-eq'Invoke-FrontendDefaultReplay'},$true)[0]
Invoke-Expression $node.Extent.Text
$root=Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'));New-Item -ItemType Directory (Join-Path $root 'inputs') -Force|Out-Null
try{
 $script:run=$root;$budget=@{limits=@{}};$simion='NOT_NATIVE';$script:calls=0;$script:pass=$true
 function Write-RunJson {param($Path,$Value,$Depth)$Value|ConvertTo-Json -Depth 100|Set-Content $Path}
 function Get-HostResourceBudget {param($Role,$Stage)return @{}}
 function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes)return @{stage=$Stage}}
 function Invoke-FrontendRuntimePython {
  param($Python,$RepoRoot,$RunDirectory,$Name,[string[]]$Arguments,[switch]$Json)
  if(($Arguments-join' ')-match'prepare_default_replay'){
   return @{argument_list=@('--nogui','--noprompt','fly','local.iob');working_directory=$root;environment=@{OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET='0'};usage_path='usage.json';stdout='separate_default.stdout.log';stderr='separate_default.stderr.log'}
  }
  if(($Arguments-join' ')-match'compare_default_replay'){return @{passed=$script:pass;mother_count=100}}
  throw 'unexpected Python action'
 }
 function Invoke-ResourceBudgetedProcess {
  param($Limits,$RunDir,$FilePath,$ArgumentList,$WorkingDirectory,$Environment,$UsagePath,$RedirectStandardOutput,$RedirectStandardError)
  if(($ArgumentList-join',')-ne'--nogui,--noprompt,fly,local.iob'){throw 'saved defaults overridden'}
  if($WorkingDirectory-ne$root-or$RedirectStandardOutput-ne'separate_default.stdout.log'){throw 'source batch output reused'}
  if($Environment.OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET-ne'0'){throw 'nonneutral ID offset'}
  $script:calls++;return @{resource_budget_exceeded=$false;exit_code=0}
 }
 $materialized=@{gui_case=@{expected_particle_ids=1..100};batches=@(@{stdout='original_batch.stdout.log'});default_replay_policy=@{comparison_policy='deterministic_trajectory_parity';scope='fresh_process';collision_active=$false}};$lease=@{}

function Get-RunNativeExecutionContext {param($Package,$Paths,$Tool) @{run_dir=$Root;projected_paths=@($Paths);environment=@{}}}
function Project-RunPath {param($Paths,$ArtifactRunDir,$RunDir,$Python) return $Paths}
 $result=Invoke-FrontendDefaultReplay -Package ([pscustomobject]@{artifact_run_dir=$Root;python="unused"}) -Materialized $materialized -HostLease ([ref]$lease) -RunDirectory $root -RepoRoot $root -Python unused -SimionExe $simion -Limits @{}
 if(-not$result.passed-or$script:calls-ne1-or$lease.stage-ne'postprocess'){throw 'fresh process or public stage transition missing'}
 $script:pass=$false
 try{Invoke-FrontendDefaultReplay -Package ([pscustomobject]@{artifact_run_dir=$Root;python="unused"}) -Materialized $materialized -HostLease ([ref]$lease) -RunDirectory $root -RepoRoot $root -Python unused -SimionExe $simion -Limits @{};throw 'mismatch accepted'}catch{if($_.Exception.Message-notlike'*differs from scheduled mother evidence*'){throw}}
 'DEFAULT_REPLAY=PASS'
}finally{Remove-Item -LiteralPath $root -Recurse -Force}
"""
        result = self.ps(script, INTEGRATION / "runtime/frontend_flight_support.ps1")
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('DEFAULT_REPLAY=PASS', result.stdout)

    def test_actual_decision_is_frozen_and_transported_to_extraction_analysis_and_saved_gui(self):
        script = """param([string]$Source,[string]$Python,[string]$Run,[string]$ExpectedStatus)
$ErrorActionPreference='Stop'
$e=$null;$t=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
if($e.Count){throw ($e|Out-String)}
$start=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$selected'},$true))
if($start.Count-ne1){throw 'actual recommendation read missing'}
$statements=@();$collect=$false
foreach($statement in $start[0].Parent.Statements){
 if($statement.Extent.StartOffset-eq$start[0].Extent.StartOffset){$collect=$true}
 if($collect){$statements+=$statement.Extent.Text}
 if($collect-and$statement-is[Management.Automation.Language.AssignmentStatementAst]-and$statement.Left.Extent.Text-eq'$scientificSummary'){break}
}
$block=[scriptblock]::Create(($statements-join"`n"))
$script:run=$Run;$package=@{native_path_preparation=@{calls=0;elapsed_seconds=0.;transport_bytes=0};input_dir=Join-Path $Run 'inputs';result_dir=Join-Path $Run 'results';summary=Join-Path $Run 'summary.json'}
$script:pythonRoot='SYNTHETIC_FROZEN_ROOT';$simion='SYNTHETIC_NO_NATIVE.exe';$budget=@{limits=@{fixture=$true}}
$nativeOperations=[Collections.Generic.List[object]]::new();$lease=@{token='TEST_ONLY_PARENT'};$source=@{particle_count=100};$discoveryResult=@{fixture=$true};$script:calls=@();$script:summary=$null
function Invoke-LocalWorkflowPython {
 param([string[]]$Arguments,[switch]$Json)
 $out=&$Python -B @Arguments
 if($LASTEXITCODE-ne0){throw 'actual decision/schedule Python failed'}
 return ($out|ConvertFrom-Json)
}
function Get-HostResourceBudget {param($Role,$Stage)return @{}}
function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes)return @{token='TEST_ONLY_PARENT'}}
function Set-LocalStage {param($Name)}
function Invoke-LocalFlightPhase {
 param($Phase,[double]$PulseTime,$SharedTimesPath)
 $decision=Get-Content (Join-Path $Run 'inputs/pulse_decision.json') -Raw|ConvertFrom-Json
 $times=Get-Content $SharedTimesPath -Raw|ConvertFrom-Json
 if($Phase-ne'extraction'-or$PulseTime-ne$decision.actual_pulse_time_us-or$times-notcontains$PulseTime){throw 'flight did not consume derived actual pulse'}
 $script:calls+='flight'
 return @{actual_pulse_time_us=$PulseTime;gui_case=@{expected_particle_ids=1..100};default_load_iob='SYNTHETIC_NO_FLY.iob'}
}
function Invoke-LocalRecordedAnalysis {
 param($Materialized,$Phase,$Times,[double]$PulseTime)
 if($Phase-ne'extraction'-or$PulseTime-ne$Materialized.actual_pulse_time_us){throw 'analysis pulse differs from flight'}
 $script:calls+='analysis';return @{actual_pulse_time_us=$PulseTime}
}
function Invoke-FrontendDefaultReplay {
 param($Package,$Materialized,$HostLease,$RunDirectory,$RepoRoot,$Python,$SimionExe,$Limits,$NativeOperations,$NativeResourceReleaseId)
 if($RunDirectory-ne$Run-or$RepoRoot-ne$script:pythonRoot-or$SimionExe-ne$simion-or-not$Limits.fixture){throw 'shared replay did not receive the explicit run context'}
 if(-not[object]::ReferenceEquals($NativeOperations,$script:nativeOperations)-or$NativeResourceReleaseId-ne'TEST_ONLY_PARENT'){throw 'replay fact binding changed'}
 if($Materialized.gui_case.expected_particle_ids.Count-ne100){throw 'full GUI population changed'}
 $script:calls+='replay';return @{passed=$true;actual_pulse_time_us=$Materialized.actual_pulse_time_us}
}
function Write-RunJson {param($Path,$Depth,$Value)$script:summary=$Value}
$caught=$null
try{. $block;$script:summary=$scientificSummary}catch{$caught=$_}
$decision=Get-Content (Join-Path $Run 'inputs/pulse_decision.json') -Raw|ConvertFrom-Json
if($decision.status-ne$ExpectedStatus){throw 'decision status changed'}
if($ExpectedStatus-eq'ready'){
 if($caught){throw $caught}
 if(($script:calls-join',')-ne'flight,analysis,replay'){throw 'wrong extraction pipeline'}
 if($script:summary.actual_pulse_time_us-ne$decision.actual_pulse_time_us-or$script:summary.recommended_pulse_time_us-ne$decision.recommendation_time_us){throw 'summary confuses recommended and applied times'}
 if($script:summary.default_replay.actual_pulse_time_us-ne$decision.actual_pulse_time_us){throw 'GUI replay differs from applied pulse'}
}else{
 if($null-eq$caught-or$caught.Exception.Message-notlike'*no replacement time selected*'-or$script:calls.Count){throw 'missing evidence did not stop before extraction'}
}
'APPLIED_PULSE_PIPELINE=PASS'
"""
        with tempfile.TemporaryDirectory() as directory:
            for policy, missing in (("detector_blind_actual_occupancy_v1", False),
                                    ("detector_blind_actual_occupancy_rf_delay_v1", False),
                                    ("detector_blind_actual_occupancy_rf_delay_v1", True)):
                with self.subTest(policy=policy, missing=missing):
                    run = Path(directory) / (policy + str(missing))
                    inputs, results = run / "inputs", run / "results/local_frontend/discovery"
                    inputs.mkdir(parents=True)
                    results.mkdir(parents=True)
                    recommended, period = 27.793500142888146, 1e6 / 3.7e6
                    actual = recommended if policy.endswith("occupancy_v1") else recommended + 25 * period
                    plan = dict(policy_id=policy, rf_period_us=period, source_birth_time_range_us=[0., 0.],
                                predicted_guide_exit_time_range_us=[10., 20.], predicted_arrival_min_us=20.,
                                predicted_arrival_max_us=40., candidate_start_us=18., candidate_stop_us=42.,
                                predicted_nominal_extraction_duration_us=2.)
                    if not policy.endswith("occupancy_v1"):
                        plan["delay_rf_periods"] = 25
                    for name, value in {"pulse_plan": plan, "numerics": dict(maximum_flight_us=200.),
                                        "frontend_contract": {}, "guide_contract": {}}.items():
                        (inputs / (name + ".json")).write_text(json.dumps(value))
                    candidate = dict(candidate_time_us=actual, pulse_eligible_count=2, eligible_ids=[3, 99], unsupported_ids=[])
                    recommendation = dict(status="selected", selected_time_us=recommended,
                                          selection_uses_future_terminal_outcome=False, candidates=[] if missing else [candidate])
                    (results / "pulse_selection.json").write_text(json.dumps(recommendation))
                    result = self.ps(script, EXECUTE, sys.executable, run, "target_snapshot_missing" if missing else "ready")
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("APPLIED_PULSE_PIPELINE=PASS", result.stdout)
                    decision = json.loads((inputs / "pulse_decision.json").read_text())
                    self.assertEqual(decision["actual_pulse_time_us"].hex(), actual.hex())
                    self.assertEqual(set(decision["input_records"]), {"recommendation", "pulse_plan", "numerics"})


if __name__ == '__main__':
    unittest.main()
