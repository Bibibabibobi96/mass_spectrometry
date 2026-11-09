"""EI resolver and real owner wiring with explicitly inert COMSOL observations.

No COMSOL, MATLAB or native scientific result is produced by this module.
"""
from __future__ import annotations
import copy
import json
import os
import shutil
from pathlib import Path
import sys
import tempfile
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from msplatform.backends.comsol import ei_model
from msplatform.execution.context import ExecutionContext
from msplatform.execution.capacity_admission import _capacity_policy
from msplatform.execution.run_session import RunSession
from msplatform.execution.processes import ProcessExecutionError
from msplatform.execution.resources import resource_path

REPO = Path(__file__).resolve().parents[2]
PROJECT = REPO / "projects/apertured_tube_electron_impact_ion_source"


def inputs():
    return tuple(json.loads((PROJECT / "config" / name).read_text(encoding="utf-8"))
                 for name in ("baseline.json", "numerical_modes.json"))


def inert_native(arguments, *, failure=None):
    """Interpret explicit request paths only; do not execute MATLAB task text."""
    def value(name):
        return arguments[arguments.index(name) + 1]
    task = Path(value("-TaskScript"))
    root = task.parent.parent
    contract = root / "inputs/resolved_model.json"
    resolved = json.loads(contract.read_text(encoding="utf-8"))
    model = root / "comsol/MS_Stage1_EISource_ei_prepared_model__build_only.mph"
    report = root / "results" / (task.stem + ".json")
    if task.stem == "build_model":
        model.parent.mkdir()
        model.write_bytes(b"EXPLICIT_INERT_MPH_NOT_A_COMSOL_MODEL")
    elif failure == "tamper":
        model.write_bytes(b"MODIFIED_BY_INERT_VERIFIER")
    runtime = Path(value("-RunDir")) / "comsol_tmp"
    runtime.mkdir()
    (runtime / "inert.tmp").write_bytes(b"diagnostic only")
    if failure == "process":
        raise RuntimeError("inert original process failure")
    result = dict(status="PASS", execution_mode="build_only", model_path=str(model), contract_path=str(contract),
        contract_project_id=resolved["project_id"], contract_model_id=resolved["model_id"],
        selected_mode_id=resolved["selected_mode_id"], parameter_bindings_verified=True,
        candidate_evidence_allowed=False, geometry_built=True, mesh_built=True,
        electrostatics_solved=False, particle_tracing_solved=False, solution_data_empty=[True, True],
        compute_calls=0, model_rewritten=False, geometry_domains=3, mesh_complete=True,
        physics_tags=["es", "cpt"], study_tags=["std1", "std2"], solver_tags=["sol1", "sol2"])
    if task.stem == "verify_model" and failure == "solved":
        result["solution_data_empty"] = [False, True]
    report.write_text(json.dumps(result), encoding="utf-8")
    Path(value("-ReportPath")).write_text("STATUS=RUNNING\nSTATUS=PASS\n", encoding="utf-8")
    receipt = dict(schema_version=1, role="comsol_launcher_completion", run_id=value("-RunId"),
        operations=[dict(operation_id="launcher-attempt-1", observation=dict(exit_confirmed=True,
            returncode=0, process_id=1234, process_started_at_utc_ticks=12345))],
        host_release=dict(inherited=True, token="inert-outer-owner", result=None, error=None))
    if failure == "exit":
        receipt["operations"][0]["observation"]["exit_confirmed"] = False
    Path(value("-CompletionPath")).write_text(json.dumps(receipt), encoding="utf-8")


class InertSession:
    declare_file = RunSession.declare_file
    add_input = RunSession.add_input
    classify_file = RunSession.classify_file

    def __init__(self, root, failure=None):
        self.run_dir = self.artifact_run_dir = root
        self.input_dir, self.result_dir, self.log_dir = (root / name for name in ("inputs", "results", "logs"))
        for path in (self.input_dir, self.result_dir, self.log_dir):
            path.mkdir()
        self.run_config = root / "run_config.json"
        self.run_config.write_text('{"inputs":{}}', encoding="utf-8")
        self.file_roles, self._lock, self.calls = {}, RLock(), []
        self.expected_operation_ids, self.run_id = ("build_model", "verify_model"), "inert-ei"
        self.context = SimpleNamespace(workspace=root, python_executable=Path(sys.executable),
            powershell_executable=Path(sys.executable), host_state_path=root / "state.sqlite3",
            policy_path=resource_path("host_resource_policy.json"),
            tools=dict(comsol_launcher=Path(sys.executable), matlab_root=root))
        self.failure = failure

    def canonical_path(self, path):
        return Path(path).resolve()

    def run_process(self, operation_id, **kwargs):
        self.calls.append((operation_id, kwargs))
        inert_native(kwargs["arguments"], failure=self.failure)


class EiModelTests(unittest.TestCase):
    def test_resolver_preserves_editable_physics_and_numerical_values(self):
        baseline, modes = inputs()
        baseline["electrodes_V"]["cathode"] -= 1
        modes["modes"]["build_only_smoke"]["mesh"]["automatic_level"] = 4
        original = copy.deepcopy((baseline, modes))
        resolved = ei_model.resolve_ei_build_request(baseline, modes, mode_id="build_only_smoke")
        self.assertEqual(resolved["physical"], baseline)
        self.assertEqual(resolved["numerical"], modes["modes"]["build_only_smoke"])
        self.assertEqual((baseline, modes), original)
        with self.assertRaisesRegex(ValueError, "unknown numerical mode"):
            ei_model.resolve_ei_build_request(baseline, modes, mode_id="missing")
        with self.assertRaisesRegex(ValueError, "build_only"):
            ei_model.resolve_ei_build_request(baseline, modes, mode_id="functional_reference", evidence_particle_count=100)

    def test_action_uses_canonical_frozen_topology_and_two_launcher_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            session = InertSession(Path(directory))
            resolved = ei_model.resolve_ei_build_request(*inputs(), mode_id="build_only_smoke")
            result = ei_model.execute_ei_model(session, resolved=resolved, limits={"explicit": 1})
            self.assertEqual([row[0] for row in session.calls], ["build_model", "verify_model"])
            for operation, call in session.calls:
                self.assertEqual((call["role"], call["stage"]), ("COMSOL", "solver"))
                self.assertEqual(call["limits"], {"explicit": 1})
                args = call["arguments"]
                launcher = Path(args[args.index("-File") + 1])
                self.assertEqual(launcher.read_bytes(), ei_model.native_resource_path("run_comsol_r2025b.ps1").read_bytes())
                self.assertTrue((launcher.parent / "../../../execution/resources/host_execution_lease.ps1").resolve().is_file())
                self.assertEqual(args[args.index("-StartupAttempts") + 1], "1")
                self.assertEqual(json.loads(args[args.index("-HostContextJson") + 1])["workspace"], str(session.run_dir))
                script = (session.input_dir / (operation + ".m")).read_text(encoding="utf-8")
                self.assertNotIn(".runAll", script)
                self.assertIn("ms_stage1_ei_source(" if operation == "build_model" else "verify_ei_source_model(", script)
            product = result["manifest_extra_fields"]["products"]["model"]
            self.assertEqual(product["kind"], "prepared_model")
            self.assertEqual(product["metadata"]["field_status"], "not_solved")
            self.assertEqual(product["metadata"]["source_status"], "not_requested")
            self.assertEqual(product["metadata"]["scientific_qualification"], "not_granted")
            for path in session.run_dir.rglob("*"):
                if path.is_file() and path != session.run_config:
                    session.classify_file(path)

    def test_action_rejects_solved_missing_exit_and_changed_mph(self):
        for failure, message in (("solved", "unsolved"), ("exit", "native exit"), ("tamper", "changed")):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                session = InertSession(Path(directory), failure)
                resolved = ei_model.resolve_ei_build_request(*inputs(), mode_id="build_only_smoke")
                with self.assertRaisesRegex((ValueError, AssertionError), message):
                    ei_model.execute_ei_model(session, resolved=resolved, limits={})

    def test_failure_preserves_and_declares_known_runtime_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            session = InertSession(Path(directory), "process")
            resolved = ei_model.resolve_ei_build_request(*inputs(), mode_id="build_only_smoke")
            with self.assertRaisesRegex(RuntimeError, "inert original"):
                ei_model.execute_ei_model(session, resolved=resolved, limits={})
            path = session.run_dir / "comsol_runtime/build_model/comsol_tmp/inert.tmp"
            self.assertTrue(path.is_file())
            self.assertEqual(session.classify_file(path), "solver_native_binary")
            self.assertEqual(len(session.calls), 1)

    def test_diagnostic_collection_failure_does_not_replace_original_process_error(self):
        with tempfile.TemporaryDirectory() as directory:
            session = InertSession(Path(directory), "process")
            resolved = ei_model.resolve_ei_build_request(*inputs(), mode_id="build_only_smoke")
            with patch.object(ei_model, "_runtime_files", side_effect=OSError("inert secondary diagnostics")):
                with self.assertRaisesRegex(RuntimeError, "inert original") as caught:
                    ei_model.execute_ei_model(session, resolved=resolved, limits={})
            self.assertTrue(any("inert secondary diagnostics" in note for note in caught.exception.__notes__))

    def test_public_operation_uses_real_owner_session_and_published_product(self):
        # This inert owner fixture reserves its own small real payload; it does
        # not require the workstation production policy's 295-GiB free disk floor.
        owner_policy = dict(_capacity_policy(), target_gib=1, minimum_free_gib=64 / 1024)
        for failure in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                policy = root / "stages.json"
                limits = dict(wall_clock_seconds=120, transient_run_directory_bytes=64*1024**2,
                    process_tree_working_set_bytes=1024**3, minimum_system_available_memory_bytes=1,
                    compact_final_retained_bytes=64*1024**2, automatic_retry_count=0)
                policy.write_text(json.dumps(dict(schema_version=1, role="execution_stage_policy",
                    stages=dict(build_ei_model=dict(limits=limits, artifact_retention=dict(policy_version=1,
                        **{"class": "solver_review"}, reason="Inert EI owner wiring fixture"))))), encoding="utf-8")
                context = ExecutionContext(workspace=root / "workspace", python_executable=Path(sys.executable),
                    powershell_executable=Path(shutil.which("pwsh")), tools=dict(comsol_launcher=Path(sys.executable), matlab_root=root),
                    host_state_path=root / "host.sqlite3", policy_path=resource_path("host_resource_policy.json"),
                    stage_policy_path=policy)
                calls = []
                def observed(_context, **kwargs):
                    calls.append(kwargs)
                    inert_native(kwargs["arguments"])
                    for name in ("stdout_path", "stderr_path", "usage_path"):
                        kwargs[name].write_text("{}", encoding="utf-8")
                    token = "inert-observed-" + str(len(calls))
                    receipt = dict(observation=dict(exit_code=2 if failure else 0, root_process_id=os.getpid(), root_process_started_at_utc_ticks=123),
                        host_release=dict(inherited=False, token=token, result=dict(status="released", token=token), error=None))
                    if failure:
                        raise ProcessExecutionError("inert native failure with actual exit seam", receipt)
                    return receipt
                with patch("msplatform.execution.capacity_admission._capacity_policy", return_value=owner_policy), \
                     patch("msplatform.execution.run_session.run_observed_process", side_effect=observed):
                    if failure:
                        with self.assertRaisesRegex(ProcessExecutionError, "inert native failure"):
                            ei_model.build_ei_model(*inputs(), mode_id="build_only_smoke", context=context)
                        manifests = list(context.workspace.glob("artifacts/projects/*/runs/*/run_manifest.json"))
                        self.assertEqual(len(manifests), 1)
                        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
                        self.assertEqual(manifest["status"], "failed")
                        self.assertNotIn("products", manifest)
                        self.assertEqual(len(calls), 1)
                        continue
                    product = ei_model.build_ei_model(*inputs(), mode_id="build_only_smoke", context=context)
                self.assertEqual(product.kind, "prepared_model")
                self.assertEqual(product.data_path("model").read_bytes(), b"EXPLICIT_INERT_MPH_NOT_A_COMSOL_MODEL")
                self.assertEqual(len(calls), 2)
                manifest = json.loads(product.manifest_location.read_text(encoding="utf-8"))
                self.assertEqual(manifest["status"], "success")
                self.assertFalse(manifest["formal_eligible"])


if __name__ == "__main__":
    unittest.main()
