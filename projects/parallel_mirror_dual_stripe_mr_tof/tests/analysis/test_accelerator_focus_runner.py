from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    load_contract,
    resolve_trajectory_profile,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_operating_point_variation import (
    OperatingPointVariationError,
    apply_overrides,
    load_operating_point,
    render_operating_point,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.drift_phase_contract import (
    resolve_drift_phase_contract,
)


ROOT = Path(__file__).resolve().parents[4]
PROJECT = ROOT / "projects/parallel_mirror_dual_stripe_mr_tof"
RUNNER = PROJECT / "simion/run_accelerator_focus_flight.ps1"
FOCUS_LUA = PROJECT / "simion/mrtof_accelerator_focus.lua"
BASELINE = PROJECT / "config/simion_candidate_two_zone.json"


class AcceleratorFocusRunnerContractTest(unittest.TestCase):
    def test_resource_stages_separate_light_prepare_flight_and_postprocess(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        prepare = source.index(
            "Enter-HostExecutionLease -Role SIMION -Stage prepare"
        )
        flight = source.index(
            "Update-HostResourceStage -Lease $lease -Stage flight"
        )
        native_flight = source.index("$failureStage='native_accelerator_focus'")
        flight_call = source.index("& $simion '--nogui' '--noprompt' 'lua' $launcher")
        postprocess = source.index(
            "Update-HostResourceStage -Lease $lease -Stage postprocess"
        )
        analysis = source.index("$failureStage='focus_analysis'")
        first_upstream_manifest_read = source.index("$familyManifest=Get-Content")
        self.assertLess(prepare, first_upstream_manifest_read)
        self.assertLess(prepare, native_flight)
        self.assertLess(native_flight, flight)
        self.assertLess(flight, flight_call)
        self.assertLess(flight_call, postprocess)
        self.assertLess(postprocess, analysis)
        self.assertNotIn("-Stage pa_prepare", source)

    def test_large_standalone_pa_copy_uses_bounded_verification_retries(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn(
            "Copy-VerifiedRunInput -Source $Source -Destination $Destination -VerificationAttempts 3",
            source,
        )

    def test_requires_manifest_bound_standalone_sources_and_same_geometry(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("[Parameter(Mandatory)][string]$AcceleratorFamilyRunPath", source)
        self.assertIn("[Parameter(Mandatory)][string]$StandaloneComponentRunPath", source)
        self.assertIn("$standaloneConfig.inputs.global_analyzer_pa", source)
        self.assertIn("$standaloneConfig.inputs.detector_pa", source)
        self.assertIn("$standaloneConfig.inputs.reviewed_geometry_contract", source)
        self.assertIn(
            "Test-RunFilesIdentical -Left $standaloneReviewed -Right (Join-Path $geometrySimion 'simion_prototype_contract.json')",
            source,
        )
        self.assertIn("Assert-ManifestOutputIdentity -Manifest $standaloneManifest", source)
        self.assertIn("require_reviewed_geometry(current,family)", source)
        self.assertNotIn(
            "Test-RunFilesIdentical -Left $familyContract -Right $baselinePath",
            source,
        )

    def test_accelerator_uses_standalone_response_composition_and_cache(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("analysis.simion_standalone_bank", source)
        self.assertIn("native_family_members_opened", source)
        self.assertIn("complete_native_generation_qualified", source)
        self.assertIn("standalone_response_contract", source)
        self.assertIn("standalone_response_filename", source)
        self.assertIn("normalization_receipt_filename", source)
        self.assertIn(
            "$targetVoltages=@(0)+@($trialValue.endpoint_voltages_v)+@($trialValue.ring_voltages_v)",
            source,
        )
        self.assertIn("common\\simion\\compose_standalone_pa.lua", source)
        self.assertIn("New-ShortPaCopy -Source $baseSource", source)
        self.assertIn("linear_basis_operating_pa_group_identity", source)
        self.assertIn("materialize_operating_pa_cache", source)
        self.assertIn("publish_operating_pa_cache", source)
        self.assertIn("read_only_voltageized", source)
        self.assertNotIn("sourceFamilyMembers", source)
        self.assertNotIn("runtimeAcceleratorPa0", source)
        self.assertNotIn("mrtof_accelerator.pa0", source)

    def test_operating_build_is_disposable_and_only_direct_pa_is_retained(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("'simion_operating_pa_'", source)
        self.assertIn(
            "Remove-PrivatePaFamilyDirectory -Path $operatingBuildDir -ExpectedNamePrefix 'simion_operating_pa_'",
            source,
        )
        self.assertIn("$acceleratorPa=Join-Path $solverDir 'iob_input_accelerator.pa'", source)
        self.assertIn(
            "standalone_accelerator_pa=ConvertTo-ArtifactRunPath $acceleratorPa",
            source,
        )

    def test_persistent_receipts_use_canonical_artifact_paths(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("function ConvertTo-ArtifactRunPath", source)
        self.assertIn("operating_iob=ConvertTo-ArtifactRunPath $operatingIob", source)
        self.assertIn(
            "Write-VerifiedRunManifest -Python $python -RepoRoot $repoRoot -RunConfig (ConvertTo-ArtifactRunPath $runConfig)",
            source,
        )

    def test_selected_energy_is_manifest_bound_and_default_drop_comes_from_theory_seed(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("[string]$ExactKRunManifest=''", source)
        self.assertIn("[string]$FixedMirrorStripeRunManifest=''", source)
        self.assertIn("[Nullable[double]]$SelectedNetGainCenterV=$null", source)
        self.assertIn("provide exactly one energy authority", source)
        self.assertIn("--require-mode analytic_mirror_exact_k_operating_point", source)
        self.assertIn("Assert-ManifestOutputIdentity -Manifest $exactKManifest", source)
        self.assertIn("$exactKSummary.selected_operating_point.energy_per_charge_v", source)
        self.assertIn("selected_net_gain_center_source=$selectedEnergySource", source)
        self.assertIn("$config.inputs.exact_k_run_manifest=", source)
        self.assertIn("$config.inputs.exact_k_summary=", source)
        self.assertIn("--require-mode dual_stripe_fixed_grid_native_downstream_seed", source)
        self.assertIn("fixed_mirror_stripe_downstream_authority.json", source)
        self.assertIn("--selected-slow-energy-per-charge-v", source)
        self.assertIn("selected_slow_energy_per_charge_v=$selectedSlowEnergyPerChargeV", source)
        self.assertIn("derive_zero_extraction_energy_focus_seed", source)
        self.assertIn("$theorySeed.first_gap_drop_v", source)
        self.assertIn("first_gap_drop_selection=$firstGapSelection", source)
        self.assertNotIn(
            "$baseline.accelerator.repeller_v-[double]$baseline.accelerator.intermediate_grid_v",
            source,
        )
        self.assertIn("[double]$Finite3dGainCorrectionV=0.0", source)
        self.assertIn("--finite-3d-gain-correction-v", source)
        self.assertIn("finite_3d_gain_correction_v=$Finite3dGainCorrectionV", source)
        self.assertIn(
            "focus-calibration replay and a finite-3D gain correction are mutually exclusive",
            source,
        )

    def test_calibration_proposal_consumes_verified_evidence_without_manual_voltage(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("[string]$FocusCalibrationRunPath=''", source)
        self.assertIn("$FocusCalibrationRunPath -and $null-ne$FirstGapDropV", source)
        self.assertIn("--require-mode two_zone_accelerator_first_time_focus", source)
        self.assertIn("derive_focus_calibration_proposal", source)
        self.assertIn("$calibrationManifest.inputs.trial_contract.path", source)
        self.assertIn("$sourceIdentity.fly2_sha256-ne$calibrationSourceSha", source)
        for field in ("focus_theory", "voltage_trial_builder", "focus_calibration_manifest", "focus_calibration_trial", "focus_calibration_analysis"):
            self.assertIn(f"$config.inputs.{field}=", source)
        self.assertIn("$startupProtected+=$calibrationRun", source)
        self.assertIn("-ProtectedPaths $startupProtected", source)
        self.assertLess(source.index("focus calibration must retain"), source.index("$failureStage='native_accelerator_focus'"))

    def test_energy_calibration_proposal_supplies_the_finite_3d_gain_correction(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        for token in (
            "[string]$EnergyCalibrationRunPath=''",
            "--require-mode accelerator_finite_3d_exit_energy_calibration",
            "accelerator_exit_energy_calibration_proposal.json",
            "Assert-ManifestOutputIdentity -Manifest $energyCalibrationManifest",
            "mrtof_accelerator_finite_3d_energy_correction_proposal",
            "unity_response_first_correction_only__real_simion_exit_required",
            "$proposalTarget-ne$SelectedNetGainCenterV",
            "$Finite3dGainCorrectionV=$proposalCorrection",
            "energy_calibration_run_manifest.json",
            "energy_calibration_proposal.json",
            "$startupProtected+=$energyCalibrationRun",
            "$config.inputs.energy_calibration_manifest=",
            "$config.inputs.energy_calibration_proposal=",
            "verified_accelerator_exit_energy_calibration_proposal",
        ):
            self.assertIn(token, source)
        self.assertIn(
            "energy-calibration evidence and a manual finite-3D gain correction are mutually exclusive",
            source,
        )
        self.assertIn(
            "focus-calibration replay and a finite-3D gain correction are mutually exclusive",
            source,
        )

    def test_operating_point_sidecar_binds_composed_accelerator_voltages(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("simion_operating_point_variation.py", source)
        self.assertIn("drift_phase_contract.py", source)
        self.assertIn("resolve_drift_phase_contract", source)
        self.assertIn("load_operating_point(base_path,phase_contract=", source)
        self.assertIn("phase_contract_source_sha256", source)
        self.assertIn("drift_phase_contract=ConvertTo-ArtifactRunPath", source)
        self.assertIn(
            "apply_overrides,load_operating_point,render_operating_point", source
        )
        self.assertIn(
            'point["accelerator_voltages_v"]=[float(value) for value in trial["endpoint_voltages_v"]]',
            source,
        )
        self.assertIn(
            'point["accelerator_ring_voltages_v"]=[float(value) for value in trial["ring_voltages_v"]]',
            source,
        )
        self.assertIn('point=apply_overrides(point,{"trajectory_quality"', source)
        self.assertIn('"maximum_step_us":profile["maximum_step_us"]', source)
        self.assertIn("nonaccelerator_fields", source)

    def test_trajectory_profile_is_resolved_from_frozen_baseline_and_frozen_in_receipts(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("[string]$TrajectoryProfileId=''", source)
        self.assertIn(
            "contract=json.loads(profile_source_path.read_text",
            source,
        )
        self.assertIn(
            "profile=resolve_trajectory_profile(contract,sys.argv[8] or None)",
            source,
        )
        self.assertIn(
            "$frozenBaseline,$frozenPhaseContract,$TrajectoryProfileId", source
        )
        self.assertIn(
            '"source_contract_sha256":hashlib.sha256(profile_source_path.read_bytes())',
            source,
        )
        for field in (
            "trajectory_profile_id",
            "trajectory_quality",
            "maximum_step_us",
            "trajectory_profile_purpose",
            "trajectory_profile_source_contract_sha256",
        ):
            self.assertIn(f"$config.parameters.{field}", source)

    def test_existing_trajectory_profiles_reach_the_rendered_sidecar_unchanged(self) -> None:
        contract = load_contract(BASELINE)
        phase = resolve_drift_phase_contract(contract)
        base = {
            "mirror_voltages_v": [0.0] * 5,
            "stripe_biases_v": [0.0] * 2,
            "prism_voltages_v": [0.0] * 2,
            "accelerator_voltages_v": [0.0] * 3,
            "accelerator_ring_voltages_v": [0.0] * 5,
            "detector_box_mm": [0.0] * 6,
            "trajectory_quality": 1.0,
            "maximum_step_us": 1.0,
            "full_path_timeout_us": 1.0,
            "nonaccelerator_scale": 1.0,
            "phase_origin_mirror_side": phase.origin_mirror_side,
            "return_mirror_side": phase.return_mirror_side,
            "target_drift_period_ratio": phase.target_period_ratio,
            "target_half_oscillation_count": phase.target_half_oscillation_count,
        }
        self.assertEqual(
            resolve_trajectory_profile(contract)["profile_id"], "center_screening"
        )
        for profile_id in ("center_screening", "center_refined", "center_precision"):
            with self.subTest(profile_id=profile_id):
                profile = resolve_trajectory_profile(contract, profile_id)
                point = apply_overrides(
                    base,
                    {
                        "trajectory_quality": profile["trajectory_quality"],
                        "maximum_step_us": profile["maximum_step_us"],
                    },
                )
                rendered = render_operating_point(point, "0" * 64)
                with self.subTest(field="trajectory_quality"):
                    self.assertIn(
                        f"trajectory_quality = {float(profile['trajectory_quality']):.17g}",
                        rendered,
                    )
                with self.subTest(field="maximum_step_us"):
                    self.assertIn(
                        f"maximum_step_us = {float(profile['maximum_step_us']):.17g}",
                        rendered,
                    )

    def test_unknown_trajectory_profile_fails_closed(self) -> None:
        contract = load_contract(BASELINE)
        with self.assertRaisesRegex(CandidateContractError, "unknown SIMION trajectory profile"):
            resolve_trajectory_profile(contract, "not_a_profile")

    def test_legacy_reviewed_sidecar_requires_explicit_matching_phase_contract(self) -> None:
        phase = {
            "phase_origin_mirror_side": 1.0,
            "return_mirror_side": -1.0,
            "target_drift_period_ratio": 25.5,
            "target_half_oscillation_count": 51.0,
        }
        point = {
            "mirror_voltages_v": [0.0] * 5,
            "stripe_biases_v": [0.0] * 2,
            "prism_voltages_v": [0.0] * 2,
            "accelerator_voltages_v": [0.0] * 3,
            "accelerator_ring_voltages_v": [0.0] * 5,
            "detector_box_mm": [0.0] * 6,
            "trajectory_quality": 1.0,
            "maximum_step_us": 1.0,
            "full_path_timeout_us": 1.0,
            "nonaccelerator_scale": 1.0,
            **phase,
        }
        rendered = render_operating_point(point, "0" * 64)
        legacy = rendered
        for name in phase:
            legacy = re.sub(
                rf"{name}\s*=\s*[^,}}]+,?\s*", "", legacy,
            )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.operating_point.lua"
            path.write_text(legacy, encoding="utf-8")
            with self.assertRaisesRegex(OperatingPointVariationError, "lacks phase_origin"):
                load_operating_point(path)
            migrated = load_operating_point(path, phase_contract=phase)
            for name, value in phase.items():
                self.assertEqual(migrated[name], value)

    def test_focus_lua_requires_composed_standalone_accelerator(self) -> None:
        source = FOCUS_LUA.read_text(encoding="utf-8")
        self.assertIn("#simion.wb.instances == 3", source)
        self.assertIn("iob_input_accelerator%.pa$", source)
        self.assertNotIn("mrtof_accelerator%.pa0", source)

    def test_generated_source_survives_iob_save_under_a_distinct_basename(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        frozen = source.index(
            "$focusFly2Input=Join-Path $inputDir 'accelerator_focus_source.input.fly2'"
        )
        consumed = source.index(
            "$focusFly2=Join-Path $solverDir 'mrtof_three_component_candidate.fly2'"
        )
        builder = source.index("$focusFly2Input)+$origins")
        byte_check = source.index(
            "Test-RunFilesIdentical -Left $focusFly2Input -Right $focusFly2"
        )
        receipt_check = source.index(
            "Get-FileHash -LiteralPath $focusFly2 -Algorithm SHA256"
        )
        flight = source.index("$failureStage='native_accelerator_focus'")
        self.assertNotEqual(frozen, consumed)
        self.assertLess(builder, byte_check)
        self.assertLess(byte_check, receipt_check)
        self.assertLess(receipt_check, flight)
        self.assertIn("frozen_source_fly2=ConvertTo-ArtifactRunPath $focusFly2Input", source)
        self.assertIn("consumed_fly2=ConvertTo-ArtifactRunPath $focusFly2", source)


if __name__ == "__main__":
    unittest.main()
