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


def check_terminal_publication_behavior(case, execute):
    """Exercise each real finalizer with inert files and the public manifest writer."""
    code = r"""param($Source,$RepoRoot,$Python,$Scenario)
$ErrorActionPreference='Stop'
. (Join-Path $RepoRoot 'common/contracts/run_artifact_support.ps1')
$script:realWriter=(Get-Item Function:Write-VerifiedRunManifest).ScriptBlock
$root=Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $root inputs),(Join-Path $root results) -Force|Out-Null
try{
 $script:events=[Collections.Generic.List[string]]::new()
 $script:run=$root;$script:pythonRoot=$RepoRoot;$frozenRoot=$RepoRoot
 $integration='instrument_assembly';$runId='20261024_190001__test__python__terminal-publication'
 $okay=$Scenario-ne'scientific_failed';$expected=if($okay){'success'}else{'failed'}
 $package=@{run_dir=$root;artifact_run_dir=$root;input_dir=(Join-Path $root inputs);run_config=(Join-Path $root run_config.json);summary=(Join-Path $root summary.json)}
 $config=@{schema_version=1;run_id=$runId;project=$integration;mode='inert_terminal_publication';inputs=@{}}
 Write-RunJson -Path $package.run_config -Value $config
 $scientific=@{status=$expected;reason=$(if($okay){'science_complete'}else{'original_scientific_failure'})}
 Write-RunJson -Path $package.summary -Value $scientific
 $summaryBefore=[IO.File]::ReadAllText($package.summary)
 [IO.File]::WriteAllText((Join-Path $package.input_dir source.json),'{}')
 [IO.File]::WriteAllText((Join-Path $root results/evidence.txt),'inert scientific evidence')
 $workingFieldGuards=[Collections.Generic.List[string]]::new();$workingFieldGuards.Add('inert-field')
 $controllerTicks=0;$nativeWritersStopped=$false;$lease=@{fixture=$true};$capacity=@{fixture=$true}
 $scope='population';$stage='analysis_complete';$populationFlightAttempted=$false
 $budget=$null;$ExecutionBudgetPath='frozen-budget.json';$artifacts=$root;$retentionReason='inert test'
 $saved=@{};$oldEnvironment=@{}
 function Get-ManagedSolverProcessSample {param($RootProcessIds,$RootProcessStartedAtUtcTicks)
  $script:events.Add('writers_stopped');return @{active_process_ids=@($PID);system_console_host_process_ids=@()}}
 function Unprotect-ImmutablePaSource {param($Source)$script:events.Add('guard_release')}
 function Exit-HostExecutionLease {param($Lease,$Outcome,$RunId)$script:events.Add('host_release')}
 function Apply-RunArtifactRetention {param($Python,$RepoRoot,$RunConfig)$script:events.Add('retention')}
 function Write-VerifiedRunManifest {
  param($Python,$RepoRoot,$RunConfig,$Manifest,$Status,$Software,$Outputs,[switch]$DeferCapacityFinalization)
  if(-not$DeferCapacityFinalization){throw 'owner finalized protected capacity too early'}
  if($Status-ne$expected){throw 'scientific terminal status changed'}
  $script:events.Add('publish')
  & $script:realWriter @PSBoundParameters
 }
 function Exit-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session)$script:events.Add('capacity_release')}
 function Invoke-FixtureSeal {
  if($script:events[-1]-ne'capacity_release'){throw 'seal ran before capacity release'}
  $script:events.Add('seal')
  $script:manifestAtSeal=[IO.File]::ReadAllText((Join-Path $root run_manifest.json))
  if(($script:manifestAtSeal|ConvertFrom-Json).status-ne$expected){throw 'manifest not published before seal'}
  if($Scenario-eq'seal_failed'){throw 'FIXTURE_SEAL_FAILURE'}
 }
 function Invoke-LocalWorkflowPython {param($Arguments,[switch]$NoCapture)
  if($Arguments-notcontains'seal-stopped-payload'){throw 'unexpected independent verify/native invocation'}
  Invoke-FixtureSeal
 }
 function Invoke-RunToolRootContext {param($RepoRoot,$Operation)
  if($Operation.ToString()-like'*seal-stopped-payload*'){Invoke-FixtureSeal;return}
  & $Operation
 }
 function Remove-RunPackageExecutionAlias {param($Package)$script:events.Add('alias_release')}
 function Restore-RunEnvironment {param($Names,$Snapshot)$script:events.Add('environment_restore')}
 $errors=$null;$tokens=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
 if($errors.Count){throw ($errors|Out-String)}
 $owners=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.TryStatementAst]-and$null-ne$n.Finally-and$n.Finally.Extent.Text-like'*Write-VerifiedRunManifest*'},$true))
 if($owners.Count-ne1){throw 'unique actual owner finalizer missing'}
 $finalizer=[scriptblock]::Create((@($owners[0].Finally.Statements|ForEach-Object{$_.Extent.Text})-join"`n"))
 $caught=$null
 try{. $finalizer}catch{$caught=$_}
 if(($null-ne$caught)-ne($Scenario-eq'seal_failed')){throw "unexpected finalizer result: $caught"}
 if($caught-and$caught.Exception.Message-ne'FIXTURE_SEAL_FAILURE'){throw $caught}
 $manifest=Get-Content (Join-Path $root run_manifest.json) -Raw|ConvertFrom-Json
 if($manifest.status-ne$expected-or$manifest.project-ne$integration){throw 'published scientific identity differs'}
 if([IO.File]::ReadAllText($package.summary)-ne$summaryBefore){throw 'finalizer rewrote scientific summary'}
 if([IO.File]::ReadAllText((Join-Path $root run_manifest.json))-ne$script:manifestAtSeal){throw 'seal failure rewrote published manifest'}
 foreach($name in @('publish','capacity_release','seal')){
  if(@($script:events|Where-Object{$_-eq$name}).Count-ne1){throw "repeated lifecycle operation: $name"}
 }
 if($script:events.IndexOf('guard_release')-gt$script:events.IndexOf('retention')-or$script:events.IndexOf('retention')-gt$script:events.IndexOf('publish')){throw 'writers/guard/retention order changed'}
 if($null-ne$capacity){throw 'owner capacity protection not released'}
 'TERMINAL_PUBLICATION_BEHAVIOR=PASS'
}finally{Remove-Item -LiteralPath $root -Recurse -Force}
"""
    for scenario in ("success", "scientific_failed", "seal_failed"):
        with case.subTest(scenario=scenario):
            result = case.ps(code, execute, REPO, sys.executable, scenario)
            case.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            case.assertIn("TERMINAL_PUBLICATION_BEHAVIOR=PASS", result.stdout)


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell 7 unavailable')
class LocalFrontendExecuteTests(unittest.TestCase):
    def test_terminal_publication_preserves_science_and_releases_before_seal(self):
        check_terminal_publication_behavior(self, EXECUTE)
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
    def test_actual_working_field_guards_hold_until_children_exit_naturally(self):
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
  $script:writerPolls++
  if($script:writerPolls-ge2){$script:writerAlive=$false}
  return @{active_process_ids=$(if($script:writerAlive){@($PID,543210)}else{@($PID)});system_console_host_process_ids=@()}
 }
 foreach($scenario in @('complete','partial_acquire')){
  $workingFieldGuards=[Collections.Generic.List[string]]::new()
  $fieldReceipt=@{working_points=$records|ForEach-Object{[pscustomobject]@{path=$_.path;bytes=$_.bytes;sha256=$_.sha256}}}
  if($scenario-eq'partial_acquire'){$fieldReceipt.working_points[2].sha256='0'*64}
  $package=@{run_dir=$root};$controllerTicks=0;$script:writerAlive=$true;$script:writerPolls=0
  $nativeWritersStopped=$false
  $caught=$null
  try{Invoke-Expression $acquire[0].Extent.Text}catch{$caught=$_}
  $expectedCount=if($scenario-eq'partial_acquire'){2}else{3}
  if($workingFieldGuards.Count-ne$expectedCount-or($null-ne$caught)-ne($scenario-eq'partial_acquire')){throw 'partial guard acquisition differs'}
  try{. $normal}finally{. $fallback}
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
 function MakeCase($index,$ids){return [pscustomobject]@{index=$index;case_id="case_$index";count=$ids.Count;expected_particle_ids=$ids;simion_particle_id_offset=0;merge_offset=0;working_directory=$root;environment=@{OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET='0'};stdout='fixture.log';stderr='fixture.err';fly_arguments=@('fly','fixture.iob')}}
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
 try{$result=Invoke-FrontendFlightPhase -RunDirectory $root -ProjectRunsRoot $root -RepoRoot $root -Python fixture -RuntimeModule fixture -SimionExe $simion -Limits @{} -Phase discovery -PulseTimeUs 12 -SharedTimesPath 'times.json' -IobVerification $verification}catch{$caught=$_}
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
 $result=Invoke-FrontendDefaultReplay -Materialized $materialized -HostLease ([ref]$lease) -RunDirectory $root -RepoRoot $root -Python unused -SimionExe $simion -Limits @{}
 if(-not$result.passed-or$script:calls-ne1-or$lease.stage-ne'postprocess'){throw 'fresh process or public stage transition missing'}
 $script:pass=$false
 try{Invoke-FrontendDefaultReplay -Materialized $materialized -HostLease ([ref]$lease) -RunDirectory $root -RepoRoot $root -Python unused -SimionExe $simion -Limits @{};throw 'mismatch accepted'}catch{if($_.Exception.Message-notlike'*differs from scheduled mother evidence*'){throw}}
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
 if($collect-and$statement.Extent.Text-like"Write-RunJson*role='rf_oatof_local_frontend_summary'*status='success'*"){break}
}
$block=[scriptblock]::Create(($statements-join"`n"))
$script:run=$Run;$package=@{input_dir=Join-Path $Run 'inputs';result_dir=Join-Path $Run 'results';summary=Join-Path $Run 'summary.json'}
$script:pythonRoot='SYNTHETIC_FROZEN_ROOT';$simion='SYNTHETIC_NO_NATIVE.exe';$budget=@{limits=@{fixture=$true}}
$lease=@{};$source=@{particle_count=100};$discoveryResult=@{fixture=$true};$script:calls=@();$script:summary=$null
function Invoke-LocalWorkflowPython {
 param([string[]]$Arguments,[switch]$Json)
 $out=&$Python -B @Arguments
 if($LASTEXITCODE-ne0){throw 'actual decision/schedule Python failed'}
 return ($out|ConvertFrom-Json)
}
function Get-HostResourceBudget {param($Role,$Stage)return @{}}
function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes)return @{}}
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
 param($Materialized,$HostLease,$RunDirectory,$RepoRoot,$Python,$SimionExe,$Limits)
 if($RunDirectory-ne$Run-or$RepoRoot-ne$script:pythonRoot-or$SimionExe-ne$simion-or-not$Limits.fixture){throw 'shared replay did not receive the explicit run context'}
 if($Materialized.gui_case.expected_particle_ids.Count-ne100){throw 'full GUI population changed'}
 $script:calls+='replay';return @{passed=$true;actual_pulse_time_us=$Materialized.actual_pulse_time_us}
}
function Write-RunJson {param($Path,$Depth,$Value)$script:summary=$Value}
$caught=$null
try{. $block}catch{$caught=$_}
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
