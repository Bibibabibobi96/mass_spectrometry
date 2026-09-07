"""Materialize governed pre-pulse time-series TRACE output artifacts."""

from __future__ import annotations

import argparse
import copy
import csv
from dataclasses import dataclass
import gzip
import hashlib
import io
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
    ATTRIBUTION_COLUMNS,
    GLOBAL_COLUMNS,
    materialize_pre_pulse_restart,
)


TRACE_PREFIX = "TRACE: pre_pulse_time_series_state"
TRACE_PATTERN = re.compile(
    r"^TRACE: pre_pulse_time_series_state "
    r"ion=(?P<ion>\d+) particle_id=(?P<particle_id>\d+) "
    r"sample_index=(?P<sample_index>\S+) "
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
SOURCE_RELEASE_PREFIX = "TRACE: source_release"
SOURCE_RELEASE_PATTERN = re.compile(
    r"^TRACE: source_release "
    r"ion=(?P<ion>\d+) particle_id=(?P<particle_id>\d+) "
    r"instrument_time_us=(?P<instrument_time>[-+0-9.eE]+) "
    r"x_mm=(?P<x>[-+0-9.eE]+) y_mm=(?P<y>[-+0-9.eE]+) "
    r"z_mm=(?P<z>[-+0-9.eE]+) "
    r"vx_mm_per_us=(?P<vx>[-+0-9.eE]+) "
    r"vy_mm_per_us=(?P<vy>[-+0-9.eE]+) "
    r"vz_mm_per_us=(?P<vz>[-+0-9.eE]+) "
    r"simion_native_kinetic_energy_eV=(?P<energy>[-+0-9.eE]+) "
    r"source_instance=(?P<source_instance>\d+)$"
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
    r"terminal_reason=(?P<reason>window_complete|splat|geometry_collision|outside_pa_termination)$"
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
STATE_ARCHIVE_FILENAME = "pre_pulse_time_series_states.csv.gz"
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


def open_pre_pulse_state_table(path: Path):
    """Open current compressed and historical uncompressed state CSV files."""

    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open(encoding="utf-8-sig", newline="")


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


def _validate_selected_time(
    *,
    selection_receipt_path: Path | None,
    states_path: Path,
    screening_receipt_path: Path,
    sample_index: int,
    sample_time_us: float,
    workspace_root: Path,
) -> dict[str, object] | None:
    """Bind an off-seed restart to its detector-blind selection receipt.

    The ballistic schedule is only a seed for a time-series search.  A later
    sample may become the physical pulse time, but only when the published
    detector-blind receipt names that exact sample and the same raw TRACE.
    """

    if selection_receipt_path is None:
        return None
    selection_receipt_path = selection_receipt_path.resolve()
    portable_path(selection_receipt_path, workspace_root)
    receipt = _load_object(
        selection_receipt_path, role="detector-blind pulse selection receipt"
    )
    authorities = receipt.get("authorities")
    ranked = receipt.get("candidates_ranked")
    if (
        receipt.get("role")
        != "rf_oatof_detector_blind_real_field_pulse_timing_selection_receipt"
        or receipt.get("status") != "success"
        or receipt.get("selection_uses_detector_outcome") is not False
        or receipt.get("detector_results_used") is not False
        or not isinstance(authorities, dict)
        or not isinstance(ranked, list)
        or not ranked
    ):
        raise ContractError("detector-blind pulse selection receipt differs")
    states_record = authorities.get("real_field_state_table")
    screening_record = authorities.get("pre_pulse_time_series_receipt")
    winner = ranked[0] if isinstance(ranked[0], dict) else None
    if (
        not isinstance(states_record, dict)
        or not isinstance(screening_record, dict)
        or not isinstance(winner, dict)
        or states_record.get("sha256") != file_sha256(states_path)
        or screening_record.get("sha256") != file_sha256(screening_receipt_path)
        or winner.get("sample_index") != sample_index
        or not math.isclose(
            float(receipt.get("selected_time_us", math.nan)), sample_time_us,
            rel_tol=0.0, abs_tol=1e-9,
        )
        or not math.isclose(
            float(winner.get("candidate_time_us", math.nan)), sample_time_us,
            rel_tol=0.0, abs_tol=1e-9,
        )
    ):
        raise ContractError("detector-blind pulse selection does not bind restart sample")
    return _restart_file_binding(selection_receipt_path, workspace_root)


def _selected_pulse_eligible_ids(
    selection_receipt_path: Path | None, *, sample_index: int
) -> list[int] | None:
    """Return the detector-blind geometry-qualified IDs for a selected sample.

    A natural archive's alive rows include ions still upstream of, or already
    outside, the accelerator bore.  The timing selector has already classified
    that full mother cohort at the selected native RF tick.  Reuse its frozen
    ``pulse_eligible_ids`` here so a reduced post-pulse IOB receives exactly
    the physically covered cohort without detector-based postselection.
    """
    if selection_receipt_path is None:
        return None
    selection = _load_object(
        selection_receipt_path.resolve(), role="detector-blind pulse selection receipt"
    )
    matches = [
        item for item in selection.get("candidates_ranked", [])
        if isinstance(item, dict) and item.get("sample_index") == sample_index
    ]
    if len(matches) != 1:
        raise ContractError("detector-blind pulse selection does not name one sample")
    candidate = matches[0]
    ids = candidate.get("pulse_eligible_ids")
    identity = candidate.get("pulse_eligible_identity")
    if (
        not isinstance(ids, list) or not ids
        or any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in ids)
        or ids != sorted(set(ids))
        or not isinstance(identity, dict)
        or identity.get("count") != len(ids)
        or identity.get("ordered_particle_id_sha256") != _restart_id_sha256(ids)
    ):
        raise ContractError("detector-blind pulse-eligible cohort identity differs")
    return ids


def materialize_manifest_bound_restart(
    *,
    child_manifest_path: Path,
    workspace_root: Path,
    state_output_path: Path,
    receipt_output_path: Path,
    sample_index: int = 1,
    selection_receipt_path: Path | None = None,
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
        or manifest.get("mode") not in {
            "rf_to_oatof_simion_single_flight",
            "rf_oatof_pre_pulse_time_series_analysis_recovery",
        }
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
        manifest, collection="outputs", name=STATE_ARCHIVE_FILENAME,
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
    if isinstance(sample_times, list):
        if sample_index > len(sample_times):
            raise ContractError("time-series restart sample is absent")
        pulse_time_us = float(sample_times[sample_index - 1])
    else:
        # v7 is intentionally not a finite predeclared window.  The selected
        # native-grid state is named by the detector-blind receipt, so later
        # pulse policies can consume the same natural trajectory archive.
        if selection_receipt_path is None:
            raise ContractError("natural archive restart requires a pulse selection receipt")
        selected = _load_object(
            selection_receipt_path.resolve(), role="detector-blind pulse selection receipt"
        )
        matches = [
            item for item in selected.get("candidates_ranked", [])
            if isinstance(item, dict) and item.get("sample_index") == sample_index
        ]
        if len(matches) != 1:
            raise ContractError("natural archive restart sample is absent")
        try:
            pulse_time_us = float(matches[0]["candidate_time_us"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("natural archive restart clock is invalid") from exc
    scheduled_time_us = float(schedule.get("pulse_effective_time_us", math.nan))
    if (
        not math.isfinite(pulse_time_us)
        or not math.isfinite(scheduled_time_us)
    ):
        raise ContractError("time-series restart clock differs from pulse schedule")
    selection_record = _validate_selected_time(
        selection_receipt_path=selection_receipt_path,
        states_path=states_path,
        screening_receipt_path=screening_receipt_path,
        sample_index=sample_index,
        sample_time_us=pulse_time_us,
        workspace_root=workspace_root,
    )
    if selection_record is None and abs(pulse_time_us - scheduled_time_us) > 1e-9:
        raise ContractError("time-series restart clock differs from pulse schedule")
    try:
        with open_pre_pulse_state_table(states_path) as handle:
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
    pulse_eligible_ids = _selected_pulse_eligible_ids(
        selection_receipt_path, sample_index=sample_index
    )
    if pulse_eligible_ids is not None:
        by_particle_id = {int(row["particle_id"]): row for row in state_rows}
        if len(by_particle_id) != len(state_rows) or not set(pulse_eligible_ids).issubset(by_particle_id):
            raise ContractError("detector-blind pulse-eligible cohort is absent from selected state rows")
        state_rows = [by_particle_id[particle_id] for particle_id in pulse_eligible_ids]
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
            "simulation_particle_id": restart_id,
            "source_particle_id": source_id,
            "arm_id": "pre_pulse_restart",
            "instrument_time_us": format(pulse_time_us, ".17g"),
            "mass_amu": format(mass, ".17g"),
            "charge_state": charge,
            **{f"{axis}_mm": format(values[f"{axis}_mm"], ".17g") for axis in "xyz"},
            **{f"v{axis}_m_s": format(value, ".17g") for axis, value in zip("xyz", velocity, strict=True)},
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
        writer = csv.DictWriter(handle, fieldnames=ATTRIBUTION_COLUMNS, lineterminator="\n")
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
            **(
                {"detector_blind_selection_receipt": selection_record}
                if selection_record is not None else {}
            ),
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
            "clock_authority": (
                "detector_blind_pulse_selection_receipt"
                if selection_record is not None
                else "resolved_single_flight_pulse_schedule"
            ),
            "pulse_effective_time_us": pulse_time_us,
            # restart_particle_id is only a contiguous SIMION row number.  The
            # frozen population identity remains the source-particle ordering,
            # including for sparse smoke selections such as source ID 46.
            "ordered_particle_id_sha256": _restart_id_sha256(source_ids),
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


def _native_checkpoint_omission(
    *,
    sample_index: int,
    prior_sample_index: int,
    instrument_time_us: float,
    actual_time_us: float,
    grid_origin_us: float,
    grid_step_us: float,
) -> bool:
    """Identify SIMION's extra checkpoint at the preceding native RF tick.

    The program's monotonically increasing ``sample_index`` is normally the
    canonical time identity.  In the observed SIMION 2020 trace anomaly, an
    extra callback consumes the next index but its requested time remains the
    preceding grid node.  The true next observation then has the following
    index, leaving one explicitly unobserved grid point.  Accept only that
    narrow, ordered pattern; an arbitrary clock mismatch remains fatal.
    """

    if sample_index != prior_sample_index + 1 or prior_sample_index < 1:
        return False
    prior_time_us = grid_origin_us + (prior_sample_index - 1) * grid_step_us
    expected_time_us = prior_time_us + grid_step_us
    tolerance_us = 1e-12 * max(1.0, abs(prior_time_us))
    return (
        abs(instrument_time_us - prior_time_us) <= tolerance_us
        and prior_time_us - tolerance_us <= actual_time_us
        and abs(actual_time_us - prior_time_us)
        <= abs(actual_time_us - expected_time_us)
    )


def resolve_natural_archive_sample_index(
    *,
    reported_token: str,
    instrument_time_us: float,
    grid_origin_us: float,
    grid_step_us: float,
) -> tuple[int, dict[str, object] | None]:
    """Resolve one native-grid index and narrowly repair formatter damage.

    SIMION 2020 can replace one decimal digit in a ``%d`` rendering even
    though the separately emitted instrument clock remains correct.  The
    frozen RF grid is therefore the numeric authority.  A decimal token must
    agree with it exactly; a damaged token is accepted only when it has the
    same width, differs at exactly one position, and that position contains a
    non-digit.  Every other malformed token or off-grid clock remains fatal.
    """

    if (
        not isinstance(reported_token, str)
        or not reported_token
        or not reported_token.isascii()
        or not all(
            math.isfinite(value)
            for value in (instrument_time_us, grid_origin_us, grid_step_us)
        )
        or grid_step_us <= 0.0
    ):
        raise ContractError("pre-pulse natural sample identity is invalid")
    raw_index = (instrument_time_us - grid_origin_us) / grid_step_us
    canonical_index = math.floor(raw_index + 0.5) + 1
    expected_time_us = grid_origin_us + (canonical_index - 1) * grid_step_us
    tolerance_us = 1e-12 * max(1.0, abs(expected_time_us))
    if canonical_index < 1 or abs(instrument_time_us - expected_time_us) > tolerance_us:
        raise ContractError("pre-pulse TRACE sample does not land on the native grid")
    if reported_token.isdecimal():
        if int(reported_token) != canonical_index:
            raise ContractError("pre-pulse TRACE sample index differs from its native-grid clock")
        return canonical_index, None

    canonical_token = str(canonical_index)
    differing = [
        offset
        for offset, (reported, expected) in enumerate(
            zip(reported_token, canonical_token, strict=False)
        )
        if reported != expected
    ]
    if (
        len(reported_token) != len(canonical_token)
        or len(differing) != 1
        or reported_token[differing[0]].isdigit()
    ):
        raise ContractError("pre-pulse TRACE sample-index formatter token is invalid")
    return canonical_index, {
        "reported_sample_index": reported_token,
        "canonical_sample_index": canonical_index,
        "instrument_time_us": instrument_time_us,
    }


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
    schema_version = contract.get("schema_version")
    active_roles = (
        {
            "fine_upstream": "simion_single_flight_upstream_bridge_pa_cache",
            "accelerator_main": "simion_single_flight_accelerator_main_pa_cache",
            "accelerator_entrance_zone_collision": (
                "simion_single_flight_accelerator_entrance_zone_collision_pa_cache"
            ),
            "accelerator_entrance_local": (
                "simion_single_flight_accelerator_entrance_local_pa_cache"
            ),
        }
        if schema_version in {5, 6, 7}
        else
        {
            "full_coarse_bridge": "simion_single_flight_frontend_pa_cache",
            "fine_upstream": "simion_single_flight_upstream_bridge_pa_cache",
            "accelerator_main": "simion_single_flight_accelerator_main_pa_cache",
            "accelerator_intermediate2_overlay": "simion_accelerator_intermediate_overlay_pa_cache",
        }
        if schema_version == 4
        else {
        "frontend": "simion_single_flight_frontend_pa_cache",
        **(
            {
                "accelerator_entrance_overlay": (
                    "simion_accelerator_entrance_overlay_pa_cache"
                ),
                "accelerator_intermediate_overlay": (
                    "simion_accelerator_intermediate_overlay_pa_cache"
                ),
            }
            if schema_version == 3
            else {"accelerator_overlay": "simion_accelerator_overlay_pa_cache"}
        ),
        }
    )
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
            # The runner permits this only after it has checked every physical
            # identity field and the exact legacy/current boundary-builder
            # hash mapping.  Preserve that verified cache key in the
            # materialized receipt; do not force an identical PA rebuild.
            "cache_hit_semantically_equivalent_boundary_builder",
        }:
            raise ContractError("pre-pulse active PA cache disposition differs")
        # File/cache identities are hexadecimal identifiers, not case-sensitive
        # display strings.  Contracts emitted by the governed PowerShell path
        # use uppercase hashes whereas the live cache receipt uses lowercase.
        expected[role] = key.upper()
    # The current reachable pre-pulse topology has exactly three instances,
    # so downstream hardware is omitted rather than retained as a formal PA
    # dependency.  Older screening contracts used the historical `formal`
    # receipt spelling and remain readable only for their explicit versions.
    downstream_disposition = (
        "not_applicable" if schema_version in {5, 6, 7} else "formal"
    )
    for role in ("flight_tube", "reflectron"):
        disposition = dispositions.get(role)
        if (
            not isinstance(disposition, dict)
            or disposition.get("key") is not None
            or disposition.get("disposition") != downstream_disposition
        ):
            raise ContractError(
                "pre-pulse downstream PA cache disposition differs"
            )
        expected[role] = None

    if schema_version == 1:
        declared = contract.get("pa_cache_keys")
        if declared != expected:
            raise ContractError("pre-pulse schema-v1 PA cache keys differ")
        return copy.deepcopy(declared)
    roles = contract.get("pa_cache_roles")
    required_roles = list(active_roles)
    if (
        not isinstance(roles, dict)
        or roles.get("identity_source")
        != "runner_materialized_verified_pa_cache_receipt"
        or roles.get("required") != required_roles
        or roles.get("prohibited") != ["flight_tube", "reflectron"]
    ):
        raise ContractError("pre-pulse PA cache role policy differs")
    return expected


def _parse_logs(
    stdout_paths: Sequence[Path],
    *,
    frozen_particle_ids: Sequence[int],
    sample_times_us: Sequence[float],
    natural_archive_grid: tuple[float, float] | None = None,
) -> tuple[dict[int, list[StateRow]], list[list[int]], int, dict[str, list[int]]]:
    if not stdout_paths:
        raise ContractError("at least one SIMION stdout log is required")
    frozen_set = set(frozen_particle_ids)
    rows_by_particle = {particle_id: [] for particle_id in frozen_set}
    alive_by_sample: list[list[int]] = [[] for _ in sample_times_us]
    seen: set[tuple[int, int]] = set()
    terminal_ids: set[int] = set()
    # SIMION may invoke the terminal callback twice for a splat while it
    # resolves the collision.  A byte-identical terminal record is therefore
    # an idempotent duplicate, not a second physical outcome.  Keep its full
    # parsed identity so that any conflicting repeat remains a hard failure.
    terminal_records: dict[int, tuple[float, float, float, float, float, float, float, str]] = {}
    terminal_by_reason: dict[str, list[int]] = {
        "window_complete": [], "splat": [], "geometry_collision": [],
        "outside_pa_termination": [],
    }
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
                        numeric = [float(match[name]) for name in (
                            "instrument_time", "x", "y", "z", "vx", "vy", "vz"
                        )]
                        if not all(math.isfinite(value) for value in numeric):
                            raise ContractError("pre-pulse terminal TRACE contains a non-finite number")
                        terminal_record = (*numeric, match["reason"])
                        previous_terminal = terminal_records.get(particle_id)
                        if previous_terminal is not None:
                            if previous_terminal != terminal_record:
                                raise ContractError(
                                    "pre-pulse terminal particle has conflicting duplicates"
                                )
                            continue
                        terminal_records[particle_id] = terminal_record
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
                    if sample_index < 1 or (
                        natural_archive_grid is None and sample_index > len(sample_times_us)
                    ):
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
                    if natural_archive_grid is not None:
                        expected_time = natural_archive_grid[0] + (
                            sample_index - 1
                        ) * natural_archive_grid[1]
                        while len(alive_by_sample) < sample_index:
                            alive_by_sample.append([])
                    else:
                        expected_time = float(sample_times_us[sample_index - 1])
                    tolerance = 1e-12 * max(1.0, abs(expected_time))
                    # A natural archive labels each sample by the canonical RF
                    # grid time.  SIMION's accumulated clock is intentionally
                    # retained in ``actual_time`` and can differ by a few ULP;
                    # it is an observation, not a second requested landing.
                    # Finite-window samples retain the historical stricter
                    # contract because both fields denote one scheduled event.
                    actual_time_mismatch = (
                        natural_archive_grid is None
                        and abs(numeric["actual_time"] - expected_time) > tolerance
                    )
                    if (
                        abs(numeric["instrument_time"] - expected_time) > tolerance
                        or actual_time_mismatch
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
        first_index = particle_rows[0].sample_index if particle_rows else 1
        if [row.sample_index for row in particle_rows] != list(
            range(first_index, first_index + len(particle_rows))
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
    def write_rows(handle: Any) -> None:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
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

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        if path.suffix == ".gz":
            with temporary.open("wb") as raw_handle:
                with gzip.GzipFile(
                    filename="", mode="wb", fileobj=raw_handle, mtime=0
                ) as compressed_handle:
                    with io.TextIOWrapper(
                        compressed_handle, encoding="utf-8", newline=""
                    ) as text_handle:
                        write_rows(text_handle)
        else:
            with temporary.open("w", encoding="utf-8", newline="") as handle:
                write_rows(handle)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _stream_logs_to_states_csv(
    stdout_paths: Sequence[Path],
    *,
    frozen_particle_ids: Sequence[int],
    sample_times_us: Sequence[float],
    natural_archive_grid: tuple[float, float] | None,
    states_path: Path,
    natural_sample_count_out: list[int] | None = None,
    trace_token_repairs_out: list[dict[str, object]] | None = None,
) -> tuple[
    int,
    dict[str, list[int]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    """Validate ordered SIMION TRACE output while writing its compact archive.

    The governed batch program emits one particle's native-RF states in order,
    and batches are ordered by their frozen global particle IDs.  Keeping every
    row plus a duplicate ``(particle_id, sample_index)`` set made a large
    natural archive require substantially more RAM than the raw logs.  This
    path retains only O(samples + particles) validation state and atomically
    publishes the same gzip CSV after the complete trace is accepted.
    """
    if not stdout_paths:
        raise ContractError("at least one SIMION stdout log is required")
    frozen_ids = list(frozen_particle_ids)
    frozen_set = set(frozen_ids)
    if len(frozen_set) != len(frozen_ids) or frozen_ids != sorted(frozen_ids):
        raise ContractError("pre-pulse frozen particle identity differs")
    rank_by_id = {particle_id: rank for rank, particle_id in enumerate(frozen_ids)}
    # Natural archives declare their native grid rather than materialising a
    # finite ``sample_times_us`` list.  The source-release callback is its
    # authoritative first (t=0) sample, so allocate that census slot before
    # streaming the first TRACE line.
    initial_sample_count = max(
        len(sample_times_us),
        1 if natural_archive_grid is not None else 0,
    )
    alive_counts = [0] * initial_sample_count
    # A finite window publishes every sample, so it needs its complete
    # identity census while streaming.  A natural archive publishes only
    # population-change points; defer their small identity census until the
    # complete gzip state table exists rather than allocating two SHA objects
    # and updating missing-ID ranges for every RF tick.
    alive_hashers = (
        None if natural_archive_grid is not None
        else [hashlib.sha256() for _ in range(initial_sample_count)]
    )
    missing_hashers = (
        None if natural_archive_grid is not None
        else [hashlib.sha256() for _ in range(initial_sample_count)]
    )
    last_rank_by_sample = [-1] * initial_sample_count
    alive_started = [False] * initial_sample_count
    missing_started = [False] * initial_sample_count
    missing_ids = None if natural_archive_grid is not None else [[] for _ in sample_times_us]

    def ensure_sample(sample_index: int) -> None:
        while len(alive_counts) < sample_index:
            alive_counts.append(0)
            if alive_hashers is not None:
                alive_hashers.append(hashlib.sha256())
            if missing_hashers is not None:
                missing_hashers.append(hashlib.sha256())
            last_rank_by_sample.append(-1)
            alive_started.append(False)
            missing_started.append(False)

    def append_id(hasher: Any, started: list[bool], index: int, particle_id: int) -> None:
        if started[index]:
            hasher.update(b",")
        else:
            hasher.update(b'{"ordered_particle_ids":[')
            started[index] = True
        hasher.update(str(particle_id).encode("ascii"))

    def append_missing_before(sample_zero_index: int, rank: int) -> None:
        if missing_hashers is None:
            return
        for missing_rank in range(last_rank_by_sample[sample_zero_index] + 1, rank):
            particle_id = frozen_ids[missing_rank]
            append_id(
                missing_hashers[sample_zero_index], missing_started,
                sample_zero_index, particle_id,
            )
            if missing_ids is not None:
                missing_ids[sample_zero_index].append(particle_id)

    terminal_ids: set[int] = set()
    terminal_records: dict[int, tuple[float, float, float, float, float, float, float, str]] = {}
    terminal_by_reason: dict[str, list[int]] = {
        "window_complete": [], "splat": [], "geometry_collision": [],
        "outside_pa_termination": [],
    }
    row_count = 0
    last_particle_rank = -1
    current_particle_id: int | None = None
    current_sample_index = 0
    omitted_checkpoint_index: int | None = None
    checkpoint_omissions: list[dict[str, object]] = []
    source_release_ids: set[int] = set()
    states_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = states_path.with_name(states_path.name + ".tmp")

    class _SegmentedGzipCsvWriter:
        """Write independently closed gzip members into one valid gzip CSV.

        Python's gzip reader (and standard gzip tooling) transparently reads
        concatenated members.  Closing the member after each SIMION batch
        bounds the native compressor lifetime without changing the archive
        bytes seen by a CSV reader: the header is still emitted exactly once.
        """

        def __init__(self, path: Path) -> None:
            self._raw = path.open("wb")
            self._compressed: gzip.GzipFile | None = None
            self._text: io.TextIOWrapper | None = None
            self._writer: Any = None

        def start_batch(self) -> None:
            if self._text is not None:
                raise RuntimeError("gzip CSV batch is already open")
            self._compressed = gzip.GzipFile(
                filename="", mode="wb", fileobj=self._raw, mtime=0
            )
            self._text = io.TextIOWrapper(
                self._compressed, encoding="utf-8", newline=""
            )
            self._writer = csv.writer(
                self._text, quoting=csv.QUOTE_ALL, lineterminator="\r\n"
            )

        def writerow(self, row: Sequence[object]) -> None:
            if self._writer is None:
                raise RuntimeError("gzip CSV batch is not open")
            self._writer.writerow(row)

        def finish_batch(self) -> None:
            if self._text is None:
                return
            self._text.close()
            self._text = None
            self._compressed = None
            self._writer = None
            self._raw.flush()

        def close(self) -> None:
            self.finish_batch()
            self._raw.close()

        def __enter__(self) -> "_SegmentedGzipCsvWriter":
            return self

        def __exit__(self, *_: object) -> None:
            self.close()

    try:
        with _SegmentedGzipCsvWriter(temporary) as writer:
                    writer.start_batch()
                    writer.writerow(CSV_COLUMNS)
                    for batch_index, stdout_path in enumerate(stdout_paths):
                        if batch_index:
                            writer.start_batch()
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
                                    # SIMION reports the initial state from
                                    # segment.initialize separately.  For the
                                    # natural archive it is the native grid's
                                    # t=0 sample, not a diagnostic-only line:
                                    # retain it so particles that collide
                                    # before the first RF tick still have a
                                    # complete alive prefix.
                                    if (
                                        natural_archive_grid is not None
                                        and line.startswith(SOURCE_RELEASE_PREFIX)
                                    ):
                                        match = SOURCE_RELEASE_PATTERN.fullmatch(line)
                                        if match is None:
                                            raise ContractError(
                                                "pre-pulse source-release TRACE line is malformed"
                                            )
                                        particle_id = int(match["particle_id"])
                                        numeric = {
                                            name: float(match[name]) for name in (
                                                "instrument_time", "x", "y", "z",
                                                "vx", "vy", "vz", "energy",
                                            )
                                        }
                                        if (
                                            particle_id not in frozen_set
                                            or particle_id in source_release_ids
                                            or not all(math.isfinite(value) for value in numeric.values())
                                        ):
                                            raise ContractError(
                                                "pre-pulse source-release identity differs"
                                            )
                                        expected_time = natural_archive_grid[0]
                                        tolerance = 1e-12 * max(1.0, abs(expected_time))
                                        if abs(numeric["instrument_time"] - expected_time) > tolerance:
                                            raise ContractError(
                                                "pre-pulse source-release time landing differs"
                                            )
                                        sample_zero_index = 0
                                        particle_rank = rank_by_id[particle_id]
                                        if particle_rank <= last_rank_by_sample[sample_zero_index]:
                                            raise ContractError(
                                                "pre-pulse source-release order differs from frozen batches"
                                            )
                                        if alive_hashers is not None:
                                            append_missing_before(sample_zero_index, particle_rank)
                                            append_id(
                                                alive_hashers[sample_zero_index], alive_started,
                                                sample_zero_index, particle_id,
                                            )
                                        alive_counts[sample_zero_index] += 1
                                        last_rank_by_sample[sample_zero_index] = particle_rank
                                        source_release_ids.add(particle_id)
                                        writer.writerow((
                                            particle_id, "pre_pulse_time_series_state", 1,
                                            _dotnet_roundtrip(expected_time),
                                            _dotnet_roundtrip(numeric["instrument_time"]),
                                            *(
                                                _dotnet_roundtrip(numeric[name])
                                                for name in ("x", "y", "z", "vx", "vy", "vz", "energy")
                                            ),
                                            "alive",
                                        ))
                                        row_count += 1
                                        continue
                                    if line.startswith(TERMINAL_PREFIX):
                                        match = TERMINAL_PATTERN.fullmatch(line)
                                        if match is None:
                                            raise ContractError("pre-pulse terminal TRACE line is malformed")
                                        particle_id = int(match["particle_id"])
                                        if particle_id not in frozen_set:
                                            raise ContractError("pre-pulse terminal particle identity differs")
                                        numeric = [float(match[name]) for name in (
                                            "instrument_time", "x", "y", "z", "vx", "vy", "vz"
                                        )]
                                        if not all(math.isfinite(value) for value in numeric):
                                            raise ContractError("pre-pulse terminal TRACE contains a non-finite number")
                                        terminal_record = (*numeric, match["reason"])
                                        previous_terminal = terminal_records.get(particle_id)
                                        if previous_terminal is not None:
                                            if previous_terminal != terminal_record:
                                                raise ContractError(
                                                    "pre-pulse terminal particle has conflicting duplicates"
                                                )
                                            continue
                                        terminal_records[particle_id] = terminal_record
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
                                        numeric = {
                                            name: float(match[name]) for name in (
                                                "instrument_time", "actual_time", "x", "y", "z",
                                                "vx", "vy", "vz", "energy",
                                            )
                                        }
                                    except ValueError as exc:
                                        raise ContractError(
                                            "pre-pulse state TRACE numeric field is invalid"
                                        ) from exc
                                    sample_index_token = match["sample_index"]
                                    if (
                                        natural_archive_grid is not None
                                        and sample_index_token.isdecimal()
                                        and particle_id == current_particle_id
                                        and _native_checkpoint_omission(
                                            sample_index=int(sample_index_token),
                                            prior_sample_index=current_sample_index,
                                            instrument_time_us=numeric["instrument_time"],
                                            actual_time_us=numeric["actual_time"],
                                            grid_origin_us=natural_archive_grid[0],
                                            grid_step_us=natural_archive_grid[1],
                                        )
                                    ):
                                        if omitted_checkpoint_index is not None:
                                            raise ContractError(
                                                "pre-pulse native checkpoint omission differs"
                                            )
                                        omitted_checkpoint_index = int(sample_index_token)
                                        checkpoint_omissions.append({
                                            "particle_id": particle_id,
                                            "sample_index": omitted_checkpoint_index,
                                            "canonical_instrument_time_us": (
                                                natural_archive_grid[0]
                                                + (omitted_checkpoint_index - 1)
                                                * natural_archive_grid[1]
                                            ),
                                            "reported_instrument_time_us": numeric[
                                                "instrument_time"
                                            ],
                                            "actual_instrument_time_us": numeric[
                                                "actual_time"
                                            ],
                                        })
                                        continue
                                    if natural_archive_grid is not None:
                                        sample_index, token_repair = (
                                            resolve_natural_archive_sample_index(
                                                reported_token=sample_index_token,
                                                instrument_time_us=numeric["instrument_time"],
                                                grid_origin_us=natural_archive_grid[0],
                                                grid_step_us=natural_archive_grid[1],
                                            )
                                        )
                                        if (
                                            token_repair is not None
                                            and trace_token_repairs_out is not None
                                        ):
                                            trace_token_repairs_out.append(token_repair)
                                    elif sample_index_token.isdecimal():
                                        sample_index = int(sample_index_token)
                                    else:
                                        raise ContractError(
                                            "pre-pulse TRACE sample index is malformed"
                                        )
                                    if particle_id not in frozen_set:
                                        raise ContractError("pre-pulse TRACE particle identity differs")
                                    if sample_index < 1 or (
                                        natural_archive_grid is None
                                        and sample_index > len(sample_times_us)
                                    ):
                                        raise ContractError(
                                            "pre-pulse TRACE sample index is outside the frozen grid"
                                        )
                                    if not all(math.isfinite(value) for value in numeric.values()):
                                        raise ContractError("pre-pulse TRACE contains a non-finite number")
                                    if natural_archive_grid is not None:
                                        ensure_sample(sample_index)
                                        expected_time = natural_archive_grid[0] + (
                                            sample_index - 1
                                        ) * natural_archive_grid[1]
                                    else:
                                        expected_time = float(sample_times_us[sample_index - 1])
                                    tolerance = 1e-12 * max(1.0, abs(expected_time))
                                    particle_rank = rank_by_id[particle_id]
                                    if particle_rank < last_particle_rank:
                                        raise ContractError(
                                            "pre-pulse TRACE particle order differs from frozen batches"
                                        )
                                    if (
                                        abs(numeric["instrument_time"] - expected_time) > tolerance
                                        or (
                                            natural_archive_grid is None
                                            and abs(numeric["actual_time"] - expected_time) > tolerance
                                        )
                                        or match["status"] != "alive"
                                    ):
                                        raise ContractError(
                                            "pre-pulse TRACE identity/time landing differs: "
                                            f"particle_id={particle_id} sample_index={sample_index} "
                                            f"expected_time_us={expected_time:.17g} "
                                            f"instrument_time_us={numeric['instrument_time']:.17g} "
                                            f"actual_time_us={numeric['actual_time']:.17g} "
                                            f"status={match['status']}"
                                        )
                                    if particle_id == current_particle_id:
                                        expected_next_index = current_sample_index + 1
                                        if omitted_checkpoint_index is not None:
                                            expected_next_index += 1
                                        if sample_index != expected_next_index:
                                            raise ContractError(
                                                "pre-pulse particle state is not one continuous alive prefix"
                                            )
                                    else:
                                        if particle_rank == last_particle_rank:
                                            raise ContractError("pre-pulse TRACE particle/sample is duplicated")
                                        current_particle_id = particle_id
                                        current_sample_index = 0
                                        omitted_checkpoint_index = None
                                        last_particle_rank = particle_rank
                                    current_sample_index = sample_index
                                    omitted_checkpoint_index = None
                                    sample_zero_index = sample_index - 1
                                    if alive_hashers is not None:
                                        append_missing_before(sample_zero_index, particle_rank)
                                        append_id(
                                            alive_hashers[sample_zero_index], alive_started,
                                            sample_zero_index, particle_id,
                                        )
                                    alive_counts[sample_zero_index] += 1
                                    last_rank_by_sample[sample_zero_index] = particle_rank
                                    writer.writerow((
                                        particle_id, "pre_pulse_time_series_state", sample_index,
                                        _dotnet_roundtrip(numeric["instrument_time"]),
                                        _dotnet_roundtrip(numeric["actual_time"]),
                                        _dotnet_roundtrip(numeric["x"]),
                                        _dotnet_roundtrip(numeric["y"]),
                                        _dotnet_roundtrip(numeric["z"]),
                                        _dotnet_roundtrip(numeric["vx"]),
                                        _dotnet_roundtrip(numeric["vy"]),
                                        _dotnet_roundtrip(numeric["vz"]),
                                        _dotnet_roundtrip(numeric["energy"]), "alive",
                                    ))
                                    row_count += 1
                        except (OSError, UnicodeError) as exc:
                            raise ContractError(
                                f"SIMION stdout log is unreadable: {stdout_path}"
                            ) from exc
                        # End each compressed member at the SIMION batch
                        # boundary.  The next member is still part of the
                        # same standards-compliant gzip CSV stream.
                        writer.finish_batch()
        for ids in terminal_by_reason.values():
            ids.sort()
        # A finite screening window terminates every particle explicitly.
        # Natural global callbacks distinguish collisions from native outside-PA
        # termination. Older local-callback archives may contain only the last
        # alive state for outside-PA ions; never invent a collision for them.
        if (
            natural_archive_grid is None
            and terminal_ids
            and terminal_ids != frozen_set
        ):
            raise ContractError("pre-pulse terminal census differs from the frozen cohort")
        if natural_archive_grid is not None:
            observed_count = sum(alive_count > 0 for alive_count in alive_counts)
            if natural_sample_count_out is not None:
                natural_sample_count_out.append(observed_count)
            sample_census = _natural_receipt_sample_census_from_states(
                states_path=temporary,
                frozen_particle_ids=frozen_ids,
                alive_counts=alive_counts,
                grid_origin_us=natural_archive_grid[0],
                grid_step_us=natural_archive_grid[1],
            )
        else:
            assert alive_hashers is not None and missing_hashers is not None
            for sample_zero_index in range(len(alive_counts)):
                append_missing_before(sample_zero_index, len(frozen_ids))
                if not alive_started[sample_zero_index]:
                    alive_hashers[sample_zero_index].update(b'{"ordered_particle_ids":[')
                alive_hashers[sample_zero_index].update(b"]}")
                if not missing_started[sample_zero_index]:
                    missing_hashers[sample_zero_index].update(b'{"ordered_particle_ids":[')
                missing_hashers[sample_zero_index].update(b"]}")
            sample_census = []
            for sample_zero_index, alive_count in enumerate(alive_counts):
                sample_census.append({
                    "sample_index": sample_zero_index + 1,
                    "instrument_time_us": sample_times_us[sample_zero_index],
                    "alive_count": alive_count,
                    "alive_particle_ids_sha256": alive_hashers[sample_zero_index].hexdigest(),
                    "missing_count": len(frozen_ids) - alive_count,
                    "missing_particle_ids": missing_ids[sample_zero_index],
                    "missing_particle_ids_sha256": missing_hashers[sample_zero_index].hexdigest(),
                })
        os.replace(temporary, states_path)
        return row_count, terminal_by_reason, sample_census, checkpoint_omissions
    finally:
        temporary.unlink(missing_ok=True)


def _receipt_sample_census(
    sample_census: Sequence[dict[str, object]], *, natural_archive: bool
) -> list[dict[str, object]]:
    """Keep a bounded natural-archive census without duplicating trajectory data.

    The gzip state table is the authoritative, complete native-grid trajectory
    payload.  Copying one JSON object for every native tick into both receipt
    and summary turns a compact screening receipt into a larger, fragile
    duplicate of that payload.  For a natural archive, retain its initial
    state, every population-change boundary and its last observed state.
    Finite scheduled windows retain their complete small census.
    """
    if not natural_archive or len(sample_census) <= 1:
        return list(sample_census)
    result = [sample_census[0]]
    previous_alive = sample_census[0].get("alive_count")
    for item in sample_census[1:-1]:
        alive = item.get("alive_count")
        if alive != previous_alive:
            result.append(item)
        previous_alive = alive
    if result[-1] is not sample_census[-1]:
        result.append(sample_census[-1])
    return result


def _natural_receipt_sample_census_from_states(
    *,
    states_path: Path,
    frozen_particle_ids: Sequence[int],
    alive_counts: Sequence[int],
    grid_origin_us: float,
    grid_step_us: float,
) -> list[dict[str, object]]:
    """Build only retained natural-census identities from the gzip state table.

    The state table is the complete native-grid evidence.  A natural receipt
    deliberately retains only its first state, survival-population changes and
    final state.  Replaying just those memberships avoids retaining a SHA
    accumulator and missing-ID range for every unreported RF tick.
    """
    observed = [index for index, count in enumerate(alive_counts) if count > 0]
    if not observed:
        return []
    retained = [observed[0]]
    previous_count = alive_counts[observed[0]]
    for index in observed[1:-1]:
        if alive_counts[index] != previous_count:
            retained.append(index)
        previous_count = alive_counts[index]
    if retained[-1] != observed[-1]:
        retained.append(observed[-1])

    frozen_ids = list(frozen_particle_ids)
    rank_by_id = {particle_id: rank for rank, particle_id in enumerate(frozen_ids)}
    records = {
        index: {
            "alive_hasher": hashlib.sha256(),
            "missing_hasher": hashlib.sha256(),
            "alive_started": False,
            "missing_started": False,
            "last_rank": -1,
            "alive_seen": 0,
        }
        for index in retained
    }

    def append_id(record: dict[str, object], *, kind: str, particle_id: int) -> None:
        hasher = record[f"{kind}_hasher"]
        started_key = f"{kind}_started"
        if record[started_key]:
            hasher.update(b",")
        else:
            hasher.update(b'{"ordered_particle_ids":[')
            record[started_key] = True
        hasher.update(str(particle_id).encode("ascii"))

    def append_missing_before(record: dict[str, object], rank: int) -> None:
        for missing_rank in range(int(record["last_rank"]) + 1, rank):
            append_id(record, kind="missing", particle_id=frozen_ids[missing_rank])

    with gzip.open(states_path, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            index = int(row["sample_index"]) - 1
            record = records.get(index)
            if record is None:
                continue
            particle_id = int(row["particle_id"])
            rank = rank_by_id.get(particle_id)
            if rank is None or rank <= int(record["last_rank"]):
                raise ContractError("natural state archive identity order differs")
            append_missing_before(record, rank)
            append_id(record, kind="alive", particle_id=particle_id)
            record["last_rank"] = rank
            record["alive_seen"] = int(record["alive_seen"]) + 1

    result: list[dict[str, object]] = []
    for index in retained:
        record = records[index]
        append_missing_before(record, len(frozen_ids))
        for kind in ("alive", "missing"):
            hasher = record[f"{kind}_hasher"]
            if not record[f"{kind}_started"]:
                hasher.update(b'{"ordered_particle_ids":[')
            hasher.update(b"]}")
        alive_count = int(alive_counts[index])
        if int(record["alive_seen"]) != alive_count:
            raise ContractError("natural state archive census differs from TRACE")
        result.append({
            "sample_index": index + 1,
            "instrument_time_us": grid_origin_us + index * grid_step_us,
            "alive_count": alive_count,
            "alive_particle_ids_sha256": record["alive_hasher"].hexdigest(),
            "missing_count": len(frozen_ids) - alive_count,
            "missing_particle_ids_sha256": record["missing_hasher"].hexdigest(),
        })
    return result


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
        "states": run_dir / "results" / STATE_ARCHIVE_FILENAME,
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

    natural_archive = contract.get("schema_version") == 7
    natural_archive_grid: tuple[float, float] | None = None
    raw_sample_times = contract.get("sample_times_us")
    if natural_archive:
        grid = contract.get("rf_time_grid")
        if (
            contract.get("terminate_at_window_end") is not False
            or not isinstance(grid, dict)
            or grid.get("time_grid_profile_id") != "natural_pre_pulse_native_rf_grid_v1"
        ):
            raise ContractError("natural pre-pulse archive contract differs")
        try:
            natural_archive_grid = (float(grid["grid_origin_us"]), float(grid["step_us"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("natural pre-pulse archive grid is invalid") from exc
        if not (
            math.isfinite(natural_archive_grid[0]) and natural_archive_grid[0] >= 0
            and math.isfinite(natural_archive_grid[1]) and natural_archive_grid[1] > 0
        ):
            raise ContractError("natural pre-pulse archive grid is invalid")
        raw_sample_times = []
        sample_times: list[float] = []
    else:
        if not isinstance(raw_sample_times, list) or not raw_sample_times:
            raise ContractError("pre-pulse sample-time grid is empty")
        try:
            sample_times = [float(value) for value in raw_sample_times]
        except (TypeError, ValueError) as exc:
            raise ContractError("pre-pulse sample-time grid is invalid") from exc
        if (
            not all(math.isfinite(value) and value >= 0 for value in sample_times)
            or contract.get("rf_time_grid", {}).get("sample_count") != len(sample_times)
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

    natural_sample_count: list[int] = []
    trace_token_repairs: list[dict[str, object]] = []
    (
        row_count,
        terminal_by_reason,
        sample_census,
        checkpoint_omissions,
    ) = _stream_logs_to_states_csv(
        [path.resolve() for path in stdout_paths],
        frozen_particle_ids=frozen_ids,
        sample_times_us=sample_times,
        natural_archive_grid=natural_archive_grid,
        states_path=states_path,
        natural_sample_count_out=natural_sample_count,
        trace_token_repairs_out=trace_token_repairs,
    )
    receipt_sample_census = _receipt_sample_census(
        sample_census, natural_archive=natural_archive
    )
    states_record: dict[str, object] = {
        "path": f"results/{STATE_ARCHIVE_FILENAME}",
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
        **({} if natural_archive else {"sample_times_us": copy.deepcopy(raw_sample_times)}),
        **({"trace_grid": copy.deepcopy(contract["rf_time_grid"])} if natural_archive else {}),
        "particle_count": particle_count,
        "state_row_count": row_count,
        "native_checkpoint_omissions": checkpoint_omissions,
        "native_trace_token_repairs": trace_token_repairs,
        "terminal_census": {
            reason: {
                "count": len(ids),
                "ordered_particle_ids_sha256": _census_id_sha256(ids),
            }
            for reason, ids in terminal_by_reason.items()
        },
        "sample_census": receipt_sample_census,
        "sample_census_policy": (
            "natural_grid_population_change_points_v1"
            if natural_archive
            else "all_scheduled_samples_v1"
        ),
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
        **({} if natural_archive else {"sample_times_us": copy.deepcopy(raw_sample_times)}),
        **({"trace_grid": copy.deepcopy(contract["rf_time_grid"])} if natural_archive else {}),
        "census": {
            "source_release": particle_count,
            "particle_count": particle_count,
            "sample_count": (
                natural_sample_count[0] if natural_archive else len(sample_census)
            ),
            "receipt_sample_census_count": len(receipt_sample_census),
            "observed_state_rows": row_count,
            "native_checkpoint_omission_count": len(checkpoint_omissions),
            "native_trace_token_repair_count": len(trace_token_repairs),
            "sample_census": receipt_sample_census,
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
