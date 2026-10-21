from __future__ import annotations

import json
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

    def test_two_stage_receipt_and_manifest_cover_native_and_standalone_files(self) -> None:
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

    def test_selector_recovers_transient_native_and_standalone_reads(self) -> None:
        self._write_receipt()
        manifest = self._manifest()
        for name in ("field.pa36", "field.response_36.pa"):
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

    def test_selector_rejects_persistent_same_size_native_hash_drift(self) -> None:
        self._write_receipt()
        manifest = self._manifest()
        target = self.root / "field.pa36"
        target.write_bytes(b"x" * target.stat().st_size)
        with patch.object(cache_generation, "PAYLOAD_VERIFICATION_RETRY_DELAY_S", 0):
            with self.assertRaisesRegex(
                StandalonePaResponseSetError, "native response 36 bytes differ"
            ) as caught:
                select_standalone_pa_records(self.root, manifest, self.receipt_name)
        self.assertIsInstance(caught.exception.__cause__, ValueError)
        self.assertIn("field.pa36", str(caught.exception.__cause__))
        self.assertEqual(str(caught.exception.__cause__).count("attempt="), 3)

    @unittest.skipUnless(cache_generation.os.name == "nt", "Windows PA snapshot recovery")
    def test_selector_recovers_only_manifest_matching_persisted_snapshot(self) -> None:
        self._write_receipt()
        manifest = self._manifest()
        target = self.root / "field.pa36"
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
