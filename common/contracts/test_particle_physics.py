"""Regression tests for shared particle-physics constants."""

from __future__ import annotations

import unittest

from common.contracts.particle_physics import (
    AMU_KG,
    ELECTRON_MASS_KG,
    ELECTRON_MASS_U,
    ELEMENTARY_CHARGE_C,
    LEGACY_OA_TOF_ATOMIC_MASS_CONSTANT_KG,
    charge_to_mass_c_per_kg,
    kinetic_energy_ev_from_speed_m_s,
    mass_to_charge_kg_per_c,
    speed_m_s_from_kinetic_energy_ev,
    thomson_to_kg_per_c,
)


class ParticlePhysicsConstantTests(unittest.TestCase):
    """Freeze the NIST 2022 CODATA electron constants."""

    def test_electron_constants_match_nist_2022_codata(self) -> None:
        self.assertEqual(ELECTRON_MASS_KG, 9.1093837139e-31)
        self.assertEqual(ELECTRON_MASS_U, 5.485799090441e-4)
        self.assertEqual(ELEMENTARY_CHARGE_C, 1.602176634e-19)

    def test_energy_speed_round_trip_uses_mass_in_unified_atomic_mass_units(self) -> None:
        speed = speed_m_s_from_kinetic_energy_ev(100.0, 4005.0)
        self.assertGreater(speed, 0.0)
        self.assertAlmostEqual(
            kinetic_energy_ev_from_speed_m_s(100.0, speed), 4005.0, places=12,
        )

    def test_charge_to_mass_preserves_charge_sign_and_inverse_magnitude(self) -> None:
        positive = charge_to_mass_c_per_kg(100.0, 2)
        negative = charge_to_mass_c_per_kg(100.0, -2)
        self.assertEqual(negative, -positive)
        self.assertAlmostEqual(mass_to_charge_kg_per_c(100.0, -2), 1.0 / positive)

    def test_thomson_conversion_uses_the_common_mass_and_charge_authority(self) -> None:
        self.assertEqual(
            thomson_to_kg_per_c(100.0),
            100.0 * AMU_KG / ELEMENTARY_CHARGE_C,
        )
        self.assertEqual(
            thomson_to_kg_per_c(
                100.0,
                atomic_mass_constant_kg=LEGACY_OA_TOF_ATOMIC_MASS_CONSTANT_KG,
            ),
            100.0 * LEGACY_OA_TOF_ATOMIC_MASS_CONSTANT_KG / ELEMENTARY_CHARGE_C,
        )

    def test_new_conversions_reject_invalid_physical_domains(self) -> None:
        for callback in (
            lambda: speed_m_s_from_kinetic_energy_ev(0.0, 1.0),
            lambda: speed_m_s_from_kinetic_energy_ev(1.0, -1.0),
            lambda: kinetic_energy_ev_from_speed_m_s(1.0, -1.0),
            lambda: charge_to_mass_c_per_kg(1.0, 0),
            lambda: mass_to_charge_kg_per_c(1.0, True),
            lambda: thomson_to_kg_per_c(0.0),
        ):
            with self.assertRaises(ValueError):
                callback()


if __name__ == "__main__":
    unittest.main()
