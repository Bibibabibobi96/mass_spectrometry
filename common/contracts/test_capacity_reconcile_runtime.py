from __future__ import annotations

import json
import io
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from datetime import date, timedelta
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from common.contracts import capacity_ledger
from common.contracts import reconcile_artifact_capacity as capacity
from common.contracts.capacity_protection import create_capacity_protection_lease


READY_DUTIES = {
    "owner": "fixture_owner",
    "retention_reason": "finite test fixture retention",
    "review_deadline": "2026-10-22",
    "retirement_route": "owner_managed_disposition",
}
WRITING_DUTIES = {
    **READY_DUTIES,
    "recovery_reason": "fixture interrupted write",
    "recovery_task": "fixture owner must recover or retire",
    "recovery_evidence_paths": ["incomplete"],
}


class DailyCapacityReconcileTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell Core is required")
    def test_host_release_failure_preserves_original_error_and_stops_pressure_recovery(self) -> None:
        repo = Path(__file__).resolve().parents[2]
        script = r'''
$ErrorActionPreference='Stop'
$RepoRoot=$env:CAPACITY_FIXTURE_REPO
. (Join-Path $RepoRoot 'common/contracts/run_artifact_support.ps1')
$results=@(foreach($scenario in @('receipt','native','success','workflow_initial','workflow')){
  & {
    param($Scenario)
    $script:releaseCount=0
    $script:capacityCount=0
    $script:renewCount=0
    function Enter-HostExecutionLease { return [pscustomobject]@{} }
    function Exit-HostExecutionLease {
      param($Lease)
      $script:releaseCount++
      if($Scenario-ne'workflow'-or$script:releaseCount-eq2){throw 'fixture host release failure'}
    }
    function Update-ArtifactWorkflowCapacitySession { param($Python,$RepoRoot,$Session) $script:renewCount++ }
    function Invoke-RunCapacityCommand {
      param($Python,$RepoRoot,$Arguments,$FailureLabel)
      $script:capacityCount++
      if($Scenario-eq'native'){throw 'fixture native failure'}
      $mode=$Arguments[[array]::IndexOf($Arguments,'--execution-mode')+1]
      return (@{role='artifact_capacity_gate';execution_mode=$mode;
        capacity_protection_lease_id='fixture';measurement_mode='LEDGER_MAINTENANCE';
        satisfied_after_apply=($Scenario-eq'success');blocking_reason='TARGET_CAPACITY_EXCEEDED';
        resident_bytes=12;total_active_lease_committed_new_bytes=2;projected_bytes=14;
        target_bytes=10;free_bytes=100;capacity_gap_bytes=4;removed=@{bytes=0}}|ConvertTo-Json -Compress)
    }
    $result=@{scenario=$Scenario;failure=$null;cleanup=$null;stage=$null;receipt=$null}
    try{
      if($Scenario-like'workflow*'){
        $session=[pscustomobject]@{artifact_root=$RepoRoot;lease_id='fixture';protected_paths=@();protected_cache_keys=@()}
        Invoke-ArtifactWorkflowCapacityAdmission -Python fixture -RepoRoot $RepoRoot -Session $session|Out-Null
      }else{
        Invoke-ArtifactCapacityGate -Python fixture -RepoRoot $RepoRoot -ArtifactRoot $RepoRoot -CapacityProtectionLeaseId fixture|Out-Null
      }
    }catch{
      $result.failure=$_.Exception.Message
      $result.cleanup=$_.Exception.Data['host_execution_lease_cleanup']
      $result.receipt=$_.Exception.Data['capacity_receipt']
      if($null-ne$_.Exception.Data['pressure_maintenance']){
        $result.stage=$_.Exception.Data['pressure_maintenance'].stage
        $result.cleanup=$_.Exception.InnerException.Data['host_execution_lease_cleanup']
      }
    }
    $result.capacity_calls=$script:capacityCount
    $result.release_calls=$script:releaseCount
    $result.renew_calls=$script:renewCount
    [pscustomobject]$result
  } $scenario
})
Write-Output ('HOST_RELEASE_RESULT='+($results|ConvertTo-Json -Depth 15 -Compress))
'''
        completed = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=repo,
                                   env=dict(os.environ, CAPACITY_FIXTURE_REPO=str(repo)),
                                   capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        line = next(line for line in completed.stdout.splitlines() if line.startswith("HOST_RELEASE_RESULT="))
        results = {row["scenario"]: row for row in json.loads(line.split("=", 1)[1])}
        for scenario, result in results.items():
            with self.subTest(scenario=scenario):
                expected_calls = 2 if scenario == "workflow" else 1
                self.assertEqual(result["capacity_calls"], expected_calls, result)
                self.assertEqual(result["release_calls"], expected_calls, result)
                self.assertEqual(result["renew_calls"], 1 if scenario == "workflow" else 0, result)
                if scenario == "success":
                    self.assertEqual(result["failure"], "fixture host release failure")
                    continue
                self.assertEqual(result["cleanup"], {"status": "failed", "error": "fixture host release failure"})
                if scenario == "native":
                    self.assertEqual(result["failure"], "fixture native failure")
                elif scenario == "workflow":
                    self.assertEqual(result["stage"], "maintenance")
                    self.assertIn("after TARGET_CAPACITY_EXCEEDED", result["failure"])
                    self.assertIn("CAPACITY_TARGET_NOT_MET", result["failure"])
                else:
                    self.assertIn("TARGET_CAPACITY_EXCEEDED", result["failure"])
                    self.assertEqual(result["receipt"]["capacity_protection_lease_id"], "fixture")

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell Core is required")
    def test_workflow_pressure_relief_uses_one_protected_pass_and_fresh_admission(self) -> None:
        """Run the real PS session/CLI/ledger against byte-sized TEMP objects."""
        repo = Path(__file__).resolve().parents[2]
        cases = (
            ("accepted", True, 1, 2), ("still_full", False, 1, 2),
            ("minimum_free", True, 1, 2), ("unrelated_owner_failure", True, 1, 2),
            ("invalid_ledger", False, 0, 1), ("invalid_lease", False, 0, 1),
            ("missing_scope", False, 0, 1), ("maintenance_failure", False, 1, 1),
            ("renewal_failure", False, 1, 1), ("expired_before_renewal", False, 1, 1),
            ("cleanup_failure", False, 1, 2),
        )
        with tempfile.TemporaryDirectory(prefix="capacity_pressure_session_") as temporary:
            workspace = Path(temporary)
            driver = workspace / "fixture_cli.py"
            driver.write_text(textwrap.dedent('''\
                import json, sys
                from datetime import datetime, timedelta
                from pathlib import Path
                from common.contracts import reconcile_artifact_capacity as capacity
                from common.contracts import capacity_protection as protection
                args = sys.argv[1:]
                root = Path(args[args.index("--artifact-root") + 1])
                scenario = root.name
                events = root / "events.jsonl"
                def record(event):
                    with events.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(event) + "\\n")
                action = next((name for name in ("create", "renew", "delete")
                               if "--" + name + "-protection-lease" in args), None)
                mode = args[args.index("--execution-mode") + 1] if "--execution-mode" in args else None
                if mode == "startup" and scenario in {"invalid_lease", "missing_scope"}:
                    lease_path = next((root / "common/capacity_protection_leases").glob("*.json"))
                    lease = json.loads(lease_path.read_text(encoding="utf-8"))
                    if scenario == "invalid_lease": lease["committed_new_bytes"] = -1
                    else: lease["protected_paths"] = ["future_run"]
                    lease_path.write_text(json.dumps(lease), encoding="utf-8")
                try:
                    leases = protection.load_capacity_protection_leases(root)
                    active = sum(row.get("status") == "active" for row in leases["audit"])
                except Exception:
                    active = None
                record({"action": action, "mode": mode, "active_leases": active})
                policy = capacity._capacity_policy()
                policy.update(target_gib=(5 if scenario in {"still_full", "cleanup_failure"} else 100 if scenario == "minimum_free" else 10) / capacity.GIB,
                              minimum_free_gib=(1 if scenario == "minimum_free" else 0) / capacity.GIB)
                capacity._capacity_policy = lambda: policy
                if scenario == "minimum_free":
                    disk_usage = capacity.shutil.disk_usage
                    capacity.shutil.disk_usage = lambda path: disk_usage(path)._replace(
                        free=1 if (root / "disposable").exists() else 9)
                if scenario == "unrelated_owner_failure":
                    def fail_owner(_root): raise ValueError("unrelated historical fixture")
                    capacity._audit_pa_transaction_owner = fail_owner
                if scenario == "maintenance_failure" and mode == "maintenance":
                    def fail_plan(*args, **kwargs): raise RuntimeError("fixture maintenance failure")
                    capacity._maintenance_plan = fail_plan
                if scenario == "renewal_failure" and action == "renew" and not (root / "disposable").exists():
                    def fail_renewal(*args, **kwargs): raise ValueError("fixture lease renewal failure")
                    protection.renew_capacity_protection_lease = fail_renewal
                if scenario == "expired_before_renewal" and action == "renew" and not (root / "disposable").exists():
                    lease_path = next((root / "common/capacity_protection_leases").glob("*.json"))
                    lease = json.loads(lease_path.read_text(encoding="utf-8"))
                    lease["expires_at_utc"] = (datetime.fromisoformat(lease["created_at_utc"].replace("Z", "+00:00"))
                                                + timedelta(milliseconds=1)).isoformat()
                    lease_path.write_text(json.dumps(lease), encoding="utf-8")
                if scenario == "cleanup_failure" and action == "delete":
                    def fail_cleanup(*args, **kwargs): raise ValueError("fixture lease cleanup failure")
                    protection.delete_capacity_protection_lease = fail_cleanup
                check = capacity._assert_maintenance_input_lease
                def observed_check(*args, **kwargs):
                    check(*args, **kwargs)
                    assert (root / "input").read_bytes() == b"keep"
                    record({"guard": "active", "input_preserved": True})
                capacity._assert_maintenance_input_lease = observed_check
                sys.argv = ["fixture-capacity", *args]
                capacity.main()
                '''), encoding="utf-8")
            for scenario, accepted, maintenance_count, startup_count in cases:
                with self.subTest(scenario=scenario):
                    root = workspace / scenario
                    root.mkdir()
                    (root / "input").write_bytes(b"keep")
                    (root / "disposable").write_bytes(b"disposal")
                    capacity_ledger.initialize_capacity_ledger(root, objects=[
                        {"path": name, "class": "rebuildable_payload", "bytes": size,
                         "status": "ready", "pin": False, **READY_DUTIES}
                        for name, size in (("input", 4), ("disposable", 8))
                    ])
                    if scenario == "invalid_ledger":
                        (root / capacity.CAPACITY_LEDGER_RELATIVE_PATH).write_text("invalid JSON", encoding="utf-8")
                    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
                    script = f'''
$ErrorActionPreference='Stop'
. {quote(repo / 'common/contracts/run_artifact_support.ps1')}
$fixturePython={quote(sys.executable)}
$fixtureDriver={quote(driver)}
function Invoke-PressureFixturePython {{
  param([Parameter(ValueFromRemainingArguments)]$NativeArguments)
  & $fixturePython $fixtureDriver @($NativeArguments | Select-Object -Skip 2)
  $global:LASTEXITCODE=$LASTEXITCODE
}}
$result=@{{accepted=$false;initial_reason=$null;failure=$null;pressure_stage=$null;cleanup=$null}}
try {{
  $session=Enter-ArtifactWorkflowCapacitySession -Python Invoke-PressureFixturePython -RepoRoot {quote(repo)} `
    -ArtifactRoot {quote(root)} -RunDirectory {quote(root / 'future_run')} `
    -CommittedNewBytes 2 -Owner fixture -LeaseTtlSeconds 120 -ProtectedPaths @({quote(root / 'input')})
  $result.accepted=$true
  $result.admission=$session.startup_gate
  Exit-ArtifactWorkflowCapacitySession -Python Invoke-PressureFixturePython -RepoRoot {quote(repo)} -Session $session|Out-Null
}} catch {{
  $result.failure=$_.Exception.Message
  $attempt=$_.Exception.Data['pressure_maintenance']
  if($null-ne$attempt){{$result.initial_reason=$attempt.trigger_reason;$result.pressure_stage=$attempt.stage}}
  $result.cleanup=$_.Exception.Data['capacity_lease_cleanup']
}}
Write-Output ('PRESSURE_RESULT='+($result|ConvertTo-Json -Depth 30 -Compress))
'''
                    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                                       MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN="",
                                       MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(root / "host.sqlite3"),
                                       SIMULATION_PYTHON_EXE=sys.executable)
                    completed = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=repo,
                                               env=environment, capture_output=True, text=True,
                                               encoding="utf-8", timeout=90, check=False)
                    self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                    line = next(line for line in completed.stdout.splitlines() if line.startswith("PRESSURE_RESULT="))
                    result = json.loads(line.split("=", 1)[1])
                    self.assertEqual(result["accepted"], accepted, result)
                    events = [json.loads(line) for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
                    self.assertEqual(sum(row.get("mode") == "maintenance" for row in events), maintenance_count, result)
                    self.assertEqual(sum(row.get("mode") == "startup" for row in events), startup_count, result)
                    self.assertEqual((root / "input").read_bytes(), b"keep")
                    remaining_leases = list((root / "common/capacity_protection_leases").glob("*.json"))
                    self.assertEqual(len(remaining_leases), 1 if scenario == "cleanup_failure" else 0)
                    if maintenance_count:
                        self.assertTrue(all(row["active_leases"] == 1 for row in events if row.get("mode") in {"startup", "maintenance"}))
                        self.assertTrue(any(row.get("guard") == "active" for row in events), events)
                    if accepted:
                        admission = result["admission"]
                        self.assertEqual(admission["total_active_lease_committed_new_bytes"], 2)
                        self.assertEqual(admission["projected_bytes"], 6)
                        self.assertEqual(admission["pressure_maintenance"]["stage"], "admitted")
                        self.assertEqual(admission["pressure_maintenance"]["maintenance"]["removed"]["bytes"], 8)
                        if scenario == "unrelated_owner_failure":
                            self.assertIn("unrelated historical fixture", str(admission["pressure_maintenance"]["maintenance"]["owner_action_failures"]))
                    else:
                        self.assertEqual(result["cleanup"]["status"], "failed" if scenario == "cleanup_failure" else "released", result)
                        if maintenance_count:
                            self.assertEqual(result["initial_reason"], "TARGET_CAPACITY_EXCEEDED")
                            self.assertIn("after TARGET_CAPACITY_EXCEEDED", result["failure"])
                    if scenario in {"maintenance_failure", "renewal_failure"}:
                        self.assertIn("fixture " + ("maintenance" if scenario == "maintenance_failure" else "lease renewal") + " failure", result["failure"])
                    if scenario == "expired_before_renewal":
                        self.assertIn("expired and cannot be renewed", result["failure"])
                        self.assertEqual(result["pressure_stage"], "renew_before_readmission")
                    if scenario == "cleanup_failure":
                        self.assertIn("TARGET_CAPACITY_EXCEEDED", result["failure"])
                        self.assertIn("fixture lease cleanup failure", result["cleanup"]["error"])

    def test_startup_cli_apply_evaluates_admission_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[])
            create_capacity_protection_lease(
                root, lease_id="current", owner="test", ttl_seconds=60,
                protected_paths=[root / "future"], committed_new_bytes=1,
            )
            for free_bytes, accepted in ((10**15, True), (0, False)):
                with (self.subTest(accepted=accepted),
                      patch.object(capacity.shutil, "disk_usage", return_value=Mock(free=free_bytes)) as disk,
                      patch.object(capacity_ledger, "load_capacity_ledger", wraps=capacity_ledger.load_capacity_ledger) as ledger,
                      patch.object(capacity.protection, "load_capacity_protection_leases",
                                   wraps=capacity.protection.load_capacity_protection_leases) as leases,
                      patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "1"}),
                      patch.object(sys, "argv", [
                          "capacity", "--artifact-root", str(root), "--capacity-protection-lease-id", "current", "--apply",
                      ]), redirect_stdout(io.StringIO()) as stdout):
                    capacity.main()
                rendered = json.loads(stdout.getvalue())
                self.assertEqual(rendered["satisfied_after_apply"], accepted)
                self.assertEqual(rendered["applied"], accepted)
                self.assertEqual(rendered["owner_actions"], {})
                self.assertTrue({"plan", "plan.disk_usage", "plan.ledger_and_leases"}.issubset(
                    rendered["timing"]["phases_seconds"],
                ))
                disk.assert_called_once()
                ledger.assert_called_once()
                leases.assert_called_once()

    def test_separate_startup_apply_rechecks_new_commitments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[])
            create_capacity_protection_lease(
                root, lease_id="current", owner="test", ttl_seconds=60,
                protected_paths=[root / "future"], committed_new_bytes=1,
            )
            receipt = capacity.plan(root, target_bytes=1, minimum_free_bytes=0,
                                    capacity_protection_lease_id="current")
            self.assertTrue(receipt["satisfied"])
            create_capacity_protection_lease(
                root, lease_id="new", owner="other", ttl_seconds=60,
                protected_paths=[root / "other"], committed_new_bytes=1,
            )
            refreshed = capacity.apply(receipt)
            self.assertFalse(refreshed["satisfied_after_apply"])
            self.assertEqual(refreshed["blocking_reason"], "TARGET_CAPACITY_EXCEEDED")
            self.assertEqual(refreshed["total_active_lease_committed_new_bytes"], 2)

    def test_owner_recovers_only_stale_atomic_ledger_temp_without_payload_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "common" / ".capacity_ledger.json.crashed"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"truncated ledger")
            os.utime(target, (0, 0))
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": target.relative_to(root).as_posix(),
                "class": "rebuildable_payload", "bytes": target.stat().st_size,
                "status": "writing", "pin": False,
                "owner": "common.capacity_lifecycle",
                "recovery_reason": "stale_capacity_ledger_atomic_temp_requires_recovery",
                "review_deadline": "2026-10-22",
            }])
            with patch("common.contracts.file_identity.file_sha256", side_effect=AssertionError("payload hash")):
                outcome = capacity_ledger.recover_stale_atomic_ledger_temps(root)
            self.assertEqual(outcome["retired_count"], 1)
            self.assertEqual(outcome["removed_bytes"], len(b"truncated ledger"))
            self.assertFalse(target.exists())
            entry = capacity_ledger.load_capacity_ledger(root)["objects"][0]
            self.assertEqual(entry["status"], "retired")
            receipt = next((root / "common" / "capacity_disposal_receipts").glob("atomic-ledger-temp-*.json"))
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["status"], "retired")

    def test_pa_runtime_directories_become_ready_without_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = sorted(capacity_ledger.PA_RUNTIME_STATE_RELATIVE_PATHS)
            for relative in paths:
                (root / relative).mkdir(parents=True)
            (root / paths[1] / "key.lock").write_bytes(b"lock")
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": relative,
                "class": "rebuildable_payload",
                "bytes": 4 if relative == paths[1] else 0,
                "status": "writing", "pin": False,
                "owner": "common.simion.pa_family_cache",
                "recovery_reason": "pa_runtime_state_recovery_required",
                "review_deadline": "2026-10-22",
            } for relative in paths])
            outcome = capacity_ledger.reconcile_pa_runtime_state(root)
            self.assertEqual(outcome["ready_count"], 3)
            self.assertEqual(outcome["ready_bytes"], 4)
            self.assertTrue((root / paths[1] / "key.lock").exists())
            self.assertTrue(all(
                item["status"] == "ready" and item["class"] == "light_evidence"
                for item in capacity_ledger.load_capacity_ledger(root)["objects"]
            ))

    def test_loading_calibrated_ledger_does_not_resolve_payload_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": "projects/p/runs/r1", "class": "light_evidence",
                "bytes": 1, "status": "ready", "pin": False,
                **READY_DUTIES,
            }])
            with patch.object(
                capacity_ledger, "capacity_object_path",
                side_effect=AssertionError("startup touched a payload path"),
            ):
                loaded = capacity_ledger.load_capacity_ledger(root)
            self.assertIsNotNone(loaded)

    def test_ledger_rejects_nested_ranges_even_when_names_sort_between_them(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            objects = [
                {"path": path, "class": "light_evidence", "bytes": 1,
                 "status": "ready", "pin": False, **READY_DUTIES}
                for path in ("a", "a-b", "a/c")
            ]
            with self.assertRaisesRegex(ValueError, "baseline is invalid"):
                capacity_ledger.initialize_capacity_ledger(root, objects=objects)

    def test_writing_recovery_responsibility_is_required_preserved_and_ready_forbids_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "baseline is invalid"):
                capacity_ledger.initialize_capacity_ledger(root, objects=[{
                    "path": "incomplete", "class": "rebuildable_payload", "bytes": 1,
                    "status": "writing", "pin": False,
                }])
            document = capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": "incomplete", "class": "rebuildable_payload", "bytes": 1,
                "status": "writing", "pin": False, "owner": "workflow-a",
                "recovery_reason": "run_manifest_not_terminal",
                "review_deadline": "2026-09-27",
                "retention_reason": "finite test fixture retention",
                "retirement_route": "owner_managed_disposition",
                "recovery_task": "workflow-a must recover or retire",
                "recovery_evidence_paths": ["incomplete"],
                "consumers": ["projects/p/runs/consumer"],
            }])
            self.assertEqual(document["objects"][0]["owner"], "workflow-a")
            self.assertEqual(document["objects"][0]["review_deadline"], "2026-09-27")
            self.assertEqual(
                document["objects"][0]["consumers"],
                ["projects/p/runs/consumer"],
            )
            with self.assertRaisesRegex(ValueError, "ready ledger objects cannot carry"):
                capacity_ledger.record_capacity_object(
                    root, path="ready", object_class="rebuildable_payload",
                    bytes_count=1, status="ready", owner="workflow-a",
                    retention_reason="fixture", recovery_reason="not_allowed",
                    review_deadline="2026-09-27", retirement_route="owner_managed_disposition",
                )
            with self.assertRaisesRegex(ValueError, "baseline is invalid"):
                capacity_ledger.initialize_capacity_ledger(root, objects=[{
                    "path": "unknown", "class": "light_evidence", "bytes": 1,
                    "status": "ready", "pin": False, "arbitrary_extra": True,
                }], overwrite=True)
            ready = capacity_ledger.record_capacity_object(
                root, path="incomplete", object_class="light_evidence",
                bytes_count=1, status="ready", **READY_DUTIES,
            )
            self.assertTrue(capacity_ledger.RECOVERY_FIELDS.isdisjoint(ready))

    def test_policy_is_minimal_and_uses_exact_light_evidence_budget(self) -> None:
        policy = json.loads(capacity.POLICY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(set(policy), {
            "schema_version", "role", "description", "target_gib",
            "minimum_free_gib", "light_evidence_budget_bytes",
            "startup_gate_target_seconds", "startup_gate_deadline_seconds",
            "eviction_order",
        })
        self.assertEqual(policy["light_evidence_budget_bytes"], 26_214_400)
        self.assertEqual(capacity._capacity_policy(), policy)

    def test_legacy_v1_ledger_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = {
                "schema_version": 1, "role": "artifact_capacity_ledger",
                "status": "calibrated", "complete": True,
                "artifact_root": str(root), "resident_bytes": 0, "objects": [],
            }
            ledger = root / "common" / "capacity_ledger.json"
            ledger.parent.mkdir()
            ledger.write_text(json.dumps(legacy), encoding="utf-8")
            self.assertIsNone(capacity_ledger.load_capacity_ledger(root))

    def test_external_scope_bytes_contribute_to_startup_resident_projection_without_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "artifacts"
            root.mkdir()
            workspace = parent / "simulation_repo"
            scratch = workspace / "scratch"
            generated = workspace / "generated"
            scratch.mkdir(parents=True)
            generated.mkdir()
            scopes = [
                {"role": "repository_scratch", "path": str(scratch.resolve()), "bytes": 40},
                {"role": "repository_generated", "path": str(generated.resolve()), "bytes": 60},
            ]
            capacity_ledger.initialize_capacity_ledger(root, objects=[], external_scopes=scopes)
            create_capacity_protection_lease(
                root, lease_id="current", owner="test", ttl_seconds=60,
                protected_paths=[root / "future"], committed_new_bytes=1,
            )
            with patch.object(capacity.shutil, "disk_usage", return_value=Mock(free=10_000)):
                receipt = capacity.plan(
                    root, target_bytes=100, minimum_free_bytes=0,
                    protected_paths=[root / "future"], capacity_protection_lease_id="current",
                )
            self.assertFalse(receipt["satisfied"])
            self.assertEqual(receipt["resident_bytes"], 100)
            self.assertEqual(receipt["projected_bytes"], 101)
            self.assertEqual(receipt["blocking_reason"], "TARGET_CAPACITY_EXCEEDED")

    def test_maintenance_registers_workspace_scratch_once_without_artifact_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "artifacts"; root.mkdir()
            source = parent / "scratch"; source.mkdir(parents=True)
            (source / "payload.bin").write_bytes(b"source")
            capacity_ledger.initialize_capacity_ledger(root, objects=[], external_scopes=[
                {"role": "repository_scratch", "path": str((parent / "simulation_repo" / "scratch").resolve()), "bytes": 0},
                {"role": "repository_generated", "path": str((parent / "generated").resolve()), "bytes": 0},
            ])
            self.assertEqual(
                capacity._register_workspace_scratch_scope(root),
                {"registered_count": 1, "registered_bytes": 6},
            )
            ledger = capacity_ledger.load_capacity_ledger(root)
            self.assertEqual(ledger["resident_bytes"], 6)
            self.assertEqual(
                capacity._register_workspace_scratch_scope(root),
                {"registered_count": 0, "registered_bytes": 6},
            )

    def test_maintenance_completes_authorized_source_scratch_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "artifacts"; root.mkdir()
            source = parent / "scratch"; source.mkdir()
            (source / "obsolete.bin").write_bytes(b"obsolete")
            capacity_ledger.initialize_capacity_ledger(root, objects=[], external_scopes=[
                {"role": "repository_scratch", "path": str((parent / "simulation_repo" / "scratch").resolve()), "bytes": 0},
                {"role": "repository_generated", "path": str((parent / "simulation_repo" / "generated").resolve()), "bytes": 0},
                {"role": "repository_workspace_scratch", "path": str(source.resolve()), "bytes": 8},
            ])
            evidence = root / capacity.SCRATCH_DISPOSITION_DIRECTORY / "obsolete.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(json.dumps({
                "schema_version": 1,
                "role": "historical_source_scratch_retirement_authorization",
                "status": "approved", "owner": "fixture-owner",
                "source_root": str(source), "retirement_authorized": True,
                "retirement_targets": ["obsolete.bin"], "active_consumers": [],
                "protected_paths": [],
            }), encoding="utf-8")
            self.assertEqual(
                capacity._resume_source_scratch_dispositions(root),
                {
                    "completed_count": 1,
                    "newly_removed_bytes": 8,
                    "evidence_archived_count": 1,
                },
            )
            self.assertFalse(evidence.exists())
            self.assertFalse(source.exists())
            self.assertEqual(capacity_ledger.load_capacity_ledger(root)["resident_bytes"], 0)

    def test_daily_module_has_no_legacy_imports(self) -> None:
        source = Path(capacity.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "legacy_capacity_backfill", "reconcile_interrupted_compact_runs",
            "solver_review_retirement", "artifact_retention", "verify_run_manifest",
        ):
            self.assertNotIn(forbidden, source)
        script = """
import sys
from common.contracts import reconcile_artifact_capacity
for name in (
    'common.contracts.legacy_capacity_backfill',
    'common.contracts.reconcile_interrupted_compact_runs',
    'common.contracts.solver_review_retirement',
    'common.contracts.artifact_retention',
    'common.contracts.verify_run_manifest',
):
    assert name not in sys.modules, name
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2], text=True,
            capture_output=True, check=False, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_startup_uses_ledger_plus_all_commitments_and_current_scope_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            required = root / "inputs" / "current"
            other = root / "inputs" / "other"
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": "resident", "class": "rebuildable_payload", "bytes": 100,
                "status": "ready", "pin": False,
                **READY_DUTIES,
            }])
            create_capacity_protection_lease(
                root, lease_id="current", owner="workflow", ttl_seconds=3600,
                protected_paths=[required], committed_new_bytes=40,
            )
            create_capacity_protection_lease(
                root, lease_id="other", owner="other", ttl_seconds=3600,
                protected_paths=[other], committed_new_bytes=10,
            )
            with patch.object(capacity.shutil, "disk_usage", return_value=Mock(free=75)):
                receipt = capacity.plan(
                    root, target_bytes=150, minimum_free_bytes=25,
                    protected_paths=[required], execution_mode="startup",
                    capacity_protection_lease_id="current",
                )
            self.assertTrue(receipt["satisfied"])
            self.assertEqual(receipt["projected_bytes"], 150)
            self.assertEqual(receipt["required_free_bytes"], 75)
            self.assertEqual(receipt["current_lease_committed_new_bytes"], 40)
            self.assertEqual(receipt["other_leases_committed_new_bytes"], 10)
            self.assertEqual(receipt["total_active_lease_committed_new_bytes"], 50)

            with patch.object(capacity.shutil, "disk_usage", return_value=Mock(free=10_000)):
                blocked = capacity.plan(
                    root, target_bytes=10_000, minimum_free_bytes=0,
                    protected_paths=[other], execution_mode="startup",
                    capacity_protection_lease_id="current",
                )
            self.assertFalse(blocked["satisfied"])
            self.assertEqual(blocked["blocking_reason"], "CURRENT_LEASE_SCOPE_INCOMPLETE")
            self.assertEqual(blocked["missing_current_lease_paths"], [str(other.resolve())])

    def test_startup_requires_lease_and_rejects_active_legacy_unknown_commitment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[])
            with self.assertRaisesRegex(ValueError, "requires capacity_protection_lease_id"):
                capacity.plan(root, target_bytes=1, minimum_free_bytes=0)
            create_capacity_protection_lease(
                root, lease_id="current", owner="workflow", ttl_seconds=3600,
                protected_paths=[root / "current"], committed_new_bytes=0,
            )
            create_capacity_protection_lease(
                root, lease_id="legacy", owner="legacy", ttl_seconds=3600,
                protected_paths=[root / "legacy"], committed_new_bytes=1,
            )
            legacy_path = root / "common" / "capacity_protection_leases" / "legacy.json"
            document = json.loads(legacy_path.read_text(encoding="utf-8"))
            document.pop("committed_new_bytes")
            legacy_path.write_text(json.dumps(document), encoding="utf-8")
            receipt = capacity.plan(
                root, target_bytes=1, minimum_free_bytes=0,
                capacity_protection_lease_id="current",
            )
            self.assertFalse(receipt["satisfied"])
            self.assertEqual(receipt["blocking_reason"], "ACTIVE_LEASE_COMMITMENT_UNKNOWN")
            self.assertEqual(receipt["active_legacy_unknown_commitment_count"], 1)

    def test_startup_reports_writing_recovery_and_blocks_overdue_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": "active-run", "class": "rebuildable_payload", "bytes": 1,
                "status": "writing", "pin": False, "owner": "workflow-a",
                "recovery_reason": "run_manifest_not_terminal",
                "review_deadline": (date.today() - timedelta(days=1)).isoformat(),
                "retention_reason": "finite test fixture retention",
                "retirement_route": "owner_managed_disposition",
                "recovery_task": "workflow-a must recover or retire",
                "recovery_evidence_paths": ["active-run"],
            }])
            create_capacity_protection_lease(
                root, lease_id="current", owner="workflow-a", ttl_seconds=3600,
                protected_paths=[root / "active-run"], committed_new_bytes=0,
            )
            receipt = capacity.plan(
                root, target_bytes=100, minimum_free_bytes=0,
                protected_paths=[root / "active-run"],
                capacity_protection_lease_id="current",
            )
            self.assertFalse(receipt["satisfied"])
            self.assertEqual(receipt["blocking_reason"], "WRITING_RECOVERY_REVIEW_OVERDUE")
            self.assertEqual(receipt["writing_object_count"], 1)
            self.assertEqual(receipt["overdue_writing_object_count"], 1)
            self.assertEqual(receipt["overdue_writing_objects"][0]["owner"], "workflow-a")

    def test_overdue_admission_uses_current_lease_input_overlap_and_cache_family(self) -> None:
        key, generation, other_key = "a" * 64, "b" * 64, "c" * 64
        cases = [
            ("ancestor", "projects/p/runs/old", ["projects/p/runs/old/input.json"], [], True),
            ("descendant", "projects/p/runs/old/input.json", ["projects/p/runs/old"], [], True),
            ("other_lease", "projects/p/runs/old", ["projects/current"], [], False),
            ("generation", f"common/simion/pa_family_cache/{key}/generations/{generation}", [], [key], True),
            ("transaction", f"common/simion/pa_family_cache/.transactions/{key}/build-scratch", [], [key], True),
            ("staging", f"projects/p/cache/simion_pa_basis/.staging/{key}/pending", [], [key], True),
            ("project_generation", f"projects/p/cache/simion_pa_basis/{key}/generations/{generation}", [], [key], True),
            ("different_key", f"common/simion/pa_family_cache/{other_key}/generations/{generation}", [], [key], False),
            ("generation_is_not_key", f"common/simion/pa_family_cache/{key}/generations/{generation}", [], [generation], False),
            ("ordinary_sha_path", f"projects/p/runs/{key}/results", [], [key], False),
        ]
        for name, relative, current_paths, current_keys, blocked in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                item = {
                    "path": relative, "class": "rebuildable_payload", "bytes": 7,
                    "status": "writing", "pin": False, **WRITING_DUTIES,
                    "review_deadline": "2000-01-01",
                }
                if name == "generation_is_not_key":
                    item.update({"class": "published_cache", "identity": generation})
                capacity_ledger.initialize_capacity_ledger(root, objects=[item])
                create_capacity_protection_lease(
                    root, lease_id="other", owner="other", ttl_seconds=3600,
                    protected_paths=[root / relative], protected_cache_keys=[key], committed_new_bytes=3,
                )
                create_capacity_protection_lease(
                    root, lease_id="current", owner="current", ttl_seconds=3600,
                    protected_paths=[root / value for value in current_paths],
                    protected_cache_keys=current_keys, committed_new_bytes=2,
                )
                ledger_path = root / "common/capacity_ledger.json"
                original = ledger_path.read_bytes()
                # No explicit required arguments: the current lease itself is
                # still the declared input scope, while other leases are not.
                receipt = capacity.plan(root, target_bytes=100, minimum_free_bytes=0,
                                        capacity_protection_lease_id="current")
                self.assertEqual(receipt["satisfied"], not blocked)
                self.assertEqual(receipt["blocking_overdue_writing_object_count"], int(blocked))
                self.assertEqual(receipt["blocking_reason"], "WRITING_RECOVERY_REVIEW_OVERDUE" if blocked else None)
                self.assertEqual(receipt["resident_bytes"], 7)
                self.assertEqual(receipt["total_active_lease_committed_new_bytes"], 5)
                self.assertEqual(receipt["projected_bytes"], 12)
                self.assertEqual(len(receipt["warnings"]), int(not blocked))
                if not blocked:
                    self.assertEqual(receipt["warnings"][0]["path"], relative)
                    over_capacity = capacity.plan(root, target_bytes=11, minimum_free_bytes=0,
                                                  capacity_protection_lease_id="current")
                    self.assertFalse(over_capacity["satisfied"])
                    self.assertEqual(over_capacity["blocking_reason"], "TARGET_CAPACITY_EXCEEDED")
                self.assertEqual(ledger_path.read_bytes(), original)

    def test_normal_api_and_cli_do_not_accept_duplicate_budget_estimates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(TypeError):
                capacity.plan(
                    root, target_bytes=1, minimum_free_bytes=0,
                    maximum_new_artifact_bytes=1,
                )
            for option in (
                "--maximum-new-artifact-bytes", "--target-gib", "--minimum-free-gib",
            ):
                with self.subTest(option=option), patch.object(sys, "argv", [
                    "reconcile_artifact_capacity", "--artifact-root", str(root),
                    option, "1",
                ]):
                    with self.assertRaises(SystemExit) as raised:
                        capacity.main()
                    self.assertEqual(raised.exception.code, 2)

    def test_maintenance_reads_only_ready_unpinned_heavy_ledger_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capacity_ledger.initialize_capacity_ledger(root, objects=[
                {
                    "path": "evidence", "class": "light_evidence", "bytes": 1,
                    "status": "ready", "pin": False,
                    **READY_DUTIES,
                },
                {
                    "path": "cache", "class": "published_cache", "bytes": 2,
                    "status": "ready", "pin": False, "identity": "a" * 64,
                    "manager": capacity_ledger.PA_CACHE_MANAGER,
                    "owner": capacity_ledger.PA_CACHE_MANAGER,
                    "retention_reason": "finite PA fixture retention",
                    "review_deadline": "2026-10-22",
                    "retirement_route": "pa_manager_disposition",
                },
                {
                    "path": "writing", "class": "rebuildable_payload", "bytes": 4,
                    "status": "writing", "pin": False, "owner": "test",
                    "recovery_reason": "fixture_incomplete",
                    "review_deadline": "2026-09-27",
                    "retention_reason": "finite test fixture retention",
                    "retirement_route": "owner_managed_disposition",
                    "recovery_task": "test must recover or retire",
                    "recovery_evidence_paths": ["writing"],
                },
                {
                    "path": "rebuildable", "class": "rebuildable_payload", "bytes": 3,
                    "status": "ready", "pin": False,
                    **READY_DUTIES,
                },
            ])
            receipt = capacity.plan(
                root, target_bytes=1, minimum_free_bytes=0,
                execution_mode="maintenance",
            )
            self.assertEqual(
                [item["class"] for item in receipt["planned"]],
                ["rebuildable_payload", "published_cache"],
            )
            self.assertEqual(receipt["candidate_count"], 2)


if __name__ == "__main__":
    unittest.main()
