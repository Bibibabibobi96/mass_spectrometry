"""Static contract checks for the managed accelerator-family runner."""
from __future__ import annotations

from pathlib import Path
import unittest


PROJECT = Path(__file__).resolve().parents[2]


class AcceleratorPAFamilyRunnerTest(unittest.TestCase):
    def test_runner_reuses_cache_and_performs_native_geometry_gate(self) -> None:
        source = (PROJECT / "simion/run_accelerator_pa_family.ps1").read_text(encoding="utf-8")
        for token in (
            "New-RunPackage",
            "Invoke-ArtifactCapacityGate",
            "simion_pa_family_cache",
            "'--action','probe'",
            "'--action','publish'",
            "test_accelerator_native_geometry.lua",
            "Enter-HostExecutionLease -Role SIMION",
            "Write-VerifiedRunManifest",
            "Remove-RunPackageExecutionAlias",
            "ConvertTo-ArtifactRunPath $frozenContract",
            "export_standalone_pa.lua",
            "export_fast_adjusted_standalone_pa.lua",
            "measure_pa_basis_voltage.lua",
            "standalone_response_contract",
            "verify_private_family_stability",
            "--require-stable-inventory",
            "Remove-GateTemporaryDirectory",
        ):
            self.assertIn(token, source)
        self.assertIn("-RetentionClass solver_review", source)
        self.assertIn("-RetentionReason", source)
        self.assertNotIn("Remove-Item", source)
        self.assertNotIn("'--action','materialize'", source)
        self.assertIn("if($cacheDisposition-eq'hit'){0}", source)
        self.assertIn("-ProtectedCacheKeys $startupProtectedCacheKeys", source)
        self.assertIn("if($cacheDisposition-eq'published')", source)
        self.assertIn("$publishedCacheBytes=$payloadBytes+$generationManifestBytes+$generationPointerBytes", source)
        self.assertIn("$maximum=$runArtifactBytes+$publishedCacheBytes", source)
        self.assertIn("Published accelerator cache inventory differs from its publication receipt.", source)
        self.assertIn("applied_voltage_v / measured_basis_normalization_v", (
            PROJECT / "analysis/simion_pa_family_cache.py"
        ).read_text(encoding="utf-8"))

    def test_runner_exports_only_inside_fresh_private_family_before_publish(self) -> None:
        source = (PROJECT / "simion/run_accelerator_pa_family.ps1").read_text(
            encoding="utf-8"
        )
        private_creation = source.index("'mrtof_accelerator_pa_family_'")
        build = source.index("Invoke-SimionStage -Stage 'build_accelerator_family'")
        export = source.index("Invoke-SimionStage -Stage 'export_zero_standalone_base'")
        publish = source.index("$failureStage='publish_cache'")
        self.assertLess(private_creation, build)
        self.assertLess(build, export)
        self.assertLess(export, publish)
        self.assertIn("$raw=Join-Path $temporaryFamily 'mrtof_accelerator.pa#'", source)
        self.assertIn("$controller=Join-Path $temporaryFamily 'mrtof_accelerator.pa0'", source)
        self.assertNotIn("Join-Path $solverDir \"mrtof_accelerator.pa$_\"", source)

    def test_runner_limits_heavy_stage_to_the_builder_that_calls_refine(self) -> None:
        source = (PROJECT / "simion/run_accelerator_pa_family.ps1").read_text(
            encoding="utf-8"
        )
        builder = (PROJECT / "simion/build_component_pa.lua").read_text(encoding="utf-8")
        self.assertIn("solved:refine{solutions={0}}", builder)
        self.assertIn("basis:refine{solutions={solution}}", builder)
        self.assertIn(
            "Enter-HostExecutionLease -Role SIMION -Stage accelerator_pa_prepare",
            source,
        )
        self.assertEqual(source.count("-Stage pa_refine"), 2)
        self.assertEqual(source.count("-Stage accelerator_pa_prepare"), 3)
        self.assertIn("-Stage accelerator_pa_postprocess", source)
        self.assertNotIn("-Stage pa_prepare", source)
        builder_call = source.index("Invoke-SimionStage -Stage 'build_accelerator_family'")
        native_gate = source.index("Invoke-SimionStage -Stage 'native_geometry'")
        self.assertLess(source.index("-Stage pa_refine"), builder_call)
        self.assertLess(source.index("-Stage accelerator_pa_prepare", builder_call), native_gate)
        self.assertLess(source.index("-Stage accelerator_pa_postprocess"), source.index("capacity_terminal"))

    def test_runner_can_republish_a_verified_native_family_without_refine(self) -> None:
        source = (PROJECT / "simion/run_accelerator_pa_family.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("[string]$RecoverySourceRunPath=''", source)
        self.assertIn("--require-mode accelerator_pa_family_build", source)
        self.assertIn("Assert-ManifestOutputIdentity -Manifest $recoveryManifest", source)
        self.assertIn("Recovery-source numerical identity differs at $field.", source)
        self.assertIn("Recovery-source refine policy differs at $field.", source)
        self.assertIn("Recovery-source builder identity differs at $field.", source)
        self.assertIn("if(-not$recoverySourceRun){", source)
        self.assertIn("native_family_source=if($recoveryUsed)", source)
        self.assertIn("if($recoverySourceRun){@($recoverySourceRun)}", source)


if __name__ == "__main__":
    unittest.main()
