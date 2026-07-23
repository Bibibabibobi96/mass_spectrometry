from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from projects.rf_quadrupole_collision_cooling.analysis import (
    resolve_spatial_registration as resolver,
)
from common.contracts.spatial_registration import write_or_check_release


class RfOatofSpatialRegistrationTests(unittest.TestCase):
    def test_active_s2_registration_publishes_one_mm_gap(self) -> None:
        release = resolver.resolve_stage(resolver.S2)
        self.assertEqual(release["project_semantics"]["stage"], "S2")
        self.assertEqual(release["project_semantics"]["connector_gap_mm"], 1.0)
        transform = release["derived_relative_transform"]["transform"]
        self.assertEqual(
            transform["rotation"],
            [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        )
        source_x = release["resolved_surfaces"]["source_exit"][
            "in_instrument_frame"
        ]["center_mm"][0]
        target_x = release["resolved_surfaces"]["target_entry"][
            "in_instrument_frame"
        ]["center_mm"][0]
        self.assertAlmostEqual(target_x - source_x, 1.0)
        source_paths = {item["path"] for item in release["sources"]}
        self.assertIn(
            "projects/rf_quadrupole_collision_cooling/config/"
            "rf_to_oatof_shared_physical_port_joint_geometry.json",
            source_paths,
        )
        self.assertNotIn(
            "projects/rf_quadrupole_collision_cooling/config/"
            "rf_to_oatof_interface_candidate.json",
            source_paths,
        )
        common_binding = release["authoritative_scalar_bindings"][
            "interface_common_reference"
        ]
        self.assertEqual(
            common_binding["json_pointer"],
            "/electrical_interface/common_potential_reference/potential_V",
        )
        self.assertTrue(
            common_binding["source"]["path"].endswith(
                "rf_to_oatof_shared_physical_port_joint_geometry.json"
            )
        )

    def test_source_hash_drift_changes_release(self) -> None:
        with tempfile.TemporaryDirectory(dir=resolver.PROJECT_ROOT) as temporary:
            root = Path(temporary)
            stage = root / "stage.json"
            shared = root / "shared.json"
            stage.write_text(
                resolver.S2.read_text(encoding="utf-8"), encoding="utf-8"
            )
            shared.write_text(
                resolver.SHARED_JOINT.read_text(encoding="utf-8"), encoding="utf-8"
            )
            first = resolver.resolve_stage(stage, shared)
            document = json.loads(stage.read_text(encoding="utf-8"))
            document["qualification_scope"] += "_hash_drift"
            stage.write_text(json.dumps(document), encoding="utf-8")
            second = resolver.resolve_stage(stage, shared)
            first_hashes = {item["path"]: item["sha256"] for item in first["sources"]}
            second_hashes = {
                item["path"]: item["sha256"] for item in second["sources"]
            }
            self.assertNotEqual(first_hashes, second_hashes)

    def test_changed_resolved_exit_republishes_surface_and_pose(self) -> None:
        baseline = resolver.resolve_stage(resolver.S2)
        with tempfile.TemporaryDirectory(dir=resolver.PROJECT_ROOT) as temporary:
            root = Path(temporary)
            stage = root / "stage.json"
            rf_resolved = root / "resolved_design.json"
            shared = root / "shared.json"
            stage_document = json.loads(resolver.S2.read_text(encoding="utf-8"))
            stage_document["nominal_registration"]["source_exit_center_local_mm"][
                2
            ] = 100.2
            stage_document["nominal_registration"]["source_component_pose"][
                "translation_mm"
            ][0] -= 10.0
            stage.write_text(json.dumps(stage_document), encoding="utf-8")
            document = json.loads(
                (
                    resolver.PROJECT_ROOT
                    / "config"
                    / "resolved_design_official.json"
                ).read_text(encoding="utf-8")
            )
            document["interfaces_mm"]["exit"][
                "connector_z_max_mm"
            ] += 10.0
            rf_resolved.write_text(json.dumps(document), encoding="utf-8")
            shared_document = json.loads(
                resolver.SHARED_JOINT.read_text(encoding="utf-8")
            )
            shared_document["physical_boundaries"]["source_exit_surface"][
                "local_center_mm"
            ][2] = 100.2
            shared.write_text(json.dumps(shared_document), encoding="utf-8")
            changed = resolver.resolve_stage(
                stage,
                shared,
                rf_resolved_path=rf_resolved,
            )
            self.assertEqual(
                changed["resolved_surfaces"]["source_exit"]["declared"][
                    "center_mm"
                ][2],
                100.2,
            )
            self.assertEqual(
                changed["project_semantics"]["source_exit_center_instrument_mm"],
                baseline["project_semantics"][
                    "source_exit_center_instrument_mm"
                ],
            )
            self.assertAlmostEqual(
                changed["component_poses"]["rf_quadrupole_component"][
                    "translation_mm"
                ][0],
                baseline["component_poses"]["rf_quadrupole_component"][
                    "translation_mm"
                ][0]
                - 10.0,
            )
            output = root / "resolved_registration.json"
            write_or_check_release(output, baseline, check=False)
            with self.assertRaisesRegex(ValueError, "stale or missing"):
                write_or_check_release(output, changed, check=True)


if __name__ == "__main__":
    unittest.main()
