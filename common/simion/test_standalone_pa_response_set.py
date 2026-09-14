from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.file_identity import file_sha256
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
