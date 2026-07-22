from __future__ import annotations

import unittest

from common.multipole.axial_acceleration import (
    AxialAccelerationError,
    resolve_axial_acceleration,
    segment_rod_array,
)


def contract() -> dict:
    return {
        "schema_version": 1,
        "role": "multipole_axial_acceleration_contract",
        "project_id": "example",
        "model_id": "multipole.segmented_rod_common_mode_staircase.v1",
        "segment_count": 4,
        "intersegment_gap_mm": 0.4,
        "entrance_common_mode_V": 0.0,
        "exit_common_mode_V": -3.0,
        "output_reference_V": -3.0,
        "functional_acceptance": {
            "minimum_transmission": 0.8,
            "minimum_mean_energy_gain_eV": 2.5,
            "maximum_mean_output_energy_error_eV": 0.5,
        },
        "claim_limit": "functional only",
    }


class AxialAccelerationTest(unittest.TestCase):
    def test_positive_ion_gains_three_ev_across_four_segments(self) -> None:
        result = resolve_axial_acceleration(
            contract(), rod_z_min_mm=0, rod_z_max_mm=79.6, source_kinetic_energy_ev=2, charge_state=1
        )
        self.assertAlmostEqual(result["derived"]["segment_length_mm"], 19.6)
        self.assertEqual(
            [segment["common_mode_V"] for segment in result["derived"]["segments"]],
            [0.0, -1.0, -2.0, -3.0],
        )
        self.assertEqual(result["derived"]["predicted_output_energy_eV"], 5.0)

    def test_segmented_array_preserves_rf_groups(self) -> None:
        resolved = resolve_axial_acceleration(
            contract(), rod_z_min_mm=0, rod_z_max_mm=79.6, source_kinetic_energy_ev=2, charge_state=1
        )
        array = {"rods": [
            {"rod_id": 1, "electrode_group": 1, "z_min_mm": 0, "z_max_mm": 79.6},
            {"rod_id": 2, "electrode_group": 2, "z_min_mm": 0, "z_max_mm": 79.6},
        ]}
        segmented = segment_rod_array(array, resolved)
        self.assertEqual(len(segmented["electrodes"]), 8)
        self.assertEqual([item["electrode_id"] for item in segmented["electrodes"]], list(range(1, 9)))
        self.assertEqual([item["electrode_group"] for item in segmented["electrodes"]], [1, 2] * 4)

    def test_output_reference_must_preserve_net_energy_gain(self) -> None:
        invalid = contract()
        invalid["output_reference_V"] = 0.0
        with self.assertRaises(AxialAccelerationError):
            resolve_axial_acceleration(
                invalid, rod_z_min_mm=0, rod_z_max_mm=79.6, source_kinetic_energy_ev=2, charge_state=1
            )


if __name__ == "__main__":
    unittest.main()
