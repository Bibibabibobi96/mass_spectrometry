from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from projects.single_reflection_oa_tof_mass_analyzer.analysis.stage_formal_simion_runtime import (
    PROJECT_ID,
    stage_runtime,
)


class StageFormalSimionRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.artifact = Path(self.temp.name) / PROJECT_ID
        self.formal = self.artifact / "formal"
        simion = self.formal / "simion"
        simion.mkdir(parents=True)
        self.source = simion / "model.iob"
        self.source.write_bytes(b"formal model")
        record = {
            "path": "simion/model.iob",
            "bytes": self.source.stat().st_size,
            "sha256": file_sha256(self.source),
        }
        (self.formal / "asset_manifest.json").write_text(
            json.dumps({
                "schema_version": 1,
                "role": "formal_asset_manifest",
                "project": PROJECT_ID,
                "release_id": "20260729_112246__sim__cross__vnext-n1000-r2",
                "assets": {"simion_iob": record},
            }),
            encoding="utf-8",
        )
        self.destination = self.artifact / "scratch/runtime"
        self.receipt = self.artifact / "runs/demo/inputs/runtime_receipt.json"

    def test_stages_verified_copy_and_receipt(self) -> None:
        result = stage_runtime(self.artifact, self.destination, self.receipt)
        self.assertEqual((self.destination / "model.iob").read_bytes(), b"formal model")
        self.assertEqual(result["assets"][0]["role"], "simion_iob")
        self.assertTrue(self.receipt.is_file())

    def test_rejects_changed_formal_asset_without_partial_runtime(self) -> None:
        self.source.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "identity differs"):
            stage_runtime(self.artifact, self.destination, self.receipt)
        self.assertFalse(self.destination.exists())

    def test_rejects_unlisted_formal_file(self) -> None:
        (self.formal / "simion/unlisted.pa0").write_bytes(b"unexpected")
        with self.assertRaisesRegex(ValueError, "file set differs"):
            stage_runtime(self.artifact, self.destination, self.receipt)

    def test_activity_scripts_never_run_simion_from_formal(self) -> None:
        project = Path(__file__).resolve().parents[2]
        scripts = {
            "mass": project / "workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1",
            "ideal": project / "simion/workbench/run_ideal_field_diagnostic.ps1",
            "geometry": project / "workflows/formal_reference/verify_geometry_contract.ps1",
            "stable": project / "workflows/formal_reference/verify_stable_entry.ps1",
            "diagnostics": project / "workflows/cross_solver_diagnostics/run_cross_solver_diagnostics.ps1",
        }
        combined = "\n".join(path.read_text(encoding="utf-8") for path in scripts.values())
        self.assertNotIn("-WorkingDirectory $formalSimion", combined)
        self.assertNotIn("-WorkingDirectory $formalDir", combined)
        self.assertNotIn("Push-Location $formalDir", combined)
        for name in ("mass", "ideal", "geometry", "stable", "diagnostics"):
            self.assertIn(
                "New-OaTofFormalSimionRuntime",
                scripts[name].read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
