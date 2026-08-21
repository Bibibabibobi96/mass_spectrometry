"""Static current-contract tests for the RF-multipole to oaTOF integration."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from common.contracts.machine_contracts import ContractError, validate_schema
from common.integration.resolve_connection import (
    load_connection_profile_registry,
    resolve_connection_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
PROFILE_REGISTRY_PATH = INTEGRATION_ROOT / "config" / "connection_profiles.json"
ADAPTER_REGISTRY_PATH = INTEGRATION_ROOT / "config" / "execution_adapter_profiles.json"
GLOBAL_REGISTRY_PATH = REPO_ROOT / "integrations" / "registry.json"
OATOF_REQUIRED_PORT_PATH = (
    REPO_ROOT
    / "projects"
    / "single_reflection_oa_tof_mass_analyzer"
    / "config"
    / "interfaces"
    / "required"
    / "oatof_accelerator_entry.json"
)
PRE_PULSE_PHASE_PATH = (
    INTEGRATION_ROOT / "config" / "family_pre_pulse_interface_transport.json"
)
PULSE_CAPTURE_PHASE_PATH = INTEGRATION_ROOT / "config" / "family_pulse_capture.json"
SOURCE_ADAPTER_PATH = INTEGRATION_ROOT / "config" / "family_source_adapter.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class IntegrationProfileContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_json(PROFILE_REGISTRY_PATH)
        cls.profiles = {
            profile["connection_profile_id"]: profile
            for profile in cls.registry["profiles"]
        }

    def test_global_registry_points_to_single_profile_authority(self) -> None:
        registry = load_json(GLOBAL_REGISTRY_PATH)
        validate_schema(registry, "integration_registry.schema.json")
        self.assertEqual(len(registry["integrations"]), 1)
        entry = registry["integrations"][0]
        self.assertEqual(entry["integration_id"], self.registry["integration_id"])
        self.assertEqual(
            (REPO_ROOT / entry["profile_registry"]).resolve(),
            PROFILE_REGISTRY_PATH.resolve(),
        )

    def test_static_profiles_require_run_local_port_materialization(self) -> None:
        registry = load_connection_profile_registry(PROFILE_REGISTRY_PATH)
        downstream_port = load_json(OATOF_REQUIRED_PORT_PATH)
        self.assertEqual(
            downstream_port["mating_surface"]["aperture_radius_mm"],
            5.0,
        )
        self.assertNotIn("transition_aperture", downstream_port)
        self.assertEqual(
            set(self.profiles),
            {
                "rf_quadrupole_oatof_shield_terminal_direct_mating_gap_0mm",
                "rf_hexapole_oatof_shield_terminal_direct_mating_gap_0mm",
                "rf_octupole_oatof_shield_terminal_direct_mating_gap_0mm",
                "rf_octupole_oatof_shield_terminal_direct_mating_gap_3p2mm",
                "rf_octupole_oatof_shield_terminal_direct_mating_gap_6p4mm",
                "rf_octupole_oatof_shield_terminal_direct_mating_gap_12p8mm",
                "rf_octupole_oatof_shield_terminal_direct_mating_gap_25p6mm",
                "rf_octupole_to_single_reflection_oatof_direct_mating_gap_51p2mm",
                "rf_octupole_to_single_reflection_oatof_direct_mating_gap_102p4mm",
                "rf_octupole_oatof_shield_terminal_aperture_050x050_direct_mating_gap_0mm",
                "rf_octupole_oatof_shield_terminal_aperture_050x020_direct_mating_gap_0mm",
            },
        )
        for profile_id in sorted(self.profiles):
            with self.subTest(profile_id=profile_id):
                upstream = self.profiles[profile_id]["upstream"]
                self.assertEqual(
                    upstream.get("port_binding"),
                    "source_run_resolved_design",
                )
                self.assertNotIn("port_contract", upstream)
                with self.assertRaisesRegex(ContractError, "binding is unresolved"):
                    resolve_connection_profile(
                        registry,
                        profile_id,
                        repo_root=REPO_ROOT,
                    )

    def test_runtime_and_source_schemas_reject_unknown_synonym_fields(self) -> None:
        adapter_registry = load_json(ADAPTER_REGISTRY_PATH)
        binding_path = REPO_ROOT / adapter_registry["mappings"][0][
            "runtime_binding_path"
        ]
        binding = load_json(binding_path)
        binding["workflow_entrypoint"] = "forbidden-synonym"
        with self.assertRaises(ContractError):
            validate_schema(
                binding,
                "rf_multipole_oatof_runtime_binding.schema.json",
            )
        source = load_json(SOURCE_ADAPTER_PATH)
        source["project_id"] = "forbidden-synonym"
        with self.assertRaises(ContractError):
            validate_schema(
                source,
                "rf_multipole_oatof_source_adapter.schema.json",
            )

    def test_phase_configuration_has_no_connection_topology_authority(self) -> None:
        forbidden_keys = {
            "nominal_registration",
            "passive_connector_geometry",
            "connector_gap_mm",
            "length_mm",
            "inner_radius_mm",
            "downstream_entry_aperture",
            "target_entry_center_instrument_mm",
            "source_exit_center_instrument_mm",
            "connector_cases",
        }

        def collect_keys(value: object) -> set[str]:
            if isinstance(value, dict):
                return set(value) | set().union(
                    *(collect_keys(item) for item in value.values())
                )
            if isinstance(value, list):
                return set().union(*(collect_keys(item) for item in value))
            return set()

        for path, expected_phase in (
            (PRE_PULSE_PHASE_PATH, "pre_pulse_interface_transport"),
            (PULSE_CAPTURE_PHASE_PATH, "pulse_capture"),
        ):
            with self.subTest(path=path.name):
                phase = load_json(path)
                self.assertEqual(phase["phase"], expected_phase)
                self.assertEqual(phase["topology_source"], "resolved_connection")
                self.assertFalse(collect_keys(phase) & forbidden_keys)

    def test_active_pre_pulse_runner_requires_resolved_connection(self) -> None:
        runner = (
            INTEGRATION_ROOT
            / "stages"
            / "comsol"
            / "run_pre_pulse_interface_transport.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("[Parameter(Mandatory)][string]$ConnectionProfileId", runner)
        self.assertIn("[Parameter(Mandatory)][string]$ResolvedConnection", runner)
        self.assertIn("resolvedConnectionDocument.connector.length_mm", runner)
        self.assertNotIn("ConnectorCaseId", runner)
        self.assertNotIn("connector_cases", runner)


if __name__ == "__main__":
    unittest.main()
