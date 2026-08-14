from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.publish_whole_stage_short_long_comparison import (
    _validate_parent_manifest,
)


class WholeStageShortLongComparisonTest(unittest.TestCase):
    def _fixture(self, root: Path, *, status: str = "success") -> tuple[Path, Path, Path]:
        run_dir = root / "parent-run"
        results = run_dir / "results"
        results.mkdir(parents=True)
        checkpoints = results / "checkpoints.csv"
        report = results / "report.json"
        checkpoints.write_text("particle_id\n1\n", encoding="utf-8")
        report.write_text("{}\n", encoding="utf-8")

        def record(path: Path) -> dict[str, object]:
            return {
                "path": str(path.resolve()),
                "exists": True,
                "bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }

        manifest = {
            "schema_version": 2,
            "role": "simulation_run_manifest",
            "run_id": run_dir.name,
            "status": status,
            "inputs": {"checkpoints": record(checkpoints)},
            "outputs": [record(report)],
        }
        manifest_path = run_dir / "run_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path, checkpoints, report

    def test_accepts_success_manifest_with_exact_input_and_output_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manifest, checkpoints, report = self._fixture(Path(temp))
            loaded = _validate_parent_manifest(
                manifest, checkpoints=checkpoints, report=report, label="test"
            )
            self.assertEqual(loaded["run_id"], "parent-run")

    def test_rejects_non_success_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manifest, checkpoints, report = self._fixture(Path(temp), status="failed")
            with self.assertRaises(ContractError):
                _validate_parent_manifest(
                    manifest, checkpoints=checkpoints, report=report, label="test"
                )


if __name__ == "__main__":
    unittest.main()
