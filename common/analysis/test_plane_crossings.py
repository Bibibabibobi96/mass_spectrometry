"""Hand-computed contracts for bounded directed crossings; no solver or I/O."""
from __future__ import annotations

from dataclasses import replace
import math
import unittest
import weakref

from common.analysis.plane_crossings import (
    CrossingBracket,
    CrossingSample,
    iter_bounded_plane_crossings,
)
from common.contracts.rigid_transform import PhaseSpaceState, PlaneSurface


def sample(pid, anchor, time, z, *, vz=-1000., frame="instrument"):
    return CrossingSample(pid, anchor, PhaseSpaceState(frame, (2., 3., z), (10., 20., vz), time))


def negative_z(z=0., frame="instrument"):
    return PlaneSurface(frame, (0., 0., z), (0., 0., -1.))


def crossings(rows, **changes):
    arguments = dict(particle_ids=[1], planes={"exit": negative_z()},
                     minimum_time_us=0., maximum_gap_us=1., gap_tolerance_us=0.)
    arguments.update(changes)
    arguments["particle_ids"] = list(arguments["particle_ids"])
    # Only the small test fixture is collected. Production adapters consume
    # each receipt while their original raw bracket is still current.
    result = {(pid, key): [] for pid in arguments["particle_ids"] for key in arguments["planes"]}
    for bracket in iter_bounded_plane_crossings(rows, **arguments):
        result[bracket.particle_id, bracket.plane_id].append(bracket)
    return {key: tuple(values) for key, values in result.items()}


class PlaneCrossingTests(unittest.TestCase):
    def test_hand_computed_bracket_preserves_original_anchors_and_inputs(self):
        rows = [sample(41, 12, 10., 4.), sample(41, "measured_exit", 10.5, 0.)]
        original = list(rows)
        result = crossings(iter(rows), particle_ids=[41], planes={"upstream": negative_z(3.)},
                           minimum_time_us=10.)
        self.assertEqual(result, {(41, "upstream"): (CrossingBracket(
            particle_id=41, plane_id="upstream", occurrence=1,
            lower_anchor=12, upper_anchor="measured_exit",
            bracket_start_us=10., bracket_end_us=10.5, bracket_gap_us=.5, interpolation_alpha=.25,
        ),)})
        self.assertEqual(rows, original)
        self.assertEqual(rows[0].state.position_mm, (2., 3., 4.))
        self.assertEqual(result[41, "upstream"][0].schema_version, 1)
        self.assertEqual(result[41, "upstream"][0].method, "bounded_linear_directed_plane_crossing")

    def test_negative_z_alpha_keeps_existing_coordinate_expression_exactly(self):
        before, plane, after = 4.312, 3.7, .937
        result = crossings([sample(1, 2, 0., before), sample(1, 3, 1., after)],
                           planes={"section": negative_z(plane)})
        self.assertEqual(result[1, "section"][0].interpolation_alpha, (plane-before)/(after-before))

    def test_plane_normal_selects_both_directions_without_axis_assumptions(self):
        for sign in (-1., 1.):
            with self.subTest(sign=sign):
                plane = PlaneSurface("instrument", (2., 0., 0.), (sign, 0., 0.))
                states = [PhaseSpaceState("instrument", (2.-sign, 6., 7.), (sign*1000., 2., 3.), 4.),
                          PhaseSpaceState("instrument", (2.+3*sign, 8., 9.), (sign*500., 4., 5.), 5.)]
                rows = [CrossingSample(1, 10+i, state) for i, state in enumerate(states)]
                result = crossings(rows, planes={"x": plane})
                self.assertEqual(result[1, "x"][0].interpolation_alpha, .25)
                self.assertEqual(crossings(rows, planes={"reverse": replace(plane, normal=(-sign, 0., 0.))}),
                                 {(1, "reverse"): ()})

    def test_oblique_plane_uses_full_position_and_velocity(self):
        plane = PlaneSurface("instrument", (0., 0., 5.), (.6, .8, 0.))
        rows = [CrossingSample(1, "before", PhaseSpaceState("instrument", (-3., -4., 2.), (300., 400., -8.), 2.)),
                CrossingSample(1, "after", PhaseSpaceState("instrument", (3., 4., 8.), (600., 800., 4.), 3.))]
        self.assertEqual(crossings(rows, planes={"oblique": plane})[1, "oblique"][0].interpolation_alpha, .5)
        backwards = [replace(row, state=replace(row.state, velocity_m_s=(-300., -400., 0.))) for row in rows]
        self.assertEqual(crossings(backwards, planes={"oblique": plane}), {(1, "oblique"): ()})

    def test_first_kth_and_all_count_shared_endpoint_once(self):
        rows = [
            sample(1, 10, 0., 2.), sample(1, 11, 1., 0.), sample(1, 12, 2., -2.),
            sample(1, 13, 3., 2., vz=1000.), sample(1, 14, 4., 2.), sample(1, 15, 5., -2.),
            sample(1, 16, 6., 2., vz=1000.), sample(1, 17, 7., 2.), sample(1, 18, 8., -2.),
        ]
        all_rows = crossings(rows, occurrence=None)[1, "exit"]
        self.assertEqual([(r.occurrence, r.lower_anchor, r.upper_anchor, r.interpolation_alpha) for r in all_rows],
                         [(1, 10, 11, 1.), (2, 14, 15, .5), (3, 17, 18, .5)])
        self.assertEqual(crossings(rows)[1, "exit"], all_rows[:1])
        self.assertEqual(crossings(rows, occurrence=2)[1, "exit"], all_rows[1:2])
        self.assertEqual(crossings(rows, occurrence=3)[1, "exit"], all_rows[2:])
        self.assertEqual(crossings(rows, occurrence=4)[1, "exit"], ())

    def test_start_on_plane_is_inclusive_but_stationary_touch_is_not_crossing(self):
        rows = [sample(1, "start", 0., 0.), sample(1, "after", 1., -2.)]
        self.assertEqual(crossings(rows)[1, "exit"][0].interpolation_alpha, 0.)
        stationary = [sample(1, 2, 0., 0.), sample(1, 3, 1., 0.)]
        self.assertEqual(crossings(stationary), {(1, "exit"): ()})

    def test_interleaved_ids_and_every_requested_pair_keep_caller_order(self):
        large_id = 2**60+1
        rows = [sample(large_id, 2, 5., 4.), sample(7, 3, 2., 4.),
                sample(7, 4, 3., -2.), sample(large_id, 5, 6., -2.)]
        result = crossings(rows, particle_ids=[large_id, 7, 99],
                           planes={"upper": negative_z(2.), "lower": negative_z()})
        self.assertEqual(list(result), [(large_id, "upper"), (large_id, "lower"),
                                       (7, "upper"), (7, "lower"), (99, "upper"), (99, "lower")])
        self.assertEqual(result[large_id, "upper"][0].particle_id, large_id)
        self.assertEqual((result[7, "lower"][0].lower_anchor, result[7, "lower"][0].upper_anchor), (3, 4))
        self.assertEqual(result[99, "upper"], ())
        self.assertEqual(result[99, "lower"], ())

    def test_no_bracket_across_time_lower_bound_and_boundary_sample_is_eligible(self):
        rows = [sample(1, 2, 9.5, 5.), sample(1, 3, 10., 3.), sample(1, 4, 10.5, 1.)]
        result = crossings(rows, minimum_time_us=10.,
                           planes={"before": negative_z(4.), "at": negative_z(3.), "after": negative_z(2.)})
        self.assertEqual(result[1, "before"], ())
        self.assertEqual(result[1, "at"][0].interpolation_alpha, 0.)
        self.assertEqual(result[1, "after"][0].interpolation_alpha, .5)
        self.assertEqual(result[1, "after"][0].lower_anchor, 3)

    def test_explicit_gap_tolerance_has_a_closed_upper_boundary(self):
        bound = .5+1e-12
        for end, tolerance, expected in ((.5, 0., True), (bound, 0., False),
                                          (bound, 1e-12, True), (math.nextafter(bound, math.inf), 1e-12, False)):
            with self.subTest(end=end, tolerance=tolerance):
                rows = [sample(1, 2, 0., 1.), sample(1, 3, end, -1.)]
                self.assertEqual(bool(crossings(rows, maximum_gap_us=.5, gap_tolerance_us=tolerance)[1, "exit"]),
                                 expected)

    def test_rejected_long_gap_is_not_bridged_and_next_adjacent_pair_is_used(self):
        rows = [sample(1, 2, 0., 4.), sample(1, 3, 2., 2.), sample(1, 4, 2.5, 0.)]
        result = crossings(rows, planes={"missing": negative_z(3.), "observed": negative_z(1.)})
        self.assertEqual(result[1, "missing"], ())
        self.assertEqual(result[1, "observed"][0].lower_anchor, 3)
        self.assertEqual(result[1, "observed"][0].interpolation_alpha, .5)

    def test_both_endpoint_velocities_must_be_strictly_forward(self):
        for before_v, after_v in ((0., -1.), (-1., 0.), (1., -1.), (-1., 1.)):
            with self.subTest(before_v=before_v, after_v=after_v):
                rows = [sample(1, 2, 0., 1., vz=before_v), sample(1, 3, 1., -1., vz=after_v)]
                self.assertEqual(crossings(rows), {(1, "exit"): ()})
        rows = [sample(1, 2, 0., 4.), sample(1, 3, 1., 2., vz=1.),
                sample(1, 4, 2., 0.), sample(1, 5, 3., -2.)]
        result = crossings(rows, planes={"missing": negative_z(1.), "observed": negative_z(-1.)})
        self.assertEqual(result[1, "missing"], ())
        self.assertEqual(result[1, "observed"][0].lower_anchor, 4)

    def test_measured_exit_above_plane_cannot_support_extrapolation(self):
        rows = [sample(1, 2, 10., 1.), sample(1, "measured_exit", 10.5, 1e-11)]
        self.assertEqual(crossings(rows, planes={"below_exit": negative_z(1e-12)}), {(1, "below_exit"): ()})
        self.assertEqual(crossings(rows, planes={"above_sample": negative_z(2.)}), {(1, "above_sample"): ()})

    def test_empty_input_keeps_missing_pairs_without_assigning_status(self):
        self.assertEqual(crossings(iter(()), particle_ids=[3, 1]), {(3, "exit"): (), (1, "exit"): ()})
        self.assertEqual(crossings(iter(()), particle_ids=[]), {})

    def test_unknown_ids_fail_before_window_and_after_selected_crossing(self):
        valid = [sample(1, 2, 0., 1.), sample(1, 3, 1., -1.)]
        for rows in ([sample(7, 10, -1., 2.)], valid+[sample(7, 11, 2., -3.)]):
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, "unknown particle_id"):
                crossings(rows)

    def test_duplicate_or_noncanonical_cohort_ids_are_rejected(self):
        for ids in ([1, 1], [True], [1.], ["1"], [0], [-1]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                crossings([], particle_ids=ids)

    def test_strict_time_order_is_required_even_before_window_or_after_selection(self):
        for times in ((1., 1.), (1., 0.), (-2., -3.)):
            with self.subTest(times=times), self.assertRaisesRegex(ValueError, "time not increasing"):
                crossings([sample(1, 2, times[0], 1.), sample(1, 3, times[1], -1.)])
        with self.assertRaisesRegex(ValueError, "time not increasing"):
            crossings([sample(1, 2, 0., 1.), sample(1, 3, 1., -1.), sample(1, 4, .5, -2.)])

    def test_original_record_keys_are_valid_and_bracket_anchors_are_distinct(self):
        for anchor in (0, -1, True, 2., "", " exit", None, ("exit", 1)):
            with self.subTest(anchor=anchor), self.assertRaises(ValueError):
                sample(1, anchor, 0., 1.)
        with self.assertRaisesRegex(ValueError, "distinct original record anchors"):
            crossings([sample(1, "event", 0., 1.), sample(1, "event", 1., -1.)])
        # The same source row/event key in separate per-particle streams is not
        # merged: complete source identity remains the caller's responsibility.
        rows = [sample(1, "before", 0., 1.), sample(2, "before", 0., 1.),
                sample(1, "after", 1., -1.), sample(2, "after", 1., -1.)]
        self.assertTrue(all(crossings(rows, particle_ids=[1, 2]).values()))

    def test_state_and_plane_types_frames_and_finite_state_are_enforced(self):
        with self.assertRaisesRegex(ValueError, "PhaseSpaceState"):
            CrossingSample(1, 2, {})
        with self.assertRaisesRegex(ValueError, "CrossingSample"):
            crossings([{}])
        for frame in ("other",):
            with self.assertRaisesRegex(ValueError, "frame mismatch"):
                crossings([sample(1, 2, -1., 1., frame=frame)])
        with self.assertRaisesRegex(ValueError, "one frame"):
            crossings([], planes={"a": negative_z(), "b": negative_z(frame="other")})
        for planes in ({}, [], {"": negative_z()}, {" p": negative_z()}, {"p": {}}):
            with self.subTest(planes=planes), self.assertRaises(ValueError):
                crossings([], planes=planes)
        for z, time in ((math.nan, 0.), (1., math.inf)):
            with self.subTest(z=z, time=time), self.assertRaises(ValueError):
                sample(1, 2, time, z)

    def test_invalid_numeric_parameters_and_occurrence_fail_closed(self):
        for field in ("minimum_time_us", "maximum_gap_us", "gap_tolerance_us"):
            for value in (True, "1", math.nan, math.inf, 1+2j, 10**1000):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    crossings([], **{field: value})
        for changes in ({"maximum_gap_us": 0.}, {"maximum_gap_us": -1.}, {"gap_tolerance_us": -1.},
                        {"maximum_gap_us": 1e308, "gap_tolerance_us": 1e308}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                crossings([], **changes)
        for value in (0, -1, True, 1., "1"):
            with self.subTest(occurrence=value), self.assertRaises(ValueError):
                crossings([], occurrence=value)

    def test_finite_inputs_with_unrepresentable_gap_or_projection_fail_closed(self):
        rows = [sample(1, 2, -1e308, 1.), sample(1, 3, 1e308, -1.)]
        with self.assertRaisesRegex(ValueError, "finite numeric range"):
            crossings(rows, minimum_time_us=-1e308, maximum_gap_us=1e308)
        rows = [sample(1, 2, 0., 1e308), sample(1, 3, 1., -1e308)]
        with self.assertRaisesRegex(ValueError, "finite numeric range"):
            crossings(rows)

    def test_stream_yields_before_consuming_next_original_row(self):
        consumed = []
        def source():
            for anchor, z in ((2, 1.), (3, -1.), (4, -2.)):
                consumed.append(anchor)
                yield sample(1, anchor, anchor-2., z)
        stream = iter_bounded_plane_crossings(source(), particle_ids=[1], planes={"exit": negative_z()},
                                             minimum_time_us=0., maximum_gap_us=1., gap_tolerance_us=0.)
        self.assertEqual(consumed, [])
        self.assertEqual(next(stream).upper_anchor, 3)
        self.assertEqual(consumed, [2, 3])
        self.assertEqual(list(stream), [])
        self.assertEqual(consumed, [2, 3, 4])

    def test_first_selection_does_not_retain_trajectory_states(self):
        references = []
        peak_live = 0
        def source():
            nonlocal peak_live
            for i in range(500):
                row = sample(1, i+2, float(i), 1.-i)
                references.append(weakref.ref(row))
                peak_live = max(peak_live, sum(ref() is not None for ref in references))
                yield row
        result = crossings(source())
        self.assertEqual(len(result[1, "exit"]), 1)
        self.assertLessEqual(peak_live, 3)
        self.assertTrue(all(ref() is None for ref in references))

    def test_bracket_version_and_evidence_validator_rejects_inconsistent_results(self):
        valid = CrossingBracket(1, "plane", 1, 2, "exit", 3., 4., 1., .5)
        changes = ({"schema_version": 2}, {"schema_version": True}, {"method": "extrapolated"},
                   {"particle_id": True}, {"plane_id": ""}, {"occurrence": 0},
                   {"upper_anchor": 2}, {"bracket_gap_us": .5}, {"bracket_end_us": 2.},
                   {"interpolation_alpha": -.01}, {"interpolation_alpha": 1.01},
                   {"interpolation_alpha": math.nan}, {"bracket_start_us": math.inf})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(valid, **change)


if __name__ == "__main__":
    unittest.main()
