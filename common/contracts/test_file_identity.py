from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from common.contracts.file_identity import (
    HASH_CHUNK_BYTES,
    canonical_json_sha256,
    file_sha256,
    file_sha256_unbuffered,
    files_have_same_identity,
    files_match_manifest_records,
    repository_text_sha256,
)
from common.contracts import write_formal_asset_manifest, write_run_manifest
from common.contracts import file_identity


def legacy_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


class FileIdentityTest(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "requires Windows unbuffered file API")
    def test_unbuffered_cli_reports_digest_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cli file.bin"
            payload = b"cli unbuffered identity" * 257
            path.write_bytes(payload)
            command = [sys.executable, "-m", "common.contracts.file_identity", "--unbuffered"]
            repo_root = Path(__file__).resolve().parents[2]
            result = subprocess.run(command + [str(path)], cwd=repo_root, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), hashlib.sha256(payload).hexdigest().upper())
            missing = subprocess.run(command + [str(path.with_name("missing.bin"))], cwd=repo_root, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(missing.returncode, 0)
            self.assertEqual(missing.stdout, "")
            conflict = subprocess.run(command + [str(path), "--left", str(path)], cwd=repo_root, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(conflict.returncode, 0)

    @unittest.skipUnless(os.name == "nt", "requires Windows unbuffered file API")
    def test_unbuffered_matches_hashlib_at_sector_and_chunk_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unbuffered.bin"
            for size in (0, 1, 511, 512, 513, 4095, 4096, 4097,
                         HASH_CHUNK_BYTES - 1, HASH_CHUNK_BYTES, HASH_CHUNK_BYTES + 1,
                         2 * HASH_CHUNK_BYTES + 37):
                with self.subTest(size=size):
                    payload = (bytes(range(256)) * ((size + 255) // 256))[:size]
                    path.write_bytes(payload)
                    self.assertEqual(file_sha256_unbuffered(path), hashlib.sha256(payload).hexdigest().upper())
                    self.assertEqual(path.read_bytes(), payload)

    @unittest.skipUnless(os.name == "nt", "requires Windows unbuffered file API")
    def test_unbuffered_failures_release_handle_and_allocation(self) -> None:
        import ctypes

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failure.bin"
            path.write_bytes(b"fixture")
            for stage in ("GetFileSizeEx", "GetFileInformationByHandleEx", "VirtualAlloc", "ReadFile", "short_read", "digest"):
                with self.subTest(stage=stage):
                    api = file_identity._windows_file_api()
                    wrapped = mock.Mock(wraps=api)
                    if stage == "short_read":
                        wrapped.ReadFile.return_value = 1
                    elif stage != "digest":
                        def fail(*args):
                            ctypes.set_last_error(5)
                            return 0
                        getattr(wrapped, stage).side_effect = fail
                    with mock.patch.object(file_identity, "_windows_file_api", return_value=wrapped):
                        if stage == "digest":
                            with mock.patch.object(file_identity.hashlib, "sha256", side_effect=RuntimeError("digest failure")):
                                with self.assertRaisesRegex(RuntimeError, "digest failure"):
                                    file_sha256_unbuffered(path)
                        else:
                            with self.assertRaises(OSError):
                                file_sha256_unbuffered(path)
                    self.assertEqual(wrapped.CloseHandle.call_count, 1)
                    self.assertEqual(wrapped.VirtualFree.call_count, int(stage in {"ReadFile", "short_read", "digest"}))
                    # The fixture is writable again only after the denied-write handle closes.
                    path.write_bytes(b"fixture")

    @unittest.skipUnless(os.name == "nt", "requires Windows unbuffered file API")
    def test_unbuffered_denies_writers_and_replacement_while_reading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "protected.bin"
            path.write_bytes(b"fixture")
            api = file_identity._windows_file_api()
            wrapped = mock.Mock(wraps=api)

            def read(*args):
                with self.assertRaises(OSError):
                    path.write_bytes(b"changed")
                with self.assertRaises(OSError):
                    path.unlink()
                return api.ReadFile(*args)

            wrapped.ReadFile.side_effect = read
            with mock.patch.object(file_identity, "_windows_file_api", return_value=wrapped):
                self.assertEqual(file_sha256_unbuffered(path), hashlib.sha256(b"fixture").hexdigest().upper())
            with path.open("r+b"):
                with self.assertRaises(OSError):
                    file_sha256_unbuffered(path)

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
