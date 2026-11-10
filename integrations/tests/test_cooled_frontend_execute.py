"""Headless orchestration fixtures; mocked PA bytes are never field evidence."""
from __future__ import annotations

import json
import copy
import contextlib
import io
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from integrations.tests.test_local_frontend_analysis import fixture, write_log
from integrations.tests.test_cooled_frontend import cooled_request_fixture
from msplatform.workflows.cooled_frontend.prepare import prepare_cooled_frontend


REPO = Path(__file__).resolve().parents[2]
EXECUTE = Path(__file__).resolve().parents[1] / "workflows/cooled_frontend/execute.ps1"


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 unavailable")
class CooledFrontendExecuteTests(unittest.TestCase):
    def ps(self, code, *arguments):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.ps1"
            path.write_text(code, encoding="utf-8", newline="\n")
            try:
                return subprocess.run(
                    ["pwsh", "-NoProfile", "-File", str(path), *map(str, arguments)],
                    cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=60,
                )
            except subprocess.TimeoutExpired as error:
                for name, captured in (("stdout", error.stdout), ("stderr", error.stderr)):
                    if captured:
                        text = captured.decode("utf-8", errors="replace") if isinstance(captured, bytes) else captured
                        print(f"COOLED_FIXTURE_TIMEOUT_PARTIAL_{name.upper()}\n{text}", file=sys.stderr, flush=True)
                raise

    def test_native_helper_projects_latest_public_context_and_preserves_process_facts(self):
        code = r"""param($ExecutePath,$Repo,$Python,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $Repo 'common/paths/workspace_paths.ps1')
foreach($entry in @(@($ExecutePath,'Invoke-CooledNative'),@((Join-Path $Repo 'integrations/runtime/frontend_flight_support.ps1'),'Add-FrontendNativeOperation'))){
 $ast=[Management.Automation.Language.Parser]::ParseFile($entry[0],[ref]$null,[ref]$null)
 $name=$entry[1]
 $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
 if($null-eq$node){throw ('Missing actual helper: '+$name)}
 Invoke-Expression $node.Extent.Text
}
# Exceed the native path bound even under the shorter CI temporary root.
$run=Join-Path $Root ('deep-'+('x'*230))
New-Item -ItemType Directory -Path $run -Force|Out-Null
$package=[pscustomobject]@{python=$Python;artifact_run_dir=$run;run_dir=$run;execution_alias=$null;execution_path_capacity=$null;
 native_path_preparation=@{calls=0;elapsed_seconds=0.;transport_bytes=0L};
 path_context=@{artifact_root=$Root;execution_root=(Join-Path $Root 'exec');host_resource_state_path=(Join-Path $Root 'host.sqlite3')}}
$working=Join-Path $run 'simion/build';$inside=Join-Path $run 'inputs/native_builder.lua';$external=Join-Path $Root 'external.pa'
$script:calls=[Collections.Generic.List[object]]::new()
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$FilePath,$ArgumentList,$WorkingDirectory,$Environment,$UsagePath,$RedirectStandardOutput,$RedirectStandardError)
 $script:calls.Add(@{argv=@($ArgumentList);cwd=$WorkingDirectory;environment=$Environment;run=$RunDir;usage=$UsagePath;stdout=$RedirectStandardOutput;stderr=$RedirectStandardError})
 if($mode-eq'unknown'){
  try{throw 'ORIGINAL_COOLED_NATIVE_OBSERVATION_FAILURE'}catch{
   $_.Exception.Data['observed_process_exit_confirmed']=$false
   $_.Exception.Data['observed_process_returncode']=$null
   $_.Exception.Data['observed_process_id']=701
   $_.Exception.Data['observed_process_started_at_utc_ticks']=801L
   throw
  }
 }
 return @{completed=$true;exit_code=0;resource_budget_exceeded=$false;root_process_id=701;root_process_started_at_utc_ticks=801L}
}
try{
 foreach($mode in @('success','unknown')){
  $facts=[Collections.Generic.List[object]]::new();$caught=$null;$before=$calls.Count
  try{Invoke-CooledNative -Package $package -Arguments @('--nogui','lua',$inside,$external,'relative.pa') -Name $mode `
   -RunDirectory $run -SimionExe 'NOT_A_SOLVER__NO_NATIVE_PROCESS' -Limits @{} -WorkingDirectory $working `
   -NativeOperations $facts -NativeResourceReleaseId 'ACTUAL_TEST_OWNER'}catch{$caught=$_}
  if($calls.Count-ne($before+1)-or$facts.Count-ne1){throw ('Native operation duplicated or process fact lost; caught='+$caught)}
  $record=$calls[-1];$alias=[string]$package.run_dir
  if($alias-eq$run-or-not(Test-Path -LiteralPath $alias)){throw 'Actual public context did not create needed junction'}
  if($record.cwd-ne(Join-Path $alias 'simion/build')-or$record.argv[2]-ne(Join-Path $alias 'inputs/native_builder.lua')){throw 'Native cwd/argv did not use current execution view'}
  if($record.argv[3]-ne$external-or$record.argv[4]-ne'relative.pa'){throw 'External or relative argument changed'}
  if($record.environment.MASS_SPECTROMETRY_RUN_DIRECTORY-ne$run-or$record.environment.MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY-ne$alias){throw 'Native environment lost canonical/execution pair'}
  if($record.run-ne$run-or$record.usage-ne(Join-Path $run "logs/$mode.resource_usage.json")-or
     $record.stdout-ne(Join-Path $run "logs/$mode.stdout.log")-or$record.stderr-ne(Join-Path $run "logs/$mode.stderr.log")){throw 'Identity or diagnostic paths became alias paths'}
  $fact=$facts[0]
  if($fact.resource_release_id-ne'ACTUAL_TEST_OWNER'-or$fact.observation.process_id-ne701-or$fact.observation.process_started_at_utc_ticks-ne801L){throw 'Original process/grant identity changed'}
  if($mode-eq'unknown'){
   if($null-eq$caught-or$caught.Exception.Message-ne'ORIGINAL_COOLED_NATIVE_OBSERVATION_FAILURE'-or
      $fact.observation.exit_confirmed-or$null-ne$fact.observation.returncode){throw 'Unknown failure was masked or made complete'}
  }elseif($caught-or-not$fact.observation.exit_confirmed-or$fact.observation.returncode-ne0){throw 'Successful native completion was not preserved'}
 }
 $facts=[Collections.Generic.List[object]]::new();$before=$calls.Count;$caught=$null
 try{Invoke-CooledNative -Package $package -Arguments @('--nogui') -Name invalid_path -RunDirectory $run `
  -SimionExe 'NOT_A_SOLVER__NO_NATIVE_PROCESS' -Limits @{} -WorkingDirectory 'relative_not_native' `
  -NativeOperations $facts -NativeResourceReleaseId 'ACTUAL_TEST_OWNER'}catch{$caught=$_}
 if($null-eq$caught-or$facts.Count-ne0-or$calls.Count-ne$before){throw 'Path preparation failure invented a writer or launched native work'}
 if($package.native_path_preparation.calls-ne2){throw 'Helper did not request current context for each call'}
 'COOLED_NATIVE_PUBLIC_CONTEXT=PASS NATIVE_PROCESSES=0'
}finally{
 # The process boundary above is a stub; no actual writer ever exists in this fixture.
 Remove-RunPackageExecutionAlias -Package $package
}
"""
        with tempfile.TemporaryDirectory() as temporary:
            result = self.ps(code, EXECUTE, REPO, sys.executable, temporary)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("COOLED_NATIVE_PUBLIC_CONTEXT=PASS NATIVE_PROCESSES=0", result.stdout)

    def test_snapshot_clock_uses_common_decision_and_all_original_births(self):
        text = EXECUTE.read_text(encoding="utf-8")
        function = text.split("function Invoke-CooledPopulationClock {", 1)[1].split(
            "function Invoke-CooledPopulationAnalysis", 1)[0]
        code = re.search(r"\$code=@'\n(.*?)\n'@", function, re.S).group(1)
        clocks = []
        for pressure in (0, 1):
            with tempfile.TemporaryDirectory() as temporary:
                run = Path(temporary)
                (run / "inputs").mkdir()
                ctx = dict(decision=dict(actual_pulse_time_us=1100., release_start_us=1000.),
                           cooled_drive=dict(entrance_close_us=50.), flight_horizon_us=1200.,
                           rows=[dict(instrument_time_us=t) for t in (0., 2.)],
                           conditioner=dict(drive=dict(frequency_hz=3.7e6)),
                           experiment=dict(common_pulse_decision={"sha256": "same"}, pressure_scale=pressure),
                           fields=dict(records={"carrier": {"path": "shared.pa"}}))
                with patch("importlib.import_module", return_value=SimpleNamespace(context=lambda _: ctx)), \
                        patch.object(sys, "argv", ["clock", str(run), "mocked_runtime"]), \
                        contextlib.redirect_stdout(io.StringIO()):
                    exec(compile(code, "production_clock", "exec"), {})
                clock = json.loads((run / "inputs/cooled_snapshot_clock.json").read_text())
                times = json.loads((run / "inputs/extraction_shared_times.json").read_text())
                self.assertEqual(times, sorted(set(times)))
                self.assertTrue({0., 2., 50., 525., 1000., 1100., 1200.}.issubset(times))
                self.assertEqual(clock["actual_pulse_time_us"], 1100.)
                clocks.append(times)
        self.assertEqual(*clocks)

    def test_population_branch_uses_public_scheduler_and_declared_saved_control_policy(self):
        code = r"""param($ExecutePath)
$ErrorActionPreference='Stop'
$root=Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $root|Out-Null
try{
 $script:events=[Collections.Generic.List[string]]::new()
 $package=@{native_path_preparation=@{calls=0;elapsed_seconds=0.;transport_bytes=0};run_dir=$root;artifact_run_dir=$root;result_dir=$root;summary=Join-Path $root summary.json}
 $frozenRoot=$root;$Python='NOT_STARTED';$module='fixture';$simion='NOT_NATIVE';$project=$root
 $source=@{particle_count=100};$author=@{pressure_scale=1;common_pulse_decision=@{sha256='shared'};field_source=@{sha256='sealed'}}
 $summaryRole='cooled_frontend_population_summary';$budget=@{limits=@{}};$lease=@{token='TEST_PARENT'}
 $nativeOperations=[Collections.Generic.List[object]]::new()
 function Set-CooledStage {param($Name)}
 $workingFieldGuards=[Collections.Generic.List[string]]::new()
 $front=@{accelerator_local_region=@{accelerator_port_aperture_discretization=@{grid_alignment=@{warnings=@()}}}}
 function Invoke-CooledPopulationClock {param($Package,$RepoRoot,$Python,$RuntimeModule)
  $script:events.Add('clock');return @{actual_pulse_time_us=1100.;shared_times_path='common_times.json';working_points=@(@{kind='carrier_off';path='same_shared_field.pa';bytes=10;sha256='frozen'})}}
 function Protect-ImmutablePaSource {param($Source,$ExpectedBytes,$ExpectedSha256)$script:events.Add('protect')}
 function Invoke-CooledCompiledAperture {param($Package,$Frontend,$PaPath,$RepoRoot,$SimionExe,$Limits)$script:events.Add('topology')}
 function Get-HostResourceBudget {param($Role,$Stage)return @{}}
 function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes)return @{stage=$Stage;token='TEST_PARENT'}}
 function Invoke-FrontendFlightPhase {
  param($Package,$RunDirectory,$ProjectRunsRoot,$RepoRoot,$Python,$RuntimeModule,$SimionExe,$Limits,$Phase,$PulseTimeUs,$SharedTimesPath,$NativeOperations,$NativeResourceReleaseId)
  if(-not[object]::ReferenceEquals($NativeOperations,$script:nativeOperations)-or$NativeResourceReleaseId-ne'TEST_PARENT'){throw 'population fact binding changed'}
  if($Phase-ne'extraction'-or$PulseTimeUs-ne1100.-or$SharedTimesPath-ne'common_times.json'){throw 'complete case decision changed'}
  $script:events.Add('scheduled_complete_population');return @{default_load_iob='full100.iob';batches=@(@{stdout='batch1.log'},@{stdout='batch2.log'});default_replay_policy=@{comparison_policy='independent_stochastic_collisions';scope='saved_controls_only'};gui_case=@{case_id='gui_full_population';iob_path='full100.iob';particle_input='full100.fly2'}}
 }
 function Invoke-CooledPopulationAnalysis {param($Package,$RepoRoot,$Python,$Module,$Materialized,$Times,$PulseTimeUs)
  if($PulseTimeUs-ne1100.-or$Times-ne'common_times.json'){throw 'analysis clock changed'}
  $script:events.Add('cooled_analysis');return @{mother_count=100}}
 function Invoke-FrontendDefaultReplay {param($Package,$Materialized,$HostLease,$RunDirectory,$RepoRoot,$Python,$SimionExe,$Limits,$NativeOperations,$NativeResourceReleaseId)
  if(@($Materialized.batches).Count-ne2-or$Materialized.default_replay_policy.scope-ne'saved_controls_only'-or$Materialized.gui_case.particle_input-ne'full100.fly2'){throw 'replay did not retain scheduled cohort and full GUI controls'}
  $script:events.Add('saved_controls_only');return @{passed=$true;mother_count=100}}
 function Write-RunJson {param($Path,$Value,$Depth)$script:summary=$Value}
 $text=Get-Content -LiteralPath $ExecutePath -Raw
 $start=$text.IndexOf(" Set-CooledStage 'verified_shared_fields_and_snapshot_clock'")
 $end=$text.IndexOf("`n }`n}catch{",$start)
 if($start-lt0-or$end-lt0){throw 'population branch missing'}
 Invoke-Expression $text.Substring($start,$end-$start)
 $script:summary=$scientificSummary
 if(($script:events-join',')-ne'clock,protect,topology,scheduled_complete_population,cooled_analysis,saved_controls_only'){throw ($script:events-join',')}
 if($script:summary.role-ne'cooled_frontend_population_summary'-or$script:summary.mother_count-ne100-or$script:summary.field_design_only){throw 'population mislabeled'}
 if(-not$populationFlightAttempted-or$workingFieldGuards.Count-ne1){throw 'native attempt/protection ownership missing'}
 'POPULATION_SEQUENCE=PASS'
}finally{Remove-Item -LiteralPath $root -Recurse -Force}
"""
        result = self.ps(code, EXECUTE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("POPULATION_SEQUENCE=PASS", result.stdout)

    def test_generic_replay_consumes_complete_baseline_and_keeps_negative_evidence(self):
        code = r"""param($Source,$Repo,$Python,$Root,$Scenario)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$node=$ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-FrontendDefaultReplay'},$true)[0]
Invoke-Expression $node.Extent.Text
$case=Get-Content -LiteralPath (Join-Path $Root case.json) -Raw|ConvertFrom-Json -AsHashtable
$materialized=@{gui_case=$case;batches=@($case);default_replay_policy=@{requested=$true;comparison_policy='deterministic_trajectory_parity';scope='fresh_process'}}
if($Scenario-eq'saved_controls'){
 $materialized.default_replay_policy=@{requested=$true;comparison_policy='independent_stochastic_collisions';scope='saved_controls_only'}
 $materialized.receipt_path=Join-Path $Root materialization.json
 ConvertTo-Json -InputObject $materialized -Depth 100|Set-Content -LiteralPath $materialized.receipt_path
}
function Write-RunJson {param($Path,$Value,$Depth=100)
 ConvertTo-Json -InputObject $Value -Depth $Depth|Set-Content -LiteralPath $Path}
function Invoke-FrontendRuntimePython {param($Python,$RepoRoot,$RunDirectory,$Name,$Arguments,[switch]$Json)
 $result=& $Python @Arguments
 if($LASTEXITCODE-ne0){throw "Python $Name failed"}
 return (($result-join "`n")|ConvertFrom-Json -AsHashtable)
}
function Get-HostResourceBudget {param($Role,$Stage)return @{}}
function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes)return @{stage=$Stage}}
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$FilePath,$ArgumentList,$WorkingDirectory,$Environment,$UsagePath,$RedirectStandardOutput,$RedirectStandardError)
 if($Scenario-eq'saved_controls'){throw 'stochastic controls check launched native replay'}
 if(($ArgumentList-join'|')-ne'--nogui|--noprompt|fly|local.iob'-or$WorkingDirectory-ne$case.working_directory){throw 'saved IOB defaults were overridden'}
 if($Environment.Count-ne1-or$Environment.OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET-ne'0'){throw 'replay environment changed'}
 $spec=Get-Content (Join-Path $Root results/default_replay/specification.json) -Raw|ConvertFrom-Json
 if($spec.control_records[0].path-ne$case.iob_path-or$spec.control_records[2].path-ne$case.particle_input){throw 'replay controls changed owner'}
 Copy-Item -LiteralPath (Join-Path $Root replay_fixture.log) -Destination $RedirectStandardOutput
 Set-Content -LiteralPath $RedirectStandardError ''
 if($Scenario-eq'control'){Add-Content -LiteralPath $case.program_path 'control drift'}
 return @{resource_budget_exceeded=$false;exit_code=0}
}
$lease=@{}
try{

function Get-RunNativeExecutionContext {param($Package,$Paths,$Tool) @{run_dir=$Root;projected_paths=@($Paths);environment=@{}}}
function Project-RunPath {param($Paths,$ArtifactRunDir,$RunDir,$Python) return $Paths}
 $result=Invoke-FrontendDefaultReplay -Package ([pscustomobject]@{artifact_run_dir=$Root;python="unused"}) -Materialized $materialized -HostLease ([ref]$lease) -RunDirectory $Root -RepoRoot $Repo -Python $Python -SimionExe NOT_NATIVE -Limits @{}
 if($Scenario-eq'saved_controls'){
  if($result.scope-ne'saved_controls_only'-or$result.native_fly_performed-or-not$result.controls_verified){throw 'controls check mislabeled'}
 }elseif($Scenario-ne'pass'-or-not$result.passed){throw 'unexpected parity acceptance'}
}catch{
 if($Scenario-in@('pass','saved_controls')-or$_.Exception.Message-notlike'*complete comparison retained*'){throw}
}
'GENERIC_COMPLETE_REPLAY=PASS'
"""
        for scenario in ("pass", "state", "control", "saved_controls"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                run = Path(temporary)
                baseline, events = fixture(run)
                (run / "results").mkdir(exist_ok=True)
                directory = run / "simion/gui_full_population"
                directory.mkdir(parents=True)
                for name in ("local.iob", "local.lua", "local.fly2"):
                    (directory / name).write_text("PURE_CONTROL_FIXTURE", encoding="utf-8")
                case = dict(count=3, expected_particle_ids=[3, 11, 67], merge_offset=0,
                            simion_particle_id_offset=0, working_directory=str(directory),
                            iob_path=str(directory / "local.iob"), program_path=str(directory / "local.lua"),
                            particle_input=str(directory / "local.fly2"), stdout=str(baseline))
                (run / "case.json").write_text(json.dumps(case), encoding="utf-8")
                replay_events = copy.deepcopy(events)
                if scenario == "state":
                    next(row for row in replay_events if row["event"] == "local_timeout")["vy_mm_per_us"] += .001
                write_log(run / "replay_fixture.log", replay_events)
                original_baseline = baseline.read_bytes()
                result = self.ps(code, REPO / "integrations/runtime/frontend_flight_support.ps1",
                                 REPO, sys.executable, run, scenario)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                comparison_dir = run / "results/default_replay"
                if scenario == "saved_controls":
                    receipt = json.loads((run / "results/saved_controls_verification.json").read_text())
                    self.assertEqual(receipt["scope"], "saved_controls_only")
                    self.assertEqual(receipt["default_replay_policy"]["comparison_policy"],
                                     "independent_stochastic_collisions")
                    self.assertFalse(receipt["native_fly_performed"])
                    self.assertFalse(comparison_dir.exists())
                    self.assertFalse((run / "inputs/default_replay_scheduled_logs.json").exists())
                    self.assertEqual(baseline.read_bytes(), original_baseline)
                    continue
                comparison = json.loads((comparison_dir / "comparison.json").read_text())
                self.assertEqual(comparison["passed"], scenario == "pass")
                self.assertEqual(comparison["mother_count"], 3)
                self.assertEqual(json.loads((run / "inputs/default_replay_scheduled_logs.json").read_text()),
                                 [str(baseline)])
                self.assertEqual(baseline.read_bytes(), original_baseline)
                self.assertTrue((comparison_dir / "native.stdout.log").is_file())
                self.assertTrue((comparison_dir / "terminal_state_comparison.csv").is_file())
                if scenario == "control":
                    self.assertFalse(comparison["controls_unchanged"])
                if scenario == "state":
                    self.assertGreater(comparison["differing_field_count"], 0)

    def test_field_design_scope_requires_explicit_solver_authorization(self):
        code = r"""param($Source)
$tokens=$null;$errors=$null
$null=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
try{& $Source -Request ignored -RepoRoot ignored -Python ignored -ValidateOnly -FieldDesignOnly;throw 'scope accepted'}
catch{if($_.Exception.Message-notlike'*FieldDesignOnly requires SolverAuthorized*'){throw}}
'SCOPE_GUARD=PASS'
"""
        result = self.ps(code, EXECUTE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SCOPE_GUARD=PASS", result.stdout)

    def test_population_missing_common_decision_stops_before_owner_or_native(self):
        with tempfile.TemporaryDirectory() as temporary:
            request = Path(temporary) / "request.json"
            request.write_text(json.dumps({"field_source": None, "common_pulse_decision": None}))
            code = r"""param($Source,$Repo,$Python,$Request)
try{& $Source -Request $Request -RepoRoot $Repo -Python $Python -SolverAuthorized -ExecutionBudgetPath ignored;throw 'unbound flight accepted'}
catch{if($_.Exception.Message-notlike'*Population flight requires an explicit sealed field source*'){throw}}
'UNBOUND_POPULATION=PASS'
"""
            result = self.ps(code, EXECUTE, REPO, sys.executable, request)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("UNBOUND_POPULATION=PASS", result.stdout)

    def test_capacity_protection_projects_only_artifact_owned_inputs(self):
        code = r"""param($Source)
$ErrorActionPreference='Stop'
$workspace=Join-Path ([IO.Path]::GetTempPath()) 'cooled_fixture_workspace'
$artifacts=Join-Path $workspace artifacts
$Request=Join-Path $workspace 'simulation_repo/request.json'
$ExecutionBudgetPath=Join-Path $workspace 'simulation_repo/budget.json'
$author=[pscustomobject]@{source=[pscustomobject]@{release=[pscustomobject]@{path='artifacts/source.csv'};model=[pscustomobject]@{path='simulation_repo/model.json'}};field_source=$null;common_pulse_decision=$null}
$text=Get-Content -LiteralPath $Source -Raw
$sourceAuthor=$author;$fieldSource=$null
$start=$text.IndexOf(' $candidates=@(');$end=$text.IndexOf(' $capacity=Enter-ArtifactWorkflowCapacitySession',$start)
if($start-lt0-or$end-lt0){throw 'actual admission projection not found'}
Invoke-Expression $text.Substring($start,$end-$start)
if($protected.Count-ne1-or$protected[0]-ne(Join-Path $artifacts source.csv)){throw 'repo inputs were handed to artifact protection'}
'ARTIFACT_PROJECTION=PASS'
"""
        result = self.ps(code, EXECUTE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ARTIFACT_PROJECTION=PASS", result.stdout)

    def test_actual_entry_imports_budget_and_public_runtime_commands(self):
        code = r"""param($Source,$RepoRoot)
$ErrorActionPreference='Stop'
$relative='integrations';$ResultPath='';$ResumeFinalization=$false
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
foreach($statement in $ast.EndBlock.Statements){
 if($statement-is[Management.Automation.Language.PipelineAst]){
  $command=$statement.PipelineElements[0]
  if($command-is[Management.Automation.Language.CommandAst]-and$command.InvocationOperator-eq'Dot'){
   Invoke-Expression $command.Extent.Text
  }
 }
}
foreach($name in @('Initialize-IntegrationStageBudget','New-RunPackage','Enter-ArtifactWorkflowCapacitySession','Invoke-FrontendFlightPhase','Invoke-FrontendDefaultReplay','Freeze-ConsumerDependencies')){
 if(-not(Get-Command $name -ErrorAction SilentlyContinue)){throw "missing public dependency: $name"}
}
'ACTUAL_IMPORT_CLOSURE=PASS'
"""
        result = self.ps(code, EXECUTE, REPO)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ACTUAL_IMPORT_CLOSURE=PASS", result.stdout)

    def test_ordinary_cache_resumes_only_missing_fields_then_hit_without_native(self):
        code=r'''param($Source,$Repo,$Python,$Run,$Cache,$Mode='normal')
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$node=$ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-CooledOrdinaryFieldBuild'},$true)[0]
Invoke-Expression $node.Extent.Text
$env:COOLED_INERT_CACHE=$Cache
# Test-private interpreter lifetime; every original script/argv still executes.
$workerCode=@'
import contextlib, ctypes, io, json, os, sys, threading, traceback
from ctypes import wintypes
sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
parent=int(sys.argv[1])
if os.name == 'nt':
    kernel=ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.WaitForSingleObject.restype=wintypes.DWORD
    handle=kernel.OpenProcess(0x00100000,False,parent)
    if not handle:
        raise OSError(ctypes.get_last_error(), 'Cannot bind actual parent process handle')
    def watch_parent():
        result=kernel.WaitForSingleObject(handle,0xFFFFFFFF)
        os._exit(91 if result == 0 else 92)
else:
    import time
    def watch_parent():
        while os.getppid() == parent:
            time.sleep(0.05)
        os._exit(91)
threading.Thread(target=watch_parent,daemon=True).start()
print(json.dumps({'pid':os.getpid(),'launcher_pid':os.getppid(),'parent_pid':parent,'python':sys.executable,'cwd':os.getcwd()}),flush=True)
from integrations.workflows.cooled_frontend import runtime as cr
original_plan=cr.field_cache_plan
try:
    for line in sys.stdin:
        arguments=json.loads(line)['arguments']
        output,errors=io.StringIO(),io.StringIO()
        exit_code=0
        cr.field_cache_plan=original_plan
        sys.argv=['-c',*arguments[2:]]
        try:
            if arguments[0] != '-c':
                raise ValueError('Expected actual inline Python argv')
            with contextlib.redirect_stdout(output),contextlib.redirect_stderr(errors):
                exec(compile(arguments[1],'<cooled-cache-request>','exec'),{'__name__':'__main__'})
        except SystemExit as error:
            exit_code=0 if error.code is None else error.code if isinstance(error.code,int) else 1
            if error.code is not None and not isinstance(error.code,int):
                print(error.code,file=errors)
        except BaseException:
            traceback.print_exc(file=errors)
            exit_code=1
        print(json.dumps({'stdout':output.getvalue(),'stderr':errors.getvalue(),'exit_code':exit_code}),flush=True)
finally:
    # The OS closes this process-owned handle on exit; do not close a handle
    # while the independent parent watcher is still waiting on it.
    sys.stdout.flush()
'@
$start=[Diagnostics.ProcessStartInfo]::new()
$start.FileName=$Python;$start.WorkingDirectory=$Repo;$start.UseShellExecute=$false;$start.CreateNoWindow=$true
$start.RedirectStandardInput=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
$start.StandardInputEncoding=[Text.UTF8Encoding]::new($false)
$start.StandardOutputEncoding=[Text.UTF8Encoding]::new($false)
$start.StandardErrorEncoding=[Text.UTF8Encoding]::new($false)
foreach($arg in @('-B','-u','-c',$workerCode,[string]$PID)){$start.ArgumentList.Add($arg)}
$worker=[Diagnostics.Process]::Start($start)
$workerErrors=$worker.StandardError.ReadToEndAsync()
$identity=$worker.StandardOutput.ReadLine()|ConvertFrom-Json
# Windows venv redirectors can own the interpreter child; bind that real edge.
if(($identity.pid-ne$worker.Id-and$identity.launcher_pid-ne$worker.Id)-or$identity.parent_pid-ne$PID-or$identity.python-ne$Python-or$identity.cwd-ne$Repo){throw ("Private worker identity mismatch: actual={0} launcher={1} parent={2} python={3} cwd={4}"-f($identity|ConvertTo-Json -Compress),$worker.Id,$PID,$Python,$Repo)}
$identity|Add-Member -NotePropertyName launch_process_pid -NotePropertyValue $worker.Id
$actualWorker=[Diagnostics.Process]::GetProcessById([int]$identity.pid)
$null=$actualWorker.Handle
[IO.File]::WriteAllText((Join-Path $Run 'worker_identity.json'),($identity|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
Write-Host ('COOLED_CACHE_WORKER pid={0} parent={1} python={2}'-f$identity.pid,$identity.parent_pid,$identity.python)
$script:realCalls=0
$script:refines=0;$script:exports=0;$script:gem=0;$script:verifies=0;$script:interrupt=$true
function Write-RunJson {param($Path,$Value,$Depth=100)
 [IO.File]::WriteAllText($Path,(ConvertTo-Json -InputObject $Value -Depth $Depth),[Text.UTF8Encoding]::new($false))
}
function Get-HostResourceBudget {param($Role,$Stage)return @{}}
function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes)return @{stage=$Stage}}
function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$ProtectedCacheKeys,$ProtectedPaths)
 if($ProtectedCacheKeys.Count-ne7-or@($ProtectedCacheKeys|Where-Object{$_.Length-ne64}).Count){throw 'published cache key not protected'}
 return @{session=$Session}
}
function Invoke-FrontendRuntimePython {
 param($Python,$RepoRoot,$RunDirectory,$Name,$Arguments,[switch]$Json)
 $prefix="import os;from pathlib import Path;from integrations.workflows.cooled_frontend import runtime as cr;original=cr.field_cache_plan;cr.field_cache_plan=lambda run: original(run,cache_root=Path(os.environ['COOLED_INERT_CACHE']));"
 $Arguments[1]=$prefix+"`n"+$Arguments[1]
 $timer=[Diagnostics.Stopwatch]::StartNew()
 Write-Host ("COOLED_CACHE_CALL START phase={0} name={1} run={2} python={3}"-f$script:cachePhase,$Name,$RunDirectory,$Python)
 $worker.StandardInput.WriteLine((@{arguments=@($Arguments)}|ConvertTo-Json -Depth 100 -Compress))
 $worker.StandardInput.Flush()
 $line=$worker.StandardOutput.ReadLine()
 if($null-eq$line){throw 'Private Python worker exited before its real response'}
 $response=$line|ConvertFrom-Json -Depth 100
 $output=[string]$response.stdout;$callExit=[int]$response.exit_code
 if($response.stderr){[Console]::Error.Write([string]$response.stderr)}
 if($script:cachePhase-ne'negative'){$script:realCalls++}
 Write-Host ("COOLED_CACHE_CALL END phase={0} name={1} elapsed={2:F6} exit={3}"-f$script:cachePhase,$Name,$timer.Elapsed.TotalSeconds,$callExit)
 if($callExit-ne0){throw "actual public cache boundary failed: $Name"}
 if($Json){return ($output|ConvertFrom-Json -Depth 100)}
}
function Invoke-CooledNative {
 param($Arguments,$Name,$RunDirectory,$SimionExe,$Limits,$WorkingDirectory)
 if(-not(Test-Path -LiteralPath $WorkingDirectory -PathType Container)){throw 'vendor working directory missing'}
 if($Arguments-contains'fly'){throw 'field build launched Fly'}
 if($Name-eq'field_gem2pa'){$script:gem++;[IO.File]::WriteAllBytes($Arguments[-1],[byte[]]::new(64))}
 elseif($Name-like'field_refine_*'){
  $script:refines++
  if($Arguments[6]-ne'zero_dirichlet'){throw 'ordinary field changed its boundary'}
  if($script:interrupt-and$script:refines-eq4){throw 'inert interruption'}
  [IO.File]::WriteAllBytes($Arguments[5],[byte[]]::new(64))
 }elseif($Name-like'field_export_*'){
  $script:exports++
  if((Split-Path -Leaf $Arguments[-1])-ne'pending.pa'){throw 'export wrote directly into completed payload'}
  [IO.File]::WriteAllBytes($Arguments[-1],[byte[]]::new(64))
 }elseif($Name-like'field_verification_*'){
  $script:verifies++
  if(-not(Test-Path -LiteralPath $Arguments[-2])){throw 'missing actual verification specification'}
  Set-Content -LiteralPath $Arguments[-1] 'INERT_ONLY_NO_NATIVE_VERIFICATION_CLAIM'
 }else{throw "unexpected vendor request $Name"}
}
$package=@{native_path_preparation=@{calls=0;elapsed_seconds=0.;transport_bytes=0};run_dir=$Run;artifact_run_dir=$Run;input_dir=Join-Path $Run inputs;result_dir=Join-Path $Run results}
$lease=@{}
$capacity=@{committed_new_bytes=[long]::MaxValue}
$call=@{Package=$package;FrozenRepoRoot=$Repo;Python=$Python;RuntimeModule='unused';SimionExe='NOT_NATIVE';Limits=@{};HostLease=[ref]$lease;CapacitySession=[ref]$capacity}
try{
 if($Mode-eq'parent_exit'){
  $active=Join-Path $Run 'worker_active.txt'
  $worker.StandardInput.WriteLine((@{arguments=@('-c',"from pathlib import Path; import sys,time; Path(sys.argv[1]).write_text('active'); time.sleep(120)",$active)}|ConvertTo-Json -Compress))
  $worker.StandardInput.Flush()
  $activeWait=[Diagnostics.Stopwatch]::StartNew()
  while(-not(Test-Path -LiteralPath $active)){
   if($activeWait.Elapsed.TotalSeconds-gt10){throw 'Worker did not enter blocking request'}
   Start-Sleep -Milliseconds 10
  }
  [Environment]::Exit(19)
 }
 if($Mode-eq'parent_exception'){throw 'PRIVATE_PARENT_EXCEPTION_SENTINEL'}
 $script:cachePhase='negative'
 try{Invoke-FrontendRuntimePython -Python $Python -RepoRoot $Repo -RunDirectory $Run -Name negative_exit -Arguments @('-c',"import sys; print('PRIVATE_ERROR_SENTINEL',file=sys.stderr); raise SystemExit(7)") -Json;throw 'nonzero accepted'}
 catch{if($_.Exception.Message-ne'actual public cache boundary failed: negative_exit'){throw}}
 try{Invoke-FrontendRuntimePython -Python $Python -RepoRoot $Repo -RunDirectory $Run -Name negative_json -Arguments @('-c',"print('NOT_JSON_SENTINEL')") -Json;throw 'invalid JSON accepted'}
 catch{if($_.FullyQualifiedErrorId-notlike'*ConvertFromJson*'){throw};Write-Host 'COOLED_CACHE_BAD_JSON_REJECTED'}
$script:cachePhase='interrupted';$phaseTimer=[Diagnostics.Stopwatch]::StartNew()
try{Invoke-CooledOrdinaryFieldBuild @call;throw 'interruption missing'}catch{if($_.Exception.Message-ne'inert interruption'){throw}}
Write-Host ("COOLED_CACHE_PHASE phase=interrupted elapsed={0:F6}"-f$phaseTimer.Elapsed.TotalSeconds)
$script:cachePhase='resumed';$phaseTimer.Restart()
$script:interrupt=$false
$result=Invoke-CooledOrdinaryFieldBuild @call
if($script:refines-ne8-or$script:exports-ne7-or$script:gem-ne1-or$script:verifies-ne7){throw 'completed members were rebuilt or lost'}
if($result.working_points.Count-ne7-or$result.retained_native_build_objects.Count-ne0){throw 'published fields were materialized'}
foreach($record in $result.working_points){if(-not(Get-Item -LiteralPath $record.path).IsReadOnly){throw 'published field is writable'}}
Write-Host ("COOLED_CACHE_PHASE phase=resumed elapsed={0:F6}"-f$phaseTimer.Elapsed.TotalSeconds)
$next=$Run+'-next'
$null=New-Item -ItemType Directory -Path $next
Copy-Item -LiteralPath (Join-Path $Run inputs) -Destination (Join-Path $next inputs) -Recurse
$null=New-Item -ItemType Directory -Path (Join-Path $next results),(Join-Path $next logs)
foreach($name in @('cooled_frontend_field_stage_receipt.json','cooled_field_bank.json')){Remove-Item -LiteralPath (Join-Path $next ('inputs/'+$name))}
$package=@{native_path_preparation=@{calls=0;elapsed_seconds=0.;transport_bytes=0};run_dir=$next;artifact_run_dir=$next;input_dir=Join-Path $next inputs;result_dir=Join-Path $next results}
$call.Package=$package
$script:cachePhase='hit';$phaseTimer.Restart()
$again=Invoke-CooledOrdinaryFieldBuild @call
Write-Host ("COOLED_CACHE_PHASE phase=hit elapsed={0:F6}"-f$phaseTimer.Elapsed.TotalSeconds)
if($script:refines-ne8-or$script:exports-ne7-or$script:gem-ne1-or$script:verifies-ne7){throw 'HIT invoked native work'}
if($again.field_directory-ne$result.field_directory){throw 'HIT changed exact generation'}
if($script:realCalls-ne47){throw ('Real argv count changed: '+$script:realCalls)}
'PUBLIC_COOLED_RESUME_AND_HIT=PASS'
}finally{
 $worker.StandardInput.Close()
 if(-not$worker.WaitForExit(5000)){$worker.Kill($true);$worker.WaitForExit()}
 if(-not$actualWorker.WaitForExit(5000)){$actualWorker.Kill($true);$actualWorker.WaitForExit()}
 $workerErrors.GetAwaiter().GetResult()|Write-Host
 Write-Host ('COOLED_CACHE_WORKER_STOPPED pid={0} worker_os_exit={1} launcher={2} launcher_os_exit={3}'-f$identity.pid,$actualWorker.ExitCode,$worker.Id,$worker.ExitCode)
 $actualWorker.Dispose()
 $worker.Dispose()
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            author,_=cooled_request_fixture(root)
            run=root/"run"
            prepare_cooled_frontend(author,run,root,run_id="20261022_120000__build__python__cooled-fixture")
            (run/"logs").mkdir();(run/"results").mkdir()
            (run/"inputs/native_discovery.json").write_text(json.dumps(dict(bytes=1,sha256="A"*64,file_version="INERT")))
            try:
                result=self.ps(code,EXECUTE,REPO,sys.executable,run,root/"cache")
                print(result.stdout, end="", flush=True)
                if result.stderr:
                    print(result.stderr, end="", file=sys.stderr, flush=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn("PUBLIC_COOLED_RESUME_AND_HIT=PASS",result.stdout)
                self.assertIn("PRIVATE_ERROR_SENTINEL", result.stderr)
                self.assertIn("COOLED_CACHE_BAD_JSON_REJECTED", result.stdout)
                self.assertIn("COOLED_CACHE_WORKER_STOPPED", result.stdout)
                self.assertIn("worker_os_exit=0", result.stdout)
                for mode in ("normal", "parent_exception", "parent_exit"):
                    with self.subTest(worker_lifecycle=mode):
                        if mode != "normal":
                            result = self.ps(code, EXECUTE, REPO, sys.executable, run, root / "cache", mode)
                            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                            if mode == "parent_exception":
                                self.assertIn("PRIVATE_PARENT_EXCEPTION_SENTINEL", result.stderr)
                                self.assertIn("COOLED_CACHE_WORKER_STOPPED", result.stdout)
                                self.assertIn("worker_os_exit=0", result.stdout)
                            else:
                                self.assertEqual(result.returncode, 19, result.stdout + result.stderr)
                                self.assertTrue((run / "worker_active.txt").is_file())
                        identity = json.loads((run / "worker_identity.json").read_text(encoding="utf-8-sig"))
                        print(f"COOLED_CACHE_WORKER_LIFECYCLE mode={mode} identity={json.dumps(identity)}", flush=True)
                        self.assertEqual(Path(identity["python"]).resolve(), Path(sys.executable).resolve())
                        for process_pid in {identity["pid"], identity["launch_process_pid"]}:
                            if sys.platform != "win32":
                                import os
                                import time

                                deadline = time.monotonic() + 5
                                while True:
                                    try:
                                        os.kill(process_pid, 0)
                                    except ProcessLookupError:
                                        break
                                    self.assertLess(time.monotonic(), deadline, "Private worker remained alive")
                                    time.sleep(0.05)
                                print(f"COOLED_CACHE_WORKER_EXIT_CONFIRMED mode={mode} pid={process_pid}", flush=True)
                                continue
                            import ctypes
                            from ctypes import wintypes

                            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                            kernel.OpenProcess.restype = wintypes.HANDLE
                            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                            kernel.WaitForSingleObject.restype = wintypes.DWORD
                            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                            handle = kernel.OpenProcess(0x00100000, False, process_pid)
                            if handle:
                                try:
                                    self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0,
                                                     f"Private worker {process_pid} remained alive after {mode}")
                                finally:
                                    kernel.CloseHandle(handle)
                            else:
                                self.assertEqual(ctypes.get_last_error(), 87,
                                                 "Worker exit probe failed for a reason other than absent process")
                            print(f"COOLED_CACHE_WORKER_EXIT_CONFIRMED mode={mode} pid={process_pid}", flush=True)
            finally:
                for path in root.rglob("*"):
                    if path.is_file():
                        path.chmod(0o666)



if __name__ == "__main__":
    unittest.main()
