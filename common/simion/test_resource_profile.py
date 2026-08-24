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
            "waves": [{"kind": "bootstrap", "batch_count": 1}],
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
        self.assertEqual(profiles[0]["resource_identity"]["field_kind"], "rf")

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
