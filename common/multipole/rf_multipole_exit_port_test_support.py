from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from common.contracts.file_identity import repository_text_sha256
from common.contracts.machine_contracts import validate_schema
from common.multipole.design_profile import resolve_design_profile


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _pointer_value(document: Any, pointer: str) -> Any:
    value = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def set_up_exit_port_contract(
    case: type[unittest.TestCase],
    project_root: Path,
    project_id: str,
) -> None:
    repo_root = project_root.parents[1]
    case.port = _load(
        project_root / "config" / "interfaces" / "provided" / "rf_multipole_exit.json"
    )
    case.source_path = repo_root / case.port["authority"]["source_contract"]
    case.source = _load(case.source_path)
    case.resolved = resolve_design_profile(
        repo_root, project_id, "no_acceleration_full_length"
    )["resolved_design"]

def assert_authority_bindings_and_freshness(case: unittest.TestCase) -> None:
    case.assertEqual(case.source, case.resolved)
    validate_schema(case.port, "component_port.schema.json")
    case.assertEqual(
        case.port["authority"]["source_sha256"],
        repository_text_sha256(case.source_path),
    )
    for binding in case.port["authority"]["bindings"]:
        case.assertEqual(
            _pointer_value(case.port, binding["port_json_pointer"]),
            _pointer_value(case.source, binding["source_json_pointer"]),
        )


def assert_derived_exit_geometry_clock_and_field_boundary(
    case: unittest.TestCase,
) -> None:
    case.assertEqual(case.port["port_id"], "rf_multipole_exit")
    case.assertEqual(
        case.port["profile_scope"],
        {
            "scope_id": "no_acceleration_full_length",
            "scope_kind": "design_profile",
            "family_experiment_port": True,
        },
    )
    coordinate = case.source["coordinate"]
    case.assertEqual(
        case.port["coordinate_frame"]["frame_id"],
        coordinate["coordinate_id"].replace(".", "_"),
    )
    case.assertEqual(coordinate["axial_axis"], "+z")
    handoff_z = case.source["interfaces_mm"]["exit"]["handoff_plane_z_mm"]
    case.assertEqual(
        case.port["mating_surface"]["center_mm"], [0.0, 0.0, handoff_z]
    )
    case.assertEqual(case.port["mating_surface"]["outward_normal"], [0.0, 0.0, 1.0])
    case.assertEqual(case.source["drive"]["phase_rad"], 0.0)
    case.assertEqual(case.source["units"]["frequency"], "Hz")
    case.assertEqual(
        case.port["clock"],
        {"time_unit": "s", "origin_id": "instrument_clock_epoch_v1"},
    )
    field_reaches_surface = (
        handoff_z < case.source["geometry_mm"]["enclosure"]["vacuum_z_max_mm"]
    )
    case.assertEqual(
        case.port["field_boundary"]["field_reaches_surface"], field_reaches_surface
    )
