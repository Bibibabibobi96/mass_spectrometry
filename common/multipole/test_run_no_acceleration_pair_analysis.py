import unittest
from pathlib import Path


RUNNER = (
    Path(__file__).with_name("run_no_acceleration_pair_analysis.ps1")
    .read_text(encoding="utf-8")
)


class NoAccelerationPairAnalysisRunnerTests(unittest.TestCase):
    def test_freezes_both_manifests_and_primary_states(self) -> None:
        self.assertIn('"${side}_run_manifest.json"', RUNNER)
        self.assertIn('$inputs["${side}_run_manifest"]', RUNNER)
        self.assertIn("particle_state__primary.csv", RUNNER)
        self.assertIn("Copy-VerifiedRunInput", RUNNER)

    def test_uses_frozen_code_and_fixed_plot_contract(self) -> None:
        self.assertIn("$env:PYTHONPATH = $codeRoot", RUNNER)
        self.assertIn("common.multipole.followup_analysis", RUNNER)
        self.assertIn("--bin-count 24", RUNNER)
        self.assertIn("--dpi 200", RUNNER)

    def test_publishes_verified_compact_artifact(self) -> None:
        self.assertIn("-RetentionContractEnabled", RUNNER)
        self.assertIn("Apply-RunArtifactRetention", RUNNER)
        self.assertIn("Write-VerifiedRunManifest", RUNNER)


if __name__ == "__main__":
    unittest.main()
