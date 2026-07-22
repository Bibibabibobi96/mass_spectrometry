import json
import math
import unittest
from pathlib import Path

from common.multipole.resolve_finite_3d_contract import resolve_contract
from common.multipole.round_rod_geometry import resolve_round_rod_geometry
from common.multipole.simion_geometry import render_gem


ROOT = Path(__file__).resolve().parents[2]


class RoundRodGeometryTest(unittest.TestCase):
    def resolve(self, project: str, ratio: float):
        root = ROOT / "projects" / project
        baseline = json.loads((root / "config/baseline.json").read_text(encoding="utf-8"))
        contract = json.loads((root / "config/finite_3d_transport.json").read_text(encoding="utf-8"))
        finite = resolve_contract(baseline, contract)
        r0 = baseline["geometry_mm"]["inscribed_radius_r0"]
        metrics = {"selected_candidate": {
            "rod_radius_mm": ratio * r0,
            "rod_center_radius_mm": (1 + ratio) * r0,
        }}
        return resolve_round_rod_geometry(baseline, finite, metrics)

    def test_hexapole_and_octupole_share_one_generator(self):
        for project, count, ratio in (
            ("rf_hexapole_ion_guide", 6, 0.55),
            ("rf_octupole_ion_guide", 8, 0.36),
        ):
            geometry = self.resolve(project, ratio)
            rods = geometry["array_mm"]["rods"]
            self.assertEqual(len(rods), count)
            self.assertEqual([rod["electrode_group"] for rod in rods], [1, 2] * (count // 2))
            for rod in rods:
                radius = math.hypot(rod["center_x_mm"], rod["center_y_mm"])
                self.assertAlmostEqual(radius, geometry["array_mm"]["rod_center_radius"])

    def test_zero_length_connector_is_direct_connection(self):
        geometry = self.resolve("rf_hexapole_ion_guide", 0.55)
        self.assertEqual(geometry["interfaces_mm"]["entrance_connector_length"], 0.0)
        self.assertEqual(geometry["interfaces_mm"]["exit_connector_length"], 0.0)

    def test_same_geometry_exports_all_rods_to_simion(self):
        geometry = self.resolve("rf_octupole_ion_guide", 0.36)
        gem = render_gem(geometry, 0.2)
        self.assertEqual(gem.count("e(1) { fill { within { cylinder"), 4)
        self.assertEqual(gem.count("e(2) { fill { within { cylinder"), 4)
        self.assertIn("planar,none", gem)
        self.assertIn("cylinder(6.2,0,79.6,2.2,,79.6)", render_gem(self.resolve("rf_hexapole_ion_guide", 0.55), 0.2))

    def test_positive_connector_shifts_planes_and_exports_tube(self):
        root = ROOT / "projects/rf_hexapole_ion_guide"
        baseline = json.loads((root / "config/baseline.json").read_text(encoding="utf-8"))
        contract = json.loads((root / "config/finite_3d_transport.json").read_text(encoding="utf-8"))
        contract["geometry_mm"]["exit_interface"]["connector_length_mm"] = 2.0
        finite = resolve_contract(baseline, contract)
        metrics = {"selected_candidate": {"rod_radius_mm": 2.2, "rod_center_radius_mm": 6.2}}
        geometry = resolve_round_rod_geometry(baseline, finite, metrics)
        self.assertAlmostEqual(finite["derived_geometry_mm"]["detector_z"], 83.1)
        self.assertIn("cylinder(0,0,82.6,21,,2)", render_gem(geometry, 0.2))


if __name__ == "__main__":
    unittest.main()
