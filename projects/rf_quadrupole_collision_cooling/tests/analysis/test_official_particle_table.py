from __future__ import annotations

import unittest
import json
from pathlib import Path

import numpy as np

from common.contracts.particle_physics import kinetic_energy_ev
from projects.rf_quadrupole_collision_cooling.analysis.generate_official_particle_table import (
    generate,
    generate_canonical,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class OfficialParticleTableTests(unittest.TestCase):
    def test_n100_is_n1000_prefix(self) -> None:
        self.assertTrue(np.array_equal(generate(100), generate(1000)[:100]))

    def test_nonstandard_count_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be one of"):
            generate(25)

    def test_canonical_projection_uses_governed_release_plane_and_same_energy(self) -> None:
        resolved = json.loads(
            (PROJECT_ROOT / "config/resolved_design_official.json").read_text()
        )
        rows = generate_canonical(100, resolved)
        release = resolved["interfaces_mm"]["entrance"]["release_plane_z_mm"]
        self.assertEqual({float(row["z_mm"]) for row in rows}, {release})
        ion = generate(100)
        for source, row in zip(ion, rows, strict=True):
            self.assertAlmostEqual(
                kinetic_energy_ev(
                    float(row["mass_amu"]),
                    float(row["vx_m_s"]),
                    float(row["vy_m_s"]),
                    float(row["vz_m_s"]),
                ),
                source[8],
                places=10,
            )


if __name__ == "__main__":
    unittest.main()
