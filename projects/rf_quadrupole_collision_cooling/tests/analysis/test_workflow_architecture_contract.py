from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
INTERFACE_RUNNER = (
    PROJECT_ROOT / "workflows" / "interface_readiness" / "run_simion.ps1"
)
MASS_FILTER_RUNNER = (
    PROJECT_ROOT / "workflows" / "mass_filter_reference" / "run_simion.ps1"
)
MASS_FILTER_WORKFLOW = PROJECT_ROOT / "workflows" / "mass_filter_reference"
SAME_SOLVER_WORKFLOW = PROJECT_ROOT / "workflows" / "same_solver_convergence"
SIMION_CONFIG_CORE = PROJECT_ROOT / "runtime" / "simion_run_config.ps1"
SIMION_EXECUTION_SUPPORT = PROJECT_ROOT / "runtime" / "simion_execution.ps1"
RUNTIME_ROOT = PROJECT_ROOT / "runtime"
RUN_ARTIFACT_SUPPORT = REPO_ROOT / "common" / "contracts" / "run_artifact_support.ps1"
SHARED_SIMION_LUA = REPO_ROOT / "common" / "multipole" / "simion_transport.lua"
EXECUTION_PROFILES = PROJECT_ROOT / "config" / "execution_profiles.json"
OFFICIAL_RESOLVED = PROJECT_ROOT / "config" / "resolved_design_official.json"
MASS_FILTER_RESOLVED = PROJECT_ROOT / "config" / "resolved_design_mass_filter.json"
INTERFACE_MODE = (
    PROJECT_ROOT / "config" / "modes" / "transport_interface_readiness.json"
)
MASS_FILTER_MODE = PROJECT_ROOT / "config" / "modes" / "mass_filter_reference.json"
INTERFACE_CONTRACT = PROJECT_ROOT / "config" / "interface_contract.json"
SIMION_SOLVER_NUMERICS = PROJECT_ROOT / "config" / "simion_solver_numerics.json"
SIMION_GEM = PROJECT_ROOT / "simion" / "geometry" / "quad_monolithic.gem"
PAIRED_BUNDLE_CORE = PROJECT_ROOT / "analysis" / "paired_particle_source_bundle.py"
INTERFACE_SOURCE_POLICY = (
    PROJECT_ROOT
    / "workflows"
    / "interface_readiness"
    / "particle_source_policy.py"
)
INTERFACE_SOURCE_CLI = (
    PROJECT_ROOT
    / "workflows"
    / "interface_readiness"
    / "generate_particle_table.py"
)

DEDICATED_RUNNERS = (INTERFACE_RUNNER, MASS_FILTER_RUNNER)
CONDITIONAL_LUA_FIELDS = {
    "ground_electrode_id",
    "ground_reference_v",
    "output_electrode_id",
    "output_reference_v",
}
LATE_LUA_FIELDS = {"mode", "operating_point", "summary_json"}
PHYSICAL_PROFILE_SWITCHES = {
    "axialvoltagev",
    "dcamplitudev",
    "detectorradiusmm",
    "detectorvoltagev",
    "entrancevoltagev",
    "exitvoltagev",
    "frequencyhz",
    "handoffplanemm",
    "rfpeakv",
    "rodzmaxmm",
    "rodzminmm",
    "waveform",
}
NUMERICAL_OVERRIDE_SWITCHES = {"rfstepsperperiod", "trajectoryquality"}
BLOCKING_PROFILE_IDS = {
    "transport_no_collision_candidate",
    "transport_interface_readiness_candidate",
    "mass_filter_simion_functional_reference",
}
REPORT_ONLY_PROFILE_IDS: set[str] = set()
DEDICATED_SIMION_PROFILE_IDS = {
    "transport_interface_readiness_candidate",
    "mass_filter_simion_functional_reference",
}
CONFIG_CORE_FUNCTIONS = {
    "Get-VerifiedRfSimionWaveform",
    "Get-VerifiedRfSimionResolvedSha256",
    "Assert-RfSimionLuaConfigContract",
    "Assert-RfSimionEqualLength",
    "Get-RfSimionRequiredProperty",
    "Get-RfSimionRequiredFiniteNumber",
    "New-RfSimionCoreRunConfig",
    "ConvertTo-RfSimionLuaLongString",
    "ConvertTo-RfSimionLuaConfig",
}
EXECUTION_SUPPORT_FUNCTIONS = {"Invoke-RfSimionCoreRun"}
RUNTIME_MODULE_FUNCTIONS = {
    "analysis_run_lifecycle.ps1": {
        "Assert-PortableManifestRecord",
        "Copy-PortableRunManifestClosure",
        "Add-RunInputClosure",
    },
    "comsol_solver_numerics.ps1": {
        "Get-RfComsolRequiredProperty",
        "Get-RfComsolRequiredFiniteNumber",
        "ConvertTo-RfComsolCanonicalValue",
        "Get-RfComsolLogicalSha256",
        "Read-RfComsolSolverNumericsContract",
        "Compile-RfComsolSolverNumerics",
    },
    "cross_solver_analysis_lifecycle.ps1": {
        "New-CrossSolverAnalysisPackage",
        "Assert-CrossSolverSourceManifest",
        "Get-CrossSolverSourcePair",
        "Get-CrossSolverResolvedDrive",
        "Copy-CrossSolverAnalysisInputs",
        "New-CrossSolverFrozenPathSet",
        "Invoke-CrossSolverAnalyzer",
        "Complete-CrossSolverAnalysis",
    },
    "particle_table_identity.ps1": {
        "Resolve-RfConfigInputPath",
        "Assert-RfTransportParticleTableIdentity",
    },
    "run_artifacts.ps1": {
        "Write-RfFrozenRunManifest",
        "Complete-RfFrozenFailedRun",
        "Resolve-RfDirectChildDirectory",
        "Get-RfManifestInputRecord",
        "Get-RfManifestOutputRecord",
        "Copy-RfStableFile",
        "Copy-RfManifestBoundFile",
        "Confirm-RfFrozenDependencyIdentity",
        "Test-RfDependencyPathWithin",
        "Copy-RfFrozenDependency",
    },
    "frozen_python_package.ps1": {
        "New-FrozenPythonPackage",
        "Assert-FrozenPythonPackage",
        "Get-FrozenPythonPackageFile",
        "Invoke-IsolatedFrozenPythonModule",
    },
    "simion_execution.ps1": EXECUTION_SUPPORT_FUNCTIONS,
    "simion_run_config.ps1": CONFIG_CORE_FUNCTIONS,
}
LEGACY_RUNTIME_FILES = {
    "analysis_run_support.ps1",
    "comsol_solver_numerics_contract.ps1",
    "cross_solver_analysis_support.ps1",
    "particle_table_identity.ps1",
    "rf_run_artifact_support.ps1",
    "simion_execution_support.ps1",
    "simion_run_config_contract.ps1",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parameter_block(source: str) -> str:
    return source[: source.index("Set-StrictMode")]


def _powershell_functions(source: str) -> set[str]:
    return set(re.findall(r"(?im)^\s*function\s+([A-Za-z0-9_-]+)\b", source))


def _production_line_count(source: str) -> int:
    return sum(
        1
        for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


class WorkflowArchitectureContractTests(unittest.TestCase):
    def test_runtime_modules_have_exact_responsibility_inventory(self) -> None:
        self.assertEqual(
            {path.name for path in RUNTIME_ROOT.glob("*.ps1")},
            set(RUNTIME_MODULE_FUNCTIONS),
        )
        for filename, functions in RUNTIME_MODULE_FUNCTIONS.items():
            source = _read(RUNTIME_ROOT / filename)
            self.assertEqual(_powershell_functions(source), functions, filename)
            self.assertIn("$ErrorActionPreference = 'Stop'", source)
            self.assertNotRegex(source, r"(?i)tests[/\\](?:support|cross_solver)")

    def test_tests_do_not_redefine_runtime_mechanisms(self) -> None:
        runtime_functions = set().union(*RUNTIME_MODULE_FUNCTIONS.values())
        for path in (PROJECT_ROOT / "tests").rglob("*.ps1"):
            overlap = _powershell_functions(_read(path)) & runtime_functions
            self.assertEqual(
                overlap,
                set(),
                f"{path} redefines runtime mechanisms: {sorted(overlap)}",
            )
        for legacy in (
            PROJECT_ROOT / "tests" / "support",
            PROJECT_ROOT / "tests" / "cross_solver",
        ):
            legacy_files = {
                path.name
                for path in legacy.glob("*.ps1")
                if path.name in LEGACY_RUNTIME_FILES
            }
            self.assertEqual(legacy_files, set())

    def test_profile_inventory_classifies_every_active_workflow(self) -> None:
        profiles = json.loads(EXECUTION_PROFILES.read_text(encoding="utf-8"))[
            "profiles"
        ]
        profile_ids = {profile["profile_id"] for profile in profiles}
        self.assertTrue(BLOCKING_PROFILE_IDS.isdisjoint(REPORT_ONLY_PROFILE_IDS))
        self.assertEqual(
            profile_ids,
            BLOCKING_PROFILE_IDS | REPORT_ONLY_PROFILE_IDS,
            "new profiles must be explicitly classified before architecture rollout",
        )

    def test_workflow_locations_and_dependency_direction_are_blocking(self) -> None:
        expected_entries = {
            "transport_no_collision_candidate": {
                "workflows/no_collision_transport/run_comsol.ps1",
                "workflows/no_collision_transport/run_simion.ps1",
                "workflows/no_collision_transport/compare_cross_solver.ps1",
            },
            "transport_interface_readiness_candidate": {
                "workflows/interface_readiness/run_comsol.ps1",
                "workflows/interface_readiness/run_simion.ps1",
                "workflows/interface_readiness/compare_cross_solver.ps1",
            },
            "mass_filter_simion_functional_reference": {
                "workflows/mass_filter_reference/run_simion.ps1",
            },
        }
        profiles = {
            profile["profile_id"]: profile
            for profile in json.loads(
                EXECUTION_PROFILES.read_text(encoding="utf-8")
            )["profiles"]
        }
        for profile_id, expected in expected_entries.items():
            entrypoints = {
                step["entrypoint"]
                for step in profiles[profile_id]["steps"]
                if step["kind"] in {"run", "analyze"}
            }
            self.assertEqual(entrypoints, expected)
            self.assertFalse(
                any(
                    entrypoint.startswith(("tests/", "analysis/", "../../common/"))
                    for entrypoint in entrypoints
                )
            )
        forbidden_locations = (
            PROJECT_ROOT / "tests" / "comsol" / "run_transport_candidate.ps1",
            PROJECT_ROOT / "tests" / "simion" / "run_transport_candidate.ps1",
            PROJECT_ROOT
            / "tests"
            / "cross_solver"
            / "verify_transport_candidate.ps1",
            PROJECT_ROOT
            / "tests"
            / "cross_solver"
            / "verify_no_collision_candidate.ps1",
            PROJECT_ROOT / "analysis" / "compare_interface_readiness.py",
            PROJECT_ROOT / "analysis" / "compare_no_collision_transport.py",
            PROJECT_ROOT / "analysis" / "assess_interface_integration_gate.py",
        )
        self.assertFalse(any(path.exists() for path in forbidden_locations))
        for root in (
            PROJECT_ROOT / "tests" / "comsol",
            PROJECT_ROOT / "tests" / "simion",
        ):
            self.assertFalse(
                any(
                    "mass_filter" in path.stem
                    for path in root.iterdir()
                    if path.suffix.lower() in {".ps1", ".m"}
                )
            )
        self.assertFalse(
            any(
                "same_solver" in path.stem
                for path in (PROJECT_ROOT / "tests" / "analysis").glob("*.ps1")
            )
        )
        active_prefixes = (
            "analyze_",
            "prepare_",
            "run_",
            "generate_",
            "render_",
            "compare_",
        )
        self.assertFalse(
            any(
                path.stem.startswith(active_prefixes)
                and (
                    "mass_filter" in path.stem
                    or "mass_scan" in path.stem
                    or "same_solver" in path.stem
                )
                for path in (PROJECT_ROOT / "analysis").glob("*.py")
            )
        )
        reverse_dependency = re.compile(
            r"projects\.rf_quadrupole_collision_cooling\.workflows|"
            r"Join-Path[^\r\n]*['\"]workflows[/\\]"
        )
        for root in (
            PROJECT_ROOT / "analysis",
            PROJECT_ROOT / "runtime",
            PROJECT_ROOT / "comsol",
            PROJECT_ROOT / "simion",
        ):
            for path in root.rglob("*"):
                if path.suffix.lower() not in {".py", ".ps1", ".m"}:
                    continue
                self.assertIsNone(
                    reverse_dependency.search(_read(path)),
                    f"{path.relative_to(PROJECT_ROOT)} reverses workflow dependency",
                )

    def test_batch3_workflows_have_exact_single_purpose_inventory(self) -> None:
        self.assertEqual(
            {path.name for path in MASS_FILTER_WORKFLOW.iterdir() if path.is_file()},
            {
                "__init__.py",
                "compare_responses.ps1",
                "evaluate_comparison.py",
                "evaluate_comsol.py",
                "evaluate_simion.py",
                "prepare_comsol_scan.py",
                "prepare_simion_scan.py",
                "render_simion_source.py",
                "run_comsol.ps1",
                "run_finite_length.py",
                "run_simion.ps1",
                "theory.py",
            },
        )
        self.assertEqual(
            {path.name for path in SAME_SOLVER_WORKFLOW.iterdir() if path.is_file()},
            {"__init__.py", "evaluate.py", "run_comparison.ps1"},
        )
        comsol_evaluator = _read(MASS_FILTER_WORKFLOW / "evaluate_comsol.py")
        simion_evaluator = _read(MASS_FILTER_WORKFLOW / "evaluate_simion.py")
        comparison_evaluator = _read(
            MASS_FILTER_WORKFLOW / "evaluate_comparison.py"
        )
        self.assertNotIn("evaluate_simion", comsol_evaluator)
        self.assertNotIn("theory_masses", comsol_evaluator)
        self.assertNotIn("simion", comsol_evaluator.lower())
        self.assertIn(".theory import theory_masses", simion_evaluator)
        self.assertIn(".theory import theory_masses", comparison_evaluator)
        comparison_runner = _read(
            MASS_FILTER_WORKFLOW / "compare_responses.ps1"
        )
        for source_run_id in ("ComsolRunId", "SimionRunId", "L1RunId"):
            self.assertIn(source_run_id, comparison_runner)
        self.assertNotRegex(
            _parameter_block(comparison_runner),
            r"(?i)\$Mode\b",
        )
        self.assertIn(
            "Copy-PortableRunManifestClosure",
            comparison_runner,
        )
        same_runner = _read(SAME_SOLVER_WORKFLOW / "run_comparison.ps1")
        self.assertNotRegex(_parameter_block(same_runner), r"(?i)\$Mode\b")
        self.assertIn("New-FrozenPythonPackage", same_runner)
        self.assertIn("Invoke-IsolatedFrozenPythonModule", same_runner)

    def test_dedicated_runners_have_no_mode_switch_or_inline_lua_core(self) -> None:
        for runner_path in DEDICATED_RUNNERS:
            source = _read(runner_path)
            parameter_block = _parameter_block(source)
            self.assertNotRegex(parameter_block, r"(?i)\$Mode\b")
            self.assertNotRegex(
                parameter_block,
                r"(?i)\$(?:RfStepsPerPeriod|TrajectoryQuality)\s*=\s*\d",
                f"{runner_path.name} must source default numerics from its contract",
            )
            self.assertNotRegex(
                source,
                r"(?m)^\s*return\s*\{",
                f"{runner_path.name} must call the shared Lua config serializer",
            )
            self.assertNotRegex(source, r"function\s+New-LuaConfig\b")
            self.assertNotIn("gem2pa", source)
            self.assertNotIn("Start-Process -FilePath $simion", source)

    def test_shared_lua_config_core_has_no_workflow_dispatch(self) -> None:
        source = _read(SIMION_CONFIG_CORE)
        branch = re.compile(
            r"(?im)^\s*(?:if|elseif|switch)\b[^\r\n]*"
            r"(?:workflow|mode|role|interface|mass[_-]?filter)"
        )
        self.assertIsNone(
            branch.search(source),
            "shared SIMION config core must not dispatch scientific workflows",
        )

    def test_particle_bundle_policy_is_owned_only_by_interface_workflow(self) -> None:
        core = _read(PAIRED_BUNDLE_CORE)
        policy = _read(INTERFACE_SOURCE_POLICY)
        cli = _read(INTERFACE_SOURCE_CLI)
        for forbidden in (
            "official_100amu_2eV",
            "rf_to_oatof_100amu_5eV",
            "rf_interface_paired_latent_family",
            "rf_quadrupole_paired_particle_source_bundle",
            "candidate",
            "interface",
            "threshold",
        ):
            self.assertNotIn(forbidden, core)
        for required in (
            "official_100amu_2eV",
            "rf_to_oatof_100amu_5eV",
            "rf_interface_paired_latent_family.v2",
            "rf_quadrupole_paired_particle_source_bundle",
            '"min": 1.8',
            '"max": 2.2',
            '"value": 5.0',
        ):
            self.assertIn(required, policy)
        self.assertIn("particle_source_policy import", cli)
        self.assertNotIn("generate_single_table", cli)
        for legacy_option in ("--operating-point", "--particles", "--output", "--metadata"):
            self.assertNotIn(legacy_option, cli)
        for consumer in (
            PROJECT_ROOT / "analysis" / "analyze_axial_acceleration_four_arm_runs.py",
            PROJECT_ROOT
            / "analysis"
            / "validate_axial_acceleration_four_arm_experiment.py",
            PROJECT_ROOT / "analysis" / "validate_paired_particle_source_binding.py",
        ):
            source = _read(consumer)
            self.assertIn("analysis.paired_particle_source_bundle import", source)
            self.assertNotIn(".workflows.", source)
        for runner in (
            PROJECT_ROOT / "workflows" / "interface_readiness" / "run_comsol.ps1",
            INTERFACE_RUNNER,
        ):
            source = _read(runner)
            self.assertIn("particle_source_policy.py", source)
            self.assertIn("paired_particle_source_bundle.py", source)
            self.assertIn("generate_particle_table", source)
            self.assertIn("--validate-bundle", source)

    def test_shared_modules_have_registered_narrow_responsibilities(self) -> None:
        config_core = _read(SIMION_CONFIG_CORE)
        execution_support = _read(SIMION_EXECUTION_SUPPORT)
        artifact_support = _read(RUN_ARTIFACT_SUPPORT)

        self.assertEqual(_powershell_functions(config_core), CONFIG_CORE_FUNCTIONS)
        self.assertEqual(
            _powershell_functions(execution_support),
            EXECUTION_SUPPORT_FUNCTIONS,
        )
        for primitive in ("Start-Process", "Copy-Item", "Get-FileHash"):
            self.assertNotIn(primitive, config_core)
        for foreign_function in (
            "Invoke-RfSimionCoreRun",
            "Copy-VerifiedRunInput",
            "Write-RunDirectoryChecksumInventory",
        ):
            self.assertNotIn(foreign_function, config_core)

        for foreign_function in CONFIG_CORE_FUNCTIONS | {
            "Copy-VerifiedRunInput",
            "Write-RunDirectoryChecksumInventory",
        }:
            self.assertNotIn(foreign_function, execution_support)
        self.assertNotRegex(
            execution_support,
            r"(?i)\b(?:role|mode|mass[_-]?filter|interface_contract|rf_peak|waveform)\b",
        )

        artifact_functions = _powershell_functions(artifact_support)
        self.assertTrue(
            {
                "Copy-VerifiedRunInput",
                "Write-RunDirectoryChecksumInventory",
                "Get-RunFileSha256",
            }.issubset(artifact_functions)
        )
        self.assertNotRegex(
            artifact_support,
            r"(?i)\b(?:rf_quadrupole|mass[_-]?filter|"
            r"transport_interface|rf_peak|waveform|operating_point)\b",
        )
        self.assertNotRegex(
            artifact_support,
            r"(?im)^\s*(?:if|elseif|switch)\b[^\r\n]*\$(?:Role|Mode)\b",
        )

    def test_runners_only_orchestrate_registered_mechanisms(self) -> None:
        for runner_path in DEDICATED_RUNNERS:
            source = _read(runner_path)
            for support_path in (
                "common\\contracts\\run_artifact_support.ps1",
                "runtime\\simion_run_config.ps1",
                "runtime\\simion_execution.ps1",
            ):
                self.assertIn(support_path, source)
            for function in (
                "New-RfSimionCoreRunConfig",
                "ConvertTo-RfSimionLuaConfig",
                "Invoke-RfSimionCoreRun",
                "Copy-VerifiedRunInput",
                "Write-RunDirectoryChecksumInventory",
            ):
                self.assertIn(function, source)
            for direct_primitive in (
                "Start-Process",
                "Copy-Item",
                "Get-FileHash",
            ):
                self.assertNotIn(direct_primitive, source)
            self.assertNotRegex(source, r"(?m)^\s*return\s*\{")
            self.assertRegex(
                source,
                r"-SharedProgramPath\s+\(Join-Path\s+\$candidateDir\s+"
                r"'quad_monolithic\.lua'\)",
                "validator must bind the frozen runtime Lua program",
            )

    def test_runners_call_one_shared_full_lua_config_core(self) -> None:
        core = _read(SIMION_CONFIG_CORE)
        required_calls = {
            "New-RfSimionCoreRunConfig",
            "ConvertTo-RfSimionLuaConfig",
        }
        for function in required_calls:
            self.assertRegex(core, rf"(?im)^\s*function\s+{function}\b")
        self.assertRegex(
            core,
            r"(?im)^\s*function\s+Assert-RfSimionLuaConfigContract\b",
        )
        for runner_path in DEDICATED_RUNNERS:
            runner = _read(runner_path)
            for function in required_calls:
                self.assertRegex(runner, rf"\b{function}\b")

    def test_runners_call_shared_workflow_neutral_launcher(self) -> None:
        execution_support = _read(SIMION_EXECUTION_SUPPORT)
        artifact_support = _read(RUN_ARTIFACT_SUPPORT)
        self.assertRegex(
            execution_support,
            r"(?im)^\s*function\s+Invoke-RfSimionCoreRun\b",
        )
        self.assertRegex(
            artifact_support,
            r"(?im)^\s*function\s+Write-RunDirectoryChecksumInventory\b",
        )
        for runner_path in DEDICATED_RUNNERS:
            runner = _read(runner_path)
            for function in (
                "Invoke-RfSimionCoreRun",
                "Write-RunDirectoryChecksumInventory",
            ):
                self.assertRegex(runner, rf"\b{function}\b")

    def test_shared_config_core_covers_complete_unconditional_lua_contract(self) -> None:
        lua = _read(SHARED_SIMION_LUA)
        required = set(re.findall(r"assert\(run_config\.([a-z0-9_]+)", lua))
        required.difference_update(CONDITIONAL_LUA_FIELDS)
        required.update(LATE_LUA_FIELDS)
        self.assertIn("parent_resolved_design_sha256", required)
        self.assertIn("waveform", required)

        core = _read(SIMION_CONFIG_CORE)
        missing = sorted(field for field in required if field not in core)
        self.assertEqual(
            missing,
            [],
            "shared config core does not validate/serialize the complete Lua contract",
        )

    def test_required_physics_cannot_silently_fall_back_to_zero(self) -> None:
        lua = _read(SHARED_SIMION_LUA)
        physics_fields = {
            "rf_peak_v",
            "dc_amplitude_v",
            "frequency_hz",
            "phase_deg",
            "waveform",
            "axis_voltage_v",
            "entrance_voltage_v",
            "exit_voltage_v",
            "detector_voltage_v",
            "rf_steps_per_period",
            "maximum_time_us",
        }
        for field in physics_fields:
            self.assertRegex(lua, rf"assert\(run_config\.{field}\)")
            self.assertNotRegex(lua, rf"run_config\.{field}\s+or\s+0(?:\.0)?\b")

    def test_profiles_bind_identity_not_repeated_physical_scalars(self) -> None:
        profiles = json.loads(EXECUTION_PROFILES.read_text(encoding="utf-8"))[
            "profiles"
        ]
        dedicated = {
            profile["profile_id"]: profile
            for profile in profiles
            if profile["profile_id"] in DEDICATED_SIMION_PROFILE_IDS
        }
        self.assertEqual(set(dedicated), DEDICATED_SIMION_PROFILE_IDS)
        for profile in dedicated.values():
            self.assertIn(
                "simion_solver_numerics_contract_path",
                profile["required_bindings"],
            )
            simion_steps = [
                step
                for step in profile["steps"]
                if step.get("kind") == "run"
                and step.get("entrypoint", "")
                in {
                    "workflows/interface_readiness/run_simion.ps1",
                    "workflows/mass_filter_reference/run_simion.ps1",
                }
            ]
            self.assertEqual(len(simion_steps), 1)
            simion_arguments = simion_steps[0]["arguments"]
            argument_values = dict(zip(simion_arguments[::2], simion_arguments[1::2]))
            self.assertEqual(
                argument_values["-SolverNumericsContractPath"],
                "{simion_solver_numerics_contract_path}",
            )
            self.assertTrue(
                set(argument_values).isdisjoint(
                    {"-RfStepsPerPeriod", "-TrajectoryQuality"}
                ),
                "ordinary profiles must take numerics only from the bound contract",
            )
            for step in profile["steps"]:
                arguments = step.get("arguments", [])
                switches = {
                    argument[1:].replace("-", "").lower()
                    for argument in arguments
                    if isinstance(argument, str) and argument.startswith("-")
                }
                self.assertTrue(
                    switches.isdisjoint(
                        PHYSICAL_PROFILE_SWITCHES | NUMERICAL_OVERRIDE_SWITCHES
                    ),
                    f"{profile['profile_id']} repeats governed physical/numerical values",
                )

        interface = dedicated["transport_interface_readiness_candidate"]
        self.assertIn("operating_point_id", interface["required_bindings"])
        for step in interface["steps"]:
            if step.get("kind") == "run":
                arguments = step.get("arguments", [])
                argument_values = dict(zip(arguments[::2], arguments[1::2]))
                self.assertEqual(
                    argument_values["-OperatingPoint"],
                    "{operating_point_id}",
                )

    def test_shared_geometry_and_scientific_contracts_do_not_drift(self) -> None:
        official = json.loads(OFFICIAL_RESOLVED.read_text(encoding="utf-8"))
        mass_resolved = json.loads(MASS_FILTER_RESOLVED.read_text(encoding="utf-8"))
        mass_mode = json.loads(MASS_FILTER_MODE.read_text(encoding="utf-8"))
        interface_mode = json.loads(INTERFACE_MODE.read_text(encoding="utf-8"))
        interface = json.loads(INTERFACE_CONTRACT.read_text(encoding="utf-8"))
        simion_numerics = json.loads(
            SIMION_SOLVER_NUMERICS.read_text(encoding="utf-8")
        )

        self.assertEqual(official["geometry_mm"], mass_resolved["geometry_mm"])
        self.assertEqual(official["interfaces_mm"], mass_resolved["interfaces_mm"])

        drive_pairs = {
            "frequency": (
                mass_mode["rf"]["frequency_Hz"],
                mass_resolved["drive"]["frequency_Hz"],
            ),
            "rf_amplitude": (
                mass_mode["rf"]["amplitude_V_zero_to_peak_per_group"],
                mass_resolved["drive"]["rf_amplitude_V_zero_to_peak_per_group"],
            ),
            "dc_amplitude": (
                mass_mode["rf"]["dc_amplitude_V_per_group"],
                mass_resolved["drive"]["dc_amplitude_V_per_group"],
            ),
            "common_mode": (
                mass_mode["rf"]["axis_common_mode_offset_V"],
                mass_resolved["drive"]["common_mode_offset_V"],
            ),
        }
        static_pairs = {
            "entrance": (
                mass_mode["static_electrodes_V"]["entrance_plate"],
                mass_resolved["static_electrodes_V"][
                    "entrance_plate_and_connector"
                ],
            ),
            "exit": (
                mass_mode["static_electrodes_V"]["exit_enclosure"],
                mass_resolved["static_electrodes_V"][
                    "exit_enclosure_and_connector"
                ],
            ),
            "detector": (
                mass_mode["static_electrodes_V"]["detector"],
                mass_resolved["static_electrodes_V"]["detector"],
            ),
        }
        for label, pair in {**drive_pairs, **static_pairs}.items():
            self.assertEqual(pair[0], pair[1], label)

        self.assertEqual(
            interface_mode["operating_point_policy"]["rf_frequency_Hz"],
            official["drive"]["frequency_Hz"],
        )
        self.assertAlmostEqual(
            interface["planes"]["source"]["z_mm"],
            official["interfaces_mm"]["entrance"]["particle_plane_z_mm"],
        )
        self.assertAlmostEqual(
            interface["planes"]["rod_exit"]["z_mm"],
            official["geometry_mm"]["rod_z_max"],
        )
        self.assertAlmostEqual(
            interface["planes"]["handoff"]["z_mm"],
            official["interfaces_mm"]["exit"]["plate_z_max_mm"],
        )
        self.assertAlmostEqual(
            interface["planes"]["acceptance_detector"]["z_mm"],
            official["interfaces_mm"]["exit"]["particle_plane_z_mm"],
        )

        gem_cell = float(
            re.search(r"(?m)^# local mmgu = ([0-9.]+)$", _read(SIMION_GEM)).group(1)
        )
        self.assertEqual(simion_numerics["simion_cell_mm"], gem_cell)

    def test_runners_use_shared_run_lifecycle(self) -> None:
        for runner_path in DEDICATED_RUNNERS:
            source = _read(runner_path)
            self.assertIn("common\\contracts\\run_artifact_support.ps1", source)
            for function in (
                "New-RunPackage",
                "Complete-FailedRun",
                "Write-VerifiedRunManifest",
            ):
                self.assertIn(function, source)
                self.assertNotRegex(source, rf"(?im)^\s*function\s+{function}\b")

    def test_production_size_and_duplication_are_report_only(self) -> None:
        sources = {
            path.name: _read(path)
            for path in (
                SIMION_CONFIG_CORE,
                SIMION_EXECUTION_SUPPORT,
                *DEDICATED_RUNNERS,
            )
        }
        line_counts = {
            name: _production_line_count(source)
            for name, source in sources.items()
        }
        runner_lines = [
            {
                line.strip()
                for line in _read(path).splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            }
            for path in DEDICATED_RUNNERS
        ]
        duplicate_ratio = len(runner_lines[0] & runner_lines[1]) / max(
            1, min(map(len, runner_lines))
        )
        print(  # noqa: T201 - intentionally visible, non-blocking architecture report
            "WORKFLOW_ARCHITECTURE_REPORT "
            f"production_loc={line_counts} "
            f"runner_exact_line_overlap={duplicate_ratio:.3f}"
        )


if __name__ == "__main__":
    unittest.main()
