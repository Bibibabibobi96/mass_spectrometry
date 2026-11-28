"""Validate historical component-exit evidence without executing a source."""
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

from msplatform.analysis.particle_census import partition_cohort
from msplatform.assembly.ip_mr_connection import validate_component_exit_binding
from msplatform.contracts.particle_state import ComponentParticleStateTable, load_component_particle_state_csv
from msplatform.contracts.rigid_transform import PhaseSpaceState, RigidTransform
from msplatform.io.clock_authority import validate_clock_authority
from msplatform.io.file_identity import file_sha256
from msplatform.io.strict_json import load_json_object, require_number


def _historical_connection(plan: dict[str, Any]) -> dict[str, Any]:
    """Check historical project IDs as recorded; this grants no execution alias."""
    recipe, scope = plan['recipe'], plan['scope']
    selected = set(scope['instance_ids'])
    instances = {row['instance_id']: row for row in recipe['instances'] if row['instance_id'] in selected}
    edges = [row for row in recipe['connections'] if row['connection_id'] in scope['connection_ids']]
    if len(selected) != 2 or len(instances) != 2 or len(edges) != 1:
        raise ValueError('historical IP/MR scope requires two instances and one connection')
    edge = edges[0]
    source, target = edge['upstream']['instance_id'], edge['downstream']['instance_id']
    if (source == target or source not in instances or target not in instances
            or instances[source]['project_id'] not in {'ion_processor', 'dual_pressure_rectilinear_ion_processor'}
            or instances[target]['project_id'] not in {'multi_reflection_tof', 'parallel_mirror_dual_stripe_mr_tof'}
            or edge['upstream']['port_id'] != 'extraction_exit' or edge['downstream']['port_id'] != 'accelerator_entry'
            or edge['coupling_mode'] != 'monolithic_joint_solve'):
        raise ValueError('historical IP/MR connection differs from its recorded provider identities')
    return edge




def _bound(record: dict[str, Any], base: Path) -> Path:
    path = Path(record["path"])
    path = path if path.is_absolute() else base / path
    if path.stat().st_size != record["bytes"] or file_sha256(path).lower() != record["sha256"].lower():
        raise ValueError(f"Bound file bytes/SHA-256 differ: {path}")
    return path


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _validate_import(handoff: dict[str, Any], base: Path) -> tuple[
    dict[str, Path], dict[str, Any], ComponentParticleStateTable,
]:
    if (handoff.get("schema_version") != 3
            or handoff.get("role") != "mrtof_ion_processor_handoff_preparation"
            or handoff.get("status") != "prepared_only"
            or handoff.get("solver_execution") is not False):
        raise ValueError("Unsupported measured handoff receipt")
    inputs = {key: _bound(record, base) for key, record in handoff["inputs"].items()}
    outputs = {key: _bound(record, base) for key, record in handoff["outputs"].items()}
    exported = load_json_object(inputs["component_receipt"])
    source_id, target_id = validate_component_exit_binding(exported)
    connection = _historical_connection(load_json_object(outputs["matching_request_resolved"])["composition_plan"])
    if (handoff.get("connection") != connection
            or (source_id, target_id) != (connection["upstream"]["instance_id"], connection["downstream"]["instance_id"])):
        raise ValueError("Measured handoff instances differ from its frozen recipe connection")
    export_base = inputs["component_receipt"].parent
    producer_inputs = {name: _bound(record, export_base) for name, record in exported["inputs"].items()}
    original_states = _bound(exported["outputs"]["component_states"], export_base)
    original_census = _bound(exported["outputs"]["mother_census"], export_base)
    if outputs["source_census"].read_bytes() != original_census.read_bytes():
        raise ValueError("Complete mother census differs from producer")
    transform = RigidTransform.from_contract(handoff["rigid_transform"])
    try:
        imported = load_component_particle_state_csv(outputs["component_particle_state"])
        original_rows = load_component_particle_state_csv(original_states).rows
    except ValueError as error:
        raise ValueError("Imported 6D/identity/clock differs from its bound rigid registration") from error
    imported_rows = imported.rows
    if len(imported_rows) != len(original_rows):
        raise ValueError("Imported measured state count differs from producer")
    for row, original in zip(imported_rows, original_rows):
        state = transform.transform_state(PhaseSpaceState(
            original["frame_id"], tuple(original[f"position_{axis}_mm"] for axis in "xyz"),
            tuple(original[f"velocity_{axis}_m_s"] for axis in "xyz"), original["instrument_time_us"]))
        expected = dict(original, frame_id=transform.to_frame_id)
        for index, axis in enumerate("xyz"):
            expected[f"position_{axis}_mm"] = state.position_mm[index]
            expected[f"velocity_{axis}_m_s"] = state.velocity_m_s[index]
        if row != expected:
            raise ValueError("Imported 6D/identity/clock differs from its bound rigid registration")
    return {**outputs, "component_receipt": inputs["component_receipt"],
            "clock_authority": producer_inputs["inputs/clock_authority.json"],
            "instrument_epoch": producer_inputs["inputs/instrument_epoch.json"]}, exported, imported


def _validate_states(handoff: dict[str, Any], paths: dict[str, Path], exported: dict[str, Any],
                     table: ComponentParticleStateTable) -> tuple[dict[str, Any], Path]:
    rows, validation = table.rows, table.report
    census = _rows(paths["source_census"])
    ids = {row["particle_id"] for row in rows}
    partition = partition_cohort([int(row["particle_id"]) for row in census],
        [(int(row["particle_id"]), row["transfer_status"]) for row in census],
        categories=("transferred", "not_transferred"), relative_weights=None)
    transferred = set(partition["particle_ids_by_category"]["transferred"])
    lost = set(partition["particle_ids_by_category"]["not_transferred"])
    counts = {"source": len(census), "transferred": len(rows), "not_transferred": len(lost)}
    if (ids != transferred
            or counts != handoff["counts"] or counts != exported["counts"]
            or ids != set(exported["transferred_particle_ids"])
            or lost != set(exported.get("not_transferred_particle_ids", exported.get("lost_particle_ids", [])))):
        raise ValueError("Complete mother census and measured IDs do not close")
    states_by_id = {row["particle_id"]: row for row in rows}
    for row in census:
        if row.get("particle_weight"):
            weight = float(row["particle_weight"])
            if not math.isfinite(weight) or weight <= 0:
                raise ValueError("Complete mother census has an invalid weight")
            particle = int(row["particle_id"])
            if particle in states_by_id and weight != states_by_id[particle]["particle_weight"]:
                raise ValueError("Complete mother census and measured state weights differ")
    frame = handoff["rigid_transform"]["to_frame_id"]
    if validation["frame_ids"] != [frame] or validation["clock_epoch_ids"] != [exported["clock_epoch_id"]]:
        raise ValueError("Measured source frame or clock differs from handoff")
    if any(row["source_component_id"] != exported["source_instance_id"] or row["target_component_id"] != exported["target_instance_id"]
           or row["state_event"] != "extraction_exit" or row["velocity_z_m_s"] >= 0 for row in rows):
        raise ValueError("Measured source must be IP extraction_exit toward negative z into MR")
    clock_path = paths["clock_authority"]
    original_clock = load_json_object(clock_path)
    # The component exporter binds its original root and both clock files.
    source_run = Path(exported["source_run"])
    validate_clock_authority(clock_path, source_run)
    epoch_path = paths["instrument_epoch"]
    if (original_clock["clock_epoch_id"] != exported["clock_epoch_id"]
            or (source_run / original_clock["authority"]["path"]).resolve() != epoch_path.resolve()):
        raise ValueError("Original canonical clock authority binding differs")
    epoch = load_json_object(epoch_path)["instrument_time_us"]
    require_number(epoch, "Original clock epoch")
    return original_clock, clock_path



def read_verified_component_exit(handoff_receipt_path: Path) -> dict[str, Any]:
    """Verify historical 6D, census and clock records without producing particles."""
    receipt = load_json_object(handoff_receipt_path)
    paths, exported, table = _validate_import(receipt, handoff_receipt_path.parent)
    clock, clock_path = _validate_states(receipt, paths, exported, table)
    return dict(receipt=receipt, paths=paths, exported=exported, table=table,
                clock=clock, clock_path=clock_path)
