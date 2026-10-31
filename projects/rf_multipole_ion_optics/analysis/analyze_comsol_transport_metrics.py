"""Derive finite-3D COMSOL transport metrics from canonical state/event exports."""

from __future__ import annotations

from common.analysis.particle_census import partition_cohort
from projects.rf_multipole_ion_optics.core.interface_geometry import transport_observations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import stdev
from typing import Any


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError(f"CSV is empty: {path}")
    return rows


def _finite(row: dict[str, str], field: str) -> float:
    value = float(row[field])
    if not math.isfinite(value):
        raise ValueError(f"state field is not finite: {field}")
    return value


def _case_metrics(
    state_rows: list[dict[str, str]], event_rows: list[dict[str, str]], case_id: str,
    entrance_port_radius_mm: float | None, exit_port_radius_mm: float | None,
) -> dict[str, Any]:
    source = {row["particle_id"] for row in state_rows if row["event"] == "source"}
    terminal = [row for row in state_rows if row["event"] == "terminal"]
    if not source or {row["particle_id"] for row in terminal} != source:
        raise ValueError(f"terminal state does not close source cohort for {case_id}")
    mother = [int(row["particle_id"]) for row in state_rows if row["event"] == "source"]
    categories = []
    for row in terminal:
        status = row["status"]
        if status not in {"transmitted", "lost", "unknown", "timeout", "alive"}:
            raise ValueError(f"unsupported terminal status for {case_id}: {status}")
        # This RF producer historically defaulted absence to lost/electrode.
        # A legacy literal is not verified physical loss evidence.
        categories.append((int(row["particle_id"]), "transmitted" if status == "transmitted" else "unknown"))
    # Unit-ID projection is used only for counts. Canonical source weights are
    # absent; do not expose its unit-weight sums as physical particle weights.
    partition = partition_cohort(mother, categories, categories=("transmitted", "lost", "unknown"),
                                 relative_weights=None)
    count_census = {key: partition[key] for key in (
        "schema_version", "mother_particle_ids", "mother_count", "particle_ids_by_category", "counts")}
    unknown_reasons: dict[str, list[int]] = {}
    unrecorded_reason_ids = []
    unknown_ids = set(count_census["particle_ids_by_category"]["unknown"])
    for row in terminal:
        pid = int(row["particle_id"])
        if pid in unknown_ids:
            reason = ("loss_evidence_unavailable" if row["status"] == "lost"
                      else row.get("terminal_reason"))
            if reason:
                unknown_reasons.setdefault(reason, []).append(pid)
            else:
                unrecorded_reason_ids.append(pid)
    acceptance_columns = [set(row) & {"acceptance_status", "acceptance_reason"} for row in terminal]
    if any(acceptance_columns) and not all(fields == {"acceptance_status", "acceptance_reason"}
                                           for fields in acceptance_columns):
        raise ValueError(f"partial acceptance facts for {case_id}")
    if not any(acceptance_columns):
        acceptance = dict(recorded=False, reason="not_recorded_by_input_format",
                          rejected_particle_ids=None, rejection_reasons=None)
    else:
        acceptance_ids = {name: [] for name in ("accepted", "rejected", "unresolved")}
        rejection_reasons: dict[str, list[int]] = {}
        for row in terminal:
            status, reason = row["acceptance_status"], row["acceptance_reason"]
            if status not in acceptance_ids or (status == "rejected" and (not reason or reason == "none")):
                raise ValueError(f"invalid acceptance facts for {case_id}")
            if (status == "accepted") != (row["status"] == "transmitted"):
                raise ValueError(f"acceptance and transmitted facts contradict for {case_id}")
            pid = int(row["particle_id"])
            acceptance_ids[status].append(pid)
            if status == "rejected":
                rejection_reasons.setdefault(reason, []).append(pid)
        acceptance = dict(recorded=True, mother_count=len(mother),
                          counts={name: len(ids) for name, ids in acceptance_ids.items()},
                          particle_ids=acceptance_ids, rejected_particle_ids=acceptance_ids["rejected"],
                          rejection_reasons=rejection_reasons)
    transmitted = [row for row in terminal if row["status"] == "transmitted"]
    radii = [_finite(row, "radial_position_mm") for row in transmitted]
    energies = [_finite(row, "kinetic_energy_eV") for row in transmitted]
    max_rods = [_finite(row, "max_rod_radius_mm") for row in terminal]
    rows = [row for row in event_rows if row["case_id"] == case_id]
    if {row["particle_id"] for row in rows} != source:
        raise ValueError(f"event rows do not close source cohort for {case_id}")
    entrance = [float(row["entrance_port_radius_mm"]) for row in rows]
    exit_values = [float(row["exit_port_radius_mm"]) for row in rows]
    return {
        "particles": len(source),
        "transmitted": len(transmitted),
        "transmission_fraction": len(transmitted) / len(source),
        "transmission_fraction_basis": "observed_acceptance_by_end_of_recorded_solution",
        "cohort_census": count_census,
        "reported_terminal_facts": {row["particle_id"]: dict(status=row["status"],
                                     terminal_reason=row.get("terminal_reason")) for row in terminal},
        "loss_evidence": dict(status="unavailable", reason="finite_rf_exports_do_not_record_verified_native_loss_cause",
                              reported_lost_particle_ids=[int(row["particle_id"]) for row in terminal if row["status"] == "lost"]),
        "unknown_terminal_reason_ids": unknown_reasons,
        "unknown_terminal_reason_unrecorded_ids": unrecorded_reason_ids,
        "terminal_fates_resolved": not unknown_ids,
        "acceptance": acceptance,
        "weight_metrics": dict(status="not_computable", reason="complete_source_weights_not_recorded"),
        "entrance_passed": sum(entrance_port_radius_mm is None or value <= entrance_port_radius_mm for value in entrance if math.isfinite(value)),
        "exit_passed": sum(exit_port_radius_mm is None or value <= exit_port_radius_mm for value in exit_values if math.isfinite(value)),
        "exit_rms_radius_mm": math.sqrt(sum(value * value for value in radii) / len(radii)) if radii else None,
        "mean_output_energy_eV": sum(energies) / len(energies) if energies else None,
        "output_energy_standard_deviation_eV": stdev(energies) if len(energies) > 1 else None,
        "maximum_rod_radius_mm": max(max_rods),
    }


def derive(events: list[dict[str, str]], primary_state: list[dict[str, str]], control_state: list[dict[str, str]], resolved: dict[str, Any], numerics: dict[str, Any], *, particle_source: list[dict[str, str]] | None = None, source_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    source_binding: dict[str, Any] = {"status": "not_verified", "reason": "pure caller did not supply frozen particle source"}
    if particle_source is not None:
        mother = [int(row["particle_id"]) for row in particle_source]
        census = partition_cohort(mother, [(pid, "source") for pid in mother],
                                  categories=("source",), relative_weights=None)
        if not mother:
            raise ValueError("frozen particle source must be nonempty")
        expected = set(census["mother_particle_ids"])
        if source_metadata is not None:
            declared = source_metadata["particle_count"]
            if isinstance(declared, bool) or not isinstance(declared, int) or declared != len(mother):
                raise ValueError("actual frozen source mother count differs from its metadata/budget authority")
        for label, rows in (("primary", primary_state), ("control", control_state)):
            actual = [int(row["particle_id"]) for row in rows if row["event"] == "source"]
            if len(actual) != len(mother) or set(actual) != expected:
                raise ValueError(f"{label} state source IDs differ from frozen particle source")
        source_binding = {"status": "verified_ids", "mother_particle_ids": census["mother_particle_ids"],
                          "mother_count": len(mother)}
    topology = resolved["axial_drive"]["topology"]
    geometry = resolved["geometry_mm"]
    observations = transport_observations(resolved)
    ports = geometry["enclosure_layout"]["ports"]
    def port_radius(name):
        section = ports[name]["cross_section"]
        return section["radius_mm"] if section["shape"] == "circle" else None
    if topology == "exit_aperture_plate_potential_step":
        primary_case, control_case = "exit_aperture_plate_acceleration_rf_on", "zero_exit_aperture_plate_drop_rf_on"
    elif topology == "segmented_rod_axial_acceleration":
        primary_case, control_case = "axial_acceleration_rf_on", "zero_axial_drop_rf_on"
    else:
        primary_case, control_case = "finite_3d_rf_on", "zero_rf_control"
    primary = _case_metrics(
        primary_state, events, primary_case, port_radius("mechanical_entrance"),
        port_radius("mechanical_exit"),
    )
    control = _case_metrics(
        control_state, events, control_case, port_radius("mechanical_entrance"),
        port_radius("mechanical_exit"),
    )
    return {
        "schema_version": 1,
        "role": "multipole_finite_3d_transport_metrics",
        "metrics_authority": "python_canonical_particle_state_and_events",
        "source_binding": source_binding,
        "status": "UNQUALIFIED",
        "project_id": resolved["identity"]["project_id"],
        "model_level": "L3",
        "selected_geometry": {
            "rod_radius_ratio": geometry["rod_radius_ratio"],
            "rod_radius_mm": geometry["rod_radius"],
            "rod_center_radius_mm": geometry["rod_center_radius"],
        },
        "voltage_contract": resolved["drive"],
        "interface_geometry_mm": {
            "entrance_port_radius": port_radius("mechanical_entrance"),
            "exit_port_radius": port_radius("mechanical_exit"),
            "release_plane_z": observations["release_plane_z_mm"],
            "census_plane_z": observations["census_plane_z_mm"],
        },
        "primary_case_id": primary_case,
        "control_case_id": control_case,
        "cases": {primary_case: primary, control_case: control},
        "rf_minus_zero_transmission": primary["transmission_fraction"] - control["transmission_fraction"],
        "axial_drive_topology": topology,
        "mesh": {
            "global_auto_level": numerics["mesh"]["global_auto_level"],
            "working_region_hmax_mm": numerics["mesh"]["working_region_maximum_element_size_mm"],
        },
        "claim_limit": "Python-derived canonical-state metrics only; no evidence claim.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--particle-source", type=Path, required=True)
    parser.add_argument("--particle-source-metadata", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--primary-state", type=Path, required=True)
    parser.add_argument("--control-state", type=Path, required=True)
    parser.add_argument("--resolved-design", type=Path, required=True)
    parser.add_argument("--numerics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = derive(
        _rows(args.events), _rows(args.primary_state), _rows(args.control_state),
        json.loads(args.resolved_design.read_text(encoding="utf-8-sig")),
        json.loads(args.numerics.read_text(encoding="utf-8-sig")),
        particle_source=_rows(args.particle_source),
        source_metadata=json.loads(args.particle_source_metadata.read_text(encoding="utf-8-sig")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
