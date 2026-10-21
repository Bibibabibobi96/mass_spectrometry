"""Resolve fixed and dynamic fields from a validated standalone PA mode set."""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.contracts.write_run_manifest import file_record

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.build_single_flight_program import (
    STANDALONE_DYNAMIC_FIELD_BANK_ROLE,
    STANDALONE_DYNAMIC_FIELD_RUNTIME_REPRESENTATION,
    _successor_analyzer_config,
    resolve_standalone_dynamic_operating_coefficients,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_electrode_contract import (
    require_pa_plus_solution_model,
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
    """Project the existing two/three-zone analyzer's linear electrode plan."""

    if pulse_state not in {"off", "on"}:
        raise ValueError("pulse state must be off or on")
    ids = analyzer["electrode_ids"]
    geometry = analyzer["geometry"]
    voltages = analyzer["voltages"]
    three_zone = "intermediate2" in ids
    pre = 0.0
    if pulse_state == "off":
        return {
            int(electrode_id): pre
            for electrode_id in (
                ids["repeller"],
                ids["grid1"],
                *ids["rings"],
                *([ids["intermediate2"]] if three_zone else []),
                ids["grid2"],
            )
        }
    result = {
        int(ids["repeller"]): float(voltages["repeller_v"]),
        int(ids["grid1"]): float(voltages["grid1_v"]),
        int(ids["grid2"]): float(voltages["exit_v"]),
    }
    z_grid1 = float(geometry["accelerator_grid1_z_mm"])
    z_grid2 = float(geometry["accelerator_grid2_z_mm"])
    endpoints = [(z_grid1, float(voltages["grid1_v"]))]
    if three_zone:
        middle = float(voltages["intermediate2_v"])
        result[int(ids["intermediate2"])] = middle
        endpoints.append((float(geometry["accelerator_intermediate2_z_mm"]), middle))
    endpoints.append((z_grid2, float(voltages["exit_v"])))
    for electrode_id, raw_z in zip(
        ids["rings"], geometry["accelerator_ring_z_mm"], strict=True
    ):
        z = float(raw_z)
        interval = next(((a, b) for a, b in zip(endpoints, endpoints[1:]) if z <= b[0]),
                        (endpoints[-2], endpoints[-1]))
        (z0, v0), (z1, v1) = interval
        result[int(electrode_id)] = v0 + (v1 - v0) * (z - z0) / (z1 - z0)
    return result


def _component_voltage_states(
    frontend: Mapping[str, Any], model: Mapping[str, Any],
) -> tuple[dict[int, float], dict[int, float]]:
    """Consume provider-projected voltages under the explicit frozen pulse policy."""
    region = frontend["accelerator_local_region"]
    if region.get("pulse_voltage_policy_id") != "all_accelerator_electrodes_zero_before_pulse_v1":
        raise ValueError("canonical component pulse voltage policy is missing or unsupported")
    physical: list[dict[int, float]] = []
    for key in ("off_voltages_v", "operating_voltages_v"):
        raw = region.get(key)
        if not isinstance(raw, Mapping) or not raw:
            raise ValueError(f"canonical component {key} is missing")
        values = {}
        for electrode_id, value in raw.items():
            if (type(electrode_id) is not int and
                    (not isinstance(electrode_id, str) or re.fullmatch(r"[1-9][0-9]*", electrode_id) is None)):
                raise ValueError("canonical component electrode ID must be a positive integer")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"canonical component {key} voltage must be finite")
            parsed_id = int(electrode_id)
            if parsed_id in values:
                raise ValueError("canonical component electrode IDs are duplicated")
            values[parsed_id] = float(value)
        physical.append(values)
    off, on = physical
    rod_ids = set(frontend["electrodes"]["multipole_rod_ids"])
    grounds = set(model["grounded_physical_electrode_ids"])
    required = {int(key) for mode in model["modes"] for key in mode["physical_electrode_coefficients"]} - rod_ids
    if set(off) != set(on) or set(on) != required | grounds:
        raise ValueError("canonical component off/on physical electrode coverage differs")
    if any(value != 0.0 for value in off.values()) or any(on[key] != 0.0 for key in grounds):
        raise ValueError("canonical component zero-before-pulse or ground voltage differs")
    return ({key: value for key, value in off.items() if key not in grounds},
            {key: value for key, value in on.items() if key not in grounds})


def resolve_mode_states(
    upstream: Mapping[str, Any],
    frontend: Mapping[str, Any],
    oatof: Mapping[str, Any],
    region_field: Mapping[str, Any],
    pa_plus_model: Mapping[str, Any],
) -> dict[str, dict[int, float]]:
    """Return carrier, unit RF response and extraction-pulse delta coefficients."""

    model = require_pa_plus_solution_model(pa_plus_model)
    if "accelerator_component" in frontend:
        physical_off, physical_on = _component_voltage_states(frontend, model)
    else:
        analyzer = _successor_analyzer_config(dict(oatof), dict(frontend), dict(region_field))
        physical_off = {
            **_accelerator_plan(analyzer, "off"),
            int(frontend["electrodes"]["entrance_reference_sleeve_id"]): float(
                upstream["axial_dc"]["entrance_reference_sleeve"]["potential_V"]),
            int(frontend["electrodes"]["entrance_plate_id"]): float(
                upstream["axial_dc"]["entrance_plate_potential_V"]),
        }
        physical_on = dict(physical_off)
        physical_on.update(_accelerator_plan(analyzer, "on"))
    projection = resolve_standalone_dynamic_operating_coefficients(
        model,
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
        set(values) != set(model["mode_ids"]) or any(not math.isfinite(value) for value in values.values())
        for values in states.values()
    ):
        raise ValueError("standalone model voltage state is incomplete")
    return states


def composition_terms(
    records: Sequence[Mapping[str, Any]], coefficients: Mapping[int, float], *,
    response_normalization_v: Mapping[int, float] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Compose requested volts using explicit measured basis-reference volts.

    Omitted normalization preserves the legacy unit-response contract; callers
    must establish that contract independently rather than infer it from a PA
    filename. A supplied mapping is the physical +1 coefficient anchor voltage
    of each raw response, not an assumed SIMION fast-adjust scale.
    """

    by_id = {int(record["response_id"]): str(record["path"]) for record in records}
    mode_ids = list(by_id)
    if not by_id or len(by_id) != len(records) or set(by_id) != set(coefficients):
        raise ValueError("standalone response selection differs from coefficient mode set")
    if any(not math.isfinite(float(value)) for value in coefficients.values()):
        raise ValueError("standalone response coefficients must be finite")
    if response_normalization_v is not None:
        if set(response_normalization_v) != set(by_id) or any(
            isinstance(value, bool) or not math.isfinite(float(value)) or float(value) == 0.
            for value in response_normalization_v.values()
        ):
            raise ValueError("measured response normalization must cover every mode with finite nonzero volts")
        coefficients = {mode_id: float(value) / float(response_normalization_v[mode_id])
                        for mode_id, value in coefficients.items()}
        if any(not math.isfinite(value) for value in coefficients.values()):
            raise ValueError("normalized response coefficient is nonfinite")
    nonzero_ids = [mode_id for mode_id in mode_ids if float(coefficients[mode_id]) != 0.0]
    base_id = nonzero_ids[0] if nonzero_ids else mode_ids[0]
    base = by_id[base_id]
    terms = []
    for mode_id in mode_ids:
        coefficient = float(coefficients[mode_id]) - (1.0 if mode_id == base_id else 0.0)
        if coefficient != 0.0:
            terms.append({"path": by_id[mode_id], "coefficient": coefficient})
    if not terms:
        # The composer requires one response; adding an exact zero preserves bytes.
        zero_id = next((mode_id for mode_id in mode_ids if mode_id != base_id), base_id)
        terms.append({"path": by_id[zero_id], "coefficient": 0.0})
    return base, terms


def read_response_normalization(path: Path, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Read measured unity anchors bound with the selected PA cache inventory.

    The caller selects the immutable generation through the existing cache
    verification boundary. This checks the small measurement bytes and exact
    selected PA inventory identities without scanning those PA payloads again.
    """
    path = Path(path).resolve()
    manifest_path = path.parent / "cache_manifest.json"
    manifest = _load(manifest_path)
    inventory = manifest.get("files", [])
    by_name = {row["name"]: row for row in inventory}
    actual = file_record(path)
    measured = by_name.get(path.name)
    if measured is None or (measured["bytes"], measured["sha256"].lower()) != (actual["bytes"], actual["sha256"].lower()):
        raise ValueError("normalization measurement is not bound to the selected cache inventory")
    selected = {int(row["response_id"]): row for row in records}
    if len(selected) != len(records) or not selected:
        raise ValueError("normalization requires unique selected response IDs")
    for row in records:
        response = Path(str(row["path"])).resolve()
        bound = by_name.get(response.name)
        if response.parent != path.parent or bound is None or (bound["bytes"], bound["sha256"].lower()) != (row["bytes"], str(row["sha256"]).lower()):
            raise ValueError("normalization and selected response inventory identities differ")
    references: dict[int, float] = {}
    anchors: dict[int, dict[str, Any]] = {}
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        required = {"mode_id", "label", "x_gu", "y_gu", "z_gu", "potential_v", "electrode",
                    "expected_coefficient", "basis_reference_v", "normalized_coefficient", "policy"}
        if set(reader.fieldnames or []) != required:
            raise ValueError("measured normalization columns differ")
        rods: dict[int, set[str]] = {mode: set() for mode in selected}
        for row in reader:
            mode, reference = int(row["mode_id"]), float(row["basis_reference_v"])
            if mode not in selected or not math.isfinite(reference) or reference == 0. or references.get(mode, reference) != reference:
                raise ValueError("measured normalization mode/reference is invalid or inconsistent")
            references[mode] = reference
            if row["label"] in {f"rod_{i}" for i in range(1, 9)}:
                if row["label"] in rods[mode]:
                    raise ValueError("normalization repeats a physical rod")
                rods[mode].add(row["label"])
            if row["policy"] == "unity_anchor":
                if mode in anchors or row["electrode"] != "true" or float(row["expected_coefficient"]) != 1. or float(row["potential_v"]) != reference:
                    raise ValueError("invalid measured physical unity anchor")
                anchors[mode] = {key: row[key] for key in ("label", "x_gu", "y_gu", "z_gu", "potential_v", "electrode")}
            elif row["policy"] != "declared_sample":
                raise ValueError("unknown normalization sample policy")
        if set(anchors) != set(selected) or any(len(value) != 8 for value in rods.values()):
            raise ValueError("normalization requires one unity anchor and all eight rods per mode")
    return {"policy_id": "native_measured_physical_unity_anchor_v1", "mode_reference_v": references,
            "anchors": anchors, "measurement": actual, "cache_manifest": file_record(manifest_path),
            "scope": "Declared native metal samples; not a full-array field convergence certificate"}


def _selection_records(
    role: str, selection: Mapping[str, Any], *, mode_ids: Sequence[int] = MODE_IDS,
) -> list[dict[str, Any]]:
    """Strictly accept only the adapter's manifest-validated selection schema."""

    if (
        set(selection) != {"schema_version", "role", "prefix", "records"}
        or selection.get("schema_version") != 1
        or selection.get("role") != "rf_oatof_standalone_pa_response_selection"
        or selection.get("prefix") != ROLE_PREFIXES.get(role)
    ):
        raise ValueError(f"standalone selection identity differs for {role}")
    if not mode_ids or len(set(mode_ids)) != len(mode_ids) or any(type(value) is not int or value < 1 for value in mode_ids):
        raise ValueError("standalone selection mode IDs are invalid")
    values = selection.get("records")
    if not isinstance(values, list) or len(values) != len(mode_ids):
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
            or response_id not in mode_ids
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
    if [int(record["response_id"]) for record in records] != list(mode_ids):
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
    parser.add_argument("--role-normalization", action="append", required=True,
                        help="ROLE=cache-bound measured normalization TSV; unmeasured native bases are rejected")
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--field-bank", type=Path, required=True)
    args = parser.parse_args()

    accelerator = _load(args.accelerator_main)
    model = require_pa_plus_solution_model(accelerator["pa_plus_solution_model"])
    states = resolve_mode_states(
        _load(args.upstream),
        _load(args.frontend),
        _load(args.oatof),
        _load(args.region_field),
        model,
    )
    roles = [_role_spec(value) for value in args.role_selection]
    normalization_paths = {}
    for value in args.role_normalization:
        role, separator, raw_path = value.partition("=")
        if not separator or not raw_path or role in normalization_paths:
            raise ValueError("role normalization requires unique ROLE=MEASUREMENT.tsv entries")
        normalization_paths[role] = Path(raw_path)
    if set(normalization_paths) != {role for role, _, _ in roles}:
        raise ValueError("every native response role requires measured normalization")
    if len({role for role, _, _ in roles}) != len(roles) or len(
        {index for _, index, _ in roles}
    ) != len(roles):
        raise ValueError("standalone field roles and instance indices must be unique")
    compositions: list[dict[str, Any]] = []
    response_copies: list[dict[str, Any]] = []
    dynamic_roles: list[dict[str, Any]] = []
    normalizations = {}
    args.output_directory.mkdir(parents=True, exist_ok=True)
    for role, index, selection_path in roles:
        selection = _load(selection_path)
        records = _selection_records(role, selection, mode_ids=model["mode_ids"])
        normalization = read_response_normalization(normalization_paths[role], records)
        normalizations[role] = normalization
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
            base, terms = composition_terms(runtime_records, states[kind],
                                             response_normalization_v=normalization["mode_reference_v"])
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
        "response_normalization": normalizations,
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
