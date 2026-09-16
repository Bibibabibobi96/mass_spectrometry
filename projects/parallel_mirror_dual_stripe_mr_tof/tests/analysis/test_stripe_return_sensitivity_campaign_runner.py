"""Static orchestration tests for the managed Stripe sensitivity campaign."""
from __future__ import annotations

from pathlib import Path
import unittest


class StripeReturnSensitivityCampaignRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (
            Path(__file__).resolve().parents[2]
            / "analysis" / "run_stripe_return_sensitivity_campaign.ps1"
        ).read_text(encoding="utf-8-sig")

    def test_plan_requires_four_prewarm_states_and_eight_members(self) -> None:
        self.assertIn("$perturbedStates.Count-ne4", self.source)
        self.assertIn("@($plan.tasks).Count-ne8", self.source)
        self.assertIn("foreach($state in $perturbedStates)", self.source)
        self.assertIn("foreach($task in @($plan.tasks))", self.source)
        self.assertIn("$_.state-ne'baseline'", self.source)

    def test_campaign_only_calls_existing_managed_entries(self) -> None:
        self.assertIn("run_local_operating_pa_prewarm.ps1", self.source)
        self.assertIn("run_two_prism_trial.ps1", self.source)
        self.assertIn("analysis.stripe_return_sensitivity','plan'", self.source)
        self.assertIn("analysis.stripe_return_sensitivity','analyze'", self.source)
        self.assertNotIn("compose_local_operating_pa_lane", self.source)
        self.assertNotIn("Start-Job", self.source)
        self.assertNotIn("ThrottleLimit", self.source)

    def test_full_member_verification_and_failed_manifest_are_mandatory(self) -> None:
        self.assertIn("common\\contracts\\verify_run_manifest.py", self.source)
        self.assertIn("prewarm_{0:D2}_run_manifest", self.source)
        self.assertIn("member_{0:D2}_run_manifest", self.source)
        self.assertIn("Write-VerifiedRunManifest", self.source)
        self.assertIn("Complete-FailedRun", self.source)
        self.assertIn("Save-CampaignConfig", self.source)
        self.assertNotIn("ConvertTo-ArtifactRunPath", self.source)
        self.assertIn("$verification=@(& $python", self.source)
        self.assertIn("foreach($line in $verification){Write-Host $line}", self.source)

    def test_explicit_resume_reuses_only_verified_identity_bound_children(self) -> None:
        self.assertIn("[switch]$ReuseSuccessfulChildren", self.source)
        self.assertIn("function Assert-PrewarmIdentity", self.source)
        self.assertIn("target_voltage_vector_v", self.source)
        self.assertIn("local_workbench_run_manifest", self.source)
        self.assertIn("$prewarmManifests+=Assert-SuccessRun", self.source)
        self.assertIn("$memberManifests+=Assert-SuccessRun", self.source)
        self.assertIn("reused_member_flight_count", self.source)


if __name__ == "__main__":
    unittest.main()
