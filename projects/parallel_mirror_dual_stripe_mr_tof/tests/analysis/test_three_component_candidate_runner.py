"""Static contract tests for the no-flight MR-TOF three-component IOB runner."""
from __future__ import annotations

import unittest
from pathlib import Path


RUNNER = Path(__file__).resolve().parents[2] / "simion" / "run_three_component_candidate.ps1"


class ThreeComponentCandidateRunnerTests(unittest.TestCase):
    def test_runner_is_a_strict_no_flight_iob_assembly_entry(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("Set-StrictMode -Version Latest", source)
        self.assertIn("$ErrorActionPreference = 'Stop'", source)
        self.assertIn("three_component_candidate_iob_assembly", source)
        self.assertNotIn("run_iob_flight.lua", source)
        self.assertNotIn("'fly'", source)

    def test_runner_freezes_complete_seed_bundle_and_existing_run_local_pas(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "3_instance_seed.iob",
            "iob_seed_placeholder_{0:D2}.pa0",
            "mrtof_analyzer.pa0",
            "mrtof_accelerator.pa0",
            "mrtof_analyzer.gem",
            "mrtof_accelerator.gem",
            "mrtof_detector.pa#",
            "analyzer raw PA# companion",
            "accelerator raw PA# companion",
            "Runner requires solved analyzer/accelerator .pa0 inputs and a raw detector .pa# input.",
            "Runner requires the exact analyzer and accelerator .gem sources that built its PA families.",
            "materialize_simion_prototype",
            "three_component_simion_run_manifest.py",
            "three_component_geometry_review.json",
            "Invoke-ArtifactCapacityGate",
            "artifact_capacity_gate_startup.json",
            "artifact_capacity_gate_terminal.json",
            "RequiredHeadroomBytes $inputCopyBytes",
        ):
            self.assertIn(token, source)

    def test_runner_serializes_simion_and_writes_a_terminal_record(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("Enter-HostExecutionLease -Role SIMION -RunId $RunId", source)
        self.assertIn("Exit-HostExecutionLease -Lease $hostExecutionLease -Outcome $hostExecutionOutcome -RunId $RunId", source)
        self.assertEqual(source.count("Complete-FailedRun"), 2)
        self.assertIn("-Status interrupted -FailureStage $failureStage", source)
        self.assertIn("Write-VerifiedRunManifest", source)
        self.assertLess(source.index("materialize_simion_prototype"), source.index("Enter-HostExecutionLease"))
        self.assertLess(
            source.index("Enter-HostExecutionLease"),
            source.index("Invoke-MrtofSimionStep -Stage 'build_three_component_iob'"),
        )
        self.assertLess(
            source.index("Invoke-MrtofSimionStep -Stage 'inspect_three_component_iob'"),
            source.index("write_geometry_review_receipt"),
        )
        self.assertLess(source.index("capacity_preflight"), source.index("freeze_inputs"))
        self.assertLess(source.index("capacity_terminal"), source.index("Write-VerifiedRunManifest"))


if __name__ == "__main__":
    unittest.main()
