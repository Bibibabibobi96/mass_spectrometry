"""Prepare measured Ion Processor states and an MR-owned matching request.

This module performs no propagation or vendor operation. Its assets retain the
upstream clock and measured velocities; they are not an ideal bunch receipt or
an executable replacement for the existing OA-specific MR flight adapter.
"""
from __future__ import annotations

import csv
import json
import math
import shutil
import statistics
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from common.contracts.component_particle_state import (
    load_component_particle_state_csv,
    write_component_particle_state_csv,
)
from common.contracts.file_identity import file_sha256
from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.rigid_transform import PhaseSpaceState, RigidTransform, relative_transform


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


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
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return float(value)


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


def _distribution(values: list[float]) -> dict[str, Any]:
    return {"count": len(values), "mean": statistics.fmean(values),
            "population_sigma": statistics.pstdev(values),
            "minimum": min(values), "maximum": max(values)}


def _exit_distributions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    energy, velocity = {}, {}
    for axis in "xyz":
        velocity[axis] = _distribution([row[f"velocity_{axis}_m_s"] for row in rows])
        values = [kinetic_energy_ev(row["mass_amu"], *(
            row[f"velocity_{other}_m_s"] if other == axis else 0.0 for other in "xyz"
        )) / abs(row["charge_state"]) for row in rows]
        energy[axis] = _distribution(values)
    total = [kinetic_energy_ev(row["mass_amu"], *(
        row[f"velocity_{axis}_m_s"] for axis in "xyz"
    )) / abs(row["charge_state"]) for row in rows]
    return {"statistic_basis": "unweighted_recorded_exit_particles_no_recentring_or_filtering",
            "energy_unit": "eV_per_abs_charge_state", "velocity_unit": "m_s",
            "directional_energy": energy, "total_energy": _distribution(total), "velocity": velocity}


def _reference_exit(reference_mr_run: Path) -> tuple[float, dict[str, Any], dict[str, Any]]:
    # Reuse the existing exact manifest projection; no PA payload is consumed.
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepare_accelerator_interface import verified_reference
    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import parse_events
    provider_path = verified_reference(reference_mr_run, "simion/accelerator_provider_runtime_receipt.json")
    source_path = verified_reference(reference_mr_run, "simion/bunch_source_receipt.json")
    log_path = verified_reference(reference_mr_run, "logs/native_two_prism_flight.log")
    provider, source = _read(provider_path), _read(source_path)
    state_path = _bound_file(source["state_table"], source_path.parent)
    with state_path.open(encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    by_id = {int(row["particle_id"]): row for row in source_rows}
    expected = set(source["expected_particle_ids"])
    if len(by_id) != len(source_rows) or set(by_id) != expected or len(expected) != source["particle_count"]:
        raise ValueError("Reference OA complete source IDs do not close")
    exits = [event for event in parse_events(log_path.read_text(encoding="utf-8-sig"))
             if event["kind"] == "accelerator_geometric_exit"]
    if len(exits) != len(expected) or {int(event["ion"]) for event in exits} != expected:
        raise ValueError("Reference OA geometric-exit IDs do not close")
    rows = []
    for event in exits:
        particle = by_id[int(event["ion"])]
        if event["z_mm"] != 0 or event["vz_mm_us"] >= 0:
            raise ValueError("Reference OA exit must be at geometric z=0 toward negative z")
        row = {"mass_amu": float(particle["mass_th"]), "charge_state": particle["charge_e"]}
        # Canonical physical charge may be serialized as a floating number.
        charge = float(row["charge_state"])
        if not charge.is_integer() or charge == 0 or row["mass_amu"] <= 0:
            raise ValueError("Reference OA species is invalid")
        row["charge_state"] = int(charge)
        row.update({f"velocity_{axis}_m_s": event[f"v{axis}_mm_us"] * 1000 for axis in "xyz"})
        rows.append(row)
    target = _finite(provider["mrtof_projection"]["target_axial_energy_per_charge_v"], "MR axial target")
    if target <= 0:
        raise ValueError("MR axial target must be positive")
    source_energy = _distribution([float(row["kinetic_energy_ev"]) / abs(float(row["charge_e"])) for row in source_rows])
    reference = {"counts": {"source": len(expected), "geometric_exit": len(rows)},
                 "surface": "accelerator_geometric_exit_z0_not_PA_safe_exit",
                 "source_release_total_energy_per_charge": source_energy,
                 "source_release_distribution": source.get("release_energy_distribution"),
                 "exit": _exit_distributions(rows)}
    identities = {name: _identity(path) for name, path in (
        ("reference_provider", provider_path), ("reference_source", source_path),
        ("reference_source_states", state_path), ("reference_log", log_path),
        ("reference_manifest", reference_mr_run / "run_manifest.json"))}
    return target, reference, identities


def validate_component_exit_binding(component: dict[str, Any]) -> tuple[str, str]:
    """Return the explicit instance pair separately from project provenance."""
    source, target = component.get("source_instance_id"), component.get("target_instance_id")
    if (component.get("schema_version") != 2 or component.get("role") != "ion_processor_component_exit_export"
            or component.get("status") != "prepared"
            or component.get("source_project") != "dual_pressure_rectilinear_ion_processor"
            or not isinstance(source, str) or not source
            or not isinstance(target, str) or not target or source == target):
        raise ValueError("Unsupported measured component instance binding")
    return source, target


def resolve_ip_mr_connection(plan: dict[str, Any]) -> dict[str, Any]:
    """Select the supported IP/MR connection from the frozen actual scope."""
    recipe = plan["recipe"]
    selected = set(plan["scope"]["instance_ids"])
    by_id = {item["instance_id"]: item for item in recipe["instances"] if item["instance_id"] in selected}
    edges = [edge for edge in recipe["connections"] if edge["connection_id"] in plan["scope"]["connection_ids"]]
    if len(selected) != 2 or len(edges) != 1:
        raise ValueError("IP/MR selected scope requires two distinct instances and one connection")
    edge = edges[0]
    upstream, downstream = edge["upstream"], edge["downstream"]
    source, target = upstream["instance_id"], downstream["instance_id"]
    if (source == target or source not in by_id or target not in by_id
            or by_id[source]["project_id"] != "dual_pressure_rectilinear_ion_processor"
            or by_id[target]["project_id"] != "parallel_mirror_dual_stripe_mr_tof"
            or upstream["port_id"] != "extraction_exit" or downstream["port_id"] != "accelerator_entry"
            or edge["coupling_mode"] != "monolithic_joint_solve"):
        raise ValueError("IP/MR preparation requires one extraction_exit to accelerator_entry monolithic_joint_solve connection")
    return edge


def resolve_ip_mr_transform(plan: dict[str, Any], connection: dict[str, Any]) -> RigidTransform:
    """Return the supported native-IP to provider-local MR registration."""
    poses = {item["instance_id"]: RigidTransform.from_contract(item["transform"])
             for item in plan["recipe"]["instances"]}
    relative = relative_transform(poses[connection["upstream"]["instance_id"]],
                                  poses[connection["downstream"]["instance_id"]])
    if relative.rotation != ((0, 0, -1), (1, 0, 0), (0, -1, 0)):
        raise ValueError("IP/MR preparation requires the supported native orientation relative to MR")
    return relative


def compare_measured_exit_energy(component_receipt_path: Path, reference_mr_run: Path) -> dict[str, Any]:
    """Compare a new measured IP exit to frozen MR target and actual OA cohort.

    No source vector is changed. Reference and IP distributions use eV/|q|;
    all mother IDs and losses are retained. A centroid residual and empirical
    spread are evidence, not an invented acceptance tolerance or performance
    PASS. This function reads only manifest/receipt-bound light evidence.
    """
    component = _read(component_receipt_path)
    validate_component_exit_binding(component)
    for record in component["inputs"].values():
        _bound_file(record, component_receipt_path.parent)
    state_path = _bound_file(component["outputs"]["component_states"], component_receipt_path.parent)
    census_path = _bound_file(component["outputs"]["mother_census"], component_receipt_path.parent)
    table = load_component_particle_state_csv(state_path)
    rows, validation = table.rows, table.report
    with census_path.open(encoding="utf-8-sig", newline="") as handle:
        census = list(csv.DictReader(handle))
    ids = {row["particle_id"] for row in rows}
    transferred = {int(row["particle_id"]) for row in census if row["transfer_status"] == "transferred"}
    lost = {int(row["particle_id"]) for row in census if row["transfer_status"] == "not_transferred"}
    if (len({int(row["particle_id"]) for row in census}) != len(census) or ids != transferred or ids & lost
            or len(ids | lost) != len(census) or ids != set(component["transferred_particle_ids"])
            or lost != set(component["lost_particle_ids"])
            or component["counts"] != {"source": len(census), "transferred": len(rows), "not_transferred": len(lost)}):
        raise ValueError("IP complete mother census and energy cohort do not close")
    if (validation["frame_ids"] != [component["frame_id"]]
            or validation["clock_epoch_ids"] != [component["clock_epoch_id"]]
            or any(row["velocity_z_m_s"] >= 0
                   or row["source_component_id"] != component["source_instance_id"]
                   or row["target_component_id"] != component["target_instance_id"]
                   or row["state_event"] != "extraction_exit" for row in rows)):
        raise ValueError("IP measured exit frame, clock or negative-z direction differs")
    target, reference, identities = _reference_exit(reference_mr_run)
    measured = _exit_distributions(rows)
    axial = measured["directional_energy"]["z"]
    ref_axial = reference["exit"]["directional_energy"]["z"]
    residual = axial["mean"] - target
    sigma = ref_axial["population_sigma"]
    return {"schema_version": 1, "role": "mrtof_measured_exit_energy_comparison",
            "status": "characterized_without_acceptance_tolerance", "qualification": "energy_distribution_comparison_only",
            "energy_unit": "eV_per_abs_charge_state", "target_axial_energy_per_charge_v": target,
            "target_basis": "historical_OA_provider_axial_design_seed_not_unique_IP_or_total_energy_target",
            "ip_counts": component["counts"], "ip_transferred_particle_ids": sorted(ids), "ip_lost_particle_ids": sorted(lost),
            "ip_exit": measured, "reference_oa": reference,
            "centroid_residual_to_target": residual,
            "centroid_residual_to_reference_oa_mean": axial["mean"]-ref_axial["mean"],
            "total_energy_centroid_difference_to_reference_oa": measured["total_energy"]["mean"]-reference["exit"]["total_energy"]["mean"],
            "directional_energy_centroid_difference_to_reference_oa": {
                axis: measured["directional_energy"][axis]["mean"]-reference["exit"]["directional_energy"][axis]["mean"]
                for axis in "xyz"},
            "nominal_total_energy_target": {
                "status": "undefined_no_explicit_same_surface_total_energy_target", "value": None,
                "reason": "Do not add historical axial seed to OA release Ey: release and exit are distinct potential/reference surfaces."},
            "electrostatic_energy_reference": {
                "invariant": "K_per_abs_charge_plus_charge_sign_times_potential",
                "positive_ion_form": "K/q + phi = constant_in_static_electrostatic_transport",
                "potential_difference_compensated": False,
                "comparison_basis": "raw_measured_kinetic_energies_at_OA_geometric_z0_and_IP_recorded_exit_z0",
                "required_for_downstream_comparison": "Determine potentials and signed directions at the same Prism design/reference surface before interpreting kinetic-energy differences."},
            "centroid_residual_in_reference_population_sigma": residual/sigma if sigma > 0 else None,
            "centroid_match_accepted": None,
            "matching_criterion": "Report axial and total-energy differences only. Evaluate subsequent Prism design using K/q+phi and signed direction at its specified surface; no tolerance or acceptance is assigned.",
            "caveats": [
                "Reference population sigma is empirical beam dispersion, not a centroid acceptance tolerance or numerical error bound.",
                "Deterministic finite cohorts do not justify an IID sigma/sqrt(N) confidence test or tolerance.",
                "Old provider 0.05 eV residual tolerances validate its own controlled extraction, not a replacement IP centroid or full beam.",
                "Small IP slow-axis energy is intentional; its difference from OA Ey is descriptive and is not a mismatch or failure criterion.",
                "Prism voltages and geometry may redistribute y/z momentum and direction, subject to electrostatic energy conservation and physical acceptance; arbitrary independent components are not implied.",
                "Matching mean Ez does not qualify emittance, time focus, prism transport or detector performance.",
                "All transferred ions enter the distributions; upstream losses remain in the full mother census.",
            ],
            "inputs": {**identities, "component_receipt": _identity(component_receipt_path),
                       "component_states": _identity(state_path), "mother_census": _identity(census_path)}}


def resolve_matching_request(
    component_receipt: Path, trajectory_contract: Path,
    accelerator_provider_receipt: Path, request_path: Path, plan_path: Path, *,
    composition_plan: dict[str, Any], connection: dict[str, Any],
) -> dict[str, Any]:
    """Read and validate matching science once, before geometry or state output."""
    if resolve_ip_mr_connection(composition_plan) != connection:
        raise ValueError("Matching connection differs from the frozen composition scope")
    request = _read(request_path)
    schema_path = Path(__file__).parents[1] / "config/ion_processor_matching_request.schema.json"
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
    lost_ids = exported["lost_particle_ids"]
    counts = exported["counts"]
    if (ids != sorted(exported["transferred_particle_ids"])
            or len(ids) != counts["transferred"]
            or len(lost_ids) != counts["not_transferred"]
            or len(census_ids) != len(set(census_ids))
            or len(census_ids) != counts["source"]
            or set(ids) & set(lost_ids)
            or set(census_ids) != set(ids) | set(lost_ids)):
        raise ValueError("Exported IDs and complete source census do not close")
    census_transferred = {int(row["particle_id"]) for row in census if row["transfer_status"] == "transferred"}
    census_lost = {int(row["particle_id"]) for row in census if row["transfer_status"] == "not_transferred"}
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
    native_pose = resolve_ip_mr_transform(composition_plan, matching["connection"])
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
