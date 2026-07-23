import unittest
from pathlib import Path


RUNNER = Path(__file__).resolve().parent / "run_simion_finite_3d_transport.ps1"
REPO_ROOT = Path(__file__).parents[2]


class SimionRunnerContractTests(unittest.TestCase):
    def test_segmented_voltage_binding_uses_resolved_dynamic_electrodes(self) -> None:
        lua = (RUNNER.parent / "simion_transport.lua").read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("adj_elect[electrode_id] = voltage", lua)
        self.assertIn("electrode_id <= 1000", lua)
        self.assertIn("$design.segmentation.segmented_rod_array", runner)
        self.assertIn("zero_axial_drop_rf_on", runner)
        self.assertNotIn("--segmented-rods", runner)

    def test_build_and_fly_are_serialized_without_nested_reentry(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("Start-Process -FilePath $simion", source)
        self.assertIn("Start-Sleep -Milliseconds 500", source)
        self.assertIn("'--nogui','--noprompt','fly'", source)
        self.assertNotIn("simion_run_fly.lua", source)

    def test_governed_profile_is_the_only_physical_entry(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        for token in ("ProjectId", "DesignProfileId", "ParticleSourcePath"):
            self.assertIn(token, source)
        for legacy in (
            "ProjectRoot",
            "ResolvedDesignPath",
            "ParticleMassAmu",
            "Adapter",
            "FieldScreenRunId",
            "AxialAccelerationContractPath",
            "EntranceConnectorLengthMm",
            "ExitConnectorLengthMm",
            "EndplateAcceleration",
        ):
            self.assertNotIn(legacy, source)
        self.assertIn("common.multipole.design_profile", source)
        self.assertIn("common.multipole.compile_design_request", source)
        self.assertIn("common.multipole.particle_source_preflight", source)

    def test_tool_paths_are_numerical_runtime_parameters(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("[string]$SimionExe", source)
        self.assertIn("[string]$TemplateIob", source)
        self.assertNotIn("C:\\Program Files\\SIMION-2020", source)

    def test_manifest_lifecycle_preserves_partial_outputs(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        support = (
            REPO_ROOT / "common/contracts/run_artifact_support.ps1"
        ).read_text(encoding="utf-8")
        self.assertEqual(source.count("Complete-FailedRun"), 1)
        self.assertIn("Write-VerifiedRunManifest", source)
        self.assertIn("Get-ChildItem -LiteralPath $directory -Recurse -File", support)
        self.assertIn("Write-VerifiedRunManifest", support)
        for output in (
            'simion_summary__$primaryName.json',
            'simion_summary__$controlName.json',
            'particle_states__$primaryName.csv',
            'particle_states__$controlName.csv',
            'trajectory_samples__$primaryName.csv',
            'trajectory_samples__$controlName.csv',
        ):
            self.assertIn(output, source)

    def test_detector_and_handoff_are_exact_resolved_projections(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("$interfaces.exit.connector_z_max_mm", source)
        self.assertIn("$interfaces.exit.particle_plane_z_mm", source)
        self.assertIn("handoff_plane_mm=$handoffPlaneMm", source)
        self.assertIn("detector_is_handoff=false", source)
        self.assertIn("$surfaceToleranceMm=[Math]::Max(1e-6*$CellMm,1e-9)", source)
        self.assertIn("$detectorPlaneMm-2*$CellMm-$surfaceToleranceMm", source)

    def test_raw_and_paired_transmission_cannot_diverge(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn(
            "SIMION paired metrics transmission differs from the raw case summaries.",
            source,
        )

    def test_waveform_and_all_drive_scalars_come_from_resolved_design(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        lua = (RUNNER.parent / "simion_transport.lua").read_text(encoding="utf-8")
        for field in (
            "waveform",
            "rf_amplitude_V_zero_to_peak_per_group",
            "dc_amplitude_V_per_group",
            "common_mode_offset_V",
            "frequency_Hz",
            "phase_rad",
        ):
            self.assertIn(field, source)
        self.assertIn("transport_waveform == 'sine'", lua)
        self.assertIn("transport_waveform == 'cosine'", lua)
        self.assertIn("unsupported RF waveform", lua)

    def test_metrics_are_unqualified_without_explicit_evidence(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("$qualification='UNQUALIFIED'", source)
        self.assertIn("evaluate_transport_evidence", source)
        self.assertIn("analyze_simion_axial_acceleration", source)
        self.assertNotIn("MinimumRfTransmission", source)
        self.assertNotIn("MinimumImprovementOverZeroRf", source)

    def test_validator_output_is_not_returned_as_case_data(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("--output $stateReport|Out-Null", source)
        self.assertIn("return Get-Content -LiteralPath $caseSummary", source)

    def test_reference_comsol_run_is_verified_before_simion(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        for token in (
            "common.contracts.verify_run_manifest",
            "--require-status success",
            "--require-local-run-config",
            "--require-run-id $ReferenceComsolRunId",
            "--require-project $ProjectId",
            "--require-mode resolved_design_transport",
            "--require-design-profile-id $DesignProfileId",
            "--require-parent-resolved-design-sha256 $resolvedHash",
            "--require-particle-source-sha256",
            "reference_comsol_run_manifest.json",
            "reference_comsol_run_manifest_sha256",
            "reference_comsol_source_run_id",
        ):
            self.assertIn(token, source)
        self.assertLess(
            source.index("common.contracts.verify_run_manifest"),
            source.index("Invoke-SimionStep 'gem2pa'"),
        )

    def test_project_wrappers_are_thin_profile_consumers(self) -> None:
        projects = (
            "rf_quadrupole_collision_cooling",
            "rf_hexapole_ion_guide",
            "rf_octupole_ion_guide",
        )
        for project in projects:
            wrapper = (
                REPO_ROOT / "projects" / project / "analysis"
                / "run_simion_finite_3d_transport.ps1"
            ).read_text(encoding="utf-8-sig")
            self.assertIn("DesignProfileId", wrapper)
            self.assertIn("ParticleSourcePath", wrapper)
            self.assertIn("common\\multipole\\run_simion_finite_3d_transport.ps1", wrapper)
            self.assertNotIn("FieldScreenRunId", wrapper)
            self.assertNotIn("AxialAccelerationContractPath", wrapper)


if __name__ == "__main__":
    unittest.main()
