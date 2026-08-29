from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from matplotlib import pyplot as plt
from matplotlib.patches import PathPatch
import pandas as pd

from common.contracts.particle_physics import kinetic_energy_ev
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight import (
    analyze as analyze_with_population_contract,
    resolve_analysis_mass_amu,
    validate_resolution_qualification,
    validate_three_zone_checkpoint_census,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_single_flight_spatial_six_panel import (
    _accelerator,
    _apply_shared_nice_ticks,
    _accelerator_boundary_planes,
    _accelerator_cross_section,
    _accelerator_shield_geometry,
    _connector_through_hole_geometry,
    _checkpoint_distribution_summary,
    _rectangular_frame_path,
    _repeller_body_geometry,
    _source_region_bounds,
    _source_region_cross_section,
    _source_region_longitudinal,
    build_accelerator_phase_space_figure,
    build_figure,
    marker_area,
    write_checkpoint_evolution_outputs,
)

RESOLUTION_QUALIFICATION_POLICY = json.loads(
    (Path(__file__).resolve().parents[1] / "config" / "simion_single_flight.json").read_text(
        encoding="utf-8"
    )
)["resolution_qualification_policy"]


def analyze(log_path, launched, mass_amu, *args, **kwargs):
    """Test fixture: compile formerly separate population values into one contract."""
    population_count = kwargs.pop("population_denominator_count", launched)
    eligible_count = kwargs.pop("eligible_population_count", launched)
    bootstrap_resamples = kwargs.pop("bootstrap_resamples", 0)
    bootstrap_seed = kwargs.pop("bootstrap_seed", 20260812)
    source_release_mode = kwargs.pop("source_release_mode", "continuous_frontend")
    paired_cohort_authority = kwargs.pop("paired_cohort_authority", None)
    cohort_authority_mode = kwargs.pop("cohort_authority_mode", None)
    denominators = {"population_count": population_count}
    if eligible_count is not None:
        denominators["eligible_population_count"] = eligible_count
    contract = {
        "schema_version": 1,
        "role": "rf_oatof_resolved_population_contract",
        "source_release_mode": source_release_mode,
        "execution_population": {"particle_count": launched},
        "denominators": denominators,
        "analysis_randomness": {
            "bootstrap_resample_count": bootstrap_resamples,
            "bootstrap_seed": bootstrap_seed,
        },
    }
    if paired_cohort_authority is not None:
        contract["paired_cohort_authority"] = paired_cohort_authority
    if cohort_authority_mode is not None:
        contract["cohort_authority_mode"] = cohort_authority_mode
    return analyze_with_population_contract(log_path, mass_amu, contract, *args, **kwargs)


class SingleFlightAnalysisTests(unittest.TestCase):
    def test_spatial_figure_marks_terminal_handoff_source_region_not_applicable(self) -> None:
        initial = pd.DataFrame({
            "particle_id": [1], "position_x_mm": [0.0],
            "position_y_mm": [0.0], "position_z_mm": [0.0],
        })
        checkpoints = pd.DataFrame({
            "particle_id": [1] * 4,
            "event": [
                "multipole_handoff", "pre_pulse_state",
                "local_accelerator_exit", "detector_crossing",
            ],
            "instrument_time_us": [0.0, 1.0, 2.0, 3.0],
            "x_mm": [0.0, 0.0, 1.0, 2.0],
            "y_mm": [0.0, 0.0, 1.0, 2.0],
            "z_mm": [0.0, 0.0, 1.0, 2.0],
        })
        frontend = {
            "source_exit_center_mm": {"z": 0.0},
            "aperture": {"width_mm": 1.0, "height_mm": 1.0},
        }
        oatof = {
            "coordinate_convention": {"detector_x": 0.0},
            "geometry_mm": {"detector_radius": 1.0},
        }
        with (
            mock.patch(
                "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_single_flight_spatial_six_panel._rod_cross_section"
            ),
            mock.patch(
                "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_single_flight_spatial_six_panel._multipole_longitudinal"
            ),
            mock.patch(
                "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_single_flight_spatial_six_panel._accelerator"
            ),
            mock.patch(
                "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_single_flight_spatial_six_panel._accelerator_cross_section"
            ),
            mock.patch(
                "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_single_flight_spatial_six_panel._cloud"
            ),
            mock.patch(
                "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_single_flight_spatial_six_panel._apply_shared_nice_ticks",
                return_value=1.0,
            ),
            mock.patch(
                "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_single_flight_spatial_six_panel._source_region_longitudinal",
                side_effect=AssertionError("must not draw absent source-region bounds"),
            ),
            mock.patch(
                "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_single_flight_spatial_six_panel._source_region_cross_section",
                side_effect=AssertionError("must not draw absent source-region bounds"),
            ),
        ):
            figure, metadata = build_figure(
                initial, checkpoints, {}, frontend, oatof, None
            )
        try:
            self.assertEqual(
                metadata["source_region_diagnostic"]["status"], "NOT_APPLICABLE"
            )
        finally:
            plt.close(figure)

    def test_analysis_mass_comes_from_frozen_initial_global_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "initial.csv"
            path.write_text(
                "particle_id,mass_amu\n1,50\n2,50.0\n", encoding="utf-8"
            )
            self.assertEqual(resolve_analysis_mass_amu(path), 50.0)
            path.write_text(
                "particle_id,mass_amu\n1,50\n2,100\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "exactly one mass_amu"):
                resolve_analysis_mass_amu(path)

    def test_resolution_qualification_uses_frozen_bootstrap_rule(self) -> None:
        valid = {
            "status": "computed",
            "resamples_requested": 5000,
            "resamples_valid": 4750,
            "relative_95pct_interval_width": 0.10,
        }
        summary = {
            "full_pulse_eligible_bootstrap": [valid],
            "spatial_window_peak": {"bootstrap": dict(valid)},
        }
        validate_resolution_qualification(summary, RESOLUTION_QUALIFICATION_POLICY)
        for field, value in (
            ("resamples_requested", 4999),
            ("resamples_valid", 4749),
            ("relative_95pct_interval_width", 0.1000001),
        ):
            invalid = json.loads(json.dumps(summary))
            invalid["full_pulse_eligible_bootstrap"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, "bootstrap acceptance failed"
            ):
                validate_resolution_qualification(
                    invalid, RESOLUTION_QUALIFICATION_POLICY
                )

    def test_three_zone_checkpoint_census_uses_frozen_monotonicity_rule(self) -> None:
        summary = {
            "census": {
                "launched": 3,
                "accelerator_grid1_forward": 3,
                "accelerator_intermediate2_forward": 2,
                "local_accelerator_exit": 1,
                "detector_crossing": 1,
            }
        }
        validate_three_zone_checkpoint_census(summary)
        loss_before_intermediate2 = json.loads(json.dumps(summary))
        loss_before_intermediate2["census"].update({
            "accelerator_intermediate2_forward": 0,
            "local_accelerator_exit": 0,
            "detector_crossing": 0,
        })
        validate_three_zone_checkpoint_census(loss_before_intermediate2)
        for field, value in (
            ("accelerator_intermediate2_forward", 4),
            ("local_accelerator_exit", 3),
            ("detector_crossing", 2),
        ):
            invalid = json.loads(json.dumps(summary))
            invalid["census"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, "checkpoint census differs"
            ):
                validate_three_zone_checkpoint_census(invalid)
        missing = json.loads(json.dumps(summary))
        del missing["census"]["accelerator_intermediate2_forward"]
        with self.assertRaisesRegex(ValueError, "checkpoint census differs"):
            validate_three_zone_checkpoint_census(missing)

    def test_accelerator_phase_space_uses_detector_blind_pre_pulse_cohort(self) -> None:
        checkpoints = pd.DataFrame(
            [
                {
                    "particle_id": 1,
                    "event": "pre_pulse_state",
                    "instrument_time_us": 58.7,
                    "x_mm": -69.1,
                    "y_mm": 0.1,
                    "z_mm": -61.0,
                    "vx_mm_per_us": 0.2,
                    "vy_mm_per_us": -0.1,
                    "vz_mm_per_us": 1.4,
                    "pulse_eligibility": "eligible",
                },
                {
                    "particle_id": 2,
                    "event": "pre_pulse_state",
                    "instrument_time_us": 58.7,
                    "x_mm": -68.8,
                    "y_mm": -0.2,
                    "z_mm": -60.5,
                    "vx_mm_per_us": -0.3,
                    "vy_mm_per_us": 0.2,
                    "vz_mm_per_us": 2.1,
                    "pulse_eligibility": "outside_transverse_bore",
                },
                {
                    "particle_id": 1,
                    "event": "detector_crossing",
                    "instrument_time_us": 75.0,
                    "x_mm": 49.0,
                    "y_mm": 0.0,
                    "z_mm": 19.8,
                    "vx_mm_per_us": "",
                    "vy_mm_per_us": "",
                    "vz_mm_per_us": "",
                    "pulse_eligibility": "eligible",
                },
            ]
        )
        figure, metadata, data = build_accelerator_phase_space_figure(checkpoints)
        try:
            self.assertEqual(len(figure.axes), 3)
            self.assertEqual(metadata["pre_pulse_count"], 2)
            self.assertEqual(metadata["pulse_eligible_count"], 1)
            self.assertEqual(metadata["not_pulse_eligible_count"], 1)
            self.assertFalse(metadata["selection_uses_detector_outcome"])
            self.assertEqual(list(data["particle_id"]), [1, 2])
            self.assertEqual(
                list(data.columns),
                [
                    "particle_id",
                    "event",
                    "instrument_time_us",
                    "x_mm",
                    "y_mm",
                    "z_mm",
                    "vx_m_per_s",
                    "vy_m_per_s",
                    "vz_m_per_s",
                    "pulse_eligibility",
                ],
            )
            self.assertEqual(figure.axes[2].get_xlabel(), "z (mm)")
            self.assertEqual(figure.axes[2].get_ylabel(), "vz (m/s)")
            self.assertEqual([panel["panel"] for panel in metadata["panels"]], ["x-vx", "y-vy", "z-vz"])
            for axis, panel in zip(figure.axes, metadata["panels"], strict=True):
                fit = panel["linear_fit"]
                self.assertEqual(fit["status"], "computed")
                self.assertEqual(fit["particle_count"], 2)
                self.assertAlmostEqual(fit["r_squared"], 1.0)
                self.assertAlmostEqual(fit["residual_rms_m_per_s"], 0.0)
                self.assertAlmostEqual(fit["residual_max_abs_m_per_s"], 0.0)
                self.assertEqual(len(axis.lines), 1)
                annotation = "\n".join(text.get_text() for text in axis.texts)
                self.assertIn("slope=", annotation)
                self.assertIn("R²=", annotation)
                self.assertIn("residual RMS=", annotation)
                self.assertIn("max|residual|=", annotation)
                self.assertIn("m/s/mm", annotation)
                self.assertIn("m/s", annotation)
            self.assertAlmostEqual(
                metadata["panels"][0]["linear_fit"]["slope_m_per_s_per_mm"],
                -5000.0 / 3.0,
            )
            self.assertAlmostEqual(
                metadata["panels"][1]["linear_fit"]["intercept_m_per_s"],
                0.0,
            )
            self.assertAlmostEqual(
                metadata["panels"][2]["linear_fit"]["slope_m_per_s_per_mm"],
                1400.0,
            )
        finally:
            plt.close(figure)

    def test_z_vz_diagnostics_report_linear_higher_order_and_random_residuals(self) -> None:
        """The checkpoint diagnostic retains an unfiltered, fixed nonlinear cohort."""

        z_values = [-2.0, -1.0, 0.0, 1.0, 2.0]
        rows = pd.DataFrame(
            {
                "x_mm": [0.0] * len(z_values),
                "y_mm": [0.0] * len(z_values),
                "z_mm": z_values,
                "vx_mm_per_us": [0.0] * len(z_values),
                "vy_mm_per_us": [0.0] * len(z_values),
                # v = 10 + 3z + 2z² + 0.5z³ in m/s.
                "vz_mm_per_us": [
                    (10.0 + 3.0 * z + 2.0 * z**2 + 0.5 * z**3) / 1000.0
                    for z in z_values
                ],
            }
        )
        diagnostic = _checkpoint_distribution_summary(rows, "local_accelerator_exit")["z_vz_affine"]
        self.assertEqual(diagnostic["status"], "computed")
        self.assertEqual(diagnostic["position_unit"], "mm")
        self.assertEqual(diagnostic["velocity_unit"], "m_per_s")
        self.assertAlmostEqual(diagnostic["slope_m_per_s_per_mm"], 4.7)
        self.assertAlmostEqual(diagnostic["intercept_m_per_s"], 14.0)
        self.assertGreater(diagnostic["residual_sigma_m_per_s"], 0.0)
        self.assertGreater(diagnostic["residual_rms_m_per_s"], 0.0)
        self.assertGreater(diagnostic["residual_max_abs_m_per_s"], 0.0)
        self.assertGreater(diagnostic["residual_p95_abs_m_per_s"], 0.0)
        quadratic = diagnostic["quadratic_fit"]
        cubic = diagnostic["cubic_fit"]
        self.assertEqual(quadratic["status"], "computed")
        self.assertEqual(cubic["status"], "computed")
        self.assertAlmostEqual(
            cubic["coefficients_m_per_s"]["constant"], 10.0
        )
        self.assertAlmostEqual(
            cubic["coefficients_m_per_s"]["linear_per_mm"], 3.0
        )
        self.assertAlmostEqual(
            cubic["coefficients_m_per_s"]["quadratic_per_mm2"], 2.0
        )
        self.assertAlmostEqual(
            cubic["coefficients_m_per_s"]["cubic_per_mm3"], 0.5
        )
        self.assertAlmostEqual(cubic["residual_rms_m_per_s"], 0.0, places=11)
        self.assertGreater(quadratic["relative_linear_residual_rms_reduction"], 0.0)
        self.assertAlmostEqual(cubic["relative_linear_residual_rms_reduction"], 1.0, places=11)
        random_residual = diagnostic["cubic_random_residual"]
        self.assertEqual(
            random_residual["definition"],
            "pointwise residual after the cubic least-squares fit",
        )
        self.assertAlmostEqual(random_residual["rms_m_per_s"], 0.0, places=11)

    def test_z_vz_diagnostics_fail_closed_for_degenerate_position_span(self) -> None:
        rows = pd.DataFrame(
            {
                "x_mm": [0.0, 0.0],
                "y_mm": [0.0, 0.0],
                "z_mm": [1.0, 1.0],
                "vx_mm_per_us": [0.0, 0.0],
                "vy_mm_per_us": [0.0, 0.0],
                "vz_mm_per_us": [0.1, 0.2],
            }
        )
        diagnostic = _checkpoint_distribution_summary(rows, "local_accelerator_exit")["z_vz_affine"]
        self.assertEqual(diagnostic["status"], "not_computed")
        self.assertEqual(diagnostic["reason"], "zero_z_span_or_single_particle")
        self.assertIsNone(diagnostic["slope_m_per_s_per_mm"])
        self.assertIsNone(diagnostic["quadratic_fit"])
        self.assertIsNone(diagnostic["cubic_fit"])
        self.assertIsNone(diagnostic["cubic_random_residual"])

    def test_checkpoint_evolution_csv_records_extended_z_vz_metrics(self) -> None:
        z_values = [-2.0, -1.0, 0.0, 1.0, 2.0]
        checkpoints = pd.DataFrame(
            {
                "particle_id": list(range(1, len(z_values) + 1)),
                "event": ["local_accelerator_exit"] * len(z_values),
                "instrument_time_us": [1.0] * len(z_values),
                "x_mm": [0.0] * len(z_values),
                "y_mm": [0.0] * len(z_values),
                "z_mm": z_values,
                "vx_mm_per_us": [0.0] * len(z_values),
                "vy_mm_per_us": [0.0] * len(z_values),
                "vz_mm_per_us": [
                    (10.0 + 3.0 * z + 2.0 * z**2 + 0.5 * z**3) / 1000.0
                    for z in z_values
                ],
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoints_path = root / "checkpoints.csv"
            figure_path = root / "evolution.png"
            metadata_path = root / "evolution.json"
            data_path = root / "evolution.csv"
            checkpoints.to_csv(checkpoints_path, index=False)
            write_checkpoint_evolution_outputs(
                checkpoints_path, figure_path, metadata_path, data_path
            )
            table = pd.read_csv(data_path)
        self.assertIn("z_vz_k_m_per_s_per_mm", table.columns)
        self.assertIn("z_vz_linear_residual_sigma_m_per_s", table.columns)
        self.assertIn("z_vz_quadratic_coefficient_m_per_s_per_mm2", table.columns)
        self.assertIn("z_vz_cubic_coefficient_m_per_s_per_mm3", table.columns)
        self.assertIn("z_vz_cubic_random_residual_rms_m_per_s", table.columns)
        self.assertAlmostEqual(table.loc[0, "z_vz_k_m_per_s_per_mm"], 4.7)
        self.assertAlmostEqual(
            table.loc[0, "z_vz_cubic_coefficient_m_per_s_per_mm3"], 0.5
        )

    def test_n1000_marker_does_not_obscure_geometry(self) -> None:
        self.assertLess(marker_area(1000), marker_area(100))
        self.assertLessEqual(marker_area(1000), 2.0)

    def test_three_zone_panel_d_renders_electrode_thickness_and_grid_planes(self) -> None:
        oatof = {
            "geometry_mm": {
                "accelerator_bore_half": 5.0,
                "accelerator_ring_width": 5.0,
                "accelerator_ring_thickness": 1.0,
                "accelerator_repeller_thickness": 1.5,
                "accelerator_exit_grid_half_width": 15.0,
                "accelerator_shield_wall": 4.0,
            },
            "coordinate_convention": {"accelerator_axis_x": -69.0},
            "rings": {"accelerator_count": 2},
            "accelerator_topology": {
                "topology_id": "three_zone_accelerator_ideal_v1",
                "planes_global_z_mm": {
                    "repeller": -63.0,
                    "intermediate1": -59.75,
                    "intermediate2": -54.65,
                    "exit": -42.75,
                },
            },
        }
        frontend = {
            "accelerator_topology_id": "three_zone_accelerator_ideal_v1",
            "accelerator_local_region": {
                "axis_x_mm": -69.0, "axis_y_mm": 0.0,
                "shield_center_z_mm": -57.875,
                "shield_outer_width_mm": 38.0, "shield_inner_width_mm": 30.0,
                "shield_span_z_mm": 30.25, "negative_x_face_mm": -88.0,
                "shield_wall_mm": 4.0, "shield_back_z_mm": -73.0,
                "grid2_z_mm": -42.75, "ring_z_mm": [-56.9, -48.4],
                "repeller_front_z_mm": -63.0, "repeller_thickness_mm": 1.5,
                "grid1_z_mm": -59.75,
                "intermediate2_z_mm": -54.65,
                "electrode_width_mm": 20.0,
                "port_center_y_mm": 0.0, "port_center_z_mm": -61.5,
                "numerical_port_width_mm": 2.0,
                "numerical_port_height_mm": 1.0,
            },
            "source_exit_center_mm": {"x": -88.0, "y": 0.0, "z": -61.5},
        }
        figure, axis = plt.subplots()
        try:
            _accelerator(axis, oatof, frontend)
            dashed = [float(line.get_ydata()[0]) for line in axis.lines if line.get_linestyle() == "--"]
            patches = list(axis.patches)
        finally:
            plt.close(figure)
        self.assertEqual(dashed, [-59.75, -54.65, -42.75])
        self.assertEqual(
            [float(line.get_xdata()[1] - line.get_xdata()[0])
             for line in axis.lines if line.get_linestyle() == "--"],
            [20.0, 20.0, 30.0],
        )
        self.assertEqual(len(patches), 7)
        self.assertIsInstance(patches[0], PathPatch)
        shield_path = patches[0].get_path()
        self.assertEqual(
            (shield_path.get_extents().xmin, shield_path.get_extents().ymin,
             shield_path.get_extents().width, shield_path.get_extents().height),
            (-88.0, -73.0, 38.0, 30.25),
        )
        self.assertEqual(list(shield_path.codes).count(shield_path.MOVETO), 1)
        self.assertEqual(len(shield_path.vertices), 9)
        self.assertIn(patches[0].get_linestyle(), ("-", "solid"))
        self.assertEqual(
            [patch.get_label() for patch in patches].count("accelerator shield body"),
            1,
        )
        self.assertNotIn("outer", str(patches[0].get_label()))
        self.assertEqual(
            (patches[1].get_x(), patches[1].get_y(), patches[1].get_width(), patches[1].get_height()),
            (-88.0, -62.0, 4.0, 1.0),
        )
        self.assertEqual((patches[2].get_y(), patches[2].get_height()), (-64.5, 1.5))
        self.assertEqual(
            sorted((patch.get_y(), patch.get_height()) for patch in patches[3:]),
            [(-57.4, 1.0), (-57.4, 1.0), (-48.9, 1.0), (-48.9, 1.0)],
        )
        self.assertNotIn("shield wall 4 mm", [line.get_label() for line in axis.lines])

    def test_panel_e_shows_exit_grid_and_ring_inner_outer_widths(self) -> None:
        oatof = {
            "geometry_mm": {
                "accelerator_bore_half": 5.0,
                "accelerator_ring_width": 5.0,
                "accelerator_exit_grid_half_width": 15.0,
                "accelerator_shield_wall": 3.0,
            },
            "coordinate_convention": {"accelerator_axis_x": -69.0},
        }
        frontend = {"accelerator_local_region": {
            "axis_x_mm": -69.0, "axis_y_mm": 0.0,
            "shield_center_z_mm": -55.0,
            "shield_outer_width_mm": 46.0, "shield_inner_width_mm": 40.0,
            "shield_span_z_mm": 24.0, "negative_x_face_mm": -92.0,
            "shield_wall_mm": 3.0, "shield_back_z_mm": -67.0,
            "grid2_z_mm": -43.0,
            "port_center_y_mm": 1.0, "port_center_z_mm": -55.0,
            "numerical_port_width_mm": 6.0,
            "numerical_port_height_mm": 4.0,
        }, "source_exit_center_mm": {"x": -92.0, "y": 1.0, "z": -55.0}}
        figure, axis = plt.subplots()
        try:
            _accelerator_cross_section(axis, oatof, frontend)
            boxes = list(axis.patches)
        finally:
            plt.close(figure)
        self.assertEqual(len(boxes), 4)
        self.assertIsInstance(boxes[0], PathPatch)
        shield_path = boxes[0].get_path()
        self.assertEqual(list(shield_path.codes).count(shield_path.MOVETO), 2)
        self.assertEqual(
            (shield_path.get_extents().xmin, shield_path.get_extents().xmax,
             shield_path.get_extents().ymin, shield_path.get_extents().ymax),
            (-92.0, -46.0, -23.0, 23.0),
        )
        self.assertIn(boxes[0].get_linestyle(), ("-", "solid"))
        self.assertEqual((boxes[1].get_x(), boxes[1].get_width()), (-92.0, 3.0))
        self.assertEqual((boxes[1].get_y(), boxes[1].get_height()), (-2.0, 6.0))
        self.assertIsInstance(boxes[2], PathPatch)
        ring_path = boxes[2].get_path()
        self.assertEqual(list(ring_path.codes).count(ring_path.MOVETO), 2)
        self.assertEqual(
            (ring_path.get_extents().xmin, ring_path.get_extents().xmax,
             ring_path.get_extents().ymin, ring_path.get_extents().ymax),
            (-79.0, -59.0, -10.0, 10.0),
        )
        labels = [box.get_label() for box in boxes]
        self.assertNotIn("shield inner vacuum", labels)
        self.assertNotIn("shield outer body", labels)
        self.assertEqual(labels.count("accelerator shield body"), 1)
        self.assertNotIn("ring outer width", labels)
        self.assertNotIn("ring inner bore", labels)
        self.assertEqual(labels.count("shaping ring body (inner/outer width)"), 1)
        self.assertEqual(labels.count("exit-grid extent"), 1)

    def test_compound_frame_follows_changed_geometry(self) -> None:
        frame = _rectangular_frame_path(
            (-17.0, 8.0, 60.0, 42.0),
            (-12.0, 13.0, 50.0, 37.0),
        )
        self.assertEqual(list(frame.codes).count(frame.MOVETO), 2)
        self.assertEqual(
            (frame.get_extents().xmin, frame.get_extents().xmax,
             frame.get_extents().ymin, frame.get_extents().ymax),
            (-17.0, 43.0, 8.0, 50.0),
        )
    def test_shared_nice_ticks_follow_current_and_larger_geometry(self) -> None:
        figure, axes = plt.subplots(2, 2)
        current_d, current_e, larger_d, larger_e = axes.flat
        try:
            current_d.set(xlim=(-89.9, -48.1), ylim=(-74.5125, -41.2375))
            current_e.set(xlim=(-89.9, -48.1), ylim=(-20.9, 20.9))
            current_step = _apply_shared_nice_ticks((current_d, current_e))
            larger_d.set(xlim=(-130.0, -42.0), ylim=(-98.0, -40.0))
            larger_e.set(xlim=(-130.0, -42.0), ylim=(-44.0, 44.0))
            larger_step = _apply_shared_nice_ticks((larger_d, larger_e))
            current_locators = (
                current_d.xaxis.get_major_locator(), current_d.yaxis.get_major_locator(),
                current_e.xaxis.get_major_locator(), current_e.yaxis.get_major_locator(),
            )
            larger_locators = (
                larger_d.xaxis.get_major_locator(), larger_d.yaxis.get_major_locator(),
                larger_e.xaxis.get_major_locator(), larger_e.yaxis.get_major_locator(),
            )
        finally:
            plt.close(figure)
        self.assertEqual(current_step, 5.0)
        self.assertEqual(larger_step, 10.0)
        for locator in current_locators:
            ticks = locator.tick_values(0.0, 20.0)
            self.assertTrue(all(abs(right - left - 5.0) < 1e-12 for left, right in zip(ticks, ticks[1:])))
        for locator in larger_locators:
            ticks = locator.tick_values(0.0, 40.0)
            self.assertTrue(all(abs(right - left - 10.0) < 1e-12 for left, right in zip(ticks, ticks[1:])))

    def test_shield_geometry_fails_closed_on_inconsistent_wall(self) -> None:
        oatof = {
            "geometry_mm": {"accelerator_shield_wall": 4.0},
            "coordinate_convention": {"accelerator_axis_x": -69.0},
        }
        frontend = {"accelerator_local_region": {
            "axis_x_mm": -69.0, "axis_y_mm": 0.0,
            "shield_center_z_mm": -57.875,
            "shield_outer_width_mm": 38.0, "shield_inner_width_mm": 31.0,
            "shield_span_z_mm": 30.25, "negative_x_face_mm": -88.0,
            "shield_wall_mm": 4.0, "shield_back_z_mm": -73.0,
            "grid2_z_mm": -42.75,
        }}
        with self.assertRaisesRegex(ValueError, "shield geometry is inconsistent"):
            _accelerator_shield_geometry(oatof, frontend)

    def test_shield_geometry_requires_all_frozen_frontend_fields(self) -> None:
        oatof = {
            "geometry_mm": {"accelerator_shield_wall": 4.0},
            "coordinate_convention": {"accelerator_axis_x": -69.0},
        }
        with self.assertRaises(KeyError):
            _accelerator_shield_geometry(
                oatof, {"accelerator_local_region": {"axis_x_mm": -69.0}}
            )

    def test_connector_through_hole_requires_complete_frontend_fields(self) -> None:
        oatof = {
            "geometry_mm": {"accelerator_shield_wall": 4.0},
            "coordinate_convention": {"accelerator_axis_x": -69.0},
        }
        with self.assertRaises(KeyError):
            _connector_through_hole_geometry(
                oatof, {"accelerator_local_region": {"axis_x_mm": -69.0}}
            )

    def test_source_region_panels_follow_analyzer_resolved_bounds(self) -> None:
        first = {"particle_source": {
            "center_x_mm": -69.0, "center_y_mm": 0.5,
            "center_z_mm": -61.5, "size_z_mm": 2.2,
        }, "geometry_mm": {
            "accelerator_repeller_z": -64.0,
            "accelerator_grid1_z": -63.0,
            "accelerator_repeller_thickness": 1.0,
        }}
        second = {"particle_source": {
            "center_x_mm": -42.0, "center_y_mm": -1.5,
            "center_z_mm": 7.0, "size_z_mm": 5.5,
        }, "geometry_mm": {
            "accelerator_repeller_z": 10.0,
            "accelerator_grid1_z": 8.0,
            "accelerator_repeller_thickness": 2.0,
        }}
        first_frontend = {"accelerator_local_region": {
            "repeller_front_z_mm": -64.0, "repeller_thickness_mm": 1.0,
            "grid1_z_mm": -63.0,
        }}
        second_frontend = {"accelerator_local_region": {
            "repeller_front_z_mm": 10.0, "repeller_thickness_mm": 2.0,
            "grid1_z_mm": 8.0,
        }}
        def diagnostic(center_x, center_y, center_z, width_z):
            centers = {"x": center_x, "y": center_y, "z": center_z}
            widths = {"x": 2.0, "y": 2.0, "z": width_z}
            return {
                "profile_id": "layout_resolved_axial_provisional_xy2_v1",
                "role": "layout_resolved_source_region_diagnostic",
                "claim_status": "PROVISIONAL_DIAGNOSTIC_ONLY",
                "event": "pre_pulse_state",
                "population_basis": "pulse_eligible",
                "selection_uses_detector_outcome": False,
                "bounds": {
                    axis: {
                        "center_binding": f"particle_source.center_{axis}_mm",
                        "center_mm": centers[axis],
                        "full_width_binding": (
                            "particle_source.size_z_mm" if axis == "z" else None
                        ),
                        "full_width_mm": widths[axis],
                        "minimum_mm": centers[axis] - widths[axis] / 2,
                        "maximum_mm": centers[axis] + widths[axis] / 2,
                    }
                    for axis in ("x", "y", "z")
                },
            }
        first_diagnostic = diagnostic(-69.0, 0.5, -61.5, 2.2)
        second_diagnostic = diagnostic(-42.0, -1.5, 7.0, 5.5)
        first_figure, (first_d, first_e) = plt.subplots(1, 2)
        second_figure, (second_d, second_e) = plt.subplots(1, 2)
        try:
            _source_region_longitudinal(
                first_d, first_diagnostic, first, first_frontend
            )
            _source_region_cross_section(first_e, first_diagnostic)
            _source_region_longitudinal(
                second_d, second_diagnostic, second, second_frontend
            )
            _source_region_cross_section(second_e, second_diagnostic)
            first_long = first_d.patches[0]
            second_long = second_d.patches[0]
            first_cross = first_e.patches[0]
            second_cross = second_e.patches[0]
        finally:
            plt.close(first_figure)
            plt.close(second_figure)
        self.assertEqual((first_long.get_x(), first_long.get_y()), (-70.0, -62.6))
        self.assertEqual((first_long.get_width(), first_long.get_height()), (2.0, 2.2))
        self.assertEqual((second_long.get_x(), second_long.get_y()), (-43.0, 4.25))
        self.assertEqual((second_long.get_width(), second_long.get_height()), (2.0, 5.5))
        self.assertEqual((first_cross.get_x(), first_cross.get_y()), (-70.0, -0.5))
        self.assertEqual((second_cross.get_x(), second_cross.get_y()), (-43.0, -2.5))

    def test_repeller_body_extends_away_from_vacuum_in_either_direction(self) -> None:
        positive = {
            "geometry_mm": {
                "accelerator_repeller_z": -63.0,
                "accelerator_grid1_z": -59.75,
                "accelerator_repeller_thickness": 1.5,
            }
        }
        negative = {
            "geometry_mm": {
                "accelerator_repeller_z": 12.0,
                "accelerator_grid1_z": 8.0,
                "accelerator_repeller_thickness": 2.0,
            }
        }
        positive_body = _repeller_body_geometry(
            positive, {"accelerator_local_region": {
                "repeller_front_z_mm": -63.0, "repeller_thickness_mm": 1.5,
                "grid1_z_mm": -59.75,
            }}
        )
        negative_body = _repeller_body_geometry(
            negative, {"accelerator_local_region": {
                "repeller_front_z_mm": 12.0, "repeller_thickness_mm": 2.0,
                "grid1_z_mm": 8.0,
            }}
        )
        self.assertEqual((positive_body["z_min"], positive_body["z_max"]), (-64.5, -63.0))
        self.assertEqual((negative_body["z_min"], negative_body["z_max"]), (12.0, 14.0))

    def test_boundary_plane_widths_follow_different_reversed_fixture(self) -> None:
        oatof = {
            "geometry_mm": {
                "accelerator_bore_half": 3.0,
                "accelerator_ring_width": 4.0,
                "accelerator_exit_grid_half_width": 9.0,
                "accelerator_grid1_z": 16.0,
                "accelerator_grid2_z": 10.0,
            }
        }
        frontend = {"accelerator_local_region": {
            "electrode_width_mm": 14.0,
            "grid1_z_mm": 16.0,
            "grid2_z_mm": 10.0,
        }}
        self.assertEqual(
            _accelerator_boundary_planes(oatof, frontend),
            [(16.0, 7.0), (10.0, 9.0)],
        )

    def test_boundary_plane_width_rejects_frontend_mismatch(self) -> None:
        oatof = {
            "geometry_mm": {
                "accelerator_bore_half": 5.0,
                "accelerator_ring_width": 5.0,
                "accelerator_exit_grid_half_width": 15.0,
                "accelerator_grid1_z": -59.75,
                "accelerator_grid2_z": -42.75,
            }
        }
        frontend = {"accelerator_local_region": {
            "electrode_width_mm": 19.0,
            "grid1_z_mm": -59.75,
            "grid2_z_mm": -42.75,
        }}
        with self.assertRaisesRegex(ValueError, "boundary-plane geometry is inconsistent"):
            _accelerator_boundary_planes(oatof, frontend)

    def test_source_region_bounds_fail_closed_on_invalid_or_missing_input(self) -> None:
        diagnostic = {
            "role": "layout_resolved_source_region_diagnostic",
            "claim_status": "PROVISIONAL_DIAGNOSTIC_ONLY",
            "event": "pre_pulse_state",
            "population_basis": "pulse_eligible",
            "selection_uses_detector_outcome": False,
            "bounds": {},
        }
        with self.assertRaisesRegex(ValueError, "identity is invalid"):
            _source_region_bounds(diagnostic)
        diagnostic["bounds"] = {
            axis: {
                "center_binding": f"particle_source.center_{axis}_mm",
                "center_mm": float("nan") if axis == "z" else 0.0,
                "full_width_binding": (
                    "particle_source.size_z_mm" if axis == "z" else None
                ),
                "full_width_mm": 2.0,
                "minimum_mm": -1.0,
                "maximum_mm": 1.0,
            }
            for axis in ("x", "y", "z")
        }
        with self.assertRaisesRegex(ValueError, "bound is invalid"):
            _source_region_bounds(diagnostic)

    def test_preserves_original_ion_identity_at_all_checkpoints(self) -> None:
        text = "\n".join(
            [
                "TRACE: source_release ion=2 instrument_time_us=0 x_mm=-68.8 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=2 vz_mm_per_us=3",
                "TRACE: single_flight_handoff ion=2 instrument_time_us=10 x_mm=-67.8 y_mm=0 z_mm=-18.4 vx_mm_per_us=1 vy_mm_per_us=2 vz_mm_per_us=3",
                "TRACE: pre_pulse_state ion=2 instrument_time_us=20 x_mm=-48.8 y_mm=0 z_mm=1.5 vx_mm_per_us=1 vy_mm_per_us=2 vz_mm_per_us=3",
                "TRACE: local_accelerator_exit ion=2 instrument_time_us=41 x_mm=-67 y_mm=0 z_mm=20 vx_mm_per_us=2 vy_mm_per_us=0 vz_mm_per_us=20",
                "TRACE: detector_crossing ion=2 t=70 x=49 y=0 z=19.83 r=0 zmax=19.83",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.txt"
            path.write_text(text, encoding="utf-8")
            rows, summary = analyze(path, 3, 100.0)
        self.assertEqual({row["particle_id"] for row in rows}, {2})
        self.assertEqual(summary["census"]["launched"], 3)
        self.assertEqual(summary["census"]["detector_crossing"], 1)
        self.assertEqual(summary["census"]["reflectron_turning_point"], 0)
        self.assertNotIn("instrument_clock_peak", summary)
        self.assertNotIn("instrument_clock_peak_is_resolution_claim", summary)
        pre_pulse = next(row for row in rows if row["event"] == "pre_pulse_state")
        self.assertGreater(pre_pulse["kinetic_energy_eV"], 0.0)

    def test_accepts_terminal_handoff_continuation_source_mode(self) -> None:
        text = (
            "TRACE: pre_pulse_state ion=1 particle_id=1 "
            "instrument_time_us=20 x_mm=-48.8 y_mm=0 z_mm=1.5 "
            "vx_mm_per_us=1 vy_mm_per_us=2 vz_mm_per_us=3\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.txt"
            path.write_text(text, encoding="utf-8")
            rows, summary = analyze(
                path, 1, 100.0,
                source_release_mode="continuous_frontend_handoff",
            )
        self.assertEqual(rows[0]["event"], "pre_pulse_state")
        self.assertEqual(summary["census"]["pre_pulse_state"], 1)

    def test_terminal_handoff_allows_physical_loss_before_pulse(self) -> None:
        text = (
            "TRACE: pre_pulse_state ion=1 particle_id=1 "
            "instrument_time_us=20 x_mm=-48.8 y_mm=0 z_mm=1.5 "
            "vx_mm_per_us=1 vy_mm_per_us=2 vz_mm_per_us=3\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.txt"
            path.write_text(text, encoding="utf-8")
            _, summary = analyze(
                path, 2, 100.0, pulse_time_us=20.0,
                population_denominator_count=3,
                eligible_population_count=2,
                source_release_mode="continuous_frontend_handoff",
            )
        self.assertEqual(
            summary["source_population"]["simulation_population_basis"],
            "terminal_handoff_full_population",
        )
        self.assertIsNone(
            summary["source_population"]["simulated_fraction_of_pulse_eligible_population"]
        )

    def test_publishes_three_zone_intermediate2_checkpoint_and_census(self) -> None:
        text = "\n".join(
            [
                "TRACE: accelerator_grid1_forward ion=1 particle_id=1 "
                "instrument_time_us=20 tof_since_pulse_us=10 x_mm=0 y_mm=0 z_mm=10 "
                "vx_mm_per_us=0 vy_mm_per_us=0 vz_mm_per_us=1",
                "TRACE: accelerator_intermediate2_forward ion=1 particle_id=1 "
                "instrument_time_us=21 tof_since_pulse_us=11 x_mm=0 y_mm=0 z_mm=20 "
                "vx_mm_per_us=0 vy_mm_per_us=0 vz_mm_per_us=1",
                "TRACE: local_accelerator_exit ion=1 particle_id=1 "
                "instrument_time_us=22 tof_since_pulse_us=12 x_mm=0 y_mm=0 z_mm=30 "
                "vx_mm_per_us=0 vy_mm_per_us=0 vz_mm_per_us=1",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.txt"
            log.write_text(text, encoding="utf-8")
            rows, summary = analyze(log, 1, 100.0, pulse_time_us=10.0)

        intermediate2 = [row for row in rows if row["event"] == "accelerator_intermediate2_forward"]
        self.assertEqual(len(intermediate2), 1)
        self.assertEqual(intermediate2[0]["particle_id"], 1)
        self.assertEqual(intermediate2[0]["pulse_effective_elapsed_us"], 11.0)
        self.assertEqual(summary["census"]["accelerator_intermediate2_forward"], 1)

    def test_two_zone_census_publishes_zero_intermediate2_count(self) -> None:
        text = (
            "TRACE: accelerator_grid1_forward ion=1 particle_id=1 "
            "instrument_time_us=20 x_mm=0 y_mm=0 z_mm=10 "
            "vx_mm_per_us=0 vy_mm_per_us=0 vz_mm_per_us=1\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.txt"
            log.write_text(text, encoding="utf-8")
            _, summary = analyze(log, 1, 100.0)

        self.assertEqual(summary["census"]["accelerator_intermediate2_forward"], 0)

    def test_rejects_duplicate_intermediate2_checkpoint_per_particle(self) -> None:
        checkpoint = (
            "TRACE: accelerator_intermediate2_forward ion=1 particle_id=1 "
            "instrument_time_us=21 tof_since_pulse_us=11 x_mm=0 y_mm=0 z_mm=20 "
            "vx_mm_per_us=0 vy_mm_per_us=0 vz_mm_per_us=1"
        )
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.txt"
            log.write_text(f"{checkpoint}\n{checkpoint}\n", encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "duplicate checkpoint: particle=1 event=accelerator_intermediate2_forward",
            ):
                analyze(log, 1, 100.0, pulse_time_us=10.0)

    def test_target_energy_uses_pre_pulse_state_inside_accelerator(self) -> None:
        text = "\n".join(
            [
                "TRACE: single_flight_handoff ion=1 instrument_time_us=9 x_mm=-88 y_mm=0 z_mm=-18.4 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
                "TRACE: pre_pulse_state ion=1 instrument_time_us=10 x_mm=-69 y_mm=0 z_mm=-18.4 vx_mm_per_us=4.392 vy_mm_per_us=0 vz_mm_per_us=0",
                "TRACE: handoff_pulse_on ion=1 instrument_time_us=10",
            ]
        )
        geometry = {
            "coordinate_convention": {"accelerator_axis_x": -69.0},
            "geometry_mm": {
                "accelerator_repeller_z": -19.9,
                "accelerator_grid1_z": -16.9,
                "accelerator_bore_half": 5.0,
            },
            "single_flight_layout_derivation": {"target_injection_energy_eV": 10.0},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "log.txt"
            model = root / "geometry.json"
            log.write_text(text, encoding="utf-8")
            model.write_text(json.dumps(geometry), encoding="utf-8")
            rows, summary = analyze(log, 1, 100.0, model, 10.0)
        validation = summary["injection_energy_validation"]
        self.assertEqual(validation["sampling_event"], "pre_pulse_state")
        self.assertEqual(validation["sample_count"], 1)
        self.assertFalse(validation["terminal_or_handoff_energy_is_target_validation"])
        handoff = next(row for row in rows if row["event"] == "multipole_handoff")
        sample = next(row for row in rows if row["event"] == "pre_pulse_state")
        self.assertNotEqual(handoff["kinetic_energy_eV"], sample["kinetic_energy_eV"])
        self.assertEqual(sample["pulse_eligibility"], "eligible")
        self.assertEqual(summary["pulse_capture"]["counts"]["eligible"], 1)
        self.assertFalse(summary["pulse_capture"]["selection_uses_detector_outcome"])

    def test_successor_pulse_callbacks_validate_effective_pulse_time(self) -> None:
        text = "\n".join(
            [
                "TRACE: source_release ion=1 instrument_time_us=0 x_mm=-69 y_mm=0 z_mm=-18.4 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
                "TRACE: source_release ion=2 instrument_time_us=0 x_mm=-69 y_mm=0 z_mm=-18.3 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
                "TRACE: pre_pulse_state ion=1 instrument_time_us=10 x_mm=-69 y_mm=0 z_mm=-18.4 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
                "TRACE: pre_pulse_state ion=2 instrument_time_us=10 x_mm=-69 y_mm=0 z_mm=-18.3 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
                "TRACE: handoff_pulse_on ion=1 instrument_time_us=10",
                "TRACE: handoff_pulse_on ion=2 instrument_time_us=10",
                "TRACE: detector_crossing ion=1 t=20 x=0 y=0 z=0",
                "TRACE: detector_crossing ion=2 t=20.001 x=0 y=0 z=0",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.txt"
            log.write_text(text, encoding="utf-8")
            _, summary = analyze(log, 2, 100.0, pulse_time_us=10.0)
        self.assertEqual(summary["pulse_effective_time_us"], 10.0)
        self.assertEqual(summary["pulse_first_observed_us"], 10.0)

    def test_legacy_pulse_trace_without_particle_identity_remains_readable(self) -> None:
        text = "\n".join(
            [
                "TRACE: source_release ion=1 instrument_time_us=0 x_mm=0 y_mm=0 "
                "z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0",
                "TRACE: handoff_pulse_on instrument_time_us=10",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.txt"
            log.write_text(text, encoding="utf-8")
            _, summary = analyze(log, 1, 100.0, pulse_time_us=10.0)
        self.assertEqual(summary["pulse_first_observed_us"], 10.0)

    def test_successor_pulse_trace_rejects_inconsistent_particle_times(self) -> None:
        text = "\n".join(
            [
                "TRACE: source_release ion=1 instrument_time_us=0 x_mm=0 y_mm=0 "
                "z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0",
                "TRACE: handoff_pulse_on ion=1 instrument_time_us=10.000001",
                "TRACE: handoff_pulse_on ion=2 instrument_time_us=10.000002",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.txt"
            log.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SIMION batches report inconsistent pulse effective times"):
                analyze(log, 2, 100.0, pulse_time_us=10.0)

    def test_canonical_clock_does_not_add_birth_time_to_detector_time(self) -> None:
        text = "\n".join(
            [
                "TRACE: source_release ion=1 instrument_time_us=0.25 x_mm=-70 y_mm=0 z_mm=-18 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
                "TRACE: source_release ion=2 instrument_time_us=0.75 x_mm=-70 y_mm=0 z_mm=-18 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
                "TRACE: detector_crossing ion=1 t=70.5 x=69 y=0 z=0",
                "TRACE: detector_crossing ion=2 t=70.0 x=69 y=0 z=0",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.txt"
            log.write_text(text, encoding="utf-8")
            rows, summary = analyze(log, 2, 100.0)
        detector_times = [row["instrument_time_us"] for row in rows if row["event"] == "detector_crossing"]
        self.assertEqual(detector_times, [70.75, 70.75])
        self.assertEqual(summary["detector_time_basis"], "canonical_instrument_time_us")

    def test_five_batch_logs_receive_global_particle_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = []
            for batch_index in range(5):
                log = root / f"batch{batch_index + 1}.txt"
                log.write_text(
                    "TRACE: source_release ion=1 instrument_time_us=0 "
                    "x_mm=0 y_mm=0 z_mm=0 vx_mm_per_us=1 "
                    "vy_mm_per_us=0 vz_mm_per_us=0\n"
                    f"TRACE: detector_crossing ion=1 t={70 + batch_index * 0.01} "
                    "x=1 y=0 z=0\n",
                    encoding="utf-8",
                )
                logs.append(log)
            rows, summary = analyze(logs, 5, 100.0, batch_particle_counts=[1] * 5)
        self.assertEqual(sorted({row["particle_id"] for row in rows}), [1, 2, 3, 4, 5])
        self.assertEqual(summary["census"]["detector_crossing"], 5)

    def test_rejects_noncanonical_local_elapsed_basis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.txt"
            log.write_text(
                "TRACE: detector_crossing ion=1 t=70 x=69 y=0 z=0",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "requires canonical instrument time"):
                analyze(log, 1, 100.0, clock_basis="local_elapsed_us")

    def test_canonical_clock_recovers_release_from_frozen_initial_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "log.txt"
            initial = root / "initial.csv"
            log.write_text(
                "TRACE: detector_crossing ion=1 t=70.5 x=69 y=0 z=0",
                encoding="utf-8",
            )
            initial.write_text(
                "particle_id,instrument_time_us,mass_amu,charge_state,"
                "position_x_mm,position_y_mm,position_z_mm,velocity_x_m_s,"
                "velocity_y_m_s,velocity_z_m_s,kinetic_energy_eV\n"
                "1,0.25,100,1,-70,0,-18,4000,0,0,8.29\n",
                encoding="utf-8",
            )
            rows, summary = analyze(
                log,
                1,
                100.0,
                initial_global_state_path=initial,
            )
        detector = next(row for row in rows if row["event"] == "detector_crossing")
        self.assertEqual(detector["instrument_time_us"], 70.75)
        self.assertEqual(summary["census"]["source_release"], 1)

    def test_full_flight_terminal_taxonomy_is_exhaustive_and_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "log.txt"
            initial = root / "initial.csv"
            log.write_text(
                "TRACE: source_release ion=1 instrument_time_us=0 x_mm=0 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0\n"
                "TRACE: source_release ion=2 instrument_time_us=0 x_mm=0 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0\n"
                "TRACE: detector_crossing ion=1 t=70 x=0 y=0 z=0\n"
                "TRACE: non_detector_splat ion=2 instance=3 t=1 x=0 y=0 z=0 zmax=0\n",
                encoding="utf-8",
            )
            initial.write_text(
                "particle_id,instrument_time_us,mass_amu,charge_state,position_x_mm,position_y_mm,position_z_mm,velocity_x_m_s,velocity_y_m_s,velocity_z_m_s,kinetic_energy_eV\n"
                "1,0,100,1,0,0,0,1000,0,0,0.5182137\n"
                "2,0,100,1,0,0,0,1000,0,0,0.5182137\n",
                encoding="utf-8",
            )
            _, summary = analyze(
                log, 2, 100.0, initial_global_state_path=initial,
                require_terminal_taxonomy=True,
            )
        taxonomy = summary["terminal_taxonomy"]
        self.assertTrue(taxonomy["classification_is_mutually_exclusive_and_exhaustive"])
        self.assertEqual(taxonomy["mother_cohort_count"], 2)
        self.assertEqual(taxonomy["terminal_outcome_count"], 2)
        self.assertEqual(taxonomy["category_counts"], {
            "detector_crossing": 1, "non_detector_splat_instance_3": 1,
        })
        self.assertEqual(
            taxonomy["particle_outcomes"],
            [
                {"particle_id": 1, "category": "detector_crossing", "terminal_event": "detector_crossing", "instance_id": 4, "terminal_elapsed_us": 70.0, "x_mm": 0.0, "y_mm": 0.0, "z_mm": 0.0, "zmax_mm": None},
                {"particle_id": 2, "category": "non_detector_splat_instance_3", "terminal_event": "non_detector_splat", "instance_id": 3, "terminal_elapsed_us": 1.0, "x_mm": 0.0, "y_mm": 0.0, "z_mm": 0.0, "zmax_mm": 0.0},
            ],
        )

    def test_full_flight_terminal_taxonomy_rejects_missing_or_duplicate_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initial = root / "initial.csv"
            initial.write_text(
                "particle_id,instrument_time_us,mass_amu,charge_state,position_x_mm,position_y_mm,position_z_mm,velocity_x_m_s,velocity_y_m_s,velocity_z_m_s,kinetic_energy_eV\n"
                "1,0,100,1,0,0,0,1000,0,0,0.5182137\n"
                "2,0,100,1,0,0,0,1000,0,0,0.5182137\n",
                encoding="utf-8",
            )
            base = (
                "TRACE: source_release ion=1 instrument_time_us=0 x_mm=0 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0\n"
                "TRACE: source_release ion=2 instrument_time_us=0 x_mm=0 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0\n"
            )
            missing = root / "missing.txt"
            missing.write_text(base + "TRACE: detector_crossing ion=1 t=70 x=0 y=0 z=0\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lacks terminal outcome"):
                analyze(missing, 2, 100.0, initial_global_state_path=initial, require_terminal_taxonomy=True)
            duplicate = root / "duplicate.txt"
            duplicate.write_text(
                base
                + "TRACE: detector_crossing ion=1 t=70 x=0 y=0 z=0\n"
                + "TRACE: non_detector_splat ion=1 instance=3 t=1 x=0 y=0 z=0 zmax=0\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate terminal outcome: particle=1"):
                analyze(duplicate, 2, 100.0, initial_global_state_path=initial, require_terminal_taxonomy=True)

    def test_prepulse_restart_synthesizes_analysis_only_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "log.txt"
            initial = root / "initial.csv"
            log.write_text("", encoding="utf-8")
            initial.write_text(
                "particle_id,instrument_time_us,mass_amu,charge_state,"
                "position_x_mm,position_y_mm,position_z_mm,velocity_x_m_s,"
                "velocity_y_m_s,velocity_z_m_s,kinetic_energy_eV\n"
                "1,45.5,100,1,-69,0,-66,4392.842636759329,0,0,10\n",
                encoding="utf-8",
            )
            digest = hashlib.sha256(initial.read_bytes()).hexdigest()
            rows, summary = analyze(
                log,
                1,
                100.0,
                pulse_time_us=45.5,
                initial_global_state_path=initial,
                source_release_mode="pre_pulse_restart",
                initial_global_state_sha256=digest,
            )
        checkpoint = next(row for row in rows if row["event"] == "pre_pulse_state")
        self.assertEqual(checkpoint["instrument_time_us"], 45.5)
        self.assertEqual(checkpoint["pulse_effective_elapsed_us"], 0.0)
        self.assertEqual(
            checkpoint["checkpoint_provenance"],
            "pre_pulse_restart_initial_global_state",
        )
        self.assertEqual(
            summary["pre_pulse_state_provenance"],
            "pre_pulse_restart_initial_global_state",
        )

    def test_prepulse_restart_rejects_unbound_initial_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "log.txt"
            initial = root / "initial.csv"
            log.write_text("", encoding="utf-8")
            initial.write_text(
                "particle_id,instrument_time_us,mass_amu,charge_state,"
                "position_x_mm,position_y_mm,position_z_mm,velocity_x_m_s,"
                "velocity_y_m_s,velocity_z_m_s,kinetic_energy_eV\n"
                "1,45.5,100,1,-69,0,-66,4392.842636759329,0,0,10\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "manifest-bound"):
                analyze(
                    log,
                    1,
                    100.0,
                    pulse_time_us=45.5,
                    initial_global_state_path=initial,
                    source_release_mode="pre_pulse_restart",
                )

    def test_prepulse_restart_validates_actual_source_release_against_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "log.txt"
            initial = root / "initial.csv"
            log.write_text(
                "TRACE: source_release ion=1 instrument_time_us=45.5 "
                "x_mm=-69 y_mm=0 z_mm=-66 vx_mm_per_us=4.392842636759329 "
                "vy_mm_per_us=0 vz_mm_per_us=0\n",
                encoding="utf-8",
            )
            initial.write_text(
                "particle_id,instrument_time_us,mass_amu,charge_state,"
                "position_x_mm,position_y_mm,position_z_mm,velocity_x_m_s,"
                "velocity_y_m_s,velocity_z_m_s,kinetic_energy_eV\n"
                "1,45.5,100,1,-69,0,-66,4392.842636759329,0,0,10\n",
                encoding="utf-8",
            )
            digest = hashlib.sha256(initial.read_bytes()).hexdigest()
            _, summary = analyze(
                log,
                1,
                100.0,
                pulse_time_us=45.5,
                initial_global_state_path=initial,
                source_release_mode="pre_pulse_restart",
                initial_global_state_sha256=digest,
                restart_position_tolerance_mm=1e-9,
                restart_velocity_tolerance_m_per_s=1e-9,
                restart_clock_tolerance_us=1e-9,
                restart_energy_tolerance_eV=5e-9,
                restart_validation_contract_sha256="A" * 64,
            )
        validation = summary["pre_pulse_restart_source_release_validation"]
        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["validation_contract_sha256"], "A" * 64)
        self.assertLessEqual(validation["maximum_velocity_rowwise_abs_error_m_per_s"], 1e-9)

    def test_prepulse_restart_uses_one_verified_logged_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "log.txt"
            initial = root / "initial.csv"
            log.write_text(
                "TRACE: source_release ion=1 instrument_time_us=45.5 "
                "x_mm=-69 y_mm=0 z_mm=-66 vx_mm_per_us=4.392842636759329 "
                "vy_mm_per_us=0 vz_mm_per_us=0\n"
                "TRACE: pre_pulse_state ion=1 instrument_time_us=45.5 "
                "x_mm=-69 y_mm=0 z_mm=-66 vx_mm_per_us=4.39284263676 "
                "vy_mm_per_us=0 vz_mm_per_us=0\n",
                encoding="utf-8",
            )
            initial.write_text(
                "particle_id,instrument_time_us,mass_amu,charge_state,"
                "position_x_mm,position_y_mm,position_z_mm,velocity_x_m_s,"
                "velocity_y_m_s,velocity_z_m_s,kinetic_energy_eV\n"
                "1,45.5,100,1,-69,0,-66,4392.842636759329,0,0,10\n",
                encoding="utf-8",
            )
            digest = hashlib.sha256(initial.read_bytes()).hexdigest()
            rows, summary = analyze(
                log,
                1,
                100.0,
                pulse_time_us=45.5,
                initial_global_state_path=initial,
                source_release_mode="pre_pulse_restart",
                initial_global_state_sha256=digest,
                restart_position_tolerance_mm=1e-9,
                restart_velocity_tolerance_m_per_s=1e-9,
                restart_clock_tolerance_us=1e-9,
                restart_energy_tolerance_eV=5e-9,
                restart_validation_contract_sha256="A" * 64,
            )
        checkpoints = [row for row in rows if row["event"] == "pre_pulse_state"]
        self.assertEqual(len(checkpoints), 1)
        self.assertEqual(
            checkpoints[0]["checkpoint_provenance"],
            "pre_pulse_restart_logged_canonical_state",
        )
        self.assertEqual(
            summary["pre_pulse_state_provenance"],
            "pre_pulse_restart_logged_canonical_state",
        )

    def test_prepulse_restart_rejects_inconsistent_logged_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "log.txt"
            initial = root / "initial.csv"
            log.write_text(
                "TRACE: source_release ion=1 instrument_time_us=45.5 "
                "x_mm=-69 y_mm=0 z_mm=-66 vx_mm_per_us=4.392842636759329 "
                "vy_mm_per_us=0 vz_mm_per_us=0\n"
                "TRACE: pre_pulse_state ion=1 instrument_time_us=45.5 "
                "x_mm=-69 y_mm=0 z_mm=-66 vx_mm_per_us=4.5 "
                "vy_mm_per_us=0 vz_mm_per_us=0\n",
                encoding="utf-8",
            )
            initial.write_text(
                "particle_id,instrument_time_us,mass_amu,charge_state,"
                "position_x_mm,position_y_mm,position_z_mm,velocity_x_m_s,"
                "velocity_y_m_s,velocity_z_m_s,kinetic_energy_eV\n"
                "1,45.5,100,1,-69,0,-66,4392.842636759329,0,0,10\n",
                encoding="utf-8",
            )
            digest = hashlib.sha256(initial.read_bytes()).hexdigest()
            with self.assertRaisesRegex(
                ValueError, "logged pre-pulse restart checkpoint differs"
            ):
                analyze(
                    log,
                    1,
                    100.0,
                    pulse_time_us=45.5,
                    initial_global_state_path=initial,
                    source_release_mode="pre_pulse_restart",
                    initial_global_state_sha256=digest,
                    restart_position_tolerance_mm=1e-9,
                    restart_velocity_tolerance_m_per_s=1e-9,
                    restart_clock_tolerance_us=1e-9,
                    restart_energy_tolerance_eV=5e-9,
                    restart_validation_contract_sha256="A" * 64,
                )

    def test_prepulse_restart_rejects_duplicate_logged_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "log.txt"
            initial = root / "initial.csv"
            state = (
                "TRACE: pre_pulse_state ion=1 instrument_time_us=45.5 "
                "x_mm=-69 y_mm=0 z_mm=-66 vx_mm_per_us=4.392842636759329 "
                "vy_mm_per_us=0 vz_mm_per_us=0\n"
            )
            log.write_text(state + state, encoding="utf-8")
            initial.write_text(
                "particle_id,instrument_time_us,mass_amu,charge_state,"
                "position_x_mm,position_y_mm,position_z_mm,velocity_x_m_s,"
                "velocity_y_m_s,velocity_z_m_s,kinetic_energy_eV\n"
                "1,45.5,100,1,-69,0,-66,4392.842636759329,0,0,10\n",
                encoding="utf-8",
            )
            digest = hashlib.sha256(initial.read_bytes()).hexdigest()
            with self.assertRaisesRegex(
                ValueError, "duplicate checkpoint: particle=1 event=pre_pulse_state"
            ):
                analyze(
                    log,
                    1,
                    100.0,
                    pulse_time_us=45.5,
                    initial_global_state_path=initial,
                    source_release_mode="pre_pulse_restart",
                    initial_global_state_sha256=digest,
                    restart_position_tolerance_mm=1e-9,
                    restart_velocity_tolerance_m_per_s=1e-9,
                    restart_clock_tolerance_us=1e-9,
                    restart_energy_tolerance_eV=5e-9,
                    restart_validation_contract_sha256="A" * 64,
                )

    def test_classifies_physical_pulse_capture_without_rejecting_losses(self) -> None:
        text = "\n".join(
            [
                "TRACE: source_release ion=1 instrument_time_us=0 x_mm=-69 y_mm=0 z_mm=-18.4 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
                "TRACE: pre_pulse_state ion=1 instrument_time_us=10 x_mm=-69 y_mm=0 z_mm=-18.4 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
                "TRACE: pre_pulse_state ion=2 instrument_time_us=10 x_mm=-69 y_mm=0 z_mm=-20.0 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
                "TRACE: pre_pulse_state ion=3 instrument_time_us=10 x_mm=-60 y_mm=0 z_mm=-18.4 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
                "TRACE: detector_crossing ion=1 t=70 x=49 y=0 z=19.83",
            ]
        )
        geometry = {
            "coordinate_convention": {"accelerator_axis_x": -69.0},
            "geometry_mm": {
                "accelerator_repeller_z": -19.9,
                "accelerator_grid1_z": -16.9,
                "accelerator_bore_half": 5.0,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "log.txt"
            model = root / "geometry.json"
            log.write_text(text, encoding="utf-8")
            model.write_text(json.dumps(geometry), encoding="utf-8")
            rows, summary = analyze(
                log,
                4,
                100.0,
                model,
                10.0,
                eligible_population_count=None,
                cohort_authority_mode="establish_observed_authority",
            )
        capture = summary["pulse_capture"]
        self.assertEqual(
            capture["counts"],
            {
                "eligible": 1,
                "upstream_of_repeller": 1,
                "downstream_of_grid1": 0,
                "outside_transverse_bore": 1,
                "missing_before_pulse": 1,
            },
        )
        self.assertEqual(capture["capture_fraction_of_launched"], 0.25)
        self.assertEqual(capture["conditional_detector_efficiency"], 1.0)
        classified = {row["particle_id"]: row["pulse_eligibility"] for row in rows if row["event"] == "pre_pulse_state"}
        self.assertEqual(classified[2], "upstream_of_repeller")
        self.assertEqual(classified[3], "outside_transverse_bore")
        observed = summary["observed_cohort_authority"]
        self.assertEqual(observed["source_release"]["ordered_particle_ids"], [1])
        self.assertEqual(observed["pre_pulse_state"]["ordered_particle_ids"], [1, 2, 3])
        self.assertEqual(observed["pulse_eligible"]["ordered_particle_ids"], [1])
        self.assertEqual(observed["outside_transverse_bore"]["ordered_particle_ids"], [3])
        for name in (
            "source_release",
            "pre_pulse_state",
            "pulse_eligible",
            "outside_transverse_bore",
        ):
            self.assertEqual(len(observed[name]["ordered_particle_id_sha256"]), 64)
            self.assertEqual(observed[name]["count"], len(observed[name]["ordered_particle_ids"]))
        self.assertEqual(summary["observed_handoff"]["ordered_particle_ids"], [])

    def test_default_source_region_reports_canonical_diagnostic_peak(self) -> None:
        lines = []
        positions = [
            (-69.0, 0.0, -18.4),
            (-69.8, 0.8, -18.8),
            (-68.2, -0.8, -18.0),
            (-67.8, 0.0, -18.4),
            (-69.0, 1.2, -18.4),
        ]
        for particle_id, (x_mm, y_mm, z_mm) in enumerate(positions, 1):
            lines.append(
                f"TRACE: source_release ion={particle_id} instrument_time_us=0 "
                f"x_mm={x_mm} y_mm={y_mm} z_mm={z_mm} "
                "vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0"
            )
            lines.append(
                f"TRACE: pre_pulse_state ion={particle_id} instrument_time_us=10 "
                f"x_mm={x_mm} y_mm={y_mm} z_mm={z_mm} "
                "vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0"
            )
            lines.append(f"TRACE: detector_crossing ion={particle_id} t={70 + particle_id * 0.01} x=49 y=0 z=19.83")
        geometry = {
            "particle_source": {
                "center_x_mm": -69.0,
                "center_y_mm": 0.0,
                "center_z_mm": -18.4,
                "size_z_mm": 1.0,
            },
            "coordinate_convention": {"accelerator_axis_x": -69.0},
            "geometry_mm": {
                "accelerator_repeller_z": -19.9,
                "accelerator_grid1_z": -16.9,
                "accelerator_bore_half": 5.0,
            },
        }
        profile = {
            "profile_id": "layout_resolved_axial_provisional_xy2_v1",
            "role": "layout_resolved_source_region_diagnostic",
            "claim_status": "PROVISIONAL_DIAGNOSTIC_ONLY",
            "event": "pre_pulse_state",
            "population_basis": "pulse_eligible",
            "axes": {
                "x": {
                    "center_binding": "particle_source.center_x_mm",
                    "full_width_mm": 2.0,
                },
                "y": {
                    "center_binding": "particle_source.center_y_mm",
                    "full_width_mm": 2.0,
                },
                "z": {
                    "center_binding": "particle_source.center_z_mm",
                    "full_width_binding": "particle_source.size_z_mm",
                },
            },
            "selection_uses_detector_outcome": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "log.txt"
            model = root / "geometry.json"
            log.write_text("\n".join(lines), encoding="utf-8")
            model.write_text(json.dumps(geometry), encoding="utf-8")
            _, summary = analyze(
                log,
                5,
                100.0,
                model,
                10.0,
                source_region_diagnostic_profile=profile,
            )
        diagnostic = summary["source_region_diagnostic"]
        self.assertIsNone(summary["spatial_window_peak"])
        self.assertIsNotNone(summary["pulse_effective_peak"])
        self.assertEqual(diagnostic["claim_status"], "PROVISIONAL_DIAGNOSTIC_ONLY")
        self.assertFalse(diagnostic["qualification_eligible"])
        self.assertEqual(diagnostic["eligible_count"], 5)
        self.assertEqual(diagnostic["selected_particle_ids"], [1, 2, 3])
        self.assertEqual(diagnostic["selected_count"], 3)
        self.assertEqual(diagnostic["detected_particle_ids"], [1, 2, 3])
        self.assertEqual(diagnostic["detected_count"], 3)
        self.assertAlmostEqual(diagnostic["occupancy_fraction"], 0.6)
        self.assertEqual(diagnostic["bounds"]["z"]["full_width_mm"], 1.0)
        self.assertEqual(
            diagnostic["bounds"]["z"]["full_width_binding"],
            "particle_source.size_z_mm",
        )
        self.assertEqual(diagnostic["peak_status"], "computed")
        self.assertIsNone(diagnostic["peak_reason"])
        self.assertEqual(diagnostic["pulse_effective_peak"]["particles"], 3)

    def test_source_region_fewer_than_three_detected_is_nonblocking(self) -> None:
        lines = []
        for particle_id, x_mm in enumerate((-69.0, -68.5, -67.0), 1):
            for event, time_us in (("source_release", 0), ("pre_pulse_state", 10)):
                lines.append(
                    f"TRACE: {event} ion={particle_id} instrument_time_us={time_us} "
                    f"x_mm={x_mm} y_mm=0 z_mm=-18.4 "
                    "vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0"
                )
            lines.append(
                f"TRACE: detector_crossing ion={particle_id} "
                f"t={70 + particle_id * 0.01} x=49 y=0 z=19.83"
            )
        geometry = {
            "particle_source": {
                "center_x_mm": -69.0,
                "center_y_mm": 0.0,
                "center_z_mm": -18.4,
                "size_z_mm": 1.0,
            },
            "coordinate_convention": {"accelerator_axis_x": -69.0},
            "geometry_mm": {
                "accelerator_repeller_z": -19.9,
                "accelerator_grid1_z": -16.9,
                "accelerator_bore_half": 5.0,
            },
        }
        profile = {
            "profile_id": "layout_resolved_axial_provisional_xy2_v1",
            "role": "layout_resolved_source_region_diagnostic",
            "claim_status": "PROVISIONAL_DIAGNOSTIC_ONLY",
            "event": "pre_pulse_state",
            "population_basis": "pulse_eligible",
            "axes": {
                "x": {
                    "center_binding": "particle_source.center_x_mm",
                    "full_width_mm": 2.0,
                },
                "y": {
                    "center_binding": "particle_source.center_y_mm",
                    "full_width_mm": 2.0,
                },
                "z": {
                    "center_binding": "particle_source.center_z_mm",
                    "full_width_binding": "particle_source.size_z_mm",
                },
            },
            "selection_uses_detector_outcome": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "log.txt"
            model = root / "geometry.json"
            log.write_text("\n".join(lines), encoding="utf-8")
            model.write_text(json.dumps(geometry), encoding="utf-8")
            _, summary = analyze(
                log,
                3,
                100.0,
                model,
                10.0,
                source_region_diagnostic_profile=profile,
            )
        diagnostic = summary["source_region_diagnostic"]
        self.assertEqual(summary["status"], "success")
        self.assertEqual(diagnostic["selected_count"], 2)
        self.assertEqual(diagnostic["detected_count"], 2)
        self.assertIsNone(diagnostic["pulse_effective_peak"])
        self.assertEqual(diagnostic["peak_status"], "not_computed")
        self.assertEqual(
            diagnostic["peak_reason"], "fewer_than_three_detected_particles"
        )

    def test_full_population_cross_checks_declared_pulse_eligible_count(self) -> None:
        lines = [
            "TRACE: source_release ion=1 instrument_time_us=0 x_mm=-69 y_mm=0 z_mm=-18 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: source_release ion=2 instrument_time_us=0 x_mm=-69 y_mm=0 z_mm=-18 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: pre_pulse_state ion=1 instrument_time_us=1 x_mm=-69 y_mm=0 z_mm=-18 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: pre_pulse_state ion=2 instrument_time_us=1 x_mm=-69 y_mm=6 z_mm=-18 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: detector_crossing ion=1 t=2 x=0 y=0 z=0",
        ]
        geometry = {
            "coordinate_convention": {"accelerator_axis_x": -69.0},
            "geometry_mm": {
                "accelerator_repeller_z": -19.9,
                "accelerator_grid1_z": -16.9,
                "accelerator_bore_half": 5.0,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "log.txt"
            model = root / "geometry.json"
            log.write_text("\n".join(lines), encoding="utf-8")
            model.write_text(json.dumps(geometry), encoding="utf-8")
            _, summary = analyze(
                log,
                2,
                100.0,
                model,
                10.0,
                eligible_population_count=1,
            )

        population = summary["source_population"]
        self.assertEqual(population["simulation_population_basis"], "candidate_full_population")
        self.assertEqual(population["simulated_population_count"], 2)
        self.assertEqual(population["pulse_eligible_population_count"], 1)
        self.assertEqual(population["raw_pulse_capture_fraction"], 0.5)
        self.assertEqual(population["simulated_fraction_of_candidate_population"], 1.0)
        self.assertIsNone(population["simulated_fraction_of_pulse_eligible_population"])

    def test_five_dimensional_window_uses_forward_velocity_angles(self) -> None:
        lines = []
        for particle_id, (vx, vy, vz) in enumerate([(0.1, 0.1, 10), (-0.1, 0, 10), (0, -0.1, 10), (0, 0, -10)], 1):
            lines.append(
                f"TRACE: source_release ion={particle_id} instrument_time_us=0 "
                f"x_mm=-69 y_mm=0 z_mm=-18.4 vx_mm_per_us={vx} "
                f"vy_mm_per_us={vy} vz_mm_per_us={vz}"
            )
            lines.append(
                f"TRACE: pre_pulse_state ion={particle_id} instrument_time_us=10 "
                f"x_mm=-69 y_mm=0 z_mm=-18.4 vx_mm_per_us={vx} "
                f"vy_mm_per_us={vy} vz_mm_per_us={vz}"
            )
            if particle_id < 4:
                lines.append(f"TRACE: detector_crossing ion={particle_id} t={70 + particle_id * 0.01} x=0 y=0 z=0")
        geometry = {
            "particle_source": {
                "center_x_mm": -69.0,
                "center_y_mm": 0.0,
                "center_z_mm": -18.4,
            },
            "coordinate_convention": {"accelerator_axis_x": -69.0},
            "geometry_mm": {
                "accelerator_repeller_z": -19.9,
                "accelerator_grid1_z": -16.9,
                "accelerator_bore_half": 20.0,
            },
        }
        profile = {
            "profile_id": "theoretical_5d_window",
            "event": "pre_pulse_state",
            "axes": {
                axis: {
                    "center_binding": f"particle_source.center_{axis}_mm",
                    "full_width_mm": 1.0,
                }
                for axis in ("x", "y", "z")
            }
            | {
                axis: {
                    "center_binding": "theory_source_center_angle_deg",
                    "center_deg": 0.0,
                    "full_width_deg": 4.0,
                }
                for axis in ("angle_x", "angle_y")
            },
            "selection_uses_detector_outcome": False,
            "field_error_budget": {
                "derivation": "synthetic_grid_field_error_budget",
                "tof_error_budget_ns": 0.537,
                "frozen_before_particle_outcomes": True,
            },
            "minimum_pulse_eligible_coverage": 0.70,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "log.txt"
            model = root / "geometry.json"
            log.write_text("\n".join(lines), encoding="utf-8")
            model.write_text(json.dumps(geometry), encoding="utf-8")
            _, summary = analyze(log, 4, 100.0, model, 10.0, spatial_window_profile=profile)
        window = summary["spatial_window_peak"]
        self.assertEqual(window["selected_count"], 3)
        self.assertEqual(window["pulse_eligible_coverage_fraction"], 0.75)
        self.assertIn("angle_x", window["bounds"])
        self.assertFalse(window["selection_uses_detector_outcome"])

    def test_pulse_effective_peak_and_reflectron_common_cohort(self) -> None:
        lines = ["TRACE: handoff_pulse_on ion=1 instrument_time_us=10"]
        for particle_id in range(1, 5):
            lines.append(
                f"TRACE: source_release ion={particle_id} instrument_time_us=0 "
                "x_mm=0 y_mm=0 z_mm=0 vx_mm_per_us=1 "
                "vy_mm_per_us=0 vz_mm_per_us=1"
            )
            times = [20, 30, 40, 50, 60]
            events = [
                "accelerator_focus_forward",
                "reflectron_entrance_forward",
                "reflectron_midgrid_forward",
                "reflectron_turning_point",
                "reflectron_exit_return",
            ]
            for index, (event, time_us) in enumerate(zip(events, times, strict=True)):
                z_mm = [0, 600, 720, 800, 600][index]
                vz = 0 if event == "reflectron_turning_point" else (10 if index < 3 else -10)
                lines.append(
                    f"TRACE: {event} ion={particle_id} particle_id={particle_id} "
                    f"instrument_time_us={time_us + particle_id * 0.001} "
                    f"tof_since_pulse_us={time_us - 10 + particle_id * 0.001} "
                    f"x_mm={particle_id} y_mm=0 z_mm={z_mm} "
                    f"vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us={vz} "
                    f"kinetic_energy_eV={kinetic_energy_ev(100, 1000, 0, 1000 * vz):.12g} "
                    "survival_status=alive"
                )
            lines.append(f"TRACE: detector_crossing ion={particle_id} t={70 + particle_id * 0.001} x=0 y=0 z=0")
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.txt"
            log.write_text("\n".join(lines), encoding="utf-8")
            _, summary = analyze(log, 4, 100.0, pulse_time_us=10.0)
        self.assertEqual(
            summary["resolution_time_basis"],
            "detector_time_minus_pulse_effective_time",
        )
        self.assertIsNotNone(summary["pulse_effective_peak"])
        self.assertNotIn("instrument_clock_peak", summary)
        self.assertNotIn("instrument_clock_peak_is_resolution_claim", summary)
        common = summary["post_focus_common_cohort"]
        self.assertEqual(common["reflectron_common_cohort_count"], 4)
        self.assertEqual(common["detector_paired_cohort_count"], 4)
        self.assertEqual(len(common["segments"]), 5)
        first_segment = common["segments"][0]
        self.assertEqual(
            first_segment["linear_regression_degrees_of_freedom"],
            4 - first_segment["linear_regression_rank"],
        )
        self.assertIsNone(first_segment["linear_regression_residual_sigma_ns"])
        self.assertEqual(
            first_segment["linear_regression_status"],
            "insufficient_rank_or_residual_degrees_of_freedom",
        )

    def test_rejects_reflectron_checkpoint_out_of_order(self) -> None:
        text = "\n".join(
            [
                "TRACE: reflectron_entrance_forward ion=1 particle_id=1 instrument_time_us=20 tof_since_pulse_us=10 x_mm=0 y_mm=0 z_mm=600 vx_mm_per_us=0 vy_mm_per_us=0 vz_mm_per_us=1",
                "TRACE: reflectron_turning_point ion=1 particle_id=1 instrument_time_us=30 tof_since_pulse_us=20 x_mm=0 y_mm=0 z_mm=700 vx_mm_per_us=0 vy_mm_per_us=0 vz_mm_per_us=0",
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.txt"
            log.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sequence is not a prefix"):
                analyze(log, 1, 100.0, pulse_time_us=10.0)

    def test_rejects_logged_energy_that_disagrees_with_velocity(self) -> None:
        text = (
            "TRACE: reflectron_entrance_forward ion=1 particle_id=1 "
            "instrument_time_us=20 tof_since_pulse_us=10 "
            "x_mm=0 y_mm=0 z_mm=600 vx_mm_per_us=1 vy_mm_per_us=0 "
            "vz_mm_per_us=1 kinetic_energy_eV=999 survival_status=alive"
        )
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.txt"
            log.write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "kinetic energy differs"):
                analyze(log, 1, 100.0, pulse_time_us=10.0)


if __name__ == "__main__":
    unittest.main()
