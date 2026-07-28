"""Static contract tests for the RF-multipole to single-reflection oaTOF integration."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.machine_contracts import validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.prepare_migration import (
    prepare_migration,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
PROFILE_REGISTRY_PATH = INTEGRATION_ROOT / "config" / "connection_profiles.json"
ORACLE_PATH = INTEGRATION_ROOT / "config" / "migration_oracles.json"
ADAPTER_REGISTRY_PATH = INTEGRATION_ROOT / "config" / "execution_adapter_profiles.json"
PREREGISTRATION_PATH = (
    INTEGRATION_ROOT / "config" / "migration_equivalence_preregistration.json"
)
GLOBAL_REGISTRY_PATH = REPO_ROOT / "integrations" / "registry.json"


def load_json(path: Path) -> dict:
    """Load a UTF-8 JSON object used by this integration."""
    return json.loads(path.read_text(encoding="utf-8"))


class IntegrationProfileContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_json(PROFILE_REGISTRY_PATH)
        cls.profiles = {
            profile["connection_profile_id"]: profile
            for profile in cls.registry["profiles"]
        }
        cls.oracle = load_json(ORACLE_PATH)

    def test_global_registry_points_to_single_profile_authority(self) -> None:
        registry = load_json(GLOBAL_REGISTRY_PATH)
        validate_schema(registry, "integration_registry.schema.json")
        self.assertEqual(len(registry["integrations"]), 1)
        entry = registry["integrations"][0]
        self.assertEqual(
            entry["integration_id"],
            self.registry["integration_id"],
        )
        self.assertEqual(
            (REPO_ROOT / entry["profile_registry"]).resolve(),
            PROFILE_REGISTRY_PATH.resolve(),
        )

    def test_only_resolved_quadrupole_profiles_are_registered(self) -> None:
        self.assertEqual(len(self.profiles), len(self.registry["profiles"]))
        self.assertEqual(len(self.profiles), 2)
        self.assertEqual(
            {profile["upstream"]["project_id"] for profile in self.profiles.values()},
            {"rf_quadrupole_ion_optics"},
        )
        validate_schema(
            self.registry,
            "connection_profile_registry.schema.json",
        )

    def test_quadrupole_oracles_preserve_gap_and_census(self) -> None:
        gap_one = self.profiles[
            "rf_quadrupole_s2_s3_grounded_connector_gap_1mm"
        ]
        gap_zero = self.profiles[
            "rf_quadrupole_s2_s3_direct_mating_gap_0mm"
        ]
        self.assertEqual(gap_one["connector"]["length_mm"], 1.0)
        self.assertEqual(gap_one["connector"]["inner_radius_mm"], 3.6)
        self.assertEqual(gap_zero["connector"]["length_mm"], 0.0)
        self.assertEqual(gap_zero["minimum_clear_radius_mm"], 0.45)
        oracle_by_id = {
            item["connection_profile_id"]: item
            for item in self.oracle["profiles"]
        }
        self.assertEqual(
            oracle_by_id[gap_one["connection_profile_id"]]["census"]["oatof_entry"],
            61,
        )
        self.assertEqual(
            oracle_by_id[gap_zero["connection_profile_id"]]["census"]["detector_hit"],
            9,
        )
        for source in self.oracle["shared_sources"].values():
            self.assertTrue((REPO_ROOT / source).is_file(), source)

    def test_ports_and_common_resolver_close_the_static_plan(self) -> None:
        from common.integration.resolve_connection import (
            load_connection_profile_registry,
            resolve_connection_profile,
        )

        registry = load_connection_profile_registry(PROFILE_REGISTRY_PATH)
        for profile_id in sorted(self.profiles):
            resolved = resolve_connection_profile(
                registry,
                profile_id,
                repo_root=REPO_ROOT,
            )
            self.assertEqual(
                resolved["selection"]["connection_profile_id"],
                profile_id,
            )

    def test_integration_owned_planner_freezes_nonempty_real_adapter_steps(self) -> None:
        temporary_root = REPO_ROOT / ".tmp"
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            for profile_id in sorted(self.profiles):
                with self.subTest(profile_id=profile_id):
                    output = Path(directory) / profile_id
                    resolved_path, plan_path = prepare_migration(
                        repo_root=REPO_ROOT,
                        profile_registry_path=PROFILE_REGISTRY_PATH,
                        adapter_registry_path=ADAPTER_REGISTRY_PATH,
                        preregistration_path=PREREGISTRATION_PATH,
                        profile_id=profile_id,
                        resolved_output=output / "resolved.json",
                        plan_output=output / "plan.json",
                    )
                    self.assertTrue(resolved_path.is_file())
                    plan = load_json(plan_path)
                    self.assertEqual(len(plan["execution_steps"]), 1)
                    step = plan["execution_steps"][0]
                    self.assertTrue((REPO_ROOT / step["entrypoint"]).is_file())
                    arguments = dict(item.split("=", 1) for item in step["arguments"])
                    self.assertTrue(
                        (REPO_ROOT / arguments["legacy_s2_entrypoint"]).is_file()
                    )
                    self.assertTrue(
                        (REPO_ROOT / arguments["legacy_s3_entrypoint"]).is_file()
                    )

    def test_prepare_only_runs_both_profiles_without_solver_execution(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is unavailable")
        temporary_root = REPO_ROOT / ".tmp"
        temporary_root.mkdir(exist_ok=True)
        entrypoint = INTEGRATION_ROOT / "execute_integration.ps1"
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            for profile_id in sorted(self.profiles):
                completed = subprocess.run(
                    [
                        pwsh,
                        "-NoProfile",
                        "-File",
                        str(entrypoint),
                        "-ConnectionProfileId",
                        profile_id,
                        "-OutputDirectory",
                        str(Path(directory) / profile_id),
                        "-PythonExe",
                        sys.executable,
                        "-PrepareOnly",
                    ],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    timeout=30,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    completed.stdout + completed.stderr,
                )
                self.assertIn("INTEGRATION_ADAPTER=PREPARED", completed.stdout)
                self.assertIn("EQUIVALENCE=BLOCKED/NOT_RUN", completed.stdout)

    def test_execute_boundary_requires_run_id_authorization_and_serial_adapter(self) -> None:
        common_execute = (
            REPO_ROOT / "common" / "integration" / "execute_connection.ps1"
        ).read_text(encoding="utf-8")
        adapter = (INTEGRATION_ROOT / "adapter.ps1").read_text(encoding="utf-8")
        self.assertIn("explicit RunId", common_execute)
        self.assertIn("explicit solver authorization", common_execute)
        self.assertIn("repository integrations tree", common_execute)
        self.assertIn(
            "AdapterEntrypoint differs from the frozen composition plan",
            common_execute,
        )
        self.assertIn("& $s3Entrypoint", adapter)
        self.assertNotIn("Start-Job", adapter)
        self.assertNotIn("ForEach-Object -Parallel", adapter)

    def test_execute_fails_before_solver_without_run_id_or_authorization(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is unavailable")
        temporary_root = REPO_ROOT / ".tmp"
        temporary_root.mkdir(exist_ok=True)
        entrypoint = INTEGRATION_ROOT / "execute_integration.ps1"
        profile_id = "rf_quadrupole_s2_s3_grounded_connector_gap_1mm"
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            common = [
                pwsh,
                "-NoProfile",
                "-File",
                str(entrypoint),
                "-ConnectionProfileId",
                profile_id,
                "-PythonExe",
                sys.executable,
            ]
            missing_run = subprocess.run(
                [*common, "-OutputDirectory", str(Path(directory) / "missing_run")],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=30,
            )
            self.assertNotEqual(missing_run.returncode, 0)
            self.assertIn("explicit RunId", missing_run.stdout + missing_run.stderr)
            missing_authorization = subprocess.run(
                [
                    *common,
                    "-OutputDirectory",
                    str(Path(directory) / "missing_authorization"),
                    "-RunId",
                    "20260728_120000__integration_migration_test",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=30,
            )
            self.assertNotEqual(missing_authorization.returncode, 0)
            self.assertIn(
                "explicit solver authorization",
                missing_authorization.stdout + missing_authorization.stderr,
            )


if __name__ == "__main__":
    unittest.main()
