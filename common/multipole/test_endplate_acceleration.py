import unittest

from common.multipole.endplate_acceleration import resolve_endplate_acceleration


class EndplateAccelerationTest(unittest.TestCase):
    def test_positive_ion_gains_three_ev(self):
        contract = {
            "schema_version": 1,
            "role": "multipole_endplate_acceleration_contract",
            "project_id": "example",
            "model_id": "multipole.endplate_potential_step.v1",
            "rod_common_mode_V": 0.0,
            "entrance_plate_V": 0.0,
            "exit_plate_V": -3.0,
            "output_reference_V": -3.0,
            "functional_acceptance": {
                "minimum_transmission": 0.8,
                "minimum_mean_energy_gain_eV": 2.5,
                "maximum_mean_output_energy_error_eV": 0.5,
            },
            "claim_limit": "functional only",
        }
        resolved = resolve_endplate_acceleration(contract, source_kinetic_energy_ev=2.0, charge_state=1)
        self.assertEqual(resolved["derived"]["predicted_output_energy_eV"], 5.0)


if __name__ == "__main__":
    unittest.main()
