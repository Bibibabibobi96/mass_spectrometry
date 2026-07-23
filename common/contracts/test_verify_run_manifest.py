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
        self.config.write_text(
            json.dumps(
                {
                    "run_id": "reference-run",
                    "project": "rf_quadrupole_collision_cooling",
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
                    "project": "rf_quadrupole_collision_cooling",
                    "mode": "resolved_design_transport",
                    "status": status,
                    "run_config": record(self.config),
                    "inputs": {},
                    "outputs": [],
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
                "rf_quadrupole_collision_cooling",
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

    def test_reference_constraints_fail_closed_on_failed_status(self) -> None:
        self._write_manifest("failed")
        result = self._verify()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected 'success'", result.stderr)

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


if __name__ == "__main__":
    unittest.main()
