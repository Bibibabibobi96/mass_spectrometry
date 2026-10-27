from pathlib import Path
import json
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import copy
import sys
import hashlib


REPO_ROOT = Path(__file__).resolve().parents[4]
RUNNER = Path(__file__).resolve().parents[2] / "analysis" / "run_native_candidate_chain.ps1"


class NativeCandidateChainRunnerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_actual_resolution_guard_accepts_only_current_matching_method(self):
        source = RUNNER.read_text(encoding="utf-8-sig")
        start = source.index("  if($rootComparison.peak_method_id")
        end = source.index("  $measuredResolution=", start)
        guard = source[start:end]
        for method, contract_method in (("common_gaussian_kde_time_v2", "common_gaussian_kde_time_v2"),
                                        ("common_gaussian_kde_time_v1", "common_gaussian_kde_time_v1"),
                                        ("unknown", "unknown"),
                                        ("common_gaussian_kde_time_v2", "common_gaussian_kde_time_v1")):
            script = ("$ErrorActionPreference='Stop';$rootComparison=@{peak_method_id='" + method
                      + "';peak_analysis_contract=@{method_id='" + contract_method + "'}};" + guard)
            with self.subTest(method=method, contract_method=contract_method):
                result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
                self.assertEqual(result.returncode == 0, method == contract_method == "common_gaussian_kde_time_v2",
                                 result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_static_center_source_projection_verifies_consumed_records_not_unused_pa(self):
        run = REPO_ROOT.parent/"artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_064108__sim__simion__converging-joint-ps-workpoint__r02-stage-020"
        if not (run/"run_manifest.json").exists():
            self.skipTest("sealed local centre evidence is unavailable")
        manifest = json.loads((run/"run_manifest.json").read_text())
        source = RUNNER.read_text(encoding="utf-8-sig")
        helpers = ""
        for name in ("Assert-Manifest", "Get-ManifestOutputPath"):
            start = source.index(f"function {name} {{")
            helpers += source[start:source.index("\nfunction ", start+1)]+"\n"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for change in (None, "missing", "hash"):
                with self.subTest(change=change):
                    document = copy.deepcopy(manifest)
                    document["inputs"]["native_global_fallback_pa"]["sha256"] = "unused-invalid-hash"
                    if change == "missing":
                        del document["inputs"]["bunch_source_receipt"]
                    elif change == "hash":
                        document["inputs"]["bunch_source_receipt"]["sha256"] = "changed-required-hash"
                    (root/"run_manifest.json").write_text(json.dumps(document))
                    script = ("param($Repo,$Root,$Python)\nSet-StrictMode -Version Latest;$ErrorActionPreference='Stop';"
                              "$repoRoot=$Repo;$python=$Python;$project='parallel_mirror_dual_stripe_mr_tof';\n"+helpers+
                              "Assert-Manifest -RunPath $Root -Status success -Mode finite_3d_two_prism_voltage_trial -StaticCenterSourceProjection\n")
                    path = root/"verify.ps1"
                    path.write_text(script)
                    result = subprocess.run(["pwsh", "-NoProfile", "-File", str(path), str(REPO_ROOT), str(root), sys.executable],
                                            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
                    if change is None:
                        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                        self.assertIn("SCOPE=consumer_projection", result.stdout)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("bunch_source_receipt", result.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_native_binding_omits_absent_optional_argv_under_real_parameter_validation(self):
        source = RUNNER.read_text(encoding="utf-8-sig")
        start = source.index("function Assert-NativeStaticFieldBinding {")
        helper = source[start:source.index("\nfunction ", start+1)]
        script = "Set-StrictMode -Version Latest;$ErrorActionPreference='Stop';"+helper+"\n"+r'''
$FieldProviderRequestPath='request';$mirrorReferenceTrialManifest='reference';$script:calls=@()
function Invoke-ProjectPython {param([Parameter(Mandatory)][string[]]$Arguments) $script:calls+=,@($Arguments)}
$base=@{BindingPath='binding';Voltages=@(-27.,0.,190.,-190.);Variation='variation';ContractPath='contract'}
Assert-NativeStaticFieldBinding @base
Assert-NativeStaticFieldBinding @base -NumericalContractPath 'numerics'
Assert-NativeStaticFieldBinding @base -NumericalContractPath 'numerics' -CenterMaterializationPath 'centre'
$counts=@($calls|ForEach-Object{$_.Count});if(($counts-join',')-ne'9,10,11'){throw 'Optional argv positional layout changed'}
if(@($calls|ForEach-Object{$_}|Where-Object{$_-eq''}).Count){throw 'Empty optional argument reached Python wrapper'}
$caught='';try{Assert-NativeStaticFieldBinding @base -CenterMaterializationPath 'centre'}catch{$caught=$_.Exception.Message}
if($caught-notlike'*frozen numerical contract*'){throw 'Centre projection omitted its required numerical authority'}
'NATIVE_OPTIONAL_ARGV=PASS'
'''
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn("NATIVE_OPTIONAL_ARGV=PASS", result.stdout)

    def test_native_center_storage_projection_accepts_actual_full_field_and_rejects_changes(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_binding
        runs = REPO_ROOT.parent/"artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs"
        materialization_path = runs/"20261014_064108__sim__simion__converging-joint-ps-workpoint__r02-stage-020/results/two_prism_trial_materialization.json"
        binding_path = runs/"20261014_073134__build__simion__converging-joint-full-field/results/field_binding.json"
        if not materialization_path.exists() or not binding_path.exists():
            self.skipTest("sealed local converging centre/full-field evidence is unavailable")
        materialization = json.loads(materialization_path.read_text())
        historical_field = runs / "20261014_064108__sim__simion__converging-joint-ps-workpoint__r02-stage-020-field"
        if (historical_field / "solver_review_retirement_receipt.json").exists():
            from common.contracts.solver_review_retirement import verify_retirement
            # Only this known optional historical asset may be absent after its
            # owner-approved retirement; malformed evidence must still fail.
            self.assertEqual(Path(materialization["field_binding"]["manifest"]).resolve().parent,
                             historical_field.resolve())
            verify_retirement(historical_field)
            self.skipTest("historical centre PA publicly retired; synthetic storage projection coverage remains in "
                          "test_downstream_fixed_grid_workpoint.test_center_storage_projection_preserves_original_problem_without_pa_reads")
        actual = load_binding(Path(materialization["field_binding"]["path"]))
        full = load_binding(binding_path)
        source = RUNNER.read_text(encoding="utf-8-sig")
        code = source.split("      $storageCode=@'\n", 1)[1].split("\n'@", 1)[0]
        with TemporaryDirectory() as directory:
            request = Path(directory)/"request.json"
            request.write_text(json.dumps({"source_binding_path": str(binding_path), "source_field_manifest": full["manifest"]}))
            for change in (None, "geometry", "grid", "voltage", "thin"):
                with self.subTest(change=change):
                    candidate = copy.deepcopy(full)
                    if change == "geometry":
                        candidate["geometry"]["mirror_convergence_transform"]["angle_deg"] += .001
                    elif change == "grid":
                        candidate["grid"]["pitch_mm"][1] += .01
                    elif change == "voltage":
                        candidate["authority"]["analyzer_electrode_voltages_v"][10] += .01
                    elif change == "thin":
                        candidate["consumer_view"] = actual["consumer_view"]
                    with patch("sys.argv", ["projection", str(materialization_path), str(request)]), \
                         patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding.load_binding",
                               side_effect=[actual, candidate]):
                        if change is None:
                            exec(code, {})
                        else:
                            with self.assertRaises(ValueError):
                                exec(code, {})
            native = source.split("function Assert-NativeStaticFieldBinding {", 1)[1]
            native_code = native.split("  $code=@'\n", 1)[1].split("\n'@", 1)[0]
            wrong = copy.deepcopy(materialization)
            wrong["field_binding"]["path"] = str(binding_path)
            wrong_path = Path(directory)/"wrong-centre.json"
            wrong_path.write_text(json.dumps(wrong))
            argv = ["native", materialization["field_binding"]["path"], str(request),
                    json.dumps([*materialization["stripe_biases_v"], *materialization["prism_voltages_v"]]),
                    "", "", "", "", str(wrong_path)]
            with patch("sys.argv", argv), \
                 patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding.load_binding",
                       side_effect=[full, actual]), \
                 patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider.derive_candidate_authority",
                       return_value=(actual["authority"], {})):
                with self.assertRaisesRegex(ValueError, "materialization binds another field"):
                    exec(native_code, {})

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_center_gate_uses_frozen_clean_energy_target_and_preserves_legacy_angle(self):
        source = RUNNER.read_text(encoding="utf-8-sig")
        helper = source[source.index("function Read-CenterWorkpointGate {"):
                        source.index("function Get-QualifiedCenterSeedManifest {")]
        helper = helper[:helper.index("\nfunction ", 1)]
        names = ["P1_P2_positive_mirror_turn_y_mm", "P1_P2_P2_shield_low_field_angle_degrees",
                 "Stripe_slow_turn_y_minus_L_mm", "Stripe_target_phase_y_minus_origin_mm"]
        energy = "P1_P2_clean_phase_effective_slow_energy_error_per_charge_v"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"results").mkdir()
            contract = {"downstream_fixed_grid_workpoint_profile": {"automatic_iteration": {
                "acceptance_tolerances": dict(zip(names, [.1, .01, .1, .1], strict=True))}}}
            target = {"mode": "converging_clean_phase_energy", "slow_energy_reference_per_charge_v": 5.374}
            for mode, angle, value, expected in [(False, .02, 0., False), (False, .005, 0., True),
                                                 (True, 1., .02, True), (True, 0., .06, False),
                                                 (True, 0., None, False)]:
                with self.subTest(mode=mode, angle=angle, energy=value):
                    authored = copy.deepcopy(contract)
                    if mode:
                        authored["prism_transport"] = {"handoff_target": target}
                    residuals = dict(zip(names, [0., angle, 0., 0.], strict=True))
                    if value is not None:
                        residuals[energy] = value
                    (root/"contract.json").write_text(json.dumps(authored))
                    (root/"results/two_prism_trial_observation.json").write_text(json.dumps({
                        "center_particle_workpoint_validation": {"status": "observed", "physical_acceptance_residuals": residuals}}))
                    (root/"results/two_prism_trial_materialization.json").write_text(json.dumps({
                        "prism_handoff_target": {**target, "energy_tolerance_per_charge_v": .05234301827428656}}))
                    script = root/"gate.ps1"
                    script.write_text("param($Root)\n$ErrorActionPreference='Stop';Set-StrictMode -Version Latest\n"+helper+
                        "\n$c=Get-Content (Join-Path $Root 'contract.json') -Raw|ConvertFrom-Json -AsHashtable\n"
                        "$g=Read-CenterWorkpointGate -ScreeningResult @{cohort_run_manifest=(Join-Path $Root 'run_manifest.json')} -ContractDocument $c\n"
                        "$g|ConvertTo-Json -Depth 20\n")
                    result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(root)],
                                            cwd=REPO_ROOT, capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                    gate = json.loads(result.stdout)
                    self.assertEqual(gate["passed"], expected)
                    if mode and not expected:
                        self.assertEqual(gate["failed"], [energy])

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_actual_probe_and_reclosed_blocks_use_python_anchor_relative_step(self):
        source = RUNNER.read_text(encoding="utf-8-sig")
        probe = source[source.index("$failureStage='te1_probe'"):
                       source.index("  if($ProbeScreeningRunPath){")]
        remeasure = source[source.index("      $remeasureVariation=Join-Path"):
                           source.index("      $remeasured=if(")]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            documents = {
                "reference.json": {
                    "schema_version": 1, "role": "mrtof_terminal_time_mirror_voltage_variation",
                    "status": "screening_candidate_materialized", "mode": "TE1", "coordinate": 1.0,
                    "qualification": "diagnostic_only__complete_3d_detector_response_pending",
                    "base_mirror_voltages_v": [0, -10, -20, 30, 40],
                    "target_mirror_voltages_v": [0, -9, -22, 33, 44],
                    "voltage_delta_v": [1, -2, 3, 4],
                },
                "period.json": {"simion_normalized_period_slopes_per_v": [0, 0, 0],
                                "energy_centers_ev": [100, 200, 300]},
                "correction.json": {"updated_local_slope_jacobian_per_v2": [[1e-8, 0, 0, 0]] * 3},
                "contract.json": {
                    "downstream_fixed_grid_workpoint_profile": {
                        "jacobian_relative_step_tiers": {"fine": 0.0005}},
                    "mirror": {"theory_requirements": {"l0_acceptance_budget": {
                        "minimum_mass_resolution": 100000, "mirror_time_width_fraction": 1}}},
                },
            }
            for name, document in documents.items():
                (root / name).write_text(json.dumps(document), encoding="utf-8")
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            script = (
                "$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;"
                + f"$fixture={quote(root)};$python={quote(sys.executable)};"
                + "$package=@{result_dir=$fixture};$baselineCoordinate=-22.894154431673797;"
                + "$te1Reference=Join-Path $fixture 'reference.json';"
                + "$mirrorPeriod=Join-Path $fixture 'period.json';"
                + "$mirrorCorrection=Join-Path $fixture 'correction.json';"
                + "$focusContractPath=Join-Path $fixture 'contract.json';"
                + "$analysisModule='projects.parallel_mirror_dual_stripe_mr_tof.analysis.source_z_energy_timing_diagnostic';"
                + "function Invoke-ProjectPython {param([string[]]$Arguments) & $python @Arguments;"
                + "if($LASTEXITCODE-ne0){throw 'Python materialization failed'}};"
                + probe
                + "$rootCoordinate=-25.;$reclosureCount=1;$rootVariations=@();"
                + remeasure
                + "@{probe=$probeVariationData;remeasure=$remeasureVariationData}|ConvertTo-Json -Depth 15 -Compress"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout.splitlines()[-1])
        direction = [1, -2, 3, 4]
        for kind, anchor in (("probe", -22.894154431673797), ("remeasure", -25.0)):
            with self.subTest(kind=kind):
                variation = result[kind]
                self.assertLess(variation["coordinate"], anchor)
                current = [v + anchor * d for v, d in
                           zip(variation["base_mirror_voltages_v"][1:], direction, strict=True)]
                relative = [abs((target - start) / start) for target, start in
                            zip(variation["target_mirror_voltages_v"][1:], current, strict=True)]
                self.assertAlmostEqual(max(relative), 0.0005, places=14)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_diagnostic_reuses_only_verified_bound_standard_output(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            flight = root / "flight"
            flight.mkdir()
            report = flight / "source_z_energy_timing_diagnostic.json"
            report.write_text(json.dumps({"role": "mrtof_source_z_energy_timing_diagnostic",
                                          "status": "candidate_diagnostic"}), encoding="utf-8")
            digest = hashlib.sha256(report.read_bytes()).hexdigest()
            historical_runner = root / "historical.ps1"
            historical_runner.write_text(
                "param($FlightRunPath,$RunId,$PythonExe) $global:diagnosticCalls++\n",
                encoding="utf-8",
            )
            for case in ("reuse", "historical", "bad_hash", "duplicate", "failed"):
                with self.subTest(case=case):
                    record = {"path": str(report), "sha256": digest if case != "bad_hash" else "0" * 64}
                    outputs = [] if case == "historical" else [record]
                    if case == "duplicate":
                        outputs.append(record)
                    manifest = flight / "run_manifest.json"
                    manifest.write_text(json.dumps({
                        "status": "failed" if case == "failed" else "success",
                        "project": "instrument_assembly",
                        "mode": "oa_mr", "outputs": outputs,
                    }), encoding="utf-8")
                    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
                    script = (
                        "$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;"
                        + f"$path={quote(RUNNER)};$fixture={quote(root)};"
                        + "$tokens=$null;$errors=$null;$ast=[System.Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors);"
                        + "$ast.FindAll({param($n) $n-is[System.Management.Automation.Language.FunctionDefinitionAst]-and"
                        + "$n.Name-in@('Get-ManifestOutputPath','Invoke-Diagnostic')},$true)|ForEach-Object {Invoke-Expression $_.Extent.Text};"
                        + "$project='parallel_mirror_dual_stripe_mr_tof';$python='mock';$global:diagnosticCalls=0;"
                        + f"$artifactRoot={quote(root)};$diagnosticRunner={quote(historical_runner)};"
                        + "function New-StageRunId {param($Activity,$Scope,$Subject) 'historical-analysis'};"
                        + "function Assert-Manifest {param($RunPath,$Status,$Mode) 'verified historical analysis'};"
                        + f"try{{$result=Invoke-Diagnostic -Stage fixture -FlightManifest {quote(manifest)};"
                        + "@{accepted=$true;path=$result;calls=$global:diagnosticCalls}|ConvertTo-Json -Compress}"
                        + "catch{@{accepted=$false;reason=$_.Exception.Message;calls=$global:diagnosticCalls}|ConvertTo-Json -Compress}"
                    )
                    completed = subprocess.run(
                        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    result = json.loads(completed.stdout.splitlines()[-1])
                    self.assertEqual(result["accepted"], case in ("reuse", "historical"), result)
                    self.assertEqual(result["calls"], 1 if case == "historical" else 0)
                    if case == "reuse":
                        self.assertEqual(Path(result["path"]), report)

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
                cwd=REPO_ROOT,
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
            "'--baseline-coordinate',[string]$baselineCoordinate",
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

    def test_completed_first_reclosed_response_reuses_evidence_without_field_or_flight(self):
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 required")
        source = RUNNER.read_text(encoding="utf-8-sig")
        start = source.index("$remeasured=if($reclosureCount-eq1-and$ReclosedResponseScreeningRunPath)")
        block = source[start:source.index("$remeasureDiagnostic=", start)]
        self.assertIn("reclosed_response_screening_run_path=$ReclosedResponseScreeningRunPath", source)
        protected = source[source.index("$protectedPaths=@("):source.index("$capacitySession=Enter-ArtifactWorkflowCapacitySession")]
        self.assertIn("$ReclosedResponseScreeningRunPath", protected)
        for attempt, path, invalid, expected_reads, expected_flights in (
            (1, "completed-response", False, 1, 0), (1, "", False, 0, 1),
            (2, "completed-response", False, 0, 1), (1, "completed-response", True, 1, 0),
        ):
            with self.subTest(attempt=attempt, path=path, invalid=invalid):
                script = (
                    "Set-StrictMode -Version Latest;$ErrorActionPreference='Stop';"
                    f"$reclosureCount={attempt};$ReclosedResponseScreeningRunPath='{path}';"
                    "$workpointRun='actual-reclosed';$sourceReceipt='canonical-mother';"
                    "$NativeCorridorBankRunPath='';$remeasureVariation='absolute-response';"
                    "$source=@{particle_states_sha256='mother-states'};$reads=0;$flights=0;$caught='';"
                    f"$invalid=${str(invalid).lower()};"
                    "function Read-ScreeningEvidence {param($RunPath,$Scope,$ExpectedWorkpointRun,$ExpectedSourceReceipt,$ExpectedNativeBankRun,$ExpectedVariation,$ExpectedSourceStatesSha256) "
                    "$script:reads++;$script:received=$PSBoundParameters;"
                    "if($invalid){throw 'incompatible screening identity'};@{reused=$true}};"
                    "function Invoke-Screening {param($Stage,$WorkpointRun,$SourceReceipt,$Variation,$ParticleCount,[switch]$FocusDiagnosticOnly) $script:flights++;@{reused=$false}};"
                    "try{" + block + "}catch{$caught=$_.Exception.Message};"
                    "@{reads=$reads;flights=$flights;caught=$caught;received=$(if($reads){$received}else{@{}})}|ConvertTo-Json -Depth 5 -Compress"
                )
                completed = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", script],
                    cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result = json.loads(completed.stdout)
                self.assertEqual((result["reads"], result["flights"]), (expected_reads, expected_flights))
                self.assertEqual(bool(result["caught"]), invalid)
                if expected_reads:
                    self.assertEqual(result["received"], {
                        "RunPath": path, "Scope": "focus", "ExpectedWorkpointRun": "actual-reclosed",
                        "ExpectedSourceReceipt": "canonical-mother", "ExpectedNativeBankRun": "",
                        "ExpectedVariation": "absolute-response", "ExpectedSourceStatesSha256": "mother-states"})

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
                    "Set-StrictMode -Version Latest; $ErrorActionPreference='Stop'; $staticFieldMode=$false\n"
                    + helpers
                    + function
                )
                return subprocess.run(
                    [shell, "-NoProfile", "-NonInteractive", "-Command", script],
                    cwd=REPO_ROOT,
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
        self.assertIn("$CompletedTe1WorkpointReclosureRunPath,$ReclosedRootScreeningRunPath,$ReclosedResponseScreeningRunPath,$FinalScreeningRunPath", source)
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
        self.assertIn("'--baseline-coordinate',[string]$baselineCoordinate", source)
        self.assertIn("$probeCoordinate=[double]$probeVariationData.coordinate", source)
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

    def test_te1_reclosure_inherits_the_sealed_seed_integration_profile(self) -> None:
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 is required for the reclosure argument regression")
        source = RUNNER.read_text(encoding="utf-8-sig")
        resolver = source[source.index("function Get-ManifestOutputPath"):
                          source.index("function Invoke-ProjectPython")]
        helper = source[source.index("function Invoke-Te1WorkpointReclosure"):
                        source.index("function Read-CompletedTe1WorkpointReclosure")]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            materialization = root / "two_prism_trial_materialization.json"
            manifest = root / "run_manifest.json"
            contract = root / "contract.json"
            contract.write_text(json.dumps({"simion": {"trajectory_profiles": {
                "center_screening": {"maximum_step_us": 0.002},
            }}}), encoding="utf-8")
            script = (
                "Set-StrictMode -Version Latest; $ErrorActionPreference='Stop'\n"
                + resolver + helper
                + "function New-StageRunId {'fixture-reclose'}\n"
                + "$TrajectoryStepScaleOverride=$null; $staticFieldMode=$true; $staticFieldRepresentation='comsol_static_scalar_v'; $NativeCorridorBankRunPath=''; "
                "$GeometryReviewRunPath='geometry'; $MirrorRunPath='mirror'; "
                "$StripeRunPath='stripe'; $AcceleratorProviderReceiptPath='oa'; "
                "$NativeSystemRuntimeBundlePath=''; $AcceleratorYAnchorMm=-55; "
                "$sourceYOffsetMm=-1; $python='python'; $SimionExe=''; "
                "$FieldProviderRequestPath='request'; $CenterSourceReceiptPath='source';$PrismControllerPolicyPath=''\n"
                + "$workpointRunner={param($TrajectoryProfileId,$TrajectoryStepScale,$SeedTrialManifest,$MirrorVoltageVariationPath,$GeometryReviewRunPath,$MirrorRunPath,$StripeRunPath,$AcceleratorProviderReceiptPath,$AcceleratorYAnchorMm,$AcceleratorSourceYOffsetMm,$ContractPath,$RunId,$PythonExe,$FieldProviderRequestPath,$CenterSourceReceiptPath,$PrismControllerPolicyPath) "
                "$captured=@{profile=$TrajectoryProfileId;scale=$TrajectoryStepScale};if($PSBoundParameters.ContainsKey('PrismControllerPolicyPath')){$captured.policy=$PrismControllerPolicyPath};$captured|ConvertTo-Json -Compress; "
                "throw 'fixture_runner_reached'}\n"
                + f"try {{ Invoke-Te1WorkpointReclosure -Attempt 1 -SeedManifest '{manifest}' "
                f"-Variation 'variation' -CurrentContractPath '{contract}' -RuntimeCheckpoint '' }} "
                "catch {if($_.Exception.Message-ne'fixture_runner_reached'){throw}}; exit 0"
            )

            def invoke() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [shell, "-NoProfile", "-NonInteractive", "-Command", script],
                    cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
                    timeout=30, check=False,
                )

            for scale in (1.0, 2.0, 0.25):
                trajectory = {"profile_id": "center_screening", "maximum_step_us": 0.002 * scale}
                if scale != 1.0:
                    trajectory.update(base_profile_id="center_screening", profile_id=f"center_screening__step_scale_{scale}")
                materialization.write_text(json.dumps({"trajectory_profile": trajectory}), encoding="utf-8")
                manifest.write_text(json.dumps({"outputs": [{
                    "path": str(materialization),
                    "sha256": hashlib.sha256(materialization.read_bytes()).hexdigest(),
                }]}), encoding="utf-8")
                completed = invoke()
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertEqual(json.loads(completed.stdout), {"profile": "center_screening", "scale": scale})
            overridden = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-Command",
                 script.replace("$TrajectoryStepScaleOverride=$null", "$TrajectoryStepScaleOverride=1")],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
            )
            self.assertEqual(overridden.returncode, 0, overridden.stdout + overridden.stderr)
            self.assertEqual(json.loads(overridden.stdout), {"profile": "center_screening", "scale": 1.0})
            explicit = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-Command",
                 script.replace("$PrismControllerPolicyPath=''", "$PrismControllerPolicyPath='frozen-policy.json'")],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
            )
            self.assertEqual(explicit.returncode, 0, explicit.stdout + explicit.stderr)
            self.assertEqual(json.loads(explicit.stdout)["policy"], "frozen-policy.json")
            materialization.write_text("{}", encoding="utf-8")
            corrupted = invoke()
            self.assertNotEqual(corrupted.returncode, 0)
            self.assertIn("Manifest output hash differs", corrupted.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_optional_prism_policy_is_frozen_validated_and_recorded(self):
        policy = {"schema_version": 1, "role": "mrtof_prism_controller_policy", "scope": "future_prism_proposals",
                  "prediction_error_fraction_of_acceptance_tolerance": .1, "trusted_advance_multiplier": 1.}
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text(json.dumps(policy))
            script = r'''
param($Source,$Root,$Python,$Policy)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Extent.Text.Contains('$PrismControllerPolicyPath=Copy-VerifiedRunInput')},$true)
$PrismControllerPolicyPath=$Policy;$package=@{input_dir=$Root};$config=@{inputs=@{}};$python=$Python
function Copy-VerifiedRunInput {param($Source,$Destination)Copy-Item -LiteralPath $Source -Destination $Destination;return $Destination}
function Invoke-ProjectPython {param($Arguments)& $python -B @Arguments;if($LASTEXITCODE-ne0){throw 'policy validation failed'}}
Invoke-Expression $node.Extent.Text
$config|ConvertTo-Json -Compress
'''
            path = root / "freeze.ps1"
            path.write_text(script)
            for provided in ("", str(source)):
                result = subprocess.run(["pwsh", "-NoProfile", "-File", str(path), str(RUNNER), str(root),
                                         sys.executable, provided], cwd=REPO_ROOT, capture_output=True,
                                        text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                inputs = json.loads(result.stdout)["inputs"]
                if provided:
                    frozen = Path(inputs["prism_controller_policy"])
                    self.assertEqual(json.loads(frozen.read_text()), policy)
                    self.assertEqual(hashlib.sha256(frozen.read_bytes()).digest(), hashlib.sha256(source.read_bytes()).digest())
                else:
                    self.assertEqual(inputs, {})

    def test_te1_reclosure_reuses_the_condition_native_runtime(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("[string]$NativeRuntimeCheckpoint=''", source)
        self.assertIn("function Get-ManifestOutputPath", source)
        self.assertIn("Manifest must bind exactly one $FileName output", source)
        helper = source[
            source.index("function Invoke-Te1WorkpointReclosure"):
            source.index("function Read-CompletedTe1WorkpointReclosure")
        ]
        self.assertIn("[Parameter(Mandatory)][AllowEmptyString()][string]$RuntimeCheckpoint", helper)
        self.assertIn("NativeRuntimeCheckpoint=$RuntimeCheckpoint", helper)
        self.assertIn("-RuntimeCheckpoint $activeNativeRuntimeCheckpoint", source)
        self.assertIn(
            "$activeNativeRuntimeCheckpoint=if($staticFieldMode){''}else{Get-ManifestOutputPath -ManifestPath $workpointManifest",
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
        self.assertIn("'--baseline-coordinate',[string]$rootCoordinate", source)
        self.assertIn("$remeasureCoordinate=[double]$remeasureVariationData.coordinate", source)
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



    def _run_field_dispatch(self, *, fail_provider=False, same_mirror=False, mismatched_handoff=False, native=False, step_override=None, same_numerics=True, basis=False, thin=False, reuse_full=False):
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 is required for field-dispatch behavior fixtures")
        source = RUNNER.read_text(encoding="utf-8-sig")
        def function(name):
            start = source.index("function " + name + " {")
            end = source.find("\nfunction ", start + 1)
            return source[start:end if end >= 0 else len(source)]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "inputs").mkdir()
            (root / "results").mkdir()
            center_manifest = root / "run_manifest.json"
            center_manifest.write_text("{}", encoding="utf-8")
            binding = root / "center_binding.json"
            binding.write_text(json.dumps({"consumer_view": {"axis": "x"}} if thin else {}), encoding="utf-8")
            mode = "native_static_pa" if native else "comsol_static_scalar_v"
            field = {"mode": mode, "path": str(binding)}
            center = {"field_binding": field, "mirror_voltages_v": [0, 1, 2, 3, 4],
                      "stripe_biases_v": [-27, 54], "prism_voltages_v": [191, -190]}
            (root / "results" / "two_prism_trial_materialization.json").write_text(
                json.dumps(center), encoding="utf-8")
            (root / "inputs" / "contract.json").write_text("{}", encoding="utf-8")
            target = center["mirror_voltages_v"] if same_mirror else [0, 2, 4, 6, 8]
            variation = root / "variation.json"
            variation.write_text(json.dumps({"target_mirror_voltages_v": target}), encoding="utf-8")
            handoff = {"selected_workpoint": {"field_binding": field,
                       "voltages_v": [-27, 54, 191, -190]}}
            if mismatched_handoff:
                handoff["selected_workpoint"]["voltages_v"][2] = 192
            handoff_path = root / "handoff.json"
            handoff_path.write_text(json.dumps(handoff), encoding="utf-8")
            provider = root / "provider.ps1"
            provider.write_text(
                "param($RequestPath,$RunDirectory,[switch]$Approved)\n"
                "$global:providerCalls++;$request=Get-Content $RequestPath -Raw|ConvertFrom-Json\n"
                "if($request.mirror_reference_trial_manifest-ne$mirrorReferenceTrialManifest){throw 'reference changed'}\n"
                "if($request.mirror_contract_path-ne(Join-Path $fixture 'inputs/contract.json')){throw 'contract changed'}\n"
                + ("if($request.numerical_contract_path-ne$ContractPath){throw 'numerical contract changed'}\n" if native else "")
                + ("if(@($request.response_basis_paths.PSObject.Properties).Count-ne4){throw 'basis dropped'};"
                   "$kind=if($request.source_binding_path-eq'original-source-binding'){'refine'}else{'compose'};"
                   "$global:kinds+=,$kind;"
                   "$out=Join-Path $RunDirectory 'field_binding.json';"
                   "$b=@{parent=@{manifest=(Join-Path $RunDirectory 'run_manifest.json')}};"
                   "if($kind-eq'compose'){$b.materialization=@{base_binding=$request.source_binding_path}};"
                   "New-Item -ItemType Directory -Path $RunDirectory -Force|Out-Null;"
                   "$b|ConvertTo-Json -Depth 20|Set-Content $out;\n" if basis else
                   "if(@($request.candidate_voltages_v.s1,$request.candidate_voltages_v.s2,$request.candidate_voltages_v.p1,$request.candidate_voltages_v.p2)-join','-ne'-27,54,191,-190'){throw 'stale request voltages'}\n")
                +
                "New-Item -ItemType Directory -Path $RunDirectory -Force|Out-Null\n"
                "@{status='" + ("failed" if fail_provider else "success") + "';field_binding=" + ("$out" if basis else "'candidate-field.json'") + "}"
                "|ConvertTo-Json|Set-Content (Join-Path $RunDirectory 'summary.json')\n",
                encoding="utf-8")
            screening = root / "screening.ps1"
            screening.write_text(
                "param($WorkpointRunPath,$BunchSourceReceiptPath,$CohortParticleCount,$RunId,$PythonExe,"
                "$MirrorVoltageVariationPath,$FieldBindingPath,$GeometryReviewRunPath,$TrajectoryStepScaleOverride)\n"
                "if(-not$FieldBindingPath){throw 'field missing'}\n"
                + ("if($GeometryReviewRunPath-ne'geometry-review'){throw 'geometry review missing'}\n" if native else "")
                +
                "$global:flightCalls++;$global:flownBindings+=@($FieldBindingPath);$global:flownScales+=@($TrajectoryStepScaleOverride)\n", encoding="utf-8")
            quote = lambda path: str(path).replace("'", "''")
            script = (
                "Set-StrictMode -Version Latest;$ErrorActionPreference='Stop'\n"
                + function("Test-SameResolvedPath") + function("Test-SameVoltageVector")
                + function("Resolve-ScreeningFieldBinding") + function("Invoke-Screening")
                + "function Get-QualifiedCenterSeedManifest {param($WorkpointRun,$Handoff) return $centerManifest}\n"
                + "function New-StageRunId {param($Activity,$Scope,$Subject) return $Subject}\n"
                + "function Read-ScreeningEvidence {param($RunPath,$Scope,$ExpectedWorkpointRun,$ExpectedSourceReceipt,$ExpectedNativeBankRun,$ExpectedVariation,$ExpectedFieldBindingPath) return @{} }\n"
                + "function Write-RunJson {param($Path,$Depth,$Value) $Value|ConvertTo-Json -Depth $Depth|Set-Content $Path}\n"
                + "function Assert-NativeStaticFieldBinding {param($BindingPath,$Voltages,$Variation,$ContractPath)}\n"
                + "function Invoke-ProjectPython {param($Arguments) if([string]$Arguments[2]-like'*candidate_authority*'){"
                + ("'true'" if reuse_full else "'false'") + ";return};"
                + ("'true'" if same_numerics else "'false'") + "}\n"
                + "function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$ProtectedPaths) $global:protected+=@($ProtectedPaths);@{session=$Session}}\n"
                + f"$fixture='{quote(root)}';$centerManifest='{quote(center_manifest)}';"
                + f"$ContractPath='{quote(root / 'inputs' / 'contract.json')}';"
                + f"$fieldProviderRunner='{quote(provider)}';$screeningRunner='{quote(screening)}';"
                + f"$handoff=Get-Content '{quote(handoff_path)}' -Raw|ConvertFrom-Json -AsHashtable;"
                + "$staticFieldMode=$true;$staticCandidateFields=@{};"
                + f"$TrajectoryStepScaleOverride={'$null' if step_override is None else step_override};"
                + f"$staticFieldRepresentation='{mode}';$GeometryReviewRunPath='geometry-review';"
                + "$NativeCorridorBankRunPath='';$python='fixture';$SimionExe='';"
                + "$artifactRoot=$fixture;$repoRoot=$fixture;$package=@{input_dir=(Join-Path $fixture 'inputs')};"
                + "$fieldProviderRequest=@{source_binding_path='original-source-binding';candidate_voltages_v=@{s1=0;s2=0;p1=0;p2=0}};"
                + "$FieldProviderRequestPath='frozen-full-request';"
                + ("$fieldProviderRequest.response_basis_paths=@{p1='p1';p2='p2';s1='s1';s2='s2'};" if basis else "")
                + "$mirrorReferenceTrialManifest='original-reference';"
                + "$capacitySession=@{status='active'};$global:protected=@();$global:providerCalls=0;$global:flightCalls=0;$global:flownBindings=@();$global:flownScales=@();$global:kinds=@();$caught='';\n"
                + "try {"
                + f"Invoke-Screening -Stage first -WorkpointRun $fixture -SourceReceipt source13 -Variation '{quote(variation)}' -ParticleCount 13 -DiagnosticPurpose controlled_aberration|Out-Null;"
                + ("$c=Get-Content (Join-Path $fixture 'results/two_prism_trial_materialization.json') -Raw|ConvertFrom-Json -AsHashtable;"
                   "$c.prism_voltages_v[0]=191.1;Write-RunJson -Path (Join-Path $fixture 'results/two_prism_trial_materialization.json') -Value $c -Depth 30;"
                   "$handoff.selected_workpoint.voltages_v[2]=191.1;" if basis else "")
                + f"Invoke-Screening -Stage second -WorkpointRun $fixture -SourceReceipt source100 -Variation '{quote(variation)}' -ParticleCount 100|Out-Null;"
                + (f"Invoke-Screening -Stage third -WorkpointRun $fixture -SourceReceipt source100 -Variation '{quote(variation)}' -ParticleCount 100|Out-Null;" if basis else "")
                + "} catch {$caught=$_.Exception.Message};"
                + "@{provider=$providerCalls;flights=$flightCalls;bindings=$flownBindings;scales=$flownScales;kinds=$kinds;protected=$protected;caught=$caught}|ConvertTo-Json -Compress"
            )
            completed = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-Command", script],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            return json.loads(completed.stdout)

    def test_native_thin_center_never_flies_off_axis_and_matching_full_source_is_reused(self):
        result = self._run_field_dispatch(native=True, same_mirror=True, thin=True, reuse_full=True)
        self.assertEqual(result['caught'], '')
        self.assertEqual(result['provider'], 0)
        self.assertEqual(result['bindings'], ['original-source-binding', 'original-source-binding'])
        rebuilt = self._run_field_dispatch(native=True, same_mirror=True, thin=True)
        self.assertEqual(rebuilt['caught'], '')
        self.assertEqual(rebuilt['provider'], 1)
        self.assertEqual(rebuilt['bindings'], ['candidate-field.json', 'candidate-field.json'])

    def test_native_mirror_offset_is_built_once_and_ps_points_compose_from_it(self):
        result = self._run_field_dispatch(native=True, basis=True)
        self.assertEqual(result['caught'], '')
        self.assertEqual(result['kinds'], ['refine', 'compose'])
        self.assertEqual((result['provider'], result['flights']), (2, 3))
        self.assertNotEqual(result['bindings'][0], result['bindings'][1])
        self.assertEqual(result['bindings'][1], result['bindings'][2])
        self.assertEqual(len(result['protected']), 2)

    def test_failed_native_offset_does_not_enter_cache_consumer_protection(self):
        result = self._run_field_dispatch(native=True, basis=True, fail_provider=True)
        self.assertIn('did not publish', result['caught'])
        self.assertEqual(result['protected'], [])
        self.assertEqual(result['flights'], 0)

    def test_static_te1_solves_before_flight_and_reuses_binding_across_sources(self):
        result = self._run_field_dispatch()
        self.assertEqual(result["caught"], "")
        self.assertEqual((result["provider"], result["flights"]), (1, 2))
        self.assertEqual(result["bindings"], ["candidate-field.json", "candidate-field.json"])
        self.assertEqual(result["scales"], [None, None])

    def test_explicit_base_step_override_is_forwarded_to_every_screening(self):
        for scale in (1.0, 2.0, 4.0):
            result = self._run_field_dispatch(native=True, step_override=scale)
            self.assertEqual(result["caught"], "")
            self.assertEqual(result["scales"], [scale, scale])
        source = RUNNER.read_text(encoding="utf-8-sig")
        initial = source[source.index("$failureStage='n1_workpoint'"):
                         source.index("$workpointManifest=Assert-Manifest")]
        self.assertIn("$arguments.TrajectoryStepScale=[double]$TrajectoryStepScaleOverride", initial)
        self.assertIn("trajectory_step_scale_override=$TrajectoryStepScaleOverride", source)

    def test_static_provider_failure_blocks_all_flights(self):
        result = self._run_field_dispatch(fail_provider=True)
        self.assertEqual((result["provider"], result["flights"]), (1, 0))
        self.assertIn("flight blocked", result["caught"])

    def test_static_same_mirror_reuses_actual_center_field_without_solve(self):
        result = self._run_field_dispatch(same_mirror=True)
        self.assertEqual(result["caught"], "")
        self.assertEqual((result["provider"], result["flights"]), (0, 2))
        self.assertEqual(result["bindings"][0], result["bindings"][1])
        self.assertTrue(result["bindings"][0].endswith("center_binding.json"))

    def test_static_mismatched_selected_center_ps_never_flies(self):
        result = self._run_field_dispatch(mismatched_handoff=True)
        self.assertEqual((result["provider"], result["flights"]), (0, 0))
        self.assertIn("different P/S", result["caught"])

    def test_native_te1_dispatches_before_flight_and_transports_geometry_review(self):
        result = self._run_field_dispatch(native=True)
        self.assertEqual(result["caught"], "")
        self.assertEqual((result["provider"], result["flights"]), (1, 2))

    def test_native_same_mirror_reuses_the_actual_flown_field(self):
        result = self._run_field_dispatch(native=True, same_mirror=True)
        self.assertEqual(result["caught"], "")
        self.assertEqual((result["provider"], result["flights"]), (0, 2))

    def test_native_same_mirror_old_default_not_registered_in_cache(self):
        result = self._run_field_dispatch(native=True, same_mirror=True, same_numerics=False)
        self.assertEqual(result["caught"], "")
        self.assertEqual((result["provider"], result["flights"]), (1, 2))
        self.assertEqual(result["bindings"], ["candidate-field.json", "candidate-field.json"])

    def test_native_reclosure_reuses_existing_seed_entry_without_old_columns_or_prior(self):
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 required")
        source = RUNNER.read_text(encoding="utf-8-sig")
        helper = source[source.index("function Invoke-Te1WorkpointReclosure {"):
                        source.index("function Read-CompletedTe1WorkpointReclosure {")]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / "runs" / "reclose" / "results"
            results.mkdir(parents=True)
            materialization = root / "two_prism_trial_materialization.json"
            binding = root / "root_field.json"
            binding.write_text(json.dumps({"parent": {"manifest": "actual-parent-manifest"}}), encoding="utf-8")
            request = root / "request.json"
            request.write_text(json.dumps({"source_binding_path": "old-field", "run_id": "old-run"}), encoding="utf-8")
            materialization.write_text(json.dumps({"trajectory_profile": {
                "base_profile_id": "center_screening", "maximum_step_us": 0.0005,
            }, "field_binding": {"path": str(binding)},
                "stripe_biases_v": [-27, 54], "prism_voltages_v": [189, -189]}), encoding="utf-8")
            contract = root / "contract.json"
            contract.write_text(json.dumps({"simion": {"trajectory_profiles": {
                "center_screening": {"maximum_step_us": 0.002},
            }}}), encoding="utf-8")
            (results / "best_physical_workpoint_handoff.json").write_text(json.dumps({
                "status": "within_tolerance", "qualification": "candidate_bunch_screening_authorized"}), encoding="utf-8")
            script = ("Set-StrictMode -Version Latest;$ErrorActionPreference='Stop';\n" + helper
                      + "function New-StageRunId {param($Activity,$Scope,$Subject) 'reclose'};"
                      f"function Get-ManifestOutputPath {{param($ManifestPath,$FileName) '{materialization}'}};"
                      "function Assert-Manifest {param($RunPath,$Status,$Mode) if($Status-ne'success'){throw 'bad status'} 'manifest'};"
                      "function Read-CompletedTe1WorkpointReclosure {param($RunPath,$Variation) @{run=$RunPath}};"
                      "function Write-RunJson {param($Path,$Depth,$Value) $Value|ConvertTo-Json -Depth $Depth|Set-Content $Path};"
                      f"$artifactRoot='{str(root).replace(chr(39), chr(39)*2)}';"
                      f"$package=@{{input_dir='{root}'}};$staticFieldRepresentation='native_static_pa';"
                      "$TrajectoryStepScaleOverride=$null;$staticFieldMode=$true;$SimionExe='';$python='python';$sourceYOffsetMm=0;"
                      "$PrismControllerPolicyPath='';"
                      "$NativeCorridorBankRunPath='';$NativeSystemRuntimeBundlePath='';"
                      "$GeometryReviewRunPath='geometry';$MirrorRunPath='mirror';$StripeRunPath='stripe';"
                      "$AcceleratorProviderReceiptPath='oa';$AcceleratorYAnchorMm=-55;"
                      f"$FieldProviderRequestPath='{request}';$CenterSourceReceiptPath='center-receipt';"
                      "$workpointRunner={param($SeedTrialManifest,$MirrorVoltageVariationPath,$GeometryReviewRunPath,$MirrorRunPath,$StripeRunPath,$AcceleratorProviderReceiptPath,$AcceleratorYAnchorMm,$AcceleratorSourceYOffsetMm,$ContractPath,$RunId,$PythonExe,$FieldProviderRequestPath,$CenterSourceReceiptPath,$TrajectoryProfileId,$TrajectoryStepScale) $global:received=$PSBoundParameters};"
                      f"Invoke-Te1WorkpointReclosure -Attempt 1 -SeedManifest selected-actual-child -Variation absolute-target -CurrentContractPath '{contract}' -RuntimeCheckpoint ''|Out-Null;"
                      "$received|ConvertTo-Json -Compress")
            completed = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", script],
                                       cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            received = json.loads(completed.stdout)
            self.assertEqual(received["SeedTrialManifest"], "selected-actual-child")
            self.assertEqual(received["MirrorVoltageVariationPath"], "absolute-target")
            actual_request = json.loads(Path(received["FieldProviderRequestPath"]).read_text(encoding="utf-8-sig"))
            self.assertEqual(actual_request["source_binding_path"], str(binding))
            self.assertEqual(actual_request["source_field_manifest"], "actual-parent-manifest")
            self.assertEqual(actual_request["mirror_reference_trial_manifest"], "selected-actual-child")
            self.assertEqual(actual_request["mirror_voltage_variation_path"], "absolute-target")
            self.assertEqual(actual_request["numerical_contract_path"], str(contract))
            self.assertEqual(actual_request["candidate_voltages_v"], {"s1": -27, "s2": 54, "p1": 189, "p2": -189})
            self.assertNotIn("run_id", actual_request)
            self.assertEqual(received["TrajectoryProfileId"], "center_screening")
            self.assertEqual(received["TrajectoryStepScale"], 0.25)
            self.assertFalse(set(received) & {"NativeRuntimeCheckpoint", "InitialWorkpointManifest",
                                            "PriorPrismDecisionManifest", "StripeColumnTrialManifests"})

    def test_native_provider_failure_never_flies(self):
        result = self._run_field_dispatch(native=True, fail_provider=True)
        self.assertEqual((result["provider"], result["flights"]), (1, 0))
        self.assertIn("flight blocked", result["caught"])

    def test_static_provider_role_selects_only_the_existing_runner(self):
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 required")
        source = RUNNER.read_text(encoding="utf-8-sig")
        start = source.index("  switch($fieldProviderRequest.role)")
        end = source.index("  if($fieldProviderRequest.ContainsKey", start)
        for role, expected in (("mrtof_native_static_field_provider_request", "native_static_pa"),
                               ("mrtof_same_mesh_field_provider_request", "comsol_static_scalar_v"),
                               ("unknown", None)):
            script = ("Set-StrictMode -Version Latest;$ErrorActionPreference='Stop';"
                      "$staticFieldRepresentation='comsol_static_scalar_v';$fieldProviderRunner='comsol';"
                      f"$fieldProviderRequest=@{{role='{role}'}};$PSScriptRoot='.';$caught='';try{{\n"
                      + source[start:end] + "}catch{$caught=$_.Exception.Message};"
                      "@{mode=$staticFieldRepresentation;runner=$fieldProviderRunner;caught=$caught}|ConvertTo-Json -Compress")
            result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", script],
                                    cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
                                    timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            if expected is None:
                self.assertIn("Unsupported", value["caught"])
            else:
                self.assertEqual(value["mode"], expected)
                self.assertEqual(value["caught"], "")
                if expected == "native_static_pa":
                    self.assertIn("run_native_static_field_provider.ps1", value["runner"])

    def _native_evidence_authority(self, mutation=None, *, rebased=False, strict_numerics=False):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import static_field_binding as fields
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import corridor_field_provider as provider
        source_code = RUNNER.read_text(encoding="utf-8-sig")
        helper = source_code.split("function Assert-NativeStaticFieldBinding {", 1)[1].split("\nfunction ", 1)[0]
        code = helper.split("$code=@'\n", 1)[1].split("\n'@", 1)[0]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            origin_path, actual_path = root / "origin.json", root / "actual.json"
            origin_path.write_text("{}", encoding="utf-8")
            other = root / "other.json"
            other.write_text('{"other":true}', encoding="utf-8")
            source = {"mode": "native_static_pa", "manifest": str(root / "origin_manifest.json"),
                      "authority": {"analyzer_electrode_voltages_v": [0] * 20},
                      "geometry": {"physical": "same"}, "grid": {"pitch_mm": [0.5, 1, 1]},
                      "native_solver_numerics": {"boundary_mode": "grounded_enclosure", "solver": "SIMION2020", "surface": "fractional", "refine_stopping": "installed_default"},
                      "refinement_windows": [{"name": "window", "grid": {"pitch_mm": [0.25, 0.25, 0.2]},
                                              "native_solver_numerics": {"boundary_mode": "x_mirror_five_faces", "solver": "SIMION2020", "surface": "fractional", "refine_stopping": "installed_default"},
                                              "active_box_mm": [[-20, 20], [-99, 389], [-324, 324]]}],
                      "instances": [{"role": name, "origin_mm": [0, 0, 0], "record": {"bytes": 1, "sha256": name}}
                                    for name in ("global_fallback", "native_corridor", "accelerator", "detector")]}
            values = [-27, 54, 191, -190]
            expected = provider.candidate_authority(source["authority"], dict(zip(("s1", "s2", "p1", "p2"), values)),
                                                    mirror_voltages_v=[0, 1, 2, 3, 4])
            actual = copy.deepcopy(source)
            actual.update(authority=expected, manifest=str(root / "run_manifest.json"))
            numerical_contract = root / "numerical.json"
            numerical_contract.write_text(json.dumps({"simion": {"numerical_profiles": {"native_static_field": {
                "refine": {"convergence_v": 1e-5}}}}}), encoding="utf-8")
            if strict_numerics:
                for level in (actual, *actual["refinement_windows"]):
                    level["native_solver_numerics"].update(refine_stopping="contract_convergence", convergence_v=1e-5)
            if mutation == "voltage":
                actual["authority"] = copy.deepcopy(expected)
                actual["authority"]["analyzer_electrode_voltages_v"][18] = 1
            elif mutation == "grid":
                actual["grid"]["pitch_mm"][1] = 0.5
            elif mutation == "collision":
                actual["instances"][2]["record"]["sha256"] = "different"
            elif mutation == "geometry":
                actual["geometry"]["physical"] = "different"
            elif mutation in ("surface", "boundary"):
                key = "surface" if mutation == "surface" else "boundary_mode"
                actual["refinement_windows"][0]["native_solver_numerics"][key] = "different"
            elif mutation == "stopping":
                actual["refinement_windows"][0]["native_solver_numerics"]["convergence_v"] = 1e-7
            request = {"schema_version": 1, "role": "mrtof_native_static_field_provider_request",
                       "source_binding_path": str(origin_path), "source_field_manifest": source["manifest"]}
            provider_source = copy.deepcopy(source)
            if rebased:
                provider_source["manifest"] = str(root / "current_anchor_manifest.json")
                provider_source["authority"] = provider.candidate_authority(source["authority"],
                    {"s1": -26, "s2": 53, "p1": 189, "p2": -189}, mirror_voltages_v=[0, 1, 2, 3, 4])
            if mutation == "source":
                provider_source["geometry"]["physical"] = "different"
            elif mutation == "source_grid":
                provider_source["refinement_windows"][0]["grid"]["pitch_mm"][2] = 0.25
            elif mutation == "source_collision":
                provider_source["instances"][2]["record"]["sha256"] = "different"
            request_path = root / "request.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            frozen = root / "frozen_request.json"
            frozen_source = root / "source_binding.json"
            provider_path = other if rebased or mutation == "source" else origin_path
            frozen_source.write_bytes(provider_path.read_bytes())
            frozen.write_text(json.dumps(dict(request, source_binding_path=str(provider_path),
                source_field_manifest=provider_source["manifest"],
                candidate_voltages_v=dict(zip(("s1", "s2", "p1", "p2"), values)),
                mirror_reference_trial_manifest="fixed-original-reference",
                mirror_voltage_variation_path="absolute-variation")), encoding="utf-8")
            (root / "run_config.json").write_text(json.dumps({"inputs": {
                "request": str(frozen), "source_binding": str(frozen_source)}}), encoding="utf-8")
            def derive(q, authority):
                self.assertEqual(q["candidate_voltages_v"], dict(zip(("s1", "s2", "p1", "p2"), values)))
                self.assertEqual(q["mirror_reference_trial_manifest"], "fixed-original-reference")
                self.assertEqual(q["mirror_voltage_variation_path"], "absolute-variation")
                return provider.candidate_authority(authority, q["candidate_voltages_v"],
                                                    mirror_voltages_v=[0, 1, 2, 3, 4]), {}
            if mutation == "source_voltage":
                provider_source["authority"]["analyzer_electrode_voltages_v"][18] = 1
            def load(path):
                return copy.deepcopy(source if path == origin_path else
                                     provider_source if path == frozen_source else actual)
            with patch.object(fields, "load_binding", side_effect=load), \
                    patch.object(fields, "_record") as record, patch.object(provider, "derive_candidate_authority", side_effect=derive), \
                    patch.object(sys, "argv", ["check", str(actual_path), str(request_path), json.dumps(values),
                                               "absolute-variation", "active-contract", "fixed-original-reference",
                                               str(numerical_contract) if strict_numerics else ""]):
                exec(compile(code, str(RUNNER), "exec"), {})
                self.assertEqual(record.call_args_list, [
                    unittest.mock.call(Path(actual["manifest"]), frozen),
                    unittest.mock.call(Path(actual["manifest"]), frozen_source)])

    def test_native_evidence_reuses_real_authority_and_sealed_provider_request(self):
        self._native_evidence_authority()

    def test_native_evidence_accepts_sealed_staged_current_anchor_source(self):
        self._native_evidence_authority(rebased=True)

    def test_native_evidence_accepts_only_contract_owned_stopping_change(self):
        self._native_evidence_authority(strict_numerics=True)
        self._native_evidence_authority(rebased=True, strict_numerics=True)
        for mutation in ("grid", "geometry", "collision", "surface", "boundary", "stopping"):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self._native_evidence_authority(mutation, strict_numerics=True)

    def test_native_evidence_rejects_full_voltage_geometry_grid_collision_and_source_mismatch(self):
        for mutation in ("voltage", "geometry", "grid", "collision", "source",
                         "source_grid", "source_collision", "source_voltage"):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self._native_evidence_authority(mutation)

    def _selected_manifest_from_real_lineage_schema(self, *, corrupt_output=False, duplicate=False, seed_only=False):
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 required")
        source = RUNNER.read_text(encoding="utf-8-sig")
        def helper(name):
            start = source.index("function " + name + " {")
            end = source.find("\nfunction ", start + 1)
            return source[start:end if end >= 0 else len(source)]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "results").mkdir()
            bindings = [root / "other_binding.json", root / "selected_binding.json"]
            for path in bindings:
                path.write_text("{}", encoding="utf-8")
            children = []
            selected_manifest = None
            for ordinal, binding in enumerate(bindings, 1):
                child = root / f"child{ordinal}"
                child.mkdir()
                materialization = child / "two_prism_trial_materialization.json"
                materialization.write_text(json.dumps({"field_binding": {"mode": "native_static_pa",
                    "path": str(bindings[1] if duplicate else binding)}}), encoding="utf-8")
                manifest = child / "run_manifest.json"
                manifest.write_text(json.dumps({"outputs": [{"path": str(materialization),
                    "sha256": hashlib.sha256(materialization.read_bytes()).hexdigest()}]}), encoding="utf-8")
                children.append({"iteration": ordinal, "child_manifest": str(manifest),
                                 "child_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()})
                if ordinal == 2:
                    selected_manifest = manifest
                    if corrupt_output:
                        materialization.write_text("{}", encoding="utf-8")
            lineage = root / "results" / "iteration_lineage.json"
            lineage.write_text(json.dumps({"children": [] if seed_only else children,
                **({"root_workpoint_manifest": {"path": str(selected_manifest),
                    "sha256": hashlib.sha256(selected_manifest.read_bytes()).hexdigest()}} if seed_only else {})}), encoding="utf-8")
            (root / "run_manifest.json").write_text(json.dumps({"outputs": [{"path": str(lineage),
                "sha256": hashlib.sha256(lineage.read_bytes()).hexdigest()}]}), encoding="utf-8")
            handoff = {"selected_history_ordinal": 2, "selected_workpoint": {
                "field_binding": {"mode": "native_static_pa", "path": str(bindings[1])}}}
            script = ("Set-StrictMode -Version Latest;$ErrorActionPreference='Stop';$staticFieldMode=$true;\n"
                      + helper("Test-SameResolvedPath") + helper("Get-ManifestOutputPath")
                      + helper("Get-QualifiedCenterSeedManifest")
                      + f"$handoff=ConvertFrom-Json -AsHashtable @'\n{json.dumps(handoff)}\n'@;"
                      + "$caught='';$selected='';try{"
                      + f"$selected=Get-QualifiedCenterSeedManifest -WorkpointRun '{str(root)}' -Handoff $handoff"
                      + "}catch{$caught=$_.Exception.Message};@{selected=$selected;caught=$caught}|ConvertTo-Json -Compress")
            result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", script],
                                    cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout), str(selected_manifest)

    def test_selected_native_child_uses_manifest_output_not_missing_lineage_materialization(self):
        result, expected = self._selected_manifest_from_real_lineage_schema()
        self.assertEqual(result["caught"], "")
        self.assertEqual(Path(result["selected"]), Path(expected))

    def test_noop_reclosure_identifies_its_actual_root_seed_without_fabricating_child(self):
        result, expected = self._selected_manifest_from_real_lineage_schema(seed_only=True)
        self.assertEqual(result["caught"], "")
        self.assertEqual(Path(result["selected"]), Path(expected))

    def test_te1_reclosure_uses_each_actual_screened_center_not_the_old_qualified_seed(self):
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("[string]$focused.result.cohort_run_manifest", source)
        self.assertIn("[string]$remeasured.result.cohort_run_manifest", source)
        self.assertIn("return Read-CompletedTe1WorkpointReclosure -RunPath $childRun -Variation $Variation", source)

    def test_selected_native_child_rejects_changed_materialization_or_duplicate_matches(self):
        result, _ = self._selected_manifest_from_real_lineage_schema(corrupt_output=True)
        self.assertIn("hash differs", result["caught"])
        result, _ = self._selected_manifest_from_real_lineage_schema(duplicate=True)
        self.assertIn("one actual centre", result["caught"])

    def test_best_focused_fallback_preserves_actual_field_for_final_cohort(self):
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 is required for fallback behavior fixture")
        source = RUNNER.read_text(encoding="utf-8-sig")
        start = source.index("  if(-not$focusConverged-and$null-ne$bestFocused){")
        end = source.index("  $failureStage='te1_final_n100'", start)
        script = (
            "Set-StrictMode -Version Latest;$ErrorActionPreference='Stop';"
            "$focusConverged=$false;$bestFocused=@{envelope_available=$true;field_binding='best-actual-field'};"
            "$focused=@{field_binding='latest-rejected-field'};"
            "$bestRootDiagnostic='best-diagnostic';$bestRootFocusDiagnostic='best-focus';$bestRootCoordinate=1;"
            "$bestRootVariation='best-variation';$bestWorkpointRun='best-workpoint';"
            "$bestWorkpointManifest='best-manifest';$bestHandoff=@{};"
            "$bestNativeRuntimeCheckpoint='';$bestFocusContractPath='best-contract';$bestFocusContract=@{};"
            "$bestQualifiedCenterSeedManifest='best-center';\n" + source[start:end]
            + "@{binding=$selectedEnvelope.field_binding;variation=$rootVariation;workpoint=$workpointRun;center=$qualifiedCenterSeedManifest}|ConvertTo-Json -Compress"
        )
        completed = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", script],
                                   cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout),
                         {"binding": "best-actual-field", "variation": "best-variation",
                          "workpoint": "best-workpoint", "center": "best-center"})


    def _static_evidence_binding(self, *, stale_source=False, wrong_selected_binding=False,
                                 selected_center_variation=False, wrong_mirror=False):
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 is required for static source identity fixtures")
        source = RUNNER.read_text(encoding="utf-8-sig")
        helpers = source[source.index("function Test-SameResolvedPath"):
                         source.index("function Read-ScreeningEvidence")]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {name: root / name for name in
                     ("source", "workpoint", "cohort", "center", "mirror", "stripe", "oa", "provider")}
            for path in paths.values():
                (path / "results").mkdir(parents=True)
                (path / "inputs").mkdir()
                (path / "run_manifest.json").write_text("{}", encoding="utf-8")
            authority = root / "authority.json"
            authority.write_text("{}", encoding="utf-8")
            original = root / "original-field.json"
            other = root / "other-mesh-field.json"
            original.write_text(json.dumps({"export_manifest": "third-mesh"}), encoding="utf-8")
            other.write_text(json.dumps({"export_manifest": "middle-mesh"}), encoding="utf-8")
            actual = root / "actual-field.json"
            actual.write_text(json.dumps({"export_manifest": str(paths["provider"] / "run_manifest.json"),
                                         "assembly_manifest": str(authority),
                                         "collision_manifest": str(authority)}), encoding="utf-8")
            (paths["provider"] / "run_config.json").write_text(json.dumps({
                "parameters": {"source_binding_path": str(other if stale_source else original)}}),
                encoding="utf-8")
            # Geometry is deliberately identical: only the saved FEM source changes.
            original.write_text(json.dumps({"export_manifest": "third-mesh",
                                           "assembly_manifest": str(authority),
                                           "collision_manifest": str(authority)}), encoding="utf-8")
            source_receipt = paths["source"] / "results" / "receipt.json"
            source_receipt.write_text("{}", encoding="utf-8")
            oa_receipt = paths["oa"] / "results" / "receipt.json"
            oa_receipt.write_text("{}", encoding="utf-8")
            contract = paths["workpoint"] / "inputs" / "contract.json"
            contract.write_text("{}", encoding="utf-8")
            variation = root / "variation.json"
            variation.write_text(json.dumps({"target_mirror_voltages_v": [0, 1, 2, 3, 4]}),
                                 encoding="utf-8")
            (paths["workpoint"] / "run_config.json").write_text(json.dumps({
                "inputs": {} if selected_center_variation else {"terminal_time_mirror_voltage_variation": str(variation)},
                "parameters": {}}), encoding="utf-8")
            (paths["workpoint"] / "results" / "best_physical_workpoint_handoff.json").write_text(
                json.dumps({"selected_workpoint": {"voltages_v": [-27, 54, 191, -190]}}),
                encoding="utf-8")
            (paths["center"] / "run_config.json").write_text(json.dumps({"inputs": {
                "mirror_run_manifest": str(paths["mirror"] / "run_manifest.json"),
                "stripe_run_manifest": str(paths["stripe"] / "run_manifest.json"),
                "terminal_time_mirror_voltage_variation": str(variation)}}), encoding="utf-8")
            cohort_variation = root / "cohort_variation.json"
            cohort_variation.write_text(json.dumps({"target_mirror_voltages_v":
                [0, 1, 2, 3, 5] if wrong_mirror else [0, 1, 2, 3, 4]}), encoding="utf-8")
            (paths["cohort"] / "run_config.json").write_text(json.dumps({"inputs": {
                "static_field_binding": str(actual),
                "bunch_source_run_manifest": str(paths["source"] / "run_manifest.json"),
                "mirror_run_manifest": str(paths["mirror"] / "run_manifest.json"),
                "stripe_run_manifest": str(paths["stripe"] / "run_manifest.json"),
                "accelerator_run_manifest": str(paths["oa"] / "run_manifest.json"),
                "trajectory_contract": str(contract),
                "terminal_time_mirror_voltage_variation": str(cohort_variation)}}), encoding="utf-8")
            (paths["cohort"] / "summary.json").write_text(json.dumps({
                "stripe_biases_v": [-27, 54], "prism_voltages_v": [191, -190]}), encoding="utf-8")
            quote = lambda path: str(path).replace("'", "''")
            script = (
                "Set-StrictMode -Version Latest;$ErrorActionPreference='Stop';$staticFieldMode=$true;$staticFieldRepresentation='comsol_static_scalar_v';\n"
                + helpers
                + "function Get-QualifiedCenterSeedManifest {param($WorkpointRun,$Handoff) return $centerManifest}\n"
                + f"$centerManifest='{quote(paths['center'] / 'run_manifest.json')}';"
                + f"$AcceleratorProviderReceiptPath='{quote(oa_receipt)}';"
                + f"$fieldProviderRequest=@{{source_binding_path='{quote(original)}'}};"
                + "$caught='';try {"
                + f"Assert-ScreeningEvidenceBinding -CohortRun '{quote(paths['cohort'])}' "
                + f"-ExpectedWorkpointRun '{quote(paths['workpoint'])}' "
                + f"-ExpectedSourceReceipt '{quote(source_receipt)}' -ExpectedNativeBankRun '' "
                + f"-ExpectedVariation '{'' if selected_center_variation else quote(variation)}' "
                + f"-ExpectedFieldBindingPath '{quote(other if wrong_selected_binding else actual)}'"
                + "} catch {$caught=$_.Exception.Message};@{caught=$caught}|ConvertTo-Json -Compress"
            )
            completed = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", script],
                                       cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            return json.loads(completed.stdout)["caught"]

    def test_static_resume_accepts_actual_candidate_from_current_fem_source(self):
        self.assertEqual(self._static_evidence_binding(), "")

    def test_static_resume_rejects_other_fem_mesh_even_with_same_geometry_and_voltages(self):
        self.assertIn("different FEM source binding", self._static_evidence_binding(stale_source=True))

    def test_static_final_resume_requires_the_exact_selected_envelope_binding(self):
        self.assertIn("different actual static field", self._static_evidence_binding(wrong_selected_binding=True))

    def test_static_resume_inherits_selected_child_variation_not_missing_parent_key(self):
        self.assertEqual(self._static_evidence_binding(selected_center_variation=True), "")
        self.assertIn("different mirror voltages", self._static_evidence_binding(
            selected_center_variation=True, wrong_mirror=True))

    def test_static_workpoint_requires_canonical_runtime_not_workflow_and_keeps_copy_guard(self):
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 required")
        source = RUNNER.read_text(encoding="utf-8-sig")
        start = source.index("function Assert-WorkpointPhysicalBinding {")
        function = source[start:source.index("function Assert-ScreeningEvidenceBinding", start)]
        same_start = source.index("function Test-SameResolvedPath {")
        same = source[same_start:source.index("function ", same_start + 9)]
        output_start = source.index("function Get-ManifestOutputPath {")
        output_helper = source[output_start:source.index("function ", output_start + 9)]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "results").mkdir()
            request = root / "request.json"
            source_binding = root / "source_binding.json"
            source_binding.write_text("{}", encoding="utf-8")
            request.write_text(json.dumps({"source_binding_path": str(source_binding)}), encoding="utf-8")
            receipt = root / "receipt.json"
            owner = root / "component_focus_workflow_receipt.json"
            owner.write_text("{}", encoding="utf-8")
            (root / "wrong.json").write_text("{}", encoding="utf-8")
            (root / "run_manifest.json").write_text("{}", encoding="utf-8")
            receipt.write_text(json.dumps({"provider_workflow_receipt": {
                "path": str(owner), "bytes": owner.stat().st_size,
                "sha256": hashlib.sha256(owner.read_bytes()).hexdigest()}}), encoding="utf-8")
            runtime = root / "mrtof_runtime_receipt.json"
            runtime.write_bytes(receipt.read_bytes())
            provider_manifest = root / "provider_manifest.json"
            provider_manifest.write_text(json.dumps({"outputs": [{"path": str(runtime),
                "sha256": hashlib.sha256(runtime.read_bytes()).hexdigest()}]}), encoding="utf-8")
            (root / "run_config.json").write_text(json.dumps({"parameters": {
                "corridor_field": "native_static_pa"}, "inputs": {
                "field_provider_request": str(request), "accelerator_provider_receipt": str(receipt),
                "accelerator_run_manifest": str(provider_manifest),
                "mirror_run_manifest": str(root / "run_manifest.json"),
                "stripe_run_manifest": str(root / "run_manifest.json")}}), encoding="utf-8")
            (root / "results" / "best_physical_workpoint_handoff.json").write_text("{}", encoding="utf-8")
            script = ("Set-StrictMode -Version Latest;$ErrorActionPreference='Stop';"
                "$staticFieldMode=$true;$staticFieldRepresentation='native_static_pa';"
                "$fieldProviderRequest=@{source_binding_path='" + str(source_binding) + "'};\n" + same + output_helper + function
                + "function Get-QualifiedCenterSeedManifest {param($WorkpointRun,$Handoff) Join-Path $WorkpointRun 'run_manifest.json'};"
                + "$outcomes=@();foreach($owner in @('" + str(runtime) + "','" + str(owner) + "','" + str(root / "wrong.json") + "')){"
                + "$caught='';try{Assert-WorkpointPhysicalBinding -WorkpointRun '" + str(root)
                + "' -ExpectedGeometryRun '" + str(root) + "' -ExpectedMirrorRun '" + str(root)
                + "' -ExpectedStripeRun '" + str(root) + "' -ExpectedProviderReceipt $owner"
                + "}catch{$caught=$_.Exception.Message};$outcomes+=,$caught};"
                + "Set-Content -LiteralPath '" + str(receipt) + "' -Value '{}';$caught='';try{"
                + "Assert-WorkpointPhysicalBinding -WorkpointRun '" + str(root)
                + "' -ExpectedGeometryRun '" + str(root) + "' -ExpectedMirrorRun '" + str(root)
                + "' -ExpectedStripeRun '" + str(root) + "' -ExpectedProviderReceipt '" + str(runtime)
                + "'}catch{$caught=$_.Exception.Message};$outcomes+=,$caught;ConvertTo-Json -InputObject $outcomes -Compress")
            result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", script],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            outcomes = json.loads(result.stdout)
            self.assertEqual(outcomes[0], "")
            self.assertIn("different accelerator provider authority", outcomes[1])
            self.assertIn("different accelerator provider authority", outcomes[2])
            self.assertIn("differs from the actually flown receipt", outcomes[3])

    def test_te1_reference_is_frozen_separately_from_original_request(self):
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 is required for reference freezing fixture")
        source = RUNNER.read_text(encoding="utf-8-sig")
        start = source.index("  if($staticFieldMode){\n    if(-not$mirrorReferenceTrialManifest)")
        end = source.index("  # The accepted centre child", start)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "original_request.json"
            original.write_text('{"source_binding_path":"original-source"}', encoding="utf-8")
            config = root / "run_config.json"
            config.write_text('{"inputs":{}}', encoding="utf-8")
            quote = lambda path: str(path).replace("'", "''")
            script = (
                "Set-StrictMode -Version Latest;$ErrorActionPreference='Stop';"
                "function Write-RunJson {param($Path,$Depth,$Value) $Value|ConvertTo-Json -Depth $Depth|Set-Content $Path};"
                f"$package=@{{input_dir='{quote(root)}';run_config='{quote(config)}'}};"
                f"$FieldProviderRequestPath='{quote(original)}';"
                "$fieldProviderRequest=Get-Content $FieldProviderRequestPath -Raw|ConvertFrom-Json -AsHashtable;"
                "$staticFieldMode=$true;$mirrorReferenceTrialManifest='';$qualifiedCenterSeedManifest='initial-reference';\n"
                + source[start:end]
                + "Get-Content $FieldProviderRequestPath -Raw"
            )
            completed = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", script],
                                       cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            request = json.loads(completed.stdout)
            self.assertEqual(request["mirror_reference_trial_manifest"], "initial-reference")
            self.assertEqual(json.loads(original.read_text(encoding="utf-8")),
                             {"source_binding_path": "original-source"})
            frozen_config = json.loads(config.read_text(encoding="utf-8-sig"))
            self.assertTrue(frozen_config["inputs"]["te1_field_provider_request"].endswith(
                "te1_field_provider_request.json"))

if __name__ == "__main__":
    unittest.main()
