from __future__ import annotations

import json
import copy
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.file_identity import file_sha256
from common.simion import cache_generation
from common.simion.standalone_pa_response_set import (
    POLICY_ID,
    ResponseExport,
    StandalonePaResponseSetError,
    select_standalone_pa_records,
    validate_standalone_pa_response_set,
    write_standalone_pa_response_set,
)


class StandalonePaResponseSetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.exporter = self.root / "export_standalone_pa.lua"
        self.exporter.write_bytes(b"exporter")
        for response_id in (36, 37):
            (self.root / f"field.pa{response_id}").write_bytes(
                f"native-{response_id}".encode()
            )
            (self.root / f"field.response_{response_id}.pa").write_bytes(
                f"standalone-{response_id}".encode()
            )
        self.exports = tuple(
            ResponseExport(
                response_id,
                f"field.pa{response_id}",
                f"field.response_{response_id}.pa",
            )
            for response_id in (36, 37)
        )
        self.receipt_name = "standalone_response_set.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_receipt(self) -> None:
        write_standalone_pa_response_set(
            self.root,
            self.exporter,
            self.exports,
            self.root / self.receipt_name,
            source_directory=self.root,
        )

    def _manifest(self) -> dict:
        names = [
            self.receipt_name,
            *(export.source_name for export in self.exports),
            *(export.standalone_name for export in self.exports),
            "field.pa#",
            "field.pa+",
        ]
        for name in ("field.pa#", "field.pa+"):
            (self.root / name).write_bytes(name.encode())
        records = [
            {
                "name": name,
                "bytes": (self.root / name).stat().st_size,
                "sha256": file_sha256(self.root / name),
            }
            for name in sorted(names)
        ]
        return {"schema_version": 3, "files": records}

    def test_receipt_hashes_persisted_producer_bytes(self) -> None:
        def persist(path: Path) -> None:
            path.write_bytes(path.read_bytes() + b'-persisted')

        with patch('common.simion.standalone_pa_response_set._flush_writable_source', side_effect=persist):
            self._write_receipt()
        receipt = json.loads((self.root / self.receipt_name).read_text())
        for response in receipt['responses']:
            for role in ('source', 'standalone'):
                record = response[role]
                self.assertEqual(record['sha256'], file_sha256(self.root / record['name']))
                self.assertTrue((self.root / record['name']).read_bytes().endswith(b'-persisted'))

    def test_two_stage_receipt_binds_provenance_and_retained_outputs(self) -> None:
        self._write_receipt()
        receipt = json.loads((self.root / self.receipt_name).read_text())
        self.assertNotIn(self.receipt_name, json.dumps(receipt))
        manifest = self._manifest()
        selected = validate_standalone_pa_response_set(
            self.root,
            manifest,
            self.receipt_name,
            expected_response_ids=(36, 37),
        )
        self.assertEqual([record.response_id for record in selected], [36, 37])

    def test_metadata_selection_reads_receipt_but_defers_all_pa_payloads(self) -> None:
        self._write_receipt()
        manifest = self._manifest()
        with patch('common.simion.cache_generation.file_sha256', wraps=file_sha256) as pa_hash:
            baseline = select_standalone_pa_records(self.root, manifest, self.receipt_name)
            self.assertEqual(pa_hash.call_count, 2)
            print('PA_SELECTOR_READS baseline=2 bytes=26')
        with (patch('common.simion.cache_generation.file_sha256', wraps=file_sha256) as pa_hash,
              patch('common.simion.standalone_pa_response_set.file_sha256', wraps=file_sha256) as receipt_hash):
            selected = select_standalone_pa_records(self.root, manifest, self.receipt_name,
                                                    verify_payload=False)
            self.assertEqual(selected, baseline)
            pa_hash.assert_not_called()
            receipt_hash.assert_called_once_with(self.root / self.receipt_name)
            print('PA_SELECTOR_READS metadata=0 receipt_reads=1')
        # Metadata selection cannot license consumption: the default deep path
        # must still reject same-length damage which metadata cannot observe.
        path = self.root / self.exports[0].standalone_name
        path.write_bytes(b'X' * path.stat().st_size)
        select_standalone_pa_records(self.root, manifest, self.receipt_name, verify_payload=False)
        with self.assertRaisesRegex(StandalonePaResponseSetError, 'bytes differ'):
            select_standalone_pa_records(self.root, manifest, self.receipt_name)

    def test_metadata_selection_retains_receipt_manifest_and_namespace_rejections(self) -> None:
        self._write_receipt()
        original = self._manifest()
        for mutation in ('receipt', 'manifest', 'ids', 'missing', 'size'):
            with self.subTest(mutation=mutation):
                manifest = copy.deepcopy(original)
                receipt = self.root / self.receipt_name
                target = self.root / self.exports[0].standalone_name
                before = receipt.read_bytes(), target.read_bytes()
                kwargs = {'verify_payload': False}
                if mutation == 'receipt':
                    receipt.write_bytes(before[0] + b' ')
                elif mutation == 'manifest':
                    next(row for row in manifest['files'] if row['name'] == target.name)['sha256'] = 'A' * 64
                elif mutation == 'ids':
                    kwargs['expected_response_ids'] = (36,)
                elif mutation == 'missing':
                    target.unlink()
                else:
                    target.write_bytes(before[1] + b'x')
                try:
                    with self.assertRaises(StandalonePaResponseSetError):
                        select_standalone_pa_records(self.root, manifest, self.receipt_name, **kwargs)
                finally:
                    receipt.write_bytes(before[0])
                    target.write_bytes(before[1])

    def test_local_selector_cli_metadata_option_preserves_default_deep_verification(self) -> None:
        self._write_receipt()
        manifest = self.root / 'cache_manifest.json'
        manifest.write_text(json.dumps(self._manifest()), encoding='utf-8', newline='\n')
        command = [sys.executable, '-B', '-m', 'integrations.runtime.standalone_pa_family',
                   '--directory', str(self.root), '--prefix', 'field', '--response-ids', '36,37',
                   '--manifest', str(manifest), '--output', str(self.root / 'selection.json')]
        def run(metadata: bool) -> subprocess.CompletedProcess:
            return subprocess.run(command + (['--metadata-only'] if metadata else []),
                                  cwd=Path(__file__).resolve().parents[2], capture_output=True,
                                  text=True, encoding='utf-8', check=False, timeout=30)
        self.assertEqual(run(False).returncode, 0)
        original = (self.root / 'selection.json').read_bytes()
        self.assertEqual(run(True).returncode, 0)
        self.assertEqual((self.root / 'selection.json').read_bytes(), original)
        target = self.root / self.exports[0].standalone_name
        target.write_bytes(b'X' * target.stat().st_size)
        self.assertEqual(run(True).returncode, 0)
        self.assertNotEqual(run(False).returncode, 0)
        receipt = self.root / self.receipt_name
        receipt.write_bytes(receipt.read_bytes() + b' ')
        self.assertNotEqual(run(True).returncode, 0)

    def test_retired_native_sources_are_provenance_not_runtime_inputs(self) -> None:
        self._write_receipt()
        manifest = self._manifest()
        manifest["files"] = [row for row in manifest["files"]
                             if row["name"] not in {export.source_name for export in self.exports}]
        for export in self.exports:
            (self.root / export.source_name).unlink()
        selected = select_standalone_pa_records(self.root, manifest, self.receipt_name)
        self.assertEqual([record.response_id for record in selected], [36, 37])
        receipt_path = self.root / self.receipt_name
        receipt = json.loads(receipt_path.read_text())
        receipt["responses"][0]["source"]["sha256"] = "A" * 64
        receipt_path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(StandalonePaResponseSetError, "receipt bytes differ"):
            select_standalone_pa_records(self.root, manifest, self.receipt_name)

    def test_retained_native_source_metadata_conflict_is_rejected_without_payload_reads(self) -> None:
        self._write_receipt()
        for field, value in (("name", "FIELD.pa36"), ("bytes", 999), ("sha256", "A" * 64)):
            manifest = self._manifest()
            source = next(row for row in manifest["files"] if row["name"] == "field.pa36")
            source[field] = value
            with (self.subTest(field=field),
                  patch("common.simion.standalone_pa_response_set._file_record",
                        side_effect=AssertionError("metadata check must not read PA")),
                  self.assertRaisesRegex(StandalonePaResponseSetError, "retained native response source identity differs")):
                validate_standalone_pa_response_set(self.root, manifest, self.receipt_name,
                                                     inventory_is_verified=True)

    def test_writer_uses_explicit_separate_native_source_directory(self) -> None:
        sources = self.root / "sources"
        sources.mkdir()
        for export in self.exports:
            (self.root / export.source_name).rename(sources / export.source_name)
        receipt = write_standalone_pa_response_set(
            self.root, self.exporter, self.exports, self.root / self.receipt_name,
            source_directory=sources,
        )
        self.assertEqual(receipt["schema_version"], 2)
        for item in receipt["responses"]:
            self.assertEqual(item["source"]["sha256"], file_sha256(sources / item["source"]["name"]))

    def test_v1_receipt_selects_manifest_bound_payload_without_rewriting(self) -> None:
        self._write_receipt()
        receipt_path = self.root / self.receipt_name
        receipt = json.loads(receipt_path.read_text())
        receipt["schema_version"] = 1
        receipt_path.write_text(json.dumps(receipt))
        manifest = self._manifest()
        before = {path: path.read_bytes() for path in self.root.iterdir()}
        selected = select_standalone_pa_records(self.root, manifest, self.receipt_name)
        self.assertEqual([record.response_id for record in selected], [36, 37])
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.iterdir()})

    def test_receipt_reader_rejects_unknown_or_noninteger_versions(self) -> None:
        self._write_receipt()
        path = self.root / self.receipt_name
        receipt = json.loads(path.read_text())
        for version in (True, False, 1.0, 2.0, "1", 0, 3):
            with self.subTest(version=version):
                path.write_text(json.dumps(dict(receipt, schema_version=version)))
                with self.assertRaisesRegex(StandalonePaResponseSetError, "identity differs"):
                    select_standalone_pa_records(self.root, self._manifest(), self.receipt_name)

    def test_v1_source_requires_exact_manifest_and_payload_identity(self) -> None:
        self._write_receipt()
        receipt_path = self.root / self.receipt_name
        receipt = json.loads(receipt_path.read_text())
        receipt["schema_version"] = 1
        receipt_path.write_text(json.dumps(receipt))
        original = self._manifest()
        source = self.root / self.exports[0].source_name
        for mutation in ("missing_record", "sha256", "bytes", "name"):
            manifest = copy.deepcopy(original)
            record = next(row for row in manifest["files"] if row["name"] == source.name)
            if mutation == "missing_record":
                manifest["files"].remove(record)
            else:
                record[mutation] = {"sha256": "A" * 64, "bytes": 999, "name": source.name.upper()}[mutation]
            with self.subTest(mutation=mutation), self.assertRaises(StandalonePaResponseSetError):
                validate_standalone_pa_response_set(self.root, manifest, self.receipt_name,
                    inventory_is_verified=True)
        with patch('common.simion.cache_generation.file_sha256', wraps=file_sha256) as hashed:
            selected = select_standalone_pa_records(self.root, original, self.receipt_name)
            self.assertEqual(hashed.call_count, 4)
        with patch('common.simion.cache_generation.file_sha256', side_effect=AssertionError("PA scan")):
            self.assertEqual(select_standalone_pa_records(self.root, original, self.receipt_name,
                verify_payload=False), selected)
        source.write_bytes(b"X" * source.stat().st_size)
        with self.assertRaisesRegex(StandalonePaResponseSetError, "native response source.*bytes differ"):
            select_standalone_pa_records(self.root, original, self.receipt_name)
        source.unlink()
        with self.assertRaisesRegex(StandalonePaResponseSetError, "file or byte length differs"):
            select_standalone_pa_records(self.root, original, self.receipt_name, verify_payload=False)

    def test_verified_inventory_binds_receipt_without_rehashing_payload(self) -> None:
        self._write_receipt()
        manifest = self._manifest()
        with patch(
            "common.simion.standalone_pa_response_set._file_record",
            side_effect=AssertionError("sealed inventory must not be rehashed"),
        ):
            selected = validate_standalone_pa_response_set(
                self.root,
                manifest,
                self.receipt_name,
                expected_response_ids=(36, 37),
                inventory_is_verified=True,
            )
        self.assertEqual([record.response_id for record in selected], [36, 37])
        self.assertEqual([record.response_id for record in selected], [36, 37])
        self.assertEqual(
            {record["name"] for record in manifest["files"]},
            {
                self.receipt_name,
                "field.pa#",
                "field.pa+",
                "field.pa36",
                "field.pa37",
                "field.response_36.pa",
                "field.response_37.pa",
            },
        )

    def test_selector_returns_only_exact_standalone_pa_outputs(self) -> None:
        self._write_receipt()
        selected = select_standalone_pa_records(
            self.root,
            self._manifest(),
            self.receipt_name,
            expected_response_ids=(36, 37),
        )
        self.assertEqual(
            [record.name for record in selected],
            ["field.response_36.pa", "field.response_37.pa"],
        )
        self.assertTrue(all(record.name.endswith(".pa") for record in selected))

    def test_selector_recovers_transient_standalone_reads(self) -> None:
        self._write_receipt()
        manifest = self._manifest()
        for name in ("field.response_36.pa",):
            target = self.root / name
            reads = 0

            def transient_digest(path: Path) -> str:
                nonlocal reads
                if path == target:
                    reads += 1
                    if reads == 1:
                        return "0" * 64
                return file_sha256(path)

            with (
                self.subTest(name=name),
                patch.object(cache_generation, "file_sha256", side_effect=transient_digest),
                patch.object(cache_generation, "PAYLOAD_VERIFICATION_RETRY_DELAY_S", 0),
            ):
                selected = select_standalone_pa_records(
                    self.root, manifest, self.receipt_name, expected_response_ids=(36, 37)
                )
                self.assertEqual([record.response_id for record in selected], [36, 37])
                self.assertEqual(reads, 3)

    def test_selector_rejects_persistent_same_size_standalone_hash_drift(self) -> None:
        self._write_receipt()
        manifest = self._manifest()
        target = self.root / "field.response_36.pa"
        target.write_bytes(b"x" * target.stat().st_size)
        with patch.object(cache_generation, "PAYLOAD_VERIFICATION_RETRY_DELAY_S", 0):
            with self.assertRaisesRegex(
                StandalonePaResponseSetError, "standalone response 36 bytes differ"
            ) as caught:
                select_standalone_pa_records(self.root, manifest, self.receipt_name)
        self.assertIsInstance(caught.exception.__cause__, ValueError)
        self.assertIn("field.response_36.pa", str(caught.exception.__cause__))
        self.assertEqual(str(caught.exception.__cause__).count("attempt="), 3)

    @unittest.skipUnless(cache_generation.os.name == "nt", "Windows PA snapshot recovery")
    def test_selector_recovers_only_manifest_matching_persisted_snapshot(self) -> None:
        self._write_receipt()
        manifest = self._manifest()
        target = self.root / "field.response_36.pa"
        original = target.read_bytes()

        def stale_digest(path: Path) -> str:
            return "D" * 64 if path == target else file_sha256(path)

        with (
            patch.object(cache_generation, "_WINDOWS_UNBUFFERED_COPY_THRESHOLD_BYTES", 0),
            patch.object(cache_generation, "file_sha256", side_effect=stale_digest),
            patch.object(cache_generation, "PAYLOAD_VERIFICATION_RETRY_DELAY_S", 0),
            patch.object(
                cache_generation, "_flush_writable_source",
                side_effect=AssertionError("immutable verification must not flush source"),
            ),
        ):
            selected = select_standalone_pa_records(self.root, manifest, self.receipt_name)
            self.assertEqual([record.response_id for record in selected], [36, 37])
            self.assertEqual(target.read_bytes(), original)
            target.write_bytes(b"x" * len(original))
            with self.assertRaisesRegex(StandalonePaResponseSetError, "bytes differ"):
                select_standalone_pa_records(self.root, manifest, self.receipt_name)

    def test_pa_family_cache_v2_inventory_is_accepted(self) -> None:
        """A PA-family cache uses the same sealed direct-file record schema."""
        self._write_receipt()
        manifest = self._manifest()
        manifest["schema_version"] = 2
        selected = select_standalone_pa_records(
            self.root,
            manifest,
            self.receipt_name,
            expected_response_ids=(36, 37),
        )
        self.assertEqual(
            [record.name for record in selected],
            ["field.response_36.pa", "field.response_37.pa"],
        )

    def test_writer_rejects_native_output_and_mismatched_or_duplicate_identity(self) -> None:
        invalid_sets = (
            (ResponseExport(36, "field.pa36", "field.pa38"),),
            (ResponseExport(37, "field.pa36", "field.response_37.pa"),),
            (self.exports[0], self.exports[0]),
        )
        for index, exports in enumerate(invalid_sets):
            with self.subTest(index=index), self.assertRaises(StandalonePaResponseSetError):
                write_standalone_pa_response_set(
                    self.root,
                    self.exporter,
                    exports,
                    self.root / f"invalid_{index}.json",
                    source_directory=self.root,
                )

    def test_validation_rejects_missing_manifest_coverage_and_byte_drift(self) -> None:
        self._write_receipt()
        manifest = self._manifest()
        manifest["files"] = [
            record
            for record in manifest["files"]
            if record["name"] != "field.response_37.pa"
        ]
        with self.assertRaisesRegex(
            StandalonePaResponseSetError, "not exactly covered by manifest"
        ):
            validate_standalone_pa_response_set(
                self.root, manifest, self.receipt_name
            )

        manifest = self._manifest()
        (self.root / "field.response_36.pa").write_bytes(b"drift")
        with self.assertRaisesRegex(StandalonePaResponseSetError, "bytes differ"):
            validate_standalone_pa_response_set(
                self.root, manifest, self.receipt_name
            )

    def test_validation_rejects_receipt_drift_policy_and_expected_ids(self) -> None:
        self._write_receipt()
        manifest = self._manifest()
        with self.assertRaisesRegex(StandalonePaResponseSetError, "ids differ"):
            validate_standalone_pa_response_set(
                self.root,
                manifest,
                self.receipt_name,
                expected_response_ids=(36,),
            )
        with self.assertRaisesRegex(StandalonePaResponseSetError, "identity differs"):
            validate_standalone_pa_response_set(
                self.root,
                manifest,
                self.receipt_name,
                expected_policy_id=POLICY_ID + "-changed",
            )

        receipt = json.loads((self.root / self.receipt_name).read_text())
        receipt["responses"].reverse()
        (self.root / self.receipt_name).write_text(json.dumps(receipt))
        changed_manifest = self._manifest()
        with self.assertRaisesRegex(StandalonePaResponseSetError, "ordered"):
            validate_standalone_pa_response_set(
                self.root, changed_manifest, self.receipt_name
            )


if __name__ == "__main__":
    unittest.main()
