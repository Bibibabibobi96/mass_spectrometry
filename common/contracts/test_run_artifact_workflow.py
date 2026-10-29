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
    output.write_text(json.dumps({"capacity_session": session["lease_id"],
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
                       observation_failure: bool = False, failure_stage: str | None = None) -> tuple[dict, Path, Path, subprocess.CompletedProcess[str]]:
        artifacts = root / "artifacts"
        artifacts.mkdir()
        initialize_capacity_ledger(artifacts, objects=[])
        callback = root / "fixture_callback.py"
        callback.write_text(CALLBACK.replace("REPOSITORY", repr(str(REPO))), encoding="utf-8")
        # Minimal fixture namespace for the real initial handshake. Production
        # prepared roots already carry this module in their frozen closure.
        (root / "common/contracts").mkdir(parents=True)
        for relative in ("common/host_resource_python.py", "common/contracts/recorded_file_removal.py", "common/contracts/file_identity.py"):
            shutil.copyfile(REPO / relative, root / relative)
        budget = root / "budget.json"
        committed = payload.get("fixture_commitment_bytes", 1048576)
        budget.write_text(json.dumps({"peak_bytes": committed}), encoding="utf-8")
        project_root = artifacts / "projects" / PROJECT
        run = project_root / "runs/20261028_120000__test__python__workflow-fixture"
        request = {
            "schema_version": 1, "role": "run_artifact_workflow_request", "repository_root": str(REPO),
            "python_executable": sys.executable,
            "package": {"project": PROJECT, "run_id": run.name, "mode": "software", "artifact_project_root": str(project_root),
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
function Invoke-ArtifactCapacityGate {{ return @{{satisfied=$true;fixture_admission=$true}} }}
{hook}
try{{$null=Invoke-RunArtifactWorkflow -RequestPath '{run / 'inputs/execution_request.json'}' -ResultPath '{root / 'result.json'}' -ResumeFinalization}}
catch{{Write-Output $_.Exception.Message;exit 7}}
""")
        return json.loads((root / "result.json").read_text(encoding="utf-8-sig")), outcome

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
                    self.assertEqual(result["recovery_session"]["lease"]["committed_new_bytes"], budget)
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

    def test_pure_prepared_process_publishes_once_and_releases_one_lease(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-pure-") as directory:
            result, run, artifacts, output = self.invoke_fixture(Path(directory), {})
            self.assertEqual(output.returncode, 0, output.stdout + output.stderr + str(result))
            self.assertEqual(result["status"], "success")
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
            self.assertNotEqual(receipt["worker_process_id"], receipt["launcher_process_id"])
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
