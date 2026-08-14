from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.particle_physics import kinetic_energy_ev
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.analyze_single_flight import analyze
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.plot_single_flight_spatial_six_panel import marker_area


class SingleFlightAnalysisTests(unittest.TestCase):
    def test_n1000_marker_does_not_obscure_geometry(self) -> None:
        self.assertLess(marker_area(1000), marker_area(100))
        self.assertLessEqual(marker_area(1000), 2.0)

    def test_preserves_original_ion_identity_at_all_checkpoints(self) -> None:
        text = "\n".join([
            "TRACE: source_release ion=2 instrument_time_us=0 x_mm=-68.8 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=2 vz_mm_per_us=3",
            "TRACE: single_flight_handoff ion=2 instrument_time_us=10 x_mm=-67.8 y_mm=0 z_mm=-18.4 vx_mm_per_us=1 vy_mm_per_us=2 vz_mm_per_us=3",
            "TRACE: pre_pulse_state ion=2 instrument_time_us=20 x_mm=-48.8 y_mm=0 z_mm=1.5 vx_mm_per_us=1 vy_mm_per_us=2 vz_mm_per_us=3",
            "TRACE: local_accelerator_exit ion=2 instrument_time_us=41 x_mm=-67 y_mm=0 z_mm=20 vx_mm_per_us=2 vy_mm_per_us=0 vz_mm_per_us=20",
            "TRACE: detector_crossing ion=2 t=70 x=49 y=0 z=19.83 r=0 zmax=19.83",
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "log.txt"
            path.write_text(text, encoding="utf-8")
            rows, summary = analyze(path, 3, 100.0)
        self.assertEqual({row["particle_id"] for row in rows}, {2})
        self.assertEqual(summary["census"]["launched"], 3)
        self.assertEqual(summary["census"]["detector_crossing"], 1)
        self.assertEqual(summary["census"]["reflectron_turning_point"], 0)
        self.assertIsNone(summary["instrument_clock_peak"])
        self.assertFalse(summary["instrument_clock_peak_is_resolution_claim"])
        pre_pulse = next(row for row in rows if row["event"] == "pre_pulse_state")
        self.assertGreater(pre_pulse["kinetic_energy_eV"], 0.0)

    def test_target_energy_uses_pre_pulse_state_inside_accelerator(self) -> None:
        text = "\n".join([
            "TRACE: single_flight_handoff ion=1 instrument_time_us=9 x_mm=-88 y_mm=0 z_mm=-18.4 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: pre_pulse_state ion=1 instrument_time_us=10 x_mm=-69 y_mm=0 z_mm=-18.4 vx_mm_per_us=4.392 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: handoff_pulse_on ion=1 instrument_time_us=10",
        ])
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

    def test_particle_pulse_callbacks_do_not_override_effective_pulse_time(self) -> None:
        text = "\n".join([
            "TRACE: source_release ion=1 instrument_time_us=0 x_mm=-69 y_mm=0 z_mm=-18.4 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: source_release ion=2 instrument_time_us=0 x_mm=-69 y_mm=0 z_mm=-18.3 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: pre_pulse_state ion=1 instrument_time_us=10 x_mm=-69 y_mm=0 z_mm=-18.4 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: pre_pulse_state ion=2 instrument_time_us=10 x_mm=-69 y_mm=0 z_mm=-18.3 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: handoff_pulse_on ion=1 instrument_time_us=10.000001",
            "TRACE: handoff_pulse_on ion=2 instrument_time_us=10.000002",
            "TRACE: detector_crossing ion=1 t=20 x=0 y=0 z=0",
            "TRACE: detector_crossing ion=2 t=20.001 x=0 y=0 z=0",
        ])
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.txt"
            log.write_text(text, encoding="utf-8")
            _, summary = analyze(log, 2, 100.0, pulse_time_us=10.0)
        self.assertEqual(summary["pulse_effective_time_us"], 10.0)
        self.assertIsNone(summary["pulse_first_observed_us"])

    def test_canonical_clock_does_not_add_birth_time_to_detector_time(self) -> None:
        text = "\n".join([
            "TRACE: source_release ion=1 instrument_time_us=0.25 x_mm=-70 y_mm=0 z_mm=-18 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: source_release ion=2 instrument_time_us=0.75 x_mm=-70 y_mm=0 z_mm=-18 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: detector_crossing ion=1 t=70.5 x=69 y=0 z=0",
            "TRACE: detector_crossing ion=2 t=70.0 x=69 y=0 z=0",
        ])
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.txt"
            log.write_text(text, encoding="utf-8")
            rows, summary = analyze(
                log, 2, 100.0
            )
        detector_times = [
            row["instrument_time_us"]
            for row in rows
            if row["event"] == "detector_crossing"
        ]
        self.assertEqual(detector_times, [70.75, 70.75])
        self.assertEqual(
            summary["detector_time_basis"], "canonical_instrument_time_us"
        )

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
        self.assertEqual(
            sorted({row["particle_id"] for row in rows}), [1, 2, 3, 4, 5]
        )
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
                log, 1, 100.0, pulse_time_us=45.5,
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
                    log, 1, 100.0, pulse_time_us=45.5,
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
                log, 1, 100.0, pulse_time_us=45.5,
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

    def test_classifies_physical_pulse_capture_without_rejecting_losses(self) -> None:
        text = "\n".join([
            "TRACE: source_release ion=1 instrument_time_us=0 x_mm=-69 y_mm=0 z_mm=-18.4 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: pre_pulse_state ion=1 instrument_time_us=10 x_mm=-69 y_mm=0 z_mm=-18.4 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: pre_pulse_state ion=2 instrument_time_us=10 x_mm=-69 y_mm=0 z_mm=-20.0 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: pre_pulse_state ion=3 instrument_time_us=10 x_mm=-60 y_mm=0 z_mm=-18.4 vx_mm_per_us=4 vy_mm_per_us=0 vz_mm_per_us=0",
            "TRACE: detector_crossing ion=1 t=70 x=49 y=0 z=19.83",
        ])
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
            rows, summary = analyze(log, 4, 100.0, model, 10.0)
        capture = summary["pulse_capture"]
        self.assertEqual(capture["counts"], {
            "eligible": 1,
            "upstream_of_repeller": 1,
            "downstream_of_grid1": 0,
            "outside_transverse_bore": 1,
            "missing_before_pulse": 1,
        })
        self.assertEqual(capture["capture_fraction_of_launched"], 0.25)
        self.assertEqual(capture["conditional_detector_efficiency"], 1.0)
        classified = {
            row["particle_id"]: row["pulse_eligibility"]
            for row in rows if row["event"] == "pre_pulse_state"
        }
        self.assertEqual(classified[2], "upstream_of_repeller")
        self.assertEqual(classified[3], "outside_transverse_bore")

    def test_three_axis_window_reports_only_detector_blind_spatial_metrics(self) -> None:
        lines = []
        positions = [
            (-69.0, 0.0, -18.4),
            (-69.4, 0.4, -18.8),
            (-68.6, -0.4, -18.0),
            (-68.4, 0.0, -18.4),
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
            lines.append(
                f"TRACE: detector_crossing ion={particle_id} "
                f"t={70 + particle_id * 0.01} x=49 y=0 z=19.83"
            )
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
                "accelerator_bore_half": 5.0,
            },
        }
        profile = {
            "profile_id": "ideal_source_box_1mm_xyz",
            "event": "pre_pulse_state",
            "axes": {
                axis: {
                    "center_binding": f"particle_source.center_{axis}_mm",
                    "full_width_mm": 1.0,
                }
                for axis in ("x", "y", "z")
            },
            "selection_uses_detector_outcome": False,
            "field_error_budget": {
                "derivation": "frozen_test_budget",
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
            _, summary = analyze(
                log, 4, 100.0, model, 10.0,
                spatial_window_profile=profile,
                population_denominator_count=6,
                eligible_population_count=4,
            )
        window = summary["spatial_window_peak"]
        self.assertNotIn("pulse_effective_peak", window)
        self.assertNotIn("bootstrap", window)
        self.assertNotIn("mass_resolution_ratio_to_full_pulse_eligible", window)
        self.assertIsNone(summary["pulse_effective_peak"])
        self.assertIsNone(summary["full_pulse_eligible_bootstrap"])
        self.assertFalse(
            summary["detector_clock_diagnostic"]["peak_metrics_computed"]
        )
        self.assertEqual(window["selected_count"], 3)
        self.assertEqual(window["pulse_eligible_coverage_fraction"], 0.75)
        self.assertFalse(window["selection_uses_detector_outcome"])
        self.assertEqual(window["axis_semantics"]["acceleration_direction"], "z")
        self.assertEqual(
            summary["source_population"]["efficiency_denominator"],
            "candidate_population_count",
        )
        self.assertEqual(
            summary["transmission"]["detector_fraction_of_candidate_population"],
            4 / 6,
        )
        population = summary["source_population"]
        self.assertEqual(
            population["simulation_population_basis"],
            "pulse_eligible_conditional_population",
        )
        self.assertEqual(population["simulated_population_count"], 4)
        self.assertEqual(population["pulse_eligible_population_count"], 4)
        self.assertEqual(population["simulated_fraction_of_candidate_population"], 4 / 6)
        self.assertEqual(population["simulated_fraction_of_pulse_eligible_population"], 1.0)

    def test_full_population_derives_pulse_eligible_count_from_observed_state(self) -> None:
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
            _, summary = analyze(log, 2, 100.0, model, 10.0)

        population = summary["source_population"]
        self.assertEqual(population["simulation_population_basis"], "candidate_full_population")
        self.assertEqual(population["simulated_population_count"], 2)
        self.assertEqual(population["pulse_eligible_population_count"], 1)
        self.assertEqual(population["raw_pulse_capture_fraction"], 0.5)
        self.assertEqual(population["simulated_fraction_of_candidate_population"], 1.0)
        self.assertIsNone(population["simulated_fraction_of_pulse_eligible_population"])

    def test_five_dimensional_window_uses_forward_velocity_angles(self) -> None:
        lines = []
        for particle_id, (vx, vy, vz) in enumerate(
            [(0.1, 0.1, 10), (-0.1, 0, 10), (0, -0.1, 10), (0, 0, -10)], 1
        ):
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
                lines.append(
                    f"TRACE: detector_crossing ion={particle_id} "
                    f"t={70 + particle_id * 0.01} x=0 y=0 z=0"
                )
        geometry = {
            "particle_source": {
                "center_x_mm": -69.0, "center_y_mm": 0.0,
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
            } | {
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
            _, summary = analyze(
                log, 4, 100.0, model, 10.0, spatial_window_profile=profile
            )
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
                "accelerator_focus_forward", "reflectron_entrance_forward",
                "reflectron_midgrid_forward", "reflectron_turning_point",
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
            lines.append(
                f"TRACE: detector_crossing ion={particle_id} "
                f"t={70 + particle_id * 0.001} x=0 y=0 z=0"
            )
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log.txt"
            log.write_text("\n".join(lines), encoding="utf-8")
            _, summary = analyze(log, 4, 100.0, pulse_time_us=10.0)
        self.assertEqual(
            summary["resolution_time_basis"],
            "detector_time_minus_pulse_effective_time",
        )
        self.assertIsNotNone(summary["pulse_effective_peak"])
        self.assertIsNotNone(summary["instrument_clock_peak"])
        self.assertFalse(summary["instrument_clock_peak_is_resolution_claim"])
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
        text = "\n".join([
            "TRACE: reflectron_entrance_forward ion=1 particle_id=1 instrument_time_us=20 tof_since_pulse_us=10 x_mm=0 y_mm=0 z_mm=600 vx_mm_per_us=0 vy_mm_per_us=0 vz_mm_per_us=1",
            "TRACE: reflectron_turning_point ion=1 particle_id=1 instrument_time_us=30 tof_since_pulse_us=20 x_mm=0 y_mm=0 z_mm=700 vx_mm_per_us=0 vy_mm_per_us=0 vz_mm_per_us=0",
        ])
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
