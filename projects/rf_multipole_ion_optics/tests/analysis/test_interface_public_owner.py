"""Thin interface CLI boundaries; public owner fault behavior is tested elsewhere."""
import csv
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[2]
CLI = PROJECT / "workflows/interface_readiness/run_comsol.ps1"
PROFILES = PROJECT / "config/execution_profiles.json"


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell7 required")
class InterfacePublicOwnerTests(unittest.TestCase):
    def run_ps(self, command):
        result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command], cwd=PROJECT.parents[1],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_limits_reader_and_actual_launcher_forwarding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            launcher = root / "common/comsol/run_comsol_r2025b.ps1"
            launcher.parent.mkdir(parents=True)
            launcher.write_text("param($TaskScript,$ReportPath,$StartupAttempts,$Limits,$ResourceBudgets,$RunId,$RunDir,$UsagePath,$CompletionPath)\n"
                                "if($Limits.wall_clock_seconds-ne17-or$ResourceBudgets.solver.memory_bytes-ne4096-or$StartupAttempts-ne1){throw 'budget transport differs'}\n"
                                "if(-not$UsagePath-or-not$CompletionPath){throw 'completion/usage not forwarded'}\n"
                                "if($TaskScript-like'*gui*'){foreach($name in @('RFQUAD_COMSOL_MODEL_PATH','RFQUAD_SOLVER_RAW_METADATA_PATH','RFQUAD_GUI_RUN_ROOT','RFQUAD_GUI_OBSERVATION_ROOT')){if([Environment]::GetEnvironmentVariable($name,'Process')-notlike'*execution*'){throw 'GUI execution projection missing'}};if($env:RFQUAD_RUN_CONFIG-cne'frozen/config.json'){throw 'GUI config not reset'}}\n"
                                "$global:LASTEXITCODE=0\n", encoding="utf-8")
            (root / "raw.json").write_text('{"release_files":[{"relative_path":"runtime/particle_001.txt"}]}', encoding="utf-8")
            limits = root / "limits.json"
            limits.write_text(json.dumps(dict(wall_clock_seconds=17, transient_run_directory_bytes=8192,
                                              process_tree_working_set_bytes=4096, minimum_system_available_memory_bytes=1024)), encoding="utf-8")
            command = r"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile(CLI,[ref]$t,[ref]$e)
if($e.Count){throw 'entry parse error'}
foreach($name in @('Read-InterfaceExecutionLimits','Invoke-InterfaceComsolTask')){
 $function=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
 . ([ScriptBlock]::Create($function.Extent.Text))
}
$Limits=Read-InterfaceExecutionLimits LIMITS
try{$null=Read-InterfaceExecutionLimits MISSING;throw 'missing accepted'}catch{if($_.Exception.Message-cne'Interface execution LimitsPath is missing.'){throw}}
function Get-RunNativeExecutionContext {param($Package,$Paths,$Tool); $script:requestedPaths=$Paths; @{environment=@{};projected_paths=@($Paths|ForEach-Object{([string]$_).Replace($repoRoot,(Join-Path $repoRoot 'execution'))})}}
$repoRoot=ROOT;$logDir=ROOT;$RunId='fixture';$StartupAttempts=1
$package=@{artifact_run_dir=ROOT;run_config='frozen/config.json'};$ResourceBudgets=@{solver=@{memory_bytes=4096}}
$state=@{calls=[Collections.Generic.List[object]]::new();timer=[Diagnostics.Stopwatch]::StartNew()};$global:LASTEXITCODE=0
Invoke-InterfaceComsolTask -Task 'frozen/task.m' -Report 'report.txt' -Stage native -State $state
$env:RFQUAD_COMSOL_MODEL_PATH=Join-Path ROOT 'model.mph';$env:RFQUAD_SOLVER_RAW_METADATA_PATH=Join-Path ROOT 'raw.json';[Environment]::SetEnvironmentVariable(('RFQUAD_GUI_RUN_'+'R'+'OOT'),ROOT,'Process')
Remove-Item Env:RFQUAD_RUN_CONFIG -ErrorAction SilentlyContinue
$observationName='RFQUAD_GUI_OBSERVATION_'+'R'+'OOT'
[Environment]::SetEnvironmentVariable($observationName,$null,'Process')
$missing=$false;try{Invoke-InterfaceComsolTask -Task 'frozen/gui.m' -Report 'gui.txt' -Stage gui -State $state}catch{if($_.Exception.Message-cne('GUI native path is missing: '+$observationName)){throw};$missing=$true}
if(-not$missing-or$state.calls.Count-ne1){throw 'missing owned observation output reached native'}
[Environment]::SetEnvironmentVariable($observationName,(Join-Path ROOT 'results'),'Process')
Invoke-InterfaceComsolTask -Task 'frozen/gui.m' -Report 'gui.txt' -Stage gui -State $state
if($script:requestedPaths.Count-ne8-or$script:requestedPaths[-1]-cne(Join-Path ROOT 'runtime/particle_001.txt')){throw 'GUI referenced file plan incomplete'}
if(@($script:requestedPaths|Select-Object -Unique).Count-ne$script:requestedPaths.Count){throw 'GUI native input/output path plan contains a duplicate'}
if($script:requestedPaths[6]-cne(Join-Path ROOT 'results')-or[Environment]::GetEnvironmentVariable($observationName,'Process')-cne(Join-Path (Join-Path ROOT 'execution') 'results')){throw 'owned observation root was not projected by the actual native context'}
if($state.calls.Count-ne2-or@($state.calls|Where-Object{-not$_.wrapper_returned}).Count){throw 'actual wrapper return facts missing'}
""".replace('CLI', literal(CLI)).replace('LIMITS', literal(limits)).replace('MISSING', literal(root/'absent.json')).replace('ROOT', literal(root))
            self.run_ps(command)

    def test_original_resume_cli_needs_no_scientific_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "projects/rf_multipole_ion_optics/workflows/interface_readiness/run_comsol.ps1"
            target.parent.mkdir(parents=True)
            shutil.copyfile(CLI, target)
            support = root / "common/contracts/run_artifact_workflow.ps1"
            support.parent.mkdir(parents=True)
            support.write_text("param($ResultPath,[switch]$ResumeFinalization)\n"
                               "function Invoke-RunArtifactWorkflow {param($RequestPath,$ResultPath,[switch]$ResumeFinalization)\n"
                               " if(-not$ResumeFinalization){throw 'not resume'}; @{stage='complete';status=$env:OWNER_FIXTURE_STATUS}}\n", encoding="utf-8")
            run = root / "parent-run"
            run.mkdir()
            (run / "run_config.json").write_text(json.dumps(dict(project="rf_multipole_ion_optics", mode="transport_interface_readiness")), encoding="utf-8")
            result = root / "result.json"
            result.write_text(json.dumps(dict(role="run_artifact_workflow_result", run_directory=str(run))), encoding="utf-8")
            original = result.read_bytes()
            command = r"""
$ErrorActionPreference='Stop';$env:OWNER_FIXTURE_STATUS='success'
& CLI -ResumeFinalization -ResultPath RESULT -PythonExe PYTHON
$env:OWNER_FIXTURE_STATUS='failed';$caught=$false
try{& CLI -ResumeFinalization -ResultPath RESULT -PythonExe PYTHON}catch{if($_.Exception.Message-notlike'*Original execution terminal status=failed*'){throw};$caught=$true}
if(-not$caught){throw 'failed terminal exit swallowed'}
foreach($ignored in @('ReleaseConstructionGate','NumericalExperimentId','StartupAttempts')){
 $args=@{ResumeFinalization=$true;ResultPath=RESULT;PythonExe=PYTHON};$args[$ignored]=$(if($ignored-eq'ReleaseConstructionGate'){$true}elseif($ignored-eq'StartupAttempts'){1}else{'ignored'})
 $rejected=$false;try{& CLI @args}catch{if($_.Exception.Message-notlike'*does not accept new execution options*'){throw};$rejected=$true};if(-not$rejected){throw 'ignored option accepted'}
}
""".replace('CLI', literal(target)).replace('RESULT', literal(result)).replace('PYTHON', literal(sys.executable))
            self.run_ps(command)
            self.assertEqual(result.read_bytes(), original)

    def test_frozen_metrics_and_state_contract_execute_actual_cli_modules(self):
        from common.contracts.particle_state import PARTICLE_STATE_COLUMNS, ion11_sources
        repo = PROJECT.parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ions = root / "ions.ion"
            ions.write_text("0.25,100,1,0,0,0,0,0,2,1,3\n", encoding="utf-8")
            expected = ion11_sources(ions)[1]
            rows = []
            for event in ("source", "terminal"):
                row = {key: 0 for key in PARTICLE_STATE_COLUMNS}
                row.update(expected)
                row.update(particle_id=1, event=event, status="alive" if event == "source" else "transmitted",
                           terminal_reason="none" if event == "source" else "acceptance_surface")
                if event == "terminal":
                    row.update(time_us=1.25, elapsed_time_us=1.)
                row["rf_phase_rad"] = (2 * math.pi * 1.1e6 * row["time_us"] * 1e-6) % (2 * math.pi)
                rows.append(row)
            state = root / "state.csv"
            with state.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=PARTICLE_STATE_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            (root / "raw.json").write_text('{"role":"rf_quadrupole_comsol_raw_solver_metadata"}', encoding="utf-8")
            command = r"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$repoRoot=REPO;$python=PYTHON
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
. (Join-Path $repoRoot 'projects/rf_multipole_ion_optics/runtime/frozen_python_package.ps1')
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile(ENTRY,[ref]$t,[ref]$e)
$list=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$frozenPythonRelativePaths'},$true)
Invoke-Expression $list.Extent.Text
$frozenPythonPackage=New-FrozenPythonPackage -SourceRoot $repoRoot -CodeRoot (Join-Path ROOT 'frozen') -RelativePaths $frozenPythonRelativePaths
$rawMetadataPath=Join-Path ROOT 'raw.json';$particleStatePath=Join-Path ROOT 'state.csv';$summaryPath=Join-Path ROOT 'metrics.json'
$particleTable=Join-Path ROOT 'ions.ion';$stateContractReport=Join-Path ROOT 'contract.json';$frozenInterface=Join-Path $repoRoot 'projects/rf_multipole_ion_optics/variants/quadrupole/config/interface_contract.json'
$resolved=@{drive=@{frequency_Hz=1100000.;phase_rad=0.}}
foreach($name in @('metricsExecution','stateContractExecution')){
 $statement=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq('$'+$name)},$true)
 Invoke-Expression $statement.Extent.Text
 $execution=Get-Variable $name -ValueOnly
 if(-not$execution.module_invoked-or$execution.working_directory-ne$frozenPythonPackage.code_root-or$execution.third_party.Count-ne0){throw 'unexpected module environment'}
 foreach($module in $execution.frozen_modules){if(-not$module.origin.StartsWith($frozenPythonPackage.code_root+[IO.Path]::DirectorySeparatorChar)){throw 'active module fallback'}}
 $execution|ConvertTo-Json -Depth 20|Set-Content (Join-Path ROOT ($name+'.json')) -Encoding utf8
}
""".replace('REPO', literal(repo)).replace('PYTHON', literal(sys.executable)).replace('ENTRY', literal(CLI)).replace('ROOT', literal(root))
            self.run_ps(command)
            self.assertEqual(json.loads((root/"metrics.json").read_text())["hits"], 1)
            self.assertEqual(json.loads((root/"contract.json").read_text())["status"], "PASS")
            for name in ("metricsExecution", "stateContractExecution"):
                execution = json.loads((root/(name+".json")).read_text(encoding="utf-8-sig"))
                self.assertTrue(execution["module_invoked"])
                self.assertEqual(execution["third_party"], [])
                print("FROZEN_EXECUTION_PROVENANCE=" + json.dumps({key: execution[key] for key in
                      ("module", "module_invoked", "working_directory", "frozen_modules", "third_party", "python_no_user_site")}))

    def test_inherited_receipts_aggregate_via_actual_public_owner_helpers(self):
        repo = PROJECT.parents[1]
        with tempfile.TemporaryDirectory() as directory:
            command = r"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path REPO 'common/contracts/run_artifact_workflow.ps1')
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile(ENTRY,[ref]$t,[ref]$e)
$function=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Complete-InterfaceOwner'},$true)
. ([scriptblock]::Create($function.Extent.Text))
function Complete-RunArtifactPowerShellOwner {param($Context,$Status,$Summary,$OutputPaths,$RetentionPreservePaths,$WriterCompletion,$WritersStopped,$OriginalFailure,$ResourceUsagePaths)
 $script:captured=$WriterCompletion
 if(-not$WritersStopped){throw 'expected unknown writer stop'}
 Assert-WorkflowWriterCompletion $WriterCompletion -PowerShellOwner
 return @{stage='complete'}
}
$RunId='fixture';$ownerContext=@{result_path=(Join-Path ROOT 'result.json');run_directory=ROOT;execution_run_directory=ROOT}
Write-RunJson -Path (Join-Path ROOT 'run_config.json') -Value @{inputs=@{}}
foreach($unknown in @($false,$true)){
 $ownerState=@{calls=[Collections.Generic.List[object]]::new();timer=[Diagnostics.Stopwatch]::StartNew();prepare_seconds=0.;writer_unknown=$false;finalization_started=$false}
 foreach($stage in @('native','gui')){
  $path=Join-Path ROOT ($stage+'.json');$errorValue=if($unknown-and$stage-eq'gui'){'unconfirmed'}else{$null}
  $receipt=@{role='comsol_launcher_completion';run_id=$RunId;host_release=@{inherited=$true;token='actual-parent-grant';result=$null;error=$errorValue};operations=@(@{operation_id='attempt-1';observation=@{exit_confirmed=$true;returncode=0;process_id=71;process_started_at_utc_ticks=[long]12345}})}
  $receipt|ConvertTo-Json -Depth 12|Set-Content $path
  $ownerState.calls.Add(@{stage=$stage;receipt=$path;usage=(Join-Path ROOT 'missing');elapsed_seconds=0.;wrapper_returned=$true})
 }
 $caught=$false;try{Complete-InterfaceOwner -Status success -Summary @{}}catch{if(-not$unknown-or$_.Exception.Message-notlike'*expected unknown writer stop*'){throw};$caught=$true}
 if($unknown){if(-not$caught-or-not$ownerState.writer_unknown){throw 'unknown release escaped failure'}}
 else{if($script:captured.operations.Count-ne2-or$script:captured.resource_releases.Count-ne1-or$script:captured.resource_releases[0].release_id-cne'actual-parent-grant'){throw 'inherited grant aggregation differs'}}
}
""".replace('REPO', literal(repo)).replace('ENTRY', literal(CLI)).replace('ROOT', literal(directory))
            self.run_ps(command)

    def test_completed_native_summary_uses_actual_stage_facts(self):
        # Pure project aggregation test: public writer/retention behavior has its
        # own real-owner test below. These receipts are explicitly inert inputs.
        with tempfile.TemporaryDirectory() as directory:
            command = r"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile(ENTRY,[ref]$t,[ref]$e)
$f=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Complete-InterfaceOwner'},$true)
. ([scriptblock]::Create($f.Extent.Text))
function Add-RunArtifactResourceRelease {param($ResourceReleases,$ReleaseId,$Receipt)}
function Assert-WorkflowWriterCompletion {param($Completion,[switch]$PowerShellOwner)}
function Convert-WorkflowOwnerPath {param($Context,$Path);$Path}
function Write-RunJson {param([switch]$Atomic,$Path,$Value,$Depth);$Value|ConvertTo-Json -Depth 64|Set-Content -LiteralPath $Path}
function Complete-RunArtifactPowerShellOwner {
 param($Context,$Status,$Summary,$OutputPaths,$WriterCompletion,$WritersStopped,$OriginalFailure,$ResourceUsagePaths)
 $script:captured=$Summary
 @{stage='complete'}
}
$root=ROOT;$RunId='inert-aggregation';New-Item -ItemType Directory -Force (Join-Path $root 'results'),(Join-Path $root 'comsol')|Out-Null
$ownerContext=@{run_directory=$root;result_path=(Join-Path $root 'result.json')}
@{inputs=@{}}|ConvertTo-Json|Set-Content (Join-Path $root 'run_config.json')
$receipt=Join-Path $root 'receipt.json';@{role='comsol_launcher_completion';run_id=$RunId;host_release=@{inherited=$false};operations=@()}|ConvertTo-Json|Set-Content $receipt
$model=Join-Path $root 'comsol/rf_multipole_ion_optics__model.mph';'inert saved model'|Set-Content $model
$metadata=Join-Path $root 'results/solver_raw_metadata.json'
foreach($case in @('gui_failed','gui_succeeded','metadata_missing')){
 if($case-eq'metadata_missing'){Remove-Item $metadata}else{@{raw_solution_persisted=$true}|ConvertTo-Json|Set-Content $metadata}
 $calls=[Collections.Generic.List[object]]::new()
 $calls.Add(@{stage='native';receipt=$receipt;usage=(Join-Path $root 'absent');wrapper_returned=$true;elapsed_seconds=1.})
 $gui=@{stage='gui';receipt=$receipt;usage=(Join-Path $root 'absent');wrapper_returned=$true;elapsed_seconds=1.}
 if($case-eq'gui_failed'){$gui.wrapper_error='actual stage failed'}
 $calls.Add($gui)
 $ownerState=@{calls=$calls;timer=[Diagnostics.Stopwatch]::StartNew();prepare_seconds=0.;finalization_started=$false;writer_unknown=$false}
 Complete-InterfaceOwner -Status failed -Summary @{role='fixture';failure_stage='comsol_gui_compute_verification'} -Outputs @($model)
 $facts=@($script:captured.completed_computations)
 if($case-eq'metadata_missing'){if($facts.Count){throw 'missing persistence evidence invented completed solve'}}
 else{if($facts.Count-ne1-or$facts[0].gui_verified-ne($case-eq'gui_succeeded')){throw ('GUI fact differs '+$case)}}
 $persisted=Get-Content (Join-Path $root 'summary.json') -Raw|ConvertFrom-Json
 if($persisted.execution_failure_stage-cne'comsol_gui_compute_verification'){throw 'actual GUI failure stage lost before finalization'}
}
""".replace('ENTRY', literal(CLI)).replace('ROOT', literal(directory))
            self.run_ps(command)
    def test_actual_config_rewrite_preserves_public_schema_and_finalizes(self):
        from common.contracts.capacity_ledger import initialize_capacity_ledger
        repo = PROJECT.parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            facade = root / "repo"
            for file in (repo/"common").rglob("*"):
                if file.is_file() and file.suffix in {".py", ".ps1", ".json"} and not any(part in {"assets", "__pycache__"} for part in file.parts):
                    target = facade/file.relative_to(repo)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(file, target)
            registry = json.loads((repo/"config/project_registry.json").read_text(encoding="utf-8"))
            target = facade/"config/project_registry.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(registry), encoding="utf-8")
            project = next(p for p in registry["projects"] if p["project_id"] == "rf_multipole_ion_optics")
            for descriptor in project["retired_project_descriptors"]:
                target = facade/descriptor["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(repo/descriptor["path"], target)
            policy = facade/"common/contracts/artifact_capacity_policy.json"
            document = json.loads(policy.read_text(encoding="utf-8"))
            document.update(target_gib=.125, minimum_free_gib=0)
            policy.write_text(json.dumps(document), encoding="utf-8")
            artifact = root/"artifacts"
            artifact.mkdir()
            initialize_capacity_ledger(artifact, objects=[])
            command = r"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$repoRoot=FACADE;$python=PYTHON;$artifact=ARTIFACT;[Environment]::SetEnvironmentVariable(('SIMULATION_'+'PY'+'THON_EXE'),$python,'Process')
. (Join-Path $repoRoot 'common/contracts/run_artifact_workflow.ps1')
$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile(ENTRY,[ref]$t,[ref]$e)
$assignment=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$runConfig'-and$n.Right.Extent.Text.Contains("role='rf_quadrupole_comsol_run_config'")},$true)
$body=[IO.File]::ReadAllText(ENTRY)
$write=$ast.Find({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.Extent.StartOffset-gt$assignment.Extent.EndOffset-and$n.GetCommandName()-eq'Write-RunJson'-and$n.Extent.Text-eq'Write-RunJson -Value $runConfig -Path $package.run_config'},$true)
if($null-eq$assignment-or$null-eq$write){throw 'actual config assignment/write boundary absent'}
$rewrite=[scriptblock]::Create($body.Substring($assignment.Extent.StartOffset,$write.Extent.EndOffset-$assignment.Extent.StartOffset))
$complete=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Complete-InterfaceOwner'},$true)
. ([scriptblock]::Create($complete.Extent.Text))
foreach($status in @('success','failed')){
 $RunId='20261031_220000__test__python__interface-rewrite-'+$status;$workflowId='transport_interface_readiness'
 $projectArtifact=Join-Path $artifact 'projects/rf_multipole_ion_optics'
 $package=New-RunPackage -Python $python -RepoRoot $repoRoot -ArtifactRoot $projectArtifact -RunId $RunId -Project rf_multipole_ion_optics -Mode $workflowId -Software @('PowerShell software fixture') -RetentionContractEnabled -RetentionClass solver_review -RetentionReason 'inert actual config rewrite' -CapacityLedgerLifecycleEnabled -UseShortExecutionPath -ExecutionRoot (Join-Path $artifact 'execution')
 $authority=Join-Path $package.input_dir 'limits.json';Write-RunJson -Path $authority -Value @{transient_run_directory_bytes=8388608}
 $hostAuthority=Join-Path $package.input_dir 'host.json';Write-RunJson -Path $hostAuthority -Value @{}
 $entry=Join-Path $package.input_dir 'entry.ps1';'throw "must not execute native"'|Set-Content $entry
 $capacity=Enter-ArtifactWorkflowCapacitySession -Python $python -RepoRoot $repoRoot -ArtifactRoot $artifact -RunDirectory $package.artifact_run_dir -CommittedNewBytes 8388608 -ProtectedPaths @($package.artifact_run_dir) -Owner ('run-artifact-workflow:rf_multipole_ion_optics:'+$RunId)
 $ownerContext=Initialize-RunArtifactPowerShellOwner -Python $python -RepoRoot $repoRoot -Package $package -CapacitySession $capacity -EntrypointPath $entry -CommitmentInputPaths @($authority,$hostAuthority)
 $packageOwnedConfig=Get-Content $package.run_config -Raw|ConvertFrom-Json -AsHashtable
 $initialLifecycle=@{artifact_retention=($packageOwnedConfig.artifact_retention|ConvertTo-Json -Compress);capacity_ledger_lifecycle=($packageOwnedConfig.capacity_ledger_lifecycle|ConvertTo-Json -Compress)}
 # All science inputs are inert small files; only the real project rewriter and
 # public lifecycle run. No scientific analysis or native stage is represented.
 foreach($variable in $assignment.FindAll({param($n)$n-is[Management.Automation.Language.VariableExpressionAst]},$true)){
  $name=$variable.VariablePath.UserPath
  if($name-notin@('runConfig','packageOwnedConfig','RunId','workflowId','repoRoot','true','false','null')){Set-Variable -Name $name -Value $authority}
 }
 $bindingDocument=@{}
 foreach($member in $assignment.FindAll({param($n)$n-is[Management.Automation.Language.MemberExpressionAst]-and$n.Expression.Extent.Text-eq'$bindingDocument'},$true)){$bindingDocument[$member.Member.Value]='inert'}
 $compiledNumerics=@{authority=@{contract_id='fixture';logical_sha256=('A'*64)};selection=@{profile_id='fixture';numerical_experiment_id=''};trajectory=@{rf_steps_per_period=80;maximum_time_us=1.};mesh=@{global_auto_level=9}}
 $codeRoot=Join-Path $package.input_dir 'code';New-Item -ItemType Directory -Force $codeRoot|Out-Null
 $codeFile=Join-Path $codeRoot 'fixture.py';'# inert source'|Set-Content $codeFile
 $compiledScientificSpec=@{fixture='no-science'}
 $frozenPythonPackage=@{schema_version=1;code_root=$codeRoot;package_roots=@($codeRoot);files=@(@{relative_path='fixture.py';path=$codeFile;sha256=(Get-RunFileSha256 $codeFile)})}
 $frozenPythonExecution=@{module_invoked=$false;working_directory=$codeRoot};$bundleInputPaths=@{}
 $expectedParticles=1;$OperatingPoint='fixture';$StartupAttempts=1;$ReleaseConstructionGate=$false
 $runDir=$package.run_dir;$resultDir=$package.result_dir;$candidateDir=$package.result_dir;$runtimeDir=$package.result_dir;$logDir=$package.log_dir
 . $rewrite
 $actual=Get-Content $package.run_config -Raw|ConvertFrom-Json -AsHashtable
 if($actual.schema_version-ne2-or$actual.schema_version-ne$packageOwnedConfig.schema_version){throw 'public schema overwritten'}
 if($actual.inputs.execution_request-cne$ownerContext.request_path-or-not$actual.inputs.execution_request.StartsWith($ownerContext.run_directory)){throw 'persistent request binding lost'}
 foreach($key in $initialLifecycle.Keys){if(($actual[$key]|ConvertTo-Json -Compress)-cne$initialLifecycle[$key]){throw 'lifecycle fields changed'}}
 if($actual.inputs.resolved_design-cne$authority-or$actual.inputs.native_execution_limits-cne$authority-or$actual.inputs.native_host_budgets-cne$hostAuthority){throw 'project input binding lost'}
 $original=$null;if($status-eq'failed'){try{throw 'original interface analysis failure'}catch{$original=$_}}
 $output=Join-Path $package.result_dir 'data.json';Write-RunJson -Path $output -Value @{fixture=$true}
 $nativeModel=Join-Path $package.run_dir 'comsol/native.mph';New-Item -ItemType Directory -Force (Split-Path $nativeModel)|Out-Null;'inert native saved bytes'|Set-Content $nativeModel
 $aliasBefore=[string]$package.execution_alias
 $ownerState=@{calls=[Collections.Generic.List[object]]::new();timer=[Diagnostics.Stopwatch]::StartNew();prepare_seconds=0.;writer_unknown=$false;finalization_started=$false}
 Complete-InterfaceOwner -Status $status -Summary @{role='rf_quadrupole_transport_summary';scientific_result='NOT_EVALUATED'} -Outputs @($output,$nativeModel) -Failure $original
 if(-not(Test-Path (Join-Path $ownerContext.run_directory 'comsol/native.mph'))){throw 'solver_review removed the sole saved native model'}
 if(Test-Path -LiteralPath $aliasBefore){throw 'completed owner execution alias remains'}
 $persisted=Get-Content (Join-Path $ownerContext.run_directory 'run_config.json') -Raw|ConvertFrom-Json -AsHashtable
 foreach($name in @('run_dir','results_dir','comsol_dir','runtime_dir','logs_dir')){
  if(-not(Test-Path -LiteralPath $persisted[$name])-or(Test-WorkflowPathWithin $persisted[$name] $aliasBefore)){throw ('unusable persistent directory '+$name)}
 }
 foreach($name in $persisted.inputs.Keys){
  $path=$persisted.inputs[$name]
  if($path-is[string]-and[IO.Path]::IsPathFullyQualified($path)){
   if(-not(Test-Path -LiteralPath $path)-or(Test-WorkflowPathWithin $path $aliasBefore)){throw ('unusable persistent input '+$name)}
  }
 }
 $frozen=$persisted.frozen_python.package
 foreach($path in @($frozen.code_root)+@($frozen.package_roots)+@($frozen.files|ForEach-Object path)){
  if(-not(Test-Path -LiteralPath $path)-or(Test-WorkflowPathWithin $path $aliasBefore)){throw 'frozen package source lost after cleanup'}
 }
 if($persisted.inputs.execution_request-cne$ownerContext.request_path){throw 'persistent execution request changed'}
 if($persisted.frozen_python.execution.working_directory-cne$codeRoot){throw 'historical execution observation rewritten'}
 $result=Get-Content $ownerContext.result_path -Raw|ConvertFrom-Json
 if($result.stage-ne'complete'-or$result.status-cne$status){throw 'actual rewritten owner did not finalize'}
 if($status-eq'failed'-and$result.exception.message-cne'original interface analysis failure'){throw 'original failure lost'}
 $manifest=Get-Content (Join-Path $ownerContext.run_directory 'run_manifest.json') -Raw|ConvertFrom-Json
 if($manifest.status-cne$status){throw 'terminal publication differs'}
 Write-Output ('ACTUAL_INTERFACE_REWRITE_FINALIZED='+$status)
}
""".replace('FACADE', literal(facade)).replace('PYTHON', literal(sys.executable)).replace('ARTIFACT', literal(artifact)).replace('ENTRY', literal(CLI))
            output = self.run_ps(command)
            self.assertIn("ACTUAL_INTERFACE_REWRITE_FINALIZED=success", output)
            self.assertIn("ACTUAL_INTERFACE_REWRITE_FINALIZED=failed", output)

    def test_real_profile_exposes_required_file_binding(self):
        profile = next(p for p in json.loads(PROFILES.read_text(encoding="utf-8"))["profiles"]
                       if p["profile_id"] == "quadrupole_transport_interface_readiness_candidate")
        self.assertIn("comsol_execution_limits_path", profile["required_bindings"])
        step = next(s for s in profile["steps"] if s["step_id"] == "comsol_run")
        self.assertEqual(step["arguments"][step["arguments"].index("-LimitsPath")+1], "{comsol_execution_limits_path}")
