from __future__ import annotations

import unittest
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_exit_energy_calibration import (
    derive_unity_response_correction,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


class AcceleratorExitEnergyCalibrationTests(unittest.TestCase):
    @staticmethod
    def _observation() -> dict:
        return {
            "schema_version": 1,
            "role": "mrtof_accelerator_exit_observation",
            "status": "observed",
            "coordinate_frame": "project",
            "safe_exit_state": {
                "position_mm": [0.0, -52.0, -5.0],
                "charge_state": 1,
            },
            "recorded_kinetic_energy_components_ev": {"z": 4198.0},
        }

    def test_derives_cumulative_command_correction_without_changing_target(self) -> None:
        with patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "accelerator_exit_energy_calibration.axial_potential_v",
            return_value=-0.25,
        ):
            result = derive_unity_response_correction(
                self._observation(), mirror_design=object(),
                target_axial_energy_per_charge_v=4199.0,
                previous_cumulative_correction_v=0.5,
            )
        self.assertEqual(result["measured_axial_hamiltonian_per_charge_v"], 4197.75)
        self.assertEqual(result["measured_minus_target_axial_energy_v"], -1.25)
        self.assertEqual(result["correction_increment_v"], 1.25)
        self.assertEqual(result["proposed_cumulative_correction_v"], 1.75)
        self.assertEqual(result["target_axial_energy_per_charge_v"], 4199.0)
        self.assertIn("real_simion_exit_required", result["qualification"])

    def test_rejects_invalid_identity_charge_and_energy(self) -> None:
        invalid = self._observation()
        invalid["role"] = "other"
        with self.assertRaisesRegex(CandidateContractError, "identity"):
            derive_unity_response_correction(
                invalid, mirror_design=object(), target_axial_energy_per_charge_v=4199.0,
            )
        invalid = self._observation()
        invalid["safe_exit_state"]["charge_state"] = 0
        with self.assertRaisesRegex(CandidateContractError, "nonzero integer"):
            derive_unity_response_correction(
                invalid, mirror_design=object(), target_axial_energy_per_charge_v=4199.0,
            )


if __name__ == "__main__":
    unittest.main()
