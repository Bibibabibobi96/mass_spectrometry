from __future__ import annotations

import json
import math
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from common.contracts.particle_state import canonical_sources, ion11_sources
from projects.rf_quadrupole_collision_cooling.analysis.generate_interface_particle_table import (
    generate_bundle,
    validate_bundle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
GENERATOR = PROJECT_ROOT / "analysis" / "generate_interface_particle_table.py"
SOURCE_FAMILY = PROJECT_ROOT / "config" / "interface_readiness_particle_source.json"
DISTRIBUTION = PROJECT_ROOT / "config" / "official_particle_source.json"
RESOLVED = PROJECT_ROOT / "config" / "resolved_design_official.json"


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
                command = [sys.executable, "-m", "projects.rf_quadrupole_collision_cooling.analysis.generate_interface_particle_table", "--source-family", str(family_path),
                           "--distribution", str(distribution_path), "--operating-point", point,
                           "--particles", "100", "--seed", "77", "--output", str(output),
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

    def test_n100_is_prefix_of_n1000(self) -> None:
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
                    "reference": {"mass_amu": 100, "charge_state": 1,
                                  "kinetic_energy_eV": {"distribution": "fixed", "value": 2.0}},
                },
            }
            distribution_path = root / "distribution.json"
            family_path = root / "family.json"
            distribution_path.write_text(json.dumps(distribution), encoding="utf-8")
            family_path.write_text(json.dumps(family), encoding="utf-8")
            tables = {}
            for count in (100, 1000):
                output = root / f"n{count}.ion"
                subprocess.run(
                    [sys.executable, "-m", "projects.rf_quadrupole_collision_cooling.analysis.generate_interface_particle_table", "--source-family", str(family_path),
                     "--distribution", str(distribution_path), "--operating-point", "reference",
                     "--particles", str(count), "--output", str(output),
                     "--metadata", str(root / f"n{count}.json")],
                    check=True, capture_output=True, text=True, cwd=REPOSITORY_ROOT, timeout=60,
                )
                tables[count] = np.loadtxt(output, delimiter=",")
            self.assertTrue(np.array_equal(tables[100], tables[1000][:100]))

    def test_legacy_cli_preserves_official_n100_bytes_and_reports_actual_count(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            output = root / "official.ion"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "projects.rf_quadrupole_collision_cooling.analysis.generate_interface_particle_table",
                    "--source-family",
                    str(SOURCE_FAMILY),
                    "--distribution",
                    str(DISTRIBUTION),
                    "--operating-point",
                    "official_100amu_2eV",
                    "--particles",
                    "100",
                    "--output",
                    str(output),
                    "--metadata",
                    str(root / "metadata.json"),
                ],
                check=True,
                capture_output=True,
                text=True,
                cwd=REPOSITORY_ROOT,
                timeout=60,
            )
            official = PROJECT_ROOT / "config" / "particles" / "official_fixed_100.ion"
            self.assertEqual(output.read_bytes(), official.read_bytes())
            self.assertIn("PARTICLES=100 ", result.stdout)

    def test_paired_bundle_freezes_prefixes_mapping_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            metadata = generate_bundle(SOURCE_FAMILY, DISTRIBUTION, RESOLVED, root)
            metadata_path = root / "paired_particle_bundle.json"
            self.assertEqual(validate_bundle(metadata_path, SOURCE_FAMILY, DISTRIBUTION, RESOLVED), metadata)
            self.assertEqual(len(metadata["artifacts"]), 8)
            self.assertEqual(
                metadata["operating_point_ids"],
                ["official_100amu_2eV", "rf_to_oatof_100amu_5eV"],
            )
            for point_id in metadata["operating_point_ids"]:
                ion_path = root / f"{point_id}_n100.ion"
                canonical_path = root / f"{point_id}_n100_canonical.csv"
                self.assertNotIn(b"\r", ion_path.read_bytes())
                self.assertNotIn(b"\r", canonical_path.read_bytes())
                ion = ion11_sources(ion_path)
                canonical = canonical_sources(canonical_path)
                self.assertEqual(set(ion), set(canonical))
                for particle_id in ion:
                    for field in (
                        "axial_z_mm",
                        "transverse_x_mm",
                        "transverse_y_mm",
                        "velocity_axial_m_s",
                        "velocity_x_m_s",
                        "velocity_y_m_s",
                    ):
                        self.assertTrue(
                            math.isclose(
                                ion[particle_id][field],
                                canonical[particle_id][field],
                                rel_tol=0.0,
                                abs_tol=1e-5,
                            ),
                            f"{point_id} particle {particle_id} {field}",
                        )
            control = np.loadtxt(
                root / "official_100amu_2eV_n100.ion", delimiter=","
            )
            candidate = np.loadtxt(
                root / "rf_to_oatof_100amu_5eV_n100.ion", delimiter=","
            )
            self.assertTrue(np.array_equal(control[:, :8], candidate[:, :8]))
            self.assertTrue(np.array_equal(control[:, 9:], candidate[:, 9:]))
            self.assertFalse(np.array_equal(control[:, 8], candidate[:, 8]))

    def test_bundle_validator_rejects_artifact_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            generate_bundle(SOURCE_FAMILY, DISTRIBUTION, RESOLVED, root)
            source = root / "official_100amu_2eV_n100.ion"
            source.write_bytes(source.read_bytes() + b"1,2,3\n")
            metadata_path = root / "paired_particle_bundle.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            for artifact in metadata["artifacts"]:
                if artifact["relative_path"] == source.name:
                    artifact["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest().upper()
            metadata_path.write_text(
                json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(
                ValueError, "prefix source validation|frozen latent family"
            ):
                validate_bundle(
                    metadata_path,
                    SOURCE_FAMILY,
                    DISTRIBUTION,
                    RESOLVED,
                )

    def test_bundle_cli_rejects_mixed_branch_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "projects.rf_quadrupole_collision_cooling.analysis.generate_interface_particle_table",
                    "--source-family",
                    str(SOURCE_FAMILY),
                    "--distribution",
                    str(DISTRIBUTION),
                    "--resolved-design",
                    str(RESOLVED),
                    "--bundle-output-dir",
                    root_text,
                    "--particles",
                    "100",
                ],
                check=False,
                capture_output=True,
                text=True,
                cwd=REPOSITORY_ROOT,
                timeout=60,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("legacy-only arguments", result.stderr)


if __name__ == "__main__":
    unittest.main()
