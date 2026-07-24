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
        self.assertIn("[string]$PythonExe", runner)
        self.assertEqual(runner.count("-PythonExe $python"), 3)
        self.assertIn(
            "inputs\\runtime_snapshot", runner
        )
        self.assertIn(
            "common\\contracts\\verify_run_manifest.py", runner
        )
        self.assertIn(
            "Resolve-RfDirectChildDirectory -ParentRoot $artifactRoot", runner
        )
        self.assertIn("$env:PYTHONPATH = $snapshotRoot", runner)
        self.assertIn("$env:PYTHONNOUSERSITE = '1'", runner)
        self.assertIn("Push-Location -LiteralPath $snapshotRoot", runner)
        for requirement in (
            "--require-status success",
            "--require-run-id $case.run_id",
            "--require-project rf_quadrupole_collision_cooling",
            "--require-mode $case.mode",
        ):
            self.assertIn(requirement, runner)
        self.assertNotIn(
            "Join-Path $repoRoot 'common\\contracts\\verify_run_manifest.py'",
            runner,
        )

    def test_internal_s3_runner_requires_explicit_s2_source(self) -> None:
        runner = (
            resolver.PROJECT_ROOT / "tests" / "comsol" / "run_s3_pulse_capture.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("[Parameter(Mandatory)][string]$SourceRunId", runner)
        self.assertIn("$sourceRunConfiguration.inputs.s2_contract", runner)
        self.assertNotIn("$s3Document.source.timing_state_run_id", runner)
        self.assertIn("New-RfRunPackage -Python $python", runner)


if __name__ == "__main__":
    unittest.main()
