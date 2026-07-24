from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CROSS_ROOT = PROJECT_ROOT / "tests" / "cross_solver"
IDENTITY_HELPER = CROSS_ROOT / "particle_table_identity.ps1"
CROSS_RUNNER = CROSS_ROOT / "verify_transport_candidate.ps1"
PROJECT_GATE = PROJECT_ROOT / "verify_project.ps1"


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
class ParticleTableIdentityTests(unittest.TestCase):
    def run_identity(
        self,
        comsol: Path,
        simion: Path,
        explicit: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "RF_IDENTITY_HELPER": str(IDENTITY_HELPER),
                "RF_COMSOL_PARTICLES": str(comsol),
                "RF_SIMION_PARTICLES": str(simion),
                "RF_EXPLICIT_PARTICLES": "" if explicit is None else str(explicit),
            }
        )
        command = (
            ". $env:RF_IDENTITY_HELPER; "
            "$identity = Assert-RfTransportParticleTableIdentity "
            "-ComsolParticlePath $env:RF_COMSOL_PARTICLES "
            "-SimionParticlePath $env:RF_SIMION_PARTICLES "
            "-ExplicitParticlePath $env:RF_EXPLICIT_PARTICLES; "
            "$identity | ConvertTo-Json -Compress"
        )
        return subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            check=False,
            encoding="utf-8",
            env=environment,
        )

    def test_different_paths_with_identical_content_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comsol = root / "comsol-input.ion"
            simion = root / "simion-frozen-input.ion"
            explicit = root / "explicit-original.ion"
            payload = b"0,100,1,0,0,0,0,0,2,1,1\n"
            for path in (comsol, simion, explicit):
                path.write_bytes(payload)

            result = self.run_identity(comsol, simion, explicit)

            self.assertEqual(result.returncode, 0, result.stderr)
            identity = json.loads(result.stdout)
            self.assertEqual(identity["path"], str(explicit.resolve()))
            self.assertEqual(
                identity["sha256"],
                hashlib.sha256(payload).hexdigest().upper(),
            )

    def test_identical_content_without_explicit_path_uses_comsol_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comsol = root / "comsol-input.ion"
            simion = root / "simion-frozen-input.ion"
            payload = b"same-frozen-particle-family\n"
            comsol.write_bytes(payload)
            simion.write_bytes(payload)

            result = self.run_identity(comsol, simion)

            self.assertEqual(result.returncode, 0, result.stderr)
            identity = json.loads(result.stdout)
            self.assertEqual(identity["path"], str(comsol.resolve()))
            self.assertEqual(
                identity["sha256"],
                hashlib.sha256(payload).hexdigest().upper(),
            )

    def test_different_solver_content_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comsol = root / "comsol-input.ion"
            simion = root / "simion-frozen-input.ion"
            comsol.write_text("same-family-row\n", encoding="ascii")
            simion.write_text("changed-family-row\n", encoding="ascii")

            result = self.run_identity(comsol, simion)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "COMSOL and SIMION particle table contents differ.",
                result.stderr,
            )

    def test_different_explicit_content_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comsol = root / "comsol-input.ion"
            simion = root / "simion-frozen-input.ion"
            explicit = root / "wrong-explicit-input.ion"
            comsol.write_text("same-family-row\n", encoding="ascii")
            simion.write_text("same-family-row\n", encoding="ascii")
            explicit.write_text("different-family-row\n", encoding="ascii")

            result = self.run_identity(comsol, simion, explicit)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "Explicit particle table contents differ from the solver run configs.",
                result.stderr,
            )


class CandidateGateParameterContractTests(unittest.TestCase):
    def test_runner_separates_execution_manifest_from_scientific_decision(self) -> None:
        cross_runner = CROSS_RUNNER.read_text(encoding="utf-8")
        self.assertIn("--particles $particlePath", cross_runner)
        self.assertIn("execution_status='success'", cross_runner)
        self.assertIn("decision_status=$comparisonDocument.status", cross_runner)
        success_manifest = cross_runner.index("--status success")
        decision_failure = cross_runner.index(
            "if ($comparisonDocument.status -ne 'PASS')"
        )
        self.assertLess(success_manifest, decision_failure)
        self.assertIn("--status failed", cross_runner)
        self.assertIn("decision_status='NOT_EVALUATED'", cross_runner)

    def test_cross_run_config_freezes_both_solver_particle_tables_and_hash(self) -> None:
        cross_runner = CROSS_RUNNER.read_text(encoding="utf-8")
        self.assertIn(
            "comsol_particle_table=$comsolParticlePath",
            cross_runner,
        )
        self.assertIn(
            "simion_particle_table=$simionParticlePath",
            cross_runner,
        )
        self.assertIn(
            "particle_table_sha256=$particleIdentity.sha256",
            cross_runner,
        )

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
