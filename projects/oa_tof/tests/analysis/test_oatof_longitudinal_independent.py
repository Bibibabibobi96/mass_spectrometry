from __future__ import annotations

import math
import random
import sys
import unittest
from pathlib import Path

import numpy as np
from scipy.integrate import quad
from scipy.optimize import brentq


PROJECT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_DIR / "analysis"))

from accelerator_time_focus import (
    accelerator_state,
    normalized_time_to_plane_mm_sqrt_v,
)
from oatof_oaaccelerator_coupling import solve_coupled_reflectron_fields
from reflectron_dual_stage_solver import (
    normalized_flight_time_mm_sqrt_v,
    solve_reflectron_fields,
)


def _accelerator_time_by_quadrature(
    energy_v: float,
    intermediate_v: float,
    field1_v_per_mm: float,
    field2_v_per_mm: float,
    drift_mm: float,
) -> float:
    remaining_v = energy_v - intermediate_v
    region1, _ = quad(
        lambda distance: 1.0 / math.sqrt(field1_v_per_mm * distance),
        0.0,
        remaining_v / field1_v_per_mm,
        epsabs=1.0e-12,
        epsrel=1.0e-12,
    )
    region2, _ = quad(
        lambda distance: 1.0
        / math.sqrt(remaining_v + field2_v_per_mm * distance),
        0.0,
        intermediate_v / field2_v_per_mm,
        epsabs=1.0e-12,
        epsrel=1.0e-12,
    )
    return region1 + region2 + drift_mm / math.sqrt(energy_v)


def _reflectron_time_by_quadrature(
    energy_v: float,
    field_free_length_mm: float,
    stage1_drop_v: float,
    stage1_field_v_per_mm: float,
    stage2_field_v_per_mm: float,
) -> float:
    stage1, _ = quad(
        lambda distance: 1.0
        / math.sqrt(energy_v - stage1_field_v_per_mm * distance),
        0.0,
        stage1_drop_v / stage1_field_v_per_mm,
        epsabs=1.0e-12,
        epsrel=1.0e-12,
    )
    remaining_v = energy_v - stage1_drop_v
    stage2, _ = quad(
        lambda distance: 1.0
        / math.sqrt(remaining_v - stage2_field_v_per_mm * distance),
        0.0,
        remaining_v / stage2_field_v_per_mm,
        epsabs=1.0e-12,
        epsrel=1.0e-12,
    )
    return field_free_length_mm / math.sqrt(energy_v) + 2.0 * (stage1 + stage2)


def _independent_coupled_residual(
    stage1_drop_v: float,
    nominal_energy_v: float,
    stage1_length_mm: float,
    field_free_length_mm: float,
    accelerator_first: float,
    accelerator_second: float,
) -> tuple[float, float]:
    remaining_v = nominal_energy_v - stage1_drop_v
    field1 = stage1_drop_v / stage1_length_mm
    inverse_field2 = math.sqrt(remaining_v) / 2.0 * (
        field_free_length_mm / (2.0 * nominal_energy_v**1.5)
        - accelerator_first
        - 2.0
        / field1
        * (
            1.0 / math.sqrt(nominal_energy_v)
            - 1.0 / math.sqrt(remaining_v)
        )
    )
    if inverse_field2 <= 0.0:
        return math.nan, math.nan
    residual = (
        accelerator_second
        + 3.0 * field_free_length_mm / (4.0 * nominal_energy_v**2.5)
        + 1.0
        / field1
        * (
            -1.0 / nominal_energy_v**1.5
            + 1.0 / remaining_v**1.5
        )
        - inverse_field2 / remaining_v**1.5
    )
    return residual, 1.0 / inverse_field2


class IndependentLongitudinalTheoryTest(unittest.TestCase):
    def test_accelerator_time_matches_direct_potential_integral(self) -> None:
        generator = random.Random(20260720)
        for _ in range(30):
            intermediate = generator.uniform(300.0, 3000.0)
            repeller = intermediate + generator.uniform(50.0, 1000.0)
            gap1 = generator.uniform(1.0, 40.0)
            gap2 = generator.uniform(2.0, 200.0)
            release = generator.uniform(0.1, 0.9) * gap1
            state = accelerator_state(
                repeller,
                intermediate,
                gap1,
                gap2,
                release_position_mm=release,
                require_downstream_focus=False,
            )
            energy = state.nominal_energy_per_charge_v
            drift = max(0.0, state.first_order_focus_drift_mm)
            analytic = normalized_time_to_plane_mm_sqrt_v(
                energy,
                state.intermediate_relative_v,
                state.field1_v_per_mm,
                state.field2_v_per_mm,
                drift,
            )
            integrated = _accelerator_time_by_quadrature(
                energy,
                state.intermediate_relative_v,
                state.field1_v_per_mm,
                state.field2_v_per_mm,
                drift,
            )
            self.assertAlmostEqual(analytic, integrated, delta=2.0e-10)

    def test_reflectron_time_matches_direct_potential_integral(self) -> None:
        generator = random.Random(19730101)
        for _ in range(30):
            energy = generator.uniform(500.0, 6000.0)
            field_free = generator.uniform(400.0, 3000.0)
            stage1_length = generator.uniform(10.0, 0.2 * field_free)
            solution = solve_reflectron_fields(
                energy,
                stage1_length,
                total_field_free_length_mm=field_free,
            )
            analytic = normalized_flight_time_mm_sqrt_v(
                energy,
                field_free,
                solution.stage1_voltage_drop_v,
                solution.stage1_field_v_per_mm,
                solution.stage2_field_v_per_mm,
            )
            integrated = _reflectron_time_by_quadrature(
                energy,
                field_free,
                solution.stage1_voltage_drop_v,
                solution.stage1_field_v_per_mm,
                solution.stage2_field_v_per_mm,
            )
            self.assertAlmostEqual(analytic, integrated, delta=2.0e-9)

    def test_coupled_root_matches_independent_scipy_solver(self) -> None:
        accelerator = accelerator_state(2240.0, 1760.0, 3.0, 16.8)
        solution = solve_coupled_reflectron_fields(
            accelerator,
            120.0,
            600.0,
            600.0,
            energy_min_v=1920.0,
            energy_max_v=2080.0,
            stage2_margin_fraction=1.0,
        )
        w0 = accelerator.nominal_energy_per_charge_v
        remaining = w0 - accelerator.intermediate_relative_v
        drift = accelerator.first_order_focus_drift_mm
        accelerator_first = (
            1.0 / (accelerator.field1_v_per_mm * math.sqrt(remaining))
            + 1.0
            / accelerator.field2_v_per_mm
            * (1.0 / math.sqrt(w0) - 1.0 / math.sqrt(remaining))
            - drift / (2.0 * w0**1.5)
        )
        accelerator_second = (
            -1.0 / (2.0 * accelerator.field1_v_per_mm * remaining**1.5)
            + 1.0
            / accelerator.field2_v_per_mm
            * (-1.0 / (2.0 * w0**1.5) + 1.0 / (2.0 * remaining**1.5))
            + 3.0 * drift / (4.0 * w0**2.5)
        )

        grid = np.linspace(1.0, 1919.999, 20000)
        finite_points: list[tuple[float, float]] = []
        for stage1_drop in grid:
            residual, _ = _independent_coupled_residual(
                stage1_drop,
                w0,
                120.0,
                1200.0,
                accelerator_first,
                accelerator_second,
            )
            if math.isfinite(residual):
                finite_points.append((stage1_drop, residual))
        brackets = [
            (left[0], right[0])
            for left, right in zip(finite_points, finite_points[1:], strict=False)
            if left[1] * right[1] < 0.0
        ]
        self.assertTrue(brackets)
        root = brentq(
            lambda value: _independent_coupled_residual(
                value,
                w0,
                120.0,
                1200.0,
                accelerator_first,
                accelerator_second,
            )[0],
            *min(brackets, key=lambda pair: abs(sum(pair) / 2.0 - 1600.0)),
            xtol=1.0e-12,
            rtol=1.0e-14,
        )
        _, field2 = _independent_coupled_residual(
            root,
            w0,
            120.0,
            1200.0,
            accelerator_first,
            accelerator_second,
        )
        self.assertAlmostEqual(root, solution.stage1_voltage_drop_v, places=8)
        self.assertAlmostEqual(field2, solution.stage2_field_v_per_mm, places=10)

    def test_coupled_solution_obeys_length_and_voltage_scaling(self) -> None:
        reference_accelerator = accelerator_state(2240.0, 1760.0, 3.0, 16.8)
        reference = solve_coupled_reflectron_fields(
            reference_accelerator,
            120.0,
            600.0,
            600.0,
            energy_min_v=1920.0,
            energy_max_v=2080.0,
            stage2_margin_fraction=1.0,
        )
        for length_scale, voltage_scale in ((0.5, 1.0), (2.0, 1.0), (1.0, 0.5), (1.0, 2.0)):
            accelerator = accelerator_state(
                2240.0 * voltage_scale,
                1760.0 * voltage_scale,
                3.0 * length_scale,
                16.8 * length_scale,
            )
            scaled = solve_coupled_reflectron_fields(
                accelerator,
                120.0 * length_scale,
                600.0 * length_scale,
                600.0 * length_scale,
                energy_min_v=1920.0 * voltage_scale,
                energy_max_v=2080.0 * voltage_scale,
                stage2_margin_fraction=1.0,
            )
            self.assertAlmostEqual(
                scaled.stage1_voltage_drop_v,
                reference.stage1_voltage_drop_v * voltage_scale,
                places=7,
            )
            self.assertAlmostEqual(
                scaled.stage2_field_v_per_mm,
                reference.stage2_field_v_per_mm * voltage_scale / length_scale,
                places=9,
            )
            self.assertAlmostEqual(
                scaled.required_stage2_depth_mm,
                reference.required_stage2_depth_mm * length_scale,
                places=7,
            )


if __name__ == "__main__":
    unittest.main()
