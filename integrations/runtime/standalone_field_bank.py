"""Resolve fixed and dynamic fields from a validated standalone PA mode set."""
from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.contracts.write_run_manifest import file_record

from integrations.runtime.build_single_flight_program import resolve_standalone_dynamic_operating_coefficients
from integrations.runtime.single_flight_electrode_contract import (
    require_pa_plus_solution_model,
)


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
    pa_plus_model: Mapping[str, Any],
) -> dict[str, dict[int, float]]:
    """Return carrier, unit RF response and extraction-pulse delta coefficients."""

    model = require_pa_plus_solution_model(pa_plus_model)
    physical_off, physical_on = _component_voltage_states(frontend, model)
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
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict):
        raise ValueError(f"JSON object required: {manifest_path}")
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
        if stream.readline().rstrip('\r\n') != 'frontend_mode_normalization_v4':
            raise ValueError("explicit physical normalization declaration required")
        counts = stream.readline().rstrip('\r\n').split('\t')
        if len(counts) != 3 or counts[0] != 'physical_count' or not all(value.isdigit() for value in counts[1:]):
            raise ValueError("normalization physical counts are invalid")
        declared = {}
        for line in stream:
            if line.rstrip('\r\n') == 'measurements':
                break
            parts = line.rstrip('\r\n').split('\t')
            if len(parts) != 4 or parts[0] != 'physical' or parts[1] in declared:
                raise ValueError("normalization physical piece declaration is invalid or repeated")
            if not parts[2].isdigit() or int(parts[2]) < 1:
                raise ValueError("normalization physical electrode ID is invalid")
            declared[parts[1]] = (int(parts[2]),parts[3])
        if (not declared or len(declared) != int(counts[1]) or
                sum(kind == 'rod' for _,kind in declared.values()) != int(counts[2])):
            raise ValueError("normalization declared physical piece coverage differs")
        reader = csv.DictReader(stream, delimiter="\t")
        required = {"mode_id", "label", "x_gu", "y_gu", "z_gu", "potential_v", "electrode",
                    "expected_coefficient", "basis_reference_v", "normalized_coefficient", "policy"}
        if set(reader.fieldnames or []) != required:
            raise ValueError("measured normalization columns differ")
        observed: dict[int, set[str]] = {mode: set() for mode in selected}
        for row in reader:
            mode, reference = int(row["mode_id"]), float(row["basis_reference_v"])
            if mode not in selected or not math.isfinite(reference) or reference == 0. or references.get(mode, reference) != reference:
                raise ValueError("measured normalization mode/reference is invalid or inconsistent")
            references[mode] = reference
            if any(not math.isfinite(float(row[key])) for key in
                   ('x_gu','y_gu','z_gu','potential_v','normalized_coefficient')):
                raise ValueError("nonfinite measured physical normalization")
            if row['expected_coefficient'] != 'any' and not math.isfinite(float(row['expected_coefficient'])):
                raise ValueError("nonfinite expected physical coefficient")
            if row["label"] in declared:
                if row['label'] in observed[mode] or row['electrode'] != 'true':
                    raise ValueError("normalization repeats or omits metal for a physical piece")
                observed[mode].add(row['label'])
            elif row['electrode'] == 'true':
                raise ValueError("normalization contains undeclared physical metal")
            if row["policy"] == "unity_anchor":
                if mode in anchors or row["electrode"] != "true" or float(row["expected_coefficient"]) != 1. or float(row["potential_v"]) != reference:
                    raise ValueError("invalid measured physical unity anchor")
                anchors[mode] = {key: row[key] for key in ("label", "x_gu", "y_gu", "z_gu", "potential_v", "electrode")}
            elif row["policy"] != "declared_sample":
                raise ValueError("unknown normalization sample policy")
        if set(anchors) != set(selected) or any(value != set(declared) for value in observed.values()):
            raise ValueError("normalization requires one unity anchor and every declared physical piece per mode")
    return {"policy_id": "native_measured_physical_unity_anchor_v1", "mode_reference_v": references,
            "anchors": anchors, "measurement": actual, "cache_manifest": file_record(manifest_path),
            "scope": "Declared native metal samples; not a full-array field convergence certificate"}
