from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.machine_contracts import (
    ContractError,
    REPO_ROOT,
    validate_schema,
)
from common.contracts.file_identity import repository_text_sha256
from common.integration.resolve_connection import (
    load_connection_profile_registry,
    resolve_connection_profile,
    verify_composition_plan,
    write_resolved_and_plan,
)


class ResolveConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temporary.name)
        self.upstream_relative = "projects/upstream/config/interfaces/provided/exit.json"
        self.downstream_relative = "projects/downstream/config/interfaces/required/entry.json"
        self.upstream_path = self.repo_root / self.upstream_relative
        self.downstream_path = self.repo_root / self.downstream_relative
        self.upstream_source_relative = "projects/upstream/config/baseline.json"
        self.downstream_source_relative = "projects/downstream/config/baseline.json"
        self.upstream_source_path = self.repo_root / self.upstream_source_relative
        self.downstream_source_path = self.repo_root / self.downstream_source_relative
        self._write_json(
            self.upstream_source_path,
            {"interface": {"aperture_radius_mm": 2.5}},
        )
        self._write_json(
            self.downstream_source_path,
            {"interface": {"aperture_radius_mm": 2.5}},
        )
        self.upstream = self._port(
            "upstream", "exit", "provided", [0.0, 0.0, 0.0], [0.0, 0.0, 1.0]
        )
        self.downstream = self._port(
            "downstream", "entry", "required", [0.0, 0.0, 1.0], [0.0, 0.0, -1.0]
        )
        self.upstream["authority"] = self._authority(
            self.upstream_source_relative, self.upstream_source_path
        )
        self.downstream["authority"] = self._authority(
            self.downstream_source_relative, self.downstream_source_path
        )
        self.profile = {
            "schema_version": 1,
            "integration_id": "upstream_to_downstream",
            "connection_profile_id": "grounded_tube",
            "upstream": {
                "project_id": "upstream",
                "port_id": "exit",
                "port_contract": self.upstream_relative,
            },
            "downstream": {
                "project_id": "downstream",
                "port_id": "entry",
                "port_contract": self.downstream_relative,
            },
            "coupling_mode": "state_handoff",
            "spatial_registration": {
                "rotation_upstream_to_downstream": [
                    [1.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0],
                    [0.0, 0.0, 1.0],
                ],
                "translation_mm": [0.0, 0.0, 0.0],
                "expected_gap_mm": 1.0,
                "position_tolerance_mm": 1e-6,
                "angular_tolerance_rad": 1e-6,
            },
            "connector": {
                "length_mm": 1.0,
                "inner_radius_mm": 2.0,
                "wall_thickness_mm": 0.5,
            },
            "transition_aperture": {
                "shape": "rectangle",
                "full_width_mm": 3.0,
                "full_height_mm": 3.2,
                "width_axis_downstream_frame": [1.0, 0.0, 0.0],
                "height_axis_downstream_frame": [0.0, 1.0, 0.0],
            },
            "minimum_clear_radius_mm": 1.5,
            "potential_alignment": {"mode": "continuous", "tolerance_V": 1e-9},
            "clock_alignment": {"mode": "same_origin", "offset_s": 0.0},
            "field_ownership_segments": [
                {"start_mm": 0.0, "end_mm": 1.0, "owner": "field_free"}
            ],
        }
        self.registry_path = self.repo_root / "profiles.json"
        self._write_inputs()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _port(
        project_id: str,
        port_id: str,
        direction: str,
        center: list[float],
        normal: list[float],
    ) -> dict:
        return {
            "schema_version": 1,
            "role": "component_port",
            "project_id": project_id,
            "port_id": port_id,
            "direction": direction,
            "profile_scope": {
                "scope_id": "test_profile",
                "scope_kind": "design_profile",
                "family_experiment_port": False,
            },
            "state_contract": {
                "schema_id": "component_particle_state",
                "schema_version": 1,
            },
            "coordinate_frame": {
                "frame_id": f"{project_id}_frame",
                "length_unit": "mm",
                "handedness": "right_handed",
            },
            "mating_surface": {
                "center_mm": center,
                "outward_normal": normal,
                "aperture_radius_mm": 2.5,
                "potential_V": 0.0,
            },
            "clock": {"time_unit": "s", "origin_id": "instrument_trigger"},
            "field_boundary": {"field_reaches_surface": False},
        }

    @staticmethod
    def _authority(relative: str, source_path: Path) -> dict:
        return {
            "source_contract": relative,
            "source_sha256": repository_text_sha256(source_path),
            "bindings": [
                {
                    "port_json_pointer": "/mating_surface/aperture_radius_mm",
                    "source_json_pointer": "/interface/aperture_radius_mm",
                }
            ],
        }

    def _write_json(self, path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def _write_inputs(self) -> None:
        self._write_json(self.upstream_path, self.upstream)
        self._write_json(self.downstream_path, self.downstream)
        self._write_json(
            self.registry_path,
            {
                "schema_version": 1,
                "role": "connection_profile_registry",
                "integration_id": "upstream_to_downstream",
                "profiles": [self.profile],
            },
        )

    def _resolve(self) -> dict:
        registry = load_connection_profile_registry(self.registry_path)
        return resolve_connection_profile(
            registry, "grounded_tube", repo_root=self.repo_root
        )

    def test_resolves_explicit_five_tuple_and_source_hashes(self) -> None:
        resolved = self._resolve()
        self.assertEqual(
            resolved["selection"],
            {
                "upstream_project_id": "upstream",
                "upstream_port_id": "exit",
                "downstream_project_id": "downstream",
                "downstream_port_id": "entry",
                "connection_profile_id": "grounded_tube",
            },
        )
        self.assertEqual(resolved["compatibility"]["status"], "pass")
        self.assertEqual(len(resolved["sources"]["profile_sha256"]), 64)
        self.assertEqual(resolved["effective_clear_radius_mm"], 1.5)
        self.assertEqual(
            resolved["port_geometry"]["upstream"]["coordinate_frame"],
            self.upstream["coordinate_frame"],
        )
        self.assertEqual(
            resolved["port_geometry"]["downstream"]["mating_surface"],
            self.downstream["mating_surface"],
        )
        self.assertEqual(
            resolved["port_geometry"]["upstream"]["clock"],
            {"time_unit": "s", "origin_id": "instrument_trigger"},
        )
        self.assertEqual(
            resolved["port_geometry"]["downstream"]["clock"],
            {"time_unit": "s", "origin_id": "instrument_trigger"},
        )
        self.assertEqual(
            resolved["transition_aperture"],
            {
                "shape": "rectangle",
                "coordinate_frame_id": "downstream_frame",
                "center_mm": [0.0, 0.0, 1.0],
                "surface_normal": [0.0, 0.0, -1.0],
                "full_width_mm": 3.0,
                "full_height_mm": 3.2,
                "width_axis": [1.0, 0.0, 0.0],
                "height_axis": [0.0, 1.0, 0.0],
            },
        )
        self.assertNotIn("transition_aperture", self.upstream)
        self.assertNotIn("transition_aperture", self.downstream)

    def test_writes_and_reverifies_frozen_composition_plan(self) -> None:
        resolved_path = self.repo_root / "output/resolved_connection.json"
        plan_path = self.repo_root / "output/composition_plan.json"
        write_resolved_and_plan(
            self.registry_path,
            "grounded_tube",
            resolved_path,
            plan_path,
            repo_root=self.repo_root,
        )
        verify_composition_plan(plan_path, resolved_path, repo_root=self.repo_root)
        resolved = json.loads(resolved_path.read_text(encoding="utf-8"))
        resolved["effective_clear_radius_mm"] = 1.9
        self._write_json(resolved_path, resolved)
        with self.assertRaisesRegex(ContractError, "SHA-256 is stale"):
            verify_composition_plan(plan_path, resolved_path, repo_root=self.repo_root)

    def test_reverification_rejects_changed_component_port(self) -> None:
        resolved_path = self.repo_root / "output/resolved_connection.json"
        plan_path = self.repo_root / "output/composition_plan.json"
        write_resolved_and_plan(
            self.registry_path,
            "grounded_tube",
            resolved_path,
            plan_path,
            repo_root=self.repo_root,
        )
        self.upstream["mating_surface"]["aperture_radius_mm"] = 2.4
        self._write_json(self.upstream_path, self.upstream)
        with self.assertRaisesRegex(ContractError, "source SHA-256 is stale"):
            verify_composition_plan(
                plan_path, resolved_path, repo_root=self.repo_root
            )

    def test_rejects_stale_authority_and_binding_value_drift(self) -> None:
        self.upstream["authority"]["source_sha256"] = "A" * 64
        self._write_inputs()
        with self.assertRaisesRegex(ContractError, "authority source SHA-256 is stale"):
            self._resolve()
        self.upstream["authority"]["source_sha256"] = repository_text_sha256(
            self.upstream_source_path
        )
        self.upstream["mating_surface"]["aperture_radius_mm"] = 2.4
        self._write_inputs()
        with self.assertRaisesRegex(ContractError, "binding value differs"):
            self._resolve()

    def test_rejects_wrong_port_identity_and_direction(self) -> None:
        self.upstream["direction"] = "required"
        self._write_inputs()
        with self.assertRaisesRegex(ContractError, "direction must be provided"):
            self._resolve()
        self.upstream["direction"] = "provided"
        self.upstream["port_id"] = "other_exit"
        self._write_inputs()
        with self.assertRaisesRegex(ContractError, "identity differs"):
            self._resolve()

    def test_rejects_component_port_without_profile_scope(self) -> None:
        del self.upstream["profile_scope"]
        self._write_inputs()
        with self.assertRaises(ContractError):
            self._resolve()

    def test_rejects_normal_gap_and_rotation_conflicts(self) -> None:
        self.downstream["mating_surface"]["outward_normal"] = [0.0, 0.0, 1.0]
        self._write_inputs()
        with self.assertRaisesRegex(ContractError, "normals are not opposed"):
            self._resolve()
        self.downstream["mating_surface"]["outward_normal"] = [0.0, 0.0, -1.0]
        self.profile["spatial_registration"]["expected_gap_mm"] = 2.0
        self._write_inputs()
        with self.assertRaisesRegex(ContractError, "gap differs"):
            self._resolve()
        self.profile["spatial_registration"]["expected_gap_mm"] = 1.0
        self.profile["spatial_registration"]["rotation_upstream_to_downstream"][0][0] = 2.0
        self._write_inputs()
        with self.assertRaisesRegex(ContractError, "not orthonormal"):
            self._resolve()

    def test_rejects_aperture_potential_and_clock_conflicts(self) -> None:
        self.profile["minimum_clear_radius_mm"] = 2.1
        self.profile["connector"]["inner_radius_mm"] = 2.0
        self._write_inputs()
        with self.assertRaisesRegex(ContractError, "aperture"):
            self._resolve()
        self.profile["minimum_clear_radius_mm"] = 1.5
        self.downstream["mating_surface"]["potential_V"] = 1.0
        self._write_inputs()
        with self.assertRaisesRegex(ContractError, "potential step"):
            self._resolve()
        self.downstream["mating_surface"]["potential_V"] = 0.0
        self.downstream["clock"]["origin_id"] = "other_trigger"
        self._write_inputs()
        with self.assertRaisesRegex(ContractError, "clock alignment"):
            self._resolve()

    def test_rejects_transition_aperture_axis_conflicts(self) -> None:
        aperture = self.profile["transition_aperture"]
        aperture["width_axis_downstream_frame"] = [2.0, 0.0, 0.0]
        self._write_inputs()
        with self.assertRaisesRegex(ContractError, "width axis is not a unit vector"):
            self._resolve()

        aperture["width_axis_downstream_frame"] = [0.0, 0.0, 1.0]
        self._write_inputs()
        with self.assertRaisesRegex(ContractError, "not in the downstream mating plane"):
            self._resolve()

        aperture["width_axis_downstream_frame"] = [1.0, 0.0, 0.0]
        aperture["height_axis_downstream_frame"] = [1.0, 0.0, 0.0]
        self._write_inputs()
        with self.assertRaisesRegex(ContractError, "in-plane axes are not orthogonal"):
            self._resolve()

    def test_transition_aperture_is_an_effective_clearance_not_a_threshold(self) -> None:
        self.profile["minimum_clear_radius_mm"] = 0.4
        self.profile["transition_aperture"]["full_width_mm"] = 1.0
        self.profile["transition_aperture"]["full_height_mm"] = 0.9
        self._write_inputs()
        resolved = self._resolve()
        self.assertEqual(resolved["effective_clear_radius_mm"], 0.45)
        self.assertEqual(self.profile["minimum_clear_radius_mm"], 0.4)

    def test_profile_rejects_a_second_transition_aperture_center_authority(self) -> None:
        self.profile["transition_aperture"]["center_mm"] = [0.0, 0.0, 1.0]
        self._write_inputs()
        with self.assertRaises(ContractError):
            self._resolve()

    def test_declared_clock_offset_preserves_both_materialized_origins(self) -> None:
        self.downstream["clock"]["origin_id"] = "downstream_trigger"
        self.profile["clock_alignment"] = {
            "mode": "declared_offset",
            "offset_s": 2.5e-6,
        }
        self._write_inputs()
        resolved = self._resolve()
        self.assertEqual(
            resolved["port_geometry"]["upstream"]["clock"]["origin_id"],
            "instrument_trigger",
        )
        self.assertEqual(
            resolved["port_geometry"]["downstream"]["clock"]["origin_id"],
            "downstream_trigger",
        )
        self.assertEqual(resolved["clock_alignment"]["offset_s"], 2.5e-6)

    def test_rejects_field_gap_overlap_and_missing_overlap_owner(self) -> None:
        self.profile["field_ownership_segments"] = [
            {"start_mm": 0.1, "end_mm": 1.0, "owner": "field_free"}
        ]
        self._write_inputs()
        with self.assertRaisesRegex(ContractError, "field responsibility has a gap"):
            self._resolve()
        self.profile["field_ownership_segments"] = [
            {"start_mm": 0.0, "end_mm": 0.6, "owner": "upstream"},
            {"start_mm": 0.5, "end_mm": 1.0, "owner": "downstream"},
        ]
        self._write_inputs()
        with self.assertRaisesRegex(ContractError, "field responsibility has a overlap"):
            self._resolve()
        self.profile["field_ownership_segments"] = [
            {"start_mm": 0.0, "end_mm": 1.0, "owner": "upstream"}
        ]
        self.profile["coupling_mode"] = "field_overlap"
        self._write_inputs()
        with self.assertRaisesRegex(ContractError, "integration-owned"):
            self._resolve()

    def test_rejects_field_responsibility_missing_at_active_port(self) -> None:
        self.upstream["field_boundary"]["field_reaches_surface"] = True
        self._write_inputs()
        with self.assertRaisesRegex(ContractError, "upstream field responsibility"):
            self._resolve()
        self.upstream["field_boundary"]["field_reaches_surface"] = False
        self.downstream["field_boundary"]["field_reaches_surface"] = True
        self._write_inputs()
        with self.assertRaisesRegex(ContractError, "downstream field responsibility"):
            self._resolve()

    def test_zero_length_direct_handoff_has_no_connector_field_segment(self) -> None:
        self.downstream["mating_surface"]["center_mm"] = [0.0, 0.0, 1e-14]
        registration = self.profile["spatial_registration"]
        registration["expected_gap_mm"] = 0.0
        self.profile["connector"]["length_mm"] = 0.0
        self.profile["field_ownership_segments"] = []
        self._write_inputs()
        resolved = self._resolve()
        self.assertEqual(resolved["spatial_registration"]["actual_gap_mm"], 0.0)

    def test_validate_only_powershell_entry_rechecks_plan(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("pwsh is unavailable")
        resolved_path = self.repo_root / "output/resolved_connection.json"
        plan_path = self.repo_root / "output/composition_plan.json"
        write_resolved_and_plan(
            self.registry_path,
            "grounded_tube",
            resolved_path,
            plan_path,
            repo_root=self.repo_root,
        )
        completed = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-File",
                str(REPO_ROOT / "common/integration/execute_connection.ps1"),
                "-CompositionPlan",
                str(plan_path),
                "-ResolvedConnection",
                str(resolved_path),
                "-PythonExe",
                sys.executable,
                "-RepoRoot",
                str(self.repo_root),
                "-ValidateOnly",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("INTEGRATION_EXECUTION=VALIDATED", completed.stdout)

    def test_integration_registry_and_artifact_identity_schemas(self) -> None:
        validate_schema(
            {
                "schema_version": 1,
                "role": "integration_registry",
                "integrations": [
                    {
                        "integration_id": "upstream_to_downstream",
                        "root": "integrations/upstream_to_downstream",
                        "profile_registry": (
                            "integrations/upstream_to_downstream/config/"
                            "connection_profiles.json"
                        ),
                    }
                ],
            },
            "integration_registry.schema.json",
        )
        validate_schema(
            {
                "schema_version": 1,
                "integration_id": "upstream_to_downstream",
                "run_id": "20260728_120000__test__cross__connection",
                "selection": {
                    "upstream_project_id": "upstream",
                    "upstream_port_id": "exit",
                    "downstream_project_id": "downstream",
                    "downstream_port_id": "entry",
                    "connection_profile_id": "grounded_tube",
                },
                "composition_plan": {
                    "path": "composition_plan.json",
                    "sha256": "A" * 64,
                },
                "source_projects": [
                    {
                        "project_id": "upstream",
                        "port_id": "exit",
                        "descriptor_sha256": "B" * 64,
                    },
                    {
                        "project_id": "downstream",
                        "port_id": "entry",
                        "descriptor_sha256": "C" * 64,
                    },
                ],
            },
            "integration_artifact_identity.schema.json",
        )


if __name__ == "__main__":
    unittest.main()
