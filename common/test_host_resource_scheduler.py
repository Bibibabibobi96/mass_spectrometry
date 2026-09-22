"""Behavior tests use isolated SQLite files and synthetic process identities."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from common.host_resource_scheduler import StaleSnapshotError, load_policy, transact, validate_budget

GIB = 1024**3
ROOT = Path(__file__).resolve().parents[1]


def _ps_quote(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell adapter required")
class HostSnapshotContentionTests(unittest.TestCase):
    """Real competing processes, with small deterministic host-budget fixtures."""

    def prelude(self, state: Path) -> str:
        return f"""
$ErrorActionPreference='Stop'
. {_ps_quote(ROOT / 'common/host_execution_lease.ps1')}
$env:SIMULATION_PYTHON_EXE={_ps_quote(sys.executable)}
$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH={_ps_quote(state)}
Remove-Item Env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN -ErrorAction SilentlyContinue
function Get-TestSnapshot {{
  return @{{complete=$true;logical_processors=4;cpu_percent=0;total_memory_bytes=32GB;
    available_memory_bytes=24GB;io_pressure=$false;processes=@(Get-Process -Name pwsh | ForEach-Object {{
      @{{pid=$_.Id;parent_pid=0;started="fixture-$($_.Id)";memory_bytes=32MB}}
    }})}}
}}
"""

    def launch(self, script: str) -> subprocess.Popen[str]:
        environment = dict(os.environ)
        environment.pop("MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN", None)
        return subprocess.Popen(
            [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", script + "\nexit 0\n"],
            cwd=ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def finish(self, process: subprocess.Popen[str]) -> str:
        try:
            output, errors = process.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            process.kill()
            output, errors = process.communicate(timeout=15)
            self.fail(f"isolated contention fixture did not progress: {output}\n{errors}")
        self.assertEqual(process.returncode, 0, output + errors)
        return output

    def test_more_than_three_stale_snapshots_resample_then_succeed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="host_contention_retry_") as directory:
            state = Path(directory) / "state.sqlite3"
            script = self.prelude(state) + f"""
$script:samples=0
function Get-HostResourceSnapshot {{
  $script:samples += 1
  $snapshot=Get-TestSnapshot
  if ($script:samples -le 5) {{
    # Commit from another Python process AFTER the caller began its sample.
    # This deterministically produces five real SQLite stale-snapshot rejects.
    $competitor=$snapshot.Clone()
    $competitor.observed_at_ticks=[DateTime]::UtcNow.Ticks
    $payload=@{{request=@{{operation='status'}};snapshot=$competitor}} | ConvertTo-Json -Depth 8 -Compress
    $null=$payload | & $env:SIMULATION_PYTHON_EXE -m common.host_resource_scheduler --state {_ps_quote(state)}
    if ($LASTEXITCODE -ne 0) {{ throw 'competing transaction failed' }}
  }}
  return $snapshot
}}
$lease=Enter-HostResourceStage -Role GATE -Stage fixture -Budget (Get-HostResourceBudget -Profile measured-small-check)
if ($script:samples -lt 6) {{ throw 'the fixture did not exceed the former retry limit' }}
Exit-HostResourceStage -Lease $lease
$script:samples=0
function Get-HostResourceSnapshot {{ $script:samples += 1; $snapshot=Get-TestSnapshot; $snapshot.cpu_percent=-1; return $snapshot }}
try {{
  $null=Enter-HostResourceStage -Role GATE -Stage invalid -Budget (Get-HostResourceBudget -Profile unknown)
  throw 'invalid telemetry was accepted'
}} catch {{
  if ($_.Exception.Message -notmatch 'invalid or unavailable host telemetry') {{ throw }}
}}
if ($script:samples -ne 1) {{ throw 'invalid telemetry was retried as normal contention' }}
"""
            output = self.finish(self.launch(script))
            self.assertIn("REASON=snapshot_contention", output)
            self.assertIn("HOST_RESOURCE=ACQUIRED", output)

    def test_sixteen_real_cim_clients_complete_without_retry_exhaustion(self) -> None:
        with tempfile.TemporaryDirectory(prefix="host_contention_parallel_") as directory:
            state = Path(directory) / "state.sqlite3"
            ready = Path(directory) / "start"
            script = self.prelude(state) + f"""
$realSnapshot=${{function:Get-HostResourceSnapshot}}
while (-not (Test-Path -LiteralPath {_ps_quote(ready)})) {{ Start-Sleep -Milliseconds 10 }}
function Get-HostResourceSnapshot {{
  # Actual CIM process identities, memory, and collection timing. Only host
  # pressure is fixed so this isolated test never claims live host capacity.
  $snapshot=& $realSnapshot
  $snapshot.cpu_percent=0; $snapshot.total_memory_bytes=32GB
  $snapshot.available_memory_bytes=24GB; $snapshot.logical_processors=4; $snapshot.io_pressure=$false
  return $snapshot
}}
$lease=Enter-HostResourceStage -Role GATE -Stage concurrent-fixture -Budget (Get-HostResourceBudget -Profile measured-small-check)
try {{ Start-Sleep -Milliseconds 200 }} finally {{ Exit-HostResourceStage -Lease $lease }}
"""
            processes = [self.launch(script) for _ in range(16)]
            try:
                ready.write_text("start", encoding="utf-8")
                outputs = [self.finish(process) for process in processes]
                self.assertTrue(all("HOST_RESOURCE=ACQUIRED" in output for output in outputs))
                self.assertTrue(all("STATUS=released" in output for output in outputs))
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                    process.communicate(timeout=15)


def budget(cpu: float = 1, memory: int = GIB, io: int = 0, exclusive: list[str] | None = None,
           unknown: bool = False) -> dict:
    return dict(schema_version=1, cpu_cores=cpu, memory_bytes=memory, io_slots=io,
                exclusive_resources=exclusive or [], unknown_peak=unknown)


class HostResourceSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="host_resource_test_")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "state.sqlite3"
        self.policy = load_policy()
        # Capacity tests model a fully idle synthetic host; live-headroom tests use the production ceiling.
        self.policy["cpu_admission_percent"] = 100
        self.snapshot = dict(complete=True, logical_processors=4, cpu_percent=0,
                             total_memory_bytes=16*GIB, available_memory_bytes=12*GIB,
                             io_pressure=False, processes=[
                                 dict(pid=pid, parent_pid=0, started="0000000000000000001", memory_bytes=GIB//16)
                                 for pid in range(1, 21)])

    def call(self, operation: str, pid: int = 1, **values: object) -> dict:
        request = dict(operation=operation, owner=dict(pid=pid, started="0000000000000000001"), **values)
        for _ in range(50):
            snapshot = copy.deepcopy(self.snapshot)
            snapshot["observed_at_ticks"] = time.time_ns()
            try:
                return transact(self.path, request, snapshot, self.policy)
            except StaleSnapshotError:
                continue
        self.fail("fresh observations did not make progress")

    def acquire(self, pid: int, resources: dict | None = None) -> dict:
        return self.call("request", pid, token=str(pid), role="GATE", stage="test", budget=resources or budget())

    def test_known_heavy_allows_light_but_excludes_another_heavy(self) -> None:
        heavy = self.policy["profiles"]["heavy-compute"]
        result = self.acquire(1, heavy)
        self.assertFalse(result["budget"]["unknown_peak"])
        self.call("inherit", token="1", require_heavy_stage=True)
        self.assertEqual(self.acquire(2)["status"], "acquired")
        self.assertEqual(self.acquire(3, heavy)["status"], "waiting")
        self.call("release", token="1")
        self.assertEqual(self.call("poll", 2, token="2")["status"], "acquired")
        self.assertEqual(self.call("poll", 3, token="3")["status"], "acquired")

    def test_heavy_permission_rejects_light_waiting_and_unrelated_clients(self) -> None:
        self.acquire(1)
        with self.assertRaisesRegex(ValueError, "heavy stage"):
            self.call("inherit", token="1", require_heavy_stage=True)
        with self.assertRaisesRegex(ValueError, "heavy stage"):
            self.call("inherit", token="1", budget=self.policy["profiles"]["heavy-compute"])
        self.acquire(4, self.policy["profiles"]["heavy-compute"])
        self.acquire(2, self.policy["profiles"]["heavy-compute"])
        with self.assertRaisesRegex(ValueError, "waiting"):
            self.call("inherit", 2, token="2", require_heavy_stage=True)
        self.call("release", 4, token="4")
        self.call("poll", 2, token="2")
        with self.assertRaisesRegex(ValueError, "owner or a live descendant"):
            self.call("inherit", 3, token="2", require_heavy_stage=True)
        self.snapshot["processes"][2]["parent_pid"] = 2
        self.call("inherit", 3, token="2", require_heavy_stage=True)

    def test_legacy_live_record_without_added_field_can_poll_and_release(self) -> None:
        self.acquire(1, budget(unknown=True))
        connection = sqlite3.connect(self.path)
        try:
            state = json.loads(connection.execute("SELECT document FROM state WHERE id=1").fetchone()[0])
            state["records"][0]["budget"].pop("heavy_stage")
            connection.execute("UPDATE state SET document=? WHERE id=1", (json.dumps(state),))
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(self.call("poll", token="1")["status"], "acquired")
        with self.assertRaisesRegex(ValueError, "heavy stage"):
            self.call("inherit", token="1", require_heavy_stage=True)
        self.assertEqual(self.call("release", token="1")["status"], "released")
        with self.assertRaises(ValueError):
            validate_budget({**budget(), "heavy_stage": "false"})

    def test_light_can_fill_heavy_headroom_but_cannot_exceed_live_pressure(self) -> None:
        self.policy["cpu_admission_percent"] = load_policy()["cpu_admission_percent"]
        with self.assertRaisesRegex(ValueError, "idle host"):
            self.acquire(4, budget(cpu=4))
        self.acquire(1, self.policy["profiles"]["heavy-compute"])
        self.snapshot["cpu_percent"] = 75
        self.assertEqual(self.acquire(2)["reason"], "cpu_headroom")
        self.snapshot["cpu_percent"] = 65
        self.assertEqual(self.call("poll", 2, token="2")["status"], "acquired")
        self.snapshot["available_memory_bytes"] = GIB
        self.assertEqual(self.acquire(3)["reason"], "memory_budget_full")

    def test_concurrent_requests_never_oversell_cpu(self) -> None:
        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(self.acquire, range(1, 13)))
        self.assertEqual(sum(r["status"] == "acquired" for r in results), 4)
        records = self.call("status")["records"]
        self.assertEqual(sum(r["budget"]["cpu_cores"] for r in records if r["status"] == "acquired"), 4)

    def test_io_and_named_resource_are_global(self) -> None:
        self.policy["io_slots"] = 1
        self.acquire(1, budget(io=1, exclusive=["gui"]))
        self.assertEqual(self.acquire(2, budget(io=1))["reason"], "io_budget_full")
        self.assertEqual(self.acquire(3, budget(exclusive=["gui"]))["reason"], "exclusive_resource_in_use")
        self.assertEqual(self.acquire(4)["status"], "acquired")

    def test_simion_flight_can_share_io_capacity_with_one_response_refine(self) -> None:
        response = self.policy["profiles"]["simion-dirichlet-response"]
        flight = self.policy["profiles"]["simion-flight"]
        self.assertEqual(self.acquire(1, response)["status"], "acquired")
        self.assertEqual(self.acquire(2, flight)["status"], "acquired")
        self.assertTrue(flight["heavy_stage"])
        self.assertEqual(flight["io_slots"], 1)

    def test_zero_host_io_capacity_uses_live_telemetry_without_static_limit(self) -> None:
        self.assertEqual(self.policy["io_slots"], 0)
        self.assertEqual(self.acquire(1, budget(io=1))["status"], "acquired")
        self.assertEqual(self.acquire(2, budget(io=1))["status"], "acquired")
        self.snapshot["io_pressure"] = True
        self.assertEqual(self.acquire(3, budget(io=1))["reason"], "io_pressure")

    def test_unknown_peak_does_not_classify_work_as_heavy(self) -> None:
        self.acquire(1, self.policy["profiles"]["heavy-compute"])
        self.assertEqual(self.acquire(2, budget(unknown=True))["status"], "acquired")
        self.assertEqual(self.acquire(3, budget(unknown=True))["status"], "acquired")
        self.call("inherit", 2, token="2", budget=budget(unknown=True))
        with self.assertRaisesRegex(ValueError, "heavy stage"):
            self.call("inherit", 2, token="2", require_heavy_stage=True)

    def test_unknown_queue_does_not_deadlock_with_other_waiters(self) -> None:
        self.acquire(1, budget(cpu=4))
        self.acquire(2, budget(unknown=True))
        self.acquire(3, budget(unknown=True))
        self.call("release", token="1")
        self.assertEqual(self.call("poll", 2, token="2")["status"], "acquired")

    def test_stage_growth_requeues_and_retains_memory(self) -> None:
        self.acquire(1, budget(cpu=1, memory=4*GIB))
        self.acquire(2, budget(cpu=3))
        self.snapshot["processes"][0]["memory_bytes"] = 3*GIB
        result = self.call("transition", token="1", stage="solve", budget=budget(cpu=4, memory=8*GIB), retained_memory_bytes=GIB)
        self.assertEqual(result["status"], "waiting")
        self.assertEqual(result["retained_bytes"], 3*GIB)
        self.call("release", 2, token="2")
        self.assertEqual(self.call("poll", token="1")["status"], "acquired")

    def test_memory_promises_not_double_counted_or_oversold(self) -> None:
        self.acquire(1, budget(memory=8*GIB))
        self.assertEqual(self.acquire(2, budget(memory=8*GIB))["status"], "waiting")
        self.snapshot["processes"][0]["memory_bytes"] = 8*GIB
        self.snapshot["available_memory_bytes"] = 6*GIB
        self.assertEqual(self.acquire(3, budget(memory=GIB))["status"], "acquired")

    def test_pressure_closes_admission_without_killing_or_releasing(self) -> None:
        self.acquire(1)
        self.snapshot["cpu_percent"] = 100
        self.assertEqual(self.acquire(2)["reason"], "cpu_pressure")
        self.assertEqual(self.call("poll", token="1")["status"], "acquired")
        self.snapshot["cpu_percent"] = 10
        self.snapshot["available_memory_bytes"] = 100
        self.assertEqual(self.call("poll", 2, token="2")["reason"], "memory_pressure")

    def test_crashed_owner_with_live_child_keeps_reservation(self) -> None:
        self.acquire(1, budget(cpu=4))
        self.snapshot["processes"].append(dict(pid=99, parent_pid=1, started="0000000000000000002", memory_bytes=2*GIB))
        self.call("register", token="1", process_id=99)
        self.snapshot["processes"] = [p for p in self.snapshot["processes"] if p["pid"] != 1]
        self.assertEqual(self.acquire(2)["reason"], "cpu_budget_full")
        self.snapshot["processes"] = [p for p in self.snapshot["processes"] if p["pid"] != 99]
        self.assertEqual(self.call("poll", 2, token="2")["status"], "acquired")

    def test_child_discovered_after_parent_exit_from_creation_order(self) -> None:
        self.acquire(1, budget(cpu=4))
        self.snapshot["processes"] = [p for p in self.snapshot["processes"] if p["pid"] != 1]
        self.snapshot["processes"].append(dict(pid=99, parent_pid=1, started="0000000000000000002", memory_bytes=2*GIB))
        self.assertEqual(self.acquire(2)["status"], "waiting")

    def test_recycled_pid_does_not_keep_dead_owner(self) -> None:
        self.acquire(1, budget(cpu=4))
        self.snapshot["processes"][0]["started"] = "0000000000000000003"
        self.assertEqual(self.acquire(2)["status"], "acquired")

    def test_explicit_release_retains_active_descendant(self) -> None:
        self.acquire(1, budget(cpu=4))
        self.snapshot["processes"].append(dict(pid=99, parent_pid=1, started="0000000000000000002", memory_bytes=2*GIB))
        self.assertEqual(self.call("release", token="1")["reason"], "owner_released_descendants_still_live")
        self.assertEqual(self.acquire(2)["status"], "waiting")

    def test_inheritance_does_not_allocate_again_and_rejects_unrelated(self) -> None:
        self.acquire(1)
        self.snapshot["processes"][1]["parent_pid"] = 1
        self.call("inherit", 2, token="1")
        self.assertEqual(len(self.call("status")["records"]), 1)
        with self.assertRaises(ValueError):
            self.call("inherit", 3, token="1")

    def test_solver_cannot_inherit_missing_named_resource_or_larger_budget(self) -> None:
        self.acquire(1)
        for requested in (budget(exclusive=["comsol-server-session"]), self.policy["profiles"]["heavy-compute"], budget(cpu=2)):
            with self.assertRaises(ValueError):
                self.call("inherit", token="1", role="COMSOL", budget=requested)

    def test_inheritance_error_identifies_exceeded_budget_without_mutating_parent(self) -> None:
        self.acquire(1)
        with self.assertRaisesRegex(ValueError, r"cpu_cores: requested=2, parent=1; memory_bytes: requested=2147483648, parent=1073741824"):
            self.call("inherit", token="1", budget=budget(cpu=2, memory=2*GIB))
        self.assertEqual(self.call("poll", token="1")["budget"], validate_budget(budget()))
        self.assertEqual(len(self.call("status")["records"]), 1)

    def test_bounded_backfill_prevents_starvation(self) -> None:
        self.policy["maximum_queue_bypasses"] = 2
        self.acquire(1, budget(cpu=3))
        self.acquire(2, budget(cpu=4))
        self.assertEqual(self.acquire(3)["status"], "acquired")
        self.call("release", 3, token="3")
        self.assertEqual(self.acquire(4)["status"], "acquired")
        self.call("release", 4, token="4")
        self.assertEqual(self.acquire(5)["status"], "waiting")
        self.call("release", token="1")
        self.assertEqual(self.call("poll", 2, token="2")["status"], "acquired")

    def test_waiting_heavy_does_not_bar_twelve_ordinary_light_tasks(self) -> None:
        heavy = self.policy["profiles"]["heavy-compute"]
        light = self.policy["profiles"]["ordinary-light"]
        self.acquire(1, heavy)
        self.assertEqual(self.acquire(2, heavy)["status"], "waiting")
        self.assertEqual(self.acquire(3, heavy)["status"], "waiting")
        for pid in range(4, 16):
            self.assertEqual(self.acquire(pid, light)["status"], "acquired")
            self.call("release", pid, token=str(pid))
        waiting = self.call("poll", 2, token="2")
        self.assertEqual(waiting["status"], "waiting")
        self.assertEqual(waiting["bypasses"], 0)
        self.call("release", token="1")
        self.assertEqual(self.call("poll", 2, token="2")["status"], "acquired")
        self.assertEqual(self.call("poll", 3, token="3")["status"], "waiting")

    def test_same_class_barrier_still_checks_and_allows_other_class(self) -> None:
        self.policy["maximum_queue_bypasses"] = 1
        self.acquire(1, budget(cpu=3))
        self.acquire(2, budget(cpu=4))
        self.acquire(3)
        self.call("release", 3, token="3")
        self.assertEqual(self.acquire(4)["reason"], "same_class_queue_barrier")
        self.snapshot["io_pressure"] = True
        heavy = self.policy["profiles"]["heavy-compute"]
        self.assertEqual(self.acquire(5, heavy)["reason"], "io_pressure")
        self.snapshot["io_pressure"] = False
        self.assertEqual(self.call("poll", 5, token="5")["status"], "acquired")

    def test_invalid_and_incomplete_telemetry_preserve_state(self) -> None:
        self.acquire(1)
        before = self.path.read_bytes()
        self.snapshot["complete"] = False
        with self.assertRaises(ValueError):
            self.acquire(2)
        self.assertEqual(before, self.path.read_bytes())
        for resources in [budget(cpu=float("nan")), budget(memory=-1), budget(exclusive=["x", "x"])]:
            with self.assertRaises(ValueError):
                validate_budget(resources)

    def test_missing_creation_identity_is_not_process_death(self) -> None:
        self.acquire(1)
        self.snapshot["processes"] = [p for p in self.snapshot["processes"] if p["pid"] != 1]
        self.snapshot["unknown_process_ids"] = [1]
        with self.assertRaisesRegex(ValueError, "identity is unavailable"):
            self.acquire(2)
        self.snapshot["unknown_process_ids"] = [999]
        self.assertEqual(self.acquire(2)["status"], "acquired")

    def test_definitely_exited_identity_is_pruned_after_snapshot_race(self) -> None:
        self.acquire(1, budget(cpu=4))
        self.snapshot["processes"] = [p for p in self.snapshot["processes"] if p["pid"] != 1]
        # The adapter saw a CIM row without CreationDate, then native process
        # lookup proved the owner had exited before this snapshot completed.
        self.snapshot["unknown_process_ids"] = [1]
        self.snapshot["definitely_exited_process_ids"] = [1]
        self.assertEqual(self.acquire(2, budget(cpu=4))["status"], "acquired")
        self.assertEqual([record["token"] for record in self.call("status")["records"]], ["2"])

    def test_definitely_exited_identity_cannot_conflict_with_live_observation(self) -> None:
        self.acquire(1)
        self.snapshot["definitely_exited_process_ids"] = [1]
        with self.assertRaisesRegex(ValueError, "conflicts with a live"):
            self.acquire(2)

    def test_live_owner_can_release_exact_waited_child_despite_unreadable_recycled_pid(self) -> None:
        self.acquire(1, budget(cpu=4))
        self.snapshot["processes"].append(
            dict(pid=99, parent_pid=1, started="0000000000000000002", memory_bytes=GIB)
        )
        self.call("register", token="1", process_id=99)
        self.snapshot["processes"] = [process for process in self.snapshot["processes"] if process["pid"] != 99]
        self.snapshot["unknown_process_ids"] = [99]
        result = self.call(
            "release", token="1",
            completed_work_processes=[dict(pid=99, started="0000000000000000002")],
        )
        self.assertEqual(result["status"], "released")
        self.assertEqual(self.acquire(2, budget(cpu=4))["status"], "acquired")

    def test_completion_evidence_rejects_descendant_and_unregistered_or_mismatched_identity(self) -> None:
        self.acquire(1)
        self.snapshot["processes"].append(
            dict(pid=99, parent_pid=1, started="0000000000000000002", memory_bytes=GIB)
        )
        self.call("register", token="1", process_id=99)
        self.snapshot["processes"] = [process for process in self.snapshot["processes"] if process["pid"] != 99]
        self.snapshot["unknown_process_ids"] = [99]
        with self.assertRaisesRegex(ValueError, "live reservation owner"):
            self.call("release", 2, token="1", completed_work_processes=[dict(pid=99, started="0000000000000000002")])
        with self.assertRaisesRegex(ValueError, "exact registered"):
            self.call("release", token="1", completed_work_processes=[dict(pid=99, started="wrong")])
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.call("release", token="1")

    def test_reopen_persistent_ledger_retains_live_reservations(self) -> None:
        self.acquire(1, budget(cpu=4))
        self.assertEqual(self.acquire(2)["status"], "waiting")
        self.assertEqual(len(self.call("status")["records"]), 2)

    def test_old_snapshot_cannot_erase_a_new_grant(self) -> None:
        stale = copy.deepcopy(self.snapshot)
        stale["observed_at_ticks"] = time.time_ns()
        stale["processes"] = [p for p in stale["processes"] if p["pid"] != 1]
        self.acquire(1, budget(cpu=4))
        with self.assertRaises(StaleSnapshotError):
            transact(self.path, dict(operation="status"), stale, self.policy)
        self.assertEqual(self.acquire(2)["status"], "waiting")

    def test_phase_cannot_exceed_host_capacity(self) -> None:
        self.acquire(1)
        self.policy["io_slots"] = 1
        for resources in (budget(cpu=5), budget(io=2), budget(memory=16*GIB)):
            with self.assertRaises(ValueError):
                self.call("transition", token="1", stage="too-big", budget=resources, retained_memory_bytes=0)
            self.assertEqual(self.call("poll", token="1")["stage"], "test")

    def test_nonfinite_and_negative_telemetry_fails_closed(self) -> None:
        for key in ("cpu_percent", "available_memory_bytes", "total_memory_bytes"):
            original = self.snapshot[key]
            for value in (float("nan"), float("inf"), -1):
                self.snapshot[key] = value
                with self.assertRaises(ValueError):
                    self.acquire(1)
            self.snapshot[key] = original

    def test_orphan_kept_when_parent_pid_already_reused(self) -> None:
        self.acquire(1, budget(cpu=4))
        self.snapshot["processes"][0]["started"] = "0000000000000000003"
        self.snapshot["processes"].append(dict(pid=99, parent_pid=1, started="0000000000000000002", memory_bytes=2*GIB))
        self.assertEqual(self.acquire(2)["status"], "waiting")

    def test_declared_retained_memory_is_not_lost_after_admission(self) -> None:
        self.acquire(1)
        result = self.call("transition", token="1", stage="retained", budget=budget(), retained_memory_bytes=8*GIB)
        self.assertEqual(result["status"], "acquired")
        self.assertEqual(self.acquire(2, budget(memory=8*GIB))["status"], "waiting")

    def test_impossible_declared_retained_memory_rolls_back(self) -> None:
        self.acquire(1)
        with self.assertRaisesRegex(ValueError, "retained memory exceeds"):
            self.call("transition", token="1", stage="too-large", budget=budget(), retained_memory_bytes=16*GIB)
        self.assertEqual(self.call("poll", token="1")["stage"], "test")

    def test_unknown_peak_still_checks_io_pressure_and_retained_promises(self) -> None:
        self.snapshot["io_pressure"] = True
        self.assertEqual(self.acquire(1, budget(unknown=True, io=1))["reason"], "io_pressure")

    def test_live_solver_prevents_phase_release_of_exclusive_resource(self) -> None:
        self.acquire(1, budget(exclusive=["solver-server"]))
        self.snapshot["processes"].append(dict(pid=99, parent_pid=1, started="0000000000000000002", memory_bytes=2*GIB))
        self.call("register", token="1", process_id=99)
        with self.assertRaisesRegex(ValueError, "live descendants"):
            self.call("transition", token="1", stage="postprocess", budget=budget(), retained_memory_bytes=0)
        self.assertEqual(self.acquire(2, budget(exclusive=["solver-server"]))["reason"], "exclusive_resource_in_use")

    def test_unregistered_control_descendant_does_not_hold_stage_boundary(self) -> None:
        self.acquire(1)
        self.snapshot["processes"].append(dict(pid=99, parent_pid=1, started="0000000000000000002", memory_bytes=2*GIB))
        result = self.call("transition", token="1", stage="next", budget=budget(), retained_memory_bytes=0)
        self.assertEqual(result["status"], "acquired")
        self.assertIn(99, result["live_process_ids"])
        self.assertEqual(result["live_work_process_ids"], [])

    def test_system_console_does_not_block_phase_but_stays_in_memory_accounting(self) -> None:
        self.acquire(1)
        self.snapshot["processes"].append(dict(pid=99, parent_pid=1, started="0000000000000000002",
                                                memory_bytes=GIB, is_system_console_host=True))
        self.call("register", token="1", process_id=99)
        result = self.call("transition", token="1", stage="next", budget=budget(), retained_memory_bytes=0)
        self.assertEqual(result["status"], "acquired")
        self.assertIn(99, result["live_process_ids"])
        self.assertEqual(result["retained_bytes"], GIB + GIB//16)
        self.snapshot["processes"].append(dict(pid=100, parent_pid=99, started="0000000000000000003",
                                                 memory_bytes=GIB, is_system_console_host=False))
        with self.assertRaisesRegex(ValueError, "live descendants"):
            self.call("transition", token="1", stage="unsafe", budget=budget(), retained_memory_bytes=0)

    def test_release_console_only_allows_another_owner_while_shell_lives(self) -> None:
        self.acquire(1, budget(unknown=True))
        self.snapshot["processes"].append(dict(pid=99, parent_pid=1, started="0000000000000000002",
                                                memory_bytes=GIB, is_system_console_host=True))
        self.assertEqual(self.call("release", token="1")["status"], "released")
        self.assertEqual(self.acquire(2, budget(cpu=4))["status"], "acquired")

    def test_release_preserves_solver_under_a_system_console(self) -> None:
        self.acquire(1, self.policy["profiles"]["heavy-compute"])
        self.snapshot["processes"].extend([
            dict(pid=99, parent_pid=1, started="0000000000000000002", memory_bytes=GIB, is_system_console_host=True),
            dict(pid=100, parent_pid=99, started="0000000000000000003", memory_bytes=GIB),
        ])
        self.assertEqual(self.call("release", token="1")["status"], "acquired")
        self.assertEqual(self.acquire(2, self.policy["profiles"]["heavy-compute"])["reason"], "heavy_stage_active")


if __name__ == "__main__":
    unittest.main()
