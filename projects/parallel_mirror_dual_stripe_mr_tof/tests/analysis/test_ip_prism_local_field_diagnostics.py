"""Finite lens CSG/figure regressions; no solver, GUI or scientific PA input."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_local_field_diagnostics as f
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ip_prism_mesh_diagnostics import _lens_slice_plans


def _case(name="lens_case"):
    spec = dict(name="Q1", center_mm=[0., .13, .13], length_mm=2., inscribed_radius_mm=1., rod_radius_mm=.5, voltage_v=30.)
    rods = []
    for i, (pair, x, y) in enumerate((("x", 1.5, .13), ("x", -1.5, .13), ("y", 0., 1.63), ("y", 0., -1.37))):
        rods.append(dict(namespace="quadrupole_lens", element_name="Q1", pair=pair, electrode_id=1000+i,
                         name=f"Q1_{pair}_{i}", voltage_v=30. if pair == "x" else -30., specification=spec,
                         solids=[dict(shape="cylinder3d", endpoints_mm=[[x, y, -.87], [x, y, 1.13]], radius_mm=.5)], cutouts=[]))
    geometry = dict(ion_processor_electrodes=[], lens_electrodes=rods, prism_ground_shields=[],
                    prism_electrodes=[dict(parts=[dict(x=[2.5, 3.], polygon_yz_mm=[[-2., -2.], [-2., -1.], [-1., -1.]])])])
    prepared = dict(geometry=geometry, geometry_checks=dict(box_mm=[0., -3., -3., 3., 3., 3.], pitch_mm=[.25]*3,
                   grid_dimensions=[13, 25, 25]), exit_z_mm=0., gap_mm=1.)
    axis = [dict(z_mm=z, potential_v=0., ex_v_per_mm=0., ey_v_per_mm=0., ez_v_per_mm=0., electrode=0.) for z in (0., -1.)]
    return dict(case_id=name, distance_mm=52.828, prepared=prepared, axis=axis)


class LocalFieldLensTests(unittest.TestCase):
    def test_existing_off_axis_mask_contains_real_circular_rods_not_bounds(self):
        case = _case()
        image, extent = f._section(case["prepared"]["geometry"], 1.5, [0., -3., -3., 3., 3., 3.], .25)
        self.assertIn(5, image)
        self.assertEqual(extent, [-3., 3., -3., 3.])
        rod = case["prepared"]["geometry"]["lens_electrodes"][0]["solids"][0]
        np.testing.assert_array_equal(f._shape_mask(rod, 1.9, np.array([.13, .53]), np.zeros(2)), [True, False])

    def test_three_lens_views_show_four_xy_and_both_longitudinal_pairs(self):
        from matplotlib import pyplot as plt
        case = _case()
        plans = _lens_slice_plans(case["prepared"])
        fig = f._lens_geometry_figure(case, plans)
        try:
            self.assertEqual([len(ax.patches) for ax in fig.axes], [4, 2, 2])
            self.assertEqual(plans[0]["requested_mm"], .13)
            self.assertEqual(plans[0]["actual_mm"], .25)
            self.assertEqual(plans[1]["actual_mm"], .25)
            self.assertTrue(all("Actual node plane" in ax.get_title() for ax in fig.axes))
            self.assertEqual([t.get_text() for t in fig.legends[0].texts], ["x rods: +30 V", "y rods: -30 V"])
        finally:
            plt.close(fig)

    def test_field_labels_distinguish_same_distance_lens_cases(self):
        from matplotlib import pyplot as plt
        fig = f._field_figure([_case("lens_30V"), _case("lens_40V")])
        try:
            self.assertEqual([line.get_label() for line in fig.axes[0].lines], ["lens_30V", "lens_40V"])
        finally:
            plt.close(fig)

    def test_default_empty_lens_adds_no_sections(self):
        prepared = _case()["prepared"]
        prepared["geometry"].pop("lens_electrodes")
        self.assertEqual(_lens_slice_plans(prepared), [])
        prepared["geometry"]["lens_electrodes"] = []
        self.assertEqual(_lens_slice_plans(prepared), [])

    def test_default_geometry_mask_and_distance_legend_are_preserved(self):
        from matplotlib import pyplot as plt
        case = _case()
        case["prepared"]["geometry"].pop("lens_electrodes")
        geometry = case["prepared"]["geometry"]
        before, _ = f._section(geometry, 1.5, [0., -3., -3., 3., 3., 3.], .25)
        geometry["lens_electrodes"] = []
        after, _ = f._section(geometry, 1.5, [0., -3., -3., 3., 3., 3.], .25)
        np.testing.assert_array_equal(before, after)
        fig = f._field_figure([case])
        try:
            self.assertEqual(fig.axes[0].lines[0].get_label(), "D = 52.828 mm")
        finally:
            plt.close(fig)

    def test_automatic_export_adds_lens_assets_and_plane_metadata(self):
        from matplotlib.figure import Figure
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            directory = run/"simion/case_01"
            directory.mkdir(parents=True)
            (run/"inputs").mkdir()
            case = _case()
            (directory/"geometry.json").write_text(json.dumps(case["prepared"]))
            with (directory/"axis_field.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(case["axis"][0]))
                writer.writeheader(); writer.writerows(case["axis"])
            resolved = dict(cases=[dict(case_id=case["case_id"], distance_mm=case["distance_mm"], directory=str(directory))],
                            contract=dict(numerics=dict(box_mm=[0., -3., -3., 3., 3., 3.], pitch_mm=[.25]*3)))
            (run/"inputs/resolved_study.json").write_text(json.dumps(resolved))
            with patch.object(f, "_geometry_figure", return_value=Figure()):
                result = f.export_field_diagnostics(run)
            metadata = json.loads(Path(result["metadata"]["path"]).read_text())
            self.assertEqual(len(metadata["lens_sections"]), 3)
            self.assertEqual(len(result["figures"]), 6)
            self.assertTrue(all(p["lens_element_name"] == "Q1" for p in metadata["lens_sections"]))


if __name__ == "__main__":
    unittest.main()
