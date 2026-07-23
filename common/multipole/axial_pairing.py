"""Resolve and audit paired axial-field SIMION source states."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _rows_by_event(path: Path, event: str) -> dict[int, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = [row for row in csv.DictReader(stream) if row["event"] == event]
    keyed = {int(row["particle_id"]): row for row in rows}
    if len(keyed) != len(rows):
        raise ValueError(f"{path} contains duplicate {event} particle IDs")
    return keyed


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
    if int(source["particle_count"]) != source_count:
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
) -> dict[str, Any]:
    """Prove source equality and physical-plane output for both comparison arms."""
    on_sources = _rows_by_event(field_on_state, "source")
    off_sources = _rows_by_event(field_off_state, "source")
    if on_sources != off_sources:
        raise ValueError("paired arms do not contain byte-equivalent source states")
    expected_count = int(resolved_pair["source"]["particles"])
    if len(on_sources) != expected_count:
        raise ValueError("paired source population differs from the resolved contract")

    handoff_mm = float(resolved_pair["physical_handoff"]["z_mm"])
    arm_files = {
        "axial_field_on": field_on_state,
        "axial_field_off": field_off_state,
    }
    arm_results: dict[str, Any] = {}
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
        arm_results[arm_id] = {
            "state_sha256": file_sha256(path),
            "source_particles": len(on_sources),
            "handoff_particles": len(handoff),
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
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
