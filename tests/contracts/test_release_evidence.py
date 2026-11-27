"""Small historical evidence publishing tests; no legacy promotion execution."""
from pathlib import Path
import json
import os
import tempfile
import unittest
from msplatform.execution.owner import publish_historical_release_evidence, read_historical_release_evidence
from msplatform.io.manifest_records import file_record
from msplatform.storage import ArtifactStore


@unittest.skipUnless(os.name == "nt", "Windows immutable file sharing required")
class HistoricalReleaseEvidenceTests(unittest.TestCase):
    def test_publish_reuse_missing_reference_and_source_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "historical-project"
            formal = project / "formal"
            assets = {}
            for role, relative in (("model", "comsol/model.mph"), ("simion", "simion/model.iob"),
                                   ("cad", "cad/model.sldasm"), ("comparison", "results/comparison.json")):
                path = formal / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((role + " frozen").encode())
                identity = file_record(path)
                assets[role] = {"path": relative, "bytes": identity["bytes"], "sha256": identity["sha256"]}
            source_manifest = formal / "asset_manifest.json"
            source_manifest.write_text(json.dumps({"schema_version": 1, "role": "formal_asset_manifest",
                "project": "fixture", "release_id": "history-1", "source_run": "original-run",
                "validation_contract": {"scope": "original"}, "assets": assets}), encoding="utf-8")
            frozen = file_record(source_manifest)
            old_bytes = {p.relative_to(formal).as_posix(): p.read_bytes() for p in formal.rglob("*") if p.is_file()}
            store = ArtifactStore(root / "store")
            args = dict(manifest_record=frozen, project_id="fixture", artifact_project_root=project, asset_roles=("model", "simion"), reserve_bytes=100000)
            first = publish_historical_release_evidence(store, **args)
            self.assertFalse(first["reference_reused"])
            with read_historical_release_evidence(store, first["run_id"]) as evidence:
                self.assertEqual(set(evidence["assets"]), {"model", "simion"})
                self.assertEqual(evidence["qualification"], "historical_evidence_only")
                with self.assertRaises(OSError):
                    (formal / "comsol/model.mph").unlink()
            second = publish_historical_release_evidence(store, **args)
            self.assertTrue(second["reference_reused"])
            self.assertEqual(second["reference_asset"], first["reference_asset"])
            with store.claim(first["reference_asset"]) as cache:
                (cache / "reference.json").unlink()
            repaired = publish_historical_release_evidence(store, **args)
            self.assertFalse(repaired["reference_reused"])
            self.assertNotEqual(repaired["reference_asset"], first["reference_asset"])
            with read_historical_release_evidence(store, first["run_id"]) as evidence:
                self.assertEqual(evidence["historical_source_run"], "original-run")
            self.assertEqual(old_bytes, {p.relative_to(formal).as_posix(): p.read_bytes() for p in formal.rglob("*") if p.is_file()})
            (formal / "comsol/model.mph").unlink()
            with self.assertRaises((FileNotFoundError, OSError, ValueError)):
                publish_historical_release_evidence(store, **args)
            with self.assertRaises((FileNotFoundError, OSError, ValueError)):
                with read_historical_release_evidence(store, first["run_id"]):
                    pass


if __name__ == "__main__":
    unittest.main()
