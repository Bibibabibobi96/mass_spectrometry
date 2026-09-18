"""Regression tests for the device-neutral SIMION PA-family cache."""
from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import common.simion.cache_generation as cache_generation
import common.simion.pa_family_cache as pa_family_cache

from common.simion.pa_family_cache import (
    CacheDisposition,
    PAFamilyCacheError,
    canonical_pa_family_cache_key,
    materialize_pa_family_cache,
    main,
    pa_family_inventory,
    probe_pa_family_cache,
    publish_pa_family_cache,
    repair_pa_family_cache_generation,
    validate_pa_family_cache_generation,
    validate_pa_family_cache_subset,
)


def identity() -> dict[str, object]:
    return {
        "geometry": {"resolved_sha256": "A" * 64},
        "gem": {"sha256": "B" * 64},
        "basis_namespace": {"ids": [0, 1, 2]},
        "mesh": {"mm_per_gu": [1, 1, 1]},
        "grid_phase": {"origin_mm": [0, 0, 0]},
        "surface": "none",
        "simion_identity": {"release": "2020"},
        "refine_policy": {"iterations": 1000},
        "builder_identity": {"sha256": "C" * 64},
    }


class PAFamilyCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "field.pa#").write_bytes(b"raw")
        (self.source / "field.pa0").write_bytes(b"zero")
        (self.source / "field.pa1").write_bytes(b"one")
        self.names = ("field.pa#", "field.pa0", "field.pa1")
        self.cache = self.root / "cache"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_key_covers_every_required_identity_dimension(self) -> None:
        original = canonical_pa_family_cache_key(identity())
        for field in identity():
            changed = identity()
            changed[field] = {"changed": field}
            self.assertNotEqual(original, canonical_pa_family_cache_key(changed), field)
        missing = identity()
        del missing["mesh"]
        with self.assertRaisesRegex(PAFamilyCacheError, "identity fields"):
            canonical_pa_family_cache_key(missing)

    def test_publish_hit_validate_and_materialize_with_hashes(self) -> None:
        first = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        self.assertEqual(first.disposition, CacheDisposition.PUBLISHED)
        self.assertFalse((first.generation_directory / "field.pa1").stat().st_mode & stat.S_IWUSR)
        self.assertFalse((first.generation_directory / "cache_manifest.json").stat().st_mode & stat.S_IWUSR)
        self.assertEqual(probe_pa_family_cache(self.cache, identity(), expected_filenames=self.names).disposition, CacheDisposition.HIT)
        manifest = validate_pa_family_cache_generation(first.generation_directory, expected_filenames=self.names)
        self.assertEqual(manifest["files"], pa_family_inventory(self.source, self.names))
        second = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        self.assertEqual(second.disposition, CacheDisposition.HIT)
        local = materialize_pa_family_cache(first.generation_directory, self.root / "run" / "simion", expected_filenames=self.names)
        self.assertEqual(local.files, tuple(manifest["files"]))
        self.assertEqual(pa_family_inventory(local.destination_directory, self.names), manifest["files"])
        self.assertTrue((local.destination_directory / "field.pa1").stat().st_mode & stat.S_IWUSR)

    def test_v2_publication_has_bound_parity_and_repairs_one_member(self) -> None:
        published = publish_pa_family_cache(
            self.cache, identity(), self.source, self.names
        )
        self.assertEqual(published.manifest["schema_version"], 2)
        self.assertNotEqual(published.manifest["redundancy"]["groups"], [])
        recovery_root = (
            published.generation_directory.parents[1]
            / "recovery"
            / published.generation_sha256
        )
        self.assertTrue(recovery_root.is_dir())

        damaged = published.generation_directory / "field.pa1"
        damaged.chmod(damaged.stat().st_mode | stat.S_IWUSR)
        damaged.write_bytes(b"bad")
        with self.assertRaisesRegex(PAFamilyCacheError, "field.pa1"):
            validate_pa_family_cache_generation(published.generation_directory)

        repaired = repair_pa_family_cache_generation(
            published.generation_directory
        )
        self.assertEqual(repaired.repaired_member, "field.pa1")
        self.assertEqual(repaired.predecessor_directory, published.generation_directory)
        self.assertTrue(repaired.predecessor_directory.is_dir())
        self.assertNotEqual(repaired.generation_sha256, published.generation_sha256)
        self.assertTrue(repaired.receipt_path.is_file())
        self.assertEqual(
            validate_pa_family_cache_generation(
                repaired.generation_directory, expected_filenames=self.names
            )["generation_sha256"],
            repaired.generation_sha256,
        )
        self.assertEqual(
            (repaired.generation_directory / "field.pa1").read_bytes(), b"one"
        )

    def test_v2_parity_corruption_is_detected_and_never_repairs_payload(self) -> None:
        published = publish_pa_family_cache(
            self.cache, identity(), self.source, self.names
        )
        group = published.manifest["redundancy"]["groups"][0]
        parity = (
            published.generation_directory.parents[1]
            / "recovery"
            / published.generation_sha256
            / group["bundle"]
            / "payload.xor"
        )
        parity.chmod(parity.stat().st_mode | stat.S_IWUSR)
        parity.write_bytes(b"X" * parity.stat().st_size)
        with self.assertRaisesRegex(PAFamilyCacheError, "redundancy payload differs"):
            validate_pa_family_cache_generation(published.generation_directory)
        pointer = published.generation_directory.parents[1] / "current_generation.json"
        before = pointer.read_bytes()
        with self.assertRaisesRegex(PAFamilyCacheError, "redundancy payload differs"):
            repair_pa_family_cache_generation(published.generation_directory)
        self.assertEqual(pointer.read_bytes(), before)
        self.assertTrue(published.generation_directory.is_dir())

    def test_publish_migrates_valid_v1_to_distinct_v2_successor(self) -> None:
        key = canonical_pa_family_cache_key(identity())
        records = pa_family_inventory(self.source, self.names)
        legacy_manifest = pa_family_cache._manifest(key, identity(), records)
        legacy = self.cache / key / "generations" / legacy_manifest["generation_sha256"]
        legacy.mkdir(parents=True)
        for record in records:
            cache_generation.copy_verified_file(
                self.source / record["name"], legacy / record["name"]
            )
        (legacy / "cache_manifest.json").write_text(
            json.dumps(legacy_manifest, sort_keys=True), encoding="utf-8"
        )
        pa_family_cache._seal_generation_files(legacy, legacy_manifest)
        pa_family_cache._publish_pointer(
            legacy.parents[1], key, legacy_manifest["generation_sha256"]
        )

        migrated = publish_pa_family_cache(
            self.cache, identity(), self.source, self.names
        )
        self.assertEqual(migrated.manifest["schema_version"], 2)
        self.assertNotEqual(migrated.generation_directory, legacy)
        self.assertEqual(
            migrated.manifest["predecessor_generation_sha256"], legacy.name
        )
        self.assertTrue(legacy.is_dir())
        self.assertEqual(
            json.loads(
                (legacy.parents[1] / "current_generation.json").read_text(
                    encoding="utf-8"
                )
            )["generation_sha256"],
            migrated.generation_sha256,
        )

    def test_materialization_copy_failure_removes_partial_destination_and_staging(self) -> None:
        """A real partial copy must leave neither consumer payload nor staging state."""

        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        source_manifest = validate_pa_family_cache_generation(
            published.generation_directory,
            expected_cache_key=published.cache_key,
            expected_filenames=self.names,
        )
        destination = self.root / "run" / "simion"
        real_snapshot = cache_generation.snapshot_immutable_file
        copy_count = 0

        def fail_third_copy(
            source: Path, target: Path, record: dict[str, object]
        ) -> dict[str, object]:
            nonlocal copy_count
            copy_count += 1
            if copy_count == 3:
                raise OSError("injected third copy failure")
            return real_snapshot(source, target, record)

        with patch.object(
            cache_generation, "snapshot_immutable_file", side_effect=fail_third_copy
        ):
            with self.assertRaisesRegex(RuntimeError, "copy failed: name=field.pa1"):
                materialize_pa_family_cache(
                    published.generation_directory,
                    destination,
                    expected_filenames=self.names,
                )

        self.assertEqual(copy_count, 3)
        self.assertFalse(destination.exists())
        self.assertEqual(
            list(destination.parent.glob(f".{destination.name}.staging-*")), []
        )
        self.assertEqual(
            validate_pa_family_cache_generation(
                published.generation_directory,
                expected_cache_key=published.cache_key,
                expected_filenames=self.names,
            ),
            source_manifest,
        )
        self.assertEqual(
            probe_pa_family_cache(
                self.cache, identity(), expected_filenames=self.names
            ).disposition,
            CacheDisposition.HIT,
        )

    def test_explicit_generation_never_follows_current_pointer_drift(self) -> None:
        """Pinned generation validation/materialization never substitutes current."""

        generation_a = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        alternate = self.root / "alternate"
        alternate.mkdir()
        for name in self.names:
            (alternate / name).write_bytes(f"alternate-{name}".encode("ascii"))
        alternate_records = pa_family_inventory(alternate, self.names)
        manifest_b = pa_family_cache._manifest(
            generation_a.cache_key, identity(), alternate_records
        )
        generation_b = (
            generation_a.generation_directory.parent / manifest_b["generation_sha256"]
        )
        generation_b.mkdir()
        for name in self.names:
            cache_generation.copy_verified_file(alternate / name, generation_b / name)
        (generation_b / "cache_manifest.json").write_text(
            json.dumps(manifest_b, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        pa_family_cache._seal_generation_files(generation_b, manifest_b)
        self.assertNotEqual(
            generation_a.generation_sha256, manifest_b["generation_sha256"]
        )
        self.assertEqual(
            validate_pa_family_cache_generation(
                generation_b,
                expected_cache_key=generation_a.cache_key,
                expected_filenames=self.names,
            ),
            manifest_b,
        )

        pointer = generation_a.generation_directory.parents[1] / "current_generation.json"
        pointer.write_text(
            json.dumps(
                {
                    "cache_key": generation_a.cache_key,
                    "generation_sha256": manifest_b["generation_sha256"],
                }
            ),
            encoding="utf-8",
        )
        current = probe_pa_family_cache(
            self.cache, identity(), expected_filenames=self.names
        )
        self.assertEqual(current.disposition, CacheDisposition.HIT)
        self.assertEqual(current.generation_directory, generation_b)

        pinned_destination = self.root / "pinned-a"
        pinned_a = validate_pa_family_cache_generation(
            generation_a.generation_directory,
            expected_cache_key=generation_a.cache_key,
            expected_filenames=self.names,
        )
        materialized = materialize_pa_family_cache(
            generation_a.generation_directory,
            pinned_destination,
            expected_filenames=self.names,
        )
        self.assertEqual(materialized.files, tuple(pinned_a["files"]))
        self.assertEqual(pa_family_inventory(pinned_destination, self.names), pinned_a["files"])
        self.assertNotEqual(materialized.files, tuple(manifest_b["files"]))

        corrupted_a = generation_a.generation_directory / "field.pa1"
        corrupted_a.chmod(corrupted_a.stat().st_mode | stat.S_IWUSR)
        corrupted_a.write_bytes(b"corrupt-a")
        with self.assertRaisesRegex(PAFamilyCacheError, "field.pa1"):
            validate_pa_family_cache_generation(
                generation_a.generation_directory,
                expected_cache_key=generation_a.cache_key,
                expected_filenames=self.names,
            )
        failed_destination = self.root / "pinned-a-fails"
        with self.assertRaisesRegex(PAFamilyCacheError, "field.pa1"):
            materialize_pa_family_cache(
                generation_a.generation_directory,
                failed_destination,
                expected_filenames=self.names,
            )
        self.assertFalse(failed_destination.exists())
        self.assertEqual(
            probe_pa_family_cache(
                self.cache, identity(), expected_filenames=self.names
            ).generation_directory,
            generation_b,
        )

    def test_missing_or_corrupt_generation_is_never_a_hit_or_overwritten(self) -> None:
        self.assertEqual(probe_pa_family_cache(self.cache, identity()).disposition, CacheDisposition.MISS)
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        (published.generation_directory / "field.pa1").chmod(
            (published.generation_directory / "field.pa1").stat().st_mode | 0o200
        )
        (published.generation_directory / "field.pa1").write_bytes(b"changed")
        probe = probe_pa_family_cache(self.cache, identity(), expected_filenames=self.names)
        self.assertEqual(probe.disposition, CacheDisposition.CORRUPT)
        with self.assertRaisesRegex(PAFamilyCacheError, "refusing to overwrite corrupt"):
            publish_pa_family_cache(self.cache, identity(), self.source, self.names)

    def test_detached_subset_does_not_open_corrupt_unrequested_native_member(self) -> None:
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        native = published.generation_directory / "field.pa1"
        native.chmod(native.stat().st_mode | stat.S_IWUSR)
        native.write_bytes(b"changed")
        manifest = validate_pa_family_cache_subset(
            published.generation_directory,
            ("field.pa#", "field.pa0"),
            expected_cache_key=published.cache_key,
        )
        self.assertEqual(manifest["generation_sha256"], published.generation_sha256)
        with self.assertRaisesRegex(PAFamilyCacheError, "field.pa1"):
            validate_pa_family_cache_subset(
                published.generation_directory,
                ("field.pa1",),
                expected_cache_key=published.cache_key,
            )

    def test_detached_subset_requires_manifest_membership(self) -> None:
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        with self.assertRaisesRegex(PAFamilyCacheError, "absent from the generation manifest"):
            validate_pa_family_cache_subset(
                published.generation_directory,
                ("standalone.pa",),
                expected_cache_key=published.cache_key,
            )

    def test_transient_payload_read_requires_two_consecutive_manifest_matches(self) -> None:
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        real_file_sha256 = pa_family_cache.file_sha256
        target_reads = 0

        def transient_digest(path: Path) -> str:
            nonlocal target_reads
            if Path(path).name == "field.pa1":
                target_reads += 1
                if target_reads == 1:
                    return "0" * 64
            return real_file_sha256(path)

        with patch.object(pa_family_cache, "file_sha256", side_effect=transient_digest):
            manifest = validate_pa_family_cache_generation(
                published.generation_directory, expected_filenames=self.names
            )
        self.assertEqual(manifest["generation_sha256"], published.generation_sha256)
        self.assertEqual(target_reads, 3)

    @unittest.skipUnless(__import__("os").name == "nt", "Windows PA snapshot recovery")
    def test_large_payload_accepts_manifest_backed_unbuffered_snapshot(self) -> None:
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        target = published.generation_directory / "field.pa1"
        expected = next(
            record for record in published.manifest["files"] if record["name"] == target.name
        )
        real_file_sha256 = pa_family_cache.file_sha256

        def stale_buffered_digest(path: Path) -> str:
            if Path(path) == target:
                return "D" * 64
            return real_file_sha256(path)

        with patch.object(
            pa_family_cache, "_WINDOWS_UNBUFFERED_COPY_THRESHOLD_BYTES", 0
        ), patch.object(
            cache_generation, "_WINDOWS_UNBUFFERED_COPY_THRESHOLD_BYTES", 0
        ), patch.object(
            pa_family_cache, "file_sha256", side_effect=stale_buffered_digest
        ):
            pa_family_cache._verify_payload_record(
                published.generation_directory, expected
            )

        self.assertEqual(target.stat().st_size, expected["bytes"])
        self.assertFalse(target.stat().st_mode & stat.S_IWUSR)

    @unittest.skipUnless(__import__("os").name == "nt", "Windows PA snapshot recovery")
    def test_large_payload_rejects_unbuffered_snapshot_not_matching_manifest(self) -> None:
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        target = published.generation_directory / "field.pa1"
        expected = next(
            record for record in published.manifest["files"] if record["name"] == target.name
        )
        wrong = {**expected, "sha256": "E" * 64}

        with patch.object(
            pa_family_cache, "_WINDOWS_UNBUFFERED_COPY_THRESHOLD_BYTES", 0
        ), patch.object(
            cache_generation, "_WINDOWS_UNBUFFERED_COPY_THRESHOLD_BYTES", 0
        ), patch.object(pa_family_cache, "file_sha256", return_value="D" * 64), patch.object(
            pa_family_cache, "PAYLOAD_VERIFICATION_RETRY_DELAY_S", 0
        ):
            with self.assertRaisesRegex(PAFamilyCacheError, "payload differs"):
                pa_family_cache._verify_payload_record(
                    published.generation_directory, wrong
                )

    def test_persistent_payload_mismatch_reports_expected_and_observed_identity(self) -> None:
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        target = published.generation_directory / "field.pa1"
        target.chmod(target.stat().st_mode | stat.S_IWUSR)
        target.write_bytes(b"changed")
        with self.assertRaises(PAFamilyCacheError) as caught:
            validate_pa_family_cache_generation(published.generation_directory)
        detail = str(caught.exception)
        self.assertIn("field.pa1", detail)
        self.assertIn("expected_bytes=3", detail)
        self.assertIn("expected_sha256=", detail)
        self.assertEqual(detail.count("attempt="), 3)

    def test_source_sidecars_are_excluded_but_missing_or_published_extra_payload_fails_closed(self) -> None:
        (self.source / "unregistered.pa2").write_bytes(b"extra")
        # Run-local source folders also contain GEM/IOB/Lua sidecars.  The
        # declared inventory, not ambient directory contents, selects a PA
        # family; the published generation itself remains exact-only.
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        self.assertEqual(
            [record["name"] for record in published.manifest["files"]], list(self.names)
        )
        (published.generation_directory / "extra.txt").write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(PAFamilyCacheError, "incomplete or has extra"):
            validate_pa_family_cache_generation(published.generation_directory)

    def test_pointer_identity_and_run_destination_preserves_sidecars_but_never_overwrites_pa(self) -> None:
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        pointer = published.generation_directory.parents[1] / "current_generation.json"
        pointer.write_text(json.dumps({"cache_key": "D" * 64, "generation_sha256": published.generation_sha256}), encoding="utf-8")
        self.assertEqual(probe_pa_family_cache(self.cache, identity()).disposition, CacheDisposition.CORRUPT)
        destination = self.root / "existing"
        destination.mkdir()
        (destination / "input.gem").write_text("sidecar", encoding="utf-8")
        materialized = materialize_pa_family_cache(published.generation_directory, destination)
        self.assertEqual(materialized.destination_directory, destination.resolve())
        self.assertTrue((destination / "input.gem").is_file())
        with self.assertRaisesRegex(PAFamilyCacheError, "would overwrite"):
            materialize_pa_family_cache(published.generation_directory, destination)

    def test_publication_refuses_a_held_key_lock(self) -> None:
        key = canonical_pa_family_cache_key(identity())
        lock = self.cache / ".locks" / key
        lock.mkdir(parents=True)
        with self.assertRaisesRegex(PAFamilyCacheError, "lock is held"):
            publish_pa_family_cache(self.cache, identity(), self.source, self.names, lock_timeout_s=0.0)

    def test_cli_probes_publishes_and_materializes_a_declared_family(self) -> None:
        identity_path = self.root / "identity.json"
        identity_path.write_text(json.dumps(identity()), encoding="utf-8")
        common = ["--cache-root", str(self.cache), "--identity", str(identity_path),
                  "--filenames", ",".join(self.names)]
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["--action", "probe", *common]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["disposition"], "miss")
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["--action", "publish", *common, "--source-directory", str(self.source)]), 0)
        published = json.loads(stdout.getvalue())
        self.assertEqual(published["disposition"], "published")
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["--action", "probe", *common]), 0)
        hit = json.loads(stdout.getvalue())
        self.assertEqual(hit["disposition"], "hit")
        self.assertEqual(hit["generation_sha256"], published["generation_sha256"])
        destination = self.root / "run" / "simion"
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["--action", "materialize", *common, "--destination-directory", str(destination)]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["disposition"], "materialized")
        self.assertEqual(pa_family_inventory(destination, self.names), pa_family_inventory(self.source, self.names))


if __name__ == "__main__":
    unittest.main()
