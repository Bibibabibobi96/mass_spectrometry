from pathlib import Path
import json
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest


RUNNER = Path(__file__).resolve().parents[2] / "analysis" / "run_native_candidate_chain.ps1"


class NativeCandidateChainRunnerTests(unittest.TestCase):
    def test_diagnostic_source_radius_is_loaded_before_span_assignment(self) -> None:
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 is required for the production assignment regression")
        source = RUNNER.read_text(encoding="utf-8-sig")
        start = source.index("$sourceDefinitionData=Get-Content -LiteralPath $diagnosticSourceDefinition")
        statements = source[start:source.index("$focusContractPath=", start)]
        with TemporaryDirectory() as temporary:
            definition = Path(temporary) / "source.json"
            definition.write_text(json.dumps({"position_radius_mm": 0.375}), encoding="utf-8")
            script = (
                "Set-StrictMode -Version Latest; $ErrorActionPreference='Stop'\n"
                + "$diagnosticSourceDefinition='" + str(definition).replace("'", "''") + "'\n"
                + statements
                + "@{radius=$sourceDefinitionData.position_radius_mm;span=$sourceZSpanMm}|ConvertTo-Json -Compress"
            )
            completed = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-Command", script],
                cwd=RUNNER.parent,
                capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {"radius": 0.375, "span": 0.75})

    def test_chain_reuses_existing_boundaries_in_physical_order(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        stages = [
            "$workpointRunner @arguments",
            "& $sourceRunner",
            "-Stage 'baseline-envelope'",
            "Invoke-Diagnostic -Stage 'baseline-envelope'",
            "-Stage 'baseline'",
            "Invoke-Diagnostic -Stage 'baseline'",
            "--te1-coordinate",
            "-Stage 'te1-probe'",
            "--first-diagnostic",
            "-Stage 'te1-root'",
            "--compare-baseline",
        ]
        main_chain = source[source.index("$failureStage='n1_workpoint'"):]
        positions = [main_chain.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("-GeometryContractPath (Join-Path $workpointRun 'inputs\\contract.json')", source)
        self.assertIn("source_selection='controlled_n13_diagnostic_and_independent_pure_volume_n100'", source)
        self.assertIn("[ValidateSet(3,13,100)][int]$ParticleCount=100", source)
        self.assertNotIn("[Parameter(Mandatory)][string]$Te1ReferencePath", source)
        self.assertIn("--build-te1-reference", source)

    def test_n1_and_common_cohort_share_the_resolved_condition_center(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("$seedManifestPath=$qualifiedCenterSeedManifest", source)
        self.assertNotIn("results\\workpoint_bootstrap.json", source)
        self.assertIn(
            "$sourceYOffsetMm=[double]$providerProjection.required_source_y_offset_from_accelerator_axis_mm",
            source,
        )
        self.assertIn("$sourceDefinitionData.source_y_offset_mm=$sourceYOffsetMm", source)
        self.assertIn("auto_matched_to_current_oa_then_qualified_n1", source)
        self.assertNotIn(
            "Source-definition y offset differs from the current accelerator provider authority",
            source,
        )
        self.assertIn("AcceleratorSourceYOffsetMm=$sourceYOffsetMm", source)
        self.assertIn("inherit_complete_qualified_n1_release_state", source)
        self.assertIn("$n1Source.kinetic_energy_ev", source)
        self.assertIn("$sourceDefinitionData.kinetic_energy_center_ev=$sourceEnergyEv", source)
        self.assertIn("Published diagnostic source does not share the current N=1 centre condition", source)
        self.assertIn("$publishedCenterState=Import-Csv", source)
        self.assertIn("Diagnostic source particle 1 does not inherit the complete qualified N=1 release state", source)

    def test_every_n100_stage_uses_one_static_cohort_without_pulse_pilot(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("[string]$BaselineCohortRunPath=''", source)
        self.assertIn("-ExistingCohortRun $BaselineCohortRunPath", source)
        self.assertNotIn("pilot_run_manifest", source)
        self.assertNotIn("-PilotRun", source)
        self.assertNotIn("mirror_terminal_time_calibration", source)

    def test_baseline_collection_hard_stop_finishes_before_te1(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        gate = "if([bool]$baselineCollectionGate.hard_stop-or-not[bool]$baselineCollectionGate.continue_downstream)"
        self.assertIn(gate, source)
        gate_position = source.index(gate)
        self.assertGreater(gate_position, source.index("Invoke-Diagnostic -Stage 'baseline'"))
        self.assertLess(gate_position, source.index("$failureStage='te1_probe'"))
        block = source[source.index("function Complete-BaselineCollectionHardStop"):
                       source.index("try{\n  $failureStage='capacity_startup'")]
        for token in (
            "warning_collection_below_hard_minimum__continue_parameter_scan",
            "baseline_diagnostic=$baselineDiagnostic",
            "prism_observation=$baselineCenterGate.observation",
            "z0_focus_classification=$baselineZ0Classification",
            "baseline=$baselineCollectionGate",
            "baseline=$baselineCenterGate",
            "detector_plane_focus",
        ):
            self.assertIn(token, block)
        self.assertIn("Complete-BaselineCollectionHardStop -Baseline $baseline", source)

    def test_resume_can_reuse_one_verified_common_source_receipt(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("[string]$PublishedSourceReceiptPath=''", source)
        self.assertIn("if($PublishedSourceReceiptPath)", source)
        self.assertIn("-Mode deterministic_bunch_source_materialization", source)
        self.assertIn("& $sourceRunner", source)

    def test_chain_owns_one_lightweight_capacity_lifecycle(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("-CapacityLedgerLifecycleEnabled", source)
        self.assertIn("Enter-ArtifactWorkflowCapacitySession", source)
        self.assertIn("Update-ArtifactWorkflowCapacitySession", source)
        self.assertIn("Exit-ArtifactWorkflowCapacitySession", source)

    def test_child_run_ids_are_derived_before_the_revision_suffix(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("function New-StageRunId", source)
        self.assertIn("$revision=if($RunId-match'__r(?<retry>\\d{2})$')", source)
        self.assertNotIn("$RunId+'__'+$Stage", source)
        self.assertNotIn("$RunId+'__n1-workpoint'", source)

    def test_completed_te1_stages_can_resume_without_reflight(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("[string]$BaselineEnvelopeScreeningRunPath=''", source)
        self.assertIn(
            "Read-ScreeningEvidence -RunPath $BaselineEnvelopeScreeningRunPath -Scope envelope",
            source,
        )
        self.assertIn("[string]$ProbeScreeningRunPath=''", source)
        self.assertIn("[string]$RootScreeningRunPath=''", source)
        self.assertIn("[string[]]$RootScreeningRunPaths=@()", source)
        self.assertIn(
            "$completedRootScreeningRuns=@(if($RootScreeningRunPaths.Count)",
            source,
        )
        self.assertIn("if($ProbeScreeningRunPath)", source)
        self.assertIn("if($rootAttempt-le$completedRootScreeningRuns.Count)", source)
        self.assertIn("$completedRootScreeningRuns[$rootAttempt-1]", source)
        self.assertIn("$rootAttempt-le$MaximumTe1RootFlights", source)
        self.assertIn("[string]$ReclosedRootScreeningRunPath=''", source)
        self.assertIn("[string]$FinalScreeningRunPath=''", source)
        self.assertIn("Read-ScreeningEvidence -RunPath $ReclosedRootScreeningRunPath -Scope envelope", source)
        self.assertIn("Read-ScreeningEvidence -RunPath $FinalScreeningRunPath -Scope formal", source)
        self.assertIn("& $screeningRunner @arguments|Out-Host", source)
        self.assertIn("& $diagnosticRunner -FlightRunPath $flightRun -RunId $childId -PythonExe $python|Out-Host", source)

    def test_reused_screening_is_bound_to_complete_workpoint_and_field(self) -> None:
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 is required for the production binding regression")
        source = RUNNER.read_text(encoding="utf-8-sig")
        helpers = source[
            source.index("function Test-SameResolvedPath"):
            source.index("function Read-ScreeningEvidence")
        ]

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {name: root / name for name in (
                "geometry", "mirror", "stripe", "provider", "bank", "source",
                "workpoint", "cohort", "other_provider", "other_bank",
            )}
            for path in paths.values():
                path.mkdir(parents=True)
                (path / "run_manifest.json").write_text("{}", encoding="utf-8")
            for path in (paths["provider"], paths["other_provider"], paths["source"]):
                (path / "results").mkdir()
            provider_receipt = paths["provider"] / "results" / "receipt.json"
            provider_receipt.write_text("{}", encoding="utf-8")
            other_provider_receipt = paths["other_provider"] / "results" / "receipt.json"
            other_provider_receipt.write_text("{}", encoding="utf-8")
            source_receipt = paths["source"] / "results" / "receipt.json"
            source_receipt.write_text("{}", encoding="utf-8")

            (paths["mirror"] / "results").mkdir()
            (paths["mirror"] / "results" / "fixed_grid_voltage_point.json").write_text(
                json.dumps({"mirror_voltages_v": [0, 1, 2, 3, 4]}), encoding="utf-8"
            )
            (paths["workpoint"] / "inputs").mkdir()
            (paths["workpoint"] / "results").mkdir()
            contract = paths["workpoint"] / "inputs" / "contract.json"
            contract.write_text('{"contract":"same"}', encoding="utf-8")
            bundle = root / "bundle.json"
            bundle.write_text('{"field":"same"}', encoding="utf-8")
            variation = root / "variation.json"
            variation.write_text(
                json.dumps({"coordinate": 1.0, "target_mirror_voltages_v": [10, 11, 12, 13, 14]}),
                encoding="utf-8",
            )
            workpoint_config = {
                "inputs": {"terminal_time_mirror_voltage_variation": str(variation)},
                "parameters": {"native_recovery_problem": {
                    "geometry": str(paths["geometry"]),
                    "mirror": str(paths["mirror"]),
                    "stripe": str(paths["stripe"]),
                    "accelerator_provider_receipt": str(provider_receipt),
                    "native_system_runtime_bundle": str(bundle),
                    "contract_sha256": "unused",
                }},
            }
            (paths["workpoint"] / "run_config.json").write_text(
                json.dumps(workpoint_config), encoding="utf-8"
            )
            (paths["workpoint"] / "results" / "best_physical_workpoint_handoff.json").write_text(
                json.dumps({"selected_workpoint": {"voltages_v": [-27, 54, 191, -190]}}),
                encoding="utf-8",
            )
            (paths["cohort"] / "simion").mkdir()
            cohort_contract = paths["cohort"] / "simion" / "contract.json"
            cohort_contract.write_text(contract.read_text(encoding="utf-8"), encoding="utf-8")
            cohort_variation = paths["cohort"] / "simion" / "variation.json"
            cohort_variation.write_text(variation.read_text(encoding="utf-8"), encoding="utf-8")
            cohort_bundle = paths["cohort"] / "simion" / "bundle.json"
            cohort_bundle.write_text(bundle.read_text(encoding="utf-8"), encoding="utf-8")
            cohort_config = {
                "inputs": {
                    "bunch_source_run_manifest": str(paths["source"] / "run_manifest.json"),
                    "geometry_run_manifest": str(paths["bank"] / "run_manifest.json"),
                    "mirror_run_manifest": str(paths["mirror"] / "run_manifest.json"),
                    "stripe_run_manifest": str(paths["stripe"] / "run_manifest.json"),
                    "accelerator_run_manifest": str(paths["provider"] / "run_manifest.json"),
                    "native_system_runtime_bundle": str(cohort_bundle),
                    "trajectory_contract": str(cohort_contract),
                    "terminal_time_mirror_voltage_variation": str(cohort_variation),
                }
            }
            cohort_config_path = paths["cohort"] / "run_config.json"
            cohort_config_path.write_text(json.dumps(cohort_config), encoding="utf-8")
            summary_path = paths["cohort"] / "summary.json"
            summary_path.write_text(
                json.dumps({"stripe_biases_v": [-27, 54], "prism_voltages_v": [191, -190]}),
                encoding="utf-8",
            )

            def invoke(function: str) -> subprocess.CompletedProcess[str]:
                script = (
                    "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)\n"
                    "Set-StrictMode -Version Latest; $ErrorActionPreference='Stop'\n"
                    + helpers
                    + function
                )
                return subprocess.run(
                    [shell, "-NoProfile", "-NonInteractive", "-Command", script],
                    cwd=RUNNER.parent,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    timeout=30, check=False,
                )

            quoted = lambda path: str(path).replace("'", "''")
            screening_call = (
                f"Assert-ScreeningEvidenceBinding -CohortRun '{quoted(paths['cohort'])}' "
                f"-ExpectedWorkpointRun '{quoted(paths['workpoint'])}' "
                f"-ExpectedSourceReceipt '{quoted(source_receipt)}' "
                f"-ExpectedNativeBankRun '{quoted(paths['bank'])}' "
                f"-ExpectedVariation '{quoted(variation)}'"
            )
            self.assertEqual(invoke(screening_call).returncode, 0)

            matching_workpoint_call = (
                f"Assert-WorkpointPhysicalBinding -WorkpointRun '{quoted(paths['workpoint'])}' "
                f"-ExpectedGeometryRun '{quoted(paths['geometry'])}' "
                f"-ExpectedMirrorRun '{quoted(paths['mirror'])}' "
                f"-ExpectedStripeRun '{quoted(paths['stripe'])}' "
                f"-ExpectedProviderReceipt '{quoted(provider_receipt)}' "
                f"-ExpectedRuntimeBundle '{quoted(bundle)}'"
            )
            self.assertEqual(invoke(matching_workpoint_call).returncode, 0)

            summary_path.write_text(
                json.dumps({"stripe_biases_v": [-28, 54], "prism_voltages_v": [191, -190]}),
                encoding="utf-8",
            )
            different_ps = invoke(screening_call)
            self.assertNotEqual(different_ps.returncode, 0)
            self.assertIn("different P/S workpoint voltages", different_ps.stdout)

            summary_path.write_text(
                json.dumps({"stripe_biases_v": [-27, 54], "prism_voltages_v": [191, -190]}),
                encoding="utf-8",
            )
            cohort_config["inputs"]["geometry_run_manifest"] = str(
                paths["other_bank"] / "run_manifest.json"
            )
            cohort_config_path.write_text(json.dumps(cohort_config), encoding="utf-8")
            different_field = invoke(screening_call)
            self.assertNotEqual(different_field.returncode, 0)
            self.assertIn("different native field bank", different_field.stdout)

            cohort_config["inputs"]["geometry_run_manifest"] = str(
                paths["bank"] / "run_manifest.json"
            )
            workpoint_config["inputs"].pop("terminal_time_mirror_voltage_variation")
            (paths["workpoint"] / "run_config.json").write_text(
                json.dumps(workpoint_config), encoding="utf-8"
            )
            cohort_config["inputs"].pop("terminal_time_mirror_voltage_variation")
            fixed_authority = paths["cohort"] / "simion" / "fixed_authority.json"
            fixed_authority.write_text(
                json.dumps({"mirror_voltages_v": [0, 1, 2, 3, 4]}), encoding="utf-8"
            )
            cohort_config["inputs"]["fixed_mirror_stripe_downstream_authority"] = str(
                fixed_authority
            )
            cohort_config_path.write_text(json.dumps(cohort_config), encoding="utf-8")
            baseline_call = (
                f"Assert-ScreeningEvidenceBinding -CohortRun '{quoted(paths['cohort'])}' "
                f"-ExpectedWorkpointRun '{quoted(paths['workpoint'])}' "
                f"-ExpectedSourceReceipt '{quoted(source_receipt)}' "
                f"-ExpectedNativeBankRun '{quoted(paths['bank'])}'"
            )
            baseline = invoke(baseline_call)
            self.assertEqual(baseline.returncode, 0, baseline.stdout)

            workpoint_call = (
                f"Assert-WorkpointPhysicalBinding -WorkpointRun '{quoted(paths['workpoint'])}' "
                f"-ExpectedGeometryRun '{quoted(paths['geometry'])}' "
                f"-ExpectedMirrorRun '{quoted(paths['mirror'])}' "
                f"-ExpectedStripeRun '{quoted(paths['stripe'])}' "
                f"-ExpectedProviderReceipt '{quoted(other_provider_receipt)}' "
                f"-ExpectedRuntimeBundle '{quoted(bundle)}'"
            )
            different_provider = invoke(workpoint_call)
            self.assertNotEqual(different_provider.returncode, 0)
            self.assertIn("different accelerator provider authority", different_provider.stdout)

    def test_completed_te1_center_reclosure_can_resume_without_repeating_n1(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("[string]$CompletedTe1WorkpointReclosureRunPath=''", source)
        self.assertIn("function Read-CompletedTe1WorkpointReclosure", source)
        self.assertIn(
            "Completed TE1 workpoint reclosure belongs to different mirror voltages.",
            source,
        )
        self.assertIn("$centerMaterialization.mirror_voltages_v", source)
        self.assertIn("$centerMaterialization.terminal_time_mirror_variation.coordinate", source)
        self.assertNotIn("mirror_voltage_variation_sha256\n  if", source)
        self.assertIn(
            "Read-CompletedTe1WorkpointReclosure -RunPath $CompletedTe1WorkpointReclosureRunPath",
            source,
        )
        self.assertIn("$CompletedTe1WorkpointReclosureRunPath,$ReclosedRootScreeningRunPath,$FinalScreeningRunPath", source)
        self.assertIn("$PublishedSourceReceiptPath,$PublishedFormalSourceReceiptPath,$NativeCorridorBankRunPath", source)

    def test_te1_root_is_verified_and_refined_automatically(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("[ValidateRange(1,3)][int]$MaximumTe1RootFlights=3", source)
        self.assertIn("for($rootAttempt=1;$rootAttempt-le$MaximumTe1RootFlights;$rootAttempt++)", source)
        self.assertIn("$focusTolerance=$sample.median_tof_us/(2.0*$minimumMassResolution*$sourceZSpanMm)", source)
        self.assertIn("if($focusConverged){break}", source)
        self.assertIn("warning_focus_not_converged__continue_parameter_scan", source)
        self.assertIn("warning_resolution_below_target__continue_parameter_scan", source)
        self.assertIn("warning_collection_below_preferred__continue_parameter_scan", source)
        self.assertIn("Read-CollectionGate -ScreeningResult $focused.result", source)
        self.assertEqual(
            source.count("$focusConverged=$responseConverged-and[bool]$candidateCenterGate.passed-and$candidateEnvelopeAvailable"),
            2,
        )
        self.assertEqual(
            source.count("$focusConverged=$responseConverged-and[bool]$candidateCenterGate.passed"),
            3,
        )
        self.assertNotIn(
            "$focusConverged=$responseConverged-and[bool]$candidateCenterGate.passed-and$candidateCollectionSatisfied",
            source,
        )
        self.assertIn("if($candidateCenterGate.passed-and$candidateEnvelopeAvailable-and", source)
        self.assertNotIn("$remeasureCollectionGate=Read-CollectionGate", source)
        self.assertIn("Read-CenterWorkpointGate -ScreeningResult $focused.result", source)
        self.assertIn("warning_center_workpoint_shifted__reclose_required", source)
        self.assertIn("TE1 detector-plane root variation is invalid", source)
        self.assertNotIn("warning_te1_root_outside_mirror_gate__continue_parameter_scan", source)
        self.assertIn("workpoint_profile.jacobian_relative_step_tiers.fine", source)
        self.assertIn("--mirror-correction", source)
        self.assertNotIn("TE1 detector-plane focus did not converge", source)
        focus_reader = source[source.index("function Read-DetectorFocusSample"):
                              source.index("$package=New-RunPackage")]
        self.assertIn("$value.controlled_detector_focus", focus_reader)
        self.assertIn("$controlled.status-eq'unavailable'", focus_reader)
        self.assertIn("available=$false", focus_reader)
        self.assertIn("$controlled.dt_d_initial_z_us_per_mm", focus_reader)
        self.assertNotIn("initial_z_association.slope", focus_reader)

    def test_final_collection_acceptance_requires_the_accepted_gate_state(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        helper = source[
            source.index("function Test-CollectionAccepted"):
            source.index("function Read-CenterWorkpointGate")
        ]
        for token in (
            "$Gate.status-eq'accepted'",
            "-not[bool]$Gate.warning",
            "[double]$Gate.detection_rate-ge[double]$Gate.preferred_minimum",
        ):
            self.assertIn(token, helper)
        self.assertEqual(source.count("Test-CollectionAccepted -Gate"), 1)
        self.assertIn(
            "if([bool]$baselineCollectionGate.hard_stop-or-not[bool]$baselineCollectionGate.continue_downstream)",
            source,
        )

    def test_legacy_workpoint_contract_gets_only_the_current_step_tiers(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("$workpointProfile.ContainsKey('jacobian_relative_step_tiers')", source)
        self.assertIn(
            "$workpointProfile.jacobian_relative_step_tiers=$currentTiers",
            source,
        )
        self.assertIn("$focusContractPath=Join-Path $package.input_dir 'focus_contract.json'", source)
        self.assertIn("'--contract',$focusContractPath", source)

    def test_te1_recloses_center_only_after_a_failed_n100_center_gate(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("[ValidateRange(0,2)][int]$MaximumTe1WorkpointReclosures=2", source)
        gate = source.index("if(-not$candidateCenterGate.passed)")
        reclose = source.index("Invoke-Te1WorkpointReclosure -Attempt", gate)
        self.assertGreater(reclose, gate)
        self.assertIn("SeedTrialManifest=$SeedManifest;MirrorVoltageVariationPath=$Variation", source)
        self.assertIn("ContractPath=$CurrentContractPath", source)
        self.assertIn("-CurrentContractPath $focusContractPath", source)
        self.assertIn("$focusContractPath=Join-Path $workpointRun 'inputs\\contract.json'", source)
        self.assertIn("$focusContract=Get-Content -LiteralPath $focusContractPath", source)
        self.assertIn("Get-QualifiedCenterSeedManifest -WorkpointRun $workpointRun", source)
        self.assertIn("$Handoff.selected_workpoint.voltages_v", source)
        self.assertIn("@($value.stripe_biases_v)+@($value.prism_voltages_v)", source)
        self.assertIn("warning_center_workpoint_reclosure_exhausted__continue_parameter_scan", source)

    def test_te1_reclosure_reuses_the_condition_native_runtime(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("[string]$NativeRuntimeCheckpoint=''", source)
        self.assertIn("function Get-ManifestOutputPath", source)
        self.assertIn("Manifest must bind exactly one $FileName output", source)
        helper = source[
            source.index("function Invoke-Te1WorkpointReclosure"):
            source.index("function Read-CompletedTe1WorkpointReclosure")
        ]
        self.assertIn("[Parameter(Mandatory)][string]$RuntimeCheckpoint", helper)
        self.assertIn("NativeRuntimeCheckpoint=$RuntimeCheckpoint", helper)
        self.assertIn("-RuntimeCheckpoint $activeNativeRuntimeCheckpoint", source)
        self.assertIn(
            "$activeNativeRuntimeCheckpoint=Get-ManifestOutputPath -ManifestPath $workpointManifest",
            source,
        )

    def test_direct_n1_bootstrap_receives_an_existing_runtime_checkpoint(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        n1 = source[source.index("$failureStage='n1_workpoint'"):source.index("$workpointManifest=Assert-Manifest")]
        self.assertIn(
            "if($NativeRuntimeCheckpoint){$arguments.NativeRuntimeCheckpoint=$NativeRuntimeCheckpoint}",
            n1,
        )

    def test_te1_remeasures_focus_response_after_center_reclosure(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        reclose = source.index("Invoke-Te1WorkpointReclosure -Attempt")
        reflight = source.index("-Stage ('te1-reclosed-root-{0:D2}'", reclose)
        remeasure = source.index("-Stage ('te1-reclosed-response-{0:D2}'", reflight)
        next_root = source.index("continue", remeasure)
        self.assertLess(reclose, reflight)
        self.assertLess(reflight, remeasure)
        self.assertLess(remeasure, next_root)
        self.assertIn("$focusCoordinates.Clear();$focusDiagnostics.Clear()", source)
        remeasure_block = source[remeasure:next_root]
        self.assertIn("-ParticleCount 3 -FocusDiagnosticOnly", remeasure_block)
        self.assertIn("$responseReclosed=Invoke-Te1WorkpointReclosure", remeasure_block)
        self.assertIn("response_point=$true", remeasure_block)
        self.assertIn("te1-reclosed-response-reclosed-", remeasure_block)
        self.assertIn("converged=$false;focus_probe_only=$true", remeasure_block)
        self.assertNotIn("Read-CollectionGate", remeasure_block)
        self.assertNotIn("$focused=$remeasured", remeasure_block)
        self.assertIn("$bestFocused=$focused", source)
        self.assertIn("if(-not$focusConverged-and$null-ne$bestFocused)", source)
        self.assertIn("$bestWorkpointRun=$workpointRun;$bestWorkpointManifest=$workpointManifest", source)
        self.assertIn("$bestNativeRuntimeCheckpoint=$activeNativeRuntimeCheckpoint", source)
        self.assertIn("$workpointRun=$bestWorkpointRun;$workpointManifest=$bestWorkpointManifest", source)
        self.assertIn("$activeNativeRuntimeCheckpoint=$bestNativeRuntimeCheckpoint", source)
        reclosure_switch = source.index("$workpointRun=$reclosed.run;$workpointManifest=$reclosed.manifest")
        reset_best = source.index("$bestFocused=$null;$bestRootDiagnostic='';$bestRootFocusDiagnostic=''", reclosure_switch)
        reclosed_screening = source.index("$focused=if($reclosureCount-eq1-and$ReclosedRootScreeningRunPath)", reset_best)
        self.assertLess(reclosure_switch, reset_best)
        self.assertLess(reset_best, reclosed_screening)

    def test_missing_controlled_pair_is_a_condition_warning_not_a_failed_run(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("function Complete-FocusResponseUnavailable", source)
        self.assertIn("warning_focus_response_unavailable__continue_parameter_scan", source)
        self.assertIn("if(-not$baselineFocusSample.available)", source)
        self.assertIn("if(-not$probeFocusSample.available)", source)
        self.assertIn("if(-not$sample.available)", source)
        self.assertIn("if(-not$remeasureSample.available)", source)

    def test_controlled_focus_pair_uses_bounded_three_particle_fallback(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        helper = source[source.index("function Resolve-DetectorFocusSample"):
                        source.index("function Invoke-Diagnostic")]
        self.assertIn("if([bool]$FormalSample.available)", helper)
        self.assertIn("half_span_percent=20;particle_count=[int]$FormalSample.particle_count", helper)
        self.assertIn("foreach($percent in @(10,5))", helper)
        self.assertIn("-ParticleCount 3 -FocusDiagnosticOnly", helper)
        self.assertIn("minimum_5_percent_pair_did_not_both_reach_detector__condition_unsuitable_for_te1_focus", helper)
        self.assertNotIn("foreach($percent in @(10,5,", helper)
        self.assertIn("--baseline-focus-diagnostic", source)
        self.assertIn("formal_diagnostic=$rootDiagnostic", source)

    def test_te1_response_probe_uses_only_the_controlled_three_particle_pair(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        probe = source[source.index("$failureStage='te1_probe'"):
                       source.index("$failureStage='te1_continuous_root'")]
        self.assertIn(
            "-Variation $probeVariation -ParticleCount 3 -FocusDiagnosticOnly",
            probe,
        )

    def test_root_envelope_selection_precedes_one_formal_n100(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        root_loop = source[
            source.index("for($rootAttempt=1;"):
            source.index("$failureStage='te1_final_n100'")
        ]
        final = source[
            source.index("$failureStage='te1_final_n100'"):
            source.index("$failureStage='compare'")
        ]
        self.assertEqual(root_loop.count("-ParticleCount 13 -DiagnosticPurpose controlled_aberration"), 3)
        self.assertNotIn("Test-CollectionAccepted -Gate", root_loop)
        self.assertIn("evidence_scope=[string]$focused.evidence_scope", root_loop)
        self.assertIn("envelope_available=($particleCount-in@(13,100))", source)
        self.assertIn("te1_coordinate=$te1Coordinate;variation_path=$variationPath", source)
        self.assertIn("$focusCoordinates.Add($baselineCoordinate);$focusCoordinates.Add($probeCoordinate)", source)
        self.assertIn("$remeasureCoordinate=$rootCoordinate+$probeStepCoordinate", source)
        self.assertIn("--baseline-coordinate',[string]$baselineCoordinate", source)
        self.assertIn("Final screening evidence belongs to a different TE1 coordinate.", source)
        self.assertIn("'focus_only_n3'", source)
        self.assertEqual(final.count("Invoke-Screening -Stage 'te1-final'"), 1)
        self.assertIn("Read-ScreeningEvidence -RunPath $FinalScreeningRunPath -Scope formal", final)
        self.assertIn("selected_envelope_screening=[ordered]@{", source)
        self.assertIn("root_screening_run_manifest=$(if($null-ne$focused)", source)

    def test_z0_is_classified_without_becoming_a_resolution_precondition(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("function Read-Z0FocusClassification", source)
        self.assertIn("topology_or_upstream_loss", source)
        self.assertIn("first_order_broadening_enter_te1", source)
        self.assertIn("higher_order_or_phase_space_warning", source)
        self.assertIn("downstream_detector_leg_contribution", source)
        self.assertIn("diagnostic_classification_only__not_a_te1_precondition", source)
        self.assertNotIn("z0_mass_resolution_satisfied", source)


if __name__ == "__main__":
    unittest.main()
