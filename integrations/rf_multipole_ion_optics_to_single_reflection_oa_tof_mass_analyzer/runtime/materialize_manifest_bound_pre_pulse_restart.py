"""Materialize a detector-blind pre-pulse restart from one successful flight."""

from __future__ import annotations

from collections.abc import Sequence
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.verify_run_manifest import record_path, verify_record
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight import (
    COLUMNS as CHECKPOINT_COLUMNS,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import (
    GLOBAL_COLUMNS,
    materialize_pre_pulse_restart,
)


INTEGRATION_ID = (
    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)
RECEIPT_ROLE = (
    "rf_oatof_manifest_bound_pre_pulse_restart_materialization_receipt"
)


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a JSON object")
    return value


def _load_csv(
    path: Path, columns: list[str], label: str,
) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != columns:
                raise ContractError(f"{label} columns differ")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ContractError(f"{label} is not readable CSV") from exc
    if not rows:
        raise ContractError(f"{label} is empty")
    return rows


def _id_sha256(particle_ids: Sequence[int]) -> str:
    payload = json.dumps(
        list(particle_ids), separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _portable(path: Path, workspace_root: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError("pre-pulse restart file escapes the workspace") from exc


def _binding(path: Path, workspace_root: Path) -> dict[str, Any]:
    return {
        "path": _portable(path, workspace_root),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _manifest_record(
    manifest: dict[str, Any],
    *,
    collection: str,
    name: str,
    run_dir: Path,
) -> Path:
    records = manifest.get(collection)
    if collection == "inputs":
        record = records.get(name) if isinstance(records, dict) else None
    else:
        matches = [
            item
            for item in records or []
            if isinstance(item, dict)
            and Path(str(item.get("path", ""))).name == name
        ]
        record = matches[0] if len(matches) == 1 else None
    if not isinstance(record, dict):
        raise ContractError(f"child manifest {collection}.{name} is missing")
    try:
        verify_record(
            f"pre-pulse restart {collection}.{name}", record, base_dir=run_dir
        )
        path = record_path(record, base_dir=run_dir).resolve()
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError(
            f"child manifest {collection}.{name} identity differs"
        ) from exc
    if not path.is_relative_to(run_dir.resolve()):
        raise ContractError(f"child manifest {collection}.{name} is nonlocal")
    return path


def _finite(row: dict[str, str], field: str, label: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError(f"{label} field {field} is not numeric") from exc
    if not math.isfinite(value):
        raise ContractError(f"{label} field {field} is not finite")
    return value


def materialize(
    *,
    child_manifest_path: Path,
    workspace_root: Path,
    state_output_path: Path,
    receipt_output_path: Path,
) -> dict[str, Any]:
    """Write one conditional post-pulse restart without detector postselection."""

    workspace_root = workspace_root.resolve()
    child_manifest_path = child_manifest_path.resolve()
    _portable(child_manifest_path, workspace_root)
    run_dir = child_manifest_path.parent
    manifest = _load_object(child_manifest_path, "child manifest")
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("project") != INTEGRATION_ID
        or manifest.get("mode") not in {
            "simion_single_flight",
            "rf_to_oatof_simion_single_flight",
        }
        or manifest.get("status") != "success"
    ):
        raise ContractError("child manifest identity or status differs")
    try:
        verify_record("pre-pulse restart child run_config", manifest["run_config"])
    except (AssertionError, KeyError, TypeError) as exc:
        raise ContractError("child run_config identity differs") from exc

    summary_path = _manifest_record(
        manifest,
        collection="outputs",
        name="summary.json",
        run_dir=run_dir,
    )
    checkpoints_path = _manifest_record(
        manifest,
        collection="outputs",
        name="single_flight_particle_checkpoints.csv",
        run_dir=run_dir,
    )
    initial_state_path = _manifest_record(
        manifest,
        collection="inputs",
        name="initial_global_state",
        run_dir=run_dir,
    )
    pulse_schedule_path = _manifest_record(
        manifest,
        collection="inputs",
        name="pulse_schedule",
        run_dir=run_dir,
    )
    population_path = _manifest_record(
        manifest,
        collection="inputs",
        name="resolved_population_contract",
        run_dir=run_dir,
    )
    geometry_path = _manifest_record(
        manifest,
        collection="inputs",
        name="oatof_resolved_geometry",
        run_dir=run_dir,
    )

    summary = _load_object(summary_path, "child summary")
    schedule = _load_object(pulse_schedule_path, "pulse schedule")
    population = _load_object(population_path, "resolved population")
    if (
        summary.get("role") != "rf_oatof_simion_single_flight_summary"
        or summary.get("status") != "success"
    ):
        raise ContractError("child summary identity or status differs")
    pulse_time_us = float(schedule.get("pulse_effective_time_us", math.nan))
    if not math.isfinite(pulse_time_us) or pulse_time_us <= 0:
        raise ContractError("pulse schedule effective time is invalid")

    cohort = summary.get("observed_cohort_authority", {}).get(
        "pulse_eligible", {}
    )
    source_ids = cohort.get("ordered_particle_ids")
    if (
        not isinstance(source_ids, list)
        or not source_ids
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for value in source_ids
        )
        or source_ids != sorted(set(source_ids))
        or cohort.get("count") != len(source_ids)
        or cohort.get("ordered_particle_id_sha256") != _id_sha256(source_ids)
    ):
        raise ContractError("pulse-eligible cohort identity differs")

    checkpoint_rows = _load_csv(
        checkpoints_path, CHECKPOINT_COLUMNS, "particle checkpoints"
    )
    eligible_rows = [
        row
        for row in checkpoint_rows
        if row["event"] == "pre_pulse_state"
        and row["pulse_eligibility"] == "eligible"
    ]
    checkpoint_ids = [int(row["particle_id"]) for row in eligible_rows]
    if checkpoint_ids != source_ids:
        raise ContractError("checkpoint pulse-eligible cohort differs from summary")

    initial_rows = _load_csv(
        initial_state_path, GLOBAL_COLUMNS, "initial global state"
    )
    initial_by_id: dict[int, dict[str, str]] = {}
    for row in initial_rows:
        particle_id = int(row["particle_id"])
        if particle_id <= 0 or particle_id in initial_by_id:
            raise ContractError("initial global state particle identity differs")
        initial_by_id[particle_id] = row
    if not set(source_ids).issubset(initial_by_id):
        raise ContractError("pulse-eligible cohort is absent from initial state")

    execution_count = population.get("execution_population", {}).get(
        "particle_count"
    )
    denominator = population.get("denominators", {}).get("population_count")
    if (
        isinstance(execution_count, bool)
        or not isinstance(execution_count, int)
        or execution_count != len(initial_rows)
        or isinstance(denominator, bool)
        or not isinstance(denominator, int)
        or denominator < execution_count
    ):
        raise ContractError("resolved population denominator differs")

    output_rows: list[dict[str, str | int]] = []
    identity_map: list[dict[str, int]] = []
    for restart_id, checkpoint in enumerate(eligible_rows, start=1):
        source_id = int(checkpoint["particle_id"])
        initial = initial_by_id[source_id]
        checkpoint_time = _finite(
            checkpoint, "instrument_time_us", "pre-pulse checkpoint"
        )
        if abs(checkpoint_time - pulse_time_us) > 1e-9:
            raise ContractError("pre-pulse checkpoint clock differs from schedule")
        velocity = tuple(
            1000.0
            * _finite(
                checkpoint,
                f"v{axis}_mm_per_us",
                "pre-pulse checkpoint",
            )
            for axis in "xyz"
        )
        mass = _finite(initial, "mass_amu", "initial global state")
        charge = int(initial["charge_state"])
        if mass <= 0 or charge == 0:
            raise ContractError("pre-pulse checkpoint species is invalid")
        energy = kinetic_energy_ev(mass, *velocity)
        output_rows.append(
            {
                "particle_id": restart_id,
                "instrument_time_us": format(pulse_time_us, ".17g"),
                "mass_amu": format(mass, ".17g"),
                "charge_state": charge,
                **{
                    f"position_{axis}_mm": format(
                        _finite(
                            checkpoint,
                            f"{axis}_mm",
                            "pre-pulse checkpoint",
                        ),
                        ".17g",
                    )
                    for axis in "xyz"
                },
                **{
                    f"velocity_{axis}_m_s": format(value, ".17g")
                    for axis, value in zip("xyz", velocity, strict=True)
                },
                "kinetic_energy_eV": format(energy, ".17g"),
            }
        )
        identity_map.append(
            {
                "restart_particle_id": restart_id,
                "producer_particle_id": source_id,
            }
        )

    state_output_path = state_output_path.resolve()
    receipt_output_path = receipt_output_path.resolve()
    _portable(state_output_path, workspace_root)
    _portable(receipt_output_path, workspace_root)
    if state_output_path == receipt_output_path:
        raise ContractError("restart state and receipt paths must differ")
    state_output_path.parent.mkdir(parents=True, exist_ok=True)
    with state_output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=GLOBAL_COLUMNS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(output_rows)
    materialize_pre_pulse_restart(state_output_path, pulse_time_us)

    restart_ids = list(range(1, len(output_rows) + 1))
    receipt = {
        "schema_version": 1,
        "role": RECEIPT_ROLE,
        "status": "PASS",
        "method": "manifest_bound_pulse_eligible_checkpoint_reindex_v1",
        "producer": {
            "run_id": manifest["run_id"],
            "manifest": _binding(child_manifest_path, workspace_root),
            "summary": _binding(summary_path, workspace_root),
            "checkpoints": _binding(checkpoints_path, workspace_root),
        },
        "authorities": {
            "initial_global_state": _binding(
                initial_state_path, workspace_root
            ),
            "pulse_schedule": _binding(pulse_schedule_path, workspace_root),
            "resolved_population_contract": _binding(
                population_path, workspace_root
            ),
            "resolved_geometry": _binding(geometry_path, workspace_root),
        },
        "selection": {
            "event": "pre_pulse_state",
            "pulse_eligibility": "eligible",
            "selection_uses_detector_outcome": False,
            "detector_results_used": False,
            "producer_population_denominator_count": denominator,
            "producer_execution_population_count": execution_count,
            "producer_particle_count": len(source_ids),
            "producer_ordered_particle_ids_sha256": _id_sha256(source_ids),
            "restart_to_producer_particle_id": identity_map,
            "postselection_prohibited": True,
        },
        "pulse_target_state": {
            **_binding(state_output_path, workspace_root),
            "particle_count": len(output_rows),
            "source_state_epoch": "pulse_effective_time",
            "source_state_locus": {
                "kind": "accelerator_stage1_interior_finite_observed_3d_cloud"
            },
            "coordinate_frame": "oatof_global_cartesian",
            "clock_basis": "canonical_instrument_time_us",
            "clock_authority": "resolved_single_flight_pulse_schedule",
            "pulse_effective_time_us": pulse_time_us,
            "ordered_particle_id_sha256": _id_sha256(restart_ids),
        },
        "reuse_scope": {
            "role": "conditional_post_pulse_transport_initial_state",
            "allowed_variation_axes": [
                "time_integration_profile_id",
                "post_pulse_accelerator_field_profile_id",
            ],
            "pulse_timing_reselection_required": False,
            "upstream_repropagation_required": False,
            "qualification": "DIAGNOSTIC_ONLY",
        },
        "claim_limit": (
            "Detector-blind pulse-eligible conditional state for paired post-pulse "
            "transport only; not a full-population transmission, pulse timing, "
            "Candidate, Formal, or qualification authority."
        ),
    }
    receipt_output_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_output_path.write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return receipt
