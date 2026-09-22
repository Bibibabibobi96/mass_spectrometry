from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np

from common.ion_release.numpy_box_cone import sample_numpy_box_cone_phase_space
from projects.rf_quadrupole_ion_optics.workflows.mass_filter_reference import (
    run_finite_length as MODULE,
)

PROJECT_ROOT = Path(__file__).parents[2]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class MassFilterL1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = load_json(PROJECT_ROOT / "config" / "baseline.json")
        cls.resolved = load_json(PROJECT_ROOT / "config" / "resolved_design_mass_filter.json")
        cls.mode = load_json(PROJECT_ROOT / "config" / "modes" / "mass_filter_reference.json")
        cls.source = load_json(PROJECT_ROOT / "config" / "official_particle_source.json")

    def test_contract_brackets_theory_passband(self) -> None:
        derived = MODULE.validate_l1_contract(self.baseline, self.mode, self.source)
        self.assertAlmostEqual(derived["theory_low_mass_Th"], 99.3275, delta=0.001)
        self.assertAlmostEqual(derived["theory_high_mass_Th"], 103.4120, delta=0.001)
        self.assertAlmostEqual(derived["calibration_mass_Th"], 101.3707, delta=0.001)

    def test_finite_length_screen_transmits_tuned_and_rejects_outer_masses(self) -> None:
        particles = MODULE._l1_particles_from_release(self.source, 64, 20260722)
        transmissions = {}
        for mass in (96.0, 101.5, 106.0):
            result = MODULE.simulate_mass(mass, particles, self.resolved, 80)
            transmissions[mass] = result["transmission_fraction"]
        self.assertGreaterEqual(transmissions[101.5], 0.9)
        self.assertLessEqual(transmissions[96.0], 0.1)
        self.assertLessEqual(transmissions[106.0], 0.1)

    def test_l1_projection_preserves_common_box_cone_release(self) -> None:
        release = sample_numpy_box_cone_phase_space(
            source=self.source, seed=20260722, particle_count=64,
        )
        particles = MODULE._l1_particles_from_release(self.source, 64, 20260722)
        self.assertTrue(np.array_equal(particles["x_m"], release["transverse_1_mm"] * 1e-3))
        self.assertTrue(np.array_equal(particles["y_m"], release["transverse_2_mm"] * 1e-3))
        self.assertTrue(np.array_equal(particles["energy_j"], release["energy_eV"] * MODULE.electron_volt))
        self.assertTrue(np.array_equal(particles["direction_x"], release["direction_transverse_1"]))
        self.assertTrue(np.array_equal(particles["direction_y"], release["direction_transverse_2"]))
        self.assertTrue(np.array_equal(particles["direction_z"], release["direction_axial"]))
        self.assertTrue(np.array_equal(particles["rf_phase_rad"], release["phase_rad"]))


if __name__ == "__main__":
    unittest.main()
