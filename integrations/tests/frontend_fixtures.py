"""Synthetic inputs shared by root integration tests.

These fixtures deliberately model compact provider contracts.  They are test
inputs only; no execution workflow or qualification run consumes them.
"""

from __future__ import annotations

import copy
import math
from typing import Any
from common.contracts.machine_contracts import ContractError, validate_schema
from projects.single_reflection_oa_tof_mass_analyzer.analysis.compile_candidate_design import (
    compile_design_overrides,
    derive_accelerator_outer_envelope_min_z,
    derive_shield_bounds,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import (
    derive_simion_geometry,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.finite_interval_design_compiler import (
    compile_finite_interval_oatof_design,
)

def canonical_frontend_fixture() -> tuple[dict, dict, dict]:
    """Return an artifact-free two-zone provider contract."""
    from projects.rf_multipole_ion_optics.core.round_rod_geometry import build_rod_array
    from projects.orthogonal_accelerator.simion.two_zone_candidate import (
        resolve_closed_two_zone_electrodes,
    )

    requirements = dict(schema_version=2, role="orthogonal_accelerator_two_zone_requirements", variant_id="two_zone",
                        acceleration_direction="-z", source_cylinder=dict(radius_mm=1, height_mm=5),
                        focus=dict(mode="two_zone_time_focus", focus_plane="test_plane"),
                        compaction=dict(axes=["y", "z"], objective="minimize_subject_to_focus"),
                        local_pa=dict(span_mm=[64, 64, 84], mesh_mm_per_gu=[.25, .25, .1], exit_z_mm=6, margin_z_mm=6),
                        placement=dict(focus_y_mm=0, global_repeller_z_mm=34, global_exit_z_mm=0),
                        side_entry=dict(face="negative_y", half_width_x_mm=1.5, half_width_z_mm=1.4))
    resolved = resolve_closed_two_zone_electrodes(requirements)
    ids = {15: 9, 22: 10, 23: 11, 24: 27, **{26 + i: 12 + i for i in range(15)}}
    volts = {15: 0.0, 22: 4400.0, 23: 4000.0, 24: 0.0,
             **{int(row["id"]): 4000 * (row["center_z_mm"] - 6) / 30 for row in resolved.rings}}
    component = dict(schema_version=1, role="rf_oatof_accelerator_component", variant_id="two_zone",
                     geometry_profile_id="closed_two_zone_compact_mr_axial_r3_gap1_4mm", requirements=requirements,
                     transform=dict(rotation=[[0, 1, 0], [1, 0, 0], [0, 0, -1]], translation_mm=[0, 0, 34]),
                     local_electrode_ids={str(key): value for key, value in ids.items()},
                     electrode_voltages_v={str(key): value for key, value in volts.items()},
                     pulse_voltage_policy_id="all_accelerator_electrodes_zero_before_pulse_v1")
    array = build_rod_array(radial_order_n=4, electrode_count=8, inscribed_radius_r0_mm=2,
                            rod_radius_mm=.6, rod_z_min_mm=0, rod_z_max_mm=29)
    for rod in array["rods"]:
        rod["physical_electrode_id"] = rod["rod_id"]
    upstream = dict(schema_version=1, role="ion_processor_bare_guide_interface", frame_id="multipole_cartesian_z_axis_v1",
                    length_unit="mm", rod_array=array,
                    mechanical_components=dict(shield=False, entrance_plate=False, exit_plate=False, reference_sleeve=False),
                    vacuum=dict(pressure_pa=0, collision_model="none", policy_id="native_guide_before_hp_vacuum_v1"),
                    source_envelope_bounds_mm=dict(min_mm=[-1, -1, -1.5], max_mm=[1, 1, 3.5]),
                    drive=dict(waveform="cosine", frequency_hz=3700000, phase_rad=0, rf_amplitude_v=500,
                               group_dc_v=[0, 0], common_mode_v=0, group_polarities={"1": 1, "2": -1}),
                    guide_exit_surface=dict(center_mm=[0, 0, 29], normal=[0, 0, 1]))
    connection = dict(spatial_registration=dict(rotation_upstream_to_downstream=[[0, 0, 1], [1, 0, 0], [0, 1, 0]],
                                                translation_mm=[-47, 0, 2]), connector=dict(length_mm=1))
    return upstream, connection, component


def canonical_three_zone_frontend_fixture() -> tuple[dict, dict, dict]:
    """Return a compact three-zone provider contract."""
    from projects.orthogonal_accelerator.tests.analysis.test_bare_three_zone_component import (
        three_zone_requirements_fixture,
    )

    upstream, _, _ = canonical_frontend_fixture()
    requirements = three_zone_requirements_fixture()
    geometry = requirements["geometry"]
    mapping = {1: 9, 2: 10, 3: 11, 4: 17, 5: 16, 6: 12, 7: 13, 8: 14, 9: 15}
    volts = {1: 0.0, 2: 4400.0, 3: 4000.0, 4: 1800.0, 5: 0.0}
    for physical_id, z_mm in zip(range(6, 10), geometry["ring_z_mm"]):
        left, right, start, end = (4000.0, 1800.0, 4.0, 14.0) if z_mm < 14 else (1800.0, 0.0, 14.0, 34.0)
        volts[physical_id] = left + (right - left) * (z_mm - start) / (end - start)
    component = dict(schema_version=1, role="rf_oatof_accelerator_component", variant_id="three_zone",
                     geometry_profile_id="explicit_sectioned_compact_three_zone_fixture", requirements=requirements,
                     transform=dict(rotation=[[0, 1, 0], [1, 0, 0], [0, 0, -1]], translation_mm=[0.0, -50.0, 34.0]),
                     local_electrode_ids={str(key): value for key, value in mapping.items()},
                     electrode_voltages_v={str(key): value for key, value in volts.items()},
                     pulse_voltage_policy_id="all_accelerator_electrodes_zero_before_pulse_v1")
    connection = dict(spatial_registration=dict(rotation_upstream_to_downstream=[[0, -1, 0], [0, 0, 1], [-1, 0, 0]],
                                                translation_mm=[0.0, -97.0, 32.0]), connector=dict(length_mm=1.0))
    return upstream, connection, component


def canonical_two_zone_frontend_contract() -> dict:
    """Return the two-zone provider metadata consumed by analysis fixtures."""
    from integrations.runtime.single_flight_electrode_contract import (
        TWO_ZONE_BARE_VARIANT,
        frontend_electrodes,
        resolve_two_zone_bare_pa_plus_solution_model,
    )

    electrodes = frontend_electrodes(ring_count=15, three_zone=False, variant=TWO_ZONE_BARE_VARIANT)
    planes = {"repeller": -40.0, "grid1": -36.0, "exit": -6.0}
    ring_z = [-36.0 + 30.0 * index / 16 for index in range(1, 16)]
    model = resolve_two_zone_bare_pa_plus_solution_model(electrodes, planes_global_z_mm=planes, ring_z_mm=ring_z)
    on = {str(identifier): 0.0 for identifier in range(9, 28)}
    on.update({"10": 2200.0, "11": 1900.0})
    for index, electrode_id in enumerate(electrodes["accelerator_ring_ids"], 1):
        on[str(electrode_id)] = 1900.0 * (16 - index) / 16
    local = {"planes": planes, "ring_z_mm": ring_z, "operating_voltages_v": on,
             "off_voltages_v": {key: 0.0 for key in on},
             "pulse_voltage_policy_id": "all_accelerator_electrodes_zero_before_pulse_v1",
             "actual_bounds_mm": {"x_min": -10.0, "x_max": 30.0, "y_min": -20.0, "y_max": 20.0, "z_min": -43.0, "z_max": -5.0},
             "accelerator_component": {"transform": {"translation_mm": [10.0, 2.0, 0.0]}}, "pa_plus_solution_model": model}
    frontend = {"role": "rf_oatof_simion_single_flight_frontend_contract", "frontend_variant": TWO_ZONE_BARE_VARIANT,
                "electrodes": electrodes, "accelerator_local_region": local, "pa_plus_solution_model": model,
                "source_exit_center_mm": {"x": -1.0, "y": 2.0, "z": -38.0},
                "instance_origin_mm": {"x": -10.0, "y": -20.0, "z": -43.0}}
    return frontend


def compile_direct_mr_frontend() -> dict:
    """Compile the direct-MR geometry used by rendering tests."""
    from integrations.runtime.single_flight_frontend import compile_frontend

    upstream, connection, component = canonical_frontend_fixture()
    # Mechanical exit-origin pose; the SIMION projection remains at PA z=-40.
    component["transform"] = dict(rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]], translation_mm=[0, 0, -34])
    connection["spatial_registration"] = dict(rotation_upstream_to_downstream=[[1, 0, 0], [0, 0, 1], [0, -1, 0]],
                                                translation_mm=[0, -47, -2])
    return compile_frontend(upstream, connection, cell_mm_xyz=dict(x=.1, y=.2, z=.1),
                            accelerator_component=component, target_solver_frame="mrtof_global_cartesian")[1]


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
    """Map one hash-bound three-zone Candidate into the layout surface."""

    if (
        candidate.get("role") != "oatof_three_zone_simion_candidate_resolved"
        or candidate.get("qualification") != "CANDIDATE_ONLY"
        or candidate.get("compiler_mode") not in {
            "T5_FROZEN_PRIMARY_AND_BRANCH_ONLY",
            "C3_J3_EXACT_LOCAL_DIRECTION_V1",
            "J2_REAL_FIELD_CANDIDATE_POOL_V1",
            "IDEAL_ACCEPTANCE_250MM_SELECTED_POINT_V1",
            "IDEAL_ACCEPTANCE_250MM_GRID_REALIZED_V1",
            "IDEAL_ACCEPTANCE_300MM_SELECTED_POINT_V1",
            "IDEAL_ACCEPTANCE_300MM_GRID_REALIZED_V1",
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
        raise ContractError("three-zone Candidate scientific identity differs")
    topology = candidate.get("accelerator_topology")
    if (
        not isinstance(topology, dict)
        or topology.get("topology_id") != profile["topology_id"]
    ):
        raise ContractError("three-zone Candidate topology differs")
    planes = topology.get("planes_global_z_mm", {})
    potentials = topology.get("potentials_v", {})
    plane_keys = {"repeller", "intermediate1", "intermediate2", "exit"}
    if set(planes) != plane_keys or set(potentials) != plane_keys:
        raise ContractError("three-zone Candidate planes or potentials are incomplete")
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
        raise ContractError("three-zone Candidate topology is not ordered")

    physics = candidate.get("accelerator_physics", {})
    lengths = physics.get("lengths_mm", {})
    if set(lengths) != {"d1", "d2", "d3"}:
        raise ContractError("three-zone Candidate lengths are incomplete")
    d1 = float(lengths["d1"])
    d2 = float(lengths["d2"])
    d3 = float(lengths["d3"])
    focus_drift = float(physics.get("focus_drift_after_exit_mm", math.nan))
    if not all(
        math.isfinite(value) and value > 0.0 for value in (d1, d2, d3)
    ):
        raise ContractError("three-zone Candidate lengths must be positive")
    axial_translation_z_mm = 0.0
    if candidate["compiler_mode"] in {
        "IDEAL_ACCEPTANCE_250MM_SELECTED_POINT_V1",
        "IDEAL_ACCEPTANCE_250MM_GRID_REALIZED_V1",
        "IDEAL_ACCEPTANCE_300MM_SELECTED_POINT_V1",
        "IDEAL_ACCEPTANCE_300MM_GRID_REALIZED_V1",
    }:
        source_center = float(candidate["source_identity"]["frozen_source"]["center_x_mm"])
        axial_translation_z_mm = float(base_geometry["particle_source"]["center_z_mm"]) - (
            plane_values["repeller"] + source_center
        )
        plane_values = {
            key: value + axial_translation_z_mm for key, value in plane_values.items()
        }
    for label, actual, expected in (
        ("d1", plane_values["intermediate1"] - plane_values["repeller"], d1),
        ("d2", plane_values["intermediate2"] - plane_values["intermediate1"], d2),
        ("d3", plane_values["exit"] - plane_values["intermediate2"], d3),
    ):
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-9):
            raise ContractError(f"three-zone Candidate {label} geometry differs")
    if (
        candidate["compiler_mode"] not in {
            "IDEAL_ACCEPTANCE_250MM_SELECTED_POINT_V1",
            "IDEAL_ACCEPTANCE_250MM_GRID_REALIZED_V1",
            "IDEAL_ACCEPTANCE_300MM_SELECTED_POINT_V1",
            "IDEAL_ACCEPTANCE_300MM_GRID_REALIZED_V1",
        }
        and not math.isclose(-plane_values["exit"], focus_drift, rel_tol=0.0, abs_tol=1e-9)
    ):
        raise ContractError("three-zone Candidate focus geometry differs")

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
    geom["accelerator_focus_z"] = axial_translation_z_mm
    geom["L_flight"] = focus_to_reflectron
    geometry["accelerator_topology"] = {
        "topology_id": topology["topology_id"],
        "planes_global_z_mm": dict(plane_values),
        "potentials_v": dict(potential_values),
    }
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
    # The catalog invariant uses d2/ring_count only as a non-overlap guard.
    # In the three-zone realization its physical span is zone2+zone3.
    accelerator["d1_mm"] = d1
    accelerator["d2_mm"] = total_l23
    if profile.get("design_overrides"):
        try:
            geometry, _ = compile_design_overrides(
                geometry, profile["design_overrides"]
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ContractError(
                f"three-zone realization compilation failed: {error}"
            ) from error
        # The design compiler returns a fresh resolved object.  Rebind these
        # handles before restoring the Candidate-owned longitudinal topology;
        # otherwise the restoration mutates the discarded pre-override map.
        geom = geometry["geometry_mm"]
        accelerator = geometry["geometry_derivation"]["accelerator"]
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
            "canonical_focus_z_mm": axial_translation_z_mm,
            "focus_drift_after_grid2_mm": focus_drift,
            "source_center_from_repeller_mm": source_center,
            "source_release_full_width_mm": source_width,
            "rule": (
                "Consume the hash-bound three-zone Candidate and preserve its "
                "exact four-plane topology."
            ),
            "realization_id": profile.get("accelerator_realization_id", "square_3d"),
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
                "Consume the hash-bound Candidate U_R1 and F_R2; retain "
                "the published reflectron lengths."
            ),
        }
    )
    derive_shield_bounds(
        geometry, derive_accelerator_outer_envelope_min_z(geometry)
    )
    evidence_identity = (
        {"candidate_plan_sha256": candidate["t5_evidence"]["plan_sha256"]}
        if candidate["compiler_mode"] not in {
            "IDEAL_ACCEPTANCE_250MM_SELECTED_POINT_V1",
            "IDEAL_ACCEPTANCE_250MM_GRID_REALIZED_V1",
            "IDEAL_ACCEPTANCE_300MM_SELECTED_POINT_V1",
            "IDEAL_ACCEPTANCE_300MM_GRID_REALIZED_V1",
        }
        else {
            "ideal_acceptance_selected_design_id": candidate[
                "ideal_acceptance_evidence"
            ]["selected_design_id"]
        }
    )
    compilation = {
        "method": profile["method"],
        "candidate": copy.deepcopy(candidate_binding),
        "candidate_campaign_id": candidate["campaign"]["campaign_id"],
        **evidence_identity,
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
        "accelerator_realization_id": profile.get(
            "accelerator_realization_id", "square_3d"
        ),
        "candidate_axial_translation_z_mm": axial_translation_z_mm,
        "simion_rebuild_plan": {
            "frontend_pa": True,
            "flight_tube_pa": True,
            "reflectron_pa": False,
        },
    }
    # T5 geometry was already published and can be consumed by manifest-bound
    # post-pulse restarts.  Preserve that resolved surface byte-for-byte;
    # later controlled candidate families declare their compiler identity.
    if candidate["compiler_mode"] != "T5_FROZEN_PRIMARY_AND_BRANCH_ONLY":
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
                "three-zone Candidate layout requires a hash-bound Candidate"
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
    finite_fields = {
        "finite_interval_phase_space_input",
        "finite_interval_source_full_width_mm",
        "accelerator_stage1_length_mm",
    }
    finite_interval_input_provenance = None
    if finite_fields & profile.keys():
        missing = finite_fields - profile.keys()
        if missing:
            raise ContractError(
                f"finite-interval layout {profile['layout_profile_id']} lacks explicit "
                f"inputs: {', '.join(sorted(missing))}"
            )
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
        frozen = profile["finite_interval_phase_space_input"]
        required_phase_space_keys = {
            "authority",
            "mass_to_charge_Th",
            "release_position_mm",
            "mean_initial_velocity_m_per_s",
            "velocity_slope_m_per_s_per_mm",
        }
        if (
            not isinstance(frozen, dict)
            or set(frozen) != required_phase_space_keys
            or frozen["authority"] != "solver_native_zero_mean_zero_slope"
            or float(frozen["mean_initial_velocity_m_per_s"]) != 0.0
            or float(frozen["velocity_slope_m_per_s_per_mm"]) != 0.0
            or float(frozen["mass_to_charge_Th"]) <= 0.0
            or not math.isfinite(float(frozen["release_position_mm"]))
        ):
            raise ContractError(
                "finite-interval phase-space input is not the governed zero-zero input"
            )
        stage1_length_mm = float(profile["accelerator_stage1_length_mm"])
        source_full_width_mm = float(profile["finite_interval_source_full_width_mm"])
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
            "phase_space_input": copy.deepcopy(frozen),
        }
    # The grounded connector owns a fixed mating plane.  Anchor the
    # accelerator by its negative-x shield face, not by a historical centre
    # coordinate.  This preserves the legacy placement at its legacy width
    # while keeping any controlled transverse realization connected.
    accelerator_outer_half_width = (
        float(geometry["geometry_mm"]["accelerator_bore_half"])
        + float(geometry["geometry_mm"]["accelerator_ring_width"])
        + float(geometry["geometry_mm"]["accelerator_insulation_gap"])
        + float(geometry["geometry_mm"]["accelerator_shield_wall"])
    )
    if not math.isfinite(accelerator_outer_half_width) or accelerator_outer_half_width <= 0.0:
        raise ContractError("accelerator transverse enclosure width is invalid")
    axis_x = port_x + accelerator_outer_half_width
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
        "accelerator_negative_x_face_mm": port_x,
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
    # The entry port is part of the controlled accelerator realization.  Its
    # clear radius must track the derived physical bore, otherwise a widened
    # shell can be placed at the correct plane while retaining an obsolete
    # nominal 5 mm mating aperture in the connection contract.
    port["mating_surface"]["aperture_radius_mm"] = float(
        geometry["geometry_mm"]["accelerator_bore_half"]
    )
    geometry["derived"] = derive_simion_geometry(
        geometry=geometry["geometry_mm"], coordinate=geometry["coordinate_convention"],
        build=geometry["simion_geometry_build"], marker=geometry["simion_detector_marker"],
        source=geometry["particle_source"],
    )
    return geometry, port, {
        "accelerator_axis_x_mm": axis_x,
        "detector_x_mm": detector_x,
        "entry_port_x_mm": port_x,
        "speed_scale": scale,
    }
