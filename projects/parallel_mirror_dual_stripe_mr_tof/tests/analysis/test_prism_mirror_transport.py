from __future__ import annotations

import math
import unittest
from dataclasses import replace

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prism_analytic import (
    trace_triangular_hard_boundary_prism,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prism_mirror_transport import (
    PhaseState2D,
    TransportError,
    TransportNumerics,
    curved_strip_potential_region,
    plane_stop_target,
    polygon_potential_region,
    propagate_segmented_hamiltonian,
)


ZERO = lambda _z: 0.0
NUMERICS = TransportNumerics(
    relative_tolerance=1.0e-10,
    absolute_tolerance=1.0e-12,
    max_step_mm_per_sqrt_v=0.02,
    event_samples_per_step=8,
    root_time_tolerance_mm_per_sqrt_v=1.0e-12,
    boundary_root_tolerance_mm=1.0e-10,
    momentum_tolerance_sqrt_v=1.0e-10,
    normal_energy_tolerance_v=1.0e-12,
    maximum_steps=200_000,
)


class PrismMirrorTransportTests(unittest.TestCase):
    def test_unequal_polygon_edges_each_return_true_signed_distance(self) -> None:
        region = polygon_potential_region("triangle", ((0.0, 0.0), (4.0, 0.0), (0.0, 3.0)), 1.0)
        vertices = ((0.0, 0.0), (4.0, 0.0), (0.0, 3.0))
        for boundary, start, end in zip(region.boundaries, vertices, vertices[1:] + vertices[:1]):
            midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
            normal = boundary.inward_normal(*midpoint)
            interior_point = (midpoint[0] + 0.25 * normal[0], midpoint[1] + 0.25 * normal[1])
            self.assertAlmostEqual(boundary.level(*interior_point), 0.25, places=12)

    def test_integer_numerics_reject_bool_and_float(self) -> None:
        common = dict(
            initial_state=PhaseState2D(0.0, 0.0, 0.0, 0.0, 1.0),
            charge_sign=1,
            mirror_potential_v=ZERO,
            mirror_gradient_v_per_mm=ZERO,
            potential_regions=(),
            stop_targets=(),
            maximum_reduced_time_mm_per_sqrt_v=1.0,
        )
        for invalid in (True, 8.0):
            with self.subTest(invalid=invalid), self.assertRaises(TransportError):
                propagate_segmented_hamiltonian(
                    numerics=replace(NUMERICS, event_samples_per_step=invalid), **common,
                )

    def test_zero_bias_band_reduces_to_bare_harmonic_mirror(self) -> None:
        band = curved_strip_potential_region(
            "zero_band",
            (-5.0, 5.0),
            lambda _y: 0.4,
            lambda _y: 0.8,
            lambda _y: 0.0,
            lambda _y: 0.0,
            0.0,
        )
        common = dict(
            initial_state=PhaseState2D(0.0, 0.0, 0.0, 0.25, 2.0),
            charge_sign=1,
            mirror_potential_v=lambda z: z * z,
            mirror_gradient_v_per_mm=lambda z: 2.0 * z,
            stop_targets=(plane_stop_target("return", (0.0, 1.0), 0.0, direction=-1),),
            maximum_reduced_time_mm_per_sqrt_v=5.0,
            numerics=NUMERICS,
        )
        bare = propagate_segmented_hamiltonian(potential_regions=(), **common)
        with_band = propagate_segmented_hamiltonian(potential_regions=(band,), **common)
        self.assertEqual(bare.status, "stopped")
        self.assertEqual(with_band.status, "stopped")
        self.assertAlmostEqual(bare.final_state.reduced_time_mm_per_sqrt_v, math.pi, places=9)
        self.assertAlmostEqual(with_band.final_state.z_mm, bare.final_state.z_mm, places=10)
        self.assertAlmostEqual(with_band.final_state.u_z_sqrt_v, bare.final_state.u_z_sqrt_v, places=9)
        self.assertAlmostEqual(with_band.final_state.y_mm, bare.final_state.y_mm, places=9)
        self.assertLess(with_band.maximum_absolute_hamiltonian_residual_v, 2.0e-9)

    def test_triangle_zero_background_matches_existing_hard_boundary_primitive(self) -> None:
        triangle = ((0.0, -1.0), (2.0, 0.0), (0.0, 1.0))
        energy = 10.0
        bias = 2.0
        reference = trace_triangular_hard_boundary_prism(
            triangle, (-1.0, -0.4), (1.0, 0.0), energy, bias, charge_sign=1,
        )
        result = propagate_segmented_hamiltonian(
            PhaseState2D(0.0, -1.0, -0.4, math.sqrt(energy), 0.0),
            charge_sign=1,
            mirror_potential_v=ZERO,
            mirror_gradient_v_per_mm=ZERO,
            potential_regions=(polygon_potential_region("p1", triangle, bias),),
            stop_targets=(plane_stop_target("downstream", (1.0, 0.0), 3.0, direction=1),),
            maximum_reduced_time_mm_per_sqrt_v=3.0,
            numerics=NUMERICS,
        )
        interfaces = [event for event in result.events if event.kind == "interface"]
        self.assertEqual(reference.status, "transmitted")
        self.assertEqual(len(interfaces), 2)
        self.assertAlmostEqual(interfaces[0].state_before.y_mm, reference.entry_point_yz_mm[0], places=10)
        self.assertAlmostEqual(interfaces[0].state_before.z_mm, reference.entry_point_yz_mm[1], places=10)
        self.assertAlmostEqual(interfaces[1].state_before.y_mm, reference.exit_point_yz_mm[0], places=9)
        self.assertAlmostEqual(interfaces[1].state_before.z_mm, reference.exit_point_yz_mm[1], places=9)
        magnitude = math.hypot(result.final_state.u_y_sqrt_v, result.final_state.u_z_sqrt_v)
        self.assertAlmostEqual(result.final_state.u_y_sqrt_v / magnitude, reference.resulting_unit_direction_yz[0], places=9)
        self.assertAlmostEqual(result.final_state.u_z_sqrt_v / magnitude, reference.resulting_unit_direction_yz[1], places=9)

    def test_charge_bias_sign_symmetry_and_reverse_reciprocity(self) -> None:
        triangle = ((0.0, -1.0), (2.0, 0.0), (0.0, 1.0))

        def run(charge: int, bias: float):
            return propagate_segmented_hamiltonian(
                PhaseState2D(0.0, -1.0, -0.4, math.sqrt(10.0), 0.0),
                charge_sign=charge,
                mirror_potential_v=ZERO,
                mirror_gradient_v_per_mm=ZERO,
                potential_regions=(polygon_potential_region("prism", triangle, bias),),
                stop_targets=(plane_stop_target("out", (1.0, 0.0), 3.0, direction=1),),
                maximum_reduced_time_mm_per_sqrt_v=3.0,
                numerics=NUMERICS,
            )

        positive = run(1, 2.0)
        negative = run(-1, -2.0)
        self.assertAlmostEqual(positive.final_state.z_mm, negative.final_state.z_mm, places=10)
        self.assertAlmostEqual(positive.final_state.u_y_sqrt_v, negative.final_state.u_y_sqrt_v, places=10)
        self.assertAlmostEqual(positive.final_state.u_z_sqrt_v, negative.final_state.u_z_sqrt_v, places=10)

        reverse = propagate_segmented_hamiltonian(
            PhaseState2D(
                0.0,
                positive.final_state.y_mm,
                positive.final_state.z_mm,
                -positive.final_state.u_y_sqrt_v,
                -positive.final_state.u_z_sqrt_v,
            ),
            charge_sign=1,
            mirror_potential_v=ZERO,
            mirror_gradient_v_per_mm=ZERO,
            potential_regions=(polygon_potential_region("prism", triangle, 2.0),),
            stop_targets=(plane_stop_target("source", (1.0, 0.0), -1.0, direction=-1),),
            maximum_reduced_time_mm_per_sqrt_v=3.0,
            numerics=NUMERICS,
        )
        self.assertAlmostEqual(reverse.final_state.z_mm, -0.4, places=8)
        self.assertAlmostEqual(reverse.final_state.u_y_sqrt_v, -math.sqrt(10.0), places=8)
        self.assertAlmostEqual(reverse.final_state.u_z_sqrt_v, 0.0, places=8)

    def test_nonmonotonic_mirror_gradient_propagates_and_returns(self) -> None:
        potential = lambda z: 0.5 * z * z + 0.2 * (math.cos(3.0 * z) - 1.0)
        gradient = lambda z: z - 0.6 * math.sin(3.0 * z)
        result = propagate_segmented_hamiltonian(
            PhaseState2D(0.0, 0.0, 0.0, 0.1, 1.5),
            charge_sign=1,
            mirror_potential_v=potential,
            mirror_gradient_v_per_mm=gradient,
            potential_regions=(),
            stop_targets=(plane_stop_target("return", (0.0, 1.0), 0.0, direction=-1),),
            maximum_reduced_time_mm_per_sqrt_v=10.0,
            numerics=NUMERICS,
        )
        self.assertEqual(result.status, "stopped")
        self.assertLess(result.final_state.u_z_sqrt_v, 0.0)
        self.assertAlmostEqual(result.final_state.u_z_sqrt_v, -1.5, places=8)
        self.assertLess(result.maximum_absolute_hamiltonian_residual_v, 2.0e-9)

    def test_finite_curved_band_uses_curve_normals_and_preserves_energy(self) -> None:
        lower = lambda y: 1.0 + 0.1 * y * y
        upper = lambda y: 2.0 + 0.1 * y * y
        derivative = lambda y: 0.2 * y
        stripe = curved_strip_potential_region(
            "stripe", (-2.0, 2.0), lower, upper, derivative, derivative, 1.0,
        )
        result = propagate_segmented_hamiltonian(
            PhaseState2D(0.0, 0.0, 0.0, 0.2, 3.0),
            charge_sign=1,
            mirror_potential_v=ZERO,
            mirror_gradient_v_per_mm=ZERO,
            potential_regions=(stripe,),
            stop_targets=(plane_stop_target("after", (0.0, 1.0), 3.0, direction=1),),
            maximum_reduced_time_mm_per_sqrt_v=2.0,
            numerics=NUMERICS,
        )
        interfaces = [event for event in result.events if event.kind == "interface"]
        self.assertEqual([event.name for event in interfaces], ["stripe.lower", "stripe.upper"])
        for event in interfaces:
            self.assertTrue(event.transmitted)
            self.assertLess(abs(event.tangential_momentum_residual_sqrt_v), 2.0e-12)
            self.assertLess(abs(event.hamiltonian_residual_v), 2.0e-9)
        entry = interfaces[0].state_before
        exit_state = interfaces[1].state_before
        self.assertAlmostEqual(entry.z_mm, lower(entry.y_mm), places=9)
        self.assertAlmostEqual(exit_state.z_mm, upper(exit_state.y_mm), places=9)
        self.assertEqual(result.active_region_names, ())

    def test_selected_transmitted_region_entry_is_an_exact_terminal_event(self) -> None:
        stripe = curved_strip_potential_region(
            "stripe", (-2.0, 2.0), lambda _y: 1.0, lambda _y: 2.0,
            lambda _y: 0.0, lambda _y: 0.0, 0.5,
        )
        result = propagate_segmented_hamiltonian(
            PhaseState2D(0.0, 0.0, 0.0, 0.2, 3.0),
            charge_sign=1,
            mirror_potential_v=ZERO,
            mirror_gradient_v_per_mm=ZERO,
            potential_regions=(stripe,),
            stop_targets=(),
            maximum_reduced_time_mm_per_sqrt_v=2.0,
            numerics=NUMERICS,
            stop_on_transmitted_entry_region_names=("stripe",),
        )
        self.assertEqual(result.status, "stopped_on_transmitted_entry")
        self.assertEqual(len(result.events), 1)
        entry = result.events[0]
        self.assertEqual(entry.kind, "interface")
        self.assertTrue(entry.entering)
        self.assertTrue(entry.transmitted)
        self.assertAlmostEqual(entry.state_before.z_mm, 1.0, places=10)
        self.assertEqual(result.final_state, entry.state_after)
        self.assertEqual(result.active_region_names, ("stripe",))

        with self.assertRaises(TransportError):
            propagate_segmented_hamiltonian(
                PhaseState2D(0.0, 0.0, 0.0, 0.2, 3.0),
                charge_sign=1,
                mirror_potential_v=ZERO,
                mirror_gradient_v_per_mm=ZERO,
                potential_regions=(stripe,),
                stop_targets=(),
                maximum_reduced_time_mm_per_sqrt_v=2.0,
                numerics=NUMERICS,
                stop_on_transmitted_entry_region_names=("missing",),
            )

    def test_forbidden_entry_reflects_without_changing_region_membership(self) -> None:
        region = curved_strip_potential_region(
            "barrier", (-1.0, 1.0), lambda _y: 1.0, lambda _y: 2.0,
            lambda _y: 0.0, lambda _y: 0.0, 2.0,
        )
        result = propagate_segmented_hamiltonian(
            PhaseState2D(0.0, 0.0, 0.0, 0.0, 1.0),
            charge_sign=1,
            mirror_potential_v=ZERO,
            mirror_gradient_v_per_mm=ZERO,
            potential_regions=(region,),
            stop_targets=(plane_stop_target("back", (0.0, 1.0), -0.5, direction=-1),),
            maximum_reduced_time_mm_per_sqrt_v=3.0,
            numerics=NUMERICS,
        )
        interface = result.events[0]
        self.assertFalse(interface.transmitted)
        self.assertEqual(interface.attempted_potential_change_v, 2.0)
        self.assertEqual(interface.applied_potential_change_v, 0.0)
        self.assertEqual(result.active_region_names, ())
        self.assertAlmostEqual(result.final_state.u_z_sqrt_v, -1.0, places=10)

    def test_consumed_boundary_can_be_crossed_again_inside_first_sample_interval(self) -> None:
        region = polygon_potential_region(
            "field_band", ((-1.0, 0.0), (1.0, 0.0), (1.0, 1.0), (-1.0, 1.0)), 0.0,
        )
        coarse = replace(NUMERICS, max_step_mm_per_sqrt_v=1.0, event_samples_per_step=2)
        result = propagate_segmented_hamiltonian(
            # z(t) = -(t-0.3)(t-0.7): entry is visible at the base
            # step's t=0.5 sample, while the return occurs before the first
            # sample of the restarted, boundary-owned segment.
            PhaseState2D(0.0, 0.0, -0.21, 0.0, 1.0),
            charge_sign=1,
            mirror_potential_v=lambda z: 4.0 * z,
            mirror_gradient_v_per_mm=lambda _z: 4.0,
            potential_regions=(region,),
            stop_targets=(plane_stop_target("returned", (0.0, 1.0), -0.22, direction=-1),),
            maximum_reduced_time_mm_per_sqrt_v=1.3,
            numerics=coarse,
        )
        interfaces = [event for event in result.events if event.kind == "interface"]
        self.assertEqual([event.name for event in interfaces], ["field_band.edge_0", "field_band.edge_0"])
        self.assertEqual([event.entering for event in interfaces], [True, False])
        self.assertLess(result.maximum_absolute_hamiltonian_residual_v, 2.0e-9)


if __name__ == "__main__":
    unittest.main()
