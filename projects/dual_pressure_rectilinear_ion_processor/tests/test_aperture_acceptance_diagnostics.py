"""Analytic single-aperture position, timing and full-census regressions."""
from __future__ import annotations

import copy
import unittest

from projects.dual_pressure_rectilinear_ion_processor.analysis.aperture_acceptance_diagnostics import (
    build_aperture_figure,
    prepare_aperture_diagnostics,
)


def _case() -> dict:
    rows = [dict(particle_id=pid, plane_z_mm=0., status="alive", x_mm=x, y_mm=0., z_mm=0.,
                 t_us=t, vx_mm_us=vx, vy_mm_us=0., vz_mm_us=-2., total_energy_eV=energy)
            for pid, x, vx, t, energy in ((1, 0., 0., 1., 100.), (2, .5, 1., 1.002, 102.), (3, 1., 0., 1.004, 104.))]
    return dict(label="A", sources=dict.fromkeys((1, 2, 3, 4)), exits=dict.fromkeys((1, 2, 3)), states=rows)


def _contract() -> dict:
    return dict(drift_lengths_mm=[0., 2.], aperture_radii_mm=[1.], center_x_mm=0., center_y_mm=0.)


class ApertureDiagnosticsTests(unittest.TestCase):
    def test_position_selection_boundary_drift_and_complete_census(self) -> None:
        result = prepare_aperture_diagnostics([_case()], _contract())
        selected = result["summary_rows"]
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["role"], "hypothetical_aperture_acceptance")
        self.assertNotIn("statistics", result)
        self.assertNotIn("decisions", result)
        self.assertEqual(selected[0]["accepted_ids"], [1, 2, 3])
        self.assertEqual(selected[1]["accepted_ids"], [1, 3])
        self.assertEqual(selected[1]["rejected_exit_ids"], [2])
        self.assertEqual(selected[1]["upstream_not_extracted_ids"], [4])
        self.assertEqual(selected[1]["transmission_mother"], .5)
        self.assertEqual(selected[1]["transmission_exit"], 2/3)
        self.assertAlmostEqual(selected[1]["sigma_t_ns"], 2.)
        self.assertAlmostEqual(selected[1]["central90_time_ns"], 3.6)
        self.assertAlmostEqual(selected[1]["sigma_total_energy_eV"], 2.)
        self.assertEqual(selected[1]["sigma_theta_x_deg"], 0.)
        self.assertEqual(len(result["particle_rows"]), 16)
        rejected = next(row for row in result["particle_rows"] if row["drift_length_mm"] == 2 and row["aperture_radius_mm"] == 1 and row["particle_id"] == 2)
        self.assertEqual(rejected["predicted_x_mm"], 1.5)
        self.assertEqual(rejected["predicted_t_us"], 2.002)
        self.assertNotIn("original_state", rejected)
        self.assertNotIn("predicted_state", rejected)
        self.assertEqual(_case()["states"][1]["x_mm"], .5)

    def test_center_and_point_aperture_singleton_widths_are_null(self) -> None:
        contract = dict(_contract(), center_x_mm=.5, aperture_radii_mm=[0.], drift_lengths_mm=[0.])
        rows = prepare_aperture_diagnostics([_case()], contract)["summary_rows"]
        self.assertEqual(rows[0]["accepted_ids"], [2])
        for key in ("sigma_theta_x_deg", "sigma_theta_y_deg", "sigma_t_ns", "central90_time_ns", "sigma_total_energy_eV"):
            self.assertIsNone(rows[0][key])

    def test_absolute_time_velocity_dependence_and_unfiltered_reference(self) -> None:
        case = _case()
        case["states"][1]["vz_mm_us"] = -1.
        result = prepare_aperture_diagnostics([case], _contract())
        particle = next(row for row in result["particle_rows"] if row["drift_length_mm"] == 2 and row["aperture_radius_mm"] is None and row["particle_id"] == 2)
        self.assertEqual(particle["original_t_us"], 1.002)
        self.assertEqual(particle["predicted_t_us"], 3.002)
        self.assertEqual(particle["predicted_x_mm"], 2.5)
        self.assertEqual(particle["predicted_total_energy_eV"], particle["original_total_energy_eV"])
        references = result["reference_rows"]
        self.assertEqual(references[1]["accepted_ids"], [1, 2, 3])
        self.assertGreater(references[1]["sigma_t_ns"], references[0]["sigma_t_ns"])
        self.assertEqual(references[1]["sigma_theta_x_deg"], references[0]["sigma_theta_x_deg"])

    def test_empty_exit_and_empty_mother_are_explicit_and_plot_safe(self) -> None:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        case = dict(label="empty", sources={1: None}, exits={}, states=[])
        result = prepare_aperture_diagnostics([case], _contract())
        row = result["summary_rows"][0]
        self.assertEqual(row["transmission_mother"], 0.)
        self.assertIsNone(row["transmission_exit"])
        self.assertIsNone(row["sigma_t_ns"])
        self.assertEqual(len(result["particle_rows"]), 4)
        figure = build_aperture_figure(result)
        self.assertEqual(len(figure.axes), 4)
        figure.canvas.draw()
        plt.close(figure)
        case["sources"] = {}
        self.assertIsNone(prepare_aperture_diagnostics([case], _contract())["summary_rows"][0]["transmission_mother"])

    def test_invalid_or_incomplete_states_and_contract_fail_closed(self) -> None:
        for key, value in (("vz_mm_us", 0.), ("t_us", float("nan")), ("z_mm", .01), ("total_energy_eV", -1.)):
            case = _case()
            case["states"][0][key] = value
            with self.assertRaises(ValueError):
                prepare_aperture_diagnostics([case], _contract())
        case = _case()
        case["states"].pop()
        with self.assertRaises(ValueError):
            prepare_aperture_diagnostics([case], _contract())
        case = _case()
        case["states"].append(copy.deepcopy(case["states"][0]))
        with self.assertRaises(ValueError):
            prepare_aperture_diagnostics([case], _contract())
        for patch in (dict(aperture_radii_mm=[-1.]), dict(drift_lengths_mm=[0., 0.]), dict(center_x_mm=True), dict(hidden_cut=1)):
            with self.assertRaises(ValueError):
                prepare_aperture_diagnostics([_case()], dict(_contract(), **patch))


if __name__ == "__main__":
    unittest.main()
