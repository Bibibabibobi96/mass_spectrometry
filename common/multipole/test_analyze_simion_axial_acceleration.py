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
    @staticmethod
    def resolved(topology: str) -> dict:
        return {
            "role": "multipole_resolved_design_do_not_edit",
            "resolved_sha256": "A" * 64,
            "identity": {"project_id": "fixture"},
            "particle_source": {
                "charge_state": 1,
                "energy_model": {
                    "kind": "monoenergetic",
                    "kinetic_energy_eV": 2.0,
                },
            },
            "axial_drive": {
                "topology": topology,
                "predicted_energy_gain_eV": 3.0,
                "predicted_output_energy_eV": 5.0,
            },
        }

    def test_segmented_pair_uses_only_common_terminal_transmitted_population(self):
        resolved = self.resolved("segmented_rod_axial_acceleration")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = root / "control.csv"
            accelerated = root / "accelerated.csv"
            source = "1,source,alive,none,0,0,0,0,0,0,1,0,0,2,0,0,0\n"
            second_source = "2,source,alive,none,0,0,0,0,0,0,1,0,0,2,0,0,0\n"
            control.write_text(
                HEADER + source + second_source
                + "1,terminal,transmitted,acceptance_detector,1,1,0,1,0,0,1,0,0,2.0,1,2,0\n"
                + "2,terminal,transmitted,acceptance_detector,1,1,0,1,0,0,1,0,0,100.0,9,9,0\n"
            )
            accelerated.write_text(
                HEADER + source + second_source
                + "1,terminal,transmitted,acceptance_detector,1,1,0,1,0,0,1,0,0,5.1,2,4,0\n"
            )
            result = evaluate(accelerated, control, resolved)
        self.assertEqual(result["status"], "UNQUALIFIED")
        self.assertAlmostEqual(result["mean_energy_gain_eV"], 3.1)
        self.assertAlmostEqual(result["paired_expected_mean_output_energy_eV"], 5.0)
        self.assertAlmostEqual(result["absolute_mean_output_energy_error_eV"], 0.1)
        self.assertAlmostEqual(result["sample_source_mean_energy_eV"], 2.0)
        self.assertAlmostEqual(result["source_model_predicted_mean_energy_eV"], 2.0)
        self.assertEqual(result["paired_transmitted_particles"], 1)
        self.assertEqual(
            result["paired_population_policy"],
            "intersection_of_transmitted_particle_ids",
        )
        self.assertAlmostEqual(result["mean_divergence_change_deg"], 2.0)
        self.assertAlmostEqual(result["rms_radial_position_change_mm"], 1.0)

    def test_handoff_transmission_cannot_mask_terminal_loss(self):
        resolved = self.resolved("segmented_rod_axial_acceleration")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = root / "control.csv"
            accelerated = root / "accelerated.csv"
            source = "1,source,alive,none,0,0,0,0,0,0,1,0,0,2,0,0,0\n"
            handoff = "1,handoff,transmitted,none,1,1,0,1,0,0,1,0,0,5,0,0,0\n"
            terminal_loss = "1,terminal,lost,electrode,2,2,0,2,0,0,1,0,0,5,0,0,0\n"
            control.write_text(HEADER + source + handoff + terminal_loss)
            accelerated.write_text(HEADER + source + handoff + terminal_loss)
            with self.assertRaisesRegex(ValueError, "no common transmitted particles"):
                evaluate(accelerated, control, resolved)

    def test_endplate_terminal_transmitted_event_is_a_valid_output(self):
        resolved = self.resolved("endplate_potential_step")
        resolved["particle_source"]["energy_model"] = {
            "kind": "bounded_distribution",
            "minimum_energy_eV": 1.8,
            "maximum_energy_eV": 2.2,
            "nominal_energy_eV": 2.0,
            "authority": "fixture.json",
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
        self.assertEqual(result["status"], "UNQUALIFIED")
        self.assertEqual(result["paired_transmitted_particles"], 1)
        self.assertEqual(result["primary_case_id"], "endplate_acceleration_rf_on")
        self.assertIsNone(result["source_model_predicted_mean_energy_eV"])

    def test_legacy_resolved_contract_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.csv"
            path.write_text(
                HEADER
                + "1,source,alive,none,0,0,0,0,0,0,1,0,0,2,0,0,0\n"
                + "1,handoff,transmitted,none,1,1,0,1,0,0,1,0,0,5,0,0,0\n"
            )
            with self.assertRaisesRegex(ValueError, "governed resolved design"):
                evaluate(path, path, {"derived": {"predicted_output_energy_eV": 5}})


if __name__ == "__main__":
    unittest.main()
