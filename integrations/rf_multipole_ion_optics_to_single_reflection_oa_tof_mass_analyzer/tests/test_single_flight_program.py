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
    build_successor_program,
    load_birth_times,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_region_field import (
    build_resolved_region_field_contract,
)
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




def _staged_source_release_validation_v2() -> dict[str, object]:
    return {
        "role": "rf_oatof_resolved_source_release_validation",
        "loader_authorization_budget": {
            "path": "config/diagnostics/loader_budget.json", "sha256": "A" * 64,
        },
        "representation": "standard_beam_direct_velocity_vector",
        "canonical_source_sha256": "B" * 64,
        "solver_executable_sha256": "C" * 64,
        "production_renderer_sha256": "D" * 64,
        "identity_position_clock_policy": "ordered_id_row_map_position_clock_exact",
        "velocity": {
            "relative_bound": 2e-8, "absolute_floor_m_per_s": 0,
            "zero_speed_must_be_exact": True,
        },
        "derived_energy": {
            "relative_bound": 3e-8, "absolute_floor_eV": 0,
            "zero_energy_must_be_exact": True,
            "authority": "actual_velocity_plus_canonical_mass_common_function",
        },
        "native_ion_ke_role": "diagnostic_only",
    }


def _successor_callback_program(
    directory: Path,
    *,
    profile_id: str = "accelerator_real_pa",
    overlay: dict[str, object] | None = None,
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
        rf_steps_per_period=160,
        overlay=overlay,
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
                with self.assertRaisesRegex(ValueError, "published topology"):
                    resolve_frontend_electrode_topology(electrodes)

    def test_staged_grid2_runner_omits_pulse_authority_and_enforces_instance_overlay(self) -> None:
        runner = (
            Path(__file__).resolve().parents[1] / "runtime" / "run_single_flight.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("$isStagedGrid2Restart -eq $hasPulseSchedule", runner)
        self.assertIn("$runConfiguration.inputs.Remove('pulse_schedule')", runner)
        self.assertIn("$runConfiguration.parameters.Remove('pulse_time_us')", runner)
        self.assertIn("$runConfiguration.parameters.Remove('pulse_width_us')", runner)
        self.assertIn("if ($isStagedGrid2Restart) { @() } else", runner)
        self.assertIn(
            "(($StagedGrid2StartInstance -eq 5) -ne [bool]$overlayEnabled)",
            runner,
        )
        self.assertIn("authority_scope = 'connection_lineage_only'", runner)

    def test_runner_consumes_frozen_electrode_topology_for_overlay_basis(self) -> None:
        runner = (
            Path(__file__).resolve().parents[1] / "runtime" / "run_single_flight.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("frontend_electrode_topology.json", runner)
        self.assertIn("$frontendBasisElectrodeIds", runner)
        self.assertIn("$maximumFrontendElectrodeId", runner)
        self.assertNotIn("basis_count=20", runner)
        self.assertNotIn("foreach ($electrode in 0..19)", runner)

    def test_staged_grid2_uses_explicit_instance_ids_and_skips_upstream_runtime(self) -> None:
        upstream, frontend = _minimal_program_contracts()
        geometry_path = REPO / (
            "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
        )
        oatof = json.loads(geometry_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            region = build_resolved_region_field_contract(
                geometry_path, Path(directory) / "region.json", "accelerator_real_pa"
            )
        context = {
            "role": "rf_oatof_staged_grid2_restart_context",
            "source_release_mode": "staged_grid2_restart",
            "population_mode": "staged_grid2_restart",
            "state_event": "local_accelerator_exit", "frame_id": "oatof_global",
            "clock_basis": "canonical_instrument_time_us",
            "clock_epoch_id": "instrument_clock_epoch_v1",
            "simion_start_instance": 3, "position_projection_applied": False,
            "skip_frontend_runtime_writes": True,
            "skip_pulse_runtime_writes": True,
            "skip_accelerator_runtime_writes": True,
            "preserve_analyzer_static_pa_initialization": True,
            "preserve_downstream_base_then_override_field_semantics": True,
            "preserve_detector_elapsed_semantics": True,
            "resolution_claim_allowed": False,
            "source_release_validation": _staged_source_release_validation_v2(),
        }
        program = build_successor_program(
            upstream, frontend, oatof, region, birth_times_us=[36.0, 37.0],
            particle_ids=[6, 97], restart_context=context,
            analyzer_component_source=ANALYZER_COMPONENT_SOURCE,
            pulse_hook_source=PULSE_HOOK_SOURCE,
            frontend_hook_source=FRONTEND_HOOK_SOURCE,
            rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
        )
        self.assertIn("local single_flight_source_particle_id={[1]=6,[2]=97}", program)
        self.assertIn("local single_flight_staged_grid2_restart=1", program)
        self.assertIn("local single_flight_staged_grid2_start_instance=3", program)
        self.assertIn("if single_flight_staged_grid2_restart~=0 then return end", program)
        self.assertIn("single_flight_trace_checkpoint('local_accelerator_exit'", program)
        self.assertIn("local result=single_flight_region_field.apply(base,state)", program)
        legacy_context = copy.deepcopy(context)
        legacy_context["source_release_validation"] = {
            "position_rowwise_abs_tolerance_mm": 1e-9,
            "velocity_rowwise_abs_tolerance_m_per_s": 1e-6,
            "clock_abs_tolerance_us": 1e-9,
            "energy_abs_tolerance_eV": 5e-9,
        }
        with self.assertRaisesRegex(ValueError, "resolved population v2 validation"):
            build_successor_program(
                upstream, frontend, oatof, region,
                birth_times_us=[36.0, 37.0], particle_ids=[6, 97],
                restart_context=legacy_context,
                analyzer_component_source=ANALYZER_COMPONENT_SOURCE,
                pulse_hook_source=PULSE_HOOK_SOURCE,
                frontend_hook_source=FRONTEND_HOOK_SOURCE,
                rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
            )
        with self.assertRaisesRegex(ValueError, "instance/overlay mapping differs"):
            build_successor_program(
                upstream, frontend, oatof, region,
                birth_times_us=[36.0, 37.0], particle_ids=[6, 97],
                restart_context=context,
                overlay={"role": "rf_oatof_simion_accelerator_overlay_contract"},
                analyzer_component_source=ANALYZER_COMPONENT_SOURCE,
                pulse_hook_source=PULSE_HOOK_SOURCE,
                frontend_hook_source=FRONTEND_HOOK_SOURCE,
                rf_drive_kernel_source=RF_DRIVE_KERNEL_SOURCE,
            )

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
            "source_release", "pre_pulse_state", "single_flight_handoff",
            "accelerator_grid1_forward", "local_accelerator_exit",
            "accelerator_focus_forward",
        ):
            self.assertIn(f"TRACE: {event}", program)
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
            self.assertEqual(load_birth_times(path), [0.25, 1.5])

    def test_replay_birth_times_use_contiguous_simulation_particle_ids(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay_state.csv"
            path.write_text(
                "simulation_particle_id,instrument_time_us\n1,31.8\n2,31.8\n",
                encoding="utf-8",
            )
            self.assertEqual(load_birth_times(path), [31.8, 31.8])

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
        cases = (
            ("successor", "accelerator_real_pa", None),
            ("successor_full_ideal", "full_domain_piecewise_ideal_field", None),
            ("successor_overlay", "accelerator_real_pa", overlay),
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for mode, profile_id, selected_overlay in cases:
                with self.subTest(mode=mode):
                    program = directory / f"{mode}.lua"
                    program.write_text(
                        _successor_callback_program(
                            directory, profile_id=profile_id,
                            overlay=selected_overlay,
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
                    self.assertIn(
                        "SUCCESSOR_SINGLE_FLIGHT_CALLBACKS=PASS", result.stdout
                    )

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
        for legacy_helper in (
            "bind_oatof_adjustables",
            "disable_redundant_ground_fast_adjust",
            "allow_accelerator_overlay_instance",
            "enable_official_global_segments",
            "build_extension",
        ):
            self.assertNotIn(f"def {legacy_helper}(", text)
        self.assertNotIn(".tests.", text)


if __name__ == "__main__":
    unittest.main()
