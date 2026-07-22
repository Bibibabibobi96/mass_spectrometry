from __future__ import annotations

import unittest

from projects.rf_quadrupole_collision_cooling.analysis import resolve_s2_connector_case as resolver


class S3CumulativeRunnerTests(unittest.TestCase):
    def test_runner_orders_all_cumulative_stages_and_forwards_source_runs(self) -> None:
        runner = (
            resolver.PROJECT_ROOT / "tests" / "cross_solver" / "run_s3_cumulative_chain.ps1"
        ).read_text(encoding="utf-8")
        s2_index = runner.index("run_s2_passive_connector_field.ps1")
        s3_index = runner.index("run_s3_pulse_capture.ps1")
        downstream_index = runner.index("run_s3_end_to_end.ps1")
        self.assertLess(s2_index, s3_index)
        self.assertLess(s3_index, downstream_index)
        self.assertIn("-SourceRunId $s2RunId", runner)
        self.assertIn("-SourceRunId $s3RunId", runner)
        self.assertIn("verify_run_manifest.py", runner)

    def test_internal_s3_runner_requires_explicit_s2_source(self) -> None:
        runner = (
            resolver.PROJECT_ROOT / "tests" / "comsol" / "run_s3_pulse_capture.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("[Parameter(Mandatory)][string]$SourceRunId", runner)
        self.assertIn("$sourceRunConfiguration.inputs.s2_contract", runner)
        self.assertNotIn("$s3Document.source.timing_state_run_id", runner)


if __name__ == "__main__":
    unittest.main()
