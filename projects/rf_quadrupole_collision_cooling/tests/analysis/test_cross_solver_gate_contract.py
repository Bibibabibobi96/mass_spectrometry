from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from projects.rf_quadrupole_collision_cooling.analysis.generate_interface_particle_table import (
    generate_bundle,
)
from projects.rf_quadrupole_collision_cooling.analysis.validate_paired_particle_source_binding import (
    resolve_binding,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
CROSS_ROOT = PROJECT_ROOT / "tests" / "cross_solver"
IDENTITY_HELPER = PROJECT_ROOT / "runtime" / "particle_table_identity.ps1"
CROSS_RUNNER = CROSS_ROOT / "verify_transport_candidate.ps1"
COMSOL_RUNNER = PROJECT_ROOT / "tests" / "comsol" / "run_transport_candidate.ps1"
PROJECT_GATE = PROJECT_ROOT / "verify_project.ps1"


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
class ParticleTableIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        cls.source_family = (
            PROJECT_ROOT / "config" / "interface_readiness_particle_source.json"
        )
        cls.distribution = (
            PROJECT_ROOT / "config" / "official_particle_source.json"
        )
        cls.resolved = (
            PROJECT_ROOT / "config" / "resolved_design_official.json"
        )
        cls.primary = root / "primary"
        cls.alternate = root / "alternate"
        generate_bundle(
            cls.source_family,
            cls.distribution,
            cls.resolved,
            cls.primary,
        )
        generate_bundle(
            cls.source_family,
            cls.distribution,
            cls.resolved,
            cls.alternate,
            seed=8675309,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def write_config(
        self,
        root: Path,
        solver: str,
        bundle: Path,
        *,
        tamper_provenance: bool = False,
    ) -> Path:
        representation = "ion11" if solver == "COMSOL" else "canonical10"
        consumed = (
            bundle / "official_100amu_2eV_n100.ion"
            if representation == "ion11"
            else bundle / "official_100amu_2eV_n100_canonical.csv"
        )
        ion11 = bundle / "official_100amu_2eV_n100.ion"
        canonical = bundle / "official_100amu_2eV_n100_canonical.csv"
        metadata = bundle / "paired_particle_bundle.json"
        binding = resolve_binding(
            metadata,
            self.source_family,
            self.distribution,
            self.resolved,
            "official_100amu_2eV",
            100,
            representation,
            consumed,
        )
        provenance = {
            field: binding[field]
            for field in (
                "source_sample_family_sha256",
                "source_family_sha256",
                "distribution_sha256",
                "latent_sha256",
                "coordinate_mapping_version",
                "representation_equivalence",
                "operating_point_id",
                "particle_count",
                "representation",
                "consumed_sha256",
                "ion11_sha256",
                "canonical10_sha256",
                "n1000_parent",
                "ion11_n1000_parent",
                "canonical10_n1000_parent",
            )
        }
        if tamper_provenance:
            provenance["latent_sha256"] = "0" * 64
        config = {
            "role": (
                "rf_quadrupole_comsol_run_config"
                if solver == "COMSOL"
                else "rf_quadrupole_simion_run_config"
            ),
            "mode": "transport_interface_readiness",
            "project_root": str(PROJECT_ROOT),
            "operating_point": "official_100amu_2eV",
            "particles": 100,
            "inputs": {
                "particle_table": str(consumed),
                "consumed_particle_table": str(consumed),
                "source_ion11": str(ion11),
                "source_canonical10": str(canonical),
                "particle_bundle_metadata": str(metadata),
                "particle_source_family": str(self.source_family),
                "particle_source_distribution": str(self.distribution),
                "resolved_design": str(self.resolved),
            },
            "provenance": provenance,
        }
        path = root / f"{solver.lower()}_config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    def run_identity(
        self,
        comsol_config: Path,
        simion_config: Path,
        output_root: Path,
        explicit: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "RF_IDENTITY_HELPER": str(IDENTITY_HELPER),
                "RF_COMSOL_CONFIG": str(comsol_config),
                "RF_SIMION_CONFIG": str(simion_config),
                "RF_COMSOL_BINDING": str(output_root / "comsol_binding.json"),
                "RF_SIMION_BINDING": str(output_root / "simion_binding.json"),
                "RF_REPO_ROOT": str(REPO_ROOT),
                "RF_PYTHON": sys.executable,
                "RF_EXPLICIT_PARTICLES": "" if explicit is None else str(explicit),
            }
        )
        command = (
            ". $env:RF_IDENTITY_HELPER; "
            "$comsol = Get-Content $env:RF_COMSOL_CONFIG -Raw | ConvertFrom-Json; "
            "$simion = Get-Content $env:RF_SIMION_CONFIG -Raw | ConvertFrom-Json; "
            "$identity = Assert-RfTransportParticleTableIdentity "
            "-Python $env:RF_PYTHON -RepoRoot $env:RF_REPO_ROOT "
            "-ComsolRunConfig $comsol -SimionRunConfig $simion "
            "-ComsolBindingOutput $env:RF_COMSOL_BINDING "
            "-SimionBindingOutput $env:RF_SIMION_BINDING "
            "-ExplicitIon11Path $env:RF_EXPLICIT_PARTICLES; "
            "$identity | ConvertTo-Json -Compress"
        )
        return subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPO_ROOT,
            timeout=60,
            capture_output=True,
            check=False,
            encoding="utf-8",
            env=environment,
        )

    def test_cross_representation_same_bundle_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comsol = self.write_config(root, "COMSOL", self.primary)
            simion = self.write_config(root, "SIMION", self.primary)

            result = self.run_identity(comsol, simion, root)

            self.assertEqual(result.returncode, 0, result.stderr)
            identity = json.loads(result.stdout.splitlines()[-1])
            self.assertEqual(
                identity["source_sample_family_sha256"],
                json.loads(
                    (self.primary / "paired_particle_bundle.json").read_text()
                )["sample_family_sha256"],
            )
            self.assertNotEqual(
                identity["ion11_sha256"],
                identity["canonical10_sha256"],
            )

    def test_mass_filter_run_role_is_rejected_before_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comsol = self.write_config(root, "COMSOL", self.primary)
            simion = self.write_config(root, "SIMION", self.primary)
            config = json.loads(simion.read_text(encoding="utf-8"))
            config["role"] = "rf_quadrupole_simion_mass_filter_run_config"
            config["mode"] = "mass_filter_reference"
            simion.write_text(json.dumps(config), encoding="utf-8")

            result = self.run_identity(comsol, simion, root)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("interface transport run-config roles", result.stderr)

    def test_different_bundle_sample_family_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comsol = self.write_config(root, "COMSOL", self.primary)
            simion = self.write_config(root, "SIMION", self.alternate)

            result = self.run_identity(comsol, simion, root)

            self.assertNotEqual(result.returncode, 0)

    def test_tampered_run_provenance_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comsol = self.write_config(
                root,
                "COMSOL",
                self.primary,
                tamper_provenance=True,
            )
            simion = self.write_config(root, "SIMION", self.primary)

            result = self.run_identity(comsol, simion, root)

            self.assertNotEqual(result.returncode, 0)

    def test_wrong_explicit_ion11_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comsol = self.write_config(root, "COMSOL", self.primary)
            simion = self.write_config(root, "SIMION", self.primary)
            wrong = root / "wrong.ion"
            wrong.write_text("not-the-bundle-source\n", encoding="ascii")

            result = self.run_identity(comsol, simion, root, wrong)

            self.assertNotEqual(result.returncode, 0)


class CandidateGateParameterContractTests(unittest.TestCase):
    def test_comsol_runner_consumes_frozen_bundle_ion11_with_binding(self) -> None:
        runner = COMSOL_RUNNER.read_text(encoding="utf-8")
        self.assertIn("[string]$ParticleBundleMetadataPath", runner)
        self.assertIn(
            "validate_paired_particle_source_binding",
            runner,
        )
        self.assertIn("'--consumed-representation','ion11'", runner)
        self.assertIn("particle_table=$particleTable", runner)
        self.assertIn("consumed_particle_table=$particleTable", runner)
        self.assertIn("source_ion11=$particleTable", runner)
        self.assertIn("source_canonical10=$frozenCanonicalPath", runner)
        self.assertIn('("bundle_artifact_{0:D3}"', runner)
        self.assertIn(
            "representation_equivalence=[string]$bindingDocument.representation_equivalence",
            runner,
        )

    def test_runner_separates_execution_manifest_from_scientific_decision(self) -> None:
        cross_runner = CROSS_RUNNER.read_text(encoding="utf-8")
        support = (
            PROJECT_ROOT
            / "runtime"
            / "cross_solver_analysis_lifecycle.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("'--particles',$frozenIon11", cross_runner)
        self.assertIn("execution_status='success'", cross_runner)
        self.assertIn("decision_status=$decisionStatus", cross_runner)
        self.assertIn("-Status success", support)
        self.assertIn("if($decisionStatus-ne'PASS')", cross_runner)
        self.assertIn("Complete-FailedRun", cross_runner)
        self.assertIn("$decisionStatus = 'NOT_EVALUATED'", cross_runner)

    def test_cross_run_config_freezes_cross_representation_bindings(self) -> None:
        cross_runner = CROSS_RUNNER.read_text(encoding="utf-8")
        self.assertIn(
            "particle_table_ion11=$frozenIon11",
            cross_runner,
        )
        self.assertIn(
            "particle_table_canonical10=$frozenCanonical",
            cross_runner,
        )
        self.assertIn(
            "source_sample_family_sha256=$particleIdentity.source_sample_family_sha256",
            cross_runner,
        )
        self.assertIn("Format='ion11'", cross_runner)
        self.assertIn("Format='canonical'", cross_runner)
        self.assertIn("Copy-CrossSolverAnalysisInputs", cross_runner)
        self.assertIn("Complete-CrossSolverAnalysis", cross_runner)

    def test_project_gate_preserves_public_labels_and_maps_to_runner_ids(self) -> None:
        project_gate = PROJECT_GATE.read_text(encoding="utf-8")
        cross_runner = CROSS_RUNNER.read_text(encoding="utf-8")
        runner_parameters = set(
            re.findall(
                r"\[string\]\$(\w+)",
                cross_runner.split("Set-StrictMode", 1)[0],
            )
        )

        for public_parameter in (
            "ComsolRunLabel",
            "SimionRunLabel",
            "ComparisonLabel",
        ):
            self.assertRegex(project_gate, rf"\[string\]\${public_parameter}\s*=")

        invocation = project_gate.split(
            "tests\\cross_solver\\verify_transport_candidate.ps1",
            1,
        )[1].split("if ($LASTEXITCODE", 1)[0]
        forwarded = dict(
            re.findall(r"-(\w+)\s+\$(\w+)", invocation)
        )
        self.assertEqual(forwarded["ComsolRunId"], "ComsolRunLabel")
        self.assertEqual(forwarded["SimionRunId"], "SimionRunLabel")
        self.assertEqual(forwarded["RunId"], "ComparisonLabel")
        self.assertTrue(
            {"ComsolRunId", "SimionRunId", "RunId"}.issubset(runner_parameters)
        )
        self.assertNotIn("ComsolRunLabel", runner_parameters)
        self.assertNotIn("SimionRunLabel", runner_parameters)
        self.assertNotIn("ComparisonLabel", runner_parameters)


if __name__ == "__main__":
    unittest.main()
