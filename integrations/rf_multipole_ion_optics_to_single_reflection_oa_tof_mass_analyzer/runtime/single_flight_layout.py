"""Compile a governed oaTOF single-flight layout and pulse schedule."""

from __future__ import annotations

import copy
import csv
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from projects.single_reflection_oa_tof_mass_analyzer.analysis.compile_candidate_design import (
    compile_design_overrides,
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ContractError(f"JSON object required: {path}")
    return value


def select_profile(registry: dict[str, Any], profile_id: str) -> dict[str, Any]:
    if (
        registry.get("schema_version") != 1
        or registry.get("role")
        != "rf_oatof_single_flight_layout_profile_registry"
    ):
        raise ContractError("single-flight layout registry identity differs")
    matches = [
        item for item in registry.get("profiles", [])
        if item.get("layout_profile_id") == profile_id
    ]
    if len(matches) != 1:
        raise ContractError(f"single-flight layout profile is not unique: {profile_id}")
    profile = copy.deepcopy(matches[0])
    if (
        profile.get("method") != "symmetric_axis_speed_scaling_v1"
        or profile.get("pulse_timing_method")
        != "multipole_handoff_ballistic_centroid_v1"
    ):
        raise ContractError("single-flight layout method is unsupported")
    reference = float(profile["reference_injection_energy_eV"])
    target = float(profile["target_injection_energy_eV"])
    if not (math.isfinite(reference) and math.isfinite(target) and reference > 0 and target > 0):
        raise ContractError("single-flight injection energies must be finite and positive")
    overrides = profile.get("design_overrides", [])
    if not isinstance(overrides, list):
        raise ContractError("single-flight design overrides must be a list")
    return profile


def compile_geometry_and_port(
    base_geometry: dict[str, Any],
    base_port: dict[str, Any],
    profile: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, float]]:
    if base_geometry.get("role") != "oa_tof_resolved_contract_do_not_edit":
        raise ContractError("single-flight layout requires the resolved oaTOF geometry")
    validate_schema(base_port, "component_port.schema.json")
    coordinate = base_geometry["coordinate_convention"]
    base_axis = float(coordinate["accelerator_axis_x"])
    base_detector = float(coordinate["detector_x"])
    base_port_x = float(base_port["mating_surface"]["center_mm"][0])
    scale = math.sqrt(
        float(profile["target_injection_energy_eV"])
        / float(profile["reference_injection_energy_eV"])
    )
    axis_x = base_axis * scale
    detector_offset = base_detector + base_axis
    detector_x = -axis_x + detector_offset
    port_offset = base_port_x - base_axis
    port_x = axis_x + port_offset

    overrides = profile.get("design_overrides", [])
    if overrides:
        try:
            geometry, design_derivation = compile_design_overrides(
                base_geometry, overrides
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ContractError(f"single-flight design compilation failed: {error}") from error
    else:
        geometry = copy.deepcopy(base_geometry)
        design_derivation = {
            "method": "catalog_design_overrides_with_theory_closure_v1",
            "changed_variables": [],
            "rebuild_effects": [],
            "simion_rebuild_plan": {
                "frontend_pa": False,
                "flight_tube_pa": False,
                "reflectron_pa": False,
            },
        }
    geometry["coordinate_convention"]["accelerator_axis_x"] = axis_x
    geometry["coordinate_convention"]["detector_x"] = detector_x
    geometry["coordinate_convention"]["origin"] = (
        "diagnostic symmetric injection-energy-scaled accelerator/detector layout"
    )
    geometry["particle_source"]["center_x_mm"] = axis_x
    geometry["single_flight_layout_derivation"] = {
        "layout_profile_id": profile["layout_profile_id"],
        "method": profile["method"],
        "reference_injection_energy_eV": float(profile["reference_injection_energy_eV"]),
        "target_injection_energy_eV": float(profile["target_injection_energy_eV"]),
        "speed_scale": scale,
        "base_accelerator_axis_x_mm": base_axis,
        "accelerator_axis_x_mm": axis_x,
        "detector_x_mm": detector_x,
        "entry_port_x_mm": port_x,
        "claim_status": profile["claim_status"],
        "design_compilation": design_derivation,
    }

    port = copy.deepcopy(base_port)
    port["profile_scope"] = {
        "scope_id": profile["layout_profile_id"],
        "scope_kind": "integration_oracle",
        "family_experiment_port": True,
    }
    port["mating_surface"]["center_mm"][0] = port_x
    return geometry, port, {
        "accelerator_axis_x_mm": axis_x,
        "detector_x_mm": detector_x,
        "entry_port_x_mm": port_x,
        "speed_scale": scale,
    }


def derive_pulse_schedule(
    state_path: Path,
    resolved_connection: dict[str, Any],
    geometry: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    with state_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [
            row for row in csv.DictReader(handle)
            if row["event"] == "handoff" and row["status"] == "transmitted"
        ]
    if not rows:
        raise ContractError("no transmitted multipole handoff states are available")
    registration = resolved_connection["spatial_registration"]
    rotation = registration["rotation_upstream_to_downstream"]
    if rotation != [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]:
        raise ContractError("pulse scheduler requires the canonical multipole-to-oaTOF rotation")
    tx, ty, tz = map(float, registration["translation_mm"])
    aperture = resolved_connection["transition_aperture"]
    center = list(map(float, aperture["center_mm"]))
    half_y = float(aperture["full_width_mm"]) / 2.0
    half_z = float(aperture["full_height_mm"]) / 2.0
    wall = float(geometry["geometry_mm"]["accelerator_shield_wall"])
    cohort: list[dict[str, float | int]] = []
    for row in rows:
        x = float(row["axial_z_mm"]) + tx
        y = float(row["transverse_x_mm"]) + ty
        z = float(row["transverse_y_mm"]) + tz
        vx = float(row["velocity_axial_m_s"])
        vy = float(row["velocity_x_m_s"])
        vz = float(row["velocity_y_m_s"])
        if vx <= 0 or not math.isclose(x, center[0], rel_tol=0, abs_tol=1e-8):
            continue
        inner_y = y + vy / vx * wall
        inner_z = z + vz / vx * wall
        if (
            abs(y - center[1]) <= half_y + 1e-12
            and abs(z - center[2]) <= half_z + 1e-12
            and abs(inner_y - center[1]) <= half_y + 1e-12
            and abs(inner_z - center[2]) <= half_z + 1e-12
        ):
            cohort.append({
                "particle_id": int(row["particle_id"]),
                "time_us": float(row["time_us"]),
                "vx_m_s": vx,
                "energy_eV": float(row["kinetic_energy_eV"]),
            })
    if not cohort:
        raise ContractError("finite-wall prediction leaves no pulse-scheduling particles")
    mean_vx = sum(float(item["vx_m_s"]) for item in cohort) / len(cohort)
    mean_vx_t = sum(
        float(item["vx_m_s"]) * float(item["time_us"]) for item in cohort
    ) / len(cohort)
    target_x = float(geometry["particle_source"]["center_x_mm"])
    pulse_time = (1000.0 * (target_x - center[0]) + mean_vx_t) / mean_vx
    predicted = [
        center[0] + float(item["vx_m_s"]) *
        (pulse_time - float(item["time_us"])) / 1000.0
        for item in cohort
    ]
    centroid_error = sum(predicted) / len(predicted) - target_x
    if not math.isclose(centroid_error, 0.0, rel_tol=0, abs_tol=1e-9):
        raise ContractError("derived single-flight pulse does not center the cohort")
    return {
        "schema_version": 1,
        "role": "rf_oatof_single_flight_multipole_handoff_pulse_schedule",
        "layout_profile_id": profile["layout_profile_id"],
        "method": profile["pulse_timing_method"],
        "source_state_path": str(state_path.resolve()),
        "source_state_sha256": file_sha256(state_path),
        "population_counts": {
            "transmitted_handoff": len(rows),
            "predicted_finite_wall_survivors": len(cohort),
        },
        "selected_particle_ids": [int(item["particle_id"]) for item in cohort],
        "mean_entry_time_us": sum(float(item["time_us"]) for item in cohort) / len(cohort),
        "mean_velocity_x_m_s": mean_vx,
        "mean_kinetic_energy_eV": sum(float(item["energy_eV"]) for item in cohort) / len(cohort),
        "target_centroid_x_mm": target_x,
        "entry_surface_x_mm": center[0],
        "derived_pulse_time_us": pulse_time,
        "pulse_width_us": 1.0,
        "predicted_centroid_error_x_mm": centroid_error,
        "claim_status": profile["claim_status"],
    }
