"""Regression tests for the content-addressed standalone operating-PA cache."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from msplatform.io.file_identity import file_sha256
from msplatform.backends.simion.resources import native_resource_path
from msplatform.backends.simion.operating_pa_cache import (
    OperatingPACacheError,
    canonical_operating_pa_cache_key,
    content_identity_from_verified_record,
    linear_basis_operating_pa_group_identity,
    operating_pa_group_identity,
    operating_pa_member_identity,
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
        implementation = native_resource_path("compose_standalone_pa.lua")
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
        with patch("msplatform.backends.simion.operating_pa_cache.file_sha256") as hasher:
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

    def test_invalid_member_contracts_fail_before_publication(self) -> None:
        changed = deepcopy(self.identity)
        changed["members"][0]["output_name"] = "nested/zone-a.pa"
        with self.assertRaisesRegex(OperatingPACacheError, "direct standalone .pa"):
            canonical_operating_pa_cache_key(changed)
        changed = deepcopy(self.identity)
        changed["members"][0]["responses"][0]["basis_normalization_v"] = 0.0
        with self.assertRaisesRegex(OperatingPACacheError, "nonzero"):
            canonical_operating_pa_cache_key(changed)

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



if __name__ == "__main__":
    unittest.main()
