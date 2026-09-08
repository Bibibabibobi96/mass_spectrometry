from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import (
    analyze_trial,
)


class TwoPrismSimionTrialTest(unittest.TestCase):
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
