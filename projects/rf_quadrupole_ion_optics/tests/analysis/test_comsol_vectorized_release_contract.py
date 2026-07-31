from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = REPO_ROOT / "projects/rf_quadrupole_ion_optics"
MATLAB_CORE = REPO_ROOT / "common/multipole/solve_finite_3d_transport.m"
RUNNER = REPO_ROOT / "common/multipole/run_finite_3d_transport.ps1"
RUNTIME_PROFILES = PROJECT_ROOT / "config/runtime_profiles.json"
PREREGISTRATION = (
    PROJECT_ROOT
    / "config/family_experiment/vectorized_release_validation/preregistration_v3.json"
)
FAILED_PREREGISTRATION = (
    PROJECT_ROOT
    / "config/family_experiment/vectorized_release_validation/preregistration.json"
)


class ComsolVectorizedReleaseContractTests(unittest.TestCase):
    def test_failed_vectorized_profiles_are_not_active(self) -> None:
        profiles = json.loads(RUNTIME_PROFILES.read_text(encoding="utf-8"))["profiles"]
        self.assertFalse(
            any(
                "comsol_particle_release_strategy" in profile
                for profile in profiles.values()
            )
        )
        failed = json.loads(FAILED_PREREGISTRATION.read_text(encoding="utf-8"))
        self.assertEqual(failed["status"], "EXECUTED_FAILED")
        self.assertFalse(failed["observed_result"]["n1000_promotion_allowed"])
        failed_v2 = json.loads(
            (
                PROJECT_ROOT
                / "config/family_experiment/vectorized_release_validation/"
                "preregistration_v2.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(failed_v2["status"], "EXECUTED_FAILED")
        self.assertTrue(failed_v2["observed_result"]["particle_solve_stage_reached"])
        result = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "EXECUTED_NOT_EQUIVALENT")
        self.assertEqual(
            result["observed_result"]["decision"],
            "VECTOR_RELEASE_NOT_EQUIVALENT_RETAIN_INDIVIDUAL_FEATURES",
        )
        self.assertFalse(result["observed_result"]["n1000_promotion_allowed"])
        self.assertEqual(
            result["observed_result"]["fixed_bin_checks"]["primary"][
                "changed_particle_ids_by_field"
            ]["divergence_angle_deg"],
            [3, 23, 38, 55, 64, 68, 75, 100],
        )

    def test_active_solver_retains_only_individual_release_semantics(self) -> None:
        matlab_source = MATLAB_CORE.read_text(encoding="utf-8-sig")
        runner_source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("ReleaseFromDataFile", matlab_source)
        self.assertIn(
            "release.set('rt', sprintf('%.17g[s]', source.birth_time_s(index)))",
            matlab_source,
        )
        for token in (
            "AuxiliaryField",
            "DistributionFunction_auxphase",
            "particle_phase_offset",
            "cpt.create('force1','Force',3)",
        ):
            self.assertNotIn(token, matlab_source)
        self.assertNotIn("MULTIPOLE_L3_PARTICLE_RELEASE_STRATEGY", runner_source)

    def test_historical_authority_hashes_remain_frozen_evidence(self) -> None:
        preregistration = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
        authorities = preregistration["frozen_authorities"]
        entries = [
            authorities["runtime_profiles"],
            authorities["comsol_solver_numerics"],
            authorities["engineering_budget"],
            authorities["effect_resolution"],
            *authorities["implementation"],
        ]
        for entry in entries:
            with self.subTest(path=entry["path"]):
                self.assertTrue((REPO_ROOT / entry["path"]).is_file())
                self.assertRegex(entry["sha256"], r"^[0-9A-F]{64}$")


if __name__ == "__main__":
    unittest.main()
