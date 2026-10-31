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

from common.contracts.capacity_ledger import initialize_capacity_ledger
from projects.rf_multipole_ion_optics.runtime.runtime_profile import resolve_runtime_profile
from projects.rf_multipole_ion_optics.analysis.validate_release_construction_gate import (
    _expected_release_state,
)


PROJECT_ROOT = Path(__file__).parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
NUMERICS = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "comsol_solver_numerics.json"
MULTIPOLE_TRANSPORT_NUMERICS = (
    PROJECT_ROOT / "config" / "comsol_solver_numerics.json"
)
RUNTIME_PROFILES = PROJECT_ROOT / "config" / "runtime_profiles.json"
MODE = PROJECT_ROOT / "config" / "modes" / "quadrupole_transport_interface_readiness.json"
PROFILES = PROJECT_ROOT / "config" / "execution_profiles.json"
RUNNER = PROJECT_ROOT / "workflows" / "interface_readiness" / "run_comsol.ps1"
TASK = (
    PROJECT_ROOT
    / "workflows"
    / "interface_readiness"
    / "comsol"
    / "run_nocollision_candidate.m"
)
GUI_VERIFY_TASK = (
    PROJECT_ROOT
    / "workflows"
    / "interface_readiness"
    / "comsol"
    / "verify_nocollision_comsol.m"
)
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
SHARED_LIVELINK_LAUNCHER = REPO_ROOT / "common" / "comsol" / "run_comsol_r2025b.ps1"
RUN_PYTHON = Path(sys.executable).resolve()
OFFICIAL_ION11 = PROJECT_ROOT / "variants" / "quadrupole" / "config" / "particles" / "official_fixed_100.ion"


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
        errors="replace",
        env=environment,
        cwd=REPO_ROOT,
        timeout=120,
    )


class ComsolWorkflowArchitectureContractTests(unittest.TestCase):
    def test_current_comsol_numerics_authorities_have_disjoint_workflow_scopes(
        self,
    ) -> None:
        candidates = sorted(PROJECT_ROOT.glob("variants/quadrupole/config/*comsol*solver*numerics*.json"))
        self.assertEqual(candidates, [NUMERICS])
        self.assertEqual(
            list((PROJECT_ROOT / "config").glob("*comsol*solver*numerics*.json")),
            [MULTIPOLE_TRANSPORT_NUMERICS],
        )
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
        self.assertEqual(set(profiles), {"baseline", "time_refined_160", "core_flow_development_coarse"})
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
        multipole_contract = json.loads(
            MULTIPOLE_TRANSPORT_NUMERICS.read_text(encoding="utf-8")
        )
        self.assertEqual(
            multipole_contract["role"],
            "multipole_comsol_solver_numerics_profiles",
        )
        self.assertEqual(
            multipole_contract["project_id"], "rf_multipole_ion_optics"
        )
        runtime_profiles = json.loads(RUNTIME_PROFILES.read_text(encoding="utf-8"))
        for variant in ("quadrupole", "hexapole", "octupole"):
            runtime = resolve_runtime_profile(
                REPO_ROOT, "rf_multipole_ion_optics",
                f"{variant}_no_acceleration_full_length",
            )
            self.assertEqual(
                Path(runtime["solver_numerics_registry_paths"]["comsol"]),
                MULTIPOLE_TRANSPORT_NUMERICS.resolve(),
            )
        runtime_numerics_ids = {
            profile["comsol_solver_numerics_profile_id"]
            for profile in runtime_profiles["profiles"].values()
        }
        self.assertNotIn("core_flow_development_coarse_8us", runtime_numerics_ids)
        self.assertEqual(
            runtime_numerics_ids | {"core_flow_development_coarse_8us"},
            set(multipole_contract["profiles"])
        )
        specialized_consumers = (
            PROJECT_ROOT / "workflows" / "interface_readiness" / "run_comsol.ps1",
            PROJECT_ROOT / "workflows" / "mass_filter_reference" / "run_comsol.ps1",
            PROJECT_ROOT
            / "workflows"
            / "same_solver_convergence"
            / "run_comparison.ps1",
        )
        for consumer in specialized_consumers:
            source = _read(consumer)
            self.assertIn("comsol_solver_numerics.json", source, consumer.name)
            self.assertNotIn(
                "multipole_transport_comsol_solver_numerics.json",
                source,
                consumer.name,
            )
        for name in ("run_comsol.ps1", "run_simion.ps1"):
            wrapper = _read(
                PROJECT_ROOT / "workflows" / "no_collision_transport" / name
            )
            self.assertIn(
                "projects\\rf_multipole_ion_optics\\runtime\\project_transport_launcher_support.ps1",
                wrapper,
            )
            self.assertIn("Invoke-MultipoleProjectFinite3dTransport", wrapper)
            self.assertNotIn("variants\quadrupole\config\\comsol_solver_numerics.json", wrapper)
            self.assertNotIn(
                "multipole_transport_comsol_solver_numerics.json", wrapper
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
            "variants\quadrupole\config\\comsol_solver_numerics.json", source
        )
        self.assertNotRegex(source, r"(?i)(?:mesh|steps|time)\w*\s*=\s*(?:1|80|160)\b")

    def test_active_profile_binds_numerics_identity_and_path_only(self) -> None:
        profiles = json.loads(PROFILES.read_text(encoding="utf-8"))["profiles"]
        interface = next(
            item
            for item in profiles
            if item["profile_id"] == "quadrupole_transport_interface_readiness_candidate"
        )
        comsol_step = next(
            step for step in interface["steps"] if step["step_id"] == "comsol_run"
        )
        arguments = dict(
            zip(comsol_step["arguments"][::2], comsol_step["arguments"][1::2])
        )
        self.assertEqual(
            arguments["-SolverNumericsContractPath"],
            "projects/rf_multipole_ion_optics/variants/quadrupole/config/comsol_solver_numerics.json",
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

    def test_profiles_use_shared_contract_driven_cross_solver_entry(self) -> None:
        profiles = {
            item["profile_id"]: item
            for item in json.loads(PROFILES.read_text(encoding="utf-8"))["profiles"]
        }
        expected = {
            "quadrupole_transport_interface_readiness_candidate": "transport_interface_readiness",
        }
        for profile_id, mode in expected.items():
            step = next(
                item
                for item in profiles[profile_id]["steps"]
                if item["step_id"] == "cross_solver_comparison"
            )
            self.assertEqual(step["entrypoint"], "workflows/cross_solver/compare_cross_solver.ps1")
            arguments = dict(zip(step["arguments"][::2], step["arguments"][1::2]))
            self.assertEqual(arguments["-Mode"], mode)
            self.assertEqual(arguments["-ComsolRunId"], "{comsol_run_id}")
            self.assertEqual(arguments["-SimionRunId"], "{simion_run_id}")

        functional = profiles["quadrupole_transport_runtime_functional"]
        self.assertEqual(functional["evidence_levels"], ["plan"])
        self.assertEqual(
            functional["required_bindings"],
            ["runtime_profile_id", "evidence_contract_path"],
        )
        self.assertFalse(any(step["kind"] == "analyze" for step in functional["steps"]))
        for step in functional["steps"]:
            if step["kind"] == "run":
                arguments = dict(zip(step["arguments"][::2], step["arguments"][1::2]))
                self.assertEqual(arguments["-RuntimeProfileId"], "{runtime_profile_id}")
                self.assertEqual(arguments["-EvidenceContractPath"], "{evidence_contract_path}")

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
        # Public validator tests own grouped file/mapping/breadcrumb behavior;
        # RfExactBirthReleasePlanTest owns exact grouping and source facts.
        runner, task, shared = _read(RUNNER), _read(RELEASE_GATE_TASK), _read(SHARED_SOLVER)
        self.assertIn("[switch]$ReleaseConstructionGate", runner)
        self.assertIn("if($ReleaseConstructionGate -and $expectedParticles-ne 100)", runner)
        self.assertIn("execution_stage='release_construction_gate'", runner)
        self.assertIn("comsol/interface_readiness/run_release_construction_gate.m", runner.replace("\\", "/"))
        self.assertIn("validate_release_construction_gate.py", runner)
        self.assertIn("threshold_result_eligible=$false", runner)
        self.assertIn("solve_deterministic_rf_quadrupole_particles(runConfig,control)", task)
        self.assertIn("requiredFinite(runConfig,'particles')==100", task)
        self.assertIn("plan_rf_exact_birth_releases(", shared)
        gate_return = shared.index("result=completeReleaseConstructionGate(model,cpt,ions,")
        for particle_operation in ("ef=cpt.create('ef1','ElectricForce',3)",
                                   "std2=model.study.create('std2')", "sol2.attach('std2'); sol2.runAll"):
            self.assertLess(gate_return, shared.index(particle_operation))

    def test_release_files_preserve_six_columns_at_existing_gate_tolerance(
        self,
    ) -> None:
        # Exercise the existing source projection and lossless six-column text
        # contract; grouped readback failures belong to the public validator.
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

    def test_runner_checkpoints_then_closes_success_and_failed_records(self) -> None:
        command = r"""
$ast=[Management.Automation.Language.Parser]::ParseFile($env:RF_INTERFACE_RUNNER,[ref]$null,[ref]$null)
$functions=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]},$true))
$complete=@($functions|Where-Object Name -CEQ 'Complete-InterfaceOwner')
if($complete.Count-ne1){throw 'Expected one actual completion adapter'}
$names=@($complete[0].Body.FindAll({param($n)$n-is[Management.Automation.Language.CommandAst]},$true)|ForEach-Object{$_.GetCommandName()})
if(@($names|Where-Object{$_-ceq'Complete-RunArtifactPowerShellOwner'}).Count-ne1){throw 'Missing public completion consumer'}
$top=@($ast.EndBlock.Statements|Where-Object{$_-isnot[Management.Automation.Language.FunctionDefinitionAst]})
$commands=@($top|ForEach-Object{$_.FindAll({param($n)$n-is[Management.Automation.Language.CommandAst]},$true)})
$initialize=@($commands|Where-Object{$_.GetCommandName()-ceq'Initialize-RunArtifactPowerShellOwner'})
$native=@($commands|Where-Object{$_.GetCommandName()-ceq'Invoke-InterfaceComsolTask'})
if($initialize.Count-ne1-or$native.Count-lt1-or$initialize[0].Extent.StartOffset-ge$native[0].Extent.StartOffset){throw 'Native entry preceded public initialization'}
if(@($functions|Where-Object Name -CEQ 'Complete-FailedRun').Count){throw 'Replaced private finalizer remains'}
'PUBLIC_OWNER_WIRING=PASS'
"""
        environment = dict(os.environ, RF_INTERFACE_RUNNER=str(RUNNER))
        result = _run_pwsh(command, environment)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PUBLIC_OWNER_WIRING=PASS", result.stdout)

    def test_interface_normal_launches_disable_attempt_local_retry(self) -> None:
        command = r"""
$ast=[Management.Automation.Language.Parser]::ParseFile($env:RF_INTERFACE_RUNNER,[ref]$null,[ref]$null)
$parameter=@($ast.ParamBlock.Parameters|Where-Object{$_.Name.VariablePath.UserPath-ceq'StartupAttempts'})
if($parameter.Count-ne1-or$parameter[0].DefaultValue.Value-ne1){throw 'Normal entry must default to one attempt'}
$adapter=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-ceq'Invoke-InterfaceComsolTask'},$true))
if($adapter.Count-ne1){throw 'Native adapter is ambiguous'}
$calls=@($adapter[0].Body.FindAll({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.InvocationOperator-eq[Management.Automation.Language.TokenKind]::Ampersand-and$n.Extent.Text.Contains('run_comsol_r2025b.ps1')},$true))
if($calls.Count-ne1){throw 'Expected one shared launcher call'}
$elements=@($calls[0].CommandElements);$index=@(0..($elements.Count-1)|Where-Object{$elements[$_]-is[Management.Automation.Language.CommandParameterAst]-and$elements[$_].ParameterName-ceq'StartupAttempts'})
if($index.Count-ne1-or$elements[$index[0]+1].VariablePath.UserPath-cne'StartupAttempts'){throw 'Shared launcher lost explicit attempt selection'}
'ATTEMPT_SELECTION=PASS'
"""
        result = _run_pwsh(command, dict(os.environ, RF_INTERFACE_RUNNER=str(RUNNER)))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ATTEMPT_SELECTION=PASS", result.stdout)

    def test_gui_solver_diagnostics_are_fail_safe_and_observational(self) -> None:
        source = _read(GUI_VERIFY_TASK)
        stages = (
            "after_mphload",
            "before_std1",
            "after_std1",
            "before_std2",
        )
        stage_offsets = [
            source.index(f"writeGuiSolverDiagnostic(fid, model, '{stage}')")
            for stage in stages
        ]
        std1_run = source.index("model.study('std1').run;")
        std2_run = source.index("model.study('std2').run;")
        self.assertLess(stage_offsets[0], stage_offsets[1])
        self.assertLess(stage_offsets[1], std1_run)
        self.assertLess(std1_run, stage_offsets[2])
        self.assertLess(stage_offsets[2], stage_offsets[3])
        self.assertLess(stage_offsets[3], std2_run)

        for token in (
            "GUI_SOLVER_DIAGNOSTIC_JSON=",
            "rf_quadrupole_gui_solver_diagnostic",
            "study_tags",
            "step_tags",
            "solver_sequence_tags",
            "feature_tags",
            "isAttached()",
            "isInitialized()",
            "isEmpty()",
            "notsolmethod",
            "getString('notsol')",
            "dependency_solver_tag",
            "'status', 'error'",
            "'error_identifier'",
            "'error_message'",
        ):
            self.assertIn(token, source)

        diagnostic_helpers = source[source.index("function writeGuiSolverDiagnostic") :]
        compact_helpers = "".join(diagnostic_helpers.split()).replace("...", "")
        main_body = source[: source.index("function text = joinJavaStrings")]
        self.assertIn("safeDiagnosticGetter", diagnostic_helpers)
        self.assertIn("catch getterError", diagnostic_helpers)
        self.assertIn("'value', []", diagnostic_helpers)
        self.assertIn("result.value = getter();", diagnostic_helpers)
        self.assertNotIn("'value', getter()", diagnostic_helpers)
        self.assertIn(
            "Diagnostics are observational and must never replace the primary GUI error.",
            diagnostic_helpers,
        )
        self.assertNotRegex(main_body, r"(?m)^\s*try\s*$")
        self.assertNotRegex(main_body, r"(?m)^\s*catch(?:\s+\w+)?\s*$")
        for wrapped_getter in (
            "safeDiagnosticGetter(@()diagnosticTags(model.study.tags()))",
            "safeDiagnosticGetter(@()diagnosticTags(model.sol.tags()))",
            "safeDiagnosticGetter(@()hasDiagnosticTag("
            "model.sol('sol2').feature.tags(),'v1'))",
            "safeDiagnosticGetter(@()char("
            "model.sol('sol2').feature('v1').getString('notsolmethod')))",
            "safeDiagnosticGetter(@()char("
            "model.sol('sol2').feature('v1').getString('notsol')))",
            "safeDiagnosticGetter(@()hasDiagnosticTag(model.study.tags(),tag))",
            "safeDiagnosticGetter(@()diagnosticTags("
            "model.study(tag).feature.tags()))",
            "safeDiagnosticGetter(@()hasDiagnosticTag(model.sol.tags(),tag))",
            "safeDiagnosticGetter(@()diagnosticTags("
            "model.sol(tag).feature.tags()))",
            "safeDiagnosticGetter(@()logical(model.sol(tag).isAttached()))",
            "safeDiagnosticGetter(@()logical(model.sol(tag).isInitialized()))",
            "safeDiagnosticGetter(@()logical(model.sol(tag).isEmpty()))",
        ):
            self.assertIn(wrapped_getter, compact_helpers)
        for forbidden in (
            "clear",
            ".set(",
            ".create(",
            ".remove(",
            ".detach(",
            ".attach(",
            "runNoGen",
            ".run",
        ):
            self.assertNotIn(forbidden, diagnostic_helpers)
        self.assertEqual(source.count("model.study('std1').run;"), 1)
        self.assertEqual(source.count("model.study('std2').run;"), 1)


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
class ComsolSolverNumericsFailureTests(unittest.TestCase):
    def test_simion_failed_closure_unconfirmed_host_preserves_owner_and_primary_error(self) -> None:
        command = r"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $PWD 'common/contracts/run_artifact_workflow.ps1')
. (Join-Path $PWD 'projects/rf_multipole_ion_optics/runtime/simion_execution.ps1')
$root=$env:RF_CLOSURE_ROOT;$physicalRunDir=$root;$runDir=$root;$resultDir=$root;$logDir=$root;$solverDir=$root
New-Item -ItemType Directory (Join-Path $root 'logs')|Out-Null
$runConfig=Join-Path $root 'run_config.json';$workflowRequestPath=Join-Path $root 'request.json'
$manifestPath=Join-Path $root 'run_manifest.json';'{"schema_version":1,"status":"checkpoint"}'|Set-Content $manifestPath
$manifestBefore=[IO.File]::ReadAllText($manifestPath)
'{}'|Set-Content $workflowRequestPath
@{inputs=@{execution_request=$workflowRequestPath}}|ConvertTo-Json|Set-Content $runConfig
$ResultPath=Join-Path $root 'result.json';$summary=Join-Path $root 'summary.json'
$ownerContext=@{run_directory=$root;result_path=$ResultPath;request_path=$workflowRequestPath;completion_written=$false;native_path_preparation=@{};session=@{status='active'}}
$hostExecutionLease=@{inherited=$false;token='owned-token'};$hostReleaseState=@{released=$false;completion=$null;unknown=$false}
$nativeOperations=@(@{operation_id='fly';resource_release_id='simion';observation=@{exit_confirmed=$true;returncode=0;process_id=71;process_started_at_utc_ticks=[long]12345}})
$script:releases=0;$script:cleanups=0
function Exit-HostResourceStage {param($Lease,[switch]$PassThru);$script:releases++;throw 'injected host release failure'}
function Exit-HostExecutionLease {$script:cleanups++;throw 'host released twice'}
function Remove-RunPackageExecutionAlias {$script:cleanups++;throw 'unknown host alias removed'}
function Exit-ArtifactWorkflowCapacitySession {$script:cleanups++;throw 'unknown host capacity released'}
function Close-RfSimionFieldCheckpointGuard {$script:cleanups++;throw 'unknown host source guard released'}
function Set-RfRunPhase {}
$package=@{};$resourceBudgetExceeded=$false;$hostReleased=$false;$deferFinalization=$false;$script:writerCompletionUnknown=$false
$fieldCheckpointGuard=@{};$continuationGuards=@();$continuationCapacity=@{status='active'}
$RunId='fixture';$ProjectId='rf_multipole_ion_optics';$phaseName='analysis';$phaseTimings=@{};$runTimer=[Diagnostics.Stopwatch]::StartNew()
$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($env:RF_TRANSPORT_RUNNER,[ref]$tokens,[ref]$errors)
$owner=@($ast.EndBlock.Statements|Where-Object{$_-is[Management.Automation.Language.TryStatementAst]-and$_.CatchClauses.Count-and$_.CatchClauses[0].Extent.Text.Contains('$simionRunFailure=$_')})[-1]
$tail=$owner.CatchClauses[0].Extent.Text+'finally'+$owner.Finally.Extent.Text
$caught=$null;try{. ([scriptblock]::Create("try{throw [InvalidOperationException]::new('original solver failure')}"+$tail))}catch{$caught=$_}
if($null-eq$caught-or$caught.Exception.Message-cne'original solver failure'){throw 'Primary failure was replaced'}
if($caught.Exception.Data['failure_closure_error']-cne'injected host release failure'-or$caught.Exception.Data['host_release_error']-cne'injected host release failure'){throw 'Host/closure facts were lost'}
if($script:releases-ne1-or$script:cleanups-ne0-or-not$hostReleaseState.unknown-or-not$deferFinalization){throw 'Unknown host ownership was released'}
if(Test-Path (Join-Path $root 'results/execution_completion.json')){throw 'Unconfirmed host published completion'}
if([IO.File]::ReadAllText($manifestPath)-cne$manifestBefore){throw 'Unconfirmed host changed parent terminal authority'}
if(-not$nativeOperations[0].observation.exit_confirmed){throw 'A stopped native worker was changed to running'}
"""
        with tempfile.TemporaryDirectory(prefix="rf-host-unknown-") as directory:
            environment = os.environ.copy()
            environment.update(RF_CLOSURE_ROOT=directory, RF_TRANSPORT_RUNNER=str(
                PROJECT_ROOT / "runtime/run_simion_finite_3d_transport.ps1"))
            result = _run_pwsh(command, environment)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            transport = json.loads((Path(directory) / "result.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(transport["execution_status"], "host_release_unconfirmed")
            self.assertEqual((transport["recovery_action"], transport["resume_action"]),
                             ("inspect_host_release", "inspect_host_release"))
            self.assertEqual(transport["failure_reason"], "injected host release failure")
            self.assertEqual(transport["exception"]["message"], "original solver failure")
            self.assertIn("injected host release failure", transport["secondary_errors"])

    def test_transport_closure_and_host_errors_preserve_original_failure(self) -> None:
        command = r"""
$ErrorActionPreference='Stop'
$tokens=$null; $parseErrors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile(
    $env:RF_TRANSPORT_RUNNER,[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count){throw 'Runner parse failed'}
$outer=@($ast.FindAll({param($node)
    $node -is [System.Management.Automation.Language.TryStatementAst] -and
    @($node.CatchClauses).Count -eq 1 -and
    $node.CatchClauses[0].Body.Extent.Text.Contains('Complete-FailedRun')
},$true))
if($outer.Count-ne 1){throw 'Expected one actual transport failure boundary'}
function Complete-FailedRun {
    $script:closureAttempted=$true
    if($script:failClosure){throw 'manifest publication failed'}
}
function Complete-RunArtifactPowerShellOwner {
    $script:closureAttempted=$true
    if($script:failClosure){throw 'manifest publication failed'}
}
function Get-RfSimionStoppedWriterCompletion {
    # Isolate publication and finally cleanup errors here. The actual shared
    # owned/inherited release contract has its own public behavior regression.
    return @{operations=@();resource_releases=@()}
}
function Set-RfRunPhase($Next) {}
function Write-RunJson {param($Path,$Value,[switch]$Atomic,$Depth)}
function Exit-HostExecutionLease {
    $script:releaseAttempted=$true
    if($script:failRelease){throw 'host release failed'}
}
function Remove-RunPackageExecutionAlias {$script:aliasRemoved=$true}
$python='unused'; $manifestRepoRoot='unused'; $runConfig='unused'; $summary='unused'
$package=@{}; $hostExecutionLease=@{}; $hostExecutionOwnsLease=$true
$resourceBudgetExceeded=$false; $RunId='fixture'; $resourceUsage='unused'
$script:writerCompletionUnknown=$false;$hostReleased=$false;$deferFinalization=$false
$ownerContext=$null;$hostReleaseState=@{released=$false;completion=$null;unknown=$false};$nativeOperations=@();$fieldCheckpointGuard=$null
$continuationGuards=@();$continuationCapacity=$null;$phaseName='flight';$phaseTimings=@{};$runTimer=[Diagnostics.Stopwatch]::StartNew()
$ResultPath=Join-Path $env:RF_CLOSURE_ROOT 'result.json';$physicalRunDir=$env:RF_CLOSURE_ROOT
$resultDir=$physicalRunDir;$logDir=$physicalRunDir;$solverDir=$physicalRunDir
$cases=@(@($true,$false,$false),@($true,$true,$false),@($true,$false,$true),
    @($true,$true,$true),@($false,$false,$false),@($false,$false,$true))
$readyCases=if($env:RF_IS_SIMION-eq'1'){@($false,$true)}else{@($false)}
$results=@(foreach($ready in $readyCases){foreach($case in $cases){
    if($ready){
      $ownerContext=@{completion_written=$false}
      $workflowRequestPath=Join-Path $physicalRunDir 'request.json'
      [IO.File]::WriteAllText($workflowRequestPath,'{}')
      $runConfig=Join-Path $physicalRunDir 'run_config.json'
      @{inputs=@{execution_request=$workflowRequestPath}}|ConvertTo-Json|Set-Content -LiteralPath $runConfig -Encoding utf8
    }else{$ownerContext=$null;Remove-Variable workflowRequestPath -ErrorAction SilentlyContinue}
    $primary=$case[0]; $script:failClosure=$case[1]; $script:failRelease=$case[2]
    $comsolRunFailure=$null; $simionRunFailure=$null
    $script:closureAttempted=$false; $script:releaseAttempted=$false; $script:aliasRemoved=$false
    $body=if($primary){"throw [InvalidOperationException]::new('original solver failure')"}
        else{'$hostExecutionOutcome="success"'}
    $handler=[scriptblock]::Create('try {'+$body+'} catch '+
        $outer[0].CatchClauses[0].Body.Extent.Text+' finally '+$outer[0].Finally.Extent.Text)
    $failure=$null
    try{if($env:RF_IS_SIMION-eq'1'){$null=& $handler}else{& $handler}}catch{$failure=$_}
    [ordered]@{message=$(if($failure){$failure.Exception.Message}else{$null})
        type=$(if($failure){$failure.Exception.GetType().Name}else{$null})
        closure_error=$(if($failure){$failure.Exception.Data['failure_closure_error']}else{$null})
        host_error=$(if($failure){$failure.Exception.Data['host_release_error']}else{$null})
        closure_attempted=$script:closureAttempted;release_attempted=$script:releaseAttempted
        alias_removed=$script:aliasRemoved}
}})
ConvertTo-Json -InputObject $results -Compress
"""
        # Finite COMSOL uses the public owner; its failure/unknown/CLI cases
        # are exercised in test_comsol_owner_finalization.py. Keep SIMION here.
        for name in ("run_simion_finite_3d_transport.ps1",):
            with self.subTest(runner=name), tempfile.TemporaryDirectory(prefix="rf-closure-") as directory:
                environment = os.environ.copy()
                environment["RF_TRANSPORT_RUNNER"] = str(PROJECT_ROOT / "runtime" / name)
                environment["RF_CLOSURE_ROOT"] = directory
                environment["RF_IS_SIMION"] = "1" if "simion" in name else "0"
                result = _run_pwsh(command, environment)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                records = json.loads(result.stdout.splitlines()[-1])
                self.assertEqual(len(records), 12 if "simion" in name else 6)
                for index, record in enumerate(records):
                    index %= 6
                    self.assertTrue(record["release_attempted"])
                    self.assertTrue(record["alias_removed"])
                    self.assertEqual(record["closure_attempted"], index < 4)
                    if index < 4:
                        self.assertEqual(record["message"], "original solver failure")
                        self.assertEqual(record["type"], "InvalidOperationException")
                        self.assertEqual(record["closure_error"], "manifest publication failed" if index in (1, 3) else None)
                        self.assertEqual(record["host_error"], "host release failed" if index in (2, 3) else None)
                    else:
                        self.assertEqual(record["message"], "host release failed" if index == 5 else None)

    def test_interface_failure_closure_preserves_original_error(self) -> None:
        # Public owner fault behavior is tested centrally; this is its actual
        # project catch/finally seam, including primary-error propagation.
        command = r"""
$ErrorActionPreference='Stop'
$ast=[System.Management.Automation.Language.Parser]::ParseFile($env:RF_INTERFACE_RUNNER,[ref]$null,[ref]$null)
$outer=@($ast.EndBlock.Statements|Where-Object{
 $_-is[System.Management.Automation.Language.TryStatementAst]-and
 $_.CatchClauses[0].Body.Extent.Text.Contains('Complete-InterfaceOwner')
})
if($outer.Count-ne1){throw 'Expected one actual interface owner failure boundary'}
$handler=[scriptblock]::Create("try { throw [InvalidOperationException]::new('original solver failure') } catch "+$outer[0].CatchClauses[0].Body.Extent.Text+' finally '+$outer[0].Finally.Extent.Text)
function Complete-InterfaceOwner {
 param($Status,$Summary,$Outputs,$Failure)
 $script:events.Add('complete')
 if($Status-cne'failed'-or$Failure.Exception.Message-cne'original solver failure'){throw 'Original failure did not reach owner'}
 if($script:failClosure){throw 'manifest publication failed'}
}
function Restore-RunEnvironment {param($Names,$Snapshot) $script:events.Add('restore')}
function Remove-RunPackageExecutionAlias {throw 'Project must not remove owner alias'}
$ownerContext=@{completion_written=$false};$ownerState=@{finalization_started=$false};$capacity=$null
$failureStage='solver';$summaryRole='fixture';$environmentNames=@();$environmentSnapshot=@{}
$resultDir=$env:RF_INTERFACE_FIXTURE_ROOT;$candidateDir=$resultDir;$logDir=$resultDir
$results=@(foreach($script:failClosure in @($false,$true)){
 $script:events=[Collections.Generic.List[string]]::new();$failure=$null
 try{& $handler}catch{$failure=$_}
 @{message=$failure.Exception.Message;type=$failure.Exception.GetType().Name;
   closure_error=$failure.Exception.Data['failure_closure_error'];events=@($script:events.ToArray())}
})
ConvertTo-Json -InputObject $results -Compress
"""
        with tempfile.TemporaryDirectory() as directory:
            environment = os.environ.copy()
            environment.update(RF_INTERFACE_RUNNER=str(RUNNER),
                               RF_INTERFACE_FIXTURE_ROOT=directory)
            result = _run_pwsh(command, environment)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(len(records), 2)
        for record in records:
            self.assertEqual(record["message"], "original solver failure")
            self.assertEqual(record["type"], "InvalidOperationException")
            self.assertEqual(record["events"], ["complete", "restore"])
        self.assertIsNone(records[0]["closure_error"])
        self.assertEqual(records[1]["closure_error"], "manifest publication failed")

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

    def test_development_coarse_compiles_and_authorization_is_not_a_bypass(self) -> None:
        environment = os.environ.copy()
        environment.update({"RF_COMSOL_NUMERICS_SUPPORT": str(NUMERICS_SUPPORT),
                            "RF_COMSOL_OFFICIAL_NUMERICS": str(NUMERICS)})
        command = r"""
. $env:RF_COMSOL_NUMERICS_SUPPORT
$ErrorActionPreference='Stop'
$contract=$env:RF_COMSOL_OFFICIAL_NUMERICS
$cases=@(
 @{id='baseline';profile='baseline';auth=''},
 @{id='coarse';profile='core_flow_development_coarse';auth='core_flow_development'},
 @{id='missing';profile='core_flow_development_coarse';auth=''},
 @{id='wrong';profile='core_flow_development_coarse';auth='same_solver_numerical_convergence'},
 @{id='unregistered';profile='coarse_inline';auth='core_flow_development'}
)
$results=@(foreach($case in $cases){
 try {
  $compiled=(Compile-RfComsolSolverNumerics -OfficialContractPath $contract `
    -RequestedContractPath $contract -ProfileId $case.profile -ExperimentAuthorizationId $case.auth).compiled
  @{id=$case.id;ok=$true;compiled=$compiled}
 } catch { @{id=$case.id;ok=$false;error=$_.Exception.Message} }
})
$results | ConvertTo-Json -Depth 32 -Compress
"""
        result = _run_pwsh(command, environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        cases = {case["id"]: case for case in json.loads(result.stdout)}
        self.assertTrue(cases["baseline"]["ok"])
        self.assertTrue(cases["coarse"]["ok"])
        baseline = cases["baseline"]["compiled"]
        coarse = cases["coarse"]["compiled"]
        self.assertEqual(coarse["role"], "rf_quadrupole_compiled_comsol_solver_numerics")
        self.assertEqual(coarse["mesh"], {"global_auto_level": 9,
                                         "working_region_hmax_override_enabled": False,
                                         "minimum_element_size_mm": 0.2})
        self.assertEqual(baseline["mesh"]["global_auto_level"], 1)
        self.assertNotIn("minimum_element_size_mm", baseline["mesh"])
        self.assertEqual(coarse["trajectory"], baseline["trajectory"])
        self.assertEqual(coarse["trajectory"], {"rf_steps_per_period": 80, "maximum_time_us": 80.0})
        self.assertEqual(coarse["authority"], baseline["authority"])
        self.assertFalse(cases["missing"]["ok"])
        self.assertIn("requires authorization", cases["missing"]["error"])
        self.assertFalse(cases["wrong"]["ok"])
        self.assertIn("requires authorization", cases["wrong"]["error"])
        self.assertFalse(cases["unregistered"]["ok"])
        self.assertIn("not registered", cases["unregistered"]["error"])
        altered = self.baseline()
        altered["profiles"][-1]["mesh"]["global_auto_level"] = 8
        altered["logical_sha256"] = _logical_sha256(altered)
        forged = self.invoke_contract(altered, "core_flow_development_coarse", "core_flow_development")
        self.assertNotEqual(forged.returncode, 0)
        self.assertIn("logical_sha256 is invalid", forged.stderr)

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
        # Actual original CLI and public finalization; only inputs are synthetic.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            initialize_capacity_ledger(artifacts, objects=[])
            invalid = self.baseline()
            invalid["profiles"][0]["mesh"]["global_auto_level"] = 2
            invalid["logical_sha256"] = _logical_sha256(invalid)
            invalid_path = root / "invalid.json"
            invalid_path.write_text(json.dumps(invalid), encoding="utf-8")
            limits = root / "limits.json"
            limits.write_text(json.dumps(dict(wall_clock_seconds=60,
                transient_run_directory_bytes=33554432,
                process_tree_working_set_bytes=2147483648,
                minimum_system_available_memory_bytes=1073741824)), encoding="utf-8")
            run_id = "20261031_110000__test__comsol__invalid-numerics"
            result_path = root / "result.json"
            environment = os.environ.copy()
            for name in ("MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN",
                         "MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID",
                         "MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE"):
                environment.pop(name, None)
            environment.update(MASS_SPECTROMETRY_ARTIFACT_ROOT=str(artifacts),
                MASS_SPECTROMETRY_EXECUTION_ROOT=str(root / "execution"),
                MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(root / "host.sqlite3"))
            command = ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(RUNNER),
                "-RunId", run_id, "-ParticleTablePath", str(invalid_path),
                "-ParticleBundleMetadataPath", str(invalid_path),
                "-SourceFamilyPath", str(invalid_path), "-ParticleDistributionPath", str(invalid_path),
                "-SolverNumericsContractPath", str(invalid_path), "-SolverNumericsProfileId", "baseline",
                "-OperatingPoint", "forged", "-PythonExe", str(RUN_PYTHON),
                "-LimitsPath", str(limits), "-ResultPath", str(result_path)]
            outcome = subprocess.run(command, cwd=REPO_ROOT, env=environment,
                capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertNotEqual(outcome.returncode, 0)
            self.assertIn("logical_sha256", outcome.stdout + outcome.stderr)
            result = json.loads(result_path.read_text(encoding="utf-8-sig"))
            self.assertEqual((result["status"], result["stage"]), ("failed", "complete"))
            self.assertIn("logical_sha256", result["failure_reason"])
            run = artifacts / "projects/rf_multipole_ion_optics/runs" / run_id
            verification = subprocess.run([str(RUN_PYTHON), "-B", "-m",
                "common.contracts.verify_run_manifest", str(run / "run_manifest.json"),
                "--require-status", "failed", "--require-local-run-config"],
                cwd=REPO_ROOT, env=environment, capture_output=True,
                text=True, encoding="utf-8", timeout=60)
            self.assertEqual(verification.returncode, 0, verification.stdout + verification.stderr)
            self.assertFalse((run / "logs/comsol_bootstrap_report.txt").exists())


if __name__ == "__main__":
    unittest.main()
