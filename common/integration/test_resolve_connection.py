from __future__ import annotations

import json
import math
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
from common.contracts.file_identity import file_sha256, repository_text_sha256
from common.integration.resolve_connection import (
    derive_direct_mating_translation,
    derive_mating_translation_with_gap,
    load_connection_profile_registry,
    resolve_connection_profile,
    verify_composition_plan,
    write_resolved_and_plan,
)


class ResolveConnectionTests(unittest.TestCase):
    def test_direct_mating_translation_is_derived_from_both_port_centers(self) -> None:
        rotation = [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        self.assertEqual(
            derive_direct_mating_translation(
                rotation, [0.0, 0.0, 80.6], [-88.0, 0.0, -18.4]
            ),
            [-168.6, 0.0, -18.4],
        )

    def test_zero_gap_translation_is_exactly_direct_mating(self) -> None:
        rotation = [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        direct = derive_direct_mating_translation(
            rotation, [0.0, 0.0, 80.6], [-88.0, 0.0, -18.4]
        )
        with_gap = derive_mating_translation_with_gap(
            rotation,
            [0.0, 0.0, 80.6],
            [0.0, 0.0, 1.0],
            [-88.0, 0.0, -18.4],
            0.0,
        )
        self.assertEqual(with_gap, direct)

    def test_gap_translation_separates_centers_along_rotated_normal(self) -> None:
        rotation = [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        translation = derive_mating_translation_with_gap(
            rotation,
            [0.0, 0.0, 80.6],
            [0.0, 0.0, 1.0],
            [-88.0, 0.0, -18.4],
            3.2,
        )
        self.assertEqual(translation, [-171.79999999999998, 0.0, -18.4])
        transformed_center = [
            sum(row[index] * [0.0, 0.0, 80.6][index] for index in range(3))
            + translation[row_index]
            for row_index, row in enumerate(rotation)
        ]
        transformed_normal = [row[2] for row in rotation]
        separation = [
            downstream - upstream
            for downstream, upstream in zip(
                [-88.0, 0.0, -18.4], transformed_center, strict=True
            )
        ]
        for actual, expected in zip(
            separation,
            [3.2 * component for component in transformed_normal],
            strict=True,
        ):
            self.assertAlmostEqual(actual, expected, delta=1e-12)

    def test_gap_translation_rejects_negative_gap_and_nonunit_normal(self) -> None:
        identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        with self.assertRaisesRegex(ContractError, "gap must be nonnegative"):
            derive_mating_translation_with_gap(
                identity,
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                -1.0,
            )
        with self.assertRaisesRegex(ContractError, "normal must be a unit vector"):
            derive_mating_translation_with_gap(
                identity,
                [0.0, 0.0, 0.0],
                [2.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                1.0,
            )

    def test_gap_translation_respects_negative_outward_normal_direction(self) -> None:
        identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        translation = derive_mating_translation_with_gap(
            identity,
            [0.0, 0.0, 0.0],
            [-1.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            2.0,
        )
        self.assertEqual(translation, [2.0, 0.0, 0.0])

    def test_gap_translation_rejects_nonrigid_rotation(self) -> None:
        with self.assertRaisesRegex(ContractError, "rotation is not orthonormal"):
            derive_mating_translation_with_gap(
                [[2.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                1.0,
            )

    def test_direct_mating_translation_keeps_invalid_input_failures(self) -> None:
        identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        with self.assertRaisesRegex(ContractError, "requires 3D rotation and centers"):
            derive_direct_mating_translation(
                identity[:2], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]
            )
        with self.assertRaisesRegex(ContractError, "inputs must be finite"):
            derive_direct_mating_translation(
                identity, [0.0, 0.0, math.nan], [1.0, 0.0, 0.0]
            )

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self.temporary.name)
        self.repo_root = self.workspace_root / "simulation_repo"
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

    def _write_artifact_inputs(self) -> Path:
        artifact_relative = Path(
            "artifacts/projects/upstream/runs/"
            "20260803_120000__test__cross__connection/inputs"
        )
        source_relative = (artifact_relative / "baseline.json").as_posix()
        port_relative = (artifact_relative / "exit.json").as_posix()
        registry_relative = (artifact_relative / "profiles.json").as_posix()
        source_path = self.workspace_root / source_relative
        port_path = self.workspace_root / port_relative
        registry_path = self.workspace_root / registry_relative

        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(
            b'{\r\n  "interface": {"aperture_radius_mm": 2.5}\r\n}\r\n'
        )
        artifact_port = json.loads(json.dumps(self.upstream))
        artifact_port["authority"] = self._authority(source_relative, source_path)
        artifact_port["authority"]["source_sha256"] = file_sha256(source_path)
        self._write_json(port_path, artifact_port)

        artifact_profile = json.loads(json.dumps(self.profile))
        artifact_profile["upstream"]["port_contract"] = port_relative
        self._write_json(
            registry_path,
            {
                "schema_version": 1,
                "role": "connection_profile_registry",
                "integration_id": "upstream_to_downstream",
                "profiles": [artifact_profile],
            },
        )
        return registry_path

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

    def test_static_upstream_binding_requires_run_local_materialization(self) -> None:
        template = json.loads(json.dumps(self.profile))
        template["upstream"].pop("port_contract")
        template["upstream"]["port_binding"] = "source_run_resolved_design"
        registry = {
            "schema_version": 1,
            "role": "connection_profile_registry",
            "integration_id": "upstream_to_downstream",
            "profiles": [template],
        }
        validate_schema(template, "connection_profile.schema.json")
        with self.assertRaisesRegex(ContractError, "port binding is unresolved"):
            resolve_connection_profile(
                registry, "grounded_tube", repo_root=self.repo_root
            )

        run_local = json.loads(json.dumps(registry))
        upstream = run_local["profiles"][0]["upstream"]
        upstream.pop("port_binding")
        upstream["port_contract"] = self.upstream_relative
        resolved = resolve_connection_profile(
            run_local, "grounded_tube", repo_root=self.repo_root
        )
        self.assertEqual(resolved["compatibility"]["status"], "pass")

    def test_upstream_binding_is_exclusive_and_downstream_requires_contract(self) -> None:
        invalid_upstream = json.loads(json.dumps(self.profile))
        invalid_upstream["upstream"]["port_binding"] = (
            "source_run_resolved_design"
        )
        with self.assertRaises(ContractError):
            validate_schema(invalid_upstream, "connection_profile.schema.json")

        invalid_downstream = json.loads(json.dumps(self.profile))
        invalid_downstream["downstream"].pop("port_contract")
        invalid_downstream["downstream"]["port_binding"] = (
            "source_run_resolved_design"
        )
        with self.assertRaises(ContractError):
            validate_schema(invalid_downstream, "connection_profile.schema.json")

    def test_active_connection_publications_are_mode_neutral(self) -> None:
        integration_config = (
            REPO_ROOT
            / "integrations"
            / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
            / "config"
        )
        active = [
            integration_config / "connection_profiles.json",
            integration_config / "execution_adapter_profiles.json",
            integration_config / "experiment_campaign.json",
            *[
                integration_config
                / f"family_{family}_direct_mating_gap_0mm_runtime_binding.json"
                for family in ("quadrupole", "hexapole", "octupole")
            ],
        ]
        for path in active:
            with self.subTest(path=path.name):
                self.assertNotIn(
                    "no_acceleration",
                    path.read_text(encoding="utf-8"),
                )

    def test_repository_authority_keeps_normalized_text_identity(self) -> None:
        payload = self.upstream_source_path.read_bytes().replace(b"\r\n", b"\n")
        self.upstream_source_path.write_bytes(payload.replace(b"\n", b"\r\n"))
        resolved = self._resolve()
        authority = resolved["sources"]["upstream_authority"]
        self.assertEqual(
            authority["sha256"],
            repository_text_sha256(self.upstream_source_path),
        )
        self.assertNotEqual(authority["sha256"], file_sha256(self.upstream_source_path))

    def test_artifact_registry_port_and_authority_use_raw_byte_identity(self) -> None:
        registry_path = self._write_artifact_inputs()
        resolved_path = self.repo_root / "output/resolved_connection.json"
        plan_path = self.repo_root / "output/composition_plan.json"
        write_resolved_and_plan(
            registry_path,
            "grounded_tube",
            resolved_path,
            plan_path,
            repo_root=self.repo_root,
        )
        resolved = json.loads(resolved_path.read_text(encoding="utf-8"))
        sources = resolved["sources"]
        for name in ("profile_registry", "upstream_port", "upstream_authority"):
            self.assertTrue(sources[name]["path"].startswith("artifacts/projects/"))
            self.assertFalse(Path(sources[name]["path"]).is_absolute())
        authority_path = self.workspace_root / sources["upstream_authority"]["path"]
        self.assertEqual(sources["upstream_authority"]["sha256"], file_sha256(authority_path))
        self.assertNotEqual(
            sources["upstream_authority"]["sha256"],
            repository_text_sha256(authority_path),
        )
        verify_composition_plan(plan_path, resolved_path, repo_root=self.repo_root)

    def test_artifact_authority_rejects_stale_raw_byte_hash(self) -> None:
        registry_path = self._write_artifact_inputs()
        registry = load_connection_profile_registry(registry_path)
        authority_path = self.workspace_root / registry["profiles"][0]["upstream"][
            "port_contract"
        ]
        port = json.loads(authority_path.read_text(encoding="utf-8"))
        source_path = self.workspace_root / port["authority"]["source_contract"]
        source_path.write_bytes(source_path.read_bytes().replace(b"\r\n", b"\n"))
        with self.assertRaisesRegex(ContractError, "authority source SHA-256 is stale"):
            resolve_connection_profile(
                registry, "grounded_tube", repo_root=self.repo_root
            )

    def test_rejects_workspace_top_level_and_parent_traversal(self) -> None:
        outside = self.workspace_root / "scratch" / "profiles.json"
        self._write_json(outside, json.loads(self.registry_path.read_text(encoding="utf-8")))
        with self.assertRaisesRegex(ContractError, "outside repository and artifacts/projects"):
            write_resolved_and_plan(
                outside,
                "grounded_tube",
                self.repo_root / "output/resolved_connection.json",
                self.repo_root / "output/composition_plan.json",
                repo_root=self.repo_root,
            )
        traversing = self.repo_root / ".." / "scratch" / "profiles.json"
        with self.assertRaisesRegex(ContractError, "parent traversal"):
            write_resolved_and_plan(
                traversing,
                "grounded_tube",
                self.repo_root / "output/resolved_connection.json",
                self.repo_root / "output/composition_plan.json",
                repo_root=self.repo_root,
            )

    def test_port_path_schemas_reject_absolute_and_parent_traversal(self) -> None:
        for invalid in (
            "C:/outside/exit.json",
            "projects/upstream/../outside/exit.json",
            "artifacts/other/exit.json",
        ):
            port = json.loads(json.dumps(self.upstream))
            port["authority"]["source_contract"] = invalid
            with self.subTest(contract="component_port", path=invalid):
                with self.assertRaises(ContractError):
                    validate_schema(port, "component_port.schema.json")
            profile = json.loads(json.dumps(self.profile))
            profile["upstream"]["port_contract"] = invalid
            with self.subTest(contract="connection_profile", path=invalid):
                with self.assertRaises(ContractError):
                    validate_schema(profile, "connection_profile.schema.json")

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
