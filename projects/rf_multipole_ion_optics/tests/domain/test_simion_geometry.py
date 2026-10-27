from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from projects.rf_multipole_ion_optics.core.interface_geometry import build_enclosure_layout
from projects.rf_multipole_ion_optics.core.round_rod_geometry import build_rod_array
from projects.rf_multipole_ion_optics.simion.simion_geometry import (
    physical_electrode_view, render_axis_mapped_segmented_rod_array_gem,
    render_gem, render_physical_gem, render_grouped_rod_array_gem,
)


def resolved_design(enclosure: dict | None = None, *, segmented: bool = False) -> dict:
    geometry = {
        "inscribed_radius_r0": 3., "rod_z_min": 2., "rod_z_max": 15.,
        "enclosure": copy.deepcopy(enclosure) if enclosure is not None else {"model": "bare"},
        "rod_array": build_rod_array(radial_order_n=2,electrode_count=4,
            inscribed_radius_r0_mm=3.,rod_radius_mm=1.,rod_z_min_mm=2.,rod_z_max_mm=15.),
        "numerical_domain": {"radius_mm": 11.,"z_min_mm": 0.,"z_max_mm": 20.,"working_region_radius_mm": 2.5},
        "observations": {"release_plane_z_mm": 2.,"handoff_plane_z_mm": 15.,"census_plane_z_mm": 18.,"acceptance_radius_mm": 2.5},
    }
    geometry["enclosure_layout"] = build_enclosure_layout(geometry)
    table = None
    if segmented:
        electrodes = []
        for index,(lo,hi) in enumerate(((2.,8.),(9.,15.)),1):
            for rod in geometry["rod_array"]["rods"]:
                electrodes.append({**rod,"z_min_mm":lo,"z_max_mm":hi,"segment_id":index,
                    "electrode_id":2*(index-1)+rod["electrode_group"],"common_mode_V":-index})
        table = {"segment_count":2,"electrodes":electrodes}
    return {"schema_version":3,"role":"multipole_resolved_design_do_not_edit","resolved_sha256":"A"*64,
        "geometry_mm":geometry,"segmentation":{"segmented_rod_array":table},
        "drive":{"common_mode_offset_V":0.,"dc_amplitude_V_per_group":0.},
        "static_electrodes_V":({"role":"grounded_shell_static_electrodes","ground_V":0.}
            if geometry["enclosure_layout"]["bodies"] else {"role":"bare_multipole_static_electrodes"})}


def shell(endcaps: dict | None = None) -> dict:
    return {"model":"cylindrical_grounded_shell","inner_radius_mm":9.,"wall_thickness_mm":1.,
            "z_min_mm":1.,"z_max_mm":19.,"endcaps":endcaps or {}}


def rectangular_reference(
    connector_shape: str,
    length_mm: float,
    *,
    enclosure_model: str = "rectangular_reference_enclosure_v1",
) -> dict:
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
    def test_default_bare_contains_only_rods_and_no_fictitious_electrode(self):
        source = resolved_design()
        view = physical_electrode_view(source)
        self.assertEqual([r["native_electrode_id"] for r in view],[1,2])
        body = render_physical_gem(source,.2)
        self.assertNotIn("e(3)",body)
        self.assertNotIn("enclosure_role",body)
        for token in ("connector", "aperture_plate", "census_marker", "pa_define", "parent_resolved"):
            self.assertNotIn(token,body)
        self.assertEqual(body.count("cylinder("),4)

    def test_shell_and_all_optional_caps_share_one_ground_and_same_frozen_shapes(self):
        cap={"aperture_radius_mm":2.,"thickness_mm":.5}
        for caps in ({},{"entrance":cap},{"exit":cap},{"entrance":cap,"exit":cap}):
            with self.subTest(caps=caps):
                source=resolved_design(shell(caps));before=copy.deepcopy(source)
                view=physical_electrode_view(source)
                self.assertEqual([r["native_electrode_id"] for r in view],[1,2,3])
                ground=view[-1]
                self.assertEqual(ground["scientific_id"],"grounded_shell")
                self.assertEqual(ground["voltage_source"],{"kind":"static","pointer":"/static_electrodes_V/ground_V"})
                self.assertEqual(ground["roles"],[b["role"] for b in source["geometry_mm"]["enclosure_layout"]["bodies"]])
                body=render_physical_gem(source,.2)
                self.assertEqual(body.count("e(3)"),1+len(caps))
                for b in source["geometry_mm"]["enclosure_layout"]["bodies"]:
                    self.assertIn(f"cylinder(0,0,{b['z_max_mm']:.12g},{b['outer_radius_mm']:.12g},,{b['z_max_mm']-b['z_min_mm']:.12g})",body)
                self.assertEqual(source,before)

    def test_numerical_domain_and_observation_changes_do_not_move_physical_bodies(self):
        source=resolved_design(shell());body=render_physical_gem(source,.2)
        source["geometry_mm"]["numerical_domain"].update(radius_mm=12.,z_min_mm=-2.,z_max_mm=23.)
        source["geometry_mm"]["observations"].update(census_plane_z_mm=21.)
        self.assertEqual(body,render_physical_gem(source,.2))
        gem=render_gem(source,{"x":.2,"y":.4,"z":.5})
        self.assertIn("pa_define(121,61,51,planar,none",gem)
        self.assertIn("locate(12,12,2)",gem)
        self.assertIn(render_physical_gem(source,{"x":.2,"y":.4,"z":.5}).rstrip(),gem)

    def test_each_instance_can_map_all_actual_ids_without_merging_or_mutating(self):
        for enclosure in (None,shell()):
            source=resolved_design(enclosure,segmented=True);view=physical_electrode_view(source)
            ids={r["native_electrode_id"] for r in view}
            self.assertEqual(ids,set(range(1,6 if enclosure else 5)))
            before=copy.deepcopy(source);mapping={i:i+20 for i in ids}
            body=render_physical_gem(source,.2,electrode_ids=mapping)
            for i in ids:self.assertIn(f"e({i+20})",body)
            self.assertEqual(source,before)
            for bad in ({i:i for i in sorted(ids)[1:]},{i:20 for i in ids},{i:True for i in ids}):
                with self.assertRaisesRegex(ValueError,"electrode_ids"):
                    render_physical_gem(source,.2,electrode_ids=bad)

    def test_incomplete_or_conflicting_segment_groups_are_rejected(self):
        source=resolved_design(segmented=True)
        for mutate in (lambda rows: rows.pop(),lambda rows: rows.append(copy.deepcopy(rows[0]))):
            bad=copy.deepcopy(source);mutate(bad["segmentation"]["segmented_rod_array"]["electrodes"])
            with self.assertRaisesRegex(ValueError,"missing or duplicates"):
                physical_electrode_view(bad)
        source["segmentation"]["segmented_rod_array"]["electrodes"][2]["common_mode_V"]=1
        with self.assertRaisesRegex(ValueError,"conflicting resolved drive"):
            physical_electrode_view(source)

    def test_nonzero_ground_and_bare_static_objects_are_rejected(self):
        source=resolved_design(shell());source["static_electrodes_V"]["ground_V"]=1
        with self.assertRaisesRegex(ValueError,"share ground"):physical_electrode_view(source)
        source=resolved_design();source["static_electrodes_V"]["ground_V"]=0
        with self.assertRaisesRegex(ValueError,"bare multipole"):physical_electrode_view(source)

    def test_retired_through_topologies_are_not_native_compatibility_inputs(self):
        for name in ('cylindrical_grounded_shield_v1','cylindrical_grounded_shield_through_exit_v1',
                     'cylindrical_grounded_shield_through_entrance_exit_v1'):
            source=resolved_design();source["geometry_mm"]["enclosure"]["model"]=name
            with self.assertRaisesRegex(ValueError,"bare or grounded-shell"):
                render_physical_gem(source,.2)

    def test_rectangular_reference_keeps_its_existing_standalone_bytes(self):
        source=rectangular_reference("cylindrical_bore",0.)
        gem=render_gem(source,.2)
        self.assertEqual(hashlib.sha256(gem.encode()).hexdigest(),
            "68d67e30b94976115a3ec3d9b5e3f4cfe66b0a7f48eb3bb7815c98bd6022e61e")
        with self.assertRaisesRegex(ValueError,"not a physical component"):
            render_physical_gem(source,.2)

    def test_asymmetric_ellipse_rods_keep_their_native_shape_and_axis_projection(self):
        source=resolved_design(segmented=True)
        for rod in source["segmentation"]["segmented_rod_array"]["electrodes"]:
            rod.pop("radius_mm")
            rod.update(semi_major_axis_mm=1.5,semi_minor_axis_mm=.75,major_axis_angle_rad=.5)
        native=render_physical_gem(source,.2)
        self.assertEqual(native.count("rotate_z(28.6478897565)"),8)
        mapped=render_axis_mapped_segmented_rod_array_gem(
            source["segmentation"]["segmented_rod_array"],axial_origin_mm=1.,
            transverse_origin_mm=(2.,3.),rotation_axis=1,rotation_degrees=90.)
        self.assertEqual(mapped.count("rotate_z(28.6478897565)"),8)
        self.assertIn("cylinder(0,0,0,1.5,0.75,6)",mapped)

    def test_cli_freezes_exact_current_geometry_and_rejects_mixed_cells(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'resolved.json';out=Path(d)/'body.gem'
            source.write_text(json.dumps(resolved_design()),encoding='utf-8')
            command=[sys.executable,'-m','projects.rf_multipole_ion_optics.simion.simion_geometry',
                '--resolved-design',str(source),'--output',str(out)]
            ok=subprocess.run(command+['--cell-mm-x','.2','--cell-mm-y','.4','--cell-mm-z','.5'],cwd=Path(__file__).parents[4],capture_output=True,text=True,timeout=30)
            self.assertEqual(ok.returncode,0,ok.stderr)
            self.assertEqual(out.read_text(),render_gem(resolved_design(),{'x':.2,'y':.4,'z':.5}))
            bad=subprocess.run(command+['--cell-mm','.2','--cell-mm-z','.5'],cwd=Path(__file__).parents[4],capture_output=True,text=True,timeout=30)
            self.assertNotEqual(bad.returncode,0)

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
