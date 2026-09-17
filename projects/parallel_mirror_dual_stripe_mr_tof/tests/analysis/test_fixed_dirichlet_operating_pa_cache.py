"""Tests for the fixed 0.25-mm Dirichlet operating-PA cache adapter."""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from common.simion.pa_family_cache import CacheDisposition, canonical_pa_family_cache_key
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.fixed_dirichlet_operating_pa_cache import (
    MIRROR_GROUPS,
    build_fixed_dirichlet_operating_pa_identity,
    main,
    materialize_fixed_dirichlet_operating_pa_cache,
    probe_fixed_dirichlet_operating_pa_cache,
    publish_fixed_dirichlet_operating_pa_cache,
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _family_identity() -> dict[str, object]:
    return {
        "geometry": {"region": "mirror_turn_negative"},
        "gem": {"sha256": "A" * 64},
        "basis_namespace": {
            "local_group_ids": {
                "mirror_B": 1,
                "mirror_C": 2,
                "mirror_D": 3,
                "mirror_E": 4,
                "drift_stripe_set_1": 5,
                "drift_stripe_set_2": 6,
                "prism_1": 7,
                "prism_2": 8,
            }
        },
        "mesh": {"mm_per_gu": [0.25, 0.25, 0.25]},
        "grid_phase": {"origin_project_mm": [-20.0, -147.0, -330.0]},
        "surface": "none",
        "simion_identity": {"release": "SIMION 2020", "executable_sha256": "B" * 64},
        "refine_policy": {"mode": "installed_default", "convergence_override": None},
        "builder_identity": {"family_adapter_sha256": "C" * 64},
    }


def _contract(identity: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "schema_version": 1,
        "role": "mrtof_analyzer_local_pa_family_contract",
        "status": "buildable",
        "region": "mirror_turn_negative",
        "scale_factor": 0.25,
        "identity": identity or _family_identity(),
    }


class FixedDirichletOperatingPACacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.contract = self.root / "fixed_contract.json"
        self.parent = self.root / "parent.pa"
        self.builder = self.root / "build_dirichlet_patch_operating_pa.lua"
        _write_json(self.contract, _contract())
        self.parent.write_bytes(b"half-mm-parent")
        self.builder.write_text("-- builder", encoding="utf-8")
        self.voltages = (2406.0, -295.0, 4268.0, 5475.0)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def identity(self, output_name: str = "local_negative_mirror.pa0") -> dict[str, object]:
        return build_fixed_dirichlet_operating_pa_identity(
            self.contract, self.parent, self.voltages, self.builder, output_name
        )

    def test_identity_binds_contract_parent_voltages_builder_and_output_name(self) -> None:
        original = self.identity()
        original_key = canonical_pa_family_cache_key(original)
        self.assertEqual(
            original["basis_namespace"]["target_voltage_by_group_v"],
            dict(zip(MIRROR_GROUPS, self.voltages, strict=True)),
        )
        self.assertEqual(
            original["geometry"]["parent_operating_pa"]["mesh_mm_per_gu"],
            [0.5, 0.5, 0.5],
        )

        changed_contract = deepcopy(_contract())
        changed_contract["identity"]["grid_phase"]["origin_project_mm"][0] = -19.75
        _write_json(self.contract, changed_contract)
        contract_key = canonical_pa_family_cache_key(self.identity())
        _write_json(self.contract, _contract())

        self.parent.write_bytes(b"different-half-mm-parent")
        parent_key = canonical_pa_family_cache_key(self.identity())
        self.parent.write_bytes(b"half-mm-parent")

        voltage_key = canonical_pa_family_cache_key(
            build_fixed_dirichlet_operating_pa_identity(
                self.contract,
                self.parent,
                (2407.0, *self.voltages[1:]),
                self.builder,
                "local_negative_mirror.pa0",
            )
        )
        self.builder.write_text("-- changed builder", encoding="utf-8")
        builder_key = canonical_pa_family_cache_key(self.identity())
        self.builder.write_text("-- builder", encoding="utf-8")
        output_key = canonical_pa_family_cache_key(self.identity("local_positive_mirror.pa0"))

        for changed_key in (contract_key, parent_key, voltage_key, builder_key, output_key):
            self.assertNotEqual(original_key, changed_key)

    def test_probe_publish_and_materialize_reuse_shared_cache(self) -> None:
        identity = self.identity()
        cache = self.root / "cache"
        output_name = "local_negative_mirror.pa0"
        self.assertIs(
            probe_fixed_dirichlet_operating_pa_cache(
                cache, identity, output_name
            ).disposition,
            CacheDisposition.MISS,
        )
        source = self.root / "source"
        source.mkdir()
        (source / output_name).write_bytes(b"solved-quarter-mm-pa")
        publication = publish_fixed_dirichlet_operating_pa_cache(
            cache, identity, output_name, source
        )
        self.assertIs(publication.disposition, CacheDisposition.PUBLISHED)
        probe = probe_fixed_dirichlet_operating_pa_cache(cache, identity, output_name)
        self.assertIs(probe.disposition, CacheDisposition.HIT)
        destination = self.root / "run" / "simion"
        materialized_probe, materialized = materialize_fixed_dirichlet_operating_pa_cache(
            cache, identity, output_name, destination
        )
        self.assertEqual(materialized_probe.cache_key, publication.cache_key)
        self.assertEqual((destination / output_name).read_bytes(), b"solved-quarter-mm-pa")
        self.assertEqual(len(materialized.files), 1)

    def test_cli_supports_probe_publish_and_materialize(self) -> None:
        cache = self.root / "cache"
        source = self.root / "source"
        source.mkdir()
        output_name = "fixed.pa0"
        (source / output_name).write_bytes(b"fixed")
        common = [
            "--cache-root", str(cache),
            "--local-family-contract", str(self.contract),
            "--parent-half-mm-pa", str(self.parent),
            "--target-mirror-voltages-v", ",".join(str(value) for value in self.voltages),
            "--dirichlet-builder", str(self.builder),
            "--output-name", output_name,
        ]
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["--action", "probe", *common]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["disposition"], "miss")
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(
                main(["--action", "publish", *common, "--source-directory", str(source)]),
                0,
            )
        self.assertEqual(json.loads(stdout.getvalue())["disposition"], "published")
        destination = self.root / "materialized"
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(
                main([
                    "--action", "materialize", *common,
                    "--destination-directory", str(destination),
                ]),
                0,
            )
        self.assertEqual(json.loads(stdout.getvalue())["disposition"], "materialized")
        self.assertEqual((destination / output_name).read_bytes(), b"fixed")

    def test_rejects_non_mirror_or_non_quarter_mm_contract(self) -> None:
        invalid = _contract()
        invalid["region"] = "central_transport"
        _write_json(self.contract, invalid)
        with self.assertRaisesRegex(ValueError, "mirror-turn"):
            self.identity()
        invalid = _contract()
        invalid["scale_factor"] = 0.5
        _write_json(self.contract, invalid)
        with self.assertRaisesRegex(ValueError, "0.25-mm"):
            self.identity()


if __name__ == "__main__":
    unittest.main()
