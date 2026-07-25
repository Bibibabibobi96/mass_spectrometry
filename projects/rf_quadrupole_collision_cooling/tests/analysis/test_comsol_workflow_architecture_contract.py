from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from projects.rf_quadrupole_collision_cooling.analysis.validate_release_construction_gate import (
    _expected_release_state,
)


PROJECT_ROOT = Path(__file__).parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
NUMERICS = PROJECT_ROOT / "config" / "comsol_solver_numerics.json"
MODE = PROJECT_ROOT / "config" / "modes" / "transport_interface_readiness.json"
PROFILES = PROJECT_ROOT / "config" / "execution_profiles.json"
RUNNER = PROJECT_ROOT / "workflows" / "interface_readiness" / "run_comsol.ps1"
TASK = PROJECT_ROOT / "tests" / "comsol" / "run_nocollision_candidate.m"
RELEASE_GATE_TASK = (
    PROJECT_ROOT / "comsol" / "interface_readiness" / "run_release_construction_gate.m"
)
DEDICATED_ENTRY = (
    PROJECT_ROOT / "comsol" / "prepare_interface_readiness_run.m"
)
SHARED_SOLVER = (
    PROJECT_ROOT / "comsol" / "solve_deterministic_rf_quadrupole_particles.m"
)
NUMERICS_SUPPORT = PROJECT_ROOT / "runtime" / "comsol_solver_numerics.ps1"
RUN_ARTIFACT_SUPPORT = REPO_ROOT / "common" / "contracts" / "run_artifact_support.ps1"
ARTIFACT_ROOT = REPO_ROOT.parent / "artifacts" / "projects" / "rf_quadrupole_collision_cooling"
RUN_PYTHON = Path(sys.executable).resolve()
OFFICIAL_ION11 = PROJECT_ROOT / "config" / "particles" / "official_fixed_100.ion"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _logical_sha256(document: dict[str, object]) -> str:
    payload = dict(document)
    payload.pop("logical_sha256", None)
    encoded = json.dumps(
        payload, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def _run_pwsh(command: str, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        check=False,
        encoding="utf-8",
        env=environment,
        cwd=REPO_ROOT,
        timeout=120,
    )


class ComsolWorkflowArchitectureContractTests(unittest.TestCase):
    def test_one_current_comsol_solver_numerics_contract_is_authoritative(self) -> None:
        candidates = sorted(PROJECT_ROOT.glob("config/*comsol*solver*numerics*.json"))
        self.assertEqual(candidates, [NUMERICS])
        contract = json.loads(NUMERICS.read_text(encoding="utf-8"))
        self.assertEqual(contract["role"], "rf_quadrupole_comsol_solver_numerics")
        self.assertEqual(contract["schema_version"], 1)
        self.assertEqual(
            contract["contract_id"], "rf_quadrupole.comsol_solver_numerics.v1"
        )
        self.assertEqual(contract["status"], "current_candidate_solver_numerics")
        self.assertIs(contract["current"], True)
        self.assertEqual(contract["logical_sha256"], _logical_sha256(contract))
        self.assertIn(contract["logical_sha256"], _read(NUMERICS_SUPPORT))
        profiles = {item["profile_id"]: item for item in contract["profiles"]}
        self.assertEqual(set(profiles), {"baseline", "time_refined_160"})
        self.assertEqual(profiles["baseline"]["usage"], "production")
        self.assertEqual(profiles["baseline"]["mesh"]["global_auto_level"], 1)
        self.assertEqual(
            profiles["baseline"]["trajectory"],
            {"rf_steps_per_period": 80, "maximum_time_us": 80.0},
        )
        self.assertEqual(
            profiles["time_refined_160"]["authorization_id"],
            "same_solver_numerical_convergence",
        )
        self.assertEqual(
            profiles["time_refined_160"]["trajectory"]["rf_steps_per_period"],
            160,
        )

        def assert_no_null(value: object, path: str = "$") -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    assert_no_null(child, f"{path}.{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    assert_no_null(child, f"{path}[{index}]")
            else:
                self.assertIsNotNone(value, path)

        assert_no_null(contract)

    def test_scientific_mode_contains_no_comsol_solver_numerics(self) -> None:
        mode = json.loads(MODE.read_text(encoding="utf-8"))
        serialized = json.dumps(mode["numerics"], sort_keys=True)
        for forbidden in (
            "maximum_time_us",
            "comsol_rf_steps_per_period",
            "comsol_mesh_auto_level",
            "mesh_hmax",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(mode["numerics"]["minimum_diagnostic_particles"], 100)

    def test_dedicated_runner_has_no_mode_or_numeric_default_switch(self) -> None:
        source = _read(RUNNER)
        parameter_block = source[: source.index("Set-StrictMode")]
        self.assertNotRegex(parameter_block, r"(?i)\$Mode\b")
        self.assertNotRegex(
            parameter_block,
            r"(?i)\$(?:RfStepsPerPeriod|MeshAutoLevel|MeshHmaxMm|MaximumTimeUs)\b",
        )
        self.assertIn("[string]$SolverNumericsContractPath", parameter_block)
        self.assertIn("[string]$SolverNumericsProfileId", parameter_block)
        self.assertIn("Compile-RfComsolSolverNumerics", source)
        self.assertIn(
            "config\\comsol_solver_numerics.json", source
        )
        self.assertNotRegex(source, r"(?i)(?:mesh|steps|time)\w*\s*=\s*(?:1|80|160)\b")

    def test_active_profile_binds_numerics_identity_and_path_only(self) -> None:
        profiles = json.loads(PROFILES.read_text(encoding="utf-8"))["profiles"]
        interface = next(
            item
            for item in profiles
            if item["profile_id"] == "transport_interface_readiness_candidate"
        )
        comsol_step = next(
            step for step in interface["steps"] if step["step_id"] == "comsol_run"
        )
        arguments = dict(
            zip(comsol_step["arguments"][::2], comsol_step["arguments"][1::2])
        )
        self.assertEqual(
            arguments["-SolverNumericsContractPath"],
            "projects/rf_quadrupole_collision_cooling/config/comsol_solver_numerics.json",
        )
        self.assertEqual(arguments["-SolverNumericsProfileId"], "baseline")
        self.assertNotIn("-Mode", arguments)
        for forbidden in (
            "-RfStepsPerPeriod",
            "-MeshAutoLevel",
            "-MeshHmaxMm",
            "-MaximumTimeUs",
        ):
            self.assertNotIn(forbidden, arguments)

    def test_profiles_use_dedicated_cross_solver_analysis_entries_without_mode(self) -> None:
        profiles = {
            item["profile_id"]: item
            for item in json.loads(PROFILES.read_text(encoding="utf-8"))["profiles"]
        }
        expected = {
            "transport_no_collision_candidate": (
                "workflows/no_collision_transport/compare_cross_solver.ps1"
            ),
            "transport_interface_readiness_candidate": (
                "workflows/interface_readiness/compare_cross_solver.ps1"
            ),
        }
        for profile_id, entrypoint in expected.items():
            step = next(
                item
                for item in profiles[profile_id]["steps"]
                if item["step_id"] == "cross_solver_comparison"
            )
            self.assertEqual(step["entrypoint"], entrypoint)
            arguments = dict(zip(step["arguments"][::2], step["arguments"][1::2]))
            self.assertNotIn("-Mode", arguments)
            self.assertEqual(arguments["-ComsolRunId"], "{comsol_run_id}")
            self.assertEqual(arguments["-SimionRunId"], "{simion_run_id}")

    def test_interface_entry_is_dedicated_and_shared_solver_has_no_workflow_branch(self) -> None:
        task = _read(TASK)
        dedicated = _read(DEDICATED_ENTRY)
        shared = _read(SHARED_SOLVER)
        self.assertIn("prepare_interface_readiness_run()", task)
        self.assertEqual(
            shared.splitlines()[1],
            "%SOLVE_DETERMINISTIC_RF_QUADRUPOLE_PARTICLES Solve one compiled no-collision case.",
        )
        self.assertIn(
            "Dedicated interface entry rejects other workflows.",
            dedicated,
        )
        self.assertIn("transport_interface_readiness", dedicated)
        for forbidden in (
            "transport_interface_readiness",
            "mass_filter_reference",
            "isMassFilter",
            "transportGateFailed",
        ):
            self.assertNotIn(forbidden, shared)
        self.assertNotRegex(
            shared,
            r"(?im)^\s*(?:if|elseif|switch)\b[^\r\n]*"
            r"(?:workflowId|runConfig\.(?:mode|role))",
        )

    def test_release_construction_gate_stops_before_particle_study(self) -> None:
        runner = _read(RUNNER)
        task = _read(RELEASE_GATE_TASK)
        dedicated = _read(DEDICATED_ENTRY)
        shared = _read(SHARED_SOLVER)

        self.assertIn("[switch]$ReleaseConstructionGate", runner)
        self.assertIn(
            "if($ReleaseConstructionGate -and $expectedParticles-ne 100)", runner
        )
        self.assertIn("execution_stage='release_construction_gate'", runner)
        self.assertIn("run_release_construction_gate.m", runner)
        self.assertIn(
            "comsol\\interface_readiness\\run_release_construction_gate.m", runner
        )
        self.assertNotIn(
            "tests\\comsol\\run_release_construction_gate.m", runner
        )
        self.assertIn("Write-VerifiedRunManifest", runner)
        self.assertIn("threshold_result_eligible=$false", runner)
        self.assertIn("return", runner)

        running_report = task.index("writeReportAtomically(reportPath,sprintf('STATUS=RUNNING")
        load_config = task.index("runConfig=jsondecode")
        gate_call = task.index(
            "solve_deterministic_rf_quadrupole_particles(runConfig,control)"
        )
        self.assertLess(running_report, load_config)
        self.assertLess(load_config, gate_call)
        self.assertIn("requiredFinite(runConfig,'particles')==100", task)
        self.assertIn("isequal(size(ions),[100 11])", task)
        self.assertIn("numel(unique(ions(:,1)))==100", task)

        production_call = "solve_deterministic_rf_quadrupole_particles(runConfig)"
        self.assertIn(production_call, dedicated)
        self.assertIn(
            "'role','rf_release_construction_gate_control'", task
        )
        self.assertNotIn("'expected_particles'", task)
        self.assertNotIn("control.expected_particles", shared)
        self.assertIn("requireFiniteScalar(runConfig,'particles')==100", shared)
        self.assertIn("isequal(size(ions),[100 11])", shared)
        self.assertIn("all(isfinite(ions),'all')", shared)
        self.assertIn("numel(unique(ions(:,1)))==100", shared)
        self.assertIn("releaseTimeExpressions=arrayfun", shared)
        self.assertIn("numel(unique(releaseTimeExpressions))==100", shared)
        self.assertIn("expectedParticles=100", shared)
        gate_return = shared.index(
            "result=completeReleaseConstructionGate(model,cpt,ions,"
        )
        electric_force = shared.index("ef=cpt.create('ef1','ElectricForce',3)")
        particle_study = shared.index("std2=model.study.create('std2')")
        particle_solve = shared.index("sol2.attach('std2'); sol2.runAll")
        self.assertLess(gate_return, electric_force)
        self.assertLess(gate_return, particle_study)
        self.assertLess(gate_return, particle_solve)
        for phase in (
            "before_create",
            "after_create",
            "after_label",
            "after_set_filename",
            "after_set_icolp",
            "after_set_velocity_specification",
            "after_set_initial_velocity",
            "after_set_icolv",
            "after_set_rt",
            "after_import",
        ):
            self.assertIn(f"'{phase}'", shared)
        self.assertIn("expectedTags=arrayfun", shared)
        self.assertIn("char(feature.getString('rt'))", shared)
        self.assertIn("char(feature.getString('icolp'))", shared)
        self.assertIn("char(feature.getString('VelocitySpecification'))", shared)
        self.assertIn("char(feature.getString('InitialVelocity'))", shared)
        self.assertIn("char(feature.getString('icolv'))", shared)
        self.assertIn("~any(strcmp(studyTags,'std2'))", shared)
        self.assertIn("~any(strcmp(solutionTags,'sol2'))", shared)
        self.assertIn("writeTextFileChecked(path,'a'", shared)
        self.assertIn("written==numel(text)", shared)
        self.assertIn("closeStatus==0", shared)
        self.assertIn("fopen(temporaryPath,'w','n','UTF-8')", task)
        self.assertIn(
            "expectedBytes=numel(unicode2native(text,'UTF-8'))", task
        )
        self.assertIn("written==expectedBytes", task)
        self.assertNotIn("written==numel(text)", task)
        self.assertIn("closeStatus==0", task)
        self.assertIn("validate_release_construction_gate.py", runner)
        self.assertIn(
            "analysis.validate_release_construction_gate", runner
        )
        gate_probe_start = runner.index(
            "$gateValidationExecution=Invoke-IsolatedFrozenPythonModule"
        )
        gate_probe_end = runner.index(
            "if(-not(Test-Path -LiteralPath $releaseGateValidation",
            gate_probe_start,
        )
        gate_probe = runner[gate_probe_start:gate_probe_end]
        self.assertIn(
            "'projects.rf_quadrupole_collision_cooling."
            "analysis.validate_release_construction_gate'",
            gate_probe,
        )
        self.assertNotIn(
            "'projects.rf_quadrupole_collision_cooling.analysis',",
            gate_probe,
        )
        self.assertIn("'--run-config',$package.run_config", runner)
        self.assertNotIn("'--expected-particle-sha256'", runner)
        self.assertIn(
            "[int]$gateResult.unique_release_time_expression_count-ne 100",
            runner,
        )
        failed_closure = runner[runner.index("} catch {") :]
        self.assertIn(
            "if($ReleaseConstructionGate -and", failed_closure
        )
        self.assertIn(
            "Test-Path -LiteralPath $releaseGateModel -PathType Leaf",
            failed_closure,
        )
        self.assertIn(
            ")+$releaseGateModel",
            failed_closure.replace("`r", "").replace("`n", ""),
        )
        self.assertIn(
            "-Status failed", failed_closure
        )

    def test_release_files_preserve_six_columns_at_existing_gate_tolerance(
        self,
    ) -> None:
        shared = _read(SHARED_SOLVER)
        self.assertIn(
            "'%.17g\\t%.17g\\t%.17g\\t%.17g\\t%.17g\\t%.17g\\n'",
            shared,
        )
        self.assertIn(
            "writeTextFileChecked(releasePath,'w',releaseText,'release data')",
            shared,
        )
        self.assertNotIn("writematrix(releaseData", shared)
        self.assertEqual(shared.count("'Delimiter',char(9)"), 2)
        self.assertNotIn("'Delimiter','tab'", shared)
        self.assertIn("releaseMaxAbsError<1e-12", shared)
        self.assertIn("actualReleaseMaxAbsError<1e-12", shared)

        with OFFICIAL_ION11.open(encoding="utf-8-sig", newline="") as stream:
            rows = [[float(value) for value in row] for row in csv.reader(stream)]
        self.assertEqual(len(rows), 100)
        maximum_error = 0.0
        for row in rows:
            release_data = _expected_release_state(row, axial_offset_mm=0.0)
            encoded = "\t".join(f"{value:.17g}" for value in release_data)
            decoded = tuple(float(value) for value in encoded.split("\t"))
            self.assertEqual(len(decoded), 6)
            maximum_error = max(
                maximum_error,
                *(
                    abs(actual - expected)
                    for actual, expected in zip(decoded, release_data)
                ),
            )
        self.assertLess(maximum_error, 1e-12)

    def test_release_readback_diagnoses_shape_finite_and_value_failures(
        self,
    ) -> None:
        shared = _read(SHARED_SOLVER)
        first_read = shared.index("releaseFile=readmatrix")
        first_shape = shared.index(
            "assert(isequal(releaseFileShape,[1 6])", first_read
        )
        first_finite = shared.index(
            "assert(isempty(nonFiniteReleaseIndices)", first_shape
        )
        first_value = shared.index(
            "assert(releaseMaxAbsError<1e-12", first_finite
        )
        first_create = shared.index("rel=cpt.create(releaseTag", first_value)
        self.assertLess(first_read, first_shape)
        self.assertLess(first_shape, first_finite)
        self.assertLess(first_finite, first_value)
        self.assertLess(first_value, first_create)

        final_read = shared.index("actualReleaseData=readmatrix")
        final_shape = shared.index(
            "assert(isequal(actualReleaseShape,[1 6])", final_read
        )
        final_finite = shared.index(
            "assert(isempty(actualNonFiniteIndices)", final_shape
        )
        final_value = shared.index(
            "assert(actualReleaseMaxAbsError<1e-12", final_finite
        )
        self.assertLess(final_read, final_shape)
        self.assertLess(final_shape, final_finite)
        self.assertLess(final_finite, final_value)

        for diagnostic in (
            "shape is %s; expected [1 6]",
            "has non-finite linear indices %s",
            "max abs error %.17g exceeds 1e-12",
        ):
            self.assertEqual(shared.count(diagnostic), 2)

    def test_failure_report_checks_utf8_bytes_for_non_ascii_diagnostics(
        self,
    ) -> None:
        task = _read(RELEASE_GATE_TASK)
        diagnostic = "错误使用 assert：六列文件精度不足"
        self.assertNotEqual(len(diagnostic), len(diagnostic.encode("utf-8")))
        self.assertIn("fopen(temporaryPath,'w','n','UTF-8')", task)
        self.assertIn(
            "expectedBytes=numel(unicode2native(text,'UTF-8'))", task
        )
        self.assertIn("assert(written==expectedBytes", task)
        self.assertNotIn("assert(written==numel(text)", task)

    def test_matlab_solver_consumes_compiled_numerics_without_reselection(self) -> None:
        shared = _read(SHARED_SOLVER)
        for token in (
            "requireExistingFile(inputs,'resolved_design')",
            "requireExistingFile(inputs,'interface_contract')",
            "requireExistingFile(inputs,'particle_table')",
            "requireStruct(runConfig,'compiled_solver_numerics')",
            "requireStruct(numerics,'mesh')",
            "requireStruct(numerics,'trajectory')",
            "maximumTimeUs=requireFiniteScalar(trajectory,'maximum_time_us')",
            "rfStepsPerPeriod=requirePositiveInteger(trajectory,'rf_steps_per_period')",
        ):
            self.assertIn(token, shared)
        for forbidden in (
            "requireExistingFile(inputs,'comsol_solver_numerics')",
            "authorization_id",
            "profiles",
            "time_refined_160",
            "same_solver_numerical_convergence",
            "selectSolverNumerics",
        ):
            self.assertNotIn(forbidden, shared)
        for mirror in (
            "solver_numerics_contract_id",
            "solver_numerics_contract_logical_sha256",
            "solver_numerics_profile_id",
            "numerical_experiment_id",
            "comsol_mesh_auto_level",
            "comsol_rf_steps_per_period",
            "maximum_time_us",
        ):
            self.assertIn(f"runConfig,'{mirror}'", shared)
        self.assertLess(
            shared.index("Compiled solver-numerics identity differs"),
            shared.index("import com.comsol.model.*"),
        )
        self.assertLess(
            shared.index("Compiled solver-numerics values differ"),
            shared.index("import com.comsol.model.*"),
        )

    def test_runner_closes_initial_interrupted_success_and_failed_records(self) -> None:
        source = _read(RUNNER)
        for token in (
            "common\\contracts\\run_artifact_support.ps1",
            "New-RunPackage",
            "Write-VerifiedRunManifest",
            "-Status interrupted",
            "-Status success",
            "Complete-FailedRun",
            "Save-RunEnvironment",
            "Restore-RunEnvironment",
            "catch {",
            "finally {",
        ):
            self.assertIn(token, source)
        self.assertLess(
            source.index("Write-VerifiedRunManifest"),
            source.index("run_comsol_r2025b.ps1"),
        )


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
class ComsolSolverNumericsFailureTests(unittest.TestCase):
    def test_bundle_artifact_array_freezes_all_entries_without_nesting(self) -> None:
        runner = _read(RUNNER)
        self.assertIn(
            "$bundleArtifacts = Get-RfComsolRequiredProperty", runner
        )
        self.assertNotIn(
            "$bundleArtifacts = @(Get-RfComsolRequiredProperty", runner
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "bundle"
            frozen_root = root / "frozen"
            source_root.mkdir()
            artifacts: list[dict[str, object]] = []
            for index in range(8):
                relative_path = f"artifact_{index:02d}.txt"
                (source_root / relative_path).write_text(
                    f"artifact {index}\n", encoding="utf-8"
                )
                artifacts.append({"relative_path": relative_path})
            metadata = source_root / "paired_particle_bundle.json"
            metadata.write_text(
                json.dumps({"artifacts": artifacts}), encoding="utf-8"
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "RF_COMSOL_NUMERICS_SUPPORT": str(NUMERICS_SUPPORT),
                    "RF_RUN_ARTIFACT_SUPPORT": str(RUN_ARTIFACT_SUPPORT),
                    "RF_BUNDLE_METADATA": str(metadata),
                    "RF_FROZEN_BUNDLE_ROOT": str(frozen_root),
                }
            )
            command = (
                ". $env:RF_COMSOL_NUMERICS_SUPPORT; "
                ". $env:RF_RUN_ARTIFACT_SUPPORT; "
                "$document=Get-Content -LiteralPath $env:RF_BUNDLE_METADATA "
                "-Raw -Encoding UTF8 | ConvertFrom-Json; "
                "$artifacts=Get-RfComsolRequiredProperty -Object $document "
                "-Property artifacts -Name artifacts; "
                "if($artifacts.Count -ne 8){"
                "throw \"Expected 8 artifacts, got $($artifacts.Count)\"}; "
                "$bundleRoot=[IO.Path]::GetFullPath("
                "(Split-Path -Parent $env:RF_BUNDLE_METADATA)); "
                "$frozenRoot=[IO.Path]::GetFullPath($env:RF_FROZEN_BUNDLE_ROOT); "
                "New-Item -ItemType Directory -Path $frozenRoot -Force | Out-Null; "
                "$copied=0; "
                "foreach($entry in $artifacts){"
                "$relativePath=[string](Get-RfComsolRequiredProperty "
                "-Object $entry -Property relative_path -Name relative_path); "
                "$source=[IO.Path]::GetFullPath((Join-Path $bundleRoot $relativePath)); "
                "if(-not $source.StartsWith("
                "$bundleRoot+[IO.Path]::DirectorySeparatorChar,"
                "[StringComparison]::OrdinalIgnoreCase)){"
                "throw \"Artifact escapes bundle root: $relativePath\"}; "
                "Copy-VerifiedRunInput -Source $source "
                "-Destination (Join-Path $frozenRoot $relativePath) | Out-Null; "
                "$copied+=1}; "
                "if($copied -ne 8){throw \"Expected 8 copies, got $copied\"}; "
                "'BUNDLE_ARTIFACT_FREEZE=PASS COUNT=8'"
            )
            result = _run_pwsh(command, environment)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("BUNDLE_ARTIFACT_FREEZE=PASS COUNT=8", result.stdout)
            frozen = sorted(frozen_root.glob("artifact_*.txt"))
            self.assertEqual(len(frozen), 8)
            for index, path in enumerate(frozen):
                self.assertEqual(path.read_text(encoding="utf-8"), f"artifact {index}\n")

    def invoke_number(
        self, json_literal: str, *, positive: bool = True, integer: bool = True
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / "number.json"
            payload.write_text(f'{{"value":{json_literal}}}', encoding="utf-8")
            environment = os.environ.copy()
            environment.update(
                {
                    "RF_COMSOL_NUMERICS_SUPPORT": str(NUMERICS_SUPPORT),
                    "RF_COMSOL_NUMBER": str(payload),
                }
            )
            switches = (" -Positive" if positive else "") + (
                " -Integer" if integer else ""
            )
            command = (
                ". $env:RF_COMSOL_NUMERICS_SUPPORT; "
                "$d=Get-Content $env:RF_COMSOL_NUMBER -Raw | ConvertFrom-Json; "
                "Get-RfComsolRequiredFiniteNumber -Object $d "
                f"-Property value -Name value{switches} | Out-Null"
            )
            return _run_pwsh(command, environment)

    def invoke_contract(
        self,
        payload: dict[str, object],
        profile_id: str = "baseline",
        authorization: str = "",
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "numerics.json"
            contract.write_text(json.dumps(payload), encoding="utf-8")
            environment = os.environ.copy()
            environment.update(
                {
                    "RF_COMSOL_NUMERICS_SUPPORT": str(NUMERICS_SUPPORT),
                    "RF_COMSOL_OFFICIAL_NUMERICS": str(NUMERICS),
                    "RF_COMSOL_NUMERICS": str(contract),
                    "RF_COMSOL_PROFILE": profile_id,
                    "RF_COMSOL_AUTH": authorization,
                }
            )
            command = (
                ". $env:RF_COMSOL_NUMERICS_SUPPORT; "
                "Compile-RfComsolSolverNumerics "
                "-OfficialContractPath $env:RF_COMSOL_OFFICIAL_NUMERICS "
                "-RequestedContractPath $env:RF_COMSOL_NUMERICS "
                "-ProfileId $env:RF_COMSOL_PROFILE "
                "-ExperimentAuthorizationId $env:RF_COMSOL_AUTH | Out-Null"
            )
            return _run_pwsh(command, environment)

    def baseline(self) -> dict[str, object]:
        return json.loads(NUMERICS.read_text(encoding="utf-8"))

    def test_json_number_type_is_strict_before_numeric_cast(self) -> None:
        for literal in ("80", "1.0"):
            with self.subTest(accepted=literal):
                result = self.invoke_number(literal)
                self.assertEqual(result.returncode, 0, result.stderr)
        for literal in ("true", "false", '"80"', '"1.0"', '"NaN"', "null", "[]", "{}"):
            with self.subTest(rejected=literal):
                result = self.invoke_number(literal)
                self.assertNotEqual(result.returncode, 0)
                self.assertRegex(result.stderr, r"(JSON number|missing)")
        self.assertNotEqual(self.invoke_number("1.5").returncode, 0)
        self.assertNotEqual(self.invoke_number("0").returncode, 0)

    def test_valid_registered_profiles_pass(self) -> None:
        baseline = self.invoke_contract(self.baseline())
        self.assertEqual(baseline.returncode, 0, baseline.stderr)
        refined = self.invoke_contract(
            self.baseline(),
            profile_id="time_refined_160",
            authorization="same_solver_numerical_convergence",
        )
        self.assertEqual(refined.returncode, 0, refined.stderr)

    def test_missing_null_nonfinite_and_illegal_ranges_fail_closed(self) -> None:
        mutations: list[dict[str, object]] = []
        missing = self.baseline()
        del missing["profiles"][0]["mesh"]["global_auto_level"]  # type: ignore[index]
        mutations.append(missing)
        null_value = self.baseline()
        null_value["profiles"][0]["trajectory"]["maximum_time_us"] = None  # type: ignore[index]
        mutations.append(null_value)
        nonfinite = self.baseline()
        nonfinite["profiles"][0]["trajectory"]["maximum_time_us"] = "NaN"  # type: ignore[index]
        mutations.append(nonfinite)
        illegal = self.baseline()
        illegal["profiles"][0]["trajectory"]["rf_steps_per_period"] = 0  # type: ignore[index]
        mutations.append(illegal)
        duplicate = self.baseline()
        duplicate["profiles"][1]["profile_id"] = "baseline"  # type: ignore[index]
        mutations.append(duplicate)

        for payload in mutations:
            with self.subTest(payload=payload):
                result = self.invoke_contract(payload)
                self.assertNotEqual(result.returncode, 0)

    def test_forged_identity_hash_mesh_and_time_cannot_self_authorize(self) -> None:
        mutations: list[dict[str, object]] = []
        for path, value in (
            (("schema_version",), 2),
            (("role",), "forged_role"),
            (("contract_id",), "forged.contract.v1"),
            (("status",), "forged_status"),
            (("current",), False),
            (("profiles", 0, "mesh", "global_auto_level"), 2),
            (("profiles", 0, "trajectory", "maximum_time_us"), 160.0),
        ):
            payload = self.baseline()
            target: object = payload
            for component in path[:-1]:
                target = target[component]  # type: ignore[index]
            target[path[-1]] = value  # type: ignore[index]
            payload["logical_sha256"] = _logical_sha256(payload)
            mutations.append(payload)
        forged_hash = self.baseline()
        forged_hash["logical_sha256"] = "0" * 64
        mutations.append(forged_hash)
        for payload in mutations:
            with self.subTest(payload=payload):
                self.assertNotEqual(self.invoke_contract(payload).returncode, 0)

    def test_experimental_profile_requires_exact_registered_authorization(self) -> None:
        missing = self.invoke_contract(
            self.baseline(), profile_id="time_refined_160"
        )
        self.assertNotEqual(missing.returncode, 0)
        wrong = self.invoke_contract(
            self.baseline(),
            profile_id="time_refined_160",
            authorization="unregistered_experiment",
        )
        self.assertNotEqual(wrong.returncode, 0)

    def test_precommercial_contract_failure_produces_verified_failed_triplet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = self.baseline()
            invalid["profiles"][0]["mesh"]["global_auto_level"] = 2  # type: ignore[index]
            invalid["logical_sha256"] = _logical_sha256(invalid)
            invalid_path = root / "invalid_numerics.json"
            invalid_path.write_text(json.dumps(invalid), encoding="utf-8")
            run_id = (
                "20260725_120000__test__comsol__numerics-preflight"
                f"__p{os.getpid()}"
            )
            run_dir = ARTIFACT_ROOT / "runs" / run_id
            if run_dir.exists():
                shutil.rmtree(run_dir)
            environment = os.environ.copy()
            environment.update(
                {
                    "RF_COMSOL_RUNNER": str(RUNNER),
                    "RF_REPO_ROOT": str(REPO_ROOT),
                    "RF_INVALID_NUMERICS": str(invalid_path),
                    "RF_RUN_ID": run_id,
                    "RF_PYTHON": str(RUN_PYTHON),
                }
            )
            names = (
                "RFQUAD_RUN_CONFIG",
                "RFQUAD_COMSOL_MODEL_PATH",
                "RFQUAD_EXPECTED_PARTICLES",
                "RFQUAD_EXPECTED_HITS",
                "RFQUAD_EXPECTED_RF_PEAK_V",
                "RFQUAD_EXPECTED_FREQUENCY_HZ",
            )
            name_literal = ",".join(f"'{name}'" for name in names)
            command = (
                f"$names=@({name_literal}); "
                "foreach($name in $names){"
                "[Environment]::SetEnvironmentVariable($name,\"sentinel-$name\")}; "
                "$failed=$false; $reason=''; "
                "try { "
                "& $env:RF_COMSOL_RUNNER -RunId $env:RF_RUN_ID "
                "-ParticleTablePath $env:RF_INVALID_NUMERICS "
                "-ParticleBundleMetadataPath $env:RF_INVALID_NUMERICS "
                "-SourceFamilyPath $env:RF_INVALID_NUMERICS "
                "-ParticleDistributionPath $env:RF_INVALID_NUMERICS "
                "-SolverNumericsContractPath $env:RF_INVALID_NUMERICS "
                "-SolverNumericsProfileId baseline -OperatingPoint forged "
                "-PythonExe $env:RF_PYTHON; "
                "} catch {$failed=$true; $reason=$_.Exception.Message}; "
                "if(-not $failed){throw 'Invalid numerics unexpectedly reached COMSOL.'}; "
                "if($reason -notmatch 'logical_sha256'){throw $reason}; "
                "foreach($name in $names){"
                "if([Environment]::GetEnvironmentVariable($name) -cne \"sentinel-$name\"){"
                "throw \"Environment was not restored: $name\"}}"
            )
            try:
                result = _run_pwsh(command, environment)
                self.assertEqual(result.returncode, 0, result.stderr)
                for filename in ("run_config.json", "summary.json", "run_manifest.json"):
                    self.assertTrue((run_dir / filename).is_file(), filename)
                verification = subprocess.run(
                    [
                        str(RUN_PYTHON),
                        str(REPO_ROOT / "common" / "contracts" / "verify_run_manifest.py"),
                        str(run_dir / "run_manifest.json"),
                        "--require-status",
                        "failed",
                        "--require-local-run-config",
                    ],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    check=False,
                    text=True,
                    encoding="utf-8",
                    timeout=60,
                )
                self.assertEqual(verification.returncode, 0, verification.stderr)
                summary = json.loads(
                    (run_dir / "summary.json").read_text(encoding="utf-8-sig")
                )
                manifest = json.loads(
                    (run_dir / "run_manifest.json").read_text(encoding="utf-8-sig")
                )
                self.assertEqual(summary["status"], "failed")
                self.assertEqual(manifest["status"], "failed")
                self.assertIn("logical_sha256", summary["reason"])
                self.assertFalse((run_dir / "logs" / "comsol_bootstrap_report.txt").exists())
            finally:
                if run_dir.exists():
                    shutil.rmtree(run_dir)


if __name__ == "__main__":
    unittest.main()
