from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import validate_schema


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
PORT_PATH = (
    PROJECT_ROOT / "config" / "interfaces" / "provided" / "rf_multipole_exit.json"
)
S2_REGISTRATION_PATH = (
    PROJECT_ROOT / "config" / "resolved_rf_to_oatof_s2_spatial_registration.json"
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
        cls.s2_registration = load(S2_REGISTRATION_PATH)
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

    def test_exit_surface_and_potential_match_s2_oracle(self) -> None:
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
            self.port["mating_surface"]["center_mm"],
            self.s2_registration["resolved_surfaces"]["source_exit"]["declared"][
                "center_mm"
            ],
        )
        self.assertEqual(
            self.port["mating_surface"]["potential_V"],
            self.s2_registration["authoritative_scalar_bindings"][
                "interface_common_reference"
            ]["value"],
        )
        self.assertEqual(
            self.port["mating_surface"]["potential_V"],
            self.s2_registration["authoritative_scalar_bindings"][
                "rf_exit_enclosure_dc"
            ]["value"],
        )
        self.assertEqual(
            self.port["field_boundary"]["field_reaches_surface"],
            handoff_z < self.source["geometry_mm"]["enclosure"]["vacuum_z_max_mm"],
        )
        self.assertEqual(
            self.port["clock"],
            {"time_unit": "s", "origin_id": "instrument_clock_epoch_v1"},
        )


if __name__ == "__main__":
    unittest.main()
