import tempfile
import unittest
from pathlib import Path

from common.multipole.analyze_simion_axial_acceleration import evaluate


HEADER = (
    "particle_id,event,status,terminal_reason,time_us,elapsed_time_us,rf_phase_rad,"
    "axial_z_mm,transverse_x_mm,transverse_y_mm,velocity_axial_m_s,velocity_x_m_s,"
    "velocity_y_m_s,kinetic_energy_eV,radial_position_mm,divergence_angle_deg,max_rod_radius_mm\n"
)


class AnalyzeSimionAxialAccelerationTest(unittest.TestCase):
    def test_paired_energy_gain_passes(self):
        resolved = {
            "derived": {"predicted_output_energy_eV": 5.0},
            "functional_acceptance": {
                "minimum_transmission": 0.8,
                "minimum_mean_energy_gain_eV": 2.5,
                "maximum_mean_output_energy_error_eV": 0.5,
            },
            "claim_limit": "functional only",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = root / "control.csv"
            accelerated = root / "accelerated.csv"
            source = "1,source,alive,none,0,0,0,0,0,0,1,0,0,2,0,0,0\n"
            control.write_text(HEADER + source + "1,handoff,transmitted,none,1,1,0,1,0,0,1,0,0,2.0,0,0,0\n")
            accelerated.write_text(HEADER + source + "1,handoff,transmitted,none,1,1,0,1,0,0,1,0,0,5.1,0,0,0\n")
            result = evaluate(accelerated, control, resolved)
        self.assertEqual(result["status"], "PASS")
        self.assertAlmostEqual(result["mean_energy_gain_eV"], 3.1)

    def test_simion_terminal_transmitted_event_is_a_valid_output(self):
        resolved = {
            "derived": {"predicted_output_energy_eV": 5.0},
            "functional_acceptance": {
                "minimum_transmission": 0.8,
                "minimum_mean_energy_gain_eV": 2.5,
                "maximum_mean_output_energy_error_eV": 0.5,
            },
            "claim_limit": "functional only",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = root / "control.csv"
            accelerated = root / "accelerated.csv"
            source = "1,source,alive,none,0,0,0,0,0,0,1,0,0,2,0,0,0\n"
            terminal = "1,terminal,transmitted,acceptance_detector,1,1,0,1,0,0,1,0,0"
            control.write_text(HEADER + source + terminal + ",2.0,0,0,0\n")
            accelerated.write_text(HEADER + source + terminal + ",5.0,0,0,0\n")
            result = evaluate(accelerated, control, resolved)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["paired_transmitted_particles"], 1)


if __name__ == "__main__":
    unittest.main()
