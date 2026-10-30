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
from integrations.workflows.cooled_frontend.prepare import prepare_cooled_frontend
from integrations.tests.test_local_frontend_execute import check_terminal_publication_behavior


REPO = Path(__file__).resolve().parents[2]
EXECUTE = Path(__file__).resolve().parents[1] / "workflows/cooled_frontend/execute.ps1"


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 unavailable")
class CooledFrontendExecuteTests(unittest.TestCase):
    def test_terminal_publication_preserves_science_and_releases_before_seal(self):
        check_terminal_publication_behavior(self, EXECUTE)
    def ps(self, code, *arguments):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.ps1"
            path.write_text(code, encoding="utf-8", newline="\n")
            return subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(path), *map(str, arguments)],
                cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=60,
            )

    def test_native_helper_uses_public_execution_context_and_canonical_diagnostics(self):
        code = r"""param($ExecutePath,$Repo,$Python,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $Repo 'common/paths/workspace_paths.ps1')
$ast=[Management.Automation.Language.Parser]::ParseFile($ExecutePath,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-CooledNative'},$true)
Invoke-Expression $node.Extent.Text
# Deliberately exceed native path limits even under short CI temporary roots.
$run=Join-Path $Root ('deep-'+('x'*230))
New-Item -ItemType Directory -Path $run -Force|Out-Null
$package=[pscustomobject]@{python=$Python;artifact_run_dir=$run;run_dir=$run;execution_alias=$null;execution_path_capacity=$null;
 native_path_preparation=@{calls=0;elapsed_seconds=0.;transport_bytes=0L};
 path_context=@{artifact_root=$Root;execution_root=(Join-Path $Root 'exec');host_resource_state_path=(Join-Path $Root 'host.sqlite3')}}
$cwd=Join-Path $run 'simion/build';$input=Join-Path $run 'inputs/native_builder.lua';$external=Join-Path $Root 'external.pa'
$script:calls=[Collections.Generic.List[object]]::new()
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$FilePath,$ArgumentList,$WorkingDirectory,$Environment,$UsagePath,$RedirectStandardOutput,$RedirectStandardError)
 $script:calls.Add(@{argv=@($ArgumentList);cwd=$WorkingDirectory;env=$Environment;run=$RunDir;usage=$UsagePath})
 if($mode-eq'unknown'){try{throw 'ORIGINAL_OBSERVATION_UNKNOWN'}catch{
  $_.Exception.Data['observed_process_exit_confirmed']=$false;throw}}
 return @{exit_code=0;resource_budget_exceeded=$false}
}
try{
 foreach($mode in @('success','unknown')){
  $before=$calls.Count;$caught=$null
  try{Invoke-CooledNative -Package $package -Arguments @('--nogui','lua',$input,$external,'relative.pa') -Name $mode `
   -RunDirectory $run -SimionExe 'INERT_NOT_STARTED' -Limits @{} -WorkingDirectory $cwd}catch{$caught=$_}
  if($calls.Count-ne($before+1)){throw 'Native call duplicated or skipped'}
  $captured=$calls[-1];$alias=[string]$package.run_dir
  if($alias-eq$run-or-not(Test-Path -LiteralPath $alias)){throw 'Public context did not select needed alias'}
  if($captured.cwd-ne(Join-Path $alias 'simion/build')-or$captured.argv[2]-ne(Join-Path $alias 'inputs/native_builder.lua')){throw 'Cwd or argv did not project'}
  if($captured.argv[3]-ne$external-or$captured.argv[4]-ne'relative.pa'){throw 'External or relative path changed'}
  if($captured.env.MASS_SPECTROMETRY_RUN_DIRECTORY-ne$run-or$captured.env.MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY-ne$alias){throw 'Native canonical/execution environment pair changed'}
  if($captured.run-ne$run-or$captured.usage-ne(Join-Path $run "logs/$mode.resource_usage.json")){throw 'Identity or diagnostics became transient'}
  if($mode-eq'unknown'){
   if($null-eq$caught-or$caught.Exception.Message-ne'ORIGINAL_OBSERVATION_UNKNOWN'-or$caught.Exception.Data['observed_process_exit_confirmed']-ne$false){throw 'Original unknown observation changed'}
  }elseif($caught){throw $caught}
 }
 $before=$calls.Count;$caught=$null
 try{Invoke-CooledNative -Package $package -Arguments @('--nogui') -Name bad -RunDirectory $run -SimionExe 'INERT_NOT_STARTED' -Limits @{} -WorkingDirectory 'relative'}catch{$caught=$_}
 if($null-eq$caught-or$calls.Count-ne$before){throw 'Prelaunch path failure started native work'}
 'COOLED_PUBLIC_NATIVE_CONTEXT=PASS NATIVE_PROCESSES=0'
}finally{Remove-RunPackageExecutionAlias -Package $package}
"""
        with tempfile.TemporaryDirectory() as temporary:
            result = self.ps(code, EXECUTE, REPO, sys.executable, temporary)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("COOLED_PUBLIC_NATIVE_CONTEXT=PASS NATIVE_PROCESSES=0", result.stdout)

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
 $package=@{run_dir=$root;result_dir=$root;summary=Join-Path $root summary.json}
 $frozenRoot=$root;$Python='NOT_STARTED';$module='fixture';$simion='NOT_NATIVE';$project=$root
 $source=@{particle_count=100};$author=@{pressure_scale=1;common_pulse_decision=@{sha256='shared'};field_source=@{sha256='sealed'}}
 $summaryRole='cooled_frontend_population_summary';$budget=@{limits=@{}};$lease=@{}
 $workingFieldGuards=[Collections.Generic.List[string]]::new()
 $front=@{accelerator_local_region=@{accelerator_port_aperture_discretization=@{grid_alignment=@{warnings=@()}}}}
 function Invoke-CooledPopulationClock {param($Package,$RepoRoot,$Python,$RuntimeModule)
  $script:events.Add('clock');return @{actual_pulse_time_us=1100.;shared_times_path='common_times.json';working_points=@(@{kind='carrier_off';path='same_shared_field.pa';bytes=10;sha256='frozen'})}}
 function Protect-ImmutablePaSource {param($Source,$ExpectedBytes,$ExpectedSha256)$script:events.Add('protect')}
 function Invoke-CooledCompiledAperture {param($Package,$Frontend,$PaPath,$RepoRoot,$SimionExe,$Limits)$script:events.Add('topology')}
 function Get-HostResourceBudget {param($Role,$Stage)return @{}}
 function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes)return @{stage=$Stage}}
 function Invoke-FrontendFlightPhase {
  param($RunDirectory,$ProjectRunsRoot,$RepoRoot,$Python,$RuntimeModule,$SimionExe,$Limits,$Phase,$PulseTimeUs,$SharedTimesPath)
  if($Phase-ne'extraction'-or$PulseTimeUs-ne1100.-or$SharedTimesPath-ne'common_times.json'){throw 'complete case decision changed'}
  $script:events.Add('scheduled_complete_population');return @{default_load_iob='full100.iob';batches=@(@{stdout='batch1.log'},@{stdout='batch2.log'});default_replay_policy=@{comparison_policy='independent_stochastic_collisions';scope='saved_controls_only'};gui_case=@{case_id='gui_full_population';iob_path='full100.iob';particle_input='full100.fly2'}}
 }
 function Invoke-CooledPopulationAnalysis {param($Package,$RepoRoot,$Python,$Module,$Materialized,$Times,$PulseTimeUs)
  if($PulseTimeUs-ne1100.-or$Times-ne'common_times.json'){throw 'analysis clock changed'}
  $script:events.Add('cooled_analysis');return @{mother_count=100}}
 function Invoke-FrontendDefaultReplay {param($Materialized,$HostLease,$RunDirectory,$RepoRoot,$Python,$SimionExe,$Limits)
  if(@($Materialized.batches).Count-ne2-or$Materialized.default_replay_policy.scope-ne'saved_controls_only'-or$Materialized.gui_case.particle_input-ne'full100.fly2'){throw 'replay did not retain scheduled cohort and full GUI controls'}
  $script:events.Add('saved_controls_only');return @{passed=$true;mother_count=100}}
 function Write-RunJson {param($Path,$Value,$Depth)$script:summary=$Value}
 $text=Get-Content -LiteralPath $ExecutePath -Raw
 $start=$text.IndexOf(' $stage=''verified_shared_fields_and_snapshot_clock''')
 $end=$text.IndexOf(("`n }`n "+'$okay='),$start)
 if($start-lt0-or$end-lt0){throw 'population branch missing'}
 Invoke-Expression $text.Substring($start,$end-$start)
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
$materialized=@{gui_case=$case;batches=@($case);default_replay_policy=@{comparison_policy='deterministic_trajectory_parity';scope='fresh_process'}}
if($Scenario-eq'saved_controls'){
 $materialized.default_replay_policy=@{comparison_policy='independent_stochastic_collisions';scope='saved_controls_only'}
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
 $result=Invoke-FrontendDefaultReplay -Materialized $materialized -HostLease ([ref]$lease) -RunDirectory $Root -RepoRoot $Repo -Python $Python -SimionExe NOT_NATIVE -Limits @{}
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
$relative='integrations'
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

    def test_native_build_objects_are_not_sent_to_trace_retention(self):
        code = r"""param($Source)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
$calls=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'Apply-RunArtifactRetention'},$true))
if($calls.Count-ne1){throw 'expected one public retention stage'}
if(@($calls[0].CommandElements|Where-Object{$_-is[Management.Automation.Language.CommandParameterAst]-and$_.ParameterName-eq'RemovePaths'}).Count){throw 'native build PAs passed to TRACE-only retention'}
'NATIVE_RETENTION_AUTHORITY=PASS'
"""
        result = self.ps(code, EXECUTE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("NATIVE_RETENTION_AUTHORITY=PASS", result.stdout)

    def test_ordinary_cache_resumes_only_missing_fields_then_hit_without_native(self):
        code=r'''param($Source,$Repo,$Python,$Run,$Cache)
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$node=$ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-CooledOrdinaryFieldBuild'},$true)[0]
Invoke-Expression $node.Extent.Text
$env:COOLED_INERT_CACHE=$Cache
$script:refines=0;$script:exports=0;$script:gem=0;$script:verifies=0;$script:interrupt=$true
function Get-HostResourceBudget {param($Role,$Stage)return @{}}
function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes)return @{stage=$Stage}}
function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$ProtectedCacheKeys)
 if($ProtectedCacheKeys.Count-ne1-or$ProtectedCacheKeys[0].Length-ne64){throw 'published cache key not protected'}
 return @{session=$Session}
}
function Invoke-FrontendRuntimePython {
 param($Python,$RepoRoot,$RunDirectory,$Name,$Arguments,[switch]$Json)
 $prefix="import os;from pathlib import Path;from integrations.workflows.cooled_frontend import runtime as cr;original=cr.field_cache_plan;cr.field_cache_plan=lambda run: original(run,cache_root=Path(os.environ['COOLED_INERT_CACHE']));"
 $Arguments[1]=$prefix+"`n"+$Arguments[1]
 $output=&$Python -B @Arguments
 if($LASTEXITCODE-ne0){throw "actual public cache boundary failed: $Name"}
 if($Json){return (($output-join"`n")|ConvertFrom-Json -Depth 100)}
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
 }elseif($Name-eq'field_verification'){
  $script:verifies++
  if(-not(Test-Path -LiteralPath $Arguments[-2])){throw 'missing actual verification specification'}
  Set-Content -LiteralPath $Arguments[-1] 'INERT_ONLY_NO_NATIVE_VERIFICATION_CLAIM'
 }else{throw "unexpected vendor request $Name"}
}
$package=@{run_dir=$Run;artifact_run_dir=$Run;input_dir=Join-Path $Run inputs;result_dir=Join-Path $Run results}
$lease=@{}
$capacity=@{}
$call=@{Package=$package;FrozenRepoRoot=$Repo;Python=$Python;RuntimeModule='unused';SimionExe='NOT_NATIVE';Limits=@{};HostLease=[ref]$lease;CapacitySession=[ref]$capacity}
try{Invoke-CooledOrdinaryFieldBuild @call;throw 'interruption missing'}catch{if($_.Exception.Message-ne'inert interruption'){throw}}
$script:interrupt=$false
$result=Invoke-CooledOrdinaryFieldBuild @call
if($script:refines-ne8-or$script:exports-ne7-or$script:gem-ne2-or$script:verifies-ne1){throw 'completed members were rebuilt or lost'}
if($result.working_points.Count-ne7-or$result.retained_native_build_objects.Count-ne0){throw 'published fields were materialized'}
foreach($record in $result.working_points){if(-not(Get-Item -LiteralPath $record.path).IsReadOnly){throw 'published field is writable'}}
$again=Invoke-CooledOrdinaryFieldBuild @call
if($script:refines-ne8-or$script:exports-ne7-or$script:gem-ne2-or$script:verifies-ne1){throw 'HIT invoked native work'}
if($again.field_directory-ne$result.field_directory){throw 'HIT changed exact generation'}
'PUBLIC_COOLED_RESUME_AND_HIT=PASS'
'''
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            author,_=cooled_request_fixture(root)
            run=root/"run"
            prepare_cooled_frontend(author,run,REPO,root,run_id="20261022_120000__build__python__cooled-fixture")
            (run/"logs").mkdir();(run/"results").mkdir()
            (run/"inputs/native_discovery.json").write_text(json.dumps(dict(bytes=1,sha256="A"*64,file_version="INERT")))
            try:
                result=self.ps(code,EXECUTE,REPO,sys.executable,run,root/"cache")
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn("PUBLIC_COOLED_RESUME_AND_HIT=PASS",result.stdout)
            finally:
                for path in root.rglob("*"):
                    if path.is_file():
                        path.chmod(0o666)



if __name__ == "__main__":
    unittest.main()
