from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.resolution_attribution_counterfactual import (
    _checkpoint_detector_times,
    _checkpoint_time_transfer,
    _canonical_replay_detector_time,
    _ideal_source,
    _phase_space_time_transfer,
    _pulse_relative_peak,
    _remove_linear_covariance,
    _collapse_linear_residual,
    _project_observed_linear_slope,
    _quantile_match_centered,
    _state_summary,
    _validate_profile,
    _write_phase_space_diagnostic,
    prepare,
)


PROFILE = Path(__file__).parents[1] / "config" / "resolution_attribution_counterfactual.json"
MATCH_PROFILE = Path(__file__).parents[1] / "config" / "accelerator_phase_space_match.json"
WORKFLOW = Path(__file__).parents[1] / "workflows" / "resolution_attribution" / "execute.ps1"


class ResolutionAttributionCounterfactualTests(unittest.TestCase):
    def test_resolution_peak_uses_detector_minus_effective_pulse_time(self) -> None:
        detector = np.asarray([75.0, 75.001, 75.002, 75.003])
        peak = _pulse_relative_peak(detector, 45.0, 100.0)
        self.assertIsNotNone(peak)
        self.assertAlmostEqual(peak["mean_tof_us"], 30.0015)
        self.assertLess(peak["mass_resolution"], 100000.0)

    def test_checkpoint_time_transfer_reports_focus_spread_and_slope(self) -> None:
        states = [
            {"simulation_particle_id": str(index), "z_mm": str(z)}
            for index, z in enumerate((-1.0, 0.0, 1.0), start=1)
        ]
        checkpoints = [
            {
                "particle_id": index,
                "event": "accelerator_focus_forward",
                "instrument_time_us": 40.0 + (2.0 * z) / 1000.0,
            }
            for index, z in enumerate((-1.0, 0.0, 1.0), start=1)
        ]
        result = _checkpoint_time_transfer(
            states, checkpoints, "accelerator_focus_forward"
        )
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["source_z_time_slope_ns_per_mm"], 2.0)
        self.assertAlmostEqual(result["time_sigma_ns"], np.std([-2.0, 0.0, 2.0]))

    def test_execution_governs_ideal_accelerator_field_mode(self) -> None:
        execution = (
            Path(__file__).resolve().parents[1]
            / "workflows/resolution_attribution/execute.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("single_flight_ideal_accel_enable", execution)
        self.assertIn("'ideal_stage1','ideal_stage2','ideal_piecewise'", execution)
        self.assertIn("$effectiveIdealAcceleratorEnabled", execution)
        self.assertIn("elseif ($AcceleratorFieldMode -eq 'ideal_piecewise')", execution)
        self.assertIn(
            '"sf_ideal_accel_enable=$effectiveIdealAcceleratorEnabled"', execution
        )

    def test_phase_space_time_transfer_reports_actual_correlated_slope(self) -> None:
        rows = []
        detector = {}
        for particle_id, (z, residual) in enumerate(
            zip((-1.0, -0.5, 0.5, 1.0), (1.0, -1.0, -1.0, 1.0)),
            start=1,
        ):
            vz = 10.0 + 2.0 * z + residual
            rows.append({
                "source_particle_id": str(particle_id),
                "z_mm": str(z),
                "vz_m_s": str(vz),
            })
            detector[particle_id] = (100.0 + 3.0 * z + 0.5 * vz) / 1000.0
        result = _phase_space_time_transfer(rows, detector)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(
            result["actual_linear_z_vz_time_slope_ns_per_mm"], 4.0
        )

    def test_phase_space_diagnostic_publishes_traceable_figure(self) -> None:
        rows = [
            {"z_mm": str(z), "vz_m_s": str(5.0 + 100.0 * z + residual)}
            for z, residual in ((-0.2, -2.0), (-0.1, 1.0), (0.1, -1.0), (0.2, 2.0))
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = root / "prepared_arms.json"
            prepared.write_text("{}\n", encoding="utf-8")
            metadata = _write_phase_space_diagnostic(
                rows, root, prepared, "source_event_and_pulse_eligibility"
            )
            self.assertEqual(metadata["particle_count"], 4)
            self.assertTrue((root / metadata["figure"]).is_file())
            self.assertTrue((root / metadata["metadata"]).is_file())
            self.assertEqual(len(metadata["figure_sha256"]), 64)

    def test_checkpoint_detector_time_is_not_offset_by_release_time_twice(self) -> None:
        rows = [
            {"particle_id": "1", "event": "source_release", "instrument_time_us": "0.4"},
            {"particle_id": "1", "event": "detector_crossing", "instrument_time_us": "76.7"},
        ]
        self.assertEqual(_checkpoint_detector_times(rows), {1: 76.7})

    def test_replay_detector_time_restores_instrument_epoch_once(self) -> None:
        self.assertAlmostEqual(
            _canonical_replay_detector_time(31.1705, 31.8137, 0.0),
            62.9842,
        )
        self.assertEqual(
            _canonical_replay_detector_time(62.9842, 31.8137, None),
            62.9842,
        )

    def test_n1000_workflow_uses_governed_process_parallel_batches(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8-sig")
        self.assertIn("Start-Job", workflow)
        self.assertNotIn("Start-ThreadJob", workflow)

    def test_workflow_accepts_frozen_n100_screening_baseline(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8-sig")
        self.assertIn("-notin @(100,200,1000)", workflow)
        self.assertIn("N=100/N=200 screening", workflow)

    def test_workflow_can_pair_a_frozen_source_with_a_selected_frontend(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8-sig")
        self.assertIn("$FrontendRunId", workflow)
        self.assertIn("Frontend source run changes frozen physical input", workflow)
        self.assertIn("PSObject.Properties.Remove('sources')", workflow)
        self.assertIn("$prepareArguments += @('--arm-id',$selectedArmId)", workflow)
        self.assertIn("Reference arm was not prepared", workflow)
        self.assertIn("$currentArmId = [string]$arm.arm_id", workflow)
        self.assertNotIn("$armId = [string]$arm.arm_id", workflow)

    def test_workflow_reuses_the_frozen_five_instance_overlay_runtime(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8-sig")
        self.assertIn("$frontendOverlayEnabled", workflow)
        self.assertIn("simion\\oatof_ideal_grounded.iob", workflow)
        self.assertIn("Accelerator-overlay replay Program build failed.", workflow)
        self.assertIn("accelerator_overlay_pa0_sha256", workflow)
        self.assertIn("cache_manifest.json", workflow)
        self.assertIn("cacheManifest.identity.inputs", workflow)
        self.assertIn("cacheInputs.frontend_pa0_sha256", workflow)
        self.assertIn("cacheInputs.overlay_gem_sha256", workflow)
        self.assertIn("-BaseName 'accelerator_overlay'", workflow)
        self.assertIn("'--initial-global-state',$replayClockState", workflow)
        self.assertIn("'--clock-basis','absolute_birth_time'", workflow)
        self.assertIn(
            "Accelerator-overlay attribution supports only combined_frontend arms.",
            workflow,
        )

    def test_formal_published_particle_schema_is_an_ideal_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "formal_particles.csv"
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow(
                    ["Ion", "X0Mm", "Y0Mm", "Z0Mm", "EnergyEv", "Hit"]
                )
                writer.writerows(
                    [[1, -1, 2, 3, 4.1, True], [2, 0, 3, 4, 4.2, True], [3, 1, 4, 5, 4.3, True]]
                )
            ideal = _ideal_source(source)
            np.testing.assert_array_equal(ideal["particle_id"], [1, 2, 3])
            np.testing.assert_allclose(ideal["x"], [-1, 0, 1])
            np.testing.assert_allclose(ideal["energy"], [4.1, 4.2, 4.3])

    def test_centered_quantile_match_preserves_current_geometry_center(self) -> None:
        values = np.asarray([-70.0, -69.0, -68.0])
        reference = np.asarray([-49.3, -48.8, -48.3])
        matched = _quantile_match_centered(values, reference)
        self.assertAlmostEqual(float(np.mean(matched)), -69.0, places=12)
        self.assertAlmostEqual(float(np.ptp(matched)), 2.0 / 3.0, places=12)

    def test_remove_covariance_preserves_velocity_mean_and_sample_sigma(self) -> None:
        z = np.asarray([-2.0, -1.0, 0.0, 1.0, 2.0])
        vz = np.asarray([-4.0, -0.5, 1.0, 2.5, 6.0])
        adjusted = _remove_linear_covariance(z, vz)
        self.assertAlmostEqual(float(np.mean(adjusted)), float(np.mean(vz)), places=12)
        self.assertAlmostEqual(float(np.std(adjusted, ddof=1)), float(np.std(vz, ddof=1)), places=12)
        self.assertAlmostEqual(float(np.cov(z, adjusted, ddof=1)[0, 1]), 0.0, places=12)

    def test_collapse_residual_preserves_observed_linear_relation(self) -> None:
        z = np.asarray([-2.0, -1.0, 0.0, 1.0, 2.0])
        vz = np.asarray([-4.0, -0.5, 1.0, 2.5, 6.0])
        adjusted = _collapse_linear_residual(z, vz)
        self.assertAlmostEqual(float(np.mean(adjusted)), float(np.mean(vz)), places=12)
        self.assertAlmostEqual(float(np.corrcoef(z, adjusted)[0, 1]), 1.0, places=12)

    def test_project_observed_slope_scales_velocity_with_target_width(self) -> None:
        observed_z = np.asarray([-2.0, -1.0, 0.0, 1.0, 2.0])
        observed_vz = np.asarray([-4.0, -0.5, 1.0, 2.5, 6.0])
        target_z = observed_z / 2.0
        adjusted = _project_observed_linear_slope(
            observed_z, observed_vz, target_z
        )
        observed_slope = np.cov(observed_z, observed_vz, ddof=1)[0, 1] / np.var(
            observed_z, ddof=1
        )
        target_slope = np.cov(target_z, adjusted, ddof=1)[0, 1] / np.var(
            target_z, ddof=1
        )
        self.assertAlmostEqual(float(target_slope), float(observed_slope), places=12)
        self.assertAlmostEqual(
            float(np.mean(adjusted)), float(np.mean(observed_vz)), places=12
        )

    def test_prepare_uses_fixed_common_particle_identity_for_every_arm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoints = root / "checkpoints.csv"
            ideal = root / "ideal.csv"
            with checkpoints.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow(
                    [
                        "particle_id",
                        "event",
                        "instrument_time_us",
                        "x_mm",
                        "y_mm",
                        "z_mm",
                        "vx_mm_per_us",
                        "vy_mm_per_us",
                        "vz_mm_per_us",
                    ]
                )
                for particle_id in range(1, 5):
                    vz = [0.01, 0.04, 0.02, 0.08][particle_id - 1]
                    writer.writerow(
                        [particle_id, "pre_pulse_state", 10, particle_id, particle_id / 2, particle_id / 3, 2, 0.1, vz]
                    )
                    writer.writerow([particle_id, "detector_crossing", 20 + particle_id / 1000, 0, 0, 0, "", "", ""])
            with ideal.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow([
                    "particle_id", "initial_x_mm", "initial_y_mm",
                    "initial_z_mm", "initial_energy_eV"
                ])
                for particle_id, value in enumerate((-0.5, -0.1, 0.1, 0.5), 1):
                    writer.writerow([particle_id, value, value / 2, value / 3, 4 + particle_id / 10])
            formal_geometry = root / "formal_geometry.json"
            formal_geometry.write_text(json.dumps({"particle_source": {
                "center_x_mm": 0.0, "center_y_mm": 0.0, "center_z_mm": 0.0,
                "size_x_mm": 1.0, "size_y_mm": 1.0, "size_z_mm": 1.0
            }}), encoding="utf-8")
            target_geometry = root / "target_geometry.json"
            target_geometry.write_text(json.dumps({"particle_source": {
                "center_x_mm": 10.0, "center_y_mm": 20.0, "center_z_mm": 30.0,
                "size_x_mm": 2.0, "size_y_mm": 3.0, "size_z_mm": 4.0
            }}), encoding="utf-8")
            available_arm_ids = [
                arm["arm_id"]
                for arm in json.loads(PROFILE.read_text(encoding="utf-8"))["arms"]
                if arm["arm_id"] not in {
                    "current_layout_ideal_1mm_linear_z_vz",
                    "current_layout_ideal_finite_interval_linear_z_vz",
                    "current_layout_ideal_finite_interval_axis_linear_z_vz",
                    "current_layout_ideal_axis_2p2mm_linear_z_vz",
                }
            ]
            result = prepare(
                PROFILE, checkpoints, ideal, formal_geometry, target_geometry,
                root / "prepared", 100.0, 1,
                1.1e6, 4,
                selected_arm_ids=available_arm_ids,
                initial_pa_instance=5,
                solver_birth_time_us=0.0,
            )
            self.assertEqual(result["paired_cohort_particles"], 4)
            self.assertEqual(result["initial_pa_instance"], 5)
            self.assertEqual(result["solver_birth_time_us"], 0.0)
            self.assertEqual(len(result["arms"]), 21)
            for arm in result["arms"]:
                state = root / "prepared" / arm["state_file"]
                with state.open(encoding="utf-8", newline="") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual([int(row["source_particle_id"]) for row in rows], [1, 2, 3, 4])
                self.assertEqual({row["arm_id"] for row in rows}, {arm["arm_id"]})
                self.assertEqual(len(arm["execution_batches"]), 4)
                self.assertEqual(
                    sum(batch["particles"] for batch in arm["execution_batches"]), 4
                )
                first_ion = root / "prepared" / arm["execution_batches"][0]["ion_file"]
                with first_ion.open(encoding="utf-8", newline="") as handle:
                    first_ion_row = next(csv.reader(handle))
                    self.assertEqual(first_ion_row[0], "0")
                    self.assertEqual(first_ion_row[-1], "5")
            manifest = json.loads((root / "prepared" / "prepared_arms.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["profile_id"], "pre_pulse_phase_space_attribution_v4")
            formal_state = root / "prepared" / "formal_ideal_source__source_state.csv"
            with formal_state.open(encoding="utf-8", newline="") as handle:
                formal_rows = list(csv.DictReader(handle))
            self.assertEqual(
                [float(row["x_mm"]) for row in formal_rows],
                [9.5, 9.9, 10.1, 10.5],
            )
            self.assertEqual(
                [float(row["y_mm"]) for row in formal_rows],
                [19.75, 19.95, 20.05, 20.25],
            )
            np.testing.assert_allclose(
                [float(row["kinetic_energy_eV"]) for row in formal_rows],
                [4.1, 4.2, 4.3, 4.4],
                rtol=0.0,
                atol=1e-12,
            )
            self.assertTrue(all(float(row["vx_m_s"]) > 0 for row in formal_rows))
            self.assertTrue(all(float(row["vy_m_s"]) == 0 for row in formal_rows))
            self.assertTrue(all(float(row["vz_m_s"]) == 0 for row in formal_rows))
            layout_state = root / "prepared" / "current_layout_ideal_source__source_state.csv"
            with layout_state.open(encoding="utf-8", newline="") as handle:
                layout_rows = list(csv.DictReader(handle))
            self.assertEqual(
                [float(row["x_mm"]) for row in layout_rows],
                [9.0, 9.8, 10.2, 11.0],
            )
            self.assertEqual(
                [float(row["z_mm"]) for row in layout_rows],
                [29.333333333333332, 29.866666666666667,
                 30.133333333333333, 30.666666666666668],
            )
            self.assertTrue(all(float(row["vy_m_s"]) == 0 for row in layout_rows))
            self.assertTrue(all(float(row["vz_m_s"]) == 0 for row in layout_rows))
            prepared_arm = next(
                arm for arm in result["arms"]
                if arm["arm_id"] == "formal_focus_mapped_layout_source"
            )
            self.assertEqual(prepared_arm["solver_profile_id"], "formal_reflectron")
            exact_arm = next(
                arm for arm in result["arms"]
                if arm["arm_id"] == "exact_formal_field_mapped_layout_source"
            )
            self.assertEqual(exact_arm["frontend_profile_id"], "formal_accelerator")

    def test_prepare_can_select_a_small_ordered_arm_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoints = root / "checkpoints.csv"
            ideal = root / "ideal.csv"
            with checkpoints.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow([
                    "particle_id", "event", "instrument_time_us", "x_mm", "y_mm",
                    "z_mm", "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us",
                ])
                for particle_id in range(1, 4):
                    writer.writerow([
                        particle_id, "pre_pulse_state", 10, particle_id, 0, 0,
                        2, 0, 0,
                    ])
                    writer.writerow([
                        particle_id, "detector_crossing", 20, 0, 0, 0, "", "", "",
                    ])
            with ideal.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow([
                    "particle_id", "initial_x_mm", "initial_y_mm",
                    "initial_z_mm", "initial_energy_eV",
                ])
                for particle_id in range(1, 4):
                    writer.writerow([particle_id, 0, 0, 0, 5])
            geometry = {
                "particle_source": {
                    "center_x_mm": 0.0, "center_y_mm": 0.0, "center_z_mm": 0.0,
                    "size_x_mm": 1.0, "size_y_mm": 1.0, "size_z_mm": 1.0,
                }
            }
            formal_geometry = root / "formal_geometry.json"
            target_geometry = root / "target_geometry.json"
            formal_geometry.write_text(json.dumps(geometry), encoding="utf-8")
            target_geometry.write_text(json.dumps(geometry), encoding="utf-8")
            arm_ids = [
                "formal_focus_mapped_layout_source",
                "exact_formal_field_mapped_layout_source",
            ]
            result = prepare(
                PROFILE, checkpoints, ideal, formal_geometry, target_geometry,
                root / "prepared", 100.0, 1, 1.1e6, 3,
                selected_arm_ids=arm_ids,
            )
            self.assertEqual([arm["arm_id"] for arm in result["arms"]], arm_ids)
            with self.assertRaisesRegex(ValueError, "unique"):
                prepare(
                    PROFILE, checkpoints, ideal, formal_geometry, target_geometry,
                    root / "duplicate", 100.0, 1, 1.1e6, 3,
                    selected_arm_ids=[arm_ids[0], arm_ids[0]],
                )
            with self.assertRaisesRegex(ValueError, "unknown"):
                prepare(
                    PROFILE, checkpoints, ideal, formal_geometry, target_geometry,
                    root / "unknown", 100.0, 1, 1.1e6, 3,
                    selected_arm_ids=["not_an_arm"],
                )

    def test_phase_space_match_uses_all_pulse_eligible_particles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoints = root / "checkpoints.csv"
            ideal = root / "ideal.csv"
            with checkpoints.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow([
                    "particle_id", "event", "instrument_time_us", "x_mm", "y_mm",
                    "z_mm", "vx_mm_per_us", "vy_mm_per_us", "vz_mm_per_us",
                    "pulse_eligibility",
                ])
                for particle_id in range(1, 6):
                    z = -18.8 + 0.2 * particle_id
                    vz = 0.02 * particle_id
                    eligibility = "eligible" if particle_id <= 4 else "ineligible"
                    writer.writerow([
                        particle_id, "pre_pulse_state", 10, -69, 0, z,
                        2, 0, vz, eligibility,
                    ])
                    if particle_id <= 2:
                        writer.writerow([
                            particle_id, "detector_crossing", 20, 0, 0, 0,
                            "", "", "", "",
                        ])
            with ideal.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow([
                    "particle_id", "initial_x_mm", "initial_y_mm",
                    "initial_z_mm", "initial_energy_eV",
                ])
                for particle_id in range(1, 6):
                    writer.writerow([particle_id, 0, 0, 0, 5])
            source = {
                "particle_source": {
                    "center_x_mm": 0.0, "center_y_mm": 0.0,
                    "center_z_mm": -18.42918680341103,
                    "size_x_mm": 1.0, "size_y_mm": 1.0, "size_z_mm": 2.2,
                }
            }
            formal_geometry = root / "formal_geometry.json"
            formal_geometry.write_text(json.dumps(source), encoding="utf-8")
            target_geometry = root / "target_geometry.json"
            target_geometry.write_text(json.dumps({
                **source,
                "geometry_derivation": {
                    "accelerator": {
                        "d1_mm": 3.0,
                        "d2_mm": 16.8,
                        "canonical_repeller_z_mm": -19.92918680341103,
                        "focus_drift_after_grid2_mm": 0.12918680341103,
                        "finite_interval_theory": {
                            "mean_initial_velocity_m_per_s": 0.0,
                            "velocity_slope_m_per_s_per_mm": 10.0,
                        },
                    },
                    "reflectron": {"nominal_energy_per_charge_V": 2000.0},
                },
                "geometry_mm": {
                    "L_flight": 600.0,
                    "L_stage1": 120.0,
                    "L_stage2": 96.1563,
                },
                "electrodes_V": {
                    "grid2": 0.0,
                    "midgrid": 1628.8001,
                    "backplate": 2531.1999,
                },
            }), encoding="utf-8")
            result = prepare(
                PROFILE, checkpoints, ideal, formal_geometry, target_geometry,
                root / "prepared", 100.0, 1, 1.1e6, 4,
                selected_arm_ids=["observed_restart_control"],
                accelerator_match_profile_path=MATCH_PROFILE,
            )
            self.assertEqual(result["cohort_policy"], "source_event_and_pulse_eligibility")
            self.assertEqual(result["paired_cohort_particles"], 4)
            self.assertEqual(len(result["arms"]), 1)
            acceptance = result["accelerator_match"]["source_acceptance"]
            self.assertTrue(acceptance["physical_gap"]["all_particles_inside"])
            self.assertFalse(acceptance["geometry_change_required"])
            state = root / "prepared" / "observed_restart_control__source_state.csv"
            with state.open(encoding="utf-8", newline="") as handle:
                source_ids = [int(row["source_particle_id"]) for row in csv.DictReader(handle)]
            self.assertEqual(source_ids, [1, 2, 3, 4])
            release = result["accelerator_match"]["release_position_mm"]
            selected_probe = prepare(
                PROFILE, checkpoints, ideal, formal_geometry, target_geometry,
                root / "prepared_probe", 100.0, 1, 1.1e6, 4,
                selected_arm_ids=["accelerator_phase_match_m010"],
                accelerator_match_profile_path=MATCH_PROFILE,
            )
            self.assertEqual(len(selected_probe["arms"]), 1)
            self.assertEqual(
                selected_probe["arms"][0]["arm_id"],
                "accelerator_phase_match_m010",
            )
            for arm in selected_probe["arms"]:
                voltage = arm["accelerator_voltage_override"]
                nominal = voltage["repeller_V"] - (
                    voltage["gap1_voltage_drop_V"] * release / 3.0
                )
                self.assertAlmostEqual(nominal, 2000.0, places=10)
            ring_result = prepare(
                PROFILE, checkpoints, ideal, formal_geometry, target_geometry,
                root / "prepared_ring", 100.0, 1, 1.1e6, 4,
                selected_arm_ids=["observed_restart_control"],
                accelerator_match_profile_path=MATCH_PROFILE,
                accelerator_match_stage="ring_shape",
            )
            self.assertEqual(ring_result["accelerator_match_stage"], "ring_shape")
            self.assertEqual(len(ring_result["arms"]), 1)
            coupled_result = prepare(
                PROFILE, checkpoints, ideal, formal_geometry, target_geometry,
                root / "prepared_coupled", 100.0, 1, 1.1e6, 4,
                selected_arm_ids=["observed_restart_control"],
                accelerator_match_profile_path=MATCH_PROFILE,
                accelerator_match_stage="coupled_reflectron",
            )
            self.assertEqual(coupled_result["accelerator_match_stage"], "coupled_reflectron")
            self.assertEqual(len(coupled_result["arms"]), 1)
            slope_result = prepare(
                PROFILE, checkpoints, ideal, formal_geometry, target_geometry,
                root / "prepared_slope", 100.0, 1, 1.1e6, 4,
                selected_arm_ids=["observed_restart_control"],
                accelerator_match_profile_path=MATCH_PROFILE,
                accelerator_match_stage="actual_slope",
            )
            self.assertEqual(slope_result["accelerator_match_stage"], "actual_slope")
            self.assertEqual(len(slope_result["arms"]), 1)
            finite_result = prepare(
                PROFILE, checkpoints, ideal, formal_geometry, target_geometry,
                root / "prepared_finite", 100.0, 1, 1.1e6, 4,
                selected_arm_ids=["observed_restart_control"],
                accelerator_match_profile_path=MATCH_PROFILE,
                accelerator_match_stage="finite_interval",
            )
            self.assertEqual(finite_result["accelerator_match_stage"], "finite_interval")
            self.assertEqual(len(finite_result["arms"]), 1)
            solution = finite_result["accelerator_match"]["finite_interval_solution"]
            self.assertEqual(solution["source_full_width_mm"], 2.2)
            finite_coupled = prepare(
                PROFILE, checkpoints, ideal, formal_geometry, target_geometry,
                root / "prepared_finite_coupled", 100.0, 1, 1.1e6, 4,
                selected_arm_ids=[
                    "finite_interval_axis_fixed_focus_accelerator",
                    "finite_interval_axis_fixed_focus_accelerator_coupled_reflectron",
                ],
                accelerator_match_profile_path=MATCH_PROFILE,
                accelerator_match_stage="finite_interval_coupled",
            )
            self.assertEqual(len(finite_coupled["arms"]), 2)
            fixed = finite_coupled["accelerator_match"]["fixed_focus_match"]
            for arm in finite_coupled["arms"]:
                voltage = arm["accelerator_voltage_override"]
                self.assertAlmostEqual(voltage["repeller_V"], fixed["repeller_v"])
                state = root / "prepared_finite_coupled" / arm["state_file"]
                with state.open(encoding="utf-8", newline="") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertTrue(all(float(row["x_mm"]) == 0.0 for row in rows))
                self.assertTrue(all(float(row["y_mm"]) == 0.0 for row in rows))
            self.assertIsNone(finite_coupled["arms"][0]["reflectron_voltage_override"])
            self.assertIsNotNone(finite_coupled["arms"][1]["reflectron_voltage_override"])
    def test_state_summary_uses_null_for_undefined_correlation(self) -> None:
        rows = [
            {
                "x_mm": str(index),
                "y_mm": "0",
                "z_mm": "1",
                "vx_m_s": "2000",
                "vy_m_s": "0",
                "vz_m_s": "3",
                "kinetic_energy_eV": "5",
            }
            for index in range(3)
        ]
        self.assertIsNone(_state_summary(rows)["z_vz_pearson"])

    def test_profile_rejects_unknown_fields(self) -> None:
        profile = json.loads(PROFILE.read_text(encoding="utf-8"))
        profile["unregistered_override"] = True
        with self.assertRaisesRegex(ValueError, "profile identity differs"):
            _validate_profile(profile)

    def test_workflow_replays_geometry_addressed_flight_tube(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("$flightTubeCacheIdentity", workflow)
        self.assertIn("$baselineOatofGeometry", workflow)
        self.assertIn("-SourceDirectory $currentFlightTubeDir `", workflow)
        self.assertIn("-BaseName 'flight_tube_ground'", workflow)
        self.assertIn("Baseline flight-tube PA cache identity differs.", workflow)
        self.assertIn("('cf_b{0:D2}.ion' -f $batchIndex)", workflow)
        self.assertIn("'--particles',$runtimeIon", workflow)


if __name__ == "__main__":
    unittest.main()
