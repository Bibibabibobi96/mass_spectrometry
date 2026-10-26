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
