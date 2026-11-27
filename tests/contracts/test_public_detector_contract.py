"""Frozen public detector plan contract, independent of native stage cache."""
import json
from pathlib import Path
import tempfile
import unittest

from msplatform.io.file_identity import file_sha256
from msplatform.io.manifest_records import file_record
from msplatform.results.public_detector_contract import read_public_detector_contract
from msplatform.storage.store import ArtifactStore


class PublicDetectorContractTests(unittest.TestCase):
    def publish(self, root, *, face=None, contract_face=None, multi=False):
        store = ArtifactStore(root / "store", high_water_bytes=100_000_000, low_water_bytes=80_000_000, safety_bytes=0)
        source = root / "source.json"
        source.write_text("{}", encoding="utf-8")
        run, work = store.begin_run()
        with store.run_writer(run), store.reserve(1_000_000):
            store.mark_running(run)
            plan = work / "detector_plan.json"
            plan.write_text(json.dumps({"detector_active_face":face}), encoding="utf-8")
            facts = work / "detector_native_facts.json"
            facts.write_text(json.dumps({"detector_observation_native": face is not None}), encoding="utf-8")
            contract = {"schema_version":1, "role":"public_native_detector_contract", "backend":"comsol",
                "source_reference":{"manifest":file_record(source), "product_id":"trajectory"},
                "source_plan_sha256":file_sha256(plan), "source_facts_sha256":file_sha256(facts),
                "detector_active_face":face if contract_face is None else contract_face}
            (work / "detector_contract.json").write_text(json.dumps(contract), encoding="utf-8")
            if multi:
                (work / "detector_contracts").mkdir()
                (work / "detector_contracts/batch.json").write_text("{}", encoding="utf-8")
            store.publish_run(work, run_id=run)
        path = store.inspect_run(run)
        manifest = json.loads((path / "run_manifest.json").read_text(encoding="utf-8"))
        return path, manifest

    def test_declared_surface_and_null_face_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            path, manifest = self.publish(Path(directory), face={"surface_id":"detector_active_face"})
            self.assertEqual(read_public_detector_contract(path, manifest)["detector_active_face"]["surface_id"], "detector_active_face")
        with tempfile.TemporaryDirectory() as directory:
            path, manifest = self.publish(Path(directory), face=None)
            self.assertIsNone(read_public_detector_contract(path, manifest)["detector_active_face"])

    def test_wrong_face_tamper_and_multi_batch_refuse(self):
        with tempfile.TemporaryDirectory() as directory:
            path, manifest = self.publish(Path(directory), face={"surface_id":"one"}, contract_face={"surface_id":"other"})
            with self.assertRaisesRegex(ValueError, "does not match"):
                read_public_detector_contract(path, manifest)
        with tempfile.TemporaryDirectory() as directory:
            path, manifest = self.publish(Path(directory), face={"surface_id":"one"})
            (path / "detector_plan.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "snapshot"):
                read_public_detector_contract(path, manifest)
        with tempfile.TemporaryDirectory() as directory:
            path, manifest = self.publish(Path(directory), face={"surface_id":"one"})
            (path / "detector_native_facts.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "snapshot"):
                read_public_detector_contract(path, manifest)
        with tempfile.TemporaryDirectory() as directory:
            path, manifest = self.publish(Path(directory), face={"surface_id":"one"}, multi=True)
            with self.assertRaisesRegex(ValueError, "multi-batch"):
                read_public_detector_contract(path, manifest)


if __name__ == "__main__":
    unittest.main()
