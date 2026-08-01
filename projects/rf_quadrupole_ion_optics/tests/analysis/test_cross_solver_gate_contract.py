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

from projects.rf_quadrupole_ion_optics.workflows.interface_readiness.particle_source_policy import (
    generate_interface_bundle as generate_bundle,
)
from projects.rf_quadrupole_ion_optics.analysis.validate_paired_particle_source_binding import (
    resolve_binding,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
CROSS_ROOT = PROJECT_ROOT / "workflows" / "interface_readiness"
IDENTITY_HELPER = PROJECT_ROOT / "runtime" / "particle_table_identity.ps1"
CROSS_RUNNER = CROSS_ROOT / "compare_cross_solver.ps1"
COMSOL_RUNNER = CROSS_ROOT / "run_comsol.ps1"
PROJECT_GATE = PROJECT_ROOT / "verify_project.ps1"
LIFECYCLE_SUPPORT = PROJECT_ROOT / "runtime" / "cross_solver_analysis_lifecycle.ps1"


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
            errors="replace",
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


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
class CrossSolverLifecycleTests(unittest.TestCase):
    def invoke_lifecycle(
        self,
        command: str,
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=REPO_ROOT,
            timeout=60,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )

    def test_source_pair_discards_manifest_verifier_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_repo = root / "repo"
            verifier = fake_repo / "common" / "contracts" / "verify_run_manifest.py"
            verifier.parent.mkdir(parents=True)
            verifier.write_text(
                "print('RUN_MANIFEST_VERIFY=PASS fake-verifier')\n",
                encoding="utf-8",
            )
            artifact_root = root / "artifacts"
            for solver, role in (
                ("comsol", "rf_quadrupole_comsol_run_config"),
                ("simion", "rf_quadrupole_simion_run_config"),
            ):
                run = artifact_root / "runs" / solver
                run.mkdir(parents=True)
                config = run / "run_config.json"
                config.write_text(json.dumps({"role": role}), encoding="utf-8")
                (run / "run_manifest.json").write_text(
                    json.dumps({"run_config": {"path": str(config)}}),
                    encoding="utf-8",
                )
            environment = os.environ.copy()
            environment.update(
                {
                    "RF_LIFECYCLE_SUPPORT": str(LIFECYCLE_SUPPORT),
                    "RF_FAKE_REPO": str(fake_repo),
                    "RF_ARTIFACT_ROOT": str(artifact_root),
                    "RF_PYTHON": sys.executable,
                }
            )
            command = (
                ". $env:RF_LIFECYCLE_SUPPORT; "
                "$pair=Get-CrossSolverSourcePair "
                "-Python $env:RF_PYTHON -RepoRoot $env:RF_FAKE_REPO "
                "-ArtifactRoot $env:RF_ARTIFACT_ROOT "
                "-ComsolRunId comsol -SimionRunId simion; "
                "[pscustomobject]@{"
                "type=$pair.GetType().FullName;"
                "comsol_role=$pair.comsol.config.role;"
                "simion_role=$pair.simion.config.role"
                "}|ConvertTo-Json -Compress"
            )
            result = self.invoke_lifecycle(command, environment)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["type"], "System.Management.Automation.PSCustomObject")
            self.assertEqual(
                payload["comsol_role"],
                "rf_quadrupole_comsol_run_config",
            )
            self.assertEqual(
                payload["simion_role"],
                "rf_quadrupole_simion_run_config",
            )
            self.assertNotIn("RUN_MANIFEST_VERIFY", result.stdout)

            verifier.write_text(
                "print('RUN_MANIFEST_VERIFY=FAIL fake-verifier')\n"
                "raise SystemExit(7)\n",
                encoding="utf-8",
            )
            rejected = self.invoke_lifecycle(command, environment)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("Source run-manifest verification failed", rejected.stderr)

    def invoke_resolved_drive(
        self,
        comsol: Path,
        simion: Path,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "RF_LIFECYCLE_SUPPORT": str(LIFECYCLE_SUPPORT),
                "RF_COMSOL_RESOLVED": str(comsol),
                "RF_SIMION_RESOLVED": str(simion),
            }
        )
        command = (
            ". $env:RF_LIFECYCLE_SUPPORT; "
            "Get-CrossSolverResolvedDrive "
            "-ComsolResolvedDesign $env:RF_COMSOL_RESOLVED "
            "-SimionResolvedDesign $env:RF_SIMION_RESOLVED "
            "|ConvertTo-Json -Compress"
        )
        return self.invoke_lifecycle(command, environment)

    def test_resolved_drive_is_authoritative_and_fails_closed(self) -> None:
        document = {
            "role": "multipole_resolved_design_do_not_edit",
            "drive": {
                "rf_amplitude_V_zero_to_peak_per_group": 139.81792,
                "frequency_Hz": 1_100_000.0,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comsol = root / "comsol.json"
            simion = root / "simion.json"
            encoded = json.dumps(document, sort_keys=True)
            comsol.write_text(encoded, encoding="utf-8")
            simion.write_text(encoded, encoding="utf-8")

            accepted = self.invoke_resolved_drive(comsol, simion)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            drive = json.loads(accepted.stdout)
            self.assertEqual(drive["rf_peak_v"], 139.81792)
            self.assertEqual(drive["frequency_hz"], 1_100_000.0)
            self.assertRegex(drive["resolved_design_sha256"], r"^[0-9A-F]{64}$")

            same_drive_different_file = dict(document)
            same_drive_different_file["additional_identity"] = "different"
            simion.write_text(
                json.dumps(same_drive_different_file, sort_keys=True),
                encoding="utf-8",
            )
            rejected_hash = self.invoke_resolved_drive(comsol, simion)
            self.assertNotEqual(rejected_hash.returncode, 0)
            self.assertIn(
                "resolved designs or drive values differ",
                rejected_hash.stderr,
            )
            simion.write_text(encoded, encoding="utf-8")

            missing_path = self.invoke_resolved_drive(
                root / "missing.json",
                simion,
            )
            self.assertNotEqual(missing_path.returncode, 0)
            self.assertIn("frozen resolved design is missing", missing_path.stderr)

            missing_value = dict(document)
            missing_value["drive"] = dict(document["drive"])
            del missing_value["drive"]["frequency_Hz"]
            comsol.write_text(json.dumps(missing_value), encoding="utf-8")
            missing = self.invoke_resolved_drive(comsol, simion)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("lacks numeric frequency_Hz", missing.stderr)

            for invalid_value in (True, None):
                with self.subTest(invalid_value=invalid_value):
                    invalid_type = dict(document)
                    invalid_type["drive"] = dict(document["drive"])
                    invalid_type["drive"]["frequency_Hz"] = invalid_value
                    comsol.write_text(json.dumps(invalid_type), encoding="utf-8")
                    rejected_type = self.invoke_resolved_drive(comsol, simion)
                    self.assertNotEqual(rejected_type.returncode, 0)
                    self.assertIn(
                        "lacks numeric frequency_Hz",
                        rejected_type.stderr,
                    )

            numeric_string = dict(document)
            numeric_string["drive"] = dict(document["drive"])
            numeric_string["drive"]["frequency_Hz"] = "1100000"
            comsol.write_text(json.dumps(numeric_string), encoding="utf-8")
            rejected_string = self.invoke_resolved_drive(comsol, simion)
            self.assertNotEqual(rejected_string.returncode, 0)
            self.assertIn("lacks numeric frequency_Hz", rejected_string.stderr)

            comsol.write_text(
                '{"role":"multipole_resolved_design_do_not_edit",'
                '"drive":{"rf_amplitude_V_zero_to_peak_per_group":139.81792,'
                '"frequency_Hz":1e9999}}',
                encoding="utf-8",
            )
            rejected_nonfinite = self.invoke_resolved_drive(comsol, simion)
            self.assertNotEqual(rejected_nonfinite.returncode, 0)
            self.assertIn("frequency_Hz is not finite", rejected_nonfinite.stderr)

            mismatch = dict(document)
            mismatch["drive"] = dict(document["drive"])
            mismatch["drive"]["frequency_Hz"] = 1_200_000.0
            comsol.write_text(encoded, encoding="utf-8")
            simion.write_text(json.dumps(mismatch), encoding="utf-8")
            rejected_mismatch = self.invoke_resolved_drive(comsol, simion)
            self.assertNotEqual(rejected_mismatch.returncode, 0)
            self.assertIn("resolved designs or drive values differ", rejected_mismatch.stderr)


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

    def test_cross_source_contract_uses_single_manifest_and_resolved_drive(self) -> None:
        cross_runner = CROSS_RUNNER.read_text(encoding="utf-8")
        support = LIFECYCLE_SUPPORT.read_text(encoding="utf-8")
        self.assertIn("$null = & $Python", support)
        self.assertIn("Get-CrossSolverResolvedDrive", support)
        self.assertNotIn("$comsolConfig.rf_peak_v", cross_runner)
        self.assertNotIn("$comsolConfig.frequency_hz", cross_runner)
        self.assertNotIn("$simionConfig.rf_peak_v", cross_runner)
        self.assertNotIn("$simionConfig.frequency_hz", cross_runner)
        self.assertIn("comsol_resolved_design=$frozenComsolResolved", cross_runner)
        self.assertIn("simion_resolved_design=$frozenSimionResolved", cross_runner)
        self.assertIn("rf_peak_v=$resolvedDrive.rf_peak_v", cross_runner)
        self.assertIn("frequency_hz=$resolvedDrive.frequency_hz", cross_runner)
        self.assertIn(
            "resolved_design_sha256=$resolvedDrive.resolved_design_sha256",
            cross_runner,
        )
        self.assertLess(
            cross_runner.index("Assert-RfTransportParticleTableIdentity"),
            cross_runner.index("$comsolResolvedSource"),
        )
        self.assertLess(
            cross_runner.index("Copy-CrossSolverAnalysisInputs"),
            cross_runner.index("$resolvedDrive = Get-CrossSolverResolvedDrive"),
        )

    def test_project_gate_does_not_select_or_forward_candidate_workflows(self) -> None:
        project_gate = PROJECT_GATE.read_text(encoding="utf-8")
        cross_runner = CROSS_RUNNER.read_text(encoding="utf-8")
        runner_parameters = set(
            re.findall(
                r"\[string\]\$(\w+)",
                cross_runner.split("Set-StrictMode", 1)[0],
            )
        )

        self.assertIn(
            "[ValidateSet('Freshness','Core','Static','Formal')]",
            project_gate,
        )
        self.assertNotIn("'Candidate'", project_gate)
        self.assertNotIn("CandidateMode", project_gate)
        self.assertNotIn("ComsolRunLabel", project_gate)
        self.assertNotIn("SimionRunLabel", project_gate)
        self.assertNotIn("ComparisonLabel", project_gate)
        self.assertNotIn("compare_cross_solver.ps1", project_gate)
        self.assertTrue(
            {"ComsolRunId", "SimionRunId", "RunId"}.issubset(runner_parameters)
        )
        self.assertNotIn("ComsolRunLabel", runner_parameters)
        self.assertNotIn("SimionRunLabel", runner_parameters)
        self.assertNotIn("ComparisonLabel", runner_parameters)

    def test_project_gate_core_keeps_physical_contracts_but_not_full_regressions(self) -> None:
        project_gate = PROJECT_GATE.read_text(encoding="utf-8")
        core_return = project_gate.index("if ($Level -eq 'Core')")
        full_analysis = project_gate.index("-m unittest discover")
        full_parse = project_gate.index("[System.Management.Automation.Language.Parser]::ParseFile")

        self.assertLess(core_return, full_analysis)
        self.assertLess(core_return, full_parse)
        for required in (
            "resolve_contract --check",
            "--profile interface --check",
            "--profile mass_filter --check",
            "sync_simion_geometry --check",
            "generate_official_particle_table --check",
            "mass_filter_reference.theory",
            "mass_filter_reference.run_finite_length",
            "entry_aperture_l0.py",
        ):
            with self.subTest(required=required):
                self.assertLess(project_gate.index(required), core_return)

    def test_project_gate_static_retains_full_analysis_and_powershell_regressions(self) -> None:
        project_gate = PROJECT_GATE.read_text(encoding="utf-8")

        self.assertIn("-m unittest discover", project_gate)
        self.assertIn("[System.Management.Automation.Language.Parser]::ParseFile", project_gate)
        self.assertLess(
            project_gate.index("if ($Level -eq 'Core')"),
            project_gate.index("-m unittest discover"),
        )


if __name__ == "__main__":
    unittest.main()
