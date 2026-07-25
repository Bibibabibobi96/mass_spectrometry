from __future__ import annotations

import json
import math
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from common.contracts.particle_state import canonical_sources, ion11_sources
from projects.rf_quadrupole_collision_cooling.analysis.paired_particle_source_bundle import (
    generate_bundle as generate_neutral_bundle,
    generate_single_table,
)
from projects.rf_quadrupole_collision_cooling.workflows.interface_readiness.particle_source_policy import (
    BUNDLE_ROLE,
    BUNDLE_VERSION,
    POINT_IDS,
    generate_interface_bundle as generate_bundle,
    load_interface_point_specs,
    validate_interface_bundle as validate_bundle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
GENERATOR = (
    PROJECT_ROOT / "workflows" / "interface_readiness" / "generate_particle_table.py"
)
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
                generate_single_table(
                    family_path,
                    distribution_path,
                    point,
                    100,
                    output,
                    root / f"{point}.json",
                    seed=77,
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
                generate_single_table(
                    family_path,
                    distribution_path,
                    "reference",
                    count,
                    output,
                    root / f"n{count}.json",
                )
                tables[count] = np.loadtxt(output, delimiter=",")
            self.assertTrue(np.array_equal(tables[100], tables[1000][:100]))

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
            official = PROJECT_ROOT / "config" / "particles" / "official_fixed_100.ion"
            self.assertTrue(
                np.array_equal(
                    np.loadtxt(
                        root / "official_100amu_2eV_n100.ion",
                        delimiter=",",
                    ),
                    np.loadtxt(official, delimiter=","),
                )
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
                    "projects.rf_quadrupole_collision_cooling.workflows.interface_readiness.generate_particle_table",
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
            self.assertIn("unrecognized arguments: --particles 100", result.stderr)

    def test_bundle_cli_generates_and_validates_current_contract(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            common = [
                sys.executable,
                "-m",
                "projects.rf_quadrupole_collision_cooling.workflows."
                "interface_readiness.generate_particle_table",
                "--source-family",
                str(SOURCE_FAMILY),
                "--distribution",
                str(DISTRIBUTION),
                "--resolved-design",
                str(RESOLVED),
            ]
            generated = subprocess.run(
                common + ["--bundle-output-dir", str(root)],
                check=True,
                capture_output=True,
                text=True,
                cwd=REPOSITORY_ROOT,
                timeout=60,
            )
            validated = subprocess.run(
                common + ["--validate-bundle", str(root / "paired_particle_bundle.json")],
                check=True,
                capture_output=True,
                text=True,
                cwd=REPOSITORY_ROOT,
                timeout=60,
            )
            self.assertIn("PARTICLES=1000", generated.stdout)
            self.assertIn("BUNDLE_VALIDATION=true", validated.stdout)

    def test_frozen_package_tree_validates_current_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            bundle = root / "bundle"
            generate_bundle(SOURCE_FAMILY, DISTRIBUTION, RESOLVED, bundle)
            code_root = root / "code"
            frozen_project = (
                code_root / "projects" / "rf_quadrupole_collision_cooling"
            )
            copies = (
                (
                    PROJECT_ROOT / "workflows" / "__init__.py",
                    frozen_project / "workflows" / "__init__.py",
                ),
                (
                    PROJECT_ROOT / "workflows" / "interface_readiness" / "__init__.py",
                    frozen_project / "workflows" / "interface_readiness" / "__init__.py",
                ),
                (
                    GENERATOR,
                    frozen_project
                    / "workflows"
                    / "interface_readiness"
                    / "generate_particle_table.py",
                ),
                (
                    PROJECT_ROOT
                    / "workflows"
                    / "interface_readiness"
                    / "particle_source_policy.py",
                    frozen_project
                    / "workflows"
                    / "interface_readiness"
                    / "particle_source_policy.py",
                ),
                (
                    PROJECT_ROOT / "analysis" / "paired_particle_source_bundle.py",
                    frozen_project / "analysis" / "paired_particle_source_bundle.py",
                ),
                (
                    REPOSITORY_ROOT / "common" / "contracts" / "particle_physics.py",
                    code_root / "common" / "contracts" / "particle_physics.py",
                ),
                (
                    REPOSITORY_ROOT
                    / "common"
                    / "contracts"
                    / "particle_count_policy.py",
                    code_root / "common" / "contracts" / "particle_count_policy.py",
                ),
                (
                    REPOSITORY_ROOT
                    / "common"
                    / "contracts"
                    / "particle_count_policy.json",
                    code_root / "common" / "contracts" / "particle_count_policy.json",
                ),
                (
                    REPOSITORY_ROOT / "common" / "multipole" / "__init__.py",
                    code_root / "common" / "multipole" / "__init__.py",
                ),
                (
                    REPOSITORY_ROOT
                    / "common"
                    / "multipole"
                    / "particle_source_preflight.py",
                    code_root
                    / "common"
                    / "multipole"
                    / "particle_source_preflight.py",
                ),
            )
            for source, destination in copies:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(code_root)
            environment["PYTHONNOUSERSITE"] = "1"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "projects.rf_quadrupole_collision_cooling.workflows."
                    "interface_readiness.generate_particle_table",
                    "--source-family",
                    str(SOURCE_FAMILY),
                    "--distribution",
                    str(DISTRIBUTION),
                    "--resolved-design",
                    str(RESOLVED),
                    "--validate-bundle",
                    str(bundle / "paired_particle_bundle.json"),
                ],
                check=True,
                capture_output=True,
                text=True,
                cwd=code_root,
                env=environment,
                timeout=60,
            )
            self.assertIn("BUNDLE_VALIDATION=true", result.stdout)

    def test_interface_policy_rejects_missing_extra_and_changed_energy_points(
        self,
    ) -> None:
        family = json.loads(SOURCE_FAMILY.read_text(encoding="utf-8"))
        mutations = []
        missing = json.loads(json.dumps(family))
        missing["operating_points"].pop(POINT_IDS[1])
        mutations.append(missing)
        wrong_mass = json.loads(json.dumps(family))
        wrong_mass["operating_points"][POINT_IDS[0]]["mass_amu"] = 99
        mutations.append(wrong_mass)
        changed = json.loads(json.dumps(family))
        changed["operating_points"][POINT_IDS[1]]["kinetic_energy_eV"]["value"] = 4.9
        mutations.append(changed)
        with tempfile.TemporaryDirectory() as root_text:
            root = Path(root_text)
            for index, document in enumerate(mutations):
                path = root / f"family_{index}.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "interface"):
                    load_interface_point_specs(path)

    def test_neutral_bundle_requires_explicit_unique_specification(self) -> None:
        specs = load_interface_point_specs(SOURCE_FAMILY)
        with tempfile.TemporaryDirectory() as root_text:
            with self.assertRaisesRegex(ValueError, "duplicated"):
                generate_neutral_bundle(
                    SOURCE_FAMILY,
                    DISTRIBUTION,
                    RESOLVED,
                    Path(root_text),
                    point_ids=(POINT_IDS[0], POINT_IDS[0]),
                    point_specs={POINT_IDS[0]: specs[POINT_IDS[0]]},
                    bundle_role=BUNDLE_ROLE,
                    bundle_version=BUNDLE_VERSION,
                )


if __name__ == "__main__":
    unittest.main()
