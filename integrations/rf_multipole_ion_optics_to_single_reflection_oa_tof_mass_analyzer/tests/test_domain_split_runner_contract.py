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
ADAPTER = (
    REPO
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
    / "workflows"
    / "family_source_closure"
    / "adapter.ps1"
)


class DomainSplitRunnerContractTests(unittest.TestCase):
    """Keep the long-gap PA family on its governed, non-superposed path."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = RUNNER.read_text(encoding="utf-8")
        cls.adapter_source = ADAPTER.read_text(encoding="utf-8")

    def test_runner_derives_radii_from_frozen_geometry_without_scalar_duplicates(self) -> None:
        self.assertIn("architecture generation identity differs", self.source)
        for parameter in (
            "ExpectedBoreRadiusMm",
            "ExpectedRingOuterRadiusMm",
            "ExpectedShieldInnerRadiusMm",
        ):
            self.assertNotIn(parameter, self.source)
            self.assertNotIn(parameter, self.adapter_source)

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
        self.assertIn("build_single_flight_full_iob.lua", self.source)
        self.assertIn("coarse_electrode_basis_dirichlet_v1", self.source)

    def test_detector_blind_pre_pulse_uses_only_the_reachable_iob_roles(self) -> None:
        self.assertIn("$prePulseEntranceZoneCollision = [bool](", self.source)
        self.assertIn("$sourceReleaseMode -eq 'continuous_frontend'", self.source)
        self.assertIn("$prePulseTerminalHandoffCollision", self.source)
        self.assertIn("$prePulseReachableIob = $prePulseEntranceZoneCollision", self.source)
        self.assertIn("if (-not $prePulseReachableIob) {", self.source)
        self.assertIn("build_single_flight_pre_pulse_iob.lua", self.source)
        self.assertIn("common\\simion\\assets\\iob_instance_seeds", self.source)
        self.assertIn("three_instance_seed.iob", self.source)
        self.assertIn("$prePulseThreeInstanceSeed", self.source)
        self.assertNotIn("examples\\sims", self.source)
        self.assertIn("Versioned three-instance pre-pulse IOB seed", self.source)
        self.assertIn("Compact pre-pulse IOB build failed.", self.source)
        self.assertIn("accelerator_entrance_zone_collision", self.source)
        self.assertIn("'fine_upstream,accelerator_entrance_zone_collision'", self.source)
        self.assertIn("geometry_role='connector_side_repeller_to_first_grid_v1'", self.source)
        self.assertIn("field_mode='zero'; refine=$false", self.source)
        self.assertIn("pre_pulse_iob_omitted_roles", self.source)

    def test_zero_field_entrance_contract_requires_refinement_to_be_prohibited(self) -> None:
        self.assertIn(
            "-not [bool]$entranceZoneGeometry.boundary_condition.direct_refinement_prohibited",
            self.source,
        )

    def test_domain_split_prohibits_monolithic_accelerator_override(self) -> None:
        self.assertIn("if ($domainSplitEnabled)", self.source)
        self.assertIn("OATOF_ACCELERATOR_PA_OVERRIDE", self.source)

    def test_domain_split_axis_field_export_does_not_pass_monolithic_override(self) -> None:
        self.assertIn("$axisFieldEnvironment = @{", self.source)
        self.assertIn("if (-not $domainSplitEnabled) {", self.source)
        self.assertIn(
            "$axisFieldEnvironment.OATOF_ACCELERATOR_PA_OVERRIDE = $frontendWorkingPa0",
            self.source,
        )
        self.assertIn("-Environment $axisFieldEnvironment", self.source)

    def test_main_pa_only_axis_field_gate_uses_a_real_five_slot_container(self) -> None:
        self.assertIn("$domainSplitMainPaOnlyAxisField", self.source)
        self.assertIn("build_single_flight_domain_split_main_only_iob.lua", self.source)
        self.assertIn("mag_quad_2dp.iob", self.source)
        self.assertIn("domain_split_iob_instance_count", self.source)
        self.assertIn("domain_split_iob_omitted_roles", self.source)
        self.assertIn("--domain-split-main-pa-only-axis-field", self.source)
        self.assertIn("-not $domainSplitMainPaOnlyAxisField -and $domainProgramOverlay.Count", self.source)

    def test_coarse_frontend_refines_fast_adjust_template_once_for_fine_boundaries(self) -> None:
        self.assertIn("refine_mode='fast_adjust_template_single_refine_v1'", self.source)
        self.assertIn("initialize_fast_adjust_pa_basis.lua", self.source)
        self.assertIn("SIMION refines every member of a fast-adjust .pa# family", self.source)
        self.assertNotIn("frontend_refine_pa{0}_resource_usage.json", self.source)

    def test_pa_refinement_uses_simion_official_default_convergence(self) -> None:
        self.assertIn("refinement_convergence='simion_official_default'", self.source)
        self.assertNotIn("'5e-7'", self.source)
        self.assertNotIn("'initialize_fast_adjust_pa_basis.lua','frontend.pa#','1e6'", self.source)
        self.assertNotIn("$cacheBasisInitializer,$cachePaSharp,'1e6'", self.source)

    def test_fine_pa_basis_refinement_uses_the_shared_independent_work_scheduler(self) -> None:
        self.assertIn("$fineRefineDispatchRequest", self.source)
        self.assertIn("$fineRefineDispatchPlan", self.source)
        self.assertIn("$fineRefineResourceUsage", self.source)
        self.assertIn("independent_work_items=$true", self.source)
        self.assertIn("Start-ObservedFormalProcess", self.source)
        self.assertIn("Invoke-ResourceBudgetedProcesses", self.source)
        self.assertIn("$fineRefineWave", self.source)

    def test_local_pa_basis_refinement_uses_the_shared_independent_work_scheduler(self) -> None:
        self.assertIn("$localRefineDispatchRequest", self.source)
        self.assertIn("$localRefineDispatchPlan", self.source)
        self.assertIn("$localRefineResourceUsage", self.source)
        self.assertIn("$localRefineWave", self.source)
        self.assertIn("Accelerator entrance-local refinement dispatch plan is invalid.", self.source)

    def test_local_basis_reads_the_immutable_main_generation_through_a_short_junction(self) -> None:
        self.assertIn("function New-RfSimionShortPathJunction", self.source)
        self.assertIn("SIMION 2020 cannot reliably open PA files beyond the legacy MAX_PATH", self.source)
        self.assertIn("-TargetDirectory $mainBuild.cache_dir", self.source)
        self.assertIn("Join-Path $mainSourceJunction 'accelerator_main.pa0'", self.source)
        self.assertIn("Remove-Item -LiteralPath $mainSourceJunction -Force", self.source)

    def test_post_pulse_materializes_only_the_main_and_local_accelerator_families(self) -> None:
        self.assertIn("if (-not $postPulseHandoffMinimal) {", self.source)
        self.assertIn("$domainSplitRuntimeBuilds = if ($postPulseHandoffMinimal)", self.source)
        self.assertIn("@('accelerator_main','accelerator_entrance_local')", self.source)
        self.assertIn("foreach ($domainSplitFineBuild in $domainSplitRuntimeBuilds)", self.source)
        self.assertNotIn(
            "Post-pulse handoff requires an existing shared accelerator-main PA cache",
            self.source,
        )

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

    def test_intermediate_overlay_uses_full_envelope_coarse_frontend_basis(self) -> None:
        self.assertIn("$basisSourcePa0 = $frontendWorkingPa0", self.source)
        self.assertIn("$basisSourceKey = $frontendCacheKey", self.source)
        self.assertIn("$basisSourceOrigin = $frontendGeometry.instance_origin_mm", self.source)
        self.assertIn("full accelerator cross-section", self.source)
        self.assertNotIn("$basisSourceWorkingDirectory = Join-Path $overlayBuildDir 'basis_source'", self.source)
        self.assertNotIn("-Filter 'accelerator_main.pa*' -File", self.source)

    def test_domain_pa_cache_copy_helper_is_defined_before_its_first_use(self) -> None:
        definition = self.source.index("function Copy-RfPaCacheFamilyToRuntime")
        first_domain_copy = self.source.index("foreach ($domainSplitFineBuild in $domainSplitFineBuilds)")
        self.assertLess(definition, first_domain_copy)

    def test_interrupted_compact_reconciliation_is_advisory_but_capacity_is_mandatory(self) -> None:
        reconciliation = self.source.index("reconcile_interrupted_compact_runs")
        capacity_check = self.source.index("Test-RepositoryDiskCapacity")
        self.assertLess(reconciliation, capacity_check)
        reconciliation_block = self.source[reconciliation:capacity_check]
        self.assertIn("try {", reconciliation_block)
        self.assertIn("INTERRUPTED_COMPACT_RECONCILIATION=WARN", reconciliation_block)
        self.assertIn("catch {", reconciliation_block)
        self.assertIn("Artifact capacity gate failed at SIMION startup.", self.source)

    def test_domain_split_aperture_check_uses_the_authoritative_local_or_main_pa(self) -> None:
        self.assertIn("Domain-split aperture topology check requires exactly one authoritative aperture PA.", self.source)
        self.assertIn("{'accelerator_entrance_local'} else {'accelerator_main'}", self.source)
        self.assertIn("$runtimeGeometryPaSuffix", self.source)
        self.assertIn("$domainSplitFineBuild.geometry.pa_plus_solution_model", self.source)
        self.assertIn(") { '.pa#' } else { '.pa0' }", self.source)
        self.assertIn("$apertureTopologyPa = [string]$domainApertureProvider[0].pa0", self.source)
        self.assertIn("$apertureTopologyGeometry.accelerator_port_aperture.discretization", self.source)
        self.assertIn("-PaPath $apertureTopologyPa", self.source)

    def test_shared_main_local_aperture_profile_is_connected_end_to_end(self) -> None:
        self.assertIn("--coarse-bridge-reference-aperture-width-mm", self.source)
        self.assertIn("--accelerator-main-reference-aperture-width-mm", self.source)
        self.assertIn("--accelerator-entrance-local-gem", self.source)
        self.assertIn("accelerator_main_electrode_basis_dirichlet_v1", self.source)
        self.assertIn("replacement_semantics='highest_priority_complete_local_replacement_v1'", self.source)
        self.assertIn("build_single_flight_full_iob.lua", self.source)
        self.assertIn("common\\simion\\assets\\iob_instance_seeds", self.source)
        self.assertIn("five_instance_seed.iob", self.source)
        self.assertIn("seven_instance_seed.iob", self.source)
        self.assertIn("$domainSplitLocalAxisField", self.source)
        self.assertIn("local-axis-field IOB builder", self.source)
        self.assertIn("--domain-split-local-axis-field", self.source)
        self.assertIn("--accelerator-entrance-local-contract", self.source)
        self.assertIn("--accelerator-entrance-local-aperture-width-mm", self.source)
        self.assertIn("$AcceleratorEntranceLocalApertureHeightMm", self.source)
        self.assertIn("$runConfiguration.parameters.accelerator_intermediate2_provider", self.source)
        self.assertIn("if ($domainSplitEnabled) { 'accelerator_main' }", self.source)
        self.assertIn("$postPulseHandoffMinimal", self.source)
        self.assertIn("build_single_flight_post_pulse_iob.lua", self.source)
        self.assertIn("validate_post_pulse_handoff_envelope.py", self.source)
        self.assertIn("Post-pulse handoff states are not covered by the reduced IOB.", self.source)
        self.assertIn("@('coarse_frontend','upstream_bridge')", self.source)
        self.assertIn(
            "requires the entrance-local replacement PA for every field-bearing flight",
            self.source,
        )
        self.assertIn(
            "requires an explicit local replacement aperture", self.source
        )

    def test_domain_split_iob_aliases_coarse_frontend_from_its_materialized_family(self) -> None:
        self.assertIn("[string]$SourceDirectory=$runtimeDir", self.source)
        self.assertIn("-SourceDirectory $frontendWorkingDir", self.source)

    def test_domain_split_program_does_not_require_the_unrelated_entrance_overlay(self) -> None:
        self.assertIn("} elseif ($overlayEnabled -and -not $domainSplitEnabled) {", self.source)

    def test_terminal_handoff_program_uses_raw_connector_contract(self) -> None:
        self.assertIn("$programUpstreamContract = if ($prePulseTerminalHandoffCollision)", self.source)
        self.assertIn("$prePulseConnectorCollisionContract", self.source)
        self.assertIn("'--upstream-bridge-contract',$programUpstreamContract", self.source)

    def test_accelerator_main_uses_the_disjoint_boundary_builder_only_for_that_large_domain(self) -> None:
        self.assertIn("build_accelerator_pa_plus_basis.lua", self.source)
        self.assertIn("$fineDefinition.name -eq 'accelerator_main'", self.source)
        self.assertIn("$fineUsesPaPlus", self.source)
        self.assertIn("$finePaPlusModeSpec", self.source)
        self.assertIn("Test-RfPaPlusModeFamily", self.source)
        self.assertIn("$finePaPlus -or (Test-Path -LiteralPath $finePaPlus", self.source)
        self.assertIn("basis_builder_sha256=(Get-FileHash -LiteralPath $fineBasisBuilderSource", self.source)

    def test_accelerator_main_builder_covers_six_faces_without_duplicate_key_tracking(self) -> None:
        builder = RUNNER.with_name("build_accelerator_main_basis_fast.lua").read_text(encoding="utf-8")
        self.assertNotIn("local seen={}", builder)
        self.assertIn("for ix=1,fine.nx-2 do", builder)
        self.assertIn("for iy=1,fine.ny-2 do", builder)
        self.assertIn('"disjoint_six_faces_v1"', builder)
        self.assertNotIn("boundary_readback", builder)
        self.assertNotIn("potential(ix,iy,iz)", builder)

    def test_accelerator_pa_plus_builder_materializes_only_independent_modes(self) -> None:
        builder = RUNNER.with_name("build_accelerator_pa_plus_basis.lua").read_text(encoding="utf-8")
        self.assertIn("local mode_spec=assert(arg[9]", builder)
        self.assertIn("local source_arrays={}", builder)
        self.assertIn("for _,mode in ipairs(modes) do", builder)
        self.assertIn("if not exists(fine_path) then copy_file(fine_pa_sharp,fine_path) end", builder)
        self.assertNotIn("initializer:refine", builder)
        self.assertNotIn("convergence=", builder)
        self.assertIn("disjoint PA+ boundary traversal", builder)

    def test_pa_plus_boundary_builder_uses_only_disjoint_writes_and_source_projection(self) -> None:
        builder = RUNNER.with_name("build_accelerator_pa_plus_basis.lua").read_text(encoding="utf-8")
        self.assertIn("mode_spec", builder)
        self.assertIn("source:potential_vc", builder)
        self.assertIn("disjoint PA+ boundary traversal", builder)
        self.assertNotIn("fine:potential", builder)

    def test_accelerator_overlay_builder_covers_six_faces_without_duplicate_key_tracking(self) -> None:
        builder = RUNNER.with_name("build_accelerator_overlay_basis.lua").read_text(encoding="utf-8")
        self.assertNotIn("local seen={}", builder)
        self.assertNotIn("ix..':'..iy..':'..iz", builder)
        self.assertIn("for ix=1,fine.nx-2 do", builder)
        self.assertIn("for iy=1,fine.ny-2 do", builder)
        self.assertIn('"disjoint_six_faces_v1"', builder)
        self.assertIn("duplicate_boundary_writes", builder)
        self.assertNotIn("boundary_readback", builder)
        self.assertNotIn("potential(ix,iy,iz)", builder)

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
