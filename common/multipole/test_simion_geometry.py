from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.multipole.round_rod_geometry import build_rod_array
from common.multipole.simion_geometry import (
    render_axis_mapped_segmented_rod_array_gem,
    render_gem,
    render_grouped_rod_array_gem,
)


def resolved_design(
    connector_shape: str,
    length_mm: float,
    *,
    enclosure_model: str = "cylindrical_grounded_shield_v1",
) -> dict:
    if enclosure_model == "cylindrical_grounded_shield_v1":
        enclosure = {
            "model": enclosure_model,
            "working_region_radius_mm": 3.0,
            "vacuum_z_min_mm": 0.0,
            "vacuum_z_max_mm": 20.0,
            "shield_inner_radius_mm": 9.0,
            "shield_outer_radius_mm": 10.0,
            "entrance_outer_endcap_upstream_face_z_mm": 0.0,
            "entrance_outer_endcap_downstream_face_z_mm": 0.5,
            "exit_outer_endcap_upstream_face_z_mm": 19.5,
            "exit_outer_endcap_downstream_face_z_mm": 20.0,
        }
    else:
        enclosure = {
            "model": enclosure_model,
            "working_region_radius_mm": 3.0,
            "vacuum_z_min_mm": 0.0,
            "vacuum_z_max_mm": 20.0,
            "outer_half_width_mm": 10.0,
            "inner_half_width_mm": 9.0,
            "exit_enclosure_z_min_mm": 15.0,
            "exit_enclosure_z_max_mm": 20.0,
            "exit_front_wall_end_z_mm": 16.0,
            "physical_detector_radius_mm": 1.2,
            "physical_detector_thickness_mm": 0.5,
        }
    rod = {
        "rod_id": 1,
        "electrode_group": 1,
        "angle_rad": 0.0,
        "center_x_mm": 4.0,
        "center_y_mm": 0.0,
        "z_min_mm": 2.0,
        "z_max_mm": 15.0,
        "radius_mm": 1.0,
    }
    return {
        "role": "multipole_resolved_design_do_not_edit",
        "resolved_sha256": "A" * 64,
        "geometry_mm": {
            "enclosure": enclosure,
            "rod_array": {"rods": [rod]},
        },
        "interfaces_mm": {
            "entrance": {
                "aperture_plate_upstream_face_z_mm": 1.0,
                "aperture_plate_downstream_face_z_mm": 1.5,
                "aperture_radius_mm": 1.2,
                "connector_length_mm": length_mm,
                "connector_shape": connector_shape,
                "release_plane_z_mm": 0.5,
            },
            "exit": {
                "aperture_plate_upstream_face_z_mm": 15.0,
                "aperture_plate_downstream_face_z_mm": 16.0,
                "aperture_radius_mm": 1.2,
                "connector_length_mm": length_mm,
                "connector_shape": connector_shape,
                "census_plane_z_mm": (
                    20.0
                    if enclosure_model == "rectangular_reference_enclosure_v1"
                    else 19.0
                ),
            },
        },
        "segmentation": {
            "strategy": "off",
            "axial_acceleration": None,
            "segmented_rod_array": None,
        },
    }


class SimionGeometryTests(unittest.TestCase):
    def test_grouped_ellipse_uses_two_radii_rotation_and_remapped_electrodes(self) -> None:
        array = build_rod_array(
            radial_order_n=2,
            electrode_count=4,
            inscribed_radius_r0_mm=3.74,
            rod_z_min_mm=2.0,
            rod_z_max_mm=15.0,
            cross_section={
                "shape": "ellipse",
                "semi_major_axis_mm": 4.3,
                "semi_minor_axis_mm": 1.88,
                "major_axis_orientation": "tangential",
            },
        )
        gem = render_grouped_rod_array_gem(
            array,
            electrode_group_ids={1: 3, 2: 4},
        )
        self.assertIn("e(3)", gem)
        self.assertIn("e(4)", gem)
        self.assertNotIn("e(1)", gem)
        self.assertNotIn("e(2)", gem)
        self.assertEqual(gem.count("rotate_z("), 4)
        self.assertEqual(gem.count("cylinder(0,0,0,4.3,1.88,13)"), 4)
        self.assertIn("locate(5.62,0,0) { rotate_z(90)", gem)

    def test_grouped_round_default_and_identity_mapping_are_byte_identical(self) -> None:
        array = build_rod_array(
            radial_order_n=2,
            electrode_count=4,
            inscribed_radius_r0_mm=4.0,
            rod_radius_mm=1.0,
            rod_z_min_mm=2.0,
            rod_z_max_mm=15.0,
        )
        self.assertEqual(
            render_grouped_rod_array_gem(array),
            render_grouped_rod_array_gem(array, electrode_group_ids={1: 1, 2: 2}),
        )
        for mapping in ({1: 3}, {1: 3, 2: 3}, {1: True, 2: 4}):
            with self.subTest(mapping=mapping), self.assertRaisesRegex(ValueError, "electrode_group_ids"):
                render_grouped_rod_array_gem(array, electrode_group_ids=mapping)

    def test_full_and_axis_mapped_renderers_accept_ellipse_rods(self) -> None:
        ellipse = {
            "rod_id": 1,
            "electrode_group": 1,
            "angle_rad": 0.0,
            "center_x_mm": 4.0,
            "center_y_mm": 0.0,
            "z_min_mm": 2.0,
            "z_max_mm": 15.0,
            "semi_major_axis_mm": 1.5,
            "semi_minor_axis_mm": 0.75,
            "major_axis_angle_rad": 0.5,
        }
        for enclosure_model in (
            "cylindrical_grounded_shield_v1",
            "rectangular_reference_enclosure_v1",
        ):
            with self.subTest(enclosure_model=enclosure_model):
                source = resolved_design(
                    "cylindrical_bore",
                    0.0,
                    enclosure_model=enclosure_model,
                )
                source["geometry_mm"]["rod_array"]["rods"] = [copy.deepcopy(ellipse)]
                gem = render_gem(source, 0.2)
                self.assertIn("rotate_z(28.6478897565)", gem)
                self.assertIn("cylinder(0,0,0,1.5,0.75,13)", gem)

        segmented = {
            "segment_count": 2,
            "electrodes": [
                {**copy.deepcopy(ellipse), "electrode_id": electrode_id}
                for electrode_id in range(1, 5)
            ],
        }
        mapped = render_axis_mapped_segmented_rod_array_gem(
            segmented,
            axial_origin_mm=1.0,
            transverse_origin_mm=(2.0, 3.0),
            rotation_axis=1,
            rotation_degrees=90.0,
        )
        self.assertEqual(mapped.count("rotate_z(28.6478897565)"), 4)
        self.assertIn("locate(16,6,3,1,90)", mapped)
        mixed = copy.deepcopy(segmented)
        mixed["electrodes"][0]["radius_mm"] = 1.0
        with self.assertRaisesRegex(ValueError, "mixes round and ellipse"):
            render_axis_mapped_segmented_rod_array_gem(
                mixed,
                axial_origin_mm=1.0,
                transverse_origin_mm=(2.0, 3.0),
                rotation_axis=1,
                rotation_degrees=90.0,
            )

    def test_connector_owned_terminal_is_not_rendered_by_the_multipole_pa(self) -> None:
        source = resolved_design("cylindrical_bore", 0.0)
        source["downstream_terminal"] = {
            "owner": "downstream",
            "upstream_terminal_electrode_present": False,
            "surface_plane_z_mm": 16.0,
            "rod_end_clearance_mm": 1.0,
            "upstream_enclosure_end_plane_z_mm": 15.5,
            "electrode_thickness_mm": 4.0,
            "electrode_outer_shape": "rectangular",
            "electrode_outer_width_mm": 38.0,
            "electrode_outer_height_mm": 38.0,
            "aperture": {"shape": "circular", "radius_mm": 1.5},
        }
        gem = render_gem(source, 0.2)
        self.assertNotIn("Exactly one physical terminal", gem)
        self.assertIn("GUI-visible numerical absorber", gem)

    def test_composed_downstream_terminal_replaces_legacy_exit_electrodes(self) -> None:
        source = resolved_design("cylindrical_bore", 0.0)
        source["axial_dc"] = {
            "entrance_reference_sleeve": {
                "inner_radius_mm": 0.8,
                "outer_radius_mm": 1.0,
                "upstream_face_z_mm": 0.0,
                "downstream_face_z_mm": 1.9,
                "minimum_insulation_gap_mm": 0.2,
            }
        }
        source["downstream_terminal"] = {
            "owner": "upstream",
            "upstream_terminal_electrode_present": True,
            "surface_plane_z_mm": 16.0,
            "rod_end_clearance_mm": 1.0,
            "upstream_enclosure_end_plane_z_mm": 15.5,
            "electrode_thickness_mm": 4.0,
            "electrode_outer_shape": "rectangular",
            "electrode_outer_width_mm": 38.0,
            "electrode_outer_height_mm": 38.0,
            "aperture": {
                "shape": "rectangular",
                "width_mm": 1.0,
                "height_mm": 0.9,
            },
        }
        gem = render_gem(source, 0.2)
        self.assertIn("pa_define(191,191,102", gem)
        self.assertEqual(gem.count("Exactly one physical terminal"), 1)
        self.assertIn("rod_end_clearance_mm=1", gem)
        self.assertIn("box3d(19,19,20,-19,-19,16)", gem)
        self.assertIn("box3d(0.5,0.45,20.2,-0.5,-0.45,15.8)", gem)
        self.assertIn("box3d(0.5,0.45,20.2,-0.5,-0.45,20)", gem)
        self.assertNotIn("GUI-visible numerical absorber", gem)
        self.assertNotIn("; connector_shape=", gem)
        self.assertIn("Functional source-reference sleeve", gem)
        self.assertIn("e(6)", gem)
        self.assertIn("e(7) { fill {\n    within { cylinder(0,0,1.5,10,,0.5) }", gem)

    def test_composed_circular_terminal_uses_cylindrical_void_and_census_marker(self) -> None:
        source = resolved_design("cylindrical_bore", 0.0)
        source["downstream_terminal"] = {
            "owner": "upstream",
            "upstream_terminal_electrode_present": True,
            "surface_plane_z_mm": 16.0,
            "rod_end_clearance_mm": 1.0,
            "upstream_enclosure_end_plane_z_mm": 15.5,
            "electrode_thickness_mm": 4.0,
            "electrode_outer_shape": "rectangular",
            "electrode_outer_width_mm": 38.0,
            "electrode_outer_height_mm": 38.0,
            "aperture": {"shape": "circular", "radius_mm": 1.5},
        }
        gem = render_gem(source, 0.2)
        self.assertIn("notin_inside { cylinder(0,0,20.2,1.5,,4.4) }", gem)
        self.assertIn("Numerical absorber fills only the circular aperture", gem)
        self.assertIn("e(5) { fill { within { cylinder(0,0,20.2,1.5,,0.2) } } }", gem)
        self.assertNotIn("box3d(0.5,0.45", gem)

    def test_cli_accepts_xyz_and_rejects_mixed_cell_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resolved = root / "resolved.json"
            output = root / "geometry.gem"
            resolved.write_text(
                json.dumps(resolved_design("cylindrical_bore", 0.0)),
                encoding="utf-8",
            )
            base = [
                sys.executable,
                "-m",
                "common.multipole.simion_geometry",
                "--resolved-design",
                str(resolved),
                "--output",
                str(output),
            ]
            accepted = subprocess.run(
                [
                    *base,
                    "--cell-mm-x",
                    "0.2",
                    "--cell-mm-y",
                    "0.5",
                    "--cell-mm-z",
                    "0.4",
                ],
                check=False,
                capture_output=True,
                cwd=Path(__file__).resolve().parents[2],
                text=True,
                timeout=20,
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertIn("pa_define(101,41,51", output.read_text(encoding="ascii"))
            rejected = subprocess.run(
                [
                    *base,
                    "--cell-mm",
                    "0.4",
                    "--cell-mm-x",
                    "0.2",
                    "--cell-mm-y",
                    "0.5",
                    "--cell-mm-z",
                    "0.4",
                ],
                check=False,
                capture_output=True,
                cwd=Path(__file__).resolve().parents[2],
                text=True,
                timeout=20,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("mutually exclusive", rejected.stderr)

    def test_anisotropic_cells_define_independent_pa_axes(self) -> None:
        gem = render_gem(
            resolved_design("cylindrical_bore", 0.0),
            {"x": 0.2, "y": 0.5, "z": 0.4},
        )
        self.assertIn(
            "pa_define(101,41,51,planar,none,electrostatic,,0.2,0.5,0.4",
            gem,
        )
        self.assertIn("cylinder(0,0,19.4,1.2,,0.4)", gem)
        self.assertIn("cylinder(0,0,20.4,9,,20.8)", gem)

    def test_rectangular_anisotropic_cells_use_z_for_axial_padding(self) -> None:
        gem = render_gem(
            resolved_design(
                "rectangular_bore",
                0.0,
                enclosure_model="rectangular_reference_enclosure_v1",
            ),
            {"x": 0.2, "y": 0.5, "z": 0.4},
        )
        self.assertIn(
            "pa_define(51,21,54,planar,xy,electrostatic,,0.2,0.5,0.4",
            gem,
        )
        self.assertIn("cylinder(0,0,5.4,1.2,,0.4)", gem)

    def test_rectangular_connector_is_box_minus_cylinder(self) -> None:
        source = resolved_design(
            "rectangular_bore",
            1.0,
            enclosure_model="rectangular_reference_enclosure_v1",
        )
        gem = render_gem(source, 0.2)
        self.assertIn("box3d(", gem)
        self.assertIn("notin_inside { cylinder(", gem)
        self.assertIn("; connector_shape=rectangular_bore", gem)
        self.assertIn("parent_resolved_sha256=" + "A" * 64, gem)
        self.assertIn("GUI-visible numerical absorber", gem)
        self.assertIn("cylinder(0,0,5.2,1.2,,0.2)", gem)

    def test_cylindrical_connector_is_cylinder_minus_cylinder(self) -> None:
        gem = render_gem(resolved_design("cylindrical_bore", 1.0), 0.2)
        connector = gem.index("; connector_shape=cylindrical_bore")
        next_connector = gem.index("; connector_shape=cylindrical_bore", connector + 1)
        self.assertIn("within { cylinder(", gem[connector:next_connector])
        self.assertNotIn("within { box3d(", gem[connector:next_connector])

    def test_cylindrical_enclosure_preserves_rectangular_connector_shape(self) -> None:
        gem = render_gem(resolved_design("rectangular_bore", 1.0), 0.2)
        entrance = gem.index("; connector_shape=rectangular_bore")
        exit_connector = gem.index("; connector_shape=rectangular_bore", entrance + 1)
        self.assertIn("within { box3d(", gem[entrance:exit_connector])
        self.assertIn("within { box3d(", gem[exit_connector:])

    def test_cylindrical_census_marker_is_gui_visible_inside_the_pa(self) -> None:
        source = resolved_design("cylindrical_bore", 0.0)
        source["interfaces_mm"]["exit"]["census_plane_z_mm"] = 19.0
        gem = render_gem(source, 0.2)
        self.assertIn("GUI-visible numerical absorber", gem)
        self.assertIn("e(4)", gem)
        self.assertIn("cylinder(0,0,19.2,1.2,,0.2)", gem)

    def test_cylindrical_census_marker_must_fit_inside_the_pa(self) -> None:
        source = resolved_design("cylindrical_bore", 0.0)
        source["interfaces_mm"]["exit"]["census_plane_z_mm"] = 19.9
        with self.assertRaisesRegex(ValueError, "numerical census marker"):
            render_gem(source, 0.2)

    def test_zero_length_creates_no_connector_feature(self) -> None:
        for shape in ("rectangular_bore", "cylindrical_bore"):
            gem = render_gem(resolved_design(shape, 0.0), 0.2)
            self.assertNotIn("; connector_shape=", gem)

    def test_unknown_connector_shape_is_rejected(self) -> None:
        invalid = resolved_design("cylindrical_bore", 1.0)
        invalid["interfaces_mm"]["exit"]["connector_shape"] = "square"
        with self.assertRaisesRegex(ValueError, "connector shape"):
            render_gem(invalid, 0.2)

    def test_rectangular_segments_anchor_cylinders_at_z_max(self) -> None:
        source = resolved_design(
            "rectangular_bore",
            0.0,
            enclosure_model="rectangular_reference_enclosure_v1",
        )
        base = source["geometry_mm"]["rod_array"]["rods"][0]
        source["segmentation"] = {
            "strategy": "explicit",
            "axial_acceleration": {"role": "multipole_axial_acceleration_resolved_contract"},
            "segmented_rod_array": {
                "segment_count": 2,
                "electrodes": [
                    {**base, "electrode_id": 1, "z_min_mm": 2.0, "z_max_mm": 7.0},
                    {**base, "electrode_id": 2, "z_min_mm": 2.0, "z_max_mm": 7.0},
                    {**base, "electrode_id": 3, "z_min_mm": 8.0, "z_max_mm": 15.0},
                    {**base, "electrode_id": 4, "z_min_mm": 8.0, "z_max_mm": 15.0},
                ],
            },
        }
        gem = render_gem(source, 0.2)
        self.assertIn("locate(0,0,7)", gem)
        self.assertIn("locate(0,0,15)", gem)
        self.assertNotIn("locate(0,0,2)", gem)
        self.assertNotIn("locate(0,0,8)", gem)

    def test_five_segment_geometry_reserves_electrodes_eleven_and_twelve(self) -> None:
        source = resolved_design("cylindrical_bore", 0.0)
        base = source["geometry_mm"]["rod_array"]["rods"][0]
        source["segmentation"] = {
            "strategy": "uniform",
            "axial_acceleration": {"role": "multipole_axial_acceleration_resolved_contract"},
            "segmented_rod_array": {
                "segment_count": 5,
                "electrodes": [
                    {**copy.deepcopy(base), "electrode_id": electrode_id}
                    for electrode_id in range(1, 11)
                ],
            },
        }
        gem = render_gem(source, 0.2)
        self.assertIn("e(11)", gem)
        self.assertIn("e(12)", gem)
        self.assertIn("e(13)", gem)


if __name__ == "__main__":
    unittest.main()
