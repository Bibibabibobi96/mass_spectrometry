from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from projects.oa_tof.analysis.generate_ion_source import (
    DotNetFrameworkRandom,
    _serialized_ion_source,
    generate_ion_source,
    validate_ion_source,
)


class GenerateIonSourceTest(unittest.TestCase):
    def source_arguments(self) -> dict[str, object]:
        return {
            "particle_count": 1000,
            "mass_amu": 524.0,
            "charge": 1,
            "energy_mean_ev": 5.0,
            "energy_std_ev": 0.4,
            "half_width_xyz_mm": (0.5, 0.5, 0.5),
            "center_xyz_mm": (-48.8, 0.0, -18.4),
            "seed": 20260713,
        }

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

    def test_existing_n1000_requires_exact_deterministic_rebuild(self) -> None:
        arguments = self.source_arguments()
        lines = generate_ion_source(**arguments)  # type: ignore[arg-type]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "parent.ion"
            source.write_bytes(_serialized_ion_source(lines))
            report = validate_ion_source(
                source_path=source, **arguments  # type: ignore[arg-type]
            )
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["particle_count"], 1000)

    def test_rebuild_rejects_seed_mass_geometry_and_energy_drift(self) -> None:
        arguments = self.source_arguments()
        lines = generate_ion_source(**arguments)  # type: ignore[arg-type]
        mutations = {
            "seed": 20260714,
            "mass_amu": 525.0,
            "center_xyz_mm": (-48.7, 0.0, -18.4),
            "half_width_xyz_mm": (0.4, 0.5, 0.5),
            "energy_mean_ev": 5.1,
            "energy_std_ev": 0.3,
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "parent.ion"
            source.write_bytes(_serialized_ion_source(lines))
            for field, value in mutations.items():
                with self.subTest(field=field):
                    changed = dict(arguments)
                    changed[field] = value
                    with self.assertRaisesRegex(ValueError, "deterministic source"):
                        validate_ion_source(
                            source_path=source, **changed  # type: ignore[arg-type]
                        )


if __name__ == "__main__":
    unittest.main()
