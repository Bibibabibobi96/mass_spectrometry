from __future__ import annotations

import json
import unittest
from pathlib import Path

from projects.rf_quadrupole_collision_cooling.analysis import run_mass_filter_l1 as MODULE

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
        particles = MODULE.generate_particles(self.source, 64, 20260722)
        transmissions = {}
        for mass in (96.0, 101.5, 106.0):
            result = MODULE.simulate_mass(mass, particles, self.resolved, 80)
            transmissions[mass] = result["transmission_fraction"]
        self.assertGreaterEqual(transmissions[101.5], 0.9)
        self.assertLessEqual(transmissions[96.0], 0.1)
        self.assertLessEqual(transmissions[106.0], 0.1)


if __name__ == "__main__":
    unittest.main()
