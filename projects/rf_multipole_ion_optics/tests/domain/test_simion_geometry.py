from __future__ import annotations

import copy
import hashlib
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from projects.rf_multipole_ion_optics.core.round_rod_geometry import build_rod_array
from projects.rf_multipole_ion_optics.simion.simion_geometry import (
    physical_electrode_view,
    render_axis_mapped_segmented_rod_array_gem,
    render_gem,
    render_physical_gem,
    render_grouped_rod_array_gem,
)
from projects.rf_multipole_ion_optics.core.compile_design_request import compile_design_request
from projects.rf_multipole_ion_optics.tests.domain.test_compile_design_request import design_request


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
        "drive": {
            "common_mode_offset_V": 0.0,
            "dc_amplitude_V_per_group": 0.0,
        },
        "static_electrodes_V": {
            "role": "cylindrical_shield_static_electrodes",
            "shield_entrance_outer_endcap_aperture_plate_connector_V": 0.0,
            "exit_outer_endcap_aperture_plate_connector_V": 0.0,
        },
    }


class SimionGeometryTests(unittest.TestCase):
    @staticmethod
    def _compiled_segmented_cylindrical_provider() -> dict:
        request = design_request(
            "hexapole",
            segmentation={
                "strategy": "uniform",
                "segment_count": 3,
                "intersegment_gap_mm": 0.4,
                "entrance_common_mode_V": 0.0,
                "exit_common_mode_V": -3.0,
                "output_reference_V": -3.0,
            },
        )
        return compile_design_request(request, expected_identity=request["identity"])

    def test_physical_electrode_view_exposes_compiled_provider_groups_without_drive_copies(self):
        view = physical_electrode_view(self._compiled_segmented_cylindrical_provider())
        self.assertEqual([row["native_electrode_id"] for row in view], list(range(1, 9)))
        rods = [row for row in view if row["roles"] == ["rod"]]
        self.assertEqual(len(rods), 6)
        self.assertEqual(
            [(row["scientific_id"], row["voltage_source"]["rf_group"])
             for row in rods],
            [(f"rod_group_{native_id}", 1 if native_id % 2 else 2)
             for native_id in range(1, 7)],
        )
        self.assertTrue(all("common_mode_v" not in row["voltage_source"] for row in view))
        self.assertTrue(all(
            row["voltage_source"]["dc_amplitude_pointer"]
            == "/drive/dc_amplitude_V_per_group"
            for row in rods
        ))
        physical_roles = {
            role
            for row in view
            for role in row["roles"]
            if role != "rod"
        }
        self.assertEqual(
            physical_roles,
            {
                "shield", "entrance_outer_endcap", "entrance_aperture_plate",
                "entrance_connector", "exit_outer_endcap", "exit_aperture_plate",
                "exit_connector",
            },
        )
        self.assertNotIn("numerical_census_marker", physical_roles)

    def test_physical_electrode_view_rejects_missing_duplicate_and_conflicting_groups(self):
        compiled = self._compiled_segmented_cylindrical_provider()
        for mutation in (
            lambda rows: rows.pop(),
            lambda rows: rows.append(copy.deepcopy(rows[0])),
        ):
            with self.subTest(mutation=mutation):
                source = copy.deepcopy(compiled)
                mutation(source["segmentation"]["segmented_rod_array"]["electrodes"])
                with self.assertRaisesRegex(ValueError, "missing or duplicates"):
                    physical_electrode_view(source)
        conflicting_drive = copy.deepcopy(compiled)
        conflicting_drive["segmentation"]["segmented_rod_array"]["electrodes"][2]["common_mode_V"] = 1.0
        with self.assertRaisesRegex(ValueError, "conflicting resolved drive source"):
            physical_electrode_view(conflicting_drive)
        request = design_request("hexapole")
        conflicting = compile_design_request(request, expected_identity=request["identity"])
        conflicting["static_electrodes_V"]["exit_outer_endcap_aperture_plate_connector_V"] = 1.0
        with self.assertRaisesRegex(ValueError, "conflicting resolved potentials"):
            physical_electrode_view(conflicting)

    def test_physical_electrode_view_requires_each_static_source_voltage(self):
        for key in (
            "shield_entrance_outer_endcap_aperture_plate_connector_V",
            "exit_outer_endcap_aperture_plate_connector_V",
        ):
            with self.subTest(static_key=key):
                source = resolved_design("cylindrical_bore", 0.0)
                source["static_electrodes_V"].pop(key)
                with self.assertRaisesRegex(ValueError, "static potential must be finite"):
                    physical_electrode_view(source)

        source = resolved_design("cylindrical_bore", 0.0)
        source["axial_dc"] = {"entrance_reference_sleeve": {}}
        with self.assertRaisesRegex(ValueError, "static potential must be finite"):
            physical_electrode_view(source)

    def test_standalone_gem_bytes_are_unchanged_by_physical_body_extraction(self):
        # Captured from the public renderer immediately before extracting its
        # physical export. These are small GEM text identities, never PA hashes.
        expected = {
            ("cylindrical_bore", 0.): "8f5e4befc6c6669f6c42109c16053f720e28f4db85ee073a1fff2ead36bfdcb7",
            ("cylindrical_bore", 2.): "e7626c158c10fd2e60f109f0fe0186dbf1bca3863c3cd49e2b1258000af930f4",
            ("rectangular_bore", 0.): "8f5e4befc6c6669f6c42109c16053f720e28f4db85ee073a1fff2ead36bfdcb7",
            ("rectangular_bore", 2.): "f742beafd3dcf5685f4fbc3fd4317600ca01454865786638bc2dc5de63f8b0ff",
        }
        for (shape, length), sha in expected.items():
            with self.subTest(shape=shape, length=length):
                gem = render_gem(resolved_design(shape, length), .2)
                self.assertEqual(hashlib.sha256(gem.encode()).hexdigest(), sha)
        rectangular = resolved_design("cylindrical_bore", 0., enclosure_model="rectangular_reference_enclosure_v1")
        self.assertEqual(hashlib.sha256(render_gem(rectangular, .2).encode()).hexdigest(),
                         "68d67e30b94976115a3ec3d9b5e3f4cfe66b0a7f48eb3bb7815c98bd6022e61e")
        through = resolved_design("cylindrical_bore", 0.)
        through["geometry_mm"]["enclosure"].update(model="cylindrical_grounded_shield_through_exit_v1", vacuum_z_max_mm=20.4)
        self.assertEqual(hashlib.sha256(render_gem(through, .2).encode()).hexdigest(),
                         "15681ac9b1063bfefe5a0e03a173b8da9c68d27e317220c3eafa1b4cc84edc3b")

    def test_physical_export_keeps_true_cap_bore_connector_sleeve_and_maps_ids_once(self):
        source = resolved_design("cylindrical_bore", 2.)
        source["geometry_mm"]["enclosure"].update(model="cylindrical_grounded_shield_through_exit_v1", vacuum_z_max_mm=20.4)
        source["axial_dc"] = dict(entrance_reference_sleeve=dict(
            upstream_face_z_mm=.6, downstream_face_z_mm=.9,
            outer_radius_mm=2., inner_radius_mm=1.5, minimum_insulation_gap_mm=.1,
            potential_V=0.0))
        before = copy.deepcopy(source)
        body = render_physical_gem(source, .2, electrode_ids={1: 11, 3: 13, 5: 15, 6: 16})
        self.assertEqual(source, before)
        self.assertNotIn("pa_define", body)
        self.assertNotIn("locate(10,10", body)
        self.assertNotIn("absorber", body)
        self.assertNotIn("e(4)", body)
        self.assertIn("e(11) { fill { within { cylinder(4,0,15,1,,13)", body)
        self.assertIn("e(13)", body)
        self.assertIn("e(15)", body)
        self.assertIn("e(16)", body)
        self.assertIn("within { cylinder(0,0,20,10,,0.5) }", body)
        self.assertIn("notin_inside { cylinder(0,0,20.2,1.2,,0.9) }", body)
        self.assertIn("within { cylinder(0,0,0.9,2,,0.3) }", body)
        self.assertIn("connector_shape=cylindrical_bore", body)
        # The native body has no standalone-domain guard or PA origin.
        source["geometry_mm"]["enclosure"]["vacuum_z_max_mm"] = 20.
        self.assertEqual(render_physical_gem(source, .2, electrode_ids={1: 11, 3: 13, 5: 15, 6: 16}), body)

    def test_segmented_physical_export_preserves_each_native_electrode(self):
        source = resolved_design("rectangular_bore", 2.)
        base = source["geometry_mm"]["rod_array"]["rods"][0]
        source["segmentation"]["segmented_rod_array"] = dict(segment_count=2, electrodes=[
            {**base, "electrode_id": i, "electrode_group": 1 if i % 2 else 2,
             "common_mode_V": 0.0, "z_min_mm": low, "z_max_mm": high}
            for i, low, high in ((1, 2., 7.), (2, 2., 7.), (3, 8., 15.), (4, 8., 15.))])
        body = render_physical_gem(source, .2, electrode_ids={i: 20+i for i in range(1, 7)})
        for i in range(1, 7):
            self.assertIn(f"e({20+i})", body)
        self.assertIn("cylinder(4,0,7,1,,5)", body)
        self.assertIn("cylinder(4,0,15,1,,7)", body)
        self.assertIn("connector_shape=rectangular_bore", body)
        self.assertNotIn("e(27)", body)  # no numerical census electrode

    def test_physical_export_rejects_ambiguous_models_and_incomplete_or_merged_ids(self):
        source = resolved_design("cylindrical_bore", 0.)
        for ids in ({1: 11}, {1: 11, 3: 11}, {1: 11, 3: 13, 4: 14}, {1: 0, 3: 13}):
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, "every physical native electrode"):
                render_physical_gem(source, .2, electrode_ids=ids)
        source["downstream_terminal"] = {"owner": "downstream"}
        with self.assertRaisesRegex(ValueError, "composed terminal"):
            render_physical_gem(source, .2)
        source.pop("downstream_terminal")
        source["geometry_mm"]["enclosure"]["vacuum_z_max_mm"] = 21.
        with self.assertRaisesRegex(ValueError, "tied to the standalone PA domain"):
            render_physical_gem(source, .2)

    def test_physical_export_retains_asymmetric_ellipse_and_electrical_identity(self):
        source = resolved_design("cylindrical_bore", 0.)
        rod = source["geometry_mm"]["rod_array"]["rods"][0]
        rod.pop("radius_mm")
        rod.update(center_x_mm=2., center_y_mm=3., semi_major_axis_mm=1.5,
                   semi_minor_axis_mm=.5, major_axis_angle_rad=math.pi/4)
        body = render_physical_gem(source, .2, electrode_ids={1: 101, 3: 103})
        self.assertIn("e(101)", body)
        self.assertIn("locate(2,3,15) { rotate_z(45) { cylinder(0,0,0,1.5,0.5,13)", body)
        self.assertNotIn("rotate_y", body)  # placement belongs to the assembly

    def test_official_single_locate_order_matches_full_recipe_pose_for_asymmetric_states(self):
        # SIMION 2020 CHM, GEM locate: rt(X), el(Z), az(Y), scale, offset.
        # This is a reference-vector check, not a native GEM rasterization.
        from common.contracts.rigid_transform import FramedPosition, FramedVector, RigidTransform
        pose = RigidTransform("native", "assembly", ((0,0,1),(1,0,0),(0,1,0)), (7,11,13))
        rotate_z90 = lambda p: (-p[1], p[0], p[2])
        rotate_y90 = lambda p: (p[2], p[1], -p[0])
        for point in ((1,0,0), (0,1,0), (0,0,1), (2,3,5)):
            rotated = rotate_y90(rotate_z90(point))
            self.assertEqual(pose.transform_vector(FramedVector("native", point)).components, rotated)
            self.assertEqual(pose.transform_position(FramedPosition("native", point)).coordinates_mm,
                             tuple(v+t for v,t in zip(rotated, (7,11,13))))
        self.assertEqual(rotate_y90(rotate_z90((2,3,5))), (5,2,3))
        self.assertNotEqual(rotate_y90((2,3,5)), (5,2,3))

    def test_through_exit_bores_outer_cap_and_leaves_guard_to_native_program(self):
        resolved = resolved_design("cylindrical_bore", 0.)
        enclosure = resolved["geometry_mm"]["enclosure"]
        enclosure.update(model="cylindrical_grounded_shield_through_exit_v1", vacuum_z_max_mm=20.4)
        gem = render_gem(resolved, .2)
        self.assertIn("notin_inside { cylinder(0,0,20.2,1.2,,0.9) }", gem)
        self.assertNotIn("numerical absorber", gem)
        self.assertIn("within { cylinder(0,0,20,10,,20) }", gem)
        self.assertNotIn("cylinder(0,0,19.2,1.2,,0.2)", gem)
        enclosure["vacuum_z_max_mm"] = 20.
        with self.assertRaisesRegex(ValueError, "two axial cells"):
            render_gem(resolved, .2)

    def test_dual_through_model_bores_both_real_outer_endcaps(self):
        resolved = resolved_design("cylindrical_bore", 0.)
        enclosure = resolved["geometry_mm"]["enclosure"]
        enclosure.update(
            model="cylindrical_grounded_shield_through_entrance_exit_v1",
            vacuum_z_max_mm=20.4,
        )
        gem = render_gem(resolved, .2)
        self.assertIn("notin_inside { cylinder(0,0,0.7,1.2,,0.9) }", gem)
        self.assertIn("notin_inside { cylinder(0,0,20.2,1.2,,0.9) }", gem)
        self.assertLess(
            gem.index("cylinder(0,0,0.7,1.2,,0.9)"),
            gem.index("cylinder(0,0,1.5,10,,0.5)"),
        )
        self.assertNotIn("numerical absorber", gem)
        enclosure["vacuum_z_max_mm"] = 30.4
        expanded_guard = render_gem(resolved, .2)
        self.assertIn("pa_define(101,101,153,planar", expanded_guard)
        self.assertIn("within { cylinder(0,0,20,10,,20) }", expanded_guard)
        self.assertNotIn("within { cylinder(0,0,30.4,10", expanded_guard)


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
                "projects.rf_multipole_ion_optics.simion.simion_geometry",
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
                cwd=Path(__file__).resolve().parents[4],
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
                cwd=Path(__file__).resolve().parents[4],
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
                    {**base, "electrode_id": 1, "electrode_group": 1, "common_mode_V": 0.0, "z_min_mm": 2.0, "z_max_mm": 7.0},
                    {**base, "electrode_id": 2, "electrode_group": 2, "common_mode_V": 0.0, "z_min_mm": 2.0, "z_max_mm": 7.0},
                    {**base, "electrode_id": 3, "electrode_group": 1, "common_mode_V": 0.0, "z_min_mm": 8.0, "z_max_mm": 15.0},
                    {**base, "electrode_id": 4, "electrode_group": 2, "common_mode_V": 0.0, "z_min_mm": 8.0, "z_max_mm": 15.0},
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
                    {**copy.deepcopy(base), "electrode_id": electrode_id,
                     "electrode_group": 1 if electrode_id % 2 else 2,
                     "common_mode_V": 0.0}
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
