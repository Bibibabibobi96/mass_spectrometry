"""Solver-free tests for the dual-cone pressure-drag screening model."""

from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from projects.dual_cone_tandem_quadrupole_ion_interface.analysis.reduced_order_transport import (
    _aperture_losses,
    _inside_stage_1_rods,
    _inside_stage_2_rods,
    gas_axial_velocity_m_s,
    load_json,
    pressure_pa,
    simulate,
    source_particles,
    summarize,
    write_result_tables,
)
from projects.dual_cone_tandem_quadrupole_ion_interface.analysis.resolve_geometry import (
    DEFAULT_BASELINE,
    DEFAULT_RESOLVED,
    load_baseline,
    resolve_geometry,
    serialized,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCIENCE_PATH = PROJECT_ROOT / "config" / "science.json"
NUMERICS_PATH = PROJECT_ROOT / "config" / "solver_numerics.json"


class GeometryContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolved = resolve_geometry(load_baseline())

    def test_resolved_publication_is_fresh(self) -> None:
        self.assertEqual(DEFAULT_RESOLVED.read_text(encoding="utf-8"), serialized(self.resolved))

    def test_user_dimensions_derive_expected_clear_radii_and_positions(self) -> None:
        geometry = self.resolved["geometry_mm"]
        stage_1 = geometry["stage_1_elliptical_quadrupole"]
        stage_2 = geometry["stage_2_round_quadrupole"]
        self.assertAlmostEqual(stage_1["ideal_field_radius_r0_mm"], 3.74)
        self.assertAlmostEqual(stage_1["rod_array"]["rod_center_radius"], 5.62)
        self.assertEqual(stage_1["rod_array"]["cross_section"]["shape"], "ellipse")
        self.assertAlmostEqual(stage_2["rod_array"]["rod_center_radius"], 5.64 / math.sqrt(2.0))
        self.assertNotIn("cross_section", stage_2["rod_array"])
        self.assertAlmostEqual(stage_2["ideal_field_radius_r0_mm"], 5.64 / math.sqrt(2.0) - 2.39)
        self.assertAlmostEqual(stage_2["upstream_flat_start_z_mm"], 55.8)
        self.assertAlmostEqual(stage_1["downstream_flat_end_z_mm"], 53.8)
        self.assertAlmostEqual(geometry["interstage"]["clear_gap_mm"], 2.0)

    def test_invalid_round_rod_overlap_fails(self) -> None:
        baseline = load_baseline(DEFAULT_BASELINE)
        baseline["geometry_mm"]["round_quadrupole"]["rod_radius_mm"] = 5.0
        with self.assertRaisesRegex(ValueError, "overlap"):
            resolve_geometry(baseline)


class PhysicsAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolved = json.loads(DEFAULT_RESOLVED.read_text(encoding="utf-8"))
        self.science = load_json(SCIENCE_PATH, "pressure_drag_transport_science_contract")

    def test_pressure_and_velocity_hit_declared_endpoints(self) -> None:
        geometry = self.resolved["geometry_mm"]
        z = np.array(
            [
                self.science["source"]["plane_z_mm"],
                geometry["second_cone"]["aperture_reference_z_mm"],
                geometry["low_pressure_enclosure"]["end_z_mm"],
            ]
        ) * 1e-3
        pressure = pressure_pa(z, self.resolved, self.science)
        self.assertAlmostEqual(pressure[0], 101325.0)
        self.assertAlmostEqual(pressure[1], math.sqrt(101325.0 * 400.0))
        self.assertAlmostEqual(pressure[2], 400.0)
        np.testing.assert_allclose(
            gas_axial_velocity_m_s(z, self.resolved, self.science),
            np.array([250.0, 150.0, 40.0]),
        )

    def test_source_is_particle_prefix_stable(self) -> None:
        small = source_particles(5, 73, self.resolved, self.science)
        large = source_particles(10, 73, self.resolved, self.science)
        for small_array, large_array in zip(small, large, strict=True):
            np.testing.assert_array_equal(small_array, large_array[:5])

    def test_aperture_and_electrode_intersections_are_explicit(self) -> None:
        old = np.array([[0.0, 0.0, -0.1e-3], [1.1e-3, 0.0, -0.1e-3]])
        new = np.array([[0.0, 0.0, 0.1e-3], [1.1e-3, 0.0, 0.1e-3]])
        np.testing.assert_array_equal(_aperture_losses(old, new, self.resolved), np.array([False, True]))
        stage_1_center = self.resolved["geometry_mm"]["stage_1_elliptical_quadrupole"]["rod_array"]["rods"][0]
        stage_2_center = self.resolved["geometry_mm"]["stage_2_round_quadrupole"]["rod_array"]["rods"][0]
        points = np.array(
            [
                [stage_1_center["center_x_mm"] * 1e-3, 0.0, 30e-3],
                [stage_2_center["center_x_mm"] * 1e-3, 0.0, 80e-3],
                [0.0, 0.0, 80e-3],
            ]
        )
        np.testing.assert_array_equal(_inside_stage_1_rods(points, self.resolved), np.array([True, False, False]))
        np.testing.assert_array_equal(_inside_stage_2_rods(points, self.resolved), np.array([False, True, False]))


class DeterministicTransportTests(unittest.TestCase):
    def test_small_zero_rf_case_publishes_valid_component_states(self) -> None:
        resolved = json.loads(DEFAULT_RESOLVED.read_text(encoding="utf-8"))
        science = load_json(SCIENCE_PATH, "pressure_drag_transport_science_contract")
        numerics = load_json(NUMERICS_PATH, "pressure_drag_transport_solver_numerics")
        science = copy.deepcopy(science)
        science["electric_field"]["stage_1"]["rf_amplitude_v_zero_to_peak_per_group"] = 0.0
        science["electric_field"]["stage_2"]["rf_amplitude_v_zero_to_peak_per_group"] = 0.0
        result = simulate(6, 91, resolved, science, numerics)
        report = summarize(result, science)
        self.assertEqual(report["particle_count"], 6)
        self.assertEqual(report["transmitted_count"], 6)
        with tempfile.TemporaryDirectory() as directory:
            validation = write_result_tables(Path(directory), result, science)
            self.assertEqual(validation["source_state_validation"]["status"], "PASS")
            self.assertEqual(validation["exit_state_validation"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
