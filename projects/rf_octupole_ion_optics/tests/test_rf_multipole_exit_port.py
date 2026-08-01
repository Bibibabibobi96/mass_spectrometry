from __future__ import annotations

import json
import unittest
from pathlib import Path

from common.contracts.file_identity import repository_text_sha256
from typing import Any

from common.contracts.machine_contracts import validate_schema
from common.multipole.design_profile import resolve_design_profile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
PORT_PATH = (
    PROJECT_ROOT / "config" / "interfaces" / "provided" / "rf_multipole_exit.json"
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
        source_relative = cls.port["authority"]["source_contract"]
        cls.source_path = REPO_ROOT / source_relative
        cls.source = load(cls.source_path)
        cls.resolved = resolve_design_profile(
            REPO_ROOT,
            "rf_octupole_ion_optics",
            "no_acceleration_full_length",
        )["resolved_design"]

    def test_schema_authority_bindings_and_freshness(self) -> None:
        self.assertEqual(self.source, self.resolved)
        validate_schema(self.port, "component_port.schema.json")
        self.assertEqual(
            self.port["authority"]["source_sha256"],
            repository_text_sha256(self.source_path),
        )
        for binding in self.port["authority"]["bindings"]:
            self.assertEqual(
                pointer_value(self.port, binding["port_json_pointer"]),
                pointer_value(self.source, binding["source_json_pointer"]),
            )

    def test_exit_geometry_clock_and_field_boundary_are_derived(self) -> None:
        self.assertEqual(self.port["port_id"], "rf_multipole_exit")
        self.assertEqual(
            self.port["profile_scope"],
            {
                "scope_id": "no_acceleration_full_length",
                "scope_kind": "design_profile",
                "family_experiment_port": True,
            },
        )
        coordinate = self.source["coordinate"]
        self.assertEqual(
            self.port["coordinate_frame"]["frame_id"],
            coordinate["coordinate_id"].replace(".", "_"),
        )
        self.assertEqual(coordinate["axial_axis"], "+z")
        handoff_z = self.source["interfaces_mm"]["exit"]["handoff_plane_z_mm"]
        self.assertEqual(self.port["mating_surface"]["center_mm"], [0.0, 0.0, handoff_z])
        self.assertEqual(self.port["mating_surface"]["outward_normal"], [0.0, 0.0, 1.0])
        self.assertEqual(self.source["drive"]["phase_rad"], 0.0)
        self.assertEqual(self.source["units"]["frequency"], "Hz")
        self.assertEqual(
            self.port["clock"],
            {"time_unit": "s", "origin_id": "instrument_clock_epoch_v1"},
        )
        field_reaches_surface = (
            handoff_z
            < self.source["geometry_mm"]["enclosure"]["vacuum_z_max_mm"]
        )
        self.assertEqual(
            self.port["field_boundary"]["field_reaches_surface"],
            field_reaches_surface,
        )


if __name__ == "__main__":
    unittest.main()
