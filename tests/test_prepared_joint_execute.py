"""Root prepared IP/MR execution routing and lifecycle, without vendor software."""

from msplatform.backends.simion.native_completion import retention_api as _manifest_retention_api
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
PREPARED_ENTRY = Path("src/msplatform/workflows/resources/prepared_joint_execute.ps1")
PREPARED_ENTRY_ID = "msplatform_workflows_prepared_joint_execute_ps1"


def prepared_joint_dependency_inventory():
    inventory = json.loads((REPO / "src/msplatform/workflows/config/runtime_dependencies.json").read_text())
    records = [record for provider in inventory["providers"] for record in provider.get("files", [])
               if record["source_repo_path"] == PREPARED_ENTRY.as_posix()]
    assert len(records) == 1 and records[0]["id"] == PREPARED_ENTRY_ID
    return inventory


def analysis_source_fixture(workspace, *, status="failed", owner="instrument_assembly", complete=True,
                            writers_stopped=True):
    """Public manifest with synthetic stopped-writer evidence, no solver or ledger."""
    from msplatform.execution.manifest_publication import build_run_manifest
    from msplatform.execution.retention import file_record
    root = workspace / "artifacts"
    run = root / "assemblies/instrument_assembly/runs/20261022_120000__test__simion__source"
    results = run / "results"
    results.mkdir(parents=True)
    logs = run / "logs"
    logs.mkdir()
    inputs = run / "inputs"
    inputs.mkdir()
    recording = dict(schema_version=1, mode="every_step", retention_class="solver_review",
                     reason="Synthetic analysis lifecycle regression", output_budget_bytes=1048576)
    contract = workspace / "new_analysis_contract.json"
    contract.write_text(json.dumps(dict(simion=dict(trajectory_recording=recording), peak_analysis=dict(test="explicit"))))
    prep = results / "prepared_joint_trial.json"
    expected = [i for i in range(1, 101) if i not in {24, 64, 80}]
    prep.write_text(json.dumps(dict(schema_version=1, role="mrtof_prepared_joint_trial", source_mode="measured_population",
        expected_particle_ids=expected, mother_particle_count=100, launched_particle_count=97,
        solver_epoch_instrument_time_us=7500.63364160348, protected_paths=[str(run)])))
    log = logs / "native_two_prism_flight.log"
    log.write_text("INERT NATIVE LOG FIXTURE; no commercial flight executed\n")
    batch_receipt = results / "batch_receipt.json"
    batch_receipt.write_text(json.dumps(dict(original_particle_ids=expected)))
    fly = results / "joint.fly2"
    fly.write_text("INERT LAUNCHED STATE FIXTURE\n")
    merge = results / "batch_log_merge_receipt.json"
    merge.write_text(json.dumps(dict(schema_version=1, role="mrtof_measured_batch_log_merge",
        status="success" if complete else "incomplete", preparation=file_record(prep), merged_log=file_record(log),
        particle_count=97, mother_particle_count=100, original_particle_ids=expected,
        all_batch_losses_retained=True, id_rebasing_applied=False, solver_epoch_instrument_time_us=7500.63364160348,
        batches=[dict(log=file_record(log), batch_receipt=file_record(batch_receipt), fly2=file_record(fly))])))
    summary = run / "summary.json"
    summary.write_text(json.dumps(dict(status=status, failure_stage="automatic_joint_diagnostics",
                                       writers_stopped=writers_stopped)))
    request = inputs / "execution_request.json"
    request.write_text(json.dumps(dict(schema_version=1, role="run_artifact_workflow_request",
        package=dict(project=owner, mode="prepared_joint", run_id=run.name))))
    config = run / "run_config.json"
    config.write_text(json.dumps(dict(schema_version=2, run_id=run.name, project=owner, mode="prepared_joint",
        inputs=dict(execution_request=str(request)),
        artifact_retention=dict(policy_version=1, **{"class": "solver_review"}, reason=recording["reason"]))))
    completion = results / "execution_completion.json"
    completion.write_text(json.dumps(dict(schema_version=1, role="run_artifact_workflow_completion",
        run_id=run.name, project=owner, status=status, run_config=file_record(config), execution_request=file_record(request),
        writer_completion=dict(
            operations=[dict(operation_id="native_flight", resource_release_id="native_flight",
                observation=dict(exit_confirmed=True, returncode=0, process_id=1234, process_started_at_utc_ticks=1))],
            resource_releases=[dict(release_id="native_flight", completion_receipt=dict(host_release=dict(
                inherited=True, token="fixture-host-token", result=None, error=None)))]))))
    manifest = build_run_manifest(config, status, output_paths=[prep, log, batch_receipt, fly, merge, summary, completion],
                                  retention_api=_manifest_retention_api)
    (run / "run_manifest.json").write_text(json.dumps(manifest))
    return run, contract


class PreparedJointAnalysisTests(unittest.TestCase):
    def test_source_admission_keeps_original_paths_and_does_not_read_native_logs(self):
        from msplatform.workflows.prepared_joint.analysis_inputs import prepare_analysis_inputs
        for status in ("success", "failed"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                source, contract = analysis_source_fixture(workspace, status=status)
                self.assertFalse((workspace / "artifacts/platform/capacity_ledger.json").exists())
                before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
                with patch("msplatform.workflows.prepared_joint.analysis_inputs.verify_record", wraps=__import__(
                    "msplatform.execution.retention", fromlist=["verify_record"]).verify_record) as verifier:
                    result = prepare_analysis_inputs(source, contract, workspace / "inputs")
                verified = [str(call.args[1]["path"]) for call in verifier.call_args_list]
                self.assertFalse(any(path.endswith((".log", ".fly2", ".pa")) for path in verified))
                self.assertEqual(result["mother_particle_count"], 100)
                self.assertEqual(result["launched_particle_count"], 97)
                self.assertEqual(result["merged_log"], str(source / "logs/native_two_prism_flight.log"))
                self.assertEqual(result["preparation"], str(source / "results/prepared_joint_trial.json"))
                self.assertEqual(result["merge_receipt"], str(source / "results/batch_log_merge_receipt.json"))
                self.assertNotIn("merged_log_identity", result)
                self.assertEqual(Path(result["analysis_contract"]).read_bytes(), contract.read_bytes())
                self.assertEqual(Path(result["source_manifest"]).read_bytes(), before[source / "run_manifest.json"])
                self.assertEqual({p.name for p in (workspace / "inputs").iterdir()},
                                 {"source_run_manifest.json", "analysis_contract.json"})
                for path, payload in before.items():
                    self.assertEqual(path.read_bytes(), payload)

    def test_source_admission_rejects_wrong_owner_and_incomplete_native_before_output(self):
        from msplatform.workflows.prepared_joint.analysis_inputs import prepare_analysis_inputs
        for owner, complete, message in (("multi_reflection_tof", True, "instrument_assembly/prepared_joint"),
                                         ("instrument_assembly", False, "complete original-ID")):
            with self.subTest(owner=owner, complete=complete), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                source, contract = analysis_source_fixture(workspace, owner=owner, complete=complete)
                with self.assertRaisesRegex(ValueError, message):
                    prepare_analysis_inputs(source, contract, workspace / "inputs")
                self.assertFalse((workspace / "inputs").exists())

    def test_source_admission_rejects_unstopped_missing_and_tampered_sources(self):
        from msplatform.workflows.prepared_joint.analysis_inputs import prepare_analysis_inputs
        cases = (
            ("unstopped", ValueError, "writer stop is not confirmed"),
            ("missing", AssertionError, "manifest .* is missing"),
            ("tampered", AssertionError, "SHA-256 changed"),
        )
        for scenario, exception, message in cases:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                source, contract = analysis_source_fixture(workspace, writers_stopped=scenario != "unstopped")
                preparation = source / "results/prepared_joint_trial.json"
                if scenario == "missing":
                    preparation.unlink()
                elif scenario == "tampered":
                    preparation.write_text(preparation.read_text().replace(
                        "measured_population", "measured_populatioX"))
                with self.assertRaisesRegex(exception, message):
                    prepare_analysis_inputs(source, contract, workspace / "inputs")
                self.assertFalse((workspace / "inputs").exists())

    def test_public_analysis_runner_freezes_sources_and_publishes_success_or_failure_without_simion(self):
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("PowerShell 7 is unavailable")
        from tests.contracts.test_support.fixture_process import run_fixture_process

        inventory = prepared_joint_dependency_inventory()
        from tests.workflows.single_reflection.test_support.single_reflection_execute_fixture import declared_dependency_paths
        records = [{'source_repo_path': path} for path in declared_dependency_paths(REPO, inventory, 'prepared_joint')]
        support = {"src/msplatform/execution/resources/run_artifact_support.ps1", "src/msplatform/execution/resources/require_powershell7.ps1", "src/msplatform/execution/resources/host_execution_lease.ps1", "src/msplatform/execution/resources/new_run_project_identities.json", "src/msplatform/execution/artifact_identity_archive.py"}
        capacity_fixture = r'''
function Invoke-RunCapacityLifecycleAdapter {return @{light_evidence_budget_exceeded=$false}}
function Assert-AnalysisFixtureSourceProtection {
 param($RunDirectory,$ProtectedPaths,$SourceReferences)
 if(@($ProtectedPaths).Count-ne1-or$ProtectedPaths[0]-ne$RunDirectory){throw 'Target run protection differs'}
 if(@($SourceReferences).Count-ne1){throw 'Analysis source authority count differs'}
 $reference=$SourceReferences[0];$record=$reference.manifest_record
 $source=$env:ANALYSIS_TEST_SOURCE_RUN;$manifest=Join-Path $source 'run_manifest.json'
 if($record.path-ne$manifest-or-not$record.exists-or$record.bytes-ne(Get-Item $manifest).Length-or$record.sha256-ne(Get-FileHash $manifest -Algorithm SHA256).Hash){throw 'Analysis source manifest binding differs'}
 if(@($reference.protected_paths).Count-ne1-or$reference.protected_paths[0]-ne$source-or@($reference.protected_cache_keys).Count){throw 'Analysis explicit source protection differs'}
}
function Enter-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$ArtifactRoot,$RunDirectory,$CommittedNewBytes,$ProtectedPaths,$SourceReferences,$Owner)
 if($CommittedNewBytes-ne1048576){throw 'Analysis capacity budget differs'}
 Assert-AnalysisFixtureSourceProtection $RunDirectory $ProtectedPaths $SourceReferences
 return @{committed_new_bytes=$CommittedNewBytes;run_directory=$RunDirectory;source_references=$SourceReferences}
}
function Update-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$Session,$ProtectedPaths,$SourceReferences,$RemainingCommittedNewBytes)
 Assert-AnalysisFixtureSourceProtection $Session.run_directory $ProtectedPaths $SourceReferences
 if($env:ANALYSIS_TEST_CAPACITY_FAIL-eq'1'-and$RemainingCommittedNewBytes-eq0){throw 'Explicit inert terminal capacity failure'}
 return @{session=$Session}
}
function Exit-ArtifactWorkflowCapacitySession {$script:capacityReleased=$true}
'''
        host_fixture = r'''
# Explicit inert host admission; this fixture never creates a host ledger.
function Assert-HostResourceHeavyStage {throw 'Analysis fixture must never request native heavy execution'}
function Test-HostResourceConsoleProcess {return $false}
function Enter-HostExecutionLease {
 param($Role,$Stage,$RunId)
 if($Role-ne'GATE'-or$Stage-ne'unclassified'){throw 'Analysis must request ordinary host admission'}
 [IO.File]::AppendAllText($env:ANALYSIS_TEST_HOST_EVENTS,"enter:$Role/$Stage`n")
 return @{test_lease='analysis';run_id=$RunId}
}
function Exit-HostExecutionLease {
 param($Lease,$Outcome,$RunId)
 if($Lease.test_lease-ne'analysis'-or$Lease.run_id-ne$RunId){throw 'Analysis released a different host lease'}
 [IO.File]::AppendAllText($env:ANALYSIS_TEST_HOST_EVENTS,"exit:$Outcome`n")
}
'''
        owner_fixture = r'''
# Explicit lifecycle boundary fixture; the real adapter and CLI recovery run
# separately in test_workflow_finalization_recovery.
function Initialize-RunArtifactPowerShellOwner {
 param($Package,$CapacitySession,$EntrypointPath,$EntrypointRecord)
 $expected=Join-Path $script:pythonRoot 'src/msplatform/workflows/resources/prepared_joint_execute.ps1'
 if($EntrypointPath-ne$expected-or$EntrypointRecord.path-ne$expected){throw 'Analysis frozen entrypoint owner differs'}
 @{package=$Package;capacity_session=$CapacitySession;result_path='inert-result'}
}
function Complete-RunArtifactPowerShellOwner {
 param($Context,$Status,$Summary,$OutputPaths,$WritersStopped,$WriterCompletion,$OriginalFailure)
 if(-not$WritersStopped-or$WriterCompletion.operations.Count-or$WriterCompletion.resource_releases.Count){throw 'Analysis fabricated native execution'}
 Write-RunJson -Path $Context.package.summary -Value $Summary
 $null=Apply-RunArtifactRetention -Python $python -RepoRoot $repoRoot -RunConfig $Context.package.run_config
 $null=Update-ArtifactWorkflowCapacitySession -Session $Context.capacity_session -ProtectedPaths @($Context.capacity_session.run_directory) -SourceReferences $Context.capacity_session.source_references -RemainingCommittedNewBytes 0
 Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig $Context.package.run_config -Status $Status -Software @('Python fixture') -Outputs @($OutputPaths) -DeferCapacityFinalization|Out-Host
 Invoke-ProjectPython -Arguments @('-m','msplatform.execution.run_capacity_lifecycle','--action','seal-stopped-payload','--run-config',$Context.package.run_config)|Out-Host
 @{status=$Status;stage='complete'}
}
'''
        analyzer_fixture = '''import json, os, sys
from pathlib import Path
args=sys.argv
assert args[1]=='analyze-joint'
def argument(key): return Path(args[args.index(key)+1])
prep=argument('--preparation'); log=argument('--log'); contract=argument('--analysis-contract'); output=argument('--output')
assert prep.parent.parent.name.endswith('__source') and log.parent.parent==prep.parent.parent
assert contract.parent.parent==output.parent.parent and contract.name=='analysis_contract.json'
assert json.loads(prep.read_text())['launched_particle_count']==97
assert json.loads(contract.read_text())['peak_analysis']=={'test':'explicit'}
assert Path(os.environ['ANALYSIS_TEST_HOST_EVENTS']).read_text()=='enter:GATE/unclassified\\n'
if os.environ['ANALYSIS_TEST_FAIL']=='1': raise RuntimeError('Explicit inert analysis failure')
output.mkdir()
(output/'diagnostics_receipt.json').write_text(json.dumps(dict(status='success',inert_test=True)))
'''
        seal_fixture = '''import json, os, sys
from pathlib import Path
def resolve_consumed_run_capacity_owner(*args, **kwargs):
    raise AssertionError('Historical admission called the retired capacity owner')
def main():
    args=sys.argv
    assert args[args.index('--action')+1]=='seal-stopped-payload'
    run=Path(args[args.index('--run-config')+1]).parent
    assert json.loads((run/'run_manifest.json').read_text(encoding='utf-8-sig'))['status'] in ('success','failed')
    if os.environ['ANALYSIS_TEST_SEAL_FAIL']=='1': raise RuntimeError('Explicit inert seal failure')
if __name__=='__main__': main()
'''
        successful_scenarios = {"success", "mutated_author_contract", "removed_author_contract"}
        admitted_scenarios = successful_scenarios | {"analysis_failure", "capacity_failure", "seal_failure", "missing_frozen_diagnostics"}
        for scenario in ("success", "mutated_author_contract", "removed_author_contract", "missing_frozen_admission",
                         "missing_frozen_diagnostics", "analysis_failure", "wrong_owner", "incomplete_native",
                         "capacity_failure", "seal_failure"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                repo = workspace / "simulation_repo"
                installed = workspace / "installed/msplatform"
                selected_paths = support | {item["source_repo_path"] for item in records}
                for relative in selected_paths:
                    target = repo / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(REPO / relative, target)
                    if relative.startswith("src/msplatform/"):
                        installed_target = installed / Path(relative).relative_to("src/msplatform")
                        installed_target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(REPO / relative, installed_target)
                dependency = repo / "src/msplatform/workflows/config/runtime_dependencies.json"
                dependency.parent.mkdir(parents=True, exist_ok=True)
                dependency.write_text(json.dumps(inventory))
                installed_dependency = installed / "workflows/config/runtime_dependencies.json"
                installed_dependency.parent.mkdir(parents=True, exist_ok=True)
                installed_dependency.write_text(json.dumps(inventory))
                helpers = repo / "src/msplatform/execution/resources/run_artifact_support.ps1"
                helpers.write_text(helpers.read_text() + capacity_fixture)
                shutil.copyfile(helpers, installed / "execution/resources/run_artifact_support.ps1")
                host_support = repo / "src/msplatform/execution/resources/host_execution_lease.ps1"
                host_support.write_text(host_support.read_text() + host_fixture)
                shutil.copyfile(host_support, installed / "execution/resources/host_execution_lease.ps1")
                workflow_owner = repo / "src/msplatform/workflows/resources/run_artifact_workflow.ps1"
                workflow_owner.write_text(workflow_owner.read_text() + owner_fixture)
                shutil.copyfile(workflow_owner, installed / "workflows/resources/run_artifact_workflow.ps1")
                (repo / "src/msplatform/workflows/prepared_joint/diagnostics.py").write_text(analyzer_fixture)
                (installed / "workflows/prepared_joint/diagnostics.py").write_text(analyzer_fixture)
                (repo / "src/msplatform/execution/run_capacity_lifecycle.py").write_text(seal_fixture)
                (installed / "execution/run_capacity_lifecycle.py").write_text(seal_fixture)
                source, contract = analysis_source_fixture(workspace,
                    owner="multi_reflection_tof" if scenario == "wrong_owner" else "instrument_assembly",
                    complete=scenario != "incomplete_native")
                contract_bytes = contract.read_bytes()
                contract_sha256 = hashlib.sha256(contract_bytes).hexdigest().upper()
                before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
                run_id = "20261022_120001__analysis__python__joint-test"
                run = source.parent / run_id
                # The wrapper cannot start this synthetic workflow or any child
                # until the public helper assigns it to its owned Job and ACKs.
                python_home = workspace / "python"
                subprocess.run([sys._base_executable, "-m", "venv", "--system-site-packages", str(python_home)],
                               check=True, capture_output=True, text=True, timeout=60, cwd=workspace)
                selected_python = python_home / "Scripts/python.exe"
                parent_site_packages = next(Path(path) for path in sys.path if (Path(path) / "referencing").is_dir())
                (python_home / "Lib/site-packages/selected-msplatform.pth").write_text(
                    str(installed.parent) + "\n" + str(parent_site_packages) + "\n", encoding="utf-8")
                arguments = [str(installed / PREPARED_ENTRY.relative_to("src/msplatform")),
                    "-AnalyzeRunPath", str(source), "-ContractPath", str(contract), "-RunId", run_id,
                    "-RepoRoot", str(repo), "-PythonExe", str(selected_python)]
                argvfile = workspace / "fixture-argv.json"
                argvfile.write_text(json.dumps(arguments), encoding="utf-8")
                launcher = workspace / "invoke-owned.ps1"
                launcher.write_text(r'''param([string]$ArgvFile)
$ErrorActionPreference='Stop'
$fixtureClock=[Diagnostics.Stopwatch]::StartNew()
$fixtureTimeline=Join-Path $PSScriptRoot 'timeline.jsonl'
function Write-AnalysisFixtureEvent {
 param([string]$Stage)
 $row=@{stage=$Stage;monotonic_seconds=$fixtureClock.Elapsed.TotalSeconds;pid=$PID}|ConvertTo-Json -Compress
 [IO.File]::AppendAllText($fixtureTimeline,$row+"`n",[Text.UTF8Encoding]::new($false))
}
Write-AnalysisFixtureEvent 'launcher_waiting_for_ownership'
if([Console]::In.ReadLine()-cne'fixture-owned-start'){throw 'Fixture ownership ACK missing'}
Write-AnalysisFixtureEvent 'ownership_acknowledged'
$values=@(Get-Content -LiteralPath $ArgvFile -Raw -Encoding utf8|ConvertFrom-Json)
$entry=[string]$values[0];$forwardParameters=@{}
if(($values.Count-1)%2-ne0){throw 'Fixture argv must contain complete named pairs'}
for($index=1;$index-lt$values.Count;$index+=2){
 $key=[string]$values[$index]
 if(-not$key.StartsWith('-')-or$forwardParameters.ContainsKey($key.Substring(1))){throw 'Fixture argv named key differs'}
 $forwardParameters[$key.Substring(1)]=[string]$values[$index+1]
}
Write-AnalysisFixtureEvent 'actual_entry_begin'
try { & $entry @forwardParameters } finally { Write-AnalysisFixtureEvent 'actual_entry_returned' }
''', encoding="utf-8")
                # Observe only named transitions in this temporary workflow copy;
                # no production file, operation, input or timeout is changed.
                entry = Path(arguments[0])
                code = entry.read_text(encoding="utf-8")
                boundary = code.index("function Invoke-PreparedJointAnalysis {")
                prefix, analysis = code[:boundary], code[boundary:]
                probes = {
                    "$source=(Resolve-Path -LiteralPath $AnalyzeRunPath).Path": "analysis_source_path",
                    "$recording=(@(Invoke-ProjectPython": "recording_config_begin",
                    "$package=New-RunPackage": "package_begin",
                    "$frozen=Freeze-ConsumerDependencies": "freeze_dependencies_begin",
                    "$script:pythonRoot=[string]$frozen.execution_root": "freeze_dependencies_returned",
                    "$selection=(@(Invoke-ProjectPython": "source_admission_begin",
                    "$stage='joint_diagnostics'": "scientific_analysis_begin",
                    "$ownerResult=Complete-RunArtifactPowerShellOwner": "owner_finalization_begin",
                    "$analysisLease=Enter-HostExecutionLease": "fixture_host_admission_begin",
                }
                for token, label in probes.items():
                    self.assertEqual(analysis.count(token), 1, token)
                    analysis = analysis.replace(token, "Write-AnalysisFixtureEvent '" + label + "'\n  " + token, 1)
                if scenario in {"mutated_author_contract", "removed_author_contract", "missing_frozen_admission"}:
                    token = "$frozenAnalysisContract=Copy-VerifiedRunInput -Source $contract -Destination (Join-Path $inputDir 'analysis_contract.json')"
                    self.assertEqual(analysis.count(token), 1)
                    action = {
                        "mutated_author_contract": "  [IO.File]::WriteAllText($contract,'{\"simion\":null}',[Text.UTF8Encoding]::new($false))",
                        "removed_author_contract": "  Remove-Item -LiteralPath $contract",
                        "missing_frozen_admission": "  Remove-Item -LiteralPath (Join-Path $inputDir 'runtime_snapshot/src/msplatform/workflows/prepared_joint/analysis_inputs.py')",
                    }[scenario]
                    analysis = analysis.replace(token, token + "\n" + action, 1)
                if scenario == "missing_frozen_diagnostics":
                    token = "$stage='joint_diagnostics'"
                    self.assertEqual(analysis.count(token), 1)
                    action = "  Remove-Item -LiteralPath (Join-Path $inputDir 'runtime_snapshot/src/msplatform/workflows/prepared_joint/diagnostics.py')"
                    analysis = analysis.replace(token, token + "\n" + action, 1)
                entry.write_text(prefix + analysis, encoding="utf-8")
                environment = {**os.environ, "PYTHONPATH": str(repo / "src") + os.pathsep + str(repo), "PYTHONNOUSERSITE": "1",
                    "ProgramFiles": str(workspace / "NO_SIMION"),
                    "ANALYSIS_TEST_HOST_EVENTS": str(workspace / "host_events.txt"),
                    "ANALYSIS_TEST_SOURCE_RUN": str(source),
                    "ANALYSIS_TEST_FAIL": "1" if scenario == "analysis_failure" else "0",
                    "ANALYSIS_TEST_CAPACITY_FAIL": "1" if scenario == "capacity_failure" else "0",
                    "ANALYSIS_TEST_SEAL_FAIL": "1" if scenario == "seal_failure" else "0",
                    "FIXTURE_PYTHON": sys.executable, "FIXTURE_TEST_SOURCE": __file__,
                    "FIXTURE_ADAPTER_SOURCE": str(entry), "FIXTURE_TEST_METHOD": self.id()}
                completed = primary = None
                try:
                    completed = run_fixture_process(
                        [pwsh, "-NoProfile", "-File", str(launcher), str(argvfile)],
                        root=workspace, cwd=workspace, environment=environment,
                        mode="prepared-analysis-" + scenario, timeout=45,
                    )
                except BaseException as error:
                    primary = error
                    raise
                finally:
                    evidence = getattr(primary if primary is not None else completed, "fixture_diagnostics", None)
                    if evidence is not None:
                        print("PREPARED_ANALYSIS_FIXTURE_DIAGNOSTICS=" + str(evidence), flush=True)
                        try:
                            for record in (argvfile, entry, workspace / "host_events.txt"):
                                if record.is_file():
                                    shutil.copyfile(record, Path(evidence) / record.name)
                        except BaseException as diagnostic_error:
                            if primary is None:
                                raise
                            primary.add_note("PREPARED_ANALYSIS_EXTRA_EVIDENCE_ERROR=" + repr(diagnostic_error))
                self.assertEqual(completed.returncode == 0, scenario in successful_scenarios, completed.stdout + completed.stderr)
                self.assertTrue((workspace / "host_events.txt").is_file(), completed.stdout + completed.stderr)
                self.assertEqual((workspace / "host_events.txt").read_text().splitlines(),
                                 ["enter:GATE/unclassified", "exit:success" if scenario in successful_scenarios else "exit:failed"])
                self.assertFalse((workspace / "artifacts/platform/host_resources.sqlite3").exists())
                manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8-sig"))
                configuration = json.loads((run / "run_config.json").read_text(encoding="utf-8-sig"))
                summary = json.loads((run / "summary.json").read_text(encoding="utf-8-sig"))
                self.assertEqual((manifest["project"], manifest["mode"]), ("instrument_assembly", "prepared_joint_analysis"))
                expected_manifest_status = (
                    "checkpoint" if scenario in {"capacity_failure", "missing_frozen_admission", "missing_frozen_diagnostics"}
                    else "success" if scenario in successful_scenarios | {"seal_failure"} else "failed"
                )
                self.assertEqual(manifest["status"], expected_manifest_status)
                self.assertFalse(summary["native_flight_executed"])
                self.assertFalse(list(run.rglob("*.pa*")))
                self.assertFalse(list(run.rglob("*.log")))
                self.assertFalse((run / "inputs/analysis_inputs.json").exists())
                self.assertNotIn("analysis_inputs", configuration["inputs"])
                if scenario in admitted_scenarios:
                    self.assertEqual(Path(configuration["inputs"]["source_preparation"]), source / "results/prepared_joint_trial.json")
                    self.assertEqual(Path(configuration["inputs"]["source_merge_receipt"]), source / "results/batch_log_merge_receipt.json")
                    self.assertEqual(Path(configuration["inputs"]["source_manifest"]).read_bytes(), before[source / "run_manifest.json"])
                    self.assertEqual(Path(configuration["inputs"]["analysis_contract"]).read_bytes(), contract_bytes)
                    if "analysis_contract" in manifest["inputs"]:
                        self.assertEqual(manifest["inputs"]["analysis_contract"]["sha256"], contract_sha256)
                    self.assertEqual((configuration["parameters"]["mother_particle_count"],
                                      configuration["parameters"]["launched_particle_count"]), (100, 97))
                    snapshot_entry = run / "inputs/runtime_snapshot" / PREPARED_ENTRY
                    self.assertEqual(snapshot_entry.read_text(), (installed / PREPARED_ENTRY.relative_to("src/msplatform")).read_text())
                    self.assertEqual(Path(configuration["inputs"][PREPARED_ENTRY_ID]), snapshot_entry)
                    self.assertTrue((run / "inputs/runtime_snapshot/src/msplatform/workflows/prepared_joint/analysis_inputs.py").is_file())
                else:
                    self.assertEqual(summary["failure_stage"], "admit_completed_native_source")
                    self.assertFalse((run / "results/diagnostics").exists())
                if scenario in {"missing_frozen_admission", "missing_frozen_diagnostics"}:
                    expected_module = "analysis_inputs" if scenario == "missing_frozen_admission" else "diagnostics"
                    self.assertIn(expected_module, summary["reason"])
                if scenario == "missing_frozen_diagnostics":
                    self.assertEqual(summary["failure_stage"], "joint_diagnostics")
                    self.assertFalse((run / "results/diagnostics").exists())
                if scenario in {"mutated_author_contract", "removed_author_contract"}:
                    self.assertNotEqual(contract.read_bytes() if contract.exists() else None, contract_bytes)
                for path, payload in before.items():
                    self.assertEqual(path.read_bytes(), payload)


class PreparedJointExecuteTests(unittest.TestCase):

    def test_scientific_event_receipt_reaches_actual_centroid_analysis_cli(self):
        import contextlib
        import io
        from msplatform.workflows.prepared_joint import trial as prepared_joint_trial
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "merge.json"
            arguments = ["analyze-probe", "--preparation", str(root / "preparation.json"),
                         "--log", str(root / "native.log"), "--output", str(root / "diagnostics"),
                         "--scientific-event-receipt", str(receipt)]
            with patch.object(prepared_joint_trial, "analyze_centroid_probe") as actual_analysis, \
                    patch.object(sys, "argv", ["trial", *arguments]), contextlib.redirect_stdout(io.StringIO()):
                prepared_joint_trial.main()
                self.assertEqual(actual_analysis.call_args.kwargs["scientific_event_receipt"], receipt)
                actual_analysis.side_effect = RuntimeError("ORIGINAL_CLI_ANALYSIS_FAILURE")
                with self.assertRaisesRegex(RuntimeError, "ORIGINAL_CLI_ANALYSIS_FAILURE"):
                    prepared_joint_trial.main()

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_retired_flight_parameters_cannot_start_and_workpoint_selects_oa(self):
        runner = REPO / PREPARED_ENTRY
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(runner),
                "-PreparedJointWorkbenchRunPath", str(root / "prepared"),
                "-PreparedSourceMode", "centroid_probe", "-ContractPath", str(root / "contract.json"),
                "-PythonExe", sys.executable, "-RepoRoot", str(REPO)], cwd=root,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("PreparedJointWorkbenchRunPath", result.stdout + result.stderr)
            self.assertFalse((root / "artifacts").exists())
            source = runner.read_text(encoding="utf-8")
            self.assertNotIn("Invoke-PreparedJointTrial", source)
            self.assertNotIn("ParameterSetName='Flight'", source)
            controller = REPO / "src/msplatform/workflows/resources/run_downstream_workpoint_iteration.ps1"
            script = root / "route.ps1"
            script.write_text(r'''param($Controller,$PackageRoot)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Controller,[ref]$null,[ref]$null)
$assignment=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$trialRunner'},$true)
if($null-eq$assignment){throw 'Workpoint trial owner assignment is missing'}
Invoke-Expression $assignment.Extent.Text
if($trialRunner-ne(Join-Path $PackageRoot 'workflows/resources/oa_mr.ps1')){throw 'Workpoint no longer selects OA owner'}
if($ast.ParamBlock.Parameters.Name.VariablePath.UserPath-contains'PreparedJointWorkbenchRunPath'){throw 'Retired Prepared route remains bound'}
'OA_WORKPOINT_ROUTE=PASS'
''', encoding="utf-8")
            route = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(script),
                str(controller), str(REPO / "src/msplatform")], cwd=root,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(route.returncode, 0, route.stdout + route.stderr)
            self.assertIn("OA_WORKPOINT_ROUTE=PASS", route.stdout)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_default_entry_uses_selected_package_and_rejects_missing_or_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "installation/Lib/site-packages/msplatform"
            shutil.copytree(REPO / "src/msplatform", package)
            python_home = root / "python"
            subprocess.run([sys._base_executable, "-m", "venv", "--system-site-packages", str(python_home)],
                           check=True, capture_output=True, text=True, timeout=60, cwd=root)
            python = python_home / "Scripts/python.exe"
            selection = python_home / "Lib/site-packages/selected-msplatform.pth"
            selection.write_text(str(package.parent) + "\n", encoding="utf-8")
            workspace = root / "workspace"
            workspace.mkdir()
            environment = {key: value for key, value in os.environ.items()
                           if key not in {"PYTHONPATH", "SIMULATION_PYTHON_EXE"}}
            command = [shutil.which("pwsh"), "-NoProfile", "-File",
                       str(package / "workflows/resources/prepared_joint_execute.ps1"),
                       "-AnalyzeRunPath", str(root / "missing-source"),
                       "-ContractPath", str(root / "missing-contract.json"), "-PythonExe", str(python)]
            boundary = subprocess.run(command, cwd=workspace, env=environment, capture_output=True,
                                      text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertNotEqual(boundary.returncode, 0)
            self.assertIn("missing-source", boundary.stdout + boundary.stderr)
            self.assertFalse((workspace / "artifacts").exists())

            selection.write_text(str(REPO / "src") + "\n", encoding="utf-8")
            mismatch = subprocess.run(command, cwd=workspace, env=environment, capture_output=True,
                                      text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertNotEqual(mismatch.returncode, 0)
            self.assertIn("package differs from the entry package", mismatch.stdout + mismatch.stderr)

            empty_python_home = root / "empty-python"
            subprocess.run([sys._base_executable, "-m", "venv", str(empty_python_home)],
                           check=True, capture_output=True, text=True, timeout=60, cwd=root)
            command[-1] = str(empty_python_home / "Scripts/python.exe")
            missing = subprocess.run(command, cwd=workspace, env=environment, capture_output=True,
                                     text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("Installed msplatform package is unavailable", missing.stdout + missing.stderr)





    def test_prepared_child_rejects_old_or_wrong_owner(self):
        from msplatform.workflows.prepared_joint.downstream_workpoint import load_prepared_centroid_trial
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "run_manifest.json"
            for owner, mode in (("multi_reflection_tof", "two_prism_joint_measured_trial"),
                                ("orthogonal_accelerator", "prepared_joint"),
                                ("instrument_assembly", "two_prism_joint_measured_trial")):
                manifest.write_text(json.dumps(dict(status="success", project=owner, mode=mode)))
                with self.subTest(owner=owner, mode=mode), self.assertRaisesRegex(ValueError, "published successful measured joint"):
                    load_prepared_centroid_trial(manifest, manifest, manifest)



    def test_equivalence_reads_exact_old_or_new_identity_without_execution_fallback(self):
        from msplatform.execution.retention import file_record
        from msplatform.workflows.prepared_joint.trial import freeze_equivalence_reference
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior = root / "prior"
            (prior / "results/source").mkdir(parents=True)
            (prior / "logs").mkdir()
            current = root / "current"
            current.mkdir()
            filenames = ("component_particle_state.csv", "source_census.csv", "source_states.lua",
                         "source_projection.lua", "source.fly2", "clock_authority.json")
            for name in filenames:
                (prior / "results/source" / name).write_text("same frozen scientific bytes")
                (current / name).write_text("same frozen scientific bytes")
            log = prior / "logs/joint_flight_batch_001.log"
            log.write_text("MRTOF_EVENT terminal ion=7 t_us=7500.57\nstatus,Fly completed. 1 splats\nIOB_FLIGHT: PASS complete\n")
            preparation = dict(expected_particle_ids=[7], mother_particle_count=100, launched_particle_count=1,
                solver_epoch_instrument_time_us=7500, numerics=dict(maximum_step_us=.001),
                parent_preparation=dict(sha256="A"*64), field_binding=dict(sha256="B"*64),
                trajectory_contract=dict(sha256="C"*64), measured_source_directory=str(current))
            receipt = prior / "results/prepared_joint_trial.json"
            receipt.write_text(json.dumps(dict(preparation, measured_source_directory=str(prior / "results/source"))))
            records = [file_record(path) for path in [receipt, log, *sorted((prior / "results/source").iterdir())]]
            for index, (owner, mode) in enumerate((("instrument_assembly", "prepared_joint"),
                ("multi_reflection_tof", "two_prism_joint_measured_trial"),
                ("multi_reflection_tof", "prepared_joint"))):
                (prior / "run_manifest.json").write_text(json.dumps(dict(project=owner, mode=mode, status="interrupted", outputs=records)))
                destination = root / str(index)
                destination.mkdir()
                with patch("msplatform.execution.manifest_verification.verify_run_manifest") as verifier:
                    if index == 2:
                        with self.assertRaisesRegex(ValueError, "owner/mode"):
                            freeze_equivalence_reference(prior, preparation, destination)
                    else:
                        result = freeze_equivalence_reference(prior, preparation, destination)
                        self.assertEqual(result["original_particle_ids"], [7])
                        self.assertEqual(Path(result["reference_log"]["path"]).read_bytes(), log.read_bytes())
                    verifier.assert_called_once()
