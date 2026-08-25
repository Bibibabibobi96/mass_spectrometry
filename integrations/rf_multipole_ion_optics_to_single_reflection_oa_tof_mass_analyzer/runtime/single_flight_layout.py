"""Compile a governed oaTOF single-flight layout and pulse schedule."""

from __future__ import annotations

import copy
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from projects.single_reflection_oa_tof_mass_analyzer.analysis.compile_candidate_design import (
    compile_design_overrides,
    derive_accelerator_outer_envelope_min_z,
    derive_shield_bounds,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.finite_interval_design_compiler import (
    compile_finite_interval_oatof_design,
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
        profile.get("method") not in {
            "symmetric_axis_speed_scaling_v1",
            "t5_frozen_three_zone_candidate_v1",
        }
        or profile.get("pulse_timing_method")
        != "multipole_handoff_ballistic_centroid_v1"
        or not isinstance(profile.get("architecture_generation_id"), str)
        or not profile["architecture_generation_id"]
    ):
        raise ContractError("single-flight layout method is unsupported")
    reference = float(profile["reference_injection_energy_eV"])
    target = float(profile["target_injection_energy_eV"])
    if not (math.isfinite(reference) and math.isfinite(target) and reference > 0 and target > 0):
        raise ContractError("single-flight injection energies must be finite and positive")
    overrides = profile.get("design_overrides", [])
    if not isinstance(overrides, list):
        raise ContractError("single-flight design overrides must be a list")
    if profile["method"] == "t5_frozen_three_zone_candidate_v1":
        if (
            overrides
            or profile.get("finite_interval_accelerator_profile") is not None
            or any(
                not isinstance(profile.get(key), str) or not profile[key]
                for key in (
                    "topology_id",
                    "geometry_id",
                    "frontend_electrode_topology_id",
                    "candidate_field_id",
                )
            )
            or profile.get("claim_status") != "CANDIDATE_ONLY"
        ):
            raise ContractError("three-zone T5 layout profile identity is invalid")
        ring_policy = profile.get("accelerator_ring_placement_policy")
        if ring_policy is not None and (
            set(ring_policy) != {
                "policy_id",
                "zone2_ring_count",
                "zone3_ring_count",
                "minimum_grid_to_ring_edge_clearance_mm",
            }
            or ring_policy.get("policy_id")
            != "three_zone_zonewise_equal_subdivision_1p4_v1"
            or ring_policy.get("zone2_ring_count") != 1
            or ring_policy.get("zone3_ring_count") != 4
            or not math.isfinite(
                float(ring_policy.get("minimum_grid_to_ring_edge_clearance_mm", math.nan))
            )
            or float(ring_policy["minimum_grid_to_ring_edge_clearance_mm"]) <= 0.0
        ):
            raise ContractError("three-zone accelerator ring placement policy is invalid")
    return profile


def _derive_three_zone_ring_placement(
    profile: dict[str, Any],
    plane_values: dict[str, float],
    *,
    ring_count: int,
    ring_thickness_mm: float,
) -> dict[str, Any] | None:
    """Resolve a profile-owned zonewise equal-subdivision ring placement."""

    policy = profile.get("accelerator_ring_placement_policy")
    if policy is None:
        return None
    zone_counts = {
        "zone2": int(policy["zone2_ring_count"]),
        "zone3": int(policy["zone3_ring_count"]),
    }
    if sum(zone_counts.values()) != ring_count:
        raise ContractError("three-zone ring placement count differs from accelerator_count")
    zones = (
        ("zone2", "intermediate1", "intermediate2"),
        ("zone3", "intermediate2", "exit"),
    )
    centers: list[float] = []
    observed_clearances: list[float] = []
    half_thickness = ring_thickness_mm / 2.0
    for zone, left_role, right_role in zones:
        left = plane_values[left_role]
        right = plane_values[right_role]
        count = zone_counts[zone]
        pitch = (right - left) / (count + 1)
        zone_centers = [left + index * pitch for index in range(1, count + 1)]
        centers.extend(zone_centers)
        observed_clearances.extend(
            (zone_centers[0] - half_thickness - left,
             right - zone_centers[-1] - half_thickness)
        )
    required_clearance = float(policy["minimum_grid_to_ring_edge_clearance_mm"])
    observed_clearance = min(observed_clearances)
    if observed_clearance + 1e-12 < required_clearance:
        raise ContractError("three-zone grid-to-ring edge clearance is below policy")
    return {
        "policy_id": policy["policy_id"],
        "zone_ring_counts": zone_counts,
        "minimum_grid_to_ring_edge_clearance_mm": required_clearance,
        "minimum_observed_grid_to_ring_edge_clearance_mm": observed_clearance,
        "ring_z_mm": centers,
    }


def _compile_three_zone_candidate(
    base_geometry: dict[str, Any],
    profile: dict[str, Any],
    candidate: dict[str, Any],
    candidate_binding: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Map one hash-bound T5 or C3_J3 Candidate into the layout surface."""

    if (
        candidate.get("role") != "oatof_three_zone_simion_candidate_resolved"
        or candidate.get("qualification") != "CANDIDATE_ONLY"
        or candidate.get("compiler_mode") not in {
            "T5_FROZEN_PRIMARY_AND_BRANCH_ONLY",
            "C3_J3_EXACT_LOCAL_DIRECTION_V1",
        }
        or set(candidate_binding) != {"path", "sha256"}
    ):
        raise ContractError("three-zone Candidate identity is invalid")
    identities = candidate.get("identities", {})
    expected_identities = {
        "topology_id": profile["topology_id"],
        "geometry_id": profile["geometry_id"],
        "field_id": profile["candidate_field_id"],
    }
    if identities != expected_identities:
        raise ContractError("three-zone T5 Candidate scientific identity differs")
    topology = candidate.get("accelerator_topology")
    if (
        not isinstance(topology, dict)
        or topology.get("topology_id") != profile["topology_id"]
    ):
        raise ContractError("three-zone T5 Candidate topology differs")
    planes = topology.get("planes_global_z_mm", {})
    potentials = topology.get("potentials_v", {})
    plane_keys = {"repeller", "intermediate1", "intermediate2", "exit"}
    if set(planes) != plane_keys or set(potentials) != plane_keys:
        raise ContractError("three-zone T5 Candidate planes or potentials are incomplete")
    order = ("repeller", "intermediate1", "intermediate2", "exit")
    plane_values = {key: float(planes[key]) for key in order}
    potential_values = {key: float(potentials[key]) for key in order}
    if (
        not all(
            math.isfinite(value)
            for value in (*plane_values.values(), *potential_values.values())
        )
        or not all(
            plane_values[left] < plane_values[right]
            for left, right in zip(order, order[1:])
        )
        or not all(
            potential_values[left] > potential_values[right]
            for left, right in zip(order, order[1:])
        )
    ):
        raise ContractError("three-zone T5 Candidate topology is not ordered")

    physics = candidate.get("accelerator_physics", {})
    lengths = physics.get("lengths_mm", {})
    if set(lengths) != {"d1", "d2", "d3"}:
        raise ContractError("three-zone T5 Candidate lengths are incomplete")
    d1 = float(lengths["d1"])
    d2 = float(lengths["d2"])
    d3 = float(lengths["d3"])
    focus_drift = float(physics.get("focus_drift_after_exit_mm", math.nan))
    if not all(
        math.isfinite(value) and value > 0.0 for value in (d1, d2, d3)
    ):
        raise ContractError("three-zone T5 Candidate lengths must be positive")
    for label, actual, expected in (
        ("d1", plane_values["intermediate1"] - plane_values["repeller"], d1),
        ("d2", plane_values["intermediate2"] - plane_values["intermediate1"], d2),
        ("d3", plane_values["exit"] - plane_values["intermediate2"], d3),
        ("focus", -plane_values["exit"], focus_drift),
    ):
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-9):
            raise ContractError(f"three-zone T5 Candidate {label} geometry differs")

    geometry = copy.deepcopy(base_geometry)
    geom = geometry["geometry_mm"]
    accelerator = geometry["geometry_derivation"]["accelerator"]
    source = candidate.get("source_identity", {}).get("frozen_source", {})
    reflectron = candidate.get("reflectron", {})
    source_center = float(source.get("center_x_mm", math.nan))
    source_width = float(profile["source_release_full_width_mm"])
    stage1_voltage = float(reflectron.get("u_r1_v", math.nan))
    stage2_field = float(reflectron.get("f_r2_v_per_mm", math.nan))
    focus_to_reflectron = float(profile["focus_to_reflectron_mm"])
    if not (
        math.isfinite(source_center)
        and 0.0 < source_center < d1
        and math.isfinite(source_width)
        and source_width > 0.0
        and math.isfinite(stage1_voltage)
        and stage1_voltage > 0.0
        and math.isfinite(stage2_field)
        and stage2_field > 0.0
        and math.isfinite(focus_to_reflectron)
        and focus_to_reflectron > 0.0
    ):
        raise ContractError("three-zone T5 source or reflectron mapping is invalid")

    total_l23 = d2 + d3
    geom["L_accel"] = d1 + total_l23
    geom["accelerator_repeller_z"] = plane_values["repeller"]
    geom["accelerator_grid1_z"] = plane_values["intermediate1"]
    geom["accelerator_grid2_z"] = plane_values["exit"]
    geom["accelerator_focus_z"] = 0.0
    geom["L_flight"] = focus_to_reflectron
    geometry["accelerator_topology"] = copy.deepcopy(topology)
    geometry["electrodes_V"].update(
        {
            "repeller": potential_values["repeller"],
            "grid1": potential_values["intermediate1"],
            "intermediate2": potential_values["intermediate2"],
            "grid2": potential_values["exit"],
            "midgrid": stage1_voltage,
            "backplate": stage1_voltage
            + stage2_field * float(geom["L_stage2"]),
        }
    )
    geometry["particle_source"]["center_z_mm"] = (
        plane_values["repeller"] + source_center
    )
    geometry["particle_source"]["center_z_rule"] = (
        "accelerator_topology.planes_global_z_mm.repeller + "
        "geometry_derivation.accelerator.source_center_from_repeller_mm"
    )
    geometry["particle_source"]["size_z_mm"] = source_width
    ring_placement = _derive_three_zone_ring_placement(
        profile,
        plane_values,
        ring_count=int(geometry["rings"]["accelerator_count"]),
        ring_thickness_mm=float(geom["accelerator_ring_thickness"]),
    )
    if ring_placement is not None:
        geometry["rings"]["accelerator_placement"] = ring_placement
    accelerator.clear()
    accelerator.update(
        {
            "topology_id": profile["topology_id"],
            "geometry_id": profile["geometry_id"],
            "d1_mm": d1,
            "d2_mm": total_l23,
            "zone2_length_mm": d2,
            "zone3_length_mm": d3,
            "canonical_repeller_z_mm": plane_values["repeller"],
            "canonical_grid1_z_mm": plane_values["intermediate1"],
            "canonical_intermediate2_z_mm": plane_values["intermediate2"],
            "canonical_grid2_z_mm": plane_values["exit"],
            "canonical_focus_z_mm": 0.0,
            "focus_drift_after_grid2_mm": focus_drift,
            "source_center_from_repeller_mm": source_center,
            "source_release_full_width_mm": source_width,
            "rule": (
                "Consume the hash-bound T5 frozen primary and preserve its "
                "exact four-plane topology."
            ),
        }
    )
    reflectron_derivation = geometry["geometry_derivation"]["reflectron"]
    reflectron_derivation.update(
        {
            "model_id": "oatof.three_zone_t5_frozen_reflectron.v1",
            "total_field_free_length_mm": 2.0 * focus_to_reflectron,
            "outbound_field_free_length_mm": focus_to_reflectron,
            "return_field_free_length_mm": focus_to_reflectron,
            "stage1_length_mm": float(geom["L_stage1"]),
            "stage1_voltage_drop_V": stage1_voltage,
            "stage2_field_V_per_mm": stage2_field,
            "nominal_energy_per_charge_V": float(
                source["nominal_energy_per_charge_v"]
            ),
            "source_release_full_width_mm": source_width,
            "rule": (
                "Consume the hash-bound T5 frozen U_R1 and F_R2; retain "
                "the published reflectron lengths."
            ),
        }
    )
    derive_shield_bounds(
        geometry, derive_accelerator_outer_envelope_min_z(geometry)
    )
    compilation = {
        "method": profile["method"],
        "candidate": copy.deepcopy(candidate_binding),
        "candidate_campaign_id": candidate["campaign"]["campaign_id"],
        "candidate_plan_sha256": candidate["t5_evidence"]["plan_sha256"],
        "changed_variables": [
            "three_zone_accelerator_topology",
            "source_release_full_width",
            "reflectron_voltage",
            *(["accelerator_ring_placement"] if ring_placement is not None else []),
        ],
        "rebuild_effects": [
            "accelerator_geometry",
            "accelerator_voltage",
            "accelerator_axial_position",
            "reflectron_voltage",
        ],
        "simion_rebuild_plan": {
            "frontend_pa": True,
            "flight_tube_pa": True,
            "reflectron_pa": False,
        },
    }
    # T5 geometry was already published and can be consumed by manifest-bound
    # post-pulse restarts.  Keep that resolved surface byte-for-byte semantic
    # compatible; only the newly introduced C3 route needs an explicit mode.
    if candidate["compiler_mode"] == "C3_J3_EXACT_LOCAL_DIRECTION_V1":
        compilation["candidate_compiler_mode"] = candidate["compiler_mode"]
    return geometry, compilation


def compile_geometry_and_port(
    base_geometry: dict[str, Any],
    base_port: dict[str, Any],
    profile: dict[str, Any],
    *,
    three_zone_candidate: dict[str, Any] | None = None,
    three_zone_candidate_binding: dict[str, str] | None = None,
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
    if profile["method"] == "t5_frozen_three_zone_candidate_v1":
        if three_zone_candidate is None or three_zone_candidate_binding is None:
            raise ContractError(
                "three-zone T5 layout requires a hash-bound Candidate"
            )
        geometry, design_derivation = _compile_three_zone_candidate(
            base_geometry,
            profile,
            three_zone_candidate,
            three_zone_candidate_binding,
        )
    elif three_zone_candidate is not None or three_zone_candidate_binding is not None:
        raise ContractError(
            "three-zone Candidate is only valid for the T5 layout"
        )
    elif overrides:
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
    finite_profile_path = profile.get("finite_interval_accelerator_profile")
    finite_interval_input_provenance = None
    if finite_profile_path is not None:
        finite_owned_variables = {
            "accelerator_stage1_length",
            "accelerator_stage2_length",
            "source_release_full_width",
            "accelerator_repeller_voltage",
            "accelerator_grid1_voltage",
        }
        conflicting_overrides = [
            item for item in overrides if item.get("variable") in finite_owned_variables
        ]
        if conflicting_overrides:
            raise ContractError(
                "finite-interval accelerator profile owns the source-width design"
            )
        match_profile = _load((Path(__file__).resolve().parents[1] / finite_profile_path).resolve())
        finite = match_profile["finite_interval_design"]
        frozen = profile.get(
            "finite_interval_phase_space_input",
            match_profile["frozen_phase_space_input"],
        )
        if "finite_interval_phase_space_input" in profile:
            required_phase_space_keys = {
                "authority",
                "mass_to_charge_Th",
                "release_position_mm",
                "mean_initial_velocity_m_per_s",
                "velocity_slope_m_per_s_per_mm",
            }
            if (
                set(frozen) != required_phase_space_keys
                or frozen["authority"] != "solver_native_zero_mean_zero_slope"
                or float(frozen["mean_initial_velocity_m_per_s"]) != 0.0
                or float(frozen["velocity_slope_m_per_s_per_mm"]) != 0.0
                or float(frozen["mass_to_charge_Th"]) <= 0.0
                or not math.isfinite(float(frozen["release_position_mm"]))
            ):
                raise ContractError(
                    "finite-interval phase-space override is not the governed zero-zero input"
                )
        accelerator = geometry["geometry_derivation"]["accelerator"]
        stage1_length_mm = float(
            profile.get("accelerator_stage1_length_mm", accelerator["d1_mm"])
        )
        source_full_width_mm = float(
            profile.get(
                "finite_interval_source_full_width_mm",
                finite["source_full_width_mm"],
            )
        )
        if stage1_length_mm <= 0 or source_full_width_mm <= 0:
            raise ContractError(
                "finite-interval stage-1 length and source width must be positive"
            )
        physical_phase_space = {
            name: frozen[name]
            for name in (
                "mass_to_charge_Th",
                "release_position_mm",
                "mean_initial_velocity_m_per_s",
                "velocity_slope_m_per_s_per_mm",
            )
        }
        try:
            geometry, design_derivation = compile_finite_interval_oatof_design(
                geometry,
                {
                    "phase_space_input": physical_phase_space,
                    "accelerator_stage1_length_mm": stage1_length_mm,
                    "source_full_width_mm": source_full_width_mm,
                },
                prior_rebuild_plan=design_derivation["simion_rebuild_plan"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ContractError(
                f"finite-interval oaTOF design compilation failed: {error}"
            ) from error
        finite_interval_input_provenance = {
            "profile_path": finite_profile_path,
            "phase_space_input": copy.deepcopy(frozen),
        }
    geometry["coordinate_convention"]["accelerator_axis_x"] = axis_x
    geometry["coordinate_convention"]["detector_x"] = detector_x
    geometry["coordinate_convention"]["origin"] = (
        "diagnostic symmetric injection-energy-scaled accelerator/detector layout"
    )
    geometry["particle_source"]["center_x_mm"] = axis_x
    geometry["single_flight_layout_derivation"] = {
        "layout_profile_id": profile["layout_profile_id"],
        "architecture_generation_id": profile["architecture_generation_id"],
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
    if finite_interval_input_provenance is not None:
        geometry["single_flight_layout_derivation"][
            "finite_interval_input_provenance"
        ] = finite_interval_input_provenance

    port = copy.deepcopy(base_port)
    port["profile_scope"] = {
        "scope_id": profile["layout_profile_id"],
        "scope_kind": "integration_oracle",
        "family_experiment_port": True,
    }
    port["mating_surface"]["center_mm"][0] = port_x
    port["mating_surface"]["center_mm"][1] = float(
        geometry["particle_source"]["center_y_mm"]
    )
    port["mating_surface"]["center_mm"][2] = float(
        geometry["particle_source"]["center_z_mm"]
    )
    return geometry, port, {
        "accelerator_axis_x_mm": axis_x,
        "detector_x_mm": detector_x,
        "entry_port_x_mm": port_x,
        "speed_scale": scale,
    }


def project_handoff_through_connector(
    rows: list[dict[str, str]],
    resolved_connection: dict[str, Any],
    geometry: dict[str, Any],
) -> dict[str, Any]:
    """Ballistically project handoff rows through the resolved finite-wall connector."""
    registration = resolved_connection["spatial_registration"]
    rotation = registration["rotation_upstream_to_downstream"]
    if rotation != [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]:
        raise ContractError("connector projection requires the canonical rotation")
    gap = float(registration["actual_gap_mm"])
    expected_gap = float(registration["expected_gap_mm"])
    connector_length = float(resolved_connection["connector"]["length_mm"])
    tolerance = float(registration["position_tolerance_mm"])
    if (
        not math.isfinite(gap)
        or gap < 0
        or not math.isclose(gap, expected_gap, rel_tol=0, abs_tol=tolerance)
        or not math.isclose(gap, connector_length, rel_tol=0, abs_tol=tolerance)
    ):
        raise ContractError("resolved connector actual gap identity differs")
    tx, ty, tz = map(float, registration["translation_mm"])
    aperture = resolved_connection["transition_aperture"]
    center = list(map(float, aperture["center_mm"]))
    half_y = float(aperture["full_width_mm"]) / 2.0
    half_z = float(aperture["full_height_mm"]) / 2.0
    wall = float(geometry["geometry_mm"]["accelerator_shield_wall"])
    candidates: list[dict[str, float | int]] = []
    survivors: list[dict[str, float | int]] = []
    for row in rows:
        handoff_x = float(row["axial_z_mm"]) + tx
        handoff_y = float(row["transverse_x_mm"]) + ty
        handoff_z = float(row["transverse_y_mm"]) + tz
        vx = float(row["velocity_axial_m_s"])
        vy = float(row["velocity_x_m_s"])
        vz = float(row["velocity_y_m_s"])
        if vx <= 0 or not math.isclose(
            handoff_x, center[0] - gap, rel_tol=0, abs_tol=max(tolerance, 1e-8)
        ):
            continue
        outer_y = handoff_y + vy / vx * gap
        outer_z = handoff_z + vz / vx * gap
        inner_y = outer_y + vy / vx * wall
        inner_z = outer_z + vz / vx * wall
        entry_time = float(row["time_us"]) + 1000.0 * gap / vx
        item: dict[str, float | int] = {
            "particle_id": int(row["particle_id"]),
            "handoff_x_mm": handoff_x,
            "handoff_y_mm": handoff_y,
            "handoff_z_mm": handoff_z,
            "outer_y_mm": outer_y,
            "outer_z_mm": outer_z,
            "inner_y_mm": inner_y,
            "inner_z_mm": inner_z,
            "entry_time_us": entry_time,
            "vx_m_s": vx,
            "vy_m_s": vy,
            "vz_m_s": vz,
            "energy_eV": float(row["kinetic_energy_eV"]),
        }
        candidates.append(item)
        if (
            abs(outer_y - center[1]) <= half_y + 1e-12
            and abs(outer_z - center[2]) <= half_z + 1e-12
            and abs(inner_y - center[1]) <= half_y + 1e-12
            and abs(inner_z - center[2]) <= half_z + 1e-12
        ):
            survivors.append(item)
    return {
        "actual_gap_mm": gap,
        "aperture_center_mm": center,
        "aperture_half_width_y_mm": half_y,
        "aperture_half_height_z_mm": half_z,
        "wall_thickness_mm": wall,
        "handoff_candidates": candidates,
        "finite_wall_survivors": survivors,
    }


def resolve_source_region_bounds(
    geometry: dict[str, Any],
    source_region_profile: dict[str, Any],
) -> dict[str, dict[str, float]]:
    """Resolve one registered source-region profile against frozen geometry."""

    if (
        source_region_profile.get("role")
        != "layout_resolved_source_region_diagnostic"
        or source_region_profile.get("event") != "pre_pulse_state"
        or source_region_profile.get("selection_uses_detector_outcome") is not False
        or set(source_region_profile.get("axes", {})) != {"x", "y", "z"}
    ):
        raise ContractError("real-field pulse source-region profile differs")
    source = geometry.get("particle_source", {})
    bounds: dict[str, dict[str, float]] = {}
    for axis in ("x", "y", "z"):
        specification = source_region_profile["axes"][axis]
        width_keys = {"full_width_mm", "full_width_binding"} & set(specification)
        if (
            set(specification) != {"center_binding", *width_keys}
            or len(width_keys) != 1
            or specification["center_binding"]
            != f"particle_source.center_{axis}_mm"
        ):
            raise ContractError("source-region axis binding differs")
        center = float(source[f"center_{axis}_mm"])
        if "full_width_binding" in specification:
            binding = specification["full_width_binding"]
            if binding != f"particle_source.size_{axis}_mm":
                raise ContractError("source-region width binding differs")
            width = float(source[f"size_{axis}_mm"])
        else:
            width = float(specification["full_width_mm"])
        if not math.isfinite(center) or not math.isfinite(width) or width <= 0:
            raise ContractError("source-region bounds must be finite and positive")
        bounds[axis] = {
            "center_mm": center,
            "full_width_mm": width,
            "minimum_mm": center - width / 2.0,
            "maximum_mm": center + width / 2.0,
        }
    return bounds


def select_detector_blind_real_field_pulse_time(
    rows: list[dict[str, str]],
    geometry: dict[str, Any],
    source_region_profile: dict[str, Any],
    *,
    candidate_times_us: list[float],
    frozen_particle_ids: list[int],
    ballistic_seed_time_us: float,
) -> dict[str, Any]:
    """Rank real pre-pulse states on a frozen detector-blind time grid.

    Every registered time must contain the exact same ordered particle-ID set. Pulse
    eligibility follows the existing open Stage-1 definition; normalized XYZ moments
    use the complete frozen cohort and the registered source-region half widths.
    """

    bounds = resolve_source_region_bounds(geometry, source_region_profile)
    times = [float(value) for value in candidate_times_us]
    if (
        not times
        or any(not math.isfinite(value) for value in times)
        or any(right <= left for left, right in zip(times, times[1:]))
    ):
        raise ContractError("real-field pulse candidate times must be strictly increasing")
    seed = float(ballistic_seed_time_us)
    if not math.isfinite(seed):
        raise ContractError("real-field pulse ballistic seed must be finite")
    expected_ids = [int(value) for value in frozen_particle_ids]
    if (
        not expected_ids
        or expected_ids != sorted(expected_ids)
        or len(set(expected_ids)) != len(expected_ids)
        or any(value <= 0 for value in expected_ids)
    ):
        raise ContractError("real-field pulse frozen particle IDs are invalid")
    expected_id_set = set(expected_ids)

    dimensions = geometry.get("geometry_mm", {})
    coordinate = geometry.get("coordinate_convention", {})
    repeller_z = float(dimensions["accelerator_repeller_z"])
    grid1_z = float(dimensions["accelerator_grid1_z"])
    bore_half = float(dimensions["accelerator_bore_half"])
    axis_x = float(coordinate["accelerator_axis_x"])
    axis_y = float(coordinate.get("accelerator_axis_y", 0.0))
    if not (
        all(math.isfinite(value) for value in (repeller_z, grid1_z, bore_half, axis_x, axis_y))
        and repeller_z < grid1_z
        and bore_half > 0.0
    ):
        raise ContractError("real-field pulse accelerator acceptance geometry is invalid")

    grouped: dict[int, dict[int, dict[str, float | int]]] = {
        index: {} for index in range(1, len(times) + 1)
    }
    for row in rows:
        sample_index_value = float(row["sample_index"])
        if (
            not math.isfinite(sample_index_value)
            or not sample_index_value.is_integer()
            or not 1 <= sample_index_value <= len(times)
        ):
            raise ContractError("real-field pulse state sample index is invalid")
        sample_index = int(sample_index_value)
        candidate_time_us = times[sample_index - 1]
        instrument_time_us = float(row["instrument_time_us"])
        actual_time_us = float(row["actual_instrument_time_us"])
        tolerance_us = 1e-12 * max(1.0, abs(candidate_time_us))
        if (
            row["event"] != "pre_pulse_time_series_state"
            or row.get("survival_status") != "alive"
            or not math.isfinite(instrument_time_us)
            or not math.isfinite(actual_time_us)
            or abs(instrument_time_us - candidate_time_us) > tolerance_us
            or abs(actual_time_us - candidate_time_us) > tolerance_us
        ):
            raise ContractError("real-field pulse state event/time landing differs")
        particle_id_value = float(row["particle_id"])
        if (
            not math.isfinite(particle_id_value)
            or not particle_id_value.is_integer()
            or particle_id_value <= 0
        ):
            raise ContractError("real-field pulse state particle ID is invalid")
        particle_id = int(particle_id_value)
        if particle_id not in expected_id_set:
            raise ContractError("real-field pulse state particle is outside frozen IDs")
        if particle_id in grouped[sample_index]:
            raise ContractError("real-field pulse state duplicates a time/particle pair")
        state = {
            "particle_id": particle_id,
            "actual_instrument_time_us": actual_time_us,
            "x_mm": float(row["x_mm"]),
            "y_mm": float(row["y_mm"]),
            "z_mm": float(row["z_mm"]),
        }
        if any(not math.isfinite(float(state[key])) for key in ("x_mm", "y_mm", "z_mm")):
            raise ContractError("real-field pulse state contains non-finite coordinates")
        grouped[sample_index][particle_id] = state

    observed_indices_by_id = {
        particle_id: [
            sample_index for sample_index in range(1, len(times) + 1)
            if particle_id in grouped[sample_index]
        ]
        for particle_id in expected_ids
    }
    if any(
        indices != list(range(1, len(indices) + 1))
        for indices in observed_indices_by_id.values()
    ):
        raise ContractError("real-field pulse particle samples are not an alive prefix")

    candidates: list[dict[str, Any]] = []
    prior_alive_ids = set(expected_ids)
    for sample_index, time_us in enumerate(times, start=1):
        states_by_id = grouped[sample_index]
        alive_ids = sorted(states_by_id)
        if not set(alive_ids).issubset(prior_alive_ids):
            raise ContractError("real-field pulse particle reappears after physical loss")
        prior_alive_ids = set(alive_ids)
        missing_ids = sorted(expected_id_set - set(alive_ids))
        if not alive_ids:
            # Complete physical loss at a late registered sample is informative
            # census data, not a malformed earlier pulse candidate.  It is kept
            # in the screening receipt and omitted from the rankable candidates.
            continue
        states = [states_by_id[particle_id] for particle_id in alive_ids]
        bore_ids = [
            int(state["particle_id"])
            for state in states
            if abs(float(state["x_mm"]) - axis_x) < bore_half
            and abs(float(state["y_mm"]) - axis_y) < bore_half
        ]
        bore_id_set = set(bore_ids)
        eligible_ids = [
            int(state["particle_id"])
            for state in states
            if int(state["particle_id"]) in bore_id_set
            and repeller_z < float(state["z_mm"]) < grid1_z
        ]
        pulse_noneligible_ids = sorted(expected_id_set - set(eligible_ids))
        transverse_nonbore_ids = sorted(expected_id_set - set(bore_ids))
        source_region_ids = [
            int(state["particle_id"])
            for state in states
            if all(
                bounds[axis]["minimum_mm"]
                <= float(state[f"{axis}_mm"])
                <= bounds[axis]["maximum_mm"]
                for axis in ("x", "y", "z")
            )
        ]
        normalized_centroid: dict[str, float] = {}
        normalized_spread: dict[str, float] = {}
        for axis in ("x", "y", "z"):
            values = [float(state[f"{axis}_mm"]) for state in states]
            half_width = bounds[axis]["full_width_mm"] / 2.0
            normalized_centroid[axis] = (
                statistics.fmean(values) - bounds[axis]["center_mm"]
            ) / half_width
            normalized_spread[axis] = statistics.pstdev(values) / half_width
        candidates.append({
            "sample_index": sample_index,
            "candidate_time_us": time_us,
            "offset_from_ballistic_seed_us": time_us - seed,
            "frozen_particle_ids": expected_ids,
            "alive_particle_ids": alive_ids,
            "missing_particle_ids": missing_ids,
            "pulse_eligible_ids": eligible_ids,
            "pulse_noneligible_ids": pulse_noneligible_ids,
            "transverse_bore_ids": bore_ids,
            "transverse_nonbore_ids": transverse_nonbore_ids,
            "source_region_ids": source_region_ids,
            "population_count": len(expected_ids),
            "alive_count": len(alive_ids),
            "missing_count": len(missing_ids),
            "pulse_eligible_count": len(eligible_ids),
            "pulse_noneligible_count": len(pulse_noneligible_ids),
            "transverse_bore_count": len(bore_ids),
            "transverse_nonbore_count": len(transverse_nonbore_ids),
            "source_region_count": len(source_region_ids),
            "normalized_xyz_centroid": normalized_centroid,
            "normalized_xyz_centroid_distance": math.sqrt(
                sum(value * value for value in normalized_centroid.values())
            ),
            "normalized_xyz_spread": normalized_spread,
            "normalized_xyz_spread_norm": math.sqrt(
                sum(value * value for value in normalized_spread.values())
            ),
            "actual_instrument_time_us": {
                "minimum": min(
                    float(state["actual_instrument_time_us"]) for state in states
                ),
                "maximum": max(
                    float(state["actual_instrument_time_us"]) for state in states
                ),
                "maximum_absolute_candidate_error_us": max(
                    abs(float(state["actual_instrument_time_us"]) - time_us)
                    for state in states
                ),
                "tolerance_us": 1e-12 * max(1.0, abs(time_us)),
            },
        })
    if not candidates:
        raise ContractError("real-field pulse screen has no alive states")
    if not any(int(item["pulse_eligible_count"]) > 0 for item in candidates):
        raise ContractError("real-field pulse screen has no pulse-eligible states")
    candidates.sort(key=lambda item: (
        -int(item["pulse_eligible_count"]),
        -int(item["transverse_bore_count"]),
        float(item["normalized_xyz_centroid_distance"]),
        float(item["normalized_xyz_spread_norm"]),
        abs(float(item["offset_from_ballistic_seed_us"])),
        float(item["candidate_time_us"]),
    ))
    return {
        "selection_order": [
            "maximize_pulse_eligible_count",
            "maximize_transverse_bore_count",
            "minimize_normalized_xyz_centroid_distance",
            "minimize_normalized_xyz_spread_norm",
            "minimize_absolute_distance_to_ballistic_seed",
            "select_earlier_time",
        ],
        "selection_uses_detector_outcome": False,
        "detector_results_used": False,
        "ballistic_seed_time_us": seed,
        "source_region_bounds": bounds,
        "population_denominator_count": len(expected_ids),
        "selected_time_us": float(candidates[0]["candidate_time_us"]),
        "candidates_ranked": candidates,
    }


def derive_pulse_schedule(
    state_path: Path,
    resolved_connection: dict[str, Any],
    geometry: dict[str, Any],
    profile: dict[str, Any],
    *,
    campaign_id: str,
    experiment_id: str,
    experiment_row_sha256: str,
    population_declaration_sha256: str,
    policy: dict[str, Any],
    rf_frequency_hz: float,
) -> dict[str, Any]:
    if policy.get("policy_id") != "multipole_handoff_ballistic_centroid_v1":
        raise ContractError("single-flight pulse policy is unsupported")
    pulse_offset_rf_periods = float(policy["offset_rf_periods"])
    pulse_width_us = float(policy["pulse_width_us"])
    if not math.isfinite(pulse_offset_rf_periods) or not (
        -0.5 <= pulse_offset_rf_periods <= 0.5
    ):
        raise ContractError("single-flight pulse RF-period offset is outside contract")
    if not math.isfinite(pulse_width_us) or pulse_width_us <= 0.0:
        raise ContractError("single-flight pulse width must be positive")
    if not math.isfinite(rf_frequency_hz) or rf_frequency_hz <= 0.0:
        raise ContractError("pulse schedule requires a positive RF frequency")
    with state_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [
            row for row in csv.DictReader(handle)
            if row["event"] == "handoff" and row["status"] == "transmitted"
        ]
    if not rows:
        raise ContractError("no transmitted multipole handoff states are available")
    projected = project_handoff_through_connector(rows, resolved_connection, geometry)
    center = projected["aperture_center_mm"]
    cohort = projected["finite_wall_survivors"]
    if not cohort:
        raise ContractError("finite-wall prediction leaves no pulse-scheduling particles")
    mean_vx = sum(float(item["vx_m_s"]) for item in cohort) / len(cohort)
    mean_vx_t = sum(
        float(item["vx_m_s"]) * float(item["entry_time_us"]) for item in cohort
    ) / len(cohort)
    target_x = float(geometry["particle_source"]["center_x_mm"])
    pulse_time = (1000.0 * (target_x - center[0]) + mean_vx_t) / mean_vx
    base_pulse_time = pulse_time
    base_predicted = [
        center[0] + float(item["vx_m_s"]) *
        (base_pulse_time - float(item["entry_time_us"])) / 1000.0
        for item in cohort
    ]
    base_centroid_error = sum(base_predicted) / len(base_predicted) - target_x
    if not math.isclose(base_centroid_error, 0.0, rel_tol=0, abs_tol=1e-9):
        raise ContractError("derived single-flight pulse does not center the cohort")
    pulse_offset_us = (
        pulse_offset_rf_periods * 1.0e6 / float(rf_frequency_hz)
        if pulse_offset_rf_periods != 0.0
        else 0.0
    )
    pulse_time += pulse_offset_us
    predicted = [
        center[0] + float(item["vx_m_s"]) *
        (pulse_time - float(item["entry_time_us"])) / 1000.0
        for item in cohort
    ]
    centroid_error = sum(predicted) / len(predicted) - target_x
    return {
        "schema_version": 1,
        "role": "rf_oatof_resolved_single_flight_pulse_schedule",
        "campaign_id": campaign_id,
        "experiment_id": experiment_id,
        "experiment_row_sha256": experiment_row_sha256,
        "population_declaration_sha256": population_declaration_sha256,
        "policy": {
            "policy_id": policy["policy_id"],
            "offset_rf_periods": pulse_offset_rf_periods,
            "pulse_width_us": pulse_width_us,
        },
        "rf_period_us": 1.0e6 / rf_frequency_hz,
        "pulse_base_time_us": base_pulse_time,
        "pulse_offset_us": pulse_offset_us,
        "pulse_effective_time_us": pulse_time,
        "pulse_width_us": pulse_width_us,
        "layout_profile_id": profile["layout_profile_id"],
        "method": profile["pulse_timing_method"],
        "source_state_path": str(state_path.resolve()),
        "source_state_sha256": file_sha256(state_path),
        "population_counts": {
            "transmitted_handoff": len(rows),
            "predicted_finite_wall_survivors": len(cohort),
        },
        "selected_particle_ids": [int(item["particle_id"]) for item in cohort],
        "mean_entry_time_us": sum(float(item["entry_time_us"]) for item in cohort) / len(cohort),
        "mean_velocity_x_m_s": mean_vx,
        "mean_kinetic_energy_eV": sum(float(item["energy_eV"]) for item in cohort) / len(cohort),
        "target_centroid_x_mm": target_x,
        "entry_surface_x_mm": center[0],
        "base_predicted_centroid_error_x_mm": base_centroid_error,
        "predicted_centroid_error_x_mm": centroid_error,
        "claim_status": profile["claim_status"],
    }
