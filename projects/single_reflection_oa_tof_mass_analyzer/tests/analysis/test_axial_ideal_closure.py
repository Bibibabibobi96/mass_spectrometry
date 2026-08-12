from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from projects.single_reflection_oa_tof_mass_analyzer.analysis.verify_axial_ideal_closure import (
    compute_receipt,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
CONTRACT_PATH = (
    REPOSITORY_ROOT
    / "projects/single_reflection_oa_tof_mass_analyzer/config/diagnostics"
    / "axial_ideal_arm8_analytic_closure.json"
)
RESOLVED_PATH = (
    REPOSITORY_ROOT
    / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
)


class AxialIdealClosureTest(unittest.TestCase):
    def _receipt(self) -> dict:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        resolved = json.loads(RESOLVED_PATH.read_text(encoding="utf-8"))
        return compute_receipt(
            contract,
            resolved,
            contract_path=CONTRACT_PATH,
            resolved_path=RESOLVED_PATH,
        )

    def test_arm8_analytic_closure_passes_all_physics_and_peak_gates(self) -> None:
        receipt = self._receipt()
        self.assertEqual(receipt["status"], "pass")
        self.assertTrue(receipt["all_assertions_passed"])
        self.assertEqual(
            receipt["longitudinal_return_focus"]["return_focus_arrival_count"], 1001
        )
        self.assertFalse(
            receipt["longitudinal_return_focus"]["mechanical_detector_hit_claimed"]
        )
        self.assertEqual(receipt["detector_arrival"]["active_disk_hit_count"], 1001)
        self.assertEqual(receipt["detector_arrival"]["active_disk_miss_count"], 0)
        self.assertEqual(
            receipt["detector_arrival"]["layout_profile_id"],
            "symmetric_10ev_injection_diagnostic",
        )
        self.assertAlmostEqual(
            receipt["detector_arrival"]["source_axis_x_mm"],
            -69.01362184380704,
        )
        self.assertAlmostEqual(
            receipt["detector_arrival"]["center_particle_offset_x_mm"],
            -1.0985150348849118,
            places=9,
        )
        self.assertAlmostEqual(
            receipt["peak_metrics"]["center_pulse_effective_return_focus_tof_us"],
            31.17087045244072,
            places=9,
        )
        self.assertAlmostEqual(
            receipt["peak_metrics"]["direct_fwhm_tof_ns"],
            0.20216219700230909,
            places=6,
        )
        self.assertAlmostEqual(
            receipt["peak_metrics"]["mass_resolution"],
            77093.86591916217,
            places=3,
        )
        self.assertEqual(receipt["peak_metrics"]["significant_kde_modes"], 1)
        self.assertFalse(receipt["qualification"]["solver_result"])

    def test_cli_writes_identified_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "projects.single_reflection_oa_tof_mass_analyzer.analysis.verify_axial_ideal_closure",
                    str(CONTRACT_PATH),
                    "--output",
                    str(output),
                ],
                cwd=REPOSITORY_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            receipt = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(receipt["arm_id"], "axial_source_all_ideal")
            self.assertEqual(receipt["claim_scope"], "analytic_closure_not_a_simion_or_comsol_solver_result")


if __name__ == "__main__":
    unittest.main()
