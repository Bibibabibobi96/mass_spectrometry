"""Static checks for the Wehnelt MATLAB resolved-contract boundary."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
ACTIVE_SCRIPTS = (
    PROJECT_ROOT / "phase1_geometry_coil_transverse.m",
    PROJECT_ROOT / "phase2_electrostatics_coil_transverse.m",
    PROJECT_ROOT / "phase4_thermal_emission_coil_transverse.m",
)


class MatlabContractBindingTests(unittest.TestCase):
    """Keep all active stages fail-closed and contract-driven."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = {
            path.name: path.read_text(encoding="utf-8") for path in ACTIVE_SCRIPTS
        }
        cls.combined = "\n".join(cls.sources.values())
        cls.binding = (
            PROJECT_ROOT / "apply_wehnelt_contract_parameters.m"
        ).read_text(encoding="utf-8")
        cls.loader = (PROJECT_ROOT / "load_wehnelt_contract.m").read_text(
            encoding="utf-8"
        )
        cls.build_test = (
            PROJECT_ROOT / "tests" / "comsol" / "test_build_only.m"
        ).read_text(encoding="utf-8")
        cls.build_runner = (
            PROJECT_ROOT / "run_build_only_smoke.ps1"
        ).read_text(encoding="utf-8")
        cls.resolver = (PROJECT_ROOT / "analysis" / "resolve_contract.py").read_text(
            encoding="utf-8"
        )

    def invoke_runner_functions(
        self, function_names: tuple[str, ...], command: str
    ) -> subprocess.CompletedProcess[str]:
        names = ",".join(f"'{name}'" for name in function_names)
        script = (
            f"$tokens=$null;$errors=$null;"
            f"$ast=[Management.Automation.Language.Parser]::ParseFile("
            f"'{self.build_runner_path()}',[ref]$tokens,[ref]$errors);"
            f"if($errors.Count){{throw ($errors|Out-String)}};"
            f"$wanted=@({names});"
            "$ast.FindAll({param($node)"
            "$node -is [Management.Automation.Language.FunctionDefinitionAst]"
            " -and $wanted -contains $node.Name},$true)|"
            "ForEach-Object{Invoke-Expression $_.Extent.Text};"
            f"{command}"
        )
        return subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )

    @staticmethod
    def build_runner_path() -> str:
        return str(PROJECT_ROOT / "run_build_only_smoke.ps1").replace("'", "''")

    def test_every_stage_requires_and_loads_resolved_contract(self) -> None:
        for name, source in self.sources.items():
            with self.subTest(name=name):
                self.assertIn("resolvedContractPath", source)
                self.assertIn("load_wehnelt_contract", source)
                self.assertIn("no defaults exist", source)
                self.assertIn("apply_wehnelt_contract_parameters", source)

    def test_geometry_and_physics_use_named_contract_parameters(self) -> None:
        required = (
            "set('rmaj', 'coil_rmaj')",
            "set('pos', {'coil_xmin' '0' 'coil_zc'})",
            "set('V0', 'V_wehnelt')",
            "set('hmax', 'mesh_coil_hmax')",
            "set('T', 'filament_T')",
            "particleProperties.set('mp'",
            "particleProperties.set('Z', particle.charge_state)",
            "wall.set('WallCondition', terminalOutcomes.wall_condition)",
            "range(particle_t_start,particle_t_step,particle_t_end)",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.combined)

    def test_active_scripts_do_not_duplicate_physical_defaults(self) -> None:
        forbidden = (
            "'0.3[mm]'",
            "'0.05[mm]'",
            "'-0.5[V]'",
            "'70[V]'",
            "'2700[K]'",
            "'0.03[mm]'",
            "'0.005[mm]'",
            "'range(0,0.1[ns],40[ns])'",
            "KE_eV > 60",
            "KE_eV < 75",
            "coil_turns*coil_pitch",
            "z_weh_top+gap2",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, self.combined)

    def test_parameter_binding_exposes_derived_coordinates_and_modes(self) -> None:
        required = (
            "derived.wehnelt_cavity_ceiling_z_mm",
            "derived.anode_bottom_z_mm",
            "derived.vacuum_domain_top_z_mm",
            "numerical.mesh.filament_surface_hmax_mm",
            "numerical.particle_time_ns.step",
            "metric.usable_energy_min_eV",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.binding)
        self.assertIn("physical.usable_final_state_metric", self.binding)
        self.assertNotIn("collection_metric", self.binding)

    def test_loader_allows_non_candidate_functional_mode_fail_closed(self) -> None:
        required = (
            "~contract.numerical.candidate_evidence_allowed",
            "~contract.evidence.candidate_evidence_allowed",
            "minimumCount = contract.evidence.minimum_particle_count",
            "strcmp(contract.numerical.execution_mode, 'full')",
            "sampling.seed_control",
            "~sampling.reproducible_particle_realization",
            "~emission.beam_current_supported",
            "~terminal.wall_loss_attribution_supported",
            "contract.physical.usable_final_state_metric",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.loader)

    def test_build_only_test_checks_identity_and_evidence_boundary(self) -> None:
        required = (
            "resolved_model.json",
            "contract_project_id",
            "selected_mode_id",
            "parameter_bindings_verified",
            "candidate_evidence_allowed",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.build_test)

    def test_build_only_returns_before_electrostatic_and_particle_solvers(self) -> None:
        for name in (
            "phase2_electrostatics_coil_transverse.m",
            "phase4_thermal_emission_coil_transverse.m",
        ):
            source = self.sources[name]
            guard = source.index("if strcmp(executionMode, 'build_only')")
            guarded_return = source.index("return;", guard)
            solver_run = source.index(".runAll;", guarded_return)
            with self.subTest(name=name):
                self.assertLess(guard, guarded_return)
                self.assertLess(guarded_return, solver_run)

    def test_particle_postprocessing_enforces_full_finite_position_rule(self) -> None:
        source = self.sources["phase4_thermal_emission_coil_transverse.m"]
        required = (
            "qx_end = pd.p(end,:,1)",
            "qy_end = pd.p(end,:,2)",
            "qz_end = pd.p(end,:,3)",
            "isfinite(qx_end) & isfinite(qy_end) & isfinite(qz_end)",
            "finiteVelocity = isfinite(vx) & isfinite(vy) & isfinite(vz)",
            "KEv = KE_eV(validEnergy)",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, source)
        self.assertNotIn("valid = ~isnan(qz_end)", source)
        self.assertNotIn("me_ =", source)
        self.assertNotIn("qe =", source)
        self.assertNotIn("self-absorbed", source)
        self.assertNotIn("passed anode", source)
        self.assertIn("unclassified; no wall-loss", source)
        self.assertIn("contract.physical.filament.material_identity", source)
        self.assertIn("particle.mass_kg", source)
        self.assertIn("particle.charge_C", source)
        self.assertIn("contract.physical.usable_final_state_metric", source)
        self.assertNotIn("collection_metric", source)
        self.assertNotIn("collection efficiency", source.lower())

    def test_required_particle_dataset_is_not_optional_plotting_work(self) -> None:
        source = self.sources["phase4_thermal_emission_coil_transverse.m"]
        dataset_index = source.index(
            "pdset1 = model.result.dataset.create('pdset1', 'Particle');"
        )
        plotting_try_index = source.index("try", dataset_index)
        extraction_index = source.index(
            "pd = mphparticle(model, 'dataset', 'pdset1');"
        )
        self.assertLess(dataset_index, plotting_try_index)
        self.assertLess(plotting_try_index, extraction_index)

    def test_commercial_runner_freezes_inputs_and_writes_verified_manifest(self) -> None:
        required = (
            "New-RunPackage",
            "tests\\comsol\\test_build_only.m",
            "config\\resolved_model.json",
            "WEHNELT_ARTIFACT_ROOT",
            "common\\comsol\\run_comsol_r2025b.ps1",
            "Write-VerifiedRunManifest",
            "-Status success",
            "-Status failed",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.build_runner)
        self.assertIn("[string]$PythonExe", self.build_runner)
        self.assertIn("New-RunPackage -Python $python", self.build_runner)
        self.assertEqual(
            self.build_runner.count("common\\comsol\\run_comsol_r2025b.ps1"),
            1,
        )
        self.assertIn("function Get-FileSha256", self.build_runner)
        self.assertNotIn("Get-FileHash", self.build_runner)

    def test_runner_executes_frozen_gate_and_checks_frozen_contract_triplet(
        self,
    ) -> None:
        required = (
            "& $frozenInputs.static_gate -PythonExe $package.python",
            "Push-Location $snapshotRoot",
            "-m projects.wehnelt_electron_gun.analysis.resolve_contract",
            "--baseline $frozenInputs.baseline",
            "--modes $frozenInputs.numerical_modes",
            "--check $frozenInputs.resolved_contract",
            "Frozen Wehnelt baseline, numerical mode, and resolved contract differ.",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.build_runner)
        self.assertNotIn(
            "& (Join-Path $projectRoot 'verify_project.ps1')",
            self.build_runner,
        )

    def test_frozen_resolver_has_its_shared_particle_physics_dependency(self) -> None:
        self.assertIn(
            "from common.contracts.particle_physics import (", self.resolver
        )
        self.assertIn(
            "particle_physics = 'common\\contracts\\particle_physics.py'",
            self.build_runner,
        )
        self.assertIn("$infrastructureRoot = $snapshotRoot", self.build_runner)

    def test_runner_strictly_consumes_the_registered_mode_descriptor(self) -> None:
        required = (
            "function Assert-BuildOnlyModeDescriptor",
            "config\\modes\\build_only_smoke.json",
            "../numerical_modes.json#/modes/build_only_smoke",
            "-ResolvedPath $frozenInputs.resolved_contract",
            "-ExecutionProfilesPath $frozenInputs.execution_profiles",
            "$resolved.numerical.execution_mode -cne 'build_only'",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.build_runner)

    def test_mode_descriptor_validator_runs_under_latest_strict_mode(self) -> None:
        mode = str(PROJECT_ROOT / "config" / "modes" / "build_only_smoke.json")
        resolved = str(PROJECT_ROOT / "config" / "resolved_model.json")
        profiles = str(PROJECT_ROOT / "config" / "execution_profiles.json")
        command = (
            "Set-StrictMode -Version Latest;"
            f"Assert-BuildOnlyModeDescriptor -Path '{mode}' "
            f"-ResolvedPath '{resolved}' -ExecutionProfilesPath '{profiles}';"
            "'MODE_DESCRIPTOR_STRICT=PASS'"
        )
        completed = self.invoke_runner_functions(
            ("Assert-BuildOnlyModeDescriptor",), command
        )
        self.assertEqual(
            completed.returncode,
            0,
            (completed.stdout or "") + (completed.stderr or ""),
        )
        self.assertIn("MODE_DESCRIPTOR_STRICT=PASS", completed.stdout)

    def test_mode_descriptor_key_diff_is_rejected_under_strict_mode(self) -> None:
        source = json.loads(
            (PROJECT_ROOT / "config" / "modes" / "build_only_smoke.json").read_text(
                encoding="utf-8"
            )
        )
        resolved = str(PROJECT_ROOT / "config" / "resolved_model.json")
        profiles = str(PROJECT_ROOT / "config" / "execution_profiles.json")
        mutations = {
            "extra": {**source, "unexpected": True},
            "missing": {
                key: value for key, value in source.items() if key != "claim_limit"
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            for label, document in mutations.items():
                with self.subTest(label=label):
                    mode = Path(directory) / f"{label}.json"
                    mode.write_text(json.dumps(document), encoding="utf-8")
                    command = (
                        "Set-StrictMode -Version Latest;"
                        "try{Assert-BuildOnlyModeDescriptor "
                        f"-Path '{mode}' -ResolvedPath '{resolved}' "
                        f"-ExecutionProfilesPath '{profiles}';exit 41}}"
                        "catch{if($_.Exception.Message -notlike "
                        "'Build-only mode descriptor has unexpected fields:*'){exit 42};"
                        "'MODE_DESCRIPTOR_KEY_DIFF=REJECTED'}"
                    )
                    completed = self.invoke_runner_functions(
                        ("Assert-BuildOnlyModeDescriptor",), command
                    )
                    self.assertEqual(
                        completed.returncode,
                        0,
                        (completed.stdout or "") + (completed.stderr or ""),
                    )
                    self.assertIn(
                        "MODE_DESCRIPTOR_KEY_DIFF=REJECTED", completed.stdout
                    )

    def test_report_parser_accepts_only_one_exact_value_per_known_key(self) -> None:
        valid = self.invoke_runner_functions(
            ("Read-BuildOnlyReport",),
            (
                "$path=[IO.Path]::GetTempFileName();"
                "try{Set-Content -LiteralPath $path -Encoding UTF8 "
                "-Value @('FLAG=true','STATUS=PASS');"
                "$expected=[ordered]@{FLAG='true';STATUS='PASS'};"
                "Read-BuildOnlyReport -Path $path -Expected $expected|"
                "ConvertTo-Json -Compress}finally{Remove-Item -LiteralPath $path}"
            ),
        )
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
        self.assertEqual(json.loads(valid.stdout)["STATUS"], "PASS")

        invalid_reports = (
            ("duplicate", "@('FLAG=true','FLAG=true','STATUS=PASS')"),
            ("unknown", "@('FLAG=true','EXTRA=x','STATUS=PASS')"),
            ("passing", "@('FLAG=true','STATUS=PASSING')"),
            ("conflict", "@('FLAG=true','FLAG=false','STATUS=PASS')"),
        )
        for label, lines in invalid_reports:
            with self.subTest(label=label):
                completed = self.invoke_runner_functions(
                    ("Read-BuildOnlyReport",),
                    (
                        "$path=[IO.Path]::GetTempFileName();"
                        f"Set-Content -LiteralPath $path -Encoding UTF8 -Value {lines};"
                        "$expected=[ordered]@{FLAG='true';STATUS='PASS'};"
                        "$failed=$false;try{$null=Read-BuildOnlyReport "
                        "-Path $path -Expected $expected}catch{$failed=$true};"
                        "Remove-Item -LiteralPath $path;if($failed){exit 17}"
                    ),
                )
                self.assertNotEqual(
                    completed.returncode,
                    0,
                    (completed.stdout or "") + (completed.stderr or ""),
                )

    def test_runner_rejects_empty_mph_and_preserves_verified_prestates(self) -> None:
        required = (
            "(Get-Item -LiteralPath $modelPath).Length -le 0",
            "function Invoke-VerifiedRecordTransition",
            "[IO.File]::ReadAllBytes($path)",
            "[IO.File]::WriteAllBytes",
            "the last verified prestate was restored",
            "bootstrap_boundary = [ordered]@{",
            "sha256 = Get-FileSha256 -Path $source",
            "Bootstrap dependency changed before it was frozen",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.build_runner)

    def test_bootstrap_identity_includes_immediate_support_dependencies(self) -> None:
        bootstrap_start = self.build_runner.index("$bootstrapFiles = [ordered]@{")
        bootstrap_end = self.build_runner.index("}\n$bootstrapIdentity", bootstrap_start)
        bootstrap_block = self.build_runner[bootstrap_start:bootstrap_end]
        required = (
            "powershell_runtime_gate = 'common\\require_powershell7.ps1'",
            "artifact_support = 'common\\contracts\\run_artifact_support.ps1'",
            "manifest_writer = 'common\\contracts\\write_run_manifest.py'",
            "manifest_verifier = 'common\\contracts\\verify_run_manifest.py'",
            "artifact_naming = 'common\\contracts\\artifact_naming.py'",
            "file_identity = 'common\\contracts\\file_identity.py'",
            "particle_physics = 'common\\contracts\\particle_physics.py'",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, bootstrap_block)
        self.assertIn(
            "foreach ($entry in $bootstrapIdentity.GetEnumerator())",
            self.build_runner,
        )
        self.assertIn(
            "Get-FileSha256 -Path $frozenInputs[$entry.Key]",
            self.build_runner,
        )

    def test_external_termination_has_a_verified_interrupted_prestate(self) -> None:
        initial_summary = self.build_runner.index(
            "New-BuildSummary -Status interrupted"
        )
        initial_manifest = self.build_runner.index(
            "-Manifest $manifestPath -Status interrupted", initial_summary
        )
        guarded_work = self.build_runner.index("try {", initial_manifest)
        commercial_call = self.build_runner.index(
            "& $frozenInputs.comsol_runner", guarded_work
        )
        self.assertLess(initial_summary, initial_manifest)
        self.assertLess(initial_manifest, guarded_work)
        self.assertLess(guarded_work, commercial_call)

    def test_partial_freeze_failure_recovers_every_existing_input(self) -> None:
        required = (
            "Get-ChildItem -LiteralPath $package.input_dir -Recurse -File",
            "$knownInputs -notcontains $file.FullName",
            "recovered_input_{0:D3}",
            "$runConfig.inputs = $frozenInputs",
            "-Status failed",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.build_runner)
        recovery = self.build_runner.index("$knownInputs = @($frozenInputs.Values")
        failed_manifest = self.build_runner.index(
            "-Manifest $manifestPath -Status failed", recovery
        )
        self.assertLess(recovery, failed_manifest)

    def test_wrapper_failure_and_success_both_persist_console_context(self) -> None:
        required = (
            "commercial_wrapper.log",
            "Tee-Object -FilePath $wrapperLog -Append",
            "STREAM_CAPTURE=all_powershell_streams_merged",
            "WRAPPER_EXCEPTION=",
            "WRAPPER_EXIT_CODE=",
            "TERMINAL_STATE=failed",
            "TERMINAL_STATE=returned",
            "Get-ExistingRunOutputs",
            "-Status success",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.build_runner)
        wrapper = self.build_runner.index("& $frozenInputs.comsol_runner")
        wrapper_catch = self.build_runner.index("WRAPPER_EXCEPTION=", wrapper)
        success = self.build_runner.index(
            "-Manifest $manifestPath -Status success", wrapper_catch
        )
        outer_failure = self.build_runner.index(
            "-Manifest $manifestPath -Status failed", success
        )
        self.assertLess(wrapper, wrapper_catch)
        self.assertLess(wrapper_catch, success)
        self.assertLess(success, outer_failure)

    def test_wrapper_tee_uses_one_supported_append_parameter_set(self) -> None:
        runner = self.build_runner_path()
        ast_script = (
            "$tokens=$null;$errors=$null;"
            "$ast=[Management.Automation.Language.Parser]::ParseFile("
            f"'{runner}',[ref]$tokens,[ref]$errors);"
            "if($errors.Count){exit 31};"
            "$commands=@($ast.FindAll({param($node)"
            "$node -is [Management.Automation.Language.CommandAst] -and "
            "$node.GetCommandName() -eq 'Tee-Object'},$true));"
            "if($commands.Count -ne 1){exit 32};"
            "@($commands[0].CommandElements|Where-Object {"
            "$_ -is [Management.Automation.Language.CommandParameterAst]}|"
            "ForEach-Object {$_.ParameterName})|ConvertTo-Json -Compress"
        )
        ast_result = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ast_script],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(
            ast_result.returncode,
            0,
            (ast_result.stdout or "") + (ast_result.stderr or ""),
        )
        self.assertEqual(set(json.loads(ast_result.stdout)), {"FilePath", "Append"})

        behavior_script = (
            "$path=[IO.Path]::GetTempFileName();"
            "try{Set-Content -LiteralPath $path -Encoding UTF8 -Value 'prefix';"
            "@('alpha','beta')|Tee-Object -FilePath $path -Append|Out-Null;"
            "$lines=@(Get-Content -LiteralPath $path -Encoding UTF8);"
            "if($lines.Count -ne 3 -or $lines[0] -cne 'prefix' -or "
            "$lines[1] -cne 'alpha' -or $lines[2] -cne 'beta'){exit 33}}"
            "finally{Remove-Item -LiteralPath $path}"
        )
        behavior_result = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                behavior_script,
            ],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(
            behavior_result.returncode,
            0,
            (behavior_result.stdout or "") + (behavior_result.stderr or ""),
        )
        self.assertNotIn("Tee-Object -LiteralPath", self.build_runner)

    def test_all_summary_states_share_governance_and_solver_fields(self) -> None:
        required = (
            "threshold_result_eligible = $false",
            "candidate_evidence_allowed = $false",
            "formal_asset_modified = $false",
            "formal_gate_passed = $false",
            "static_gate_passed = $staticGatePassed",
            "commercial_wrapper_invocation_attempted = $CommercialWrapperInvocationAttempted",
            "commercial_wrapper_completed = $CommercialWrapperCompleted",
            "failure_stage = $FailureStage",
            "electrostatics_solved = $null -ne $ReportValues",
            "particle_tracing_solved = $null -ne $ReportValues",
            "New-BuildSummary -Status success",
            "New-BuildSummary -Status failed",
            "New-BuildSummary -Status interrupted",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.build_runner)

    def test_summary_function_emits_interrupted_and_failed_governance_fields(
        self,
    ) -> None:
        for status, stage, attempted, completed_wrapper in (
            ("interrupted", "commercial_wrapper", True, False),
            ("failed", "input_freeze", False, False),
            ("success", "none", True, True),
        ):
            completed = self.invoke_runner_functions(
                ("New-BuildSummary",),
                (
                    f"New-BuildSummary -Status {status} -Reason test "
                    f"-FailureStage {stage} "
                    f"-CommercialWrapperInvocationAttempted ${str(attempted).lower()} "
                    f"-CommercialWrapperCompleted ${str(completed_wrapper).lower()}|"
                    "ConvertTo-Json -Compress"
                ),
            )
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            summary = json.loads(completed.stdout)
            self.assertEqual(summary["status"], status)
            self.assertEqual(summary["failure_stage"], stage)
            self.assertFalse(summary["threshold_result_eligible"])
            self.assertFalse(summary["electrostatics_solved"])
            self.assertFalse(summary["particle_tracing_solved"])
            self.assertEqual(
                summary["commercial_wrapper_invocation_attempted"],
                attempted,
            )
            self.assertEqual(
                summary["commercial_wrapper_completed"], completed_wrapper
            )
            self.assertNotIn("commercial_wrapper_started", summary)

    def test_governance_and_actual_common_entries_are_frozen(self) -> None:
        required = (
            "config\\execution_profiles.json",
            "config\\project.json",
            "analysis\\resolve_contract.py",
            "verify_project.ps1",
            "common\\contracts\\run_artifact_support.ps1",
            "common\\contracts\\write_run_manifest.py",
            "common\\contracts\\verify_run_manifest.py",
            "common\\contracts\\particle_physics.py",
            "common\\comsol\\run_comsol_r2025b.ps1",
            "common\\comsol\\resolve_comsol_64.ps1",
            "common\\comsol\\livelink_r2025b\\comsolstartup.m",
            ". $frozenInputs.artifact_support",
            "& $frozenInputs.comsol_runner",
            "Write-VerifiedRunManifest",
        )
        for token in required:
            with self.subTest(token=token):
                self.assertIn(token, self.build_runner)

    def test_frozen_gate_does_not_mutate_its_declared_input_set(self) -> None:
        if os.environ.get("WEHNELT_NESTED_FROZEN_GATE") == "1":
            return
        project_relatives = (
            "run_build_only_smoke.ps1",
            "tests/comsol/test_build_only.m",
            "egun_paths.m",
            "load_wehnelt_contract.m",
            "apply_wehnelt_contract_parameters.m",
            "phase1_geometry_coil_transverse.m",
            "phase2_electrostatics_coil_transverse.m",
            "phase4_thermal_emission_coil_transverse.m",
            "config/baseline.json",
            "config/numerical_modes.json",
            "config/resolved_model.json",
            "config/modes/build_only_smoke.json",
            "config/execution_profiles.json",
            "config/project.json",
            "analysis/__init__.py",
            "analysis/resolve_contract.py",
            "verify_project.ps1",
        )
        common_relatives = (
            "pyproject.toml",
            "common/require_powershell7.ps1",
            "common/verify_lightweight.ps1",
            "common/contracts/run_artifact_support.ps1",
            "common/contracts/write_run_manifest.py",
            "common/contracts/verify_run_manifest.py",
            "common/contracts/artifact_naming.py",
            "common/contracts/file_identity.py",
            "common/contracts/particle_physics.py",
            "common/contracts/build_project_registry.py",
            "common/contracts/machine_contracts.py",
            "common/comsol/run_comsol_r2025b.ps1",
            "common/comsol/resolve_comsol_64.ps1",
            "common/comsol/livelink_failure_classification.ps1",
            "common/comsol/livelink_environment.ps1",
            "common/comsol/livelink_r2025b/comsolstartup.m",
        )
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "repository"
            frozen_project = snapshot / "projects" / "wehnelt_electron_gun"
            declared: set[Path] = set()

            def freeze(source: Path, destination: Path) -> None:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                declared.add(destination.resolve())

            for relative in project_relatives:
                freeze(PROJECT_ROOT / relative, frozen_project / relative)
            for source in sorted((PROJECT_ROOT / "tests" / "analysis").glob("*.py")):
                freeze(source, frozen_project / "tests" / "analysis" / source.name)
            for relative in common_relatives:
                freeze(REPO_ROOT / relative, snapshot / relative)
            for source in sorted(
                (REPO_ROOT / "common" / "contracts" / "schemas").glob("*.json")
            ):
                freeze(
                    source,
                    snapshot / "common" / "contracts" / "schemas" / source.name,
                )

            environment = os.environ.copy()
            environment.update(
                {
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "RUFF_NO_CACHE": "true",
                    "WEHNELT_NESTED_FROZEN_GATE": "1",
                }
            )
            completed = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(frozen_project / "verify_project.ps1"),
                    "-PythonExe",
                    sys.executable,
                ],
                cwd=snapshot,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=90,
            )
            self.assertEqual(
                completed.returncode,
                0,
                (completed.stdout or "") + (completed.stderr or ""),
            )
            actual = {path.resolve() for path in snapshot.rglob("*") if path.is_file()}
            self.assertEqual(actual, declared)
            self.assertFalse(any(path.suffix == ".pyc" for path in actual))
            self.assertFalse((snapshot / ".ruff_cache").exists())

    def test_frozen_input_set_rejects_extra_and_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            declared = root / "declared.txt"
            extra = root / "extra.txt"
            command = (
                "Set-StrictMode -Version Latest;"
                f"Set-Content -LiteralPath '{declared}' -Value declared;"
                f"$inputs=[ordered]@{{declared='{declared}'}};"
                f"Assert-FrozenInputSet -InputDirectory '{root}' -Inputs $inputs;"
                f"Set-Content -LiteralPath '{extra}' -Value extra;"
                f"try{{Assert-FrozenInputSet -InputDirectory '{root}' "
                "-Inputs $inputs;exit 51}catch{};"
                f"Remove-Item -LiteralPath '{extra}','{declared}';"
                f"try{{Assert-FrozenInputSet -InputDirectory '{root}' "
                "-Inputs $inputs;exit 52}catch{};"
                "'FROZEN_INPUT_SET_FAIL_CLOSED=PASS'"
            )
            completed = self.invoke_runner_functions(
                ("Assert-FrozenInputSet",), command
            )
            self.assertEqual(
                completed.returncode,
                0,
                (completed.stdout or "") + (completed.stderr or ""),
            )
            self.assertIn("FROZEN_INPUT_SET_FAIL_CLOSED=PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
