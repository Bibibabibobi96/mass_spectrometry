from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from common.simion.cache_generation import (
    generation_input,
    generation_sha256,
    inventory_direct_files,
    payload_sha256,
    validate_direct_inventory,
)

REPO = Path(__file__).resolve().parents[2]


class CacheGenerationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
