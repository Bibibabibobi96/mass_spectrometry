"""Independent analytic optics/PA fixtures; no native solver or external runs."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

import matplotlib
matplotlib.use("Agg")
import numpy as np

from projects.parallel_mirror_dual_stripe_mr_tof.analysis import ip_prism_field_theory as theory
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.standalone_pa_composition import PaHeader


def source(pid, x, vx, t=100., z=0., vz=-2.):
    return dict(particle_id=pid, x_mm=x, y_mm=.2, z_mm=z, vx_mm_us=vx,
                vy_mm_us=0., vz_mm_us=vz, t_us=t)


def quadratic_fixture():
    header = PaHeader(-2, 1, 10000., 9, 9, 13, 1 | (100 << 4), .5, .5, .5)
    z, y, x = np.meshgrid(np.arange(13)*.5-4, np.arange(9)*.5-2, np.arange(9)*.5, indexing="ij")
    return header, x*x+2*y*y-3*z*z+4*y+5*z, [0., -2., -4., 4., 2., 2.]


class FieldTheoryTests(unittest.TestCase):
    def test_linear_lens_and_emittance(self):
        # Orthogonal centered x/residual signs: x variance 1, residual variance .01.
        rows = [source(i+1, x, 2*(.3*x+.1*noise)) for i, (x, noise) in
                enumerate([(-1, -1), (-1, 1), (1, -1), (1, 1)])]
        row = theory.linear_optics(rows)[0]
        self.assertAlmostEqual(row["thin_lens_best_k_per_mm"], .3)
        self.assertAlmostEqual(row["residual_slope_lower_bound"], .1)
        self.assertAlmostEqual(row["rms_emittance_mm"], .1)
        self.assertAlmostEqual(row["unconstrained_waist_distance_mm"], -3.)
        self.assertNotAlmostEqual(row["sigma_projected_angle_rad"], row["sigma_slope"])
        x = np.array([r["x_mm"] for r in rows])
        slope = np.array([r["vx_mm_us"]/2 for r in rows])
        collimated = slope-.3*x
        self.assertAlmostEqual(float(np.std(collimated)), .1)
        # Independent thin-lens ray map to a target 2 mm downstream.
        k_spot = .3+1/2
        spot = x+2*(slope-k_spot*x)
        self.assertAlmostEqual(float(np.std(spot)), .2)
        self.assertGreater(float(np.std(x+2*(slope-(k_spot+.1)*x))), float(np.std(spot)))

    def test_empty_and_constant(self):
        self.assertIsNone(theory.linear_optics([])[0]["rms_emittance_mm"])
        row = theory.linear_optics([source(1, 1, 0), source(2, 1, 0)])[0]
        self.assertIsNone(row["thin_lens_best_k_per_mm"])
        self.assertIsNone(row["unconstrained_waist_distance_mm"])

    def test_exact_quadratic_anisotropic_and_mirror(self):
        header, raw, box = quadratic_fixture()
        for x in [1., -1., 0.]:
            row = theory.probe_pa(raw, header, box, [x, .5, -1.])
            self.assertEqual(row["status"], "valid")
            self.assertAlmostEqual(row["potential_v"], x*x-5.5)
            self.assertAlmostEqual(row["ex_v_per_mm"], -2*x)
            self.assertAlmostEqual(row["ey_v_per_mm"], -6)
            self.assertAlmostEqual(row["ez_v_per_mm"], -11)
            self.assertAlmostEqual(row["d2v_dx2_v_per_mm2"], 2)
            self.assertAlmostEqual(row["d2v_dy2_v_per_mm2"], 4)
            self.assertAlmostEqual(row["d2v_dz2_v_per_mm2"], -6)
            self.assertAlmostEqual(row["laplacian_v_per_mm2"], 0)
        from dataclasses import replace
        header = replace(header, dx_mm=.25, dy_mm=.4, dz_mm=.2)
        z, y, x = np.meshgrid(np.arange(13)*.2-4, np.arange(9)*.4-2, np.arange(9)*.25, indexing="ij")
        row = theory.probe_pa(x*x+2*y*y-3*z*z, header, [0, -2, -4, 2, 1.2, -1.6], [-.5, -.8, -3.])
        self.assertAlmostEqual(row["ex_v_per_mm"], 1)
        self.assertAlmostEqual(row["d2v_dz2_v_per_mm2"], -6)

    def test_invalid_stencil_preserved(self):
        header, raw, box = quadratic_fixture()
        self.assertEqual(theory.probe_pa(raw, header, box, [4, 0, -1])["reason"], "stencil_outside_pa")
        self.assertEqual(theory.probe_pa(raw, header, box, [4.1, 0, -1])["reason"], "probe_outside_pa")
        raw[6, 4, 2] = 2*header.max_voltage
        rows = theory._field_rows([source(7, 1, 0)], [dict(name="down", z_mm=-1)], header, raw, box, 524, 1)
        self.assertEqual(len(rows), 2)
        self.assertEqual(next(r for r in rows if r["plane_name"] == "down")["reason"], "electrode_in_stencil")
        self.assertEqual({r["particle_id"] for r in rows}, {7})

    def test_signed_charge_acceleration_and_longitudinal_slope_term(self):
        header, raw, box = quadratic_fixture()
        # At the rounded downstream node x=1,y=0,z=-1: Ex=-2, Ez=-11
        # for V=x²+2y²-3z²+4y+5z, with Ez=6z-5.
        # x'=0.2 therefore Ex+x'Ez=-4.2, distinctly different from Ex.
        state = source(7, 1., .4)
        mass_kg, unit_charge = 524*1.66053906660e-27, 1.602176634e-19
        kz_ev = .5*mass_kg*2000**2/unit_charge
        for charge in [1, -1]:
            rows = theory._field_rows([state], [dict(name="down", z_mm=-1)], header, raw, box, 524, charge)
            row = next(r for r in rows if r["plane_name"] == "down")
            self.assertEqual(row["status"], "valid")
            self.assertAlmostEqual(row["propagation_time_us"], .5)
            self.assertAlmostEqual(row["ex_v_per_mm"], -2.)
            self.assertAlmostEqual(row["ez_v_per_mm"], -11.)
            expected_kick = charge*unit_charge/mass_kg*(-2*1000)*(.5e-6)*1e-3
            self.assertAlmostEqual(row["local_field_hold_kick_vx_mm_us"], expected_kick)
            self.assertAlmostEqual(row["drift_path_dxprime_ds_per_mm"], charge*(-2+.2*(-11))/(2*kz_ev))

    def test_noncommon_birth_z_and_clock_and_target_lens(self):
        rows = [source(1, -1, .4, t=100, z=.5), source(2, 1, -.4, t=101, z=0)]
        original = json.dumps(rows)
        stats, optics, decisions = theory._drift_rows(rows, [dict(name="a", z_mm=-1), dict(name="b", z_mm=-2)], 524)
        self.assertAlmostEqual(stats[0]["mean_t_us"], (100.75+101.5)/2)
        self.assertAlmostEqual(stats[0]["time_sigma_ns"], 375)
        self.assertEqual(json.dumps(rows), original)
        self.assertEqual(len(decisions), 4)
        a = optics[0]
        self.assertAlmostEqual(a["thin_lens_target_spot_best_k_per_mm"], a["thin_lens_best_k_per_mm"]+1)
        self.assertAlmostEqual(a["target_spot_lower_bound_mm"], a["residual_slope_lower_bound"])

    def test_unreachable_plane_not_removed(self):
        stats, _, decisions = theory._drift_rows([source(1, 0, 0)], [dict(name="birth", z_mm=0)], 524)
        self.assertEqual(stats[0]["missing_ids"], [1])
        self.assertIsNone(stats[0]["time_sigma_ns"])
        self.assertEqual(decisions[0]["reason"], "plane_not_strictly_future_downstream")

    def test_paired_covariance_at_exact_crossing(self):
        rows = [source(1, -1, .4, t=100, z=.5), source(2, 1, -.4, t=101, z=0)]
        cov = theory.plane_covariances(rows, [dict(name="a", z_mm=-1)])
        # Arrival times [100.75,101.5], x=[-.7,.8]: Cov=.375*.75.
        row = next(r for r in cov if r["first_quantity"] == "t_us" and r["second_quantity"] == "x_mm")
        self.assertAlmostEqual(row["covariance"], .28125)
        self.assertTrue(row["complete_source"])

    def test_export_fixture_and_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            (run/"inputs").mkdir()
            case = run/"case"
            case.mkdir()
            header, raw, box = quadratic_fixture()
            path = case/"field.pa"
            path.write_bytes(header.pack()+np.asarray(raw, dtype="<f8").tobytes())
            original = path.read_bytes()
            states = [source(1, -.5, .1), source(2, .5, -.1)]
            (case/"source_states.json").write_text(json.dumps(states))
            (case/"geometry.json").write_text(json.dumps(dict(geometry_checks=dict(box_mm=box, grid_dimensions=[9, 9, 13]))))
            census = case/"census.csv"
            census.write_text("particle_id\n1\n2\n3\n")
            owner = dict(field_case_id="B_fixture", directory=str(case), field_path=str(path), source_census_csv=str(census),
                         source_count=2, mother_count=3, mass_u=524, charge_state=1, pitch_mm=[.5]*3)
            (run/"inputs/resolved_study.json").write_text(json.dumps(dict(field_owners=[owner], contract=dict(observation_planes=[dict(name="near", z_mm=-1), dict(name="exit", z_mm=-2)]))))
            metadata = theory.export_field_theory(run)
            self.assertEqual(metadata["fields"][0]["upstream_not_transferred_ids"], [3])
            self.assertEqual(path.read_bytes(), original)
            self.assertTrue((run/"results/field_theory/field_theory.png").stat().st_size > 1000)
            with (run/"results/field_theory/drift_path_field_probes.csv").open() as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 6)


if __name__ == "__main__":
    unittest.main()
