"""Tests for campaign-only stable runtime authorities."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from common.contracts.machine_contracts import validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.refresh_family_repository_bindings import (
    compile_publications,
    publication_differences,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = INTEGRATION_ROOT / "config"
ADAPTER = INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1"
FAMILIES = ("quadrupole", "hexapole", "octupole")


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class CampaignRuntimeAuthoritiesTests(unittest.TestCase):
    def test_source_adapter_is_run_independent(self) -> None:
        contract = load(CONFIG_ROOT / "family_source_adapter.json")
        validate_schema(contract, "rf_multipole_oatof_source_adapter.schema.json")
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
        validate_schema(policy, "rf_multipole_oatof_execution_policy.schema.json")
        self.assertEqual(policy["commercial_solver_concurrency_limit"], 1)
        self.assertTrue(policy["stop_after_first_failure"])
        self.assertEqual(policy["retention_class"], "compact")
        self.assertEqual(
            set(policy["stage_limits"]),
            {
                "pre_pulse_interface_transport",
                "pulse_capture",
                "analyzer_transport",
            },
        )
        for stage in policy["stage_limits"].values():
            self.assertEqual(stage["automatic_retry_count"], 0)
        serialized = json.dumps(policy)
        for forbidden in ("particle_count", "source_run", "operating_mode"):
            self.assertNotIn(forbidden, serialized)

    def test_adapter_uses_frozen_execution_policy_authority(self) -> None:
        adapter = ADAPTER.read_text(encoding="utf-8-sig")
        self.assertIn("$runtime.contracts.execution_policy_contract", adapter)
        self.assertIn("$executionPolicy.policy_id", adapter)
        self.assertNotIn("$campaign.resource_profile", adapter)

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
            validate_schema(binding, "rf_multipole_oatof_runtime_binding.schema.json")
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


if __name__ == "__main__":
    unittest.main()
