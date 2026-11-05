"""Synthetic inputs shared by root integration tests.

These fixtures deliberately model compact provider contracts.  They are test
inputs only; no execution workflow or qualification run consumes them.
"""

from __future__ import annotations

from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import (
    derive_simion_geometry,
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


from msplatform.components.single_reflection_oa_tof.layout import (
    _derive_three_zone_ring_placement as _derive_three_zone_ring_placement,
    _compile_three_zone_candidate as _canonical_compile_three_zone_candidate,
    compile_geometry_and_port as _canonical_compile_geometry_and_port,
)

def _design_catalog():
    from pathlib import Path
    import json
    return json.loads((Path(__file__).resolve().parents[2] / "projects/single_reflection_oa_tof_mass_analyzer/config/design_variables.json").read_text(encoding="utf-8"))

def _compile_three_zone_candidate(base_geometry, profile, candidate, candidate_binding):
    return _canonical_compile_three_zone_candidate(base_geometry, profile, candidate, candidate_binding, design_catalog=_design_catalog())

def compile_geometry_and_port(base_geometry, base_port, profile, *, three_zone_candidate=None, three_zone_candidate_binding=None):
    geometry, port, layout = _canonical_compile_geometry_and_port(base_geometry, base_port, profile, three_zone_candidate=three_zone_candidate, three_zone_candidate_binding=three_zone_candidate_binding, design_catalog=_design_catalog())
    geometry["derived"] = derive_simion_geometry(geometry=geometry["geometry_mm"], coordinate=geometry["coordinate_convention"], build=geometry["simion_geometry_build"], marker=geometry["simion_detector_marker"], source=geometry["particle_source"])
    return geometry, port, layout
