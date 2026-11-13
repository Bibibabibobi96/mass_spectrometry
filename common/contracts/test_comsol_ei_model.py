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
import unittest
from unittest.mock import patch

from msplatform.backends.comsol import ei_model, model_execution, wehnelt_model
from msplatform.backends.comsol.resources import native_resource_path
from msplatform.execution.context import ExecutionContext
from msplatform.execution.capacity_admission import _capacity_policy
from msplatform.execution.processes import ProcessExecutionError
from msplatform.execution.resources import resource_path
from common.contracts.test_support.comsol_model import InertComsolSession, inert_native
from common.contracts.test_comsol_wehnelt_model import inputs as wehnelt_inputs

REPO = Path(__file__).resolve().parents[2]
PROJECT = REPO / "projects/apertured_tube_electron_impact_ion_source"


def inputs():
    return tuple(json.loads((PROJECT / "config" / name).read_text(encoding="utf-8"))
                 for name in ("baseline.json", "numerical_modes.json"))




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
            session = InertComsolSession(Path(directory), model_relative_paths=ei_model.NATIVE_MODEL.model_relative_paths)
            resolved = ei_model.resolve_ei_build_request(*inputs(), mode_id="build_only_smoke")
            result = model_execution.execute_unsolved_model(session, resolved=resolved, limits={"explicit": 1}, spec=ei_model.NATIVE_MODEL)
            self.assertEqual([row[0] for row in session.calls], ["build_model", "verify_model"])
            for operation, call in session.calls:
                self.assertEqual((call["role"], call["stage"]), ("COMSOL", "solver"))
                self.assertEqual(call["limits"], {"explicit": 1})
                args = call["arguments"]
                launcher = Path(args[args.index("-File") + 1])
                self.assertEqual(launcher.read_bytes(), native_resource_path("run_comsol_r2025b.ps1").read_bytes())
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
                session = InertComsolSession(Path(directory), model_relative_paths=ei_model.NATIVE_MODEL.model_relative_paths, failure=failure)
                resolved = ei_model.resolve_ei_build_request(*inputs(), mode_id="build_only_smoke")
                with self.assertRaisesRegex((ValueError, AssertionError), message):
                    model_execution.execute_unsolved_model(session, resolved=resolved, limits={}, spec=ei_model.NATIVE_MODEL)

    def test_failure_preserves_and_declares_known_runtime_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            session = InertComsolSession(Path(directory), model_relative_paths=ei_model.NATIVE_MODEL.model_relative_paths, failure="process")
            resolved = ei_model.resolve_ei_build_request(*inputs(), mode_id="build_only_smoke")
            with self.assertRaisesRegex(RuntimeError, "inert original"):
                model_execution.execute_unsolved_model(session, resolved=resolved, limits={}, spec=ei_model.NATIVE_MODEL)
            path = session.run_dir / "comsol_runtime/build_model/comsol_tmp/inert.tmp"
            self.assertTrue(path.is_file())
            self.assertEqual(session.classify_file(path), "solver_native_binary")
            self.assertEqual(len(session.calls), 1)

    def test_diagnostic_collection_failure_does_not_replace_original_process_error(self):
        with tempfile.TemporaryDirectory() as directory:
            session = InertComsolSession(Path(directory), model_relative_paths=ei_model.NATIVE_MODEL.model_relative_paths, failure="process")
            resolved = ei_model.resolve_ei_build_request(*inputs(), mode_id="build_only_smoke")
            with patch.object(model_execution, "declare_runtime_files", side_effect=OSError("inert secondary diagnostics")):
                with self.assertRaisesRegex(RuntimeError, "inert original") as caught:
                    model_execution.execute_unsolved_model(session, resolved=resolved, limits={}, spec=ei_model.NATIVE_MODEL)
            self.assertTrue(any("inert secondary diagnostics" in note for note in caught.exception.__notes__))

    @patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN": ""})
    def test_public_operation_uses_real_owner_session_and_published_product(self):
        # This inert owner fixture reserves its own small real payload; it does
        # not require the workstation production policy's 295-GiB free disk floor.
        owner_policy = dict(_capacity_policy(), target_gib=1, minimum_free_gib=64 / 1024)
        cases = (("build_ei_model", ei_model.build_ei_model, inputs(), {}, ei_model.NATIVE_MODEL),
                 ("build_wehnelt_model", wehnelt_model.build_wehnelt_model, wehnelt_inputs(),
                  {"evidence_particle_count": 3}, wehnelt_model.NATIVE_MODEL))
        for action_name, operation, documents, request_options, spec in cases:
            for failure in (False, True):
                with self.subTest(action=action_name, failure=failure), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    policy = root / "stages.json"
                    limits = dict(wall_clock_seconds=120, transient_run_directory_bytes=64*1024**2,
                        process_tree_working_set_bytes=1024**3, minimum_system_available_memory_bytes=1,
                        compact_final_retained_bytes=64*1024**2, automatic_retry_count=0)
                    stage = dict(limits=limits, artifact_retention=dict(policy_version=1,
                        **{"class": "solver_review"}, reason="Inert COMSOL owner wiring fixture"))
                    policy.write_text(json.dumps(dict(schema_version=1, role="execution_stage_policy",
                        stages={action_name: stage})), encoding="utf-8")
                    context = ExecutionContext(workspace=root / "workspace", python_executable=Path(sys.executable),
                        powershell_executable=Path(shutil.which("pwsh")), tools=dict(comsol_launcher=Path(sys.executable), matlab_root=root),
                        host_state_path=root / "host.sqlite3", policy_path=resource_path("host_resource_policy.json"),
                        stage_policy_path=policy)
                    calls = []
                    def observed(_context, **kwargs):
                        calls.append(kwargs)
                        inert_native(kwargs["arguments"], model_relative_paths=spec.model_relative_paths)
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
                                operation(*documents, mode_id="build_only_smoke", context=context, **request_options)
                            manifests = list(context.workspace.glob("artifacts/projects/*/runs/*/run_manifest.json"))
                            self.assertEqual(len(manifests), 1)
                            manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
                            self.assertEqual(manifest["status"], "failed")
                            self.assertNotIn("products", manifest)
                            self.assertEqual(len(calls), 1)
                            continue
                        product = operation(*documents, mode_id="build_only_smoke", context=context, **request_options)
                    self.assertEqual(product.kind, "prepared_model")
                    self.assertEqual(product.data_path("model").read_bytes(), b"EXPLICIT_INERT_MPH_NOT_A_COMSOL_MODEL")
                    self.assertEqual(len(calls), 2)
                    manifest = json.loads(product.manifest_location.read_text(encoding="utf-8"))
                    self.assertEqual(manifest["status"], "success")
                    self.assertFalse(manifest["formal_eligible"])


if __name__ == "__main__":
    unittest.main()
