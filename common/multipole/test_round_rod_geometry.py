import json
import math
import unittest
from pathlib import Path

from common.multipole.resolve_finite_3d_contract import (
    Finite3DContractError,
    apply_connector_length_overrides,
    resolve_contract,
)
from common.multipole.interface_geometry import build_axial_interface_layout
from common.multipole.round_rod_geometry import build_round_rod_array, resolve_round_rod_geometry
from common.multipole.simion_geometry import (
    render_gem,
    render_grouped_rod_array_gem,
    render_segmented_rod_array_gem,
)
from common.multipole.compile_design_request import compile_design_request


ROOT = Path(__file__).resolve().parents[2]


class RoundRodGeometryTest(unittest.TestCase):
    def test_quadrupole_uses_same_array_generator(self):
        array = build_round_rod_array(
            radial_order_n=2,
            electrode_count=4,
            inscribed_radius_r0_mm=4.0,
            rod_radius_mm=4.592,
            rod_z_min_mm=5.8,
            rod_z_max_mm=85.4,
        )
        self.assertEqual([rod["electrode_group"] for rod in array["rods"]], [1, 2, 1, 2])
        positions = [(round(rod["center_x_mm"], 12), round(rod["center_y_mm"], 12)) for rod in array["rods"]]
        self.assertEqual(positions, [(8.592, 0.0), (0.0, 8.592), (-8.592, 0.0), (0.0, -8.592)])
        gem = render_grouped_rod_array_gem(array)
        self.assertIn("cylinder(8.592,0,0, 4.592,, 79.6)", gem)
        self.assertEqual(gem.count("fill { within { cylinder"), 4)

    def test_shared_interface_layout_supports_direct_and_connected_ends(self):
        base = {
            "aperture_radius_mm": 1.2,
            "plate_thickness_mm": 0.8,
            "rod_clearance_mm": 4.0,
            "connector_length_mm": 0.0,
            "connector_shape": "rectangular_bore",
            "particle_plane_distance_mm": 1.0,
        }
        exit_interface = dict(base, aperture_radius_mm=3.6, connector_length_mm=2.0)
        layout = build_axial_interface_layout(
            rod_z_min_mm=5.8,
            rod_z_max_mm=85.4,
            entrance=base,
            exit_interface=exit_interface,
        )
        self.assertEqual(layout["entrance"]["connector_length_mm"], 0.0)
        self.assertAlmostEqual(layout["entrance"]["particle_plane_z_mm"], 0.0)
        self.assertAlmostEqual(layout["exit"]["connector_z_max_mm"], 92.2)
        self.assertAlmostEqual(layout["exit"]["particle_plane_z_mm"], 93.2)

    def test_axial_layout_keeps_legacy_non_connector_contract_compatible(self):
        interface = {
            "aperture_radius_mm": 1.2,
            "plate_thickness_mm": 0.8,
            "rod_clearance_mm": 4.0,
            "connector_length_mm": 0.0,
            "particle_plane_distance_mm": 1.0,
        }
        layout = build_axial_interface_layout(
            rod_z_min_mm=5.8,
            rod_z_max_mm=85.4,
            entrance=interface,
            exit_interface=interface,
        )
        self.assertNotIn("connector_shape", layout["entrance"])

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
        self.assertEqual(geometry["interfaces_mm"]["entrance_connector_shape"], "cylindrical_bore")

    def test_same_geometry_exports_all_rods_to_simion(self):
        resolved = json.loads(
            (ROOT / "projects/rf_octupole_ion_guide/config/resolved_design.json").read_text()
        )
        gem = render_gem(resolved, 0.2)
        self.assertEqual(gem.count("e(1) { fill { within { cylinder"), 4)
        self.assertEqual(gem.count("e(2) { fill { within { cylinder"), 4)
        self.assertIn("planar,none", gem)
        self.assertIn(f"parent_resolved_sha256={resolved['resolved_sha256']}", gem)

    def test_positive_connector_shifts_planes_and_exports_tube(self):
        request = json.loads(
            (ROOT / "projects/rf_hexapole_ion_guide/config/requests/baseline.json").read_text()
        )
        request["geometry_mm"]["exit_interface"]["connector_length_mm"] = 2.0
        request["geometry_mm"]["enclosure"]["vacuum_z_max_mm"] += 2.0
        resolved = compile_design_request(request, expected_identity=request["identity"])
        self.assertEqual(resolved["interfaces_mm"]["exit"]["connector_length_mm"], 2.0)
        self.assertIn(",,2)", render_gem(resolved, 0.2))

    def test_finite_3d_contract_rejects_unknown_connector_shape(self):
        root = ROOT / "projects/rf_hexapole_ion_guide"
        baseline = json.loads((root / "config/baseline.json").read_text(encoding="utf-8"))
        contract = json.loads((root / "config/finite_3d_transport.json").read_text(encoding="utf-8"))
        contract["geometry_mm"]["entrance_interface"]["connector_shape"] = "square"
        with self.assertRaisesRegex(Finite3DContractError, "connector_shape"):
            resolve_contract(baseline, contract)

    def test_segmented_simion_geometry_separates_rods_ground_and_output(self):
        resolved = json.loads(
            (ROOT / "projects/rf_hexapole_ion_guide/config/resolved_design.json").read_text(
                encoding="utf-8"
            )
        )
        segmented = resolved["segmentation"]["segmented_rod_array"]
        gem = render_gem(resolved, 0.2)
        for electrode_id in range(1, 9):
            self.assertIn(f"e({electrode_id}) {{ fill {{ within {{ cylinder", gem)
        self.assertIn("e(9) { fill {", gem)
        self.assertIn("e(10) { fill {", gem)
        self.assertNotIn("e(3) { fill {\n    within { cylinder(0,0", gem)
        quad_gem = render_segmented_rod_array_gem(segmented)
        self.assertEqual(quad_gem.count("locate(0,0,"), 24)
        self.assertIn("e(8) { fill { within { cylinder(", quad_gem)
        first = segmented["electrodes"][0]
        self.assertIn(f"locate(0,0,{first['z_max_mm']:.15g})", quad_gem)

    def test_endplate_mode_keeps_continuous_rods_and_separates_output(self):
        resolved = json.loads(
            (ROOT / "projects/rf_hexapole_ion_guide/config/resolved_design.json").read_text()
        )
        with self.assertRaises(TypeError):
            render_gem(resolved, 0.2, separate_output_electrode=True)

    def test_connector_override_rejects_negative_length(self):
        root = ROOT / "projects/rf_hexapole_ion_guide"
        contract = json.loads((root / "config/finite_3d_transport.json").read_text(encoding="utf-8"))
        with self.assertRaises(Finite3DContractError):
            apply_connector_length_overrides(contract, entrance_connector_length_mm=-0.1)


if __name__ == "__main__":
    unittest.main()
