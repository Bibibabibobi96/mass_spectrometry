"""Native and static-field contract tests for the MR-TOF flight runner."""
from pathlib import Path
import json
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

RUNNER = Path(__file__).resolve().parents[2] / "simion" / "run_two_prism_trial.ps1"

class TwoPrismTrialRunnerTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_preflight_checkpoint_refresh_only_after_formal_observation(self):
        source = RUNNER.read_text(encoding="utf-8-sig")
        start = source.index("    $finalBatchPlan=Get-Content")
        block = source[start:source.index(
            "    if($pendingSpecs.Count-eq0-and$existingRecords.Count-eq0){", start)]
        initial = {"inputs": {"simion_execution_batch_plan": "frozen-plan.json"},
                   "parameters": {"unchanged": "frozen source and field"}}
        cases = (
            ("exact", None, [1, 2], [1, 2], initial, False, [1, 2], 0),
            ("formal_index_zero", 0, [0, 1, 2], [0, 1, 2], initial, False, [1, 2], 1),
            ("continuation_replay", None, [1, 2], [2], initial, False, [2], 0),
            ("empty", None, [], [], None, False, [], 0),
            ("missing_inputs", 0, [0, 1], [0, 1], {}, False, None, 0),
            ("write_failure", 0, [0, 1], [0, 1], initial, True, None, 1),
        )
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for label, formal, indices, replay, config, write_failure, pending, writes in cases:
                with self.subTest(case=label):
                    run_config, batch_plan = root / "run_config.json", root / "batch_plan.json"
                    if run_config.exists():
                        run_config.unlink()
                    if config is not None:
                        run_config.write_text(json.dumps(config), encoding="utf-8")
                    before = run_config.read_bytes() if run_config.exists() else None
                    batch_plan.write_text(json.dumps({"batches": [{"index": i} for i in indices]}),
                                          encoding="utf-8")
                    formal_value = "$null" if formal is None else str(formal)
                    script = (
                        "$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;"
                        f"$runConfig={quote(run_config)};$batchPlanPath={quote(batch_plan)};"
                        f"$runDir={quote(root)};$formalBatchIndex={formal_value};"
                        f"$replayBatchIndexes=@({','.join(map(str, replay))});"
                        "$batchRecords=@{};"
                        f"foreach($index in @({','.join(map(str, indices))}))"
                        "{$batchRecords[[int]$index]=@{index=[int]$index}};"
                        "$checkpointOutputs=@('initial-output.json');$python='unused';$repoRoot='unused';"
                        "$script:writes=0;$script:manifests=0;"
                        "function Write-RunJson {param($Path,$Value) $script:writes++;"
                        + ("throw 'WRITE_FAILURE';" if write_failure else
                           "$Value|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $Path;")
                        + "};function Write-VerifiedRunManifest {param($Python,$RepoRoot,$RunConfig,"
                        "$Manifest,$Status,$Software,$Outputs) $script:manifests++;"
                        "if($Status-ne'checkpoint'-or$Outputs[0]-ne'initial-output.json'){throw 'identity changed'}};"
                        "function Get-MrtofBatchProcessSpecification {param($Record) $Record.index};"
                        "try {\n" + block + "\n} catch {"
                        "@{error=$_.Exception.Message;writes=$script:writes;manifests=$script:manifests}"
                        "|ConvertTo-Json -Compress;exit 1};"
                        "@{writes=$script:writes;manifests=$script:manifests;pending=@($pendingSpecs)}"
                        "|ConvertTo-Json -Compress"
                    )
                    result = subprocess.run(
                        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                        cwd=RUNNER.parents[3], capture_output=True, text=True, encoding="utf-8", timeout=30,
                    )
                    actual = json.loads(result.stdout.splitlines()[-1])
                    self.assertEqual(actual["writes"], writes)
                    if pending is None:
                        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertEqual(actual["manifests"], 0)
                        if write_failure:
                            self.assertEqual(actual["error"], "WRITE_FAILURE")
                    else:
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertEqual(actual["manifests"], writes)
                        self.assertEqual(actual["pending"], pending)
                        if formal is not None:
                            expected = {**initial, "inputs": {"simion_execution_batch_plan": str(batch_plan)}}
                            self.assertEqual(json.loads(run_config.read_text(encoding="utf-8-sig")), expected)
                        else:
                            self.assertEqual(run_config.read_bytes() if run_config.exists() else None, before)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_static_pose_reuses_validated_origins_without_geometry_resolution(self):
        source = RUNNER.read_text(encoding="utf-8-sig")
        start = source.index("  $posePath=Join-Path $resultDir 'resolved_iob_pose.json'")
        block = source[start:source.index("  # The native-system bundle", start)]
        origins = {"analyzer": [0, -242, -425], "accelerator": [0, -72.25, -6],
                   "detector": [-10, -20, -30]}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            contract, plan = root/'contract.json', root/'plan.json'
            contract.write_text(json.dumps({"simion": {"component_mesh_mm_per_gu": {
                "analyzer": 1, "detector": .5}}}), encoding="utf-8")
            plan.write_text(json.dumps({"numerical_domain": {"mesh_mm_per_gu": .25}}), encoding="utf-8")
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            for static, mode in ((True, 'native_static_pa'), (True, 'comsol_static_scalar_v'),
                                 (False, 'native_static_pa')):
                with self.subTest(static=static, mode=mode):
                    binding = {"instances": [{"origin_mm": origins['analyzer']}, {},
                        {"origin_mm": origins['accelerator']}, {"origin_mm": origins['detector']}]}
                    expected = {"origins_mm": origins, "mesh_mm_per_gu": {
                        "analyzer": 1, "accelerator": .25, "detector": .5},
                        "analyzer_geometry_authority": mode+'_frozen_resolved_geometry' if static else 'reviewed_analyzer_contract',
                        "accelerator_geometry_authority": 'oa_provider_plan__mr_configurable_clearance_gated_y_pose',
                        "detector_return_policy_authority": 'current_trajectory_contract'}
                    script = (
                        "$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;"
                        f"$staticFieldRequested=${str(static).lower()};$staticFieldMode={quote(mode)};"
                        f"$resultDir={quote(root)};$trajectoryContract={quote(contract)};"
                        f"$acceleratorProviderPlanLocal={quote(plan)};$reviewed='unused';$acceleratorLocal='unused';"
                        f"$staticFieldBinding={quote(json.dumps(binding))}|ConvertFrom-Json -Depth 100;"
                        f"$expected={quote(json.dumps(expected))}|ConvertFrom-Json -Depth 100;$script:calls=0;"
                        "function Write-RunJson {param($Path,$Depth,$Value) $Value|ConvertTo-Json -Depth 100|Set-Content -LiteralPath $Path};"
                        "function Invoke-ProjectPython {param($Arguments) $script:calls++;"
                        "Write-RunJson -Path $posePath -Depth 100 -Value $expected};\n"
                        + block + "\n@{calls=$script:calls;pose=$pose}|ConvertTo-Json -Depth 100 -Compress"
                    )
                    completed = subprocess.run(["pwsh", "-NoProfile", "-Command", script],
                        cwd=RUNNER.parents[3], capture_output=True, text=True, encoding="utf-8", timeout=30)
                    self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
                    actual = json.loads(completed.stdout.splitlines()[-1])
                    self.assertEqual(actual['pose'], expected)
                    self.assertEqual(actual['calls'], 0 if static else 1)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_final_config_preserves_native_nested_geometry_and_stopping_identity(self):
        numerics = {"solver": "SIMION2020", "refine_stopping": "contract_convergence",
                    "convergence_v": 1e-5, "surface": "fractional", "boundary_mode": "grounded_enclosure"}
        window = {"native_solver_numerics": {**numerics, "boundary_mode": "x_mirror_five_faces"},
                  "authority": {"assembly": {"accelerator_resolved_electrodes": {
                      "grid_supports": [{"aperture_box_mm": {"x_min_mm": -21, "x_max_mm": 21},
                                         "ideal_sheet_mm": {"z_mm": 30}}]}}},
                  "geometry": {"prism_electrodes": [{"parts": [{
                      "polygon_yz_mm": [[0, 1], [2, 3]], "x": [0, 1]}]}]}}
        value = {"inputs": {"static_field_dependencies": {
                    "native_solver_numerics": numerics, "refinement_windows": [window]}},
                 "provenance": {"upstream_manifest_verification": {"static_field": {"windows": [window]}}}}
        publication = next(line.strip() for line in RUNNER.read_text(encoding="utf-8-sig").splitlines()
                           if line.strip().startswith("Write-RunJson -Path $runConfig -Value $config"))
        writer = RUNNER.parents[3] / "common/contracts/run_artifact_support.ps1"
        with TemporaryDirectory() as directory:
            source, target = Path(directory) / "input.json", Path(directory) / "run_config.json"
            source.write_text(json.dumps(value), encoding="utf-8")
            quote = lambda path: "'" + str(path).replace("'", "''") + "'"
            command = (f". {quote(writer)}\n"
                       f"$config=Get-Content -Raw -LiteralPath {quote(source)}|ConvertFrom-Json -Depth 100\n"
                       f"$runConfig={quote(target)}\n{publication}")
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], cwd=RUNNER.parent,
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8-sig")), value)
            self.assertNotIn("truncated", result.stdout.lower())

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_standard_source_diagnostic_is_one_postprocess_output(self):
        source = RUNNER.read_text(encoding="utf-8-sig")
        start = source.index("  $sourceTimingDiagnostic=$null;")
        end = source.index("  $retention=Apply-RunArtifactRetention", start)
        block = source[start:end]
        self.assertGreater(start, source.rindex("Write-RunJson -Path $runConfig -Value $config", 0, start))
        self.assertLess(end, source.rindex("Write-VerifiedRunManifest"))
        publication = next(line for line in source.splitlines()
                           if line.strip().startswith("if($null-ne$sourceTimingDiagnostic){$manifestOutputs"))
        with TemporaryDirectory() as directory:
            for bunch, count, safe_exit, subset, minimum_id, expected in (
                (True, 13, False, False, 1, 1), (False, 1, False, False, 1, 0),
                (True, 13, True, False, 1, 0), (True, 12, False, True, 2, 0),
                (True, 100, False, True, 1, 1), (True, 1, False, True, 1, 0),
            ):
                with self.subTest(bunch=bunch, count=count, safe_exit=safe_exit, subset=subset, minimum_id=minimum_id):
                    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
                    script = (
                        "$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;"
                        + f"$resultDir={quote(directory)};$logDir=$resultDir;"
                        + f"$isBunchFlight=${str(bunch).lower()};$isSafeExitOnly=${str(safe_exit).lower()};"
                        + f"$bunchSelectionRequested=${str(subset).lower()};"
                        + f"$BunchParticleIdMin={minimum_id};$trial=@{{source_particle_count={count}}};"
                        + "$runConfig='final-config.json';$observation='observation.json';"
                        + "$batchMergeReceipt='merge.json';$global:calls=0;$global:received=@();"
                        + "function Invoke-ProjectPython {param($Arguments) $global:calls++;"
                        + "$global:received=$Arguments}\n"
                        + block + "\n$manifestOutputs=@('observation.json');" + publication
                        + "\n@{calls=$global:calls;args=$global:received;outputs=$manifestOutputs;"
                        + "log_exists=($null-ne$sourceTimingDiagnosticLog-and(Test-Path -LiteralPath $sourceTimingDiagnosticLog));"
                        + "log_text=$(if($null-ne$sourceTimingDiagnosticLog-and(Test-Path -LiteralPath $sourceTimingDiagnosticLog)){"
                        + "Get-Content -LiteralPath $sourceTimingDiagnosticLog -Raw}else{''})}|ConvertTo-Json -Compress"
                    )
                    completed = subprocess.run(
                        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                        cwd=RUNNER.parents[3], capture_output=True, text=True,
                        encoding="utf-8", timeout=30,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    result = json.loads(completed.stdout.splitlines()[-1])
                    self.assertEqual(result["calls"], expected)
                    self.assertEqual(len(result["outputs"]), 3 if expected else 1)
                    self.assertEqual(result["log_exists"], bool(expected))
                    if expected:
                        self.assertIn("SOURCE_Z_ENERGY_TIMING_DIAGNOSTIC=PASS", result["log_text"])
                        self.assertIn("--completed-run-config", result["args"])
                        self.assertIn("final-config.json", result["args"])
                        self.assertIn("--batch-merge-receipt", result["args"])
                        self.assertNotIn("--run-dir", result["args"])

    @classmethod
    def setUpClass(cls):
        cls.source = RUNNER.read_text(encoding="utf-8")

    def test_requires_native_bank_and_system_bundle(self):
        selection = self.source.split("if($staticFieldRequested){", 1)[1].split(
            "$nativeCorridorRun=", 1,
        )[0]
        static, native = selection.split("}else{", 1)
        self.assertIn("analysis.static_field_binding", static)
        self.assertIn("Static field binding cannot consume a native adjustable runtime.", static)
        self.assertNotIn("IsNullOrWhiteSpace($NativeCorridorBankRunPath)", static)
        self.assertIn("IsNullOrWhiteSpace($NativeCorridorBankRunPath)", native)
        self.assertIn("NativeCorridorBankRunPath is required for a native flight.", native)
        self.assertIn("NativeCorridorBankRunPath requires NativeSystemRuntimeBundlePath.", native)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_summary_preserves_nested_phase_space_acceptance_objects(self):
        acceptance = {
            "status": "evaluated__center_particle_only",
            "absolute_tolerance_per_charge_v": 0.05,
            "reference_provider_tolerance_per_charge_v": None,
            "within_tolerance": False,
        }
        value = {"cohort_analysis": {"prism_phase_space_diagnostic": {"surfaces": {
            "accelerator_safe_exit": {"kinetic_energy_per_charge": {
                "component_target_diagnostic": {"components": {
                    "Ex": {"acceptance": acceptance},
                    "Ey": {"acceptance": {**acceptance, "within_tolerance": True}},
                }}
            }}
        }}}}
        publication = next(
            line.strip() for line in self.source.splitlines()
            if line.strip().startswith("Write-RunJson -Path $summary ")
        )
        writer = RUNNER.parents[3] / "common/contracts/run_artifact_support.ps1"
        with TemporaryDirectory() as directory:
            source = Path(directory) / "input.json"
            target = Path(directory) / "summary.json"
            source.write_text(json.dumps(value), encoding="utf-8")
            quote = lambda path: "'" + str(path).replace("'", "''") + "'"
            command = (
                f". {quote(writer)}\n"
                f"$summaryValue=Get-Content -Raw -LiteralPath {quote(source)}|ConvertFrom-Json\n"
                f"$summary={quote(target)}\n{publication}"
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command],
                cwd=RUNNER.parent,
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8-sig")), value)

    def test_no_legacy_five_region_public_inputs_remain(self):
        for name in ("LocalWorkbenchRunPath", "LocalResponseFamilyRunPath",
                     "LocalRegionOverrideWorkbenchRunPath", "LocalRegionOverrideRegions",
                     "LocalHandoffSelectionRunPath", "RuntimeCentralStripeResponse",
                     "BootstrapGlobalOperatingPa", "localWorkbenchRun",
                     "useNativeCorridor", "hybridFixedResponseScreening",
                     "localOperatingCacheReceipt", "batchTemplateRecord"):
            self.assertNotIn(name, self.source)
        self.assertNotIn("basisLinkDir", self.source)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_all_step_scale_boundaries_allow_coarser_finite_positive_values(self):
        project = RUNNER.parents[1]
        for path, variable, guard in (
            (RUNNER, "TrajectoryStepScale", "if([double]::IsNaN($TrajectoryStepScale)"),
            (project / "analysis/run_native_candidate_chain.ps1", "TrajectoryStepScaleOverride",
             "if($null-ne$TrajectoryStepScaleOverride-and("),
            (project / "analysis/run_native_corridor_bunch_screening.ps1", "trajectoryStepScale",
             "if($null-ne$trajectoryStepScale-and("),
        ):
            source = path.read_text(encoding="utf-8-sig")
            start = source.index(guard)
            # The validator is either a one-line guard or the existing three-line guard.
            end = source.index("}", start) + 1
            validator = source[start:end]
            for expression, valid in (("1", True), ("2", True), ("4", True),
                                      ("0", False), ("-1", False),
                                      ("[double]::NaN", False), ("[double]::PositiveInfinity", False)):
                script = ("$ErrorActionPreference='Stop';$" + variable + "=" + expression + ";"
                          + validator + ";'accepted'")
                completed = subprocess.run(
                    ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                    cwd=project.parents[1], capture_output=True, text=True, encoding="utf-8", timeout=30,
                )
                self.assertEqual(completed.returncode == 0, valid, completed.stdout + completed.stderr)

    def test_native_runtime_preserves_four_instance_and_bundle_identity(self):
        for token in ("build_native_corridor_iob.lua", "4_instance_seed.iob",
                      "native_system_runtime", "NativeCorridorRuntimeSession",
                      "native_corridor_private_fast_adjust_family"):
            self.assertIn(token, self.source)
        self.assertIn("$privateIobSeed=Join-Path $temporarySolverDir '4_instance_seed.iob'", self.source)
        self.assertIn("foreach($seedIndex in 2..4)", self.source)
        self.assertIn("New-Item -ItemType HardLink", self.source)
        self.assertNotIn("Get-FileHash -LiteralPath $privateSeedPlaceholder", self.source)
        self.assertIn("$nativeControllerForIob=[IO.Path]::GetFullPath([string]$nativeRuntime.receipt.controller_path)", self.source)
        self.assertIn("$privateIobSeed,$iobAnalyzerInput,$nativeControllerForIob", self.source)

    def test_standalone_n1_can_open_one_existing_native_checkpoint(self):
        self.assertIn("[string]$NativeRuntimeCheckpoint=''", self.source)
        self.assertIn(
            "Supply NativeCorridorRuntimeSession or NativeRuntimeCheckpoint, not both.",
            self.source,
        )
        self.assertIn("directory=[IO.Path]::GetFullPath([string]$checkpoint.directory)", self.source)
        self.assertIn("checkpoint_path=$nativeRuntimeCheckpointPath", self.source)

    def test_checkpoint_is_opened_before_capacity_peak_is_computed(self):
        opened = self.source.index("Open-NativeCorridorRuntimeCheckpoint")
        peak = self.source.index("$nativeFamilyPeakBytes=10*")
        self.assertLess(opened, peak)
        self.assertIn("$NativeCorridorRuntimeSession.resident_bytes-gt0", self.source)

    def test_global_fallback_identity_is_reused_without_an_extra_full_hash(self):
        self.assertIn(
            "$voltageSourceHash=[string]$globalFallbackRecord.sha256", self.source
        )
        self.assertNotIn(
            "Get-FileHash -LiteralPath $globalFallbackAnalyzer", self.source
        )

    def test_shared_runtime_retains_small_gui_workbench_under_compact_policy(self):
        for token in (
            "[switch]$RetainGuiWorkbench",
            "$trajectoryRetentionClass=if($null-eq$trajectoryRecording){'compact'}",
            "$retainGuiWorkbenchFiles=($null-ne$NativeCorridorRuntimeSession)-or($staticFieldRequested-and$RetainGuiWorkbench)",
            "Join-Path $artifactSolverDir 'gui_workbench'",
            "Retained GUI workbench native checkpoint controller is missing.",
            "PA payloads have already been bound through the runtime and published",
            "pa_dependencies=$guiPaDependencies",
            "Get-ChildItem -LiteralPath $temporarySolverDir -File -Filter 'trj*.tmp'",
        ):
            self.assertIn(token, self.source)
        # Prepared replay retains explicit trajectory observations; ordinary
        # OA GUI retention must continue to use the compact default instead.
        oa_execution = self.source.split("\nforeach($value in @($Prism1VoltageV,$Prism2VoltageV))", 1)[1]
        self.assertNotIn("-RetentionClass solver_review", oa_execution)
        self.assertIn("-RetentionClass $trajectoryRetentionClass -RetentionReason $trajectoryRetentionReason", oa_execution)
        prepared = self.source.split("function Invoke-PreparedJointTrial {", 1)[1].split(
            "\nif($PSCmdlet.ParameterSetName-eq'PreparedJoint'){", 1)[0]
        self.assertIn("if($null-eq$recording){throw 'Prepared joint flight requires retained trajectory observations.'}", prepared)
        self.assertIn("-RetentionClass solver_review -RetentionReason $recording.reason", prepared)
        self.assertIn("if($retainGuiWorkbenchFiles){", self.source)
        self.assertNotIn("Join-Path $temporarySolverDir 'pa_inputs'", self.source)
        self.assertNotIn("simion_pa_links_", self.source)
        self.assertNotIn("iobInputCopyDir", self.source)
        self.assertIn("$privateIobSeed,", self.source)
        self.assertIn(
            "if(-not$staticFieldRequested-and$RetainGuiWorkbench-and$null-eq$NativeCorridorRuntimeSession)",
            self.source,
        )
        self.assertIn(
            "standalone retention would duplicate the complete PA family",
            self.source,
        )

    def test_retained_gui_rebinds_shared_runtime_to_persistent_checkpoint(self):
        self.assertIn(
            "Join-Path ([string]$NativeCorridorRuntimeSession.directory) 'mrtof_analyzer_corridor.pa0'",
            self.source,
        )
        self.assertIn("-Stage 'rebind_retained_gui_iob'", self.source)
        self.assertIn("$nativeRuntime.controller_path=$stableNativeController", self.source)
        self.assertIn(
            "$privateIobSeed,$globalFallbackAnalyzer,$guiNativeController,$persistentAcceleratorController,$sourceDetector",
            self.source,
        )
        self.assertIn("persistent_controller_path", self.source)
        self.assertIn("$iobAcceleratorInput=$persistentAcceleratorController", self.source)
        self.assertIn("private_accelerator_controller_pa=$persistentAcceleratorController", self.source)
        accelerator_block = self.source.split("$failureStage='prepare_accelerator_runtime_family'", 1)[1].split(
            "$nativeOrigins=", 1,
        )[0]
        self.assertNotIn("New-NativeFastAdjustRuntimeFamily", accelerator_block)
        self.assertNotIn("Remove-ShortPaCopy -Path $projectedPa", self.source)
        self.assertIn(
            "Remove-IobSeedPlaceholderCompanions -Directory $temporarySolverDir -Count 4",
            self.source,
        )
        self.assertNotIn(
            "shared runtime sessions are not portable GUI dependencies", self.source
        )
        self.assertNotIn(
            "Get-ChildItem -LiteralPath $temporarySolverDir -Recurse -File", self.source
        )

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_gui_retention_condition_covers_native_and_static_modes(self):
        assignment = next(
            line for line in self.source.splitlines()
            if line.startswith("$retainGuiWorkbenchFiles=")
        )
        command = (
            "foreach($native in @($false,$true)){foreach($staticFieldRequested in @($false,$true)){"
            "foreach($RetainGuiWorkbench in @($false,$true)){"
            "$NativeCorridorRuntimeSession=if($native){[pscustomobject]@{}}else{$null};"
            + assignment
            + ";[int]$retainGuiWorkbenchFiles}}}"
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", command],
            cwd=RUNNER.parents[3], capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([int(value) for value in result.stdout.split()], [0, 0, 0, 1, 1, 1, 1, 1])

    def test_bunch_batches_use_official_shared_iob_particle_override(self):
        self.assertIn("official_shared_iob__per_process_particles_override", self.source)
        self.assertIn("$batchIob=$temporaryIob", self.source)
        self.assertIn("$Record.iob,$Record.source_fly2", self.source)
        self.assertNotIn("build_native_batch_iob_", self.source)
        self.assertNotIn("batch_iob_bundle_portability_receipt", self.source)
        self.assertNotIn("batchPaCopyDirectories", self.source)
        self.assertIn("shared_native_corridor_runtime__four_instances__no_refine", self.source)
        self.assertNotIn("build_local_refinement_iob.lua", self.source)
        self.assertNotIn("build_three_component_iob.lua", self.source)

    def test_dispatch_identity_reuses_verified_component_and_bank_receipts(self):
        self.assertIn(
            "frontend_pa0_sha256=$(if($staticFieldRequested){[string]$staticFieldBinding.records.scalar_pa.sha256}else{[string]$nativeBankCache.generation_sha256})",
            self.source,
        )
        self.assertIn("accelerator_overlay_generation_sha256=[string]$providerAccelerator.pa_family.generation_sha256", self.source)
        self.assertIn("reflectron_pa0_sha256=[string]$nativeSystemRuntimeRecords['detector'].sha256", self.source)
        self.assertNotIn("Get-FileHash -LiteralPath $sourceAccelerator", self.source)
        self.assertNotIn("Get-FileHash -LiteralPath $sourceDetector", self.source)

    def test_static_pa_assets_are_guarded_once_and_not_materialized_per_trial(self):
        self.assertIn("$requiredBytes+=$nativeFamilyPeakBytes", self.source)
        self.assertNotIn("iobProjectionBytes", self.source)
        self.assertIn(
            "Protect-ImmutablePaSource -Source $globalFallbackAnalyzer", self.source
        )
        self.assertIn("Protect-ImmutablePaSource -Source $sourceDetector", self.source)
        self.assertIn("$iobAnalyzerInput=$globalFallbackAnalyzer", self.source)
        self.assertIn("$iobDetectorInput=$sourceDetector", self.source)
        self.assertNotIn("function Copy-IobPaInput", self.source)
        self.assertNotIn("New-ShortPaCopy -Source $sourceDetector", self.source)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_static_capacity_protects_response_layers_and_keeps_plain_default(self):
        start = self.source.index("  $protectedPaths=@($package.artifact_run_dir,$nativeCorridorRun,$nativeBankGeneration)")
        end = self.source.index("  $capacitySession=$sessionUpdate.session", start)
        block = self.source[start:end]
        base = {"export_manifest": "base/manifest.json", "collision_geometry": "collision/geometry.json",
                "sources": {"scalar_pa": "base/v.pa", "valid_pa": "base/mask.pa"},
                "instances": [{"pa_path": "collision/collision.pa", "manifest": "collision/manifest.json"}],
                "refinement_windows": [{"export_manifest": "base/window/manifest.json",
                                        "sources": {"scalar_pa": "base/window/v.pa", "valid_pa": "base/window/mask.pa"}}]}
        ordinary = {"run", "binding.json", "collision/geometry.json", "collision/collision.pa",
                    "collision/manifest.json", "base/manifest.json", "base/v.pa", "base/mask.pa",
                    "base/window/manifest.json", "base/window/v.pa", "base/window/mask.pa"}
        with TemporaryDirectory() as directory:
            for combined in (False, True, "native", "native_no_surface"):
                with self.subTest(combined=combined):
                    binding = json.loads(json.dumps(base))
                    expected = set(ordinary)
                    mode = "comsol_static_scalar_v"
                    if combined in ("native", "native_no_surface"):
                        mode = "native_static_pa"
                        binding = {"mode": mode, "manifest": "base/manifest.json",
                                   "sources": {"scalar_pa": "base/v.pa", "surface": "base/v.pa-surf"},
                                   "instances": base["instances"],
                                   "refinement_windows": [{"manifest": "base/window/manifest.json",
                                       "sources": {"scalar_pa": "base/window/v.pa",
                                                   "surface": "base/window/v.pa-surf"}}]}
                        expected = {"run", "binding.json", "collision/collision.pa", "collision/manifest.json",
                                    "base/manifest.json", "base/v.pa", "base/v.pa-surf",
                                    "base/window/manifest.json", "base/window/v.pa", "base/window/v.pa-surf"}
                        if combined == "native_no_surface":
                            binding["sources"]["surface"] = None
                            binding["refinement_windows"][0]["sources"]["surface"] = None
                            expected -= {"base/v.pa-surf", "base/window/v.pa-surf"}
                    if combined is True:
                        binding["response_terms"] = []
                        for name in ("baseline", "s1", "s2"):
                            component = {"export_manifest": f"{name}/manifest.json",
                                         "sources": {"scalar_pa": f"{name}/v.pa", "valid_pa": f"{name}/mask.pa"},
                                         "refinement_windows": [{"export_manifest": f"{name}/local/manifest.json",
                                                                 "sources": {"scalar_pa": f"{name}/local/v.pa", "valid_pa": f"{name}/local/mask.pa"}}]}
                            binding["response_terms"].append({"coefficient": 0. if name == "s2" else 1.,
                                                              "binding_path": f"{name}/binding.json", "binding": component})
                            expected.update({f"{name}/binding.json", component["export_manifest"],
                                             *component["sources"].values(),
                                             component["refinement_windows"][0]["export_manifest"],
                                             *component["refinement_windows"][0]["sources"].values()})
                    path = Path(directory) / "binding.json"
                    path.write_text(json.dumps(binding), encoding="utf-8")
                    quoted = "'" + str(path).replace("'", "''") + "'"
                    command = (
                        "$ErrorActionPreference='Stop';Set-StrictMode -Version Latest\n"
                        f"$staticFieldMode='{mode}';$staticFieldRequested=$true;$package=@{{artifact_run_dir='run'}};"
                        "$FieldBindingPath='binding.json';$nativeCorridorRun=$null;$nativeBankGeneration=$null;"
                        "$nativeBankKey=$null;$requiredBytes=0;$ownsCapacitySession=$false;$trajectoryRecording=$null;"
                        "$capacitySession=[pscustomobject]@{committed_new_bytes=0};$python='mock';$repoRoot='repo'\n"
                        f"$staticFieldBinding=Get-Content -LiteralPath {quoted} -Raw|ConvertFrom-Json -Depth 100\n"
                        "function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$ProtectedPaths,$ProtectedCacheKeys,$RemainingCommittedNewBytes)"
                        " [Console]::WriteLine((@{paths=@($ProtectedPaths);keys=@($ProtectedCacheKeys)}|ConvertTo-Json -Compress));"
                        " return @{session=$Session}}\n" + block
                    )
                    result = subprocess.run(["pwsh", "-NoProfile", "-Command", command],
                                            cwd=RUNNER.parent, capture_output=True, text=True,
                                            encoding="utf-8", errors="replace", timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    actual = json.loads(result.stdout)
                    self.assertEqual(set(actual["paths"]), expected)
                    self.assertEqual(actual["keys"], [])

    def test_first_batch_observation_keeps_repository_scheduler_contract(self):
        self.assertIn("Start-ObservedFormalProcess -DispatchPlanPath", self.source)
        self.assertNotIn("WaitForNaturalCompletionAfterObservation", self.source)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_native_static_guards_gui_and_provenance_need_no_comsol_export(self):
        guard_start = self.source.index("    $guardPaths=@($staticFieldBinding.instances")
        guard = self.source[guard_start:self.source.index("    foreach($path in", guard_start)]
        gui_start = self.source.index("      $guiPaDependencies=@($staticFieldBinding.instances")
        gui = self.source[gui_start:self.source.index("      $guiWorkbenchOutputs+=", gui_start)]
        provenance_start = self.source.index("  if($staticFieldRequested){\n    if($staticFieldMode-eq'native_static_pa')")
        provenance = self.source[provenance_start:self.source.index("  $config.parameters.prism_1_voltage_v=", provenance_start)]
        binding = {"manifest": "native/manifest.json", "sources": {
            "scalar_pa": "native/v.pa", "surface": "native/v.pa-surf", "geometry_authority": "native/geometry.json"},
            "records": {"scalar_pa": {"path": "native/v.pa"}, "surface": {"path": "native/v.pa-surf"}},
            "instances": [{"pa_path": f"collision/{i}.pa", "manifest": f"collision/{i}/manifest.json"} for i in range(4)],
            "refinement_windows": [{"manifest": "local/manifest.json", "sources": {
                "scalar_pa": "local/v.pa", "surface": "local/v.pa-surf"},
                "records": {"scalar_pa": {"path": "local/v.pa"}, "surface": {"path": "local/v.pa-surf"}}}]}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "binding.json"
            path.write_text(json.dumps(binding), encoding="utf-8")
            quote = "'" + str(path).replace("'", "''") + "'"
            command = ("$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;"
                       "$staticFieldRequested=$true;$staticFieldMode='native_static_pa';"
                       "$config=@{provenance=@{upstream_manifest_verification=@{native_system_runtime='old'}}};"
                       f"$staticFieldBinding=Get-Content -Raw -LiteralPath {quote}|ConvertFrom-Json -Depth 100\n"
                       + guard + gui + provenance +
                       "@{guard=@($guardPaths);gui=@($guiPaDependencies);provenance=$config.provenance}|ConvertTo-Json -Depth 30 -Compress")
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], cwd=RUNNER.parent,
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(set(value["guard"]), {*(f"collision/{i}.pa" for i in range(4)),
                "native/v.pa", "native/v.pa-surf", "local/v.pa", "local/v.pa-surf"})
            self.assertEqual(len(value["gui"]), 8)
            upstream = value["provenance"]["upstream_manifest_verification"]
            self.assertNotIn("native_system_runtime", upstream)
            self.assertEqual(upstream["static_field"]["manifest"], "native/manifest.json")
            self.assertNotIn("export_manifest", upstream["static_field"])
            self.assertEqual(upstream["geometry"]["instances"], binding["instances"])
            binding["refinement_windows"][0]["sources"]["surface"] = None
            binding["refinement_windows"][0]["records"]["surface"] = None
            path.write_text(json.dumps(binding), encoding="utf-8")
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], cwd=RUNNER.parent,
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            value = json.loads(result.stdout)
            self.assertNotIn(None, value["guard"])
            self.assertNotIn("local/v.pa-surf", value["guard"])
            self.assertIn("native/v.pa-surf", value["guard"])
            self.assertEqual(len(value["gui"]), 7)

    def test_first_completed_batch_publishes_existing_controlled_aberration_report(self):
        self.assertIn("function Publish-MrtofFirstBatchAberration", self.source)
        self.assertIn("--first-batch-log',$Record.stdout", self.source)
        self.assertIn("--source-receipt',$bunchSourceLocal", self.source)
        self.assertIn("Publish-MrtofFirstBatchAberration -Record", self.source)
        self.assertIn("$manifestOutputs+=$earlyAberrationReport", self.source)

    def test_bunch_batches_publish_common_whole_batch_checkpoints(self):
        for token in (
            "[string]$BatchContinuationRunPath=''",
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_continuation",
            "simion_batch_continuation_plan",
            "continuation accepts only whole completed batches",
            "-OnProcessCompleted $checkpointAction",
            "-Status checkpoint",
        ):
            self.assertIn(token, self.source)
        self.assertIn("$replayBatchIndexes-contains$index", self.source)
        self.assertIn("$replayBatchIndexes=@(", self.source)
        self.assertIn(
            "$replayBatchIndexes=@($replanned.batches|ForEach-Object{[int]$_.index})",
            self.source,
        )

    def test_failure_removes_only_disposable_trajectory_cache_before_publication(self):
        catch = self.source.index("}catch{")
        failed = self.source.index("Complete-FailedRun", catch)
        cache_cleanup = self.source.index(
            "Get-ChildItem -LiteralPath $temporarySolverDir -File -Filter 'trj*.tmp'",
            catch,
        )
        self.assertLess(cache_cleanup, failed)

    def test_compact_postprocess_does_not_transition_a_finished_solver_lease(self):
        self.assertNotIn("-Stage 'mrtof_postprocess'", self.source)

    def test_inherited_host_lease_is_reused_and_not_released_by_child(self):
        self.assertIn("[pscustomobject]$InheritedHostResourceLease=$null", self.source)
        self.assertIn("$resourceLease=$InheritedHostResourceLease", self.source)
        self.assertIn("$ownsHostResourceLease=$null-eq$InheritedHostResourceLease", self.source)
        self.assertIn("if($ownsHostResourceLease){", self.source)
        self.assertNotIn("Update-HostResourceStage -Lease $resourceLease -Stage 'mrtof_prepare'", self.source)
        self.assertEqual(
            self.source.count("Update-HostResourceStage -Lease $resourceLease -Stage 'mrtof_flight'"),
            2,
        )
        self.assertIn("if($ownsHostResourceLease-and$null-ne$resourceLease)", self.source)

    def test_shared_host_lease_does_not_accumulate_transient_work_roots(self):
        self.assertIn("[bool]$RegisterHostProcess=$true", self.source)
        self.assertIn(
            "if($RegisterHostProcess-and-not$process.HasExited)", self.source
        )
        self.assertEqual(
            self.source.count("-RegisterHostProcess $ownsHostResourceLease"), 4
        )
        self.assertNotIn(
            "a reserved process creation identity is unavailable", self.source
        )

    def test_provider_runtime_receipt_is_the_only_accelerator_input(self):
        self.assertIn("AcceleratorProviderReceiptPath", self.source)
        self.assertNotIn("AcceleratorRunPath", self.source)
        self.assertIn("orthogonal_accelerator_mrtof_runtime_receipt", self.source)
        self.assertIn("published_standalone_response_bank", self.source)
        self.assertIn("Provider consumed input byte count differs from its declared receipt.", self.source)
        self.assertIn("$acceleratorConsumerProjectionId='mrtof_accelerator_provider_receipt_v1'", self.source)
        self.assertIn("--consumer-projection-id $acceleratorConsumerProjectionId --consumed-output $acceleratorProviderReceipt", self.source)
        self.assertIn("@($providerAccelerator.provider_plan,$providerAccelerator.resolved_campaign)", self.source)
        self.assertNotIn("$providerAccelerator.pa_child_manifest", self.source)
        self.assertIn("$iobAcceleratorInput=$sourceAccelerator", self.source)
        self.assertNotIn("Copy-IobPaInput -Source $sourceAccelerator", self.source)
        self.assertIn(
            "@('-c',$poseCode,$reviewed,$acceleratorLocal,$trajectoryContract,$posePath,$acceleratorProviderPlanLocal)",
            self.source,
        )
        self.assertNotIn(
            "@('-c',$poseCode,$reviewed,$acceleratorGeometry,$trajectoryContract,$posePath)",
            self.source,
        )

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell is required")
    def test_exit_only_skips_detector_gate_but_full_flight_calls_it(self):
        start = self.source.index("  $collectionGatePath=$null;$collectionGate=$null")
        end = self.source.index("  $observedResiduals=", start)
        block = self.source[start:end]
        with TemporaryDirectory() as directory:
            quoted = "'" + directory.replace("'", "''") + "'"
            for scope, expected_calls in (
                ("accelerator_safe_exit_envelope_only", 0),
                ("complete_three_dimensional_static_return", 1),
            ):
                with self.subTest(scope=scope):
                    command = (
                        "$ErrorActionPreference='Stop'; $isBunchFlight=$true; $calls=0\n"
                        f"$trial=@{{execution_scope='{scope}'}}; $resultDir={quoted}\n"
                        "$observation='unused'; function Invoke-ProjectPython { param($Arguments) "
                        "$script:calls++; '{}' | Set-Content -LiteralPath $Arguments[-1] }\n"
                        + block
                        + "\n@{calls=$calls; gate_is_null=($null-eq$collectionGate)}|ConvertTo-Json -Compress"
                    )
                    result = subprocess.run(
                        ["pwsh", "-NoProfile", "-Command", command],
                        cwd=RUNNER.parent,
                        capture_output=True, text=True, encoding="utf-8", timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    actual = json.loads(result.stdout)
                    self.assertEqual(actual["calls"], expected_calls)
                    self.assertEqual(actual["gate_is_null"], expected_calls == 0)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell is required")
    def test_flight_scope_follows_execution_scope(self):
        scope_start = self.source.index("$isSafeExitOnly=")
        scope_end = self.source.index("\n", scope_start)
        label_start = self.source.index("$config.parameters.flight_scope=")
        label_end = self.source.index(";$config.parameters.execution_scope=", label_start)
        for scope in (
            "accelerator_safe_exit_envelope_only",
            "complete_three_dimensional_static_return",
        ):
            with self.subTest(scope=scope):
                command = (
                    "$ErrorActionPreference='Stop'; $config=@{parameters=@{}}; "
                    f"$trial=@{{execution_scope='{scope}'}}\n"
                    + self.source[scope_start:scope_end] + "\n"
                    + self.source[label_start:label_end] + "\n"
                    + "$config.parameters | ConvertTo-Json -Compress"
                )
                result = subprocess.run(
                    ["pwsh", "-NoProfile", "-Command", command],
                    cwd=RUNNER.parent,
                    capture_output=True, text=True, encoding="utf-8", timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)["flight_scope"], scope)

    def test_provider_small_inputs_are_frozen_and_consumed_locally(self):
        for variable, filename, option in (
            ("acceleratorProviderPlan", "accelerator_provider_plan.json", "--accelerator-provider-plan"),
            ("acceleratorResolvedCampaign", "accelerator_resolved_campaign.json", "--accelerator-resolved-campaign"),
        ):
            self.assertIn(f"${variable}Local=Copy-RequiredInput ${variable}", self.source)
            self.assertIn(f"'{option}',${variable}Local", self.source)
            self.assertIn(f"Join-Path $artifactSolverDir '{filename}'", self.source)
            capacity_line = next(line for line in self.source.splitlines() if "$requiredBytes+=[int64]" in line and "foreach" in line)
            self.assertIn(f"${variable}", capacity_line)
        pose = next(line for line in self.source.splitlines() if line.strip().startswith('$poseCode='))
        self.assertIn("plan=json.loads(Path(sys.argv[5]).read_text", pose)
        self.assertNotIn("receipt['provider_plan']['path']", pose)

    def test_trajectory_contract_authority_precedes_its_derived_inputs(self):
        authority = "$trajectoryContractSource=$trajectoryContractInput"
        self.assertLess(
            self.source.index(authority),
            self.source.index("$selectedContract=$trajectoryContractSource"),
        )
        self.assertLess(
            self.source.index(authority),
            self.source.index("$acceleratorGeometryContract=$trajectoryContractSource"),
        )

    def test_optional_contract_controls_pose_and_trajectory_without_rebuilding_pa(self):
        self.assertIn("[string]$ContractPath=''", self.source)
        self.assertIn("$trajectoryContractInput=if([string]::IsNullOrWhiteSpace($ContractPath))", self.source)
        self.assertIn("$trajectoryContractSource=$trajectoryContractInput", self.source)

    def test_direct_trial_accepts_run_input_accelerator_y_pose(self):
        self.assertIn("[Nullable[double]]$AcceleratorYAnchorMm=$null", self.source)
        self.assertIn(
            "$resolvedContract.accelerator.focus_y_anchor.project_y_mm=[double]$AcceleratorYAnchorMm",
            self.source,
        )
        self.assertIn(
            "foreach($resolvedContractPath in @($contract,$acceleratorGeometry,$trajectoryContract))",
            self.source,
        )
        self.assertIn("$config.parameters.accelerator_y_anchor_mm", self.source)

if __name__ == "__main__":
    unittest.main()
