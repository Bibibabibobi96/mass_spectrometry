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
from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.verify_run_manifest import record_path, verify_record
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.run_publication import (
    portable_path,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import (
    GLOBAL_COLUMNS,
    materialize_pre_pulse_restart,
)


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
TERMINAL_PREFIX = "TRACE: pre_pulse_screening_terminal"
TERMINAL_PATTERN = re.compile(
    r"^TRACE: pre_pulse_screening_terminal "
    r"ion=(?P<ion>\d+) particle_id=(?P<particle_id>\d+) "
    r"instrument_time_us=(?P<instrument_time>[-+0-9.eE]+) "
    r"x_mm=(?P<x>[-+0-9.eE]+) y_mm=(?P<y>[-+0-9.eE]+) "
    r"z_mm=(?P<z>[-+0-9.eE]+) "
    r"vx_mm_per_us=(?P<vx>[-+0-9.eE]+) "
    r"vy_mm_per_us=(?P<vy>[-+0-9.eE]+) "
    r"vz_mm_per_us=(?P<vz>[-+0-9.eE]+) "
    r"terminal_reason=(?P<reason>window_complete|splat)$"
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
INTEGRATION_SCHEMA_DIR = Path(__file__).resolve().parents[1] / "config" / "schemas"
TIME_SERIES_RESTART_RECEIPT_ROLE = (
    "rf_oatof_manifest_bound_time_series_restart_materialization_receipt"
)


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


def _manifest_local_record(
    manifest: dict[str, Any],
    *,
    collection: str,
    name: str,
    run_dir: Path,
) -> Path:
    """Resolve exactly one verified manifest record inside its producer run."""

    records = manifest.get(collection)
    if collection == "inputs":
        record = records.get(name) if isinstance(records, dict) else None
    else:
        matches = [
            item for item in records or []
            if isinstance(item, dict)
            and Path(str(item.get("path", ""))).name == name
        ]
        record = matches[0] if len(matches) == 1 else None
    if not isinstance(record, dict):
        raise ContractError(f"time-series producer {collection}.{name} is missing")
    try:
        verify_record(
            f"time-series producer {collection}.{name}", record,
            base_dir=run_dir,
        )
        path = record_path(record, base_dir=run_dir).resolve()
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError(
            f"time-series producer {collection}.{name} identity differs"
        ) from exc
    if not path.is_relative_to(run_dir.resolve()):
        raise ContractError(f"time-series producer {collection}.{name} is nonlocal")
    return path


def _restart_file_binding(path: Path, workspace_root: Path) -> dict[str, object]:
    return {
        "path": portable_path(path, workspace_root),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _restart_id_sha256(particle_ids: Sequence[int]) -> str:
    return hashlib.sha256(
        json.dumps(list(particle_ids), separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()


def _load_global_state_by_id(path: Path) -> dict[int, dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != GLOBAL_COLUMNS:
                raise ContractError("time-series initial global state columns differ")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ContractError("time-series initial global state is unreadable") from exc
    result: dict[int, dict[str, str]] = {}
    for row in rows:
        try:
            particle_id = int(row["particle_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("time-series initial global state ID is invalid") from exc
        if particle_id < 1 or particle_id in result:
            raise ContractError("time-series initial global state IDs differ")
        result[particle_id] = row
    if not result:
        raise ContractError("time-series initial global state is empty")
    return result


def materialize_manifest_bound_restart(
    *,
    child_manifest_path: Path,
    workspace_root: Path,
    state_output_path: Path,
    receipt_output_path: Path,
    sample_index: int = 1,
) -> dict[str, Any]:
    """Convert one pulse-disabled screening sample into a canonical restart.

    This is a state-format conversion only.  The source is detector blind and
    conditional on reaching the frozen pulse epoch; its original full mother
    population and terminal loss census remain bound in the receipt.
    """

    if isinstance(sample_index, bool) or sample_index < 1:
        raise ContractError("time-series restart sample index is invalid")
    workspace_root = workspace_root.resolve()
    child_manifest_path = child_manifest_path.resolve()
    portable_path(child_manifest_path, workspace_root)
    run_dir = child_manifest_path.parent
    manifest = _load_object(child_manifest_path, role="time-series child manifest")
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("project")
        != "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
        or manifest.get("mode") != "rf_to_oatof_simion_single_flight"
        or manifest.get("status") != "success"
    ):
        raise ContractError("time-series child manifest identity or status differs")
    try:
        verify_record(
            "time-series child run_config", manifest["run_config"], base_dir=run_dir
        )
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError("time-series child run_config identity differs") from exc

    run_config_path = record_path(manifest["run_config"], base_dir=run_dir)
    run_config = _load_object(run_config_path, role="time-series child run_config")
    if run_config.get("parameters", {}).get("execution_mode") != (
        "real_pa_rf_pre_pulse_time_series"
    ):
        raise ContractError("time-series child mode differs")
    states_path = _manifest_local_record(
        manifest, collection="outputs", name="pre_pulse_time_series_states.csv",
        run_dir=run_dir,
    )
    screening_receipt_path = _manifest_local_record(
        manifest, collection="outputs",
        name="pre_pulse_time_series_screening_receipt.json", run_dir=run_dir,
    )
    summary_path = _manifest_local_record(
        manifest, collection="outputs", name="summary.json", run_dir=run_dir,
    )
    initial_state_path = _manifest_local_record(
        manifest, collection="inputs", name="initial_global_state", run_dir=run_dir,
    )
    schedule_path = _manifest_local_record(
        manifest, collection="inputs", name="pulse_schedule", run_dir=run_dir,
    )
    population_path = _manifest_local_record(
        manifest, collection="inputs", name="resolved_population_contract",
        run_dir=run_dir,
    )
    geometry_path = _manifest_local_record(
        manifest, collection="inputs", name="oatof_resolved_geometry", run_dir=run_dir,
    )
    screening = _load_object(screening_receipt_path, role="time-series receipt")
    summary = _load_object(summary_path, role="time-series summary")
    schedule = _load_object(schedule_path, role="time-series pulse schedule")
    population = _load_object(population_path, role="time-series population")
    if (
        screening.get("role") != "rf_oatof_pre_pulse_time_series_screening_receipt"
        or screening.get("status") != "success"
        or screening.get("pulse_disabled") is not True
        or summary.get("status") != "success"
    ):
        raise ContractError("time-series receipt or summary identity differs")
    sample_times = screening.get("sample_times_us")
    if not isinstance(sample_times, list) or sample_index > len(sample_times):
        raise ContractError("time-series restart sample is absent")
    pulse_time_us = float(sample_times[sample_index - 1])
    scheduled_time_us = float(schedule.get("pulse_effective_time_us", math.nan))
    if (
        not math.isfinite(pulse_time_us)
        or not math.isfinite(scheduled_time_us)
        or abs(pulse_time_us - scheduled_time_us) > 1e-9
    ):
        raise ContractError("time-series restart clock differs from pulse schedule")
    try:
        with states_path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != CSV_COLUMNS:
                raise ContractError("time-series state columns differ")
            state_rows = [
                row for row in reader if int(row["sample_index"]) == sample_index
            ]
    except (OSError, UnicodeError, csv.Error, KeyError, ValueError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError("time-series state is unreadable") from exc
    if not state_rows:
        raise ContractError("time-series restart sample has no surviving particles")
    state_rows.sort(key=lambda row: int(row["particle_id"]))
    source_ids = [int(row["particle_id"]) for row in state_rows]
    if len(source_ids) != len(set(source_ids)) or any(value < 1 for value in source_ids):
        raise ContractError("time-series restart state IDs differ")
    initial_by_id = _load_global_state_by_id(initial_state_path)
    if not set(source_ids).issubset(initial_by_id):
        raise ContractError("time-series restart state is absent from mother source")
    output_rows: list[dict[str, str | int]] = []
    identity_map: list[dict[str, int]] = []
    for restart_id, row in enumerate(state_rows, start=1):
        source_id = int(row["particle_id"])
        initial = initial_by_id[source_id]
        values = {
            key: float(row[key]) for key in (
                "instrument_time_us", "actual_instrument_time_us", "x_mm", "y_mm",
                "z_mm", "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us",
                "kinetic_energy_eV",
            )
        }
        if (
            row.get("event") != "pre_pulse_time_series_state"
            or row.get("survival_status") != "alive"
            or not all(math.isfinite(value) for value in values.values())
            or abs(values["instrument_time_us"] - pulse_time_us) > 1e-9
            or abs(values["actual_instrument_time_us"] - pulse_time_us) > 1e-9
        ):
            raise ContractError("time-series restart state identity or clock differs")
        mass = float(initial["mass_amu"])
        charge = int(initial["charge_state"])
        velocity = tuple(1000.0 * values[f"v{axis}_mm_per_us"] for axis in "xyz")
        energy = kinetic_energy_ev(mass, *velocity)
        if (
            mass <= 0 or charge == 0
            or not math.isclose(energy, values["kinetic_energy_eV"], rel_tol=0.0, abs_tol=5e-9)
        ):
            raise ContractError("time-series restart state energy or species differs")
        output_rows.append({
            "particle_id": restart_id,
            "instrument_time_us": format(pulse_time_us, ".17g"),
            "mass_amu": format(mass, ".17g"),
            "charge_state": charge,
            **{f"position_{axis}_mm": format(values[f"{axis}_mm"], ".17g") for axis in "xyz"},
            **{f"velocity_{axis}_m_s": format(value, ".17g") for axis, value in zip("xyz", velocity, strict=True)},
            "kinetic_energy_eV": format(energy, ".17g"),
        })
        identity_map.append({"restart_particle_id": restart_id, "producer_particle_id": source_id})
    state_output_path = state_output_path.resolve()
    receipt_output_path = receipt_output_path.resolve()
    portable_path(state_output_path, workspace_root)
    portable_path(receipt_output_path, workspace_root)
    if state_output_path == receipt_output_path:
        raise ContractError("time-series restart output paths must differ")
    state_output_path.parent.mkdir(parents=True, exist_ok=True)
    with state_output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=GLOBAL_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(output_rows)
    materialize_pre_pulse_restart(state_output_path, pulse_time_us)
    execution_count = population.get("execution_population", {}).get("particle_count")
    denominator = population.get("denominators", {}).get("population_count")
    if execution_count != len(initial_by_id) or not isinstance(denominator, int) or denominator < execution_count:
        raise ContractError("time-series mother population differs")
    terminal_census = screening.get("terminal_census")
    if not isinstance(terminal_census, dict):
        raise ContractError("time-series terminal census is missing")
    receipt = {
        "schema_version": 1,
        "role": TIME_SERIES_RESTART_RECEIPT_ROLE,
        "status": "PASS",
        "method": "manifest_bound_pulse_disabled_time_series_restart_v1",
        "producer": {
            "run_id": manifest["run_id"],
            "manifest": _restart_file_binding(child_manifest_path, workspace_root),
            "summary": _restart_file_binding(summary_path, workspace_root),
            "states": _restart_file_binding(states_path, workspace_root),
            "screening_receipt": _restart_file_binding(screening_receipt_path, workspace_root),
        },
        "authorities": {
            "initial_global_state": _restart_file_binding(initial_state_path, workspace_root),
            "pulse_schedule": _restart_file_binding(schedule_path, workspace_root),
            "resolved_population_contract": _restart_file_binding(population_path, workspace_root),
            "resolved_geometry": _restart_file_binding(geometry_path, workspace_root),
        },
        "selection": {
            "event": "pre_pulse_time_series_state",
            "sample_index": sample_index,
            "selection_uses_detector_outcome": False,
            "detector_results_used": False,
            "pulse_disabled": True,
            "producer_population_denominator_count": denominator,
            "producer_execution_population_count": execution_count,
            "producer_particle_count": len(source_ids),
            "producer_ordered_particle_ids_sha256": _restart_id_sha256(source_ids),
            "restart_to_producer_particle_id": identity_map,
            "terminal_census": terminal_census,
            "postselection_prohibited": True,
        },
        "pulse_target_state": {
            **_restart_file_binding(state_output_path, workspace_root),
            "particle_count": len(output_rows),
            "source_state_epoch": "pulse_effective_time",
            "source_state_locus": {"kind": "accelerator_stage1_interior_finite_observed_3d_cloud"},
            "coordinate_frame": "oatof_global_cartesian",
            "clock_basis": "canonical_instrument_time_us",
            "clock_authority": "resolved_single_flight_pulse_schedule",
            "pulse_effective_time_us": pulse_time_us,
            "ordered_particle_id_sha256": _restart_id_sha256(list(range(1, len(output_rows) + 1))),
        },
        "reuse_scope": {
            "role": "conditional_post_pulse_transport_initial_state",
            "allowed_variation_axes": ["accelerator_working_point"],
            "pulse_timing_reselection_required": False,
            "upstream_repropagation_required": False,
            "qualification": "DEVELOPMENT_ONLY",
        },
        "claim_limit": (
            "Detector-blind pulse-disabled source snapshot for paired inherited-versus-z-vz "
            "working-point reproduction; full mother losses remain reported and this is not locked evidence."
        ),
    }
    receipt_output_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_output_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n")
    return receipt


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


def _resolve_frozen_pre_pulse_contract(
    value: object, *, run_dir: Path
) -> Path:
    """Resolve the immutable contract after a short execution alias disappears.

    ``UseShortExecutionPath`` legitimately records a temporary execution path in
    the live run configuration.  The governed copy is always retained under the
    run's canonical ``inputs`` directory.  Only this fixed name may be used as
    a fallback, and its SHA is still verified by the caller.
    """
    try:
        return _resolve_run_path(value, role="pre-pulse time-series contract")
    except ContractError:
        retained = run_dir / "inputs" / "pre_pulse_time_series_screening_contract.json"
        if retained.is_file():
            return retained.resolve()
        raise


def _resolve_frozen_particle_row_map(value: object, *, run_dir: Path) -> Path:
    """Resolve the retained immutable particle identity map after alias cleanup.

    The map is frozen beside the screening contract before a short execution
    path may be removed.  Falling back only to this canonical run-local name
    preserves the original identity contract; it never regenerates a map.
    """
    try:
        return _resolve_run_path(value, role="particle row map")
    except ContractError:
        retained = run_dir / "inputs" / "single_flight_particle_row_map.csv"
        if retained.is_file():
            return retained.resolve()
        raise


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
        # File/cache identities are hexadecimal identifiers, not case-sensitive
        # display strings.  Contracts emitted by the governed PowerShell path
        # use uppercase hashes whereas the live cache receipt uses lowercase.
        expected[role] = key.upper()
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
) -> tuple[dict[int, list[StateRow]], list[list[int]], int, dict[str, list[int]]]:
    if not stdout_paths:
        raise ContractError("at least one SIMION stdout log is required")
    frozen_set = set(frozen_particle_ids)
    rows_by_particle = {particle_id: [] for particle_id in frozen_set}
    alive_by_sample: list[list[int]] = [[] for _ in sample_times_us]
    seen: set[tuple[int, int]] = set()
    terminal_ids: set[int] = set()
    terminal_by_reason: dict[str, list[int]] = {"window_complete": [], "splat": []}
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
                    if line.startswith(TERMINAL_PREFIX):
                        match = TERMINAL_PATTERN.fullmatch(line)
                        if match is None:
                            raise ContractError("pre-pulse terminal TRACE line is malformed")
                        particle_id = int(match["particle_id"])
                        if particle_id not in frozen_set:
                            raise ContractError("pre-pulse terminal particle identity differs")
                        if particle_id in terminal_ids:
                            raise ContractError("pre-pulse terminal particle is duplicated")
                        numeric = [float(match[name]) for name in (
                            "instrument_time", "x", "y", "z", "vx", "vy", "vz"
                        )]
                        if not all(math.isfinite(value) for value in numeric):
                            raise ContractError("pre-pulse terminal TRACE contains a non-finite number")
                        terminal_ids.add(particle_id)
                        terminal_by_reason[match["reason"]].append(particle_id)
                        continue
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
    for ids in terminal_by_reason.values():
        ids.sort()
    if terminal_ids and terminal_ids != frozen_set:
        raise ContractError("pre-pulse terminal census differs from the frozen cohort")
    return rows_by_particle, alive_by_sample, row_count, terminal_by_reason


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

    contract_path = _resolve_frozen_pre_pulse_contract(
        inputs.get("pre_pulse_time_series_contract"), run_dir=run_dir
    )
    if (
        not isinstance(expected_contract_sha256, str)
        or SHA_PATTERN.fullmatch(expected_contract_sha256) is None
        or file_sha256(contract_path) != expected_contract_sha256.upper()
    ):
        raise ContractError("pre-pulse time-series contract SHA-256 differs")
    contract = _load_object(contract_path, role="pre-pulse time-series contract")
    validate_schema(
        contract,
        INTEGRATION_SCHEMA_DIR / "rf_oatof_pre_pulse_time_series_screening_contract.schema.json",
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

    particle_row_map = _resolve_frozen_particle_row_map(
        inputs.get("particle_row_map"), run_dir=run_dir
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

    rows_by_particle, alive_by_sample, row_count, terminal_by_reason = _parse_logs(
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
        "terminal_census": {
            reason: {
                "count": len(ids),
                "ordered_particle_ids_sha256": _census_id_sha256(ids),
            }
            for reason, ids in terminal_by_reason.items()
        },
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
            "terminal_census": {
                reason: {"count": len(ids)}
                for reason, ids in terminal_by_reason.items()
            },
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
