from __future__ import annotations

import unittest

from common.simion.particle_source import render_source_states, render_standard_beams


class StandardBeamTests(unittest.TestCase):
    def test_source_state_precision_default_is_legacy_and_17_roundtrips(self) -> None:
        value = 1.2345678901234567
        state = dict(particle_id=7, t=value, x=value, y=value, z=value, vx=value, vy=value, vz=value, ke=value)
        legacy = render_source_states([state])
        self.assertEqual(legacy, "return {\n  [7]={t=1.23456789012346,x=1.23456789012346,y=1.23456789012346,z=1.23456789012346,vx=1.23456789012346,vy=1.23456789012346,vz=1.23456789012346,ke=1.23456789012346},\n}\n")
        precise = render_source_states([state], significant_digits=17)
        self.assertIn(f"x={value!r}", precise)

    def test_source_state_precision_rejects_unsupported_values(self) -> None:
        for value in (True, 16, 0, "17", 17.0):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "15 or 17"):
                render_source_states([], significant_digits=value)

    def test_legacy_angles_remain_byte_stable(self) -> None:
        source = render_standard_beams(
            [{
                "tob": 0, "mass": 100, "charge": 1,
                "x": 1, "y": 2, "z": 3, "ke": 4,
                "az": 5, "el": 6, "cwf": 1, "color": 2,
            }]
        )
        self.assertIn("    x = 1,\n    y = 2,\n    z = 3,", source)
        self.assertIn("    az = 5,\n    el = 6,", source)
        self.assertNotIn("direction = vector", source)

    def test_explicit_direction_uses_simion_vector_form(self) -> None:
        source = render_standard_beams(
            [{
                "tob": 0, "mass": 500, "charge": 1,
                "x": 25.5, "y": 25.5, "z": 1,
                "direction": (0, 0, 20), "ke": 0.001,
                "cwf": 1, "color": 3,
            }]
        )
        self.assertIn("position = vector(25.5,25.5,1)", source)
        self.assertIn("direction = vector(0,0,20)", source)
        self.assertNotIn("    az =", source)

    def test_direction_must_be_three_dimensional(self) -> None:
        with self.assertRaisesRegex(ValueError, "three components"):
            render_standard_beams(
                [{
                    "tob": 0, "mass": 500, "charge": 1,
                    "x": 0, "y": 0, "z": 0, "direction": (0, 1),
                    "ke": 1, "cwf": 1, "color": 1,
                }]
            )


if __name__ == "__main__":
    unittest.main()
