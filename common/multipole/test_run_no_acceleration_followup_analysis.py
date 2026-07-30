from pathlib import Path
import unittest


RUNNER = Path(__file__).with_name(
    "run_no_acceleration_followup_analysis.ps1"
).read_text(encoding="utf-8-sig")


class FollowupAnalysisRunnerTests(unittest.TestCase):
    def test_runner_freezes_all_factorial_manifests_and_states(self) -> None:
        self.assertIn("foreach ($arm in $armRunIds.Keys)", RUNNER)
        self.assertIn('arm_${arm}_run_manifest', RUNNER)
        self.assertIn('arm_${arm}_particle_state', RUNNER)
        self.assertIn("particle_states__rf_on.csv", RUNNER)

    def test_runner_uses_frozen_analysis_code_and_shared_plot_contract(self) -> None:
        self.assertIn("$env:PYTHONPATH = $codeRoot", RUNNER)
        self.assertIn("common.multipole.followup_analysis", RUNNER)
        self.assertIn("common.multipole.exit_state_plot", RUNNER)
        self.assertIn("'--bin-count', '24'", RUNNER)
        self.assertIn("'--dpi', '200'", RUNNER)

    def test_runner_publishes_a_compact_verified_run(self) -> None:
        self.assertIn("-RetentionContractEnabled", RUNNER)
        self.assertIn("Apply-RunArtifactRetention", RUNNER)
        self.assertIn("Write-VerifiedRunManifest", RUNNER)
        self.assertIn("formal_gate_passed = $false", RUNNER)


if __name__ == "__main__":
    unittest.main()
