from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import load_json, sha256, validate_schema


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PORT_PATH = (
    PROJECT_ROOT
    / "config"
    / "interfaces"
    / "required"
    / "oatof_accelerator_entry.json"
)
STATE_SCHEMA_PATH = (
    REPO_ROOT / "common" / "contracts" / "schemas" / "component_particle_state.schema.json"
)


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    value = document
    for raw_token in pointer.removeprefix("/").split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


class RequiredComponentPortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.port = load_json(PORT_PATH)
        source_relative = cls.port["authority"]["source_contract"]
        cls.source_path = REPO_ROOT / source_relative
        cls.source = load_json(cls.source_path)

    def test_port_validates_against_public_schema(self) -> None:
        validate_schema(self.port, "component_port.schema.json")
        self.assertEqual(self.port["port_id"], "oatof_accelerator_entry")
        self.assertEqual(self.port["direction"], "required")
        self.assertEqual(
            self.port["profile_scope"],
            {
                "scope_id": "formal_reference",
                "scope_kind": "formal_reference",
                "family_experiment_port": False,
            },
        )

    def test_authority_hash_and_direct_bindings_are_fresh(self) -> None:
        self.assertEqual(sha256(self.source_path), self.port["authority"]["source_sha256"])
        for binding in self.port["authority"]["bindings"]:
            with self.subTest(binding=binding):
                self.assertEqual(
                    resolve_json_pointer(self.port, binding["port_json_pointer"]),
                    resolve_json_pointer(self.source, binding["source_json_pointer"]),
                )

    def test_surface_location_and_normal_are_derived_from_resolved_geometry(self) -> None:
        geometry = self.source["geometry_mm"]
        convention = self.source["coordinate_convention"]
        particle_source = self.source["particle_source"]
        expected_x = (
            convention["accelerator_axis_x"]
            - geometry["accelerator_bore_half"]
            - geometry["accelerator_ring_width"]
            - geometry["accelerator_insulation_gap"]
            - geometry["accelerator_shield_wall"]
        )
        self.assertAlmostEqual(self.port["mating_surface"]["center_mm"][0], expected_x)
        expected_normal = [
            -particle_source["direction_x"],
            -particle_source["direction_y"],
            -particle_source["direction_z"],
        ]
        self.assertEqual(self.port["mating_surface"]["outward_normal"], expected_normal)

    def test_port_publishes_the_canonical_particle_state_and_acceptance_basis(self) -> None:
        state_schema = load_json(STATE_SCHEMA_PATH)
        self.assertEqual(
            self.port["state_contract"],
            {"schema_id": "component_particle_state", "schema_version": 1},
        )
        self.assertEqual(state_schema["required"], state_schema["x-csv-column-order"])
        self.assertEqual(len(state_schema["required"]), 28)
        self.assertEqual(
            self.port["clock"],
            {"time_unit": "s", "origin_id": "instrument_clock_epoch_v1"},
        )
        self.assertTrue(self.port["field_boundary"]["field_reaches_surface"])


if __name__ == "__main__":
    unittest.main()
