"""Independent kinematic checks for frozen-cohort pulse duration derivation."""

import copy
import math
import unittest

from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_pulse_duration import (
    derive_pulse_duration,
)


class PulseDurationTests(unittest.TestCase):
    def setUp(self) -> None:
        # Three equal-field intervals reduce to a single constant acceleration.
        self.geometry = {
            "accelerator_topology": {
                "planes_global_z_mm": {
                    "repeller": 10.0, "intermediate1": 20.0,
                    "intermediate2": 40.0, "exit": 70.0,
                },
                "potentials_v": {
                    "repeller": 600.0, "intermediate1": 500.0,
                    "intermediate2": 300.0, "exit": 0.0,
                },
            },
            "geometry_mm": {"accelerator_focus_z": 90.0},
        }
        self.row = {
            "particle_id": 7, "position_z_mm": 15.0,
            "velocity_z_m_s": 500.0, "mass_amu": 100.0, "charge_state": 1,
            "instrument_time_us": 30.0,
        }

    def derive(self, rows=None, geometry=None, minimum=0.1):
        return derive_pulse_duration(
            [self.row] if rows is None else rows,
            self.geometry if geometry is None else geometry,
            minimum_width_us=minimum,
        )

    def test_equal_fields_match_independent_constant_acceleration(self) -> None:
        # SI kinematics, independently of the normalized-time implementation.
        acceleration = 1.602176634e-19 * 10_000 / (100 * 1.66053906660e-27)
        initial_velocity = self.row["velocity_z_m_s"]
        final_velocity = math.sqrt(initial_velocity**2 + 2 * acceleration * 0.055)
        exit_time = (final_velocity - initial_velocity) / acceleration * 1e6
        focus_time = exit_time + 0.020 / final_velocity * 1e6
        result = self.derive()
        self.assertAlmostEqual(result["ideal_max_exit_time_us"], exit_time, places=8)
        self.assertAlmostEqual(result["ideal_max_focus_time_us"], focus_time, places=8)
        self.assertEqual(result["pulse_width_us"], result["ideal_max_focus_time_us"])

    def test_full_population_slowest_particle_sets_duration(self) -> None:
        slow = {**self.row, "particle_id": 91, "mass_amu": 400.0}
        result = self.derive([self.row, slow])
        self.assertEqual(result["particle_count"], 2)
        self.assertEqual(result["limiting_particle_id"], 91)
        self.assertEqual(result["pulse_width_us"], self.derive([slow])["pulse_width_us"])
        self.assertEqual(result, self.derive([slow, self.row]))

    def test_signed_initial_velocity_is_not_energy_only(self) -> None:
        backwards = {**self.row, "velocity_z_m_s": -500.0}
        self.assertGreater(self.derive([backwards])["pulse_width_us"], self.derive()["pulse_width_us"])

    def test_mass_to_charge_scaling_and_minimum_width(self) -> None:
        stopped = {**self.row, "velocity_z_m_s": 0.0}
        baseline = self.derive([stopped])["pulse_width_us"]
        self.assertAlmostEqual(
            self.derive([{**stopped, "mass_amu": 400.0}])["pulse_width_us"], 2 * baseline
        )
        self.assertAlmostEqual(
            self.derive([{**stopped, "charge_state": 4}])["pulse_width_us"], baseline / 2
        )
        self.assertEqual(self.derive(minimum=100)["pulse_width_us"], 100)

    def test_clock_translation_and_potential_gauge_do_not_change_duration(self) -> None:
        geometry = copy.deepcopy(self.geometry)
        for key in geometry["accelerator_topology"]["planes_global_z_mm"]:
            geometry["accelerator_topology"]["planes_global_z_mm"][key] += 100
            geometry["accelerator_topology"]["potentials_v"][key] += 230
        geometry["geometry_mm"]["accelerator_focus_z"] += 100
        row = {**self.row, "position_z_mm": 115.0, "instrument_time_us": 9999.0}
        self.assertEqual(self.derive([row], geometry), self.derive())

    def test_invalid_population_and_geometry_are_rejected_without_filtering(self) -> None:
        with self.assertRaises(ContractError):
            self.derive([])
        for changes in (
            {"position_z_mm": 10.0}, {"position_z_mm": 20.0},
            {"velocity_z_m_s": -100_000.0}, {"velocity_z_m_s": math.nan},
            {"mass_amu": 0}, {"charge_state": -1},
        ):
            with self.subTest(changes=changes), self.assertRaises(ContractError):
                self.derive([self.row, {**self.row, **changes, "particle_id": 8}])
        geometry = copy.deepcopy(self.geometry)
        geometry["geometry_mm"]["accelerator_focus_z"] = 60
        with self.assertRaises(ContractError):
            self.derive(geometry=geometry)
        for minimum in (0, -1, math.inf):
            with self.subTest(minimum=minimum), self.assertRaises(ContractError):
                self.derive(minimum=minimum)


if __name__ == "__main__":
    unittest.main()
