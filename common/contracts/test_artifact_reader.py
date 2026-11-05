"""Published-data reading across processes; these fixtures are not native evidence."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from msplatform import api
from msplatform.execution.manifest_records import file_record
from msplatform.io.file_identity import file_sha256
from msplatform.execution.terminal_publication import publish_terminal_state, TERMINAL_JOURNAL_NAME


class ArtifactReaderTests(unittest.TestCase):
    def test_resolved_location_snapshot_survives_relocation_and_cannot_mutate_reader(self):
        moved = self.root/'moved locations'
        shutil.move(str(self.run), moved)
        resolver = lambda record, base: moved/Path(record['path']).name if base is None else base/record['path']
        result = api.open_artifact(self.reference, expected_kind='trajectory_result', resolver=resolver)
        self.assertFalse(self.run.exists())
        self.assertEqual(result.manifest_location, moved/'run_manifest.json')
        self.assertEqual(result.reference, self.reference)
        locations = result.data_locations
        self.assertEqual(locations['observations'], moved/self.data.name)
        locations['observations'] = self.root/'injected'
        locations.clear()
        self.assertEqual(result.data_locations, {'observations':moved/self.data.name})
        (moved/self.data.name).write_bytes(b'changed after opening')
        # A location is a verified-at-open snapshot, never a later integrity proof.
        self.assertEqual(result.data_locations['observations'], moved/self.data.name)
        with self.assertRaises(AssertionError):
            result.data_path('observations')
        (moved/'run_manifest.json').write_bytes(b'changed manifest')
        with self.assertRaises(AssertionError):
            api.open_artifact(self.reference, expected_kind='trajectory_result', resolver=resolver)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="artifact reader ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root / "producer"
        self.run.mkdir()
        self.data = self.run / "observations.csv"
        self.data.write_text("particle_id,time_us\n7,10\n42,12\n", encoding="utf-8", newline="\n")
        record = file_record(self.data, recorded_path=Path(self.data.name))
        self.manifest = dict(schema_version=2, role="simulation_run_manifest", run_id="reader-fixture",
            project="software_fixture", mode="completed_observation", status="failed",
            inputs={"unused_execution_code":dict(path="missing-old-source.py", exists=True, bytes=1, sha256="0"*64)},
            outputs=[record], products={"flight":dict(schema_version=1, kind="trajectory_result",
                status="complete", metadata=dict(scientific_status="FAIL", mother_ids=[7,42]),
                data={"observations":record})})
        publish_terminal_state(self.run, {"status":"failed"}, self.manifest)
        self.reference = {"manifest":file_record(self.run / "run_manifest.json"), "product_id":"flight"}

    def reference_after_manifest_edit(self, document):
        path = self.run / "run_manifest.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return {"manifest":file_record(path), "product_id":"flight"}

    def test_complete_scientific_failure_can_be_read_without_execution_closure_or_tools(self):
        original = copy.deepcopy(self.reference)
        with patch("subprocess.Popen", side_effect=AssertionError("native process")), \
             patch.object(Path, "write_text", side_effect=AssertionError("data write")), \
             patch.object(Path, "mkdir", side_effect=AssertionError("directory creation")):
            result = api.open_artifact(self.reference, expected_kind="trajectory_result")
            self.assertEqual(result.data_path("observations").read_text(encoding="utf-8"),
                             "particle_id,time_us\n7,10\n42,12\n")
        self.assertEqual(result.producer["status"], "failed")
        self.assertEqual(result.metadata["scientific_status"], "FAIL")
        result.metadata["mother_ids"].clear()
        result.data_records.clear()
        result.reference.clear()
        self.reference.clear()
        self.assertEqual(result.metadata["mother_ids"], [7,42])
        self.assertEqual(result.reference, original)
        self.assertFalse((self.run / "missing-old-source.py").exists())

    def test_new_process_new_cwd_and_no_tool_path_read_the_same_product(self):
        reference_path = self.root / "reference.json"
        reference_path.write_text(json.dumps(self.reference), encoding="utf-8")
        other = self.root / "other cwd"
        other.mkdir()
        program = """
import json,sys
from pathlib import Path
from msplatform import api
result=api.open_artifact(json.loads(Path(sys.argv[1]).read_text()),expected_kind='trajectory_result')
assert result.metadata['mother_ids']==[7,42]
assert result.data_path('observations').read_text().splitlines()[2]=='42,12'
print(result.producer['status'])
"""
        completed = subprocess.run([sys.executable,"-I","-c",program,str(reference_path)], cwd=other,
            env=dict(os.environ, PATH="", PYTHONPATH="", SIMION_HOME=""), capture_output=True,
            text=True, encoding="utf-8", timeout=30, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
        self.assertEqual(completed.stdout.strip(), "failed")

    def test_bundle_relative_members_survive_move_and_historical_paths_use_explicit_resolver(self):
        old_manifest = self.reference["manifest"]["path"]
        moved = self.root / "moved"
        shutil.move(str(self.run), moved)
        with self.assertRaises(AssertionError):
            api.open_artifact(self.reference, expected_kind="trajectory_result")
        resolver = lambda record, base: moved / Path(record["path"]).name if base is None else base / record["path"]
        result = api.open_artifact(self.reference, expected_kind="trajectory_result", resolver=resolver)
        self.assertEqual(result.data_path("observations"), moved / self.data.name)
        self.assertEqual(result.reference["manifest"]["path"], old_manifest)

    def test_manifest_and_payload_tamper_missing_members_and_unbound_records_fail(self):
        self.data.write_text("particle_id,time_us\n7,11\n42,12\n", encoding="utf-8", newline="\n")
        with self.assertRaisesRegex(AssertionError, "SHA-256 changed"):
            api.open_artifact(self.reference, expected_kind="trajectory_result")
        self.data.unlink()
        with self.assertRaisesRegex(AssertionError, "missing"):
            api.open_artifact(self.reference, expected_kind="trajectory_result")
        document = copy.deepcopy(self.manifest)
        document["products"]["flight"]["data"]["observations"] = dict(
            path="unbound.csv", exists=True, bytes=0, sha256="0"*64)
        with self.assertRaisesRegex(ValueError, "not bound"):
            api.open_artifact(self.reference_after_manifest_edit(document), expected_kind="trajectory_result")
        (self.run / "run_manifest.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(AssertionError):
            api.open_artifact(self.reference, expected_kind="trajectory_result")

    def test_journal_partial_unknown_version_and_kind_are_rejected_without_replay(self):
        journal = self.run / TERMINAL_JOURNAL_NAME
        journal.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "publication is incomplete"):
            api.open_artifact(self.reference, expected_kind="trajectory_result")
        self.assertTrue(journal.exists())
        journal.unlink()
        for key, value in (("status","running"),("schema_version",99),("schema_version",True)):
            document = copy.deepcopy(self.manifest)
            document[key] = value
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                api.open_artifact(self.reference_after_manifest_edit(document), expected_kind="trajectory_result")
        for key, value in (("status","partial"),("schema_version",99),("schema_version",True),("kind","field_bundle")):
            document = copy.deepcopy(self.manifest)
            document["products"]["flight"][key] = value
            with self.subTest(product_key=key,value=value), self.assertRaises(ValueError):
                api.open_artifact(self.reference_after_manifest_edit(document), expected_kind="trajectory_result")

    def test_data_member_is_revalidated_before_later_consumption(self):
        result = api.open_artifact(self.reference, expected_kind="trajectory_result")
        self.data.write_text("particle_id,time_us\n7,11\n42,12\n", encoding="utf-8", newline="\n")
        with self.assertRaisesRegex(AssertionError, "SHA-256 changed"):
            result.data_path("observations")
        with self.assertRaisesRegex(ValueError, "no declared data member"):
            result.data_path("unrecorded")

    def test_explicit_native_record_uses_the_shared_unbuffered_tier_without_policy_lookup(self):
        # Reduce the byte threshold for this dispatch oracle; no native PA or
        # real large-file I/O qualification is claimed by the small fixture.
        document = copy.deepcopy(self.manifest)
        record = document["outputs"][0]
        record["retention_role"] = "solver_native_binary"
        document["products"]["flight"]["data"]["observations"] = copy.deepcopy(record)
        reference = self.reference_after_manifest_edit(document)
        reference["manifest"]["retention_role"] = "scientific_metadata"
        with patch("msplatform.execution.manifest_records._UNBUFFERED_SOLVER_PAYLOAD_BYTES",8), \
             patch("msplatform.execution.manifest_records.file_sha256_unbuffered",wraps=file_sha256) as unbuffered, \
             patch("msplatform.execution.resources.resource_path",side_effect=AssertionError("policy lookup")):
            result = api.open_artifact(reference,expected_kind="trajectory_result")
            self.assertEqual(result.data_path("observations"),self.data)
        self.assertEqual(unbuffered.call_count,2)
        self.assertTrue(all(call.args == (self.data,) for call in unbuffered.call_args_list))


if __name__ == "__main__":
    unittest.main()
