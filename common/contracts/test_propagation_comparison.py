"""Descriptive arithmetic using CSV1 states and actual collector plane shapes."""
from __future__ import annotations
import copy
import math
import unittest

from msplatform.analysis.propagation_comparison import compare_propagations
from msplatform.assembly.handoff import HandoffMother
from msplatform.contracts.clock import ClockIdentity


def state(pid=7, *, time=12., position=(1., 2., 3.), velocity=(3000., 4000., 0.), phase=.2):
    birth = 5. if pid == 7 else 8.
    return dict(particle_id=pid, parent_particle_id=None, generation=0, species_id="ion100", particle_weight=2.,
        source_component_id="a", target_component_id="b", state_event="mechanical_exit", frame_id="world",
        clock_epoch_id="epoch", instrument_time_us=time, particle_age_us=time-birth, lineage_age_us=time-birth,
        last_component_elapsed_time_us=1., lineage_birth_time_us=birth, particle_birth_time_us=birth,
        mass_amu=100., charge_state=1, mass_to_charge_Th=100.,
        kinetic_energy_eV=.5*100.*1.66053906660e-27*sum(v*v for v in velocity)/1.602176634e-19,
        **{f"position_{a}_mm": v for a, v in zip("xyz", position)},
        **{f"velocity_{a}_m_s": v for a, v in zip("xyz", velocity)},
        phase_reference_id="rf" if phase is not None else None, phase_rad=phase)


def event(row, occurrence=1):
    return dict(particle_id=row["particle_id"], observation_id="exit", direction="outward", occurrence=occurrence,
        instrument_time_us=row["instrument_time_us"], method="accepted_step_linear_interpolation",
        raw_line_number=10, log="frozen-native.log", step_start_instrument_time_us=10., step_end_instrument_time_us=20.,
        **{f"{a}_mm": row[f"position_{a}_mm"] for a in "xyz"},
        **{f"v{a}_mm_per_us": row[f"velocity_{a}_m_s"]/1000 for a in "xyz"})


class PropagationComparisonTests(unittest.TestCase):
    def setUp(self):
        self.left = [state(), state(99)]
        self.right = [state(time=14., position=(4., 6., 3.), velocity=(0., 4000., 3000.), phase=2*math.pi-.2)]
        keys = ("species_id", "mass_amu", "charge_state", "particle_weight", "particle_birth_time_us")
        self.mother = HandoffMother({r["particle_id"]: {k: r[k] for k in keys} for r in self.left},
            ({"particle_id": 7, "terminal_reason": "unknown"}, {"particle_id": 99, "terminal_reason": "censored"}))
        self.clock = ClockIdentity("epoch", "A"*64)

    def compare(self, **changes):
        args = dict(mother=self.mother, left_clock=self.clock, right_clock=self.clock,
            left_fates={7: "detected", 99: "unknown"}, right_fates={7: "censored", 99: "unknown"},
            observation_id="exit", direction="outward", occurrence=1,
            left_events=[event(r) for r in self.left], right_events=[event(r) for r in self.right])
        left = changes.pop("left_states", self.left)
        right = changes.pop("right_states", self.right)
        args.update(changes)
        return compare_propagations(left, right, **args)

    def test_independent_arithmetic_full_mother_and_input_preservation(self):
        before = copy.deepcopy((self.left, self.right, self.mother))
        result = self.compare()
        delta = result["pairs"][0]["right_minus_left"]
        self.assertEqual(delta["position_components_mm"], [3., 4., 0.])
        self.assertEqual(delta["position_norm_mm"], 5.)
        self.assertEqual(delta["velocity_components_m_s"], [-3000., 0., 3000.])
        self.assertAlmostEqual(delta["velocity_norm_m_s"], 3000*math.sqrt(2))
        self.assertEqual([delta[k] for k in ("instrument_time_us", "particle_age_us", "lineage_age_us")], [2.]*3)
        self.assertEqual(delta["kinetic_energy_eV"], 0.)
        self.assertAlmostEqual(delta["phase_raw_rad"], 2*math.pi-.4)
        self.assertAlmostEqual(delta["phase_wrapped_rad"], -.4)
        self.assertEqual(result["unmatched_particle_ids"], {"left": [99], "right": []})
        self.assertEqual(result["missing_state_particle_ids"], {"left": [], "right": [99]})
        self.assertEqual(result["fate_partitions"]["left"]["counts"]["unknown"], 1)
        self.assertEqual(result["fate_differences"], [dict(particle_id=7, left="detected", right="censored")])
        result["mother_records"][7]["particle_weight"] = 88
        self.assertEqual((self.left, self.right, self.mother), before)

    def test_nonzero_residual_and_changed_fate_do_not_create_failure_verdict(self):
        result = self.compare(left_states=self.left[:1], mother=HandoffMother(
            {7: self.mother.records[7]}, ({"particle_id": 7, "terminal_reason": "unknown"},)),
            left_events=[event(self.left[0])], left_fates={7: "unknown"}, right_fates={7: "censored"})
        self.assertEqual(result["status"], "comparison_completed")
        self.assertEqual(result["pairs"][0]["right_minus_left"]["position_norm_mm"], 5.)
        self.assertNotIn("passed", result)
        self.assertNotIn("threshold", result)

    def test_explicit_occurrence_and_sparse_original_order(self):
        rows = self.left[::-1]
        events = [event(r, 2) for r in rows]+[event(r) for r in self.left]
        result = self.compare(right_states=rows, left_events=events, right_events=events, occurrence=2)
        self.assertEqual(result["matched_particle_ids"], [7, 99])
        self.assertEqual(result["status"], "comparison_completed")

    def test_missing_phase_does_not_hide_other_observations(self):
        rows = copy.deepcopy(self.right)
        rows[0].update(phase_rad=None, phase_reference_id=None)
        result = self.compare(right_states=rows, right_events=[event(r) for r in rows])
        self.assertIsNone(result["pairs"][0]["right_minus_left"]["phase_wrapped_rad"])
        self.assertEqual(result["pairs"][0]["right_minus_left"]["instrument_time_us"], 2.)
        self.assertEqual(result["status"], "insufficient_observations")

    def test_zero_observations_retain_all_mother_fates(self):
        result = self.compare(left_states=[], right_states=[], left_events=[], right_events=[])
        self.assertEqual(result["missing_state_particle_ids"], {"left": [7, 99], "right": [7, 99]})
        self.assertEqual(result["unobserved_in_both_particle_ids"], [7, 99])
        self.assertEqual(result["fate_partitions"]["right"]["mother_weight_sum"], 4.)
        self.assertEqual(result["status"], "insufficient_observations")

    def test_clock_weight_frame_and_incomplete_fates_reject(self):
        with self.assertRaisesRegex(ValueError, "authority"):
            self.compare(right_clock=ClockIdentity("epoch", "B"*64))
        for key, value in (("particle_weight", 3.), ("frame_id", "other")):
            rows = copy.deepcopy(self.right)
            rows[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.compare(right_states=rows, right_events=[event(r) for r in rows])
        with self.assertRaises(ValueError):
            self.compare(right_fates={7: "unknown"})

    def test_corrupt_event_identity_units_nonfinite_and_duplicates_reject(self):
        for key, value in (("particle_id", 3), ("x_mm", 123.), ("vx_mm_per_us", float("nan")), ("occurrence", True)):
            rows = [event(self.right[0])]
            rows[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.compare(right_events=rows)
        with self.assertRaises(ValueError):
            self.compare(right_events=[event(self.right[0])]*2)
        with self.assertRaises(ValueError):
            self.compare(right_states=self.right*2)

    def test_serialization_binding_is_not_cross_run_difference_filter(self):
        rows = [event(self.right[0])]
        rows[0]["x_mm"] = math.nextafter(rows[0]["x_mm"], math.inf)
        result = self.compare(right_events=rows)
        self.assertEqual(result["pairs"][0]["right_minus_left"]["position_components_mm"], [3., 4., 0.])

    def test_energy_difference_uses_valid_species_velocity_and_no_reweighting(self):
        rows = [state(time=14., velocity=(0., 4000., 0.))]
        result = self.compare(right_states=rows, right_events=[event(rows[0])])
        expected = -.5*100.*1.66053906660e-27*9000000./1.602176634e-19
        self.assertAlmostEqual(result["pairs"][0]["right_minus_left"]["kinetic_energy_eV"], expected)
        self.assertEqual(result["fate_partitions"]["left"]["mother_weight_sum"], 4.)
        rows[0]["particle_birth_time_us"] = 6.
        rows[0].update(particle_age_us=8., lineage_birth_time_us=6., lineage_age_us=8.)
        with self.assertRaisesRegex(ValueError, "original birth"):
            self.compare(right_states=rows, right_events=[event(rows[0])])

    def test_unobserved_mother_metadata_and_original_fates_are_not_exempt(self):
        records = copy.deepcopy(self.mother.records)
        records[99]["mass_amu"] = float("nan")
        with self.assertRaisesRegex(ValueError, "mother metadata"):
            self.compare(left_states=[], right_states=[], left_events=[], right_events=[],
                mother=HandoffMother(records, self.mother.fates))
        with self.assertRaisesRegex(ValueError, "fate records"):
            self.compare(mother=HandoffMother(self.mother.records, self.mother.fates[:1]))


if __name__ == "__main__":
    unittest.main()
