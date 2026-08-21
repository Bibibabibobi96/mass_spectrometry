from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import (
    HASH_CHUNK_BYTES,
    canonical_json_sha256,
    file_sha256,
    files_have_same_identity,
    files_match_manifest_records,
    repository_text_sha256,
)
from common.contracts import write_formal_asset_manifest, write_run_manifest


def legacy_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


class FileIdentityTest(unittest.TestCase):
    def test_fixed_content_and_empty_file_match_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in (("empty.bin", b""), ("fixed.bin", b"mass-spectrometry\n")):
                path = root / name
                path.write_bytes(content)
                self.assertEqual(file_sha256(path), hashlib.sha256(content).hexdigest().upper())

    def test_cross_chunk_file_is_streamed_without_digest_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cross_chunk.bin"
            content = b"A" * HASH_CHUNK_BYTES + b"B" * 37
            path.write_bytes(content)
            self.assertEqual(file_sha256(path), hashlib.sha256(content).hexdigest().upper())

    def test_path_and_string_inputs_preserve_uppercase_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.bin"
            path.write_bytes(b"case-sensitive-hex")
            expected = legacy_sha256(path)
            self.assertEqual(file_sha256(path), expected)
            self.assertEqual(file_sha256(str(path)), expected)
            self.assertEqual(file_sha256(path), file_sha256(path).upper())
            self.assertTrue(any(character in "ABCDEF" for character in expected))

    def test_missing_file_preserves_file_not_found_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                file_sha256(Path(directory) / "missing.bin")

    def test_repository_text_identity_is_line_ending_invariant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lf = root / "lf.json"
            crlf = root / "crlf.json"
            legacy_cr = root / "cr.json"
            lf.write_bytes(b'{"value": 1}\n')
            crlf.write_bytes(b'{"value": 1}\r\n')
            legacy_cr.write_bytes(b'{"value": 1}\r')
            expected = repository_text_sha256(lf)
            self.assertEqual(repository_text_sha256(crlf), expected)
            self.assertEqual(repository_text_sha256(legacy_cr), expected)
            self.assertNotEqual(file_sha256(crlf), expected)

    def test_canonical_json_identity_ignores_mapping_order_and_rejects_nan(self) -> None:
        self.assertEqual(
            canonical_json_sha256({"a": [1, 2], "b": "ion"}),
            canonical_json_sha256({"b": "ion", "a": [1, 2]}),
        )
        with self.assertRaises(ValueError):
            canonical_json_sha256({"nonfinite": float("nan")})

    def test_manifest_record_fields_are_byte_for_byte_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "payload.bin"
            path.write_bytes(b"manifest-record-contract")
            digest = legacy_sha256(path)
            expected_absolute = {
                "path": str(path),
                "exists": True,
                "bytes": path.stat().st_size,
                "sha256": digest,
            }
            expected_relative = {
                "path": "payload.bin",
                "bytes": path.stat().st_size,
                "sha256": digest,
            }
            self.assertEqual(
                json.dumps(write_run_manifest.file_record(path), separators=(",", ":")),
                json.dumps(expected_absolute, separators=(",", ":")),
            )
            for actual in (write_formal_asset_manifest.record(path, root),):
                self.assertEqual(
                    json.dumps(actual, separators=(",", ":")),
                    json.dumps(expected_relative, separators=(",", ":")),
                )

    def test_manifest_record_comparison_is_shared_byte_identity_primitive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "payload.bin"
            payload.write_bytes(b"cached-pa-bytes")
            record = {
                "name": payload.name,
                "bytes": payload.stat().st_size,
                "sha256": file_sha256(payload),
            }
            self.assertTrue(files_match_manifest_records(root, [record]))
            record["sha256"] = "0" * 64
            self.assertFalse(files_match_manifest_records(root, [record]))

    def test_pair_comparison_uses_size_then_shared_byte_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left, same, different = root / "left.bin", root / "same.bin", root / "other.bin"
            left.write_bytes(b"same bytes")
            same.write_bytes(b"same bytes")
            different.write_bytes(b"different!")
            self.assertTrue(files_have_same_identity(left, same))
            self.assertFalse(files_have_same_identity(left, different))


if __name__ == "__main__":
    unittest.main()
