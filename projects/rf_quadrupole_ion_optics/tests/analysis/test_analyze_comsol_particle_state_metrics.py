from __future__ import annotations

import unittest

from projects.rf_quadrupole_ion_optics.analysis.analyze_comsol_particle_state_metrics import derive


class ComsolParticleStateMetricsTests(unittest.TestCase):
    def test_derives_transmission_rms_and_energy_from_terminal_state(self) -> None:
        rows = [
            {"particle_id": "1", "event": "source", "status": "alive", "radial_position_mm": "0", "kinetic_energy_eV": "2"},
            {"particle_id": "2", "event": "source", "status": "alive", "radial_position_mm": "0", "kinetic_energy_eV": "2"},
            {"particle_id": "1", "event": "terminal", "status": "transmitted", "radial_position_mm": "3", "kinetic_energy_eV": "5"},
            {"particle_id": "2", "event": "terminal", "status": "transmitted", "radial_position_mm": "4", "kinetic_energy_eV": "7"},
        ]
        result = derive({"role": "rf_quadrupole_comsol_raw_solver_metadata", "solver": "COMSOL"}, rows)
        self.assertEqual(result["metrics_authority"], "python_canonical_particle_state")
        self.assertEqual(result["transmission"], 1.0)
        self.assertEqual(result["exit_rms_radius_mm"], (12.5) ** 0.5)
        self.assertEqual(result["mean_output_energy_eV"], 6.0)
        self.assertAlmostEqual(result["output_energy_standard_deviation_eV"], 2**0.5)

    def test_rejects_terminal_rows_that_do_not_close_source_cohort(self) -> None:
        rows = [{"particle_id": "1", "event": "source", "status": "alive", "radial_position_mm": "0", "kinetic_energy_eV": "2"}]
        with self.assertRaisesRegex(ValueError, "do not close"):
            derive({"role": "rf_quadrupole_comsol_raw_solver_metadata"}, rows)


if __name__ == "__main__":
    unittest.main()
