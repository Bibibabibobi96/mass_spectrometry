"""Solver-free regression tests for the dual-cone resolved geometry."""

from __future__ import annotations

import math
import unittest
from pathlib import Path

from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.geometry import (
    load_baseline,
    resolve_geometry,
    serialized,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = PROJECT_ROOT / "config" / "baseline.json"
DEFAULT_RESOLVED = PROJECT_ROOT / "config" / "resolved_geometry.json"


class GeometryContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolved = resolve_geometry(load_baseline(DEFAULT_BASELINE))

    def test_resolved_publication_is_fresh(self) -> None:
        self.assertEqual(
            DEFAULT_RESOLVED.read_text(encoding="utf-8"),
            serialized(self.resolved),
        )
        core_root = PROJECT_ROOT.parents[1] / "src" / "msplatform"
        core_modules = [
            *(core_root / "components" / PROJECT_ROOT.name).glob("*.py"),
            core_root / "backends" / "simion" / "dual_cone_geometry.py",
        ]
        for module in core_modules:
            with self.subTest(module=module.name):
                source = module.read_text(encoding="utf-8")
                self.assertNotIn("PROJECT_ROOT", source)
                self.assertNotIn("DEFAULT_", source)
                self.assertNotIn("__file__", source)
                self.assertNotIn('"projects"', source)

    def test_user_dimensions_derive_expected_clear_radii_and_positions(self) -> None:
        geometry = self.resolved["geometry_mm"]
        stage_1 = geometry["stage_1_elliptical_quadrupole"]
        stage_2 = geometry["stage_2_round_quadrupole"]
        self.assertAlmostEqual(stage_1["ideal_field_radius_r0_mm"], 3.74)
        self.assertAlmostEqual(stage_1["rod_array"]["rod_center_radius"], 5.62)
        self.assertEqual(stage_1["rod_array"]["cross_section"]["shape"], "ellipse")
        self.assertAlmostEqual(
            stage_2["rod_array"]["rod_center_radius"],
            5.64 / math.sqrt(2.0),
        )
        self.assertAlmostEqual(
            stage_2["ideal_field_radius_r0_mm"],
            5.64 / math.sqrt(2.0) - 2.39,
        )
        self.assertAlmostEqual(stage_2["upstream_flat_start_z_mm"], 55.8)
        self.assertAlmostEqual(stage_1["downstream_flat_end_z_mm"], 53.8)
        self.assertAlmostEqual(geometry["interstage"]["clear_gap_mm"], 2.0)
        plate = geometry["downstream_aperture_plate"]
        self.assertAlmostEqual(plate["upstream_face_z_mm"], 110.22)
        self.assertAlmostEqual(plate["downstream_face_z_mm"], 110.72)
        self.assertAlmostEqual(plate["aperture_radius_mm"], 0.75)
        self.assertAlmostEqual(plate["downstream_observation_end_z_mm"], 120.0)
        self.assertAlmostEqual(plate["post_plate_observation_length_mm"], 9.28)

    def test_invalid_round_rod_overlap_fails(self) -> None:
        baseline = load_baseline(DEFAULT_BASELINE)
        baseline["geometry_mm"]["round_quadrupole"]["rod_radius_mm"] = 5.0
        with self.assertRaisesRegex(ValueError, "overlap"):
            resolve_geometry(baseline)


if __name__ == "__main__":
    unittest.main()
