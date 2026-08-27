from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_c4_locked_prediction import (
    analyze_c4_locked_prediction,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_focusability import (
    assign_detector_blind_cohorts,
)


class Paper1C4LockedPredictionTest(unittest.TestCase):
    def _locked_ids(self, salt: str) -> list[int]:
        return [item.particle_id for item in assign_detector_blind_cohorts(range(1, 200), salt=salt) if item.role == "locked_test"][:12]

    def _run(self, root: Path, name: str, identifiers: list[int], fwhm: float, transmission: float) -> Path:
        path = root / name
        path.mkdir()
        summary = {
            "status": "success", "launched_particle_count": len(identifiers), "pulse_effective_time_us": 10.0,
            "census": {"detector_crossing": len(identifiers)},
            "source_population": {"candidate_population_count": 80, "complete_pulse_eligible_population_simulated": True},
            "observed_cohort_authority": {"source_release": {"count": len(identifiers), "ordered_particle_ids": identifiers}},
            "pulse_effective_peak": {"direct_fwhm_mass_Da": fwhm, "mass_resolution": 100.0 / fwhm, "tail_fraction_outside_3sigma": 0.01, "significant_kde_modes": 1},
            "full_pulse_eligible_bootstrap": {"resolution_p2p5": 10.0, "resolution_p97p5": 20.0},
            "transmission": {"detector_fraction_of_candidate_population": transmission},
        }
        (path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (path / "run_manifest.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")
        return path

    def _case(self, root: Path, salt: str, runs: dict[str, Path]) -> Path:
        path = root / "case.json"
        path.write_text(json.dumps({"case_id": "test", "source_condition_id": "S1", "architecture": "three_zone", "cohort_salt": salt, "mother_cohort_count": 80, "minimum_detector_count": 10, "prediction_score": {"improve": 1.0, "zero": 2.0, "worsen": 3.0}, "runs": {name: str(run) for name, run in runs.items()}}), encoding="utf-8")
        return path

    def test_requires_c3_pass_before_detector_results_are_opened(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            c3, case = root / "c3.json", root / "case.json"
            c3.write_text(json.dumps({"stage_id": "C3_J3", "conclusion": "INCONCLUSIVE_REVISE"}), encoding="utf-8")
            case.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "PASS_CONTINUE"):
                analyze_c4_locked_prediction(c3_stage_report=c3, case_path=case)

    def test_accepts_frozen_locked_prediction_without_a_transmission_trade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, salt = Path(directory), "c4-test"
            ids = self._locked_ids(salt)
            runs = {"improve": self._run(root, "improve", ids, 0.01, 0.20), "zero": self._run(root, "zero", ids, 0.02, 0.20), "worsen": self._run(root, "worsen", ids, 0.03, 0.19)}
            c3 = root / "c3.json"
            c3.write_text(json.dumps({"stage_id": "C3_J3", "conclusion": "PASS_CONTINUE"}), encoding="utf-8")
            result = analyze_c4_locked_prediction(c3_stage_report=c3, case_path=self._case(root, salt, runs))
        self.assertEqual(result["conclusion"], "PASS_CONTINUE")
        self.assertEqual(result["metrics"]["observed_fwhm_order"], ["improve", "zero", "worsen"])

    def test_rejects_an_apparent_improvement_bought_by_transmission_loss(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, salt = Path(directory), "c4-test"
            ids = self._locked_ids(salt)
            runs = {"improve": self._run(root, "improve", ids, 0.01, 0.19), "zero": self._run(root, "zero", ids, 0.02, 0.20), "worsen": self._run(root, "worsen", ids, 0.03, 0.20)}
            c3 = root / "c3.json"
            c3.write_text(json.dumps({"stage_id": "C3_J3", "conclusion": "PASS_CONTINUE"}), encoding="utf-8")
            result = analyze_c4_locked_prediction(c3_stage_report=c3, case_path=self._case(root, salt, runs))
        self.assertEqual(result["conclusion"], "INCONCLUSIVE_REVISE")
        self.assertIn("improvement_not_bought_by_mother_transmission_loss", result["failures"])


if __name__ == "__main__":
    unittest.main()
