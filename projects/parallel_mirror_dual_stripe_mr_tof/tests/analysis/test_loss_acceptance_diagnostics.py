"""Population/contact/topology and recorded mirror-domain evidence boundaries."""
from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from matplotlib import pyplot as plt

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.loss_acceptance_diagnostics import (
    STATE, _stages, build_loss_acceptance_figure, prepare_loss_rows, prepare_mirror_domain_rows, summarize_loss_acceptance,
)


def geometry():
    result = {key: [] for key in ("mirror_electrodes", "mirror_slot", "mirror_inner_shield_slot",
              "mirror_ground_shields", "mirror_e_closures", "stripe_electrodes", "stripe_slot",
              "central_ground_electrodes", "central_ground_slots", "prism_electrodes", "prism_ground_shields")}
    result["mirror_inner_shield_slot"] = [-2, -10, -110, 2, 10, -100]
    result["mirror_slot"] = [-2, -10, -210, 2, 10, -110]
    result["mirror_ground_shields"] = [dict(box=[-10, -20, -109, 10, 20, -107])]
    result["mirror_electrodes"] = [dict(id=1, box=[-10, -20, -209, 10, 20, -111])]
    return result


def state():
    return dict(position_x_mm=.1, position_y_mm=-54, position_z_mm=0,
                velocity_x_m_s=200, velocity_y_m_s=100, velocity_z_m_s=-40000,
                mass_amu=524, charge_state=1, instrument_time_us=7500, kinetic_energy_eV=4344)


def terminal(particle, code, x=3):
    return dict(kind="terminal", ion=particle, splat=code, t_us=7512,
                x_mm=x, y_mm=0, z_mm=-107, vx_mm_us=.1, vy_mm_us=.2, vz_mm_us=40)


class LossAcceptanceDiagnosticsTests(unittest.TestCase):
    def test_contact_panels_share_automatic_z_extent_without_excluding_points(self):
        events = [terminal(1, -1), dict(terminal(2, -1), z_mm=107), terminal(79, 4)]
        census = [dict(particle_id=i, downstream_status="loss") for i in (1, 2, 79)]
        rows, collision = prepare_loss_rows(events, {i: state() for i in (1, 2, 79)}, census, geometry())
        before = repr(rows)
        figure, axes = build_loss_acceptance_figure(rows, geometry())
        try:
            expected = (-107-214*.08, 107+214*.08)
            self.assertEqual(axes[1, 0].get_xlim(), expected)
            self.assertEqual(axes[1, 1].get_xlim(), expected)
            for row in rows:
                if row["termination_kind"] == "native_contact":
                    self.assertLess(expected[0], row["terminal_z_mm"])
                    self.assertGreater(expected[1], row["terminal_z_mm"])
            summary = summarize_loss_acceptance(rows, collision, {})
            self.assertEqual(summary["geometry_context"]["contact_z_limits_mm"], list(expected))
            self.assertEqual(repr(rows), before)
        finally:
            plt.close(figure)

    def test_single_contact_has_one_mm_margin_and_empty_keeps_geometry_context(self):
        for contact in (True, False):
            events = [terminal(1, -1 if contact else 1)]
            rows, collision = prepare_loss_rows(events, {1: state()},
                [dict(particle_id=1, downstream_status="loss" if contact else "detected")], geometry())
            figure, axes = build_loss_acceptance_figure(rows, geometry())
            try:
                if contact:
                    self.assertEqual(axes[1, 0].get_xlim(), (-108, -106))
                    self.assertEqual(axes[1, 1].get_xlim(), (-108, -106))
                else:
                    self.assertLess(axes[1, 0].get_xlim()[0], -209)
                    self.assertGreater(axes[1, 0].get_xlim()[1], -100)
                    self.assertIsNone(summarize_loss_acceptance(rows, collision, {})["geometry_context"]["contact_z_limits_mm"])
            finally:
                plt.close(figure)

    def test_outline_projections_preserve_overlapping_solids_and_all_aperture_families(self):
        native = geometry()
        triangle = [[-1, -3], [-1, 3], [1, 0]]
        native["prism_ground_shields"] = [dict(x=[-5, 5], body_sections=[dict(x=[-5, 5], polygon_yz_mm=triangle)],
            prism_clearance_polygon_yz_mm=triangle, rectangular_slots_mm=[[-2, -2, -4, 2, 2, 4]])]
        native["stripe_slot"] = [-2, -2, -4, 2, 2, 4]
        native["central_ground_slots"] = [[-2, 0, -10, 2, 10, 10]]
        native["detector"] = dict(box=[-25, -87, 95, 25, -37, 97])
        native["ion_processor_electrodes"] = [dict(solids=[dict(shape="box", min_mm=[-1, -54, 6], max_mm=[1, -53, 7]),
            dict(shape="cylinder3d", endpoints_mm=[[0, -56, 8], [0, -50, 8]], radius_mm=.6)],
            cutouts=[dict(shape="box", min_mm=[-.4, -54, 6], max_mm=[.4, -53, 7])])]
        figure, axes = build_loss_acceptance_figure([], native)
        try:
            patches = [p for axis in axes[1] for p in axis.patches]
            self.assertTrue(all(not p.get_fill() for p in patches))
            self.assertTrue(all(p.get_facecolor()[3] == 0 for p in patches))
            self.assertEqual({p.get_gid() for p in patches}, {"solid_projection", "aperture_projection"})
            self.assertTrue(any(getattr(p, "get_x", lambda: None)() == 95 for p in axes[1, 0].patches))
            self.assertTrue(any(getattr(p, "center", None) == (8, 0) for p in axes[1, 0].patches))
            self.assertIn("Aperture projection", [t.get_text() for t in figure.legends[0].get_texts()])
        finally:
            plt.close(figure)

    def test_recorded_forward_negative_central_stage_is_not_clean_domain_acceptance(self):
        stage = "first_forward_negative_central_crossing"
        event = dict(kind="central_plane_directional", n=1, direction_z=-1, vy_mm_us=1, y_mm=500)
        self.assertTrue(dict(_stages([event]))[stage])
        self.assertFalse(dict(_stages([dict(event, vy_mm_us=-1)]))[stage])

    def test_native_contact_and_noncontact_topology_keep_all_mother_ids(self):
        events = [terminal(1, -1), terminal(79, 4),
                  dict(kind="splat", ion=79, code=4, t_us=7512, physical_collision=0,
                       termination_kind="programmatic_topology_rejection", reason="unexpected_post_return_mirror_turn"),
                  dict(kind="target_k_phase_sample", ion=79, t_us=7510, x_mm=.2, y_mm=16.5, z_mm=-280),
                  dict(kind="prism_entry", ion=79, n=2, t_us=7501)]
        census = [dict(particle_id=1, downstream_status="loss"), dict(particle_id=79, downstream_status="loss"),
                  dict(particle_id=24, downstream_status="not_transferred", upstream_terminal_reason="upstream loss")]
        rows, collisions = prepare_loss_rows(events, {1: state(), 79: state()}, census, geometry())
        self.assertEqual([r["particle_id"] for r in rows], [1, 79, 24])
        self.assertEqual(rows[0]["termination_kind"], "native_contact")
        self.assertEqual(rows[0]["component"], "mirror_inner_ground_shields")
        self.assertEqual(rows[0]["electrode_id"], 15)
        self.assertEqual(rows[1]["group"], "topology")
        self.assertEqual(rows[1]["component"], "")
        self.assertEqual(rows[1]["target_phase_y_mm"], 16.5)
        self.assertEqual(rows[2]["source_position_x_mm"], "")
        self.assertEqual(len(collisions["collision_particles"]), 1)
        self.assertGreater(rows[0]["source_Ex_per_charge_eV"], 0)
        figure, _ = build_loss_acceptance_figure(rows, geometry())
        plt.close(figure)

    def test_no_arrivals_and_empty_losses_have_defined_output(self):
        for events, census in (([], []), ([terminal(1, 1)], [dict(particle_id=1, downstream_status="detected")])):
            with self.subTest(census=census):
                rows, collision = prepare_loss_rows(events, {1: state()}, census, geometry())
                self.assertEqual(collision["collision_particles"], [])
                figure, _ = build_loss_acceptance_figure(rows, geometry())
                plt.close(figure)

    def test_late_contact_uses_recorded_p2_entry_not_turn_count(self):
        events = [dict(kind="prism_entry", ion=1, n=2, t_us=7501), terminal(1, -1)]
        rows, _ = prepare_loss_rows(events, {1: state()}, [dict(particle_id=1, downstream_status="loss")], geometry())
        self.assertEqual(rows[0]["group"], "later_contact")
        self.assertEqual(rows[0]["first_missing_recorded_stage"], "p1_exit")

    def test_mirror_x_counts_first_pass_and_signed_crossing_brackets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"trajectory.csv"
            values = [(0, 0, 0), (1, .5, -120), (2, 1.2, -150), (3, -1.3, -160),
                      (4, .2, 0), (5, .1, -130), (6, 9, -140)]
            with path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["ion", "phase", "t_us", *STATE])
                writer.writeheader()
                for time, x, z in values:
                    writer.writerow(dict(ion=1, phase="step", t_us=time, x_mm=x, y_mm=0,
                                         z_mm=z, vx_mm_us=.1, vy_mm_us=.2, vz_mm_us=40))
            binding = dict(geometry=geometry(), refinement_windows=[dict(name="fine_negative",
                active_box_mm=[[-1, 1], [-10, 10], [-220, -90]])])
            rows, crossings, metadata = prepare_mirror_domain_rows(path, binding, {1, 2},
                {1: dict(t_us=5), 2: dict(t_us=5)})
            all_samples, first_pass, empty_all, empty_first = rows
            self.assertEqual(all_samples["sample_count"], 4)
            self.assertEqual(all_samples["outside_x_sample_count"], 2)
            self.assertEqual(first_pass["sample_count"], 3)
            self.assertEqual(first_pass["maximum_abs_x_mm"], 1.3)
            self.assertEqual(empty_all["maximum_abs_x_mm"], "")
            self.assertEqual(empty_first["sample_count"], 0)
            self.assertEqual([r["boundary_x_mm"] for r in crossings], [1, -1, 1])
            self.assertEqual(crossings[0]["before_x_mm"], .5)
            self.assertEqual(crossings[0]["after_x_mm"], 1.2)
            self.assertIn("no interpolation", metadata["crossing"])


if __name__ == "__main__":
    unittest.main()
