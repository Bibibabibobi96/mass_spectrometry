import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.simion.resource_profile import (
    discover_case_resource_profiles,
    discover_resource_profiles,
    publish_resource_profile,
)


class ResourceProfileTests(unittest.TestCase):
    def write_bootstrap_run(self, root: Path, name: str = "run") -> Path:
        run = root / name
        (run / "inputs").mkdir(parents=True)
        (run / "results").mkdir()
        plan = {
            "role": "simion_repository_dispatch_plan",
            "resource_identity": {"solver": "SIMION", "field_kind": "rf", "rf_steps_per_period": 40},
            "waves": [{"kind": "bootstrap", "batch_count": 1, "batches": [{"count": 1}]}],
        }
        usage = {
            "role": "multipole_resource_usage", "status": "completed",
            "peak_process_tree_working_set_bytes": 123,
        }
        plan_path, usage_path = run / "inputs" / "simion_repository_dispatch_plan.json", run / "results" / "resource_usage.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        usage_path.write_text(json.dumps(usage), encoding="utf-8")
        profile = publish_resource_profile(run_id=name, resource_usage_path=usage_path, dispatch_plan_path=plan_path)
        profile_path = run / "results" / "simion_resource_profile.json"
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
        manifest = {
            "role": "simulation_run_manifest", "status": "success", "run_id": name,
            "outputs": [{"path": str(profile_path), "sha256": file_sha256(profile_path)}],
        }
        (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return run

    def test_publish_and_discover_completed_single_process_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_bootstrap_run(root)
            profiles = discover_resource_profiles(root)
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["per_batch_peak_working_set_bytes"], 123)
        self.assertEqual(profiles[0]["observed_batch_work_units"], 1)
        self.assertEqual(profiles[0]["resource_identity"]["field_kind"], "rf")

    def test_formal_profile_uses_conservative_managed_memory_peak(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "formal"
            (run / "inputs").mkdir(parents=True)
            (run / "results").mkdir()
            plan = {
                "role": "simion_repository_dispatch_plan",
                "resource_identity": {"solver": "SIMION", "field_kind": "electrostatic"},
                "estimation": {"per_process_cpu_percent": 10.0,
                               "per_process_cpu_budget_percent": 10.5,
                               "cpu_demand_safety_factor": 1.05},
                "waves": [{"kind": "scheduled", "batch_count": 1, "batches": [{"count": 1}]}],
            }
            usage = {
                "role": "multipole_resource_usage", "status": "completed",
                "first_formal_observation": {
                    "peak_working_set_bytes": 100,
                    "peak_managed_memory_bytes": 250,
                    "process_cpu_percent": 6.2,
                },
            }
            plan_path = run / "inputs" / "dispatch.json"
            usage_path = run / "results" / "usage.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            usage_path.write_text(json.dumps(usage), encoding="utf-8")
            profile = publish_resource_profile(
                run_id="formal", resource_usage_path=usage_path, dispatch_plan_path=plan_path
            )
        self.assertEqual(profile["per_batch_peak_working_set_bytes"], 250)
        self.assertEqual(profile["per_batch_cpu_percent"], 6.2)

    def test_profile_keeps_peak_and_count_from_the_same_measured_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = self.write_bootstrap_run(Path(directory))
            plan_path = run / "inputs/simion_repository_dispatch_plan.json"
            plan = json.loads(plan_path.read_text())
            plan["waves"] = [{"kind": "scheduled", "batch_count": 2,
                              "batches": [{"count": 10}, {"count": 7}]}]
            plan_path.write_text(json.dumps(plan))
            usage_path = run / "results/resource_usage.json"
            usage = {
                "role": "multipole_resource_usage", "status": "completed",
                "peak_process_tree_managed_memory_bytes": 1000000,
                "first_formal_observation": {"peak_managed_memory_bytes": 100,
                                             "process_cpu_percent": 0.0},
                "per_process_memory_observation": {
                    "process": "TEST_ONLY_batch_two", "work_units": 7,
                    "root_process_id": 123, "root_process_started_at_utc_ticks": 456,
                },
            }
            for worker_peak, expected_peak, expected_count in ((250, 250, 7), (80, 100, 10), (100, 100, 10)):
                with self.subTest(worker_peak=worker_peak):
                    usage["per_process_memory_observation"]["peak_managed_memory_bytes"] = worker_peak
                    usage_path.write_text(json.dumps(usage))
                    profile = publish_resource_profile(run_id="run", resource_usage_path=usage_path,
                                                       dispatch_plan_path=plan_path)
                    self.assertEqual(profile["per_batch_peak_working_set_bytes"], expected_peak)
                    self.assertEqual(profile["observed_batch_work_units"], expected_count)
                    self.assertEqual("per_batch_cpu_percent" in profile, worker_peak <= 100)
            usage["per_process_memory_observation"]["work_units"] = 0
            usage_path.write_text(json.dumps(usage))
            with self.assertRaisesRegex(ValueError, "worker work-unit count"):
                publish_resource_profile(run_id="run", resource_usage_path=usage_path, dispatch_plan_path=plan_path)

    def test_historical_missing_loading_policy_remains_unspecified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.write_bootstrap_run(root)
            profile_path = run / "results" / "simion_resource_profile.json"
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["resource_identity"].pop("field_loading_policy_id")
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            manifest_path = run / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["outputs"][0]["sha256"] = file_sha256(profile_path)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(discover_resource_profiles(root), [profile])
            profile["resource_identity"]["unrecognized_loading_claim"] = "changed"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            manifest["outputs"][0]["sha256"] = file_sha256(profile_path)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(discover_resource_profiles(root), [])

    def test_publish_rejects_parallel_or_noncompleted_measurements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.write_bootstrap_run(root)
            usage_path = run / "results" / "resource_usage.json"
            usage = json.loads(usage_path.read_text(encoding="utf-8"))
            usage["execution_wave"] = {"process_count": 2}
            usage_path.write_text(json.dumps(usage), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly one process"):
                publish_resource_profile(run_id="run", resource_usage_path=usage_path, dispatch_plan_path=run / "inputs" / "simion_repository_dispatch_plan.json")

    def test_discovers_manifest_bound_log_usage_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.write_bootstrap_run(root)
            usage = run / "results" / "resource_usage.json"
            log_usage = run / "logs" / "resource_usage.json"
            log_usage.parent.mkdir()
            usage.replace(log_usage)
            plan = run / "inputs" / "simion_repository_dispatch_plan.json"
            profile = publish_resource_profile(
                run_id=run.name, resource_usage_path=log_usage, dispatch_plan_path=plan,
                resource_usage_relative_path="logs/resource_usage.json",
            )
            profile_path = run / "results" / "simion_resource_profile.json"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            manifest_path = run / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["outputs"][0]["sha256"] = file_sha256(profile_path)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(discover_resource_profiles(root), [profile])

    def test_discovery_ignores_tampered_profile_and_non_success_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.write_bootstrap_run(root)
            profile_path = run / "results" / "simion_resource_profile.json"
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            profile["per_batch_peak_working_set_bytes"] = 1
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            self.assertEqual(discover_resource_profiles(root), [])
            self.write_bootstrap_run(root, "failed")
            failed_manifest = root / "failed" / "run_manifest.json"
            document = json.loads(failed_manifest.read_text(encoding="utf-8"))
            document["status"] = "failed"
            failed_manifest.write_text(json.dumps(document), encoding="utf-8")
            self.assertEqual(discover_resource_profiles(root), [])

    def test_case_profiles_require_a_successful_manifest_bound_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "case-run"
            run.mkdir()
            summary = run / "summary.json"
            summary.write_text(json.dumps({
                "role": "oatof_radial_compaction_campaign_summary",
                "simion_case_resource_profiles": [{
                    "resource_identity": {
                        "solver": "SIMION", "field_kind": "electrostatic",
                        "case_input_sha256": "A" * 64,
                    },
                    "per_batch_peak_working_set_bytes": 456,
                }],
            }), encoding="utf-8")
            manifest = run / "run_manifest.json"
            manifest.write_text(json.dumps({
                "role": "simulation_run_manifest", "status": "success", "run_id": "case-run",
                "outputs": [{"path": str(summary), "sha256": file_sha256(summary)}],
            }), encoding="utf-8")
            profiles = discover_case_resource_profiles(root)
            self.assertEqual(len(profiles), 1)
            self.assertEqual(profiles[0]["per_batch_peak_working_set_bytes"], 456)
            summary.write_text("{}", encoding="utf-8")
            self.assertEqual(discover_case_resource_profiles(root), [])

    def test_cli_discovers_only_verified_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_bootstrap_run(root)
            output = root / "profiles.json"
            result = subprocess.run(
                [sys.executable, "-m", "common.simion.resource_profile", "discover", "--runs-root", str(root), "--output", str(output)],
                cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("SIMION_RESOURCE_PROFILES=PASS COUNT=1", result.stdout)
            self.assertEqual(len(json.loads(output.read_text(encoding="utf-8"))), 1)
