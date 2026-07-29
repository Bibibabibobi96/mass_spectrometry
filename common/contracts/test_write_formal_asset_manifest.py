from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from common.contracts.write_formal_asset_manifest import (
    write_formal_asset_manifest,
)


RUN_ID = "20260729_120000__test__cross__formal-release"


class FormalAssetManifestWriterTests(unittest.TestCase):
    def test_writer_targets_staging_without_touching_current_formal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_root = root / "demo"
            run = project_root / "runs" / RUN_ID
            run.mkdir(parents=True)
            for name in ("run_config.json", "summary.json", "run_manifest.json"):
                (run / name).write_text("{}\n", encoding="utf-8")
            staging = project_root / ".formal-staging"
            asset = staging / "results" / "comparison.json"
            asset.parent.mkdir(parents=True)
            asset.write_text("{}\n", encoding="utf-8")
            destination = staging / "asset_manifest.json"

            manifest = write_formal_asset_manifest(
                destination=destination,
                formal_root=staging,
                project="demo",
                source_run_id=RUN_ID,
                source_run_root=run,
                validation_contract_path="projects/demo/config/formal.json",
                validation_contract_bytes=b'{"status":"formal"}\n',
                assets={"comparison": asset},
                recorded_at_utc="2026-07-29T00:00:00+00:00",
            )

            self.assertTrue(destination.is_file())
            self.assertEqual(manifest["assets"]["comparison"]["path"], "results/comparison.json")
            self.assertFalse((project_root / "formal").exists())

    def test_writer_rejects_assets_outside_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_root = root / "demo"
            run = project_root / "runs" / RUN_ID
            run.mkdir(parents=True)
            for name in ("run_config.json", "summary.json", "run_manifest.json"):
                (run / name).write_text("{}\n", encoding="utf-8")
            staging = project_root / ".formal-staging"
            staging.mkdir()
            outside = project_root / "outside.txt"
            outside.write_text("outside\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                write_formal_asset_manifest(
                    destination=staging / "asset_manifest.json",
                    formal_root=staging,
                    project="demo",
                    source_run_id=RUN_ID,
                    source_run_root=run,
                    validation_contract_path="projects/demo/config/formal.json",
                    validation_contract_bytes=b"{}\n",
                    assets={"outside": outside},
                )


if __name__ == "__main__":
    unittest.main()
