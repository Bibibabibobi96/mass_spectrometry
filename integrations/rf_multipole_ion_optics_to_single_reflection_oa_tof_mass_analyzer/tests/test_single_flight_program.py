from __future__ import annotations

import json
import copy
import re
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.build_single_flight_program import (
    allow_accelerator_overlay_instance,
    bind_oatof_adjustables,
    build_extension,
    disable_redundant_ground_fast_adjust,
    enable_official_global_segments,
    load_birth_times,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_frontend import (
    compile_accelerator_overlay,
    compile_frontend,
)


REPO = Path(__file__).resolve().parents[3]


def _minimal_program_contracts() -> tuple[dict[str, object], dict[str, object]]:
    upstream = {
        "role": "multipole_resolved_design_do_not_edit",
        "drive": {
            "waveform": "cosine",
            "rf_amplitude_V_zero_to_peak_per_group": 100.0,
            "frequency_Hz": 1.0e6,
        },
        "segmentation": {
            "segmented_rod_array": {
                "electrodes": [
                    {"electrode_id": electrode_id, "electrode_group": 1 + electrode_id % 2}
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
    }
    return upstream, frontend


class SingleFlightProgramTests(unittest.TestCase):
    def test_official_global_segments_follow_workbench_declaration(self) -> None:
        program = enable_official_global_segments(
            "simion.workbench_program()\nadjustable x=0\n"
        )
        self.assertTrue(
            program.startswith(
                "simion.workbench_program()\n"
                "simion.early_access(8.2)\n"
                "sim_segment_global = 1\n"
            )
        )

    def test_parallel_program_does_not_readjust_frozen_ground_pas(self) -> None:
        formal = (
            REPO / "projects/single_reflection_oa_tof_mass_analyzer/simion/"
            "workbench/formal/oatof_ideal_grounded.lua"
        ).read_text()
        prepared = disable_redundant_ground_fast_adjust(formal)
        self.assertIn("r:fast_adjust(reflectron_voltages)", prepared)
        self.assertNotIn("t:fast_adjust{[1]=0}", prepared)
        self.assertNotIn("d:fast_adjust{[1]=0}", prepared)

    def test_overlay_workbench_requires_gui_visible_fifth_instance(self) -> None:
        formal = (
            REPO / "projects/single_reflection_oa_tof_mass_analyzer/simion/"
            "workbench/formal/oatof_ideal_grounded.lua"
        ).read_text()
        prepared = allow_accelerator_overlay_instance(formal)
        self.assertIn("#simion.wb.instances==5", prepared)
        self.assertIn("accelerator_overlay%.pa0", prepared)
        self.assertNotIn("#simion.wb.instances==4", prepared)

    def test_resolved_oatof_values_are_bound_into_program_defaults(self) -> None:
        formal = (
            REPO / "projects/single_reflection_oa_tof_mass_analyzer/simion/"
            "workbench/formal/oatof_ideal_grounded.lua"
        ).read_text()
        oatof = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/"
             "resolved_geometry.json").read_text()
        )
        oatof["geometry_mm"]["L_stage2"] = 116.6151
        oatof["geometry_mm"]["L_reflectron"] = 236.6151
        oatof["electrodes_V"]["backplate"] = 2723.1999
        bound = bind_oatof_adjustables(formal, oatof)
        for name, expected in {
            "V_backplate": 2723.1999,
            "reflectron_stage2_length_mm": 116.6151,
            "reflectron_backplate_z_mm": 836.6151,
        }.items():
            match = re.search(rf"(?m)^adjustable {name}=([^\r\n]+)$", bound)
            self.assertIsNotNone(match)
            self.assertAlmostEqual(float(match.group(1)), expected)

    def test_frontend_electrode_schedule_keeps_rf_and_pulse_in_one_instance(self) -> None:
        run = REPO.parent / "artifacts/projects/rf_octupole_ion_optics/runs/20260804_112000__sim__simion__oct-segmented-aperture050__n1000"
        if not run.is_dir():
            self.skipTest("local N=1000 octupole source artifact is unavailable")
        upstream = json.loads((run / "inputs/multipole_resolved_design.json").read_text(encoding="utf-8-sig"))
        oatof = json.loads((REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json").read_text())
        connection = json.loads((REPO.parent / "artifacts/projects/rf_octupole_ion_optics/runs/20260804_125500__sim__simion__oct-aperture100x090-interface__n459/inputs/resolved_connection.json").read_text(encoding="utf-8-sig"))
        upstream = copy.deepcopy(upstream)
        upstream["axial_dc"]["upstream_shield_potential_V"] = 0.0
        upstream["axial_dc"]["entrance_plate_potential_V"] = 3.0
        upstream["axial_dc"]["entrance_reference_sleeve"] = {
            "profile_id": "source_reference_sleeve_v1",
            "role": "functional_source_reference_not_shield",
            "potential_V": 3.0,
            "inner_radius_mm": 1.0,
            "outer_radius_mm": 1.4,
            "upstream_face_z_mm": -2.5,
            "downstream_face_z_mm": -0.1,
            "minimum_insulation_gap_mm": 0.2,
        }
        upstream["downstream_terminal"]["terminal_potential_V"] = 0.0
        connection["connector"].update({
            "shield_connection_profile_id": "grounded_circular_to_rectangular_shield_v1",
            "shield_potential_V": 0.0,
            "flange_thickness_binding": "oatof.geometry_mm.accelerator_shield_wall",
        })
        _, frontend = compile_frontend(upstream, oatof, connection)
        extension = build_extension(
            upstream,
            frontend,
            birth_times_us=[0.25, 1.0],
            terminate_after_pulse=True,
        )
        self.assertIn("OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET", extension)
        self.assertNotIn("OATOF_ACCEL_PLANE_DIAGNOSTIC_PARTICLE_ID", extension)
        self.assertIn(
            "single_flight_birth_time_us[global_particle_id]", extension
        )
        self.assertIn("adj_elect[9]=0", extension)
        self.assertIn("adj_elect[10]=pulse_on and V_repeller", extension)
        self.assertIn("adj_elect[17]=0", extension)
        self.assertIn("adj_elect[18]=3", extension)
        self.assertIn("adj_elect[19]=3", extension)
        self.assertIn("single_flight_handoff", extension)
        self.assertIn("TRACE: source_release", extension)
        self.assertNotIn(
            "if trajectory_log_enable~=0 then\n"
            "    print(string.format('TRACE: source_release",
            extension,
        )
        self.assertIn("TRACE: pre_pulse_state", extension)
        self.assertIn("TRACE: accelerator_grid1_forward", extension)
        self.assertIn("single_flight_rf_steps=160", extension)
        self.assertNotIn("accelerator_ring_quadratic_V", extension)
        self.assertNotIn("accelerator_ring_cubic_V", extension)
        self.assertIn("single_flight_accelerator_ring_voltage(1)", extension)
        self.assertIn("return V_grid1*((6-index)/6)", extension)
        self.assertNotIn("single_flight_absolute_birth_clock", extension)
        self.assertIn("return birth+ion_time_of_flight", extension)
        self.assertNotIn("ion_time_of_flight=birth", extension)
        self.assertIn("math.cos(single_flight_omega*instrument_time_us)", extension)
        self.assertIn("single_flight_terminate_after_pulse=1", extension)
        self.assertIn("instrument_time_us>=handoff_pulse_time_us then ion_splat=1", extension)
        self.assertNotIn("sf_ideal_accel", extension)
        self.assertNotIn("OATOF_IDEAL_ACCEL", extension)
        self.assertNotIn("function segment.efield_adjust()", extension)
        self.assertIn("next_plane=accelerator_grid1_z_mm", extension)
        self.assertIn("next_plane=accelerator_grid2_z_mm", extension)
        self.assertIn("local crossing_time=distance/ion_vz_mm", extension)
        self.assertIn("ion_time_step=crossing_time", extension)
        self.assertIn("local single_flight_accel_plane_state={}", extension)
        self.assertIn("single_flight_accel_state_for_current_particle()", extension)
        self.assertIn("if state==nil then", extension)
        self.assertIn("state=initialized", extension)
        self.assertIn("accelerator plane state is invalid", extension)
        self.assertNotIn("accelerator plane state is missing", extension)
        self.assertIn("state[stage]='willhit'", extension)
        self.assertIn("plane_state[stage]='hitting'", extension)
        self.assertIn("plane_state[stage]='hitted'", extension)
        self.assertIn("local crossed=p.z<plane and ion_pz_mm>=plane", extension)
        self.assertIn("plane_state[stage..'_oa_count']==1", extension)
        self.assertNotIn("accelerator_plane_tstep_diagnostic", extension)
        self.assertNotIn("accelerator_plane_other_actions_diagnostic", extension)
        self.assertIn("local coordinate_tolerance=32*2.2204460492503131e-16", extension)
        self.assertIn("status=='willhit' and math.abs(distance)", extension)
        self.assertIn("math.abs(distance)<=coordinate_tolerance", extension)
        self.assertIn("ion_time_step=0", extension)
        self.assertIn("state[stage]='hitting'", extension)
        self.assertIn("plane_state[stage]='hitted'", extension)
        self.assertIn("if not repeated_plane_evaluation then", extension)
        self.assertNotIn("repeated_plane_evaluation then return", extension)
        self.assertIn("accelerator plane crossing estimate made no representable time progress", extension)
        self.assertNotIn("landing did not reach its governed boundary", extension)
        self.assertIn("ion_pz_mm<accelerator_grid1_z_mm", extension)
        self.assertNotIn("accelerator_focus_drift_mm then next_plane", extension)
        self.assertNotIn("ion_pz_mm=next_plane", extension)
        self.assertNotIn("sf_ideal_accel", extension)
        self.assertNotIn("OATOF_IDEAL_ACCEL", extension)

        _, overlay = compile_accelerator_overlay(
            frontend, cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05}
        )
        overlay_extension = build_extension(
            upstream,
            frontend,
            birth_times_us=[0.25, 1.0],
            overlay=overlay,
        )
        self.assertIn("local single_flight_overlay_enabled=1", overlay_extension)
        self.assertIn("simion.wb.instances[5]", overlay_extension)
        self.assertIn("function segment.instance_adjust()", overlay_extension)
        self.assertIn("di:inside_wc(ion_px_mm,ion_py_mm,ion_pz_mm)", overlay_extension)
        self.assertIn("ion_pz_mm>=single_flight_overlay_active_z_max", overlay_extension)
        self.assertIn("ion_instance==5", overlay_extension)

    def test_birth_times_are_loaded_as_contiguous_instrument_times(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.csv"
            path.write_text(
                "particle_id,instrument_time_us\n1,0.25\n2,1.5\n",
                encoding="utf-8",
            )
            self.assertEqual(load_birth_times(path), [0.25, 1.5])

    def test_delayed_continuous_birth_initializes_plane_state_on_first_tstep(self) -> None:
        upstream, frontend = _minimal_program_contracts()
        extension = build_extension(upstream, frontend, birth_times_us=[41.079981])
        initializer = extension.index(
            "local function single_flight_accel_state_for_current_particle()"
        )
        tstep = extension.index("function segment.tstep_adjust()", initializer)
        first_tstep_call = extension.index(
            "local state=single_flight_accel_state_for_current_particle()", tstep
        )
        self.assertGreater(first_tstep_call, tstep)
        self.assertIn(
            "initialized_time=ion_time_of_flight,initialized_instance=ion_instance",
            extension,
        )

    def test_plane_lifecycle_observes_crossing_only_after_completed_step(self) -> None:
        upstream, frontend = _minimal_program_contracts()
        extension = build_extension(upstream, frontend, birth_times_us=[41.079981])
        tstep = extension.index("function segment.tstep_adjust()")
        other_actions = extension.index("function segment.other_actions()", tstep)
        request = extension.index("state[stage]='willhit'", tstep, other_actions)
        observe = extension.index("plane_state[stage]='hitting'", other_actions)
        finish = extension.index("plane_state[stage]='hitted'", observe)
        self.assertLess(request, other_actions)
        self.assertLess(other_actions, observe)
        self.assertLess(observe, finish)
        self.assertNotIn("pending_status=='willhit'", extension[tstep:other_actions])

    def test_unrepresentable_spatial_progress_uses_one_zero_step_state_confirmation(self) -> None:
        upstream, frontend = _minimal_program_contracts()
        extension = build_extension(upstream, frontend, birth_times_us=[41.081286])
        tstep = extension.index("function segment.tstep_adjust()")
        other_actions = extension.index("function segment.other_actions()", tstep)
        zero_request = extension.index("ion_time_step=0", tstep, other_actions)
        hitting = extension.index("state[stage]='hitting'", tstep, other_actions)
        hitted = extension.index("plane_state[stage]='hitted'", other_actions)
        self.assertLess(hitting, zero_request)
        self.assertLess(zero_request, other_actions)
        self.assertLess(other_actions, hitted)
        self.assertIn("state[stage..'_zero_step_count']==1", extension)
        self.assertNotIn("ion_pz_mm=next_plane", extension)

    def test_reflectron_checkpoints_are_ordered_particle_resolved_states(self) -> None:
        upstream, frontend = _minimal_program_contracts()
        extension = build_extension(upstream, frontend, birth_times_us=[0.0])
        checkpoint_events = [
            "reflectron_entrance_forward",
            "reflectron_midgrid_forward",
            "reflectron_turning_point",
            "reflectron_exit_return",
        ]
        checkpoint_offsets = [extension.index(name) for name in checkpoint_events]
        self.assertEqual(checkpoint_offsets, sorted(checkpoint_offsets))
        for name in checkpoint_events:
            self.assertEqual(
                extension.count(f"single_flight_trace_checkpoint('{name}'"), 1
            )
        self.assertIn(
            "particle_id=%d instrument_time_us=%.12g tof_since_pulse_us=%.12g",
            extension,
        )
        self.assertIn(
            "kinetic_energy_eV=%.12g survival_status=alive", extension
        )
        self.assertIn(
            "global_particle_id=ion_number+single_flight_particle_id_offset",
            extension,
        )
        self.assertIn(
            "single_flight_reflectron_midgrid_reported[ion_number] and not "
            "single_flight_reflectron_turning_reported[ion_number] and p.vz>0",
            extension,
        )
        self.assertIn(
            "single_flight_reflectron_turning_reported[ion_number]=true",
            extension,
        )
        self.assertIn(
            "single_flight_reflectron_turning_reported[ion_number] and not "
            "single_flight_reflectron_exit_reported",
            extension,
        )

    def test_replay_birth_times_use_contiguous_simulation_particle_ids(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay_state.csv"
            path.write_text(
                "simulation_particle_id,instrument_time_us\n1,31.8\n2,31.8\n",
                encoding="utf-8",
            )
            self.assertEqual(load_birth_times(path), [31.8, 31.8])

    def test_field_switches_are_absent_and_overlay_keeps_geometry_role(self) -> None:
        text = (REPO / "integrations" /
                "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer" /
                "runtime" / "build_single_flight_program.py").read_text(encoding="utf-8")
        self.assertNotIn("OATOF_IDEAL_ACCEL_STAGE1_ENABLE", text)
        self.assertNotIn("pulse_resolution_accelerator_stage_mode", text)
        self.assertNotIn("ideal_stage1_region", text)
        self.assertNotIn("ideal_stage2_region", text)
        self.assertNotIn("ideal_stage_regions_disable_overlay_instance5=1", text)
        self.assertIn("resolved_region_field_contract active=1", text)
        self.assertNotIn("OATOF_IDEAL_REFLECTRON_STAGE1_ENABLE", text)
        self.assertNotIn("pulse_resolution_reflectron_stage_mode", text)


if __name__ == "__main__":
    unittest.main()
