"""Neutral workflow owner tests using isolated ledgers and short Python callbacks."""

from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from common.contracts.capacity_ledger import initialize_capacity_ledger, load_capacity_ledger
from common.contracts.capacity_protection import load_capacity_protection_leases
from common.contracts.write_run_manifest import file_record


REPO = Path(__file__).resolve().parents[2]
OWNER = REPO / "common/contracts/run_artifact_workflow.ps1"
PROJECT = "single_reflection_oa_tof_mass_analyzer"
PWSH = shutil.which("pwsh")

# This callback is deliberately solver-free. It changes scientific inputs only;
# every lifecycle operation under test is still the real common implementation.
CALLBACK = '''import json, os, sys, time
from pathlib import Path
sys.path.insert(0, REPOSITORY)
from common.contracts.write_run_manifest import file_record
from common.contracts.capacity_protection import load_capacity_protection_leases

def execute_prepared_run(config_path, session_path, request_path, completion_path):
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    request = json.loads(request_path.read_text(encoding="utf-8-sig"))
    session = json.loads(session_path.read_text(encoding="utf-8-sig"))
    root = config_path.parent
    payload = request["payload"]
    counter = Path(payload["counter_path"])
    counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else "1", encoding="utf-8")
    protection = load_capacity_protection_leases(Path(session["artifact_root"]))
    assert root.resolve() in protection["protected_paths"]
    assert protection["committed_new_bytes"] == request["capacity"]["committed_new_bytes"]
    if payload.get("raise"):
        raise RuntimeError("original prepared fixture failure")
    config["parameters"] = {"fixture": True}
    config_path.write_text(json.dumps(config), encoding="utf-8")
    output = root / "results/science.json"
    output.write_text(json.dumps({"capacity_session": session["lease_id"], "worker_process_id": os.getpid(),
        "host_resource_state_path": os.environ["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"]}), encoding="utf-8")
    outputs, required, preserve = [str(output)], [str(output)], []
    if payload.get("disposable"):
        for name in ("first.pa0", "second.pa0"):
            path = root / "results" / name
            path.write_bytes(b"disposable fixture payload")
            outputs.append(str(path))
    if payload.get("outside_preserve"):
        preserve.append(payload["outside_preserve"])
    if payload.get("log"):
        log = root / "logs/simion__batch01.stdout.log"
        log.write_text("status,Fly completed. 1 splats, 0.1 seconds\\n" if payload["log"] == "complete" else "started\\n", encoding="utf-8")
        outputs.append(str(log)); required.append(str(log))
        if payload.get("preserve"): preserve.append(str(log))
    status = payload.get("status", "success")
    completion = {
        "schema_version": 1, "role": "run_artifact_workflow_completion",
        "run_id": config["run_id"], "project": config["project"],
        "execution_request": file_record(request_path), "run_config": file_record(config_path),
        "status": status, "summary": {"run_id": config["run_id"], "status": status},
        "output_paths": outputs, "required_output_paths": required,
        "retention_preserve_paths": preserve, "manifest_extra_fields": {},
        "writer_completion": payload.get("writers", {"operations": [], "resource_releases": []}),
        "exception": None if status == "success" else {"type": "FixtureFailure", "message": "original scientific failure", "notes": []},
    }
    if payload.get("summary_padding_bytes"):
        completion["summary"]["fixture_padding"] = "x" * payload["summary_padding_bytes"]
    if payload.get("change_request"):
        request_path.write_text("{}", encoding="utf-8")
    if payload.get("change_lifecycle"):
        config["artifact_retention"]["class"] = "qualification"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        completion["run_config"] = file_record(config_path)
    completion_path.write_text(json.dumps(completion), encoding="utf-8")
    if payload.get("late_output"):
        time.sleep(.2)
        print("late prepared stdout 中文", flush=True)
        print("late prepared stderr 中文", file=sys.stderr, flush=True)
    if status != "success": raise RuntimeError("original scientific failure")
'''


def released_writer() -> dict:
    """Synthetic structural receipt, never presented as a real scheduler event."""
    return {
        "operations": [{"operation_id": "native", "observation": {"exit_confirmed": True, "returncode": 0},
                        "resource_release_id": "pool"}],
        "resource_releases": [{"release_id": "pool", "completion_receipt": {"host_release": {
            "inherited": False, "token": "fixture-token", "result": {"status": "released", "token": "fixture-token"},
            "error": None,
        }}}],
    }


@unittest.skipUnless(PWSH and os.name == "nt", "Windows PowerShell workflow boundary")
class RunArtifactWorkflowTests(unittest.TestCase):
    def test_direct_powershell_release_keeps_actual_transaction_fields(self):
        script=r'''param($Repo)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_workflow.ps1')
# Use the real Exit adapter with an isolated transaction boundary. No native
# process is represented by the inert grammar-only operation below.
function Invoke-HostResourceTransaction {param($StatePath,$Request) return [pscustomobject]@{status='released';token=$Request.token}}
$lease=@{inherited=$false;token='INERT_CONTRACT_TOKEN';completed_work_processes=@();state_path='unused';role='SIMION';stage='prepare';environment_set=$false}
$actual=Exit-HostResourceStage -Lease $lease -PassThru
if($actual-isnot[pscustomobject]){throw 'Fixture must exercise the actual direct adapter representation'}
$releases=[Collections.Generic.List[object]]::new()
Add-RunArtifactResourceRelease -ResourceReleases $releases -ReleaseId $lease.token -Receipt @{host_release=@{inherited=$false;token=$lease.token;result=$actual;error=$null}}
$completion=@{operations=@(@{operation_id='inert_contract_shape';resource_release_id=$lease.token;observation=@{exit_confirmed=$true;returncode=0;process_id=1;process_started_at_utc_ticks=1L}});resource_releases=@($releases.ToArray())}
Assert-WorkflowWriterCompletion $completion -PowerShellOwner
if($releases[0].completion_receipt.host_release.result-isnot[Collections.IDictionary]-or$actual.PSObject.Properties.Name.Count-ne2){throw 'Transaction adaptation changed the source'}
$inheritedActual=Exit-HostResourceStage -Lease @{inherited=$true;environment_set=$false} -PassThru
if($null-ne$inheritedActual){throw 'Actual inherited exit must not fabricate a transaction'}
$inherited=[Collections.Generic.List[object]]::new()
foreach($stage in 1..2){Add-RunArtifactResourceRelease -ResourceReleases $inherited -ReleaseId 'INERT_PARENT_TOKEN' -Receipt @{host_release=@{inherited=$true;token='INERT_PARENT_TOKEN';result=$inheritedActual;error=$null}}}
if($inherited.Count-ne1-or$null-ne$inherited[0].completion_receipt.host_release.result){throw 'Inherited stages did not share their actual null receipt'}
$conflict=$false
try{Add-RunArtifactResourceRelease -ResourceReleases $inherited -ReleaseId 'INERT_PARENT_TOKEN' -Receipt @{host_release=@{inherited=$true;token='INERT_PARENT_TOKEN';result=@{status='acquired';token='INERT_PARENT_TOKEN'};error=$null}}}catch{$conflict=$true}
if(-not$conflict){throw 'Fabricated inherited transaction was accepted as a duplicate'}
foreach($invalid in @([pscustomobject]@{status='released';token=$lease.token;extra='must_not_be_removed'},[pscustomobject]@{status='released';token='OTHER'})){
 $bad=[Collections.Generic.List[object]]::new()
 Add-RunArtifactResourceRelease -ResourceReleases $bad -ReleaseId $lease.token -Receipt @{host_release=@{inherited=$false;token=$lease.token;result=$invalid;error=$null}}
 $completion.resource_releases=@($bad.ToArray());$rejected=$false
 try{Assert-WorkflowWriterCompletion $completion -PowerShellOwner}catch{$rejected=$true}
 if(-not$rejected){throw 'Representation conversion relaxed the release contract'}
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'direct_release.ps1';path.write_text(script,encoding='utf-8',newline='\n')
            result=subprocess.run([PWSH,'-NoProfile','-File',str(path),str(REPO)],cwd=REPO,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def run_ps(self, root: Path, script: str) -> subprocess.CompletedProcess[str]:
        path = root / "invoke.ps1"
        path.write_text(script, encoding="utf-8")
        return subprocess.run([PWSH, "-NoProfile", "-File", str(path)], cwd=REPO,
                              capture_output=True, text=True, encoding="utf-8", timeout=90)

    def test_writer_receipt_rejects_unknown_inherited_conflicting_and_unbound(self) -> None:
        cases = [("direct_ps", released_writer(), True), ("pure", {"operations": [], "resource_releases": []}, True)]
        bridge = released_writer()
        bridge["resource_releases"][0]["completion_receipt"].update(
            bridge_process_exit_confirmed=True, bridge_process_returncode=0, host_release_confirmed=True)
        cases.append(("bridge", bridge, True))
        for name in ("unknown", "inherited", "wrong_token", "missing_release", "duplicate", "bridge_unknown", "acquired", "contradiction", "duplicate_token"):
            value = copy.deepcopy(bridge)
            receipt = value["resource_releases"][0]["completion_receipt"]
            if name == "unknown": value["operations"][0]["observation"]["exit_confirmed"] = False
            elif name == "inherited": receipt["host_release"]["inherited"] = True
            elif name == "wrong_token": receipt["host_release"]["result"]["token"] = "different"
            elif name == "missing_release": value["resource_releases"] = []
            elif name == "duplicate": value["operations"] *= 2
            elif name == "bridge_unknown": receipt["bridge_process_exit_confirmed"] = False
            elif name == "acquired": receipt["host_release"]["result"]["status"] = "acquired"
            elif name == "contradiction": receipt["host_release_confirmed"] = False
            elif name == "duplicate_token":
                second = copy.deepcopy(value["resource_releases"][0])
                second["release_id"] = "other"
                value["resource_releases"].append(second)
            cases.append((name, value, False))
        with tempfile.TemporaryDirectory(prefix="workflow-receipts-") as directory:
            root = Path(directory)
            data = root / "cases.json"
            data.write_text(json.dumps(cases), encoding="utf-8")
            outcome = self.run_ps(root, f""". '{OWNER}'
$cases=Get-Content -Raw '{data}'|ConvertFrom-Json -AsHashtable
foreach($case in $cases){{
  $accepted=$true
  try{{Assert-WorkflowWriterCompletion $case[1]}}catch{{$accepted=$false}}
  if($accepted-ne$case[2]){{throw ('Wrong writer verdict: '+$case[0])}}
}}
Write-Output 'RECEIPTS=PASS'
""")
            self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
            self.assertIn("RECEIPTS=PASS", outcome.stdout)

    def invoke_fixture(self, root: Path, payload: dict, *, retention: str = "compact", host_state: str | None = None,
                       observation_failure: bool = False, failure_stage: str | None = None, project: str = PROJECT,
                       callback_text: str | None = None) -> tuple[dict, Path, Path, subprocess.CompletedProcess[str]]:
        artifacts = root / "artifacts"
        artifacts.mkdir()
        initialize_capacity_ledger(artifacts, objects=[])
        callback = root / "fixture_callback.py"
        callback.write_text((CALLBACK if callback_text is None else callback_text).replace("REPOSITORY", repr(str(REPO))), encoding="utf-8")
        # Minimal fixture namespace for the real initial handshake. Production
        # prepared roots already carry this module in their frozen closure.
        (root / "common/contracts").mkdir(parents=True, exist_ok=True)
        for relative in ("common/host_resource_python.py", "common/contracts/recorded_file_removal.py", "common/contracts/file_identity.py"):
            shutil.copyfile(REPO / relative, root / relative)
        budget = root / "budget.json"
        committed = payload.get("fixture_commitment_bytes", 1048576)
        budget.write_text(json.dumps({"peak_bytes": committed}), encoding="utf-8")
        project_root = artifacts / "projects" / project
        run = project_root / "runs/20261028_120000__test__python__workflow-fixture"
        request = {
            "schema_version": 1, "role": "run_artifact_workflow_request", "repository_root": str(REPO),
            "python_executable": sys.executable,
            "package": {"project": project, "run_id": run.name, "mode": "software", "artifact_project_root": str(project_root),
                        "software": ["Python"], "retention_class": retention, "retention_reason": "review fixture" if retention != "compact" else ""},
            "capacity": {"committed_new_bytes": committed, "commitment_inputs": [file_record(budget)], "protected_paths": [], "protected_cache_keys": []},
            "prepared": {"module": "fixture_callback", "function": "execute_prepared_run", "import_root": str(root), "entrypoint": file_record(callback)},
            "payload": dict(payload, counter_path=str(root / "callback_count.txt")),
        }
        request_path, result_path = root / "request.json", root / "result.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        # Only disk/host admission is isolated: capacity lease CRUD, package,
        # retention, terminal journal and finalization use the actual TEMP ledger.
        state_setup = (f"$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH='{host_state}'" if host_state is not None else
                       "[Environment]::SetEnvironmentVariable('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH',[NullString]::Value,'Process')")
        sampler = "function Get-ManagedSolverProcessSample { throw 'fixture initial observation unavailable' }" if observation_failure else ""
        hooks = ""
        if failure_stage == "retention_before":
            hooks = "function Apply-RunArtifactRetention { throw 'fixture before retention' }"
        elif failure_stage == "retention_pending":
            # Run the real retention CLI, failing only its first progress write
            # after the actual unlink; no fake receipt or deletion is supplied.
            hooks = '''$script:retentionFailureCode=@'
import common.contracts.artifact_retention as owner
original = owner.write_json_atomic
def crash(path, value):
    if value.get("status") == "pending" and value.get("removed_file_count") == 1:
        raise OSError("fixture retention progress failure")
    return original(path, value)
owner.write_json_atomic = crash
owner.main()
'@
$needle=@'
& $Python (Join-Path $RepoRoot 'common\\contracts\\artifact_retention.py') @arguments
'@
$body=${function:Apply-RunArtifactRetention}.ToString().Replace($needle,'& $Python -B -c $script:retentionFailureCode @arguments')
Set-Item Function:Apply-RunArtifactRetention ([scriptblock]::Create($body))
'''
        elif failure_stage == "publication_journal":
            hooks = '''$injection=@'
import common.contracts.write_run_manifest as publisher_owner
original_write = publisher_owner.write_json_atomic
def crash(path, value):
    original_write(path, value)
    if path.name == "summary.json": raise OSError("fixture after summary publication")
publisher_owner.write_json_atomic = crash

'@
$needle='completion_path, session_path, wait_path = map(Path, sys.argv[1:4])'
$body=${function:Publish-WorkflowTerminal}.ToString().Replace($needle,$injection+"`n"+$needle)
Set-Item Function:Publish-WorkflowTerminal ([scriptblock]::Create($body))
'''
        elif failure_stage == "seal":
            hooks = '''$script:realCapacityCommand=${function:Invoke-RunCapacityCommand}
function Invoke-RunCapacityCommand {
  param($Python,$RepoRoot,$Arguments,$FailureLabel)
  if('seal-stopped-payload'-in$Arguments){throw 'fixture stopped payload seal failure'}
  & $script:realCapacityCommand @PSBoundParameters
}
'''
        elif failure_stage == "release":
            hooks = "function Exit-ArtifactWorkflowCapacitySession { throw 'fixture capacity release failure' }"
        outcome = self.run_ps(root, f""". '{OWNER}'
{state_setup}
{sampler}
Write-RunJson -Path '{root / 'expected_context.json'}' -Value @{{host_resource_state_path=(Resolve-HostResourceStatePath)}}
function Invoke-ArtifactCapacityGate {{ return @{{satisfied=$true;fixture_admission=$true}} }}
{hooks}
try{{$null=Invoke-RunArtifactWorkflow -RequestPath '{request_path}' -ResultPath '{result_path}'}}
catch{{Write-Output $_.Exception.Message;exit 7}}
""")
        self.assertTrue(result_path.is_file(), outcome.stdout + outcome.stderr)
        return json.loads(result_path.read_text(encoding="utf-8-sig")), run, artifacts, outcome

    def resume_fixture(self, root: Path, run: Path, *, fail_publication: bool = False) -> tuple[dict, subprocess.CompletedProcess[str]]:
        hook = "function Publish-WorkflowTerminal { throw 'fixture recovery publication failure' }" if fail_publication else ""
        outcome = self.run_ps(root, f""". '{OWNER}'
function Invoke-ArtifactCapacityGate {{
 param($ArtifactRoot,$CapacityProtectionLeaseId)
 $lease=Get-Content -LiteralPath (Join-Path $ArtifactRoot ('common/capacity_protection_leases/'+$CapacityProtectionLeaseId+'.json')) -Raw|ConvertFrom-Json
 return @{{satisfied=$true;fixture_admission=$true;admitted_lease_committed_new_bytes=$lease.committed_new_bytes}}
}}
{hook}
try{{$null=Invoke-RunArtifactWorkflow -RequestPath '{run / 'inputs/execution_request.json'}' -ResultPath '{root / 'result.json'}' -ResumeFinalization}}
catch{{Write-Output $_.Exception.Message;exit 7}}
""")
        return json.loads((root / "result.json").read_text(encoding="utf-8-sig")), outcome

    def test_powershell_owner_all_reuse_resumes_after_owner_exits(self) -> None:
        # Exercise the real capacity session and journal with an owner that has
        # no native writers (the RF all-reuse path). The publishing failure is
        # injected before journal creation; a second PowerShell process resumes.
        with tempfile.TemporaryDirectory(prefix="workflow-ps-owner-") as directory:
            root = Path(directory)
            _, run, _, _ = self.invoke_fixture(root, {}, failure_stage="retention_before")
            request_path = run / "inputs/execution_request.json"
            request = json.loads(request_path.read_text(encoding="utf-8-sig"))
            entry = run / "inputs/owner.ps1"
            entry.write_text("# frozen all-reuse owner fixture\n", encoding="utf-8")
            request["prepared"] = {"owner_kind": "powershell", "entrypoint": file_record(entry)}
            request_path.write_text(json.dumps(request), encoding="utf-8")
            completion_path = run / "results/execution_completion.json"
            completion = json.loads(completion_path.read_text(encoding="utf-8-sig"))
            completion["execution_request"] = file_record(request_path)
            completion["writer_completion"] = {"operations": [], "resource_releases": []}
            completion["resource_usage_paths"] = []
            completion["resource_profile"] = None
            completion_path.write_text(json.dumps(completion), encoding="utf-8")
            (root / "result.json").unlink()
            initial = self.run_ps(root, f""". '{OWNER}'
function Invoke-ArtifactCapacityGate {{ return @{{satisfied=$true;fixture_admission=$true}} }}
$config=Get-Content '{run / 'run_config.json'}' -Raw|ConvertFrom-Json
$alias=New-RunExecutionAlias -TargetDirectory '{run}' -ExecutionRoot $config.paths.execution_root
$completion=Get-Content '{completion_path}' -Raw|ConvertFrom-Json -AsHashtable
$completion.execution_alias=@{{path=$alias.execution_alias;target_directory='{run}'}}
Write-RunJson -Atomic -Path '{completion_path}' -Value $completion
$wait=@{{schema_version=1;role='run_artifact_powershell_owner_wait';owner_pid=$PID;
  owner_start_utc_ticks=(Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks;
  native_writers_confirmed=$true;exception=$null;observation_error=$null}}
Write-RunJson -Atomic -Path '{run / 'logs/prepared_wait.json'}' -Value $wait
function Publish-WorkflowTerminal {{ throw 'fixture publication failure' }}
try{{$null=Invoke-RunArtifactWorkflow -RequestPath '{request_path}' -ResultPath '{root / 'result.json'}' -ResumeFinalization}}catch{{Write-Output $_.Exception.Message;exit 7}}
""")
            self.assertEqual(initial.returncode, 7, initial.stdout + initial.stderr)
            self.assertTrue((root / "result.json").exists(), initial.stdout + initial.stderr)
            saved = json.loads(completion_path.read_text(encoding="utf-8-sig"))
            self.assertFalse(Path(saved["execution_alias"]["path"]).exists())
            self.assertFalse((run / "run_manifest.json").read_text(encoding="utf-8-sig").find('"status": "success"') >= 0)
            result, resumed = self.resume_fixture(root, run)
            self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
            self.assertEqual(result["status"], "success")
            self.assertTrue(result["execution_alias_removed"])


    def test_ip_original_cli_replays_public_owner_after_publication_or_seal_failure(self) -> None:
        project = "dual_pressure_rectilinear_ion_processor"
        cli = REPO / "projects" / project / "simion/run_functional.ps1"
        for failure in ("publication", "seal", "unknown"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory(prefix="ip-owner-recovery-") as directory:
                root = Path(directory)
                _, run, _, _ = self.invoke_fixture(root, {}, project=project, retention="solver_review", failure_stage="retention_before")
                config_path = run / "run_config.json"
                config = json.loads(config_path.read_text(encoding="utf-8-sig"))
                config["mode"] = "native_electrode_functional"
                config_path.write_text(json.dumps(config), encoding="utf-8")
                for relative in ("inputs/execution_request.json", "results/execution_completion.json", "logs/prepared_wait.json"):
                    (run / relative).unlink()
                entry = run / "inputs/run_functional.ps1"
                shutil.copyfile(cli, entry)
                budget = run / "inputs/runtime_profiles.json"
                budget.write_text('{"fixture_budget_bytes":1048576}', encoding="utf-8")
                result_path = run.parent.parent / "scratch/workflow_results" / run.name / "result.json"
                hook = "function Publish-WorkflowTerminal { throw 'IP_PUBLICATION_SENTINEL' }" if failure == "publication" else ""
                if failure == "seal":
                    hook = """$actualCapacity=${function:Invoke-RunCapacityCommand}
function Invoke-RunCapacityCommand {
 param($Python,$RepoRoot,$Arguments,$FailureLabel)
 if('seal-stopped-payload'-in$Arguments){throw 'IP_SEAL_SENTINEL'}
 & $actualCapacity @PSBoundParameters
}
"""
                execution = "writer_completion_unknown" if failure == "unknown" else "completed"
                validity = "unknown" if failure == "unknown" else "valid"
                science = "unknown" if failure == "unknown" else "passed"
                first = self.run_ps(root, f""". '{OWNER}'
function Invoke-ArtifactCapacityGate {{ return @{{satisfied=$true;fixture_admission=$true}} }}
function Invoke-ResourceBudgetedProcess {{throw 'NATIVE_MUST_NOT_START'}}
$session=Get-Content '{run / 'logs/capacity_session.json'}' -Raw|ConvertFrom-Json
$package=@{{native_path_preparation=@{{calls=0;elapsed_seconds=0.0;transport_bytes=0L}};run_config='{config_path}';run_dir='{run}';artifact_run_dir='{run}'}}
$context=Initialize-RunArtifactPowerShellOwner -Python '{sys.executable}' -RepoRoot '{REPO}' -Package $package -CapacitySession $session -EntrypointPath '{entry}' -CommitmentInputPaths @('{budget}') -Software @('Python')
{hook}
try {{
 $outcome=Complete-RunArtifactPowerShellOwner -Context $context -Status success -Summary @{{role='ion_processor_functional_summary';execution_status='{execution}';data_validity='{validity}';science_status='{science}';phase_durations_seconds=@{{analysis=0.1}};total_elapsed_seconds=0.1}} -OutputPaths @('{run / 'results/science.json'}') -WriterCompletion @{{operations=@();resource_releases=@()}} -WritersStopped ${str(failure != 'unknown').lower()}
 throw 'Expected closeout injection did not fail'
}} catch {{
 if($_.Exception.Message-notmatch'IP_PUBLICATION_SENTINEL|IP_SEAL_SENTINEL|writer completion is unknown'){{throw}}
 if($context.completion_written-ne${str(failure != 'unknown').lower()}){{throw 'Completion persistence state differs'}}
}}
""")
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                result = json.loads(result_path.read_text(encoding="utf-8-sig"))
                self.assertEqual(result["resume_action"], "inspect_writer_completion" if failure == "unknown" else "resume_finalization")
                if failure == "unknown":
                    self.assertEqual(result["execution_status"], "writer_completion_unknown")
                    self.assertEqual(result["data_validity"], "unknown")
                    self.assertEqual(result["recovery_action"], "inspect_writer_completion")
                    self.assertEqual(result["phase_timings_seconds"], {"analysis": 0.1})
                terminal_before = (run / "run_manifest.json").read_bytes()
                command = [PWSH, "-NoProfile", "-File", str(cli), "-RunId", run.name,
                           "-ResultPath", str(result_path), "-ResumeFinalization"]
                resumed = subprocess.run(command, cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=90)
                if failure == "unknown":
                    self.assertNotEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
                    self.assertEqual((run / "run_manifest.json").read_bytes(), terminal_before)
                    self.assertIn(run.resolve(), load_capacity_protection_leases(root / "artifacts")["protected_paths"])
                    continue
                self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
                result = json.loads(result_path.read_text(encoding="utf-8-sig"))
                self.assertTrue(result["terminal_published"] and result["capacity_finalized"] and result["lease_released"])
                self.assertEqual(result["scientific_result"], "passed")
                self.assertGreaterEqual(result["total_elapsed_seconds"], 0.1)
                if failure == "seal":
                    self.assertEqual((run / "run_manifest.json").read_bytes(), terminal_before)
                manifest_bytes = (run / "run_manifest.json").read_bytes()
                summary_bytes = (run / "summary.json").read_bytes()
                repeated = subprocess.run(command, cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=90)
                self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
                self.assertEqual((run / "run_manifest.json").read_bytes(), manifest_bytes)
                self.assertEqual((run / "summary.json").read_bytes(), summary_bytes)
                self.assertEqual((root / "callback_count.txt").read_text(), "1")

    def test_powershell_unknown_host_preserves_owner_reason_primary_and_secondary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-host-unconfirmed-") as directory:
            root = Path(directory)
            _, run, _, _ = self.invoke_fixture(root, {}, retention="solver_review", failure_stage="retention_before")
            for relative in ("inputs/execution_request.json", "results/execution_completion.json", "logs/prepared_wait.json"):
                (run / relative).unlink()
            entry = run / "inputs/owner.ps1"
            entry.write_text("# inert frozen owner; no native execution\n", encoding="utf-8")
            budget = run / "inputs/budget.json"
            budget.write_text('{"peak_bytes":1048576}', encoding="utf-8")
            raw = run / "results/raw.csv"
            raw.write_text("inert complete raw fixture retained unchanged\n", encoding="utf-8")
            original_raw = raw.read_bytes()
            original_manifest = (run / "run_manifest.json").read_bytes()
            original_summary = (run / "summary.json").read_bytes()
            result_path = root / "host_result.json"
            outcome = self.run_ps(root, f""". '{OWNER}'
$session=Get-Content '{run / 'logs/capacity_session.json'}' -Raw|ConvertFrom-Json
$leasePath=[string]$session.lease.path;$leaseBefore=[Convert]::ToBase64String([IO.File]::ReadAllBytes($leasePath))
$package=@{{native_path_preparation=@{{calls=0;elapsed_seconds=0.0;transport_bytes=0L}};run_config='{run / 'run_config.json'}';run_dir='{run}';artifact_run_dir='{run}'}}
$context=Initialize-RunArtifactPowerShellOwner -Python '{sys.executable}' -RepoRoot '{REPO}' -Package $package -CapacitySession $session -ResultPath '{result_path}' -EntrypointPath '{entry}' -CommitmentInputPaths @('{budget}') -Software @('Python')
function Apply-RunArtifactRetention {{throw 'RETENTION_MUST_NOT_RUN'}}
function Publish-WorkflowTerminal {{throw 'TERMINAL_MUST_NOT_RUN'}}
function Exit-ArtifactWorkflowCapacitySession {{throw 'LEASE_MUST_NOT_RELEASE'}}
try{{throw 'PRIMARY_ANALYSIS_SENTINEL'}}catch{{$primary=$_}}
$summary=@{{execution_status='host_release_unconfirmed';data_validity='valid';science_status='not_passed';failure_stage='host_release';failure_reason='HOST_RELEASE_SENTINEL';recovery_action='inspect_host_release';secondary_errors=@('HOST_RELEASE_SENTINEL');phase_timings_seconds=@{{analysis=0.2}};total_elapsed_seconds=0.3}}
$guard=[IO.File]::Open('{raw}',[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
try{{
 try{{Complete-RunArtifactPowerShellOwner -Context $context -Status failed -Summary $summary -WriterCompletion @{{operations=@();resource_releases=@()}} -WritersStopped $false -OriginalFailure $primary|Out-Null;throw 'unknown host accepted'}}catch{{if($_.Exception.Message-notmatch'writer completion is unknown'){{throw}}}}
 $blocked=$false;try{{$writer=[IO.File]::Open('{raw}',[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite);$writer.Dispose()}}catch{{$blocked=$true}}
 if(-not$blocked){{throw 'owner guard was lost'}}
}}finally{{$guard.Dispose()}}
if($context.completion_written-or$context.finalized){{throw 'unknown host claimed completion'}}
if([Convert]::ToBase64String([IO.File]::ReadAllBytes($leasePath))-cne$leaseBefore){{throw 'host failure changed capacity protection'}}
""")
            self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
            result = json.loads(result_path.read_text(encoding="utf-8-sig"))
            self.assertEqual((result["status"], result["writers_confirmed"]), ("failed", False))
            self.assertEqual((result["execution_status"], result["data_validity"], result["scientific_result"]),
                             ("host_release_unconfirmed", "valid", "not_passed"))
            self.assertEqual(result["failure_stage"], "host_release")
            self.assertEqual(result["failure_reason"], "HOST_RELEASE_SENTINEL")
            self.assertEqual(result["resume_action"], "inspect_host_release")
            self.assertEqual(result["recovery_action"], "inspect_host_release")
            self.assertEqual(result["exception"]["message"], "PRIMARY_ANALYSIS_SENTINEL")
            self.assertEqual(result["exception"]["notes"], [])
            self.assertEqual(result["secondary_errors"], ["HOST_RELEASE_SENTINEL"])
            self.assertEqual(result["phase_timings_seconds"], {"analysis": 0.2})
            self.assertEqual(result["total_elapsed_seconds"], 0.3)
            self.assertEqual(raw.read_bytes(), original_raw)
            self.assertEqual((run / "run_manifest.json").read_bytes(), original_manifest)
            self.assertEqual((run / "summary.json").read_bytes(), original_summary)
            self.assertFalse((run / "results/execution_completion.json").exists())
            self.assertFalse((run / "logs/prepared_wait.json").exists())

    def test_powershell_inherited_grant_is_rechecked_across_processes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-ps-inherited-") as directory:
            root = Path(directory)
            _, run, _, _ = self.invoke_fixture(root, {}, host_state=str(root / "host.json"), failure_stage="retention_before")
            request_path = run / "inputs/execution_request.json"
            request = json.loads(request_path.read_text(encoding="utf-8-sig"))
            entry = run / "inputs/owner.ps1"
            entry.write_text("# frozen inherited owner fixture\n", encoding="utf-8")
            request["prepared"] = {"owner_kind": "powershell", "entrypoint": file_record(entry)}
            request_path.write_text(json.dumps(request), encoding="utf-8")
            completion_path = run / "results/execution_completion.json"
            completion = json.loads(completion_path.read_text(encoding="utf-8-sig"))
            completion["execution_request"] = file_record(request_path)
            completion["resource_usage_paths"] = []
            completion["resource_profile"] = None
            completion_path.write_text(json.dumps(completion), encoding="utf-8")
            (root / "result.json").unlink()
            child = root / "inherited_child.ps1"
            child.write_text(f""". '{OWNER}'
$ErrorActionPreference='Stop'
function Invoke-ArtifactCapacityGate {{ return @{{satisfied=$true;fixture_admission=$true}} }}
if($args[0]-eq'first'){{
  $proc=Start-Process -FilePath '{sys.executable}' -ArgumentList @('-c','pass') -PassThru
  $ticks=$proc.StartTime.ToUniversalTime().Ticks;$proc.WaitForExit()
  $grant=Invoke-HostResourceTransaction -Request @{{operation='inherit';token=$env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN}} -StatePath $env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH
  $childLease=Enter-HostResourceStage -Role SIMION -Stage flight -Budget (Get-HostResourceBudget -Role SIMION -Stage flight)
  $actualExit=Exit-HostResourceStage -Lease $childLease -PassThru
  if($null-ne$actualExit){{throw 'Inherited Exit unexpectedly returned a transaction'}}
  $completion=Get-Content -Raw '{completion_path}'|ConvertFrom-Json -AsHashtable
  $completion.writer_completion=@{{operations=@(@{{operation_id='native';observation=@{{exit_confirmed=$true;returncode=$proc.ExitCode;process_id=$proc.Id;process_started_at_utc_ticks=$ticks}};resource_release_id='simion'}});
    resource_releases=@(@{{release_id='simion';completion_receipt=@{{host_release=@{{inherited=$true;token=$grant.token;result=$actualExit;error=$null}}}}}})}}
  Write-RunJson -Atomic -Path '{completion_path}' -Value $completion -Depth 64
  Write-RunJson -Atomic -Path '{run / 'logs/prepared_wait.json'}' -Value @{{schema_version=1;role='run_artifact_powershell_owner_wait';owner_pid=$PID;owner_start_utc_ticks=(Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks;native_writers_confirmed=$true;exception=$null;observation_error=$null}}
  function Publish-WorkflowTerminal {{ throw 'fixture publication failure' }}
}}
try{{$null=Invoke-RunArtifactWorkflow -RequestPath '{request_path}' -ResultPath '{root / 'result.json'}' -ResumeFinalization}}catch{{Write-Output $_.Exception.Message;exit 7}}
""", encoding="utf-8")
            outcome = self.run_ps(root, f""". '{OWNER}'
$ErrorActionPreference='Stop'
[Environment]::SetEnvironmentVariable('MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN',[NullString]::Value,'Process')
$lease=Enter-HostResourceStage -Role SIMION -Stage flight -StatePath '{root / 'host.json'}' -Budget (Get-HostResourceBudget -Role SIMION -Stage flight)
try{{
 & '{PWSH}' -NoProfile -File '{child}' first
 if($LASTEXITCODE-ne7){{throw 'initial publication did not fail'}}
 & '{PWSH}' -NoProfile -File '{child}' resume
 if($LASTEXITCODE-ne0){{throw 'inherited recovery failed'}}
 $terminalHash=(Get-FileHash -Algorithm SHA256 '{run / 'run_manifest.json'}').Hash
}}finally{{Exit-HostResourceStage -Lease $lease}}
& '{PWSH}' -NoProfile -File '{child}' resume
if($LASTEXITCODE-ne7){{throw 'expired inherited grant was accepted'}}
if((Get-FileHash -Algorithm SHA256 '{run / 'run_manifest.json'}').Hash-ne$terminalHash){{throw 'terminal was changed'}}
""")
            self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
            self.assertEqual(json.loads((root / "result.json").read_text(encoding="utf-8-sig"))["status"], "failed")

    def test_public_powershell_owner_preserves_inherited_capacity_until_parent_seals(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-inherited-capacity-") as directory:
            root = Path(directory)
            _, run, _, _ = self.invoke_fixture(root, {}, retention="solver_review", failure_stage="retention_before")
            for relative in ("inputs/execution_request.json", "results/execution_completion.json", "logs/prepared_wait.json"):
                (run / relative).unlink()
            entry = run / "inputs/owner.ps1"
            entry.write_text("# inert frozen PowerShell owner fixture\n", encoding="utf-8")
            budget = run / "inputs/budget.json"
            budget.write_text('{"peak_bytes":1048576}', encoding="utf-8")
            payload = run / "results/retained.pa0"
            payload.write_bytes(b"inert native-format payload fixture; no solver executed")
            parent = root / "parent_summary.json"
            parent.write_text('{"status":"success","fixture_parent":true}', encoding="utf-8")
            outcome = self.run_ps(root, f""". '{OWNER}'
function Invoke-ArtifactCapacityGate {{ return @{{satisfied=$true;fixture_admission=$true}} }}
$old=Get-Content '{run / 'logs/capacity_session.json'}' -Raw|ConvertFrom-Json
Exit-ArtifactWorkflowCapacitySession -Python '{sys.executable}' -RepoRoot '{REPO}' -Session $old|Out-Null
$session=Enter-ArtifactWorkflowCapacitySession -Python '{sys.executable}' -RepoRoot '{REPO}' -ArtifactRoot '{root / 'artifacts'}' -RunDirectory '{run}' -CommittedNewBytes 1048576 -ProtectedPaths @('{run}') -Owner 'fixture-existing-parent-owner'
$leasePath=[string]$session.lease.path;$leaseBytes=[IO.File]::ReadAllBytes($leasePath);$parentBytes=[IO.File]::ReadAllBytes('{parent}')
$package=@{{native_path_preparation=@{{calls=0;elapsed_seconds=0.0;transport_bytes=0L}};run_config='{run / 'run_config.json'}';run_dir='{run}';artifact_run_dir='{run}'}}
$context=Initialize-RunArtifactPowerShellOwner -Python '{sys.executable}' -RepoRoot '{REPO}' -Package $package -CapacitySession $session -EntrypointPath '{entry}' -CommitmentInputPaths @('{budget}') -Software @('Python') -OwnCapacitySession $false
$actualPublisher=${{function:Publish-WorkflowTerminal}}
function Publish-WorkflowTerminal {{throw 'INHERITED_PUBLICATION_SENTINEL'}}
try {{Complete-RunArtifactPowerShellOwner -Context $context -Status success -Summary @{{execution_status='completed';data_validity='valid';scientific_result='fixture_only'}} -OutputPaths @('{payload}','{run / 'results/science.json'}') -WriterCompletion @{{operations=@();resource_releases=@()}} -WritersStopped $true|Out-Null;throw 'injection not reached'}}catch{{if($_.Exception.Message-ne'INHERITED_PUBLICATION_SENTINEL'){{throw}}}}
Set-Item Function:Publish-WorkflowTerminal $actualPublisher
$first=Invoke-RunArtifactWorkflow -RequestPath $context.request_path -ResultPath $context.result_path -ResumeFinalization
if($first.status-ne'success'-or$first.capacity_finalized-or$first.lease_released-or$first.resume_action-ne'parent_capacity_owner_finalize'){{throw 'inherited child claimed parent finalization'}}
if([Convert]::ToBase64String([IO.File]::ReadAllBytes($leasePath))-cne[Convert]::ToBase64String($leaseBytes)){{throw 'child changed parent lease or commitment'}}
$manifestBytes=[IO.File]::ReadAllBytes('{run / 'run_manifest.json'}');$summaryBytes=[IO.File]::ReadAllBytes('{run / 'summary.json'}')
$second=Invoke-RunArtifactWorkflow -RequestPath $context.request_path -ResultPath $context.result_path -ResumeFinalization
if($second.capacity_finalized-or$second.resume_action-ne'parent_capacity_owner_finalize'){{throw 'repeat child stole parent finalization'}}
Exit-ArtifactWorkflowCapacitySession -Python '{sys.executable}' -RepoRoot '{REPO}' -Session $session|Out-Null
$blocked=$false
try{{Invoke-RunArtifactWorkflow -RequestPath $context.request_path -ResultPath $context.result_path -ResumeFinalization|Out-Null}}catch{{$blocked=$true}}
if(-not$blocked){{throw 'missing parent authority was accepted'}}
$result=Get-Content $context.result_path -Raw|ConvertFrom-Json
if($result.resume_action-ne'parent_capacity_owner_finalize'){{throw 'missing parent recovery action'}}
& '{sys.executable}' -m common.contracts.run_capacity_lifecycle --action seal-stopped-payload --artifact-root '{root / 'artifacts'}' --run-config '{run / 'run_config.json'}' --owner '{PROJECT}' --confirm-writing-stopped --retention-reason 'review fixture'|Out-Null
if($LASTEXITCODE-ne0){{throw 'actual parent sealing failed'}}
$closed=Invoke-RunArtifactWorkflow -RequestPath $context.request_path -ResultPath $context.result_path -ResumeFinalization
if(-not$closed.capacity_finalized-or$closed.lease_released-or$closed.status-ne'success'){{throw 'parent ready state was not reused'}}
foreach($pair in @(@('{run / 'run_manifest.json'}',$manifestBytes),@('{run / 'summary.json'}',$summaryBytes),@('{parent}',$parentBytes))){{if([Convert]::ToBase64String([IO.File]::ReadAllBytes($pair[0]))-cne[Convert]::ToBase64String($pair[1])){{throw 'terminal evidence was rewritten'}}}}
""")
            self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)

    def test_public_powershell_failed_owner_retains_complete_batches_and_latest_scope(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-complete-batch-retention-") as directory:
            root = Path(directory)
            _, run, _, _ = self.invoke_fixture(root, {}, retention="solver_review", failure_stage="retention_before")
            for relative in ("inputs/execution_request.json", "results/execution_completion.json", "logs/prepared_wait.json"):
                (run / relative).unlink()
            entry = run / "inputs/owner.ps1"
            entry.write_text("# inert frozen owner fixture\n", encoding="utf-8")
            budget = run / "inputs/budget.json"
            budget.write_text('{"peak_bytes":1048576}', encoding="utf-8")
            complete = run / "logs/simion__batch1.stdout.log"
            incomplete = run / "logs/simion__batch2.stdout.log"
            complete.write_text("status,Fly completed. 1 splats, 0.1 seconds\n", encoding="utf-8")
            incomplete.write_text("started\n", encoding="utf-8")
            external = root / "artifacts/projects" / PROJECT / "runs/20261028_115959__test__python__dependency/results/evidence.txt"
            external.parent.mkdir(parents=True)
            external.write_text("existing protected dependency fixture", encoding="utf-8")
            outcome = self.run_ps(root, f""". '{OWNER}'
function Invoke-ArtifactCapacityGate {{ return @{{satisfied=$true;fixture_admission=$true}} }}
$session=Get-Content '{run / 'logs/capacity_session.json'}' -Raw|ConvertFrom-Json
$package=@{{native_path_preparation=@{{calls=0;elapsed_seconds=0.0;transport_bytes=0L}};run_config='{run / 'run_config.json'}';run_dir='{run}';artifact_run_dir='{run}'}}
$context=Initialize-RunArtifactPowerShellOwner -Python '{sys.executable}' -RepoRoot '{REPO}' -Package $package -CapacitySession $session -EntrypointPath '{entry}' -CommitmentInputPaths @('{budget}') -Software @('Python')
$context.session=(Update-ArtifactWorkflowCapacitySession -Python '{sys.executable}' -RepoRoot '{REPO}' -Session $context.session -ProtectedPaths @('{external}')).session
$request=Get-Content $context.request_path -Raw|ConvertFrom-Json -AsHashtable
$request.capacity.protected_paths=@($context.session.protected_paths)
Write-RunJson -Atomic -Path $context.request_path -Value $request -Depth 64
$result=Complete-RunArtifactPowerShellOwner -Context $context -Status failed -Summary @{{execution_status='failed';data_validity='unknown';scientific_result='fixture_failure'}} -OutputPaths @('{complete}','{incomplete}','{run / 'results/science.json'}') -RequiredOutputPaths @('{complete}','{external}') -WriterCompletion @{{operations=@();resource_releases=@()}} -WritersStopped $true
if($result.status-ne'failed'-or-not$result.terminal_published-or-not$result.capacity_finalized){{throw 'failed scientific result did not finish retention'}}
$snapshot=Get-Content '{run / 'logs/capacity_session.json'}' -Raw|ConvertFrom-Json
if('{external}'-notin@($snapshot.protected_paths)){{throw 'latest source scope was not persisted'}}
""")
            self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
            self.assertTrue(complete.exists())
            self.assertFalse(incomplete.exists())
            action = json.loads((run / "retention_actions.json").read_text(encoding="utf-8-sig"))
            self.assertEqual([item["path"] for item in action["preserved"]], [complete.relative_to(run).as_posix()])

    def test_rf_original_cli_resumes_existing_owner_completion(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-rf-cli-") as directory:
            root = Path(directory)
            _, run, _, _ = self.invoke_fixture(root, {}, failure_stage="retention_before", project="rf_multipole_ion_optics")
            request_path = run / "inputs/execution_request.json"
            request = json.loads(request_path.read_text(encoding="utf-8-sig"))
            entry = run / "inputs/owner.ps1"
            entry.write_text("# frozen all-reuse owner fixture\n", encoding="utf-8")
            request["prepared"] = {"owner_kind": "powershell", "entrypoint": file_record(entry)}
            request_path.write_text(json.dumps(request), encoding="utf-8")
            completion_path = run / "results/execution_completion.json"
            completion = json.loads(completion_path.read_text(encoding="utf-8-sig"))
            completion.update(execution_request=file_record(request_path), writer_completion={"operations": [], "resource_releases": []},
                              resource_usage_paths=[], resource_profile=None)
            completion_path.write_text(json.dumps(completion), encoding="utf-8")
            (root / "result.json").unlink()
            initial = self.run_ps(root, f""". '{OWNER}'
Write-RunJson -Atomic -Path '{run / 'logs/prepared_wait.json'}' -Value @{{schema_version=1;role='run_artifact_powershell_owner_wait';owner_pid=$PID;owner_start_utc_ticks=(Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks;native_writers_confirmed=$true;exception=$null;observation_error=$null}}
""")
            self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)
            fixture_repo = root / "simulation_repo"
            shutil.copytree(REPO / "common", fixture_repo / "common", ignore=shutil.ignore_patterns("__pycache__"))
            relative = Path("projects/rf_multipole_ion_optics/workflows/no_collision_transport/run_simion.ps1")
            cli = fixture_repo / relative
            cli.parent.mkdir(parents=True)
            shutil.copyfile(REPO / relative, cli)
            outcome = subprocess.run([PWSH, "-NoProfile", "-File", str(cli), "-ResumeFinalization", "-RunId", run.name,
                                      "-PythonExe", sys.executable, "-ResultPath", str(root / "result.json")],
                                     cwd=fixture_repo, capture_output=True, text=True, encoding="utf-8", timeout=90)
            self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
            self.assertIn("MULTIPOLE_SIMION_FINALIZATION=success", outcome.stdout)
            self.assertEqual(json.loads((root / "result.json").read_text(encoding="utf-8-sig"))["status"], "success")
            self.assertEqual((root / "callback_count.txt").read_text(), "1")

    def test_retention_pending_and_expired_pre_retention_resume_without_prepared(self) -> None:
        for stage, lease_state in (("retention_pending", "active"), ("retention_before", "expired"),
                                   ("retention_pending", "expired"), ("retention_before", "missing")):
            with self.subTest(stage=stage, lease=lease_state), tempfile.TemporaryDirectory(prefix="workflow-recover-retention-") as directory:
                root = Path(directory)
                first, run, artifacts, process = self.invoke_fixture(root, {"disposable": True}, failure_stage=stage)
                self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
                science = (run / "results/science.json").read_bytes()
                old_id = first["lease_id"]
                baseline = sum(path.stat().st_size for path in run.rglob("*") if path.is_file())
                if lease_state != "active":
                    lease = artifacts / "common/capacity_protection_leases" / f"{old_id}.json"
                    if lease_state == "expired":
                        data = json.loads(lease.read_text()); data["expires_at_utc"] = "2001-01-01T00:00:00Z"
                        lease.write_text(json.dumps(data), encoding="utf-8")
                    else:
                        lease.unlink()
                    # The scientific author/plan may have changed after the old
                    # run. Recovery consumes only the frozen run authorities.
                    (root / "budget.json").write_text("changed live budget", encoding="utf-8")
                    (root / "fixture_callback.py").write_text("raise RuntimeError('must not import again')", encoding="utf-8")
                result, resumed = self.resume_fixture(root, run)
                self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
                self.assertTrue(result["terminal_published"] and result["capacity_finalized"] and result["lease_released"])
                self.assertEqual((run / "results/science.json").read_bytes(), science)
                self.assertEqual((root / "callback_count.txt").read_text(), "1")
                self.assertFalse((run / "results/first.pa0").exists())
                self.assertFalse((run / "results/second.pa0").exists())
                if lease_state != "active":
                    self.assertNotEqual(result["lease_id"], old_id)
                    self.assertEqual(result["recovery_session"]["committed_new_bytes"], 0)
                    budget = json.loads((REPO / "common/contracts/artifact_capacity_policy.json").read_text())["light_evidence_budget_bytes"]
                    # Admission is an immutable historical receipt; session.lease
                    # follows the actual renewal through zero and release.
                    session = result["recovery_session"]
                    self.assertEqual(session["startup_gate"]["admitted_lease_committed_new_bytes"], budget)
                    self.assertEqual(session["lease"]["committed_new_bytes"], 0)
                    self.assertEqual(session["status"], "released")
                    self.assertFalse((lease.parent / f"{session['lease_id']}.json").exists())
                    self.assertEqual(result["recovery_maximum_run_bytes"], baseline + budget)
                    if lease_state == "expired":
                        self.assertEqual(json.loads(lease.read_text())["expires_at_utc"], "2001-01-01T00:00:00Z")
                before = {name: (run / name).read_bytes() for name in ("summary.json", "run_manifest.json", "retention_actions.json")}
                repeated, replay = self.resume_fixture(root, run)
                self.assertEqual(replay.returncode, 0, replay.stdout + replay.stderr)
                self.assertTrue(repeated["capacity_finalized"])
                self.assertEqual({name: (run / name).read_bytes() for name in before}, before)
                self.assertEqual((root / "callback_count.txt").read_text(), "1")

    def test_recovery_reuses_fresh_lease_and_rejects_proof_or_terminal_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-recover-proof-") as directory:
            root = Path(directory)
            first, run, artifacts, _ = self.invoke_fixture(root, {"disposable": True}, failure_stage="retention_pending")
            lease = artifacts / "common/capacity_protection_leases" / f"{first['lease_id']}.json"
            data = json.loads(lease.read_text()); data["expires_at_utc"] = "2001-01-01T00:00:00Z"
            lease.write_text(json.dumps(data), encoding="utf-8")
            wait = run / "logs/prepared_wait.json"
            wait_before = wait.read_bytes()
            receipt_before = (run / "retention_actions.json").read_bytes()
            ledger_before = (artifacts / "common/capacity_ledger.json").read_bytes()
            modified = json.loads(wait_before); modified["fixture_tamper"] = True
            wait.write_text(json.dumps(modified), encoding="utf-8")
            _, rejected = self.resume_fixture(root, run)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual((run / "retention_actions.json").read_bytes(), receipt_before)
            self.assertEqual((artifacts / "common/capacity_ledger.json").read_bytes(), ledger_before)
            self.assertEqual(len(list(lease.parent.glob("workflow-*.json"))), 1)
            wait.write_bytes(wait_before)
            # Project wrappers may already have removed their TEMP result.
            # First recovery selects a stable outside-run transport; subsequent
            # retries must preserve it to reuse the fresh recovery session.
            (root / "result.json").unlink()
            stable = root / "stable-closeout"
            stable.mkdir()
            config = json.loads((run / "run_config.json").read_text())
            self.assertEqual(Path(config["inputs"]["execution_request"]), run / "inputs/execution_request.json")
            second, failed = self.resume_fixture(stable, run, fail_publication=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertFalse((root / "result.json").exists())
            self.assertTrue((stable / "result.json").is_file())
            recovery_id = second["recovery_session"]["lease_id"]
            self.assertNotEqual(recovery_id, first["lease_id"])
            third, completed = self.resume_fixture(stable, run)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(third["lease_id"], recovery_id)
            self.assertEqual((root / "callback_count.txt").read_text(), "1")
            manifest = (run / "run_manifest.json").read_bytes()
            ledger = (artifacts / "common/capacity_ledger.json").read_bytes()
            science = run / "results/science.json"
            science.write_bytes(science.read_bytes() + b" ")
            _, rejected = self.resume_fixture(stable, run)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual((run / "run_manifest.json").read_bytes(), manifest)
            self.assertEqual((artifacts / "common/capacity_ledger.json").read_bytes(), ledger)

    def test_recovery_publication_budget_bounds_combined_metadata_peak(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-recover-budget-") as directory:
            root = Path(directory)
            first, run, artifacts, process = self.invoke_fixture(root, {
                "summary_padding_bytes": 9 * 1024 * 1024, "fixture_commitment_bytes": 16 * 1024 * 1024,
            }, failure_stage="retention_before")
            self.assertNotEqual(process.returncode, 0)
            lease = artifacts / "common/capacity_protection_leases" / f"{first['lease_id']}.json"
            lease.unlink()
            baseline = sum(path.stat().st_size for path in run.rglob("*") if path.is_file())
            before = {name: (run / name).read_bytes() for name in ("summary.json", "run_manifest.json")}
            result, rejected = self.resume_fixture(root, run)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("metadata exceeds admitted run byte ceiling", rejected.stderr)
            self.assertFalse((run / ".run_terminal_publication.json").exists())
            self.assertEqual({name: (run / name).read_bytes() for name in before}, before)
            self.assertFalse(result["terminal_published"] or result["lease_released"])
            budget = result["recovery_session"]["lease"]["committed_new_bytes"]
            # Each prospective summary/journal is about 9 MiB, below 25 MiB;
            # their combined target/atomic-temporary peak must still be refused.
            self.assertGreater(budget, 9 * 1024 * 1024)
            self.assertEqual(result["recovery_maximum_run_bytes"], baseline + budget)
            self.assertLessEqual(sum(path.stat().st_size for path in run.rglob("*") if path.is_file()), baseline + budget)
            self.assertEqual((root / "callback_count.txt").read_text(), "1")

    def test_journal_and_seal_failures_resume_original_terminal_bytes(self) -> None:
        for stage, retention, status in (("publication_journal", "compact", "success"),
                                         ("publication_journal", "compact", "failed"),
                                         ("release", "solver_review", "success"),
                                         ("seal", "solver_review", "success")):
            with self.subTest(stage=stage, status=status), tempfile.TemporaryDirectory(prefix="workflow-recover-terminal-") as directory:
                root = Path(directory)
                payload = {"status": status, "log": "complete", "preserve": True} if status == "failed" else {}
                first, run, _, process = self.invoke_fixture(root, payload, retention=retention, failure_stage=stage)
                self.assertNotEqual(process.returncode, 0, process.stdout + process.stderr)
                native_log = run / "logs/simion__batch01.stdout.log"
                native_before = native_log.read_bytes() if native_log.exists() else None
                if stage == "publication_journal":
                    journal = json.loads((run / ".run_terminal_publication.json").read_text())
                    expected = journal["documents"]
                else:
                    expected = {name: json.loads((run / name).read_text()) for name in ("summary.json", "run_manifest.json")}
                    self.assertEqual(first["lease_released"], stage == "seal")
                    self.assertFalse(first["capacity_finalized"])
                    self.assertEqual(first["last_completed_stage"], "release" if stage == "seal" else "publication")
                    self.assertEqual(first["stage"], "capacity_finalization" if stage == "seal" else "release")
                result, process = self.resume_fixture(root, run)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                self.assertTrue(result["capacity_finalized"])
                self.assertEqual(result["status"], status)
                if stage == "seal":
                    self.assertNotIn("stopped_payload_receipt", first)
                    self.assertEqual(result["stopped_payload_receipt"]["action"], "seal_stopped_payload")
                    self.assertEqual(result["stopped_payload_receipt"]["run_config"], file_record(run / "run_config.json"))
                if status == "failed": self.assertEqual(result["exception"]["message"], "original scientific failure")
                self.assertFalse((run / ".run_terminal_publication.json").exists())
                self.assertEqual({name: json.loads((run / name).read_text()) for name in expected}, expected)
                self.assertEqual((root / "callback_count.txt").read_text(), "1")
                terminal_before = {name: (run / name).read_bytes() for name in expected}
                _, repeated = self.resume_fixture(root, run)
                self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
                self.assertEqual({name: (run / name).read_bytes() for name in expected}, terminal_before)
                if native_before is not None: self.assertEqual(native_log.read_bytes(), native_before)

    def test_deep_frozen_import_uses_run_execution_cwd_and_durable_recovery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-deep-python-") as directory:
            short = Path(directory)
            root = short
            while len(str(root)) <= 280:
                root = root / "frozen_source_segment"
            root.mkdir(parents=True)
            copy_started = time.perf_counter()
            shutil.copytree(REPO / "common", root / "common", ignore=lambda directory, _names:
                            {"__pycache__"} | ({"assets"} if Path(directory) == REPO / "common/simion" else set()))
            copied_bytes = sum(path.stat().st_size for path in (root / "common").rglob("*") if path.is_file())
            print(json.dumps({"fixture": "deep_frozen_python", "copied_bytes": copied_bytes,
                              "copy_seconds": time.perf_counter() - copy_started}))
            self.assertFalse((root / "common/simion/assets").exists())
            (root / "frozen_dependency.py").write_text("VALUE = 'frozen-only'\n", encoding="utf-8")
            (root / "frozen_resource.txt").write_text("frozen resource", encoding="utf-8")
            original = CALLBACK
            frozen = original.replace("sys.path.insert(0, REPOSITORY)", "from frozen_dependency import VALUE")
            frozen = frozen.replace("    config = json.loads", "    assert VALUE == 'frozen-only'\n    assert Path(__file__).with_name('frozen_resource.txt').read_text() == 'frozen resource'\n    assert Path.cwd() != Path(__file__).parent\n    config = json.loads", 1)
            execution = short / "execution"
            old_execution = os.environ.get("MASS_SPECTROMETRY_EXECUTION_ROOT")
            os.environ["MASS_SPECTROMETRY_EXECUTION_ROOT"] = str(execution)
            try:
                result, run, _, output = self.invoke_fixture(root, {}, callback_text=frozen)
            finally:
                if old_execution is None:
                    os.environ.pop("MASS_SPECTROMETRY_EXECUTION_ROOT", None)
                else:
                    os.environ["MASS_SPECTROMETRY_EXECUTION_ROOT"] = old_execution
            self.assertEqual(output.returncode, 0, output.stdout + output.stderr + str(result))
            self.assertEqual(result["status"], "success")
            self.assertTrue(result["execution_alias_removed"])
            completion = json.loads((run / "results/execution_completion.json").read_text(encoding="utf-8-sig"))
            self.assertFalse(Path(completion["execution_alias"]["path"]).exists())
            self.assertEqual(Path(completion["run_config"]["path"]), run / "run_config.json")
            stats = completion["summary"]["native_path_preparation"]
            self.assertGreater(stats["calls"], 0)
            self.assertGreaterEqual(stats["elapsed_seconds"], 0)
            self.assertEqual(stats["transport_bytes"], 0)
            self.assertEqual(result["native_path_preparation"], stats)
            self.assertEqual(json.loads((run / "summary.json").read_text(encoding="utf-8-sig"))["native_path_preparation"], stats)
            self.assertTrue((root / "frozen_resource.txt").is_file())
            before = (run / "run_manifest.json").read_bytes()
            resumed, recovery = self.resume_fixture(root, run)
            self.assertEqual(recovery.returncode, 0, recovery.stdout + recovery.stderr + str(resumed))
            self.assertEqual(resumed["status"], "success")
            self.assertEqual((root / "callback_count.txt").read_text(), "1")
            self.assertEqual(resumed["native_path_preparation"], stats)
            self.assertEqual((run / "run_manifest.json").read_bytes(), before)

    def test_pure_prepared_process_publishes_once_and_releases_one_lease(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-pure-") as directory:
            result, run, artifacts, output = self.invoke_fixture(Path(directory), {})
            self.assertEqual(output.returncode, 0, output.stdout + output.stderr + str(result))
            self.assertEqual(result["status"], "success")
            self.assertNotIn("execution_alias_removed", result)
            self.assertNotIn("stopped_payload_receipt", result)
            self.assertTrue(result["writers_confirmed"] and result["terminal_published"] and result["lease_released"])
            manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(manifest["status"], "success")
            self.assertTrue(json.loads((run / "summary.json").read_text())["writers_stopped"])
            self.assertEqual(load_capacity_ledger(artifacts)["objects"][0]["status"], "ready")
            session = json.loads((run / "logs/capacity_session.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(session["lease_id"], result["lease_id"])
            self.assertEqual(session["committed_new_bytes"], 1048576)
            self.assertFalse(load_capacity_protection_leases(artifacts)["protected_paths"])
            observed = json.loads((run / "results/science.json").read_text())["host_resource_state_path"]
            expected = json.loads((Path(directory) / "expected_context.json").read_text(encoding="utf-8-sig"))["host_resource_state_path"]
            self.assertEqual(observed, expected)
            self.assertEqual(result["execution_context"]["host_resource_state_path"], expected)

    def test_owner_timing_covers_failed_stage_and_finalization_only_resume(self) -> None:
        def check(result):
            self.assertGreater(result["elapsed_seconds"], 0)
            self.assertTrue(result["timing"])
            self.assertTrue(all(value >= 0 for value in result["timing"].values()))
            self.assertAlmostEqual(sum(result["timing"].values()), result["elapsed_seconds"], places=2)

        with tempfile.TemporaryDirectory(prefix="workflow-timing-") as directory:
            root = Path(directory)
            result, run, _, output = self.invoke_fixture(root, {}, failure_stage="retention_before")
            self.assertEqual(output.returncode, 7, output.stdout + output.stderr)
            check(result)
            self.assertEqual(result["stage"], "retention")
            self.assertEqual(result["last_completed_stage"], "completion")
            self.assertEqual(result["resume_action"], "resume_finalization")
            self.assertIn("prepared", result["timing"])
            result, output = self.resume_fixture(root, run)
            self.assertEqual(output.returncode, 0, output.stdout + output.stderr)
            check(result)
            self.assertEqual(result["stage"], "complete")
            self.assertIsNone(result["resume_action"])
            self.assertNotIn("prepared", result["timing"])
            self.assertEqual((root / "callback_count.txt").read_text(), "1")

    def test_explicit_control_plane_path_reaches_prepared_without_new_database(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-context-") as directory:
            root = Path(directory)
            state = root / "host.sqlite3"
            result, run, _, output = self.invoke_fixture(root, {}, host_state=str(state))
            self.assertEqual(output.returncode, 0, output.stdout + output.stderr)
            observed = json.loads((run / "results/science.json").read_text())["host_resource_state_path"]
            self.assertEqual(Path(observed), state)
            self.assertEqual(result["execution_context"]["host_resource_state_path"], observed)
            self.assertFalse(state.exists())

    def test_actual_worker_and_late_logs_close_before_terminal_hashes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-wait-") as directory:
            result, run, _, output = self.invoke_fixture(Path(directory), {"late_output": True})
            self.assertEqual(output.returncode, 0, output.stdout + output.stderr + str(result))
            receipt = json.loads((run / "logs/prepared_wait.json").read_text(encoding="utf-8-sig"))["managed_process"]
            self.assertTrue(receipt["ownership_confirmed"] and receipt["worker_exit_confirmed"])
            self.assertTrue(receipt["stdout_drained"] and receipt["stderr_drained"])
            actual_worker = json.loads((run / "results/science.json").read_text())["worker_process_id"]
            self.assertEqual(receipt["worker_process_id"], actual_worker)
            self.assertGreater(receipt["launcher_process_id"], 0)
            self.assertTrue(receipt["launcher_exit_confirmed"])
            manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8-sig"))
            before = {path: file_record(run / path) for path in ("logs/prepared_stdout.log", "logs/prepared_stderr.log")}
            time.sleep(.15)
            for name, record in before.items():
                self.assertEqual(file_record(run / name), record)
                sealed = next(item for item in manifest["outputs"] if Path(item["path"]) == run / name)
                self.assertEqual((sealed["bytes"], sealed["sha256"]), (record["bytes"], record["sha256"]))
                self.assertIn("late prepared", (run / name).read_text(encoding="utf-8"))

    def test_unconfirmed_actual_worker_cannot_start_or_publish(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-before-ack-") as directory:
            result, run, artifacts, output = self.invoke_fixture(Path(directory), {}, observation_failure=True)
            self.assertEqual(output.returncode, 7)
            self.assertIn("fixture initial observation unavailable", result["exception"]["message"])
            self.assertFalse(result["writers_confirmed"] or result["terminal_published"] or result["lease_released"])
            self.assertEqual(result["resume_action"], "inspect_writer_completion")
            self.assertEqual(result["last_completed_stage"], "initialize")
            self.assertGreater(result["timing"]["prepared"], 0)
            self.assertFalse((run / "results/science.json").exists())
            self.assertFalse((run / "results/execution_completion.json").exists())
            self.assertIn(run.resolve(), load_capacity_protection_leases(artifacts)["protected_paths"])

    def test_prepared_exception_is_structured_when_completion_is_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-original-error-") as directory:
            result, run, _, output = self.invoke_fixture(Path(directory), {"raise": True})
            self.assertEqual(output.returncode, 7)
            self.assertEqual(result["exception"]["type"], "RuntimeError")
            self.assertEqual(result["exception"]["message"], "original prepared fixture failure")
            self.assertTrue(result["secondary_errors"])
            self.assertFalse(result["terminal_published"] or result["lease_released"])
            self.assertIn("original prepared fixture failure", (run / "logs/prepared_stderr.log").read_text())

    def test_noncompact_releases_closed_run_before_existing_payload_seal(self) -> None:
        for retention, status in (("solver_review", "success"), ("qualification", "success"), ("solver_review", "failed")):
            with self.subTest(retention=retention, status=status), tempfile.TemporaryDirectory(prefix="workflow-seal-") as directory:
                result, run, artifacts, output = self.invoke_fixture(Path(directory), {"status": status}, retention=retention)
                self.assertEqual(output.returncode, 0, output.stdout + output.stderr + str(result))
                self.assertEqual(result["status"], status)
                self.assertTrue(result["capacity_finalized"] and result["lease_released"])
                entry = load_capacity_ledger(artifacts)["objects"][0]
                self.assertEqual(entry["class"], "rebuildable_payload")
                self.assertTrue(entry["pin"])
                self.assertEqual(entry["bytes"], sum(path.stat().st_size for path in run.rglob("*") if path.is_file()))
                receipt = result["stopped_payload_receipt"]
                self.assertEqual(receipt["role"], "run_capacity_lifecycle_receipt")
                self.assertEqual(receipt["action"], "seal_stopped_payload")
                self.assertEqual(receipt["run_status"], status)
                self.assertEqual(receipt["run_directory"], str(run))
                self.assertEqual(receipt["run_config"], file_record(run / "run_config.json"))
                self.assertEqual(receipt["ledger_entry"], entry)
                self.assertEqual(receipt["bytes"], entry["bytes"])
                self.assertEqual(receipt["file_count"], sum(path.is_file() for path in run.rglob("*")))

    def test_unknown_or_changed_identity_keeps_checkpoint_and_protection(self) -> None:
        unknown = released_writer()
        unknown["operations"][0]["observation"]["exit_confirmed"] = False
        for payload in ({"writers": unknown}, {"change_request": True}, {"change_lifecycle": True}, {"raise": True}):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory(prefix="workflow-reject-") as directory:
                result, run, artifacts, output = self.invoke_fixture(Path(directory), payload)
                self.assertEqual(output.returncode, 7)
                self.assertFalse(result["terminal_published"] or result["lease_released"])
                self.assertEqual(load_capacity_ledger(artifacts)["objects"][0]["status"], "writing")
                self.assertEqual(json.loads((run / "run_manifest.json").read_text(encoding="utf-8-sig"))["status"], "checkpoint")
                self.assertFalse((run / "retention_actions.json").exists())
                protected = load_capacity_protection_leases(artifacts)["protected_paths"]
                self.assertIn(run.resolve(), protected)

    def test_failed_completion_preserves_original_and_explicit_completed_log(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-failed-") as directory:
            result, run, _, output = self.invoke_fixture(Path(directory), {"status": "failed", "log": "complete", "preserve": True})
            self.assertEqual(output.returncode, 0, output.stdout + output.stderr + str(result))
            self.assertEqual(result["status"], "failed")
            self.assertTrue(result["terminal_published"] and result["lease_released"])
            self.assertEqual(result["exception"]["message"], "original scientific failure")
            self.assertTrue((run / "logs/simion__batch01.stdout.log").is_file())

    def test_required_is_not_preserve_and_incomplete_log_cannot_be_preserved(self) -> None:
        for preserve, log in ((False, "complete"), (True, "incomplete")):
            with self.subTest(preserve=preserve), tempfile.TemporaryDirectory(prefix="workflow-retention-") as directory:
                result, run, _, output = self.invoke_fixture(Path(directory), {"status": "failed", "log": log, "preserve": preserve})
                self.assertEqual(output.returncode, 7)
                self.assertFalse(result["terminal_published"] or result["lease_released"])
                self.assertEqual(result["exception"]["message"], "original scientific failure")
                self.assertTrue(result["secondary_errors"])
                self.assertEqual((run / "logs/simion__batch01.stdout.log").exists(), preserve)

    def test_preserve_path_cannot_escape_the_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-scope-") as directory:
            root = Path(directory)
            outside = root / "outside.stdout.log"
            outside.write_text("status,Fly completed. 1 splats, 0.1 seconds\n", encoding="utf-8")
            original = outside.read_bytes()
            result, run, _, output = self.invoke_fixture(root, {"outside_preserve": str(outside)})
            self.assertEqual(output.returncode, 7)
            self.assertIn("escapes the run", result["exception"]["message"])
            self.assertFalse(result["terminal_published"] or result["lease_released"])
            self.assertFalse((run / "retention_actions.json").exists())
            self.assertEqual(outside.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
