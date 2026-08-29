import csv
from pathlib import Path
import tempfile
import unittest

from projects.single_reflection_oa_tof_mass_analyzer.analysis.exported_axis_field_integrator import (
    integrate_axis_to_plane_us, load_total_axis_field,
)


class ExportedAxisFieldIntegratorTests(unittest.TestCase):
    def test_constant_axis_field_matches_constant_acceleration_solution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "field.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["z_mm", "Ez_V_per_mm"])
                writer.writeheader()
                writer.writerows({"z_mm": z, "Ez_V_per_mm": 1.0} for z in range(0, 11))
            elapsed = integrate_axis_to_plane_us(
                load_total_axis_field(path), z0_mm=0.0, vz0_mm_per_us=0.0,
                z_stop_mm=10.0, mass_th=1.0, charge_state=1, dt_us=1e-4,
            )
        self.assertAlmostEqual(elapsed, 0.455286, delta=2e-5)

    def test_allows_initial_upstream_velocity_before_accelerator_turnaround(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "field.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["z_mm", "Ez_V_per_mm"])
                writer.writeheader()
                writer.writerows({"z_mm": z / 10, "Ez_V_per_mm": 10.0} for z in range(0, 101))
            elapsed = integrate_axis_to_plane_us(
                load_total_axis_field(path), z0_mm=1.0, vz0_mm_per_us=-0.1,
                z_stop_mm=9.0, mass_th=1.0, charge_state=1, dt_us=1e-5,
            )
        self.assertGreater(elapsed, 0.0)

    def test_unreached_stop_plane_fails_at_declared_propagation_horizon(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "field.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["z_mm", "Ez_V_per_mm"])
                writer.writeheader()
                writer.writerows({"z_mm": z, "Ez_V_per_mm": 0.0} for z in range(0, 11))
            with self.assertRaisesRegex(RuntimeError, "max_elapsed_us"):
                integrate_axis_to_plane_us(
                    load_total_axis_field(path), z0_mm=0.0, vz0_mm_per_us=0.0,
                    z_stop_mm=10.0, mass_th=1.0, charge_state=1,
                    dt_us=1.0e-3, max_elapsed_us=0.01,
                )

    def test_identical_adjacent_endpoint_is_folded_but_conflict_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "field.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["z_mm", "Ez_V_per_mm"])
                writer.writeheader()
                writer.writerows([
                    {"z_mm": 0.0, "Ez_V_per_mm": 1.0},
                    {"z_mm": 1.0, "Ez_V_per_mm": 2.0},
                    {"z_mm": 1.0, "Ez_V_per_mm": 2.0},
                ])
            self.assertEqual(load_total_axis_field(path).z_mm.size, 2)
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["z_mm", "Ez_V_per_mm"])
                writer.writeheader()
                writer.writerows([
                    {"z_mm": 0.0, "Ez_V_per_mm": 1.0},
                    {"z_mm": 1.0, "Ez_V_per_mm": 2.0},
                    {"z_mm": 1.0, "Ez_V_per_mm": 3.0},
                ])
            with self.assertRaisesRegex(ValueError, "conflicting Ez"):
                load_total_axis_field(path)

    def test_c3_export_is_top_level_and_reproduces_post_pulse_fast_adjust(self) -> None:
        builder = Path(__file__).resolve().parents[4] / (
            "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
            "runtime/build_single_flight_program.py"
        )
        source = builder.read_text(encoding="utf-8")
        self.assertIn("include_total_axis_field_exporter", source)
        self.assertIn("--total-axis-field-exporter-output", source)
        self.assertIn("simion.command('", source)
        self.assertIn("frontend.apply_at(pulse_time_us", source)
        self.assertIn("ai.pa:fast_adjust(ai_values)", source)
        self.assertIn(
            "simion.wb.instances[overlay.instance_index].pa:fast_adjust(oi_values)",
            source,
        )
        self.assertIn("ai.pa:load(frontend_pa)", source)
        self.assertIn("{1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19}", source)
        self.assertIn("1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20", source)
        self.assertIn("instance:potential_wc(x,y,z,values)", source)
        self.assertIn("instance:field_wc(x,y,z,values)", source)
        self.assertIn("TOTAL_AXIS_FIELD_INSTANCE", source)
        self.assertIn("for index=1,#simion.wb.instances do", source)
        exporter_source = source[source.index('exporter = f"""'):]
        self.assertNotIn("simion.workbench_program()", exporter_source)
        self.assertIn("analyzer.initialize_workbench", source)
        self.assertIn("apply_placement(ai,initialized.placements.accelerator)", source)
        self.assertIn("ai.x,ai.y,ai.z={_lua_number(origin['x'])}", exporter_source)
        self.assertIn("oi.x,oi.y,oi.z=overlay.origin_mm.x", exporter_source)
        self.assertIn("oi.az,oi.el,oi.rt,oi.scale=0,0,0,1", exporter_source)
        self.assertIn("TOTAL_AXIS_FIELD_ACCELERATOR_POSTPLACEMENT", exporter_source)
        self.assertIn("TOTAL_AXIS_FIELD_OVERLAY_POSTPLACEMENT", exporter_source)
        self.assertIn("local z_start=", source)
        self.assertIn("(index==count) and z_end", source)
        self.assertNotIn("single_flight_export_total_axis_field_if_requested", source)
