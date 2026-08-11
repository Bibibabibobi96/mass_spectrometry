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
    load_birth_times,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_frontend import (
    compile_accelerator_overlay,
    compile_frontend,
)


REPO = Path(__file__).resolve().parents[3]


class SingleFlightProgramTests(unittest.TestCase):
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
            clock_basis="absolute_birth_time",
            terminate_after_pulse=True,
        )
        self.assertIn("OATOF_SINGLE_FLIGHT_PARTICLE_ID_OFFSET", extension)
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
        self.assertIn("TRACE: pre_pulse_state", extension)
        self.assertIn("single_flight_rf_steps=160", extension)
        self.assertIn("single_flight_absolute_birth_clock=1", extension)
        self.assertIn("return birth+ion_time_of_flight", extension)
        self.assertNotIn("ion_time_of_flight=birth", extension)
        self.assertIn("math.cos(single_flight_omega*instrument_time_us)", extension)
        self.assertIn("single_flight_terminate_after_pulse=1", extension)
        self.assertIn("instrument_time_us>=handoff_pulse_time_us then ion_splat=1", extension)
        self.assertIn("adjustable sf_ideal_accel_enable=0", extension)
        self.assertIn("single_flight_base_efield_adjust()", extension)
        self.assertIn("sf_ideal_accel_enable==0 or ion_instance~=3", extension)
        self.assertIn("math.abs(ion_px_mm-accelerator_axis_x_mm)>accelerator_bore_half_mm", extension)
        self.assertIn("not single_flight_pulse_is_on() then return", extension)

        _, overlay = compile_accelerator_overlay(
            frontend, cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05}
        )
        overlay_extension = build_extension(
            upstream,
            frontend,
            birth_times_us=[0.25, 1.0],
            clock_basis="absolute_birth_time",
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


if __name__ == "__main__":
    unittest.main()
