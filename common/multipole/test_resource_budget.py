from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common.multipole.resource_budget import validate_pilot_budget
from common.multipole.runtime_profile import resolve_runtime_profile

REPO_ROOT = Path(__file__).resolve().parents[2]
QUAD = "rf_quadrupole_ion_optics"
HEX = "rf_hexapole_ion_optics"
OCT = "rf_octupole_ion_optics"


class ResourceBudgetTests(unittest.TestCase):
    def test_disk_capacity_check_reports_live_volume_capacity_and_fails_closed(self) -> None:
        """The public preflight adds transient demand above the requested floor."""
        support = REPO_ROOT / "common/multipole/resource_budget_support.ps1"
        command = (
            f". '{support}';"
            "$pass=Test-RepositoryDiskCapacity -TargetPath $env:TEMP "
            "-TransientRunDirectoryBytes 0 -MinimumFreeBytes 10GB;"
            "if($pass.role-ne'repository_disk_capacity_check'-or"
            "$pass.system_disk_reserve_bytes-ne10GB-or$pass.minimum_free_bytes-ne10GB-or-not$pass.passed-or"
            "$pass.free_bytes-lt$pass.required_available_bytes){exit 3};"
            "try{Test-RepositoryDiskCapacity -TargetPath $env:TEMP "
            "-TransientRunDirectoryBytes ([int64]::MaxValue-10GB) -MinimumFreeBytes 10GB;exit 4}catch{"
            "$failed=$_.TargetObject;if($failed.role-ne'repository_disk_capacity_check'-or"
            "$failed.passed-or$failed.free_bytes-ge$failed.required_available_bytes){exit 5}}"
        )
        completed = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_scheduler_lifecycle_event_reports_real_batch_metadata(self) -> None:
        """Public executor events must identify the completed work exactly."""
        support = REPO_ROOT / "common/multipole/resource_budget_support.ps1"
        command = (
            f". '{support}';"
            "$spec=[pscustomobject]@{scheduler_batch=[pscustomobject]@{"
            "index=2;total_batches=4;particle_id_min=1251;particle_id_max=2500;count=1250}};"
            "$record=[pscustomobject]@{name='fly__test__batch_2';specification=$spec};"
            "Write-RepositorySchedulerEvent -Event 'BATCH_COMPLETED' -Record $record "
            "-ActiveCount 1 -PendingCount 2 -Details @{EXIT_CODE=0;NATURAL='true';"
            "WALL_CLOCK_SECONDS=12.5;MORE_PENDING='true'}"
        )
        completed = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for token in (
            "SIMION_RESOURCE_EVENT=BATCH_COMPLETED",
            "BATCH=2",
            "TOTAL_BATCHES=4",
            "PARTICLE_ID_MIN=1251",
            "PARTICLE_ID_MAX=2500",
            "PARTICLE_COUNT=1250",
            "ACTIVE=1",
            "PENDING=2",
            "EXIT_CODE=0",
            "MORE_PENDING=true",
            "WALL_CLOCK_SECONDS=12.5",
        ):
            self.assertIn(token, completed.stdout)

    def test_repository_scheduler_owns_stagger_and_latest_first_memory_recovery(self) -> None:
        source = (REPO_ROOT / "common/multipole/resource_budget_support.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("$seconds-ne 45", source)
        self.assertIn("$now.AddSeconds(5)", source)
        self.assertIn("Sort-Object started_at -Descending", source)
        self.assertIn("available_memory_below_0p5_gib_for_15_seconds", source)
        self.assertIn("$warningBytes-ne 1GB-or$criticalBytes-ne 512MB", source)
        self.assertIn("maximum_memory_danger_termination_attempts-ne 2", source)
        self.assertIn("$dangerTerminationAttempts-ge$maximumDangerTerminations", source)
        self.assertIn("PrivateMemorySize64", source)
        self.assertIn("peak_process_tree_managed_memory_bytes", source)
        self.assertIn("$dangerRecoveryPending=$true", source)
        self.assertIn("-not$dangerRecoveryPending", source)
        self.assertIn("available_memory_below_dynamic_admission", source)
        self.assertIn("$pending.Insert(0,$victim.specification)", source)
        self.assertIn("requeue_priority='front'", source)
        self.assertIn("$maximumConcurrency-1", source)
        self.assertNotIn("CalibrationDurationSeconds", source)

    def test_scheduler_suppresses_checkpoint_callback_pipeline_output(self) -> None:
        """A manifest-publishing callback must not turn the wave receipt into an array."""
        source = (REPO_ROOT / "common/multipole/resource_budget_support.ps1").read_text(
            encoding="utf-8"
        )
        self.assertEqual(source.count("$null = & $OnProcessCompleted $record"), 2)
        self.assertNotIn("      & $OnProcessCompleted $record", source)

    def test_invalid_windows_cpu_sample_is_discarded(self) -> None:
        """An out-of-range WMI sample must not suppress otherwise safe lanes."""
        support = REPO_ROOT / "common/multipole/resource_budget_support.ps1"
        command = (
            f". '{support}';"
            "function Get-CimInstance { [pscustomobject]@{LoadPercentage=109.072} };"
            "if($null -ne (Get-SystemCpuPercent)){exit 3};"
            "function Get-CimInstance { [pscustomobject]@{LoadPercentage=6} };"
            "if((Get-SystemCpuPercent)-ne6){exit 4}"
        )
        completed = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_process_sample_discards_reused_root_pid(self) -> None:
        """A new process with an old solver PID must not hold its watchdog open."""
        support = REPO_ROOT / "common/multipole/resource_budget_support.ps1"
        command = (
            f". '{support}';"
            "$ticks=[int64]((Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks-1);"
            "$sample=Get-ManagedSolverProcessSample -RootProcessIds @($PID) "
            "-RootProcessStartedAtUtcTicks @{([string]$PID)=$ticks};"
            "if(@($sample.active_process_ids).Count-ne0){exit 3}"
        )
        completed = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_formal_observation_exports_conservative_managed_peak(self) -> None:
        """A trimmed working set must not lower the profile passed to admission."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch = root / "dispatch.json"
            dispatch.write_text(
                json.dumps(
                    {
                        "role": "simion_repository_dispatch_plan",
                        "estimation": {"kind": "formal_first_batch_observation"},
                        "limits": {
                            "formal_observation_seconds": 45,
                            "memory_critical_reserve_bytes": 512 * 1024**2,
                            "memory_critical_seconds": 15,
                        },
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/multipole/resource_budget_support.ps1"
            stdout, stderr = root / "stdout.log", root / "stderr.log"
            command = (
                f". '{support}';"
                "$script:sampleCalls=0;"
                "function Get-ManagedSolverProcessSample {"
                "param([int[]]$RootProcessIds,[int[]]$TrackedProcessIds);"
                "$script:sampleCalls+=1;"
                "$active=$(if($script:sampleCalls-lt3){@($RootProcessIds[0])}else{@()});"
                "[pscustomobject]@{tracked_process_ids=@($RootProcessIds[0]);"
                "active_process_ids=$active;working_set_bytes=1073741824;"
                "private_bytes=4294967296;managed_memory_bytes=4294967296;"
                "total_processor_time_ticks=0}"
                "};"
                "$spec=[pscustomobject]@{name='formal';file_path=(Get-Process -Id $PID).Path;"
                "argument_list=@('-NoProfile','-Command','Start-Sleep -Seconds 1');"
                f"stdout='{stdout}';stderr='{stderr}';environment=@{{}};working_directory='{root}'}};"
                f"$r=Start-ObservedFormalProcess -DispatchPlanPath '{dispatch}' -ProcessSpecification $spec;"
                "if($r.observed_peak_process_tree_working_set_bytes-ne4294967296 -or"
                "$r.observed_peak_process_tree_managed_memory_bytes-ne4294967296 -or"
                "$r.observed_peak_process_tree_resident_working_set_bytes-ne1073741824){exit 3}"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_completed_first_formal_observation_still_writes_admission_receipt(self) -> None:
        """A naturally completed N=1 observation skips the dispatch loop safely."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch, usage = root / "dispatch.json", root / "usage.json"
            dispatch.write_text(json.dumps({
                "role": "simion_repository_dispatch_plan",
                "particle_count": 1,
                "estimation": {
                    "kind": "observed_formal_batch",
                    "per_process_memory_budget_bytes": 123456,
                    "memory_safety_factor": 1.0,
                },
                "limits": {
                    "maximum_concurrency": 1, "launch_stagger_seconds": 5,
                    "memory_critical_seconds": 15,
                    "memory_recovery_stable_seconds": 45,
                    "maximum_memory_recovery_attempts": 2,
                    "maximum_memory_danger_termination_attempts": 2,
                    "memory_admission_reserve_bytes": 1024**3,
                    "memory_critical_reserve_bytes": 512 * 1024**2,
                    "cpu_admission_percent": 95.0,
                },
            }), encoding="utf-8")
            support = REPO_ROOT / "common/multipole/resource_budget_support.ps1"
            command = (
                f". '{support}';"
                "$record=[pscustomobject]@{name='batch01';completed=$true;exit_code=0;"
                "peak_working_set_bytes=[int64]10;peak_managed_memory_bytes=[int64]20;"
                "completed_during_observation=$true;observed_process_cpu_percent=0.0;"
                "observed_background_cpu_percent=0.0};"
                f"$r=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' "
                f"-RunDir '{root}' -UsagePath '{usage}' -ExistingProcessRecords @($record);"
                "if($r.resource_budget_exceeded){exit 3};"
                f"$receipt=Get-Content -Raw '{usage}'|ConvertFrom-Json;"
                "if($receipt.scheduler_receipt.dynamic_admission_bytes_at_finish-ne123456){exit 4}"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT, check=False, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=15,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_scheduler_recovers_twice_then_fails_closed_after_third_danger(self) -> None:
        """Exercise the 15 s danger, 45 s recovery, and terminal-fail state machine."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch, usage = root / "dispatch.json", root / "usage.json"
            dispatch.write_text(
                json.dumps(
                    {
                        "role": "simion_repository_dispatch_plan",
                        "estimation": {
                            "kind": "exact_resource_profile",
                            "per_process_memory_budget_bytes": 1024**3,
                            "memory_safety_factor": 1.10,
                        },
                        "limits": {
                            "maximum_concurrency": 2,
                            "launch_stagger_seconds": 5,
                            "memory_critical_seconds": 15,
                            "memory_recovery_stable_seconds": 45,
                            "maximum_memory_recovery_attempts": 2,
                            "maximum_memory_danger_termination_attempts": 2,
                            "memory_admission_reserve_bytes": 1024**3,
                            "memory_critical_reserve_bytes": 512 * 1024**2,
                            "cpu_admission_percent": 95.0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/multipole/resource_budget_support.ps1"
            command = (
                f". '{support}';"
                "$script:now=[datetimeoffset]'2026-08-26T00:00:00Z';$script:nextPid=100;"
                "function Get-RepositoryUtcNow {$script:now};"
                "function Start-Sleep {param([int]$Seconds=0,[int]$Milliseconds=0);"
                "$script:now=$script:now.AddSeconds($Seconds+($Milliseconds/1000.0))};"
                "function Get-RepositoryAvailableMemoryBytes {"
                "$seconds=($script:now-[datetimeoffset]'2026-08-26T00:00:00Z').TotalSeconds;"
                "if(($seconds-ge1-and$seconds-lt17)-or($seconds-ge72-and$seconds-lt88)-or$seconds-ge138){return [int64](256MB)};"
                "return [int64](8GB)};"
                "function Get-SystemCpuPercent {[double]0};"
                "function Start-RepositoryScheduledProcess {param($Specification);$script:nextPid+=1;"
                "[pscustomobject]@{name=[string]$Specification.name;specification=$Specification;process=$null;"
                "root_process_id=$script:nextPid;started_at=(Get-RepositoryUtcNow);tracked_process_ids=@($script:nextPid);"
                "active=$true;completed=$false;exit_code=$null;peak_working_set_bytes=[int64]0;"
                "peak_managed_memory_bytes=[int64]0;pressure_terminated=$false}};"
                "function Get-ManagedSolverProcessSample {param([int[]]$RootProcessIds,[int[]]$TrackedProcessIds);"
                "[pscustomobject]@{tracked_process_ids=@($RootProcessIds[0]);active_process_ids=@($RootProcessIds[0]);"
                "working_set_bytes=1073741824;private_bytes=2147483648;managed_memory_bytes=2147483648;"
                "total_processor_time_ticks=0}};"
                "function Stop-ManagedSolverProcesses {param([int[]]$ProcessIds)};"
                "$specs=@('a','b'|ForEach-Object {[pscustomobject]@{name=$_;file_path='unused';argument_list=@();"
                "stdout='unused';stderr='unused';environment=@{};working_directory=''}});"
                f"$r=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' -RunDir '{root}' "
                f"-UsagePath '{usage}' -ProcessSpecifications $specs;"
                "if(-not$r.resource_budget_exceeded){exit 3};"
                f"$receipt=Get-Content -Raw '{usage}'|ConvertFrom-Json;"
                "if($receipt.status-ne'resource_pressure_failed' -or"
                "$receipt.failure_class-ne'memory_danger_recovery_attempts_exhausted' -or"
                "$receipt.scheduler_receipt.termination_requeue_events.Count-ne2 -or"
                "$receipt.scheduler_receipt.recovery_relaunch_events.Count-ne2 -or"
                "$receipt.scheduler_receipt.recovery_relaunch_events[0].attempt-ne1 -or"
                "$receipt.scheduler_receipt.recovery_relaunch_events[1].attempt-ne2){exit 4};"
                "if(([datetimeoffset]$receipt.scheduler_receipt.recovery_relaunch_events[0].at_utc-"
                "[datetimeoffset]$receipt.scheduler_receipt.termination_requeue_events[0].at_utc).TotalSeconds-lt45){exit 5}"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_failed_batch_cancels_its_wave_without_claiming_resource_pressure(self) -> None:
        """A solver failure stops siblings and queued work, preserving its cause."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch, usage = root / "dispatch.json", root / "usage.json"
            dispatch.write_text(
                json.dumps(
                    {
                        "role": "simion_repository_dispatch_plan",
                        "estimation": {
                            "kind": "exact_resource_profile",
                            "per_process_memory_budget_bytes": 1024**2,
                            "memory_safety_factor": 1.10,
                        },
                        "limits": {
                            "maximum_concurrency": 2,
                            "launch_stagger_seconds": 5,
                            "memory_critical_seconds": 15,
                            "memory_recovery_stable_seconds": 45,
                            "maximum_memory_recovery_attempts": 2,
                            "maximum_memory_danger_termination_attempts": 2,
                            "memory_admission_reserve_bytes": 1024**3,
                            "memory_critical_reserve_bytes": 512 * 1024**2,
                            "cpu_admission_percent": 95.0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/multipole/resource_budget_support.ps1"
            command = (
                f". '{support}';"
                "function Get-SystemCpuPercent {[double]0};"
                "function Get-RepositoryAvailableMemoryBytes {[int64](32GB)};"
                "$exe=(Get-Process -Id $PID).Path;"
                "$specs=@("
                "[pscustomobject]@{name='fails';file_path=$exe;"
                "argument_list=@('-NoProfile','-Command','Start-Sleep -Seconds 7; exit 7');"
                f"stdout='{root}\\fails.out';stderr='{root}\\fails.err';environment=@{{}};working_directory='{root}'}},"
                "[pscustomobject]@{name='sibling';file_path=$exe;"
                "argument_list=@('-NoProfile','-Command','Start-Sleep -Seconds 20');"
                f"stdout='{root}\\sibling.out';stderr='{root}\\sibling.err';environment=@{{}};working_directory='{root}'}},"
                "[pscustomobject]@{name='queued';file_path=$exe;"
                "argument_list=@('-NoProfile','-Command','Start-Sleep -Seconds 20');"
                f"stdout='{root}\\queued.out';stderr='{root}\\queued.err';environment=@{{}};working_directory='{root}'}}) ;"
                f"$r=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' -RunDir '{root}' "
                f"-UsagePath '{usage}' -ProcessSpecifications $specs;"
                "if($r.resource_budget_exceeded){exit 3};"
                f"$receipt=Get-Content -Raw '{usage}'|ConvertFrom-Json;"
                "if($receipt.status-ne'process_failed' -or "
                "$receipt.scheduler_receipt.batch_failure_cancellation_events.Count-ne1){exit 4};"
                "if(Test-Path -LiteralPath '" + str(root / "queued.out") + "'){exit 5}"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=25,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_shared_runtime_key_serializes_only_conflicting_workers(self) -> None:
        """A shared SIMION PA family waits without becoming a global lane cap."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch, usage = root / "dispatch.json", root / "usage.json"
            dispatch.write_text(
                json.dumps(
                    {
                        "role": "simion_repository_dispatch_plan",
                        "estimation": {
                            "kind": "exact_resource_profile",
                            "per_process_memory_budget_bytes": 1024**2,
                            "memory_safety_factor": 1.10,
                        },
                        "limits": {
                            "maximum_concurrency": 2,
                            "launch_stagger_seconds": 5,
                            "memory_critical_seconds": 15,
                            "memory_recovery_stable_seconds": 45,
                            "maximum_memory_recovery_attempts": 2,
                            "maximum_memory_danger_termination_attempts": 2,
                            "memory_admission_reserve_bytes": 1024**3,
                            "memory_critical_reserve_bytes": 512 * 1024**2,
                            "cpu_admission_percent": 95.0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/multipole/resource_budget_support.ps1"
            command = (
                f". '{support}';"
                "function Get-SystemCpuPercent {[double]0};"
                "function Get-RepositoryAvailableMemoryBytes {[int64](32GB)};"
                "$exe=(Get-Process -Id $PID).Path;"
                "$specs=@('first','second'|ForEach-Object {[pscustomobject]@{name=$_;file_path=$exe;"
                "argument_list=@('-NoProfile','-Command','Start-Sleep -Seconds 7');"
                f"stdout='{root}\\$_.out';stderr='{root}\\$_.err';environment=@{{}};working_directory='{root}';"
                "exclusive_resource_key='shared-pa-family'}});"
                f"$r=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' -RunDir '{root}' "
                f"-UsagePath '{usage}' -ProcessSpecifications $specs;"
                "if($r.resource_budget_exceeded-or$r.processes.Count-ne2-or"
                "@($r.processes|Where-Object {$_.exit_code-ne0}).Count-ne0){exit 3};"
                f"$receipt=Get-Content -Raw '{usage}'|ConvertFrom-Json;"
                "if($receipt.scheduler_receipt.peak_concurrency-ne1){exit 4};"
                "$waits=@($receipt.scheduler_receipt.launch_pause_events|Where-Object {$_.reason-eq'exclusive_resource_in_use'});"
                "if($waits.Count-lt1){exit 5}"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_dynamic_admission_pause_records_memory_reason_with_two_gib_free(self) -> None:
        """The 1 GiB reserve alone is insufficient when the next worker is larger."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch, usage = root / "dispatch.json", root / "usage.json"
            dispatch.write_text(
                json.dumps(
                    {
                        "role": "simion_repository_dispatch_plan",
                        "estimation": {
                            "kind": "exact_resource_profile",
                            "per_process_memory_budget_bytes": 5 * 1024**3,
                            "memory_safety_factor": 1.10,
                        },
                        "limits": {
                            "maximum_concurrency": 2,
                            "launch_stagger_seconds": 5,
                            "memory_critical_seconds": 15,
                            "memory_recovery_stable_seconds": 45,
                            "maximum_memory_recovery_attempts": 2,
                            "maximum_memory_danger_termination_attempts": 2,
                            "memory_admission_reserve_bytes": 1024**3,
                            "memory_critical_reserve_bytes": 512 * 1024**2,
                            "cpu_admission_percent": 95.0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/multipole/resource_budget_support.ps1"
            command = (
                f". '{support}';$script:memorySamples=0;"
                "function Get-SystemCpuPercent {[double]0};"
                "function Get-RepositoryAvailableMemoryBytes {$script:memorySamples+=1;"
                "if($script:memorySamples-eq1-or$script:memorySamples-gt11){return [int64](10GB)};"
                "return [int64](5GB)};"
                "$exe=(Get-Process -Id $PID).Path;"
                "$specs=@('a','b'|ForEach-Object {[pscustomobject]@{name=$_;file_path=$exe;"
                "argument_list=@('-NoProfile','-Command','Start-Sleep -Seconds 7');"
                f"stdout='{root}\\$_.out';stderr='{root}\\$_.err';environment=@{{}};working_directory='{root}'}}}});"
                f"$r=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' -RunDir '{root}' "
                f"-UsagePath '{usage}' -ProcessSpecifications $specs;"
                "if($r.resource_budget_exceeded){exit 3};"
                f"$receipt=Get-Content -Raw '{usage}'|ConvertFrom-Json;"
                "$pauses=@($receipt.scheduler_receipt.launch_pause_events|Where-Object {$_.reason-eq'available_memory_below_dynamic_admission'});"
                "if($pauses.Count-lt1-or$pauses[0].available_memory_bytes-ne(5GB)-or"
                "$pauses[0].required_available_memory_bytes-le(5GB)){exit 4}"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_one_lane_observed_formal_profile_starts_from_single_peak_not_concurrency_headroom(self) -> None:
        """A completed formal batch must allow its sole remaining lane to start."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch, usage = root / "dispatch.json", root / "usage.json"
            observed_peak = 35 * 1024**3
            dispatch.write_text(
                json.dumps(
                    {
                        "role": "simion_repository_dispatch_plan",
                        "estimation": {
                            "kind": "observed_formal_batch",
                            "observed_peak_bytes": observed_peak,
                            "per_process_memory_budget_bytes": int(observed_peak * 1.10),
                            "memory_safety_factor": 1.10,
                        },
                        "limits": {
                            "maximum_concurrency": 1,
                            "launch_stagger_seconds": 5,
                            "memory_critical_seconds": 15,
                            "memory_recovery_stable_seconds": 45,
                            "maximum_memory_recovery_attempts": 2,
                            "maximum_memory_danger_termination_attempts": 2,
                            "memory_admission_reserve_bytes": 1024**3,
                            "memory_critical_reserve_bytes": 512 * 1024**2,
                            "cpu_admission_percent": 95.0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/multipole/resource_budget_support.ps1"
            command = (
                f". '{support}';"
                "function Get-SystemCpuPercent {[double]0};"
                "function Get-RepositoryAvailableMemoryBytes {[int64](38GB)};"
                "$exe=(Get-Process -Id $PID).Path;"
                "$specs=@([pscustomobject]@{name='only';file_path=$exe;"
                "argument_list=@('-NoProfile','-Command','Start-Sleep -Milliseconds 200');"
                f"stdout='{root}\\only.out';stderr='{root}\\only.err';environment=@{{}};working_directory='{root}'}});"
                f"$r=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' -RunDir '{root}' "
                f"-UsagePath '{usage}' -ProcessSpecifications $specs;"
                "if($r.resource_budget_exceeded-or$r.processes.Count-ne1-or$r.processes[0].exit_code-ne0){exit 3};"
                f"$receipt=Get-Content -Raw '{usage}'|ConvertFrom-Json;"
                "if(@($receipt.scheduler_receipt.launch_pause_events).Count-ne0){exit 4}"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_process_sampler_drops_a_reused_tracked_pid(self) -> None:
        """A reused child PID must not keep a completed SIMION lane alive."""
        support = REPO_ROOT / "common/multipole/resource_budget_support.ps1"
        command = (
            f". '{support}';"
            "$stale=@{([string]$PID)=[int64]1};"
            "$sample=Get-ManagedSolverProcessSample -RootProcessIds @($PID) "
            "-TrackedProcessIds @($PID) -TrackedProcessStartedAtUtcTicks $stale;"
            "if(@($sample.active_process_ids).Count-ne0){exit 3};"
            "if(@($sample.tracked_process_ids).Count-ne0){exit 4}"
        )
        completed = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_single_process_meter_carries_descendant_birth_identities(self) -> None:
        """The lightweight meter must not confuse a reused helper PID with SIMION."""
        support = (REPO_ROOT / "common/multipole/resource_budget_support.ps1").read_text(
            encoding="utf-8"
        )
        start = support.index("function Invoke-ResourceBudgetedProcess")
        end = support.index("function Assert-RepositoryProcessSpecification", start)
        meter = support[start:end]
        self.assertIn(
            "-TrackedProcessStartedAtUtcTicks $trackedProcessStartedAtUtcTicks",
            meter,
        )
        self.assertIn(
            "$trackedProcessStartedAtUtcTicks=$sample.tracked_process_started_at_utc_ticks",
            meter,
        )


    def validate(
        self,
        project_id: str = OCT,
        runtime_profile_id: str = "exit_aperture_plate_acceleration_n100_spatial_refined",
        retention_class: str = "compact",
    ) -> dict:
        runtime = resolve_runtime_profile(REPO_ROOT, project_id, runtime_profile_id)
        return validate_pilot_budget(
            repo_root=REPO_ROOT,
            budget_path=Path(runtime["engineering_budget"]["path"]),
            project_id=project_id,
            solver="comsol",
            runtime_profile_id=runtime_profile_id,
            design_profile_id=runtime["design_profile_id"],
            particle_source_path=Path(runtime["particle_source"]["path"]),
            retention_class=retention_class,
        )

    def test_closed_projects_reject_commercial_solver_pairs(self) -> None:
        for project_id, profile in (
            (QUAD, "exit_aperture_plate_acceleration_n100_spatial_refined"),
            (OCT, "exit_aperture_plate_acceleration_n100_spatial_refined"),
        ):
            with self.assertRaisesRegex(
                ValueError, "not authorized|differs from authorized scope"
            ):
                self.validate(project_id, profile)
        with self.assertRaisesRegex(
            ValueError, "not authorized|differs from authorized scope"
        ):
            self.validate(HEX, "exit_aperture_plate_acceleration_n100_spatial_refined")
        with self.assertRaisesRegex(
            ValueError, "not authorized|differs from authorized scope"
        ):
            self.validate(
                OCT,
                "exit_aperture_plate_acceleration",
            )

    def test_hexapole_closed_mesh_build_profiles_are_not_authorized(self) -> None:
        for profile in (
            "exit_aperture_plate_acceleration_n100_hybrid_d1_mesh_build",
            "exit_aperture_plate_acceleration_n100_hybrid_p1_coarse",
            "exit_aperture_plate_acceleration_n100_hybrid_d2_mesh_build",
        ):
            with self.assertRaisesRegex(ValueError, "unknown runtime profile"):
                resolve_runtime_profile(REPO_ROOT, HEX, profile)

    def test_high_cost_runners_validate_before_creating_run_package(self) -> None:
        for name in ("run_finite_3d_transport.ps1", "run_simion_finite_3d_transport.ps1"):
            source = (REPO_ROOT / "common/multipole" / name).read_text(encoding="utf-8")
            self.assertLess(
                source.index("common.multipole.resource_budget"),
                source.index("New-RunPackage"),
            )
            for token in (
                "[Parameter(Mandatory=$true)][string]$RuntimeProfileId",
                "[Parameter(Mandatory=$true)][string]$EngineeringBudgetPath",
                "resource_budget_exceeded",
                "Complete-ResourceUsage",
            ):
                self.assertIn(token, source)
            self.assertIn("-UseShortExecutionPath", source)
            self.assertIn("Remove-RunPackageExecutionAlias", source)
        comsol = (REPO_ROOT / "common/multipole/run_finite_3d_transport.ps1").read_text(
            encoding="utf-8"
        )
        comsol += (
            REPO_ROOT / "common/multipole/finite_3d_transport_preflight.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("'-StartupAttempts','1'", comsol)
        self.assertIn(
            "[ValidateSet('transport','mesh_build','field_solve')]"
            "[string]$StopStage='transport'",
            comsol,
        )
        self.assertIn("MULTIPOLE_L3_STOP_STAGE", comsol)
        self.assertIn("UNQUALIFIED_MESH_BUILD_DIAGNOSTIC_ONLY", comsol)
        self.assertIn("UNQUALIFIED_FIELD_SOLVE_DIAGNOSTIC_ONLY", comsol)
        self.assertNotIn("$RuntimeProfileId -like '*_mesh_build'", comsol)
        self.assertIn("Assert-MultipoleFieldSolveReport", comsol)
        self.assertIn(
            "'common/multipole/configure_comsol_segment_hybrid_mesh.m'",
            comsol,
        )
        self.assertIn(
            "$resolvedBudget.PSObject.Properties.Name-notcontains'stop_stage'",
            comsol,
        )
        self.assertIn("$StopStage-ne$authorizedStopStage", comsol)
        self.assertLess(
            comsol.index("$StopStage-ne$authorizedStopStage"),
            comsol.index("New-RunPackage"),
        )
        self.assertIn(
            "stationary_linear_solver_backend="
            "$authorizedBackend",
            comsol,
        )
        self.assertIn(
            "$authorizedBackend-notin@('mumps','pardiso','cg_amg')",
            comsol,
        )
        self.assertIn(
            "electric_potential_element_order=$authorizedElementOrder",
            comsol,
        )
        self.assertIn("omits the required electric-potential element order", comsol)
        self.assertIn("MESH_GLOBAL_ELEMENTS", comsol)
        self.assertIn("maximum_mesh_cells", comsol)
        self.assertIn("$usage.limit_name='maximum_mesh_cells'", comsol)
        self.assertIn("MULTIPOLE_L3_MAXIMUM_MESH_CELLS", comsol)
        self.assertIn("Assert-MultipoleMeshCellBudgetReport", comsol)
        self.assertIn("Compiled resolved design differs from the authorized run identity", comsol)
        solver = (
            REPO_ROOT / "common/multipole/solve_finite_3d_transport.m"
        ).read_text(encoding="utf-8")
        budget_gate = solver.index("MULTIPOLE_L3_MAXIMUM_MESH_CELLS")
        self.assertGreater(budget_gate, solver.index("CHECKPOINT=MESH_COMPLETE"))
        self.assertLess(budget_gate, solver.index("material = model.material.create"))
        self.assertNotIn("fflush(", solver)
        self.assertIn("MESH_LOCAL_SENSITIVE_REGION_PRESENT=1", solver)
        self.assertIn("MESH_LOCAL_SENSITIVE_SIZE_FEATURE_PRESENT=%d", solver)

    def test_comsol_runner_fails_closed_on_stop_stage_disagreement(self) -> None:
        runner = (
            REPO_ROOT / "common/multipole/run_finite_3d_transport.ps1"
        ).read_text(encoding="utf-8")
        start = runner.index(
            "  if($resolvedBudget.PSObject.Properties.Name-notcontains'stop_stage')"
        )
        end = runner.index("  $authorizedNumerics=$resolvedBudget.solver_numerics", start)
        stop_stage_gate = runner[start:end]

        def run_gate(resolved_budget: str, cli_stop_stage: str) -> subprocess.CompletedProcess[str]:
            command = (
                f"$resolvedBudget={resolved_budget};"
                f"$StopStage='{cli_stop_stage}';"
                f"{stop_stage_gate}"
                'Write-Output "STOP_STAGE=$authorizedStopStage"'
            )
            return subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )

        matching = run_gate("[pscustomobject]@{stop_stage='field_solve'}", "field_solve")
        self.assertEqual(matching.returncode, 0, matching.stderr)
        self.assertIn("STOP_STAGE=field_solve", matching.stdout)

        missing = run_gate("[pscustomobject]@{}", "field_solve")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("omits the runtime-profile stop stage", missing.stderr)

        mismatch = run_gate("[pscustomobject]@{stop_stage='mesh_build'}", "field_solve")
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertIn("differs from the authorized runtime profile", mismatch.stderr)

    def test_mesh_cell_limit_is_optional_and_strictly_positive(self) -> None:
        budget_path = (
            REPO_ROOT
            / "projects"
            / HEX
            / "config"
            / "qualification"
            / "engineering_budget.json"
        )
        active_budget = json.loads(budget_path.read_text(encoding="utf-8"))
        runtime_profile_id = active_budget["pilot_authorization"]["scope"][
            "runtime_profile_id"
        ]
        runtime = resolve_runtime_profile(REPO_ROOT, HEX, runtime_profile_id)
        self.assertEqual(
            budget_path.resolve(),
            Path(runtime["engineering_budget"]["path"]).resolve(),
        )
        authorized_fixture = json.loads(budget_path.read_text(encoding="utf-8"))
        authorized_fixture["pilot_authorization"]["authorized"] = True
        authorized_fixture["pilot_authorization"]["scope"]["stop_stage"] = runtime[
            "stop_stage"
        ]
        authorized_fixture["pilot_authorization"]["limits"][
            "maximum_mesh_cells"
        ] = 100
        hybrid_runtime = json.loads(json.dumps(runtime))
        hybrid_runtime["solver_numerics"]["comsol"]["values"]["mesh"][
            "strategy"
        ] = "physical_segment_hybrid_swept_tetra_v1"

        def validate_with(candidate: dict) -> dict:
            with (
                mock.patch(
                    "common.multipole.resource_budget._load",
                    return_value=candidate,
                ),
                mock.patch(
                    "common.multipole.resource_budget.resolve_runtime_profile",
                    return_value=hybrid_runtime,
                ),
            ):
                return validate_pilot_budget(
                    repo_root=REPO_ROOT,
                    budget_path=budget_path,
                    project_id=HEX,
                    solver="comsol",
                    runtime_profile_id=runtime_profile_id,
                    design_profile_id=runtime["design_profile_id"],
                    particle_source_path=Path(runtime["particle_source"]["path"]),
                    retention_class="compact",
                )

        resolved = validate_with(authorized_fixture)
        self.assertEqual(resolved["limits"]["maximum_mesh_cells"], 100)
        self.assertEqual(resolved["stop_stage"], runtime["stop_stage"])
        runtime_without_stop_stage = json.loads(json.dumps(runtime))
        del runtime_without_stop_stage["stop_stage"]
        with (
            mock.patch(
                "common.multipole.resource_budget.resolve_runtime_profile",
                return_value=runtime_without_stop_stage,
            ),
            mock.patch(
                "common.multipole.resource_budget._load",
                return_value=authorized_fixture,
            ),
            self.assertRaisesRegex(ValueError, "stop stage is missing or unsupported"),
        ):
            validate_pilot_budget(
                repo_root=REPO_ROOT,
                budget_path=budget_path,
                project_id=HEX,
                solver="comsol",
                runtime_profile_id=runtime_profile_id,
                design_profile_id=runtime["design_profile_id"],
                particle_source_path=Path(runtime["particle_source"]["path"]),
                retention_class="compact",
            )
        legacy_budget = json.loads(json.dumps(authorized_fixture))
        del legacy_budget["pilot_authorization"]["limits"]["maximum_mesh_cells"]
        self.assertNotIn("maximum_mesh_cells", validate_with(legacy_budget)["limits"])
        for invalid in (True, 0, -1, 1.5, "3000000"):
            with self.subTest(invalid=invalid):
                invalid_budget = json.loads(json.dumps(authorized_fixture))
                invalid_budget["pilot_authorization"]["limits"][
                    "maximum_mesh_cells"
                ] = invalid
                with self.assertRaisesRegex(ValueError, "positive integers"):
                    validate_with(invalid_budget)
        invalid_identity = json.loads(json.dumps(authorized_fixture))
        invalid_identity["pilot_authorization"]["scope"][
            "expected_run_parent_resolved_design_sha256"
        ] = "not-a-sha"
        with self.assertRaisesRegex(ValueError, "must be uppercase SHA-256"):
            validate_with(invalid_identity)

    def test_optional_authorized_run_id_is_exact_and_legacy_compatible(self) -> None:
        budget_path = (
            REPO_ROOT
            / "projects"
            / HEX
            / "config"
            / "qualification"
            / "engineering_budget.json"
        )
        fixture = json.loads(budget_path.read_text(encoding="utf-8"))
        runtime_profile_id = fixture["pilot_authorization"]["scope"][
            "runtime_profile_id"
        ]
        runtime = resolve_runtime_profile(REPO_ROOT, HEX, runtime_profile_id)
        fixture["pilot_authorization"]["authorized"] = True
        fixture["pilot_authorization"]["scope"]["stop_stage"] = runtime["stop_stage"]
        authorized_run_id = "20260731_010203__sim__simion__authorized-run"
        fixture["pilot_authorization"]["scope"][
            "authorized_run_id"
        ] = authorized_run_id

        def validate_with(candidate: dict, run_id: str | None) -> dict:
            with mock.patch(
                "common.multipole.resource_budget._load",
                return_value=candidate,
            ):
                return validate_pilot_budget(
                    repo_root=REPO_ROOT,
                    budget_path=budget_path,
                    project_id=HEX,
                    solver="comsol",
                    runtime_profile_id=runtime_profile_id,
                    design_profile_id=runtime["design_profile_id"],
                    particle_source_path=Path(runtime["particle_source"]["path"]),
                    retention_class="compact",
                    run_id=run_id,
                )

        resolved = validate_with(fixture, authorized_run_id)
        self.assertEqual(resolved["authorized_run_id"], authorized_run_id)
        with self.assertRaisesRegex(ValueError, "differs from authorized_run_id"):
            validate_with(fixture, authorized_run_id + "__r02")
        self.assertEqual(
            validate_with(fixture, None)["authorized_run_id"],
            authorized_run_id,
        )
        legacy = json.loads(json.dumps(fixture))
        del legacy["pilot_authorization"]["scope"]["authorized_run_id"]
        self.assertIsNone(validate_with(legacy, authorized_run_id)["authorized_run_id"])

    def test_simion_pa_grid_limit_is_optional_solver_specific_and_positive(
        self,
    ) -> None:
        budget_path = (
            REPO_ROOT
            / "projects"
            / HEX
            / "config"
            / "qualification"
            / "engineering_budget.json"
        )
        fixture = json.loads(budget_path.read_text(encoding="utf-8"))
        runtime_profile_id = fixture["pilot_authorization"]["scope"][
            "runtime_profile_id"
        ]
        runtime = resolve_runtime_profile(REPO_ROOT, HEX, runtime_profile_id)
        fixture["pilot_authorization"]["authorized"] = True
        fixture["pilot_authorization"]["scope"]["stop_stage"] = runtime["stop_stage"]
        fixture["pilot_authorization"]["scope"]["allowed_solvers"] = [
            "comsol",
            "simion",
        ]
        limits = fixture["pilot_authorization"]["limits"]
        limits.pop("maximum_mesh_cells", None)
        limits["maximum_pa_grid_points"] = 20_000_000

        def validate_with(candidate: dict, solver: str = "simion") -> dict:
            with mock.patch(
                "common.multipole.resource_budget._load",
                return_value=candidate,
            ):
                return validate_pilot_budget(
                    repo_root=REPO_ROOT,
                    budget_path=budget_path,
                    project_id=HEX,
                    solver=solver,
                    runtime_profile_id=runtime_profile_id,
                    design_profile_id=runtime["design_profile_id"],
                    particle_source_path=Path(runtime["particle_source"]["path"]),
                    retention_class="compact",
                )

        resolved = validate_with(fixture)
        self.assertEqual(resolved["limits"]["maximum_pa_grid_points"], 20_000_000)
        legacy = json.loads(json.dumps(fixture))
        del legacy["pilot_authorization"]["limits"]["maximum_pa_grid_points"]
        self.assertNotIn("maximum_pa_grid_points", validate_with(legacy)["limits"])
        with self.assertRaisesRegex(ValueError, "only valid for SIMION"):
            validate_with(fixture, solver="comsol")
        for invalid in (True, 0, -1, 1.5, "20000000"):
            with self.subTest(invalid=invalid):
                invalid_budget = json.loads(json.dumps(fixture))
                invalid_budget["pilot_authorization"]["limits"][
                    "maximum_pa_grid_points"
                ] = invalid
                with self.assertRaisesRegex(ValueError, "positive integers"):
                    validate_with(invalid_budget)

    def test_mesh_build_report_enforces_declared_cell_limit(self) -> None:
        runner = (
            REPO_ROOT / "common/multipole/finite_3d_transport_preflight.ps1"
        ).read_text(encoding="utf-8")
        start = runner.index("function Assert-MultipoleMeshBuildReport")
        end = runner.index("\nfunction Assert-MultipoleFieldSolveReport", start)
        assertion_function = runner[start:end]
        required_lines = [
            "STOP_STAGE=mesh_build",
            "FIELD_PHYSICS_CREATED=0",
            "FIELD_STUDIES_CREATED=0",
            "FIELD_SOLUTIONS_CREATED=0",
            "PARTICLE_PHYSICS_CREATED=0",
            "PARTICLE_STUDIES_CREATED=0",
            "MESH_FEATURE_ROD_BOUNDARY_SIZE_PRESENT=1",
            "MESH_SWEPT_TETRAHEDRAL_OVERLAP_DOMAIN_COUNT=0",
            "MESH_VACUUM_UNCOVERED_DOMAIN_COUNT=0",
            "MESH_NONVACUUM_PARTITION_DOMAIN_COUNT=0",
            "MESH_VACUUM_VOLUME_STATUS=MEASURED",
            "MESH_BUILD_DIAGNOSTIC=PASS",
            "STATUS=PASS",
            "MESH_VACUUM_SELECTION_ENTITY_COUNT=1",
            "MESH_VACUUM_VOLUME_MM3=1",
            "MESH_VACUUM_MIN_QUALITY=0.5",
        ]
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "mesh_report.txt"

            def run_assertion(
                element_value: str | None,
                *,
                report_present: bool = True,
            ) -> subprocess.CompletedProcess[str]:
                report_path = (
                    report
                    if report_present
                    else Path(directory) / "missing_mesh_report.txt"
                )
                if report_present:
                    lines = required_lines.copy()
                    if element_value is not None:
                        lines.append(f"MESH_GLOBAL_ELEMENTS={element_value}")
                    report_path.write_text(
                        "\n".join(lines) + "\n",
                        encoding="utf-8",
                    )
                escaped_path = str(report_path).replace("'", "''")
                command = (
                    f"{assertion_function}\n"
                    f"$cells=Assert-MultipoleMeshBuildReport -Path '{escaped_path}' "
                    "-MaximumMeshCells 100;"
                    'Write-Output "MESH_CELLS=$cells"'
                )
                return subprocess.run(
                    ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                    cwd=REPO_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=20,
                )

            accepted = run_assertion("100")
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertIn("MESH_CELLS=100", accepted.stdout)
            for element_value, report_present, expected in (
                (None, False, "mesh-build report is missing"),
                (None, True, "exactly one MESH_GLOBAL_ELEMENTS"),
                ("100.0", True, "invalid positive-integer"),
                ("101", True, "cell budget exceeded"),
            ):
                with self.subTest(
                    element_value=element_value,
                    report_present=report_present,
                ):
                    rejected = run_assertion(
                        element_value,
                        report_present=report_present,
                    )
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertIn(expected, rejected.stdout + rejected.stderr)

    def test_field_solve_report_requires_complete_fields_and_no_particles(self) -> None:
        runner = (
            REPO_ROOT / "common/multipole/finite_3d_transport_preflight.ps1"
        ).read_text(encoding="utf-8")
        start = runner.index("function Assert-MultipoleFieldSolveReport")
        end = len(runner)
        assertion_function = runner[start:end]
        required_lines = [
            "CHECKPOINT=STATIONARY_FIELDS_COMPLETE",
            "STOP_STAGE=field_solve",
            "STATIONARY_LINEAR_SOLVER_BACKEND=PARDISO",
            "ELECTRIC_POTENTIAL_ELEMENT_ORDER=QUADRATIC",
            "STATIONARY_CONTROL=NOT_APPLICABLE",
            "STATIONARY_RELATIVE_TOLERANCE=NOT_APPLICABLE",
            "STATIONARY_FULLY_COUPLED_LINEAR_SOLVER=DDEF",
            "STATIONARY_MAX_LINEAR_ITERATIONS=NOT_APPLICABLE",
            "STATIONARY_LINEAR_ERROR_CHECK=NOT_APPLICABLE",
            "STATIONARY_CONVERGENCE_LOG=NOT_APPLICABLE",
            "FIELD_PHYSICS_CREATED=1",
            "FIELD_STUDIES_CREATED=2",
            "FIELD_SOLUTIONS_CREATED=2",
            "PARTICLE_PHYSICS_CREATED=0",
            "PARTICLE_STUDIES_CREATED=0",
            "DIFFERENTIAL_FIELD_DOF=100",
            "DIFFERENTIAL_FIELD_ITERATIONS=UNKNOWN",
            "DIFFERENTIAL_FIELD_FINAL_RESIDUAL=UNKNOWN",
            "DIFFERENTIAL_FIELD_SOLVER_EVIDENCE_SOURCE=NOT_APPLICABLE_DIRECT_SOLVER",
            "STATIC_FIELD_DOF=100",
            "STATIC_FIELD_ITERATIONS=UNKNOWN",
            "STATIC_FIELD_FINAL_RESIDUAL=UNKNOWN",
            "STATIC_FIELD_SOLVER_EVIDENCE_SOURCE=NOT_APPLICABLE_DIRECT_SOLVER",
            "FIELD_SOLVE_DIAGNOSTIC=PASS",
            "STATUS=PASS",
        ]
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "field_report.txt"

            def run_assertion(lines: list[str]) -> subprocess.CompletedProcess[str]:
                report.write_text("\n".join(lines) + "\n", encoding="utf-8")
                escaped_path = str(report).replace("'", "''")
                command = (
                    f"{assertion_function}\n"
                    f"$result=Assert-MultipoleFieldSolveReport -Path '{escaped_path}';"
                    'Write-Output "BACKEND=$($result.stationary_linear_solver_backend) '
                    'CONTROL=$($result.stationary_solver_configuration.control)"'
                )
                return subprocess.run(
                    ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                    cwd=REPO_ROOT,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=20,
                )

            accepted = run_assertion(required_lines)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertIn("BACKEND=pardiso CONTROL=not_applicable", accepted.stdout)
            cg_lines = [
                (
                    "STATIONARY_LINEAR_SOLVER_BACKEND=CG_AMG"
                    if line == "STATIONARY_LINEAR_SOLVER_BACKEND=PARDISO"
                    else "STATIONARY_CONTROL=USER"
                    if line == "STATIONARY_CONTROL=NOT_APPLICABLE"
                    else "STATIONARY_RELATIVE_TOLERANCE=0.001"
                    if line == "STATIONARY_RELATIVE_TOLERANCE=NOT_APPLICABLE"
                    else "STATIONARY_FULLY_COUPLED_LINEAR_SOLVER=I1"
                    if line == "STATIONARY_FULLY_COUPLED_LINEAR_SOLVER=DDEF"
                    else "STATIONARY_MAX_LINEAR_ITERATIONS=500"
                    if line == "STATIONARY_MAX_LINEAR_ITERATIONS=NOT_APPLICABLE"
                    else "STATIONARY_LINEAR_ERROR_CHECK=ON"
                    if line == "STATIONARY_LINEAR_ERROR_CHECK=NOT_APPLICABLE"
                    else "STATIONARY_CONVERGENCE_LOG=DETAILED"
                    if line == "STATIONARY_CONVERGENCE_LOG=NOT_APPLICABLE"
                    else "DIFFERENTIAL_FIELD_ITERATIONS=12"
                    if line == "DIFFERENTIAL_FIELD_ITERATIONS=UNKNOWN"
                    else "DIFFERENTIAL_FIELD_FINAL_RESIDUAL=1e-8"
                    if line == "DIFFERENTIAL_FIELD_FINAL_RESIDUAL=UNKNOWN"
                    else "DIFFERENTIAL_FIELD_SOLVER_EVIDENCE_SOURCE=COMSOL_PROGRESS_LINIT_LINRES"
                    if line
                    == "DIFFERENTIAL_FIELD_SOLVER_EVIDENCE_SOURCE=NOT_APPLICABLE_DIRECT_SOLVER"
                    else "STATIC_FIELD_ITERATIONS=9"
                    if line == "STATIC_FIELD_ITERATIONS=UNKNOWN"
                    else "STATIC_FIELD_FINAL_RESIDUAL=2e-8"
                    if line == "STATIC_FIELD_FINAL_RESIDUAL=UNKNOWN"
                    else "STATIC_FIELD_SOLVER_EVIDENCE_SOURCE=COMSOL_PROGRESS_LINIT_LINRES"
                    if line
                    == "STATIC_FIELD_SOLVER_EVIDENCE_SOURCE=NOT_APPLICABLE_DIRECT_SOLVER"
                    else line
                )
                for line in required_lines
            ]
            accepted_cg = run_assertion(cg_lines)
            self.assertEqual(accepted_cg.returncode, 0, accepted_cg.stderr)
            self.assertIn("BACKEND=cg_amg CONTROL=user", accepted_cg.stdout)
            invalid_cases = (
                (
                    [
                        line
                        for line in required_lines
                        if line != "PARTICLE_PHYSICS_CREATED=0"
                    ]
                    + ["PARTICLE_PHYSICS_CREATED=1"],
                    "PARTICLE_PHYSICS_CREATED=0",
                ),
                (
                    [
                        line
                        for line in required_lines
                        if line != "STATIC_FIELD_DOF=100"
                    ],
                    "incomplete field-DOF identity",
                ),
                (
                    [
                        "STATIONARY_LINEAR_SOLVER_BACKEND=ITERATIVE"
                        if line == "STATIONARY_LINEAR_SOLVER_BACKEND=PARDISO"
                        else line
                        for line in required_lines
                    ],
                    "invalid stationary solver backend",
                ),
                (
                    [
                        line
                        for line in required_lines
                        if line != "ELECTRIC_POTENTIAL_ELEMENT_ORDER=QUADRATIC"
                    ],
                    "invalid electric-potential element order",
                ),
                (
                    [
                        "DIFFERENTIAL_FIELD_ITERATIONS=0"
                        if line == "DIFFERENTIAL_FIELD_ITERATIONS=12"
                        else line
                        for line in cg_lines
                    ],
                    "lacks positive DIFFERENTIAL_FIELD LinIt/LinRes evidence",
                ),
            )
            for lines, expected in invalid_cases:
                with self.subTest(expected=expected):
                    rejected = run_assertion(lines)
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertIn(expected, rejected.stdout + rejected.stderr)

    def test_observer_does_not_interrupt_a_healthy_child_on_wall_clock_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            budget = root / "budget.json"
            usage = root / "usage.json"
            budget.write_text(
                json.dumps(
                    {
                        "limits": {
                            "wall_clock_seconds": 1,
                            "transient_run_directory_bytes": 1024**3,
                            "process_tree_working_set_bytes": 1024**3,
                            "minimum_system_available_memory_bytes": 1,
                            "compact_final_retained_bytes": 1024**2,
                            "automatic_retry_count": 0,
                        }
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/multipole/resource_budget_support.ps1"
            command = (
                f". '{support}';"
                f"$r=Invoke-ResourceBudgetedProcess -ResolvedBudgetPath '{budget}' "
                f"-RunDir '{root}' -UsagePath '{usage}' -FilePath (Get-Process -Id $PID).Path "
                "-ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 5');"
                "if($r.resource_budget_exceeded-or$r.exit_code-ne0){exit 3}"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            measured = json.loads(usage.read_text(encoding="utf-8-sig"))
            self.assertEqual(measured["status"], "running")
            self.assertIsNone(measured["limit_name"])

    def test_single_process_waits_for_verified_live_root_when_tree_sample_is_empty(
        self,
    ) -> None:
        """A transient empty tree observation cannot release a live solver's staging area."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            budget = root / "budget.json"
            usage = root / "usage.json"
            budget.write_text(
                json.dumps(
                    {
                        "limits": {
                            "wall_clock_seconds": 10,
                            "transient_run_directory_bytes": 1024**3,
                            "process_tree_working_set_bytes": 1024**3,
                            "minimum_system_available_memory_bytes": 1,
                            "compact_final_retained_bytes": 1024**2,
                            "automatic_retry_count": 0,
                        }
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/multipole/resource_budget_support.ps1"
            command = (
                f". '{support}';"
                "function Get-ManagedSolverProcessSample {"
                "param([int[]]$RootProcessIds,[int[]]$TrackedProcessIds,"
                "[hashtable]$RootProcessStartedAtUtcTicks,[hashtable]$TrackedProcessStartedAtUtcTicks);"
                "[pscustomobject]@{tracked_process_ids=@($RootProcessIds);"
                "active_process_ids=@();working_set_bytes=0;private_bytes=0;"
                "managed_memory_bytes=0;total_processor_time_ticks=0}"
                "};"
                f"$started=[Diagnostics.Stopwatch]::StartNew();$r=Invoke-ResourceBudgetedProcess "
                f"-ResolvedBudgetPath '{budget}' -RunDir '{root}' -UsagePath '{usage}' "
                "-FilePath (Get-Process -Id $PID).Path "
                "-ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 2');"
                "$started.Stop();if($r.resource_budget_exceeded-or$r.exit_code-ne0-or"
                "$started.Elapsed.TotalSeconds-lt1.5){exit 3}"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            measured = json.loads(usage.read_text(encoding="utf-8-sig"))
            self.assertGreaterEqual(measured["wall_clock_seconds"], 1.5)

    def test_parallel_wave_tracks_worker_after_short_lived_launcher_exits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            budget = root / "budget.json"
            dispatch = root / "dispatch.json"
            usage = root / "usage.json"
            stdout = root / "stdout.log"
            stderr = root / "stderr.log"
            budget.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "role": "multipole_engineering_budget",
                        "limits": {
                            "wall_clock_seconds": 60,
                            "transient_run_directory_bytes": 1_000_000_000,
                            "process_tree_working_set_bytes": 1_000_000_000,
                            "minimum_system_available_memory_bytes": 1,
                            "compact_final_retained_bytes": 1_000_000_000,
                            "automatic_retry_count": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            dispatch.write_text(json.dumps({
                "role": "simion_repository_dispatch_plan",
                "particle_count": 1,
                "estimation": {"kind": "exact_resource_profile"},
                "limits": {
                    "maximum_concurrency": 1, "launch_stagger_seconds": 5,
                    "memory_critical_seconds": 15,
                    "memory_recovery_stable_seconds": 45,
                    "maximum_memory_recovery_attempts": 2,
                    "maximum_memory_danger_termination_attempts": 2,
                    "memory_admission_reserve_bytes": 1024**3,
                    "memory_critical_reserve_bytes": 512 * 1024**2,
                    "cpu_admission_percent": 95.0,
                },
            }), encoding="utf-8")
            support = REPO_ROOT / "common/multipole/resource_budget_support.ps1"
            command = (
                f". '{support}';"
                "$child=(Get-Process -Id $PID).Path;"
                "$spec=[pscustomobject]@{name='launcher';file_path=$child;"
                "argument_list=@('-NoProfile','-Command',"
                "'Start-Process -FilePath $env:ComSpec "
                "-ArgumentList @(''/c'',''timeout /t 2 /nobreak >nul'') "
                "-WindowStyle Hidden');"
                f"stdout='{stdout}';stderr='{stderr}';environment=@{{}};working_directory='{root}'}};"
                f"$r=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' "
                f"-RunDir '{root}' -UsagePath '{usage}' "
                "-ProcessSpecifications @($spec);"
                "if($r.resource_budget_exceeded-or$r.processes[0].exit_code-ne0){exit 3}"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT,
                check=False,
                # The test deliberately launches a descendant which outlives
                # its PowerShell launcher.  Captured anonymous pipes would be
                # inherited by that descendant and make ``communicate`` wait
                # for a handle that is unrelated to the tested scheduler
                # completion condition.
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
            self.assertEqual(completed.returncode, 0)
            measured = json.loads(usage.read_text(encoding="utf-8-sig"))
            self.assertEqual(measured["status"], "running")
            self.assertGreaterEqual(measured["wall_clock_seconds"], 1.5)
            self.assertGreater(measured["peak_process_tree_working_set_bytes"], 0)

    def test_parallel_wave_finishes_after_direct_simion_root_exits(self) -> None:
        """A stale helper sample cannot strand a completed direct SIMION batch."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch = root / "dispatch.json"
            usage = root / "usage.json"
            dispatch.write_text(json.dumps({
                "role": "simion_repository_dispatch_plan",
                "particle_count": 1,
                "estimation": {"kind": "exact_resource_profile"},
                "limits": {
                    "maximum_concurrency": 1, "launch_stagger_seconds": 5,
                    "memory_critical_seconds": 15,
                    "memory_recovery_stable_seconds": 45,
                    "maximum_memory_recovery_attempts": 2,
                    "maximum_memory_danger_termination_attempts": 2,
                    "memory_admission_reserve_bytes": 1024**3,
                    "memory_critical_reserve_bytes": 512 * 1024**2,
                    "cpu_admission_percent": 95.0,
                },
            }), encoding="utf-8")
            support = REPO_ROOT / "common/multipole/resource_budget_support.ps1"
            command = (
                f". '{support}';"
                "function Start-RepositoryScheduledProcess {param($Specification);"
                "$p=Start-Process -FilePath (Get-Process -Id $PID).Path "
                "-ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 1') -PassThru;"
                "[pscustomobject]@{name='direct_simion';specification=$Specification;process=$p;"
                "root_process_id=$p.Id;root_process_started_at_utc_ticks=[int64]$p.StartTime.ToUniversalTime().Ticks;"
                "started_at=(Get-RepositoryUtcNow);tracked_process_ids=@($p.Id);"
                "tracked_process_started_at_utc_ticks=@{([string]$p.Id)=[int64]$p.StartTime.ToUniversalTime().Ticks};"
                "active=$true;completed=$false;exit_code=$null;peak_working_set_bytes=[int64]0;"
                "peak_managed_memory_bytes=[int64]0;pressure_terminated=$false};"
                "};"
                "function Get-ManagedSolverProcessSample {param([int[]]$RootProcessIds);"
                "[pscustomobject]@{tracked_process_ids=@($RootProcessIds);active_process_ids=@($RootProcessIds);"
                "tracked_process_started_at_utc_ticks=@{};working_set_bytes=0;private_bytes=0;"
                "managed_memory_bytes=0;total_processor_time_ticks=0};"
                "};"
                "$spec=[pscustomobject]@{name='direct_simion';file_path='C:\\SIMION\\simion.exe';"
                "argument_list=@();stdout='';stderr='';environment=@{};working_directory=''};"
                f"$r=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' -RunDir '{root}' "
                f"-UsagePath '{usage}' -ProcessSpecifications @($spec);"
                "if($r.resource_budget_exceeded-or$r.processes.Count-ne1-or$r.processes[0].exit_code-ne0){exit 3}"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("SIMION_RESOURCE_EVENT=BATCH_WAVE_COMPLETED", completed.stdout)

    def test_watchdog_samples_run_directory_on_frozen_cadence_and_at_exit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            budget = root / "budget.json"
            usage = root / "usage.json"
            budget.write_text(
                json.dumps(
                    {
                        "limits": {
                            "wall_clock_seconds": 10,
                            "transient_run_directory_bytes": 1024,
                            "transient_run_directory_sample_interval_seconds": 10,
                            "process_tree_working_set_bytes": 1024**3,
                            "minimum_system_available_memory_bytes": 1,
                            "compact_final_retained_bytes": 1024**2,
                            "automatic_retry_count": 0,
                        }
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/multipole/resource_budget_support.ps1"
            command = (
                f". '{support}';"
                "$script:directoryMeasurements=0;"
                "function Get-RunDirectoryBytes {"
                "param([string]$RunDir);$script:directoryMeasurements+=1;"
                "if($script:directoryMeasurements-eq 1){return 0};return 2048};"
                f"$r=Invoke-ResourceBudgetedProcess -ResolvedBudgetPath '{budget}' "
                f"-RunDir '{root}' -UsagePath '{usage}' "
                "-FilePath (Get-Process -Id $PID).Path "
                "-ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 1');"
                "if($r.resource_budget_exceeded-or$r.exit_code-ne0-or"
                "$null-ne$r.limit_name-or"
                "$script:directoryMeasurements-ne 2){exit 3}"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            measured = json.loads(usage.read_text(encoding="utf-8-sig"))
            self.assertEqual(measured["status"], "running")
            self.assertIsNone(measured["limit_name"])
            self.assertEqual(measured["peak_run_directory_bytes"], 2048)
            self.assertEqual(
                measured["warning_names"], ["transient_run_directory_bytes"]
            )

    def test_common_runners_reject_free_numerics_before_run_package(self) -> None:
        project = REPO_ROOT / "projects" / QUAD
        source = REPO_ROOT / (
            "common/multipole/sources/rf_multipole_family_mother_sample_v1_100.csv"
        )
        budget = project / "config/family_experiment/engineering_budget.json"
        cases = (
            (
                "run_finite_3d_transport.ps1",
                [
                    "-WorkingRegionMaximumElementSizeMm",
                    "0.4",
                    "-MeshAutoLevel",
                    "6",
                    "-RfStepsPerPeriod",
                    "80",
                    "-MaximumTimeUs",
                    "80",
                ],
            ),
            (
                "run_simion_finite_3d_transport.ps1",
                [
                    "-CellMm",
                    "0.15",
                    "-TrajectoryQuality",
                    "10",
                    "-RfStepsPerPeriod",
                    "40",
                    "-MaximumTimeUs",
                    "80",
                    "-SimionExe",
                    str(Path(shutil.which("pwsh") or "pwsh.exe").resolve()),
                ],
            ),
        )
        for index, (name, extra) in enumerate(cases, start=1):
            run_id = f"20260728_23590{index}__test__cross__budget-reject__n100"
            command = [
                "pwsh",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(REPO_ROOT / "common/multipole" / name),
                "-ProjectId",
                QUAD,
                "-RuntimeProfileId",
                "no_acceleration_full_length_n100_temporal_refined",
                "-DesignProfileId",
                "no_acceleration_full_length",
                "-ParticleSourcePath",
                str(source),
                "-EngineeringBudgetPath",
                str(budget),
                "-RunId",
                run_id,
                "-PythonExe",
                sys.executable,
                *extra,
            ]
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "not authorized",
                completed.stdout + completed.stderr,
            )
            run_dir = (
                REPO_ROOT.parent
                / "artifacts/projects"
                / QUAD
                / "runs"
                / run_id
            )
            self.assertFalse(run_dir.exists(), "rejected numerics created a run package")


if __name__ == "__main__":
    unittest.main()
