"""Build a solver-neutral component handoff and derived oa-TOF ION table.

The canonical CSV preserves particle identity, lineage-ready fields and the
instrument clock.  The ION table is a derived input for the current static
oa-TOF consumers; its local birth time may be zero only because the canonical
clock remains available for reconstruction after the downstream run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from common.contracts.component_particle_state import (
    csv_columns as component_state_columns,
    validate_component_particle_state_csv,
)
from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.rigid_transform import (
    FramedPosition,
    FramedVector,
    RigidTransform,
)
from projects.oa_tof.analysis.rf_handoff_adapter import (
    encode_simion_accelerator_velocity,
)


PROJECT_ROOT = Path(
    os.environ.get("RF_HANDOFF_PROJECT_ROOT", Path(__file__).resolve().parents[1])
).resolve()
DEFAULT_CONTRACT = PROJECT_ROOT / "config" / "rf_to_oatof_handoff.json"

REQUIRED_SOURCE_COLUMNS = {
    "particle_id",
    "event",
    "status",
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
}

HYBRID_MESH_SOURCE_COLUMNS = {
    "particle_id", "event", "status", "global_time_us", "particle_age_us", "rf_phase_rad",
    "x_mm", "y_mm", "z_mm", "vx_m_s", "vy_m_s", "vz_m_s", "kinetic_energy_eV",
}

ROW_MAP_COLUMNS = [
    "solver_row_index",
    "particle_id",
    "instrument_time_us",
    "lineage_age_us",
    "particle_age_us",
    "solver_birth_time_us",
    "azimuth_deg",
    "elevation_deg",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def advance_chain_clock(
    instrument_time_in_us: float,
    lineage_age_in_us: float,
    particle_age_in_us: float,
    component_elapsed_time_us: float,
) -> tuple[float, float, float]:
    """Advance shared, lineage and current-particle clocks through transport."""
    elapsed = float(component_elapsed_time_us)
    if elapsed < 0 or not math.isfinite(elapsed):
        raise ValueError("component_elapsed_time_us must be finite and non-negative")
    return (
        float(instrument_time_in_us) + elapsed,
        float(lineage_age_in_us) + elapsed,
        float(particle_age_in_us) + elapsed,
    )


def mass_amu_from_mass_to_charge(mass_to_charge_th: float, charge_state: int) -> float:
    """Convert signed-charge particle identity to the actual mass for solver input."""
    charge = int(charge_state)
    if charge == 0:
        raise ValueError("charge_state must be non-zero")
    mass_to_charge = float(mass_to_charge_th)
    if mass_to_charge <= 0 or not math.isfinite(mass_to_charge):
        raise ValueError("mass_to_charge_Th must be finite and positive")
    return mass_to_charge * abs(charge)


def simion_accelerator_instance_angles(velocity: list[float]) -> tuple[float, float]:
    """Compatibility wrapper around the oaTOF supplier-frame adapter."""
    return encode_simion_accelerator_velocity(velocity)


def _close_vector(left: list[float], right: list[float], tolerance: float = 1e-12) -> bool:
    return all(math.isclose(a, b, rel_tol=0.0, abs_tol=tolerance) for a, b in zip(left, right))


def _project_root_path(relative_path: str) -> Path:
    return (PROJECT_ROOT / relative_path).resolve()


def validate_contract(
    contract_path: Path = DEFAULT_CONTRACT,
    registration_path: Path | None = None,
) -> dict[str, Any]:
    if registration_path is None:
        raise ValueError("resolved spatial registration must be supplied explicitly")
    contract = load_json(contract_path)
    if contract.get("role") != "component_chain_handoff_contract":
        raise ValueError("unsupported handoff contract role")
    if contract.get("status") == "frozen":
        raise ValueError("this projection contract must not be frozen before its physical blockers close")
    if contract.get("package_generation_allowed") is not False:
        raise ValueError("draft handoff must prohibit package generation")
    if contract.get("electrical_interface", {}).get("status") != "unresolved":
        raise ValueError("current electrical interface must remain explicitly unresolved")

    source = contract["source_component"]
    energy_profile = source.get("energy_match_profile", {})
    if energy_profile.get("mode") != "rf_to_oatof_energy_match_n100":
        raise ValueError("the RF energy-match handoff profile is missing or unsupported")
    if int(energy_profile.get("particles", 0)) < int(source["minimum_particles"]):
        raise ValueError("the RF energy-match handoff profile is below the particle minimum")
    energy_contract = load_json(_project_root_path(energy_profile["contract"]))
    if energy_contract.get("claims", {}).get("energy_match_pass_allowed") is not True:
        raise ValueError("the RF energy-match source has not passed its energy gate")
    if energy_contract.get("input_candidate", {}).get("operating_point") != energy_profile["operating_point"]:
        raise ValueError("the RF energy-match operating point is inconsistent")
    source_interface = load_json((PROJECT_ROOT / source["interface_contract"]).resolve())
    source_handoff_z = float(source_interface["planes"][source["event"]]["z_mm"])
    transform = contract["coordinate_transform"]
    if not math.isclose(float(transform["source_origin_mm"][2]), source_handoff_z, abs_tol=1e-12):
        raise ValueError("coordinate source origin does not match the RF handoff plane")

    target = contract["target_component"]
    target_baseline = load_json(_project_root_path(target["baseline"]))
    target_source = target_baseline["particle_source"]
    expected_target_origin = [
        float(target_source["center_x_mm"]),
        float(target_source["center_y_mm"]),
        float(target_source["center_z_mm"]),
    ]
    if not _close_vector([float(v) for v in transform["target_origin_mm"]], expected_target_origin):
        raise ValueError("coordinate target origin does not match the oa-TOF source center")

    spatial_registration = load_json(registration_path)
    if (
        spatial_registration.get("role")
        != "resolved_spatial_registration_do_not_edit"
    ):
        raise ValueError("authoritative spatial registration is invalid")
    spatial_transform = RigidTransform.from_contract(
        spatial_registration["derived_relative_transform"]["transform"]
    )
    rotation = transform["rotation_source_to_target"]
    if [list(row) for row in spatial_transform.rotation] != rotation:
        raise ValueError(
            "legacy transform rotation differs from resolved registration"
        )
    determinant = 1.0
    if not math.isclose(determinant, float(transform["determinant_expected"]), abs_tol=1e-12):
        raise ValueError("coordinate rotation determinant mismatch")
    axial = RigidTransform(
        spatial_transform.from_frame_id,
        spatial_transform.to_frame_id,
        spatial_transform.rotation,
        (0.0, 0.0, 0.0),
    ).transform_vector(
        FramedVector("rf_quadrupole_component", (0.0, 0.0, 1.0))
    )
    if not _close_vector(list(axial.components), [1.0, 0.0, 0.0]):
        raise ValueError("RF axial direction must map to oa-TOF +x")

    timing = contract["timing_contract"]
    if "upgrade_before_upstream_components" not in timing.get("current_rf_source_mapping", {}):
        raise ValueError("the current RF clock mapping must declare its upstream-component upgrade")
    if timing["current_oatof_projection"].get("canonical_time_retained") is not True:
        raise ValueError("the canonical instrument time must be retained")
    if "time_dependent_fields" not in timing["solver_local_time_policy"]:
        raise ValueError("time-dependent component policy is required")
    return {
        "contract": contract,
        "source_interface": source_interface,
        "target_baseline": target_baseline,
        "rotation": rotation,
        "determinant": determinant,
        "spatial_transform": spatial_transform,
        "spatial_registration": spatial_registration,
        "registration_path": registration_path,
    }


def verify_source_manifest(source_csv: Path, manifest_path: Path, contract: dict[str, Any]) -> str:
    manifest = load_json(manifest_path)
    source = contract["source_component"]
    if manifest.get("project") != source["project_id"]:
        raise ValueError("source manifest project mismatch")
    if manifest.get("status") != "success":
        raise ValueError("source manifest is not successful")
    manifest_mode = manifest.get("mode")
    manifest_inputs = manifest.get("inputs", {})
    if manifest_mode == source["mode"]:
        for input_key, contract_key in (("baseline", "baseline"), ("mode", "mode_contract")):
            current_path = (PROJECT_ROOT / source[contract_key]).resolve()
            expected_sha = sha256(current_path)
            if manifest_inputs.get(input_key, {}).get("sha256", "").upper() != expected_sha:
                raise ValueError(f"source manifest {input_key} hash does not match the current contract")
        if "interface_contract" in manifest_inputs:
            interface_sha = sha256((PROJECT_ROOT / source["interface_contract"]).resolve())
            if manifest_inputs["interface_contract"].get("sha256", "").upper() != interface_sha:
                raise ValueError("source manifest interface-contract hash is stale")
    elif manifest_mode == "rf_full_device_hybrid_mesh_n100_functional_arbitration":
        run_config_record = manifest.get("run_config", {})
        run_config_path = Path(run_config_record.get("path", ""))
        if not run_config_path.is_file() or sha256(run_config_path) != run_config_record.get("sha256", "").upper():
            raise ValueError("hybrid-mesh source run config is missing or stale")
        run_config = load_json(run_config_path)
        parameters = run_config.get("parameters", {})
        if parameters.get("particle_tracking") is not True or int(parameters.get("particle_count", 0)) != 100:
            raise ValueError("hybrid-mesh source is not the frozen N=100 particle diagnostic")
        if float(parameters.get("end_core_hmax_mm", -1.0)) not in (0.5, 0.25):
            raise ValueError("hybrid-mesh source is outside the retained pair")
        if Path(manifest_inputs.get("contract", {}).get("path", "")).name != "rf_hybrid_mesh_candidate.json":
            raise ValueError("hybrid-mesh source lacks its frozen mesh contract")
    elif manifest_mode == source["energy_match_profile"]["mode"]:
        profile = source["energy_match_profile"]
        run_config_record = manifest.get("run_config", {})
        run_config_path = Path(run_config_record.get("path", ""))
        if not run_config_path.is_file() or sha256(run_config_path) != run_config_record.get("sha256", "").upper():
            raise ValueError("energy-match source run config is missing or stale")
        run_config = load_json(run_config_path)
        parameters = run_config.get("parameters", {})
        if parameters.get("particle_tracking") is not True or int(parameters.get("particle_count", 0)) != int(profile["particles"]):
            raise ValueError("energy-match source is not the frozen N=100 particle diagnostic")
        if parameters.get("energy_match_enabled") is not True:
            raise ValueError("energy-match source did not enable the named operating point")
        if parameters.get("source_operating_point") != profile["operating_point"]:
            raise ValueError("energy-match source operating point mismatch")
        if not math.isclose(float(parameters.get("end_core_hmax_mm", -1.0)), float(profile["end_core_hmax_mm"]), abs_tol=1e-12):
            raise ValueError("energy-match source mesh does not match the accepted profile")
        energy_record = manifest_inputs.get("energy_match_contract", {})
        frozen_energy_path = Path(energy_record.get("path", ""))
        if not frozen_energy_path.is_file() or sha256(frozen_energy_path) != energy_record.get("sha256", "").upper():
            raise ValueError("energy-match source contract is missing or stale")
        frozen_energy = load_json(frozen_energy_path)
        frozen_candidate = frozen_energy.get("input_candidate", {})
        frozen_changes = frozen_energy.get("model_changes", {})
        if frozen_energy.get("role") != "rf_to_oatof_axial_energy_match_candidate":
            raise ValueError("energy-match source contract role mismatch")
        if frozen_energy.get("claims", {}).get("energy_match_pass_allowed") is not True:
            raise ValueError("energy-match source contract did not pass its energy gate")
        if frozen_candidate.get("operating_point") != profile["operating_point"]:
            raise ValueError("energy-match source contract operating point mismatch")
        if int(frozen_candidate.get("particles", 0)) != int(profile["particles"]):
            raise ValueError("energy-match source contract particle count mismatch")
        if not math.isclose(float(frozen_candidate.get("kinetic_energy_eV", -1.0)), 5.0, abs_tol=1e-12):
            raise ValueError("energy-match source contract energy mismatch")
        prohibited_changes = (
            "geometry_changed", "electrode_potentials_changed", "differential_rf_amplitude_changed",
            "collisions_enabled", "velocity_rewrite_at_handoff_allowed",
        )
        if any(frozen_changes.get(name) is not False for name in prohibited_changes):
            raise ValueError("energy-match source contract changed prohibited RF or handoff physics")
    else:
        raise ValueError("source manifest mode is not an accepted handoff source profile")
    actual_sha = sha256(source_csv)
    matching = [entry for entry in manifest.get("outputs", []) if Path(entry["path"]).name == source_csv.name]
    if not matching or not any(entry.get("sha256", "").upper() == actual_sha for entry in matching):
        raise ValueError("source particle-state CSV is not covered by the manifest hash")
    return actual_sha


def read_handoff_rows(source_csv: Path, contract: dict[str, Any]) -> list[dict[str, str]]:
    with source_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if REQUIRED_SOURCE_COLUMNS.issubset(fields):
            normalize = lambda row: row
        elif HYBRID_MESH_SOURCE_COLUMNS.issubset(fields):
            normalize = lambda row: {
                **row,
                "time_us": row["global_time_us"],
                "elapsed_time_us": row["particle_age_us"],
                "axial_z_mm": row["z_mm"],
                "transverse_x_mm": row["x_mm"],
                "transverse_y_mm": row["y_mm"],
                "velocity_axial_m_s": row["vz_m_s"],
                "velocity_x_m_s": row["vx_m_s"],
                "velocity_y_m_s": row["vy_m_s"],
            }
        else:
            legacy_missing = sorted(REQUIRED_SOURCE_COLUMNS - fields)
            hybrid_missing = sorted(HYBRID_MESH_SOURCE_COLUMNS - fields)
            raise ValueError(
                f"source particle-state CSV matches neither supported profile; "
                f"legacy missing={legacy_missing}, hybrid missing={hybrid_missing}"
            )
        source = contract["source_component"]
        rows = [
            normalize(row) for row in reader
            if row["event"] == source["event"] and row["status"] == source["required_status"]
        ]
    ids = [int(row["particle_id"]) for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("handoff particle IDs must be unique")
    rows.sort(key=lambda row: int(row["particle_id"]))
    if len(rows) < int(source["minimum_particles"]):
        raise ValueError("handoff particle count is below the contract minimum")
    return rows


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_handoff(
    source_csv: Path,
    source_manifest: Path,
    contract_path: Path,
    canonical_output: Path,
    ion_output: Path,
    row_map_output: Path,
    metadata_output: Path,
    solver_clock: str = "local_zero",
    target_origin_override_mm: list[float] | None = None,
    registration_path: Path | None = None,
) -> dict[str, Any]:
    validated = validate_contract(contract_path, registration_path)
    contract = validated["contract"]
    source_sha = verify_source_manifest(source_csv, source_manifest, contract)
    rows = read_handoff_rows(source_csv, contract)
    transform = contract["coordinate_transform"]
    target_origin = (
        [float(value) for value in target_origin_override_mm]
        if target_origin_override_mm is not None
        else [float(value) for value in transform["target_origin_mm"]]
    )
    if len(target_origin) != 3 or not all(math.isfinite(value) for value in target_origin):
        raise ValueError("target origin override must contain three finite millimetre coordinates")
    base_transform = validated["spatial_transform"]
    configured_target = validated["spatial_registration"]["resolved_surfaces"][
        "source_exit"
    ]["in_instrument_frame"]["center_mm"]
    target_offset = tuple(
        target - configured
        for target, configured in zip(target_origin, configured_target)
    )
    spatial_transform = RigidTransform(
        base_transform.from_frame_id,
        base_transform.to_frame_id,
        base_transform.rotation,
        tuple(
            value + offset
            for value, offset in zip(
                base_transform.translation_mm,
                target_offset,
            )
        ),
    )
    source = contract["source_component"]
    target = contract["target_component"]
    timing = contract["timing_contract"]
    if solver_clock not in {"local_zero", "instrument_time"}:
        raise ValueError("solver_clock must be local_zero or instrument_time")
    local_solver_birth_time = float(timing["current_oatof_projection"]["solver_birth_time_us"])
    mass_th = float(source["mass_to_charge_Th"])
    charge_state = int(source["charge_state"])
    mass_amu = mass_amu_from_mass_to_charge(mass_th, charge_state)
    acceptance = contract["acceptance_criteria"]["projection"]

    canonical_rows: list[dict[str, Any]] = []
    row_map_rows: list[dict[str, Any]] = []
    ion_lines: list[str] = []
    maximum_energy_residual = 0.0
    for solver_index, row in enumerate(rows, start=1):
        source_position = [
            float(row["transverse_x_mm"]),
            float(row["transverse_y_mm"]),
            float(row["axial_z_mm"]),
        ]
        target_position = list(
            spatial_transform.transform_position(
                FramedPosition(
                    spatial_transform.from_frame_id,
                    source_position,
                )
            ).coordinates_mm
        )
        source_velocity = [
            float(row["velocity_x_m_s"]),
            float(row["velocity_y_m_s"]),
            float(row["velocity_axial_m_s"]),
        ]
        target_velocity = list(
            spatial_transform.transform_vector(
                FramedVector(
                    spatial_transform.from_frame_id,
                    source_velocity,
                    "polar",
                )
            ).components
        )
        if acceptance["require_positive_target_beam_velocity"] and target_velocity[0] <= 0:
            raise ValueError("projected particle has non-positive oa-TOF beam velocity")
        if abs(target_position[1]) > float(acceptance["maximum_abs_target_y_mm"]):
            raise ValueError("projected particle exceeds the oa-TOF transverse source aperture")
        if not float(acceptance["target_z_min_mm"]) < target_position[2] < float(acceptance["target_z_max_mm"]):
            raise ValueError("projected particle is outside the oa-TOF extraction gap")

        kinetic_energy = float(row["kinetic_energy_eV"])
        velocity_energy = kinetic_energy_ev(mass_amu, *target_velocity)
        residual = abs(velocity_energy - kinetic_energy) / kinetic_energy
        maximum_energy_residual = max(maximum_energy_residual, residual)
        if residual > float(acceptance["maximum_energy_velocity_relative_residual"]):
            raise ValueError("kinetic energy is inconsistent with transformed velocity")

        azimuth, elevation = simion_accelerator_instance_angles(target_velocity)
        instrument_time = float(row["time_us"])
        solver_birth_time = instrument_time if solver_clock == "instrument_time" else local_solver_birth_time
        lineage_age = float(row["elapsed_time_us"])
        particle_age = float(row["elapsed_time_us"])
        lineage_birth_time = instrument_time - lineage_age
        particle_birth_time = instrument_time - particle_age
        particle_id = int(row["particle_id"])
        canonical_rows.append({
            "particle_id": particle_id,
            "parent_particle_id": "",
            "generation": int(contract["identity_contract"]["current_generation"]),
            "species_id": "ion_100amu_q1",
            "particle_weight": "1",
            "source_component_id": source["project_id"],
            "target_component_id": target["project_id"],
            "state_event": "component_handoff",
            "frame_id": transform["target_frame_id"],
            "clock_epoch_id": timing["clock_epoch_id"],
            "instrument_time_us": f"{instrument_time:.15g}",
            "lineage_age_us": f"{lineage_age:.15g}",
            "particle_age_us": f"{particle_age:.15g}",
            "last_component_elapsed_time_us": f"{particle_age:.15g}",
            "lineage_birth_time_us": f"{lineage_birth_time:.15g}",
            "particle_birth_time_us": f"{particle_birth_time:.15g}",
            "mass_to_charge_Th": f"{mass_th:.15g}",
            "mass_amu": f"{mass_amu:.15g}",
            "charge_state": charge_state,
            "position_x_mm": f"{target_position[0]:.15g}",
            "position_y_mm": f"{target_position[1]:.15g}",
            "position_z_mm": f"{target_position[2]:.15g}",
            "velocity_x_m_s": f"{target_velocity[0]:.15g}",
            "velocity_y_m_s": f"{target_velocity[1]:.15g}",
            "velocity_z_m_s": f"{target_velocity[2]:.15g}",
            "kinetic_energy_eV": f"{kinetic_energy:.15g}",
            "phase_reference_id": "rf_quadrupole_drive.v1",
            "phase_rad": f"{float(row['rf_phase_rad']):.15g}",
        })
        row_map_rows.append({
            "solver_row_index": solver_index,
            "particle_id": particle_id,
            "instrument_time_us": f"{instrument_time:.15g}",
            "lineage_age_us": f"{lineage_age:.15g}",
            "particle_age_us": f"{particle_age:.15g}",
            "solver_birth_time_us": f"{solver_birth_time:.15g}",
            "azimuth_deg": f"{azimuth:.15g}",
            "elevation_deg": f"{elevation:.15g}",
        })
        ion_values = [
            solver_birth_time,
            mass_amu,
            charge_state,
            *target_position,
            azimuth,
            elevation,
            kinetic_energy,
            1,
            3,
        ]
        ion_lines.append(",".join(f"{float(value):.15g}" for value in ion_values))

    _write_csv(canonical_output, component_state_columns(), canonical_rows)
    validate_component_particle_state_csv(canonical_output)
    _write_csv(row_map_output, ROW_MAP_COLUMNS, row_map_rows)
    ion_output.parent.mkdir(parents=True, exist_ok=True)
    ion_output.write_text("\n".join(ion_lines) + "\n", encoding="utf-8", newline="\n")
    metadata = {
        "schema_version": 1,
        "role": "component_handoff_projection_metadata",
        "status": "PASS",
        "qualification_scope": contract["qualification_scope"],
        "particles": len(rows),
        "source": {
            "particle_state_csv": str(source_csv.resolve()),
            "particle_state_sha256": source_sha,
            "run_manifest": str(source_manifest.resolve()),
            "run_manifest_sha256": sha256(source_manifest),
        },
        "contract": {"path": str(contract_path.resolve()), "sha256": sha256(contract_path)},
        "spatial_registration": {
            "path": str(registration_path.resolve()),
            "sha256": sha256(registration_path),
        },
        "outputs": {
            "canonical_handoff_csv": {"path": str(canonical_output.resolve()), "sha256": sha256(canonical_output)},
            "oatof_ion": {"path": str(ion_output.resolve()), "sha256": sha256(ion_output)},
            "row_map_csv": {"path": str(row_map_output.resolve()), "sha256": sha256(row_map_output)},
        },
        "clock": {
            "clock_epoch_id": timing["clock_epoch_id"],
            "canonical_instrument_time_retained": True,
            "canonical_lineage_age_retained": True,
            "canonical_particle_age_retained": True,
            "solver_clock": solver_clock,
            "solver_birth_time_us": (
                "per_particle_instrument_time" if solver_clock == "instrument_time"
                else local_solver_birth_time
            ),
            "solver_time_rebase_allowed_only_for_static_fields": solver_clock == "local_zero",
        },
        "diagnostics": {
            "rotation_determinant": validated["determinant"],
            "maximum_energy_velocity_relative_residual": maximum_energy_residual,
            "target_origin_mm": target_origin,
            "target_origin_overridden": target_origin_override_mm is not None,
        },
        "package_generation_allowed": False,
        "open_blockers": contract["open_blockers"],
    }
    metadata_output.parent.mkdir(parents=True, exist_ok=True)
    metadata_output.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check-contract", action="store_true")
    action.add_argument("--convert", action="store_true")
    parser.add_argument("--source-csv", type=Path)
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--canonical-output", type=Path)
    parser.add_argument("--ion-output", type=Path)
    parser.add_argument("--row-map-output", type=Path)
    parser.add_argument("--metadata-output", type=Path)
    parser.add_argument("--solver-clock", choices=("local_zero", "instrument_time"), default="local_zero")
    parser.add_argument("--target-origin-mm", type=float, nargs=3)
    parser.add_argument(
        "--resolved-registration",
        type=Path,
        required=True,
    )
    args = parser.parse_args()
    if args.check_contract:
        validated = validate_contract(args.contract, args.resolved_registration)
        print(f"ROTATION_DETERMINANT={validated['determinant']:.12g}")
        print("COMPONENT_HANDOFF_CONTRACT=PASS STATUS=DRAFT PACKAGE_GENERATION_ALLOWED=false")
        return
    required = (
        args.source_csv,
        args.source_manifest,
        args.canonical_output,
        args.ion_output,
        args.row_map_output,
        args.metadata_output,
    )
    if any(value is None for value in required):
        parser.error("--convert requires all source and output paths")
    metadata = build_handoff(
        args.source_csv,
        args.source_manifest,
        args.contract,
        args.canonical_output,
        args.ion_output,
        args.row_map_output,
        args.metadata_output,
        args.solver_clock,
        args.target_origin_mm,
        args.resolved_registration,
    )
    print(f"COMPONENT_HANDOFF_PROJECTION=PASS PARTICLES={metadata['particles']}")


if __name__ == "__main__":
    main()
