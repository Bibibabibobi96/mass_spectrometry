from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
GENERATOR = PROJECT_ROOT / "analysis" / "generate_interface_particle_table.py"


class InterfaceParticleTableTests(unittest.TestCase):
    def test_fixed_and_uniform_energy_points_preserve_paired_phase_space(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            distribution = {
                "time_of_birth_us": {"min": 0.0, "max": 1.0},
                "position_mm": {"axial": 0.0, "transverse_1": {"min": -0.1, "max": 0.1},
                                "transverse_2": {"min": -0.1, "max": 0.1}},
                "direction": {"half_angle_deg": 5.0}, "cwf": 1, "color": 3,
            }
            family = {
                "paired_sampling": {"base_seed": 10},
                "operating_points": {
                    "uniform": {"mass_amu": 100, "charge_state": 1,
                                "kinetic_energy_eV": {"distribution": "uniform", "min": 1.8, "max": 2.2}},
                    "fixed": {"mass_amu": 100, "charge_state": 1,
                              "kinetic_energy_eV": {"distribution": "fixed", "value": 5.0}},
                },
            }
            distribution_path = root / "distribution.json"
            family_path = root / "family.json"
            distribution_path.write_text(json.dumps(distribution), encoding="utf-8")
            family_path.write_text(json.dumps(family), encoding="utf-8")
            tables = []
            for point in ("uniform", "fixed"):
                output = root / f"{point}.ion"
                command = [sys.executable, str(GENERATOR), "--source-family", str(family_path),
                           "--distribution", str(distribution_path), "--operating-point", point,
                           "--particles", "20", "--seed", "77", "--output", str(output),
                           "--metadata", str(root / f"{point}.json")]
                subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    cwd=REPOSITORY_ROOT,
                    timeout=60,
                )
                tables.append(np.loadtxt(output, delimiter=","))
            uniform, fixed = tables
            self.assertTrue(np.array_equal(uniform[:, :8], fixed[:, :8]))
            self.assertTrue(np.array_equal(uniform[:, 9:], fixed[:, 9:]))
            self.assertFalse(np.array_equal(uniform[:, 8], fixed[:, 8]))


if __name__ == "__main__":
    unittest.main()
