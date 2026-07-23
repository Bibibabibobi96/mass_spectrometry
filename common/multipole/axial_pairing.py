"""Resolve and audit solver-independent paired axial-field particle states."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256


SOURCE_IDENTITY_COLUMNS = (
    "particle_id",
    "event",
    "status",
    "terminal_reason",
    "time_us",
    "elapsed_time_us",
    "rf_phase_rad",
    "axial_z_mm",
    "transverse_x_mm",
    "transverse_y_mm",
    "velocity_axial_m_s",
    "velocity_x_m_s",
    "velocity_y_m_s",
    "kinetic_energy_eV",
    "radial_position_mm",
    "divergence_angle_deg",
)
HANDOFF_METRIC_COLUMNS = (
    "divergence_angle_deg",
    "radial_position_mm",
    "kinetic_energy_eV",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _rows_by_event(path: Path, event: str) -> dict[int, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not {"particle_id", "event"}.issubset(reader.fieldnames):
            raise ValueError(f"{path} is not a canonical particle-state table")
        rows = [row for row in reader if row["event"] == event]
    keyed = {int(row["particle_id"]): row for row in rows}
    if len(keyed) != len(rows):
        raise ValueError(f"{path} contains duplicate {event} particle IDs")
    return keyed


def _source_identity(rows: dict[int, dict[str, str]]) -> dict[int, tuple[str, ...]]:
    for row in rows.values():
        missing = set(SOURCE_IDENTITY_COLUMNS) - set(row)
        if missing:
            raise ValueError(f"source state is missing columns: {', '.join(sorted(missing))}")
    return {
        particle_id: tuple(row[column] for column in SOURCE_IDENTITY_COLUMNS)
        for particle_id, row in rows.items()
    }


def _finite_value(row: dict[str, str], column: str) -> float:
    if column not in row:
        raise ValueError(f"handoff state is missing column: {column}")
    value = float(row[column])
    if not math.isfinite(value):
        raise ValueError(f"handoff state contains non-finite {column}")
    return value


def _rms(values: list[float]) -> float:
    return math.sqrt(math.fsum(value * value for value in values) / len(values))


def _percentile(values: list[float], probability: float) -> float:
    """Return the linearly interpolated percentile used by the paired audit."""
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def _arm_metrics(path: Path, handoff: dict[int, dict[str, str]],
                 source_particles: int) -> dict[str, Any]:
    divergence = [
        _finite_value(row, "divergence_angle_deg") for row in handoff.values()
    ]
    radius = [_finite_value(row, "radial_position_mm") for row in handoff.values()]
    energy = [_finite_value(row, "kinetic_energy_eV") for row in handoff.values()]
    if any(value < 0.0 for value in divergence + radius + energy):
        raise ValueError("handoff divergence, radius and kinetic energy must be non-negative")
    mean_energy = math.fsum(energy) / len(energy)
    energy_variance = (
        math.fsum((value - mean_energy) ** 2 for value in energy) / (len(energy) - 1)
        if len(energy) > 1
        else 0.0
    )
    return {
        "state_sha256": file_sha256(path),
        "source_particles": source_particles,
        "handoff_particles": len(handoff),
        "rms_divergence_angle_deg": _rms(divergence),
        "p95_divergence_angle_deg": _percentile(
            [abs(value) for value in divergence], 0.95
        ),
        "rms_radial_position_mm": _rms(radius),
        "mean_kinetic_energy_eV": mean_energy,
        "kinetic_energy_sample_std_eV": math.sqrt(energy_variance),
    }


def _paired_handoff_rows(
    field_on: dict[int, dict[str, str]],
    field_off: dict[int, dict[str, str]],
) -> list[dict[str, float | int]]:
    paired: list[dict[str, float | int]] = []
    for particle_id in sorted(field_on):
        row: dict[str, float | int] = {"particle_id": particle_id}
        for column in HANDOFF_METRIC_COLUMNS:
            field_on_value = _finite_value(field_on[particle_id], column)
            field_off_value = _finite_value(field_off[particle_id], column)
            row[f"field_on_{column}"] = field_on_value
            row[f"field_off_{column}"] = field_off_value
            row[f"delta_{column}"] = field_on_value - field_off_value
        paired.append(row)
    return paired


def _write_paired_rows(path: Path, rows: list[dict[str, float | int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def resolve_pair(
    contract: dict[str, Any],
    interface: dict[str, Any],
    resolved_geometry: dict[str, Any],
    *,
    selected_axial_contract_name: str,
    source_path: Path,
    source_count: int,
    source_mean_energy_ev: float,
    project_id: str,
) -> dict[str, Any]:
    """Validate the frozen comparison and bind it to one source identity."""
    if contract.get("schema_version") != 1:
        raise ValueError("axial pairing contract schema differs")
    if contract.get("role") != "multipole_axial_field_paired_diagnostic":
        raise ValueError("axial pairing contract role differs")
    if contract.get("project_id") != project_id:
        raise ValueError("axial pairing project differs")
    if contract.get("axial_contract_file") != selected_axial_contract_name:
        raise ValueError("selected axial contract is outside this paired diagnostic")

    source = contract["source"]
    if source.get("operating_point") != "official_100amu_2eV":
        raise ValueError("paired diagnostic must use the official 2 eV source profile")
    if source_count < 1 or int(source["particle_count"]) != source_count:
        raise ValueError("paired diagnostic source count differs")
    energy_bounds = [float(value) for value in source["mean_kinetic_energy_bounds_eV"]]
    if len(energy_bounds) != 2 or not energy_bounds[0] <= source_mean_energy_ev <= energy_bounds[1]:
        raise ValueError("independent 5 eV source profiles are forbidden for axial pairing")

    planes = interface.get("planes", {})
    handoff_mm = float(planes["handoff"]["z_mm"])
    detector_mm = float(planes["acceptance_detector"]["z_mm"])
    resolved_handoff_mm = float(resolved_geometry["derived_geometry_mm"]["exit_plate_z_max"])
    resolved_detector_mm = float(resolved_geometry["derived_geometry_mm"]["detector_z"])
    if not math.isclose(handoff_mm, resolved_handoff_mm, rel_tol=0, abs_tol=1e-12):
        raise ValueError("versioned interface handoff differs from resolved exit plane")
    if not math.isclose(detector_mm, resolved_detector_mm, rel_tol=0, abs_tol=1e-12):
        raise ValueError("versioned detector differs from resolved standalone detector")
    if math.isclose(handoff_mm, detector_mm, rel_tol=0, abs_tol=1e-12):
        raise ValueError("physical handoff and standalone detector must remain distinct")

    arms = contract["arms"]
    expected_arms = {
        "axial_field_on": ("axial_acceleration_rf_on", 1, 1),
        "axial_field_off": ("zero_axial_drop_rf_on", 0, 1),
    }
    actual_arms = {
        arm["arm_id"]: (arm["case_id"], int(arm["axial_scale"]), int(arm["rf_scale"]))
        for arm in arms
    }
    if actual_arms != expected_arms:
        raise ValueError("paired arms must vary only axial_scale while retaining RF")
    if contract.get("independent_5ev_source_allowed") is not False:
        raise ValueError("paired diagnostic must reject an independent 5 eV source")

    return {
        "schema_version": 1,
        "role": "multipole_axial_field_pair_resolved",
        "pair_id": contract["pair_id"],
        "project_id": project_id,
        "source": {
            "operating_point": source["operating_point"],
            "particles": source_count,
            "mean_kinetic_energy_eV": source_mean_energy_ev,
            "particle_source_sha256": file_sha256(source_path),
        },
        "physical_handoff": {
            "event": "handoff",
            "z_mm": handoff_mm,
            "standalone_detector_z_mm": detector_mm,
        },
        "arms": arms,
        "invariants": contract["invariants"],
        "excluded_legacy_run_ids": contract["excluded_legacy_run_ids"],
        "claim_limit": contract["claim_limit"],
    }


def audit_pair(
    resolved_pair: dict[str, Any],
    field_on_state: Path,
    field_off_state: Path,
    paired_output: Path | None = None,
) -> dict[str, Any]:
    """Prove source equality and physical-plane output for both comparison arms."""
    on_sources = _rows_by_event(field_on_state, "source")
    off_sources = _rows_by_event(field_off_state, "source")
    if _source_identity(on_sources) != _source_identity(off_sources):
        raise ValueError("paired arms do not contain identical canonical source states")
    expected_count = int(resolved_pair["source"]["particles"])
    if len(on_sources) != expected_count:
        raise ValueError("paired source population differs from the resolved contract")

    handoff_mm = float(resolved_pair["physical_handoff"]["z_mm"])
    arm_files = {
        "axial_field_on": field_on_state,
        "axial_field_off": field_off_state,
    }
    arm_results: dict[str, Any] = {}
    handoff_by_arm: dict[str, dict[int, dict[str, str]]] = {}
    for arm_id, path in arm_files.items():
        handoff = _rows_by_event(path, "handoff")
        if set(handoff) != set(on_sources):
            raise ValueError(f"{arm_id} does not publish one handoff for every source particle")
        if any(
            row["status"] != "transmitted"
            or not math.isclose(float(row["axial_z_mm"]), handoff_mm, rel_tol=0, abs_tol=1e-9)
            for row in handoff.values()
        ):
            raise ValueError(f"{arm_id} handoff rows are not transmitted states on the physical plane")
        handoff_by_arm[arm_id] = handoff
        arm_results[arm_id] = _arm_metrics(path, handoff, len(on_sources))
    paired = _paired_handoff_rows(
        handoff_by_arm["axial_field_on"],
        handoff_by_arm["axial_field_off"],
    )
    if paired_output is not None:
        _write_paired_rows(paired_output, paired)
    paired_differences = {
        f"field_on_minus_field_off_{column}": {
            "mean": math.fsum(float(row[f"delta_{column}"]) for row in paired) / len(paired),
            "rms": _rms([float(row[f"delta_{column}"]) for row in paired]),
            "p95_absolute": _percentile(
                [abs(float(row[f"delta_{column}"])) for row in paired], 0.95
            ),
        }
        for column in HANDOFF_METRIC_COLUMNS
    }
    return {
        "schema_version": 1,
        "role": "multipole_axial_field_pair_audit",
        "status": "PASS",
        "pair_id": resolved_pair["pair_id"],
        "source_particle_sha256": resolved_pair["source"]["particle_source_sha256"],
        "source_rows_identical": True,
        "particle_ids_identical": True,
        "geometry_rf_solver_invariants_required": True,
        "arms": arm_results,
        "paired_difference": paired_differences,
        "paired_particle_output": str(paired_output.resolve()) if paired_output else None,
        "claim_limit": resolved_pair["claim_limit"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--resolve", action="store_true")
    action.add_argument("--audit", action="store_true")
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--interface", type=Path)
    parser.add_argument("--resolved-geometry", type=Path)
    parser.add_argument("--selected-axial-contract-name")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--source-count", type=int)
    parser.add_argument("--source-mean-energy-ev", type=float)
    parser.add_argument("--project-id")
    parser.add_argument("--resolved-pair", type=Path)
    parser.add_argument("--field-on-state", type=Path)
    parser.add_argument("--field-off-state", type=Path)
    parser.add_argument("--paired-output", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.resolve:
        result = resolve_pair(
            load_json(args.contract),
            load_json(args.interface),
            load_json(args.resolved_geometry),
            selected_axial_contract_name=args.selected_axial_contract_name,
            source_path=args.source,
            source_count=args.source_count,
            source_mean_energy_ev=args.source_mean_energy_ev,
            project_id=args.project_id,
        )
    else:
        result = audit_pair(
            load_json(args.resolved_pair),
            args.field_on_state,
            args.field_off_state,
            args.paired_output,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
