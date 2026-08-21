"""Aggregate manifest-bound resolution evidence across gap and field cases.

This is an analysis boundary, not an execution runner.  The input inventory is
explicit: every row names one immutable evidence JSON, its SHA-256, the metric
JSON pointer, and the two scientific comparison axes (field condition and
source population).  No filename, run directory, or missing metric is inferred.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError


REQUEST_ROLE = "rf_oatof_resolution_matrix_request"
RESULT_ROLE = "rf_oatof_resolution_matrix"
FIELD_CONDITIONS = (
    "real_field",
    "accelerator_ideal_field",
    "reflectron_ideal_field",
    "full_ideal_field",
)
SOURCE_POPULATIONS = ("ideal_source_region", "full_domain")
PULSE_EFFECTIVE_BASIS = "detector_time_minus_pulse_effective_time"
DIRECT_FWHM_METHOD = "canonical_direct_kde_fwhm"


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ContractError(f"{label} must be a SHA-256 string")
    if any(c not in "0123456789abcdefABCDEF" for c in value):
        raise ContractError(f"{label} must be a SHA-256 string")
    return value.upper()


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value.strip()


def _finite(value: object, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{label} must be finite")
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise ContractError(f"{label} must be finite" + (" and positive" if positive else ""))
    return number


def _pointer(value: object, pointer: str) -> object:
    current = value
    if not pointer:
        return current
    if not pointer.startswith("/"):
        raise ContractError("metric_json_pointer must be empty or start with /")
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            raise ContractError(f"metric_json_pointer does not resolve: {pointer}")
    return current


def _exact_keys(value: Mapping[str, Any], required: set[str], label: str) -> None:
    missing = required - set(value)
    unknown = set(value) - required
    if missing or unknown:
        raise ContractError(f"{label} keys differ: missing={sorted(missing)}, unknown={sorted(unknown)}")


_ROW_KEYS = {
    "record_id", "run_id", "gap_mm", "field_condition", "source_population",
    "evidence_path", "evidence_sha256", "metric_json_pointer", "nominal_mass_da",
    "charge_state", "resolution_time_basis", "metric_role", "fwhm_method",
    "comparison_contract_id", "source_identity", "geometry_identity", "grid_identity",
}


def _identity(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    _exact_keys(value, {"id", "sha256"}, label)
    return {"id": _text(value["id"], f"{label}.id"), "sha256": _sha(value["sha256"], f"{label}.sha256")}


def _row(value: object, index: int) -> dict[str, Any]:
    label = f"rows[{index}]"
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    _exact_keys(value, _ROW_KEYS, label)
    result = dict(value)
    for key in ("record_id", "run_id", "evidence_path", "resolution_time_basis", "metric_role", "fwhm_method", "comparison_contract_id"):
        result[key] = _text(value[key], f"{label}.{key}")
    result["gap_mm"] = _finite(value["gap_mm"], f"{label}.gap_mm")
    if result["gap_mm"] < 0:
        raise ContractError(f"{label}.gap_mm must not be negative")
    if value["field_condition"] not in FIELD_CONDITIONS:
        raise ContractError(f"{label}.field_condition is unknown")
    if value["source_population"] not in SOURCE_POPULATIONS:
        raise ContractError(f"{label}.source_population is unknown")
    result["evidence_sha256"] = _sha(value["evidence_sha256"], f"{label}.evidence_sha256")
    result["metric_json_pointer"] = value["metric_json_pointer"]
    if not isinstance(value["metric_json_pointer"], str):
        raise ContractError(f"{label}.metric_json_pointer must be a string")
    result["nominal_mass_da"] = _finite(value["nominal_mass_da"], f"{label}.nominal_mass_da", positive=True)
    if isinstance(value["charge_state"], bool) or not isinstance(value["charge_state"], int) or value["charge_state"] == 0:
        raise ContractError(f"{label}.charge_state must be a nonzero integer")
    result["source_identity"] = _identity(value["source_identity"], f"{label}.source_identity")
    result["geometry_identity"] = _identity(value["geometry_identity"], f"{label}.geometry_identity")
    result["grid_identity"] = _identity(value["grid_identity"], f"{label}.grid_identity")
    return result


def validate_inventory(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError("resolution matrix inventory must be an object")
    _exact_keys(value, {"schema_version", "role", "rows"}, "resolution matrix inventory")
    if value["schema_version"] != 1 or value["role"] != REQUEST_ROLE:
        raise ContractError("resolution matrix inventory identity differs")
    if not isinstance(value["rows"], list) or not value["rows"]:
        raise ContractError("resolution matrix inventory requires rows")
    rows = [_row(row, index) for index, row in enumerate(value["rows"])]
    ids = [row["record_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ContractError("resolution matrix record_id values must be unique")
    return {"schema_version": 1, "role": REQUEST_ROLE, "rows": rows}


def _metric(record: Mapping[str, Any], inventory_dir: Path) -> dict[str, Any]:
    path = Path(record["evidence_path"])
    if not path.is_absolute():
        path = (inventory_dir / path).resolve()
    if not path.is_file():
        raise ContractError(f"evidence file is missing: {path}")
    observed = file_sha256(path)
    if observed != record["evidence_sha256"]:
        raise ContractError(f"evidence SHA differs for record {record['record_id']}")
    try:
        evidence = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"evidence JSON cannot be read: {path}") from error
    metric = _pointer(evidence, record["metric_json_pointer"])
    if not isinstance(metric, Mapping):
        raise ContractError(f"metric object is not a mapping: {record['record_id']}")
    required = ("particles", "mean_tof_us", "direct_fwhm_tof_ns", "mass_resolution", "significant_kde_modes")
    if any(key not in metric for key in required):
        raise ContractError(f"metric is incomplete: {record['record_id']}")
    particles = metric["particles"]
    if isinstance(particles, bool) or not isinstance(particles, int) or particles < 1:
        raise ContractError(f"metric particles is invalid: {record['record_id']}")
    modes = metric["significant_kde_modes"]
    if isinstance(modes, bool) or not isinstance(modes, int) or modes < 1:
        raise ContractError(f"metric significant_kde_modes is invalid: {record['record_id']}")
    return {
        "record_id": record["record_id"], "run_id": record["run_id"], "gap_mm": record["gap_mm"],
        "field_condition": record["field_condition"], "source_population": record["source_population"],
        "nominal_mass_da": record["nominal_mass_da"], "charge_state": record["charge_state"],
        "comparison_contract_id": record["comparison_contract_id"],
        "resolution_time_basis": record["resolution_time_basis"], "metric_role": record["metric_role"],
        "fwhm_method": record["fwhm_method"], "particles": particles,
        "mean_tof_us": _finite(metric["mean_tof_us"], "mean_tof_us", positive=True),
        "direct_fwhm_tof_ns": _finite(metric["direct_fwhm_tof_ns"], "direct_fwhm_tof_ns", positive=True),
        "mass_resolution": _finite(metric["mass_resolution"], "mass_resolution", positive=True),
        "significant_kde_modes": modes, "evidence_path": str(path), "evidence_sha256": observed,
        "source_identity": record["source_identity"], "geometry_identity": record["geometry_identity"],
        "grid_identity": record["grid_identity"],
    }


def aggregate_matrix(inventory: object, *, inventory_dir: Path) -> dict[str, Any]:
    normalized = validate_inventory(inventory)
    rows = [_metric(row, inventory_dir.resolve()) for row in normalized["rows"]]
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = f"{row['gap_mm']:.12g}"
        groups.setdefault(key, []).append(row)
    comparison_warnings: list[str] = []
    contracts = {row["comparison_contract_id"] for row in rows}
    if len(contracts) > 1:
        comparison_warnings.append("comparison_contract_id_differs")
    return {
        "schema_version": 1, "role": RESULT_ROLE, "status": "success",
        "comparison_axes": {"gap": "gap_mm", "field": list(FIELD_CONDITIONS), "source_population": list(SOURCE_POPULATIONS)},
        "row_count": len(rows), "gap_values_mm": sorted({row["gap_mm"] for row in rows}),
        "comparison_warnings": comparison_warnings, "rows": rows,
        "groups_by_gap_mm": groups,
    }


CSV_FIELDS = ("record_id", "run_id", "gap_mm", "field_condition", "source_population", "particles", "mean_tof_us", "direct_fwhm_tof_ns", "mass_resolution", "significant_kde_modes", "nominal_mass_da", "charge_state", "comparison_contract_id", "resolution_time_basis", "metric_role", "fwhm_method", "evidence_path", "evidence_sha256")


def _write_atomic(path: Path, content: str) -> None:
    pending = path.with_name(f".{path.name}.pending")
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(content, encoding="utf-8", newline="\n")
    os.replace(pending, path)


def write_matrix_outputs(inventory_path: Path, output_json: Path, output_csv: Path) -> dict[str, Any]:
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"resolution matrix inventory cannot be read: {inventory_path}") from error
    result = aggregate_matrix(inventory, inventory_dir=inventory_path.resolve().parent)
    _write_atomic(output_json, json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    from io import StringIO
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in result["rows"]:
        writer.writerow({key: row[key] for key in CSV_FIELDS})
    _write_atomic(output_csv, buffer.getvalue())
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-csv", required=True, type=Path)
    args = parser.parse_args(argv)
    result = write_matrix_outputs(args.inventory, args.output_json, args.output_csv)
    print(f"RF_OATOF_RESOLUTION_MATRIX=PASS ROWS={result['row_count']} GAPS={len(result['gap_values_mm'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
