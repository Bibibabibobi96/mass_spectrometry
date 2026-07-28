from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.particle_count_policy import (
    validate_prefix_particle_sources,
    validate_standard_particle_count,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.generate_ion_source import (
    _serialized_ion_source,
    generate_ion_source,
    validate_ion_source,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNNER = (
    PROJECT_ROOT
    / "workflows"
    / "mass_spectrum_candidate"
    / "run_mass_spectrum_candidate.ps1"
)
MODE = PROJECT_ROOT / "config" / "modes" / "mass_spectrum.json"
REPO_ROOT = PROJECT_ROOT.parents[1]


class ParticleSourcePolicyTests(unittest.TestCase):
    def test_mass_spectrum_mode_uses_only_the_named_standard_n100_tier(self) -> None:
        mode = json.loads(MODE.read_text(encoding="utf-8"))
        counts = [int(species["particle_count"]) for species in mode["species"]]
        self.assertEqual(counts, [100] * 5)
        for count in counts:
            self.assertEqual(validate_standard_particle_count(count), 100)
        with self.assertRaisesRegex(ValueError, "must be one of"):
            validate_standard_particle_count(99)

    def test_prefix_contract_accepts_exact_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            large = [f"particle-{index}" for index in range(1000)]
            n100 = root_path / "n100.ion"
            n1000 = root_path / "n1000.ion"
            n100.write_text("\n".join(large[:100]) + "\n", encoding="utf-8")
            n1000.write_text("\n".join(large) + "\n", encoding="utf-8")
            validate_prefix_particle_sources(n100, n1000)

    def test_prefix_contract_rejects_independently_changed_n100(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            large = [f"particle-{index}" for index in range(1000)]
            small = large[:100]
            small[50] = "changed"
            n100 = root_path / "n100.ion"
            n1000 = root_path / "n1000.ion"
            n100.write_text("\n".join(small) + "\n", encoding="utf-8")
            n1000.write_text("\n".join(large) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "deterministic prefix"):
                validate_prefix_particle_sources(n100, n1000)

    def test_runner_derives_n100_from_parent_and_validates_before_comsol(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("ParticleCountOverride", source)
        self.assertNotIn("effective_mode.json", source)
        self.assertIn("__n1000_parent.ion", source)
        self.assertIn("-m common.contracts.particle_count_policy", source)
        self.assertIn("--prefix-n100 $ionPath --prefix-n1000 $parentIonPath", source)
        self.assertIn("Select-Object -First $particleCount", source)
        self.assertLess(
            source.index("--prefix-n100 $ionPath"),
            source.index("common\\comsol\\run_comsol_r2025b.ps1"),
        )
        rebuild = source.index("-ValidateExisting")
        resume_branch = source.index("if ($resumeExisting)")
        prefix = source.index("--prefix-n100 $ionPath")
        self.assertLess(resume_branch, rebuild)
        self.assertLess(rebuild, prefix)
        checkpoint = source.index(
            "status = 'pending_deterministic_parent_validation'"
        )
        checkpoint_write = source.index(
            "Write-RunJson -Path $runConfigPath -Depth 12",
            checkpoint,
        )
        self.assertLess(checkpoint_write, rebuild)
        self.assertIn('["particle_source_$($species.species_id)"]', source)
        self.assertIn('["particle_source_parent_$($species.species_id)"]', source)
        self.assertIn("particle_source_provenance = @($sourceProvenance)", source)
        self.assertIn("$outputs += @($parentIonPaths)", source)
        self.assertIn("$outputs += @($sourceValidationPaths)", source)

    def test_post_prefix_parent_tampering_requires_full_rebuild_validation(self) -> None:
        arguments = {
            "particle_count": 1000,
            "mass_amu": 524.0,
            "charge": 1,
            "energy_mean_ev": 5.0,
            "energy_std_ev": 0.4,
            "half_width_xyz_mm": (0.5, 0.5, 0.5),
            "center_xyz_mm": (-48.8, 0.0, -18.4),
            "seed": 20260713,
        }
        parent_lines = generate_ion_source(**arguments)
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            parent = root_path / "n1000.ion"
            child = root_path / "n100.ion"
            parent.write_bytes(_serialized_ion_source(parent_lines))
            child.write_bytes(_serialized_ion_source(parent_lines[:100]))
            validate_prefix_particle_sources(child, parent)
            parent_lines[899] = parent_lines[899].replace(",1,0", ",2,0")
            parent.write_bytes(_serialized_ion_source(parent_lines))
            validate_prefix_particle_sources(child, parent)
            with self.assertRaisesRegex(ValueError, "deterministic source"):
                validate_ion_source(source_path=parent, **arguments)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_seed_mismatch_terminal_record_preserves_frozen_source_evidence(self) -> None:
        arguments = {
            "particle_count": 1000,
            "mass_amu": 524.0,
            "charge": 1,
            "energy_mean_ev": 5.0,
            "energy_std_ev": 0.4,
            "half_width_xyz_mm": (0.5, 0.5, 0.5),
            "center_xyz_mm": (-48.8, 0.0, -18.4),
            "seed": 20260713,
        }
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            inputs = run_dir / "inputs"
            inputs.mkdir()
            frozen_mode = inputs / "mass_spectrum.json"
            frozen_resolved = inputs / "resolved_geometry.json"
            frozen_policy = inputs / "particle_count_policy.json"
            shutil.copyfile(MODE, frozen_mode)
            shutil.copyfile(
                PROJECT_ROOT / "config" / "resolved_geometry.json",
                frozen_resolved,
            )
            shutil.copyfile(
                REPO_ROOT / "common" / "contracts" / "particle_count_policy.json",
                frozen_policy,
            )
            parent = run_dir / "parent.ion"
            child = run_dir / "child.ion"
            lines = generate_ion_source(**arguments)
            parent.write_bytes(_serialized_ion_source(lines))
            child.write_bytes(_serialized_ion_source(lines[:100]))
            run_config = {
                "schema_version": 1,
                "run_id": "20260725_120000__test__python__source-preflight-failure",
                "project": "single_reflection_oa_tof_mass_analyzer",
                "mode": "mass_spectrum_candidate",
                "project_root": str(PROJECT_ROOT),
                "formal_gate_passed": False,
                "inputs": {
                    "mode_config": str(frozen_mode),
                    "resolved_geometry": str(frozen_resolved),
                    "particle_count_policy": str(frozen_policy),
                    "particle_source_test": str(child),
                    "particle_source_parent_test": str(parent),
                },
                "particle_source_preflight": [
                    {
                        "species_id": "test",
                        "status": "pending_deterministic_parent_validation",
                        "consumed_source_path": str(child),
                        "parent_source_path": str(parent),
                        "seed": arguments["seed"],
                    }
                ],
            }
            config_path = run_dir / "run_config.json"
            config_path.write_text(json.dumps(run_config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "deterministic source"):
                validate_ion_source(
                    source_path=parent,
                    **{**arguments, "seed": 20260714},
                )
            environment = os.environ.copy()
            environment.update(
                {
                    "OATOF_TEST_RUN_DIR": str(run_dir),
                    "OATOF_TEST_REPO_ROOT": str(REPO_ROOT),
                    "OATOF_TEST_PYTHON": sys.executable,
                }
            )
            command = (
                ". (Join-Path $env:OATOF_TEST_REPO_ROOT "
                "'common/contracts/run_artifact_support.ps1'); "
                "Write-TerminalRunRecord -RunDir $env:OATOF_TEST_RUN_DIR "
                "-Status failed -Reason 'seed mismatch' "
                "-RepoRoot $env:OATOF_TEST_REPO_ROOT "
                "-Python $env:OATOF_TEST_PYTHON "
                "-SummaryRole 'oa_tof_terminal_run_summary'"
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                check=False,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            terminal_config = json.loads(config_path.read_text(encoding="utf-8-sig"))
            manifest = json.loads(
                (run_dir / "run_manifest.json").read_text(encoding="utf-8-sig")
            )
            self.assertEqual(terminal_config["inputs"]["mode_config"], str(frozen_mode))
            self.assertEqual(
                terminal_config["particle_source_preflight"][0]["seed"],
                arguments["seed"],
            )
            self.assertEqual(manifest["status"], "failed")
            expected_inputs = {
                "mode_config": frozen_mode,
                "resolved_geometry": frozen_resolved,
                "particle_count_policy": frozen_policy,
                "particle_source_test": child,
                "particle_source_parent_test": parent,
            }
            for role, path in expected_inputs.items():
                self.assertEqual(manifest["inputs"][role]["path"], str(path))
                self.assertTrue(manifest["inputs"][role]["exists"])
                self.assertRegex(manifest["inputs"][role]["sha256"], r"^[0-9A-F]{64}$")

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_removed_arbitrary_particle_override_fails_at_parameter_binding(self) -> None:
        result = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-File",
                str(RUNNER),
                "-ParticleCountOverride",
                "30",
            ],
            cwd=PROJECT_ROOT.parents[1],
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ParticleCountOverride", result.stderr)


if __name__ == "__main__":
    unittest.main()
