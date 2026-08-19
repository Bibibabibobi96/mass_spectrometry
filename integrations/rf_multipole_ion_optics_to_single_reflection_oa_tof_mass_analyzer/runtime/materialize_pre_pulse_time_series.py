"""Materialize governed pre-pulse time-series TRACE output artifacts."""

from __future__ import annotations

import argparse
import copy
import csv
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Sequence

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema


TRACE_PREFIX = "TRACE: pre_pulse_time_series_state"
TRACE_PATTERN = re.compile(
    r"^TRACE: pre_pulse_time_series_state "
    r"ion=(?P<ion>\d+) particle_id=(?P<particle_id>\d+) "
    r"sample_index=(?P<sample_index>\d+) "
    r"instrument_time_us=(?P<instrument_time>[-+0-9.eE]+) "
    r"actual_instrument_time_us=(?P<actual_time>[-+0-9.eE]+) "
    r"x_mm=(?P<x>[-+0-9.eE]+) y_mm=(?P<y>[-+0-9.eE]+) "
    r"z_mm=(?P<z>[-+0-9.eE]+) "
    r"vx_mm_per_us=(?P<vx>[-+0-9.eE]+) "
    r"vy_mm_per_us=(?P<vy>[-+0-9.eE]+) "
    r"vz_mm_per_us=(?P<vz>[-+0-9.eE]+) "
    r"kinetic_energy_eV=(?P<energy>[-+0-9.eE]+) "
    r"survival_status=(?P<status>\S+)$"
)
PROHIBITED_DOWNSTREAM_PATTERN = re.compile(
    r"^TRACE: (?:detector_crossing|diagnostic_return_plane)"
)
CSV_COLUMNS = (
    "particle_id",
    "event",
    "sample_index",
    "instrument_time_us",
    "actual_instrument_time_us",
    "x_mm",
    "y_mm",
    "z_mm",
    "vx_mm_per_us",
    "vy_mm_per_us",
    "vz_mm_per_us",
    "kinetic_energy_eV",
    "survival_status",
)
SHA_PATTERN = re.compile(r"^[A-Fa-f0-9]{64}$")


@dataclass(frozen=True, slots=True)
class StateRow:
    particle_id: int
    sample_index: int
    instrument_time_us: float
    actual_instrument_time_us: float
    x_mm: float
    y_mm: float
    z_mm: float
    vx_mm_per_us: float
    vy_mm_per_us: float
    vz_mm_per_us: float
    kinetic_energy_eV: float


@dataclass(frozen=True)
class MaterializationResult:
    state_row_count: int
    states_record: dict[str, object]
    receipt_record: dict[str, object]


def _load_object(path: Path, *, role: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{role} is not readable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{role} must be a JSON object")
    return value


def _id_list_sha256(particle_ids: Sequence[int]) -> str:
    payload = json.dumps(list(particle_ids), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _census_id_sha256(particle_ids: Sequence[int]) -> str:
    payload = json.dumps(
        {"ordered_particle_ids": list(particle_ids)}, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _dotnet_roundtrip(value: float) -> str:
    """Match PowerShell Export-Csv's invariant round-trip double formatting."""
    if not math.isfinite(value):
        raise ContractError("pre-pulse TRACE contains a non-finite number")
    text = repr(value)
    if text.endswith(".0"):
        text = text[:-2]
    return text.replace("e", "E")


def _write_json_crlf(path: Path, value: dict[str, Any]) -> None:
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").replace(
        "\n", "\r\n"
    )
    _atomic_write_bytes(path, payload.encode("utf-8"))


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _resolve_run_path(value: object, *, role: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"run configuration {role} path is invalid")
    path = Path(value).resolve()
    if not path.is_file():
        raise ContractError(f"run configuration {role} is missing: {path}")
    return path


def _frozen_particle_ids(path: Path) -> list[int]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or "source_particle_id" not in reader.fieldnames:
                raise ContractError(
                    "particle row map lacks source_particle_id"
                )
            particle_ids = [int(row["source_particle_id"]) for row in reader]
    except (OSError, UnicodeError, csv.Error, TypeError, ValueError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError("particle row map is invalid") from exc
    return particle_ids


def _cache_keys(
    contract: dict[str, Any], run_config: dict[str, Any]
) -> dict[str, str | None]:
    dispositions = run_config.get("parameters", {}).get("pa_cache_dispositions")
    if not isinstance(dispositions, dict):
        raise ContractError("pre-pulse PA cache dispositions are missing")
    expected: dict[str, str | None] = {}
    active_roles = {
        "frontend": "simion_single_flight_frontend_pa_cache",
        "accelerator_overlay": "simion_accelerator_overlay_pa_cache",
    }
    for role, expected_role in active_roles.items():
        disposition = dispositions.get(role)
        if not isinstance(disposition, dict):
            raise ContractError("pre-pulse active PA cache disposition is missing")
        key = disposition.get("key")
        if not isinstance(key, str) or re.fullmatch(r"[a-f0-9]{64}", key) is None:
            raise ContractError("pre-pulse active PA cache key is invalid")
        if disposition.get("role") != expected_role or disposition.get(
            "disposition"
        ) not in {
            "cache_hit",
            "built_and_published",
        }:
            raise ContractError("pre-pulse active PA cache disposition differs")
        expected[role] = key
    for role in ("flight_tube", "reflectron"):
        disposition = dispositions.get(role)
        if (
            not isinstance(disposition, dict)
            or disposition.get("key") is not None
            or disposition.get("disposition") != "formal"
        ):
            raise ContractError("pre-pulse downstream PA cache must be formal")
        expected[role] = None

    if contract.get("schema_version") == 1:
        declared = contract.get("pa_cache_keys")
        if declared != expected:
            raise ContractError("pre-pulse schema-v1 PA cache keys differ")
        return copy.deepcopy(declared)
    roles = contract.get("pa_cache_roles")
    if (
        not isinstance(roles, dict)
        or roles.get("identity_source")
        != "runner_materialized_verified_pa_cache_receipt"
        or roles.get("required") != ["frontend", "accelerator_overlay"]
        or roles.get("prohibited") != ["flight_tube", "reflectron"]
    ):
        raise ContractError("pre-pulse schema-v2 PA cache role policy differs")
    return expected


def _parse_logs(
    stdout_paths: Sequence[Path],
    *,
    frozen_particle_ids: Sequence[int],
    sample_times_us: Sequence[float],
) -> tuple[dict[int, list[StateRow]], list[list[int]], int]:
    if not stdout_paths:
        raise ContractError("at least one SIMION stdout log is required")
    frozen_set = set(frozen_particle_ids)
    rows_by_particle = {particle_id: [] for particle_id in frozen_set}
    alive_by_sample: list[list[int]] = [[] for _ in sample_times_us]
    seen: set[tuple[int, int]] = set()
    row_count = 0
    for stdout_path in stdout_paths:
        if not stdout_path.is_file():
            raise ContractError(f"SIMION stdout log is missing: {stdout_path}")
        try:
            with stdout_path.open("r", encoding="utf-8", errors="strict") as handle:
                for raw_line in handle:
                    line = raw_line.rstrip("\r\n")
                    if PROHIBITED_DOWNSTREAM_PATTERN.match(line):
                        raise ContractError(
                            "pre-pulse screening emitted a prohibited downstream event"
                        )
                    if not line.startswith(TRACE_PREFIX):
                        continue
                    match = TRACE_PATTERN.fullmatch(line)
                    if match is None:
                        raise ContractError("pre-pulse state TRACE line is malformed")
                    try:
                        particle_id = int(match["particle_id"])
                        sample_index = int(match["sample_index"])
                        numeric = {
                            name: float(match[name])
                            for name in (
                                "instrument_time",
                                "actual_time",
                                "x",
                                "y",
                                "z",
                                "vx",
                                "vy",
                                "vz",
                                "energy",
                            )
                        }
                    except ValueError as exc:
                        raise ContractError(
                            "pre-pulse state TRACE numeric field is invalid"
                        ) from exc
                    if particle_id not in frozen_set:
                        raise ContractError(
                            "pre-pulse TRACE particle identity differs"
                        )
                    if sample_index < 1 or sample_index > len(sample_times_us):
                        raise ContractError(
                            "pre-pulse TRACE sample index is outside the frozen grid"
                        )
                    key = (particle_id, sample_index)
                    if key in seen:
                        raise ContractError(
                            "pre-pulse TRACE particle/sample is duplicated"
                        )
                    if not all(math.isfinite(value) for value in numeric.values()):
                        raise ContractError(
                            "pre-pulse TRACE contains a non-finite number"
                        )
                    expected_time = float(sample_times_us[sample_index - 1])
                    tolerance = 1e-12 * max(1.0, abs(expected_time))
                    if (
                        abs(numeric["instrument_time"] - expected_time) > tolerance
                        or abs(numeric["actual_time"] - expected_time) > tolerance
                        or match["status"] != "alive"
                    ):
                        raise ContractError(
                            "pre-pulse TRACE identity/time landing differs"
                        )
                    row = StateRow(
                        particle_id=particle_id,
                        sample_index=sample_index,
                        instrument_time_us=numeric["instrument_time"],
                        actual_instrument_time_us=numeric["actual_time"],
                        x_mm=numeric["x"],
                        y_mm=numeric["y"],
                        z_mm=numeric["z"],
                        vx_mm_per_us=numeric["vx"],
                        vy_mm_per_us=numeric["vy"],
                        vz_mm_per_us=numeric["vz"],
                        kinetic_energy_eV=numeric["energy"],
                    )
                    seen.add(key)
                    rows_by_particle[particle_id].append(row)
                    alive_by_sample[sample_index - 1].append(particle_id)
                    row_count += 1
        except (OSError, UnicodeError) as exc:
            raise ContractError(f"SIMION stdout log is unreadable: {stdout_path}") from exc

    for particle_id, particle_rows in rows_by_particle.items():
        particle_rows.sort(key=lambda row: row.sample_index)
        if [row.sample_index for row in particle_rows] != list(
            range(1, len(particle_rows) + 1)
        ):
            raise ContractError(
                "pre-pulse particle state is not one continuous alive prefix"
            )
    for alive_ids in alive_by_sample:
        alive_ids.sort()
    return rows_by_particle, alive_by_sample, row_count


def _write_states_csv(path: Path, rows_by_particle: dict[int, list[StateRow]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(
                handle, quoting=csv.QUOTE_ALL, lineterminator="\r\n"
            )
            writer.writerow(CSV_COLUMNS)
            for particle_id in sorted(rows_by_particle):
                for row in rows_by_particle[particle_id]:
                    writer.writerow(
                        (
                            row.particle_id,
                            "pre_pulse_time_series_state",
                            row.sample_index,
                            _dotnet_roundtrip(row.instrument_time_us),
                            _dotnet_roundtrip(row.actual_instrument_time_us),
                            _dotnet_roundtrip(row.x_mm),
                            _dotnet_roundtrip(row.y_mm),
                            _dotnet_roundtrip(row.z_mm),
                            _dotnet_roundtrip(row.vx_mm_per_us),
                            _dotnet_roundtrip(row.vy_mm_per_us),
                            _dotnet_roundtrip(row.vz_mm_per_us),
                            _dotnet_roundtrip(row.kinetic_energy_eV),
                            "alive",
                        )
                    )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def materialize(
    *,
    stdout_paths: Sequence[Path],
    run_config_path: Path,
    expected_contract_sha256: str,
    states_path: Path,
    receipt_path: Path,
    summary_path: Path,
) -> MaterializationResult:
    """Validate TRACE logs and write the frozen screening artifacts."""
    run_config_path = run_config_path.resolve()
    run_config = _load_object(run_config_path, role="run configuration")
    inputs = run_config.get("inputs")
    parameters = run_config.get("parameters")
    if not isinstance(inputs, dict) or not isinstance(parameters, dict):
        raise ContractError("run configuration inputs/parameters are invalid")
    if (
        parameters.get("execution_mode") != "real_pa_rf_pre_pulse_time_series"
        or parameters.get("resolution_claim_allowed") is not False
    ):
        raise ContractError("run configuration is not pre-pulse screening")

    run_dir = run_config_path.parent.resolve()
    expected_outputs = {
        "states": run_dir / "results" / "pre_pulse_time_series_states.csv",
        "receipt": run_dir
        / "results"
        / "pre_pulse_time_series_screening_receipt.json",
        "summary": run_dir / "summary.json",
    }
    supplied_outputs = {
        "states": states_path.resolve(),
        "receipt": receipt_path.resolve(),
        "summary": summary_path.resolve(),
    }
    if supplied_outputs != expected_outputs:
        raise ContractError("pre-pulse materializer output paths differ")

    contract_path = _resolve_run_path(
        inputs.get("pre_pulse_time_series_contract"),
        role="pre-pulse time-series contract",
    )
    if (
        not isinstance(expected_contract_sha256, str)
        or SHA_PATTERN.fullmatch(expected_contract_sha256) is None
        or file_sha256(contract_path) != expected_contract_sha256.upper()
    ):
        raise ContractError("pre-pulse time-series contract SHA-256 differs")
    contract = _load_object(contract_path, role="pre-pulse time-series contract")
    validate_schema(
        contract, "rf_oatof_pre_pulse_time_series_screening_contract.schema.json"
    )

    raw_sample_times = contract.get("sample_times_us")
    if not isinstance(raw_sample_times, list) or not raw_sample_times:
        raise ContractError("pre-pulse sample-time grid is empty")
    try:
        sample_times = [float(value) for value in raw_sample_times]
    except (TypeError, ValueError) as exc:
        raise ContractError("pre-pulse sample-time grid is invalid") from exc
    if (
        not all(math.isfinite(value) and value >= 0 for value in sample_times)
        or contract.get("rf_time_grid", {}).get("sample_count")
        != len(sample_times)
    ):
        raise ContractError("pre-pulse sample-time grid identity differs")

    particle_row_map = _resolve_run_path(
        inputs.get("particle_row_map"), role="particle row map"
    )
    frozen_ids = _frozen_particle_ids(particle_row_map)
    particle_count = parameters.get("particle_count")
    launched_count = parameters.get("launched_particle_count")
    identities = contract.get("identities")
    if (
        not isinstance(particle_count, int)
        or isinstance(particle_count, bool)
        or particle_count <= 0
        or launched_count != particle_count
        or len(frozen_ids) != particle_count
        or len(set(frozen_ids)) != particle_count
        or not isinstance(identities, dict)
        or identities.get("ordered_particle_id_sha256")
        != _id_list_sha256(frozen_ids)
    ):
        raise ContractError("pre-pulse frozen particle identity differs")
    cache_keys = _cache_keys(contract, run_config)

    rows_by_particle, alive_by_sample, row_count = _parse_logs(
        [path.resolve() for path in stdout_paths],
        frozen_particle_ids=frozen_ids,
        sample_times_us=sample_times,
    )
    frozen_set = set(frozen_ids)
    sample_census: list[dict[str, object]] = []
    for zero_index, alive_ids in enumerate(alive_by_sample):
        missing_ids = sorted(frozen_set.difference(alive_ids))
        sample_census.append(
            {
                "sample_index": zero_index + 1,
                "instrument_time_us": raw_sample_times[zero_index],
                "alive_count": len(alive_ids),
                "alive_particle_ids_sha256": _census_id_sha256(alive_ids),
                "missing_count": len(missing_ids),
                "missing_particle_ids": missing_ids,
                "missing_particle_ids_sha256": _census_id_sha256(missing_ids),
            }
        )

    _write_states_csv(states_path, rows_by_particle)
    states_record: dict[str, object] = {
        "path": "results/pre_pulse_time_series_states.csv",
        "sha256": file_sha256(states_path),
        "bytes": states_path.stat().st_size,
        "row_count": row_count,
    }
    receipt = {
        "schema_version": 1,
        "role": "rf_oatof_pre_pulse_time_series_screening_receipt",
        "status": "success",
        "qualification": "FUNCTIONAL_ONLY",
        "execution_mode": "real_pa_rf_pre_pulse_time_series",
        "resolution_claim_allowed": False,
        "pulse_disabled": True,
        "contract_sha256": expected_contract_sha256.upper(),
        "identities": copy.deepcopy(identities),
        "pa_cache_keys": cache_keys,
        "rf_time_grid": copy.deepcopy(contract["rf_time_grid"]),
        "sample_times_us": copy.deepcopy(raw_sample_times),
        "particle_count": particle_count,
        "state_row_count": row_count,
        "sample_census": sample_census,
        "outputs": {"states": states_record},
        "prohibited_outputs": copy.deepcopy(contract["prohibited_outputs"]),
    }
    _write_json_crlf(receipt_path, receipt)
    receipt_record: dict[str, object] = {
        "path": "results/pre_pulse_time_series_screening_receipt.json",
        "sha256": file_sha256(receipt_path),
        "bytes": receipt_path.stat().st_size,
    }
    summary = {
        "schema_version": 1,
        "role": "rf_oatof_simion_single_flight_summary",
        "status": "success",
        "execution_mode": "real_pa_rf_pre_pulse_time_series",
        "qualification": "FUNCTIONAL_ONLY",
        "resolution_claim_allowed": False,
        "pulse_disabled": True,
        "sample_times_us": copy.deepcopy(raw_sample_times),
        "census": {
            "source_release": particle_count,
            "particle_count": particle_count,
            "sample_count": len(sample_times),
            "observed_state_rows": row_count,
            "sample_census": sample_census,
        },
        "pa_cache_dispositions": copy.deepcopy(
            parameters["pa_cache_dispositions"]
        ),
        "outputs": {
            "states": states_record,
            "receipt": receipt_record,
        },
        "prohibited_outputs": copy.deepcopy(contract["prohibited_outputs"]),
    }
    _write_json_crlf(summary_path, summary)
    return MaterializationResult(
        state_row_count=row_count,
        states_record=states_record,
        receipt_record=receipt_record,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize governed pre-pulse time-series TRACE output."
    )
    parser.add_argument("--run-config", required=True, type=Path)
    parser.add_argument(
        "--pre-pulse-time-series-contract-sha256", required=True
    )
    parser.add_argument(
        "--stdout-log", action="append", required=True, type=Path
    )
    parser.add_argument("--states-output", required=True, type=Path)
    parser.add_argument("--receipt-output", required=True, type=Path)
    parser.add_argument("--summary-output", required=True, type=Path)
    arguments = parser.parse_args()
    materialize(
        stdout_paths=arguments.stdout_log,
        run_config_path=arguments.run_config,
        expected_contract_sha256=(
            arguments.pre_pulse_time_series_contract_sha256
        ),
        states_path=arguments.states_output,
        receipt_path=arguments.receipt_output,
        summary_path=arguments.summary_output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
