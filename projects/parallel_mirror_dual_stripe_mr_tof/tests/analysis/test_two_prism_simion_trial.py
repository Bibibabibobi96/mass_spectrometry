from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import (
    _lua_prism_switch,
    analyze_trial,
)


class TwoPrismSimionTrialTest(unittest.TestCase):
    def test_lua_switch_serializes_both_physical_prisms(self) -> None:
        text = _lua_prism_switch({
            "enabled": True,
            "electrode_id": 17,
            "time_us": 773.5,
            "injection_voltage_v": -179.0,
            "extraction_voltage_v": -140.0,
            "prism_1_extraction_voltage_v": 0.0,
        })
        self.assertIn("prism_1_extraction_voltage_v = 0", text)
        self.assertIn("extraction_voltage_v = -140", text)
        self.assertTrue(text.endswith("}, "))

    def test_switched_trial_reports_nearest_detector_rectangle_residual(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [177.0, -179.0],
                "source_position_project_mm": [0.0, -55.0, 0.0],
                "target_turn_y_mm": 0.0,
                "target_slow_kinetic_energy_per_charge_v": 5.0,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "continue_main_drift": False,
                "detector_box_mm": [-25.0, -87.0, 95.0, 25.0, -37.0, 97.0],
                "prism_switch": {
                    "time_us": 10.0,
                    "extraction_voltage_v": -120.0,
                    "prism_1_extraction_voltage_v": 0.0,
                },
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("\n".join([
                "MRTOF_EVENT prism_voltage_switch ion=1 electrode=17 t_us=10 from_v=-179 to_v=-120",
                "MRTOF_EVENT prism_voltage_switch ion=1 electrode=16 t_us=10 from_v=177 to_v=0",
                "MRTOF_EVENT post_return_mirror_turn ion=1 n=1 t_us=10.2 x_mm=0 y_mm=-2 z_mm=-280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0",
                "MRTOF_EVENT post_return_mirror_turn ion=1 n=2 t_us=10.7 x_mm=0 y_mm=-5 z_mm=280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=0",
                "MRTOF_EVENT detector_plane ion=1 direction_z=-1 t_us=11 x_mm=0 y_mm=-36.8 z_mm=97 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-39",
                "MRTOF_EVENT detector_plane ion=1 direction_z=-1 t_us=12 x_mm=27 y_mm=-50 z_mm=97 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-39",
                "MRTOF_EVENT terminal ion=1 splat=-1 t_us=13 x_mm=0 y_mm=-40 z_mm=0 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-39 turns=1 central_crossings=1",
            ]) + "\n", encoding="utf-8")
            result = analyze_trial(
                log_path=log,
                trial_receipt_path=receipt,
                output_path=root / "observation.json",
            )
            diagnostic = result["extraction_diagnostic"]
            self.assertTrue(diagnostic["event_contract_ok"])
            self.assertEqual(diagnostic["expected_switched_electrodes"], [16, 17])
            self.assertEqual(diagnostic["post_return_mirror_turn_count"], 2)
            self.assertEqual(diagnostic["mirror_turns_before_earliest_causal_plane"], 2)
            self.assertAlmostEqual(diagnostic["earliest_causal_center_residual_xy_mm"][1], 25.2)
            self.assertAlmostEqual(diagnostic["nearest_rectangle_distance_mm"], 0.2)
            self.assertAlmostEqual(diagnostic["nearest_rectangle_residual_xy_mm"][0], 0.0)
            self.assertAlmostEqual(diagnostic["nearest_rectangle_residual_xy_mm"][1], 0.2)

    def test_continued_trial_reports_L_and_fractional_K_residuals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [177.0, -180.0],
                "source_position_project_mm": [0.0, -55.0, 0.0],
                "target_turn_y_mm": 0.0,
                "target_slow_kinetic_energy_per_charge_v": 5.0,
                "target_slow_turn_y_mm": 340.0,
                "target_oscillation_count": 25,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "continue_main_drift": True,
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("\n".join([
                "MRTOF_EVENT prism_pass ion=1 n=1 t_us=1 x_mm=0 y_mm=-40 z_mm=-101 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-2",
                "MRTOF_EVENT pre_injection_mirror_turn ion=1 t_us=2 x_mm=0 y_mm=-30 z_mm=-280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT prism_pass ion=1 n=2 t_us=3 x_mm=0 y_mm=-10 z_mm=97 vx_mm_us=0 vy_mm_us=1 vz_mm_us=2",
                "MRTOF_EVENT drift_phase_origin ion=1 t_us=4 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1.358049167 vz_mm_us=0",
                "MRTOF_EVENT slow_turn ion=1 n=1 t_us=10 x_mm=0 y_mm=258.75 z_mm=0",
                "MRTOF_EVENT drift_coordinate_return ion=1 k_before=19 fractional_k=19.014 phase_turn_t_us=20 phase_turn_y_mm=0.5 phase_time_residual_us=0.4 phase_period_us=30 t_us=20.4 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-2",
                "MRTOF_EVENT terminal ion=1 splat=-1 t_us=21 x_mm=0 y_mm=-1 z_mm=0 vx_mm_us=0 vy_mm_us=-1 vz_mm_us=-2 turns=38 central_crossings=38",
            ]) + "\n", encoding="utf-8")
            output = root / "observation.json"
            result = analyze_trial(log_path=log, trial_receipt_path=receipt, output_path=output)
            self.assertEqual(result["status"], "full_drift_observed")
            self.assertAlmostEqual(result["residuals"]["Stripe_slow_turn_y_minus_L_mm"], -81.25)
            self.assertAlmostEqual(result["residuals"]["Stripe_fractional_K_minus_target"], -5.986)

    def test_continued_trial_fails_closed_without_return(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "trial.json"
            receipt.write_text(json.dumps({
                "prism_voltages_v": [177.0, -180.0],
                "source_position_project_mm": [0.0, -55.0, 0.0],
                "target_turn_y_mm": 0.0,
                "target_slow_kinetic_energy_per_charge_v": 5.0,
                "target_slow_turn_y_mm": 340.0,
                "target_oscillation_count": 25,
                "particle_mass_th": 524.0,
                "charge_state": 1,
                "continue_main_drift": True,
            }), encoding="utf-8")
            log = root / "flight.log"
            log.write_text("\n".join([
                "MRTOF_EVENT prism_pass ion=1 n=1 t_us=1 x_mm=0 y_mm=-40 z_mm=-101 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-2",
                "MRTOF_EVENT pre_injection_mirror_turn ion=1 t_us=2 x_mm=0 y_mm=-30 z_mm=-280 vx_mm_us=0 vy_mm_us=1 vz_mm_us=0",
                "MRTOF_EVENT prism_pass ion=1 n=2 t_us=3 x_mm=0 y_mm=-10 z_mm=97 vx_mm_us=0 vy_mm_us=1 vz_mm_us=2",
                "MRTOF_EVENT drift_phase_origin ion=1 t_us=4 x_mm=0 y_mm=0 z_mm=280 vx_mm_us=0 vy_mm_us=1.358049167 vz_mm_us=0",
                "MRTOF_EVENT terminal ion=1 splat=-1 t_us=5 x_mm=0 y_mm=1 z_mm=0 vx_mm_us=0 vy_mm_us=1 vz_mm_us=-2 turns=0 central_crossings=0",
            ]) + "\n", encoding="utf-8")
            result = analyze_trial(
                log_path=log,
                trial_receipt_path=receipt,
                output_path=root / "observation.json",
            )
            self.assertEqual(result["status"], "full_drift_incomplete")
            self.assertNotIn("Stripe_fractional_K_minus_target", result["residuals"])


if __name__ == "__main__":
    unittest.main()
