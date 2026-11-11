"""Prepare measured IP-to-MR source cohorts without solver execution."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import shutil
from typing import Any

from msplatform.execution.clock_authority import validate_clock_authority
from msplatform.analysis.particle_census import partition_cohort
from msplatform.contracts.particle_state import (
    ComponentParticleStateTable, load_component_particle_state_csv, write_component_particle_state_csv,
)
from msplatform.contracts.particle_physics import kinetic_energy_ev
from msplatform.io.file_identity import file_sha256
from msplatform.io.strict_json import load_json_object, require_number
from msplatform.contracts.rigid_transform import PhaseSpaceState, RigidTransform
from msplatform.backends.simion.source import project_direct_velocity, render_source_states, render_standard_beams
from msplatform.backends.simion.resources import native_resource_path
from msplatform.workflows.prepared_joint.ip_mr_connection import resolve_ip_mr_connection, validate_component_exit_binding


def _identity(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": file_sha256(path)}


def _bound(record: dict[str, Any], base: Path) -> Path:
    path = Path(record["path"])
    path = path if path.is_absolute() else base / path
    if path.stat().st_size != record["bytes"] or file_sha256(path).lower() != record["sha256"].lower():
        raise ValueError(f"Bound file bytes/SHA-256 differ: {path}")
    return path


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


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
    connection = resolve_ip_mr_connection(load_json_object(outputs["matching_request_resolved"])["composition_plan"])
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


def _project_rows(rows: list[dict[str, Any]], epoch: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    states, beams, mapping = [], [], []
    for ordinal, row in enumerate(rows, 1):
        position = [row[f"position_{axis}_mm"] for axis in "xyz"]
        velocity = [row[f"velocity_{axis}_m_s"] for axis in "xyz"]
        state, beam = project_direct_velocity(particle_id=ordinal, time_us=row["instrument_time_us"]-epoch,
            position_mm=position, velocity_m_s=velocity, energy_ev=row["kinetic_energy_eV"],
            mass_amu=row["mass_amu"], charge_state=row["charge_state"], beam_position_mm=position,
            beam_direction=[value/1000 for value in velocity], weight=row["particle_weight"], color=0)
        states.append(state)
        beams.append(beam)
        mapping.append({"simion_ordinal": ordinal, "particle_id": row["particle_id"],
                        "mass_amu": row["mass_amu"], "charge_state": row["charge_state"],
                        "instrument_time_us": row["instrument_time_us"], "solver_birth_time_us": state["t"],
                        "particle_birth_time_us": row["particle_birth_time_us"],
                        "lineage_birth_time_us": row["lineage_birth_time_us"]})
    return states, beams, mapping


def _write_projection(output_directory: Path, rows: list[dict[str, Any]], epoch: float,
                      clock: dict[str, Any]) -> list[dict[str, Any]]:
    states, beams, mapping = _project_rows(rows, epoch)
    (output_directory / "source.fly2").write_text(render_standard_beams(beams), encoding="utf-8", newline="\n")
    (output_directory / "source_states.lua").write_text(render_source_states(states, significant_digits=17), encoding="utf-8", newline="\n")
    (output_directory / "source_runtime.lua").write_bytes(
        native_resource_path("mrtof_measured_source_runtime.lua").read_bytes())
    projection = [f"return {{epoch_us={epoch!r},clock_epoch_id={json.dumps(clock['clock_epoch_id'])},",
                  f"frame_id={json.dumps(rows[0]['frame_id'])},mapping={{"]
    for item in mapping:
        projection.append("{" + ",".join(f"{key}={value!r}" for key, value in item.items()) + "},")
    projection.append("}}\n")
    (output_directory / "source_projection.lua").write_text("\n".join(projection), encoding="utf-8", newline="\n")
    with (output_directory / "ordinal_source_map.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(mapping[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(mapping)
    return mapping


def materialize_measured_source(handoff_receipt_path: Path, output_directory: Path) -> dict[str, Any]:
    """Publish FLY2, exact-state runtime and ID/clock projection from a bound handoff.

    Raises on changed bytes, source/clock/frame mismatch, invalid census or
    opposite direction. Refuses an existing destination. No solver is called.
    State positions use the MR project/workbench frame, velocities mm/us in
    SIMION companions and m/s in the unchanged canonical CSV.
    """
    if output_directory.exists():
        raise FileExistsError(f"Refusing to overwrite measured source: {output_directory}")
    handoff = load_json_object(handoff_receipt_path)
    paths, exported, table = _validate_import(handoff, handoff_receipt_path.parent)
    rows = table.rows
    clock, clock_path = _validate_states(handoff, paths, exported, table)
    epoch = min(row["instrument_time_us"] for row in rows)
    output_directory.mkdir(parents=True)
    for name in ("component_particle_state", "source_census"):
        shutil.copyfile(paths[name], output_directory / f"{name}.csv")
    shutil.copyfile(clock_path, output_directory / "upstream_clock_authority.json")
    _write(output_directory / "instrument_epoch.json", {"instrument_time_us": epoch})
    projected_clock = dict(clock, authority={"path": "instrument_epoch.json", "field": "instrument_time_us",
                                           "sha256": file_sha256(output_directory / "instrument_epoch.json")})
    _write(output_directory / "clock_authority.json", projected_clock)
    validate_clock_authority(output_directory / "clock_authority.json", output_directory)
    mapping = _write_projection(output_directory, rows, epoch, clock)
    clock_record = exported["inputs"]["inputs/clock_authority.json"]
    report = {"schema_version": 1, "role": "mrtof_measured_component_source", "status": "prepared_only",
              "solver_execution": False, "source_materialization_ready": True, "joint_field_qualified": False,
              "counts": handoff["counts"], "frame_id": rows[0]["frame_id"], "clock_epoch_id": clock["clock_epoch_id"],
              "solver_epoch_instrument_time_us": epoch, "birth_offsets_us": [item["solver_birth_time_us"] for item in mapping],
              "clock_mapping": "instrument_time_us = solver_epoch_instrument_time_us + solver_time_us once",
              "id_mapping": "SIMION 1-based ordinal to original particle_id; event consumers must restore",
              "inputs": {"handoff_receipt": _identity(handoff_receipt_path),
                         "upstream_clock": {"path": str(clock_path.resolve()), "bytes": clock_record["bytes"],
                                            "sha256": clock_record["sha256"].upper()}},
              "outputs": {path.stem: _identity(path) for path in sorted(output_directory.iterdir())},
              "official_support": {"vendor": "SIMION", "target_version": "2020 (8.2)", "review_date": "2026-10-16",
                                   "urls": ["https://simion.com/info/time.html", "https://simion.com/info/fly2_file.html",
                                            "https://simion.com/info/particle_initial_conditions.html"],
                                   "method": "FLY2 per-particle TOB; initialize full Cartesian state; project-owned ID/clock bookkeeping"}}
    _write(output_directory / "source_receipt.json", report)
    return report


def materialize_centroid_probe(source_directory: Path, output_directory: Path) -> dict[str, Any]:
    """Construct a separate unit-weight centroid probe, never select mother ID 1.

    All seven primary coordinates are arithmetic means of the transferred
    cohort. The velocity vector is not rescaled to the mean particle energy.
    Original canonical states and the entire mother census are provenance only.
    """
    receipt_path = source_directory / "source_receipt.json"
    receipt = load_json_object(receipt_path)
    if receipt.get("role") != "mrtof_measured_component_source":
        raise ValueError("Centroid requires an original measured population")
    for record in receipt["outputs"].values():
        _bound({**record, "path": str(source_directory / Path(record["path"]).name)}, source_directory)
    canonical = source_directory / "component_particle_state.csv"
    rows = load_component_particle_state_csv(canonical).rows
    census = _rows(source_directory / "source_census.csv")
    ids = {row["particle_id"] for row in rows}
    if (not rows or ids != {int(row["particle_id"]) for row in census if row["transfer_status"] == "transferred"}
            or len(ids) != len(rows) or len(census) != receipt["counts"]["source"]
            or len({int(row["particle_id"]) for row in census}) != len(census)
            or any(row["transfer_status"] not in {"transferred", "not_transferred"} for row in census)
            or sum(row["transfer_status"] == "not_transferred" for row in census) != receipt["counts"]["not_transferred"]
            or len(rows) != receipt["counts"]["transferred"]):
        raise ValueError("Centroid mother population does not close")
    species = ("mass_amu", "charge_state", "frame_id", "clock_epoch_id", "source_component_id", "target_component_id")
    if any(any(row[key] != rows[0][key] for key in species) for row in rows):
        raise ValueError("Centroid requires one species, frame and canonical clock")
    handoff = load_json_object(_bound(receipt["inputs"]["handoff_receipt"], source_directory))
    if (handoff.get("schema_version") != 3 or handoff.get("role") != "mrtof_ion_processor_handoff_preparation"):
        raise ValueError("Unsupported measured handoff binding")
    connection = handoff.get("connection")
    if not isinstance(connection, dict):
        raise ValueError("Unsupported measured handoff binding")
    if (rows[0]["frame_id"] != receipt["frame_id"] or rows[0]["clock_epoch_id"] != receipt["clock_epoch_id"]
            or rows[0]["source_component_id"] != connection["upstream"]["instance_id"]
            or rows[0]["target_component_id"] != connection["downstream"]["instance_id"]):
        raise ValueError("Centroid measured source frame, clock or component identity differs")
    if any(row["position_z_mm"] != 0 or row["velocity_z_m_s"] >= 0 for row in rows):
        raise ValueError("Centroid requires measured z=0 crossings toward negative z")
    validate_clock_authority(source_directory / "clock_authority.json", source_directory)
    def mean(key: str) -> float:
        return math.fsum(row[key] for row in rows) / len(rows)
    time = mean("instrument_time_us")
    row = dict(rows[0])
    for key in ("instrument_time_us", *[f"position_{axis}_mm" for axis in "xyz"],
                *[f"velocity_{axis}_m_s" for axis in "xyz"]):
        row[key] = mean(key)
    velocity = tuple(row[f"velocity_{axis}_m_s"] for axis in "xyz")
    mass = row["mass_amu"]
    energy = kinetic_energy_ev(mass, *velocity)
    row.update(particle_id=1, state_event="constructed_measured_exit_centroid", parent_particle_id="", generation=0,
               instrument_time_us=time, lineage_birth_time_us=time, particle_birth_time_us=time,
               lineage_age_us=0, particle_age_us=0, last_component_elapsed_time_us=0,
               particle_weight=1, kinetic_energy_eV=energy, phase_rad="", phase_reference_id="")
    if output_directory.exists():
        raise FileExistsError(output_directory)
    output_directory.mkdir(parents=True)
    write_component_particle_state_csv(output_directory / "component_particle_state.csv", [row])
    shutil.copyfile(canonical, output_directory / "mother_component_particle_state.csv")
    shutil.copyfile(source_directory / "source_census.csv", output_directory / "mother_source_census.csv")
    with (output_directory / "source_census.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(census[0]), lineterminator="\n")
        writer.writeheader()
        probe_census = dict(census[0], particle_id=1, transfer_status="transferred")
        for key in ("reason", "loss_reason"):
            if key in probe_census:
                probe_census[key] = ""
        writer.writerow(probe_census)
    clock = load_json_object(source_directory / "clock_authority.json")
    _write(output_directory / "instrument_epoch.json", {"instrument_time_us": time})
    clock["authority"] = {"path": "instrument_epoch.json", "field": "instrument_time_us",
                          "sha256": file_sha256(output_directory / "instrument_epoch.json")}
    _write(output_directory / "clock_authority.json", clock)
    _write_projection(output_directory, [row], time, clock)
    axes = {axis: kinetic_energy_ev(mass, *(velocity[i] if i == j else 0.0 for i in range(3)))
            for j, axis in enumerate("xyz")}
    mean_axes = {axis: math.fsum(kinetic_energy_ev(mass, *(r[f"velocity_{a}_m_s"] if a == axis else 0.0
                for a in "xyz")) for r in rows) / len(rows) for axis in "xyz"}
    result = dict(schema_version=1, role="mrtof_measured_exit_centroid_probe_source", status="prepared_only",
                  solver_execution=False, cohort="constructed_measured_exit_centroid_probe",
                  particle_id_semantics="ID 1 belongs to the independent constructed probe, not mother particle 1",
                  source_projection="measured_exit_centroid", averaging="unit_weight_arithmetic_mean_position_velocity_absolute_time",
                  velocity_rescaled=False, counts=dict(source=1, transferred=1, not_transferred=0),
                  mother_counts=receipt["counts"], mother_particle_ids=sorted(int(r["particle_id"]) for r in census),
                  transferred_mother_particle_ids=sorted(ids), frame_id=row["frame_id"], clock_epoch_id=row["clock_epoch_id"],
                  mass_amu=mass, charge_state=row["charge_state"],
                  solver_epoch_instrument_time_us=time, birth_offsets_us=[0.0],
                  mean_particle_kinetic_energy_eV=mean("kinetic_energy_eV"), centroid_kinetic_energy_eV=energy,
                  mean_particle_axis_energy_eV=mean_axes, centroid_axis_energy_eV=axes,
                  inputs=dict(mother_source_receipt=_identity(receipt_path)),
                  outputs={p.stem: _identity(p) for p in sorted(output_directory.iterdir())})
    _write(output_directory / "source_receipt.json", result)
    return result


def materialize_measured_source_slice(source_directory: Path, output_directory: Path,
                                      ordinal_min: int, ordinal_max: int) -> dict[str, Any]:
    """Project one scheduler ordinal interval without rebasing the instrument epoch."""
    receipt = load_json_object(source_directory / "source_receipt.json")
    if receipt.get("role") not in {"mrtof_measured_component_source", "mrtof_measured_exit_centroid_probe_source"}:
        raise ValueError("Measured source receipt required")
    for record in receipt["outputs"].values():
        _bound({**record, "path": str(source_directory / Path(record["path"]).name)}, source_directory)
    rows = load_component_particle_state_csv(source_directory / "component_particle_state.csv").rows
    if not 1 <= ordinal_min <= ordinal_max <= len(rows):
        raise ValueError("Measured source ordinal interval is invalid")
    if output_directory.exists():
        raise FileExistsError(output_directory)
    shutil.copytree(source_directory, output_directory)
    epoch = receipt["solver_epoch_instrument_time_us"]
    clock = load_json_object(source_directory / "clock_authority.json")
    mapping = _write_projection(output_directory, rows[ordinal_min-1:ordinal_max], epoch, clock)
    result = dict(schema_version=1, role="mrtof_measured_source_batch",
                  ordinal_min=ordinal_min, ordinal_max=ordinal_max, count=len(mapping),
                  original_particle_ids=[item["particle_id"] for item in mapping],
                  solver_epoch_instrument_time_us=epoch,
                  source_receipt=_identity(source_directory / "source_receipt.json"),
                  source_cohort=receipt.get("cohort", "original_measured_population"),
                  outputs={path.stem: _identity(path) for path in sorted(output_directory.iterdir())
                           if path.name != "source_receipt.json"})
    _write(output_directory / "source_receipt.json", result)
    return result
