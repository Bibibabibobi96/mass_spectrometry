"""Explicit failed-action outputs over the real owner; no native subprocesses."""

import json
from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest
from msplatform.execution import owner
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.io.manifest_records import file_record
from tests.contracts import test_execution_runtime as runtime


class FailureOutputTests(unittest.TestCase):
    def test_only_explicit_declared_stopped_outputs_publish_and_primary_survives(self):
        for scenario in ("valid", "undeclared", "escape", "missing", "unknown_writer", "scalar"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                helper = runtime.NormalOwnerTests()
                capacity_policy = root / "fixture-capacity-policy.json"
                capacity_policy.write_text(json.dumps(helper._policy()), encoding="utf-8")
                context = replace(helper._context(root), capacity_policy_path=capacity_policy)
                primary = RuntimeError("original action failure")
                selected = []

                def action(session):
                    path = session.run_dir / "retained.txt"
                    if scenario == "escape":
                        path = root / "outside.txt"
                    if scenario != "undeclared":
                        session.declare_file(path, "required_evidence")
                    if scenario != "missing":
                        path.write_text("explicit recoverable output", encoding="utf-8")
                    other = session.declare_file(session.run_dir / "not_selected.txt", "required_evidence")
                    other.write_text("not automatically published", encoding="utf-8")
                    if scenario == "unknown_writer":
                        session._active.add("inert_unknown_writer")
                    primary.failure_output_paths = str(path) if scenario == "scalar" else [path]
                    selected.append(path)
                    raise primary

                args = helper._arguments(root, action)
                args["action_record"] = file_record(Path(__file__), "required_evidence")
                args["completion_api"] = no_particle_batch_completion_api
                with self.assertRaises(RuntimeError) as caught:
                    owner.run_managed_stage(context, **args)
                self.assertIs(caught.exception, primary)
                manifest_path = next(context.workspace.glob("artifacts/assemblies/instrument_assembly/runs/*/run_manifest.json"))
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if scenario == "valid":
                    self.assertEqual(manifest["status"], "failed", getattr(primary, "__notes__", []))
                    self.assertIn(str(selected[0]), [record["path"] for record in manifest["outputs"]])
                    self.assertNotIn("not_selected.txt", [Path(record["path"]).name for record in manifest["outputs"]])
                else:
                    self.assertEqual(manifest["status"], "checkpoint")
                    self.assertTrue(any("Workflow finalization failed" in note for note in primary.__notes__))
                    self.assertNotIn(str(selected[0]), [record["path"] for record in manifest["outputs"]])
    def _interrupted_store_failure(self):
        from contextlib import ExitStack
        import sys
        from unittest.mock import patch
        from msplatform.backends.simion import native_completion
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.native_artifact_controls import protect_native_controls
        from msplatform.execution.resources import resource_path
        from tests.repository.test_native_artifact_controls import NativeArtifactControlsTests

        fixture = NativeArtifactControlsTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        budget = fixture.root / "budget.json"
        budget.write_text('{"bytes":100}', encoding="utf-8")
        context = ExecutionContext(workspace=fixture.root / "study", python_executable=Path(sys.executable),
            powershell_executable=Path(sys.executable), tools={}, host_state_path=fixture.host,
            policy_path=resource_path("host_resource_policy.json"))
        calls = []
        selected = {}
        primary = RuntimeError("original interrupted science fixture")

        def action(session):
            calls.append(session.run_id)
            evidence = session.declare_file(session.result_dir / "retained.txt", "required_evidence")
            evidence.write_bytes(b"original required failure evidence")
            batch = session.declare_file(session.artifact_run_dir / "logs/simion__batch01.trace.log",
                                         "dense_trajectory")
            batch.write_bytes(b"inert interrupted batch fixture; no completion\n")
            selected.update(evidence=evidence, batch=batch)
            primary.failure_output_paths = [evidence]

            def interrupted(**_kwargs):
                raise OSError("store seal interrupted")

            session._store_seal = interrupted
            raise primary

        run, work = fixture.store.begin_run()
        with fixture.store.run_writer(run):
            fixture.store.mark_running(run)
            with ExitStack() as lifetime, fixture.store.claim_token(fixture.asset) as (claim, _), \
                 fixture.store.reserve(1000000) as reservation:
                with protect_native_controls(fixture.store, run_id=run, claim_ids=(claim,),
                        reservation_ids=(reservation,), work_directory=work), owner.managed_native_store(
                        fixture.store, task_key="original-failure-stage", lifetime=lifetime,
                        account=lambda _path: None), patch.object(
                        owner, "path_capacity", return_value={"legacy_windows_compatible": True}):
                    with self.assertRaisesRegex(RuntimeError, "original interrupted science fixture") as caught:
                        owner.run_managed_stage(context,
                            descriptor=dict(project="instrument_assembly", mode="test", software=[]),
                            run_id="20261128_000000__test__python__store-failure", payload={},
                            committed_new_bytes=100, commitment_inputs=[file_record(budget, "required_evidence")],
                            retention={"policy_version": 1, "class": "solver_review", "reason": "inert test"},
                            expected_operation_ids=[], operation_dependencies={}, action=action,
                            action_record=file_record(Path(__file__), "required_evidence"),
                            completion_api=lambda: native_completion)
                self.assertIs(caught.exception, primary)
                with fixture.store._db() as db:
                    protected_controls = db.execute("SELECT id,kind FROM controls ORDER BY id").fetchall()
            fixture.store.finish_run(run, "failed", reason="owner interrupted")
        with fixture.store._db() as db:
            identity, state = db.execute(
                "SELECT id,state FROM assets WHERE key LIKE 'original-failure-stage:%'").fetchone()
        self.assertEqual(state, "publishing")
        stage_run = next((fixture.store.asset_status(identity)["path"] / "runs").iterdir())
        return dict(fixture=fixture, context=context, identity=identity, stage_run=stage_run,
                    calls=calls, selected=selected, primary=primary, protected_controls=protected_controls)

    @unittest.skipUnless(os.name == "nt", "Windows immutable file sharing required")
    def test_store_recovery_rejects_completion_override_then_preserves_original_failure(self):
        from unittest.mock import patch
        from msplatform.execution.completion import no_particle_batch_completion_api

        fixture = self._interrupted_store_failure()
        store = fixture["fixture"].store
        identity = fixture["identity"]
        run = fixture["stage_run"]
        original_files = {path.relative_to(run).as_posix(): path.read_bytes()
                          for path in run.rglob("*") if path.is_file()}
        self.assertGreaterEqual(len(fixture["protected_controls"]), 2)
        self.assertEqual(store.asset_status(identity)["state"], "publishing")
        with patch("subprocess.Popen", side_effect=AssertionError("recovery must not launch science")):
            with self.assertRaises(TypeError):
                owner.recover_managed_native_store_stage(store, identity, context=fixture["context"],
                    completion_api=no_particle_batch_completion_api)
            self.assertEqual({path.relative_to(run).as_posix(): path.read_bytes()
                              for path in run.rglob("*") if path.is_file()}, original_files)
            self.assertEqual(store.asset_status(identity)["state"], "publishing")
            self.assertEqual(fixture["calls"], ["20261128_000000__test__python__store-failure"])
            self.assertTrue(owner.recover_managed_native_store_stage(
                store, identity, context=fixture["context"]))
            self.assertFalse(owner.recover_managed_native_store_stage(
                store, identity, context=fixture["context"]))
        self.assertEqual(fixture["calls"], ["20261128_000000__test__python__store-failure"])
        self.assertEqual(store.asset_status(identity)["state"], "failed")
        self.assertEqual(fixture["selected"]["evidence"].read_bytes(), b"original required failure evidence")
        self.assertFalse(fixture["selected"]["batch"].exists())
        for relative in ("run_config.json", "inputs/execution_request.json", "results/execution_completion.json"):
            self.assertEqual((run / relative).read_bytes(), original_files[relative])
        retention = json.loads((run / "retention_actions.json").read_text())
        self.assertEqual([(row["path"], row["action"]) for row in retention["removed"]],
                         [("logs/simion__batch01.trace.log", "removed_incomplete_native_trace_before_terminal_manifest")])
        manifest = json.loads((run / "run_manifest.json").read_text())
        self.assertEqual(manifest["status"], "failed")
        self.assertIn(str(fixture["selected"]["evidence"]), [row["path"] for row in manifest["outputs"]])
        with store._db() as db:
            failure = db.execute("SELECT failure FROM assets WHERE id=?", (identity,)).fetchone()[0]
            self.assertEqual(json.loads(failure)["message"], str(fixture["primary"]))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM controls").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM claims").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0], 0)
        self.assertEqual(store.collect(100)["released_bytes"], len(b"field"))
        self.assertEqual(fixture["selected"]["evidence"].read_bytes(), b"original required failure evidence")

    def test_store_publication_recovery_rejects_missing_or_tampered_payload_without_replay(self):
        from unittest.mock import patch
        from msplatform.storage import ArtifactStore

        for case in ("missing", "tampered"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                store = ArtifactStore(Path(directory) / "store")
                run, work = store.begin_run()
                payload = work / "payload"
                payload.write_bytes(b"original failed evidence")
                with store.run_writer(run):
                    store.mark_running(run)
                    with patch("msplatform.storage.store.os.replace", side_effect=OSError("interrupted")):
                        with self.assertRaises(OSError):
                            store.publish_run(work, run_id=run)
                    store.finish_run(run, "failed", reason="original failure")
                if case == "missing":
                    payload.unlink()
                else:
                    payload.write_bytes(b"tampered evidence")
                with patch("subprocess.Popen", side_effect=AssertionError("recovery must not launch science")):
                    with self.assertRaisesRegex(ValueError, "missing or modified"):
                        store.recover_run_publication(run)
                status = store.run_status(run)
                self.assertEqual(status["publication_status"], "publishing")
                self.assertEqual(status["execution_status"], "failed")
                self.assertEqual(status["reason"], "original failure")
                with store._db() as db:
                    self.assertEqual(db.execute(
                        "SELECT COUNT(*) FROM run_writers WHERE run_id=?", (run,)).fetchone()[0], 1)
