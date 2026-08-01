from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import validate_schema
from common.multipole.design_profile import resolve_design_profile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
PORT_PATH = (
    PROJECT_ROOT / "config" / "interfaces" / "provided" / "rf_multipole_exit.json"
)
FAMILY_PORT_PATH = PORT_PATH.with_name(
    "rf_multipole_exit_no_acceleration_full_length.json"
)
def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pointer_value(document: Any, pointer: str) -> Any:
    value = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


class RfMultipoleExitPortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.port = load(PORT_PATH)
        cls.source_path = REPO_ROOT / cls.port["authority"]["source_contract"]
        cls.source = load(cls.source_path)

    def test_schema_authority_bindings_and_freshness(self) -> None:
        validate_schema(self.port, "component_port.schema.json")
        self.assertEqual(
            self.port["authority"]["source_sha256"],
            hashlib.sha256(self.source_path.read_bytes()).hexdigest().upper(),
        )
        for binding in self.port["authority"]["bindings"]:
            self.assertEqual(
                pointer_value(self.port, binding["port_json_pointer"]),
                pointer_value(self.source, binding["source_json_pointer"]),
            )

    def test_scope_is_official_oatof_oracle_not_family_experiment(self) -> None:
        self.assertEqual(self.port["port_id"], "rf_multipole_exit")
        self.assertEqual(
            self.port["profile_scope"],
            {
                "scope_id": "official_transport_oatof_oracle",
                "scope_kind": "integration_oracle",
                "family_experiment_port": False,
            },
        )
        self.assertEqual(
            self.source["geometry_mm"]["enclosure"]["model"],
            "rectangular_reference_enclosure_v1",
        )
        self.assertEqual(
            self.source["interfaces_mm"]["exit"]["connector_shape"],
            "rectangular_bore",
        )

    def test_exit_surface_and_potential_match_source_authority(self) -> None:
        handoff_z = self.source["interfaces_mm"]["exit"]["handoff_plane_z_mm"]
        self.assertEqual(
            self.port["mating_surface"]["center_mm"],
            [0.0, 0.0, handoff_z],
        )
        self.assertEqual(
            self.port["mating_surface"]["outward_normal"],
            [0.0, 0.0, 1.0],
        )
        self.assertEqual(
            self.port["field_boundary"]["field_reaches_surface"],
            handoff_z < self.source["geometry_mm"]["enclosure"]["vacuum_z_max_mm"],
        )
        self.assertEqual(
            self.port["clock"],
            {"time_unit": "s", "origin_id": "instrument_clock_epoch_v1"},
        )


class NoAccelerationFamilyExitPortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.oracle_port = load(PORT_PATH)
        cls.port = load(FAMILY_PORT_PATH)
        cls.source_path = REPO_ROOT / cls.port["authority"]["source_contract"]
        cls.source = load(cls.source_path)
        cls.resolved = resolve_design_profile(
            REPO_ROOT,
            "rf_quadrupole_ion_optics",
            "no_acceleration_full_length",
        )["resolved_design"]

    def test_publication_and_port_are_fresh_from_the_governed_profile(self) -> None:
        self.assertEqual(self.source, self.resolved)
        validate_schema(self.port, "component_port.schema.json")
        self.assertEqual(
            self.port["authority"]["source_sha256"],
            hashlib.sha256(self.source_path.read_bytes()).hexdigest().upper(),
        )
        for binding in self.port["authority"]["bindings"]:
            self.assertEqual(
                pointer_value(self.port, binding["port_json_pointer"]),
                pointer_value(self.source, binding["source_json_pointer"]),
            )

    def test_family_scope_does_not_replace_the_oatof_oracle_scope(self) -> None:
        self.assertEqual(
            self.port["profile_scope"],
            {
                "scope_id": "no_acceleration_full_length",
                "scope_kind": "design_profile",
                "family_experiment_port": True,
            },
        )
        self.assertNotEqual(
            self.port["mating_surface"]["center_mm"],
            self.oracle_port["mating_surface"]["center_mm"],
        )
        self.assertEqual(
            self.oracle_port["profile_scope"]["scope_kind"],
            "integration_oracle",
        )


if __name__ == "__main__":
    unittest.main()
