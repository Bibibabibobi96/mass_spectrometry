"""Regression tests for the device-neutral SIMION PA-family cache."""
from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from common.simion.pa_family_cache import (
    CacheDisposition,
    PAFamilyCacheError,
    canonical_pa_family_cache_key,
    materialize_pa_family_cache,
    main,
    pa_family_inventory,
    probe_pa_family_cache,
    publish_pa_family_cache,
    validate_pa_family_cache_generation,
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
        self.assertEqual(probe_pa_family_cache(self.cache, identity(), expected_filenames=self.names).disposition, CacheDisposition.HIT)
        manifest = validate_pa_family_cache_generation(first.generation_directory, expected_filenames=self.names)
        self.assertEqual(manifest["files"], pa_family_inventory(self.source, self.names))
        second = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        self.assertEqual(second.disposition, CacheDisposition.HIT)
        local = materialize_pa_family_cache(first.generation_directory, self.root / "run" / "simion", expected_filenames=self.names)
        self.assertEqual(local.files, tuple(manifest["files"]))
        self.assertEqual(pa_family_inventory(local.destination_directory, self.names), manifest["files"])

    def test_missing_or_corrupt_generation_is_never_a_hit_or_overwritten(self) -> None:
        self.assertEqual(probe_pa_family_cache(self.cache, identity()).disposition, CacheDisposition.MISS)
        published = publish_pa_family_cache(self.cache, identity(), self.source, self.names)
        (published.generation_directory / "field.pa1").write_bytes(b"changed")
        probe = probe_pa_family_cache(self.cache, identity(), expected_filenames=self.names)
        self.assertEqual(probe.disposition, CacheDisposition.CORRUPT)
        with self.assertRaisesRegex(PAFamilyCacheError, "refusing to overwrite corrupt"):
            publish_pa_family_cache(self.cache, identity(), self.source, self.names)

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
        self.assertEqual(json.loads(stdout.getvalue())["disposition"], "published")
        destination = self.root / "run" / "simion"
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["--action", "materialize", *common, "--destination-directory", str(destination)]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["disposition"], "materialized")
        self.assertEqual(pa_family_inventory(destination, self.names), pa_family_inventory(self.source, self.names))


if __name__ == "__main__":
    unittest.main()
