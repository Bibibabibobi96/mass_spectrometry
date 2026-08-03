from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from common.integration.adapter_contract import (
    load_execution_adapter_registry,
    resolve_execution_mapping,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_ROOT = (
    REPO_ROOT
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)


class IntegrationAdapterContractTests(unittest.TestCase):
    def test_all_profile_mappings_resolve_frozen_runtime_bindings(self) -> None:
        registry = load_execution_adapter_registry(
            INTEGRATION_ROOT / "config" / "execution_adapter_profiles.json"
        )
        profile_ids = {
            item["connection_profile_id"] for item in registry["mappings"]
        }
        connection_registry = json.loads(
            (
                INTEGRATION_ROOT / "config" / "connection_profiles.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            profile_ids,
            {
                item["connection_profile_id"]
                for item in connection_registry["profiles"]
            },
        )
        for profile_id in profile_ids:
            mapping = resolve_execution_mapping(
                registry,
                profile_id,
                repo_root=REPO_ROOT,
            )
            adapter = REPO_ROOT / mapping["adapter_entrypoint"]
            self.assertEqual(file_sha256(adapter), mapping["adapter_sha256"])
            binding = REPO_ROOT / mapping["runtime_binding_path"]
            self.assertTrue(binding.is_file())
            self.assertEqual(
                file_sha256(binding),
                mapping["runtime_binding_sha256"],
            )
            self.assertNotIn("workflow_entrypoint", mapping)
            self.assertNotIn("connector_case_id", mapping)

    def test_mapping_rejects_stale_adapter_sha256(self) -> None:
        path = INTEGRATION_ROOT / "config" / "execution_adapter_profiles.json"
        invalid = copy.deepcopy(json.loads(path.read_text(encoding="utf-8")))
        invalid["mappings"][0]["adapter_sha256"] = "0" * 64
        with self.assertRaisesRegex(ContractError, "adapter SHA-256 is stale"):
            resolve_execution_mapping(
                invalid,
                invalid["mappings"][0]["connection_profile_id"],
                repo_root=REPO_ROOT,
            )

    def test_mapping_vocabulary_rejects_physical_overrides(self) -> None:
        path = INTEGRATION_ROOT / "config" / "execution_adapter_profiles.json"
        invalid = copy.deepcopy(json.loads(path.read_text(encoding="utf-8")))
        invalid["mappings"][0]["connector_length_mm"] = 1.0
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory) / "invalid_adapter.json"
            temporary.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaises(ContractError):
                load_execution_adapter_registry(temporary)

if __name__ == "__main__":
    unittest.main()
