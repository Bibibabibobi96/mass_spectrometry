from __future__ import annotations

import json
from pathlib import Path
import unittest

from common.contracts.file_identity import repository_text_sha256
from common.contracts.machine_contracts import validate_schema


REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = INTEGRATION_ROOT / "config"
INVENTORY = CONFIG_ROOT / "family_runtime_dependencies.json"
FAMILIES = ("quadrupole", "hexapole", "octupole")


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class FamilyDependencyResolutionTests(unittest.TestCase):
    def test_single_stable_64_item_inventory(self) -> None:
        inventory = load(INVENTORY)
        dependencies = inventory["dependencies"]
        ids = [item["id"] for item in dependencies]
        run_inputs = [item["run_input_name"] for item in dependencies]
        self.assertEqual(len(dependencies), 64)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(run_inputs), len(set(run_inputs)))
        self.assertEqual(
            inventory["consumer_scope"],
            "rf_multipole_registered_handoff_family",
        )
        for removed in (
            "rf_resolved_design",
            "rf_project_descriptor",
            "rf_family_source_bundle_publisher",
        ):
            self.assertNotIn(removed, ids)

    def test_inventory_paths_are_explicit_repository_files(self) -> None:
        inventory = load(INVENTORY)
        for dependency in inventory["dependencies"]:
            with self.subTest(dependency=dependency["id"]):
                relative = Path(dependency["source_repo_path"])
                self.assertFalse(relative.is_absolute())
                self.assertNotIn("..", relative.parts)
                self.assertTrue((REPO_ROOT / relative).is_file())

    def test_obsolete_base_and_overlays_are_absent(self) -> None:
        self.assertFalse((CONFIG_ROOT / "family_dependencies_base.json").exists())
        for family in FAMILIES:
            self.assertFalse(
                (CONFIG_ROOT / f"family_{family}_dependencies_overlay.json").exists()
            )

    def test_active_bindings_use_one_inventory_authority(self) -> None:
        expected_path = INVENTORY.relative_to(REPO_ROOT).as_posix()
        expected_sha256 = repository_text_sha256(INVENTORY)
        for family in FAMILIES:
            binding = load(
                CONFIG_ROOT
                / f"family_{family}_direct_mating_gap_0mm_runtime_binding.json"
            )
            validate_schema(binding, "rf_multipole_oatof_runtime_binding.schema.json")
            self.assertEqual(
                binding["contracts"]["dependency_contract"],
                {"path": expected_path, "sha256": expected_sha256},
            )

    def test_phase_contracts_use_run_local_source_and_design(self) -> None:
        expected = {
            "source_contract": "run_input:resolved_source_contract",
            "rf_resolved_geometry": "run_input:upstream_resolved_design",
        }
        for name in (
            "family_pre_pulse_interface_transport.json",
            "family_pulse_capture.json",
            "family_shared_physical_port_joint_geometry.json",
        ):
            contract = load(CONFIG_ROOT / name)
            inputs = contract.get("inputs", contract.get("authoritative_inputs"))
            with self.subTest(contract=name):
                for key, value in expected.items():
                    self.assertEqual(inputs[key], value)
        handoff = load(CONFIG_ROOT / "family_handoff.json")["source_component"]
        self.assertEqual(
            handoff["profile"],
            "run_input:upstream_resolved_design:/design_profile_id",
        )
        self.assertEqual(
            handoff["event"],
            "run_input:resolved_source_contract:/selector/event",
        )
        self.assertEqual(
            handoff["required_status"],
            "run_input:resolved_source_contract:/selector/status",
        )


if __name__ == "__main__":
    unittest.main()
