from __future__ import annotations

import unittest

from projects.oa_tof.analysis.generate_ion_source import (
    DotNetFrameworkRandom,
    generate_ion_source,
)


class GenerateIonSourceTest(unittest.TestCase):
    def test_dotnet_random_known_seed_sequence(self) -> None:
        random = DotNetFrameworkRandom(1)

        self.assertAlmostEqual(random.next_double(), 0.24866858415709278)
        self.assertAlmostEqual(random.next_double(), 0.11074397718102856)

    def test_n100_is_exact_prefix_of_n1000(self) -> None:
        arguments = {
            "mass_amu": 524.0,
            "charge": 1,
            "energy_mean_ev": 5.0,
            "energy_std_ev": 0.4,
            "half_width_xyz_mm": (0.5, 0.5, 0.5),
            "center_xyz_mm": (-48.8, 0.0, -18.4),
            "seed": 20260713,
        }

        n100 = generate_ion_source(particle_count=100, **arguments)
        n1000 = generate_ion_source(particle_count=1000, **arguments)

        self.assertEqual(n100, n1000[:100])
        self.assertIn("5.24000000E+002", n100[0])


if __name__ == "__main__":
    unittest.main()
