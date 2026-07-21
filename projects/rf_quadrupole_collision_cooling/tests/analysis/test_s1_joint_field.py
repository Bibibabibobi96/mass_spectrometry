import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "analysis"))

import validate_s1_joint_field as module  # noqa: E402
import analyze_s1_joint_field as analysis_module  # noqa: E402
import validate_field_performance_experiment as experiment_module  # noqa: E402
import validate_rf_continuous_shield as shield_module  # noqa: E402
import analyze_rf_continuous_shield_2d as shield_analysis_module  # noqa: E402


class S1JointFieldContractTests(unittest.TestCase):
    def test_repository_contract(self):
        contract = module.validate()
        self.assertEqual(contract["port_sweep"]["full_width_y_mm"], [1.0, 0.75, 0.5, 0.25])
        self.assertEqual(contract["port_sweep"]["closed_control_full_width_y_mm"], 0.0)
        self.assertTrue(contract["numerical_qualification"]["closed_control_required_before_port_selection"])
        self.assertEqual(contract["numerical_qualification"]["accelerator_routine_hmax_mm"], 1.0)
        self.assertEqual(contract["numerical_qualification"]["connector_diagnostic_hmax_mm"], 0.25)
        self.assertEqual(len(contract["numerical_qualification"]["diagnostic_controls"]), 2)
        self.assertEqual(contract["local_domain"]["oatof_downstream_buffer_diagnostic_mm"], [5.0, 15.0, 30.0])
        self.assertEqual(contract["local_domain"]["legacy_external_vacuum_diagnostic_margin_mm"], [1.0, 10.0, 30.0])
        self.assertFalse(contract["local_domain"]["external_vacuum_field_domain_included"])
        self.assertFalse(contract["permissions"]["field_solve_allowed"])
        self.assertFalse(contract["permissions"]["particle_runtime_allowed"])
        self.assertEqual(contract["evaluation"]["field_reference_role"], "diagnostic_alert_only")
        self.assertFalse(contract["evaluation"]["field_reference_alert_clear_required_for_s1_pass"])

    def test_field_performance_experiment(self):
        plan = experiment_module.validate()
        self.assertEqual([stage["id"] for stage in plan["experiment_stages"]], ["E0", "E1", "E2", "E3", "E4"])
        self.assertEqual(plan["formal_baseline_policy"]["formal_baseline_count"], 1)
        self.assertEqual(
            plan["provisional_performance_budgets"]["maximum_numerical_uncertainty_fraction_of_each_performance_budget"],
            0.2,
        )

    def test_component_profiles_and_line_integrals_are_separate(self):
        samples = pd.DataFrame({
            "x_mm": [0.0, 0.0, 0.0, 0.0],
            "y_mm": [0.0, 0.0, 0.5, 0.5],
            "z_mm": [0.0, 1.0, 0.0, 1.0],
            "Ex_V_per_m": [0.0, 0.0, 2.0, 2.0],
            "Ey_V_per_m": [0.0, 0.0, 3.0, 3.0],
            "Ez_V_per_m": [10.0, 10.0, 10.0, 10.0],
            "potential_V": [0.0, 1.0, 0.0, 1.0],
        })
        envelope = analysis_module.component_profile_envelope(samples)
        edge = envelope[np.isclose(envelope["abs_y_mm"], 0.5)].iloc[0]
        self.assertAlmostEqual(edge["ex_profile_relative_rms"], 0.2)
        self.assertAlmostEqual(edge["ey_profile_relative_rms"], 0.3)

        injection = pd.DataFrame({
            "x_mm": [0.0, 1.0],
            "static_Ex_V_per_m": [2.0, 2.0],
            "static_Ey_V_per_m": [3.0, 3.0],
            "static_Ez_V_per_m": [4.0, 4.0],
        })
        integrals = analysis_module.field_line_integrals(injection, "static")
        self.assertAlmostEqual(integrals["ex_line_integral_V"], 0.002)
        self.assertAlmostEqual(integrals["ey_line_integral_V"], 0.003)

    def test_two_formal_baselines_are_rejected(self):
        plan = experiment_module.load(experiment_module.DEFAULT_PLAN)
        plan["formal_baseline_policy"]["formal_baseline_count"] = 2
        from tempfile import TemporaryDirectory
        import json

        with TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "one current formal baseline"):
                experiment_module.validate(path)

    def test_closed_control_uses_formal_source_width(self):
        self.assertEqual(analysis_module.evaluation_half_width(0.0, 1.0), 0.5)
        self.assertEqual(analysis_module.evaluation_half_width(0.75, 1.0), 0.375)

    def test_comsol_sampler_includes_exact_port_edge(self):
        source = (PROJECT_ROOT / "tests" / "comsol" / "build_s1_joint_field_candidate.m").read_text(
            encoding="utf-8"
        )
        self.assertIn("portWidth/2", source)
        self.assertIn("if portWidth>0", source)
        self.assertIn("meshAutoLevel", source)
        self.assertIn("geom1_relvol_dom", source)
        self.assertIn("acceleratorHmax", source)
        self.assertIn("includeRfHardware", source)
        self.assertIn("downstreamBuffer", source)
        self.assertIn("outerVacuumMargin", source)
        runner = (PROJECT_ROOT / "tests" / "comsol" / "run_s1_joint_field_candidate.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("permissions.field_solve_allowed", runner)
        self.assertIn("blocked until the continuous RF shield radius is selected", runner)

    def test_continuous_rf_shield_parameter_sweep(self):
        shield = shield_module.validate()
        geometry = shield["candidate_geometry_mm"]
        self.assertEqual(geometry["inner_radius_ratio_to_rod_outer_extent_sweep"], [1.5, 2.0, 3.0])
        self.assertIsNone(geometry["selected_inner_radius_mm"])
        self.assertFalse(geometry["oa_accelerator_outer_size_dependency_allowed"])
        self.assertEqual(
            shield["two_dimensional_screen_evidence"]["retained_inner_radius_mm_for_3d"],
            [19.776, 26.368],
        )

    def test_continuous_rf_shield_harmonics_are_resolved(self):
        theta = np.linspace(0.0, 2.0 * np.pi, 72, endpoint=False)
        potential = 5.0 * np.cos(2.0 * theta) + 0.1 * np.cos(6.0 * theta)
        samples = pd.DataFrame({
            "shield_inner_radius_mm": np.full(theta.size, 19.776),
            "mesh_hmax_mm": np.full(theta.size, 0.2),
            "sample_radius_mm": np.full(theta.size, 2.0),
            "theta_rad": theta,
            "potential_V": potential,
            "Ex_V_per_m": np.zeros(theta.size),
            "Ey_V_per_m": np.zeros(theta.size),
        })
        row = shield_analysis_module.characterize(samples).iloc[0]
        self.assertAlmostEqual(row["order_2_amplitude_V"], 5.0)
        self.assertAlmostEqual(row["order_6_relative_to_order_2"], 0.02)
        self.assertLess(row["order_10_relative_to_order_2"], 1e-12)

    def test_width_above_reference_is_rejected(self):
        original = module.load

        def altered(path):
            value = original(path)
            if Path(path).name == "rf_to_oatof_s1_joint_field.json":
                value = deepcopy(value)
                value["port_sweep"]["full_width_y_mm"] = [1.25]
            return value

        with patch.object(module, "load", side_effect=altered):
            with self.assertRaisesRegex(ValueError, "exceeds"):
                module.validate()

    def test_premature_field_solve_permission_is_rejected(self):
        original = module.load

        def altered(path):
            value = original(path)
            if Path(path).name == "rf_to_oatof_s1_joint_field.json":
                value = deepcopy(value)
                value["permissions"]["field_solve_allowed"] = True
            return value

        with patch.object(module, "load", side_effect=altered):
            with self.assertRaisesRegex(ValueError, "permissions"):
                module.validate()


if __name__ == "__main__":
    unittest.main()
