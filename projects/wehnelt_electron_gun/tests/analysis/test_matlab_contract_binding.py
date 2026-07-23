"""Static checks for the Wehnelt MATLAB resolved-contract boundary."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
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
        cls.build_test = (
            PROJECT_ROOT / "tests" / "comsol" / "test_build_only.m"
        ).read_text(encoding="utf-8")
        cls.build_runner = (
            PROJECT_ROOT / "run_build_only_smoke.ps1"
        ).read_text(encoding="utf-8")

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
            ["powershell", "-NoProfile", "-Command", script],
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
        self.assertEqual(
            self.build_runner.count("common\\comsol\\run_comsol_r2025b.ps1"),
            1,
        )
        self.assertIn("function Get-FileSha256", self.build_runner)
        self.assertNotIn("Get-FileHash", self.build_runner)

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
            "Tee-Object -LiteralPath $wrapperLog -Append",
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

    def test_all_summary_states_share_governance_and_solver_fields(self) -> None:
        required = (
            "threshold_result_eligible = $false",
            "candidate_evidence_allowed = $false",
            "formal_asset_modified = $false",
            "formal_gate_passed = $false",
            "static_gate_passed = $staticGatePassed",
            "commercial_wrapper_started = $commercialWrapperStarted",
            "commercial_wrapper_completed = $commercialWrapperCompleted",
            "failure_stage = $FailureStage",
            "electrostatics_solved = $reportText -match",
            "particle_tracing_solved = $reportText -match",
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
        for status, stage in (
            ("interrupted", "commercial_wrapper"),
            ("failed", "input_freeze"),
            ("success", "none"),
        ):
            completed = self.invoke_runner_functions(
                ("New-BuildSummary",),
                (
                    f"New-BuildSummary -Status {status} -Reason test "
                    f"-FailureStage {stage}|ConvertTo-Json -Compress"
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
            expected_commercial = status == "success"
            self.assertEqual(
                summary["commercial_wrapper_started"], expected_commercial
                or stage == "commercial_wrapper"
            )

    def test_governance_and_actual_common_entries_are_frozen(self) -> None:
        required = (
            "config\\execution_profiles.json",
            "config\\project.json",
            "analysis\\resolve_contract.py",
            "verify_project.ps1",
            "common\\contracts\\run_artifact_support.ps1",
            "common\\contracts\\write_run_manifest.py",
            "common\\contracts\\verify_run_manifest.py",
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


if __name__ == "__main__":
    unittest.main()
