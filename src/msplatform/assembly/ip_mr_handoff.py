"""Prepare measured Ion Processor states and an MR-owned matching request.

This module performs no propagation or vendor operation. Its assets retain the
upstream clock and measured velocities; they are not an ideal bunch receipt or
an executable replacement for the existing OA-specific MR flight adapter.
"""
from __future__ import annotations

from importlib.resources import files
import csv
import json
import shutil
import statistics
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from msplatform.assembly.ip_mr_connection import (
    validate_component_exit_binding,
    resolve_ip_mr_transform as _resolve_ip_mr_transform,
)
from msplatform.assembly import ip_mr_connection
from msplatform.analysis.particle_census import partition_cohort
from msplatform.contracts.particle_state import (
    load_component_particle_state_csv,
    write_component_particle_state_csv,
)
from msplatform.contracts.particle_physics import kinetic_energy_ev
from msplatform.contracts.rigid_transform import PhaseSpaceState, RigidTransform
from msplatform.io.file_identity import file_sha256
from msplatform.io.strict_json import load_json_object, require_number










def _read(path: Path) -> dict[str, Any]:
    return load_json_object(path)


def _identity(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "sha256": file_sha256(path), "bytes": path.stat().st_size}


def _bound_file(identity: dict[str, Any], relative_to: Path) -> Path:
    path = Path(identity["path"])
    if not path.is_absolute():
        path = relative_to / path
    if file_sha256(path).lower() != identity["sha256"].lower():
        raise ValueError(f"Bound source SHA-256 differs: {path}")
    if path.stat().st_size != identity["bytes"]:
        raise ValueError(f"Bound source byte count differs: {path}")
    return path


def _finite(value: Any, label: str) -> float:
    return require_number(value, label)


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _energy_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for axis in "xyz":
        values = [kinetic_energy_ev(row["mass_amu"], *(
            row[f"velocity_{other}_m_s"] if other == axis else 0.0
            for other in "xyz"
        )) / abs(row["charge_state"]) for row in rows]
        result[axis] = {"mean": statistics.fmean(values), "minimum": min(values), "maximum": max(values)}
    return {"unit": "eV_per_abs_charge_state", "directional_energy": result}











def matching_request_schema_path() -> Path:
    return Path(str(files("msplatform.contracts").joinpath(
        "schemas/ion_processor_matching_request.schema.json"))).resolve(strict=True)


def resolve_matching_request(
    component_receipt: Path, trajectory_contract: Path,
    accelerator_provider_receipt: Path, request_path: Path, plan_path: Path, *,
    composition_plan: dict[str, Any], connection: dict[str, Any],
) -> dict[str, Any]:
    """Read and validate matching science once, before geometry or state output."""
    if ip_mr_connection.resolve_ip_mr_connection(composition_plan) != connection:
        raise ValueError("Matching connection differs from the frozen composition scope")
    request = _read(request_path)
    schema_path = matching_request_schema_path()
    Draft202012Validator(_read(schema_path)).validate(request)
    exported = _read(component_receipt)
    validate_component_exit_binding(exported)
    bound_inputs = {name: _bound_file(identity, component_receipt.parent)
                    for name, identity in exported["inputs"].items()}
    trajectory = _read(trajectory_contract)
    provider = _read(accelerator_provider_receipt)
    target_energy = _finite(provider["mrtof_projection"]["target_axial_energy_per_charge_v"], "MR axial target")
    if target_energy <= 0:
        raise ValueError("MR axial energy target must be positive")
    anchor = _finite(trajectory["accelerator"]["focus_y_anchor"]["project_y_mm"], "MR y anchor")
    frame = trajectory["coordinate_system"]["frame_id"]
    surface = exported["observation_surface"]
    if surface.get("normal") != [0, 0, -1]:
        raise ValueError("Observation surface normal must point toward negative z")
    source_csv = _bound_file(exported["outputs"]["component_states"], component_receipt.parent)
    census_csv = _bound_file(exported["outputs"]["mother_census"], component_receipt.parent)
    table = load_component_particle_state_csv(source_csv)
    rows, validation = table.rows, table.report
    if validation["frame_ids"] != [exported["frame_id"]] or validation["clock_epoch_ids"] != [exported["clock_epoch_id"]]:
        raise ValueError("Component source frame or clock differs from its receipt")
    with census_csv.open(encoding="utf-8-sig", newline="") as handle:
        census = list(csv.DictReader(handle))
    ids = sorted(row["particle_id"] for row in rows)
    census_ids = [int(row["particle_id"]) for row in census]
    partition = partition_cohort(census_ids, [(int(row["particle_id"]), row["transfer_status"]) for row in census],
        categories=("transferred", "not_transferred"), relative_weights=None)
    lost_ids = exported.get("not_transferred_particle_ids", exported.get("lost_particle_ids", []))
    counts = exported["counts"]
    if (ids != sorted(exported["transferred_particle_ids"])
            or len(ids) != counts["transferred"]
            or len(lost_ids) != counts["not_transferred"]
            or len(census_ids) != counts["source"]
            or set(ids) & set(lost_ids)
            or set(census_ids) != set(ids) | set(lost_ids)):
        raise ValueError("Exported IDs and complete source census do not close")
    census_transferred = set(partition["particle_ids_by_category"]["transferred"])
    census_lost = set(partition["particle_ids_by_category"]["not_transferred"])
    if census_transferred != set(ids) or census_lost != set(lost_ids):
        raise ValueError("Source census transfer statuses differ from the transferred and lost IDs")
    if (exported["source_instance_id"] != connection["upstream"]["instance_id"]
            or exported["target_instance_id"] != connection["downstream"]["instance_id"]
            or any(row["source_component_id"] != exported["source_instance_id"]
                   or row["target_component_id"] != exported["target_instance_id"]
                   or row["state_event"] != "extraction_exit" for row in rows)):
        raise ValueError("Measured component instances differ from the frozen connection")
    if any(row["velocity_z_m_s"] >= 0 for row in rows):
        raise ValueError("Measured source must travel toward negative z")
    resolved = {
        "schema_version": 2, "role": "mrtof_ion_processor_matching_request_resolved",
        "status": "prepared_only", "preparation_complete": True,
        "solver_ready": False, "solver_execution": False,
        "target": {"axial_energy_per_charge_v": target_energy,
                   "energy_definition": "exit_axial_kinetic_energy_per_charge",
                   "energy_basis": "/mrtof_projection/target_axial_energy_per_charge_v",
                   "anchor_y_mm": anchor, "frame_id": frame,
                   "anchor_basis": "/accelerator/focus_y_anchor/project_y_mm"},
        "mirror_nominal_energy_reference": trajectory.get("accelerator_energy_contract"),
        "current_measured_baseline": _energy_statistics(rows),
        "composition_plan": composition_plan, "design_variables": request["design_variables"],
        "policies": request["policies"], "requirements": request["requirements"],
        "old_oa_field_valid_for_replacement": False,
        "known_gaps": [
            "The provider seed is resolved; physical energy, geometry and timing matching remain unqualified.",
            "The observation plane is not qualified as a grounded aperture, field-free plane or time focus.",
            "Prepared joint flight consumes measured states; joint fields, phase-space matching and time focus remain unqualified.",
            "Replace the old OA and rebuild affected parent/local field boundaries before a joint solve.",
            "Source RF phase is preserved provenance, not an MR pulse schedule.",
        ],
    }
    model_path = bound_inputs["inputs/resolved_model.json"]
    source_model = _read(model_path)
    source_pose = RigidTransform.from_contract(source_model["coordinate_transform"])
    if source_pose.to_frame_id != exported["frame_id"]:
        raise ValueError("exported state frame differs from its frozen provider coordinate transform")
    return dict(resolved=resolved, connection=connection, rows=rows, exported=exported, census_csv=census_csv,
                source_pose=source_pose, source_model=source_model, source_model_path=model_path, inputs={name: _identity(path) for name, path in (
                    ("component_receipt", component_receipt), ("trajectory_contract", trajectory_contract),
                    ("accelerator_provider_receipt", accelerator_provider_receipt), ("request", request_path),
                    ("composition_plan", plan_path))})


def prepare_handoff(matching: dict[str, Any], composition_plan: dict[str, Any],
                    output_directory: Path) -> dict[str, Any]:
    """Project measured states once using the checked native component pose."""
    if output_directory.exists():
        raise ValueError(f"Refusing to overwrite preparation directory: {output_directory}")
    if composition_plan != matching["resolved"]["composition_plan"]:
        raise ValueError("mechanical composition differs from the frozen actual scope")
    native_pose = _resolve_ip_mr_transform(composition_plan, matching["connection"])
    if native_pose.to_frame_id != matching["resolved"]["target"]["frame_id"]:
        raise ValueError("MR local source frame differs from the frozen trajectory frame")
    transform = matching["source_pose"].inverse().then(native_pose)
    transformed = []
    for row in matching["rows"]:
        state = transform.transform_state(PhaseSpaceState(
            row["frame_id"], tuple(row[f"position_{axis}_mm"] for axis in "xyz"),
            tuple(row[f"velocity_{axis}_m_s"] for axis in "xyz"), row["instrument_time_us"]))
        changed = dict(row, frame_id=state.frame_id)
        for index, axis in enumerate("xyz"):
            changed[f"position_{axis}_mm"] = state.position_mm[index]
            changed[f"velocity_{axis}_m_s"] = state.velocity_m_s[index]
        transformed.append(changed)
    resolved = dict(matching["resolved"], rigid_transform=transform.to_contract())
    output_directory.mkdir(parents=True, exist_ok=False)
    output_csv = output_directory / "component_particle_state.csv"
    output_validation = write_component_particle_state_csv(output_csv, transformed)
    output_census = output_directory / "source_census.csv"
    shutil.copyfile(matching["census_csv"], output_census)
    resolved_path = output_directory / "matching_request_resolved.json"
    _write(resolved_path, resolved)
    report = {
        "schema_version": 3, "role": "mrtof_ion_processor_handoff_preparation",
        "status": "prepared_only", "preparation_complete": True,
        "solver_ready": False, "solver_execution": False,
        "qualification": "measured_state_import_and_target_request_only",
        "inputs": matching["inputs"],
        "outputs": {name: _identity(path) for name, path in (
            ("component_particle_state", output_csv), ("source_census", output_census),
            ("matching_request_resolved", resolved_path))},
        "counts": matching["exported"]["counts"], "rigid_transform": transform.to_contract(),
        "connection": matching["connection"],
        "validation": output_validation,
        "preserved": ["particle_id", "kinetic_energy", "absolute_instrument_time", "clock_epoch",
                      "lineage", "source_phase", "all_mother_census_bytes"],
    }
    _write(output_directory / "handoff_receipt.json", report)
    return report
