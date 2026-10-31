"""Thin production-adapter behavior; shared lifecycle/scheduler matrices live in common."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[4]
RELATIVE = Path("projects/single_reflection_oa_tof_mass_analyzer/workflows/reflectron_voltage_compensation")
ADAPTER = ROOT / RELATIVE / "execute_compensation.ps1"


PYTHON_ACTIONS = r'''
import argparse,hashlib,json,os
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--action');p.add_argument('--run');p.add_argument('--label');p.add_argument('--index');p.add_argument('--process-record');p.add_argument('--dispatch-plan');a,_=p.parse_known_args()
root=Path(os.environ['FIXTURE_ROOT']); mode=os.environ['FIXTURE_MODE']
with (root/'events').open('a', encoding='utf-8') as f:f.write('action:'+a.action+(':'+a.label if a.label else '')+'\n')
run=Path(a.run) if a.run else None
if a.action=='inspect':
    source=root/'source.pa'
    record={'path':str(source),'bytes':source.stat().st_size,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    value={'source_run':str(root/'parent'),'predecessor_manifest':None,'committed_new_bytes':10,'source_manifest':{},'runtime_files':[{'relative_path':'field.pa1' if mode=='native_family' else 'field.pa','pa':True,'record':record}],'producer':None if mode in ['reuse','analysis_failure','finalization_failure','native_family'] else {},'protected_cache_keys':[]}
elif a.action=='freeze':
    value={'frozen_code_root':str(root),'basis_export_required':mode=='producer_fresh'}
elif a.action=='fit':
    modes=[]
    for label in ['baseline','compensated','ideal_reflectron']:
        estimation={'kind':'profile'}
        if mode=='formal':estimation={'kind':'formal_first_batch_observation'}
        if mode=='recovered':estimation={'kind':'profile','recovered_missing_observation':True,'observed_missing_batch_index':1}
        path=run/('results/'+label+'.dispatch_plan.json');path.write_text(json.dumps({'estimation':estimation}), encoding='utf-8')
        modes.append({'label':label,'all_reused':(mode in ['reuse','analysis_failure','finalization_failure'] or mode=='producer_reuse'),'reused_batch_indices':[0],'dispatch_plan':str(path)})
    value={'modes':modes,'native_fly_required':(mode not in ['reuse','analysis_failure','finalization_failure'] and mode!='producer_reuse')}
elif a.action=='materialize':
    for name in ['oatof_ideal_grounded.lua','reflectron_voltage_profile.lua']:(run/'simion'/name).write_text('immutable', encoding='utf-8')
    value={}
elif a.action=='producer-spec':
    value={'name':'field_provider','script_path':str(root/'inert-producer.ps1'),'parameters':{'Run':str(run)},'environment':{'OATOF_REFLECTRON_VOLTAGE_COMPENSATION':'0'}}
elif a.action=='producer-complete':
    value={'writers_stopped':mode!='producer_unknown','failure_reason':None,'runtime_prepared':True,'iob_ready':True,
      'control_binding':{'iob_path':str(run/'simion/oatof_ideal_grounded.iob'),'program_path':str(run/'simion/oatof_ideal_grounded.lua'),'source_ion_path':str(run/'inputs/source.ion')},
      'writer_completion':{'operations':[{'operation_id':'build','observation':{'exit_confirmed':True,'returncode':0,'process_id':42,'process_started_at_utc_ticks':77},'resource_release_id':'producer'}],
      'resource_releases':[{'release_id':'producer','completion_receipt':{'host_release':{'inherited':True,'token':'fixture','result':None,'error':None}}}]}}
elif a.action=='export-spec':
    value={'name':'basis','file_path':'inertbasis','argument_list':[],'working_directory':str(run),'stdout_path':str(run/'logs/iob.stdout'),'stderr_path':str(run/'logs/iob.stderr')}
elif a.action=='materialize-batches':
    batches=[]
    for index in [0,1]:
        batches.append({'batch':{'index':index,'count':1},'reused':index==0,'name':a.label+str(index),'file_path':'inert','argument_list':[],'working_directory':str(run),'stdout_path':str(run/'logs/out'),'stderr_path':str(run/'logs/err'),'environment':{'COMPENSATION':a.label},'ion':'inert'})
    value={'batches':batches}
elif a.action=='complete-batch':
    assert json.loads(Path(a.process_record).read_text(encoding='utf-8-sig'))['completed'] is True
    value={}
elif a.action=='analyze':
    if mode=='analysis_failure':raise RuntimeError('ANALYSIS_SENTINEL')
    value={'scientific_result':'INCONCLUSIVE'}
else:raise RuntimeError(a.action)
print(json.dumps(value))
'''


OWNER_FIXTURE = r'''
$script:python=$env:FIXTURE_PYTHON
function Event($Value){Add-Content -LiteralPath (Join-Path $env:FIXTURE_ROOT 'events') -Value $Value}
function Write-RunJson {param($Path,$Value,$Depth=100,[switch]$Atomic);[IO.Directory]::CreateDirectory((Split-Path -Parent $Path))|Out-Null;$Value|ConvertTo-Json -Depth $Depth|Set-Content -LiteralPath $Path -Encoding utf8}
function Invoke-RunToolRootContext {param($RepoRoot,$Operation);Push-Location $RepoRoot;try{& $Operation}finally{Pop-Location}}
function Enter-RunTerminalConsumptionGuard {param($RunDirectory);Event reader;return [IO.MemoryStream]::new()}
function Enter-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$ArtifactRoot,$RunDirectory,$CommittedNewBytes,$ProtectedPaths,$ProtectedCacheKeys,$Owner);Event capacity;return @{}}
function Exit-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session);Event capacity_exit}
function New-RunPackage {
 param($Python,$RepoRoot,$ArtifactRoot,$RunId,$Project,$Mode,$Software,[switch]$RetentionContractEnabled,$RetentionClass,$RetentionReason,[switch]$CapacityLedgerLifecycleEnabled,$AdditionalDirectories,$PathContext)
 if($null-eq$PathContext-or$PathContext.host_resource_state_path-cne$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH-or$ArtifactRoot-cne(Join-Path $PathContext.artifact_root 'projects/single_reflection_oa_tof_mass_analyzer')){throw 'Package must freeze the selected workspace context'}
 $run=Join-Path $ArtifactRoot ('runs/'+$RunId);foreach($d in @('inputs','results','logs','simion')){[IO.Directory]::CreateDirectory((Join-Path $run $d))|Out-Null}
 $config=Join-Path $run 'run_config.json';Write-RunJson $config @{inputs=@{}}
 return @{artifact_run_dir=$run;run_dir=$run;input_dir=(Join-Path $run 'inputs');result_dir=(Join-Path $run 'results');log_dir=(Join-Path $run 'logs');run_config=$config}
}
function Copy-VerifiedRunInput {param($Source,$Destination,$VerifiedIdentity);Copy-Item -LiteralPath $Source -Destination $Destination;$VerifiedIdentity.Value=@{path=$Destination;bytes=(Get-Item $Destination).Length;sha256=('a'*64)}}
function Initialize-RunArtifactPowerShellOwner {param($Python,$RepoRoot,$Package,$CapacitySession,$ResultPath,$EntrypointPath,$EntrypointRecord,$CommitmentInputPaths,$Software);Event owner;if($env:FIXTURE_MODE-eq'release_failure'){Write-RunJson (Join-Path $env:FIXTURE_ROOT 'result.json') @{role='run_artifact_workflow_result';stage='prepared';exception=$null;secondary_errors=@();terminal_published=$false;capacity_finalized=$false;lease_released=$false}};$request=Join-Path $Package.input_dir 'execution_request.json';Write-RunJson $request @{};return @{result_path=(Join-Path $env:FIXTURE_ROOT 'result.json');request_path=$request}}
function Complete-RunArtifactPowerShellOwner {
 param($Context,$Status,$Summary,$OutputPaths,$WriterCompletion,$WritersStopped,$OriginalFailure)
 Event ('finalize:'+ $WritersStopped)
 Write-RunJson (Join-Path $env:FIXTURE_ROOT 'completion.json') @{status=$Status;summary=$Summary;writers_stopped=$WritersStopped;facts=$WriterCompletion}
 Write-RunJson $Context.result_path @{role='run_artifact_workflow_result';exception=$Summary.failure_reason;secondary_errors=@()}
 if($env:FIXTURE_MODE-eq'finalization_failure'){throw 'FINALIZATION_SENTINEL'}
 if(-not$WritersStopped){throw 'UNKNOWN_WRITER_FINALIZATION'}
}
function Invoke-RunArtifactWorkflow {param($RequestPath,$ResultPath,[switch]$ResumeFinalization);Event resume;return @{status='success'}}
function Get-RunNativeExecutionContext {param($Package,$Paths,$Tool);Event public_context;return @{run_dir=$Package.run_dir;projected_paths=$Paths;environment=@{MASS_SPECTROMETRY_RUN_DIRECTORY=$Package.artifact_run_dir}}}
function Project-RunPath {param($Paths,$ArtifactRunDir,$RunDir,$Python);return ,@($Paths)}
function Enter-HostExecutionLease {param($Role,$Stage,$StatePath);Event lease;return @{inherited=$false;token='fixture';state_path='inert'}}
function Update-HostResourceStage {param($Lease,$Stage,$Budget,[Parameter(Mandatory)]$RetainedMemoryBytes);Event transition;return $Lease}
function Get-HostResourceBudget {param($Role,$Stage);return @{}}
function Exit-HostResourceStage {param($Lease,[switch]$PassThru);Event release;if($env:FIXTURE_MODE-eq'release_failure'){throw 'RELEASE_SECONDARY_SENTINEL'};return @{status='released';token='fixture'}}
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$UsagePath,$FilePath,$ArgumentList,$WorkingDirectory,$RedirectStandardOutput,$RedirectStandardError,$Environment)
 if($FilePath-ne'inertbasis'){throw 'Only the basis exporter may use the direct native adapter'}
 Event native_basis;return @{exit_code=0;resource_budget_exceeded=$false;root_process_id=123;root_process_started_at_utc_ticks=1}
}
function Invoke-SimionBatchPhase {
 param($DispatchPlanPath,$RunDir,$UsagePath,$PrepareRemaining,$FirstSpecification,$Replan,$OnProcessCompleted)
 Event wave
 if($env:FIXTURE_MODE-eq'release_failure'){$e=[Exception]::new('FLY_PRIMARY_SENTINEL');$e.Data['simion_wave_writer_completion_confirmed']=$true;throw $e}
 foreach($name in @('oatof_ideal_grounded.lua','reflectron_voltage_profile.lua')){
   $blocked=$false
   try{$writer=[IO.File]::Open((Join-Path $RunDir ('simion/'+$name)),[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::Read);$writer.Dispose()}
   catch [IO.IOException]{$blocked=$true}
   if(-not$blocked){throw 'Fly controls must be guarded after the builder exits.'}
 }
 if($env:FIXTURE_MODE-eq'unknown'){$e=[Exception]::new('UNKNOWN_WRITER_SENTINEL');$e.Data['simion_wave_writer_completion_confirmed']=$false;throw $e}
 if($null-ne$FirstSpecification){
   Event ('formal:'+ $FirstSpecification.name)
   $record=[pscustomobject]@{name=$FirstSpecification.name;completed=$true;exit_code=0;root_process_id=125;root_process_started_at_utc_ticks=3;specification=$FirstSpecification}
   & $OnProcessCompleted $record
   & $Replan ([pscustomobject]@{process_record=$record;observed_peak_process_tree_working_set_bytes=100;observed_process_cpu_percent=1;observed_background_cpu_percent=1;available_memory_bytes=1000;total_physical_memory_bytes=2000})
 }
 $prepared=& $PrepareRemaining $null;$records=@()
 foreach($spec in $prepared.pending){
   Event ('dispatch:'+ $spec.name+':'+$spec.environment.COMPENSATION)
   $record=[pscustomobject]@{name=$spec.name;completed=$true;exit_code=0;root_process_id=124;root_process_started_at_utc_ticks=2;specification=$spec}
   & $OnProcessCompleted $record;$records+=@($record)
 }
 return @{resource_budget_exceeded=$false;processes=$records}
}
function Complete-ResourceUsage {param($RunDir,$UsagePath);Event usage}
'''


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell required")
class CompensationPowerShellAdapterTests(unittest.TestCase):
    def test_native_consumers_use_one_public_context_for_paths_environment_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "paths.ps1"
            script.write_text(r'''param($Repo,$Adapter,$Root,$Python)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $Repo 'common/paths/workspace_paths.ps1')
$configuredPaths=Resolve-WorkspacePaths -SourceRoot $Repo -ArtifactRoot (Join-Path $Root 'configured-artifacts') -ExecutionRoot (Join-Path $Root 'exec') -HostResourceStatePath (Join-Path $Root 'host.sqlite3') -Python $Python
$run=Join-Path $configuredPaths.artifact_root 'projects/test/runs/fixture'
foreach($d in @('logs','results','simion')){[IO.Directory]::CreateDirectory((Join-Path $run $d))|Out-Null}
$package=[pscustomobject]@{artifact_run_dir=$run;run_dir=$run;execution_alias=$null;execution_path_capacity=$null;python=$Python;path_context=$configuredPaths}
$ast=[Management.Automation.Language.Parser]::ParseFile($Adapter,[ref]$null,[ref]$null)
foreach($name in @('Invoke-CompensationNative','Convert-CompensationBatch')){
 $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
 Invoke-Expression $node.Extent.Text
}
$script:run=$run;$python=$Python;$script:writersStopped=$true;$script:called=0
function Add-CompensationOperation {param($Name,$Record);if($Record.root_process_id-ne42){throw 'Lost native fact'}}
function Invoke-ResourceBudgetedProcess {param($Limits,$RunDir,$UsagePath,$FilePath,$ArgumentList,$WorkingDirectory,$RedirectStandardOutput,$RedirectStandardError,$Environment)
 if($WorkingDirectory-cne(Join-Path $run 'simion')-or$ArgumentList[1]-cne(Join-Path $run 'simion/input.iob')){throw 'Path projection differs'}
 if($RedirectStandardOutput-cne(Join-Path $run 'logs/out')-or$RedirectStandardError-cne(Join-Path $run 'logs/err')){throw 'Log projection differs'}
 if($Environment.MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH-cne$configuredPaths.host_resource_state_path-or$Environment.MASS_SPECTROMETRY_ARTIFACT_ROOT-cne$configuredPaths.artifact_root){throw 'Context roots differ'}
 $script:called++;return @{exit_code=0;resource_budget_exceeded=$false;root_process_id=42;root_process_started_at_utc_ticks=1}
}
$spec=[pscustomobject]@{name='basis';file_path='inert';argument_list=@('fly',(Join-Path $run 'simion/input.iob'));working_directory=(Join-Path $run 'simion');stdout_path=(Join-Path $run 'logs/out');stderr_path=(Join-Path $run 'logs/err');environment=[pscustomobject]@{ARM='compensated'};batch=@{index=1}}
Invoke-CompensationNative $spec
$batch=Convert-CompensationBatch $spec
if($script:called-ne1-or$batch.environment.ARM-cne'compensated'-or$batch.environment.MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH-cne$configuredPaths.host_resource_state_path-or$batch.stdout-cne$spec.stdout_path){throw 'Batch context differs'}
if($null-ne$package.execution_alias){throw 'Short plan must not create an alias'}
Write-Output 'PUBLIC_CONTEXT_PASS'
''', encoding="utf-8", newline="\n")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(ROOT), str(ADAPTER), str(root), sys.executable],
                                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PUBLIC_CONTEXT_PASS", result.stdout)

    def test_public_python_cli_transports_only_requested_resume_inputs(self):
        import argparse
        import ast
        import types

        source = ADAPTER.with_name("run_compensation.py")
        tree = ast.parse(source.read_text(encoding="utf-8"))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {"main", "_load"}]
        launch = unittest.mock.Mock()
        namespace = dict(__file__=str(source), __doc__="actual public CLI transport",
            argparse=argparse, json=json, Path=Path, sys=sys, Any=object, REPO_ROOT=ROOT,
            LABELS=("baseline", "compensated", "ideal_reflectron"), subprocess=types.SimpleNamespace(run=launch))
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), namespace)
        with patch.object(sys, "argv", [str(source), "--resume-finalization", "--run-id", "existing", "--result-path", "original-result.json"]):
            namespace["main"]()
        command = launch.call_args.args[0]
        self.assertEqual(command[command.index("-PythonExe")+1], sys.executable)
        self.assertEqual(command[command.index("-ResultPath")+1], "original-result.json")
        self.assertIn("-ResumeFinalization", command)
        self.assertNotIn("-SimionExe", command)
        self.assertNotIn("-ParticleCount", command)
        self.assertEqual(launch.call_args.kwargs, dict(cwd=ROOT, timeout=None, check=True))
        launch.reset_mock()
        for option in ("--case-dir", "--numerics-path", "--resume-from", "--particle-count"):
            value = "100" if option == "--particle-count" else "must-not-read"
            with self.subTest(option=option), patch.object(sys, "argv", [str(source), "--resume-finalization", "--run-id", "existing", option, value]), self.assertRaises(SystemExit) as raised:
                namespace["main"]()
            self.assertEqual(raised.exception.code, 2)
        launch.assert_not_called()

    def test_resume_binding_rejects_new_science_before_source_or_owner_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/"binding.ps1"
            script.write_text(r'''param($Entry)
$ErrorActionPreference='Stop';$cases=@()
foreach($option in @('CaseDirectory','SimionExe','NumericsPath','ParticleCount')){
 $arguments=@{ResumeFinalization=$true;RunId='existing'}
 $arguments[$option]=if($option-eq'ParticleCount'){100}else{'must-not-read'}
 try{& $Entry @arguments;$cases+=@{option=$option;type='unexpected_success';id=''}}
 catch{$cases+=@{option=$option;type=$_.Exception.GetType().FullName;id=$_.FullyQualifiedErrorId}}
}
ConvertTo-Json -InputObject @($cases) -Compress
''', encoding="utf-8")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(ADAPTER)], cwd=ROOT,
                capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            cases = json.loads(result.stdout)
            self.assertEqual(len(cases), 4)
            for case in cases:
                with self.subTest(option=case["option"]):
                    self.assertEqual(case["type"], "System.Management.Automation.ParameterBindingException")
                    self.assertTrue(case["id"].startswith("AmbiguousParameterSet,"), case)
    def test_inherited_finalization_keeps_actual_null_without_releasing_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/"inherited.ps1"
            script.write_text(r'''param($Entry,$Repo,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_workflow.ps1')
function Invoke-HostResourceTransaction {throw 'PARENT_TRANSACTION_MUST_NOT_RUN'}
$ast=[Management.Automation.Language.Parser]::ParseFile($Entry,[ref]$null,[ref]$null)
$ownerTry=$ast.Find({param($n)$n-is[Management.Automation.Language.TryStatementAst]-and$null-ne$n.Finally-and$null-ne$n.Finally.Find({param($command)$command-is[Management.Automation.Language.CommandAst]-and$command.GetCommandName()-eq'Complete-RunArtifactPowerShellOwner'},$true)},$true)
if($null-eq$ownerTry){throw 'Missing actual compensation owner finalizer'}
$script:owner=@{result_path=(Join-Path $Root 'result.json')};$script:writersStopped=$true
$script:lease=@{inherited=$true;environment_set=$false;token='real-parent-grant'}
$script:operations=[ordered]@{inert=@{operation_id='inert-consumer-contract';resource_release_id='simion';observation=@{exit_confirmed=$true;returncode=0;process_id=$PID;process_started_at_utc_ticks=(Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks}}}
$script:run=$Root;$script:executionAlias=$null;$script:readers=@();$script:controlGuards=@();$script:capacity=$null
$science=@{};$failure=$null;$finalizationFailure=$null;$timings=@{};$clock=[Diagnostics.Stopwatch]::StartNew()
function Set-CompensationStage {param($Name)}
function Complete-RunArtifactPowerShellOwner {
 param($Context,$Status,$Summary,$OutputPaths,$WriterCompletion,$WritersStopped,$OriginalFailure)
 Assert-WorkflowWriterCompletion $WriterCompletion -PowerShellOwner
 $receipt=$WriterCompletion.resource_releases[0].completion_receipt.host_release
 if(-not$receipt.inherited-or$receipt.token-ne'real-parent-grant'-or$null-ne$receipt.result){throw 'Consumer invented inherited acquired/released result'}
 $script:validated=$true
}
$before=$env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN
Invoke-Expression $ownerTry.Finally.Extent.Text.TrimStart('{').TrimEnd('}')
if(-not$script:validated-or$null-ne$script:lease-or$null-ne$finalizationFailure-or$env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN-cne$before){throw 'Parent ownership or actual receipt changed'}
''', encoding="utf-8")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(ADAPTER), str(ROOT), directory],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_original_cli_resumes_actual_public_result_without_reexecuting_prepared_work(self):
        from common.contracts.test_run_artifact_workflow import RunArtifactWorkflowTests

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = RunArtifactWorkflowTests("runTest")
            invoke = fixture.run_ps
            def bind_compensation_mode(fixture_root, script):
                request_path = fixture_root/"request.json"
                request = json.loads(request_path.read_text(encoding="utf-8"))
                request["package"]["mode"] = "reflectron_voltage_compensation"
                request_path.write_text(json.dumps(request), encoding="utf-8")
                return invoke(fixture_root, script)
            environment = dict(os.environ)
            for name in ("MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN", "MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID", "MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE"):
                environment.pop(name, None)
            environment["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"] = str(root/"host.sqlite3")
            with patch.dict(os.environ, environment, clear=True), patch.object(fixture, "run_ps", side_effect=bind_compensation_mode):
                _, run, _, initial = fixture.invoke_fixture(root, {}, retention="solver_review",
                    failure_stage="retention_before", project="single_reflection_oa_tof_mass_analyzer", host_state=str(root/"host.sqlite3"))
            self.assertNotEqual(initial.returncode, 0)
            counter = (root/"callback_count.txt").read_bytes()
            target = root/"repo"/RELATIVE
            target.mkdir(parents=True)
            shutil.copyfile(ADAPTER, target/"execute_compensation.ps1")
            # The real public PS owner is shared; its request freezes the real
            # Python repository. Only the original CLI's dispatch location varies.
            for source in (ROOT/"common").rglob("*"):
                if source.is_file() and source.suffix in {".ps1", ".json"} and "history" not in source.parts:
                    destination = root/"repo"/source.relative_to(ROOT)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
            shutil.copyfile(ROOT/"common/paths/workspace_paths.py", root/"repo/common/paths/workspace_paths.py")
            command = ["pwsh", "-NoProfile", "-File", str(target/"execute_compensation.ps1"),
                "-ResumeFinalization", "-RunId", run.name, "-ResultPath", str(root/"result.json"), "-PythonExe", sys.executable]
            environment["MASS_SPECTROMETRY_ARTIFACT_ROOT"] = str(root/"different-default-artifacts")
            environment["MASS_SPECTROMETRY_EXECUTION_ROOT"] = str(root/"different-default-execution")
            for attempt in (1, 2):
                result = subprocess.run(command, cwd=root/"repo", env=environment,
                    capture_output=True, text=True, encoding="utf-8", timeout=60)
                self.assertEqual(result.returncode, 0, f"attempt={attempt}\n"+result.stdout+result.stderr)
                outcome = json.loads((root/"result.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(outcome["stage"], "complete")
                self.assertTrue(outcome["lease_released"])
                self.assertTrue(outcome["terminal_published"])
                self.assertTrue(outcome["capacity_finalized"])
                self.assertEqual((root/"callback_count.txt").read_bytes(), counter)
            wrong = list(command)
            wrong[wrong.index("-RunId") + 1] = "20261028_120001__test__python__wrong-run"
            rejected = subprocess.run(wrong, cwd=root/"repo", env=environment,
                capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("Result RunId binding differs", rejected.stderr)
            self.assertEqual((root/"callback_count.txt").read_bytes(), counter)

    def test_safe_producer_worker_facts_share_one_outer_release(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "producer_facts.ps1"
            script.write_text(r'''param($Entry,$LeaseSupport)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Entry,[ref]$null,[ref]$null)
foreach($name in @('Add-CompensationOperation','Add-CompensationProducerCompletion')){
  $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
  Invoke-Expression $node.Extent.Text
}
$script:operations=[ordered]@{};$script:lease=@{token='outer-grant'}
$leaseAst=[Management.Automation.Language.Parser]::ParseFile($LeaseSupport,[ref]$null,[ref]$null)
$exitNode=$leaseAst.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Exit-HostResourceStage'},$true)
Invoke-Expression $exitNode.Extent.Text
$inheritedResult=Exit-HostResourceStage -Lease @{inherited=$true;environment_set=$false} -PassThru
$completion=[pscustomobject]@{writers_stopped=$true;writer_completion=@{
  operations=@(@{operation_id='managed-build';observation=@{exit_confirmed=$true;returncode=0;process_id=42;process_started_at_utc_ticks=77};resource_release_id='producer'});
  resource_releases=@(@{release_id='producer';completion_receipt=@{host_release=@{inherited=$true;token='outer-grant';result=$inheritedResult;error=$null}}})}}
Add-CompensationProducerCompletion $completion
if(-not$script:writersStopped-or$script:operations.Count-ne1){throw 'Validated producer was not adopted'}
$fact=$script:operations['producer.managed-build']
if($fact.resource_release_id-ne'simion'-or$fact.observation.process_id-ne42-or$fact.observation.process_started_at_utc_ticks-ne77){throw 'Producer worker identity was replaced by launcher or outer host'}
$completion.writer_completion.resource_releases[0].completion_receipt.host_release.token='different-owner'
$caught=$false;try{Add-CompensationProducerCompletion $completion}catch{$caught=$true}
if(-not$caught-or$script:writersStopped){throw 'Wrong producer token was accepted'}
$completion.writers_stopped=$false
$caught=$false;try{Add-CompensationProducerCompletion $completion}catch{$caught=$true}
if(-not$caught-or$script:writersStopped){throw 'Unknown producer writer was accepted'}
''', encoding="utf-8")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script),
                str(ADAPTER), str(ROOT / 'common/host_execution_lease.ps1')], cwd=ROOT,
                text=True, encoding="utf-8", capture_output=True, check=False, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def run_fixture(self, mode: str, *, resume: bool = False) -> tuple[subprocess.CompletedProcess[str], list[str], dict]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            target = root / RELATIVE
            target.mkdir(parents=True)
            shutil.copyfile(ADAPTER, target / "execute_compensation.ps1")
            (root / "common/paths").mkdir(parents=True)
            for filename in ("workspace_paths.ps1", "workspace_paths.py"):
                shutil.copyfile(ROOT / "common/paths" / filename, root / "common/paths" / filename)
            (root / "common/contracts").mkdir(parents=True)
            (root / "common/simion").mkdir(parents=True)
            (root / "common/contracts/run_artifact_workflow.ps1").write_text(OWNER_FIXTURE + r'''
$publicAst=[Management.Automation.Language.Parser]::ParseFile($env:FIXTURE_PUBLIC_OWNER_SOURCE,[ref]$null,[ref]$null)
$release=$publicAst.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Add-RunArtifactResourceRelease'},$true)
Invoke-Expression $release.Extent.Text
''', encoding="utf-8")
            (root / "source.pa").write_bytes(b"inert byte transport fixture, no native PA")
            (root / "common/simion/resource_profile.py").write_text("", encoding="utf-8")
            (root / "common/simion/resource_scheduler.py").write_text(
                "import os,sys\nfrom pathlib import Path\n"
                "with (Path(os.environ['FIXTURE_ROOT'])/'events').open('a', encoding='utf-8') as f: f.write('replan:'+sys.argv[1]+'\\n')\n",
                encoding="utf-8",
            )
            (target / "run_compensation.py").write_text(PYTHON_ACTIONS, encoding="utf-8")
            (root / "inert-producer.ps1").write_text(r'''param($Run)
Event producer
if($env:PYTHONDONTWRITEBYTECODE-ne'1'){throw 'Producer may mutate frozen code with bytecode caches'}
if($env:OATOF_REFLECTRON_VOLTAGE_COMPENSATION-ne'0'){throw 'Producer inherited a compensation arm'}
foreach($name in @('oatof_ideal_grounded.iob','oatof_ideal_grounded.lua','reflectron_voltage_profile.lua')){
  [IO.File]::WriteAllText((Join-Path $Run ('simion/'+$name)),'inert producer control')
}
[IO.File]::WriteAllText((Join-Path $Run 'inputs/source.ion'),'same frozen source')
if($env:FIXTURE_MODE-eq'producer_failure'){throw 'PRODUCER_ORIGINAL_SENTINEL'}
''', encoding="utf-8")
            env = dict(os.environ, FIXTURE_ROOT=str(root), FIXTURE_MODE=mode, FIXTURE_PYTHON=sys.executable, FIXTURE_PUBLIC_OWNER_SOURCE=str(ROOT/"common/contracts/run_artifact_workflow.ps1"))
            env.update(MASS_SPECTROMETRY_ARTIFACT_ROOT=str(root / "configured_artifacts"),
                       MASS_SPECTROMETRY_EXECUTION_ROOT=str(root / "execution"),
                       MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(root / "host.sqlite3"))
            env.pop("SIMULATION_PYTHON_EXE", None)
            env.pop("PYTHONPATH", None)
            env.pop("PYTHONHOME", None)
            command = ["pwsh", "-NoProfile", "-File", str(target / "execute_compensation.ps1"), "-PythonExe", sys.executable, "-RunId", "fixture"]
            command += ["-ResumeFinalization"] if resume else ["-CaseDirectory", "inert", "-SimionExe", "inert"]
            if resume:
                prior_run = root / "original-artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/fixture"
                (prior_run / "inputs").mkdir(parents=True)
                (prior_run / "inputs/execution_request.json").write_text(json.dumps({"package": {"project": "single_reflection_oa_tof_mass_analyzer", "run_id": "fixture", "mode": "reflectron_voltage_compensation"}}), encoding="utf-8")
                (root / "resume-result.json").write_text(json.dumps({"role": "run_artifact_workflow_result", "run_directory": str(prior_run)}), encoding="utf-8")
                command += ["-ResultPath", str(root / "resume-result.json")]
            if mode.startswith("producer"):
                command += ["-NumericsPath", "explicit-coarse-input"]
            result = subprocess.run(command, cwd=root, text=True, encoding="utf-8", capture_output=True, env=env, check=False, timeout=30)
            events = (root / "events").read_text(encoding="utf-8").splitlines() if (root / "events").exists() else []
            completion = json.loads((root / "completion.json").read_text(encoding="utf-8-sig")) if (root / "completion.json").exists() else {}
            if (root / "result.json").exists():
                completion["retained_result"] = json.loads((root / "result.json").read_text(encoding="utf-8-sig"))
            self.assertEqual((root / "source.pa").read_bytes(), b"inert byte transport fixture, no native PA")
            return result, events, completion

    def test_safe_producer_uses_one_owner_and_no_copy_or_duplicate_iob(self):
        result, events, completed = self.run_fixture("producer")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(events.count("producer"), 1)
        self.assertEqual(events.count("public_context"), 3)
        self.assertNotIn("alias", events)
        self.assertNotIn("alias_remove", events)
        self.assertNotIn("action:materialize", events)
        self.assertNotIn("native_iob", events)
        self.assertNotIn("action:iob-spec", events)
        self.assertEqual(events.count("release"), 1)
        self.assertEqual(len(completed["facts"]["resource_releases"]), 1)
        fact = next(f for f in completed["facts"]["operations"] if f["operation_id"].startswith("producer."))
        self.assertEqual(fact["observation"]["process_id"], 42)
        self.assertEqual(fact["resource_release_id"], "simion")
        fresh, events, completed = self.run_fixture("producer_fresh")
        self.assertEqual(fresh.returncode, 0, fresh.stdout + fresh.stderr)
        self.assertEqual(events.count("producer"), 1)
        self.assertEqual(events.count("native_basis"), 1)
        self.assertLess(events.index("producer"), events.index("native_basis"))
        self.assertLess(events.index("native_basis"), events.index("action:fit"))
        self.assertNotIn("action:iob-spec", events)
        reused, events, completed = self.run_fixture("producer_reuse")
        self.assertEqual(reused.returncode, 0, reused.stdout + reused.stderr)
        self.assertNotIn("producer", events)
        self.assertNotIn("lease", events)
        self.assertNotIn("native_iob", events)
        self.assertNotIn("action:materialize", events)
        self.assertNotIn("wave", events)
        failed, events, completed = self.run_fixture("producer_failure")
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("PRODUCER_ORIGINAL_SENTINEL", failed.stderr)
        self.assertIn("action:producer-complete", events)
        self.assertNotIn("wave", events)
        unknown, events, completed = self.run_fixture("producer_unknown")
        self.assertNotEqual(unknown.returncode, 0)
        self.assertFalse(completed["writers_stopped"])
        self.assertNotIn("release", events)

    def test_all_reuse_has_no_native_materialization_or_host_lease(self):
        result, events, completed = self.run_fixture("reuse")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("lease", events)
        self.assertNotIn("alias", events)
        self.assertNotIn("action:materialize", events)
        self.assertNotIn("wave", events)
        self.assertEqual([e for e in events if e.startswith("action:materialize-batches")],
                         ["action:materialize-batches:" + label for label in ("baseline", "compensated", "ideal_reflectron")])
        self.assertEqual(completed["facts"]["operations"], [])
        self.assertEqual(completed["summary"]["scientific_result"], "INCONCLUSIVE")

    def test_only_missing_complete_units_use_public_batch_phase(self):
        result, events, completed = self.run_fixture("partial")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("action:materialize", events)
        self.assertNotIn("native_iob", events)
        self.assertEqual(events.count("producer"), 1)
        self.assertLess(events.index("producer"), events.index("wave"))
        self.assertEqual(events.count("wave"), 3)
        self.assertEqual([e for e in events if e.startswith("dispatch:")],
                         [f"dispatch:{label}1:{label}" for label in ("baseline", "compensated", "ideal_reflectron")])
        self.assertEqual(len(completed["facts"]["operations"]), 4)
        self.assertEqual(len(completed["facts"]["resource_releases"]), 1)

    def test_failed_host_release_retains_primary_result_and_never_repeats_release(self):
        result, events, completed = self.run_fixture("release_failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FLY_PRIMARY_SENTINEL", result.stderr)
        self.assertEqual(events.count("release"), 1)
        self.assertFalse(any(event.startswith("finalize:") for event in events))
        retained = completed["retained_result"]
        self.assertIsInstance(retained["exception"], dict)
        self.assertIn("FLY_PRIMARY_SENTINEL", retained["exception"]["message"])
        self.assertTrue(retained["exception"]["type"])
        self.assertEqual(retained["exception"]["notes"], [])
        self.assertEqual(retained["execution_status"], "finalization_failed")
        self.assertEqual(retained["failure_stage"], "host_release")
        self.assertEqual(retained["recovery_action"], "inspect_release_without_refly")
        self.assertTrue(any("RELEASE_SECONDARY_SENTINEL" in error for error in retained["secondary_errors"]))
        self.assertEqual(retained["stage"], "prepared")
        for flag in ("terminal_published", "capacity_finalized", "lease_released"):
            self.assertFalse(retained[flag])

    def test_unknown_writer_preserves_primary_failure_and_host_protection(self):
        result, events, completed = self.run_fixture("unknown")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UNKNOWN_WRITER_SENTINEL", result.stderr)
        self.assertNotIn("release", events)
        self.assertFalse(completed["writers_stopped"])
        self.assertEqual(completed["summary"]["failure_stage"], "fly_baseline")
        self.assertNotIn("action:analyze", events)
        self.assertIn("UNKNOWN_WRITER_SENTINEL", completed["retained_result"]["exception"]["message"])
        self.assertEqual(completed["retained_result"]["secondary_errors"], ["UNKNOWN_WRITER_FINALIZATION"])

    def test_formal_first_unit_is_retained_and_recovery_uses_missing_plan(self):
        for mode, option in [("formal", "--prepared-plan"), ("recovered", "--recovered-missing-plan")]:
            with self.subTest(mode=mode):
                result, events, _ = self.run_fixture(mode)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(events.count("replan:" + option), 3)
                self.assertEqual([e for e in events if e.startswith("formal:")],
                                 [f"formal:{label}1" for label in ("baseline", "compensated", "ideal_reflectron")])
                self.assertFalse(any(e.startswith("dispatch:") for e in events))

    def test_published_native_family_cannot_be_laundered_by_private_copy(self):
        result, events, completed = self.run_fixture("native_family")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("standalone response provider", result.stderr)
        self.assertNotIn("lease", events)
        self.assertNotIn("alias", events)
        self.assertNotIn("action:materialize", events)
        self.assertNotIn("native_iob", events)
        self.assertNotIn("wave", events)
        self.assertEqual(completed["summary"]["failure_stage"], "materialize")

    def test_analysis_and_finalization_failure_never_fly_and_resume_is_early(self):
        for mode, sentinel in [("analysis_failure", "ANALYSIS_SENTINEL"), ("finalization_failure", "FINALIZATION_SENTINEL")]:
            with self.subTest(mode=mode):
                result, events, _ = self.run_fixture(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(sentinel, result.stderr)
                self.assertNotIn("lease", events)
                self.assertNotIn("wave", events)
        result, events, _ = self.run_fixture("reuse", resume=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ["resume"])


if __name__ == "__main__":
    unittest.main()
