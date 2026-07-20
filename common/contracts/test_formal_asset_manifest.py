from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from verify_artifact_layout import verify_project


RUN_ID = "20260721_120000__sim__cross__formal-validation__n100"


def record(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
    }


class FormalAssetManifestTests(unittest.TestCase):
    def make_project(self, root: Path) -> Path:
        project = root / "demo_project"
        project.mkdir()
        (project / "00_README.txt").write_text("demo\n", encoding="utf-8")
        run = project / "runs" / RUN_ID
        run.mkdir(parents=True)
        (run / "run_config.json").write_text(
            json.dumps({"run_id": RUN_ID}) + "\n", encoding="utf-8"
        )
        (run / "summary.json").write_text("{}\n", encoding="utf-8")
        (run / "run_manifest.json").write_text(
            json.dumps({"run_id": RUN_ID}) + "\n", encoding="utf-8"
        )
        formal = project / "formal"
        formal.mkdir()
        result_manifest = formal / "results.sha256"
        result_manifest.write_text("result identity\n", encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "role": "formal_asset_manifest",
            "project": project.name,
            "release_id": RUN_ID,
            "source_run": {
                "run_id": RUN_ID,
                "path": f"runs/{RUN_ID}",
                "run_config": record(run / "run_config.json", project),
                "summary": record(run / "summary.json", project),
                "run_manifest": record(run / "run_manifest.json", project),
            },
            "validation_contract": {"path": "config/formal.json", "bytes": 1, "sha256": "0" * 64},
            "assets": {"formal_results_manifest": record(result_manifest, formal)},
        }
        (formal / "asset_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return project

    def test_structure_and_hash_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = self.make_project(Path(temp))
            verify_project(project)
            verify_project(project, verify_hashes=True)
            manifest_path = project / "formal" / "asset_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["assets"]["formal_results_manifest"]["sha256"] = "F" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            verify_project(project)
            with self.assertRaisesRegex(AssertionError, "SHA-256 differs"):
                verify_project(project, verify_hashes=True)


if __name__ == "__main__":
    unittest.main()
