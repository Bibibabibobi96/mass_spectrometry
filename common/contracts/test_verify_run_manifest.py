import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256


VERIFIER = Path(__file__).with_name("verify_run_manifest.py")
REPO_ROOT = Path(__file__).parents[2]


def record(path: Path) -> dict:
    return {
        "path": str(path),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


class VerifyRunManifestIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.run = Path(self.temporary_directory.name) / "runs" / "reference-run"
        self.run.mkdir(parents=True)
        self.resolved_sha = "A" * 64
        self.source_sha = "B" * 64
        self.config = self.run / "run_config.json"
        self.consumed_input = self.run / "consumed_input.json"
        self.consumed_input.write_text('{"stable": true}\n', encoding="utf-8")
        self.unconsumed_input = self.run / "unconsumed_input.bin"
        self.unconsumed_input.write_bytes(b"original")
        self.consumed_output = self.run / "consumed_output.json"
        self.consumed_output.write_text('{"result": 1}\n', encoding="utf-8")
        self.unconsumed_output = self.run / "unconsumed_output.bin"
        self.unconsumed_output.write_bytes(b"original")
        self.config.write_text(
            json.dumps(
                {
                    "run_id": "reference-run",
                    "project": "rf_quadrupole_ion_optics",
                    "mode": "resolved_design_transport",
                    "parameters": {"design_profile_id": "official"},
                    "provenance": {
                        "parent_resolved_design_sha256": self.resolved_sha,
                        "particle_source_sha256": self.source_sha,
                    },
                }
            ),
            encoding="utf-8",
        )
        self.manifest = self.run / "run_manifest.json"
        self._write_manifest("success")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write_manifest(self, status: str) -> None:
        self.manifest.write_text(
            json.dumps(
                {
                    "run_id": "reference-run",
                    "project": "rf_quadrupole_ion_optics",
                    "mode": "resolved_design_transport",
                    "status": status,
                    "run_config": record(self.config),
                    "inputs": {
                        "consumed_contract": record(self.consumed_input),
                        "unconsumed_payload": record(self.unconsumed_input),
                    },
                    "outputs": [
                        record(self.consumed_output),
                        record(self.unconsumed_output),
                    ],
                }
            ),
            encoding="utf-8",
        )

    def _verify(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(VERIFIER),
                str(self.manifest),
                "--require-status",
                "success",
                "--require-local-run-config",
                "--require-run-id",
                "reference-run",
                "--require-project",
                "rf_quadrupole_ion_optics",
                "--require-mode",
                "resolved_design_transport",
                "--require-design-profile-id",
                "official",
                "--require-parent-resolved-design-sha256",
                self.resolved_sha,
                "--require-particle-source-sha256",
                self.source_sha,
                *extra,
            ],
            text=True,
            capture_output=True,
            check=False,
            cwd=REPO_ROOT,
            timeout=30,
        )

    def test_reference_constraints_accept_matching_fixture(self) -> None:
        result = self._verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RUN_MANIFEST_VERIFY=PASS", result.stdout)

    def test_pending_terminal_journal_blocks_manifest_consumption(self) -> None:
        (self.run / ".run_terminal_publication.json").write_text("{}\n", encoding="utf-8")
        result = self._verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("publication is incomplete", result.stderr)

    def test_historical_run_relative_records_resolve_from_manifest(self) -> None:
        document = json.loads(self.manifest.read_text(encoding="utf-8"))
        document["run_config"]["path"] = "run_config.json"
        self.manifest.write_text(json.dumps(document), encoding="utf-8")
        result = self._verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RUN_MANIFEST_VERIFY=PASS", result.stdout)

    def test_reference_constraints_fail_closed_on_failed_status(self) -> None:
        self._write_manifest("failed")
        result = self._verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected 'success'", result.stderr)

    def test_checkpoint_manifest_is_verifiable_when_explicitly_requested(self) -> None:
        self._write_manifest("checkpoint")
        result = subprocess.run(
            [
                sys.executable,
                str(VERIFIER),
                str(self.manifest),
                "--require-status",
                "checkpoint",
            ],
            text=True,
            capture_output=True,
            check=False,
            cwd=REPO_ROOT,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reference_constraints_fail_closed_on_identity_mismatch(self) -> None:
        document = json.loads(self.config.read_text(encoding="utf-8"))
        document["provenance"]["particle_source_sha256"] = "C" * 64
        self.config.write_text(json.dumps(document), encoding="utf-8")
        self._write_manifest("success")
        result = self._verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("particle_source_sha256", result.stderr)

    def test_reference_constraints_reject_external_run_config(self) -> None:
        external = self.run.parent / "external_run_config.json"
        external.write_text(self.config.read_text(encoding="utf-8"), encoding="utf-8")
        document = json.loads(self.manifest.read_text(encoding="utf-8"))
        document["run_config"] = record(external)
        self.manifest.write_text(json.dumps(document), encoding="utf-8")
        result = self._verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside its run directory", result.stderr)

    def test_consumer_projection_verifies_only_explicit_path_bound_records(self) -> None:
        self.unconsumed_input.write_bytes(b"corrupt")
        self.unconsumed_output.write_bytes(b"corrupt")
        result = self._verify(
            "--consumer-projection-id",
            "test_contract_consumer_v1",
            "--consumed-input",
            "consumed_contract",
            str(self.consumed_input),
            "--consumed-output",
            str(self.consumed_output),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SCOPE=consumer_projection", result.stdout)
        self.assertIn("CONSUMED_INPUTS=1", result.stdout)
        self.assertIn("CONSUMED_OUTPUTS=1", result.stdout)

    def test_consumer_projection_fails_closed_on_consumed_record_drift(self) -> None:
        self.consumed_input.write_text('{"stable": truf}\n', encoding="utf-8")
        result = self._verify(
            "--consumer-projection-id",
            "test_contract_consumer_v1",
            "--consumed-input",
            "consumed_contract",
            str(self.consumed_input),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256 changed", result.stderr)

    def test_consumer_projection_binds_declared_record_to_consumed_path(self) -> None:
        result = self._verify(
            "--consumer-projection-id",
            "test_contract_consumer_v1",
            "--consumed-input",
            "consumed_contract",
            str(self.unconsumed_input),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("path is", result.stderr)

    def test_consumer_projection_requires_named_records(self) -> None:
        result = self._verify(
            "--consumer-projection-id",
            "test_contract_consumer_v1",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires --consumed-input or --consumed-output", result.stderr)

    def test_consumed_selectors_require_projection_identity(self) -> None:
        result = self._verify(
            "--consumed-output",
            str(self.consumed_output),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("require --consumer-projection-id", result.stderr)


if __name__ == "__main__":
    unittest.main()
