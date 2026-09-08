from __future__ import annotations

import copy
import unittest
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prism_l0 import PrismL0Error, derive_first_prism_l0
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import load_contract


PROJECT = Path(__file__).resolve().parents[2]


class FirstPrismL0Test(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_contract(PROJECT / "config" / "simion_candidate_two_zone.json")

    def test_derives_total_energy_partition_triangle_crossings_and_static_seed(self) -> None:
        result = derive_first_prism_l0(self.contract)
        self.assertEqual(result.total_kinetic_energy_ev, 4005.0)
        self.assertEqual(result.drift_kinetic_energy_ev, 5.0)
        self.assertEqual(result.fast_kinetic_energy_ev, 4000.0)
        self.assertAlmostEqual(result.drift_angle_degrees, 2.0248682972773406)
        self.assertEqual(result.entry_position_project_mm, (0.0, 55.328, 0.0))
        self.assertEqual(result.entry_unit_direction_project, (0.0, 0.0, -1.0))
        self.assertAlmostEqual(result.target_unit_direction_project[1], -(5.0 / 4005.0) ** 0.5)
        self.assertAlmostEqual(result.target_unit_direction_project[2], -(4000.0 / 4005.0) ** 0.5)
        self.assertEqual(result.triangle_entry_project_mm, (0.0, 55.328, -52.5))
        self.assertEqual(result.triangle_exit_project_mm, (0.0, 55.328, -77.5))
        self.assertEqual(result.target_plane_z_mm, -101.0)
        self.assertEqual(result.target_plane_x_mm, 0.0)
        self.assertEqual(result.target_plane_y_acceptance_mm, (35.0, 75.0))
        self.assertAlmostEqual(result.hard_boundary_seed_voltage_v, 20000.0**0.5)
        self.assertEqual(result.second_prism_status, "pre_stripe_injection_pending")

    def test_rejects_energy_semantics_angle_convention_and_second_prism_premature_solution(self) -> None:
        for mutate in (
            lambda contract: contract["prism_transport"]["energy_partition"].__setitem__("semantics", "axial_energy"),
            lambda contract: contract["prism_transport"]["energy_partition"].__setitem__("total_kinetic_energy_ev", 4000),
            lambda contract: contract["prism_transport"]["first_prism"].__setitem__("local_angle_convention", "unspecified"),
            lambda contract: contract["prism_transport"]["second_prism"].__setitem__("voltage_v", 1.0),
        ):
            with self.subTest(mutate=mutate):
                contract = copy.deepcopy(self.contract)
                mutate(contract)
                with self.assertRaises(PrismL0Error):
                    derive_first_prism_l0(contract)

    def test_contract_energy_and_target_plane_are_derived_not_code_constants(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["prism_transport"]["energy_partition"]["total_kinetic_energy_ev"] = 4006
        contract["prism_transport"]["energy_partition"]["drift_kinetic_energy_ev"] = 6
        contract["prism_transport"]["energy_partition"]["fast_reflection_kinetic_energy_ev"] = 4000
        contract["prism_transport"]["first_prism"]["target_interface"]["coordinate_mm"] = -100.5
        result = derive_first_prism_l0(contract)
        self.assertEqual(result.total_kinetic_energy_ev, 4006.0)
        self.assertEqual(result.drift_kinetic_energy_ev, 6.0)
        self.assertEqual(result.fast_kinetic_energy_ev, 4000.0)
        self.assertEqual(result.target_plane_z_mm, -100.5)
        self.assertAlmostEqual(
            result.hard_boundary_seed_voltage_v,
            (6.0 * 4000.0) ** 0.5,
        )

    def test_rejects_wrong_station_ray_plane_and_slot_contract(self) -> None:
        for mutate in (
            lambda contract: contract["prism_transport"]["first_prism"]["entry_reference"].__setitem__("direction_project", [0, 1, 0]),
            lambda contract: contract["prism_transport"]["first_prism"]["entry_reference"]["position_project_mm"].__setitem__(1, 55.0),
            lambda contract: contract["prism_transport"]["first_prism"]["target_interface"].__setitem__("coordinate_mm", -100),
            lambda contract: contract["prism_transport"]["first_prism"]["target_interface"].__setitem__("ground_shield_id", 20),
            lambda contract: contract["prisms"]["ground_shields"][0]["rectangular_slots_mm"][0].__setitem__("box", [3, 35, -100, 4, 75, -30]),
        ):
            with self.subTest(mutate=mutate):
                contract = copy.deepcopy(self.contract)
                mutate(contract)
                with self.assertRaises(PrismL0Error):
                    derive_first_prism_l0(contract)


if __name__ == "__main__":
    unittest.main()
