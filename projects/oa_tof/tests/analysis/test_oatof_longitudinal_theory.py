from __future__ import annotations

import json
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
from projects.oa_tof.analysis.accelerator_time_focus import accelerator_state
from projects.oa_tof.analysis.oatof_oaaccelerator_coupling import (
    coupled_normalized_flight_time_mm_sqrt_v,
    derive as derive_coupled,
    source_position_samples,
)
from projects.oa_tof.analysis.reflectron_dual_stage_solver import (
    normalized_derivatives,
    normalized_flight_time_mm_sqrt_v,
    solve_reflectron_fields,
)


def _five_point_first(function, x: float, h: float) -> float:
    return (
        function(x - 2.0 * h)
        - 8.0 * function(x - h)
        + 8.0 * function(x + h)
        - function(x + 2.0 * h)
    ) / (12.0 * h)


def _five_point_second(function, x: float, h: float) -> float:
    return (
        -function(x + 2.0 * h)
        + 16.0 * function(x + h)
        - 30.0 * function(x)
        + 16.0 * function(x - h)
        - function(x - 2.0 * h)
    ) / (12.0 * h * h)


class OatofLongitudinalTheoryTest(unittest.TestCase):
    def test_theory_markdown_uses_github_safe_math_fences(self) -> None:
        theory_dir = PROJECT_DIR / "docs" / "theory"
        for name in (
            "oaaccelerator_time_focus.md",
            "dual_stage_reflectron.md",
            "oatof_oaaccelerator_coupling.md",
        ):
            lines = (theory_dir / name).read_text(encoding="utf-8").splitlines()
            self.assertNotIn("```math", lines, msg=f"{name} uses a legacy math fence")
            delimiter_count = lines.count("$$")
            self.assertGreater(delimiter_count, 0)
            self.assertEqual(
                delimiter_count % 2,
                0,
                msg=f"{name} has unpaired display-math delimiters",
            )
            self.assertFalse(
                any("$$" in line and line != "$$" for line in lines),
                msg=f"{name} has a display-math delimiter with inline content",
            )

    def test_current_baseline_reproduces_uncoupled_reflectron(self) -> None:
        solution = solve_reflectron_fields(
            2000.0,
            120.0,
            upstream_from_accelerator_focus_mm=600.0,
            downstream_to_detector_mm=600.0,
        )
        self.assertAlmostEqual(solution.stage1_voltage_drop_v, 1600.0)
        self.assertAlmostEqual(solution.stage1_field_v_per_mm, 1600.0 / 120.0)
        self.assertAlmostEqual(solution.stage2_field_v_per_mm, 9.213106741667369)
        self.assertAlmostEqual(
            2.0 * solution.nominal_stage2_penetration_mm, 86.83281572999746
        )

    def test_reflectron_derivatives_match_independent_finite_difference(self) -> None:
        solution = solve_reflectron_fields(
            2000.0,
            120.0,
            total_field_free_length_mm=1200.0,
        )
        function = lambda energy: normalized_flight_time_mm_sqrt_v(
            energy,
            solution.total_field_free_length_mm,
            solution.stage1_voltage_drop_v,
            solution.stage1_field_v_per_mm,
            solution.stage2_field_v_per_mm,
        )
        analytic_first, analytic_second = normalized_derivatives(
            2000.0,
            solution.total_field_free_length_mm,
            solution.stage1_voltage_drop_v,
            solution.stage1_field_v_per_mm,
            solution.stage2_field_v_per_mm,
        )
        h = 0.2
        self.assertAlmostEqual(
            analytic_first, _five_point_first(function, 2000.0, h), places=11
        )
        self.assertAlmostEqual(
            analytic_second, _five_point_second(function, 2000.0, h), places=10
        )

    def test_coupled_candidate_is_diagnostic_and_not_baseline_equivalent(self) -> None:
        path = (
            PROJECT_DIR
            / "config"
            / "candidates"
            / "oatof_longitudinal_coupled_reference.json"
        )
        contract = json.loads(path.read_text(encoding="utf-8"))
        result, rows = derive_coupled(contract)
        coupled = result["coupled_reflectron"]
        self.assertAlmostEqual(coupled["stage1_voltage_drop_v"], 1628.8000630464526)
        self.assertNotAlmostEqual(coupled["stage1_voltage_drop_v"], 1600.0)
        self.assertLess(abs(coupled["total_first_derivative_residual"]), 1.0e-15)
        self.assertLess(abs(coupled["total_second_derivative_residual"]), 1.0e-15)
        self.assertFalse(coupled["stage2_depth_pass"])
        self.assertFalse(result["formal_FWHM_eligible"])
        self.assertEqual(len(rows), 101)
        self.assertIsInstance(rows[0]["sample_index"], int)

    def test_coupled_time_retains_accelerator_time(self) -> None:
        accelerator = accelerator_state(2240.0, 1760.0, 3.0, 16.8)
        contract = json.loads(
            (
                PROJECT_DIR
                / "config"
                / "candidates"
                / "oatof_longitudinal_coupled_reference.json"
            ).read_text(encoding="utf-8")
        )
        result, _ = derive_coupled(contract)
        solution = result["coupled_reflectron"]
        reflectron_only = normalized_flight_time_mm_sqrt_v(
            2000.0,
            1200.0,
            solution["stage1_voltage_drop_v"],
            solution["stage1_field_v_per_mm"],
            solution["stage2_field_v_per_mm"],
        )
        total = coupled_normalized_flight_time_mm_sqrt_v(
            2000.0,
            accelerator,
            600.0,
            600.0,
            solution["stage1_voltage_drop_v"],
            solution["stage1_field_v_per_mm"],
            solution["stage2_field_v_per_mm"],
        )
        self.assertGreater(total, reflectron_only)

    def test_sample_count_rejects_fractional_value(self) -> None:
        accelerator = accelerator_state(2240.0, 1760.0, 3.0, 16.8)
        contract = json.loads(
            (
                PROJECT_DIR
                / "config"
                / "candidates"
                / "oatof_longitudinal_coupled_reference.json"
            ).read_text(encoding="utf-8")
        )
        result, _ = derive_coupled(contract)
        coupled_dict = result["coupled_reflectron"]
        from projects.oa_tof.analysis.oatof_oaaccelerator_coupling import CoupledReflectronSolution

        coupled = CoupledReflectronSolution(
            **{
                key: value
                for key, value in coupled_dict.items()
                if key in CoupledReflectronSolution.__dataclass_fields__
            }
        )
        with self.assertRaisesRegex(ValueError, "integer"):
            source_position_samples(accelerator, coupled, 524.0, 1.0, 10.5)


if __name__ == "__main__":
    unittest.main()
