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
LEGACY_S2_CANDIDATE_PATH = (
    REPO_ROOT
    / "projects"
    / "rf_quadrupole_ion_optics"
    / "docs"
    / "history"
    / "20260729__superseded-rf-oatof-s2-s3-active-contracts"
    / "config__rf_to_oatof_s2_passive_connector.json"
)
OATOF_REQUIRED_PORT_PATH = (
    REPO_ROOT
    / "projects"
    / "single_reflection_oa_tof_mass_analyzer"
    / "config"
    / "interfaces"
    / "required"
    / "oatof_accelerator_entry.json"
)
PRE_PULSE_PHASE_PATH = (
    REPO_ROOT
    / "projects"
    / "rf_quadrupole_ion_optics"
    / "config"
    / "rf_to_oatof_pre_pulse_passive_connector.json"
)
PULSE_CAPTURE_PHASE_PATH = PRE_PULSE_PHASE_PATH.with_name(
    "rf_to_oatof_pulse_capture.json"
)


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
            "rf_quadrupole_grounded_connector_gap_1mm"
        ]
        gap_zero = self.profiles[
            "rf_quadrupole_direct_mating_gap_0mm"
        ]
        self.assertEqual(gap_one["connector"]["length_mm"], 1.0)
        self.assertEqual(gap_one["connector"]["inner_radius_mm"], 3.6)
        self.assertEqual(gap_zero["connector"]["length_mm"], 0.0)
        self.assertEqual(gap_zero["connector"]["inner_radius_mm"], 3.6)
        self.assertEqual(gap_zero["minimum_clear_radius_mm"], 0.45)
        legacy_aperture = load_json(LEGACY_S2_CANDIDATE_PATH)[
            "passive_connector_geometry"
        ]["downstream_entry_aperture"]
        for profile in (gap_one, gap_zero):
            aperture = profile["transition_aperture"]
            self.assertEqual(aperture["shape"], legacy_aperture["shape"])
            self.assertEqual(
                aperture["full_width_mm"],
                legacy_aperture["full_width_y_mm"],
            )
            self.assertEqual(
                aperture["full_height_mm"],
                legacy_aperture["full_height_z_mm"],
            )
            self.assertEqual(
                aperture["width_axis_downstream_frame"],
                [0.0, 1.0, 0.0],
            )
            self.assertEqual(
                aperture["height_axis_downstream_frame"],
                [0.0, 0.0, 1.0],
            )
        self.assertIn(
            "1.0 mm by 0.9 mm",
            self.oracle["profile_interpretation"]["direct_mating_inner_radius_mm"],
        )
        oracle_by_source_case = {
            item["source_case"]: item for item in self.oracle["profiles"]
        }
        self.assertEqual(
            oracle_by_source_case["nominal_gap_1mm"]["census"]["oatof_entry"],
            61,
        )
        self.assertEqual(
            oracle_by_source_case["direct_mating_gap_0mm"]["census"]["detector_hit"],
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
        downstream_port = load_json(OATOF_REQUIRED_PORT_PATH)
        self.assertEqual(
            downstream_port["mating_surface"]["aperture_radius_mm"],
            5.0,
        )
        self.assertNotIn("transition_aperture", downstream_port)
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
            self.assertEqual(resolved["effective_clear_radius_mm"], 0.45)
            self.assertEqual(
                resolved["port_geometry"]["downstream"]["mating_surface"],
                downstream_port["mating_surface"],
            )
            self.assertEqual(
                resolved["transition_aperture"]["center_mm"],
                downstream_port["mating_surface"]["center_mm"],
            )
            self.assertEqual(
                resolved["transition_aperture"]["coordinate_frame_id"],
                downstream_port["coordinate_frame"]["frame_id"],
            )
            self.assertEqual(
                resolved["transition_aperture"]["full_width_mm"],
                1.0,
            )
            self.assertEqual(
                resolved["transition_aperture"]["full_height_mm"],
                0.9,
            )
            self.assertNotIn(
                "aperture_radius_mm",
                resolved["transition_aperture"],
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
                        (REPO_ROOT / arguments["workflow_entrypoint"]).is_file()
                    )
                    self.assertEqual(
                        arguments["workflow_entrypoint"],
                        "projects/rf_quadrupole_ion_optics/workflows/"
                        "rf_to_oatof_integration/run_rf_to_oatof_transfer.ps1",
                    )
                    self.assertEqual(
                        set(arguments),
                        {"workflow_entrypoint", "adapter_registry_sha256"},
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
        self.assertIn("& $workflowEntrypoint", adapter)
        self.assertNotIn("Start-Job", adapter)
        self.assertNotIn("ForEach-Object -Parallel", adapter)

    def test_execute_fails_before_solver_without_run_id_or_authorization(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is unavailable")
        temporary_root = REPO_ROOT / ".tmp"
        temporary_root.mkdir(exist_ok=True)
        entrypoint = INTEGRATION_ROOT / "execute_integration.ps1"
        profile_id = "rf_quadrupole_grounded_connector_gap_1mm"
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

    def test_phase_configuration_has_no_connection_topology_authority(self) -> None:
        forbidden_keys = {
            "nominal_registration",
            "passive_connector_geometry",
            "connector_gap_mm",
            "length_mm",
            "inner_radius_mm",
            "downstream_entry_aperture",
            "target_entry_center_instrument_mm",
            "source_exit_center_instrument_mm",
            "connector_cases",
        }

        def collect_keys(value: object) -> set[str]:
            if isinstance(value, dict):
                return set(value) | set().union(
                    *(collect_keys(item) for item in value.values())
                )
            if isinstance(value, list):
                return set().union(*(collect_keys(item) for item in value))
            return set()

        for path, expected_phase in (
            (PRE_PULSE_PHASE_PATH, "pre_pulse_interface_transport"),
            (PULSE_CAPTURE_PHASE_PATH, "pulse_capture"),
        ):
            with self.subTest(path=path.name):
                phase = load_json(path)
                self.assertEqual(phase["phase"], expected_phase)
                self.assertEqual(phase["topology_source"], "resolved_connection")
                self.assertFalse(collect_keys(phase) & forbidden_keys)

    def test_active_pre_pulse_runner_requires_resolved_connection(self) -> None:
        runner = (
            REPO_ROOT
            / "projects"
            / "rf_quadrupole_ion_optics"
            / "workflows"
            / "rf_to_oatof_integration"
            / "comsol"
            / "run_pre_pulse_interface_transport.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("[Parameter(Mandatory)][string]$ConnectionProfileId", runner)
        self.assertIn("[Parameter(Mandatory)][string]$ResolvedConnection", runner)
        self.assertIn("resolvedConnectionDocument.connector.length_mm", runner)
        self.assertNotIn("ConnectorCaseId", runner)
        self.assertNotIn("connector_cases", runner)


if __name__ == "__main__":
    unittest.main()
