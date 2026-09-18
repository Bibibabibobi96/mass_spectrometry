"""Tests for immutable equal-length PA XOR parity recovery."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from common.simion.immutable_pa_parity import (
    ImmutablePaParityError,
    create_xor_parity_bundle,
    verify_and_recover_xor_parity,
)


class ImmutablePaParityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.generation = self.root / "generation"
        self.generation.mkdir()
        self.payloads = {
            "field.pa0": bytes(range(97)),
            "field.pa1": bytes((value * 3 + 7) % 256 for value in range(97)),
            "field.pa2": bytes((value * 5 + 11) % 256 for value in range(97)),
        }
        for name, payload in self.payloads.items():
            (self.generation / name).write_bytes(payload)
        self.bundle = self.root / "parity"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def build(self) -> dict[str, object]:
        return create_xor_parity_bundle(
            self.generation,
            list(reversed(self.payloads)),
            self.bundle,
            chunk_bytes=13,
        )

    def test_streaming_bundle_records_members_and_parity(self) -> None:
        manifest = self.build()
        self.assertEqual([record["name"] for record in manifest["members"]], sorted(self.payloads))
        for record in manifest["members"]:
            payload = self.payloads[record["name"]]
            self.assertEqual(record["bytes"], len(payload))
            self.assertEqual(record["sha256"], hashlib.sha256(payload).hexdigest().upper())
        expected = bytes(
            first ^ second ^ third
            for first, second, third in zip(*[self.payloads[name] for name in sorted(self.payloads)], strict=True)
        )
        self.assertEqual((self.bundle / "payload.xor").read_bytes(), expected)
        self.assertEqual(
            json.loads((self.bundle / "xor_parity_manifest.json").read_text(encoding="utf-8")),
            manifest,
        )

    def test_intact_group_does_not_create_recovery_staging(self) -> None:
        self.build()
        staging = self.root / "recovered"
        result = verify_and_recover_xor_parity(
            self.generation, self.bundle, staging, chunk_bytes=11
        )
        self.assertEqual(result.status, "intact")
        self.assertFalse(staging.exists())

    def test_recovers_one_corrupt_member_without_modifying_generation(self) -> None:
        self.build()
        damaged = self.generation / "field.pa1"
        damaged.write_bytes(b"X" * len(self.payloads[damaged.name]))
        staging = self.root / "recovered"
        result = verify_and_recover_xor_parity(
            self.generation, self.bundle, staging, chunk_bytes=17
        )
        self.assertEqual(result.status, "recovered")
        self.assertEqual(result.damaged_name, damaged.name)
        self.assertEqual(result.recovered_path.read_bytes(), self.payloads[damaged.name])
        self.assertEqual(result.recovered_bytes, len(self.payloads[damaged.name]))
        self.assertEqual(
            result.recovered_sha256,
            hashlib.sha256(self.payloads[damaged.name]).hexdigest().upper(),
        )
        self.assertEqual(damaged.read_bytes(), b"X" * len(self.payloads[damaged.name]))
        self.assertEqual([path.name for path in staging.iterdir()], [damaged.name])

    def test_recovers_one_missing_member(self) -> None:
        self.build()
        missing = self.generation / "field.pa2"
        missing.unlink()
        result = verify_and_recover_xor_parity(
            self.generation, self.bundle, self.root / "recovered", chunk_bytes=19
        )
        self.assertEqual(result.recovered_path.read_bytes(), self.payloads[missing.name])
        self.assertFalse(missing.exists())

    def test_single_member_bundle_is_a_recoverable_replica(self) -> None:
        single = self.root / "single"
        single.mkdir()
        payload = bytes((value * 7 + 3) % 256 for value in range(101))
        (single / "only.pa").write_bytes(payload)
        bundle = self.root / "single-parity"
        manifest = create_xor_parity_bundle(
            single, ["only.pa"], bundle, chunk_bytes=17
        )
        self.assertEqual(manifest["members"][0]["name"], "only.pa")
        self.assertEqual((bundle / "payload.xor").read_bytes(), payload)
        (single / "only.pa").unlink()
        recovered = verify_and_recover_xor_parity(
            single, bundle, self.root / "single-recovered", chunk_bytes=19
        )
        self.assertEqual(recovered.recovered_path.read_bytes(), payload)

    def test_two_bad_members_fail_closed_without_staging(self) -> None:
        self.build()
        (self.generation / "field.pa0").write_bytes(b"A" * 97)
        (self.generation / "field.pa1").write_bytes(b"B" * 97)
        staging = self.root / "recovered"
        with self.assertRaisesRegex(ImmutablePaParityError, "exactly one"):
            verify_and_recover_xor_parity(self.generation, self.bundle, staging)
        self.assertFalse(staging.exists())

    def test_bad_parity_fails_closed_without_staging(self) -> None:
        self.build()
        (self.bundle / "payload.xor").write_bytes(b"P" * 97)
        (self.generation / "field.pa1").write_bytes(b"B" * 97)
        staging = self.root / "recovered"
        with self.assertRaisesRegex(ImmutablePaParityError, "parity payload is damaged"):
            verify_and_recover_xor_parity(self.generation, self.bundle, staging)
        self.assertFalse(staging.exists())

    def test_reconstructed_member_must_match_target_sha(self) -> None:
        manifest = self.build()
        manifest["members"][1]["sha256"] = "0" * 64
        (self.bundle / "xor_parity_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        staging = self.root / "recovered"
        with self.assertRaisesRegex(ImmutablePaParityError, "frozen identity"):
            verify_and_recover_xor_parity(self.generation, self.bundle, staging)
        self.assertFalse(staging.exists())

    def test_creation_rejects_unequal_lengths_and_cleans_staging(self) -> None:
        (self.generation / "field.pa2").write_bytes(b"short")
        with self.assertRaisesRegex(ImmutablePaParityError, "common byte length"):
            self.build()
        self.assertFalse(self.bundle.exists())
        self.assertEqual(list(self.root.glob(".parity.staging-*")), [])

    def test_member_names_are_direct_and_case_insensitively_unique(self) -> None:
        with self.assertRaisesRegex(ImmutablePaParityError, "direct filename"):
            create_xor_parity_bundle(
                self.generation, ["..", "field.pa1"], self.bundle
            )
        with self.assertRaisesRegex(ImmutablePaParityError, "unique"):
            create_xor_parity_bundle(
                self.generation, ["field.pa0", "FIELD.PA0"], self.bundle
            )

    def test_recovery_cannot_target_published_generation(self) -> None:
        self.build()
        (self.generation / "field.pa1").write_bytes(b"B" * 97)
        with self.assertRaisesRegex(ImmutablePaParityError, "outside the immutable generation"):
            verify_and_recover_xor_parity(
                self.generation, self.bundle, self.generation / "repair"
            )
        self.assertFalse((self.generation / "repair").exists())

    def test_existing_recovery_staging_is_never_overwritten(self) -> None:
        self.build()
        (self.generation / "field.pa1").write_bytes(b"B" * 97)
        staging = self.root / "recovered"
        staging.mkdir()
        marker = staging / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ImmutablePaParityError, "already exists"):
            verify_and_recover_xor_parity(self.generation, self.bundle, staging)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
