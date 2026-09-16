"""Resolve fixed and dynamic fields from one eight-mode standalone PA set."""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.build_single_flight_program import (
    STANDALONE_DYNAMIC_FIELD_BANK_ROLE,
    STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,
    _successor_analyzer_config,
    resolve_standalone_dynamic_operating_coefficients,
)


MODE_IDS = tuple(range(36, 44))
SHA256 = re.compile(r"^[A-Fa-f0-9]{64}$")
ROLE_PREFIXES = {
    "coarse_frontend": "frontend",
    "accelerator_main": "accelerator_main",
    "upstream_bridge": "upstream_bridge",
    "accelerator_entrance_local": "accelerator_entrance_local",
}


def _accelerator_plan(
    analyzer: Mapping[str, Any], pulse_state: str
) -> dict[int, float]:
    """Mirror the frozen three-zone analyzer's linear electrode plan."""

    if pulse_state not in {"off", "on"}:
        raise ValueError("pulse state must be off or on")
    ids = analyzer["electrode_ids"]
    geometry = analyzer["geometry"]
    voltages = analyzer["voltages"]
    pre = 0.0
    if pulse_state == "off":
        return {
            int(electrode_id): pre
            for electrode_id in (
                ids["repeller"],
                ids["grid1"],
                *ids["rings"],
                ids["intermediate2"],
                ids["grid2"],
            )
        }
    result = {
        int(ids["repeller"]): float(voltages["repeller_v"]),
        int(ids["grid1"]): float(voltages["grid1_v"]),
        int(ids["intermediate2"]): float(voltages["intermediate2_v"]),
        int(ids["grid2"]): float(voltages["exit_v"]),
    }
    z_grid1 = float(geometry["accelerator_grid1_z_mm"])
    z_middle = float(geometry["accelerator_intermediate2_z_mm"])
    z_grid2 = float(geometry["accelerator_grid2_z_mm"])
    for electrode_id, raw_z in zip(
        ids["rings"], geometry["accelerator_ring_z_mm"], strict=True
    ):
        z = float(raw_z)
        if z <= z_middle:
            z0, z1 = z_grid1, z_middle
            v0, v1 = float(voltages["grid1_v"]), float(voltages["intermediate2_v"])
        else:
            z0, z1 = z_middle, z_grid2
            v0, v1 = float(voltages["intermediate2_v"]), float(voltages["exit_v"])
        result[int(electrode_id)] = v0 + (v1 - v0) * (z - z0) / (z1 - z0)
    return result


def resolve_mode_states(
    upstream: Mapping[str, Any],
    frontend: Mapping[str, Any],
    oatof: Mapping[str, Any],
    region_field: Mapping[str, Any],
    pa_plus_model: Mapping[str, Any],
) -> dict[str, dict[int, float]]:
    """Return carrier, unit RF response and extraction-pulse delta coefficients."""

    analyzer = _successor_analyzer_config(
        dict(oatof), dict(frontend), dict(region_field)
    )
    physical_off = {
        **_accelerator_plan(analyzer, "off"),
        int(frontend["electrodes"]["entrance_reference_sleeve_id"]): float(
            upstream["axial_dc"]["entrance_reference_sleeve"]["potential_V"]
        ),
        int(frontend["electrodes"]["entrance_plate_id"]): float(
            upstream["axial_dc"]["entrance_plate_potential_V"]
        ),
    }
    physical_on = dict(physical_off)
    physical_on.update(_accelerator_plan(analyzer, "on"))
    projection = resolve_standalone_dynamic_operating_coefficients(
        pa_plus_model,
        upstream,
        accelerator_off_physical_voltages_v=physical_off,
        accelerator_on_physical_voltages_v=physical_on,
    )
    carrier = {
        int(mode_id): float(value)
        for mode_id, value in projection["carrier_off_mode_coefficients_v"].items()
    }
    pulse_delta = {
        int(mode_id): float(value)
        for mode_id, value in projection["pulse_delta_mode_coefficients_v"].items()
    }
    rf_unit = {
        int(mode_id): float(value)
        for mode_id, value in projection[
            "rf_differential_mode_coefficients_per_v"
        ].items()
    }
    states = {"carrier_off": carrier, "rf_differential_unit": rf_unit, "pulse_delta": pulse_delta}
    if any(
        set(values) != set(MODE_IDS) or any(not math.isfinite(value) for value in values.values())
        for values in states.values()
    ):
        raise ValueError("standalone eight-mode voltage state is incomplete")
    return states


def composition_terms(
    records: Sequence[Mapping[str, Any]], coefficients: Mapping[int, float]
) -> tuple[str, list[dict[str, Any]]]:
    """Represent a linear state with the smallest useful response working set."""

    by_id = {int(record["response_id"]): str(record["path"]) for record in records}
    if set(by_id) != set(MODE_IDS):
        raise ValueError("standalone response selection must contain modes 36 through 43")
    nonzero_ids = [mode_id for mode_id in MODE_IDS if float(coefficients[mode_id]) != 0.0]
    base_id = nonzero_ids[0] if nonzero_ids else 36
    base = by_id[base_id]
    terms = []
    for mode_id in MODE_IDS:
        coefficient = float(coefficients[mode_id]) - (1.0 if mode_id == base_id else 0.0)
        if coefficient != 0.0:
            terms.append({"path": by_id[mode_id], "coefficient": coefficient})
    if not terms:
        # The composer requires one response; adding an exact zero preserves bytes.
        zero_id = 36 if base_id != 36 else 37
        terms.append({"path": by_id[zero_id], "coefficient": 0.0})
    return base, terms


def _selection_records(role: str, selection: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Strictly accept only the adapter's manifest-validated selection schema."""

    if (
        set(selection) != {"schema_version", "role", "prefix", "records"}
        or selection.get("schema_version") != 1
        or selection.get("role") != "rf_oatof_standalone_pa_response_selection"
        or selection.get("prefix") != ROLE_PREFIXES.get(role)
    ):
        raise ValueError(f"standalone selection identity differs for {role}")
    values = selection.get("records")
    if not isinstance(values, list) or len(values) != len(MODE_IDS):
        raise ValueError(f"standalone selection records differ for {role}")
    records: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, dict) or set(value) != {
            "response_id",
            "name",
            "path",
            "bytes",
            "sha256",
        }:
            raise ValueError(f"standalone selection record fields differ for {role}")
        response_id = value["response_id"]
        name = value["name"]
        path = Path(str(value["path"]))
        size = value["bytes"]
        digest = value["sha256"]
        if (
            isinstance(response_id, bool)
            or not isinstance(response_id, int)
            or response_id not in MODE_IDS
            or not isinstance(name, str)
            or name
            != f"{ROLE_PREFIXES[role]}.response_{response_id}.pa"
            or not path.is_absolute()
            or path.name != name
            or not name.lower().endswith(".pa")
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or not isinstance(digest, str)
            or SHA256.fullmatch(digest) is None
        ):
            raise ValueError(f"standalone selection record identity differs for {role}")
        records.append(dict(value))
    if [int(record["response_id"]) for record in records] != list(MODE_IDS):
        raise ValueError(f"standalone selection response order differs for {role}")
    return records


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _role_spec(value: str) -> tuple[str, int, Path]:
    parts = value.split("=", 2)
    if len(parts) != 3:
        raise ValueError("role selections use ROLE=INSTANCE_INDEX=SELECTION.json")
    role, raw_index, path = parts
    index = int(raw_index)
    if not role or index < 1:
        raise ValueError("role selection identity is invalid")
    return role, index, Path(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--frontend", type=Path, required=True)
    parser.add_argument("--oatof", type=Path, required=True)
    parser.add_argument("--region-field", type=Path, required=True)
    parser.add_argument("--accelerator-main", type=Path, required=True)
    parser.add_argument("--role-selection", action="append", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--field-bank", type=Path, required=True)
    args = parser.parse_args()

    accelerator = _load(args.accelerator_main)
    states = resolve_mode_states(
        _load(args.upstream),
        _load(args.frontend),
        _load(args.oatof),
        _load(args.region_field),
        accelerator["pa_plus_solution_model"],
    )
    roles = [_role_spec(value) for value in args.role_selection]
    if len({role for role, _, _ in roles}) != len(roles) or len(
        {index for _, index, _ in roles}
    ) != len(roles):
        raise ValueError("standalone field roles and instance indices must be unique")
    compositions: list[dict[str, Any]] = []
    response_copies: list[dict[str, Any]] = []
    dynamic_roles: list[dict[str, Any]] = []
    args.output_directory.mkdir(parents=True, exist_ok=True)
    for role, index, selection_path in roles:
        selection = _load(selection_path)
        records = _selection_records(role, selection)
        runtime_records: list[dict[str, Any]] = []
        for record in records:
            mode_id = int(record["response_id"])
            destination = (
                args.output_directory / f"__compose_{role}_mode_{mode_id}.pa"
            ).resolve()
            response_copies.append(
                {
                    "role": role,
                    "response_id": mode_id,
                    "source": str(record["path"]),
                    "output": str(destination),
                    "bytes": int(record["bytes"]),
                    "sha256": str(record["sha256"]),
                }
            )
            runtime_records.append(
                {"response_id": mode_id, "path": str(destination)}
            )
        carrier_name = f"{role}.carrier_off.pa"
        pulse_name = f"{role}.pulse_delta.pa"
        rf_name = f"{role}.rf_differential.pa"
        for kind, output_name in (
            ("carrier_off", carrier_name),
            ("pulse_delta", pulse_name),
            ("rf_differential_unit", rf_name),
        ):
            base, terms = composition_terms(runtime_records, states[kind])
            compositions.append(
                {
                    "role": role,
                    "kind": kind,
                    "base": base,
                    "output": str((args.output_directory / output_name).resolve()),
                    "terms": terms,
                }
            )
        dynamic_roles.append(
            {
                "role": role,
                "instance_index": index,
                "carrier_pa_basename": carrier_name,
                "rf_differential_pa_basename": rf_name,
                "pulse_delta_pa_basename": pulse_name,
            }
        )
    plan = {
        "schema_version": 1,
        "role": "rf_oatof_standalone_field_composition_plan",
        "mode_states_v": {
            key: {str(mode_id): value for mode_id, value in state.items()}
            for key, state in states.items()
        },
        "response_copies": response_copies,
        "compositions": compositions,
    }
    bank = {
        "schema_version": 1,
        "role": STANDALONE_DYNAMIC_FIELD_BANK_ROLE,
        "runtime_representation": STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,
        "dynamic_roles": sorted(dynamic_roles, key=lambda item: item["instance_index"]),
    }
    for path, document in ((args.plan, plan), (args.field_bank, bank)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
