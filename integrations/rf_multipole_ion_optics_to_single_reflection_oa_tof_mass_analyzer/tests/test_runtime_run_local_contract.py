"""Static regression tests for mandatory run-local integration inputs."""

from __future__ import annotations

from pathlib import Path
import unittest


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_BINDING = INTEGRATION_ROOT / "runtime" / "runtime_binding.ps1"
WORKFLOW_ENTRY = (
    INTEGRATION_ROOT / "workflows" / "family_source_closure" / "execute.ps1"
)
SINGLE_FLIGHT_RUNNER = INTEGRATION_ROOT / "runtime" / "run_single_flight.ps1"
FAMILY_ADAPTER = (
    INTEGRATION_ROOT / "workflows" / "family_source_closure" / "adapter.ps1"
)
RUNNERS = (
    INTEGRATION_ROOT / "runtime" / "run_transfer.ps1",
    INTEGRATION_ROOT / "stages" / "comsol" / "run_pre_pulse_interface_transport.ps1",
    INTEGRATION_ROOT / "stages" / "comsol" / "run_pulse_capture.ps1",
    INTEGRATION_ROOT / "stages" / "cross_solver" / "run_analyzer_transport.ps1",
)


class RuntimeRunLocalContractTests(unittest.TestCase):
    def test_all_runtime_boundaries_require_four_run_local_identities(self) -> None:
        parameters = (
            "ResolvedSourceContract",
            "ResolvedSourceContractSha256",
            "UpstreamResolvedDesign",
            "UpstreamResolvedDesignSha256",
        )
        for path in (RUNTIME_BINDING, *RUNNERS):
            text = path.read_text(encoding="utf-8")
            for parameter in parameters:
                self.assertRegex(
                    text,
                    rf"\[Parameter\(Mandatory\)\]\[string\]\${parameter}\b",
                    (path, parameter),
                )
            self.assertNotIn("SourceContractOverride", text, path)
            self.assertNotIn("UpstreamResolvedDesignOverride", text, path)

    def test_runtime_accepts_only_active_v3_and_fixed_parent_run_files(self) -> None:
        text = RUNTIME_BINDING.read_text(encoding="utf-8")
        self.assertIn("$binding.schema_version -ne 3", text)
        self.assertNotRegex(text, r"sourceContract\.schema_version\s+-eq\s+1")
        self.assertIn("filename = 'resolved_source_contract.json'", text)
        self.assertIn("filename = 'upstream_resolved_design.json'", text)
        self.assertIn("-Root $parentRunRoot", text)
        self.assertIn("contractPaths.resolved_source_contract", text)
        self.assertNotIn("binding.contracts.source_contract", text)
        self.assertNotIn("binding.contracts.upstream_resolved_design", text)

    def test_stage_modes_and_manifest_roles_are_particle_count_neutral(self) -> None:
        joined = "\n".join(path.read_text(encoding="utf-8") for path in RUNNERS)
        for forbidden in (
            "rf_to_oatof_pre_pulse_interface_transport_n100",
            "rf_to_oatof_pulse_capture_n100",
            "rf_to_oatof_analyzer_transport_n100",
        ):
            self.assertNotIn(forbidden, joined)
        for path in RUNNERS[1:]:
            text = path.read_text(encoding="utf-8")
            self.assertIn("resolved_source_contract", text, path)
            self.assertIn("upstream_resolved_design", text, path)

    def test_pulse_capture_uses_run_local_design_not_repository_inventory(self) -> None:
        text = RUNNERS[2].read_text(encoding="utf-8")
        self.assertIn(
            "Copy-Item -LiteralPath $runtime.contracts.upstream_resolved_design "
            "-Destination $rf",
            text.replace("`\n    ", ""),
        )
        self.assertNotIn("'rf_resolved_design'", text)

    def test_validate_cleanup_tolerates_parallel_empty_root_removal(self) -> None:
        self.assertIn(
            "Remove-Item -LiteralPath $validationRoot -Force "
            "-ErrorAction SilentlyContinue",
            WORKFLOW_ENTRY.read_text(encoding="utf-8"),
        )

    def test_pulse_only_candidate_pilot_skips_downstream_pa_rebuilds(self) -> None:
        text = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertEqual(text.count("$SamplingMode -ne 'steady_candidate_pool' -and"), 2)
        self.assertIn("$programArguments += '--terminate-after-pulse'", text)

    def test_overlay_cache_is_staged_and_reuses_the_basis_report(self) -> None:
        text = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertIn("'b-' + [guid]::NewGuid().ToString('N').Substring(0,12)", text)
        self.assertIn("legacy path-length limit", text)
        self.assertIn(
            "$overlayCacheDir = Publish-RfVerifiedCacheEntry",
            text,
        )
        self.assertIn(
            "$overlayCacheBasisReport = Join-Path $overlayCacheDir "
            "'basis_build.json'",
            text,
        )
        self.assertIn(
            "Copy-Item -LiteralPath $overlayCacheBasisReport "
            "-Destination $overlayBasisReport",
            text,
        )
        self.assertNotIn(
            "Copy-Item -LiteralPath $overlayCacheManifest "
            "-Destination $overlayBasisReport",
            text,
        )

    def test_all_four_pa_cache_roles_use_one_verified_contract(self) -> None:
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        artifacts = (INTEGRATION_ROOT / "runtime" / "run_artifacts.ps1").read_text(
            encoding="utf-8"
        )
        for role in (
            "simion_single_flight_frontend_pa_cache",
            "simion_accelerator_overlay_pa_cache",
            "simion_oatof_flight_tube_pa_cache",
            "simion_oatof_reflectron_pa_cache",
        ):
            self.assertIn(role, runner)
        self.assertIn("Get-RfSimionSolverCacheIdentity", runner)
        self.assertIn("Get-RfContentIdentitySha256", runner)
        self.assertIn("executable_sha256", artifacts)
        self.assertIn("product_version", artifacts)
        self.assertIn("Test-RfReusableCacheEntry", artifacts)
        self.assertIn("Publish-RfVerifiedCacheEntry", artifacts)
        self.assertNotIn("requires manual quarantine", runner)
        for input_name in (
            "frontend_pa_cache_manifest",
            "accelerator_overlay_pa_cache_manifest",
            "flight_tube_pa_cache_manifest",
            "reflectron_pa_cache_manifest",
        ):
            self.assertIn(input_name, runner)

    def test_dz0025_profile_keeps_coarse_grid_isotropic_and_refines_only_z(self) -> None:
        import json

        settings = json.loads(
            (INTEGRATION_ROOT / "config" / "simion_single_flight.json").read_text(
                encoding="utf-8"
            )
        )
        profile = next(
            item for item in settings["frontend_grid_profiles"]
            if item["profile_id"] == "frontend_isotropic_020_accelerator_overlay_z0025"
        )
        self.assertEqual(profile["cell_mm_xyz"], {"x": 0.2, "y": 0.2, "z": 0.2})
        self.assertEqual(
            profile["accelerator_overlay"]["cell_mm_xyz"],
            {"x": 0.2, "y": 0.2, "z": 0.025},
        )
        self.assertEqual(
            profile["accelerator_overlay"]["boundary_mode"],
            "coarse_electrode_basis_dirichlet_v1",
        )
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertIn("'transient_disk_estimate'", runner)
        self.assertIn("$frontendCellMmX -ne $frontendCellMmY", runner)
        self.assertIn("$overlayCellMmX -ne $frontendCellMmX", runner)

    def test_resolution_qualification_requires_full_bootstrap(self) -> None:
        text = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("[int]$BootstrapResamples = 0", text)
        self.assertIn("[switch]$ResolutionQualification", text)
        self.assertIn("$BootstrapResamples -ne 5000", text)
        self.assertIn(
            "$populationContract.analysis_randomness.bootstrap_resample_count", text
        )
        self.assertNotIn("'--bootstrap-resamples'", text)
        self.assertIn("[int]$_.resamples_valid -lt 4750", text)
        self.assertIn(
            "[double]$_.relative_95pct_interval_width -gt 0.10", text
        )

    def test_population_contract_is_the_only_release_and_mode_authority(self) -> None:
        runner = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        adapter = FAMILY_ADAPTER.read_text(encoding="utf-8")
        self.assertNotIn("[string]$SourceReleaseMode", runner)
        self.assertNotIn("$runnerArguments.SourceReleaseMode", adapter)
        self.assertIn(
            "$sourceReleaseMode = [string]$populationContract.source_release_mode",
            runner,
        )
        self.assertNotIn("source_release_mode=$sourceReleaseMode", runner)
        self.assertNotIn("source_release_mode=$SourceReleaseMode", runner)
        for mode in (
            "staged_three_stage",
            "continuous_injection_full_population",
            "resolved_layout_pulse_ideal_linear_z_vz",
            "pre_pulse_restart",
            "pulse_eligible_conditional",
            "first_100_rows_in_frozen_file_order",
        ):
            self.assertIn(f"'{mode}'", runner)
        self.assertIn(
            'default { throw "Unsupported resolved population mode:', runner
        )

    def test_paired_n100_field_authority_is_run_local_contract(self) -> None:
        text = SINGLE_FLIGHT_RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("OATOF_IDEAL_ACCEL_STAGE1_ENABLE", text)
        self.assertNotIn("OATOF_IDEAL_ACCEL_STAGE2_ENABLE", text)
        self.assertNotIn("single_flight_ideal_accel_stage1_enable", text)
        self.assertIn("ResolvedRegionFieldContractSha256", text)
        self.assertIn("ResolvedRegionFieldSemanticSha256", text)
        self.assertIn("PulseResolutionBaselineCheckpointsSha256", text)
        self.assertIn("pulse_resolution_real_beam_ideal_stage1_n100_candidate_result.json", text)
        self.assertIn("if ($PulseResolutionArmId -ne 'real_beam_all_real')", text)
        self.assertIn("execution_status=$expectedStatus", text)
        self.assertIn("$PulseResolutionArmId + '_n100_promotion_receipt.json'", text)


if __name__ == "__main__":
    unittest.main()
