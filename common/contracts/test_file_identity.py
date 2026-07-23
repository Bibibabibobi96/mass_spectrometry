from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import HASH_CHUNK_BYTES, file_sha256
from common.contracts import (
    migrate_artifacts_v2,
    write_formal_asset_manifest,
    write_run_manifest,
)


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
            self.assertEqual(
                json.dumps(migrate_artifacts_v2.file_record(path), separators=(",", ":")),
                json.dumps(expected_absolute, separators=(",", ":")),
            )
            for actual in (
                migrate_artifacts_v2.relative_file_record(path, root),
                write_formal_asset_manifest.record(path, root),
            ):
                self.assertEqual(
                    json.dumps(actual, separators=(",", ":")),
                    json.dumps(expected_relative, separators=(",", ":")),
                )


if __name__ == "__main__":
    unittest.main()
