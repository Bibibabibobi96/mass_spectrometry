from __future__ import annotations

import json
import unittest
from pathlib import Path

from common.multipole.prepare_quadrupole_finite_3d_inputs import build_inputs


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPO_ROOT / "projects" / "rf_quadrupole_collision_cooling"


class PrepareQuadrupoleFinite3DInputsTests(unittest.TestCase):
    @staticmethod
    def identity() -> dict[str, object]:
        return {
            "identity": {
                "project_id": "rf_quadrupole_collision_cooling",
                "family_id": "rf_multipole_ion_optics",
                "radial_order_n": 2,
                "electrode_count": 4,
                "coordinate_convention_id": "multipole.cartesian.z_axis.v1",
                "voltage_convention_id": "multipole.pair_about_common_mode.zero_to_peak.v1",
                "r0_convention_id": "nearest_ideal_electrode_surface.v1",
            }
        }

    def test_preserves_reference_geometry_and_n100_source(self) -> None:
        load = lambda path: json.loads(path.read_text(encoding="utf-8"))
        resolved = load(PROJECT_ROOT / "config" / "resolved_geometry.json")
        inputs = build_inputs(
            resolved,
            self.identity(),
            PROJECT_ROOT / "config" / "particles" / "official_fixed_100.ion",
        )
        contract = inputs["contract"]
        self.assertEqual(len(inputs["particle_source"]), 100)
        self.assertEqual(contract["geometry_model"], "rectangular_reference_enclosure_v1")
        self.assertEqual(contract["derived_geometry_mm"]["rod_z_max"], 85.4)
        self.assertEqual(contract["derived_geometry_mm"]["detector_z"], 95.2)
        self.assertEqual(contract["geometry_mm"]["entrance_interface"]["aperture_radius_mm"], 1.2)
        self.assertEqual(contract["geometry_mm"]["entrance_interface"]["connector_shape"], "rectangular_bore")
        self.assertEqual(inputs["round_rod_geometry"]["array_mm"], resolved["rod_array_mm"])
        self.assertAlmostEqual(inputs["particle_source"][0]["z_mm"], 0.0)

    def test_zero_and_positive_connector_lengths_share_one_contract(self) -> None:
        resolved = json.loads(
            (PROJECT_ROOT / "config" / "resolved_geometry.json").read_text(encoding="utf-8")
        )
        particles = PROJECT_ROOT / "config" / "particles" / "official_fixed_100.ion"
        zero = build_inputs(resolved, self.identity(), particles, 0.0, 0.0)
        positive = build_inputs(resolved, self.identity(), particles, 0.5, 1.0)
        self.assertEqual(zero["contract"]["geometry_mm"]["entrance_interface"]["connector_length_mm"], 0.0)
        self.assertEqual(positive["contract"]["geometry_mm"]["entrance_interface"]["connector_length_mm"], 0.5)
        self.assertEqual(positive["contract"]["geometry_mm"]["exit_interface"]["connector_length_mm"], 1.0)

    def test_rejects_connector_that_overlaps_source_plane(self) -> None:
        resolved = json.loads(
            (PROJECT_ROOT / "config" / "resolved_geometry.json").read_text(encoding="utf-8")
        )
        particles = PROJECT_ROOT / "config" / "particles" / "official_fixed_100.ion"
        with self.assertRaisesRegex(ValueError, "source plane"):
            build_inputs(resolved, self.identity(), particles, 1.1, 0.0)


if __name__ == "__main__":
    unittest.main()
