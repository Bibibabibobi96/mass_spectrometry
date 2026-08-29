from __future__ import annotations

import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
RUNNER = (
    REPO
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
    / "runtime"
    / "run_single_flight.ps1"
)


class DomainSplitRunnerContractTests(unittest.TestCase):
    """Keep the long-gap PA family on its governed, non-superposed path."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = RUNNER.read_text(encoding="utf-8")

    def test_long_gap_has_only_the_registered_buffers_and_coarse_middle_sleeve(self) -> None:
        self.assertIn("function Resolve-RfPositiveGapDomainSplit", self.source)
        self.assertIn("$bufferMm = 10.0", self.source)
        self.assertIn("$minimumSplitGapMm = 50.0", self.source)
        self.assertIn("coarse_sleeve_length_mm=($gapMm - 2.0*$bufferMm)", self.source)
        self.assertIn("fine_domain_overlap_prohibited=$true", self.source)
        self.assertIn("minimum_split_gap_mm=$minimumSplitGapMm", self.source)

    def test_zero_and_short_positive_gaps_remain_on_integrated_path(self) -> None:
        self.assertIn("mode='integrated_frontend'; reason='direct_mating_gap_zero'", self.source)
        self.assertIn(
            "mode='integrated_frontend'; reason='positive_gap_below_split_threshold'",
            self.source,
        )

    def test_long_gap_builds_governed_split_pa_and_iob_path(self) -> None:
        self.assertIn("mode='domain_split'; reason='positive_gap_meets_split_threshold'", self.source)
        self.assertIn("field_superposition_prohibited=$true", self.source)
        self.assertIn("domain_split_runtime_contract.json", self.source)
        self.assertIn("--upstream-bridge-contract", self.source)
        self.assertIn("--accelerator-main-contract", self.source)
        self.assertIn("build_single_flight_domain_split_iob.lua", self.source)
        self.assertIn("coarse_electrode_basis_dirichlet_v1", self.source)

    def test_domain_split_prohibits_monolithic_accelerator_override(self) -> None:
        self.assertIn("if ($domainSplitEnabled)", self.source)
        self.assertIn("OATOF_ACCELERATOR_PA_OVERRIDE", self.source)

    def test_coarse_frontend_keeps_each_refined_basis_for_fine_boundaries(self) -> None:
        self.assertIn("refine_mode='per_basis_lua_explicit_v2'", self.source)
        self.assertIn("initialize_fast_adjust_pa_basis.lua", self.source)
        self.assertIn("refine_single_pa.lua", self.source)
        self.assertIn("foreach ($electrode in 0..$maximumFrontendElectrodeId)", self.source)
        self.assertIn('"frontend.pa{0}" -f $electrode', self.source)
        self.assertNotIn("-ArgumentList @('--nogui','--noprompt','refine',$cachePaSharp)", self.source)

    def test_pa_refinement_uses_simion_official_default_convergence(self) -> None:
        self.assertIn("refinement_convergence='simion_official_default'", self.source)
        self.assertNotIn("'5e-7'", self.source)
        self.assertNotIn("'initialize_fast_adjust_pa_basis.lua','frontend.pa#','1e6'", self.source)
        self.assertNotIn("$cacheBasisInitializer,$cachePaSharp,'1e6'", self.source)

    def test_domain_split_uses_declared_coarse_bridge_grid_only_for_frontend(self) -> None:
        self.assertIn("$executionProfile.coarse_bridge_cell_mm_xyz", self.source)
        self.assertIn("Positive-gap domain split requires a coarse-bridge grid declaration.", self.source)
        self.assertIn("Domain-split coarse frontend PA grid differs from the declared coarse-bridge grid.", self.source)
        self.assertIn("$additionalFrontendGem", self.source)
        self.assertIn("$additionalFrontendContract", self.source)
        self.assertIn("'--partition-cell-mm-x',([string]$frontendCellMmX)", self.source)
        self.assertNotIn("'--partition-cell-mm-x','0.25'", self.source)

    def test_empty_cache_miss_is_not_used_as_a_filesystem_path(self) -> None:
        self.assertIn("if (-not [string]::IsNullOrWhiteSpace($cacheDir))", self.source)
        self.assertIn(
            "if (-not [string]::IsNullOrWhiteSpace($cacheDir) -and @($requiredFrontendBasisFiles",
            self.source,
        )

    def test_intermediate_overlay_materializes_read_only_main_cache_before_boundary_copy(self) -> None:
        self.assertIn("$basisSourceWorkingDirectory = Join-Path $overlayBuildDir 'basis_source'", self.source)
        self.assertIn("-Filter 'accelerator_main.pa*' -File", self.source)
        self.assertIn("Set-RfMaterializedCacheFileWritable -Path $target", self.source)
        self.assertIn("$basisSourceForBuildPa0", self.source)
        self.assertIn("Remove-Item -LiteralPath $basisSourceWorkingDirectory -Recurse -Force", self.source)

    def test_domain_pa_cache_copy_helper_is_defined_before_its_first_use(self) -> None:
        definition = self.source.index("function Copy-RfPaCacheFamilyToRuntime")
        first_domain_copy = self.source.index("foreach ($domainSplitFineBuild in $domainSplitFineBuilds)")
        self.assertLess(definition, first_domain_copy)

    def test_domain_split_aperture_check_uses_the_fine_accelerator_main_pa(self) -> None:
        self.assertIn("Domain-split aperture topology check requires accelerator-main PA.", self.source)
        self.assertIn("$apertureTopologyPa = [string]$domainApertureMain[0].pa0", self.source)
        self.assertIn("$apertureTopologyGeometry.accelerator_port_aperture.discretization", self.source)
        self.assertIn("-PaPath $apertureTopologyPa", self.source)

    def test_domain_split_iob_aliases_coarse_frontend_from_its_materialized_family(self) -> None:
        self.assertIn("[string]$SourceDirectory=$runtimeDir", self.source)
        self.assertIn("-SourceDirectory $frontendWorkingDir", self.source)

    def test_domain_split_program_does_not_require_the_unrelated_entrance_overlay(self) -> None:
        self.assertIn("} elseif ($overlayEnabled -and -not $domainSplitEnabled) {", self.source)

    def test_accelerator_main_uses_the_disjoint_boundary_builder_only_for_that_large_domain(self) -> None:
        self.assertIn("build_accelerator_main_basis_fast.lua", self.source)
        self.assertIn("$fineDefinition.name -eq 'accelerator_main'", self.source)
        self.assertIn("basis_builder_sha256=(Get-FileHash -LiteralPath $fineBasisBuilderSource", self.source)

    def test_accelerator_main_builder_covers_six_faces_without_duplicate_key_tracking(self) -> None:
        builder = RUNNER.with_name("build_accelerator_main_basis_fast.lua").read_text(encoding="utf-8")
        self.assertNotIn("local seen={}", builder)
        self.assertIn("for ix=1,fine.nx-2 do", builder)
        self.assertIn("for iy=1,fine.ny-2 do", builder)
        self.assertIn('"disjoint_six_faces_v1"', builder)
        self.assertIn("duplicate_boundary_writes", builder)

    def test_accelerator_overlay_builder_covers_six_faces_without_duplicate_key_tracking(self) -> None:
        builder = RUNNER.with_name("build_accelerator_overlay_basis.lua").read_text(encoding="utf-8")
        self.assertNotIn("local seen={}", builder)
        self.assertNotIn("ix..':'..iy..':'..iz", builder)
        self.assertIn("for ix=1,fine.nx-2 do", builder)
        self.assertIn("for iy=1,fine.ny-2 do", builder)
        self.assertIn('"disjoint_six_faces_v1"', builder)
        self.assertIn("duplicate_boundary_writes", builder)

    def test_semantically_equivalent_boundary_builder_cache_is_reused(self) -> None:
        self.assertIn("function Resolve-RfSemanticallyEquivalentFineCache", self.source)
        self.assertIn("8236707F574393E796DC4CF0A75C4CA79C13AFD86992C75C0F8199551084B73D", self.source)
        self.assertIn("399BA109A1559BD8BE90E1725BB0A8138435628D5AFD70A6113C1FB0B3ED3C17", self.source)
        self.assertIn("cache_hit_semantically_equivalent_boundary_builder", self.source)
        self.assertIn("$candidateIdentity.inputs.basis_builder_sha256 = $CurrentBuilderSha256", self.source)

    def test_disjoint_face_partition_is_the_same_complete_boundary_as_the_legacy_loops(self) -> None:
        # Small non-cubic dimensions exercise each edge/corner ownership rule.
        nx, ny, nz = 7, 5, 4
        legacy = {
            (ix, iy, iz)
            for iz in range(nz)
            for iy in range(ny)
            for ix in (0, nx - 1)
        }
        legacy |= {
            (ix, iy, iz)
            for iz in range(nz)
            for ix in range(nx)
            for iy in (0, ny - 1)
        }
        legacy |= {
            (ix, iy, iz)
            for iy in range(ny)
            for ix in range(nx)
            for iz in (0, nz - 1)
        }
        disjoint = {
            (ix, iy, iz)
            for iz in range(nz)
            for iy in range(ny)
            for ix in (0, nx - 1)
        }
        disjoint |= {
            (ix, iy, iz)
            for iz in range(nz)
            for ix in range(1, nx - 1)
            for iy in (0, ny - 1)
        }
        disjoint |= {
            (ix, iy, iz)
            for iy in range(1, ny - 1)
            for ix in range(1, nx - 1)
            for iz in (0, nz - 1)
        }
        self.assertEqual(disjoint, legacy)
        self.assertEqual(len(disjoint), 2 * ny * nz + 2 * (nx - 2) * nz + 2 * (nx - 2) * (ny - 2))


if __name__ == "__main__":
    unittest.main()
