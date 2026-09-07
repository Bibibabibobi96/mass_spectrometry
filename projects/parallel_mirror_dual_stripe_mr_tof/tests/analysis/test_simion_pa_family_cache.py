"""Tests for the thin MR-to-common PA-family cache adapter."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from common.simion.pa_family_cache import (
    CacheDisposition, PAFamilyCacheError, canonical_pa_family_cache_key,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import CandidateContractError
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_pa_family_cache import (
    build_pa_family_identity,
    materialize_component_pa_cache,
    pa_family_filenames,
    probe_component_pa_cache,
    publish_component_pa_cache,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry import (
    build_accelerator_gem, build_analyzer_gem,
)


PROJECT = Path(__file__).resolve().parents[2]


class SimionPAFamilyCacheAdapterTest(unittest.TestCase):
    def test_accelerator_identity_and_run_sidecar_materialization(self) -> None:
        contract = PROJECT / "config" / "simion_candidate_two_zone.json"
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            gem = root / "mrtof_accelerator.gem"
            gem.write_text(build_accelerator_gem(contract), encoding="utf-8", newline="\n")
            executable = root / "simion.exe"
            executable.write_bytes(b"synthetic-simion")
            source = root / "source"
            source.mkdir()
            (source / "mrtof_accelerator.gem").write_bytes(gem.read_bytes())
            for name in pa_family_filenames("accelerator"):
                (source / name).write_bytes(name.encode("ascii"))
            (source / "frozen_input.lua").write_text("sidecar", encoding="utf-8")
            cache = root / "cache"
            identity = build_pa_family_identity(contract, "accelerator", gem, executable, "SIMION test")
            expected_mesh = json.loads(contract.read_text(encoding="utf-8"))["simion"]["component_mesh_mm_per_gu"]["accelerator"]
            self.assertEqual(identity["mesh"]["mm_per_gu"], expected_mesh)
            self.assertEqual(identity["basis_namespace"]["stable_local_ids"], list(range(1, 10)))
            _, miss = probe_component_pa_cache(cache, contract, "accelerator", gem, executable, "SIMION test")
            self.assertEqual(miss.disposition, CacheDisposition.MISS)
            published = publish_component_pa_cache(cache, contract, "accelerator", gem, source, executable, "SIMION test")
            self.assertEqual(published["disposition"], "published")
            destination = root / "run" / "simion"
            destination.mkdir(parents=True)
            (destination / "mrtof_accelerator.gem").write_text("run sidecar", encoding="utf-8")
            materialized = materialize_component_pa_cache(
                cache, contract, "accelerator", gem, destination, executable, "SIMION test",
            )
            self.assertEqual(materialized["disposition"], "materialized")
            self.assertTrue((destination / "mrtof_accelerator.gem").is_file())
            self.assertEqual(
                sorted(item["name"] for item in materialized["files"]), sorted(pa_family_filenames("accelerator")),
            )

    def test_publication_rejects_a_pa_directory_without_its_exact_source_gem(self) -> None:
        contract = PROJECT / "config" / "simion_candidate_two_zone.json"
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            gem = root / "mrtof_accelerator.gem"
            gem.write_text(build_accelerator_gem(contract), encoding="utf-8", newline="\n")
            executable = root / "simion.exe"
            executable.write_bytes(b"synthetic-simion")
            source = root / "source"
            source.mkdir()
            for name in pa_family_filenames("accelerator"):
                (source / name).write_bytes(name.encode("ascii"))
            with self.assertRaisesRegex(PAFamilyCacheError, "exact canonical source GEM"):
                publish_component_pa_cache(
                    root / "cache", contract, "accelerator", gem, source, executable, "SIMION test"
                )
            (source / "mrtof_accelerator.gem").write_text("different gem", encoding="utf-8")
            with self.assertRaisesRegex(PAFamilyCacheError, "source GEM differs"):
                publish_component_pa_cache(
                    root / "cache", contract, "accelerator", gem, source, executable, "SIMION test"
                )

    def test_identity_rejects_noncanonical_gem_and_changes_with_mesh(self) -> None:
        contract = PROJECT / "config" / "simion_candidate_two_zone.json"
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            gem = root / "mrtof_accelerator.gem"
            gem.write_text(build_accelerator_gem(contract), encoding="utf-8", newline="\n")
            executable = root / "simion.exe"
            executable.write_bytes(b"synthetic-simion")
            first = build_pa_family_identity(contract, "accelerator", gem, executable, "SIMION test")
            gem.write_text(gem.read_text(encoding="utf-8") + "; changed\n", encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "canonical contract-derived GEM"):
                build_pa_family_identity(contract, "accelerator", gem, executable, "SIMION test")
            changed = json.loads(contract.read_text(encoding="utf-8"))
            changed["simion"]["component_mesh_mm_per_gu"]["accelerator"] = [1, 1, 1]
            changed_contract = root / "changed.json"
            changed_contract.write_text(json.dumps(changed), encoding="utf-8")
            gem.write_text(build_accelerator_gem(changed_contract), encoding="utf-8", newline="\n")
            third = build_pa_family_identity(changed_contract, "accelerator", gem, executable, "SIMION test")
            self.assertNotEqual(first["mesh"], third["mesh"])
            self.assertNotEqual(canonical_pa_family_cache_key(first), canonical_pa_family_cache_key(third))

    def test_accelerator_geometry_change_preserves_only_analyzer_identity(self) -> None:
        contract = PROJECT / "config" / "simion_candidate_two_zone.json"
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            executable = root / "simion.exe"
            executable.write_bytes(b"synthetic-simion")
            changed = json.loads(contract.read_text(encoding="utf-8"))
            changed["accelerator"]["stage_2_rings"]["thickness_z_mm"] = 0.8
            changed_contract = root / "changed.json"
            changed_contract.write_text(json.dumps(changed), encoding="utf-8")
            for component, generator in (("analyzer", build_analyzer_gem), ("accelerator", build_accelerator_gem)):
                with self.subTest(component=component):
                    gem = root / f"mrtof_{component}.gem"
                    gem.write_text(generator(contract), encoding="utf-8", newline="\n")
                    first = build_pa_family_identity(contract, component, gem, executable, "SIMION test")
                    original_bytes = gem.read_bytes()
                    gem.write_text(generator(changed_contract), encoding="utf-8", newline="\n")
                    second = build_pa_family_identity(changed_contract, component, gem, executable, "SIMION test")
                    self.assertEqual(original_bytes == gem.read_bytes(), component == "analyzer")
                    self.assertEqual(
                        canonical_pa_family_cache_key(first) == canonical_pa_family_cache_key(second),
                        component == "analyzer",
                    )

    def test_analyzer_geometry_change_invalidates_analyzer_identity(self) -> None:
        contract = PROJECT / "config" / "simion_candidate_two_zone.json"
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            executable = root / "simion.exe"
            executable.write_bytes(b"synthetic-simion")
            gem = root / "mrtof_analyzer.gem"
            gem.write_text(build_analyzer_gem(contract), encoding="utf-8", newline="\n")
            first = build_pa_family_identity(contract, "analyzer", gem, executable, "SIMION test")
            changed = json.loads(contract.read_text(encoding="utf-8"))
            changed["mirror"]["outer_width_x_mm"] = 126
            changed_contract = root / "changed.json"
            changed_contract.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "canonical contract-derived GEM"):
                build_pa_family_identity(changed_contract, "analyzer", gem, executable, "SIMION test")
            gem.write_text(build_analyzer_gem(changed_contract), encoding="utf-8", newline="\n")
            second = build_pa_family_identity(changed_contract, "analyzer", gem, executable, "SIMION test")
            self.assertNotEqual(first["geometry"], second["geometry"])
            self.assertNotEqual(canonical_pa_family_cache_key(first), canonical_pa_family_cache_key(second))


if __name__ == "__main__":
    unittest.main()
