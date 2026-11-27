from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4] / "src/msplatform/components/single_reflection_oa_tof"


def entry_source(relative: str) -> Path:
    root = PROJECT_ROOT.parents[3]
    if relative.startswith("workflows/"):
        return root / "src/msplatform/workflows/resources" / relative.rsplit("/", 1)[-1]
    if relative.startswith("simion/workbench/"):
        return root / "src/msplatform/backends/simion/resources" / relative.rsplit("/", 1)[-1]
    if relative.startswith("tests/"):
        return root / "tests/components/single_reflection_oa_tof_mass_analyzer" / relative[len("tests/"):]
    return root / relative


class GovernedRunEntrypointTests(unittest.TestCase):
    def test_governed_oa_artifact_entrypoints_use_registered_run_packages(self):
        entries = {
            "workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1": "solver_review",
            "workflows/formal_reference/run_formal_validation.ps1": "qualification",
            "workflows/cross_solver_diagnostics/run_cross_solver_diagnostics.ps1": "solver_review",
            "simion/workbench/run_ideal_field_diagnostic.ps1": "solver_review",
            "tests/simion/run_field_idealization_sweep.ps1": "compact",
        }
        for relative, retention_class in entries.items():
            with self.subTest(entry=relative):
                source = entry_source(relative).read_text(encoding="utf-8")
                if relative == "workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1":
                    self.assertIn("msplatform.workflows.single_reflection_mass_spectrum_study", source)
                    self.assertIn("resume-finalization", source)
                    self.assertNotIn("New-RunPackage", source)
                    self.assertNotIn("Initialize-RunRecord", source)
                    continue
                self.assertIn("New-RunPackage", source)
                self.assertIn("-RetentionContractEnabled", source)
                self.assertIn("-CapacityLedgerLifecycleEnabled", source)
                self.assertIn(f"-RetentionClass {retention_class}", source)
                self.assertNotIn("Initialize-RunRecord", source)
                if relative != "simion/workbench/run_ideal_field_diagnostic.ps1":
                    self.assertIn("artifact_retention", source)
                    self.assertIn("capacity_ledger_lifecycle", source)
                # Ideal diagnostics now retain these fields by merging the existing public package.
                # Its actual normal-entrypoint test checks retained paths/capacity/sentinel values;
                # the public New-RunPackage/retention/lifecycle switches above remain required here.

    def test_installed_entrypoints_require_explicit_roots_without_checkout_fallbacks(self):
        public_entries = (
            "workflows/formal_reference/run_formal_validation.ps1",
            "workflows/cross_solver_diagnostics/run_cross_solver_diagnostics.ps1",
            "workflows/accelerator_transverse_field_uniformity/run_accelerator_transverse_field_uniformity.ps1",
            "simion/workbench/run_parameterized_geometry_smoke.ps1",
            "simion/workbench/run_ideal_field_diagnostic.ps1",
        )
        for relative in public_entries:
            with self.subTest(entry=relative):
                source = entry_source(relative).read_text(encoding="utf-8")
                self.assertIn("$WorkspaceRoot", source)
                self.assertIn("$ArtifactRootPath", source)
                self.assertIn("$ScienceRoot", source)
                self.assertIn("$packageRoot", source)
                for fallback in (".venv", "PYTHONPATH", "Join-Path $repoRoot 'src"):
                    self.assertNotIn(fallback, source)
        mass = entry_source("workflows/mass_spectrum_candidate/run_mass_spectrum_candidate.ps1").read_text(encoding="utf-8")
        self.assertIn("$Workspace", mass)
        self.assertIn("$ArtifactRootPath", mass)
        self.assertIn("$ScienceRoot", mass)
        self.assertNotIn("MASS_SPECTRUM_WORKSPACE", mass)
        self.assertNotIn("PYTHONPATH", mass)
        transport = entry_source("simion/workbench/run_n100_transport.ps1").read_text(encoding="utf-8")
        self.assertIn("$packageRoot", transport)
        self.assertIn("inputs/code", transport)
        self.assertNotIn(".venv", transport)
        self.assertNotIn("PYTHONPATH", transport)

    def test_public_output_directory_overrides_are_canonical_run_paths(self):
        for relative in (
            "simion/workbench/run_ideal_field_diagnostic.ps1",
            "tests/simion/run_field_idealization_sweep.ps1",
        ):
            with self.subTest(entry=relative):
                source = entry_source(relative).read_text(encoding="utf-8")
                self.assertIn("$expectedOutputDir", source)
                self.assertIn("canonical artifacts/runs", source)
                self.assertLess(source.index("$expectedOutputDir"), source.index("New-RunPackage"))


if __name__ == "__main__":
    unittest.main()
