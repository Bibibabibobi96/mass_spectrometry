"""Prepare measured IP exit particles for a later MR SIMION flight, without flying.

Canonical states/census remain byte-identical. SIMION ordinal IDs and local
birth times are projections only; the runtime restores original IDs and the
absolute instrument clock. This is source preparation, not field qualification.
"""
from __future__ import annotations

import csv
import copy
import json
import math
from pathlib import Path
import shutil
from typing import Any

from common.contracts.canonical_clock_authority import validate_clock_authority
from common.contracts.component_particle_state import (
    ComponentParticleStateTable, load_component_particle_state_csv, write_component_particle_state_csv,
)
from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.file_identity import file_sha256
from common.contracts.rigid_transform import PhaseSpaceState, RigidTransform
from common.simion.particle_source import render_source_states, render_standard_beams

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import (
    resolve_ip_mr_connection, validate_component_exit_binding,
)


def author_measured_centroid_prism_target(*, event_field_audit: dict, audit_request: dict,
        controller_projection: dict, source_receipt: dict, trajectory_contract: dict, design_target: dict,
        stripe_1_voltage_v: float, input_records: dict) -> dict:
    """Freeze one source-specific engineering reference using the existing L0 Psi.

    The caller verifies and freezes the parsed JSON documents and input records
    through the existing manifest APIs before calling. This pure function checks
    their internal identities; it performs no I/O. The target is immutable per anchor;
    this authoring inverse is not a P/S controller or an energy acceptance gate.
    """
    from scipy.optimize import brentq
    from common.contracts.component_particle_state import DERIVED_ABSOLUTE_TOLERANCE, DERIVED_RELATIVE_TOLERANCE
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.dual_stripe_l0 import (
        converging_design_potential_delta_v, resolve_converging_prism_target,
    )

    documents = dict(event_field_audit=event_field_audit, audit_request=audit_request,
                     controller_projection=controller_projection, source_receipt=source_receipt,
                     trajectory_contract=trajectory_contract, design_target=design_target)
    if set(input_records) != set(documents):
        raise ValueError("Target authoring requires all six frozen input records")
    for record in input_records.values():
        if (not isinstance(record, dict) or not isinstance(record.get("path"), str)
                or type(record.get("bytes")) is not int or record["bytes"] <= 0
                or not isinstance(record.get("sha256"), str) or len(record["sha256"]) != 64
                or any(c not in "0123456789abcdefABCDEF" for c in record["sha256"])):
            raise ValueError("Frozen input file identity is incomplete")

    def finite(value: Any, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Finite target-authoring value required: " + name)
        return float(value)

    def equal_record(a: dict, b: dict) -> bool:
        return a.get("bytes") == b.get("bytes") and str(a.get("sha256", "")).lower() == str(b.get("sha256", "")).lower()

    def close(a: float, b: float) -> bool:
        # Canonical derived-value consistency, not a trajectory energy tolerance.
        return math.isclose(a, b, rel_tol=DERIVED_RELATIVE_TOLERANCE, abs_tol=DERIVED_ABSOLUTE_TOLERANCE)

    if (event_field_audit.get("schema_version") != 1
            or event_field_audit.get("role") != "mrtof_actual_probe_event_energy_field_audit"
            or event_field_audit.get("status") != "reported"
            or event_field_audit.get("potential_authority") != "actual_materialized_scalar_native_PA__scalar_adapter_raw_sample"
            or audit_request.get("role") != "mrtof_actual_probe_event_field_audit_request" or audit_request.get("schema_version") != 1
            or not equal_record(event_field_audit["inputs"]["request"], input_records["audit_request"])
            or source_receipt.get("role") != "mrtof_measured_exit_centroid_probe_source"
            or source_receipt.get("counts") != dict(source=1, transferred=1, not_transferred=0)
            or design_target.get("role") != "mrtof_measured_centroid_closure_target_authority"):
        raise ValueError("Actual same-binding constructed-probe evidence is required")
    request_inputs = audit_request["inputs"]
    if (not equal_record(request_inputs["source_receipt"], input_records["source_receipt"])
            or not equal_record(request_inputs["canonical_source"], source_receipt["outputs"]["component_particle_state"])):
        raise ValueError("Actual audit names a different canonical probe source")
    if (controller_projection.get("role") != "mrtof_measured_exit_centroid_controller_projection"
            or not equal_record(request_inputs["projection"], input_records["controller_projection"])
            or not equal_record(controller_projection["inputs"]["source_receipt"], input_records["source_receipt"])):
        raise ValueError("Audit names a different controller projection")
    field = controller_projection["field_authority_projection"]
    if (field.get("role") != "mrtof_measured_centroid_live_field_projection"
            or not equal_record(field["binding_record"], request_inputs["candidate_binding"])):
        raise ValueError("Birth and clean evidence must use one frozen actual binding")
    voltages = field["analyzer_electrode_voltages_v"]
    stripe = finite(stripe_1_voltage_v, "S1 anchor")
    if len(voltages) != 20 or voltages[10] != stripe or voltages[11] != stripe or voltages[12:14] != [0, 0]:
        raise ValueError("Target anchor must retain actual S1 and grounded S2")
    mass, charge = finite(source_receipt["mass_amu"], "mass"), finite(source_receipt["charge_state"], "charge")
    if mass <= 0 or charge <= 0 or mass != audit_request["mass_amu"] or charge != audit_request["charge_state"]:
        raise ValueError("Target authoring requires the same positive-ion species")
    rows, points = event_field_audit["samples"], audit_request["points"]
    if (not rows or len({r["sample_id"] for r in rows}) != len(rows)
            or {r["sample_id"] for r in rows} != {p["sample_id"] for p in points} or len(points) != len(rows)):
        raise ValueError("Actual event-field population does not close")
    requested = {p["sample_id"]: p for p in points}
    energies = {}
    for row in rows:
        point = requested[row["sample_id"]]
        for key in ("event", "instrument_time_us", "position_mm", "velocity_m_s", "kinetic_energy_per_charge_ev"):
            if row[key] != point[key]:
                raise ValueError("Audit event differs from its frozen actual query")
        position, velocity = row["position_mm"], row["velocity_m_s"]
        if len(position) != 3 or len(velocity) != 3:
            raise ValueError("Complete Cartesian state required")
        for value in [*position, *velocity, row["instrument_time_us"]]:
            finite(value, "actual event state")
        axes = [kinetic_energy_ev(mass, *(velocity[i] if i == a else 0 for i in range(3)))/charge for a in range(3)]
        kinetic = finite(row["kinetic_energy_per_charge_ev"], "event K/q")
        phi = finite(row.get("phi_v"), "actual electrostatic phi")
        if not close(sum(axes), kinetic) or not close(kinetic+phi, finite(row["k_over_q_plus_phi_v"], "event H/q")):
            raise ValueError("Actual K/velocity/phi energy ledger is inconsistent")
        energies[row["sample_id"]] = axes
    births = [r for r in rows if r["sample_id"] == "source_centroid" and r["event"] == "source_centroid"]
    if len(births) != 1:
        raise ValueError("Unique canonical centroid birth required")
    birth = births[0]
    birth_k = finite(source_receipt["centroid_kinetic_energy_eV"], "canonical centroid K")/charge
    h = birth_k+birth["phi_v"]
    if (not close(birth_k, birth["kinetic_energy_per_charge_ev"])
            or birth["instrument_time_us"] != source_receipt["solver_epoch_instrument_time_us"]
            or not close(h, finite(event_field_audit["source_centroid_h_over_q_v"], "source H/q"))):
        raise ValueError("Actual birth ledger differs from canonical centroid")
    reference = design_target["prism_handoff_target"]
    contract = copy.deepcopy(trajectory_contract)
    all_authored = ("mode", "axial_energy_per_charge_v", "mirror_axial_width_w_mm",
        "slow_energy_reference_per_charge_v", "total_energy_reference_per_charge_v", "clean_reference_slow_energy_per_charge_v")
    contract["prism_transport"]["handoff_target"] = {key:reference[key] for key in all_authored}
    bridges = contract["dual_stripe"]["beam_slot_y_bridges_mm"]
    geometry = dict(mirror_convergence_transform=contract["mirror"]["convergence_transform"], metadata=dict(
        ion_foil_slot_bridge_from_min_y_mm=bridges["from_min_y_mm"], ion_foil_slot_bridge_from_max_y_mm=bridges["from_max_y_mm"]))
    if resolve_converging_prism_target(contract, geometry) != reference:
        raise ValueError("MR design model geometry or tolerance differs from its frozen contract")
    lo, hi = reference["clean_y_interval_mm"]
    clean_rows = [r for r in rows if r["event"] == "central_plane_directional"
        and r["instrument_time_us"] > birth["instrument_time_us"] and r["position_mm"][2] == 0
        and lo < r["position_mm"][1] < hi and r["velocity_m_s"][1] > 0 and r["velocity_m_s"][2] < 0]
    if not clean_rows:
        raise ValueError("First forward clean negative-z reference was not observed")
    clean = min(clean_rows, key=lambda r: r["instrument_time_us"])
    ex = energies[clean["sample_id"]][0]
    available = finite(h-clean["phi_v"]-ex, "available YZ energy")
    ws = finite(reference["slow_energy_reference_per_charge_v"], "MR design Ws")
    if available <= 0 or ws <= 0:
        raise ValueError("Positive available YZ energy and MR design action required")

    def residual(energy: float) -> float:
        target = dict(reference, axial_energy_per_charge_v=energy)
        return available-energy+converging_design_potential_delta_v(target, stripe, clean["position_mm"][1])-ws

    # Physical open interval; no arbitrary search range or energy acceptance.
    lower = math.nextafter(max(0.0, stripe), math.inf)
    upper = math.nextafter(available, 0.0)
    if lower >= upper or not math.isfinite(residual(lower)) or not math.isfinite(residual(upper)) or residual(lower)*residual(upper) > 0:
        raise ValueError("No bracketed physical fast/slow partition in the existing L0 model")
    fast = float(brentq(residual, lower, upper))
    slow = available-fast
    if not 0 < fast < available or not slow > 0 or not close(slow+converging_design_potential_delta_v(
            dict(reference, axial_energy_per_charge_v=fast), stripe, clean["position_mm"][1]), ws):
        raise ValueError("No physical self-consistent target partition")
    authored_keys = ("mode", "axial_energy_per_charge_v", "mirror_axial_width_w_mm", "slow_energy_reference_per_charge_v")
    contract["prism_transport"]["handoff_target"] = {k: reference[k] for k in authored_keys}
    contract["prism_transport"]["handoff_target"].update(axial_energy_per_charge_v=fast,
        total_energy_reference_per_charge_v=available, clean_reference_slow_energy_per_charge_v=slow)
    resolved = resolve_converging_prism_target(contract, geometry)
    target = copy.deepcopy(design_target)
    target["prism_handoff_target"] = resolved
    target["inputs"].update(interface_energy_field_audit=copy.deepcopy(input_records["event_field_audit"]),
                             trajectory_contract=copy.deepcopy(input_records["trajectory_contract"]))
    target["source_energy_ledger"] = dict(mean_particle_kinetic_energy_ev_per_q=finite(source_receipt["mean_particle_kinetic_energy_eV"],"mother mean K")/charge,
        kinetic_energy_of_mean_velocity_ev_per_q=birth_k, centroid_joint_phi_v=birth["phi_v"], centroid_joint_hamiltonian_ev_per_q=h)
    target["qualification"] = "immutable_anchor_source_specific_L0_engineering_target__not_3D_action_or_N100_energy_acceptance"
    return dict(schema_version=1, role="mrtof_measured_centroid_prism_target_authoring", inputs=copy.deepcopy(input_records),
        target_authority=target, authoring_ledger=dict(binding=copy.deepcopy(request_inputs["candidate_binding"]),
            birth_sample_id=birth["sample_id"], clean_sample_id=clean["sample_id"], clean_position_mm=copy.deepcopy(clean["position_mm"]),
            stripe_1_anchor_voltage_v=stripe, source_h_over_q_v=h, actual_clean_phi_v=clean["phi_v"], actual_clean_ex_ev_per_q=ex,
            available_clean_yz_energy_ev_per_q=available, observed_clean_ky_ev_per_q=energies[clean["sample_id"]][1],
            observed_clean_delta_h_v=clean["k_over_q_plus_phi_v"]-h, fast_reference_ev_per_q=fast, slow_reference_ev_per_q=slow,
            self_consistency_residual_ev_per_q=residual(fast), clean_target_angle_degrees=math.degrees(math.atan2(math.sqrt(slow),math.sqrt(fast))),
            model_total_energy_semantics="YZ available energy after subtracting physical phi and Ex; not full 3D Hamiltonian",
            p2_angle_semantics="retained historical engineering diagnostic; clean angle is not a P2-plane target",
            source_velocity_rescaled=False, target_updates="new explicit version and cleared columns; never move within one anchor"),
        physical_matching_qualified=False, energy_acceptance="not_declared")

# Official SIMION 8.0/8.1 FLY2 and initialize APIs; also present in SIMION 2020
# docs/simion.chm (fly2_file.html, time.html, particle_initial_conditions.html).
# Reviewed 2026-10-16: https://simion.com/info/time.html and /fly2_file.html.
# TOF is solver time from zero, not time since each particle's TOB.
RUNTIME_LUA = r'''-- Pure loader module: compose with the downstream workbench program.
local M = {}
function M.load(directory)
  local states = assert(loadfile(directory..'/source_states.lua'))()
  local point = assert(loadfile(directory..'/source_projection.lua'))()
  local runtime = {}
  local function source(ordinal)
    assert(type(ordinal)=='number' and ordinal%1==0, 'invalid SIMION ordinal')
    return assert(point.mapping[ordinal], 'unmapped SIMION ordinal')
  end
  function runtime.source_id(ordinal) return source(ordinal).particle_id end
  function runtime.instrument_time_us(solver_time_us)
    assert(type(solver_time_us)=='number' and solver_time_us>=0 and solver_time_us<math.huge,
      'invalid solver clock')
    return point.epoch_us + solver_time_us
  end
  function runtime.initialize(ordinal)
    -- Pure data boundary: ordinary loadfile does not inherit the workbench
    -- reserved-variable environment (SIMION manual L-31 / lua_scope.html).
    local mapping = source(ordinal)
    local state = assert(states[ordinal], 'missing measured source state')
    return {mass=mapping.mass_amu, charge=mapping.charge_state, t=state.t,
      x=state.x, y=state.y, z=state.z, vx=state.vx, vy=state.vy, vz=state.vz}
  end
  function runtime.restore_event_state(ordinal, solver_time_us, x,y,z,vx,vy,vz)
    local mapping = source(ordinal)
    assert(solver_time_us >= states[ordinal].t, 'event precedes measured handoff')
    local absolute_time = runtime.instrument_time_us(solver_time_us)
    return {particle_id=mapping.particle_id, clock_epoch_id=point.clock_epoch_id,
      instrument_time_us=absolute_time, frame_id=point.frame_id,
      particle_birth_time_us=mapping.particle_birth_time_us,
      lineage_birth_time_us=mapping.lineage_birth_time_us,
      particle_age_us=absolute_time-mapping.particle_birth_time_us,
      lineage_age_us=absolute_time-mapping.lineage_birth_time_us,
      last_component_elapsed_time_us=solver_time_us-states[ordinal].t,
      position_x_mm=x, position_y_mm=y, position_z_mm=z,
      velocity_x_m_s=vx*1000, velocity_y_m_s=vy*1000, velocity_z_m_s=vz*1000}
  end
  runtime.particle_count = #point.mapping
  runtime.clock_epoch_id, runtime.epoch_us = point.clock_epoch_id, point.epoch_us
  return runtime
end
return M
'''


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


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
    exported = _read(inputs["component_receipt"])
    source_id, target_id = validate_component_exit_binding(exported)
    connection = resolve_ip_mr_connection(_read(outputs["matching_request_resolved"])["composition_plan"])
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
    transferred = {int(row["particle_id"]) for row in census if row["transfer_status"] == "transferred"}
    lost = {int(row["particle_id"]) for row in census if row["transfer_status"] == "not_transferred"}
    counts = {"source": len(census), "transferred": len(rows), "not_transferred": len(lost)}
    if (len({row["particle_id"] for row in census}) != len(census)
            or ids != transferred or ids & lost or len(ids | lost) != len(census)
            or counts != handoff["counts"] or counts != exported["counts"]
            or ids != set(exported["transferred_particle_ids"]) or lost != set(exported["lost_particle_ids"])):
        raise ValueError("Complete mother census and measured IDs do not close")
    frame = handoff["rigid_transform"]["to_frame_id"]
    if validation["frame_ids"] != [frame] or validation["clock_epoch_ids"] != [exported["clock_epoch_id"]]:
        raise ValueError("Measured source frame or clock differs from handoff")
    if any(row["source_component_id"] != exported["source_instance_id"] or row["target_component_id"] != exported["target_instance_id"]
           or row["state_event"] != "extraction_exit" or row["velocity_z_m_s"] >= 0 for row in rows):
        raise ValueError("Measured source must be IP extraction_exit toward negative z into MR")
    clock_path = paths["clock_authority"]
    original_clock = _read(clock_path)
    # The component exporter binds its original root and both clock files.
    source_run = Path(exported["source_run"])
    validate_clock_authority(clock_path, source_run)
    epoch_path = paths["instrument_epoch"]
    if (original_clock["clock_epoch_id"] != exported["clock_epoch_id"]
            or (source_run / original_clock["authority"]["path"]).resolve() != epoch_path.resolve()):
        raise ValueError("Original canonical clock authority binding differs")
    epoch = _read(epoch_path)["instrument_time_us"]
    if not isinstance(epoch, (int, float)) or not math.isfinite(epoch):
        raise ValueError("Original clock epoch must be finite")
    return original_clock, clock_path


def _project_rows(rows: list[dict[str, Any]], epoch: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    states, beams, mapping = [], [], []
    for ordinal, row in enumerate(rows, 1):
        state = {axis: row[f"position_{axis}_mm"] for axis in "xyz"}
        state.update({f"v{axis}": row[f"velocity_{axis}_m_s"] / 1000 for axis in "xyz"})
        state.update(particle_id=ordinal, t=row["instrument_time_us"]-epoch, ke=row["kinetic_energy_eV"])
        states.append(state)
        beams.append({**state, "tob": state["t"], "mass": row["mass_amu"], "charge": row["charge_state"],
                      "direction": [state[f"v{axis}"] for axis in "xyz"], "cwf": row["particle_weight"], "color": 0})
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
    (output_directory / "source_runtime.lua").write_text(RUNTIME_LUA, encoding="utf-8", newline="\n")
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
    handoff = _read(handoff_receipt_path)
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
    receipt = _read(receipt_path)
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
    handoff = _read(_bound(receipt["inputs"]["handoff_receipt"], source_directory))
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
    clock = _read(source_directory / "clock_authority.json")
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
    receipt = _read(source_directory / "source_receipt.json")
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
    clock = _read(source_directory / "clock_authority.json")
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
