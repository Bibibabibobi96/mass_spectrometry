from __future__ import annotations

import json
import hashlib
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ROOT = REPO_ROOT / "projects/rf_quadrupole_ion_optics"
MATLAB_CORE = REPO_ROOT / "common/multipole/solve_finite_3d_transport.m"
RUNNER = REPO_ROOT / "common/multipole/run_finite_3d_transport.ps1"
RUNTIME_PROFILES = PROJECT_ROOT / "config/runtime_profiles.json"
PREREGISTRATION = (
    PROJECT_ROOT
    / "config/family_experiment/vectorized_release_validation/preregistration.json"
)


class ComsolVectorizedReleaseContractTests(unittest.TestCase):
    def test_vectorized_profile_isolated_from_legacy_profiles(self) -> None:
        profiles = json.loads(RUNTIME_PROFILES.read_text(encoding="utf-8"))["profiles"]
        vectorized = profiles[
            "no_acceleration_full_length_n100_vectorized_release_exit020_t160"
        ]
        self.assertEqual(
            vectorized["comsol_particle_release_strategy"],
            "vectorized_phase",
        )
        self.assertNotIn(
            "comsol_particle_release_strategy",
            profiles["no_acceleration_full_length_n100_comsol_followup_exit020_t160"],
        )

    def test_matlab_core_preserves_both_release_semantics(self) -> None:
        source = MATLAB_CORE.read_text(encoding="utf-8-sig")
        for token in (
            "{'individual_features', 'vectorized_phase'}",
            "AuxiliaryField",
            "DistributionFunction_auxphase",
            "particle_phase_offset",
            "release.set('rt', '0[s]')",
            "release.set('rt',sprintf('%.17g[s]'",
            "absoluteTimeOffset=double(addBirthTimeOffset)",
        ):
            self.assertIn(token, source)

    def test_runner_freezes_and_exports_release_strategy(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn(
            "comsol_particle_release_strategy=$ComsolParticleReleaseStrategy",
            source,
        )
        self.assertIn(
            "$env:MULTIPOLE_L3_PARTICLE_RELEASE_STRATEGY="
            "$ComsolParticleReleaseStrategy",
            source,
        )
        self.assertIn(
            "COMSOL particle release strategy differs from the authorized runtime profile.",
            source,
        )

    def test_preregistration_authority_hashes_are_current(self) -> None:
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
                digest = hashlib.sha256(
                    (REPO_ROOT / entry["path"]).read_bytes()
                ).hexdigest().upper()
                self.assertEqual(digest, entry["sha256"])


if __name__ == "__main__":
    unittest.main()
