from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "analysis" / "run_target_operating_point_chain.ps1"


class TargetOperatingPointChainRunnerTests(unittest.TestCase):
    def test_runner_composes_managed_exact_k_and_stripe_stages(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("run_mirror_exact_k_operating_point.ps1", source)
        self.assertIn("run_dual_stripe_operating_seed.ps1", source)
        self.assertIn("ExactKRunManifest = $exactManifest", source)
        self.assertIn("target_drift_period_ratio", source)
        self.assertIn("target_half_oscillation_count", source)
        self.assertIn("qualification = [string]$stripeSummary.qualification", source)

    def test_runner_has_no_independent_k_override_or_fixed_k_value(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("[double]$K", source)
        self.assertNotIn("25.5", source)
        self.assertIn("ContractPath", source)
        self.assertIn("refuses to overwrite", source)


if __name__ == "__main__":
    unittest.main()
