"""Ordinary-SL header fixtures and analytic mesh-section regressions; no solver."""
from __future__ import annotations

import csv
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_mesh_diagnostics as m
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_local_field_diagnostics import _shape_mask


def _box(low: list, high: list) -> dict:
    return dict(shape="box", min_mm=low, max_mm=high)


def _prepared() -> dict:
    solids = {5: [_box([-1.2, -1., -.8], [1.2, 1., -.6])],
              6: [_box([-1.2, -1., .6], [1.2, 1., .8])],
              11: [_box([-.7, -.5, -.15], [-.5, .5, .15]), _box([.5, -.5, -.15], [.7, .5, .15])],
              14: [_box([-1.5]*3, [1.5]*3)]}
    electrodes = [dict(electrode_id=e, solids=s, cutouts=[_box([-1.]*3, [1.]*3)] if e == 14 else []) for e, s in solids.items()]
    return dict(geometry=dict(ion_processor_electrodes=electrodes),
                geometry_checks=dict(box_mm=[0., -2., -2., 2., 2., 2.], pitch_mm=[.5]*3,
                                     grid_dimensions=[5, 9, 9], nominal_y_mm=.26))


class MeshDiagnosticsTests(unittest.TestCase):
    def test_closed_slab_keeps_both_aligned_faces_without_physical_margin(self):
        coarse = m._closed_slab_layers(-120., .1, 1451, -20.2, -19.8)
        np.testing.assert_array_equal(coarse, np.arange(998, 1003))
        fine = m._closed_slab_layers(-120., .05, 2901, -20.2, -19.8)
        np.testing.assert_array_equal(fine, np.arange(1996, 2005))
        self.assertGreater(-120.+coarse[-1]*.1, -19.8)  # Previous strict-world predicate lost this face.
        np.testing.assert_array_equal(m._closed_slab_layers(-120., .1, 1451, -20.2, -19.800001), np.arange(998, 1002))

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        (self.run/"inputs").mkdir()
        self.directory = self.run/"simion/case_01"
        self.directory.mkdir(parents=True)
        self.header = m.PaHeader(-2, 1, 100., 5, 9, 9, 1 | (100 << 4), .5, .5, .5)
        self.prepared = _prepared()
        (self.directory/"geometry.json").write_text(json.dumps(self.prepared), encoding="utf-8")
        self.path = self.directory/"field.pa"
        z, y, x = np.meshgrid(np.arange(9)*.5-2, np.arange(9)*.5-2, np.arange(5)*.5, indexing="ij")
        flags = m._metal(self.prepared["geometry"]["ion_processor_electrodes"], [x, y, z])
        # Same ordinary fixture encoding as test_standalone_pa_composition:
        # negative electrode voltage still yields raw>max_voltage.
        values = np.full(flags.shape, -50., dtype="<f8")+flags*200.
        self.path.write_bytes(self.header.pack()+values.tobytes())
        owner = dict(case_id="C", field_case_id="C_h050", field_path=str(self.path), directory=str(self.directory))
        (self.run/"inputs/resolved_study.json").write_text(json.dumps(dict(field_owners=[owner], build_cases=[])), encoding="utf-8")

    def _install_aperture(self, shape: str = "circle", thickness: float = .5) -> dict:
        # Synthetic geometry only. Open the existing frame along z, allowing a
        # separately specified finite plate to be the actual beam obstruction.
        frame = next(e for e in self.prepared["geometry"]["ion_processor_electrodes"] if e["electrode_id"] == 14)
        frame["cutouts"] = [_box([-1., -1., -2.], [1., 1., 2.])]
        center = [0., 0., -1.25]
        spec = dict(shape=shape, center_mm=center, normal=[0, 0, -1], thickness_mm=thickness,
                    outer_half_widths_mm=[1.5, 1.5], voltage_v=0., connection="prism_ground_shield")
        lo, hi = center[2]-thickness/2, center[2]+thickness/2
        if shape == "circle":
            spec["radius_mm"] = .75
            hole = dict(shape="cylinder3d", endpoints_mm=[[0., 0., lo], [0., 0., hi]], radius_mm=.75)
        else:
            spec["half_widths_mm"] = [1., .25]
            hole = _box([-1., -.25, lo], [1., .25, hi])
        plate = dict(specification=spec, solids=[_box([-1.5, -1.5, lo], [1.5, 1.5, hi])], cutouts=[hole])
        self.prepared["geometry"]["aperture_electrodes"] = [plate]
        (self.directory/"geometry.json").write_text(json.dumps(self.prepared), encoding="utf-8")
        z, y, x = np.meshgrid(np.arange(9)*.5-2, np.arange(9)*.5-2, np.arange(5)*.5, indexing="ij")
        electrodes = self.prepared["geometry"]["ion_processor_electrodes"]+[plate]
        flags = m._metal(electrodes, [x, y, z])
        self.path.write_bytes(self.header.pack()+(np.full(flags.shape, -50., dtype="<f8")+flags*200.).tobytes())
        return plate

    def _topology(self, plate: dict) -> dict:
        output = self.run/"topology"
        output.mkdir(exist_ok=True)
        raw = np.memmap(self.path, dtype="<f8", mode="r", offset=m.HEADER.size, shape=(9, 9, 5))
        try:
            return m._aperture_topology(raw, self.header, self.prepared, plate, 0, output, "fixture")
        finally:
            del raw

    def test_raw_flags_and_negative_x_mirror_indices(self) -> None:
        plan = m._slice_plan(self.prepared, self.header)[0]
        raw = np.memmap(self.path, dtype="<f8", mode="r", offset=m.HEADER.size, shape=(9, 9, 5))
        sample = m._sample_section(raw, self.header, plan, self.prepared["geometry"]["ion_processor_electrodes"])
        np.testing.assert_array_equal(sample["flags"], sample["metal"])
        np.testing.assert_array_equal(sample["flags"], sample["flags"][:, ::-1])
        self.assertTrue((sample["xyz"][0] < 0).any())
        self.assertEqual(sample["ijk"][0][0, 0], sample["ijk"][0][0, -1])
        self.assertIn(150., sample["raw"])
        del raw

    def test_requested_and_actual_planes_are_separate(self) -> None:
        plans = m._slice_plan(self.prepared, self.header)
        self.assertEqual(plans[0]["requested_mm"], .26)
        self.assertEqual(plans[0]["actual_mm"], .5)
        self.assertEqual(plans[1]["requested_mm"], 0.)
        self.assertEqual(plans[1]["actual_mm"], 0.)

    def test_convex_mask_and_section_do_not_use_bounding_box(self) -> None:
        # Right triangular prism x>=0,z>=0,x+z<=2, |y|<=1.
        wedge = dict(shape="convex_polyhedron", vertices_mm=[[x, y, z] for y in [-1., 1.] for x, z in [(0., 0.), (2., 0.), (0., 2.)]])
        xyz = [np.array([.25, 1.5]), np.zeros(2), np.array([.25, 1.5])]
        np.testing.assert_array_equal(m._mask(wedge, xyz), [True, False])
        np.testing.assert_array_equal(_shape_mask(wedge, 1.5, np.zeros(2), np.array([.25, 1.5])), [True, False])
        section = m._section_shapes(wedge, 1, 0., (0, 2))
        self.assertEqual(len(section[0][1]), 3)
        self.assertEqual(m._section_shapes(wedge, 1, 2., (0, 2)), [])

    def test_holes_and_exact_box_plane_intersection(self) -> None:
        body = dict(solids=[_box([-2.]*3, [2.]*3)], cutouts=[_box([-.5]*3, [.5]*3)])
        xyz = [np.array([0., 1.]), np.zeros(2), np.zeros(2)]
        np.testing.assert_array_equal(m._metal([body], xyz), [False, True])
        self.assertEqual(m._section_shapes(body["solids"][0], 2, 3., (0, 1)), [])
        self.assertEqual(m._section_shapes(body["solids"][0], 2, 0., (0, 1))[0][1], [[-2., -2.], [2., -2.], [2., 2.], [-2., 2.]])

    def test_unknown_or_mismatched_header_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            m._slice_plan(self.prepared, replace(self.header, raw_mirror=0))
        with self.assertRaises(ValueError):
            m._slice_plan(self.prepared, replace(self.header, dx_mm=.1))
        with self.assertRaises(ValueError):
            m._mask(dict(shape="unsupported"), [np.zeros(1)]*3)
        self.path.write_bytes(self.header.pack())
        with self.assertRaises(ValueError):
            m.read_pa_header(self.path)

    def test_export_is_source_preserving_headless_and_canonical(self) -> None:
        before = self.path.read_bytes()
        result = m.export_mesh_diagnostics(self.run)
        self.assertEqual(result["field_count"], 1)
        metadata = json.loads(Path(result["metadata"]["path"]).read_text(encoding="utf-8"))
        record = metadata["fields"][0]
        self.assertFalse(record["full_pa_hash_performed"])
        self.assertEqual(len(record["sections"]), 4)
        self.assertEqual([s["name"] for s in record["sections"]][2:],
                         ["yz_at_beam_axis", "yz_at_e11_body_center"])
        self.assertEqual(self.path.read_bytes(), before)
        for section in record["sections"]:
            self.assertEqual(section["mismatch_count"], 0)
            with Path(section["coordinates"]["path"]).open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), section["node_count"])
            if 0 in section["axes"]:
                self.assertTrue(any(float(row["x_mm"]) < 0 for row in rows))
            else:
                self.assertEqual(len({row["x_mm"] for row in rows}), 1)
            self.assertEqual(len(section["figures"]), 2)

    def test_circle_aperture_xy_and_thickness_slices_and_grid_report(self) -> None:
        plate = self._install_aperture()
        plans = m._slice_plan(self.prepared, self.header)
        self.assertEqual([p["name"] for p in plans if "aperture_index" in p], ["aperture_00_xy_center", "aperture_00_xz_thickness"])
        topology = self._topology(plate)
        self.assertEqual(topology["status"], "PASS_sampled_z_node_columns")
        self.assertEqual(topology["open_columns"], 9)
        self.assertEqual(topology["blocked_hole_columns"], 0)
        self.assertEqual(topology["actual_z_layers_mm"], [-1.5, -1.])
        self.assertEqual(topology["plate_thickness_gu"], 1.)
        self.assertEqual(topology["opening_widths_xy_gu"], [3., 3.])
        self.assertGreater(topology["represented_metal_nodes"], 0)
        self.assertEqual(topology["missing_metal_nodes"], 0)
        before = self.path.read_bytes()
        result = m.export_mesh_diagnostics(self.run)
        metadata = json.loads(Path(result["metadata"]["path"]).read_text(encoding="utf-8"))
        self.assertEqual(len(metadata["fields"][0]["sections"]), 6)
        self.assertEqual(metadata["fields"][0]["aperture_topology"][0]["open_columns"], 9)
        self.assertEqual(self.path.read_bytes(), before)

    def test_one_blocked_column_preserves_evidence_without_good_tolerance(self) -> None:
        plate = self._install_aperture()
        raw = np.memmap(self.path, dtype="<f8", mode="r+", offset=m.HEADER.size, shape=(9, 9, 5))
        raw[2, 4, 0] = 200.
        raw.flush(); del raw
        report = self._topology(plate)
        self.assertEqual(report["open_columns"], 8)
        self.assertEqual(report["blocked_hole_columns"], 1)
        with Path(report["columns"]["path"]).open(encoding="utf-8", newline="") as stream:
            center = next(row for row in csv.DictReader(stream) if float(row["x_mm"]) == float(row["y_mm"]) == 0.)
        self.assertEqual(center["status"], "blocked")

    def test_y_slit_and_unresolved_plate_layers_are_explicit(self) -> None:
        plate = self._install_aperture("y_slit")
        report = self._topology(plate)
        self.assertEqual(report["opening_widths_xy_mm"], [2., .5])
        self.assertEqual(report["hole_candidate_columns"], 5)
        self.assertEqual(report["open_columns"], 5)
        plate = self._install_aperture(thickness=.1)
        report = self._topology(plate)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["failure_reason"], "no_node_layers_in_plate")
        self.assertFalse(report["fly_permitted_by_this_check"])
        plate = self._install_aperture()
        raw = np.memmap(self.path, dtype="<f8", mode="r+", offset=m.HEADER.size, shape=(9, 9, 5))
        raw[:] = 0.
        raw.flush(); del raw
        report = self._topology(plate)
        self.assertEqual(report["failure_reason"], "plate_metal_not_represented")

    def test_fully_blocked_circle_saves_diagnostics_before_fly_rejection(self) -> None:
        self._install_aperture()
        raw = np.memmap(self.path, dtype="<f8", mode="r+", offset=m.HEADER.size, shape=(9, 9, 5))
        raw[2, :, :] = 200.
        raw.flush(); del raw
        with self.assertRaisesRegex(ValueError, "Fly prohibited"):
            m.export_mesh_diagnostics(self.run)
        metadata_path = self.run/"results/mesh_diagnostics/metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["status"], "FAIL")
        self.assertEqual(metadata["failed_apertures"][0]["reason"], "all_hole_columns_blocked")
        field = metadata["fields"][0]
        self.assertEqual(len(field["sections"]), 6)
        self.assertEqual(field["aperture_topology"][0]["open_columns"], 0)
        self.assertTrue(Path(field["aperture_topology"][0]["nodes"]["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
