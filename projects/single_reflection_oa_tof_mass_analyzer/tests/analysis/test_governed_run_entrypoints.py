from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class GovernedRunEntrypointTests(unittest.TestCase):
    def test_governed_oa_artifact_entrypoints_use_registered_run_packages(self):
        entries = {
            "workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1": "solver_review",
            "workflows/formal_reference/run_formal_validation.ps1": "qualification",
            "workflows/cross_solver_diagnostics/run_cross_solver_diagnostics.ps1": "solver_review",
            "simion/workbench/run_ideal_field_diagnostic.ps1": "solver_review",
            "tests/simion/run_field_idealization_sweep.ps1": "compact",
            "tests/comsol/run_extreme_particle_count_case.ps1": "compact",
        }
        for relative, retention_class in entries.items():
            with self.subTest(entry=relative):
                source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("New-RunPackage", source)
                self.assertIn("-RetentionContractEnabled", source)
                self.assertIn("-CapacityLedgerLifecycleEnabled", source)
                self.assertIn(f"-RetentionClass {retention_class}", source)
                self.assertNotIn("Initialize-RunRecord", source)
                self.assertIn("artifact_retention", source)
                self.assertIn("capacity_ledger_lifecycle", source)
        mass_source = (PROJECT_ROOT / "workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1").read_text(encoding="utf-8")
        self.assertIn("Resume requires an existing governed retention and capacity-ledger lifecycle.", mass_source)

    def test_public_output_directory_overrides_are_canonical_run_paths(self):
        for relative in (
            "simion/workbench/run_ideal_field_diagnostic.ps1",
            "tests/simion/run_field_idealization_sweep.ps1",
        ):
            with self.subTest(entry=relative):
                source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("$expectedOutputDir", source)
                self.assertIn("canonical artifacts/runs", source)
                self.assertLess(source.index("$expectedOutputDir"), source.index("New-RunPackage"))


if __name__ == "__main__":
    unittest.main()
