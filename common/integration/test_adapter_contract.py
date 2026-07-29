from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.machine_contracts import ContractError
from common.integration.adapter_contract import (
    load_execution_adapter_registry,
    resolve_execution_mapping,
    validate_migration_preregistration,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_ROOT = (
    REPO_ROOT
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)


class IntegrationAdapterContractTests(unittest.TestCase):
    def test_both_profile_mappings_resolve_the_semantic_transfer_entry(self) -> None:
        registry = load_execution_adapter_registry(
            INTEGRATION_ROOT / "config" / "execution_adapter_profiles.json"
        )
        profile_ids = {
            item["connection_profile_id"] for item in registry["mappings"]
        }
        self.assertEqual(len(profile_ids), 2)
        for profile_id in profile_ids:
            mapping = resolve_execution_mapping(
                registry,
                profile_id,
                repo_root=REPO_ROOT,
            )
            self.assertTrue(
                mapping["workflow_entrypoint"].endswith(
                    "workflows/rf_to_oatof_integration/run_rf_to_oatof_transfer.ps1"
                )
            )
            self.assertNotIn("workflow_entrypoints", mapping)
            self.assertNotIn("legacy_entrypoints", mapping)
            self.assertNotIn("connector_case_id", mapping)

    def test_mapping_vocabulary_rejects_physical_overrides(self) -> None:
        path = INTEGRATION_ROOT / "config" / "execution_adapter_profiles.json"
        invalid = copy.deepcopy(json.loads(path.read_text(encoding="utf-8")))
        invalid["mappings"][0]["connector_length_mm"] = 1.0
        temporary_root = REPO_ROOT / ".tmp"
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            temporary = Path(directory) / "invalid_adapter.json"
            temporary.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaises(ContractError):
                load_execution_adapter_registry(temporary)

    def test_equivalence_preregistration_is_blocked_and_oracle_bound(self) -> None:
        document = validate_migration_preregistration(
            INTEGRATION_ROOT
            / "config"
            / "migration_equivalence_preregistration.json",
            repo_root=REPO_ROOT,
            expected_profile_ids={
                "rf_quadrupole_grounded_connector_gap_1mm",
                "rf_quadrupole_direct_mating_gap_0mm",
            },
        )
        self.assertEqual(document["equivalence_status"], "BLOCKED")
        self.assertEqual(document["execution_status"], "NOT_RUN")


if __name__ == "__main__":
    unittest.main()
