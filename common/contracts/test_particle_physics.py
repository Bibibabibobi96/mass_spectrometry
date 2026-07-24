"""Regression tests for shared particle-physics constants."""

from __future__ import annotations

import unittest

from common.contracts.particle_physics import (
    ELECTRON_MASS_KG,
    ELECTRON_MASS_U,
    ELEMENTARY_CHARGE_C,
)


class ParticlePhysicsConstantTests(unittest.TestCase):
    """Freeze the NIST 2022 CODATA electron constants."""

    def test_electron_constants_match_nist_2022_codata(self) -> None:
        self.assertEqual(ELECTRON_MASS_KG, 9.1093837139e-31)
        self.assertEqual(ELECTRON_MASS_U, 5.485799090441e-4)
        self.assertEqual(ELEMENTARY_CHARGE_C, 1.602176634e-19)


if __name__ == "__main__":
    unittest.main()
