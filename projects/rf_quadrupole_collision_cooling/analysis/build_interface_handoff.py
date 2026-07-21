"""Build the compact source-exit event stream for the RF-to-oaTOF interface.

The authoritative output contains one time-stamped phase-space row per first
forward crossing.  Solver adapters, pulse-time snapshots and dense trajectories
are deliberately derived elsewhere and are not duplicate handoff authorities.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

import build_oatof_handoff as legacy
import entry_aperture_l0


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = PROJECT_ROOT / "config" / "rf_to_oatof_interface_candidate.json"
EVENT_COLUMNS = [
    "particle_id",
    "species_id",
    "instrument_time_us",
    "position_x_mm",
    "position_y_mm",
    "position_z_mm",
    "velocity_x_m_s",
    "velocity_y_m_s",
    "velocity_z_m_s",
    "lineage_birth_time_us",
    "particle_birth_time_us",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def project_path(value: str) -> Path:
    return (PROJECT_ROOT / value).resolve()


def derive_oatof_entry_reference(target_baseline: dict[str, Any]) -> dict[str, Any]:
    """Locate the blocked +x entry reference on the current closed shield."""

    geometry = target_baseline["geometry_mm"]
    source = target_baseline["particle_source"]
    axis_x = float(target_baseline["coordinate_convention"]["accelerator_axis_x"])
    inner_half = sum(float(geometry[key]) for key in (
        "accelerator_bore_half",
        "accelerator_ring_width",
        "accelerator_insulation_gap",
    ))
    wall = float(geometry["accelerator_shield_wall"])
    outer_half = inner_half + wall
    return {
        "center_mm": [
            axis_x - outer_half,
            float(source["center_y_mm"]),
            float(source["center_z_mm"]),
        ],
        "shield_inner_face_x_mm": axis_x - inner_half,
        "shield_outer_face_x_mm": axis_x - outer_half,
        "shield_inner_half_width_mm": inner_half,
        "shield_outer_half_width_mm": outer_half,
        "shield_wall_thickness_mm": wall,
        "incoming_axis": "+x",
    }


def _vector3(values: list[float], label: str) -> list[float]:
    if len(values) != 3:
        raise ValueError(f"{label} must contain three values")
    vector = [float(value) for value in values]
    if not all(math.isfinite(value) for value in vector):
        raise ValueError(f"{label} must be finite")
    return vector


def transpose3(matrix: list[list[float]]) -> list[list[float]]:
    return [[matrix[row][column] for row in range(3)] for column in range(3)]


def matmul3(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    return [
        [sum(left[row][k] * right[k][column] for k in range(3)) for column in range(3)]
        for row in range(3)
    ]


def validate_rotation_matrix(matrix: list[list[float]]) -> list[list[float]]:
    if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
        raise ValueError("rotation must be a 3x3 matrix")
    rotation = [[float(value) for value in row] for row in matrix]
    if not all(math.isfinite(value) for row in rotation for value in row):
        raise ValueError("rotation values must be finite")
    for row in range(3):
        for other in range(3):
            dot = sum(rotation[row][k] * rotation[other][k] for k in range(3))
            expected = 1.0 if row == other else 0.0
            if not math.isclose(dot, expected, rel_tol=0.0, abs_tol=1e-12):
                raise ValueError("rotation must be orthonormal")
    if not math.isclose(legacy.determinant3(rotation), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("rotation must be right handed with determinant +1")
    return rotation


def derive_target_from_source_pose(
    source_rotation_to_instrument: list[list[float]],
    source_translation_mm: list[float],
    target_rotation_to_instrument: list[list[float]],
    target_translation_mm: list[float],
) -> dict[str, list[float] | list[list[float]]]:
    """Derive the only source-to-target transform from two component poses."""

    source_rotation = validate_rotation_matrix(source_rotation_to_instrument)
    target_rotation = validate_rotation_matrix(target_rotation_to_instrument)
    source_translation = _vector3(source_translation_mm, "source translation")
    target_translation = _vector3(target_translation_mm, "target translation")
    instrument_to_target = transpose3(target_rotation)
    relative_rotation = matmul3(instrument_to_target, source_rotation)
    relative_translation = legacy.matvec(
        instrument_to_target,
        [source_translation[index] - target_translation[index] for index in range(3)],
    )
    validate_rotation_matrix(relative_rotation)
    return {
        "rotation_source_to_target": relative_rotation,
        "translation_mm": relative_translation,
    }


def transform_phase_space(
    position_mm: list[float],
    velocity_m_s: list[float],
    rotation_source_to_target: list[list[float]],
    translation_mm: list[float],
) -> dict[str, list[float]]:
    """Register one state between frames without modeling physical transport."""

    rotation = validate_rotation_matrix(rotation_source_to_target)
    position = _vector3(position_mm, "position")
    velocity = _vector3(velocity_m_s, "velocity")
    translation = _vector3(translation_mm, "translation")
    rotated_position = legacy.matvec(rotation, position)
    return {
        "position_mm": [rotated_position[index] + translation[index] for index in range(3)],
        "velocity_m_s": legacy.matvec(rotation, velocity),
    }


def build_virtual_entry_rows(
    source_events: list[dict[str, Any]],
    contract: dict[str, Any],
    source_origin_mm: list[float],
    rotation_source_to_target: list[list[float]],
) -> list[dict[str, Any]]:
    """Register exit events on the blocked target plane without physical propagation."""

    source_origin = _vector3(source_origin_mm, "source origin")
    rotation = validate_rotation_matrix(rotation_source_to_target)
    target_origin = _vector3(
        contract["boundaries"]["target_entry_surface"]["center_mm"], "target origin"
    )
    rows: list[dict[str, Any]] = []
    for event in source_events:
        source_position = [float(event[f"position_{axis}_mm"]) for axis in "xyz"]
        relative_position = [
            source_position[index] - source_origin[index] for index in range(3)
        ]
        transformed = transform_phase_space(
            relative_position,
            [float(event[f"velocity_{axis}_m_s"]) for axis in "xyz"],
            rotation,
            target_origin,
        )
        row = dict(event)
        for index, axis in enumerate("xyz"):
            row[f"position_{axis}_mm"] = f"{transformed['position_mm'][index]:.17g}"
            row[f"velocity_{axis}_m_s"] = f"{transformed['velocity_m_s'][index]:.17g}"
        rows.append(row)
    return rows


def validate_contract(contract_path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    contract = load_json(contract_path)
    if contract.get("schema_version") != 2:
        raise ValueError("interface candidate must use schema version 2")
    if contract.get("role") != "two_boundary_time_resolved_component_interface_candidate":
        raise ValueError("unsupported interface candidate role")
    if contract.get("package_generation_allowed") is not False:
        raise ValueError("unresolved interface candidate must prohibit package generation")

    source = contract["source_component"]
    source_interface = load_json(project_path(source["interface_contract"]))
    source_baseline = load_json(project_path(source["baseline"]))
    source_boundary = contract["boundaries"]["source_exit_surface"]
    expected_z = float(source_interface["planes"][source["event"]]["z_mm"])
    if not math.isclose(float(source_boundary["z_mm"]), expected_z, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("source-exit surface differs from the RF interface contract")
    expected_radius = float(source_baseline["geometry_mm"]["exit_aperture_radius"])
    actual_radius = float(source_boundary["physical_aperture"]["radius_mm"])
    if not math.isclose(actual_radius, expected_radius, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("source-exit aperture differs from the RF baseline")
    if source_boundary.get("selection_rule") != "first_forward_crossing_only":
        raise ValueError("source-exit events must use the first forward crossing")

    target = contract["target_component"]
    target_baseline = load_json(project_path(target["baseline"]))
    target_reference = contract["target_reference_distribution"]
    particle_source = target_baseline["particle_source"]
    for axis in "xyz":
        contract_size = float(target_reference[f"size_{axis}_mm"])
        baseline_size = float(particle_source[f"size_{axis}_mm"])
        if not math.isclose(contract_size, baseline_size, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("target reference distribution differs from the oaTOF baseline")
    if target_reference.get("hard_acceptance") is not False:
        raise ValueError("the oaTOF formal release distribution is not a hard acceptance")
    target_entry = contract["boundaries"]["target_entry_surface"]
    if target_entry.get("status") != "blocked_by_closed_accelerator_shield":
        raise ValueError("target entry must expose the closed-shield topology blocker")
    entry_reference = derive_oatof_entry_reference(target_baseline)
    if not all(
        math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-12)
        for actual, expected in zip(target_entry["center_mm"], entry_reference["center_mm"])
    ):
        raise ValueError("target entry reference center differs from the oaTOF baseline")
    for key in ("shield_inner_face_x_mm", "shield_outer_face_x_mm", "shield_wall_thickness_mm"):
        if not math.isclose(float(target_entry[key]), float(entry_reference[key]), rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("target entry shield reference differs from the oaTOF baseline")
    if target_entry.get("physical_aperture") is not None:
        raise ValueError("the current closed shield must not claim a physical entry aperture")
    if target_entry.get("reference_surface_is_an_opening") is not False:
        raise ValueError("the target reference plane is blocked by solid shield material")
    connector = contract["connector"]
    if connector.get("status") != "blocked_by_target_shield_topology":
        raise ValueError("connector must remain blocked by the missing target entry port")
    topology_audit = connector["target_entry_topology_audit"]
    if topology_audit.get("status") != "FAIL":
        raise ValueError("closed target shield must remain a failed topology audit")
    if any(not topology_audit.get(key) for key in ("comsol", "simion", "cad", "conclusion")):
        raise ValueError("target entry topology audit must cover COMSOL, SIMION and CAD")
    aperture = connector["entry_aperture_design"]
    if aperture.get("status") != "blocked_pending_theoretical_feasibility":
        raise ValueError("entry aperture must remain blocked pending theoretical feasibility")
    if aperture.get("shape") is not None or aperture.get("design_semi_axes_mm") is not None:
        raise ValueError("entry aperture geometry may not be selected before its bounds are frozen")
    if aperture.get("unconstrained_candidate_scan_allowed") is not False:
        raise ValueError("entry aperture may not be selected by an unconstrained scan")
    gap_bound = entry_aperture_l0.evaluate_entry_aperture_l0(
        repeller_z_mm=float(target_baseline["geometry_mm"]["accelerator_repeller_z"]),
        grid1_z_mm=float(target_baseline["geometry_mm"]["accelerator_grid1_z"]),
        entry_center_z_mm=float(target_baseline["particle_source"]["center_z_mm"]),
    )
    declared_gap = aperture["upper_bounds"]["first_gap_geometry"][
        "absolute_axial_semi_height_ceiling_mm"
    ]
    if not math.isclose(
        float(declared_gap),
        float(gap_bound["absolute_gap_semi_height_ceiling_mm"]),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("entry-aperture first-gap ceiling differs from the oaTOF baseline")
    geometry = target_baseline["geometry_mm"]
    voltages = target_baseline["electrodes_V"]
    reflectron = target_baseline["geometry_derivation"]["reflectron"]
    field1 = (
        float(voltages["repeller"]) - float(voltages["grid1"])
    ) / (
        float(geometry["accelerator_grid1_z"])
        - float(geometry["accelerator_repeller_z"])
    )
    stage2_field = (
        float(voltages["backplate"]) - float(voltages["midgrid"])
    ) / float(geometry["L_stage2"])
    theory_full_width = entry_aperture_l0.coupled_longitudinal_full_width_ceiling_mm(
        nominal_energy_per_charge_v=float(reflectron["nominal_energy_per_charge_V"]),
        field1_v_per_mm=field1,
        reflectron_stage1_voltage_drop_v=(
            float(voltages["midgrid"]) - float(voltages["entgrid"])
        ),
        reflectron_stage2_field_v_per_mm=stage2_field,
        reflectron_stage2_length_mm=float(geometry["L_stage2"]),
        stage2_margin_fraction=float(reflectron["stage2_margin_fraction"]),
        stage2_margin_absolute_mm=float(reflectron["stage2_margin_absolute_mm"]),
        intrinsic_energy_half_range_v=float(
            reflectron["intrinsic_axial_energy_per_charge_half_range_V"]
        ),
    )
    longitudinal_bound = aperture["upper_bounds"]["coupled_longitudinal_envelope"]
    expected_model = "oatof.oaaccelerator_reflectron_coupled.ideal_1d.v1"
    if reflectron.get("model_id") != expected_model:
        raise ValueError("oaTOF baseline is not the required coupled accelerator-reflectron model")
    if longitudinal_bound.get("required_theory_model_id") != expected_model:
        raise ValueError("entry-aperture contract does not require the active coupled theory model")
    focus_conditions = longitudinal_bound.get("focus_conditions", "")
    if "tau_A+tau_R" not in focus_conditions or "d2" not in focus_conditions:
        raise ValueError("entry-aperture contract must name both coupled focus conditions")
    if not math.isclose(
        float(longitudinal_bound["axial_full_height_ceiling_mm"]),
        theory_full_width,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("entry-aperture 1 mm theory ceiling differs from the oaTOF baseline")
    if not math.isclose(
        float(longitudinal_bound["axial_semi_height_ceiling_mm"]),
        theory_full_width / 2.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("entry-aperture full-height and semi-height semantics disagree")
    if not math.isclose(
        float(aperture["upper_bounds"]["current_known_axial_full_height_ceiling_mm"]),
        min(2.0 * float(declared_gap), theory_full_width),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("known axial aperture ceiling is not the minimum derived bound")
    unresolved = aperture["unresolved_inputs"]
    if any(unresolved.get(key) is not None for key in (
        "axial_electrode_clearance_mm",
        "effective_grounded_tube_length_mm",
        "maximum_relative_field_leakage",
        "high_voltage_and_breakdown_limit_mm",
        "field_uniformity_limit_mm",
        "design_safety_factor",
        "required_beam_semi_axes_mm",
        "alignment_allowance_mm",
    )):
        raise ValueError("unresolved aperture inputs must not contain invented design values")
    if contract["boundaries"]["pulse_capture_state"].get("stored_by_default") is not False:
        raise ValueError("pulse snapshots must remain derived on demand")
    if contract["time_control"]["pulse_waveform"].get("status") != "unresolved":
        raise ValueError("pulse waveform may not be implied by the present static oaTOF model")

    registration = contract["spatial_registration"]
    if registration.get("status") != "unresolved":
        raise ValueError("component poses must remain unresolved before mechanical placement is frozen")
    for key in ("source_component_pose", "target_component_pose"):
        pose = registration[key]
        if pose.get("status") != "unresolved":
            raise ValueError("component pose unexpectedly claims to be resolved")
        if pose.get("translation_mm") is not None or pose.get("rotation_component_to_instrument") is not None:
            raise ValueError("unresolved component pose must not contain nominal coordinates")
    relative_pose = registration["derived_target_from_source_pose"]
    if relative_pose.get("status") != "unresolved":
        raise ValueError("relative pose must be derived only after both component poses are frozen")
    if relative_pose.get("translation_mm") is not None or relative_pose.get("rotation_source_to_target") is not None:
        raise ValueError("unresolved relative pose must not contain a duplicate transform")
    if "teleport" not in registration["rigid_transform_rules"].get("physical_policy", ""):
        raise ValueError("coordinate registration must explicitly prohibit particle teleportation")
    alignment = registration["alignment_variables"]
    if alignment.get("status") != "candidate_variables_without_frozen_values_or_tolerances":
        raise ValueError("alignment variables must remain untoleranced candidates")

    required_columns = contract["state_transfer"]["required_columns"]
    lineage_columns = contract["state_transfer"]["lineage_columns_when_available"]
    if EVENT_COLUMNS != required_columns + lineage_columns:
        raise ValueError("event CSV columns differ from the interface contract")
    forbidden = set(contract["state_transfer"]["derived_not_stored"])
    if forbidden.intersection(EVENT_COLUMNS):
        raise ValueError("derived quantities may not be duplicated in the event CSV")
    return {
        "contract": contract,
        "source_interface": source_interface,
        "source_baseline": source_baseline,
        "target_baseline": target_baseline,
        "entry_aperture_theory_full_width_ceiling_mm": theory_full_width,
    }


def solver_local_time_us(instrument_time_us: float, run_window_start_us: float) -> float:
    local_time = float(instrument_time_us) - float(run_window_start_us)
    if not math.isfinite(local_time) or local_time < 0:
        raise ValueError("particle precedes the downstream run window")
    return local_time


def field_free_snapshot(event: dict[str, Any], snapshot_time_us: float) -> dict[str, float] | None:
    """Derive a common-time diagnostic snapshot for field-free propagation.

    This is a lightweight clock/geometry reference, not a replacement for a
    connector containing electric, magnetic, collision or space-charge physics.
    """

    event_time = float(event["instrument_time_us"])
    if snapshot_time_us < event_time:
        return None
    elapsed_us = float(snapshot_time_us) - event_time
    # 1 m/s * 1 us = 1e-3 mm.
    return {
        "instrument_time_us": float(snapshot_time_us),
        **{
            f"position_{axis}_mm": float(event[f"position_{axis}_mm"])
            + float(event[f"velocity_{axis}_m_s"]) * elapsed_us * 1e-3
            for axis in "xyz"
        },
        **{f"velocity_{axis}_m_s": float(event[f"velocity_{axis}_m_s"]) for axis in "xyz"},
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def convert_source_rows(
    source_rows: list[dict[str, str]], contract: dict[str, Any]
) -> tuple[list[dict[str, Any]], float]:
    """Convert diagnostic source rows without writing a second data authority."""

    source = contract["source_component"]
    species_id = source["species_id"]
    species = contract["species_catalog"][species_id]
    mass_amu = float(species["mass_amu"])
    plane_z = float(contract["boundaries"]["source_exit_surface"]["z_mm"])
    event_rows: list[dict[str, Any]] = []
    maximum_energy_residual = 0.0
    for row in source_rows:
        instrument_time = float(row["time_us"])
        elapsed_time = float(row["elapsed_time_us"])
        if not math.isfinite(instrument_time) or not math.isfinite(elapsed_time) or elapsed_time < 0:
            raise ValueError("source handoff contains an invalid clock")
        if not math.isclose(float(row["axial_z_mm"]), plane_z, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("source handoff row is not on the source-exit surface")
        if float(row["velocity_axial_m_s"]) <= 0:
            raise ValueError("source handoff row is not a forward crossing")

        speed_squared = sum(float(row[key]) ** 2 for key in (
            "velocity_x_m_s", "velocity_y_m_s", "velocity_axial_m_s"
        ))
        derived_energy = (
            0.5 * mass_amu * legacy.ATOMIC_MASS_KG * speed_squared / legacy.ELEMENTARY_CHARGE_C
        )
        source_energy = float(row["kinetic_energy_eV"])
        residual = abs(derived_energy - source_energy) / source_energy
        maximum_energy_residual = max(maximum_energy_residual, residual)

        birth_time = instrument_time - elapsed_time
        event_rows.append({
            "particle_id": int(row["particle_id"]),
            "species_id": species_id,
            "instrument_time_us": f"{instrument_time:.17g}",
            "position_x_mm": f"{float(row['transverse_x_mm']):.17g}",
            "position_y_mm": f"{float(row['transverse_y_mm']):.17g}",
            "position_z_mm": f"{float(row['axial_z_mm']):.17g}",
            "velocity_x_m_s": f"{float(row['velocity_x_m_s']):.17g}",
            "velocity_y_m_s": f"{float(row['velocity_y_m_s']):.17g}",
            "velocity_z_m_s": f"{float(row['velocity_axial_m_s']):.17g}",
            "lineage_birth_time_us": f"{birth_time:.17g}",
            "particle_birth_time_us": f"{birth_time:.17g}",
        })
    return event_rows, maximum_energy_residual


def validate_source_without_writing(
    source_csv: Path, source_manifest: Path, contract_path: Path
) -> dict[str, Any]:
    validated = validate_contract(contract_path)
    contract = validated["contract"]
    source_sha = legacy.verify_source_manifest(source_csv, source_manifest, contract)
    source_rows = legacy.read_handoff_rows(source_csv, contract)
    event_rows, maximum_energy_residual = convert_source_rows(source_rows, contract)
    return {
        "particles": len(event_rows),
        "source_sha256": source_sha,
        "maximum_energy_velocity_relative_residual": maximum_energy_residual,
    }


def build_exit_events(
    source_csv: Path,
    source_manifest: Path,
    contract_path: Path,
    event_output: Path,
    metadata_output: Path,
) -> dict[str, Any]:
    validated = validate_contract(contract_path)
    contract = validated["contract"]
    source_sha = legacy.verify_source_manifest(source_csv, source_manifest, contract)
    source_rows = legacy.read_handoff_rows(source_csv, contract)
    source = contract["source_component"]
    event_rows, maximum_energy_residual = convert_source_rows(source_rows, contract)

    _write_csv(event_output, event_rows)
    metadata = {
        "schema_version": 2,
        "role": "component_source_exit_event_metadata",
        "status": "PASS",
        "qualification_scope": contract["qualification_scope"],
        "particles": len(event_rows),
        "frame_id": source["frame_id"],
        "clock_epoch_id": contract["time_control"]["clock_epoch_id"],
        "species_catalog": contract["species_catalog"],
        "source": {
            "particle_state_csv": str(source_csv.resolve()),
            "particle_state_sha256": source_sha,
            "run_manifest": str(source_manifest.resolve()),
            "run_manifest_sha256": legacy.sha256(source_manifest),
        },
        "contract": {
            "path": str(contract_path.resolve()),
            "sha256": legacy.sha256(contract_path),
        },
        "output": {
            "source_exit_event_csv": str(event_output.resolve()),
            "source_exit_event_sha256": legacy.sha256(event_output),
            "columns": EVENT_COLUMNS,
        },
        "diagnostics": {
            "maximum_energy_velocity_relative_residual": maximum_energy_residual,
        },
        "derived_outputs_written": [],
        "package_generation_allowed": False,
        "open_blockers": contract["open_blockers"],
    }
    metadata_output.parent.mkdir(parents=True, exist_ok=True)
    metadata_output.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check-contract", action="store_true")
    action.add_argument("--check-source", action="store_true")
    action.add_argument("--build-exit-events", action="store_true")
    parser.add_argument("--source-csv", type=Path)
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--event-output", type=Path)
    parser.add_argument("--metadata-output", type=Path)
    args = parser.parse_args()
    if args.check_contract:
        validate_contract(args.contract)
        print("TWO_BOUNDARY_INTERFACE_CONTRACT=PASS STATUS=DRAFT RUNTIME_ALLOWED=false")
        return
    if args.check_source:
        if args.source_csv is None or args.source_manifest is None:
            parser.error("--check-source requires --source-csv and --source-manifest")
        result = validate_source_without_writing(args.source_csv, args.source_manifest, args.contract)
        print(
            "SOURCE_EXIT_INPUT=PASS "
            f"PARTICLES={result['particles']} "
            f"MAX_ENERGY_RESIDUAL={result['maximum_energy_velocity_relative_residual']:.12g}"
        )
        return
    required = (args.source_csv, args.source_manifest, args.event_output, args.metadata_output)
    if any(value is None for value in required):
        parser.error("--build-exit-events requires all source and output paths")
    metadata = build_exit_events(
        args.source_csv,
        args.source_manifest,
        args.contract,
        args.event_output,
        args.metadata_output,
    )
    print(f"SOURCE_EXIT_EVENTS=PASS PARTICLES={metadata['particles']}")


if __name__ == "__main__":
    main()
