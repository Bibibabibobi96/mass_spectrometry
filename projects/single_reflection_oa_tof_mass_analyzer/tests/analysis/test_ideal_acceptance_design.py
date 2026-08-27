"""Focused regressions for finite-source moments and exact event envelopes."""

from dataclasses import replace
import json
import unittest

import numpy as np

from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_acceptance_design import (
    DesignDomainError, finite_source_envelope, prepare_source_quadrature,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison import (
    IdealWorkingPoint, NumericalSourceSpec,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    InnerSolution, OuterGeometry, ReflectronGeometry, derive_three_zone_state,
)


class IdealAcceptanceDesignTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = NumericalSourceSpec(100., 1.498375640839315, -2.9323518410018137, 228.80604377795845)
        outer = OuterGeometry(3.25, 17., .3, 250., 2000.)
        mirror = ReflectronGeometry(120., 96.1563, 600., 600.)
        inner = InnerSolution(1701.7426470174573, 9.880402594970798, -1.0391326394747527)
        affine = self.spec.affine()
        self.point = IdealWorkingPoint(affine, derive_three_zone_state(affine, outer, inner.eta),
                                      mirror, inner, 42.742615461548496, None)
        self.quadrature = prepare_source_quadrature(self.spec, full_width_mm=2.8,
            residual_sigma_m_per_s=10., position_order=12, residual_order=8)

    def test_quadrature_normalization_and_known_source_moments(self) -> None:
        q = self.quadrature
        self.assertAlmostEqual(float(q.weights.sum()), 1., places=14)
        self.assertAlmostEqual(float(q.weights @ q.position_offset_mm), 0., places=14)
        self.assertAlmostEqual(float(q.weights @ q.position_offset_mm**2), 2.8**2/12, places=14)
        self.assertAlmostEqual(float(q.weights @ q.residual_m_per_s**2), 100., places=11)

    def test_finite_envelope_matches_dense_energy_extrema(self) -> None:
        result = finite_source_envelope(self.spec, self.point, 2.8, 60.)
        y = np.linspace(-1.4, 1.4, 1001)[:, None]
        residual = np.linspace(-60., 60., 201)[None, :]
        velocity = self.spec.center_velocity_m_per_s+self.spec.velocity_slope_m_per_s_per_mm*y+residual
        chi = velocity*self.spec.affine().time_scale_s_per_mm_sqrt_v*1e3
        state = self.point.state
        energy = state.repeller_v-state.field1_v_per_mm*(self.spec.center_x_mm+y)+chi**2
        self.assertAlmostEqual(result["energy_min_v"], float(energy.min()), places=10)
        self.assertAlmostEqual(result["energy_max_v"], float(energy.max()), places=10)
        self.assertGreater(result["minimum_repeller_turn_mm"], 0.)
        json.dumps(result, allow_nan=False)

    def test_geometry_and_backward_collision_are_explicit(self) -> None:
        with self.assertRaisesRegex(DesignDomainError, "first acceleration"):
            finite_source_envelope(self.spec, self.point, 3., 60.)
        with self.assertRaisesRegex(DesignDomainError, "repeller"):
            finite_source_envelope(self.spec, self.point, 2.8, 100000.)

    def test_invalid_envelope_and_mismatched_source_rejected(self) -> None:
        for width, residual in ((0., 60.), (2.8, -1.), (float("nan"), 60.)):
            with self.assertRaises(ValueError):
                finite_source_envelope(self.spec, self.point, width, residual)
        with self.assertRaisesRegex(ValueError, "must match"):
            finite_source_envelope(replace(self.spec, center_x_mm=1.6), self.point, 2.8, 60.)

    def test_quadrature_validation_and_zero_residual(self) -> None:
        for order in (1, True, 2.5):
            with self.assertRaises(ValueError):
                prepare_source_quadrature(self.spec, full_width_mm=1.,
                    residual_sigma_m_per_s=0., position_order=order, residual_order=4)
        q = prepare_source_quadrature(self.spec, full_width_mm=1.,
            residual_sigma_m_per_s=0., position_order=4, residual_order=4)
        self.assertTrue(np.all(q.residual_m_per_s == 0.))


if __name__ == "__main__":
    unittest.main()
