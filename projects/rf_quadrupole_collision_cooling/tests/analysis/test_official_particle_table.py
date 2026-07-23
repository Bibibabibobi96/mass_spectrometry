from __future__ import annotations

import unittest

import numpy as np

from projects.rf_quadrupole_collision_cooling.analysis.generate_official_particle_table import generate


class OfficialParticleTableTests(unittest.TestCase):
    def test_n100_is_n1000_prefix(self) -> None:
        self.assertTrue(np.array_equal(generate(100), generate(1000)[:100]))

    def test_nonstandard_count_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be one of"):
            generate(25)


if __name__ == "__main__":
    unittest.main()
