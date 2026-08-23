"""Tests for campaign-only stable runtime authorities."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.machine_contracts import validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.refresh_family_repository_bindings import (
    compile_publications,
    publication_differences,
    write_publications,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = INTEGRATION_ROOT / "config"
SCHEMA_ROOT = CONFIG_ROOT / "schemas"
RETIRED_CAMPAIGN_ARCHIVE_INDEX = (
    INTEGRATION_ROOT / "docs" / "history" / "retired_campaigns"
    / "diagnostics_archive_index.json"
)
INACTIVE_AUTHORIZED_CAMPAIGN_ARCHIVE_INDEX = (
    INTEGRATION_ROOT / "docs" / "history" / "retired_campaigns"
    / "inactive_authorized_campaign_archive_index.json"
)
ADAPTER = INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1"
FAMILIES = ("quadrupole", "hexapole", "octupole")


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class CampaignRuntimeAuthoritiesTests(unittest.TestCase):
    def test_retired_campaigns_are_archived_with_byte_identity(self) -> None:
        index = load(RETIRED_CAMPAIGN_ARCHIVE_INDEX)
        self.assertEqual(
            index["role"],
            "rf_oatof_retired_diagnostics_campaign_archive_index",
        )
        entries = index["entries"]
        for entry in entries:
            with self.subTest(path=entry["source_path"]):
                source = REPO_ROOT / entry["source_path"]
                archived = REPO_ROOT / entry["archived_path"]
                self.assertFalse(source.exists())
                self.assertTrue(archived.is_file())
                self.assertIn(entry["status"], {"retired", "archived_invalid"})
                self.assertEqual(
                    entry["sha256"],
                    hashlib.sha256(archived.read_bytes()).hexdigest(),
                )

    def test_inactive_authorized_campaigns_are_archived_with_byte_identity(self) -> None:
        index = load(INACTIVE_AUTHORIZED_CAMPAIGN_ARCHIVE_INDEX)
        self.assertEqual(
            index["role"],
            "rf_oatof_inactive_authorized_campaign_archive_index",
        )
        entries = index["entries"]
        self.assertEqual(len(entries), 9)
        for entry in entries:
            with self.subTest(path=entry["source_path"]):
                source = REPO_ROOT / entry["source_path"]
                archived = REPO_ROOT / entry["archived_path"]
                self.assertFalse(source.exists())
                self.assertTrue(archived.is_file())
                self.assertEqual(entry["status"], "authorized")
                self.assertEqual(
                    entry["sha256"],
                    hashlib.sha256(archived.read_bytes()).hexdigest(),
                )

    def test_diagnostics_lifecycle_registry_has_current_authorities(self) -> None:
        registry_path = CONFIG_ROOT / "diagnostics" / "lifecycle_registry.json"
        registry = load(registry_path)
        validate_schema(
            registry,
            CONFIG_ROOT / "schemas" /
            "rf_oatof_diagnostics_lifecycle_registry.schema.json",
        )
        self.assertEqual(registry["discovery_policy"], "default_deny")
        active = registry["active_campaigns"]
        self.assertGreaterEqual(len(active), 1)
        active_paths = {row["path"] for row in active}
        discovered = set()
        diagnostics_root = INTEGRATION_ROOT / "config" / "diagnostics"
        for path in diagnostics_root.glob("*.json"):
            document = load(path)
            if document.get("role") != registry["campaign_selector"]["role"]:
                continue
            relative = path.relative_to(REPO_ROOT).as_posix()
            self.assertEqual(document.get("status"), "authorized")
            if document.get("status") == "authorized":
                discovered.add(relative)
        # The registry is default-deny: an immutable historical campaign may
        # retain `authorized` in order not to mutate a run-manifest input, yet
        # it is no longer executable once absent from this registry.
        self.assertEqual(active_paths, discovered)
        for row in active:
            active_path = REPO_ROOT / row["path"]
            self.assertEqual(load(active_path)["status"], "authorized")
            self.assertEqual(
                row["content_sha256"],
                hashlib.sha256(active_path.read_bytes()).hexdigest(),
            )

    def test_repository_publication_writer_requires_canonical_lf_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "publication.json"
            path.write_bytes(b"{}\r\n")
            compiled = {path: b"{}\n"}
            target = (
                "integrations.rf_multipole_ion_optics_to_single_reflection_"
                "oa_tof_mass_analyzer.runtime.refresh_family_repository_bindings."
                "compile_publications"
            )
            with patch(target, return_value=compiled):
                self.assertEqual(publication_differences(REPO_ROOT), [path])
                self.assertEqual(write_publications(REPO_ROOT), [path])
                self.assertEqual(path.read_bytes(), b"{}\n")

    def test_source_adapter_is_run_independent(self) -> None:
        contract = load(CONFIG_ROOT / "family_source_adapter.json")
        validate_schema(
            contract, SCHEMA_ROOT / "rf_multipole_oatof_source_adapter.schema.json"
        )
        self.assertEqual(
            set(contract),
            {
                "schema_version",
                "role",
                "integration_id",
                "selector",
                "adapter",
                "canonical_state",
            },
        )
        serialized = json.dumps(contract)
        for forbidden in ("run_id", "particle_count", "source_branches"):
            self.assertNotIn(forbidden, serialized)

    def test_execution_policy_is_scientific_input_independent(self) -> None:
        policy = load(CONFIG_ROOT / "execution_policy.json")
        validate_schema(
            policy, SCHEMA_ROOT / "rf_multipole_oatof_execution_policy.schema.json"
        )
        self.assertEqual(policy["commercial_solver_concurrency_limit"], 1)
        self.assertNotIn("single_flight_batch_parallel_limit", policy)
        self.assertTrue(policy["stop_after_first_failure"])
        self.assertEqual(policy["retention_class"], "compact")
        self.assertEqual(
            set(policy["stage_limits"]),
            {
                "pre_pulse_interface_transport",
                "pulse_capture",
                "analyzer_transport",
                "single_flight_transport",
            },
        )
        for stage in policy["stage_limits"].values():
            self.assertEqual(stage["automatic_retry_count"], 0)
        self.assertEqual(
            {
                name: stage["compact_final_retained_bytes"]
                for name, stage in policy["stage_limits"].items()
            },
            {
                "pre_pulse_interface_transport": 26214400,
                "pulse_capture": 26214400,
                "analyzer_transport": 26214400,
                "single_flight_transport": 268435456,
            },
        )
        serialized = json.dumps(policy)
        for forbidden in ("particle_count", "source_run", "operating_mode"):
            self.assertNotIn(forbidden, serialized)

    def test_adapter_uses_frozen_execution_policy_authority(self) -> None:
        adapter = ADAPTER.read_text(encoding="utf-8-sig")
        self.assertIn("$runtime.contracts.execution_policy_contract", adapter)
        self.assertIn("$executionPolicy.policy_id", adapter)
        self.assertNotIn("$campaign.resource_profile", adapter)

    def test_adapter_uses_repository_text_identity_for_campaign(self) -> None:
        adapter = ADAPTER.read_text(encoding="utf-8-sig")
        self.assertIn(
            "(Get-RfOatofRepositoryTextSha256 -Path $campaignPath) -ne",
            adapter,
        )
        campaign_guard = adapter.split("$campaignPath =", 1)[1].split(
            "$campaign =", 1
        )[0]
        self.assertNotIn("Get-FileHash -LiteralPath $campaignPath", campaign_guard)
        self.assertLess(
            adapter.index("runtime\\runtime_binding.ps1"),
            adapter.index("$campaignPath ="),
        )

    def test_active_bindings_reference_only_stable_source_and_policy(self) -> None:
        expected_dependencies = (
            "integrations/"
            "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
            "config/family_runtime_dependencies.json"
        )
        expected_source = (
            "integrations/"
            "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
            "config/family_source_adapter.json"
        )
        expected_policy = (
            "integrations/"
            "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
            "config/execution_policy.json"
        )
        for family in FAMILIES:
            binding = load(
                CONFIG_ROOT
                / f"family_{family}_direct_mating_gap_0mm_runtime_binding.json"
            )
            validate_schema(
                binding, SCHEMA_ROOT / "rf_multipole_oatof_runtime_binding.schema.json"
            )
            self.assertEqual(binding["schema_version"], 3)
            contracts = binding["contracts"]
            self.assertNotIn("source_contract", contracts)
            self.assertNotIn("upstream_resolved_design", contracts)
            self.assertEqual(
                contracts["dependency_contract"]["path"],
                expected_dependencies,
            )
            self.assertEqual(
                contracts["source_adapter_contract"]["path"], expected_source
            )
            self.assertEqual(
                contracts["execution_policy_contract"]["path"], expected_policy
            )

    def test_retired_revision_bindings_are_absent_from_repo_and_closure(self) -> None:
        for family in FAMILIES:
            self.assertFalse(
                (
                    CONFIG_ROOT
                    / f"family_{family}_hybrid_reference_"
                    "direct_mating_gap_0mm_runtime_binding.json"
                ).exists()
            )
        targets = {
            path.relative_to(REPO_ROOT).as_posix()
            for path in compile_publications(REPO_ROOT)
        }
        self.assertFalse(any("hybrid_reference" in path for path in targets))
        self.assertFalse(any("_n100_source_contract.json" in path for path in targets))
        self.assertFalse(any("source_revision" in path for path in targets))

    def test_active_publication_closure_is_fresh(self) -> None:
        self.assertEqual(publication_differences(REPO_ROOT), [])

    def test_active_publications_follow_every_adapter_mapping(self) -> None:
        registry = load(CONFIG_ROOT / "execution_adapter_profiles.json")
        targets = {
            path.relative_to(REPO_ROOT).as_posix()
            for path in compile_publications(REPO_ROOT)
        }
        self.assertTrue(registry["mappings"])
        for mapping in registry["mappings"]:
            with self.subTest(profile=mapping["connection_profile_id"]):
                self.assertIn(mapping["runtime_binding_path"], targets)

    def test_multipole_campaign_terminal_registry_hashes_are_compiled(self) -> None:
        targets = {
            path.relative_to(REPO_ROOT).as_posix()
            for path in compile_publications(REPO_ROOT)
        }
        self.assertIn(
            "common/multipole/campaigns/"
            "20260805__oct_15mm_sleeve_8v_entrance_rf_off_n100.json",
            targets,
        )

    def test_single_flight_program_builder_is_runtime_bound(self) -> None:
        implementation = load(CONFIG_ROOT / "family_runtime_implementation.json")
        self.assertEqual(
            implementation["implementation"]["single_flight_program_builder"]["path"],
            (
                "integrations/"
                "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
                "runtime/build_single_flight_program.py"
            ),
        )
        runtime_binding = (
            INTEGRATION_ROOT / "runtime" / "runtime_binding.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn(
            "'single_flight_runner','pre_pulse_runner','pulse_capture_runner'",
            runtime_binding,
        )
        self.assertIn("foreach ($property in $implementationRecords)", runtime_binding)
        self.assertNotIn("-Expected @($implementationPaths.Keys)", runtime_binding)
        self.assertEqual(
            implementation["implementation"]["single_flight_source"]["path"],
            (
                "integrations/"
                "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
                "runtime/single_flight_source.py"
            ),
        )

    def test_single_flight_run_metadata_uses_compiled_aperture_parameters(self) -> None:
        runner = (
            INTEGRATION_ROOT / "runtime" / "run_single_flight.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn(
            "$apertureHeightMm = [double]$frontendGeometry.aperture.height_mm",
            runner,
        )
        self.assertIn("aperture_height_mm=$apertureHeightMm", runner)
        self.assertNotIn("aperture_height_mm=0.9", runner)

    def test_batch_scheduling_is_not_part_of_pa_content_identity(self) -> None:
        runner = (
            INTEGRATION_ROOT / "runtime" / "run_single_flight.ps1"
        ).read_text(encoding="utf-8-sig")
        frontend_identity = runner.split(
            "$frontendCacheIdentity = [ordered]@{", 1
        )[1].split("$frontendCacheKey =", 1)[0]
        overlay_identity = runner.split(
            "$overlayIdentity = [ordered]@{", 1
        )[1].split("$overlayKey =", 1)[0]
        self.assertNotIn("max_parallel_batches", frontend_identity)
        self.assertNotIn("max_parallel_batches", overlay_identity)
        self.assertNotIn("single_flight_batch_count", frontend_identity)
        self.assertNotIn("single_flight_batch_count", overlay_identity)
        self.assertNotIn("parallel_batch_memory_reservation_bytes", frontend_identity)
        self.assertNotIn("parallel_batch_memory_reservation_bytes", overlay_identity)
        self.assertIn("frontend_gem_sha256", frontend_identity)
        self.assertIn("overlay_gem_sha256", overlay_identity)

    def test_pa_content_identity_excludes_runtime_field_and_state_diagnostics(
        self,
    ) -> None:
        """Keep PA reuse tied to compiled geometry, not post-build semantics.

        Field profiles select the runtime field implementation and diagnostic
        transforms modify a materialized particle state.  Neither changes a PA
        basis.  Conversely, the compiled GEM hashes and the overlay electrode
        topology are physical build inputs and must remain in the cache keys.
        """
        runner = (
            INTEGRATION_ROOT / "runtime" / "run_single_flight.ps1"
        ).read_text(encoding="utf-8-sig")
        frontend_identity = runner.split(
            "$frontendCacheIdentity = [ordered]@{", 1
        )[1].split("$frontendCacheKey =", 1)[0]
        overlay_identity = runner.split(
            "$overlayIdentity = [ordered]@{", 1
        )[1].split("$overlayKey =", 1)[0]
        downstream_identity = runner.split(
            "$identity = [ordered]@{", 1
        )[1].split("$key = Get-RfContentIdentitySha256", 1)[0]

        for identity in (frontend_identity, overlay_identity, downstream_identity):
            self.assertNotIn("field_profile", identity)
            self.assertNotIn("resolved_region_field", identity)
            self.assertNotIn("diagnostic_state_transform", identity)

        self.assertIn("frontend_gem_sha256", frontend_identity)
        self.assertIn("overlay_gem_sha256", overlay_identity)
        self.assertIn("electrode_topology_id", overlay_identity)
        self.assertIn("pa_build_geometry_sha256", downstream_identity)
        self.assertNotIn("oatof_geometry_sha256", downstream_identity)

    def test_single_flight_fails_closed_on_compiled_pa_aperture_topology(self) -> None:
        runner = (
            INTEGRATION_ROOT / "runtime" / "run_single_flight.ps1"
        ).read_text(encoding="utf-8-sig")
        verifier = (
            REPO_ROOT / "common/simion/verify_aperture_topology.lua"
        ).read_text(encoding="utf-8-sig")
        self.assertIn("compiled_pa_open_column_check_required", runner)
        self.assertIn("verify_simion_aperture_topology.lua", runner)
        self.assertIn("simion_aperture_topology_support.ps1", runner)
        self.assertIn("Invoke-SimionCompiledApertureTopologyCheck", runner)
        self.assertIn("frontend_open_aperture_column_count", runner)
        refine = runner.index("'--nogui','--noprompt','refine',$cachePaSharp")
        audit = runner.index("Invoke-SimionCompiledApertureTopologyCheck")
        flight = runner.index("'--nogui','--noprompt','fly'")
        self.assertLess(refine, audit)
        self.assertLess(audit, flight)
        self.assertIn("open_columns > 0", verifier)
        self.assertIn("for ix = ix_min, ix_max", verifier)
        self.assertIn("pa:point(ix, iy, iz)", verifier)

    def test_analysis_capabilities_are_unique_and_lifecycle_bounded(self) -> None:
        catalog = load(CONFIG_ROOT / "analysis_capabilities.json")
        self.assertEqual(
            catalog["role"], "rf_multipole_oatof_analysis_capability_catalog"
        )
        capabilities = catalog["capabilities"]
        identities = [row["capability_id"] for row in capabilities]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertIn("rf_oatof_chain_checkpoint_six_panel_v1", identities)
        self.assertIn(
            "rf_oatof_grid2_downstream_six_panel_resolution_v1", identities
        )
        self.assertIn("rf_oatof_ideal_actual_resolution_gap_v1", identities)
        self.assertTrue(
            all(row["claim_class"] != "FORMAL" for row in capabilities)
        )


if __name__ == "__main__":
    unittest.main()
