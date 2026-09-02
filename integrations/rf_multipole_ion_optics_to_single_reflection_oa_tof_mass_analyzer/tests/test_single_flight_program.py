from __future__ import annotations

import json
import copy
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.build_single_flight_program import (
    SOURCE_RELEASE_MODES,
    build_successor_program,
    load_initial_state,
    load_row_map,
    reflectron_fast_adjust_assignments,
    resolve_domain_split_program_contract,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_region_field import (
    build_resolved_region_field_contract,
)


def _pa_plus_model() -> dict:
    physical_ids = [*range(1, 9), 10, 11, 20, 17, 18, 19]
    modes = [
        {
            "mode_id": 36 + index,
            "name": f"mode_{36 + index}",
            "source_physical_electrode_id": physical_id,
            "physical_electrode_coefficients": {str(physical_id): 1.0},
        }
        for index, physical_id in enumerate(physical_ids)
    ]
    return {
        "schema_version": 1,
        "model_id": "three_zone_linear_ring_pa_plus_v1",
        "voltage_control_policy": {
            "policy_id": "three_zone_linear_ring_interpolation_v1",
            "independent_accelerator_electrode_ids": [10, 11, 20, 17],
            "derived_accelerator_ring_ids": [12, 13, 14, 15, 16],
            "per_ring_independent_adjustment_supported": False,
        },
        "mode_ids": list(range(36, 50)),
        "mode_count": 14,
        "modes": modes,
        "grounded_physical_electrode_ids": [9],
    }
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_electrode_contract import (
    FRONTEND_ELECTRODES,
    THREE_ZONE_FRONTEND_ELECTRODES,
    resolve_frontend_electrode_topology,
)


REPO = Path(__file__).resolve().parents[3]
RF_DRIVE_KERNEL_SOURCE = (
    REPO / "common/multipole/simion_rf_drive.lua"
).read_text(encoding="utf-8")
ANALYZER_COMPONENT_SOURCE = (
    REPO / "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/"
    "candidates/oatof_analyzer_component.lua"
).read_text(encoding="utf-8")
PULSE_HOOK_SOURCE = (
    REPO / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
    "runtime/single_flight_pulse_hook.lua"
).read_text(encoding="utf-8")
FRONTEND_HOOK_SOURCE = (
    REPO / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
    "runtime/single_flight_frontend_hook.lua"
).read_text(encoding="utf-8")
SIMION = Path(r"C:\Program Files\SIMION-2020\simion.exe")
CALLBACK_HARNESS = Path(__file__).with_name("test_single_flight_program_callbacks.lua")
CALLBACK_TEST_CONTROL = """
segment.__successor_test_set_adjustable=function(name,value)
  assert(type(name)=='string' and type(value)=='number')
  if name=='handoff_pulse_mode' then handoff_pulse_mode=value
  elseif name=='handoff_pulse_time_us' then handoff_pulse_time_us=value
  elseif name=='handoff_pulse_width_us' then handoff_pulse_width_us=value
  elseif name=='trajectory_log_enable' then trajectory_log_enable=value
  else error('test adjustable name is not authorized: '..name) end
end
segment.__successor_test_get_value=function(name)
  if name=='V_repeller' then return V_repeller
  elseif name=='V_grid1' then return V_grid1
  elseif name=='accelerator_grid1_z_mm' then return accelerator_grid1_z_mm
  elseif name=='accelerator_grid2_z_mm' then return accelerator_grid2_z_mm
  elseif name=='accelerator_repeller_front_z_mm' then return accelerator_repeller_front_z_mm
  else error('test value name is not authorized: '..tostring(name)) end
end
"""

def _successor_callback_program(
    directory: Path,
    *,
    profile_id: str = "accelerator_real_pa",
    overlay: dict[str, object] | None = None,
    pre_pulse_time_series_contract: dict[str, object] | None = None,
    rf_steps_per_period: int = 160,
    source_release_mode: str | None = None,
) -> str:
    geometry_path = REPO / (
        "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
    )
    oatof = json.loads(geometry_path.read_text(encoding="utf-8"))
    upstream, frontend = _minimal_program_contracts()
    region = build_resolved_region_field_contract(
        geometry_path, directory / "successor_resolved_region.json", profile_id
    )
    return build_successor_program(
        upstream,
        frontend,
        oatof,
        region,
        birth_times_us=[0.25, 1.0],
        analyzer_component_source=ANALYZER_COMPONENT_SOURCE,
        pulse_hook_source=PULSE_HOOK_SOURCE,
        frontend_hook_source=FRONTEND_HOOK_SOURCE,
        rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
        source_release_mode=source_release_mode,
        rf_steps_per_period=rf_steps_per_period,
        overlay=overlay,
        pre_pulse_time_series_contract=pre_pulse_time_series_contract,
    ) + CALLBACK_TEST_CONTROL


def _minimal_program_contracts() -> tuple[dict[str, object], dict[str, object]]:
    upstream = {
        "role": "multipole_resolved_design_do_not_edit",
        "drive": {
            "waveform": "cosine",
            "rf_amplitude_V_zero_to_peak_per_group": 100.0,
            "dc_amplitude_V_per_group": 0.0,
            "common_mode_offset_V": 0.0,
            "frequency_Hz": 1.0e6,
            "phase_rad": 0.0,
        },
        "segmentation": {
            "segmented_rod_array": {
                "segment_count": 4,
                "electrodes": [
                    {
                        "electrode_id": electrode_id,
                        "electrode_group": 1 + electrode_id % 2,
                        "center_x_mm": float(electrode_id),
                        "center_y_mm": 0.0,
                        "z_min_mm": 0.0,
                        "z_max_mm": 1.0,
                        "radius_mm": 0.5,
                    }
                    for electrode_id in range(1, 9)
                ]
            }
        },
        "axial_dc": {
            "upstream_shield_potential_V": 0.0,
            "rod_electrodes": [
                {"electrode_id": electrode_id, "potential_V": 0.0}
                for electrode_id in range(1, 9)
            ],
            "entrance_reference_sleeve": {"potential_V": 0.0},
            "entrance_plate_potential_V": 0.0,
        },
    }
    frontend = {
        "role": "rf_oatof_simion_single_flight_frontend_contract",
        "junction_enclosure": {"shield_potential_V": 0.0},
        "instance_origin_mm": {"x": 0.0, "y": 0.0, "z": 0.0},
        "source_exit_center_mm": {"x": -1.0, "y": 0.0, "z": 0.0},
        "electrodes": copy.deepcopy(FRONTEND_ELECTRODES),
    }
    return upstream, frontend


class SingleFlightProgramTests(unittest.TestCase):
    def test_domain_accelerator_filename_drives_analyzer_and_iob_contracts(self) -> None:
        source = (
            REPO
            / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
            / "runtime/build_single_flight_program.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'analyzer_config["instance_filenames"]["accelerator"] = (\n'
            "        domain_accelerator_filename",
            source,
        )

    def test_analyzer_component_accepts_the_published_three_zone_topology(self) -> None:
        self.assertIn(
            "config.accelerator_topology_id == 'three_zone_frontend_v1'",
            ANALYZER_COMPONENT_SOURCE,
        )

    def test_long_connector_contract_requires_disjoint_fine_pa_endpoints(self) -> None:
        split = {
            "connector_length_mm": 98.4,
            "terminal_end_x_mm": 1.6,
            "upstream_end_x_mm": 11.6,
            "accelerator_start_x_mm": 90.0,
            "coarse_sleeve_x_min_mm": 11.6,
            "coarse_sleeve_x_max_mm": 90.0,
            "endpoint_guard_mm": 10.0,
            "partition_policy_id": "grounded_sleeve_disjoint_fine_domains_v1",
        }
        upstream = {
            "role": "rf_oatof_simion_upstream_bridge_contract",
            "status": "bridge_coupling_required",
            "domain_split": split,
            "instance_bounds_mm": {"x_min": -100.0, "x_max": 11.6},
            "instance_origin_mm": {"x": -100.0, "y": -10.0, "z": -10.0},
        }
        accelerator = {
            "role": "rf_oatof_simion_accelerator_main_contract",
            "status": "bridge_coupling_required",
            "domain_split": split,
            "instance_bounds_mm": {"x_min": 90.0, "x_max": 125.0},
            "instance_origin_mm": {"x": 90.0, "y": -10.0, "z": -350.0},
            "pa_plus_solution_model": _pa_plus_model(),
        }
        resolved = resolve_domain_split_program_contract(upstream, accelerator)
        self.assertEqual(resolved["upstream_end_x_mm"], 11.6)
        self.assertEqual(resolved["accelerator_start_x_mm"], 90.0)
        self.assertGreater(
            resolved["accelerator_start_x_mm"], resolved["upstream_end_x_mm"]
        )
        accelerator["instance_bounds_mm"]["x_min"] = 89.9
        with self.assertRaisesRegex(ValueError, "must start"):
            resolve_domain_split_program_contract(upstream, accelerator)

    def test_domain_split_pre_pulse_program_uses_coarse_and_disjoint_fine_roles(self) -> None:
        topology = {
            "topology_id": "three_zone_accelerator_ideal_v1",
            "planes_global_z_mm": {
                "repeller": -19.9, "intermediate1": -16.9,
                "intermediate2": -11.6, "exit": -0.1,
            },
            "potentials_v": {
                "repeller": 2000.0, "intermediate1": 1750.0,
                "intermediate2": 1450.0, "exit": 0.0,
            },
        }
        geometry_path = REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
        oatof = json.loads(geometry_path.read_text(encoding="utf-8"))
        oatof["accelerator_topology"] = topology
        upstream, frontend = _minimal_program_contracts()
        frontend["accelerator_topology_id"] = topology["topology_id"]
        frontend["electrodes"] = copy.deepcopy(THREE_ZONE_FRONTEND_ELECTRODES)
        frontend["accelerator_local_region"] = {
            "intermediate2_grid_provider": "accelerator_overlay",
            "ring_z_mm": [-14.2, -9.3, -7.0, -4.7, -2.4],
        }
        region = build_resolved_region_field_contract(
            geometry_path, Path(tempfile.gettempdir()) / "domain_split_region.json",
            "accelerator_ideal_three_zone_real_reflectron", accelerator_topology=topology,
        )
        domain = {
            "upstream_instance_index": 2, "accelerator_instance_index": 3,
            "upstream_end_x_mm": 11.6, "accelerator_start_x_mm": 90.0,
            "upstream_bounds_mm": {"x_min": -100.0, "x_max": 11.6},
            "accelerator_bounds_mm": {"x_min": 90.0, "x_max": 125.0},
            "upstream_origin_mm": {"x": -100.0, "y": -10.0, "z": -10.0},
            "accelerator_origin_mm": {"x": 90.0, "y": -10.0, "z": -20.0},
            "pa_plus_solution_model": _pa_plus_model(),
            "accelerator_zero_field": True,
        }
        intermediate = {
            "role": "rf_oatof_simion_accelerator_overlay_contract",
            "region_id": "intermediate2",
            "cell_mm_xyz": {"x": 0.2, "y": 0.2, "z": 0.05},
            "instance_origin_mm": {"x": 90.0, "y": -1.0, "z": -13.6},
            "active_bounds_mm": {"x_min": 89.9, "x_max": 91.0, "y_min": -1.0, "y_max": 1.0, "z_min": -13.5, "z_max": -9.5},
        }
        screening = {
            "schema_version": 5,
            "role": "rf_oatof_pre_pulse_time_series_screening_contract",
            "mode": "real_pa_rf_pre_pulse_time_series",
            "active_scope": "pre_pulse_frontend_accelerator",
            "pulse_disabled": True, "terminate_at_window_end": True,
            "resolution_claim_allowed": False,
            "prohibited_outputs": ["detector_crossing", "resolution_metrics", "single_flight_spatial_six_panel"],
            "sample_times_us": [1.0],
        }
        program = build_successor_program(
            upstream, frontend, oatof, region, birth_times_us=[0.25],
            analyzer_component_source=ANALYZER_COMPONENT_SOURCE,
            pulse_hook_source=PULSE_HOOK_SOURCE,
            frontend_hook_source=FRONTEND_HOOK_SOURCE,
            rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
            pre_pulse_time_series_contract=screening,
            intermediate_overlay=intermediate, domain_split=domain,
        )
        self.assertIn("coarse_frontend=1", program)
        self.assertIn("upstream_bridge=2", program)
        self.assertIn("accelerator=3", program)
        self.assertIn("single_flight_accelerator_instance_index=3", program)
        self.assertNotIn("accelerator_intermediate_overlay=6", program)
        self.assertIn("single_flight_pre_pulse_collision_only=0", program)
        self.assertIn("single_flight_pre_pulse_accelerator_zero_field=1", program)
        self.assertIn("single_flight_active_field_instances={1,2}", program)
        self.assertIn("single_flight_pre_pulse_scope_instances={1,2,3}", program)
        self.assertIn('pre_pulse_active_roles={"coarse_frontend","upstream_bridge","accelerator"}', program)
        self.assertIn('upstream_bridge="upstream_bridge.pa0"', program)
        self.assertIn('accelerator="accelerator_entrance_zero_field.pa0"', program)
        self.assertIn("single_flight_pre_pulse_accelerator_zero_field==0 and #single_flight_pa_plus_modes==0", program)
        domain["pa_plus_solution_model"] = None
        zero_field_without_pa_plus_metadata = build_successor_program(
            upstream, frontend, oatof, region, birth_times_us=[0.25],
            analyzer_component_source=ANALYZER_COMPONENT_SOURCE,
            pulse_hook_source=PULSE_HOOK_SOURCE,
            frontend_hook_source=FRONTEND_HOOK_SOURCE,
            rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
            pre_pulse_time_series_contract=screening,
            intermediate_overlay=intermediate, domain_split=domain,
        )
        self.assertIn("single_flight_pa_plus_modes={}", zero_field_without_pa_plus_metadata)
        domain["pa_plus_solution_model"] = _pa_plus_model()
        full_flight_program = build_successor_program(
            upstream, frontend, oatof, region, birth_times_us=[0.25],
            analyzer_component_source=ANALYZER_COMPONENT_SOURCE,
            pulse_hook_source=PULSE_HOOK_SOURCE,
            frontend_hook_source=FRONTEND_HOOK_SOURCE,
            rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
            intermediate_overlay=intermediate, domain_split=domain,
        )
        self.assertIn("coarse_frontend=1", full_flight_program)
        self.assertIn('flight_tube="flight_tube_ground.pa0"', full_flight_program)
        self.assertIn("flight_tube=4", full_flight_program)
        self.assertIn("reflectron=5", full_flight_program)
        self.assertIn("detector=7", full_flight_program)
        self.assertIn("upstream_bridge=2", full_flight_program)
        self.assertIn("accelerator_intermediate_overlay=6", full_flight_program)
        self.assertIn(
            "single_flight_active_field_instances={1,2,3,6}",
            full_flight_program,
        )
        self.assertIn("active_scope=='pre_pulse_frontend_accelerator'", full_flight_program)
        self.assertIn("or 'full_flight'", full_flight_program)
        self.assertIn("TRACE: detector_crossing", full_flight_program)

    def test_domain_split_entrance_local_reuses_slot6_and_main_electrode_plan(self) -> None:
        topology = {
            "topology_id": "three_zone_accelerator_ideal_v1",
            "planes_global_z_mm": {
                "repeller": -19.9, "intermediate1": -16.9,
                "intermediate2": -11.6, "exit": -0.1,
            },
            "potentials_v": {
                "repeller": 2000.0, "intermediate1": 1750.0,
                "intermediate2": 1450.0, "exit": 0.0,
            },
        }
        geometry_path = REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
        oatof = json.loads(geometry_path.read_text(encoding="utf-8"))
        oatof["accelerator_topology"] = topology
        upstream, frontend = _minimal_program_contracts()
        frontend["accelerator_topology_id"] = topology["topology_id"]
        frontend["electrodes"] = copy.deepcopy(THREE_ZONE_FRONTEND_ELECTRODES)
        frontend["accelerator_local_region"] = {
            "intermediate2_grid_provider": "accelerator_overlay",
            "ring_z_mm": [-14.2, -9.3, -7.0, -4.7, -2.4],
        }
        domain = {
            "upstream_instance_index": 2, "accelerator_instance_index": 3,
            "upstream_end_x_mm": 11.6, "accelerator_start_x_mm": 90.0,
            "upstream_bounds_mm": {"x_min": -100.0, "x_max": 11.6},
            "accelerator_bounds_mm": {"x_min": 90.0, "x_max": 125.0},
            "upstream_origin_mm": {"x": -100.0, "y": -10.0, "z": -10.0},
            "accelerator_origin_mm": {"x": 90.0, "y": -10.0, "z": -20.0},
            "pa_plus_solution_model": _pa_plus_model(),
        }
        local = {
            "schema_version": 1,
            "role": "rf_oatof_simion_accelerator_entrance_aperture_local_contract",
            "cell_mm_xyz": {"x": 0.25, "y": 0.25, "z": 0.1},
            "instance_origin_mm": {"x": 90.0, "y": -8.0, "z": -20.0},
            "active_bounds_mm": {
                "x_min": 90.25, "x_max": 101.75,
                "y_min": -7.75, "y_max": 7.75,
                "z_min": -19.9, "z_max": -15.9,
            },
            "electrodes": copy.deepcopy(THREE_ZONE_FRONTEND_ELECTRODES),
            "pa_plus_solution_model": _pa_plus_model(),
            "boundary_condition": {
                "mode": "accelerator_main_electrode_basis_dirichlet_v1",
                "source_role": "rf_oatof_simion_accelerator_main_contract",
                "basis_electrode_ids": list(range(21)),
                "pa_plus_mode_ids": list(range(36, 50)),
            },
            "replacement_semantics": {
                "mode": "highest_priority_complete_local_replacement_v1",
                "field_superposition_prohibited": True,
                "parent_role": "rf_oatof_simion_accelerator_main_contract",
            },
        }
        intermediate = {
            "role": "rf_oatof_simion_accelerator_overlay_contract",
            "region_id": "intermediate2",
            "cell_mm_xyz": {"x": 0.2, "y": 0.2, "z": 0.05},
            "instance_origin_mm": {"x": 90.0, "y": -1.0, "z": -13.6},
            "active_bounds_mm": {
                "x_min": 89.9, "x_max": 91.0,
                "y_min": -1.0, "y_max": 1.0,
                "z_min": -13.5, "z_max": -9.5,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            region = build_resolved_region_field_contract(
                geometry_path, Path(directory) / "entrance_local_region.json",
                "accelerator_ideal_three_zone_real_reflectron",
                accelerator_topology=topology,
            )
            program, exporter = build_successor_program(
                upstream, frontend, oatof, region, birth_times_us=[0.25],
                analyzer_component_source=ANALYZER_COMPONENT_SOURCE,
                pulse_hook_source=PULSE_HOOK_SOURCE,
                frontend_hook_source=FRONTEND_HOOK_SOURCE,
                rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
                accelerator_entrance_local=local,
                domain_split=domain,
                include_total_axis_field_exporter=True,
            )
        self.assertIn("accelerator_entrance_aperture_local=6", program)
        self.assertIn(
            'accelerator_entrance_aperture_local="accelerator_entrance_local.pa0"',
            program,
        )
        self.assertNotIn("accelerator_intermediate_overlay=6", program)
        self.assertIn("detector=7", program)
        self.assertIn("single_flight_active_field_instances={1,2,3,6}", program)
        self.assertIn(
            "for _,physical_id in ipairs({1,2,3,4,5,6,7,8,10,11,12,13,14,15,16,17,18,19,20}) do",
            program,
        )
        self.assertIn(
            "if initial[physical_id]==nil then initial[physical_id]=0 end",
            program,
        )
        self.assertIn("local function single_flight_project_pa_plus(source)\n  local values={}", program)
        self.assertIn(
            "values[mode.mode_id]=assert(source[mode.source_electrode_id]", program
        )
        self.assertNotIn("total=total+term.coefficient", program)
        self.assertNotIn("for id,value in pairs(source) do values[id]=value end", program)
        self.assertIn("local single_flight_pa_plus_source={}", program)
        self.assertIn("single_flight_pa_plus_source[id]=value", program)
        self.assertIn("single_flight_pa_plus_source=initial", program)
        self.assertIn(
            "if not single_flight_is_pa_plus_instance(ion_instance) then\n"
            "    adj_elect[id]=value\n"
            "    return\n"
            "  end\n"
            "  single_flight_pa_plus_source[id]=value",
            program,
        )
        self.assertIn(
            "Never write a physical ID into a PA+ array: SIMION\n"
            "  -- treats that as an absent electrode, not as a harmless no-op.",
            program,
        )
        self.assertIn("single_flight_is_pa_plus_instance(index) and initial_pa_plus or initial", program)
        self.assertIn("single_flight_pa_plus_instance_indices={3,6}", program)
        self.assertNotIn("ipairs({1,2,3,4,5,6,7,8,9,10", program)
        self.assertIn("adjustable V_intermediate2=1450", program)
        self.assertIn(
            "single_flight_frontend.apply_at(single_flight_instrument_time_us(),single_flight_set_electrode)",
            program,
        )
        self.assertIn("if overlay.instance_index==instance_index then return overlay end", program)
        self.assertIn("ion_pz_mm<=b.z_min or ion_pz_mm>=b.z_max then ion_instance=0 end", program)
        self.assertIn("assert(#simion.wb.instances==6", exporter)
        self.assertIn("local instance_number=3", exporter)
        self.assertIn("instance_number=overlay.instance_index", exporter)
        post_pulse = build_successor_program(
            upstream, frontend, oatof, region, birth_times_us=[0.25],
            analyzer_component_source=ANALYZER_COMPONENT_SOURCE,
            pulse_hook_source=PULSE_HOOK_SOURCE,
            frontend_hook_source=FRONTEND_HOOK_SOURCE,
            rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
            source_release_mode="pre_pulse_restart",
            accelerator_entrance_local=local,
            domain_split=domain,
        )
        self.assertIn("flight_tube=1", post_pulse)
        self.assertIn("accelerator_entrance_aperture_local=5", post_pulse)
        self.assertNotIn("coarse_frontend=1", post_pulse)
        self.assertNotIn("upstream_bridge=2", post_pulse)
        self.assertIn("single_flight_active_field_instances={3,5}", post_pulse)
        self.assertIn("single_flight_post_pulse_handoff_minimal=1", post_pulse)
        local_axis_program, local_axis_exporter = build_successor_program(
            upstream, frontend, oatof, region, birth_times_us=[0.25],
            analyzer_component_source=ANALYZER_COMPONENT_SOURCE,
            pulse_hook_source=PULSE_HOOK_SOURCE,
            frontend_hook_source=FRONTEND_HOOK_SOURCE,
            rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
            accelerator_entrance_local=local,
            domain_split=domain,
            domain_split_local_axis_field=True,
            include_total_axis_field_exporter=True,
        )
        self.assertIn("accelerator_entrance_aperture_local=5", local_axis_program)
        self.assertIn("single_flight_active_field_instances={3,5}", local_axis_program)
        self.assertIn("single_flight_post_pulse_handoff_minimal=1", local_axis_program)
        self.assertIn("assert(#simion.wb.instances==5", local_axis_exporter)
        with self.assertRaisesRegex(ValueError, "only for entrance-local axis-field export"):
            build_successor_program(
                upstream, frontend, oatof, region, birth_times_us=[0.25],
                analyzer_component_source=ANALYZER_COMPONENT_SOURCE,
                pulse_hook_source=PULSE_HOOK_SOURCE,
                frontend_hook_source=FRONTEND_HOOK_SOURCE,
                rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
                accelerator_entrance_local=local,
                domain_split=domain,
                domain_split_local_axis_field=True,
            )
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            build_successor_program(
                upstream, frontend, oatof, region, birth_times_us=[0.25],
                analyzer_component_source=ANALYZER_COMPONENT_SOURCE,
                pulse_hook_source=PULSE_HOOK_SOURCE,
                frontend_hook_source=FRONTEND_HOOK_SOURCE,
                rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
                accelerator_entrance_local=local,
                intermediate_overlay=intermediate,
                domain_split=domain,
            )
        with self.assertRaisesRegex(ValueError, "ordinary domain-split full flight"):
            build_successor_program(
                upstream, frontend, oatof, region, birth_times_us=[0.25],
                analyzer_component_source=ANALYZER_COMPONENT_SOURCE,
                pulse_hook_source=PULSE_HOOK_SOURCE,
                frontend_hook_source=FRONTEND_HOOK_SOURCE,
                rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
                accelerator_entrance_local=local,
            )

    def test_pre_pulse_screening_accepts_identity_bearing_schema_v4(self) -> None:
        screening = {
            "schema_version": 4,
            "role": "rf_oatof_pre_pulse_time_series_screening_contract",
            "mode": "real_pa_rf_pre_pulse_time_series",
            "active_scope": "pre_pulse_frontend_accelerator",
            "pulse_disabled": True,
            "terminate_at_window_end": True,
            "resolution_claim_allowed": False,
            "prohibited_outputs": [
                "detector_crossing", "resolution_metrics", "single_flight_spatial_six_panel",
            ],
            "sample_times_us": [1.0],
            "identities": {"experiment_row_sha256": "A" * 64},
        }
        with tempfile.TemporaryDirectory() as directory:
            program = _successor_callback_program(
                Path(directory), pre_pulse_time_series_contract=screening
            )
        self.assertIn("pre-pulse time-series", program)

    def test_terminal_handoff_is_an_advertised_release_mode(self) -> None:
        self.assertIn("continuous_frontend_handoff", SOURCE_RELEASE_MODES)

    def test_reflectron_fast_adjust_assignments_are_python_compiled(self) -> None:
        oatof = {
            "rings": {"stage1_count": 2, "stage2_count": 3},
            "electrodes_V": {"midgrid": 120.0, "backplate": 420.0},
        }
        self.assertEqual(
            reflectron_fast_adjust_assignments(oatof),
            [
                "1=0",
                "2=40",
                "3=80",
                "4=120",
                "5=195",
                "6=270",
                "7=345",
                "8=420",
                "9=0",
            ],
        )
        for invalid in (
            {"rings": {"stage1_count": 0, "stage2_count": 3}, "electrodes_V": oatof["electrodes_V"]},
            {"rings": oatof["rings"], "electrodes_V": {"midgrid": float("nan"), "backplate": 420.0}},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    reflectron_fast_adjust_assignments(invalid)

    def test_runner_passes_release_mode_and_omits_rf_cap_for_pre_pulse_restart(self) -> None:
        runner = (
            REPO
            / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
            / "runtime/run_single_flight.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("'--source-release-mode',$sourceReleaseMode", runner)
        self.assertIn("if (-not $isPrePulseRestart)", runner)
        self.assertIn('"single_flight_rf_steps={0}" -f $rfStepsPerPeriod', runner)

    def test_pre_pulse_restart_disables_rf_drive_and_rf_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            program = _successor_callback_program(
                Path(directory), source_release_mode="pre_pulse_restart",
            )
        self.assertIn("local single_flight_rf_enabled=0", program)
        self.assertIn("rf_drive=false", program)

    def test_terminal_handoff_continuation_keeps_rf_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            program = _successor_callback_program(
                Path(directory), source_release_mode="continuous_frontend_handoff",
            )
        self.assertIn("local single_flight_rf_enabled=1", program)
        self.assertIn("single_flight_rf_kernel.new", program)
        self.assertIn("single_flight_rf_steps", program)
        self.assertIn("single_flight_frontend.apply_at", program)
        self.assertIn("single_flight_pulse.cap_timestep_at", program)

    def test_pre_pulse_time_series_uses_native_contract_dt40_landings(self) -> None:
        contract = {
            # The public family workflow currently materializes v3 contracts.
            "schema_version": 3,
            "role": "rf_oatof_pre_pulse_time_series_screening_contract",
            "mode": "real_pa_rf_pre_pulse_time_series",
            "active_scope": "pre_pulse_frontend_accelerator",
            "pulse_disabled": True,
            "terminate_at_window_end": True,
            "resolution_claim_allowed": False,
            "prohibited_outputs": [
                "detector_crossing",
                "resolution_metrics",
                "single_flight_spatial_six_panel",
            ],
            "sample_times_us": [1.0, 1.025],
        }
        with tempfile.TemporaryDirectory() as directory:
            program = _successor_callback_program(
                Path(directory), pre_pulse_time_series_contract=contract,
                rf_steps_per_period=40,
            )
        self.assertIn("adjustable handoff_pulse_mode=2", program)
        self.assertIn("assert(handoff_pulse_mode==2", program)
        self.assertNotIn("assert(handoff_pulse_mode==0", program)
        self.assertIn("existing held-off pulse mode", program)
        self.assertIn("assert(single_flight_rf_steps==40", program)
        self.assertIn("'pre_pulse_frontend_accelerator' or 'full_flight'", program)
        self.assertIn("single_flight_analyzer.initialize_workbench", program)
        self.assertNotIn("initialize_upstream_workbench", program)
        self.assertIn(
            "pre-pulse screening particle escaped its frontend/accelerator active scope",
            program,
        )
        self.assertIn("ion_time_step=next_time-time", program)
        self.assertIn(
            "pre-pulse time-series sample did not land on its native SIMION timestep",
            program,
        )
        self.assertIn("actual_instrument_time_us=%.17g", program)
        self.assertNotIn("fraction=(sample_time-p.t)", program)
        self.assertIn("TRACE: pre_pulse_screening_terminal", program)
        self.assertIn("terminal_reason=", program)
        self.assertIn("adjustable trajectory_log_enable=1", program)
        self.assertIn(
            "if single_flight_pre_pulse_time_series~=0 then\n"
            "      if rf then rf.apply_at(single_flight_instrument_time_us(),single_flight_set_electrode) end",
            program,
        )
        self.assertIn(
            "else\n"
            "      single_flight_frontend.apply_at(single_flight_instrument_time_us(),single_flight_set_electrode)",
            program,
        )
        invalid = dict(contract, pulse_disabled=False)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "contract mode differs"):
                _successor_callback_program(
                    Path(directory), pre_pulse_time_series_contract=invalid
                )

    def test_electrode_topology_registry_preserves_two_zone_and_adds_only_id_20(self) -> None:
        two_zone = resolve_frontend_electrode_topology(FRONTEND_ELECTRODES)
        self.assertEqual(two_zone["topology_id"], "two_zone_frontend_v1")
        self.assertEqual(two_zone["basis_electrode_ids"], list(range(20)))
        self.assertEqual(
            {
                key: value
                for key, value in THREE_ZONE_FRONTEND_ELECTRODES.items()
                if key != "accelerator_intermediate2_id"
            },
            FRONTEND_ELECTRODES,
        )
        three_zone = resolve_frontend_electrode_topology(
            THREE_ZONE_FRONTEND_ELECTRODES
        )
        self.assertEqual(three_zone["topology_id"], "three_zone_frontend_v1")
        self.assertEqual(three_zone["basis_electrode_ids"], list(range(21)))
        self.assertEqual(
            THREE_ZONE_FRONTEND_ELECTRODES["accelerator_intermediate2_id"], 20
        )

    def test_electrode_topology_registry_rejects_unknown_missing_and_noncontiguous(self) -> None:
        invalid = [
            {**FRONTEND_ELECTRODES, "unknown_electrode_id": 20},
            {
                key: value
                for key, value in FRONTEND_ELECTRODES.items()
                if key != "accelerator_grid2_id"
            },
            {**THREE_ZONE_FRONTEND_ELECTRODES, "accelerator_intermediate2_id": 21},
        ]
        for electrodes in invalid:
            with self.subTest(electrodes=electrodes):
                with self.assertRaisesRegex(ValueError, "derived topology"):
                    resolve_frontend_electrode_topology(electrodes)

    def test_three_zone_program_requires_overlay_and_publishes_intermediate2(self) -> None:
        topology = {
            "topology_id": "three_zone_accelerator_ideal_v1",
            "planes_global_z_mm": {
                "repeller": -19.92918680341103,
                "intermediate1": -16.87918680341103,
                "intermediate2": -11.57918680341103,
                "exit": -0.12918680341102995,
            },
            "potentials_v": {
                "repeller": 2000.0,
                "intermediate1": 1750.0,
                "intermediate2": 1450.0,
                "exit": 100.0,
            },
        }
        geometry_path = REPO / (
            "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
        )
        oatof = json.loads(geometry_path.read_text(encoding="utf-8"))
        oatof["accelerator_topology"] = copy.deepcopy(topology)
        upstream, frontend = _minimal_program_contracts()
        frontend["accelerator_topology_id"] = topology["topology_id"]
        frontend["electrodes"] = copy.deepcopy(THREE_ZONE_FRONTEND_ELECTRODES)
        frontend["accelerator_local_region"] = {
            "intermediate2_grid_provider": "accelerator_overlay",
            "ring_z_mm": [-14.5, -12.0, -9.5, -7.0, -4.5],
        }
        overlay = {
            "role": "rf_oatof_simion_accelerator_overlay_contract",
            "cell_mm_xyz": {"x": 0.2, "y": 0.2, "z": 0.025},
            "instance_origin_mm": {"x": 0.0, "y": 0.0, "z": 0.0},
            "active_bounds_mm": {
                "x_min": -1.0,
                "x_max": 1.0,
                "y_min": -1.0,
                "y_max": 1.0,
                "z_min": -20.0,
                "z_max": 1.0,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            region = build_resolved_region_field_contract(
                geometry_path,
                Path(directory) / "region.json",
                "accelerator_ideal_three_zone_real_reflectron",
                accelerator_topology=topology,
            )
            kwargs = {
                "birth_times_us": [0.25],
                "analyzer_component_source": ANALYZER_COMPONENT_SOURCE,
                "pulse_hook_source": PULSE_HOOK_SOURCE,
                "frontend_hook_source": FRONTEND_HOOK_SOURCE,
                "rf_drive_kernel_source": RF_DRIVE_KERNEL_SOURCE,
            }
            with self.assertRaisesRegex(ValueError, "requires the governed"):
                build_successor_program(
                    upstream, frontend, oatof, region, **kwargs
                )
            program = build_successor_program(
                upstream, frontend, oatof, region, overlay=overlay, **kwargs
            )
            if SIMION.is_file():
                program_path = Path(directory) / "three_zone_program.lua"
                checker_path = Path(directory) / "syntax_check.lua"
                program_path.write_text(program, encoding="utf-8", newline="\n")
                checker_path.write_text(
                    "local chunk,message=loadfile(assert(arg[1])); "
                    "assert(chunk,message); print('THREE_ZONE_PROGRAM_SYNTAX=PASS')\n",
                    encoding="utf-8",
                    newline="\n",
                )
                result = subprocess.run(
                    [
                        str(SIMION),
                        "--nogui",
                        "--noprompt",
                        "lua",
                        str(checker_path),
                        str(program_path),
                    ],
                    cwd=directory,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("THREE_ZONE_PROGRAM_SYNTAX=PASS", result.stdout)
        self.assertIn("adjustable V_intermediate2=1450", program)
        self.assertIn("adjustable V_exit=100", program)
        self.assertIn("intermediate2=20", program)
        self.assertIn(
            "planes_z_mm={accelerator_grid1_z_mm,accelerator_intermediate2_z_mm,accelerator_grid2_z_mm}",
            program,
        )
        self.assertIn("TRACE: accelerator_intermediate2_forward", program)

    def test_two_disjoint_accelerator_overlays_use_six_iob_slots(self) -> None:
        topology = {
            "topology_id": "three_zone_accelerator_ideal_v1",
            "planes_global_z_mm": {"repeller": -19.92918680341103, "intermediate1": -16.87918680341103, "intermediate2": -11.57918680341103, "exit": -0.12918680341102995},
            "potentials_v": {"repeller": 2000.0, "intermediate1": 1750.0, "intermediate2": 1450.0, "exit": 100.0},
        }
        geometry_path = REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
        oatof = json.loads(geometry_path.read_text(encoding="utf-8"))
        oatof["accelerator_topology"] = copy.deepcopy(topology)
        upstream, frontend = _minimal_program_contracts()
        frontend["accelerator_topology_id"] = topology["topology_id"]
        frontend["electrodes"] = copy.deepcopy(THREE_ZONE_FRONTEND_ELECTRODES)
        frontend["accelerator_local_region"] = {"intermediate2_grid_provider": "accelerator_overlay", "ring_z_mm": [-14.5, -12.0, -9.5, -7.0, -4.5]}
        def overlay(region_id: str, z_min: float, z_max: float) -> dict[str, object]:
            return {
                "role": "rf_oatof_simion_accelerator_overlay_contract", "region_id": region_id,
                "cell_mm_xyz": {"x": 0.2, "y": 0.2, "z": 0.025},
                "instance_origin_mm": {"x": 0.0, "y": 0.0, "z": z_min},
                "active_bounds_mm": {"x_min": -1.0, "x_max": 1.0, "y_min": -1.0, "y_max": 1.0, "z_min": z_min, "z_max": z_max},
            }
        with tempfile.TemporaryDirectory() as directory:
            region = build_resolved_region_field_contract(geometry_path, Path(directory) / "region.json", "accelerator_ideal_three_zone_real_reflectron", accelerator_topology=topology)
            program, exporter = build_successor_program(
                upstream, frontend, oatof, region, birth_times_us=[0.25],
                analyzer_component_source=ANALYZER_COMPONENT_SOURCE, pulse_hook_source=PULSE_HOOK_SOURCE,
                frontend_hook_source=FRONTEND_HOOK_SOURCE, rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
                overlay=overlay("entrance", -20.0, -16.0),
                intermediate_overlay=overlay("intermediate2", -13.5, -9.5),
                include_total_axis_field_exporter=True,
            )
        self.assertIn("accelerator_entrance_overlay", program)
        self.assertIn("accelerator_intermediate_overlay", program)
        self.assertIn("single_flight_is_active_field_instance(ion_instance)", program)
        self.assertIn("if instance==nil then return end", program)
        self.assertIn("assert(#simion.wb.instances==6", exporter)
        self.assertIn("C3 overlay active bounds overlap", exporter)

        # The production positive-gap topology has no entrance overlay in the
        # IOB.  Its intermediate2 overlay is the governed fine field source.
        with tempfile.TemporaryDirectory() as directory:
            region = build_resolved_region_field_contract(geometry_path, Path(directory) / "region.json", "accelerator_ideal_three_zone_real_reflectron", accelerator_topology=topology)
            program, exporter = build_successor_program(
                upstream, frontend, oatof, region, birth_times_us=[0.25],
                analyzer_component_source=ANALYZER_COMPONENT_SOURCE, pulse_hook_source=PULSE_HOOK_SOURCE,
                frontend_hook_source=FRONTEND_HOOK_SOURCE, rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
                intermediate_overlay=overlay("intermediate2", -13.5, -9.5),
                domain_split={
                    "upstream_instance_index": 2, "accelerator_instance_index": 3,
                    "upstream_end_x_mm": -20.0, "accelerator_start_x_mm": -10.0,
                    "upstream_bounds_mm": {"x_min": -30.0, "x_max": -20.0},
                    "accelerator_bounds_mm": {"x_min": -10.0, "x_max": 1.0},
                    "upstream_origin_mm": {"x": -30.0, "y": -1.0, "z": -1.0},
                    "accelerator_origin_mm": {"x": -10.0, "y": -1.0, "z": -1.0},
                },
                include_total_axis_field_exporter=True,
            )
        self.assertIn("single_flight_domain_split_enabled=1", program)
        self.assertIn("assert(#simion.wb.instances==6", exporter)
        self.assertIn("accelerator_main in slot 3", exporter)
        self.assertIn("active_scope='pre_pulse_frontend_accelerator'", exporter)
        self.assertNotIn("OATOF_ACCELERATOR_PA_OVERRIDE", exporter)
        self.assertIn("math.floor((z_end-z_start)/z_step+0.5)+1", exporter)

        with tempfile.TemporaryDirectory() as directory:
            region = build_resolved_region_field_contract(geometry_path, Path(directory) / "main_only_region.json", "accelerator_ideal_three_zone_real_reflectron", accelerator_topology=topology)
            main_only_program, main_only_exporter = build_successor_program(
                upstream, frontend, oatof, region, birth_times_us=[0.25],
                analyzer_component_source=ANALYZER_COMPONENT_SOURCE, pulse_hook_source=PULSE_HOOK_SOURCE,
                frontend_hook_source=FRONTEND_HOOK_SOURCE, rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
                domain_split={
                    "upstream_instance_index": 2, "accelerator_instance_index": 3,
                    "upstream_end_x_mm": -20.0, "accelerator_start_x_mm": -10.0,
                    "upstream_bounds_mm": {"x_min": -30.0, "x_max": -20.0},
                    "accelerator_bounds_mm": {"x_min": -10.0, "x_max": 1.0},
                    "upstream_origin_mm": {"x": -30.0, "y": -1.0, "z": -1.0},
                    "accelerator_origin_mm": {"x": -10.0, "y": -1.0, "z": -1.0},
                },
                domain_split_main_pa_only_axis_field=True,
                include_total_axis_field_exporter=True,
            )
        self.assertNotIn("accelerator_intermediate_overlay=6", main_only_program)
        self.assertIn("assert(#simion.wb.instances==5", main_only_exporter)
        self.assertIn("local overlay_specs={}", main_only_exporter)
        self.assertIn(
            "local ai_values=pa_adjustments({1,2,3,4,5,6,7,8,10,11,12,13,14,15,16,17,18,19,20})",
            main_only_exporter,
        )
        self.assertNotIn("missing electrode 21", main_only_exporter)
        with self.assertRaisesRegex(ValueError, "only for overlay-free axis-field export"):
            build_successor_program(
                upstream, frontend, oatof, region, birth_times_us=[0.25],
                analyzer_component_source=ANALYZER_COMPONENT_SOURCE, pulse_hook_source=PULSE_HOOK_SOURCE,
                frontend_hook_source=FRONTEND_HOOK_SOURCE, rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
                domain_split_main_pa_only_axis_field=True,
            )

    def test_three_zone_axis_exporter_replays_frozen_dynamic_pa_values(self) -> None:
        topology = {
            "topology_id": "three_zone_accelerator_ideal_v1",
            "planes_global_z_mm": {
                "repeller": -19.92918680341103,
                "intermediate1": -16.87918680341103,
                "intermediate2": -11.57918680341103,
                "exit": -0.12918680341102995,
            },
            "potentials_v": {
                "repeller": 2000.0,
                "intermediate1": 1750.0,
                "intermediate2": 1450.0,
                "exit": 100.0,
            },
        }
        overlay = {
            "role": "rf_oatof_simion_accelerator_overlay_contract",
            "cell_mm_xyz": {"x": 0.2, "y": 0.2, "z": 0.025},
            "instance_origin_mm": {"x": 0.0, "y": 0.0, "z": 0.0},
            "active_bounds_mm": {
                "x_min": -1.0, "x_max": 1.0, "y_min": -1.0, "y_max": 1.0,
                "z_min": -20.0, "z_max": 1.0,
            },
        }
        geometry_path = REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
        oatof = json.loads(geometry_path.read_text(encoding="utf-8"))
        oatof["accelerator_topology"] = copy.deepcopy(topology)
        upstream, frontend = _minimal_program_contracts()
        frontend["accelerator_topology_id"] = topology["topology_id"]
        frontend["electrodes"] = copy.deepcopy(THREE_ZONE_FRONTEND_ELECTRODES)
        frontend["accelerator_local_region"] = {
            "intermediate2_grid_provider": "accelerator_overlay",
            "ring_z_mm": [-14.5, -12.0, -9.5, -7.0, -4.5],
        }
        with tempfile.TemporaryDirectory() as directory:
            region = build_resolved_region_field_contract(
                geometry_path, Path(directory) / "region.json",
                "accelerator_ideal_three_zone_real_reflectron",
                accelerator_topology=topology,
            )
            _, exporter = build_successor_program(
                upstream, frontend, oatof, region, overlay=overlay,
                birth_times_us=[0.25], analyzer_component_source=ANALYZER_COMPONENT_SOURCE,
                pulse_hook_source=PULSE_HOOK_SOURCE, frontend_hook_source=FRONTEND_HOOK_SOURCE,
                rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
                include_total_axis_field_exporter=True,
            )
        self.assertIn("local inside_overlay=not detector:inside_wc(x,y,z)", exporter)
        self.assertIn("instance:field_wc(x,y,z,values)", exporter)
        self.assertIn("instance:potential_wc(x,y,z,values)", exporter)
        self.assertNotIn("ai.pa:fast_adjust(ai_values)", exporter)
        self.assertNotIn("pa:fast_adjust(oi_values)", exporter)
        self.assertNotIn("simion.wb:efield", exporter)
        self.assertNotIn("simion.wb:epotential", exporter)
        self.assertIn("Program suppresses overlay points outside its active bounds", exporter)
        self.assertIn("-- overlapping PA fields must not be added", exporter)

    def test_successor_has_one_workbench_and_one_definition_per_callback(self) -> None:
        upstream, frontend = _minimal_program_contracts()
        geometry_path = REPO / (
            "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
        )
        oatof = json.loads(geometry_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            region = build_resolved_region_field_contract(
                geometry_path, Path(directory) / "region.json", "accelerator_real_pa"
            )
        program = build_successor_program(
            upstream,
            frontend,
            oatof,
            region,
            birth_times_us=[0.25, 1.0],
            analyzer_component_source=ANALYZER_COMPONENT_SOURCE,
            pulse_hook_source=PULSE_HOOK_SOURCE,
            frontend_hook_source=FRONTEND_HOOK_SOURCE,
            rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
        )
        self.assertEqual(program.count("simion.workbench_program()"), 1)
        self.assertIn("for index=1,#simion.wb.instances do", program)
        self.assertIn("local instance=simion.wb.instances[index]", program)
        self.assertNotIn("ipairs(simion.wb.instances)", program)
        self.assertNotIn("pairs(simion.wb.instances)", program)
        for callback in (
            "load", "initialize_run", "efield_adjust", "fast_adjust",
            "instance_adjust", "initialize", "tstep_adjust", "other_actions",
            "terminate",
        ):
            self.assertEqual(
                len(re.findall(rf"function\s+segment\.{callback}\s*\(", program)),
                1,
                callback,
            )
        self.assertNotIn("oatof_ideal_grounded.lua", program)
        self.assertNotIn("oatof_handoff_pulse.lua", program)
        for event in (
            "source_release", "pre_pulse_state", "handoff_pulse_on",
            "single_flight_handoff",
            "accelerator_grid1_forward", "local_accelerator_exit",
            "accelerator_focus_forward",
        ):
            self.assertIn(f"TRACE: {event}", program)
        self.assertIn(
            "ion_number,handoff_pulse_time_us,pulse_x,pulse_y,pulse_z,"
            "pulse_vx,pulse_vy,pulse_vz",
            program,
        )
        self.assertNotIn(
            "ion_number,time,ion_px_mm,ion_py_mm,ion_pz_mm,ion_vx_mm,"
            "ion_vy_mm,ion_vz_mm)) end\n  end\n  local handoff_x",
            program,
        )
        for event in (
            "reflectron_entrance_forward", "reflectron_midgrid_forward",
            "reflectron_turning_point", "reflectron_exit_return",
        ):
            self.assertIn(f"single_flight_trace_checkpoint('{event}'", program)
        self.assertIn(
            "TRACE: detector_crossing ion=%d t=%.12g x=%.12g y=%.12g z=%.12g",
            program,
        )
        self.assertIn("adjustable diagnostic_max_tof_us=90", program)
        self.assertIn(
            "diagnostics={max_tof_us=diagnostic_max_tof_us,log_stride=trajectory_log_stride}",
            program,
        )
        self.assertIn("TRACE: diagnostic_return_plane", program)

    def test_successor_rejects_callback_owning_component_source(self) -> None:
        upstream, frontend = _minimal_program_contracts()
        geometry_path = REPO / (
            "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
        )
        oatof = json.loads(geometry_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            region = build_resolved_region_field_contract(
                geometry_path, Path(directory) / "region.json", "accelerator_real_pa"
            )
        with self.assertRaisesRegex(ValueError, "callback-neutral"):
            build_successor_program(
                upstream, frontend, oatof, region, birth_times_us=[0.25],
                analyzer_component_source="segment.fast_adjust=function() end",
                pulse_hook_source=PULSE_HOOK_SOURCE,
                frontend_hook_source=FRONTEND_HOOK_SOURCE,
                rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
            )

    def test_active_cli_requires_pure_components_not_historical_programs(self) -> None:
        source = (
            REPO / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
            "runtime/build_single_flight_program.py"
        ).read_text(encoding="utf-8")
        active = source[source.index("def main()") :]
        for option in ("--analyzer-component", "--pulse-hook", "--frontend-hook",
                       "--rf-drive-kernel"):
            self.assertIn(f'parser.add_argument("{option}", required=True', active)
        self.assertNotIn('parser.add_argument("--formal"', active)
        self.assertNotIn('parser.add_argument("--pulse-extension"', active)

    def test_birth_times_are_loaded_as_contiguous_instrument_times(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.csv"
            path.write_text(
                "particle_id,instrument_time_us\n1,0.25\n2,1.5\n",
                encoding="utf-8",
            )
            self.assertEqual(load_initial_state(path), ([0.25, 1.5], [1, 2]))

    def test_replay_birth_times_use_contiguous_simulation_particle_ids(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay_state.csv"
            path.write_text(
                "simulation_particle_id,instrument_time_us\n1,31.8\n2,31.8\n",
                encoding="utf-8",
            )
            self.assertEqual(load_initial_state(path), ([31.8, 31.8], [1, 2]))

    def test_row_map_keeps_reindexed_restart_rows_linked_to_mother_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "row_map.csv"
            path.write_text(
                "simulation_particle_id,source_particle_id\n1,46\n",
                encoding="utf-8",
            )
            self.assertEqual(load_row_map(path, 1), [46])

    def test_row_map_requires_the_initial_state_row_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "row_map.csv"
            path.write_text(
                "simulation_particle_id,source_particle_id\n1,46\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "count differs"):
                load_row_map(path, 2)

    @unittest.skipUnless(SIMION.is_file(), "official SIMION Lua CLI unavailable")
    def test_official_simion_cli_successor_callback_vectors(self) -> None:
        overlay = {
            "role": "rf_oatof_simion_accelerator_overlay_contract",
            "instance_origin_mm": {"x": 10.0, "y": 20.0, "z": 30.0},
            "active_bounds_mm": {
                "x_min": 0.0, "x_max": 100.0, "y_min": 0.0,
                "y_max": 100.0, "z_min": 0.0, "z_max": 100.0,
            },
        }
        time_series_contract = {
            "schema_version": 1,
            "role": "rf_oatof_pre_pulse_time_series_screening_contract",
            "mode": "real_pa_rf_pre_pulse_time_series",
            "active_scope": "pre_pulse_frontend_accelerator",
            "pulse_disabled": True,
            "terminate_at_window_end": True,
            "resolution_claim_allowed": False,
            "prohibited_outputs": [
                "detector_crossing",
                "resolution_metrics",
                "single_flight_spatial_six_panel",
            ],
            "sample_times_us": [1.0, 1.00625],
        }
        cases = (
            ("successor", "accelerator_real_pa", None, None),
            ("successor_full_ideal", "full_domain_piecewise_ideal_field", None, None),
            ("successor_overlay", "accelerator_real_pa", overlay, None),
            (
                "successor_time_series_mode2",
                "accelerator_real_pa",
                None,
                time_series_contract,
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for mode, profile_id, selected_overlay, time_series in cases:
                with self.subTest(mode=mode):
                    program = directory / f"{mode}.lua"
                    program.write_text(
                        _successor_callback_program(
                            directory, profile_id=profile_id,
                            overlay=selected_overlay,
                            pre_pulse_time_series_contract=time_series,
                        ),
                        encoding="utf-8", newline="\n",
                    )
                    result = subprocess.run(
                        [str(SIMION), "--nogui", "--noprompt", "lua",
                         str(CALLBACK_HARNESS), str(program), mode],
                        cwd=REPO, check=False, capture_output=True, text=True,
                        encoding="utf-8", errors="replace",
                        env={**os.environ,
                             "OATOF_ACCELERATOR_PA_OVERRIDE": "frontend.pa0"},
                        timeout=20,
                    )
                    self.assertEqual(
                        result.returncode, 0, result.stderr + result.stdout
                    )
                    expected = (
                        "SUCCESSOR_TIME_SERIES_HELD_OFF_MODE=PASS"
                        if time_series is not None
                        else "SUCCESSOR_SINGLE_FLIGHT_CALLBACKS=PASS"
                    )
                    self.assertIn(expected, result.stdout)

    @unittest.skipUnless(SIMION.is_file(), "official SIMION Lua CLI unavailable")
    def test_official_simion_cli_rejects_wrong_iob_or_override(self) -> None:
        overlay = {
            "role": "rf_oatof_simion_accelerator_overlay_contract",
            "instance_origin_mm": {"x": 10.0, "y": 20.0, "z": 30.0},
            "active_bounds_mm": {
                "x_min": 0.0, "x_max": 100.0, "y_min": 0.0,
                "y_max": 100.0, "z_min": 0.0, "z_max": 100.0,
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            normal = directory / "successor_negative.lua"
            normal.write_text(
                _successor_callback_program(directory), encoding="utf-8", newline="\n"
            )
            overlaid = directory / "successor_overlay_negative.lua"
            overlaid.write_text(
                _successor_callback_program(directory, overlay=overlay),
                encoding="utf-8", newline="\n",
            )
            for program, mode in (
                (normal, "successor_reject_count"),
                (normal, "successor_reject_slot3"),
                (overlaid, "successor_overlay_reject_slot3"),
                (overlaid, "successor_overlay_reject_slot5"),
            ):
                with self.subTest(mode=mode):
                    result = subprocess.run(
                        [str(SIMION), "--nogui", "--noprompt", "lua",
                         str(CALLBACK_HARNESS), str(program), mode],
                        cwd=REPO, check=False, capture_output=True, text=True,
                        encoding="utf-8", errors="replace",
                        env={**os.environ,
                             "OATOF_ACCELERATOR_PA_OVERRIDE": "frontend.pa0"},
                        timeout=20,
                    )
                    self.assertEqual(
                        result.returncode, 0, result.stderr + result.stdout
                    )
                    self.assertIn(
                        f"SUCCESSOR_FORMAL_IOB_NEGATIVE=PASS MODE={mode}",
                        result.stdout,
                    )
            wrong = subprocess.run(
                [str(SIMION), "--nogui", "--noprompt", "lua",
                 str(CALLBACK_HARNESS), str(normal), "successor"],
                cwd=REPO, check=False, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                env={**os.environ,
                     "OATOF_ACCELERATOR_PA_OVERRIDE": "wrong.pa0"},
                timeout=20,
            )
            self.assertNotEqual(wrong.returncode, 0)
            self.assertIn(
                "accelerator override payload basename differs",
                wrong.stderr + wrong.stdout,
            )

    def test_field_switches_are_absent_and_overlay_keeps_geometry_role(self) -> None:
        text = (REPO / "integrations" /
                "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer" /
                "runtime" / "build_single_flight_program.py").read_text(encoding="utf-8")
        self.assertNotIn("OATOF_IDEAL_ACCEL_STAGE1_ENABLE", text)
        self.assertNotIn("pulse_resolution_accelerator_stage_mode", text)
        self.assertNotIn("ideal_stage1_region", text)
        self.assertNotIn("ideal_stage2_region", text)
        self.assertNotIn("ideal_stage_regions_disable_overlay_instance5=1", text)
        self.assertIn("resolved_region_field_hook_lua", text)
        self.assertNotIn("OATOF_IDEAL_REFLECTRON_STAGE1_ENABLE", text)
        self.assertNotIn("pulse_resolution_reflectron_stage_mode", text)
        self.assertNotIn(".tests.", text)


if __name__ == "__main__":
    unittest.main()
