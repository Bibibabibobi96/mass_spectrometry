from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from projects.rf_multipole_ion_optics.runtime.resource_budget import validate_pilot_budget, validate_analysis_budget, validate_resource_limits
from projects.rf_multipole_ion_optics.tests.analysis.test_comsol_analysis_recovery import engineering_budget
from projects.rf_multipole_ion_optics.runtime.runtime_profile import resolve_runtime_profile

REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ID = "rf_multipole_ion_optics"

# Process/memory fixtures isolate the host permit; facade tests exercise its ledger.
HOST_PERMIT_FIXTURE = "function Assert-HostResourceHeavyStage {};"


def dispatch_limits(**overrides: int | float) -> dict[str, int | float]:
    """Deterministic process fixtures; production defaults belong to the policy."""
    return {
        "maximum_concurrency": 2,
        "launch_stagger_seconds": 5,
        "memory_critical_seconds": 15,
        "memory_recovery_stable_seconds": 45,
        "maximum_memory_recovery_attempts": 2,
        "maximum_memory_danger_termination_attempts": 2,
        "memory_admission_reserve_bytes": 1024**3,
        "memory_critical_reserve_bytes": 512 * 1024**2,
        "cpu_admission_percent": 95.0,
        "minimum_process_cpu_percent": 6.25,
        **overrides,
    }


def _admission_pause_barrier(root: Path, reason: str, *, memory_pressure: bool = False) -> str:
    """Release real fixture children after the scheduler observes the tested pause."""
    worker = root / "barrier_worker.ps1"
    worker.write_text(r"""param([string]$ReleasePath)
$ErrorActionPreference='Stop'
Write-Output "BARRIER_CHILD_PID=$PID"
$deadline=[DateTime]::UtcNow.AddSeconds(15)
while(-not(Test-Path -LiteralPath $ReleasePath)-and[DateTime]::UtcNow-lt$deadline){
 Start-Sleep -Milliseconds 20
}
if(-not(Test-Path -LiteralPath $ReleasePath)){exit 9}
Write-Output 'BARRIER_RELEASED_NATURALLY'
exit 0
""", encoding="utf-8")
    release = str(root / "admission_observed.txt").replace("'", "''")
    pressure = "$script:memoryPhase='waiting';" if memory_pressure else ""
    after_start = "if($Event-eq'BATCH_STARTED'){$script:memoryPhase='pressured'};" if memory_pressure else ""
    after_pause = "$script:memoryPhase='released';" if memory_pressure else ""
    return (pressure +
            "$script:originalSchedulerEvent=${function:Write-RepositorySchedulerEvent};"
            "function Write-RepositorySchedulerEvent {"
            "[CmdletBinding()]param([Parameter(Mandatory)][string]$Event,$Record=$null,"
            "[int]$ActiveCount=-1,[int]$PendingCount=-1,[hashtable]$Details=@{});"
            "& $script:originalSchedulerEvent @PSBoundParameters;" + after_start +
            f"if($Event-eq'RESOURCE_ADMISSION_PAUSED'-and$Details.REASON-eq'{reason}'){{" + after_pause +
            f"Set-Content -LiteralPath '{release}' -Value 'observed'}}}};")



class AnalysisBudgetTests(unittest.TestCase):
    def arguments(self):
        parent = engineering_budget()
        config = dict(project=PROJECT_ID, parameters=dict(runtime_profile_id='frozen-runtime', design_profile_id='frozen-design'),
                      provenance=dict(parent_resolved_design_sha256='A'*64))
        return dict(parent_config=config, parent_budget=parent, source_metadata=dict(particle_count=1),
                    retention_class='compact', run_id='20261031_060001__analysis__python__csv-child')

    def test_old_one_particle_source_analysis_uses_only_frozen_scope_without_sampling_or_defaults(self):
        budget = engineering_budget(retention_class='compact', transient=33554432)
        with mock.patch('projects.rf_multipole_ion_optics.runtime.resource_budget.resolve_runtime_profile', side_effect=AssertionError('today profile')), \
             mock.patch('projects.rf_multipole_ion_optics.runtime.resource_budget.resolve_runtime_selection', side_effect=AssertionError('today campaign')), \
             mock.patch('projects.rf_multipole_ion_optics.runtime.resource_budget._particle_count', side_effect=AssertionError('rescan source')):
            value = validate_analysis_budget(budget, **self.arguments())
        self.assertEqual(value['limits']['transient_run_directory_bytes'], 33554432)
        self.assertEqual(value['limits']['automatic_retry_count'], 0)
        self.assertEqual(value['retention_class'], 'compact')

    def test_new_analysis_budget_cannot_change_frozen_science(self):
        for field, value in (('particle_count', 100), ('runtime_profile_id', 'today-default'), ('design_profile_id', 'other'),
                             ('particle_source_profile_id', 'new-source')):
            with self.subTest(field=field):
                budget = engineering_budget(retention_class='compact')
                budget['pilot_authorization']['scope'][field] = value
                with self.assertRaisesRegex(ValueError, 'frozen science'):
                    validate_analysis_budget(budget, **self.arguments())

    def test_analysis_campaign_scope_comes_from_frozen_experiment_not_current_profile(self):
        for kind in ('profile', 'inline'):
            with self.subTest(kind=kind):
                arguments = self.arguments()
                binding = dict(kind=kind, **({'profile_id': 'frozen-simion'} if kind == 'profile' else {'numerics_id': 'frozen-simion'}))
                arguments['parent_budget'] = dict(role='multipole_transport_experiment_campaign', experiments=[dict(
                    experiment_id='frozen-runtime', project_id=PROJECT_ID, stop_stage='transport',
                    design_profile_id='frozen-design', particle_source_profile_id='frozen-source',
                    comsol_solver_numerics_profile_id='frozen-comsol', simion_solver_numerics=binding,
                    solver='comsol', retention_class='solver_review')])
                with mock.patch('projects.rf_multipole_ion_optics.runtime.resource_budget.resolve_runtime_profile', side_effect=AssertionError('today profile')):
                    result = validate_analysis_budget(engineering_budget(retention_class='compact'), **arguments)
                self.assertEqual(result['runtime_profile_id'], 'frozen-runtime')

    def test_shared_numeric_retry_and_matrix_policy_applies_to_normal_and_analysis(self):
        for fault in ('negative', 'boolean', 'retry', 'matrix'):
            with self.subTest(fault=fault):
                budget = engineering_budget(retention_class='compact')
                limits = budget['pilot_authorization']['limits']
                if fault == 'negative':
                    limits['transient_run_directory_bytes'] = -1
                elif fault == 'boolean':
                    limits['process_tree_working_set_bytes'] = True
                elif fault == 'retry':
                    limits['automatic_retry_count'] = 1
                else:
                    budget['full_matrix_authorization']['authorized'] = True
                with self.assertRaises(ValueError):
                    validate_resource_limits(limits, budget['full_matrix_authorization'])
                with self.assertRaises(ValueError):
                    validate_analysis_budget(budget, **self.arguments())


class ResourceBudgetTests(unittest.TestCase):
    def test_frozen_runtime_budget_does_not_resolve_defaults_and_keeps_authorization(self) -> None:
        runtime = resolve_runtime_profile(REPO_ROOT, PROJECT_ID, "octupole_no_acceleration_full_length")
        runtime = json.loads(json.dumps(runtime))
        runtime["engineering_budget"]["inline_contract"]["pilot_authorization"]["authorized"] = True
        options = dict(repo_root=REPO_ROOT, budget_path=Path(runtime["engineering_budget"]["path"]),
            project_id=PROJECT_ID, solver="simion", runtime_profile_id=runtime["runtime_profile_id"],
            design_profile_id=runtime["design_profile_id"], particle_source_path=Path(runtime["particle_source"]["path"]),
            retention_class="compact", resolved_runtime=runtime)
        with mock.patch("projects.rf_multipole_ion_optics.runtime.resource_budget._load", side_effect=lambda _: runtime["engineering_budget"]["inline_contract"]), \
             mock.patch("projects.rf_multipole_ion_optics.runtime.resource_budget.resolve_runtime_profile", side_effect=AssertionError("re-resolved defaults")), \
             mock.patch("projects.rf_multipole_ion_optics.runtime.resource_budget.resolve_runtime_selection", side_effect=AssertionError("re-resolved campaign")):
            result = validate_pilot_budget(**options)
            self.assertEqual(result["solver_numerics"], runtime["solver_numerics"]["simion"]["values"])
            runtime["engineering_budget"]["inline_contract"]["pilot_authorization"]["authorized"] = False
            with self.assertRaisesRegex(ValueError, "not authorized"):
                validate_pilot_budget(**options)
            with self.assertRaisesRegex(ValueError, "runtime identity"):
                validate_pilot_budget(**dict(options, design_profile_id="other"))


    def test_release_budget_uses_authorized_declaration_without_sampling(self) -> None:
        runtime = resolve_runtime_profile(REPO_ROOT, PROJECT_ID, "octupole_no_acceleration_full_length")
        budget = json.loads(Path(runtime["engineering_budget"]["path"]).read_text(encoding="utf-8-sig"))
        runtime["particle_source"] = dict(
            profile_id="new_release",
            particle_count=100,
            release_spec=dict(path="frozen.json", bytes=1, sha256="A" * 64),
        )
        # Test-local validator fixture only; the production bare budget stays unauthorized.
        budget["pilot_authorization"]["authorized"] = True
        budget["pilot_authorization"]["scope"]["particle_source_profile_id"] = "new_release"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "budget.json"
            path.write_text(json.dumps(budget), encoding="utf-8")
            runtime["engineering_budget"]["path"] = str(path)
            options = dict(
                repo_root=REPO_ROOT,
                budget_path=path,
                project_id=PROJECT_ID,
                solver="simion",
                runtime_profile_id=runtime["runtime_profile_id"],
                design_profile_id=runtime["design_profile_id"],
                retention_class="compact",
            )
            with (
                mock.patch("projects.rf_multipole_ion_optics.runtime.resource_budget.resolve_runtime_profile", return_value=runtime),
                mock.patch(
                    "common.ion_release.mt19937_disk_cone_rf_phase.generate_mt19937_disk_cone_rf_phase_states",
                    side_effect=AssertionError("budget sampled"),
                ),
                mock.patch(
                    "projects.rf_multipole_ion_optics.runtime.resource_budget._particle_count",
                    side_effect=AssertionError("budget read nonexistent CSV"),
                ),
            ):
                value = validate_pilot_budget(**options)
                self.assertEqual(value["particle_source"], runtime["particle_source"])
                with self.assertRaisesRegex(ValueError, "external particle source"):
                    validate_pilot_budget(**options, particle_source_path=path)
                runtime["particle_source"]["particle_count"] = 99
                with self.assertRaisesRegex(ValueError, "authorized scope"):
                    validate_pilot_budget(**options)

    def test_live_launcher_rejects_invalid_frozen_effective_cpu_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for section, field in (
                ("limits", "minimum_process_cpu_budget_percent"),
                ("estimation", "per_process_cpu_budget_percent"),
            ):
                for budget in (0, "NaN"):
                    with self.subTest(section=section, budget=budget):
                        plan = dict(
                            role="simion_repository_dispatch_plan",
                            limits=dispatch_limits(),
                            estimation=dict(kind="exact_resource_profile"),
                        )
                        plan[section][field] = budget
                        dispatch = root / "dispatch.json"
                        dispatch.write_text(json.dumps(plan), encoding="utf-8")
                        support = REPO_ROOT / "common/resource_budget_support.ps1"
                        command = (
                            f". '{support}';"
                            "$record=[pscustomobject]@{name='completed';completed=$true;exit_code=0;"
                            "peak_working_set_bytes=0;peak_managed_memory_bytes=0};"
                            f"Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' "
                            f"-RunDir '{root}' -UsagePath '{root}/usage.json' -ExistingProcessRecords @($record)"
                        )
                        completed = subprocess.run(
                            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                            cwd=REPO_ROOT,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=10,
                            check=False,
                        )
                        self.assertNotEqual(completed.returncode, 0)
                        self.assertIn("must be finite and positive", completed.stderr)

    def test_live_cpu_admission_uses_frozen_margin_once_and_preserves_legacy_plan(self) -> None:
        """88.5+6.5625 waits; 88.4+6.5625 fits, without multiplying twice."""
        for effective in (None, 6.5625):
            with self.subTest(effective_budget=effective), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                estimation = dict(kind="exact_resource_profile", per_process_cpu_percent=6.25)
                limits = dispatch_limits(maximum_concurrency=1, launch_stagger_seconds=1)
                if effective is not None:
                    estimation.update(per_process_cpu_budget_percent=effective, cpu_demand_safety_factor=1.05)
                    limits.update(minimum_process_cpu_budget_percent=effective, cpu_demand_safety_factor=1.05)
                dispatch = root / "dispatch.json"
                dispatch.write_text(
                    json.dumps(dict(role="simion_repository_dispatch_plan", estimation=estimation, limits=limits)),
                    encoding="utf-8",
                )
                support = REPO_ROOT / "common/resource_budget_support.ps1"
                expected_sample = 1 if effective is None else 2
                command = (
                    f". '{support}';{HOST_PERMIT_FIXTURE}$script:cpuSamples=0;"
                    "function Get-RepositoryAvailableMemoryBytes {[int64](64GB)};"
                    "function Get-SystemCpuPercent {$script:cpuSamples++;"
                    "if($script:cpuSamples-eq1){88.5}elseif($script:cpuSamples-eq2){88.4}else{0.0}};"
                    "$script:originalStart=${function:Start-RepositoryScheduledProcess};"
                    "function Start-RepositoryScheduledProcess {param($Specification);"
                    "$script:cpuAtLaunch=$script:cpuSamples;& $script:originalStart -Specification $Specification};"
                    "$exe=(Get-Process -Id $PID).Path;"
                    "$spec=[pscustomobject]@{name='cpu-margin';file_path=$exe;"
                    "argument_list=@('-NoProfile','-Command','exit 0');"
                    f"stdout='{root}/child.out';stderr='{root}/child.err';"
                    f"environment=@{{}};working_directory='{root}'}};"
                    f"$result=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' "
                    f"-RunDir '{root}' -UsagePath '{root}/usage.json' -ProcessSpecifications @($spec);"
                    f"if($script:cpuAtLaunch-ne{expected_sample}){{throw ('wrong launch sample '+$script:cpuAtLaunch)}};"
                    "if($result.resource_budget_exceeded-or$result.processes[0].exit_code-ne0){exit 4}"
                )
                completed = subprocess.run(
                    ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                usage = json.loads((root / "usage.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(usage["scheduler_receipt"]["per_process_cpu_budget_percent"], effective or 6.25)
                pauses = usage["scheduler_receipt"]["launch_pause_events"]
                self.assertEqual(any(p["reason"] == "cpu_admission_exceeded" for p in pauses), effective is not None)

    def test_live_launcher_rejects_missing_or_invalid_cpu_floor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            for floor in (None, 0, 101):
                with self.subTest(cpu_floor=floor):
                    limits = dispatch_limits()
                    if floor is None:
                        limits.pop("minimum_process_cpu_percent")
                    else:
                        limits["minimum_process_cpu_percent"] = floor
                    dispatch = root / "dispatch.json"
                    dispatch.write_text(
                        json.dumps(
                            {
                                "role": "simion_repository_dispatch_plan",
                                "estimation": {"kind": "exact_resource_profile"},
                                "limits": limits,
                            }
                        ),
                        encoding="utf-8",
                    )
                    command = (
                        f". '{support}';"
                        "$record=[pscustomobject]@{name='completed';completed=$true;"
                        "exit_code=0;peak_working_set_bytes=0;peak_managed_memory_bytes=0};"
                        f"Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' "
                        f"-RunDir '{root}' -UsagePath '{root}/usage.json' "
                        "-ExistingProcessRecords @($record)"
                    )
                    completed = subprocess.run(
                        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                        cwd=REPO_ROOT,
                        check=False,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=10,
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    expected = "require minimum_process_cpu_percent" if floor is None else "must be finite"
                    self.assertIn(expected, completed.stderr)

    def test_live_launcher_consumes_normalized_cpu_floor_and_keeps_cpu_ceiling(self) -> None:
        """A 16-core worker fits at 86%; an exact 95% projection must wait."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch, usage = root / "dispatch.json", root / "usage.json"
            dispatch.write_text(
                json.dumps(
                    {
                        "role": "simion_repository_dispatch_plan",
                        "estimation": {"kind": "exact_resource_profile", "per_process_cpu_percent": 6.2},
                        "limits": dispatch_limits(maximum_concurrency=1, launch_stagger_seconds=1),
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}$script:cpuSamples=0;"
                "function Get-RepositoryAvailableMemoryBytes {return [int64](64GB)};"
                "function Get-SystemCpuPercent {$script:cpuSamples+=1;"
                "if($script:cpuSamples-eq1){return [double]88.75};return [double]86};"
                "$exe=(Get-Process -Id $PID).Path;"
                f"$spec=[pscustomobject]@{{name='cpu-fixture';file_path=$exe;"
                "argument_list=@('-NoProfile','-Command','exit 0');"
                f"stdout='{root}/child.out';stderr='{root}/child.err';"
                f"environment=@{{}};working_directory='{root}'}};"
                f"$r=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' "
                f"-RunDir '{root}' -UsagePath '{usage}' -ProcessSpecifications @($spec);"
                "if($r.resource_budget_exceeded-or$script:cpuSamples-lt2){exit 3};"
                "if($r.processes.Count-ne1-or$r.processes[0].exit_code-ne0){exit 4}"
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
            receipt = json.loads(usage.read_text(encoding="utf-8-sig"))
            pauses = receipt["scheduler_receipt"]["launch_pause_events"]
            self.assertTrue(any(event["reason"] == "cpu_admission_exceeded" for event in pauses))

    def test_simion_formal_observation_resets_transient_critical_pressure(self) -> None:
        """Separated low samples never become one sustained danger interval."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch = root / "dispatch.json"
            dispatch.write_text(
                json.dumps(
                    {
                        "role": "simion_repository_dispatch_plan",
                        "estimation": {"kind": "formal_first_batch_observation"},
                        "limits": {
                            "formal_observation_seconds": 10,
                            "memory_policy": "warn_single_worker",
                            "memory_critical_reserve_bytes": 512 * 1024**2,
                            "memory_critical_seconds": 1,
                        },
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                "$script:memorySamples=0;function Get-RepositoryAvailableMemoryBytes {"
                "$script:memorySamples++;if($script:memorySamples-in@(1,3)){[int64](100MB)}else{[int64](8GB)}};"
                "function Get-SystemCpuPercent {0.0};"
                "function Stop-ManagedSolverProcesses {throw 'Warning killed observation'};"
                "$spec=[pscustomobject]@{name='formal';file_path=(Get-Process -Id $PID).Path;"
                "argument_list=@('-NoProfile','-Command','Start-Sleep -Seconds 5;exit 7');"
                f"stdout='{root / 'out'}';stderr='{root / 'err'}';environment=@{{}};working_directory='{root}'}};"
                f"$r=Start-ObservedFormalProcess -DispatchPlanPath '{dispatch}' -ProcessSpecification $spec;"
                "if(-not$r.completed_naturally-or$r.resource_budget_exceeded-or$r.exit_code-ne7){throw 'Lost real process result'};"
                "if(@($r.process_record.memory_warning_events).Count-ne2){throw 'Pressure interval was not reset'}"
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_simion_formal_observation_stops_only_owned_batch_on_sustained_danger(self) -> None:
        """Warning admission cannot disable the measured host-danger threshold."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch = root / "dispatch.json"
            dispatch.write_text(
                json.dumps(dict(
                    role="simion_repository_dispatch_plan",
                    estimation=dict(kind="formal_first_batch_observation"),
                    limits=dict(formal_observation_seconds=10, memory_policy="warn_single_worker",
                                memory_critical_reserve_bytes=512 * 1024**2, memory_critical_seconds=1),
                )), encoding="utf-8",
            )
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                "function Get-RepositoryAvailableMemoryBytes {[int64](100MB)};"
                "function Get-SystemCpuPercent {0.0};"
                "$script:stops=@();$script:originalStop=${function:Stop-ManagedSolverProcesses};"
                "function Stop-ManagedSolverProcesses {param([int[]]$ProcessIds);"
                "$script:stops+=,@($ProcessIds);&$script:originalStop -ProcessIds $ProcessIds};"
                "$script:started=$null;$script:originalStart=${function:Start-RepositoryScheduledProcess};"
                "function Start-RepositoryScheduledProcess {param($Specification);"
                "$script:started=&$script:originalStart -Specification $Specification;return $script:started};"
                "$spec=[pscustomobject]@{name='owned-formal';file_path=(Get-Process -Id $PID).Path;"
                "argument_list=@('-NoProfile','-Command','Start-Sleep -Seconds 30');"
                f"stdout='{root / 'out'}';stderr='{root / 'err'}';environment=@{{}};working_directory='{root}'}};"
                "try{"
                f"$r=Start-ObservedFormalProcess -DispatchPlanPath '{dispatch}' -ProcessSpecification $spec;"
                "if($r.completed_naturally-or-not$r.resource_budget_exceeded-or$null-ne$r.exit_code){throw 'Danger result lost'};"
                "if(-not$r.process_record.pressure_terminated-or$script:stops.Count-ne1){throw 'Danger stop missing/repeated'};"
                "if((($script:stops[0]|Sort-Object)-join',')-ne(($r.process_record.tracked_process_ids|Sort-Object)-join',')){throw 'Stopped another unit'};"
                "if($r.process_record.root_process_id-notin$script:stops[0]){throw 'Owned root not stopped'};"
                "if(@($r.process_record.memory_warning_events).Count-ne1){throw 'Warning missing/spam'}"
                "}finally{if($null-ne$script:started){"
                "Stop-Process -Id $script:started.root_process_id -Force -ErrorAction SilentlyContinue}};exit 0"
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command], cwd=REPO_ROOT,
                capture_output=True, text=True, encoding="utf-8", timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("MEMORY_DANGER_TERMINATION", result.stdout)

    def test_simion_warning_policy_runs_serially_under_memory_pressure(self) -> None:
        """Exercise admission and transient pressure with a deterministic clock."""
        for transient_critical in (False, True):
            with self.subTest(transient_critical=transient_critical), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                dispatch, usage = root / "dispatch.json", root / "usage.json"
                dispatch.write_text(
                    json.dumps(
                        {
                            "role": "simion_repository_dispatch_plan",
                            "estimation": {
                                "kind": "exact_resource_profile",
                                "per_process_memory_budget_bytes": 40 * 1024**3,
                                "memory_safety_factor": 1.0,
                            },
                            "limits": {
                                **dispatch_limits(),
                                "memory_policy": "warn_single_worker",
                                "memory_admission_reserve_bytes": 0,
                                "memory_critical_seconds": 1,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                support = REPO_ROOT / "common/resource_budget_support.ps1"
                memory_function = (
                    "$script:activeCriticalSamples=0;function Get-RepositoryAvailableMemoryBytes {"
                    "if($null-ne$script:firstWorkerAt){$elapsed=($script:now-$script:firstWorkerAt).TotalSeconds;"
                    "if($elapsed-ge0.5-and$elapsed-lt1){$script:activeCriticalSamples++;return [int64](100MB)}};"
                    "return [int64](1GB)};"
                    if transient_critical else
                    "function Get-RepositoryAvailableMemoryBytes {[int64](1GB)};"
                )
                # Real launch/ancestry/console behavior has separate tests below.
                # Here six-second workers outlive the five-second launch stagger,
                # so a wrongly admitted sibling would actually overlap.
                command = (
                    f". '{support}';{HOST_PERMIT_FIXTURE}"
                    "$script:now=[datetimeoffset]'2026-10-27T00:00:00Z';"
                    "$script:firstWorkerAt=$null;$script:workers=@{};$script:nextPid=100;$script:disposed=0;"
                    "function Get-RepositoryProcessSnapshot {};"
                    "function Get-CimInstance {throw 'Policy fixture queried host CIM'};"
                    "function Start-Process {throw 'Policy fixture launched a native worker'};"
                    "function Get-RepositoryUtcNow {$script:now};"
                    "function Start-Sleep {param([int]$Seconds=0,[int]$Milliseconds=0);"
                    "$script:now=$script:now.AddSeconds($Seconds+$Milliseconds/1000.0);"
                    "if($script:now-gt[datetimeoffset]'2026-10-27T00:00:30Z'){throw 'Policy did not finish'}};"
                    "$script:cpuSamples=0;function Get-SystemCpuPercent {"
                    "$script:cpuSamples++;if($script:cpuSamples-eq1){96.0}else{0.0}};"
                    f"{memory_function}"
                    "function Stop-ManagedSolverProcesses {throw 'Memory warning killed a worker'};"
                    "function Start-RepositoryScheduledProcess {param($Specification);$script:nextPid++;"
                    "if($null-eq$script:firstWorkerAt){$script:firstWorkerAt=$script:now};"
                    "$script:workers[$script:nextPid]=$script:now;"
                    "$process=[pscustomobject]@{ExitCode=0};$process|Add-Member ScriptMethod WaitForExit {};"
                    "$process|Add-Member ScriptMethod Dispose {$script:disposed++};"
                    "[pscustomobject]@{name=$Specification.name;specification=$Specification;process=$process;"
                    "root_process_id=$script:nextPid;tracked_process_ids=@($script:nextPid);started_at=$script:now;"
                    "active=$true;completed=$false;exit_code=$null;pressure_terminated=$false;"
                    "peak_working_set_bytes=[int64]0;peak_managed_memory_bytes=[int64]0}};"
                    "function Get-ManagedSolverProcessSample {param($RootProcessIds,$TrackedProcessIds);"
                    "$worker=$RootProcessIds[0];$active=@();"
                    "if(($script:now-$script:workers[$worker]).TotalSeconds-lt6){$active=@($worker)};"
                    "[pscustomobject]@{tracked_process_ids=@($worker);active_process_ids=$active;"
                    "working_set_bytes=[int64](1MB);managed_memory_bytes=[int64](1MB)}};"
                    "$specs=@('a','b'|ForEach-Object {[pscustomobject]@{name=$_;file_path='unused';argument_list=@();"
                    f"stdout='{root}\\$_.out';stderr='{root}\\$_.err';environment=@{{}};working_directory='{root}'}}}});"
                    f"$r=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' -RunDir '{root}' "
                    f"-UsagePath '{usage}' -ProcessSpecifications $specs;"
                    "if($r.resource_budget_exceeded-or$r.processes.Count-ne2){throw 'Incomplete wave'};"
                    f"$receipt=Get-Content -Raw '{usage}'|ConvertFrom-Json;"
                    "if($receipt.execution_wave.peak_concurrency-ne1){throw 'Over-admitted siblings'};"
                    "if($receipt.scheduler_receipt.memory_policy-ne'warn_single_worker'){throw 'Missing policy'};"
                    "if(@($receipt.scheduler_receipt.memory_warning_events).Count-ne1){throw 'Warning spam/missing warning'};"
                    "if(@($receipt.scheduler_receipt.launch_pause_events|Where-Object {$_.reason-eq'cpu_admission_exceeded'}).Count-lt1){throw 'CPU bypassed'};"
                    "if(@($r.processes|Where-Object {$_.exit_code-ne0}).Count){throw 'Process failed'};"
                    "if($script:disposed-ne2){throw 'Worker completion lost'};"
                    "if((@($r.processes.name|Sort-Object)-join',')-ne'a,b'){throw 'Work item identity lost'};"
                    "if(($script:workers[101]-[datetimeoffset]'2026-10-27T00:00:00Z').TotalSeconds-lt2){throw 'Launched before CPU resample'};"
                    "if(($script:workers[102]-$script:workers[101]).TotalSeconds-lt6){throw 'Overlapping warning workers'};"
                    + ("if($script:activeCriticalSamples-ne1){throw 'Active transient pressure not exercised'}" if transient_critical else "")
                )
                result = subprocess.run(
                    ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=60,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dispatch_limits_reject_invalid_values_before_launch(self) -> None:
        support = REPO_ROOT / "common/resource_budget_support.ps1"
        script = (
            f". '{support}';"
            + r"""
foreach($value in @($null,$true,'5',0,-1,1.5,[double]::NaN,[double]::PositiveInfinity)){
 $rejected=$false
 try{Assert-RepositoryDispatchLimits -Limits @{duration=$value} -PositiveIntegers duration}
 catch{$rejected=$true}
 if(-not$rejected){throw "Invalid limit accepted: $value"}
}
Assert-RepositoryDispatchLimits -Limits @{duration=7;bytes=[int64]3221225472} -PositiveIntegers duration,bytes
"""
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_single_simion_native_verbs_require_heavy_only_for_refine_and_fly(self) -> None:
        """Known construction steps reach launch under light; solving cannot."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            budget = root / "budget.json"
            budget.write_text(json.dumps({"limits": {}}), encoding="utf-8")
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            for verb in ("gem2pa", "lua", "refine", "fly"):
                with self.subTest(verb=verb):
                    expected = "fixture-permit-denied" if verb in {"refine", "fly"} else "fixture-reached-start"
                    command = (
                        f". '{support}';"
                        "function Assert-HostResourceHeavyStage {throw 'fixture-permit-denied'};"
                        "function Start-Process {throw 'fixture-reached-start'};"
                        "try {Invoke-ResourceBudgetedProcess "
                        f"-Limits ((Get-Content -LiteralPath '{budget}' -Raw|ConvertFrom-Json).limits) -RunDir '{root}' "
                        f"-UsagePath '{root / 'usage.json'}' -FilePath 'C:\\fixture\\simion.exe' "
                        f"-ArgumentList @('--nogui','--noprompt','{verb}','build_simion_runtime_iob.lua');exit 3}} catch {{"
                        f"if($_.Exception.Message-ne'{expected}'){{throw}}}};exit 0"
                    )
                    result = subprocess.run(
                        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                        cwd=REPO_ROOT,
                        capture_output=True,
                        timeout=15,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, repr(result.stdout) + repr(result.stderr))
                    self.assertFalse((root / "usage.json").exists())

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_comsol_parent_hands_owned_prepare_to_child_and_reacquires_postprocess(self) -> None:
        source = (REPO_ROOT / "projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1").read_text(encoding="utf-8")
        start = source.index("    if($hostExecutionLease.inherited){")
        end = source.index("    if($solverProcess.resource_budget_exceeded)", start)
        block = source[start:end]
        facade = REPO_ROOT / "common/host_execution_lease.ps1"
        for scenario in (
            "success",
            "child_failure",
            "failure_and_postprocess_denied",
            "inherited_light",
            "inherited_heavy",
        ):
            with self.subTest(scenario=scenario):
                script = (
                    f". '{facade}'\n$scenario='{scenario}'\n"
                    + r"""
Remove-Item Env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN -ErrorAction SilentlyContinue
$script:events=@();$script:counter=0
function Enter-HostExecutionLease {
 param($Role,$Stage,$RunId)
 if($Stage-eq'postprocess'-and$scenario-eq'failure_and_postprocess_denied'){throw 'postprocess-denied'}
 $budget=Get-HostResourceBudget -Role $Role -Stage $Stage
 $script:counter++;$token="fixture-$script:counter"
 $script:events+="enter:$Stage`:$($budget.heavy_stage)"
 $env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN=$token
 return @{token=$token;role=$Role;stage=$Stage;inherited=$false;heavy=$budget.heavy_stage}
}
function Exit-HostExecutionLease {
 param($Lease)
 if(-not$Lease.inherited){
   if($env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN-ne$Lease.token){throw 'wrong-token-released'}
   $script:events+="release:$($Lease.token)"
   Remove-Item Env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN
 }
}
function Assert-HostResourceHeavyStage {
 param($Lease)
 if(-not$Lease.heavy){throw 'inherited-light-denied'}
}
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$UsagePath,$FilePath,$ArgumentList)
 if($Limits.wall_clock_seconds-ne30){throw 'resolved-limits-not-forwarded'}
 $script:events+='child-start'
 if($scenario-eq'inherited_heavy'){
   if($env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN-ne'parent'){throw 'inherited-token-cleared'}
   return @{resource_budget_exceeded=$false;exit_code=0}
 }
 if($env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN){throw 'parent-token-leaked-to-child'}
 $child=Enter-HostExecutionLease -Role COMSOL -Stage prepare
 try {
   $budget=Get-HostResourceBudget -Role COMSOL -Stage solver
   if(-not$budget.heavy_stage){throw 'child-solver-not-heavy'}
   $script:events+='child-solver-heavy'
   if($scenario-ne'success'){throw 'child-original-failure'}
   return @{resource_budget_exceeded=$false;exit_code=0}
 }finally{
   $budget=Get-HostResourceBudget -Role COMSOL -Stage postprocess
   if($budget.heavy_stage){throw 'child-postprocess-not-light'}
   $script:events+='child-terminal'
   Exit-HostExecutionLease -Lease $child
 }
}
$RunId='fixture';$resolvedBudget=[pscustomobject]@{limits=[pscustomobject]@{wall_clock_seconds=30}};$runDir='.';$resourceUsage='unused'
$pwsh='unused';$codeRoot='.';$task='unused';$report='unused'
if($scenario-like'inherited_*'){
 $hostExecutionLease=@{token='parent';role='COMSOL';stage='prepare';inherited=$true;heavy=($scenario-eq'inherited_heavy')}
 $env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='parent'
}else{
 $hostExecutionLease=Enter-HostExecutionLease -Role COMSOL -Stage prepare
}
$caught=''
try {
"""
                    + block
                    + r"""
}catch{$caught=$_.Exception.Message}
if($scenario-eq'inherited_light'){
 if($caught-ne'inherited-light-denied'-or$script:events.Count){throw 'inherited-light-bypassed'}
 if($env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN-ne'parent'){throw 'parent-token-changed'}
}elseif($scenario-eq'inherited_heavy'){
 if($caught-or($script:events-join',')-ne'child-start'){throw 'inherited-heavy-released'}
}else{
 if($scenario-ne'success'-and$caught-ne'child-original-failure'){throw "original-failure-lost:$caught"}
 if($scenario-eq'success'-and$caught){throw $caught}
 $expected='enter:prepare:False,release:fixture-1,child-start,enter:prepare:False,child-solver-heavy,child-terminal,release:fixture-2'
 if($scenario-ne'failure_and_postprocess_denied'){
   $expected+=',enter:postprocess:False'
   if($hostExecutionLease.stage-ne'postprocess'){throw 'parent-did-not-reacquire-light'}
 }elseif($null-ne$hostExecutionLease){throw 'invented-postprocess-lease'}
 if(($script:events-join',')-ne$expected){throw "wrong-sequence:$($script:events-join',')"}
 if($null-ne$hostExecutionLease){Exit-HostExecutionLease -Lease $hostExecutionLease}
 if($env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN){throw 'owned-token-remains'}
}
"""
                )
                completed = subprocess.run(
                    ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    timeout=20,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, repr(completed.stdout) + repr(completed.stderr))

    def test_internal_dispatch_checks_host_permit_before_work(self) -> None:
        """Pending and active workers require permission before touching inputs."""
        support = REPO_ROOT / "common/resource_budget_support.ps1"
        for invocation in (
            "Start-ObservedFormalProcess -DispatchPlanPath missing.json -ProcessSpecification ([pscustomobject]@{})",
            "Invoke-ResourceBudgetedProcesses -DispatchPlanPath missing.json "
            "-RunDir . -UsagePath missing-usage.json -ProcessSpecifications @([pscustomobject]@{})",
            "Invoke-ResourceBudgetedProcesses -DispatchPlanPath missing.json "
            "-RunDir . -UsagePath missing-usage.json "
            "-ExistingProcessRecords @([pscustomobject]@{completed=$false})",
        ):
            with self.subTest(invocation=invocation):
                command = (
                    f". '{support}';"
                    "function Assert-HostResourceHeavyStage {throw 'fixture-permit-denied'};"
                    f"try {{{invocation};exit 3}} catch {{"
                    "if($_.Exception.Message-ne'fixture-permit-denied'){throw}};exit 0"
                )
                result = subprocess.run(
                    ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_disk_capacity_check_reports_live_volume_capacity_and_fails_closed(self) -> None:
        """The public preflight adds transient demand above the requested floor."""
        support = REPO_ROOT / "common/resource_budget_support.ps1"
        command = (
            f". '{support}';{HOST_PERMIT_FIXTURE}"
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
        support = REPO_ROOT / "common/resource_budget_support.ps1"
        command = (
            f". '{support}';{HOST_PERMIT_FIXTURE}"
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

    def test_scheduler_suppresses_checkpoint_callback_pipeline_output(self) -> None:
        """A manifest-publishing callback must not turn the wave receipt into an array."""
        source = (REPO_ROOT / "common/resource_budget_support.ps1").read_text(encoding="utf-8")
        self.assertEqual(source.count("$null = & $OnProcessCompleted $record"), 2)
        self.assertNotIn("      & $OnProcessCompleted $record", source)

    def test_invalid_windows_cpu_sample_is_discarded(self) -> None:
        """An out-of-range WMI sample must not suppress otherwise safe lanes."""
        support = REPO_ROOT / "common/resource_budget_support.ps1"
        command = (
            f". '{support}';{HOST_PERMIT_FIXTURE}"
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
        support = REPO_ROOT / "common/resource_budget_support.ps1"
        command = (
            f". '{support}';{HOST_PERMIT_FIXTURE}"
            "function Get-CimInstance {throw 'TEST_ONLY forced CIM denial'};"
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

    def test_process_snapshot_preserves_complete_family_sample(self) -> None:
        """Sharing enumeration retains identity, scoped unknowns, console and meters."""
        support = REPO_ROOT / "common/resource_budget_support.ps1"
        command = f". '{support}';" + r"""
$birth=[datetime]::new(2026,10,28,0,0,0,[DateTimeKind]::Utc)
$script:events=[Collections.Generic.List[string]]::new()
function New-TestProcess($Id,$Working,$Private,$Cpu,$Path) {
 $p=[pscustomobject]@{Id=$Id;WorkingSet64=$Working;PrivateMemorySize64=$Private;
   TotalProcessorTime=[timespan]::FromTicks($Cpu);Path=$Path}
 $p|Add-Member ScriptProperty StartTime {$script:events.Add('birth');$birth}
 $p
}
$root=New-TestProcess 101 10 30 7 ''
$child=New-TestProcess 102 40 20 11 ''
$console=New-TestProcess 103 5 8 3 (Join-Path $env:SystemRoot 'System32/conhost.exe')
$unknown=[pscustomobject]@{Id=104;Path=''}
$unknown|Add-Member ScriptProperty StartTime {throw 'TEST_ONLY inaccessible birth'}
$script:processes=@($root,$child,$console,$unknown)
function Get-Process {$script:events.Add('process');$script:processes}
function Get-HostResourceNativeProcessCreationTicks {param($ProcessId);$null}
function Get-CimInstance {
 $script:events.Add('cim')
 if($script:scenario-ne'cim'){throw 'TEST_ONLY CIM unavailable'}
 foreach($entry in @(@(101,0),@(102,101),@(103,101),@(104,0))){
  [pscustomobject]@{ProcessId=$entry[0];ParentProcessId=$entry[1]}
 }
}
function Get-HostResourceProcessParents {
 $script:events.Add('fallback')
 $parents=[Collections.Generic.Dictionary[int,int]]::new()
 $parents[101]=0;$parents[102]=$(if($script:scenario-eq'reused_tracked'){0}else{101});$parents[103]=101
 $parents[104]=$(if($script:scenario-eq'owned_unknown'){101}else{0})
 [pscustomobject]@{parents=$parents;complete=($script:scenario-ne'incomplete');
   started_at_utc_ticks=$birth.AddSeconds(1).Ticks}
}
function Convert-TestPublicProcessSample {
 param($Sample)
 # JSON object keys are strings; preserve every public sample field and value.
 $parents=[ordered]@{}
 foreach($id in $Sample.process_parent_ids.Keys){$parents[[string]$id]=$Sample.process_parent_ids[$id]}
 [ordered]@{ancestry_complete=$Sample.ancestry_complete;process_parent_ids=$parents;
  unknown_ancestry_process_ids=$Sample.unknown_ancestry_process_ids;
  tracked_process_ids=$Sample.tracked_process_ids;tracked_process_started_at_utc_ticks=$Sample.tracked_process_started_at_utc_ticks;
  active_process_ids=$Sample.active_process_ids;system_console_host_process_ids=$Sample.system_console_host_process_ids;
  working_set_bytes=$Sample.working_set_bytes;private_bytes=$Sample.private_bytes;
  managed_memory_bytes=$Sample.managed_memory_bytes;total_processor_time_ticks=$Sample.total_processor_time_ticks;
  processor_time_ticks_by_process_id=$Sample.processor_time_ticks_by_process_id}
}
$results=@()
foreach($script:scenario in @('cim','fallback','owned_unknown','incomplete','reused_root','reused_tracked')){
 $script:events.Clear()
 $args=@{RootProcessIds=@(101);RootProcessStartedAtUtcTicks=@{'101'=$birth.Ticks}}
 if($script:scenario-eq'reused_root'){$args.RootProcessStartedAtUtcTicks['101']=$birth.Ticks-1}
 if($script:scenario-eq'reused_tracked'){
  $args.TrackedProcessIds=@(102);$args.TrackedProcessStartedAtUtcTicks=@{'102'=($birth.Ticks-1)}
  # A reused PID no longer belongs to the old parent; neither parent table reconnects it.
 }
 $independent=Get-ManagedSolverProcessSample @args
 $cimIndex=$script:events.IndexOf('cim')
 if($script:events[0]-ne'process'-or$cimIndex-lt2-or
   @($script:events.GetRange(1,$cimIndex-1)|Where-Object {$_-ne'birth'}).Count){
  throw ('Standalone enumeration order changed: '+($script:events-join','))
 }
 $snapshot=Get-RepositoryProcessSnapshot
 $before=$script:events.Count
 $shared=Get-ManagedSolverProcessSample @args -ProcessSnapshot $snapshot
 $newEvents=@($script:events|Select-Object -Skip $before)
 if(@($newEvents|Where-Object {$_-in@('process','cim','fallback')}).Count){throw 'Shared sample re-enumerated'}
 $results+=@{scenario=$script:scenario;expected_birth_ticks=$birth.Ticks;independent=(Convert-TestPublicProcessSample $independent);shared=(Convert-TestPublicProcessSample $shared)}
}
$results|ConvertTo-Json -Depth 12 -Compress
"""
        completed = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPO_ROOT, check=False, capture_output=True, text=True, encoding="utf-8", timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        samples = json.loads(completed.stdout)
        for case in samples:
            with self.subTest(scenario=case["scenario"]):
                self.assertEqual(case["shared"], case["independent"])
                sample = case["shared"]
                if case["scenario"] == "reused_root":
                    self.assertEqual(sample["active_process_ids"], [])
                    continue
                expected_ids = [101, 103] if case["scenario"] == "reused_tracked" else [101, 102, 103]
                self.assertEqual(sample["active_process_ids"], expected_ids)
                self.assertEqual(sample["system_console_host_process_ids"], [103])
                for pid in expected_ids:
                    self.assertIn(pid, sample["tracked_process_ids"])
                    self.assertEqual(sample["tracked_process_started_at_utc_ticks"][str(pid)], case["expected_birth_ticks"])
                    self.assertEqual(sample["processor_time_ticks_by_process_id"][str(pid)], {101: 7, 102: 11, 103: 3}[pid])
                self.assertEqual(sample["process_parent_ids"]["103"], 101)
                if case["scenario"] == "reused_tracked":
                    self.assertNotIn("102", sample["process_parent_ids"])
                else:
                    self.assertEqual(sample["process_parent_ids"]["102"], 101)
                self.assertEqual(sample["managed_memory_bytes"], 38 if len(expected_ids) == 2 else 78)
                self.assertEqual(sample["working_set_bytes"], 15 if len(expected_ids) == 2 else 55)
                self.assertEqual(sample["private_bytes"], 38 if len(expected_ids) == 2 else 58)
                self.assertEqual(sample["total_processor_time_ticks"], 10 if len(expected_ids) == 2 else 21)
                self.assertEqual(sample["ancestry_complete"], case["scenario"] not in {"owned_unknown", "incomplete"})
                self.assertEqual(sample["unknown_ancestry_process_ids"], [104] if case["scenario"] == "owned_unknown" else [])

    def test_parallel_wave_enumerates_once_per_poll_and_refreshes(self) -> None:
        """The real dispatch loop shares both successful and fallback observations."""
        support = REPO_ROOT / "common/resource_budget_support.ps1"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch = root / "dispatch.json"
            dispatch.write_text(json.dumps({
                "role": "simion_repository_dispatch_plan",
                "estimation": {"kind": "exact_resource_profile"},
                "limits": dispatch_limits(maximum_concurrency=8),
            }), encoding="utf-8")
            command = f". '{support}';{HOST_PERMIT_FIXTURE}$directory='{root}';$dispatch='{dispatch}';" + r"""
function Get-SystemCpuPercent {0.0}
function Get-RepositoryAvailableMemoryBytes {[int64](64GB)}
function Stop-ManagedSolverProcesses {throw 'Unexpected termination'}
function Start-Sleep {param($Milliseconds);$script:sleeps++}
function Get-Process {
 $script:enumerations++
 if($script:sleeps-eq0){$script:observed}
}
function Get-CimInstance {
 $script:cimCalls++
 if($script:fallback){throw 'TEST_ONLY CIM unavailable'}
 if($script:sleeps-eq0){foreach($p in $script:observed){
  [pscustomobject]@{ProcessId=$p.Id;ParentProcessId=0}
 }}
}
function Get-HostResourceProcessParents {
 $script:fallbackCalls++
 $parents=[Collections.Generic.Dictionary[int,int]]::new()
 foreach($p in $script:observed){$parents[$p.Id]=0}
 [pscustomobject]@{parents=$parents;complete=$true;started_at_utc_ticks=[datetime]::UtcNow.Ticks}
}
$results=@()
foreach($count in @(1,4,8)){
 foreach($script:fallback in @($false,$true)){
  $script:enumerations=0;$script:cimCalls=0;$script:fallbackCalls=0;$script:sleeps=0
  $script:waited=0;$script:disposed=0;$script:observed=@();$records=@()
  foreach($index in 1..$count){
   $process=[pscustomobject]@{Id=(100+$index);StartTime=[datetime]::new(2026,10,28,0,0,0,[DateTimeKind]::Utc);
    Path='';WorkingSet64=10;PrivateMemorySize64=20;TotalProcessorTime=[timespan]::FromTicks(30);ExitCode=0}
   $process|Add-Member ScriptMethod WaitForExit {$script:waited++}
   $process|Add-Member ScriptMethod Dispose {$script:disposed++}
   $script:observed+=@($process)
   $records+=@([pscustomobject]@{name="worker$index";process=$process;
    specification=[pscustomobject]@{file_path='fixture.exe'};root_process_id=$process.Id;
    root_process_started_at_utc_ticks=$process.StartTime.Ticks;tracked_process_ids=@($process.Id);
    started_at=[datetimeoffset]::UtcNow;active=$true;completed=$false;exit_code=$null;
    pressure_terminated=$false;peak_working_set_bytes=0;peak_managed_memory_bytes=0;
    completed_during_observation=$false;observed_process_cpu_percent=0;observed_background_cpu_percent=0})
  }
  $result=Invoke-ResourceBudgetedProcesses -DispatchPlanPath $dispatch -RunDir $directory `
   -UsagePath (Join-Path $directory 'usage.json') -ProcessSpecifications @() -ExistingProcessRecords $records
  if($result.processes.Count-ne$count-or$script:waited-ne$count-or$script:disposed-ne$count){throw 'Incomplete wave'}
  $results+=@{workers=$count;fallback=$script:fallback;enumerations=$script:enumerations;
    cim=$script:cimCalls;parents=$script:fallbackCalls;sleeps=$script:sleeps}
 }
}
'RESULT='+($results|ConvertTo-Json -Compress)
"""
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT, check=False, capture_output=True, text=True, encoding="utf-8", timeout=20,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            results = json.loads(next(line[7:] for line in completed.stdout.splitlines() if line.startswith("RESULT=")))
            for result in results:
                with self.subTest(workers=result["workers"], fallback=result["fallback"]):
                    self.assertEqual(result["enumerations"], 2)
                    self.assertEqual(result["cim"], 2)
                    self.assertEqual(result["parents"], 2 if result["fallback"] else 0)
                    self.assertEqual(result["sleeps"], 1)

    def test_native_parent_observation_marks_missing_ancestry_without_stopping_root(self) -> None:
        support = REPO_ROOT / "common/resource_budget_support.ps1"
        command = (
            f". '{support}';"
            "function Get-CimInstance {throw 'TEST_ONLY forced CIM denial'};"
            "function Get-HostResourceProcessParents {"
            "[pscustomobject]@{parents=[Collections.Generic.Dictionary[int,int]]::new();"
            "complete=$false;started_at_utc_ticks=[DateTime]::UtcNow.Ticks}};"
            "$sample=Get-ManagedSolverProcessSample -RootProcessIds @($PID);"
            "if($sample.ancestry_complete-or$sample.active_process_ids-notcontains$PID){exit 3};"
            "function Get-HostResourceProcessParents {"
            "$parents=[Collections.Generic.Dictionary[int,int]]::new();$parents[$PID]=123;"
            "[pscustomobject]@{parents=$parents;complete=$true;started_at_utc_ticks=0}};"
            "$sample=Get-ManagedSolverProcessSample -RootProcessIds @($PID);"
            "if($sample.ancestry_complete-or$sample.unknown_ancestry_process_ids-notcontains$PID){exit 4}"
        )
        result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPO_ROOT, check=False, capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_native_parent_unknown_identity_is_scoped_to_owned_candidates(self) -> None:
        """TEST_ONLY protected identities are unrelated until their parent joins this tree."""
        support = REPO_ROOT / "common/resource_budget_support.ps1"
        command = f"""
. '{support}'
function Get-CimInstance {{throw 'TEST_ONLY forced CIM denial'}}
$realOwner=Get-Process -Id $PID
$protected=[pscustomobject]@{{Id=424242;Path=''}}
$protected|Add-Member -MemberType ScriptProperty -Name StartTime -Value {{throw 'TEST_ONLY inaccessible creation time'}}
$grandchild=[pscustomobject]@{{Id=424243;Path=''}}
$grandchild|Add-Member -MemberType ScriptProperty -Name StartTime -Value {{throw 'TEST_ONLY inaccessible creation time'}}
function Get-Process {{@($realOwner,$protected,$grandchild)}}
function Get-HostResourceNativeProcessCreationTicks {{param($ProcessId);return $null}}
$script:ownedCandidate=$false
function Get-HostResourceProcessParents {{
 $parents=[Collections.Generic.Dictionary[int,int]]::new()
 $parents[$PID]=0;$parents[424242]=$(if($script:ownedCandidate){{$PID}}else{{0}})
 $parents[424243]=424242
 [pscustomobject]@{{parents=$parents;complete=$true;started_at_utc_ticks=[DateTime]::UtcNow.Ticks}}
}}
$sample=Get-ManagedSolverProcessSample -RootProcessIds @($PID)
if(-not$sample.ancestry_complete-or$sample.unknown_ancestry_process_ids.Count-ne0){{throw 'Unrelated protected identities polluted the owned tree'}}
$script:ownedCandidate=$true
$sample=Get-ManagedSolverProcessSample -RootProcessIds @($PID)
if($sample.ancestry_complete-or($sample.unknown_ancestry_process_ids-join',')-ne'424242,424243'){{throw 'Unresolved owned candidate chain disappeared'}}
if($sample.active_process_ids-contains424242-or$sample.active_process_ids-contains424243){{throw 'Unknown identities became verified owned processes'}}
"""
        result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPO_ROOT, check=False, capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_launcher_completion_ignores_only_classified_system_console_hosts(self) -> None:
        """Console infrastructure cannot strand work or hide a real descendant."""
        support = REPO_ROOT / "common/resource_budget_support.ps1"
        command = (
            f". '{support}';{HOST_PERMIT_FIXTURE}"
            "$spec=[pscustomobject]@{file_path=(Get-Process -Id $PID).Path};"
            "$old=[pscustomobject]@{active_process_ids=@(41)};"
            "if(-not(Test-RepositoryManagedProcessIsActive -Specification $spec "
            "-RootProcessId $PID -RootProcessStartedAtUtcTicks 0 -Sample $old)){exit 3};"
            "$consoleOnly=[pscustomobject]@{active_process_ids=@(41);"
            "system_console_host_process_ids=@(41)};"
            "if(Test-RepositoryManagedProcessIsActive -Specification $spec "
            "-RootProcessId $PID -RootProcessStartedAtUtcTicks 0 -Sample $consoleOnly){exit 4};"
            "$ordinaryChild=[pscustomobject]@{active_process_ids=@(41,42);"
            "system_console_host_process_ids=@(41)};"
            "if(-not(Test-RepositoryManagedProcessIsActive -Specification $spec "
            "-RootProcessId $PID -RootProcessStartedAtUtcTicks 0 -Sample $ordinaryChild)){exit 5}"
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

    @unittest.skipUnless(sys.platform == "win32" and shutil.which("pwsh"), "Windows PowerShell 7 required")
    def test_process_sample_classifies_real_hidden_console_without_removing_accounting(self) -> None:
        """The executor recognizes the protected conhost path and still meters it."""
        support = REPO_ROOT / "common/resource_budget_support.ps1"
        command = (
            f". '{support}';{HOST_PERMIT_FIXTURE}"
            "$child=Start-Process -FilePath (Get-Process -Id $PID).Path "
            "-ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 5') "
            "-WindowStyle Hidden -PassThru;"
            "try{"
            "$ticks=[int64]$child.StartTime.ToUniversalTime().Ticks;$sample=$null;"
            "foreach($attempt in 1..30){"
            "$sample=Get-ManagedSolverProcessSample -RootProcessIds @($child.Id) "
            "-RootProcessStartedAtUtcTicks @{([string]$child.Id)=$ticks};"
            "if(@($sample.system_console_host_process_ids).Count-gt0){break};"
            "Start-Sleep -Milliseconds 100};"
            "$consoleIds=@($sample.system_console_host_process_ids);"
            "if($consoleIds.Count-eq0){exit 3};"
            "foreach($id in $consoleIds){"
            "if(@($sample.active_process_ids)-notcontains$id){exit 4};"
            "if(@($sample.tracked_process_ids)-notcontains$id){exit 5}};"
            "if([int64]$sample.managed_memory_bytes-le0){exit 6}"
            "}finally{if(-not$child.HasExited){Stop-Process -Id $child.Id -Force};$child.Dispose()}"
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

    def test_parallel_wave_advances_after_launcher_has_only_system_console_host(self) -> None:
        """A completed wrapper cannot strand the next queued work item."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch = root / "dispatch.json"
            usage = root / "usage.json"
            dispatch.write_text(
                json.dumps(
                    {
                        "role": "simion_repository_dispatch_plan",
                        "dispatch_unit": "independent_work_items",
                        "work_item_count": 2,
                        "estimation": {"kind": "exact_resource_profile"},
                        "limits": dispatch_limits(maximum_concurrency=1, launch_stagger_seconds=1),
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                "function Get-RepositoryAvailableMemoryBytes{return [int64](64GB)};"
                "function Get-SystemCpuPercent{return [double]0};"
                "function Get-RepositoryProcessSnapshot {};"
                "function Get-ManagedSolverProcessSample{"
                "param([int[]]$RootProcessIds,[int[]]$TrackedProcessIds,"
                "[hashtable]$RootProcessStartedAtUtcTicks,[hashtable]$TrackedProcessStartedAtUtcTicks);"
                "$rootId=[int]$RootProcessIds[0];$rootLive=$null-ne(Get-Process -Id $rootId -ErrorAction SilentlyContinue);"
                "$active=$(if($rootLive){@($rootId,900001)}else{@(900001)});"
                "[pscustomobject]@{tracked_process_ids=@($rootId,900001);"
                "tracked_process_started_at_utc_ticks=@{};active_process_ids=$active;"
                "system_console_host_process_ids=@(900001);working_set_bytes=0;private_bytes=0;"
                "managed_memory_bytes=0;total_processor_time_ticks=0}};"
                "$pwsh=(Get-Process -Id $PID).Path;"
                f"$root='{root}';"
                '$specs=@(1,2|ForEach-Object{[pscustomobject]@{name="worker$_";file_path=$pwsh;'
                "argument_list=@('-NoProfile','-Command','exit 0');"
                'stdout=(Join-Path $root "worker$_.stdout.log");stderr=(Join-Path $root "worker$_.stderr.log");'
                "environment=@{};working_directory=$root;scheduler_batch=[pscustomobject]@{"
                "execution_unit='independent_work_items';index=$_;total_batches=2;"
                "work_item_id_min=$_;work_item_id_max=$_;count=1}}});"
                f"$r=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' -RunDir '{root}' "
                f"-UsagePath '{usage}' -ProcessSpecifications $specs;"
                "if($r.resource_budget_exceeded-or$r.processes.Count-ne2){exit 3};"
                "if(($r.processes.name-join',')-ne'worker1,worker2'){exit 4};"
                "if(@($r.processes|Where-Object exit_code -ne 0).Count-ne0){exit 5}"
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
            measured = json.loads(usage.read_text(encoding="utf-8-sig"))
            self.assertEqual(measured["execution_wave"]["process_count"], 2)
            self.assertEqual(measured["execution_wave"]["peak_concurrency"], 1)

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
                        "host": {"logical_processors": 16},
                        "limits": {
                            "formal_observation_seconds": 7,
                            "memory_critical_reserve_bytes": 512 * 1024**2,
                            "memory_critical_seconds": 15,
                        },
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            stdout, stderr = root / "stdout.log", root / "stderr.log"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
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

    def test_formal_observation_does_not_charge_a_new_childs_historical_cpu(self) -> None:
        """Late process-tree discovery establishes a baseline instead of a CPU spike."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch = root / "dispatch.json"
            dispatch.write_text(
                json.dumps(
                    {
                        "role": "simion_repository_dispatch_plan",
                        "estimation": {"kind": "formal_first_batch_observation"},
                        "host": {"logical_processors": 16},
                        "limits": {
                            "formal_observation_seconds": 7,
                            "memory_critical_reserve_bytes": 512 * 1024**2,
                            "memory_critical_seconds": 15,
                        },
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            stdout, stderr = root / "stdout.log", root / "stderr.log"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                "function Get-RepositoryAvailableMemoryBytes{return [int64](64GB)};"
                "function Get-SystemCpuPercent{return [double]0};"
                "$script:sampleCalls=0;$script:now=[datetime]'2026-09-17T00:00:00Z';"
                "function Get-RepositoryUtcNow{return $script:now};"
                "function Start-Sleep {param([int]$Milliseconds);"
                "$script:now=$script:now.AddMilliseconds($Milliseconds)};"
                "function Get-ManagedSolverProcessSample {"
                "param([int[]]$RootProcessIds,[int[]]$TrackedProcessIds);"
                "$script:sampleCalls+=1;$root=[string]$RootProcessIds[0];"
                "$active=$(if($script:sampleCalls-lt4){@([int]$root)}else{@()});"
                "$ticks=$(if($script:sampleCalls-eq1){@{$root=[int64]10000000}}"
                "elseif($script:sampleCalls-eq2){@{$root=[int64]11000000;'900001'=[int64]900000000000}}"
                "elseif($script:sampleCalls-eq3){@{$root=[int64]21000000;'900001'=[int64]900030000000}}"
                "else{@{}});"
                "[pscustomobject]@{tracked_process_ids=@([int]$root,900001);"
                "active_process_ids=$active;working_set_bytes=1;private_bytes=1;managed_memory_bytes=1;"
                "total_processor_time_ticks=($ticks.Values|Measure-Object -Sum).Sum;"
                "processor_time_ticks_by_process_id=$ticks}"
                "};"
                "$spec=[pscustomobject]@{name='formal';file_path=(Get-Process -Id $PID).Path;"
                "argument_list=@('-NoProfile','-Command','Start-Sleep -Seconds 1');"
                f"stdout='{stdout}';stderr='{stderr}';environment=@{{}};working_directory='{root}'}};"
                f"$r=Start-ObservedFormalProcess -DispatchPlanPath '{dispatch}' -ProcessSpecification $spec;"
                "if([math]::Abs([double]$r.observed_process_cpu_percent-50.0)-gt0.001){"
                "Write-Error ('unexpected observed CPU: '+$r.observed_process_cpu_percent);exit 3}"
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

    def test_formal_observation_uses_sustained_tail_cpu_not_startup_peak(self) -> None:
        """A short Fast Adjust-like CPU burst must not serialize the flight."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch = root / "dispatch.json"
            dispatch.write_text(
                json.dumps(
                    {
                        "role": "simion_repository_dispatch_plan",
                        "estimation": {"kind": "formal_first_batch_observation"},
                        "host": {"logical_processors": 16},
                        "limits": {
                            "formal_observation_seconds": 45,
                            "memory_critical_reserve_bytes": 512 * 1024**2,
                            "memory_critical_seconds": 15,
                        },
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            stdout, stderr = root / "stdout.log", root / "stderr.log"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                "function Get-RepositoryAvailableMemoryBytes{return [int64](64GB)};"
                "function Get-SystemCpuPercent{return [double]0};"
                "$script:sampleCalls=0;$script:ticks=[int64]0;"
                "$script:now=[datetime]'2026-09-17T00:00:00Z';"
                "function Get-RepositoryUtcNow{return $script:now};"
                "function Start-Sleep {param([int]$Milliseconds);"
                "$script:now=$script:now.AddMilliseconds($Milliseconds)};"
                "function Get-ManagedSolverProcessSample {"
                "param([int[]]$RootProcessIds,[int[]]$TrackedProcessIds);"
                "$script:sampleCalls+=1;$root=[string]$RootProcessIds[0];"
                "if($script:sampleCalls-gt1){"
                "$script:ticks+=$(if($script:sampleCalls-le71){[int64]72000000}else{[int64]5000000})};"
                "[pscustomobject]@{tracked_process_ids=@([int]$root);active_process_ids=@([int]$root);"
                "working_set_bytes=1;private_bytes=1;managed_memory_bytes=1;"
                "total_processor_time_ticks=$script:ticks;"
                "processor_time_ticks_by_process_id=@{$root=$script:ticks}}"
                "};"
                "$spec=[pscustomobject]@{name='formal';file_path=(Get-Process -Id $PID).Path;"
                "argument_list=@('-NoProfile','-Command','Start-Sleep -Seconds 60');"
                f"stdout='{stdout}';stderr='{stderr}';environment=@{{}};working_directory='{root}'}};"
                f"$r=Start-ObservedFormalProcess -DispatchPlanPath '{dispatch}' -ProcessSpecification $spec;"
                "try{"
                "if([math]::Abs([double]$r.observed_process_cpu_percent-6.25)-gt0.001){"
                "Write-Error ('unexpected sustained CPU: '+$r.observed_process_cpu_percent);exit 3};"
                "if([double]$r.observed_process_cpu_peak_percent-lt89.0){exit 4};"
                "if($r.observed_process_cpu_measurement-ne'median_final_observation_window'){exit 5}"
                "}finally{Stop-Process -Id $r.process_record.root_process_id -Force -ErrorAction SilentlyContinue}"
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

    def test_wave_publishes_measured_worker_peak_with_its_own_count_and_identity(self) -> None:
        """TEST_ONLY children measure real worker memory, never wave/count arithmetic."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch, usage = root / "dispatch.json", root / "usage.json"
            dispatch.write_text(json.dumps({
                "role": "simion_repository_dispatch_plan", "particle_count": 7,
                "estimation": {"kind": "observed_formal_batch"},
                "limits": dispatch_limits(maximum_concurrency=1, launch_stagger_seconds=1),
            }), encoding="utf-8")
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                "function Get-RepositoryAvailableMemoryBytes {[int64](8GB)};"
                "function Get-SystemCpuPercent {0.0};"
                "$spec=[pscustomobject]@{name='TEST_ONLY_seven';scheduler_batch=[pscustomobject]@{count=7;index=2};"
                "file_path=(Get-Process -Id $PID).Path;argument_list=@('-NoProfile','-Command',"
                "'$memory=[byte[]]::new(96MB);$memory[0]=1;$PID;Start-Sleep -Seconds 3');"
                f"stdout='{root / 'worker.out'}';stderr='{root / 'worker.err'}';environment=@{{}};working_directory='{root}'}};"
                f"$r=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' -RunDir '{root}' "
                f"-UsagePath '{usage}' -ProcessSpecifications @($spec);"
                "if($r.resource_budget_exceeded){throw 'Controlled child did not finish'}"
            )
            result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            observation = json.loads(usage.read_text())["per_process_memory_observation"]
            self.assertEqual(observation["work_units"], 7)
            self.assertEqual(observation["process"], "TEST_ONLY_seven")
            self.assertEqual(observation["root_process_id"], int((root / "worker.out").read_text().strip()))
            self.assertGreater(observation["root_process_started_at_utc_ticks"], 0)
            self.assertGreater(observation["peak_managed_memory_bytes"], 96 * 1024**2)

    def test_completed_first_formal_observation_still_writes_admission_receipt(self) -> None:
        """A terminal first batch publishes evidence without a renewed heavy permit."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch, usage = root / "dispatch.json", root / "usage.json"
            trace = root / "trace.log"
            trace.write_text("TRACE: fixture\n", encoding="utf-8")
            dispatch.write_text(
                json.dumps(
                    {
                        "role": "simion_repository_dispatch_plan",
                        "particle_count": 1,
                        "estimation": {
                            "kind": "observed_formal_batch",
                            "per_process_memory_budget_bytes": 123456,
                            "memory_safety_factor": 1.0,
                        },
                        "limits": dispatch_limits(maximum_concurrency=1),
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = (
                f". '{support}';"
                "function Assert-HostResourceHeavyStage {throw 'fixture-permit-expired'};"
                "$script:callbackCount=0;"
                "$callback={param($completedRecord);$script:callbackCount+=1;"
                "Add-Content -LiteralPath $completedRecord.specification.trace "
                "-Value 'status,Fly completed.' -Encoding utf8};"
                "$record=[pscustomobject]@{name='batch01';completed=$true;exit_code=0;"
                "peak_working_set_bytes=[int64]10;peak_managed_memory_bytes=[int64]20;"
                "completed_during_observation=$true;observed_process_cpu_percent=0.0;"
                "observed_background_cpu_percent=0.0;"
                f"specification=[pscustomobject]@{{trace='{trace}'}}}};"
                f"$r=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' "
                f"-RunDir '{root}' -UsagePath '{usage}' -ExistingProcessRecords @($record) "
                "-OnProcessCompleted $callback;"
                "if($r.resource_budget_exceeded){exit 3};"
                f"$receipt=Get-Content -Raw '{usage}'|ConvertFrom-Json;"
                "if($receipt.scheduler_receipt.dynamic_admission_bytes_at_finish-ne123456){exit 4};"
                "if($script:callbackCount-ne1){exit 5};"
                "if($receipt.PSObject.Properties.Name-contains'per_process_memory_observation'){exit 7};"
                f"if((Get-Content -LiteralPath '{trace}' -Tail 1)-ne"
                "'status,Fly completed.'){exit 6}"
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

    def test_scheduler_recovers_twice_then_fails_closed_after_third_danger(self) -> None:
        """Frozen timing and reserve changes drive the same pressure state machine."""
        for scale, warning in ((1, False), (2, False), (1, True), (2, True)):
            with self.subTest(policy_scale=scale, warning_policy=warning):
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
                                "limits": dispatch_limits(
                                    launch_stagger_seconds=5 * scale,
                                    memory_critical_seconds=15 * scale,
                                    memory_recovery_stable_seconds=45 * scale,
                                    memory_admission_reserve_bytes=0 if warning else 1024**3 * scale,
                                    **({"memory_policy": "warn_single_worker"} if warning else {}),
                                    memory_critical_reserve_bytes=512 * 1024**2 * scale,
                                ),
                            }
                        ),
                        encoding="utf-8",
                    )
                    support = REPO_ROOT / "common/resource_budget_support.ps1"
                    command = (
                        f". '{support}';{HOST_PERMIT_FIXTURE}$script:policyScale={scale};"
                        "$script:now=[datetimeoffset]'2026-08-26T00:00:00Z';$script:nextPid=100;$script:stoppedIds=@();"
                        "function Get-RepositoryUtcNow {$script:now};"
                        "function Start-Sleep {param([int]$Seconds=0,[int]$Milliseconds=0);"
                        "$script:now=$script:now.AddSeconds($Seconds+($Milliseconds/1000.0))};"
                        "function Get-RepositoryAvailableMemoryBytes {"
                        "$seconds=($script:now-[datetimeoffset]'2026-08-26T00:00:00Z').TotalSeconds/$script:policyScale;"
                        "if(($seconds-ge0-and$seconds-lt0.5)-or($seconds-ge1-and$seconds-lt17)-or($seconds-ge72-and$seconds-lt88)-or$seconds-ge138){return [int64](256MB)};"
                        "return [int64](8GB)};"
                        "function Get-SystemCpuPercent {[double]0};"
                        "function Start-RepositoryScheduledProcess {param($Specification);$script:nextPid+=1;"
                        "[pscustomobject]@{name=[string]$Specification.name;specification=$Specification;process=$null;"
                        "root_process_id=$script:nextPid;started_at=(Get-RepositoryUtcNow);tracked_process_ids=@($script:nextPid);"
                        "active=$true;completed=$false;exit_code=$null;peak_working_set_bytes=[int64]0;"
                        "peak_managed_memory_bytes=[int64]0;pressure_terminated=$false}};"
                        "function Get-RepositoryProcessSnapshot {};"
                        "function Get-ManagedSolverProcessSample {param([int[]]$RootProcessIds,[int[]]$TrackedProcessIds);"
                        "[pscustomobject]@{tracked_process_ids=@($RootProcessIds[0]);active_process_ids=@($RootProcessIds[0]);"
                        "working_set_bytes=1073741824;private_bytes=2147483648;managed_memory_bytes=2147483648;"
                        "total_processor_time_ticks=0}};"
                        "function Stop-ManagedSolverProcesses {param([int[]]$ProcessIds);$script:stoppedIds+=@($ProcessIds)};"
                        "$specs=@('a','b'|ForEach-Object {[pscustomobject]@{name=$_;file_path='unused';argument_list=@();"
                        "stdout='unused';stderr='unused';environment=@{};working_directory=''}});"
                        f"$r=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' -RunDir '{root}' "
                        f"-UsagePath '{usage}' -ProcessSpecifications $specs;"
                        "if(-not$r.resource_budget_exceeded){exit 3};"
                        "if(@($script:stoppedIds|Where-Object{$_-lt101-or$_-gt$script:nextPid}).Count){throw 'Stopped unrelated unit'};"
                        f"$receipt=Get-Content -Raw '{usage}'|ConvertFrom-Json;"
                        "if($receipt.status-ne'resource_pressure_failed' -or"
                        "$receipt.failure_class-ne'memory_danger_recovery_attempts_exhausted' -or"
                        "$receipt.scheduler_receipt.termination_requeue_events.Count-ne2 -or"
                        "$receipt.scheduler_receipt.recovery_relaunch_events.Count-ne2 -or"
                        "$receipt.scheduler_receipt.recovery_relaunch_events[0].attempt-ne1 -or"
                        "$receipt.scheduler_receipt.recovery_relaunch_events[1].attempt-ne2){exit 4};"
                        "$firstStopSeconds=([datetimeoffset]$receipt.scheduler_receipt.termination_requeue_events[0].at_utc-"
                        "[datetimeoffset]'2026-08-26T00:00:00Z').TotalSeconds;"
                        "if($firstStopSeconds-lt(16*$script:policyScale)){throw 'Transient danger timer was not reset'};"
                        "if(([datetimeoffset]$receipt.scheduler_receipt.recovery_relaunch_events[0].at_utc-"
                        "[datetimeoffset]$receipt.scheduler_receipt.termination_requeue_events[0].at_utc).TotalSeconds-lt(45*$script:policyScale)){exit 5}"
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

    def test_managed_termination_failure_preserves_live_process_and_cause(self) -> None:
        support = REPO_ROOT / "common/resource_budget_support.ps1"
        command = f"""
. '{support}'
$script:exited=$false;$script:disposed=0;$script:kills=0
function Get-Process {{
 param($Id,$ErrorAction)
 $p=[pscustomobject]@{{HasExited=$script:exited}}
 $p|Add-Member ScriptMethod Refresh {{}}
 $p|Add-Member ScriptMethod Dispose {{$script:disposed++}}
 return $p
}}
function taskkill.exe {{$script:kills++;$global:LASTEXITCODE=5}}
try{{Stop-ManagedSolverProcesses -ProcessIds @(12345);throw 'Live termination failure was accepted'}}
catch{{if($_.Exception.Message-ne'MANAGED_PROCESS_TERMINATION_FAILED PID=12345 EXIT_CODE=5'){{throw}}}}
$script:exited=$true
Stop-ManagedSolverProcesses -ProcessIds @(12345)
if($script:disposed-ne2-or$script:kills-ne2){{throw 'Held process instance was not disposed'}}
Write-Output 'TERMINATION_FAILURE=PASS'
"""
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("TERMINATION_FAILURE=PASS", result.stdout)

    def test_failed_batch_halts_new_launches_without_stopping_healthy_siblings(self) -> None:
        """A peer failure preserves natural evidence from active healthy workers."""
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
                        "limits": dispatch_limits(launch_stagger_seconds=1),
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                "function Get-SystemCpuPercent {[double]0};"
                "function Get-RepositoryAvailableMemoryBytes {[int64](32GB)};"
                # These workers execute directly: keep this failure test independent
                # of machine-wide WMI latency; descendant tracking has its own tests.
                "function Get-RepositoryProcessSnapshot {};"
                "function Get-ManagedSolverProcessSample {param($RootProcessIds,$TrackedProcessIds);"
                "$live=@(Get-Process -Id $RootProcessIds -ErrorAction SilentlyContinue);"
                "[pscustomobject]@{tracked_process_ids=@($RootProcessIds);"
                "active_process_ids=@($live|ForEach-Object Id);working_set_bytes=[int64]1MB;"
                "managed_memory_bytes=[int64]1MB;total_processor_time_ticks=[int64]0}};"
                "$exe=(Get-Process -Id $PID).Path;"
                "$specs=@("
                "[pscustomobject]@{name='fails';file_path=$exe;"
                "argument_list=@('-NoProfile','-Command','Start-Sleep -Seconds 2; exit 7');"
                f"stdout='{root}\\fails.out';stderr='{root}\\fails.err';environment=@{{}};working_directory='{root}'}},"
                "[pscustomobject]@{name='sibling';file_path=$exe;"
                "argument_list=@('-NoProfile','-Command','Start-Sleep -Seconds 5');"
                f"stdout='{root}\\sibling.out';stderr='{root}\\sibling.err';environment=@{{}};working_directory='{root}'}},"
                "[pscustomobject]@{name='queued';file_path=$exe;"
                "argument_list=@('-NoProfile','-Command','Start-Sleep -Seconds 5');"
                f"stdout='{root}\\queued.out';stderr='{root}\\queued.err';environment=@{{}};working_directory='{root}'}}) ;"
                f"$r=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' -RunDir '{root}' "
                f"-UsagePath '{usage}' -ProcessSpecifications $specs;"
                "if($r.resource_budget_exceeded){exit 3};"
                f"$receipt=Get-Content -Raw '{usage}'|ConvertFrom-Json;"
                "if($receipt.status-ne'process_failed' -or "
                "$receipt.scheduler_receipt.batch_failure_cancellation_events.Count-ne1 -or "
                "$receipt.scheduler_receipt.batch_failure_cancellation_events[0].stopped_active_batch_count-ne0){exit 4};"
                "if(Test-Path -LiteralPath '" + str(root / "queued.out") + "'){exit 5};"
                "if(-not(Test-Path -LiteralPath '" + str(root / "sibling.out") + "')){exit 6}"
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

    def test_preparation_failure_drains_already_started_worker(self) -> None:
        """A later preparation failure waits for the earlier owned worker."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch, usage = root / "dispatch.json", root / "usage.json"
            dispatch.write_text(json.dumps({"role": "simion_repository_dispatch_plan",
                "estimation": {"kind": "exact_resource_profile", "per_process_memory_budget_bytes": 1024**2,
                               "memory_safety_factor": 1.10},
                "limits": dispatch_limits(launch_stagger_seconds=1)}), encoding="utf-8")
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            marker = root / "completed.txt"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                "function Get-SystemCpuPercent {[double]0};"
                "function Get-RepositoryAvailableMemoryBytes {[int64](32GB)};"
                "function Get-RepositoryProcessSnapshot {};"
                "function Get-ManagedSolverProcessSample {param($RootProcessIds,$TrackedProcessIds);"
                "$live=@(Get-Process -Id $RootProcessIds -ErrorAction SilentlyContinue);"
                "[pscustomobject]@{tracked_process_ids=@($RootProcessIds);"
                "active_process_ids=@($live|ForEach-Object Id);working_set_bytes=[int64]1MB;"
                "managed_memory_bytes=[int64]1MB;total_processor_time_ticks=[int64]0}};"
                "$exe=(Get-Process -Id $PID).Path;$script:checkpointed=@();"
                "$specs=@([pscustomobject]@{name='first';file_path=$exe;"
                f"argument_list=@('-NoProfile','-Command',\"Start-Sleep -Seconds 4; Set-Content -LiteralPath '{marker}' -Value done\");"
                f"stdout='{root}\\first.out';stderr='{root}\\first.err';environment=@{{}};working_directory='{root}'}},"
                "[pscustomobject]@{name='next';file_path=$exe;argument_list=@('-NoProfile','-Command','exit 0');"
                f"stdout='{root}\\next.out';stderr='{root}\\next.err';environment=@{{}};working_directory='{root}';"
                "prepare={throw 'later preparation failure'}});"
                "$checkpoint={param($record) $script:checkpointed+=@($record.name)};"
                f"try{{Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' -RunDir '{root}' "
                f"-UsagePath '{usage}' -ProcessSpecifications $specs -OnProcessCompleted $checkpoint;exit 2}}catch{{"
                "if($_.Exception.Message-ne'later preparation failure'-or-not$_.Exception.Data['simion_wave_writer_completion_confirmed']){throw};"
                f"if(-not(Test-Path -LiteralPath '{marker}')-or$script:checkpointed-notcontains'first'){{exit 3}}}}"
            )
            completed = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_observation_error_drains_started_formal_worker(self) -> None:
        """A sampling error after launch must not orphan the formal worker."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch, usage, marker = root / "dispatch.json", root / "usage.json", root / "finished.txt"
            dispatch.write_text(json.dumps({"role": "simion_repository_dispatch_plan",
                "estimation": {"kind": "formal_first_batch_observation", "per_process_memory_budget_bytes": 1024**2,
                               "memory_safety_factor": 1.10},
                "limits": dispatch_limits(formal_observation_seconds=5)}), encoding="utf-8")
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                "function Get-SystemCpuPercent {[double]0};"
                "function Get-RepositoryAvailableMemoryBytes {[int64](32GB)};"
                "function Get-RepositoryProcessSnapshot {}; $script:samples=0;"
                "function Get-ManagedSolverProcessSample {param($RootProcessIds,$TrackedProcessIds);"
                "$script:samples++;if($script:samples-eq1){throw 'observation failure'};"
                "$live=@(Get-Process -Id $RootProcessIds -ErrorAction SilentlyContinue);"
                "[pscustomobject]@{tracked_process_ids=@($RootProcessIds);"
                "active_process_ids=@($live|ForEach-Object Id);working_set_bytes=[int64]1MB;"
                "managed_memory_bytes=[int64]1MB;total_processor_time_ticks=[int64]0}};"
                "$exe=(Get-Process -Id $PID).Path;"
                "$spec=[pscustomobject]@{name='formal';file_path=$exe;"
                f"argument_list=@('-NoProfile','-Command',\"Start-Sleep -Seconds 3; Set-Content -LiteralPath '{marker}' -Value done\");"
                f"stdout='{root}\\formal.out';stderr='{root}\\formal.err';environment=@{{}};working_directory='{root}'}};"
                f"try{{Invoke-SimionFormalObservation -DispatchPlanPath '{dispatch}' -RunDir '{root}' "
                f"-UsagePath '{usage}' -ProcessSpecification $spec -Replan {{throw 'unexpected replan'}};exit 2}}catch{{"
                "if($_.Exception.Message-ne'observation failure'-or$_.Exception.Data['simion_first_batch_writer_unknown']){throw};"
                f"if(-not(Test-Path -LiteralPath '{marker}')){{exit 3}}}}"
            )
            completed = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_checkpoint_failure_waits_for_active_workers_and_records_them(self) -> None:
        """Checkpoint errors stop new launches while active results can still be recorded."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch, usage = root / "dispatch.json", root / "usage.json"
            dispatch.write_text(json.dumps({"role": "simion_repository_dispatch_plan",
                "estimation": {"kind": "exact_resource_profile", "per_process_memory_budget_bytes": 1024**2,
                               "memory_safety_factor": 1.10},
                "limits": dispatch_limits(launch_stagger_seconds=1)}), encoding="utf-8")
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                "function Get-SystemCpuPercent {[double]0};"
                "function Get-RepositoryAvailableMemoryBytes {[int64](32GB)};"
                "function Get-RepositoryProcessSnapshot {};"
                "function Get-ManagedSolverProcessSample {param($RootProcessIds,$TrackedProcessIds);"
                "$live=@(Get-Process -Id $RootProcessIds -ErrorAction SilentlyContinue);"
                "[pscustomobject]@{tracked_process_ids=@($RootProcessIds);"
                "active_process_ids=@($live|ForEach-Object Id);working_set_bytes=[int64]1MB;"
                "managed_memory_bytes=[int64]1MB;total_processor_time_ticks=[int64]0}};"
                "$exe=(Get-Process -Id $PID).Path;$script:seen=@();"
                "$specs=@('first','sibling','queued'|ForEach-Object {"
                "$seconds=if($_-eq'first'){2}else{5};[pscustomobject]@{name=$_;file_path=$exe;"
                "argument_list=@('-NoProfile','-Command',\"Start-Sleep -Seconds $seconds\");"
                f"stdout='{root}\\$_.out';stderr='{root}\\$_.err';environment=@{{}};working_directory='{root}'}}}});"
                "$checkpoint={param($record) $script:seen+=@($record.name);"
                "if($record.name-eq'first'){throw 'checkpoint failed'}};"
                f"try{{Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' -RunDir '{root}' "
                f"-UsagePath '{usage}' -ProcessSpecifications $specs -OnProcessCompleted $checkpoint;exit 2}}catch{{"
                "if($_.Exception.Message-ne'checkpoint failed'-or-not$_.Exception.Data['simion_wave_writer_completion_confirmed']){throw};"
                f"if($script:seen-notcontains'sibling'-or(Test-Path -LiteralPath '{root / 'queued.out'}')){{exit 3}}}}"
            )
            completed = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
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
                        "limits": dispatch_limits(launch_stagger_seconds=1),
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                + _admission_pause_barrier(root, "exclusive_resource_in_use") +
                "function Get-SystemCpuPercent {[double]0};"
                "function Get-RepositoryAvailableMemoryBytes {[int64](32GB)};"
                "$exe=(Get-Process -Id $PID).Path;"
                "$specs=@('first','second'|ForEach-Object {[pscustomobject]@{name=$_;file_path=$exe;"
                f"argument_list=@('-NoProfile','-File','{root / 'barrier_worker.ps1'}','-ReleasePath','{root / 'admission_observed.txt'}');"
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
                        "limits": dispatch_limits(launch_stagger_seconds=1),
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                + _admission_pause_barrier(root, "available_memory_below_dynamic_admission", memory_pressure=True) +
                "function Get-SystemCpuPercent {[double]0};"
                "function Get-RepositoryAvailableMemoryBytes {"
                "if($script:memoryPhase-eq'pressured'){return [int64](5GB)};return [int64](10GB)};"
                "$exe=(Get-Process -Id $PID).Path;"
                "$specs=@('a','b'|ForEach-Object {[pscustomobject]@{name=$_;file_path=$exe;"
                f"argument_list=@('-NoProfile','-File','{root / 'barrier_worker.ps1'}','-ReleasePath','{root / 'admission_observed.txt'}');"
                f"stdout='{root}\\$_.out';stderr='{root}\\$_.err';environment=@{{}};working_directory='{root}'}}}});"
                f"$r=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' -RunDir '{root}' "
                f"-UsagePath '{usage}' -ProcessSpecifications $specs;"
                "if($r.resource_budget_exceeded-or$r.processes.Count-ne2-or"
                "@($r.processes|Where-Object {$_.exit_code-ne0}).Count-ne0){exit 3};"
                f"$receipt=Get-Content -Raw '{usage}'|ConvertFrom-Json;"
                "$pauses=@($receipt.scheduler_receipt.launch_pause_events|Where-Object {$_.reason-eq'available_memory_below_dynamic_admission'});"
                "if($pauses.Count-lt1-or$pauses[0].available_memory_bytes-ne(5GB)-or"
                "$pauses[0].required_available_memory_bytes-le(5GB)){exit 4}"
            )
            # Real children finish only after the actual low-memory pause is observed.
            # The fixture deadline fails naturally if admission evidence never arrives.
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_one_lane_waits_for_safe_memory_then_starts_without_replanning(self) -> None:
        """A sole lane keeps its safety margin and resumes after transient pressure."""
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
                        "limits": dispatch_limits(maximum_concurrency=1),
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                "function Get-SystemCpuPercent {[double]0};"
                "$script:memorySamples=0;"
                "function Get-RepositoryAvailableMemoryBytes {"
                "$script:memorySamples++;"
                "if($script:memorySamples-le2){[int64](38GB)}else{[int64](40GB)}};"
                "$exe=(Get-Process -Id $PID).Path;"
                "$specs=@([pscustomobject]@{name='only';file_path=$exe;"
                "argument_list=@('-NoProfile','-Command','Start-Sleep -Milliseconds 200');"
                f"stdout='{root}\\only.out';stderr='{root}\\only.err';environment=@{{}};working_directory='{root}'}});"
                f"$r=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' -RunDir '{root}' "
                f"-UsagePath '{usage}' -ProcessSpecifications $specs;"
                "if($r.resource_budget_exceeded-or$r.processes.Count-ne1-or$r.processes[0].exit_code-ne0){exit 3};"
                f"$receipt=Get-Content -Raw '{usage}'|ConvertFrom-Json;"
                "$pauses=@($receipt.scheduler_receipt.launch_pause_events|Where-Object "
                "{$_.reason-eq'available_memory_below_dynamic_admission'});"
                "if($pauses.Count-lt1-or$script:memorySamples-lt3){exit 4}"
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
        support = REPO_ROOT / "common/resource_budget_support.ps1"
        command = (
            f". '{support}';{HOST_PERMIT_FIXTURE}"
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
        support = (REPO_ROOT / "common/resource_budget_support.ps1").read_text(encoding="utf-8")
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
        project_id: str = PROJECT_ID,
        runtime_profile_id: str = "octupole_segmented_rod_axial_acceleration_n100_spatial_refined",
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
            (PROJECT_ID, "quadrupole_segmented_rod_axial_acceleration_n100_spatial_refined"),
            (PROJECT_ID, "octupole_segmented_rod_axial_acceleration_n100_spatial_refined"),
        ):
            with self.assertRaisesRegex(ValueError, "not authorized|differs from authorized scope"):
                self.validate(project_id, profile)
        with self.assertRaisesRegex(ValueError, "not authorized|differs from authorized scope"):
            self.validate(PROJECT_ID, "hexapole_segmented_rod_axial_acceleration_n100_spatial_refined")
        with self.assertRaisesRegex(ValueError, "not authorized|differs from authorized scope"):
            self.validate(
                PROJECT_ID,
                "octupole_no_acceleration_full_length",
            )

    def test_hexapole_closed_mesh_build_profiles_are_not_authorized(self) -> None:
        for profile in (
            "exit_aperture_plate_acceleration_n100_hybrid_d1_mesh_build",
            "exit_aperture_plate_acceleration_n100_hybrid_p1_coarse",
            "exit_aperture_plate_acceleration_n100_hybrid_d2_mesh_build",
        ):
            with self.assertRaisesRegex(ValueError, "unknown runtime profile"):
                resolve_runtime_profile(REPO_ROOT, PROJECT_ID, f"hexapole_{profile}")

    def test_preflight_temp_cleanup_runs_after_success_and_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for name in ("run_finite_3d_transport.ps1", "run_simion_finite_3d_transport.ps1"):
                runner = REPO_ROOT / "projects/rf_multipole_ion_optics/runtime" / name
                command = (
                    f"$path='{runner}';$budgetPreflight='{Path(directory) / 'budget.json'}';"
                    + r"""
$ast=[Management.Automation.Language.Parser]::ParseFile($path,[ref]$null,[ref]$null)
$blocks=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.TryStatementAst] -and $node.Finally -and $node.Finally.Extent.Text.Contains('Remove-Item -LiteralPath $budgetPreflight')},$true))
if($blocks.Count-ne1-or-not$blocks[0].Body.Extent.Text.Contains('projects.rf_multipole_ion_optics.runtime.resource_budget')){throw 'TEMP cleanup does not belong to the compiler preflight'}
foreach($fail in @($false,$true)){
 Set-Content -LiteralPath $budgetPreflight -Value '{}'
 $script=[scriptblock]::Create('try {if($fail){throw "fixture"}} finally '+$blocks[0].Finally.Extent.Text)
 try{& $script}catch{if($_.Exception.Message-ne'fixture'){throw}}
 if(Test-Path -LiteralPath $budgetPreflight){throw 'Compiler TEMP budget leaked'}
}
"""
                )
                result = subprocess.run(
                    ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=False,
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_high_cost_runners_validate_before_creating_run_package(self) -> None:
        for name in ("run_finite_3d_transport.ps1", "run_simion_finite_3d_transport.ps1"):
            source = (REPO_ROOT / "projects/rf_multipole_ion_optics/runtime" / name).read_text(encoding="utf-8")
            self.assertLess(
                source.index("projects.rf_multipole_ion_optics.runtime.resource_budget"),
                source.index("New-RunPackage"),
            )
            for token in (
                "[Parameter(Mandatory=$true)][string]$RuntimeProfileId",
                "[Parameter(Mandatory=$true)][string]$EngineeringBudgetPath",
                "resource_budget_exceeded",
            ):
                self.assertIn(token, source)
            owner = (REPO_ROOT / "common/contracts/run_artifact_workflow.ps1").read_text(encoding="utf-8-sig")
            self.assertIn("Complete-ResourceUsage", owner if "simion" in name else source)
            if "simion" in name:
                self.assertIn("Complete-RunArtifactPowerShellOwner -Context $ownerContext", source)
                self.assertIn("-ResourceUsagePaths $resourceItems", source)
                self.assertIn("-ResourceUsagePaths $failureUsage", source)
                self.assertIn("path=(Convert-WorkflowOwnerPath $ownerContext $caseResourceUsage[$_])", source)
                self.assertIn("resource_usage_paths=@($ResourceUsagePaths|ForEach-Object", owner)
            self.assertIn("-UseShortExecutionPath", source)
            self.assertIn("Remove-RunPackageExecutionAlias", source)
        comsol = (REPO_ROOT / "projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1").read_text(encoding="utf-8")
        comsol += (REPO_ROOT / "projects/rf_multipole_ion_optics/runtime/finite_3d_transport_preflight.ps1").read_text(encoding="utf-8")
        self.assertIn("'-StartupAttempts','1'", comsol)
        self.assertIn(
            "[ValidateSet('transport','mesh_build','field_solve')][string]$StopStage='transport'",
            comsol,
        )
        self.assertIn("MULTIPOLE_L3_STOP_STAGE", comsol)
        self.assertIn("UNQUALIFIED_MESH_BUILD_DIAGNOSTIC_ONLY", comsol)
        self.assertIn("UNQUALIFIED_FIELD_SOLVE_DIAGNOSTIC_ONLY", comsol)
        self.assertNotIn("$RuntimeProfileId -like '*_mesh_build'", comsol)
        self.assertIn("Assert-MultipoleFieldSolveReport", comsol)
        self.assertIn(
            "'projects/rf_multipole_ion_optics/comsol/configure_comsol_segment_hybrid_mesh.m'",
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
            "stationary_linear_solver_backend=$authorizedBackend",
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
        solver = (REPO_ROOT / "projects/rf_multipole_ion_optics/comsol/solve_finite_3d_transport.m").read_text(encoding="utf-8")
        budget_gate = solver.index("MULTIPOLE_L3_MAXIMUM_MESH_CELLS")
        self.assertGreater(budget_gate, solver.index("CHECKPOINT=MESH_COMPLETE"))
        self.assertLess(budget_gate, solver.index("material = model.material.create"))
        self.assertNotIn("fflush(", solver)
        self.assertIn("MESH_LOCAL_SENSITIVE_REGION_PRESENT=1", solver)
        self.assertIn("MESH_LOCAL_SENSITIVE_SIZE_FEATURE_PRESENT=%d", solver)

    def test_comsol_runner_fails_closed_on_stop_stage_disagreement(self) -> None:
        runner = (REPO_ROOT / "projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1").read_text(encoding="utf-8")
        start = runner.index("  if($resolvedBudget.PSObject.Properties.Name-notcontains'stop_stage')")
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
        budget_path = REPO_ROOT / "projects/rf_multipole_ion_optics/variants/hexapole/config/bare_transport_budget.json"
        active_budget = json.loads(budget_path.read_text(encoding="utf-8"))
        runtime_profile_id = active_budget["pilot_authorization"]["scope"]["runtime_profile_id"]
        runtime = resolve_runtime_profile(REPO_ROOT, PROJECT_ID, runtime_profile_id)
        self.assertEqual(
            budget_path.resolve(),
            Path(runtime["engineering_budget"]["path"]).resolve(),
        )
        authorized_fixture = json.loads(budget_path.read_text(encoding="utf-8"))
        authorized_fixture["pilot_authorization"]["authorized"] = True
        authorized_fixture["pilot_authorization"]["scope"]["stop_stage"] = runtime["stop_stage"]
        authorized_fixture["pilot_authorization"]["limits"]["maximum_mesh_cells"] = 100
        hybrid_runtime = json.loads(json.dumps(runtime))
        hybrid_runtime["solver_numerics"]["comsol"]["values"]["mesh"]["strategy"] = (
            "physical_segment_hybrid_swept_tetra_v1"
        )

        def validate_with(candidate: dict) -> dict:
            with (
                mock.patch(
                    "projects.rf_multipole_ion_optics.runtime.resource_budget._load",
                    return_value=candidate,
                ),
                mock.patch(
                    "projects.rf_multipole_ion_optics.runtime.resource_budget.resolve_runtime_profile",
                    return_value=hybrid_runtime,
                ),
            ):
                return validate_pilot_budget(
                    repo_root=REPO_ROOT,
                    budget_path=budget_path,
                    project_id=PROJECT_ID,
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
                "projects.rf_multipole_ion_optics.runtime.resource_budget.resolve_runtime_profile",
                return_value=runtime_without_stop_stage,
            ),
            mock.patch(
                "projects.rf_multipole_ion_optics.runtime.resource_budget._load",
                return_value=authorized_fixture,
            ),
            self.assertRaisesRegex(ValueError, "stop stage is missing or unsupported"),
        ):
            validate_pilot_budget(
                repo_root=REPO_ROOT,
                budget_path=budget_path,
                project_id=PROJECT_ID,
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
                invalid_budget["pilot_authorization"]["limits"]["maximum_mesh_cells"] = invalid
                with self.assertRaisesRegex(ValueError, "positive integers"):
                    validate_with(invalid_budget)
        invalid_identity = json.loads(json.dumps(authorized_fixture))
        invalid_identity["pilot_authorization"]["scope"]["expected_run_parent_resolved_design_sha256"] = "not-a-sha"
        with self.assertRaisesRegex(ValueError, "must be uppercase SHA-256"):
            validate_with(invalid_identity)

    def test_optional_authorized_run_id_is_exact_and_legacy_compatible(self) -> None:
        budget_path = REPO_ROOT / "projects/rf_multipole_ion_optics/variants/hexapole/config/bare_transport_budget.json"
        fixture = json.loads(budget_path.read_text(encoding="utf-8"))
        runtime_profile_id = fixture["pilot_authorization"]["scope"]["runtime_profile_id"]
        runtime = resolve_runtime_profile(REPO_ROOT, PROJECT_ID, runtime_profile_id)
        fixture["pilot_authorization"]["authorized"] = True
        fixture["pilot_authorization"]["scope"]["stop_stage"] = runtime["stop_stage"]
        authorized_run_id = "20260731_010203__sim__simion__authorized-run"
        fixture["pilot_authorization"]["scope"]["authorized_run_id"] = authorized_run_id

        def validate_with(candidate: dict, run_id: str | None) -> dict:
            with mock.patch(
                "projects.rf_multipole_ion_optics.runtime.resource_budget._load",
                return_value=candidate,
            ):
                return validate_pilot_budget(
                    repo_root=REPO_ROOT,
                    budget_path=budget_path,
                    project_id=PROJECT_ID,
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
        budget_path = REPO_ROOT / "projects/rf_multipole_ion_optics/variants/hexapole/config/bare_transport_budget.json"
        fixture = json.loads(budget_path.read_text(encoding="utf-8"))
        runtime_profile_id = fixture["pilot_authorization"]["scope"]["runtime_profile_id"]
        runtime = resolve_runtime_profile(REPO_ROOT, PROJECT_ID, runtime_profile_id)
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
                "projects.rf_multipole_ion_optics.runtime.resource_budget._load",
                return_value=candidate,
            ):
                return validate_pilot_budget(
                    repo_root=REPO_ROOT,
                    budget_path=budget_path,
                    project_id=PROJECT_ID,
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
                invalid_budget["pilot_authorization"]["limits"]["maximum_pa_grid_points"] = invalid
                with self.assertRaisesRegex(ValueError, "positive integers"):
                    validate_with(invalid_budget)

    def test_mesh_build_report_enforces_declared_cell_limit(self) -> None:
        runner = (REPO_ROOT / "projects/rf_multipole_ion_optics/runtime/finite_3d_transport_preflight.ps1").read_text(encoding="utf-8")
        start = runner.index("function Assert-MultipoleMeshBuildReport")
        end = runner.index("\nfunction Assert-MultipoleFieldSolveReport", start)
        assertion_function = runner[start:end]
        required_lines = [
            "MESH_STRATEGY=physical_segment_hybrid_swept_tetra_v1",
            "MESH_GLOBAL_EMPTY=0", "MESH_GLOBAL_HAS_PROBLEMS=0",
            "MESH_VACUUM_EMPTY=0", "MESH_VACUUM_HAS_PROBLEMS=0", "MESH_VACUUM_ELEMENTS=80",
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
                report_path = report if report_present else Path(directory) / "missing_mesh_report.txt"
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
                    f"$ErrorActionPreference='Stop';\n{assertion_function}\n"
                    f"$cells=Assert-MultipoleMeshBuildReport -Path '{escaped_path}' "
                    "-ExpectedMeshStrategy physical_segment_hybrid_swept_tetra_v1 -MaximumMeshCells 100;"
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
        runner = (REPO_ROOT / "projects/rf_multipole_ion_optics/runtime/finite_3d_transport_preflight.ps1").read_text(encoding="utf-8")
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
                    if line == "DIFFERENTIAL_FIELD_SOLVER_EVIDENCE_SOURCE=NOT_APPLICABLE_DIRECT_SOLVER"
                    else "STATIC_FIELD_ITERATIONS=9"
                    if line == "STATIC_FIELD_ITERATIONS=UNKNOWN"
                    else "STATIC_FIELD_FINAL_RESIDUAL=2e-8"
                    if line == "STATIC_FIELD_FINAL_RESIDUAL=UNKNOWN"
                    else "STATIC_FIELD_SOLVER_EVIDENCE_SOURCE=COMSOL_PROGRESS_LINIT_LINRES"
                    if line == "STATIC_FIELD_SOLVER_EVIDENCE_SOURCE=NOT_APPLICABLE_DIRECT_SOLVER"
                    else line
                )
                for line in required_lines
            ]
            invalid_cases = (
                (
                    [line for line in required_lines if line != "PARTICLE_PHYSICS_CREATED=0"]
                    + ["PARTICLE_PHYSICS_CREATED=1"],
                    "PARTICLE_PHYSICS_CREATED=0",
                ),
                (
                    [line for line in required_lines if line != "STATIC_FIELD_DOF=100"],
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
                    [line for line in required_lines if line != "ELECTRIC_POTENTIAL_ELEMENT_ORDER=QUADRATIC"],
                    "invalid electric-potential element order",
                ),
                (
                    [
                        "DIFFERENTIAL_FIELD_ITERATIONS=0" if line == "DIFFERENTIAL_FIELD_ITERATIONS=12" else line
                        for line in cg_lines
                    ],
                    "lacks positive DIFFERENTIAL_FIELD LinIt/LinRes evidence",
                ),
            )
            # These are independent text-parser cases, not process/owner cases.
            # Load the actual assertion once; keep each report and error distinct.
            reports = [required_lines, cg_lines] + [lines for lines, _ in invalid_cases]
            paths = []
            for index, lines in enumerate(reports):
                path = Path(directory) / f"field_report_{index}.txt"
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                paths.append(str(path))
            cases = Path(directory) / "cases.json"
            cases.write_text(json.dumps(paths), encoding="utf-8")
            escaped_cases = str(cases).replace("'", "''")
            command = (
                "$ErrorActionPreference='Stop';" + assertion_function +
                f"\n$paths=Get-Content -LiteralPath '{escaped_cases}' -Raw|ConvertFrom-Json;" +
                "$results=@(foreach($path in $paths){try{"
                "$result=Assert-MultipoleFieldSolveReport -Path $path;"
                "@{exit_code=0;backend=$result.stationary_linear_solver_backend;"
                "control=$result.stationary_solver_configuration.control}"
                "}catch{@{exit_code=1;error=$_.Exception.Message}}});"
                "ConvertTo-Json -InputObject $results -Depth 5 -Compress"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT, check=False, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=20,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            results = json.loads(completed.stdout)
            self.assertEqual(len(results), len(reports))
            for result, backend, control in zip(results[:2], ("pardiso", "cg_amg"), ("not_applicable", "user")):
                self.assertEqual(result["exit_code"], 0, result)
                self.assertEqual(result["backend"], backend)
                self.assertEqual(result["control"], control)
            for result, (_, expected) in zip(results[2:], invalid_cases):
                with self.subTest(expected=expected):
                    self.assertNotEqual(result["exit_code"], 0)
                    self.assertIn(expected, result["error"])

    def test_observer_warns_without_interrupting_a_healthy_child_on_wall_clock_limit(self) -> None:
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
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                f"$r=Invoke-ResourceBudgetedProcess -Limits ((Get-Content -LiteralPath '{budget}' -Raw|ConvertFrom-Json).limits) "
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
            self.assertIn("wall_clock_seconds", measured["warning_names"])

    def test_observer_warns_without_interrupting_a_healthy_child_on_observed_limits(self) -> None:
        """Observed budget excursions are evidence, not a solver-health verdict."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            budget = root / "budget.json"
            usage = root / "usage.json"
            budget.write_text(
                json.dumps(
                    {
                        "limits": {
                            "wall_clock_seconds": 60,
                            "transient_run_directory_bytes": 1,
                            "process_tree_working_set_bytes": 1,
                            "minimum_system_available_memory_bytes": 1024**5,
                            "compact_final_retained_bytes": 1024**2,
                            "automatic_retry_count": 0,
                        }
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                f"$r=Invoke-ResourceBudgetedProcess -Limits ((Get-Content -LiteralPath '{budget}' -Raw|ConvertFrom-Json).limits) "
                f"-RunDir '{root}' -UsagePath '{usage}' -FilePath (Get-Process -Id $PID).Path "
                "-ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 2');"
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
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            measured = json.loads(usage.read_text(encoding="utf-8-sig"))
            self.assertEqual(measured["status"], "running")
            self.assertIsNone(measured["limit_name"])
            self.assertTrue(
                {
                    "transient_run_directory_bytes",
                    "process_tree_working_set_bytes",
                    "minimum_system_available_memory_bytes",
                } <= set(measured["warning_names"])
            )

    def test_every_production_completion_call_binds_to_the_real_usage_helper(self) -> None:
        """Execute parsed call sites, including multiline staged-runner cleanup."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = f"""
. '{REPO_ROOT / "common/resource_budget_support.ps1"}'
function Get-RunDirectoryBytes {{ param($RunDir) return [int64]128 }}
$runDir='{root}';$runRoot=$runDir;$run=$runDir;$RunDirectory=$runDir;$OutputDirectory=$runDir;$phaseDirectory=$runDir
$usage=Join-Path $runDir 'usage.json'
$usagePath=$usage
$item=@{{path=$usage}}
$resourceUsage=$usage;$controlResourceUsage=$usage;$axisFieldUsage=$usage
$batchResourceUsagePath=$usage
$package=@{{run_dir=$runDir;artifact_run_dir=$runDir;result_dir=$runDir}};$arguments=@{{RunDir=$runDir;UsagePath=$usage}}
$actualComplete=${{function:Complete-ResourceUsage}}
function Complete-ResourceUsage {{
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$RunDir,[Parameter(Mandatory)][string]$UsagePath)
    @{{status='running';peak_run_directory_bytes=0;limits=@{{fixture=42}}}} |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $UsagePath
    $script:boundUsagePath=$UsagePath
    & $actualComplete @PSBoundParameters
}}
$count=0
foreach($folder in @('common','projects','integrations')){{
    foreach($source in Get-ChildItem -LiteralPath (Join-Path '{REPO_ROOT}' $folder) -Recurse -File -Filter '*.ps1'){{
        if($source.FullName-match'[\\/]docs[\\/]history[\\/]|[\\/]tests[\\/]'){{continue}}
        $tokens=$null;$errors=$null
        $ast=[Management.Automation.Language.Parser]::ParseFile($source.FullName,[ref]$tokens,[ref]$errors)
        if($errors){{throw ($errors|Out-String)}}
        $invocations=@($ast.FindAll({{param($node)
            $node-is[Management.Automation.Language.CommandAst]-and
            $node.GetCommandName()-eq'Invoke-ResourceBudgetedProcess'
        }},$true))
        foreach($invoke in $invocations){{
            $splat=@($invoke.CommandElements|Where-Object{{
                $_-is[Management.Automation.Language.VariableExpressionAst]-and$_.Splatted
            }})
            $parameters=@($invoke.CommandElements|Where-Object{{
                $_-is[Management.Automation.Language.CommandParameterAst]
            }}|ForEach-Object ParameterName)
            if($splat.Count-eq0-and$parameters-notcontains'Limits'){{
                throw ('Single-process invocation omits Limits: '+$source.FullName+': '+$invoke.Extent.Text)
            }}
        }}
        $calls=@($ast.FindAll({{param($node)
            $node-is[Management.Automation.Language.CommandAst]-and
            $node.GetCommandName()-eq'Complete-ResourceUsage'
        }},$true))
        foreach($call in $calls){{
            $completed=. ([scriptblock]::Create($call.Extent.Text))
            $receipt=Get-Content -LiteralPath $boundUsagePath -Raw|ConvertFrom-Json
            if($completed-ne$true-or$receipt.status-ne'completed'-or
                $receipt.final_retained_bytes-ne128-or$receipt.limits.fixture-ne42){{
                throw ('Completion receipt changed: '+$source.FullName)
            }}
            $count++
        }}
    }}
}}
if($count-eq0){{throw 'No production usage completion calls found'}}
Write-Output "COMPLETION_CALLS=$count"
exit 0
"""
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("COMPLETION_CALLS=", completed.stdout)

    def test_single_process_limits_preserve_receipts_for_json_and_dictionary_inputs(self) -> None:
        """The real observer accepts existing JSON objects and both map types equally."""
        limits = dict(
            wall_clock_seconds=10,
            transient_run_directory_bytes=1,
            transient_run_directory_sample_interval_seconds=1,
            process_tree_working_set_bytes=1024**3,
            minimum_system_available_memory_bytes=1,
            compact_final_retained_bytes=1024**2,
            automatic_retry_count=0,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = f"""
. '{support}'
{HOST_PERMIT_FIXTURE}
$decoded = '{json.dumps(limits)}' | ConvertFrom-Json
$plain = @{{}}; $ordered = [ordered]@{{}}
foreach($property in $decoded.PSObject.Properties){{
    $plain[$property.Name]=$property.Value
    $ordered[$property.Name]=$property.Value
}}
function Get-RunDirectoryBytes {{ param($RunDir) return [int64]2 }}
$variants=@($decoded,$plain,$ordered)
for($index=0;$index-lt$variants.Count;$index++){{
    $usage=Join-Path '{root}' ($index.ToString()+'.json')
    $result=Invoke-ResourceBudgetedProcess -Limits $variants[$index] -RunDir '{root}' `
        -UsagePath $usage -FilePath (Get-Process -Id $PID).Path `
        -ArgumentList @('-NoProfile','-NonInteractive','-Command','exit 7')
    if($result.exit_code-ne7-or$result.resource_budget_exceeded-or$null-ne$result.limit_name){{
        throw 'Object limits changed process exit or advisory limit semantics'
    }}
    $variants[$index].transient_run_directory_sample_interval_seconds=0
    try{{
        Invoke-ResourceBudgetedProcess -Limits $variants[$index] -RunDir '{root}' `
            -UsagePath $usage -FilePath 'must-not-launch' -ArgumentList @('unused')
        throw 'Invalid sample interval was accepted'
    }}catch{{if($_.Exception.Message-ne'Transient run-directory sample interval must be one positive integer.'){{throw}}}}
}}
exit 0
"""
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                # Allow three native child launches and live process sampling on shared CI.
                timeout=90,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            for index in range(3):
                measured = json.loads((root / f"{index}.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(measured["limits"], limits)
                self.assertEqual(measured["status"], "process_failed")
                self.assertIsNone(measured["limit_name"])
                self.assertEqual(measured["peak_run_directory_bytes"], 2)
                self.assertEqual(measured["warning_names"], ["transient_run_directory_bytes"])

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
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                "function Get-ManagedSolverProcessSample {"
                "param([int[]]$RootProcessIds,[int[]]$TrackedProcessIds,"
                "[hashtable]$RootProcessStartedAtUtcTicks,[hashtable]$TrackedProcessStartedAtUtcTicks);"
                "[pscustomobject]@{tracked_process_ids=@($RootProcessIds);"
                "active_process_ids=@();working_set_bytes=0;private_bytes=0;"
                "managed_memory_bytes=0;total_processor_time_ticks=0}"
                "};"
                f"$started=[Diagnostics.Stopwatch]::StartNew();$r=Invoke-ResourceBudgetedProcess "
                f"-Limits ((Get-Content -LiteralPath '{budget}' -Raw|ConvertFrom-Json).limits) -RunDir '{root}' -UsagePath '{usage}' "
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

    def test_single_direct_simion_finishes_when_stale_descendant_sample_stays_active(
        self,
    ) -> None:
        """A dead direct SIMION root, not a stale descendant PID, ends metering."""
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
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                "function Start-Process {"
                "param([string]$FilePath,[string[]]$ArgumentList,[switch]$PassThru,"
                "[string]$WindowStyle,[string]$WorkingDirectory,"
                "[string]$RedirectStandardOutput,[string]$RedirectStandardError,"
                "[hashtable]$Environment);"
                "Microsoft.PowerShell.Management\\Start-Process "
                "-FilePath (Get-Process -Id $PID).Path "
                "-ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 1') "
                "-PassThru -WindowStyle Hidden"
                "};"
                "function Get-ManagedSolverProcessSample {"
                "param([int[]]$RootProcessIds,[int[]]$TrackedProcessIds,"
                "[hashtable]$RootProcessStartedAtUtcTicks,"
                "[hashtable]$TrackedProcessStartedAtUtcTicks);"
                "[pscustomobject]@{tracked_process_ids=@($RootProcessIds);"
                "tracked_process_started_at_utc_ticks=$RootProcessStartedAtUtcTicks;"
                "active_process_ids=@(987654);working_set_bytes=0;private_bytes=0;"
                "managed_memory_bytes=0;total_processor_time_ticks=0}"
                "};"
                f"$r=Invoke-ResourceBudgetedProcess -Limits ((Get-Content -LiteralPath '{budget}' -Raw|ConvertFrom-Json).limits) "
                f"-RunDir '{root}' -UsagePath '{usage}' -FilePath 'C:\\SIMION\\simion.exe' "
                "-ArgumentList @('ignored');"
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
                timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            measured = json.loads(usage.read_text(encoding="utf-8-sig"))
            self.assertLess(measured["wall_clock_seconds"], 5.0)

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
            dispatch.write_text(
                json.dumps(
                    {
                        "role": "simion_repository_dispatch_plan",
                        "particle_count": 1,
                        "estimation": {"kind": "exact_resource_profile"},
                        "limits": dispatch_limits(maximum_concurrency=1),
                    }
                ),
                encoding="utf-8",
            )
            observed = root / "worker_observed"
            identities = root / "process_identities.json"
            orphan_observed = root / "worker_observed_after_launcher_exit"
            worker = f"""
$deadline=[DateTime]::UtcNow.AddSeconds(10)
while(-not(Test-Path -LiteralPath '{observed}')){{
    if([DateTime]::UtcNow-ge$deadline){{throw 'fixture worker was not observed'}}
    Start-Sleep -Milliseconds 20
}}
Start-Sleep -Seconds 2
"""
            worker_command = base64.b64encode(worker.encode("utf-16-le")).decode("ascii")
            launcher = f"""
$worker=Start-Process -FilePath (Get-Process -Id $PID).Path -WindowStyle Hidden -PassThru `
    -ArgumentList @('-NoProfile','-NonInteractive','-EncodedCommand','{worker_command}')
@(@{{pid=$worker.Id;started=$worker.StartTime.ToUniversalTime().Ticks}},
  @{{pid=$PID;started=(Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks}}) |
    ConvertTo-Json | Set-Content -LiteralPath '{identities}'
$deadline=[DateTime]::UtcNow.AddSeconds(10)
while(-not(Test-Path -LiteralPath '{observed}')){{
    if([DateTime]::UtcNow-ge$deadline){{throw 'fixture launcher observation timed out'}}
    Start-Sleep -Milliseconds 20
}}
"""
            launcher_command = base64.b64encode(launcher.encode("utf-16-le")).decode("ascii")
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            # Release the launcher only after a real process-family sample has
            # discovered its worker. Sleep alone cannot establish that boundary.
            command = f"""
. '{support}'
{HOST_PERMIT_FIXTURE}
function Get-SystemCpuPercent {{0.0}}
function Get-RepositoryAvailableMemoryBytes {{[int64](64GB)}}
function Get-CimInstance {{throw 'TEST_ONLY forced CIM denial for hidden launcher and worker'}}
$originalSample=${{function:Get-ManagedSolverProcessSample}}
function Get-ManagedSolverProcessSample {{
    param([int[]]$RootProcessIds,[int[]]$TrackedProcessIds,
          [hashtable]$RootProcessStartedAtUtcTicks,[hashtable]$TrackedProcessStartedAtUtcTicks,$ProcessSnapshot)
    $sample=& $originalSample @PSBoundParameters
    if(Test-Path -LiteralPath '{identities}'){{
        $owned=@(Get-Content -LiteralPath '{identities}' -Raw | ConvertFrom-Json)
        if(@($sample.active_process_ids)-contains$owned[0].pid){{
            Set-Content -LiteralPath '{observed}' -Value 'observed'
            if(@($sample.active_process_ids)-notcontains$owned[1].pid){{
                Set-Content -LiteralPath '{orphan_observed}' -Value 'observed'
            }}
        }}
    }}
    return $sample
}}
$spec=[pscustomobject]@{{name='launcher';file_path=(Get-Process -Id $PID).Path;
    argument_list=@('-NoProfile','-NonInteractive','-EncodedCommand','{launcher_command}');
    stdout='{stdout}';stderr='{stderr}';environment=@{{}};working_directory='{root}'}}
$r=Invoke-ResourceBudgetedProcesses -DispatchPlanPath '{dispatch}' -RunDir '{root}' `
    -UsagePath '{usage}' -ProcessSpecifications @($spec)
if($r.resource_budget_exceeded-or$r.processes[0].exit_code-ne0){{exit 3}}
"""
            scheduler_log = root / "scheduler.log"
            try:
                # A real file preserves admission/lifecycle evidence without
                # an inherited anonymous PIPE delaying communicate().
                with scheduler_log.open("w", encoding="utf-8") as stream:
                    completed = subprocess.run(
                        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                        cwd=REPO_ROOT,
                        check=False,
                        stdout=stream,
                        stderr=subprocess.STDOUT,
                        timeout=15,
                    )
            except subprocess.TimeoutExpired as exc:
                self.fail(f"{exc}\n{scheduler_log.read_text(encoding='utf-8', errors='replace')}")
            finally:
                # Drain only this fixture's recorded process identities before
                # TemporaryDirectory attempts to remove their working directory.
                drain = f"""
$ErrorActionPreference='Stop'
if(Test-Path -LiteralPath '{identities}'){{
    foreach($owned in @(Get-Content -LiteralPath '{identities}' -Raw | ConvertFrom-Json)){{
        $process=Get-Process -Id $owned.pid -ErrorAction SilentlyContinue
        if($process-and$process.StartTime.ToUniversalTime().Ticks-eq$owned.started){{
            if(-not$process.WaitForExit(15000)){{throw 'fixture process failed to drain naturally'}}
        }}
    }}
}}
exit 0
"""
                drained = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", drain],
                    cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=35)
                self.assertEqual(drained.returncode, 0, drained.stdout + drained.stderr)
            self.assertEqual(
                completed.returncode,
                0,
                scheduler_log.read_text(encoding="utf-8", errors="replace"),
            )
            measured = json.loads(usage.read_text(encoding="utf-8-sig"))
            self.assertTrue(orphan_observed.is_file(), "worker was never sampled after launcher exit")
            self.assertEqual(measured["status"], "running")
            self.assertGreaterEqual(measured["wall_clock_seconds"], 1.5)
            self.assertGreater(measured["peak_process_tree_working_set_bytes"], 0)

    def test_parallel_wave_finishes_after_direct_simion_root_exits(self) -> None:
        """A stale helper sample cannot strand a completed direct SIMION batch."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dispatch = root / "dispatch.json"
            usage = root / "usage.json"
            dispatch.write_text(
                json.dumps(
                    {
                        "role": "simion_repository_dispatch_plan",
                        "particle_count": 1,
                        "estimation": {"kind": "exact_resource_profile"},
                        "limits": dispatch_limits(maximum_concurrency=1),
                    }
                ),
                encoding="utf-8",
            )
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                "function Get-SystemCpuPercent {0.0};"
                "function Get-RepositoryAvailableMemoryBytes {[int64](64GB)};"
                "function Start-RepositoryScheduledProcess {param($Specification);"
                "$p=Start-Process -FilePath (Get-Process -Id $PID).Path "
                "-ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 1') "
                "-PassThru -WindowStyle Hidden;"
                "[pscustomobject]@{name='direct_simion';specification=$Specification;process=$p;"
                "root_process_id=$p.Id;root_process_started_at_utc_ticks=[int64]$p.StartTime.ToUniversalTime().Ticks;"
                "started_at=(Get-RepositoryUtcNow);tracked_process_ids=@($p.Id);"
                "tracked_process_started_at_utc_ticks=@{([string]$p.Id)=[int64]$p.StartTime.ToUniversalTime().Ticks};"
                "active=$true;completed=$false;exit_code=$null;peak_working_set_bytes=[int64]0;"
                "peak_managed_memory_bytes=[int64]0;pressure_terminated=$false};"
                "};"
                "function Get-RepositoryProcessSnapshot {};"
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
            scheduler_log = root / "scheduler.log"
            try:
                with scheduler_log.open("w", encoding="utf-8") as stream:
                    completed = subprocess.run(
                        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                        cwd=REPO_ROOT,
                        check=False,
                        stdout=stream,
                        stderr=subprocess.STDOUT,
                        timeout=15,
                    )
            except subprocess.TimeoutExpired as exc:
                self.fail(f"{exc}\n{scheduler_log.read_text(encoding='utf-8', errors='replace')}")
            events = scheduler_log.read_text(encoding="utf-8", errors="replace")
            self.assertEqual(completed.returncode, 0, events)
            self.assertIn("SIMION_RESOURCE_EVENT=BATCH_WAVE_COMPLETED", events)

    def test_shared_observation_uses_common_danger_policy_and_resets_unknown_or_transient_pressure(self) -> None:
        support = REPO_ROOT / "common/resource_budget_support.ps1"
        command = f"""
. '{support}'
$script:now=[datetimeoffset]::UtcNow
function Get-RepositoryUtcNow {{$script:now}}
$script:available=[int64](100MB)
function Get-RepositoryAvailableMemoryBytes {{$script:available}}
function Get-RunDirectoryBytes {{throw 'No ordinary limits must not scan a run directory'}}
$observation=New-RepositoryProcessObservation
if($null-ne$observation.usage){{throw 'No-limit observer invented a usage payload'}}
$sample=[pscustomobject]@{{ancestry_complete=$true;working_set_bytes=0}}
if((Update-RepositoryProcessObservation -Observation $observation -Sample $sample).physical_danger){{exit 3}}
$script:now=$script:now.AddSeconds($observation.critical_seconds)
$sample.ancestry_complete=$false
if((Update-RepositoryProcessObservation -Observation $observation -Sample $sample).physical_danger){{exit 4}}
$sample.ancestry_complete=$true
if((Update-RepositoryProcessObservation -Observation $observation -Sample $sample).physical_danger){{exit 5}}
$script:available=[int64](8GB)
$null=Update-RepositoryProcessObservation -Observation $observation -Sample $sample
$script:available=[int64](100MB)
$null=Update-RepositoryProcessObservation -Observation $observation -Sample $sample
$script:now=$script:now.AddSeconds($observation.critical_seconds-1)
if((Update-RepositoryProcessObservation -Observation $observation -Sample $sample).physical_danger){{exit 6}}
$script:now=$script:now.AddSeconds(1)
if(-not(Update-RepositoryProcessObservation -Observation $observation -Sample $sample).physical_danger){{exit 7}}
$limits=[pscustomobject]@{{wall_clock_seconds=100;process_tree_working_set_bytes=100;transient_run_directory_bytes=100;minimum_system_available_memory_bytes=1}}
$metrics=New-RepositoryProcessObservation -Limits $limits -RunDir $env:TEMP -UsagePath (Join-Path $env:TEMP ('TEST_ONLY_never_published_'+[guid]::NewGuid().ToString('N')+'.json'))
$null=Update-RepositoryProcessObservation -Observation $metrics -Sample $sample
$script:now=$script:now.AddSeconds($metrics.critical_seconds)
if(-not(Update-RepositoryProcessObservation -Observation $metrics -Sample $sample).physical_danger){{throw 'Directory failure hid known physical danger'}}
function Get-RunDirectoryBytes {{return 0}}
function Write-ResourceUsage {{param($Usage,$Path);throw 'TEST_ONLY metrics write failure'}}
if(-not(Update-RepositoryProcessObservation -Observation $metrics -Sample $sample -Final).physical_danger){{throw 'Usage write failure hid known physical danger'}}
"""
        result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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
            support = REPO_ROOT / "common/resource_budget_support.ps1"
            command = (
                f". '{support}';{HOST_PERMIT_FIXTURE}"
                "$script:directoryMeasurements=0;"
                "function Get-RunDirectoryBytes {"
                "param([string]$RunDir);$script:directoryMeasurements+=1;"
                "if($script:directoryMeasurements-eq 1){return 0};return 2048};"
                f"$r=Invoke-ResourceBudgetedProcess -Limits ((Get-Content -LiteralPath '{budget}' -Raw|ConvertFrom-Json).limits) "
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
            self.assertEqual(measured["warning_names"], ["transient_run_directory_bytes"])

    def test_common_runners_reject_free_numerics_before_run_package(self) -> None:
        project = REPO_ROOT / "projects" / PROJECT_ID
        source = REPO_ROOT / ("projects/rf_multipole_ion_optics/config/sources/rf_multipole_family_mother_sample_v1_100.csv")
        budget = project / "variants/quadrupole/config/bare_transport_budget.json"
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
                str(REPO_ROOT / "projects/rf_multipole_ion_optics/runtime" / name),
                "-ProjectId",
                PROJECT_ID,
                "-RuntimeProfileId",
                "quadrupole_no_acceleration_full_length_n100_temporal_refined",
                "-DesignProfileId",
                "quadrupole_no_acceleration_full_length",
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
            run_dir = REPO_ROOT.parent / "artifacts/projects" / PROJECT_ID / "runs" / run_id
            self.assertFalse(run_dir.exists(), "rejected numerics created a run package")


if __name__ == "__main__":
    unittest.main()
