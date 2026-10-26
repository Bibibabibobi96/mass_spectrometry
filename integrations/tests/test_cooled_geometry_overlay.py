"""Frozen conditioner sections, native placement and default-figure regressions."""
from __future__ import annotations

import copy
import unittest

import matplotlib.pyplot as plt
from matplotlib.path import Path
import numpy as np
import pandas as pd

from integrations.analysis.plot_single_flight_spatial_six_panel import build_local_shared_time_figure
from integrations.tests.test_cooled_frontend import cooled_fixture
from integrations.workflows.cooled_frontend.geometry import compile_cooled_frontend
from integrations.workflows.cooled_frontend.plot_geometry import add_conditioner_section, prepare_conditioner_sections


def frontend_fixture(variant: str = "three_zone") -> dict:
    guide, connection, component, conditioner, _ = cooled_fixture(variant)
    return compile_cooled_frontend(guide, connection, component, conditioner,
                                  cell_mm_xyz=dict(x=.2, y=.2, z=.2), exit_gap_mm=1.)[1]


class CooledGeometryOverlayTests(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_longitudinal_real_gate_positions_and_circular_hole_chord(self):
        conditioner = frontend_fixture()["conditioner_contract"]
        original = copy.deepcopy(conditioner)
        sections = prepare_conditioner_sections(conditioner, transverse="y", cut_mm=0.)
        for name, low, high in (("entrance_gate", -67.5, -67.), ("exit_gate", 33., 33.5)):
            paths = [item["path"] for item in sections if item["name"] == name]
            self.assertEqual(len(paths), 2)
            extents = sorted(tuple(path.get_extents().extents) for path in paths)
            np.testing.assert_allclose(extents, [(29., low, 31., high), (33., low, 35., high)])
        # Off-axis longitudinal section uses the circle chord, not an AABB hole.
        off = prepare_conditioner_sections(conditioner, transverse="y", cut_mm=.6)
        limits = sorted(tuple(item["path"].get_extents().extents) for item in off if item["name"] == "exit_gate")
        np.testing.assert_allclose(limits, [(29., 33., 31.2, 33.5), (32.8, 33., 35., 33.5)])
        self.assertEqual(conditioner, original)

    def test_corner_and_inner_sections_are_actual_finite_csg(self):
        conditioner = frontend_fixture()["conditioner_contract"]
        center = conditioner["geometry"]["trap_center_mr_mm"]
        sections = prepare_conditioner_sections(conditioner, transverse="x", cut_mm=center[1])
        corners = [item for item in sections if item["name"] == "hp_auxiliary"]
        self.assertEqual(len(corners), 4)
        self.assertEqual({item["electrode_id"] for item in sections}, {40, 41, 42, 44, 45})
        inner = [tuple(item["path"].get_extents().extents) for item in sections if item["name"] == "end_inner_auxiliary"]
        np.testing.assert_allclose(sorted(inner), [(31.85, -1.6, 32.15, -1.4), (31.85, 1.4, 32.15, 1.6)])
        outside = prepare_conditioner_sections(conditioner, transverse="x", cut_mm=center[1]-2.)
        self.assertNotIn("end_inner_auxiliary", {item["name"] for item in outside})

    def test_gate_cross_section_preserves_round_aperture_and_draws_white_vacuum(self):
        conditioner = frontend_fixture()["conditioner_contract"]
        sections = prepare_conditioner_sections(conditioner, transverse="x", cut_mm=33.25)
        path = next(item["path"] for item in sections if item["name"] == "exit_gate")
        self.assertIn(Path.CURVE4, path.codes)
        fig, ax = plt.subplots(figsize=(2, 2), dpi=100)
        add_conditioner_section(ax, conditioner, transverse="x", cut_mm=33.25)
        ax.set(xlim=(28, 36), ylim=(-4, 4))
        fig.canvas.draw()
        pixels = np.asarray(fig.canvas.buffer_rgba())
        def rgb(z, x):
            px, py = ax.transData.transform((z, x))
            return pixels[pixels.shape[0]-1-round(py), round(px), :3]
        self.assertTrue(np.all(rgb(32., 0.) == 255))
        # Inside the square AABB of the aperture but outside its radius: metal.
        self.assertFalse(np.all(rgb(32.8, .8) == 255))

    def test_convex_shape_is_not_replaced_by_its_rectangular_bounds(self):
        conditioner = frontend_fixture()["conditioner_contract"]
        electrode = conditioner["native_projection_fragment"]["electrodes"][0]
        electrode["solids"] = [dict(shape="convex_polyhedron", vertices_mm=[
            [x, y, z] for x in (124., 126.) for y, z in ((-2., -2.), (-2., 2.), (2., 0.))])]
        items = prepare_conditioner_sections(conditioner, transverse="x", cut_mm=28.)
        path = next(item["path"] for item in items if item["name"] == "hp_rf_a")
        self.assertEqual(len(path.vertices), 4)  # closed triangle, not an AABB
        np.testing.assert_allclose(sorted(map(tuple, path.vertices[:-1])), [(30., 0.), (34., -2.), (34., 2.)])

    def test_both_oa_variants_keep_stats_and_add_all_conditioner_ids_in_same_figure(self):
        for variant in ("two_zone", "three_zone"):
            frontend = frontend_fixture(variant)
            before = copy.deepcopy(frontend)
            active = pd.DataFrame([dict(requested_time_us=1., z_mm=32., x_mm=.1, y_mm=28.)])
            unchanged = active.copy(deep=True)
            counts = [dict(instrument_time_us=1., active=1, not_born=0, already_exit=0, already_loss=0, numerical_unsupported=0)]
            figure, axes = build_local_shared_time_figure(active, counts, frame_id="mrtof_global_cartesian",
                frontend_contract=frontend, terminal_rows=pd.DataFrame())
            figure.canvas.draw()
            all_axes = [a for main in axes.flat for a in (main, *main.child_axes)]
            gids = {artist.get_gid() for ax in all_axes for artist in ax.get_children() if artist.get_gid()}
            for eid in range(40, 47):
                self.assertTrue(any(gid.startswith(f"conditioner_geometry_{eid}_") for gid in gids))
            self.assertEqual(len(axes[0, 0].child_axes), 1)
            self.assertEqual(axes[0, 0].collections[0].get_offsets().tolist(), [[32., .1]])
            self.assertLess(axes[1, 0].get_ylim()[0], -97.)
            self.assertGreater(axes[1, 0].get_ylim()[1], 33.5)
            legend = [text.get_text() for text in figure.legends[0].texts]
            self.assertIn("E42 HP corner auxiliary", legend)
            self.assertIn("E45 Terminal inner auxiliary", legend)
            self.assertEqual(frontend, before)
            pd.testing.assert_frame_equal(active, unchanged)
            plt.close(figure)

    def test_bad_pose_and_incomplete_identity_fail_closed(self):
        conditioner = frontend_fixture()["conditioner_contract"]
        conditioner["native_to_mr"]["rotation"][0][0] = 1.
        with self.assertRaisesRegex(ValueError, "pose"):
            prepare_conditioner_sections(conditioner, transverse="y", cut_mm=0.)
        conditioner = frontend_fixture()["conditioner_contract"]
        conditioner["electrode_ids"]["unknown"] = 99
        with self.assertRaisesRegex(ValueError, "identities"):
            prepare_conditioner_sections(conditioner, transverse="y", cut_mm=0.)


if __name__ == "__main__":
    unittest.main()
