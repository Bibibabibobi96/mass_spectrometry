from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import common.simion.cache_generation as cache_generation

from common.simion.cache_generation import (
    generation_input,
    generation_sha256,
    inventory_direct_files,
    materialize_direct_inventory,
    payload_sha256,
    stable_inventory_direct_files,
    validate_direct_inventory,
)

REPO = Path(__file__).resolve().parents[2]


class CacheGenerationTests(unittest.TestCase):
    def test_stable_inventory_requires_two_identical_full_passes(self) -> None:
        first = [{"name": "family.pa0", "bytes": 1, "sha256": "A" * 64}]
        second = [{"name": "family.pa0", "bytes": 1, "sha256": "B" * 64}]
        with patch.object(
            cache_generation,
            "inventory_direct_files",
            side_effect=[first, second],
        ) as inventory:
            with self.assertRaisesRegex(ValueError, "changed between stability passes"):
                stable_inventory_direct_files("unused", exclude=("manifest.json",))
        self.assertEqual(inventory.call_count, 2)

    def test_stable_inventory_returns_the_second_matching_pass(self) -> None:
        records = [{"name": "family.pa0", "bytes": 1, "sha256": "A" * 64}]
        with patch.object(
            cache_generation,
            "inventory_direct_files",
            side_effect=[records, [dict(records[0])]],
        ) as inventory:
            stable = stable_inventory_direct_files("unused")
        self.assertEqual(stable, records)
        self.assertEqual(inventory.call_count, 2)

    def test_materialization_is_complete_writable_and_source_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "run" / "family"
            source.mkdir()
            for name, payload in (
                ("family.pa0", b"zero"),
                ("family.pa36", b"mode-36"),
                ("family.pa43", b"mode-43"),
            ):
                (source / name).write_bytes(payload)
                (source / name).chmod(0o444)
            records = inventory_direct_files(source)
            copied = materialize_direct_inventory(source, destination, records)
            self.assertEqual(copied, records)
            for record in records:
                target = destination / record["name"]
                self.assertTrue(target.stat().st_mode & 0o200)
            (destination / "family.pa36").write_bytes(b"private mutation")
            self.assertEqual((source / "family.pa36").read_bytes(), b"mode-36")
            with self.assertRaisesRegex(ValueError, "overwrite"):
                materialize_direct_inventory(source, destination, records)

    def test_existing_destination_fails_before_payload_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "run" / "family"
            source.mkdir()
            destination.mkdir(parents=True)
            (source / "family.pa0").write_bytes(b"payload")
            records = inventory_direct_files(source)
            with patch.object(cache_generation, "_copy_verified_file") as copy_file:
                with self.assertRaisesRegex(ValueError, "overwrite"):
                    materialize_direct_inventory(source, destination, records)
            copy_file.assert_not_called()

    def test_materialization_accepts_uppercase_manifest_digests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "run" / "family"
            source.mkdir()
            (source / "family.pa0").write_bytes(b"payload")
            records = inventory_direct_files(source)
            records[0]["sha256"] = records[0]["sha256"].lower()
            copied = materialize_direct_inventory(source, destination, records)
            self.assertEqual(copied[0]["sha256"], records[0]["sha256"].upper())
            self.assertEqual((destination / "family.pa0").read_bytes(), b"payload")

    @unittest.skipUnless(__import__("os").name == "nt", "Windows path regression")
    def test_materialization_supports_run_length_windows_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "accelerator_main.processed.gem").write_bytes(b"payload")
            parent = root
            while len(str(parent / ".family.staging-" / "accelerator_main.processed.gem")) < 300:
                parent /= "run_path_padding"
            destination = parent / "family"
            copied = materialize_direct_inventory(
                source, destination, inventory_direct_files(source)
            )
            self.assertEqual(copied[0]["bytes"], len(b"payload"))

    def test_materialization_rejects_source_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "family.pa0").write_bytes(b"original")
            records = inventory_direct_files(source)
            (source / "family.pa0").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "differs"):
                materialize_direct_inventory(source, root / "run", records)

    def test_materialization_publishes_the_complete_directory_in_one_rename(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "run" / "family"
            source.mkdir()
            (source / "family.pa0").write_bytes(b"zero")
            (source / "family.pa36").write_bytes(b"mode")
            records = inventory_direct_files(source)
            real_replace = cache_generation.os.replace
            replacements: list[tuple[Path, Path]] = []

            def recording_replace(old: str | Path, new: str | Path) -> None:
                replacements.append((Path(old), Path(new)))
                real_replace(old, new)

            with patch.object(cache_generation.os, "replace", side_effect=recording_replace):
                materialize_direct_inventory(source, destination, records)
            self.assertEqual(len(replacements), 1)
            self.assertEqual(replacements[0][1], destination)
            self.assertTrue(replacements[0][0].name.startswith(".family.staging-"))

    def test_source_drift_during_copy_leaves_no_destination_or_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "run" / "family"
            source.mkdir()
            payload = source / "family.pa0"
            payload.write_bytes(b"original")
            records = inventory_direct_files(source)
            real_copy = cache_generation._copy_verified_file

            def mutate_then_copy(old: Path, new: Path) -> dict[str, object]:
                old.write_bytes(b"changed")
                return real_copy(old, new)

            with patch.object(cache_generation, "_copy_verified_file", side_effect=mutate_then_copy):
                with self.assertRaisesRegex(ValueError, "differs from its manifest"):
                    materialize_direct_inventory(source, destination, records)
            self.assertFalse(destination.exists())
            self.assertEqual(list((root / "run").glob(".*.staging-*")), [])

    def test_copy_failure_cleans_a_read_only_staging_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "run" / "family"
            source.mkdir()
            payload = source / "family.pa0"
            payload.write_bytes(b"original")
            payload.chmod(0o444)
            records = inventory_direct_files(source)
            with patch.object(
                cache_generation,
                "_make_file_writable",
                side_effect=RuntimeError("simulated writable-attribute failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "writable-attribute"):
                    materialize_direct_inventory(source, destination, records)
            self.assertFalse(destination.exists())
            self.assertEqual(list((root / "run").glob(".*.staging-*")), [])

    def test_inventory_and_v3_digests_match_frozen_compact_json_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "b.pa1").write_bytes(b"b")
            (root / "a.pa0").write_bytes(b"aa")
            records = inventory_direct_files(root)
        self.assertEqual([record["name"] for record in records], ["a.pa0", "b.pa1"])
        expected_payload = hashlib.sha256(
            b'[{"name":"a.pa0","bytes":2,"sha256":"'
            + records[0]["sha256"].encode("ascii")
            + b'"},{"name":"b.pa1","bytes":1,"sha256":"'
            + records[1]["sha256"].encode("ascii")
            + b'"}]'
        ).hexdigest()
        self.assertEqual(payload_sha256(records), expected_payload)
        cache_key = "a" * 64
        input_text = generation_input(cache_key, expected_payload, "run-1")
        self.assertEqual(
            input_text,
            '{"schema_version":1,"cache_key":"' + cache_key
            + '","payload_sha256":"' + expected_payload + '","provider_run_id":"run-1"}',
        )
        self.assertEqual(
            generation_sha256(input_text), hashlib.sha256(input_text.encode("utf-8")).hexdigest()
        )

    def test_rejects_extra_fields_duplicate_and_nested_names(self) -> None:
        digest = "a" * 64
        for records in (
            [{"name": "x.pa0", "bytes": 1, "sha256": digest, "extra": 1}],
            [{"name": "x.pa0", "bytes": 1, "sha256": digest}, {"name": "x.pa0", "bytes": 1, "sha256": digest}],
            [{"name": "nested/x.pa0", "bytes": 1, "sha256": digest}],
        ):
            with self.assertRaises(ValueError):
                validate_direct_inventory(records)

    def test_cli_emits_the_same_v3_description(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "family.pa0").write_bytes(b"payload")
            completed = subprocess.run(
                [
                    "python", "-m", "common.simion.cache_generation",
                    "--directory", str(root), "--cache-key", "b" * 64,
                    "--provider-run-id", "run-2",
                ],
                text=True, encoding="utf-8", capture_output=True, check=True, cwd=REPO, timeout=30,
            )
        document = json.loads(completed.stdout)
        self.assertEqual(document["payload_sha256"], payload_sha256(document["files"]))
        self.assertEqual(document["generation_sha256"], generation_sha256(document["generation_input"]))

    def test_cli_rejects_stability_flag_in_materialization_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "family.pa0").write_bytes(b"payload")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps({"files": inventory_direct_files(source)}), encoding="utf-8"
            )
            completed = subprocess.run(
                [
                    "python",
                    "-m",
                    "common.simion.cache_generation",
                    "--directory",
                    str(source),
                    "--materialize-manifest",
                    str(manifest),
                    "--destination",
                    str(root / "destination"),
                    "--require-stable-inventory",
                ],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
                cwd=REPO,
                timeout=30,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertIn(
            "materialization does not accept digest-generation arguments",
            completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
