from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd


from projects.rf_quadrupole_collision_cooling.analysis import compare_s1_entry_to_oatof_ideal_source as module


class S1EntryIdealComparisonTests(unittest.TestCase):
    def test_enrich_rf_applies_aperture_outcomes_and_direction_angles(self) -> None:
        entry = pd.DataFrame([
            {"particle_id": 1, "kinetic_energy_eV": 2, "velocity_x_m_s": 1000,
             "velocity_y_m_s": 0, "velocity_z_m_s": 0},
            {"particle_id": 2, "kinetic_energy_eV": 2, "velocity_x_m_s": 1000,
             "velocity_y_m_s": 100, "velocity_z_m_s": -100},
        ])
        local = pd.DataFrame([
            {"particle_id": 1, "event": "local_joint_exit"},
            {"particle_id": 2, "event": "geometric_reject"},
        ])
        result = module.enrich_rf(entry, local)
        self.assertEqual(result["inside_port"].tolist(), [True, False])
        self.assertAlmostEqual(result.iloc[0]["angle_deg"], 0.0)
        self.assertGreater(result.iloc[1]["angle_deg"], 0.0)

    def test_ideal_ion_speed_uses_mass_matched_energy(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            ion = Path(root) / "ideal.ion"
            ion.write_text("0,100,1,-48.8,0,-18.4,0,0,5,1,0\n", encoding="utf-8")
            result = module.read_ideal_ion(ion)
            self.assertEqual(result.iloc[0]["vy_m_s"], 0.0)
            self.assertEqual(result.iloc[0]["vz_m_s"], 0.0)
            self.assertGreater(result.iloc[0]["vx_m_s"], 0.0)


if __name__ == "__main__":
    unittest.main()
