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
    def test_frozen_s1_gap_zero_and_s2_gap_one(self) -> None:
        for source, stage, gap in (
            (resolver.S1, "S1", 0.0),
            (resolver.S2, "S2", 1.0),
        ):
            with self.subTest(stage=stage):
                release = resolver.resolve_stage(source)
                self.assertEqual(release["project_semantics"]["stage"], stage)
                self.assertEqual(
                    release["project_semantics"]["connector_gap_mm"], gap
                )
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
                self.assertAlmostEqual(target_x - source_x, gap)

    def test_source_hash_drift_changes_release(self) -> None:
        with tempfile.TemporaryDirectory(dir=resolver.PROJECT_ROOT) as temporary:
            root = Path(temporary)
            stage = root / "stage.json"
            interface = root / "interface.json"
            stage.write_text(
                resolver.S2.read_text(encoding="utf-8"), encoding="utf-8"
            )
            interface.write_text(
                resolver.INTERFACE.read_text(encoding="utf-8"), encoding="utf-8"
            )
            first = resolver.resolve_stage(stage, interface)
            document = json.loads(stage.read_text(encoding="utf-8"))
            document["qualification_scope"] += "_hash_drift"
            stage.write_text(json.dumps(document), encoding="utf-8")
            second = resolver.resolve_stage(stage, interface)
            first_hashes = {item["path"]: item["sha256"] for item in first["sources"]}
            second_hashes = {
                item["path"]: item["sha256"] for item in second["sources"]
            }
            self.assertNotEqual(first_hashes, second_hashes)

    def test_changed_resolved_exit_republishes_surface_and_pose(self) -> None:
        baseline = resolver.resolve_stage(resolver.S2)
        with tempfile.TemporaryDirectory(dir=resolver.PROJECT_ROOT) as temporary:
            root = Path(temporary)
            rf_resolved = root / "resolved_design.json"
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
            changed = resolver.resolve_stage(
                resolver.S2,
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
