"""Regression tests for the content-addressed standalone operating-PA cache."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.file_identity import file_sha256
from common.simion.operating_pa_cache import (
    CacheDisposition,
    OperatingPACacheError,
    canonical_operating_pa_cache_key,
    content_identity_from_verified_record,
    linear_basis_operating_pa_group_identity,
    materialize_operating_pa_cache,
    operating_pa_group_identity,
    operating_pa_member_identity,
    probe_operating_pa_cache,
    publish_operating_pa_cache,
    validate_operating_pa_cache_generation,
)


class OperatingPACacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.inputs = self.root / "inputs"
        self.outputs = self.root / "outputs"
        self.inputs.mkdir()
        self.outputs.mkdir()
        for name, body in {
            "base-a.pa": b"base-a",
            "base-b.pa": b"base-b",
            "a-s1.pa": b"a-s1-response",
            "a-p1.pa": b"a-p1-response",
            "b-s1.pa": b"b-s1-response",
        }.items():
            (self.inputs / name).write_bytes(body)
        (self.outputs / "zone-a.pa").write_bytes(b"operating-zone-a")
        (self.outputs / "zone-b.pa").write_bytes(b"operating-zone-b")
        self.cache = self.root / "cache"
        member_a = operating_pa_member_identity(
            "zone-a.pa",
            self.inputs / "base-a.pa",
            [
                {"coordinate": "stripe_1", "path": self.inputs / "a-s1.pa",
                 "basis_normalization_v": 10000.0, "applied_voltage_delta_v": 0.125},
                {"coordinate": "prism_1", "path": self.inputs / "a-p1.pa",
                 "basis_normalization_v": 10000.0, "applied_voltage_delta_v": -0.25},
            ],
            [-25.0, 50.0, 177.5, -179.1],
        )
        member_b = operating_pa_member_identity(
            "zone-b.pa",
            self.inputs / "base-b.pa",
            [{"coordinate": "stripe_1", "path": self.inputs / "b-s1.pa",
              "basis_normalization_v": 10000.0, "applied_voltage_delta_v": 0.125}],
            [-25.0, 50.0, 177.5, -179.1],
        )
        self.identity = operating_pa_group_identity(
            [member_b, member_a],
            algorithm_id="standalone_linear_response_composition",
            algorithm_format_version=2,
            implementation_sha256="A" * 64,
            pa_format_version=2020,
        )
        self.members = [member_a, member_b]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_key_covers_every_synthesis_input_dimension(self) -> None:
        original = canonical_operating_pa_cache_key(self.identity)
        mutations = []
        for path, value in [
            (("members", 0, "base_pa", "sha256"), "B" * 64),
            (("members", 0, "responses", 0, "content", "sha256"), "C" * 64),
            (("members", 0, "target_voltage_vector_v", 0), -24.9),
            (("members", 0, "responses", 0, "basis_normalization_v"), 9999.0),
            (("members", 0, "responses", 0, "applied_voltage_delta_v"), 0.124),
            (("synthesis", "algorithm_id"), "different_algorithm"),
            (("synthesis", "algorithm_format_version"), 3),
            (("synthesis", "implementation_sha256"), "D" * 64),
            (("synthesis", "pa_format_version"), 2021),
        ]:
            changed = deepcopy(self.identity)
            target = changed
            for item in path[:-1]:
                target = target[item]
            target[path[-1]] = value
            mutations.append(changed)
        for changed in mutations:
            self.assertNotEqual(original, canonical_operating_pa_cache_key(changed))

    def test_linear_basis_helper_binds_standalone_composer(self) -> None:
        identity = linear_basis_operating_pa_group_identity(self.members, pa_format_version=2020)
        implementation = Path(__file__).with_name("compose_standalone_pa.lua")
        self.assertEqual(
            identity["synthesis"]["algorithm_id"],
            "standalone_linear_response_composition",
        )
        self.assertEqual(identity["schema_version"], 2)
        self.assertEqual(identity["role"], "simion_standalone_operating_pa_group")
        self.assertEqual(identity["synthesis"]["implementation_sha256"], file_sha256(implementation))

    def test_verified_record_identity_avoids_payload_rehash(self) -> None:
        source = self.inputs / "base-a.pa"
        record = {"bytes": source.stat().st_size, "sha256": file_sha256(source)}
        with patch("common.simion.operating_pa_cache.file_sha256") as hasher:
            self.assertEqual(content_identity_from_verified_record(record, path=source), record)
            hasher.assert_not_called()

    def test_verified_record_identity_rejects_missing_or_wrong_size_payload(self) -> None:
        source = self.inputs / "base-a.pa"
        record = {"bytes": source.stat().st_size + 1, "sha256": file_sha256(source)}
        with self.assertRaisesRegex(OperatingPACacheError, "byte count differs"):
            content_identity_from_verified_record(record, path=source)
        with self.assertRaisesRegex(OperatingPACacheError, "is missing"):
            content_identity_from_verified_record(
                {"bytes": 1, "sha256": "A" * 64}, path=self.inputs / "missing.pa"
            )

    def test_publish_hit_validate_read_only_and_materialize_group(self) -> None:
        published = publish_operating_pa_cache(self.cache, self.identity, self.outputs)
        self.assertEqual(published.disposition, CacheDisposition.PUBLISHED)
        self.assertEqual(published.cache_key, canonical_operating_pa_cache_key(self.identity))
        self.assertEqual(probe_operating_pa_cache(self.cache, self.identity).disposition, CacheDisposition.HIT)
        manifest = validate_operating_pa_cache_generation(
            published.generation_directory, expected_identity=self.identity
        )
        self.assertEqual([record["name"] for record in manifest["files"]], ["zone-a.pa", "zone-b.pa"])
        self.assertEqual(
            manifest["redundancy"],
            {"algorithm": "none_reconstructible", "groups": []},
        )
        self.assertFalse(
            (
                published.generation_directory.parents[1]
                / "recovery"
                / published.generation_sha256
            ).exists()
        )
        for name in ("zone-a.pa", "zone-b.pa", "cache_manifest.json"):
            self.assertFalse((published.generation_directory / name).stat().st_mode & stat.S_IWUSR)
        second = publish_operating_pa_cache(self.cache, self.identity, self.outputs)
        self.assertEqual(second.disposition, CacheDisposition.HIT)
        destination = self.root / "run" / "simion"
        materialized = materialize_operating_pa_cache(
            published.generation_directory, destination, expected_identity=self.identity
        )
        self.assertEqual(len(materialized.files), 2)
        self.assertEqual(file_sha256(destination / "zone-a.pa"), file_sha256(self.outputs / "zone-a.pa"))
        self.assertTrue((destination / "zone-a.pa").stat().st_mode & stat.S_IWUSR)

    def test_corruption_and_identity_or_inventory_drift_fail_closed(self) -> None:
        published = publish_operating_pa_cache(self.cache, self.identity, self.outputs)
        payload = published.generation_directory / "zone-a.pa"
        payload.chmod(payload.stat().st_mode | stat.S_IWUSR)
        payload.write_bytes(b"corrupt")
        self.assertEqual(probe_operating_pa_cache(self.cache, self.identity).disposition, CacheDisposition.CORRUPT)
        with self.assertRaisesRegex(OperatingPACacheError, "refusing to overwrite corrupt"):
            publish_operating_pa_cache(self.cache, self.identity, self.outputs)

    def test_invalid_member_contracts_fail_before_publication(self) -> None:
        changed = deepcopy(self.identity)
        changed["members"][0]["output_name"] = "nested/zone-a.pa"
        with self.assertRaisesRegex(OperatingPACacheError, "direct standalone .pa"):
            canonical_operating_pa_cache_key(changed)
        changed = deepcopy(self.identity)
        changed["members"][0]["responses"][0]["basis_normalization_v"] = 0.0
        with self.assertRaisesRegex(OperatingPACacheError, "nonzero"):
            canonical_operating_pa_cache_key(changed)
        (self.outputs / "zone-b.pa").unlink()
        with self.assertRaisesRegex(OperatingPACacheError, "incomplete"):
            publish_operating_pa_cache(self.cache, self.identity, self.outputs)

    def test_family_forms_and_surface_metadata_are_rejected(self) -> None:
        for suffix in (".pa0", ".pa1", ".pa+", ".pa_"):
            source = self.inputs / f"forbidden{suffix}"
            source.write_bytes(b"family-form")
            with self.assertRaisesRegex(OperatingPACacheError, "family forms are forbidden"):
                operating_pa_member_identity(
                    "output.pa", source, [], [1.0]
                )
        with self.assertRaisesRegex(OperatingPACacheError, "standalone .pa"):
            operating_pa_member_identity(
                "output.pa0", self.inputs / "base-a.pa", [], [1.0]
            )
        surface = self.inputs / "base-a.pa-surf"
        surface.write_bytes(b"surface")
        with self.assertRaisesRegex(OperatingPACacheError, "surface metadata"):
            operating_pa_member_identity(
                "output.pa", self.inputs / "base-a.pa", [], [1.0]
            )

    def test_version_one_pa0_identity_is_a_breaking_migration(self) -> None:
        legacy = deepcopy(self.identity)
        legacy["schema_version"] = 1
        legacy["role"] = "simion_operating_pa0_group"
        legacy["members"][0]["source_pa0"] = legacy["members"][0].pop("base_pa")
        with self.assertRaisesRegex(OperatingPACacheError, "fields differ|role or version differs"):
            canonical_operating_pa_cache_key(legacy)

    def test_pointer_failure_never_exposes_partial_publication_as_a_hit(self) -> None:
        with patch("common.simion.pa_family_cache._publish_pointer", side_effect=OSError("pointer failure")):
            with self.assertRaisesRegex(OSError, "pointer failure"):
                publish_operating_pa_cache(self.cache, self.identity, self.outputs)
        self.assertEqual(probe_operating_pa_cache(self.cache, self.identity).disposition, CacheDisposition.MISS)


if __name__ == "__main__":
    unittest.main()
