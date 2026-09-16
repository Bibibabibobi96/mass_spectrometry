from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import MirrorL0Design
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prism_mirror_transport import (
    PhaseState2D,
    TransportEvent,
    TransportError,
    TransportNumerics,
    TransportResult,
    plane_stop_target,
    polygon_potential_region,
    propagate_segmented_hamiltonian,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    load_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_segmented_transport import (
    build_two_prism_segmented_potential_regions,
    evaluate_two_prism_segmented_voltage_pair,
    predict_p2_ideal_bias_for_reference_tangent_ratio,
    validate_two_prism_voltage_polarity_domain,
    _propagate_to_first_complete_positive_stripe_pass,
    _propagate_to_first_positive_mirror_turn,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prism_analytic import (
    hard_boundary_bias_v,
    trace_triangular_hard_boundary_prism,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_handoff import (
    ProjectPhaseSpaceState,
)


PROJECT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT / "config" / "simion_candidate_two_zone.json"
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
    maximum_steps=20_000,
)


class PrismVoltagePolarityContractTests(unittest.TestCase):
    def test_positive_ion_requires_positive_p1_and_negative_p2(self) -> None:
        receipt = validate_two_prism_voltage_polarity_domain(
            load_contract(CONTRACT),
            charge_state=1,
            p1_bounds_v=(100.0, 300.0),
            p2_bounds_v=(-300.0, -100.0),
        )
        self.assertEqual(receipt["p1_required_sign"], 1)
        self.assertEqual(receipt["p2_required_sign"], -1)

    def test_positive_p2_domain_fails_closed(self) -> None:
        with self.assertRaisesRegex(CandidateContractError, "P2.*strictly negative"):
            validate_two_prism_voltage_polarity_domain(
                load_contract(CONTRACT),
                charge_state=1,
                p1_bounds_v=(100.0, 300.0),
                p2_bounds_v=(100.0, 300.0),
            )

    def test_negative_ion_reverses_both_signs(self) -> None:
        receipt = validate_two_prism_voltage_polarity_domain(
            load_contract(CONTRACT),
            charge_state=-1,
            p1_bounds_v=(-300.0, -100.0),
            p2_bounds_v=(100.0, 300.0),
        )
        self.assertEqual(receipt["p1_required_sign"], -1)
        self.assertEqual(receipt["p2_required_sign"], 1)


def build(contract=None):
    return build_two_prism_segmented_potential_regions(
        load_contract(CONTRACT) if contract is None else contract,
        prism_bias_v_by_electrode_id={16: 101.0, 17: -102.0},
        stripe_bias_v_by_set_name={"set_1": 11.0, "set_2": -12.0},
    )


def transport_event(
    name: str,
    before: PhaseState2D,
    after: PhaseState2D,
    *,
    region: str | None,
    entering: bool | None,
    transmitted: bool | None,
) -> TransportEvent:
    return TransportEvent(
        "stop" if region is None else "interface",
        name,
        before,
        after,
        region,
        entering,
        transmitted,
        0.0,
        0.0,
        0.0,
        0.0,
    )


def transport_result(
    initial: PhaseState2D,
    final: PhaseState2D,
    events: list[TransportEvent],
    *,
    status: str = "stopped",
) -> TransportResult:
    return TransportResult(
        status, initial, final, (), tuple(events), 4005.0, 4005.0, 0.0, 0.0,
    )


def staged_results() -> tuple[TransportResult, TransportResult, TransportResult, TransportResult]:
    source = PhaseState2D(0.0, -55.328, 0.0, 1.0, -20.0)
    p1_entry = PhaseState2D(1.0, -55.0, -40.0, 1.0, -19.0)
    p1_exit = PhaseState2D(2.0, -54.0, -90.0, 1.0, -18.0)
    stage_a_final = PhaseState2D(3.0, -53.0, -101.0, 1.0, -17.0)
    stage_a = transport_result(source, stage_a_final, [
        transport_event(
            "prism_16.edge_0", p1_entry, p1_entry,
            region="prism_16", entering=True, transmitted=True,
        ),
        transport_event(
            "prism_16.edge_1", p1_exit, p1_exit,
            region="prism_16", entering=False, transmitted=True,
        ),
        transport_event(
            "p1_post_prism_interface", stage_a_final, stage_a_final,
            region=None, entering=None, transmitted=None,
        ),
    ])
    p2_entry = PhaseState2D(5.0, -20.0, -20.0, 1.1, 16.0)
    p2_exit = PhaseState2D(6.0, -18.0, 20.0, 1.1, 15.0)
    stage_b_final = PhaseState2D(7.0, -8.0, 33.0, 1.2, 14.0)
    stage_b = transport_result(stage_a_final, stage_b_final, [
        transport_event(
            "prism_17.edge_0", p2_entry, p2_entry,
            region="prism_17", entering=True, transmitted=True,
        ),
        transport_event(
            "prism_17.edge_1", p2_exit, p2_exit,
            region="prism_17", entering=False, transmitted=True,
        ),
        transport_event(
            "p2_low_field_reference", stage_b_final, stage_b_final,
            region=None, entering=None, transmitted=None,
        ),
    ])
    turn = PhaseState2D(12.0, 0.25, 280.0, 1.2, 0.0)
    stage_c = transport_result(stage_b_final, turn, [
        transport_event(
            "first_post_P2_positive_mirror_turn", turn, turn,
            region=None, entering=None, transmitted=None,
        ),
    ], status="stopped_at_positive_mirror_turn")
    stripe_entry_before = PhaseState2D(13.0, 1.0, 60.0, 1.2, -14.0)
    stripe_entry_after = PhaseState2D(13.0, 1.0, 60.0, 1.25, -13.9)
    stripe_exit_before = PhaseState2D(14.0, 2.0, 45.0, 1.25, -13.9)
    stripe_exit_after = PhaseState2D(14.0, 2.0, 45.0, 1.2, -14.0)
    stage_d = transport_result(turn, stripe_exit_after, [
        transport_event(
            "stripe_11_set_1.lower", stripe_entry_before, stripe_entry_after,
            region="stripe_11_set_1", entering=True, transmitted=True,
        ),
        transport_event(
            "stripe_11_set_1.upper", stripe_exit_before, stripe_exit_after,
            region="stripe_11_set_1", entering=False, transmitted=True,
        ),
        transport_event(
            "first_post_turn_positive_stripe_pass_complete", stripe_exit_after, stripe_exit_after,
            region=None, entering=None, transmitted=None,
        ),
    ], status="stopped_after_first_positive_stripe_pass")
    return stage_a, stage_b, stage_c, stage_d


class TwoPrismSegmentedTransportTests(unittest.TestCase):
    def test_p2_ideal_prediction_uses_actual_face_order_and_pre_entry_state(self) -> None:
        energy = 4000.0
        triangle = [(0.0, 0.0), (-1.0, 0.0), (0.0, 1.0)]
        incidence = math.radians(49.0)
        incident = (math.sin(incidence), math.cos(incidence))
        entry = (-0.2, 0.0)
        origin = tuple(value - direction for value, direction in zip(entry, incident))
        bias = hard_boundary_bias_v(energy, 4.0, 1.8)
        trace = trace_triangular_hard_boundary_prism(
            triangle, origin, incident, energy, bias, charge_sign=1,
        )
        root_energy = math.sqrt(energy)
        inside_root_energy = math.sqrt(trace.inside_kinetic_energy_per_charge_v)
        entry_before = PhaseState2D(
            1.0, *trace.entry_point_yz_mm,
            root_energy * incident[0], root_energy * incident[1],
        )
        entry_after = PhaseState2D(
            1.0, *trace.entry_point_yz_mm,
            inside_root_energy * trace.inside_unit_direction_yz[0],
            inside_root_energy * trace.inside_unit_direction_yz[1],
        )
        exit_before = PhaseState2D(
            2.0, *trace.exit_point_yz_mm,
            inside_root_energy * trace.inside_unit_direction_yz[0],
            inside_root_energy * trace.inside_unit_direction_yz[1],
        )
        exit_after = PhaseState2D(
            2.0, *trace.exit_point_yz_mm,
            root_energy * trace.resulting_unit_direction_yz[0],
            root_energy * trace.resulting_unit_direction_yz[1],
        )
        entry_event = TransportEvent(
            "interface", "prism_17.edge_0", entry_before, entry_after,
            "prism_17", True, True, bias, bias, 0.0, 0.0,
        )
        exit_event = TransportEvent(
            "interface", "prism_17.edge_2", exit_before, exit_after,
            "prism_17", False, True, -bias, -bias, 0.0, 0.0,
        )
        stop_event = TransportEvent(
            "stop", "p2_low_field_reference", exit_after, exit_after,
            None, None, None, 0.0, 0.0, 0.0, 0.0,
        )
        stage = TransportResult(
            "stopped", entry_before, exit_after,
            (), (entry_event, exit_event, stop_event),
            energy, energy, 0.0, 0.0,
        )
        diagnostic = SimpleNamespace(
            stage_b_p1_exit_to_p2_low_field_reference=stage,
        )
        resolved = {"prism_electrodes": [{
            "id": 17,
            "parts": [
                {"polygon_yz_mm": triangle},
                {"polygon_yz_mm": triangle},
            ],
        }]}
        mirror = MirrorL0Design(
            transverse_half_gap_mm=15.0,
            transition_z_mm=(0.0, 1.0, 2.0, 3.0, 4.0),
            electrode_voltages_v=(0.0, 0.0, 0.0, 0.0, 0.0),
            terminal_electrode_plane_z_mm=5.0,
            terminal_electrode_voltage_v=0.0,
        )
        with patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "two_prism_segmented_transport.resolve_geometry",
            return_value=resolved,
        ), patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "two_prism_segmented_transport.axial_potential_v",
            return_value=0.0,
        ):
            prediction = predict_p2_ideal_bias_for_reference_tangent_ratio(
                {"prism_transport": {"second_prism": {"electrode_id": 17}}},
                diagnostic,
                mirror_design=mirror,
                charge_state=1,
                target_reference_tangent_ratio=(
                    trace.resulting_unit_direction_yz[0]
                    / trace.resulting_unit_direction_yz[1]
                ),
            )
        self.assertAlmostEqual(prediction.predicted_prism_bias_v, bias, places=10)
        self.assertEqual((prediction.entry_edge_index, prediction.exit_edge_index), (0, 2))

    def evaluate(self, stage_a=None, stage_b=None, stage_c=None, stage_d=None, *, source=None, stage_b_end=200.0):
        contract = load_contract(CONTRACT)
        first, second, third, fourth = staged_results()
        mirror = MirrorL0Design(
            transverse_half_gap_mm=15.0,
            transition_z_mm=(0.0, 100.0, 130.0, 160.0, 190.0),
            electrode_voltages_v=(0.0, 1000.0, 2000.0, 3000.0, 5000.0),
            terminal_electrode_plane_z_mm=230.0,
            terminal_electrode_voltage_v=5000.0,
        )
        selected_source = source or ProjectPhaseSpaceState(
            (0.0, -55.328, 0.0), (0.0, 0.01, -0.2),
        )
        with patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "two_prism_segmented_transport.propagate_segmented_hamiltonian",
            side_effect=(stage_a or first, stage_b or second),
        ) as propagate, patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "two_prism_segmented_transport._propagate_to_first_positive_mirror_turn",
            return_value=stage_c or third,
        ), patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "two_prism_segmented_transport._propagate_to_first_complete_positive_stripe_pass",
            return_value=stage_d or fourth,
        ):
            result = evaluate_two_prism_segmented_voltage_pair(
                contract,
                source=selected_source,
                particle_mass_th=100.0,
                charge_state=1,
                mirror_design=mirror,
                selected_axial_energy_per_charge_v=4000.0,
                target_slow_kinetic_energy_per_charge_v=5.0,
                target_p2_reference_tangent_ratio=1.2 / 14.0,
                prism_bias_v_by_electrode_id={16: 100.0, 17: -100.0},
                stripe_bias_v_by_set_name={"set_1": -25.0, "set_2": 50.0},
                numerics=NUMERICS,
                stage_a_maximum_reduced_time_mm_per_sqrt_v=20.0,
                stage_b_maximum_reduced_time_mm_per_sqrt_v=stage_b_end,
            )
        return result, propagate

    def test_voltage_pair_evaluator_preserves_signed_source_and_two_residuals(self) -> None:
        result, propagate = self.evaluate()
        first_call = propagate.call_args_list[0]
        initial = first_call.args[0]
        self.assertGreater(initial.u_y_sqrt_v, 0.0)
        self.assertLess(initial.u_z_sqrt_v, 0.0)
        self.assertIs(first_call.kwargs["numerics"], NUMERICS)
        self.assertEqual(
            first_call.kwargs["maximum_reduced_time_mm_per_sqrt_v"], 20.0,
        )
        self.assertEqual(
            propagate.call_args_list[1].kwargs["maximum_reduced_time_mm_per_sqrt_v"],
            200.0,
        )
        self.assertTrue(result.inferred_negative_mirror_pre_reflection)
        self.assertEqual(result.stripe_entrance_region_name, "stripe_11_set_1")
        self.assertEqual(
            tuple(name for name, _value in result.voltage_residuals),
            (
                "P1_P2_positive_mirror_turn_y_mm",
                "P1_P2_P2_shield_low_field_signed_vy_over_vz",
            ),
        )
        self.assertEqual(result.voltage_residuals[0][1], 0.25)
        self.assertEqual(result.derived_positive_mirror_turn_z_mm, 280.0)
        self.assertNotIn(
            "source_slow_energy_residual_v",
            tuple(name for name, _value in result.voltage_residuals),
        )
        self.assertEqual(result.qualification, "projected_yz_seed_only")
        self.assertIn("x focusing", " ".join(result.limitations))
        self.assertIn("not P1/P2 voltage residuals", " ".join(result.limitations))
        self.assertIn("not evaluated", " ".join(result.limitations))

    def test_stage_b_limit_is_an_absolute_reduced_time_terminal(self) -> None:
        stage_a, stage_b, _stage_c, _stage_d = staged_results()
        with self.assertRaisesRegex(CandidateContractError, "absolute maximum.*follow"):
            self.evaluate(stage_a, stage_b, stage_b_end=stage_a.final_state.reduced_time_mm_per_sqrt_v)

    def test_expected_transport_errors_are_reported_with_stage_context(self) -> None:
        stage_a, stage_b, _stage_c, _stage_d = staged_results()
        with self.assertRaisesRegex(
            CandidateContractError, "stage A segmented transport failed:.*tangent",
        ) as stage_a_error:
            self.evaluate(stage_a=TransportError("trajectory is tangent"))
        self.assertIsInstance(stage_a_error.exception.__cause__, TransportError)

        with self.assertRaisesRegex(
            CandidateContractError, "stage B segmented transport failed:.*wrong side",
        ) as stage_b_error:
            self.evaluate(stage_a=stage_a, stage_b=TransportError("approaches the wrong side"))
        self.assertIsInstance(stage_b_error.exception.__cause__, TransportError)

        class ProgrammingFailure(RuntimeError):
            pass

        with self.assertRaises(ProgrammingFailure):
            self.evaluate(stage_a=ProgrammingFailure("do not translate"), stage_b=stage_b)

    def test_source_inside_a_potential_band_is_rejected(self) -> None:
        with self.assertRaisesRegex(CandidateContractError, "outside every prism and Stripe"):
            self.evaluate(source=ProjectPhaseSpaceState(
                (0.0, -55.0, -60.0), (0.0, 0.01, -0.2),
            ))

    def test_voltage_pair_evaluator_preserves_transverse_source_projection(self) -> None:
        source = ProjectPhaseSpaceState(
            (-0.000115990801928, -55.328, 0.0),
            (-0.000460781565887, 0.01, -0.2),
        )
        result, propagate = self.evaluate(source=source)
        self.assertIs(result.source, source)
        self.assertEqual(result.transverse_projection.source_x_mm, source.position_mm[0])
        self.assertEqual(
            result.transverse_projection.source_vx_mm_per_us,
            source.velocity_mm_per_us[0],
        )
        self.assertGreater(result.transverse_projection.transverse_kinetic_energy_ev, 0.0)
        initial = propagate.call_args_list[0].args[0]
        self.assertEqual(initial.y_mm, source.position_mm[1])
        self.assertEqual(initial.z_mm, source.position_mm[2])
        self.assertNotIn(source.position_mm[0], (initial.y_mm, initial.z_mm))

    def test_voltage_pair_evaluator_keeps_source_direction_and_finite_gates(self) -> None:
        with self.assertRaisesRegex(CandidateContractError, "negative project z"):
            self.evaluate(source=ProjectPhaseSpaceState(
                (0.0, -55.328, 0.0), (0.0, 0.01, 0.2),
            ))
        with self.assertRaisesRegex(CandidateContractError, "finite"):
            ProjectPhaseSpaceState(
                (float("nan"), -55.328, 0.0), (0.0, 0.01, -0.2),
            )

    def test_voltage_pair_evaluator_rejects_wrong_p2_direction(self) -> None:
        stage_a, stage_b, _stage_c, _stage_d = staged_results()
        events = list(stage_b.events)
        entry = events[0]
        wrong = PhaseState2D(
            entry.state_before.reduced_time_mm_per_sqrt_v,
            entry.state_before.y_mm,
            entry.state_before.z_mm,
            entry.state_before.u_y_sqrt_v,
            -entry.state_before.u_z_sqrt_v,
        )
        events[0] = transport_event(
            entry.name, wrong, wrong,
            region="prism_17", entering=True, transmitted=True,
        )
        invalid = transport_result(
            stage_b.initial_state, stage_b.final_state, events,
            status="stopped",
        )
        with self.assertRaisesRegex(CandidateContractError, "positive-z transmitted P2"):
            self.evaluate(stage_a, invalid)

    def test_voltage_pair_evaluator_rejects_pre_turn_or_invalid_post_turn_stripe(self) -> None:
        stage_a, stage_b, stage_c, stage_d = staged_results()
        pre_turn_interface = list(stage_d.events[:2]) + list(stage_c.events)
        invalid_stage_c = transport_result(
            stage_c.initial_state, stage_c.final_state, pre_turn_interface,
            status="stopped_at_positive_mirror_turn",
        )
        with self.assertRaisesRegex(CandidateContractError, "before every Stripe interface"):
            self.evaluate(stage_a, stage_b, invalid_stage_c)

        reflected_events = list(stage_d.events)
        event = reflected_events[0]
        reflected_events[0] = transport_event(
            event.name, event.state_before, event.state_after,
            region=event.region_name, entering=True, transmitted=False,
        )
        reflected = transport_result(
            stage_d.initial_state, stage_d.final_state, reflected_events,
            status="stopped_after_first_positive_stripe_pass",
        )
        with self.assertRaisesRegex(CandidateContractError, "transmitted enter/exit"):
            self.evaluate(stage_a, stage_b, stage_c, reflected)

        missing_entry = transport_result(
            stage_d.initial_state, stage_d.final_state, [stage_d.events[-1]],
            status="stopped_after_first_positive_stripe_pass",
        )
        with self.assertRaisesRegex(CandidateContractError, "exactly one complete"):
            self.evaluate(stage_a, stage_b, stage_c, missing_entry)

    def test_positive_mirror_turn_localizer_finds_first_smooth_momentum_zero(self) -> None:
        result = _propagate_to_first_positive_mirror_turn(
            PhaseState2D(0.0, -8.0, 1.0, 1.0, 2.0),
            charge_sign=1,
            mirror_potential_v=lambda z: z * z,
            mirror_gradient_v_per_mm=lambda z: 2.0 * z,
            potential_regions=(),
            maximum_reduced_time_mm_per_sqrt_v=5.0,
            numerics=NUMERICS,
        )
        self.assertEqual(result.status, "stopped_at_positive_mirror_turn")
        self.assertEqual(result.events[-1].name, "first_post_P2_positive_mirror_turn")
        self.assertAlmostEqual(result.final_state.z_mm, 5.0**0.5, places=7)
        self.assertEqual(result.final_state.u_z_sqrt_v, 0.0)
        self.assertGreater(result.final_state.u_y_sqrt_v, 0.0)

    def test_positive_mirror_turn_localizer_rejects_interface_momentum_sign_flip(self) -> None:
        initial = PhaseState2D(0.0, -8.0, 1.0, 1.0, 2.0)
        before = PhaseState2D(0.05, -7.95, 1.08, 1.0, 1.0)
        after = PhaseState2D(0.05, -7.95, 1.08, 1.0, -1.0)
        final = PhaseState2D(0.1, -7.9, 1.02, 1.0, -1.2)
        segment = transport_result(initial, final, [
            transport_event(
                "stripe_11_set_1.lower", before, after,
                region="stripe_11_set_1", entering=True, transmitted=True,
            ),
        ], status="maximum_reduced_time")
        with (
            patch(
                "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
                "two_prism_segmented_transport.propagate_segmented_hamiltonian",
                return_value=segment,
            ),
            self.assertRaisesRegex(CandidateContractError, "hard-boundary interface"),
        ):
            _propagate_to_first_positive_mirror_turn(
                initial,
                charge_sign=1,
                mirror_potential_v=ZERO,
                mirror_gradient_v_per_mm=ZERO,
                potential_regions=(),
                maximum_reduced_time_mm_per_sqrt_v=1.0,
                numerics=NUMERICS,
            )

    def test_stage_d_starts_at_turn_and_stops_after_first_complete_stripe_pass(self) -> None:
        stripe = polygon_potential_region(
            "stripe_11_set_1",
            ((-10.0, 0.2), (10.0, 0.2), (10.0, 0.4), (-10.0, 0.4)),
            0.0,
        )
        result = _propagate_to_first_complete_positive_stripe_pass(
            PhaseState2D(0.0, 0.0, 1.0, 1.0, 0.0),
            charge_sign=1,
            mirror_potential_v=lambda z: z,
            mirror_gradient_v_per_mm=lambda _z: 1.0,
            potential_regions=(stripe,),
            positive_stripe_region_names=(stripe.name,),
            maximum_reduced_time_mm_per_sqrt_v=3.0,
            numerics=NUMERICS,
        )
        self.assertEqual(result.status, "stopped_after_first_positive_stripe_pass")
        self.assertEqual(
            [(event.region_name, event.entering) for event in result.events if event.kind == "interface"],
            [(stripe.name, True), (stripe.name, False)],
        )
        self.assertEqual(result.events[-1].name, "first_post_turn_positive_stripe_pass_complete")
        self.assertLess(result.final_state.u_z_sqrt_v, 0.0)

    def test_stage_d_rejects_transmitted_stripe_entry_or_exit_z_sign_change(self) -> None:
        turn = PhaseState2D(0.0, 0.0, 1.0, 1.0, 0.0)
        negative = PhaseState2D(0.1, 0.1, 0.9, 1.0, -1.0)
        positive = PhaseState2D(0.1, 0.1, 0.9, 1.0, 1.0)
        later_negative = PhaseState2D(0.2, 0.2, 0.8, 1.0, -1.0)
        cases = (
            (
                "entry",
                [transport_event(
                    "stripe_11_set_1.lower", negative, positive,
                    region="stripe_11_set_1", entering=True, transmitted=True,
                )],
            ),
            (
                "exit",
                [
                    transport_event(
                        "stripe_11_set_1.lower", negative, negative,
                        region="stripe_11_set_1", entering=True, transmitted=True,
                    ),
                    transport_event(
                        "stripe_11_set_1.upper", later_negative, positive,
                        region="stripe_11_set_1", entering=False, transmitted=True,
                    ),
                ],
            ),
        )
        for label, events in cases:
            with self.subTest(label=label), patch(
                "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
                "two_prism_segmented_transport.propagate_segmented_hamiltonian",
                return_value=transport_result(
                    turn, events[-1].state_after, events,
                    status="maximum_reduced_time",
                ),
            ), self.assertRaisesRegex(CandidateContractError, "strictly negative z momentum"):
                _propagate_to_first_complete_positive_stripe_pass(
                    turn,
                    charge_sign=1,
                    mirror_potential_v=ZERO,
                    mirror_gradient_v_per_mm=ZERO,
                    potential_regions=(),
                    positive_stripe_region_names=("stripe_11_set_1",),
                    maximum_reduced_time_mm_per_sqrt_v=1.0,
                    numerics=NUMERICS,
                )

    def test_stage_d_rejects_smooth_z_turn_before_stripe_exit(self) -> None:
        turn = PhaseState2D(0.0, 0.0, 1.0, 1.0, 0.0)
        entry = PhaseState2D(0.1, 0.1, 0.9, 1.0, -1.0)
        near_turn = PhaseState2D(0.2, 0.2, 0.8, 1.0, 0.0)
        segment = transport_result(turn, near_turn, [
            transport_event(
                "stripe_11_set_1.lower", entry, entry,
                region="stripe_11_set_1", entering=True, transmitted=True,
            ),
        ], status="maximum_reduced_time")
        with patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "two_prism_segmented_transport.propagate_segmented_hamiltonian",
            return_value=segment,
        ), self.assertRaisesRegex(CandidateContractError, "smooth turn before"):
            _propagate_to_first_complete_positive_stripe_pass(
                turn,
                charge_sign=1,
                mirror_potential_v=ZERO,
                mirror_gradient_v_per_mm=ZERO,
                potential_regions=(),
                positive_stripe_region_names=("stripe_11_set_1",),
                maximum_reduced_time_mm_per_sqrt_v=1.0,
                numerics=NUMERICS,
            )

    def test_real_contract_binds_stable_prism_and_stripe_topology(self) -> None:
        regions = build()
        self.assertEqual(
            [region.name for region in regions],
            ["prism_16", "prism_17", "stripe_11_set_1", "stripe_12_set_1",
             "stripe_13_set_2", "stripe_14_set_2"],
        )
        self.assertEqual([region.bias_v for region in regions], [101.0, -102.0, 11.0, 11.0, -12.0, -12.0])

    def test_trim_and_active_curve_cross_y_zero_without_internal_interface(self) -> None:
        regions = build()
        result = propagate_segmented_hamiltonian(
            PhaseState2D(0.0, -1.0, 80.0, 1.0, 0.0),
            charge_sign=1,
            mirror_potential_v=ZERO,
            mirror_gradient_v_per_mm=ZERO,
            potential_regions=regions,
            stop_targets=(plane_stop_target("after_join", (1.0, 0.0), 1.0, direction=1),),
            maximum_reduced_time_mm_per_sqrt_v=3.0,
            numerics=NUMERICS,
        )
        self.assertEqual(result.status, "stopped")
        self.assertEqual([event.kind for event in result.events], ["stop"])
        self.assertEqual(result.active_region_names, ("stripe_11_set_1",))
        self.assertLess(abs(result.final_hamiltonian_residual_v), 1.0e-10)

    def test_negative_z_instances_are_exact_mirrors(self) -> None:
        regions = {region.name: region for region in build()}
        for set_name, positive_id, negative_id in (("set_1", 11, 12), ("set_2", 13, 14)):
            positive = regions[f"stripe_{positive_id}_{set_name}"]
            negative = regions[f"stripe_{negative_id}_{set_name}"]
            for y in (-1.0, 0.0, 120.0, 390.0):
                for z in (20.0, 50.0, 80.0, 100.0):
                    self.assertEqual(positive.contains(y, z), negative.contains(y, -z))

    def test_invalid_terminal_trim_fails_closed(self) -> None:
        base = load_contract(CONTRACT)
        cases = (
            ("disconnected", [60.0, 63.0], "disconnected"),
            ("overlapping", [55.0, 70.0], "overlap"),
            ("negative_width", [70.0, 60.0], "positive y-z area"),
        )
        for label, bounds, message in cases:
            with self.subTest(label=label):
                contract = deepcopy(base)
                contract["dual_stripe"]["theory_profile"]["set_1"]["terminal_z_mm"] = bounds
                with self.assertRaisesRegex(CandidateContractError, message):
                    build(contract)

    def test_bias_maps_are_complete_and_finite(self) -> None:
        contract = load_contract(CONTRACT)
        with self.assertRaises(CandidateContractError):
            build_two_prism_segmented_potential_regions(
                contract,
                prism_bias_v_by_electrode_id={16: 1.0},
                stripe_bias_v_by_set_name={"set_1": 1.0, "set_2": 2.0},
            )
        with self.assertRaises(CandidateContractError):
            build_two_prism_segmented_potential_regions(
                contract,
                prism_bias_v_by_electrode_id={16: 1.0, 17: 2.0},
                stripe_bias_v_by_set_name={"set_1": float("nan"), "set_2": 2.0},
            )

    def test_prism_facing_x_sections_must_share_one_triangle(self) -> None:
        contract = deepcopy(load_contract(CONTRACT))
        contract["prisms"]["electrodes"][0]["polygons_yz_mm"][1][0] += 0.1
        with self.assertRaisesRegex(CandidateContractError, "consistent y-z triangle"):
            build(contract)


if __name__ == "__main__":
    unittest.main()
