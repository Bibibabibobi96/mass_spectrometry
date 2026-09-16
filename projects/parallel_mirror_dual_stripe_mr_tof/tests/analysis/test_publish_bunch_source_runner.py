from __future__ import annotations

from pathlib import Path
import unittest


PROJECT = Path(__file__).resolve().parents[2]
RUNNER = PROJECT / "analysis" / "run_publish_bunch_source.ps1"


class PublishBunchSourceRunnerTests(unittest.TestCase):
    def test_runner_freezes_complete_definition_and_geometry(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("[Parameter(Mandatory)][string]$SourceDefinitionPath", source)
        self.assertIn("[Parameter(Mandatory)][string]$GeometryContractPath", source)
        self.assertIn("Copy-VerifiedRunInput -Source $sourceDefinition", source)
        self.assertIn("Copy-VerifiedRunInput -Source $geometryContract", source)
        self.assertIn("--geometry-contract $frozenGeometry", source)
        self.assertIn("Write-VerifiedRunManifest", source)
        self.assertIn("Apply-RunArtifactRetention", source)
        self.assertIn("Invoke-ArtifactCapacityGate", source)

    def test_runner_publishes_only_source_payloads_without_solver_execution(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("bunch_source_states.csv", source)
        self.assertIn("bunch_source.fly2", source)
        self.assertIn("bunch_source_receipt.json", source)
        self.assertIn("solver_execution='none'", source)
        self.assertNotIn("simion.exe", source.lower())
        self.assertNotIn("run_iob", source.lower())
        self.assertNotIn("refine", source.lower())


if __name__ == "__main__":
    unittest.main()
