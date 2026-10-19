"""Synthetic impulse closure, full census and headless export; no commercial solver."""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from common.contracts.particle_physics import charge_to_mass_c_per_kg
from projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_force_budget import (
    IMPULSE_COLUMNS, STEP_COLUMNS, build_force_budget_figure, covariance_budget,
    export_force_budget, extraction_surfaces, prepare_force_budget, spatial_fractions,
)
from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection

PROJECT = Path(__file__).resolve().parents[1]


def write_table(path: Path, rows: list[dict], fields: tuple | list) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class ForceBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ip_force_budget_")
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        for sub in ("inputs", "simion", "results"):
            (self.run/sub).mkdir()
        read = lambda name: json.loads((PROJECT/f"config/{name}.json").read_text(encoding="utf-8-sig"))
        self.config = dict(baseline=read("baseline"), source=read("source"),
                           coordinate_transform=read("coordinate_transform"),
                           native_timing={"primary_quench_us": 7500})
        self.config["native_projection"] = native_projection(self.config["baseline"], read("numerics"))
        self.model = self.run/"inputs/resolved_model.json"
        self.model.write_text(json.dumps(self.config), encoding="utf-8")
        event_fields = ["particle_id", "event", "t_us", "x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us", "reason"]
        events = []
        self.steps, self.impulses = [], []
        species = self.config["source"]["species"]
        self.factor = charge_to_mass_c_per_kg(species["mass_amu"], species["charge_state"]) * 1e-3
        for pid in range(1, 101):
            common = dict(particle_id=pid, x_mm=pid*.01, y_mm=170, z_mm=9.8,
                          vx_mm_us=pid/1000, vy_mm_us=0, vz_mm_us=-1)
            events.append(dict(common, event="source", t_us=0, reason="none"))
            if pid <= 2:
                initial = np.array([pid, 0, -1000.])
                for index in (1, 2):
                    components = np.zeros((15, 3))
                    if index == 2:
                        components[4] = [pid*10, 0, -20]
                        components[13] = [-pid*5, 0, -30]
                    residual = np.array([pid*.25, pid*.5, pid]) if index == 2 else np.zeros(3)
                    collision = np.array([0, pid, 0]) if index == 2 else np.array([0, .1*pid, 0])
                    pre = initial + components.sum(axis=0) + residual
                    post = pre + collision
                    row = dict(particle_id=pid, step_index=index, start_t_us=7500, end_t_us=7500 if index == 1 else 7501,
                               start_x_mm=pid*.01, start_y_mm=170, start_z_mm=9.8,
                               end_x_mm=pid*.01, end_y_mm=170, end_z_mm=9.8 if index == 1 else -.2, pressure_pa=.2)
                    for prefix, vector in (("start_post", initial), ("end_pre", pre), ("end_post", post)):
                        row.update({f"{prefix}_v{axis}_mm_us": value/1000 for axis, value in zip("xyz", vector, strict=True)})
                    self.steps.append(row)
                    for electrode, vector in enumerate(components, 1):
                        impulse = dict(particle_id=pid, step_index=index, electrode_id=electrode,
                                       start_t_us=row["start_t_us"], end_t_us=row["end_t_us"],
                                       max_reconstruction_error_v_per_mm=0)
                        for axis, value in zip("xyz", vector, strict=True):
                            impulse[f"integral_e{axis}_v_us_per_mm"] = value/self.factor
                            impulse[f"fine_minus_coarse_e{axis}_v_us_per_mm"] = value/self.factor*.001
                            impulse[f"unit_integral_e{axis}_us_per_mm"] = value/self.factor/10
                        self.impulses.append(impulse)
                    initial = post
                common.update(vx_mm_us=post[0]/1000, vy_mm_us=post[1]/1000, vz_mm_us=post[2]/1000, z_mm=-.2)
                if pid == 1:
                    events.append(dict(common, event="extraction_exit", t_us=7500.9, reason="acceptance_surface", z_mm=0))
            events.append(dict(common, event="terminal", t_us=7501 if pid <= 2 else 1,
                               reason="acceptance_surface" if pid == 1 else "electrode"))
        write_table(self.run/"simion/events.csv", events, event_fields)
        self.write_audits()

    def write_audits(self) -> None:
        write_table(self.run/"simion/extraction_steps.csv", self.steps, STEP_COLUMNS)
        write_table(self.run/"simion/extraction_impulses.csv", self.impulses, IMPULSE_COLUMNS)

    def test_unscaled_electric_collision_and_residual_close_full_census(self) -> None:
        data = prepare_force_budget(self.run)
        self.assertEqual(data["source_count"], 100)
        self.assertEqual(len(data["particles"]), 100)
        self.assertEqual(len(data["losses"]), 99)
        self.assertEqual(data["covariance"]["count"], 2)
        first = data["particles"][0]
        self.assertAlmostEqual(first["actual_electric_delta_v_x_m_s"], 5.25)
        self.assertAlmostEqual(first["collision_delta_v_y_m_s"], 1.1)
        self.assertAlmostEqual(first["field_residual_delta_v_x_m_s"], .25)
        self.assertAlmostEqual(first["audit_last_minus_interpolated_exit_us"], .1)
        self.assertEqual(data["particles"][2]["availability"], "not_recorded_in_audit_window")
        self.assertEqual(data["particles"][1]["terminal_reason"], "electrode")
        self.assertLess(data["covariance"]["covariance_closure_max_abs_m2_s2"], 1e-9)
        self.assertLess(data["spatial_covariance"]["covariance_closure_max_abs_m2_s2"], 1e-9)
        e5 = next(row for row in data["electrodes"] if row["particle_id"] == 1 and row["electrode_id"] == 5)
        self.assertAlmostEqual(e5["delta_v_x_m_s"], 10)
        self.assertAlmostEqual(e5["fixed_path_response_x_m_s_per_v"], 1)
        self.assertAlmostEqual(e5["signed_5_minus_3_node_delta_v_x_m_s"], .01)
        self.assertTrue(all(row["event_csv_line"] > 1 for row in data["losses"]))
        self.assertEqual(data["phase_space"]["actual_last"]["count"], 2)
        self.assertEqual(np.asarray(data["phase_space"]["actual_last"]["covariance"]).shape, (6, 6))
        self.assertEqual(data["phase_space"]["actual_last"]["angles"]["count"], 2)

    def test_geometry_and_chord_split_derive_surfaces_and_preserve_sum(self) -> None:
        surfaces = extraction_surfaces(self.config)
        np.testing.assert_allclose(surfaces["planes_z_mm"], [7.8, 7.3, 6.8, 6.3])
        changed = copy.deepcopy(self.config)
        changed["coordinate_transform"]["translation_mm"][2] += 2
        np.testing.assert_allclose(extraction_surfaces(changed)["planes_z_mm"], np.array(surfaces["planes_z_mm"])+2)
        fractions = spatial_fractions(9.8, -.2, surfaces["planes_z_mm"])
        np.testing.assert_allclose(fractions, [.2, .05, .05, .05, .65])
        np.testing.assert_allclose(spatial_fractions(-.2, 9.8, surfaces["planes_z_mm"]), fractions)
        self.assertEqual(float(fractions.sum()), 1)
        data = prepare_force_budget(self.run)
        collision_y = [row["delta_v_y_m_s"] for row in data["spatial"]
                       if row["particle_id"] == 1 and row["component"] == "collision"]
        np.testing.assert_allclose(collision_y, [.1, 0, 0, 0, 1])

    def test_full_xyz_covariance_includes_negative_cross_component_terms(self) -> None:
        terms = np.array([[[1, 2, 3], [-2, -1, 1]], [[-1, -2, -3], [2, 1, -1]]], dtype=float)
        result = covariance_budget(terms, ["initial", "field"], terms.sum(axis=1))
        matrix = np.array(result["matrix_m2_s2"])
        self.assertEqual(matrix.shape, (6, 6))
        self.assertEqual(matrix[0, 3], -2)
        self.assertEqual(matrix[0, 4], -1)
        self.assertEqual(result["covariance_closure_max_abs_m2_s2"], 0)

    def test_variance_growth_preserves_signed_cross_terms_and_matches_last_state(self) -> None:
        data = prepare_force_budget(self.run)
        covariance = np.asarray(data["covariance"]["matrix_m2_s2"])
        final = np.asarray(data["covariance"]["final_covariance_m2_s2"])
        for index, axis in enumerate("xyz"):
            contribution = sum(row["variance_contribution_m2_s2"] for row in data["variance_terms"]
                               if row["axis"] == axis and row["included_in_variance_growth"])
            self.assertAlmostEqual(contribution, final[index, index]-covariance[index, index])
        self.assertTrue(any(row["variance_contribution_m2_s2"] < 0 for row in data["variance_terms"]))

    def test_negative_charge_retains_signed_electric_response_without_rebalancing(self) -> None:
        self.config["source"]["species"]["charge_state"] = -1
        self.model.write_text(json.dumps(self.config), encoding="utf-8")
        data = prepare_force_budget(self.run)
        e5 = next(row for row in data["electrodes"] if row["particle_id"] == 1 and row["electrode_id"] == 5)
        self.assertAlmostEqual(e5["delta_v_x_m_s"], -10)
        self.assertAlmostEqual(e5["fixed_path_response_x_m_s_per_v"], -1)
        self.assertGreater(data["particles"][0]["field_residual_delta_v_x_m_s"], 10)

    def test_interpolated_terminal_may_precede_actual_last_callback(self) -> None:
        path = self.run/"simion/events.csv"
        with path.open(newline="") as stream:
            events = list(csv.DictReader(stream))
        for row in events:
            if row["particle_id"] == "1" and row["event"] == "terminal":
                row["t_us"] = 7500.9
                row["z_mm"] = 0
        write_table(path, events, list(events[0]))
        first = prepare_force_budget(self.run)["particles"][0]
        self.assertGreater(first["audit_last_t_us"], first["terminal_t_us"])
        self.assertAlmostEqual(first["actual_last_minus_interpolated_exit_z_mm"], -.2)

    def test_missing_audit_and_bad_headers_fail_closed(self) -> None:
        (self.run/"simion/extraction_impulses.csv").unlink()
        with self.assertRaisesRegex(FileNotFoundError, "required extraction"):
            prepare_force_budget(self.run)
        write_table(self.run/"simion/extraction_impulses.csv", [], ["particle_id"])
        with self.assertRaisesRegex(ValueError, "columns"):
            prepare_force_budget(self.run)

    def test_incomplete_duplicate_and_unknown_electrode_records_fail(self) -> None:
        original = self.impulses
        for rows in (original[:-1], original+[original[0]], [dict(original[0], electrode_id=16), *original[1:]]):
            with self.subTest(count=len(rows)):
                self.impulses = rows
                self.write_audits()
                with self.assertRaisesRegex(ValueError, "15 electrode|duplicate|unknown"):
                    prepare_force_budget(self.run)

    def test_broken_state_clocks_and_continuity_fail(self) -> None:
        original = copy.deepcopy(self.steps)
        for field, value in (("start_t_us", 7499), ("start_post_vx_mm_us", 42), ("start_x_mm", 42), ("pressure_pa", float("nan"))):
            with self.subTest(field=field):
                self.steps = copy.deepcopy(original)
                self.steps[1][field] = value
                self.write_audits()
                with self.assertRaises(ValueError):
                    prepare_force_budget(self.run)

    def test_headless_export_has_english_units_and_refuses_overwrite(self) -> None:
        before = (self.run/"simion/extraction_steps.csv").read_bytes()
        data = prepare_force_budget(self.run)
        figure = build_force_budget_figure(data)
        labels = [axis.get_xlabel()+axis.get_ylabel()+axis.get_title() for axis in figure.axes]
        self.assertTrue(any("m/s" in label for label in labels))
        self.assertTrue(any("Unassigned" in label for label in labels))
        self.assertTrue(any("Cov(vx" in label for label in labels))
        figure.clear()
        result = export_force_budget(self.run)
        self.assertEqual(result["source_particle_count"], 100)
        output = self.run/"results/extraction_force_budget"
        for name in ("budget.json", "particles.csv", "electrodes.csv", "spatial.csv", "steps.csv", "losses.csv", "variance_terms.csv", "impulse_phase_space.png", "impulse_phase_space.svg"):
            self.assertGreater((output/name).stat().st_size, 0)
        self.assertEqual(before, (self.run/"simion/extraction_steps.csv").read_bytes())
        with self.assertRaises(FileExistsError):
            export_force_budget(self.run)

    def test_no_window_states_keep_all_unavailable_and_render(self) -> None:
        self.steps, self.impulses = [], []
        self.write_audits()
        path = self.run/"simion/events.csv"
        with path.open(newline="") as stream:
            events = [row for row in csv.DictReader(stream) if row["event"] != "extraction_exit"]
        for row in events:
            if row["event"] == "terminal":
                row.update(t_us=1, reason="electrode")
        write_table(path, events, list(events[0]))
        result = export_force_budget(self.run)
        self.assertEqual(result["available_particle_count"], 0)
        self.assertIsNone(result["covariance"]["matrix_m2_s2"])
        with (self.run/"results/extraction_force_budget/particles.csv").open(newline="") as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 100)

    def test_header_only_cannot_hide_surviving_window_particles(self) -> None:
        self.steps, self.impulses = [], []
        self.write_audits()
        with self.assertRaisesRegex(ValueError, "availability"):
            prepare_force_budget(self.run)


if __name__ == "__main__":
    unittest.main()
