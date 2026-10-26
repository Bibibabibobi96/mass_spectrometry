from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from projects.rf_multipole_ion_optics.core.family_contract import (
    VoltageDrive,
    electrode_group_voltages,
    from_high_order_baseline,
    from_high_order_resolved_design,
    l1_l2_transport_contract_from_resolved_design,
    from_quadrupole_contract,
    load_family_contract,
)
from projects.rf_multipole_ion_optics.runtime.design_profile import resolve_design_profile
from projects.rf_multipole_ion_optics.core.mass_response import aggregate_response, evaluate_functional_contrast, load_terminal_statuses
from projects.rf_multipole_ion_optics.core.ideal_transport import source_particles
from projects.rf_multipole_ion_optics.core.paired_mass_scan import build_paired_ion_rows
from projects.rf_multipole_ion_optics.analysis.verify_family_foundation import validate_family_foundation
from projects.rf_multipole_ion_optics.runtime.runtime_profile import resolve_runtime_profile


REPO_ROOT = Path(__file__).parents[4]
SUPPORT_PATH = (
    REPO_ROOT / "projects/rf_multipole_ion_optics/runtime/project_transport_launcher_support.ps1"
)
SIMION_RUNNER = REPO_ROOT / "projects/rf_multipole_ion_optics/runtime/run_simion_finite_3d_transport.ps1"
SIMION_PROGRAM = REPO_ROOT / "projects/rf_multipole_ion_optics/simion/simion_transport.lua"
PROJECTS = tuple(
    ("rf_multipole_ion_optics", "workflows/no_collision_transport", f"{variant}_{profile}")
    for variant, profile in (
        ("quadrupole", "no_acceleration_full_length"),
        ("hexapole", "segmented_rod_axial_acceleration"),
        ("octupole", "no_acceleration_full_length"),
    )
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class MultipoleFamilyContractTests(unittest.TestCase):
    def test_machine_contract_text_bytes_are_cross_platform_stable(self) -> None:
        attributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
        lines = attributes.splitlines()
        for extension in (
            "json",
            "csv",
            "py",
            "ps1",
            "m",
            "lua",
            "gem",
            "toml",
            "yaml",
            "yml",
            "txt",
            "md",
        ):
            with self.subTest(extension=extension):
                self.assertIn(f"*.{extension} text eol=lf", lines)

    def test_frozen_family_foundation_gate(self) -> None:
        validate_family_foundation()

    def test_all_three_variants_close_over_one_frozen_rf_drive_kernel(self) -> None:
        support = SUPPORT_PATH.read_text(encoding="utf-8-sig")
        runner = SIMION_RUNNER.read_text(encoding="utf-8-sig")
        program = SIMION_PROGRAM.read_text(encoding="utf-8")

        self.assertEqual(
            support.count("projects\\rf_multipole_ion_optics\\runtime\\run_simion_finite_3d_transport.ps1"),
            1,
        )
        self.assertIn("common\\simion\\rf_drive.lua", runner)
        self.assertIn("Copy-VerifiedRunInput", runner)
        self.assertIn("multipole_rf_drive_kernel.lua", runner)
        self.assertIn("simion_rf_drive_kernel=$rfDriveKernelLua", runner)
        self.assertIn(
            "$env:MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA=$rfDriveKernelLua",
            runner,
        )
        self.assertIn(
            "os.getenv('MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA')",
            program,
        )
        self.assertNotIn("common/simion/rf_drive.lua", program)

        for project_id, entry_directory, _ in PROJECTS:
            entry_root = REPO_ROOT / "projects" / project_id / entry_directory
            launcher_name = "run_simion.ps1"
            launcher = (entry_root / launcher_name).read_text(encoding="utf-8-sig")
            self.assertIn("project_transport_launcher_support.ps1", launcher)
            self.assertNotIn("simion_rf_drive.lua", launcher)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_real_wrappers_resolve_once_and_delegate_governed_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            support = root / SUPPORT_PATH.relative_to(REPO_ROOT)
            support.parent.mkdir(parents=True)
            shutil.copyfile(SUPPORT_PATH, support)
            profile_path, calls_path, runner_path = (
                root / name for name in ("profile.json", "calls.jsonl", "runner.json")
            )
            python = root / "resolver.ps1"
            python.write_text(
                "ConvertTo-Json -Compress -InputObject @($args) | Add-Content $env:TEST_CALLS\n"
                "Copy-Item $env:TEST_PROFILE $args[([array]::IndexOf($args,'--output')+1)]\n"
                "$global:LASTEXITCODE=0\n", encoding="utf-8",
            )
            for solver in ("comsol", "simion"):
                entry = support.parent / (
                    "run_finite_3d_transport.ps1" if solver == "comsol"
                    else "run_simion_finite_3d_transport.ps1"
                )
                entry.write_text(
                    "$bound=@{}; for($i=0;$i-lt$args.Count;$i+=2){"
                    "$bound[$args[$i].TrimStart('-').TrimEnd(':')]=$args[$i+1]}\n"
                    "$bound.solver=$MyInvocation.MyCommand.Name\n"
                    "$bound | ConvertTo-Json -Compress -Depth 20 | Add-Content $env:TEST_RUNNER\n"
                    "$global:LASTEXITCODE=0\n", encoding="utf-8",
                )
            environment = dict(os.environ, TEST_PROFILE=str(profile_path),
                               TEST_CALLS=str(calls_path), TEST_RUNNER=str(runner_path))
            for project_id, entry_directory, selected_profile_id in PROJECTS:
                profile = resolve_runtime_profile(REPO_ROOT, project_id, selected_profile_id)
                profile["solver_numerics"]["simion"]["values"]["cell_mm_xyz"] = {
                    "x": 0.31, "y": 0.42, "z": 0.53,
                }
                for solver in ("comsol", "simion"):
                    with self.subTest(project=project_id, solver=solver):
                        name = f"run_{solver}.ps1"
                        relative = Path("projects") / project_id / entry_directory / name
                        wrapper = root / relative
                        wrapper.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(REPO_ROOT / relative, wrapper)
                        profile_path.write_text(json.dumps(profile), encoding="utf-8")
                        calls_path.unlink(missing_ok=True)
                        runner_path.unlink(missing_ok=True)
                        command = r"""
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$p=$env:TEST_WRAPPER
$ast=[System.Management.Automation.Language.Parser]::ParseFile($p,[ref]$null,[ref]$null)
$profileParameter=($ast.ParamBlock.Parameters | Where-Object {$_.Name.VariablePath.UserPath-eq'RuntimeProfileId'})
$default=if($null-eq$profileParameter.DefaultValue){$null}else{$profileParameter.DefaultValue.SafeGetValue()}
& $p -RuntimeProfileId $env:TEST_RUNTIME -PythonExe $env:TEST_PYTHON
if($LASTEXITCODE-ne 0){exit $LASTEXITCODE}
@{default=$default; parameters=@((Get-Command $p).Parameters.Keys)} | ConvertTo-Json -Compress
"""
                        environment.update(TEST_WRAPPER=str(wrapper), TEST_PYTHON=str(python), TEST_RUNTIME=selected_profile_id)
                        result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                                                cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        public = json.loads(result.stdout)
                        self.assertFalse(public["default"])
                        self.assertTrue({"DesignProfileId", "ParticleSourcePath", "EngineeringBudgetPath",
                                         "MeshAutoLevel", "CellMm", "CellMmX", "CellMmY", "CellMmZ", "Adapter"}.isdisjoint(public["parameters"]))
                        calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
                        self.assertEqual(len(calls), 1)
                        self.assertEqual(calls[0][:2], ["-m", "projects.rf_multipole_ion_optics.runtime.runtime_profile"])
                        for flag, expected in (("--project-id", project_id), ("--runtime-profile-id", selected_profile_id)):
                            self.assertEqual(calls[0][calls[0].index(flag) + 1], expected)
                        delegations = runner_path.read_text(encoding="utf-8-sig").splitlines()
                        self.assertEqual(len(delegations), 1)
                        bound = json.loads(delegations[0])
                        self.assertEqual(bound["solver"], f"run_{'simion_' if solver == 'simion' else ''}finite_3d_transport.ps1")
                        self.assertEqual(bound["ProjectId"], project_id)
                        self.assertEqual(bound["RuntimeProfileId"], selected_profile_id)
                        self.assertEqual(bound["DesignProfileId"], profile["design_profile_id"])
                        self.assertEqual(bound["ParticleSourcePath"], profile["particle_source"]["path"])
                        self.assertEqual(bound["EngineeringBudgetPath"], profile["engineering_budget"]["path"])
                        numerics = profile["solver_numerics"][solver]["values"]
                        self.assertEqual(bound["RfStepsPerPeriod"], numerics["trajectory"]["rf_steps_per_period"])
                        self.assertEqual(bound["MaximumTimeUs"], numerics["trajectory"]["maximum_global_time_us"])
                        if solver == "comsol":
                            self.assertEqual(bound["StopStage"], profile["stop_stage"])
                            self.assertEqual(bound["MeshAutoLevel"], numerics["mesh"]["global_auto_level"])
                        else:
                            self.assertEqual([bound[f"CellMm{axis.upper()}"] for axis in "xyz"],
                                             [numerics["cell_mm_xyz"][axis] for axis in "xyz"])
                            self.assertFalse(Path(bound["ResolvedRuntimeProfilePath"]).exists())
            for mutation, error in (("stage", "does not support stop stage"), ("numerics", "System.Double")):
                invalid = copy.deepcopy(profile)
                if mutation == "stage":
                    invalid["stop_stage"] = "mesh_build"
                else:
                    invalid["solver_numerics"]["simion"]["values"]["cell_mm_xyz"]["x"] = "invalid"
                profile_path.write_text(json.dumps(invalid), encoding="utf-8")
                runner_path.unlink(missing_ok=True)
                result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                                        cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)
                self.assertFalse(runner_path.exists())
                failed_call = json.loads(calls_path.read_text().splitlines()[-1])
                self.assertFalse(Path(failed_call[failed_call.index("--output") + 1]).exists())
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command",
                 "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
                 f". '{support}'; Invoke-MultipoleProjectFinite3dTransport -Solver invalid "
                 f"-ProjectId test -RuntimeProfileId test -RepoRoot '{root}'"],
                cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ValidateSet", result.stderr)

    def test_high_order_n100_source_is_n1000_prefix(self) -> None:
        resolved = resolve_design_profile(
            REPO_ROOT, "rf_multipole_ion_optics", "hexapole_no_acceleration_full_length"
        )["resolved_design"]
        projection = l1_l2_transport_contract_from_resolved_design(resolved)
        statistical = copy.deepcopy(projection)
        statistical["particle_source"]["count"] = 1000
        self.assertEqual(source_particles(projection), source_particles(statistical)[:100])
        self.assertEqual(
            from_high_order_baseline(projection),
            from_high_order_resolved_design(resolved),
        )

    def test_obsolete_family_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "family.json"
            path.write_text('{"schema_version": 1, "role": "rf_multipole_family_contract"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema or role differs"):
                load_family_contract(path)

    def test_three_structural_variants_share_one_project_and_family_identity(self) -> None:
        hexapole = from_high_order_resolved_design(
            resolve_design_profile(
                REPO_ROOT, "rf_multipole_ion_optics", "hexapole_no_acceleration_full_length"
            )["resolved_design"]
        )
        octupole = from_high_order_resolved_design(
            resolve_design_profile(
                REPO_ROOT, "rf_multipole_ion_optics", "octupole_no_acceleration_full_length"
            )["resolved_design"]
        )
        quad_root = REPO_ROOT / "projects/rf_multipole_ion_optics/variants/quadrupole/config"
        quadrupole = from_quadrupole_contract(
            load_json(quad_root / "baseline.json"),
            load_json(REPO_ROOT / "projects/rf_multipole_ion_optics/config/modes/quadrupole_mass_filter_reference.json"),
        )
        self.assertEqual(
            {hexapole.identity.family_id, octupole.identity.family_id, quadrupole.identity.family_id},
            {"rf_multipole_ion_optics"},
        )
        self.assertEqual(
            [quadrupole.identity.radial_order_n, hexapole.identity.radial_order_n, octupole.identity.radial_order_n],
            [2, 3, 4],
        )
        self.assertEqual({hexapole.geometry.r0_mm, octupole.geometry.r0_mm, quadrupole.geometry.r0_mm}, {4.0})

    def test_rf_dc_group_voltage_semantics_are_shared(self) -> None:
        root = REPO_ROOT / "projects/rf_multipole_ion_optics/variants/quadrupole/config"
        operating = from_quadrupole_contract(
            load_json(root / "baseline.json"), load_json(REPO_ROOT / "projects/rf_multipole_ion_optics/config/modes/quadrupole_mass_filter_reference.json")
        )
        positive, negative = electrode_group_voltages(operating.voltage, 0.0)
        self.assertAlmostEqual(positive, 14.763014939677756)
        self.assertAlmostEqual(negative, -30.763014939677756)
        self.assertAlmostEqual(positive - negative, 45.52602987935551)

    def test_interface_mode_requires_and_records_explicit_rf_binding(self) -> None:
        root = REPO_ROOT / "projects/rf_multipole_ion_optics/variants/quadrupole/config"
        baseline = load_json(root / "baseline.json")
        mode = load_json(REPO_ROOT / "projects/rf_multipole_ion_optics/config/modes/quadrupole_transport_interface_readiness.json")
        with self.assertRaisesRegex(ValueError, "explicit per-run RF amplitude"):
            from_quadrupole_contract(baseline, mode)
        operating = from_quadrupole_contract(baseline, mode, rf_amplitude_v_per_group=140.0)
        self.assertEqual(operating.voltage.rf_amplitude_v_per_group, 140.0)
        self.assertEqual(operating.voltage.frequency_hz, 1.1e6)
        self.assertEqual(operating.voltage.dc_amplitude_v_per_group, 0.0)

    def test_explicit_run_binding_overrides_embedded_rf_values(self) -> None:
        root = REPO_ROOT / "projects/rf_multipole_ion_optics/variants/quadrupole/config"
        operating = from_quadrupole_contract(
            load_json(root / "baseline.json"),
            load_json(REPO_ROOT / "projects/rf_multipole_ion_optics/config/modes/quadrupole_transport_no_collision.json"),
            rf_amplitude_v_per_group=141.0,
            frequency_hz=1.2e6,
        )
        self.assertEqual(operating.voltage.rf_amplitude_v_per_group, 141.0)
        self.assertEqual(operating.voltage.frequency_hz, 1.2e6)

    def test_waveform_phase_dc_and_common_mode_are_all_executed(self) -> None:
        drive = VoltageDrive("cosine", 10.0, 2.0, -3.0, 1.0, 0.0)
        self.assertEqual(electrode_group_voltages(drive, 0.0), (9.0, -15.0))
        solver = (REPO_ROOT / "projects/rf_multipole_ion_optics/comsol/solve_finite_3d_transport.m").read_text(
            encoding="utf-8"
        )
        for token in ("V_dc", "V_axis", "phi_rf", "rf.waveform", "Vdiff", "Vstatic"):
            self.assertIn(token, solver)

    def test_all_acceleration_modes_use_separate_static_solutions(self) -> None:
        shared_solver = (
            REPO_ROOT / "projects/rf_multipole_ion_optics/comsol/solve_finite_3d_transport.m"
        ).read_text(encoding="utf-8")
        quadrupole_solver = (
            REPO_ROOT
            / "projects"
            / "rf_multipole_ion_optics"
            / "comsol"
            / "solve_deterministic_rf_quadrupole_particles.m"
        ).read_text(encoding="utf-8")
        self.assertIn("if accelerationEnabled\n        studyDiff=", shared_solver)
        self.assertIn("if accelerationEnabled\n        force.set('E'", shared_solver)
        self.assertNotIn("withsol(", quadrupole_solver)
        self.assertNotIn("axial_acceleration_reference", quadrupole_solver)
        self.assertNotIn("exit_aperture_plate_acceleration_reference", quadrupole_solver)
        self.assertIn("withsol(", shared_solver)
        self.assertIn("configure_comsol_stationary_solver", shared_solver)
        self.assertNotIn("configure_comsol_stationary_direct_solver", shared_solver)
        self.assertIn("electric_potential_element_order", shared_solver)
        self.assertIn("apply_electric_potential_element_order(", shared_solver)
        self.assertIn("'order_electricpotential'", shared_solver)
        stationary_helper = (
            REPO_ROOT
            / "projects/rf_multipole_ion_optics/comsol/configure_comsol_stationary_solver.m"
        ).read_text(encoding="utf-8")
        self.assertFalse(
            (
                REPO_ROOT
                / "projects/rf_multipole_ion_optics/comsol/configure_comsol_stationary_direct_solver.m"
            ).exists()
        )
        for token in (
            "'cg_amg'",
            "xor(hasFullyCoupled, hasSegregated)",
            "feature.create('i1', 'Iterative')",
            "iterative.set('linsolver', 'cg')",
            "iterative.set('maxlinit', maximumIterations)",
            "iterative.set('errorchk', errorCheckMode)",
            "feature.create('mg1', 'Multigrid')",
            "feature('mg1').set('prefun', 'amg')",
            "feature('fc1').set('linsolver', 'i1')",
            "stationary.set('control', 'user')",
            "stationary.set('stol', relativeTolerance)",
            "stationary.feature('aDef')",
            "stationary.feature.create('a1', 'Advanced')",
            "advanced.set('convinfo', 'detailed')",
        ):
            self.assertIn(token, stationary_helper)
        self.assertLess(
            stationary_helper.index("feature.create('fc1', 'FullyCoupled')"),
            stationary_helper.index("feature.remove('se1')"),
        )
        self.assertNotIn("feature.remove('i2')", stationary_helper)
        self.assertNotIn("stationary.set('convinfo'", stationary_helper)
        stationary_smoke = (
            REPO_ROOT
            / "projects/rf_multipole_ion_optics/tests/domain/test_comsol_stationary_solver_smoke.m"
        ).read_text(encoding="utf-8")
        for token in (
            "DUAL_PHYSICS_SEGREGATED_TREE_NORMALIZED=1",
            "DUAL_PHYSICS_DIRECT_TREE_NORMALIZED=1",
            "UNUSED_AUTOMATIC_ITERATIVE_FEATURE_TOLERATED=1",
        ):
            self.assertIn(token, stationary_smoke)
        self.assertIn("stationary_iterative_solver", shared_solver)
        self.assertIn("COMSOL_PROGRESS_LINIT_LINRES", shared_solver)
        self.assertNotIn("getSolverLog", shared_solver)
        self.assertIn("getString('order_electricpotential')", shared_solver)
        self.assertIn(
            "isequaln(first.relative_tolerance,second.relative_tolerance)",
            shared_solver,
        )
        self.assertIn("if isfinite(workingHmax) && workingHmax>0", shared_solver)
        self.assertIn("configure_comsol_segment_hybrid_mesh", shared_solver)
        self.assertIn("MESH_SWEPT_SEGMENT_", shared_solver)
        self.assertIn("emit_selection_region(fid, 'MESH_TETRAHEDRAL'", shared_solver)
        self.assertIn("emit_mesh_info(fid, 'MESH_GLOBAL'", shared_solver)
        self.assertIn("emit_selection_region(fid, 'MESH_VACUUM'", shared_solver)
        self.assertIn("emit_mesh_prebuild_diagnostics", shared_solver)
        self.assertIn("emit_mesh_postbuild_diagnostics", shared_solver)
        self.assertIn("MESH_SWEPT_TETRAHEDRAL_OVERLAP_DOMAIN_COUNT", shared_solver)
        self.assertIn("MESH_FEATURE_ROD_BOUNDARY_SIZE_PRESENT", shared_solver)
        self.assertIn("%s_MIN_QUALITY", shared_solver)
        self.assertLess(
            shared_solver.index("emit_mesh_prebuild_diagnostics"),
            shared_solver.index("mesh.run;"),
        )
        self.assertLess(
            shared_solver.index("emit_mesh_postbuild_diagnostics"),
            shared_solver.index("Finite 3D vacuum mesh failed."),
        )
        mesh_build_return = shared_solver.index("return\n    end\n    material =")
        for token in (
            "model.material.create('mat_vac'",
            "comp.physics.create('es'",
            "studyDiff=model.study.create",
            "model.sol.create('sol_es_diff'",
            "comp.physics.create('cpt'",
        ):
            self.assertGreater(shared_solver.index(token), mesh_build_return)
        for token in (
            "FIELD_PHYSICS_CREATED=%d",
            "FIELD_STUDIES_CREATED=%d",
            "FIELD_SOLUTIONS_CREATED=%d",
            "PARTICLE_PHYSICS_CREATED=%d",
            "PARTICLE_STUDIES_CREATED=%d",
        ):
            self.assertIn(token, shared_solver)
        hybrid = (
            REPO_ROOT
            / "projects/rf_multipole_ion_optics/comsol/configure_comsol_segment_hybrid_mesh.m"
        ).read_text(encoding="utf-8")
        for token in (
            "'Sweep'",
            "'Distribution'",
            "'FreeTet'",
            "'sel_mesh_rod_bnd'",
            "sprintf('szRod%d'",
            "'szTetRod'",
            "strategy.radial_core_and_rod_hmax_mm",
            "minimum_element_size_mm, 2",
        ):
            self.assertIn(token, hybrid)
        self.assertGreaterEqual(hybrid.count("if ~localized"), 2)
        self.assertNotIn("'szTetInterface'", hybrid)
        self.assertNotIn("localized_size(", hybrid)
        self.assertNotIn("add_size(mesh, 'szRodBnd'", hybrid)
        self.assertIn("emit_mesh_problem_diagnostics(fid, mesh)", shared_solver)
        self.assertIn("MESH_PROBLEM_%d_MESSAGE=%s", shared_solver)
        self.assertNotIn("feature.hasProblems()", shared_solver)
        self.assertIn("MESH_PROBLEM_DIAGNOSTIC_STATUS=AVAILABLE", shared_solver)
        self.assertIn("MESH_PROBLEM_DIAGNOSTIC_STATUS=UNAVAILABLE", shared_solver)
        self.assertLess(
            shared_solver.index("meshInfo = mphmeshstats(model, 'mesh1')"),
            shared_solver.index("emit_mesh_problem_diagnostics(fid, mesh)"),
        )

    def test_comsol_run_freezes_executed_matlab_sources(self) -> None:
        runner = (REPO_ROOT / "projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1").read_text(encoding="utf-8")
        self.assertIn("$codeRoot=Join-Path $inputDir 'code'", runner)
        self.assertIn("$codeInventory=Join-Path $inputDir 'code_inventory.json'", runner)
        self.assertIn("$task=Join-Path $codeRoot 'projects\\rf_multipole_ion_optics\\comsol\\solve_finite_3d_transport.m'", runner)
        self.assertIn("common\\comsol\\run_comsol_r2025b.ps1", runner)
        self.assertIn("$env:PYTHONPATH=$codeRoot", runner)

    def test_comsol_field_preregistration_is_complete_before_run_package(self) -> None:
        runner = (
            REPO_ROOT / "projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1"
        ).read_text(encoding="utf-8")
        preflight = (
            REPO_ROOT / "projects/rf_multipole_ion_optics/runtime/finite_3d_transport_preflight.ps1"
        ).read_text(encoding="utf-8")
        required_report_gate = preflight.index(
            "preregistration omits required_report"
        )
        package_creation = len(preflight) + runner.index("$package=New-RunPackage")
        postrun_report_use = runner.index(
            "foreach($token in $fieldPreregistration.required_report.tokens)"
        ) + len(preflight)
        self.assertLess(required_report_gate, package_creation)
        self.assertLess(package_creation, postrun_report_use)
        for token in (
            "preregistration required_report fields differ",
            "preregistration required_report values are invalid",
            "preregistration required_report omits core token",
            "preregistration required_report omits forbidden checkpoint",
            "CHECKPOINT=STATIONARY_FIELD_SAMPLES_COMPLETE",
            "PRIMARY_PARTICLE_CASE_COMPLETE",
            "CONTROL_PARTICLE_CASE_COMPLETE",
        ):
            self.assertIn(token, preflight)

    def test_comsol_canonical_state_policy_is_resolved_design_only(self) -> None:
        runner = (REPO_ROOT / "projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1").read_text(encoding="utf-8")
        self.assertIn("$env:MULTIPOLE_L3_CANONICAL_STATE=$canonicalState", runner)
        self.assertIn("$env:MULTIPOLE_L3_SOLVER_PROGRESS_DIR=$solverProgressDir", runner)
        self.assertIn("$solverProgressDir=Join-Path $logDir 'solver_progress'", runner)
        self.assertIn("Get-ChildItem -LiteralPath $solverProgressDir -File", runner)
        self.assertIn("MULTIPOLE_L3_PARTICLE_SOURCE_METADATA", runner)
        self.assertIn(
            "$outputs=@($events,$trajectories,$metrics,$plot,$exitStatePlot,$exitStatePlotManifest,",
            runner,
        )
        self.assertIn("$model,$canonicalState,$resourceUsage", runner)
        self.assertIn("-m projects.rf_multipole_ion_optics.analysis.exit_state_plot", runner)
        self.assertNotIn("AxialAccelerationContractPath", runner)
        self.assertNotIn("Adapter", runner)
        solver = (
            REPO_ROOT / "projects/rf_multipole_ion_optics/comsol/solve_finite_3d_transport.m"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "write_canonical_particle_state(pdOn,source,canonicalStatePath",
            solver,
        )
        self.assertIn("'handoff_plane_z',interfaces.exit.handoff_plane_z_mm", solver)
        self.assertIn("d.handoff_plane_z,d.census_plane_z", solver)
        self.assertNotIn(
            "d.exit_aperture_plate_downstream_face_z,d.census_plane_z,g.working_region_radius",
            solver,
        )
        self.assertIn("'rod_z_min',resolvedGeometry.rod_z_min", solver)
        self.assertNotIn("g.rod_z_min", solver)
        self.assertNotIn("90.2", runner)
        self.assertNotIn("90.2", solver)

    def test_comsol_segmented_run_keeps_paired_arms_and_external_evidence(self) -> None:
        runner = (
            REPO_ROOT / "projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1"
        ).read_text(encoding="utf-8")
        for token in (
            "DesignProfileId",
            "EvidenceContractPath",
            "evaluate_transport_evidence",
            "qualification_status=$qualification",
        ):
            self.assertIn(token, runner)
        solver = (REPO_ROOT / "projects/rf_multipole_ion_optics/comsol/solve_finite_3d_transport.m").read_text(
            encoding="utf-8"
        )
        self.assertIn("axial_acceleration_rf_on", solver)
        self.assertIn("zero_axial_drop_rf_on", solver)
        self.assertNotIn("functional_acceptance", solver)


class MultipoleMassResponseTests(unittest.TestCase):
    def test_paired_rows_change_only_mass(self) -> None:
        source = [["0", "100", "1", "0", "0.1", "0.2", "0", "0", "2", "1", "3"]]
        rows = build_paired_ion_rows(source, [90.0, 100.0, 110.0])
        self.assertEqual([float(row[1]) for row in rows], [90.0, 100.0, 110.0])
        self.assertEqual(rows[0][2:], rows[1][2:])

    def test_generic_functional_contrast(self) -> None:
        response = aggregate_response(
            {1: 90.0, 2: 100.0, 3: 110.0},
            {1: "lost", 2: "transmitted", 3: "lost"},
        )
        metrics = evaluate_functional_contrast(response, 100.0, {
            "minimum_center_transmission": 0.8,
            "maximum_endpoint_transmission": 0.2,
            "minimum_center_to_endpoint_contrast": 0.6,
        })
        self.assertEqual(metrics["status"], "PASS")

    def test_unknown_terminal_status_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "particle_state.csv"
            fixture.write_text("particle_id,event,status\n1,terminal,unknown\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown terminal status"):
                load_terminal_statuses(fixture)


if __name__ == "__main__":
    unittest.main()
