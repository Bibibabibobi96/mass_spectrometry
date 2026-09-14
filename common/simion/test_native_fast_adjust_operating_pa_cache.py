"""Tests for native-family Fast Adjust operating PA publication."""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import stat
import tempfile
import unittest

from common.contracts.file_identity import file_sha256
from common.simion.native_fast_adjust_operating_pa_cache import (
    CacheDisposition,
    NativeOperatingPACacheError,
    PA_FORMAT_VERSION,
    build_native_operating_pa_export_plan,
    canonical_native_operating_pa_cache_key,
    canonical_native_operating_pa_identity,
    materialize_native_operating_pa_cache,
    native_operating_pa_group_identity,
    native_operating_pa_member_identity,
    probe_native_operating_pa_cache,
    publish_native_operating_pa_cache,
    validate_native_operating_pa_cache_generation,
)


class NativeFastAdjustOperatingPACacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.staging = self.root / "family-staging"
        self.outputs = self.root / "operating-outputs"
        self.cache = self.root / "cache"
        self.staging.mkdir()
        self.outputs.mkdir()
        self.controller = self.staging / "accelerator.pa0"
        self.controller.write_bytes(b"private-native-controller")
        self.members = [
            native_operating_pa_member_identity(
                "carrier_off.pa", {36: 0.0, 37: -1250.0, 38: 15.25}
            ),
            native_operating_pa_member_identity(
                "pulse_delta.pa", {36: 950.0, 37: 1250.0, 38: -15.25}
            ),
        ]
        self.identity = native_operating_pa_group_identity(
            source_family_role="accelerator_main",
            source_family_cache_key="a" * 64,
            controller_basename=self.controller.name,
            solution_ids=[36, 37, 38],
            members=reversed(self.members),
        )
        (self.outputs / "carrier_off.pa").write_bytes(b"carrier-off")
        (self.outputs / "pulse_delta.pa").write_bytes(b"pulse-delta")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_identity_binds_every_native_synthesis_dimension(self) -> None:
        original = canonical_native_operating_pa_cache_key(self.identity)
        mutations = [
            (("source_family", "role"), "accelerator_local"),
            (("source_family", "cache_key"), "b" * 64),
            (("source_family", "controller_basename"), "other.pa0"),
            (("members", 0, "output_name"), "other.pa"),
            (("members", 0, "electrode_voltages_v", 1, "voltage_v"), -1249.0),
            (("synthesis", "algorithm_format_version"), 2),
            (("synthesis", "exporter_sha256"), "B" * 64),
        ]
        for path, value in mutations:
            changed = deepcopy(self.identity)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            self.assertNotEqual(original, canonical_native_operating_pa_cache_key(changed))
        changed = deepcopy(self.identity)
        changed["source_family"]["solution_ids"][2] = 39
        for member in changed["members"]:
            member["electrode_voltages_v"][2]["electrode_id"] = 39
        self.assertNotEqual(original, canonical_native_operating_pa_cache_key(changed))
        self.assertEqual(self.identity["synthesis"]["pa_format_version"], PA_FORMAT_VERSION)

    def test_member_table_is_complete_sorted_positive_and_finite(self) -> None:
        canonical = canonical_native_operating_pa_identity(self.identity)
        self.assertEqual(
            [entry["electrode_id"] for entry in canonical["members"][0]["electrode_voltages_v"]],
            [36, 37, 38],
        )
        for bad_table, message in [
            ({36: 0.0, 37: 1.0}, "cover every"),
            ({36: 0.0, 37: 1.0, 38: math.inf}, "finite"),
            ({0: 0.0, 37: 1.0, 38: 2.0}, "positive integer"),
        ]:
            changed = deepcopy(self.identity)
            with self.assertRaisesRegex(NativeOperatingPACacheError, message):
                changed["members"][0] = native_operating_pa_member_identity(
                    "carrier_off.pa", bad_table
                )
                canonical_native_operating_pa_identity(changed)

    def test_group_normalizes_hex_and_rejects_non_2020_format(self) -> None:
        changed = deepcopy(self.identity)
        changed["source_family"]["cache_key"] = "Aa" * 32
        self.assertEqual(
            canonical_native_operating_pa_identity(changed)["source_family"]["cache_key"],
            "AA" * 32,
        )
        changed["source_family"]["cache_key"] = "not-a-cache-key"
        with self.assertRaisesRegex(NativeOperatingPACacheError, "must be 64-hex"):
            canonical_native_operating_pa_identity(changed)
        changed = deepcopy(self.identity)
        changed["source_family"]["solution_ids"] = [36, 38, 37]
        with self.assertRaisesRegex(NativeOperatingPACacheError, "sorted and unique"):
            canonical_native_operating_pa_identity(changed)
        changed = deepcopy(self.identity)
        changed["synthesis"]["pa_format_version"] = 2021
        with self.assertRaisesRegex(NativeOperatingPACacheError, "SIMION 2020"):
            canonical_native_operating_pa_identity(changed)

    def test_export_plan_requires_private_controller_and_exact_exporter(self) -> None:
        new_outputs = self.root / "new-outputs"
        new_outputs.mkdir()
        plan = build_native_operating_pa_export_plan(self.identity, self.staging, new_outputs)
        self.assertEqual([item.output_path.name for item in plan], ["carrier_off.pa", "pulse_delta.pa"])
        self.assertEqual(plan[0].voltage_arguments, ("36=0", "37=-1250", "38=15.25"))
        self.assertEqual(plan[0].lua_arguments[1], str(self.controller))
        self.assertEqual(
            plan[0].receipt_path.name,
            "carrier_off.pa.boundary_mask_restoration.json",
        )
        self.assertEqual(plan[0].lua_arguments[3], str(plan[0].receipt_path))
        changed = deepcopy(self.identity)
        changed["synthesis"]["exporter_sha256"] = "C" * 64
        with self.assertRaisesRegex(NativeOperatingPACacheError, "exporter differs"):
            build_native_operating_pa_export_plan(changed, self.staging, new_outputs)
        self.controller.chmod(self.controller.stat().st_mode & ~stat.S_IWUSR)
        with self.assertRaisesRegex(NativeOperatingPACacheError, "must be writable"):
            build_native_operating_pa_export_plan(self.identity, self.staging, new_outputs)

    def test_publish_probe_validate_and_materialize_standalone_group(self) -> None:
        publication = publish_native_operating_pa_cache(self.cache, self.identity, self.outputs)
        self.assertEqual(publication.disposition, CacheDisposition.PUBLISHED)
        self.assertEqual(
            publication.cache_key, canonical_native_operating_pa_cache_key(self.identity)
        )
        probe = probe_native_operating_pa_cache(self.cache, self.identity)
        self.assertEqual(probe.disposition, CacheDisposition.HIT)
        manifest = validate_native_operating_pa_cache_generation(
            publication.generation_directory, expected_identity=self.identity
        )
        self.assertEqual(
            [record["name"] for record in manifest["files"]],
            ["carrier_off.pa", "pulse_delta.pa"],
        )
        for name in ("carrier_off.pa", "pulse_delta.pa", "cache_manifest.json"):
            self.assertFalse(
                publication.generation_directory.joinpath(name).stat().st_mode & stat.S_IWUSR
            )
        destination = self.root / "run-local"
        materialized = materialize_native_operating_pa_cache(
            publication.generation_directory, destination, expected_identity=self.identity
        )
        self.assertEqual(len(materialized.files), 2)
        self.assertEqual(
            file_sha256(destination / "carrier_off.pa"),
            file_sha256(self.outputs / "carrier_off.pa"),
        )
        self.assertTrue((destination / "carrier_off.pa").stat().st_mode & stat.S_IWUSR)

    def test_publication_accepts_only_direct_standalone_pa_payloads(self) -> None:
        (self.outputs / "carrier_off.pa-surf").write_bytes(b"surface")
        with self.assertRaisesRegex(NativeOperatingPACacheError, "surface metadata"):
            publish_native_operating_pa_cache(self.cache, self.identity, self.outputs)
        bad = deepcopy(self.identity)
        bad["members"][0]["output_name"] = "carrier_off.pa0"
        with self.assertRaisesRegex(NativeOperatingPACacheError, "ending in .pa"):
            canonical_native_operating_pa_identity(bad)
        bad = deepcopy(self.identity)
        bad["source_family"]["controller_basename"] = "nested/accelerator.pa0"
        with self.assertRaisesRegex(NativeOperatingPACacheError, "direct filename"):
            canonical_native_operating_pa_identity(bad)

    def test_corruption_remains_fail_closed(self) -> None:
        publication = publish_native_operating_pa_cache(self.cache, self.identity, self.outputs)
        payload = publication.generation_directory / "carrier_off.pa"
        payload.chmod(payload.stat().st_mode | stat.S_IWUSR)
        payload.write_bytes(b"corrupt")
        self.assertEqual(
            probe_native_operating_pa_cache(self.cache, self.identity).disposition,
            CacheDisposition.CORRUPT,
        )
        with self.assertRaisesRegex(NativeOperatingPACacheError, "refusing to overwrite corrupt"):
            publish_native_operating_pa_cache(self.cache, self.identity, self.outputs)


if __name__ == "__main__":
    unittest.main()
