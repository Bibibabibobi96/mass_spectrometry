from __future__ import annotations

from pathlib import Path
import json
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import copy
import sys


REPO_ROOT = Path(__file__).resolve().parents[4]
RUNNER = Path(__file__).resolve().parents[2] / "analysis" / "run_native_corridor_bunch_screening.ps1"


class NativeCorridorBunchScreeningRunnerTest(unittest.TestCase):
    def test_screening_runs_one_static_cohort_from_checkpointed_family(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "Open-NativeCorridorRuntimeCheckpoint -Session $nativeRuntimeSession",
            "NativeCorridorRuntimeSession=$nativeRuntimeSession",
            "NativeSystemRuntimeBundlePath=$nativeSystemRuntimeBundlePath",
            "[string]$InitialCohortRunPath=''",
            "[ValidateSet(3,13,100,1000)][int]$CohortParticleCount=1000",
            "$cohortRunId=New-CohortRunId",
            "BunchParticleIdMax=$CohortParticleCount",
            "RetainGuiWorkbench=$true",
            "[string]$MirrorVoltageVariationPath=''",
            "$cohortArguments.MirrorVoltageVariationPath=$mirrorVoltageVariation",
            "one_checkpointed_native_fast_adjust_family__no_pa_copy_or_refine",
            "accelerator_field_mode='static'",
            "Suspend-NativeCorridorRuntimeSession -Session $nativeRuntimeSession",
        ):
            self.assertIn(token, source)
        self.assertNotIn("New-NativeCorridorRuntimeFamily", source)
        self.assertEqual(source.count("RetainGuiWorkbench=$true"), 1)
        self.assertNotIn("AcceleratorPulseSchedulePath", source)
        self.assertNotIn("run_freeze_bunch_pulse_schedule.ps1", source)

    def test_workpoint_mirror_variation_is_inherited_when_not_explicit(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn(
            "$mirrorInputs.terminal_time_mirror_voltage_variation",
            source,
        )
        self.assertIn(
            "$cohortArguments.MirrorVoltageVariationPath=$mirrorVoltageVariation",
            source,
        )

    def test_controlled_diagnostic_sizes_are_explicit(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("[switch]$FocusDiagnosticOnly", source)
        self.assertIn(
            "[ValidateSet('','focus_z','slow_energy','controlled_aberration')]",
            source,
        )
        self.assertIn(
            "$requiredDiagnosticCount = if($DiagnosticPurpose -eq 'controlled_aberration'){13}",
            source,
        )
        self.assertIn(
            "focus_z/slow_energy use N=3 and controlled_aberration uses N=13.",
            source,
        )

    def test_numerical_probe_can_override_only_the_trajectory_step_scale(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("[Nullable[double]]$TrajectoryStepScaleOverride=$null", source)
        self.assertIn("TrajectoryStepScaleOverride must be finite and positive.", source)
        self.assertIn(
            "TrajectoryStepScale=$(if($null-eq$trajectoryStepScale){[double]$problem.trajectory_step_scale}else{$trajectoryStepScale})",
            source,
        )

    def test_source_center_y_must_match_workpoint_accelerator_pose(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("$contractData.accelerator.focus_y_anchor.project_y_mm", source)
        self.assertIn("$sourceData.nominal_center_state.position_workbench_mm[1]", source)
        self.assertIn("source centre does not match the workpoint accelerator y pose", source)

    def test_native_bunch_flights_forward_only_the_bound_system_bundle(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("Workpoint has no native system runtime bundle identity.", source)
        self.assertIn("NativeSystemRuntimeBundlePath=$nativeSystemRuntimeBundlePath", source)
        self.assertIn("Workpoint must bind an OA accelerator provider receipt.", source)
        self.assertIn("$cohortArguments.AcceleratorProviderReceiptPath=$providerReceipt", source)
        self.assertNotIn("AcceleratorRunPath", source)
        self.assertIn("$centerConfig.inputs.accelerator_run_manifest", source)
        self.assertNotIn("LocalWorkbenchRunPath=[string]$problem.local_workbench", source)

    def test_bunch_flights_reuse_the_workpoint_frozen_contract(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("$workpointContract=(Resolve-Path -LiteralPath (Join-Path $workpointRun 'inputs\\contract.json')).Path", source)
        self.assertIn("Workpoint frozen contract identity differs from its physical-problem identity.", source)
        self.assertEqual(source.count("ContractPath=$workpointContract"), 1)

    def test_legacy_warning_handoff_is_reselected_from_verified_history(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("if($handoffData.status-ne'within_tolerance')", source)
        self.assertIn("Get-VerifiedManifestOutput -ManifestPath $workpointManifest -Name 'iteration_history.json'", source)
        self.assertIn("--select-best-physical-workpoint','--history',$history", source)
        self.assertIn("$handoffData.status-ne'within_tolerance'", source)

    def test_verified_initial_static_cohort_can_resume_without_reflight(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("if($null-ne$initialCohortRun)", source)
        self.assertIn(
            "$cohortSummary.source_cohort.mother_particle_count-ne[int]$sourceData.mother_particle_count",
            source,
        )
        self.assertNotIn(
            "$cohortSummary.source_cohort.mother_particle_count-ne[int]$sourceData.particle_count",
            source,
        )
        self.assertIn("source_cohort.selection.parent_particle_states_sha256", source)
        self.assertIn("$cohortVoltages=@($cohortSummary.stripe_biases_v)+@($cohortSummary.prism_voltages_v)", source)
        self.assertIn("Cohort run does not bind the requested source, workpoint voltages, and static accelerator mode.", source)
        self.assertLess(source.index("if($null-ne$initialCohortRun)"), source.index("& $trialRunner @cohortArguments"))
        self.assertNotIn("New-ShortPaCopy", source)

    def test_incomplete_cohort_can_use_common_batch_continuation(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "[string]$CohortBatchContinuationRunPath=''",
            "$cohortArguments.BatchContinuationRunPath=$CohortBatchContinuationRunPath",
        ):
            self.assertIn(token, source)

    def test_static_cohort_collection_gate_is_the_only_downstream_gate(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("stop_below_collection_hard_minimum", source)
        self.assertIn("[bool]$cohortGateData.hard_stop", source)
        self.assertNotIn("pilotGate", source)

    def test_cohort_run_id_keeps_revision_at_the_end(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("function New-CohortRunId", source)
        self.assertIn("$cohortRunId=New-CohortRunId", source)
        self.assertNotIn('$RunId+"__n$CohortParticleCount-static"', source)


    def _selected_static_center(self, *, mismatch=False, duplicate=False, manifest_only=False):
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 is required for selected-centre fixtures")
        source = RUNNER.read_text(encoding="utf-8-sig")
        start = source.index("function Read-SelectedStaticCenter {")
        helper = source[start:source.index("\nfunction ", start + 1)]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "results").mkdir()
            children = []
            bindings = []
            for index in (1, 2):
                child = root / f"child{index}"
                (child / "results").mkdir(parents=True)
                binding = child / "field_binding.json"
                binding.write_text("{}", encoding="utf-8")
                bindings.append(binding)
                materialization = child / "results" / "two_prism_trial_materialization.json"
                materialization.write_text(json.dumps({
                    "field_binding": {"mode": "native_static_pa" if manifest_only else "comsol_static_scalar_v", "path": str(binding)},
                    "stripe_biases_v": [-27, 54], "prism_voltages_v": [191 + index, -190],
                }), encoding="utf-8")
                (child / "run_config.json").write_text(json.dumps({"selected_child": index}),
                                                       encoding="utf-8")
                (child / "run_manifest.json").write_text("{}", encoding="utf-8")
                children.append({"child_manifest": str(child / "run_manifest.json")})
                if not manifest_only:
                    children[-1]["materialization"] = str(materialization)
            if duplicate:
                children.append(children[0])
            (root / "results" / "iteration_lineage.json").write_text(
                json.dumps({"children": children}), encoding="utf-8")
            handoff = root / "handoff.json"
            handoff.write_text(json.dumps({"selected_history_ordinal": 1,
                "selected_workpoint": {
                    "field_binding": {"mode": "native_static_pa" if manifest_only else "comsol_static_scalar_v", "path": str(bindings[0])},
                    "voltages_v": [-27, 54, 999 if mismatch else 192, -190]}}), encoding="utf-8")
            quote = lambda path: str(path).replace("'", "''")
            script = (
                "Set-StrictMode -Version Latest;$ErrorActionPreference='Stop'\n" + helper
                + "function Assert-VerifiedManifest {param($ManifestPath,$Status,$Mode,$ConsumedOutput)}\n"
                + "function Get-VerifiedManifestOutput {param($ManifestPath,$Name) return (Join-Path (Split-Path -Parent $ManifestPath) ('results/'+$Name))}\n"
                + f"$handoff=Get-Content '{quote(handoff)}' -Raw|ConvertFrom-Json -AsHashtable;"
                + "$caught='';$selected=$null;"
                + f"try {{$selected=Read-SelectedStaticCenter -WorkpointRun '{quote(root)}' -Handoff $handoff}}"
                + " catch {$caught=$_.Exception.Message};"
                + "@{caught=$caught;child=$(if($selected){$selected.config.selected_child}else{0})}|ConvertTo-Json -Compress"
            )
            result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", script],
                                    cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

    def test_static_handoff_selects_actual_earlier_center_not_latest_field(self):
        self.assertEqual(self._selected_static_center(), {"caught": "", "child": 1})

    def test_native_handoff_resolves_manifest_only_lineage(self):
        self.assertEqual(self._selected_static_center(manifest_only=True), {"caught": "", "child": 1})

    def test_static_handoff_voltage_mismatch_blocks_selection(self):
        result = self._selected_static_center(mismatch=True)
        self.assertEqual(result["child"], 0)
        self.assertIn("different P/S", result["caught"])

    def test_static_handoff_ambiguous_child_blocks_selection(self):
        result = self._selected_static_center(duplicate=True)
        self.assertEqual(result["child"], 0)
        self.assertIn("one actual centre child", result["caught"])

    def test_static_dispatch_forwards_binding_without_native_runtime(self):
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 is required for dispatch fixture")
        source = RUNNER.read_text(encoding="utf-8-sig")
        start = source.index("  $cohortArguments=@{")
        end = source.index("  if($null-ne$mirrorVoltageVariation)", start)
        script = (
            "Set-StrictMode -Version Latest;$ErrorActionPreference='Stop';"
            "$problem=@{geometry='geometry';mirror='mirror';stripe='stripe';trajectory_profile='center_screening';trajectory_step_scale=1;source_y_offset_mm=0};"
            "$nativeSystemRuntimeBundlePath='';$bankRun='';$capacitySession=@{};"
            "$sourceReceipt='source';$CohortParticleCount=13;$workpointContract='contract';"
            "$voltages=@(-27,54,191,-190);$trajectoryStepScale=$null;$cohortRunId='cohort';$python='fixture';"
            "$staticFieldMode=$true;$FieldBindingPath='selected-actual-field';$providerReceipt='oa';\n"
            + source[start:end]
            + "$cohortArguments|ConvertTo-Json -Depth 5 -Compress"
        )
        result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", script],
                                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = json.loads(result.stdout)
        self.assertEqual(arguments["FieldBindingPath"], "selected-actual-field")
        self.assertEqual(arguments["BunchSourceReceiptPath"], "source")
        self.assertEqual(arguments["AcceleratorProviderReceiptPath"], "oa")
        self.assertNotIn("NativeCorridorBankRunPath", arguments)
        self.assertNotIn("NativeSystemRuntimeBundlePath", arguments)


    def test_native_field_mode_detection_does_not_require_static_marker(self):
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 is required for mode-detection fixture")
        source = RUNNER.read_text(encoding="utf-8-sig")
        statement = next(line for line in source.splitlines()
                         if line.startswith("$staticFieldMode="))
        script = (
            "Set-StrictMode -Version Latest;$ErrorActionPreference='Stop';$modes=@();"
            "foreach($parameters in @(@{native_recovery_problem=@{}},"
            "@{corridor_field='native_full_corridor_at_0p25_mm'},"
            "@{corridor_field='comsol_static_scalar_v'},@{corridor_field='native_static_pa'})){"
            "$workpointConfig=@{parameters=$parameters};" + statement
            + ";$modes+=@($staticFieldMode)};ConvertTo-Json -InputObject $modes -Compress"
        )
        completed = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", script],
                                   cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), [False, False, True, True])

    def _static_problem(self, *, missing_review=False, wrong_geometry=False, wrong_source=False,
                        owner_mode="resolved_engineering_cad_export", missing_geometry_key=False,
                        wrong_geometry_hash=False):
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 is required")
        source = RUNNER.read_text(encoding="utf-8-sig")
        start = source.index("function Read-StaticCenterProblem {")
        helper = source[start:source.index("\nfunction ", start + 1)]
        support = REPO_ROOT / "common/contracts/run_artifact_support.ps1"
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            review = root / "review"
            oa = root / "oa"
            review.mkdir()
            (oa / "results").mkdir(parents=True)
            geometry = root / "resolved_geometry.json"
            geometry.write_text('{"geometry":"same"}', encoding="utf-8")
            selected_geometry = root / "selected_geometry.json"
            selected_geometry.write_text('{"geometry":"different"}' if wrong_geometry else geometry.read_text(), encoding="utf-8")
            import hashlib
            geometry_key = "resolved_geometry" if owner_mode == "native_static_field_provider" else "resolved_geometry.json"
            record = {"exists": True, "path": str(geometry),
                      "sha256": "wrong" if wrong_geometry_hash else hashlib.sha256(geometry.read_bytes()).hexdigest()}
            (review / "run_manifest.json").write_text(json.dumps({
                "status": "success", "project": "parallel_mirror_dual_stripe_mr_tof", "mode": owner_mode,
                "inputs": {} if missing_geometry_key else {geometry_key: record}}), encoding="utf-8")
            binding = root / "binding.json"
            binding.write_text(json.dumps({"parent": {"geometry_authority_path": str(selected_geometry)}}), encoding="utf-8")
            receipt = oa / "results/mrtof_runtime_receipt.json"
            receipt.write_text('{"provider_workflow_receipt":{"path":"workflow"}}', encoding="utf-8")
            frozen_receipt = root / "frozen_receipt.json"
            frozen_receipt.write_bytes(receipt.read_bytes())
            mother = root / "mother.json"
            mother.write_text('{"source_y_offset_mm":0}', encoding="utf-8")
            frozen_source = root / "frozen_source.json"
            frozen_source.write_text('{"source_y_offset_mm":1}' if wrong_source else mother.read_text(), encoding="utf-8")
            contract = root / "contract.json"
            contract.write_text(json.dumps({"simion": {"trajectory_profiles": {"center_screening": {"maximum_step_us": .002}}}}), encoding="utf-8")
            selected = root / "selected.json"
            selected.write_text(json.dumps({"materialization": {
                "field_binding": {"mode": "native_static_pa", "path": str(binding)},
                "trajectory_profile": {"base_profile_id": "center_screening", "profile_id": "center_screening__step_scale_0.25", "maximum_step_us": .0005}},
                "config": {"inputs": {"accelerator_run_manifest": str(oa / "run_manifest.json"),
                    "accelerator_provider_receipt": str(frozen_receipt), "bunch_source_receipt": str(frozen_source),
                    "mirror_run_manifest": str(root / "mirror/run_manifest.json"), "stripe_run_manifest": str(root / "stripe/run_manifest.json")}}}), encoding="utf-8")
            quote = lambda p: str(p).replace("'", "''")
            script = (
                f". '{quote(support)}';$projectId='parallel_mirror_dual_stripe_mr_tof';\n" + helper
                + "function Get-VerifiedManifestOutput {param($ManifestPath,$Name) Join-Path (Split-Path -Parent $ManifestPath) ('results/'+$Name)}\n"
                + "function Invoke-ProjectPython {param($Arguments) $a=Get-Content $Arguments[2] -Raw|ConvertFrom-Json -AsHashtable;$b=Get-Content $Arguments[3] -Raw|ConvertFrom-Json -AsHashtable;if($a.source_y_offset_mm-ne$b.source_y_offset_mm){throw 'Screening source physical state differs: source_y_offset_mm'}}\n"
                + f"$selected=Get-Content '{quote(selected)}' -Raw|ConvertFrom-Json -AsHashtable;$caught='';$value=$null;"
                + f"try{{$value=Read-StaticCenterProblem -Selected $selected -ContractPath '{quote(contract)}' -SourceReceipt '{quote(mother)}' -GeometryReviewRun '{'' if missing_review else quote(review)}'}}catch{{$caught=$_.Exception.Message}};"
                + "@{caught=$caught;value=$value}|ConvertTo-Json -Depth 8 -Compress"
            )
            result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", script], cwd=REPO_ROOT,
                                    capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

    def test_native_static_problem_transports_original_owners_and_scaled_profile(self):
        result = self._static_problem()
        self.assertEqual(result["caught"], "")
        self.assertEqual(result["value"]["trajectory_profile"], "center_screening")
        self.assertEqual(result["value"]["trajectory_step_scale"], .25)
        self.assertTrue(result["value"]["accelerator_provider_receipt"].endswith("mrtof_runtime_receipt.json"))
        self.assertNotIn("native_system_runtime_bundle", result["value"])

    def test_native_static_problem_requires_review_owner(self):
        self.assertIn("original GeometryReviewRunPath", self._static_problem(missing_review=True)["caught"])

    def test_native_static_field_owner_uses_its_declared_geometry_key(self):
        result = self._static_problem(owner_mode="native_static_field_provider")
        self.assertEqual(result["caught"], "")
        self.assertIn("required geometry review input record", self._static_problem(
            owner_mode="native_static_field_provider", missing_geometry_key=True)["caught"])
        self.assertIn("Frozen geometry review differs", self._static_problem(
            owner_mode="native_static_field_provider", wrong_geometry_hash=True)["caught"])
        self.assertIn("unsupported mode", self._static_problem(owner_mode="unregistered_owner")["caught"])

    def test_native_static_problem_rejects_different_review_geometry(self):
        self.assertIn("sealed native field geometry", self._static_problem(wrong_geometry=True)["caught"])

    def test_native_static_problem_rejects_different_mother_source(self):
        self.assertIn("physical state differs", self._static_problem(wrong_source=True)["caught"])

    def _te1_field_preflight(self, mutation=None, *, variation_enabled=True, center_view=False):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import static_field_binding as fields
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import corridor_field_provider as provider
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import downstream_fixed_grid_workpoint as workpoint
        text = RUNNER.read_text(encoding="utf-8-sig")
        helper = text.split("function Assert-StaticScreeningField {", 1)[1].split("\nfunction ", 1)[0]
        code = helper.split("$code=@'\n", 1)[1].split("\n'@", 1)[0]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            center_path, actual_path, source_path = [root / name for name in ("center.json", "actual.json", "source.json")]
            values = [-27., 54., 190., -189.]
            candidate = dict(zip(("s1", "s2", "p1", "p2"), values))
            authority = provider.candidate_authority({"analyzer_electrode_voltages_v": [0.] * 20,
                                                     "component_voltages": {"oa": 30.}}, candidate)
            center = {"mode": "native_static_pa", "manifest": str(root / "source_manifest.json"),
                      "authority": authority, "geometry": {"physical": "same"},
                      "grid": {"pitch_mm": [.5, 1., 1.]},
                      "native_solver_numerics": {"boundary_mode": "grounded_enclosure"},
                      "refinement_windows": [{"name": "window", "grid": {"pitch_mm": [.25, .25, .2]},
                                              "active_box_mm": [[-22, 22], [-99, 389], [-324, 324]],
                                              "native_solver_numerics": {"refine_stopping": "installed_default"}}],
                      "instances": [{"role": name, "origin_mm": [0, 0, 0],
                                     "record": {"bytes": 1, "sha256": name}}
                                    for name in ("global_fallback", "native_corridor", "accelerator", "detector")]}
            expected = (provider.candidate_authority(authority, candidate, mirror_voltages_v=[0, 1, 2, 3, 4])
                        if variation_enabled else copy.deepcopy(authority))
            actual = copy.deepcopy(center)
            actual.update(authority=copy.deepcopy(expected), manifest=str(root / "run_manifest.json"))
            original_layout = [copy.deepcopy(center), *copy.deepcopy(center["refinement_windows"])]
            if center_view:
                center["consumer_view"] = {"kind": "x_symmetry_plane", "stored_x_nodes": 5}
                center["grid"]["dimensions"] = [5, 2, 2]
                center["refinement_windows"][0]["grid"]["dimensions"] = [5, 2, 2]
                center["refinement_windows"][0]["active_box_mm"][0] = [-.5, .5]
            # Parent bytes legitimately change with the declared mirror voltage.
            actual["instances"][0]["record"]["sha256"] = "new-parent"
            if mutation == "voltage":
                actual["authority"]["analyzer_electrode_voltages_v"][18] = 1
            elif mutation == "component":
                actual["authority"]["component_voltages"]["oa"] = 31
            elif mutation == "geometry":
                actual["geometry"]["physical"] = "different"
            elif mutation == "grid":
                actual["grid"]["pitch_mm"][1] = .5
            elif mutation == "window":
                actual["refinement_windows"][0]["active_box_mm"][1][1] = 388
            elif mutation == "numerics":
                actual["native_solver_numerics"]["convergence_v"] = 1e-5
            elif mutation == "window_numerics":
                actual["refinement_windows"][0]["native_solver_numerics"] = {
                    "refine_stopping": "contract_convergence", "convergence_v": 1e-5}
            elif mutation == "collision":
                actual["instances"][2]["record"]["sha256"] = "different"
            elif mutation == "mirror":
                actual["authority"]["analyzer_electrode_voltages_v"][1] = 9
            variation = root / "variation.json"
            frozen_variation = root / "frozen_variation.json"
            variation_data = {"coordinate": 1, "base_mirror_voltages_v": [0, 0, 0, 0, 0],
                "target_mirror_voltages_v": [0, 1, 2, 3, 4], "voltage_delta_v": [1, 2, 3, 4],
                "mode": "TE1", "detector_plane_root_fit": {"samples": [
                    {"coordinate": 0, "detector_dt_d_initial_z_us_per_mm": .05,
                     "diagnostic_path": "current-analysis.json"}]}}
            saved_variation = copy.deepcopy(variation_data)
            if mutation == "variation":
                saved_variation["coordinate"] = 2
            elif mutation == "diagnostic_locator":
                saved_variation["detector_plane_root_fit"]["samples"][0]["diagnostic_path"] = "previous-analysis.json"
            elif mutation == "variation_base":
                saved_variation["base_mirror_voltages_v"][1] = 1
            elif mutation == "variation_target":
                saved_variation["target_mirror_voltages_v"][1] = 2
            elif mutation == "variation_delta":
                saved_variation["voltage_delta_v"][0] = -1
            elif mutation == "variation_slope":
                saved_variation["detector_plane_root_fit"]["samples"][0]["detector_dt_d_initial_z_us_per_mm"] = .06
            variation.write_text(json.dumps(variation_data), encoding="utf-8")
            frozen_variation.write_text(json.dumps(saved_variation), encoding="utf-8")
            request = {"schema_version": 1, "role": "mrtof_native_static_field_provider_request",
                       "source_binding_path": str(source_path), "source_field_manifest": center["manifest"],
                       "candidate_voltages_v": dict(candidate), "mirror_voltage_variation_path": str(frozen_variation),
                       "mirror_reference_trial_manifest": "original-reference"}
            if mutation == "undeclared":
                request.pop("mirror_voltage_variation_path")
            elif mutation == "prism":
                request["candidate_voltages_v"]["p1"] += 1
            request_path = root / "request.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            materialization_path = root / "materialization.json"
            materialization = {"source_position_project_mm": [0., -55., 32.],
                               "source_direction_project": [0., 1., 0.]}
            if mutation == "source_position":
                materialization["source_position_project_mm"][0] = .01
            elif mutation == "source_direction":
                materialization["source_direction_project"][0] = .01
            materialization_path.write_text(json.dumps(materialization), encoding="utf-8")
            (root / "run_config.json").write_text(json.dumps({"inputs": {"request": str(request_path)}}), encoding="utf-8")
            def derive(q, source_authority):
                self.assertEqual(q["mirror_voltage_variation_path"], str(variation))
                self.assertEqual(q["mirror_contract_path"], "active-contract")
                self.assertEqual(q["mirror_reference_trial_manifest"], "original-reference")
                self.assertEqual(source_authority, authority)
                return expected, {}
            def load(path):
                return actual if path == actual_path else center
            with patch.object(fields, "load_binding", side_effect=load), patch.object(fields, "_record") as record, \
                    patch.object(provider, "derive_candidate_authority", side_effect=derive), \
                    patch.object(workpoint, "_native_original_consumer_layout", return_value=original_layout), \
                    patch.object(sys, "argv", ["check", str(center_path), str(actual_path),
                                               str(variation) if variation_enabled else "",
                                               "active-contract", json.dumps(values), str(materialization_path)]):
                exec(compile(code, str(RUNNER), "exec"), {})
                record.assert_called_once_with(Path(actual["manifest"]), request_path)

    def test_native_te1_rebinding_retains_anchor_and_accepts_declared_mirror_change(self):
        self._te1_field_preflight()

    def test_native_te1_rebinding_accepts_republished_diagnostic_locators_only(self):
        self._te1_field_preflight("diagnostic_locator")

    def test_native_full_field_continues_verified_center_storage_view(self):
        for variation_enabled in (False, True):
            with self.subTest(variation=variation_enabled):
                self._te1_field_preflight(variation_enabled=variation_enabled, center_view=True)

    def test_native_storage_projection_rejects_actual_off_plane_center(self):
        for mutation in ("source_position", "source_direction"):
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "actual source"):
                self._te1_field_preflight(mutation, variation_enabled=False, center_view=True)

    def test_native_storage_continuation_retains_physics_numerics_and_collision_checks(self):
        for variation_enabled in (False, True):
            for mutation in ("prism", "voltage", "component", "mirror", "geometry", "grid", "window",
                             "numerics", "window_numerics", "collision"):
                with self.subTest(variation=variation_enabled, mutation=mutation), self.assertRaises(ValueError):
                    self._te1_field_preflight(mutation, variation_enabled=variation_enabled, center_view=True)

    def test_native_te1_rebinding_rejects_unrelated_physics_or_numerics(self):
        for mutation in ("undeclared", "variation", "prism", "voltage", "component", "mirror",
                         "geometry", "grid", "window", "numerics", "window_numerics", "collision", "variation_base",
                         "variation_target", "variation_delta", "variation_slope"):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self._te1_field_preflight(mutation)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
    def test_comsol_screening_still_rejects_different_field_bytes(self):
        text = RUNNER.read_text(encoding="utf-8-sig")
        start = text.index("function Assert-StaticScreeningField {")
        helper = text[start:text.index("\nfunction ", start + 1)]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            center, other, variation = [root / name for name in ("center.json", "other.json", "variation.json")]
            center.write_text("{}", encoding="utf-8")
            other.write_text('{"different":true}', encoding="utf-8")
            variation.write_text("{}", encoding="utf-8")
            for mode, declared in (("comsol_static_scalar_v", ""), ("comsol_static_scalar_v", str(variation))):
                script = helper + (f"\n$selected=@{{materialization=@{{field_binding=@{{mode='{mode}';path='{center}'}}}}}};"
                                   f"try{{Assert-StaticScreeningField -Selected $selected -BindingPath '{other}' "
                                   f"-Variation '{declared}' -ContractPath 'contract' -Voltages @(1,2,3,4);exit 1}}"
                                   "catch{Write-Output $_.Exception.Message;exit 0}")
                result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", script],
                                        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("cannot rebind", result.stdout)

    def _source_physical_comparison(self, mutation=None):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import bunch_source_and_schedule as sources
        text = RUNNER.read_text(encoding="utf-8-sig")
        start = text.index("  $sourceCode=@'\n") + len("  $sourceCode=@'\n")
        code = text[start:text.index("\n'@", start)]
        definition = {
            "coordinate_semantics": {"workbench_from_project": "identity"},
            "center_rule": "resolved_provider_accelerator_release_position", "field_cache_dependency": "none",
            "aperture_plane_axes": [0, 2], "acceleration_axis": 1, "position_radius_mm": .5,
            "acceleration_axis_full_width_mm": 1, "kinetic_energy_center_ev": 5.374,
            "kinetic_energy_full_width_ev": .1, "nominal_direction_workbench": [0, 1, 0],
            "angular_full_width_deg": 0, "mass_th": 524, "charge_e": 1, "common_time_of_birth_us": 0,
        }
        receipt = {
            "cohort_role": "controlled_diagnostic", "source_profile_id": "controlled",
            "nominal_center_state": {"position_workbench_mm": [0, -56, 32], "direction_workbench": [0, 1, 0],
                                     "mass_th": 524, "charge_e": 1, "kinetic_energy_ev": 5.374, "tob_us": 0},
            "species": {"mass_th": 524, "charge_e": 1}, "frame_id": "xyz", "clock_basis": "common",
            "common_time_of_birth_us": 0, "source_y_offset_mm": -1,
            "center_rule": definition["center_rule"], "geometry_contract": {"derived_center_workbench_mm": [0, -56, 32]},
        }
        projection = {"accepted_release": {"radius_mm": .5}, "geometry": {"gap_1_mm": 4},
                      "endpoint_voltages_v": [4700, 4000, 0], "ring_voltages_v": [3700, 250],
                      "target_axial_energy_per_charge_v": 4372, "required_source_y_offset_from_accelerator_axis_mm": -1}
        provider = {"role": "orthogonal_accelerator_mrtof_runtime_receipt", "resolved_campaign": {"sha256": "same-science"},
                    "mrtof_projection": projection}
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            mother, actual = copy.deepcopy(receipt), copy.deepcopy(receipt)
            actual.update(cohort_role="formal_volume", source_profile_id="formal", expected_particle_ids=[17, 18])
            actual_definition = copy.deepcopy(definition)
            actual_provider = copy.deepcopy(provider)
            if mutation is not None:
                kind, key = mutation
                if kind == "state":
                    actual[key] = "drift" if key in ("frame_id", "clock_basis", "center_rule") else {"drift": 1}
                elif kind == "definition":
                    actual_definition[key] = "drift"
                elif kind == "oa":
                    actual_provider["mrtof_projection"][key] = "drift"
                elif kind == "campaign":
                    actual_provider["resolved_campaign"]["sha256"] = "other-science"
                elif kind == "geometry":
                    actual["geometry_contract"]["derived_center_workbench_mm"][1] += 1
            for label, data, d, p in (("mother", mother, definition, provider), ("formal", actual, actual_definition, actual_provider)):
                definition_path, provider_path = root / (label + "_definition.json"), root / (label + "_oa.json")
                definition_path.write_text(json.dumps(d), encoding="utf-8")
                provider_path.write_text(json.dumps(dict(p, owner=label)), encoding="utf-8")
                data["definition"] = {"path": str(definition_path)}
                data["accelerator_provider_receipt"] = {"path": str(provider_path)}
            current = root / "current_oa.json"
            current.write_text(json.dumps(provider), encoding="utf-8")
            with patch.object(sources, "load_verified_bunch_source_receipt", side_effect=[actual, mother]), \
                    patch.object(sys, "argv", ["check", "formal", "mother", str(current)]):
                exec(compile(code, str(RUNNER), "exec"), {})

    def test_formal_source_may_differ_in_role_sampling_and_owner_with_same_physics(self):
        self._source_physical_comparison()

    def test_static_screening_rejects_source_physics_and_oa_projection_drift(self):
        for kind, keys in (
            ("state", ("nominal_center_state", "species", "frame_id", "clock_basis", "common_time_of_birth_us", "source_y_offset_mm", "center_rule")),
            ("definition", ("position_radius_mm", "acceleration_axis_full_width_mm", "kinetic_energy_center_ev", "kinetic_energy_full_width_ev", "nominal_direction_workbench", "angular_full_width_deg", "kinetic_energy_distribution")),
            ("oa", ("accepted_release", "geometry", "endpoint_voltages_v", "ring_voltages_v", "target_axial_energy_per_charge_v", "required_source_y_offset_from_accelerator_axis_mm")),
            ("campaign", ("sha256",)), ("geometry", ("centre",)),
        ):
            for key in keys:
                with self.subTest(kind=kind, key=key), self.assertRaises(ValueError):
                    self._source_physical_comparison((kind, key))

if __name__ == "__main__":
    unittest.main()
