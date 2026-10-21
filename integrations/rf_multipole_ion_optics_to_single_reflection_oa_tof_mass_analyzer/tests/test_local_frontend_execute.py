"""Pure PowerShell orchestration contracts; no commercial process is launched."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
INTEGRATION = Path(__file__).resolve().parents[1]
EXECUTE = INTEGRATION / 'workflows/local_frontend/execute.ps1'
SUPPORT = INTEGRATION / 'runtime/run_artifacts.ps1'


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
    def test_actual_working_field_guards_hold_until_children_stop_and_release_on_failure(self):
        script = """param([string]$Source,[string]$GuardSupport)
. $GuardSupport
$e=$null;$t=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
if($e.Count){throw ($e|Out-String)}
$acquire=$ast.FindAll({param($n)$n-is[Management.Automation.Language.ForEachStatementAst]-and$n.Condition.Extent.Text-eq'$fieldReceipt.working_points'},$true)
if(@($acquire).Count-ne1){throw 'working-field acquisition missing'}
$outer=$ast.FindAll({param($n)$n-is[Management.Automation.Language.TryStatementAst]-and$null-ne$n.Finally-and$n.Finally.Extent.Text-like'*$workingFieldGuards.Clear()*'},$true)
if(@($outer).Count-ne1){throw 'working-field terminal cleanup missing'}
$cleanup=$outer[0].Finally.Statements[0]
$prefix=@(foreach($statement in $cleanup.Body.Statements){
 if($statement-is[Management.Automation.Language.IfStatementAst]-and$statement.Clauses[0].Item1.Extent.Text-eq'$lease'){break}
 $statement.Extent.Text
})
$normal=[scriptblock]::Create(($prefix-join"`n"))
$fallback=[scriptblock]::Create($cleanup.Finally.Statements[0].Extent.Text)
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
 function Get-ManagedSolverProcessSample {
  param($RootProcessIds,$RootProcessStartedAtUtcTicks)
  Assert-Guarded
  return @{active_process_ids=$(if($script:writerAlive){@($PID,543210)}else{@($PID)});system_console_host_process_ids=@()}
 }
 function Stop-ManagedSolverProcesses {
  param($ProcessIds)
  Assert-Guarded
  if(($ProcessIds-join',')-ne'543210'){throw 'unexpected process selected'}
  if($script:stopFails){throw 'fixture stop failure'}
  $script:writerAlive=$false
 }
 foreach($scenario in @('complete','partial_acquire','stop_failure')){
  $workingFieldGuards=[Collections.Generic.List[string]]::new()
  $fieldReceipt=@{working_points=$records|ForEach-Object{[pscustomobject]@{path=$_.path;bytes=$_.bytes;sha256=$_.sha256}}}
  if($scenario-eq'partial_acquire'){$fieldReceipt.working_points[2].sha256='0'*64}
  $package=@{run_dir=$root};$controllerTicks=0;$script:writerAlive=$true
  $nativeWritersStopped=$false;$script:stopFails=$scenario-eq'stop_failure'
  $caught=$null
  try{Invoke-Expression $acquire[0].Extent.Text}catch{$caught=$_}
  $expectedCount=if($scenario-eq'partial_acquire'){2}else{3}
  if($workingFieldGuards.Count-ne$expectedCount-or($null-ne$caught)-ne($scenario-eq'partial_acquire')){throw 'partial guard acquisition differs'}
  try{. $normal;if($scenario-eq'stop_failure'){throw 'stop failure silently ignored'}}catch{
   if($scenario-ne'stop_failure'-or$_.Exception.Message-ne'fixture stop failure'){throw}
  }finally{. $fallback}
  if($scenario-eq'stop_failure'){
   if(-not$script:writerAlive-or$global:MassSpectrometryImmutablePaSourceGuards.Count-ne3){throw 'guards released while child exit unconfirmed'}
   Assert-Guarded
   $script:writerAlive=$false;$nativeWritersStopped=$true;. $fallback
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

    def test_existing_budget_default_and_explicit_solver_review_remain_strict(self):
        script = """param([string]$Support)
. $Support
$root=Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'));New-Item -ItemType Directory $root|Out-Null
try{
 foreach($class in @('compact','solver_review')){
  $source=Join-Path $root ($class+'.json');$inputs=Join-Path $root ($class+'_inputs');New-Item -ItemType Directory $inputs|Out-Null
  Write-RunJson -Path $source -Value @{schema_version=1;role='integration_resolved_engineering_budget';integration_id='fixture';connection_profile_id='local_frontend';particle_count=100;retention_class=$class;stage_limits=@{single_flight_transport=@{solver='simion';automatic_retry_count=0;wall_clock_seconds=7200;transient_run_directory_bytes=100000;process_tree_working_set_bytes=100000;minimum_system_available_memory_bytes=100000;compact_final_retained_bytes=100000}}}
  $args=@{ResolvedBudget=$source;InputDir=$inputs;ExpectedIntegrationId='fixture';ExpectedConnectionProfileId='local_frontend';StageId='single_flight_transport';Solver='simion'}
  if($class-eq'solver_review'){$args.ExpectedRetentionClass=$class}
  $receipt=Initialize-RfIntegrationStageBudget @args
  if($receipt.limits.wall_clock_seconds-ne7200){throw 'original resource budget changed'}
  if($class-eq'solver_review'){
   $other=Join-Path $root 'reject';New-Item -ItemType Directory $other|Out-Null;$args.InputDir=$other;$args.Remove('ExpectedRetentionClass')
   try{$null=Initialize-RfIntegrationStageBudget @args;throw 'mismatched retention accepted'}catch{if($_.Exception.Message-notmatch'engineering-budget identity differs'){throw}}
  }
 }
 'BUDGET_RETENTION=PASS'
}finally{Remove-Item -LiteralPath $root -Recurse -Force}
"""
        result = self.ps(script, SUPPORT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('BUDGET_RETENTION=PASS', result.stdout)

    def test_formal_result_is_retained_tail_replanned_and_gui_never_flown(self):
        script = """param([string]$Source)
$e=$null;$t=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
foreach($name in @('New-LocalFlightSpecification','Invoke-LocalFlightPhase')){
 $node=$ast.FindAll({param($a)$a-is[Management.Automation.Language.FunctionDefinitionAst]-and$a.Name-eq$name},$true)[0]
 Invoke-Expression $node.Extent.Text
}
$root=Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'));New-Item -ItemType Directory (Join-Path $root 'results') -Force|Out-Null
try{
 $script:run=$root;$projectArtifacts=$root;$workflowModule='fixture';$runId='fixture';$simion='not-started.exe'
 $script:events=[Collections.Generic.List[string]]::new();$script:materializeCount=0
 function MakeCase($index,$ids){return [pscustomobject]@{index=$index;case_id="case_$index";count=$ids.Count;expected_particle_ids=$ids;simion_particle_id_offset=0;merge_offset=0;working_directory=$root;environment=@{OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET='0'};stdout='fixture.log';stderr='fixture.err';fly_arguments=@('fly','fixture.iob')}}
 $script:first=MakeCase 1 @(1);$script:tail=MakeCase 2 @(2,3);$script:gui=MakeCase 99 @(1,2,3)
 function Invoke-LocalWorkflowPython {
  param([string[]]$Arguments,[switch]$Json)
  if($Arguments-contains'prepare-dispatch'){return @{dispatch_request_path='request.json'}}
  if($Arguments-contains'common.simion.resource_scheduler'){
   $script:events.Add($(if($Arguments-contains'--first-batch-completed'){'adaptive'}else{'plan'}))
   @{estimation=@{kind='formal_first_batch_observation'}}|ConvertTo-Json|Set-Content (Join-Path $root 'results/discovery.dispatch_plan.json');return
  }
  if($Arguments-contains'materialize-batches'){
   $script:materializeCount++
   if($script:materializeCount-eq1){return @{batches=@($script:first)}}
   return @{coverage='complete_population';pending_particle_ids=@();batches=@($script:first,$script:tail);gui_case=$script:gui}
  }
 }
 function Invoke-LocalIobBuild {param($Case,[string]$Phase)$script:events.Add('build_'+$Case.case_id)}
 function Start-ObservedFormalProcess {
  param($DispatchPlanPath,$ProcessSpecification,[switch]$WaitForNaturalCompletionAfterObservation)
  if(-not$WaitForNaturalCompletionAfterObservation){throw 'formal process was not observed to completion'}
  $script:events.Add('formal_'+$ProcessSpecification.name)
  return @{process_record=@{completed=$true};resource_budget_exceeded=$false;completed_naturally=$true;exit_code=0;observed_peak_process_tree_working_set_bytes=100;observed_process_cpu_percent=1;observed_background_cpu_percent=0;available_memory_bytes=1000;total_physical_memory_bytes=2000}
 }
 function Invoke-ResourceBudgetedProcesses {
  param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords)
  if(@($ProcessSpecifications).Count-ne1-or$ProcessSpecifications[0].name-ne'case_2'-or@($ExistingProcessRecords).Count-ne1){throw 'formal result was replayed or GUI scheduled'}
  $script:events.Add('tail_case_2');return @{resource_budget_exceeded=$false;processes=@(@{exit_code=0})}
 }
 function Complete-ResourceUsage {param($RunDir,$UsagePath)}
 $result=Invoke-LocalFlightPhase -Phase discovery -PulseTime 12 -SharedTimesPath 'times.json'
 if(($script:events-join',')-ne'plan,build_case_1,formal_case_1,adaptive,build_case_2,build_case_99,tail_case_2'){throw ($script:events-join',')}
 if($result.batches.Count-ne2){throw 'full source materialization lost'}
 'FORMAL_TAIL_GUI=PASS'
}finally{Remove-Item -LiteralPath $root -Recurse -Force}
"""
        result = self.ps(script, EXECUTE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('FORMAL_TAIL_GUI=PASS', result.stdout)

    def test_default_replay_uses_fresh_process_without_flight_overrides_and_rejects_difference(self):
        script = """param([string]$Source)
$e=$null;$t=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)
if($e.Count){throw ($e|Out-String)}
$node=$ast.FindAll({param($a)$a-is[Management.Automation.Language.FunctionDefinitionAst]-and$a.Name-eq'Invoke-LocalDefaultReplay'},$true)[0]
Invoke-Expression $node.Extent.Text
$root=Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'));New-Item -ItemType Directory (Join-Path $root 'inputs') -Force|Out-Null
try{
 $script:run=$root;$budget=@{limits=@{}};$simion='NOT_NATIVE';$script:calls=0;$script:pass=$true
 function Write-RunJson {param($Path,$Value,$Depth)$Value|ConvertTo-Json -Depth 100|Set-Content $Path}
 function Get-HostResourceBudget {param($Role,$Stage)return @{}}
 function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes)return @{stage=$Stage}}
 function Invoke-LocalWorkflowPython {
  param([string[]]$Arguments,[switch]$Json)
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
 $materialized=@{gui_case=@{expected_particle_ids=1..100};batches=@(@{stdout='original_batch.stdout.log'})};$lease=@{}
 $result=Invoke-LocalDefaultReplay -Materialized $materialized -HostLease ([ref]$lease)
 if(-not$result.passed-or$script:calls-ne1-or$lease.stage-ne'postprocess'){throw 'fresh process or public stage transition missing'}
 $script:pass=$false
 try{Invoke-LocalDefaultReplay -Materialized $materialized -HostLease ([ref]$lease);throw 'mismatch accepted'}catch{if($_.Exception.Message-notlike'*differs from scheduled mother evidence*'){throw}}
 'DEFAULT_REPLAY=PASS'
}finally{Remove-Item -LiteralPath $root -Recurse -Force}
"""
        result = self.ps(script, EXECUTE)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('DEFAULT_REPLAY=PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
