from __future__ import annotations

import hashlib
import json
import unittest

from common.contracts.particle_physics import kinetic_energy_ev
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.rf_handoff_adapter import (
    decode_simion_accelerator_velocity,
    encode_simion_accelerator_velocity,
    ordered_solver_identity_map,
    validate_ion_velocity_adapter,
)


class RfHandoffAdapterCharacterizationTests(unittest.TestCase):
    def test_velocity_projection_bytes_are_frozen(self) -> None:
        vectors = [
            (1000.0, 10.0, -20.0),
            (-4000.0, 250.0, -5.0),
            (0.0, 0.0, 0.0),
        ]
        characterized = []
        for velocity in vectors:
            azimuth, elevation = encode_simion_accelerator_velocity(velocity)
            energy = kinetic_energy_ev(100.0, *velocity)
            decoded = decode_simion_accelerator_velocity(
                100.0, energy, azimuth, elevation
            )
            characterized.append(
                {
                    "v": [format(value, ".17g") for value in velocity],
                    "a": format(azimuth, ".17g"),
                    "e": format(elevation, ".17g"),
                    "d": [format(value, ".17g") for value in decoded],
                }
            )
        canonical = json.dumps(
            characterized, sort_keys=True, separators=(",", ":")
        ).encode()
        self.assertEqual(
            hashlib.sha256(canonical).hexdigest().upper(),
            "554BF5954531D653811715132CFDAE86AB5DB0F384ADF88E69190352F905354C",
        )

    def test_identity_and_velocity_validation_behavior_is_frozen(self) -> None:
        velocity = (1000.0, 10.0, -20.0)
        energy = kinetic_energy_ev(100.0, *velocity)
        azimuth, elevation = encode_simion_accelerator_velocity(velocity)
        canonical = [
            {
                "particle_id": "11",
                "mass_amu": "100",
                "kinetic_energy_eV": format(energy, ".17g"),
                **{
                    f"velocity_{axis}_m_s": format(value, ".17g")
                    for axis, value in zip("xyz", velocity)
                },
            }
        ]
        row_map = [
            {
                "solver_row_index": "1",
                "particle_id": "11",
                "azimuth_deg": format(azimuth, ".17g"),
                "elevation_deg": format(elevation, ".17g"),
            }
        ]
        ion = [
            "0",
            "100",
            "1",
            "0",
            "0",
            "0",
            format(azimuth, ".17g"),
            format(elevation, ".17g"),
            format(energy, ".17g"),
            "1",
            "3",
        ]
        self.assertEqual(ordered_solver_identity_map(canonical, row_map), {1: 11})
        self.assertIsNone(validate_ion_velocity_adapter(canonical[0], row_map[0], ion))

        invalid_map = [{**row_map[0], "particle_id": "12"}]
        with self.assertRaisesRegex(ValueError, "canonical particle identity"):
            ordered_solver_identity_map(canonical, invalid_map)
        invalid_state = {**canonical[0], "kinetic_energy_eV": "1"}
        with self.assertRaisesRegex(ValueError, "energy and velocity"):
            validate_ion_velocity_adapter(invalid_state, row_map[0], ion)


if __name__ == "__main__":
    unittest.main()
