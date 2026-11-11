"""Explicit failed-action outputs over the real owner; no native subprocesses."""

import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from msplatform.execution import owner
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.io.manifest_records import file_record
from common.contracts import test_execution_runtime as runtime


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
                manifest_path = next(context.workspace.glob("artifacts/projects/*/runs/*/run_manifest.json"))
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if scenario == "valid":
                    self.assertEqual(manifest["status"], "failed", getattr(primary, "__notes__", []))
                    self.assertIn(str(selected[0]), [record["path"] for record in manifest["outputs"]])
                    self.assertNotIn("not_selected.txt", [Path(record["path"]).name for record in manifest["outputs"]])
                else:
                    self.assertEqual(manifest["status"], "checkpoint")
                    self.assertTrue(any("Workflow finalization failed" in note for note in primary.__notes__))
                    self.assertNotIn(str(selected[0]), [record["path"] for record in manifest["outputs"]])
    def test_public_resume_rejects_wrong_completion_policy_then_finalizes_original_failure(self):
        from unittest.mock import patch
        from msplatform.backends.simion import native_completion
        from msplatform.execution import resume_run
        from msplatform.execution.capacity_ledger import load_capacity_ledger
        from msplatform.execution.capacity_protection import load_capacity_protection_leases

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = runtime.NormalOwnerTests()
            capacity_policy = root / "fixture-capacity-policy.json"
            capacity_policy.write_text(json.dumps(helper._policy()), encoding="utf-8")
            context = replace(helper._context(root), capacity_policy_path=capacity_policy)
            calls = []
            selected = {}
            primary = RuntimeError("original interrupted science fixture")

            def action(session):
                calls.append(session.run_id)
                evidence = session.declare_file(session.result_dir / "retained.txt", "required_evidence")
                evidence.write_bytes(b"original required failure evidence")
                batch = session.declare_file(session.artifact_run_dir / "logs/simion__batch01.trace.log",
                                             "dense_trajectory")
                # Incomplete software fixture: no native completion, PID or exit receipt.
                batch.write_bytes(b"inert interrupted batch fixture; no completion\n")
                selected.update(evidence=evidence, batch=batch)
                primary.failure_output_paths = [evidence]
                raise primary

            arguments = helper._arguments(root, action)
            arguments["action_record"] = file_record(Path(__file__), "required_evidence")
            arguments["completion_api"] = lambda: native_completion
            with patch("msplatform.execution.artifact_retention.apply_retention",
                       side_effect=OSError("RETENTION_INTERRUPTED_BEFORE_PLAN")):
                with self.assertRaises(RuntimeError) as caught:
                    owner.run_managed_stage(context, **arguments)
            self.assertIs(caught.exception, primary)
            self.assertTrue(any("RETENTION_INTERRUPTED_BEFORE_PLAN" in note for note in primary.__notes__))
            artifacts = context.workspace / "artifacts"
            result_path = next(artifacts.glob("projects/*/scratch/workflow_results/*/result.json"))
            pending = json.loads(result_path.read_text(encoding="utf-8"))
            run = Path(pending["run_directory"])
            self.assertEqual(pending["stage"], "finalization")
            self.assertEqual(pending["resume_action"], "resume_finalization")
            self.assertTrue(pending["writers_confirmed"])
            self.assertEqual(pending["exception"]["message"], str(primary))
            self.assertEqual(json.loads((run / "run_manifest.json").read_text())["status"], "checkpoint")
            self.assertFalse((run / "retention_actions.json").exists())
            self.assertFalse((run / ".run_terminal_publication.json").exists())
            original_result = result_path.read_bytes()
            original_files = {path.relative_to(run).as_posix(): path.read_bytes()
                              for path in run.rglob("*") if path.is_file()}
            original_ledger = load_capacity_ledger(artifacts)
            protection = load_capacity_protection_leases(artifacts)
            self.assertEqual(len(protection["audit"]), 1)
            lease = protection["audit"][0]
            self.assertEqual(lease["status"], "active")
            lease_fields = ("lease_id", "owner", "status", "protected_paths",
                            "protected_cache_keys", "committed_new_bytes")
            original_lease = {name: lease[name] for name in lease_fields}
            self.assertIn(run.resolve(), protection["protected_paths"])
            self.assertEqual(calls, [arguments["run_id"]])

            with patch("subprocess.Popen", side_effect=AssertionError("resume must not launch science")):
                with self.assertRaisesRegex(ValueError, "Non-particle action contains unexpected particle batch evidence"):
                    resume_run(result_path, mode="finalization", context=context,
                               completion_api=no_particle_batch_completion_api)
                self.assertEqual(result_path.read_bytes(), original_result)
                self.assertEqual({path.relative_to(run).as_posix(): path.read_bytes()
                                  for path in run.rglob("*") if path.is_file()}, original_files)
                self.assertEqual(load_capacity_ledger(artifacts), original_ledger)
                wrong_protection = load_capacity_protection_leases(artifacts)
                self.assertEqual(len(wrong_protection["audit"]), 1)
                # Resume renews the same live lease; TTL bytes are not immutable.
                self.assertEqual({name: wrong_protection["audit"][0][name] for name in lease_fields},
                                 original_lease)
                self.assertEqual(wrong_protection["protected_paths"], protection["protected_paths"])
                self.assertEqual(calls, [arguments["run_id"]])
                result = resume_run(result_path, mode="finalization", context=context,
                                    completion_api=arguments["completion_api"])
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["stage"], "complete")
            self.assertEqual(result["exception"]["message"], str(primary))
            self.assertEqual(calls, [arguments["run_id"]])
            self.assertEqual(selected["evidence"].read_bytes(), b"original required failure evidence")
            self.assertFalse(selected["batch"].exists())
            for relative in ("run_config.json", "inputs/execution_request.json", "results/execution_completion.json"):
                self.assertEqual((run / relative).read_bytes(), original_files[relative])
            retention = json.loads((run / "retention_actions.json").read_text())
            self.assertEqual([(row["path"], row["action"]) for row in retention["removed"]],
                             [("logs/simion__batch01.trace.log", "removed_incomplete_native_trace_before_terminal_manifest")])
            manifest = json.loads((run / "run_manifest.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertIn(str(selected["evidence"]), [row["path"] for row in manifest["outputs"]])
            self.assertEqual(load_capacity_protection_leases(artifacts)["audit"], [])
            self.assertEqual([(row["class"], row["status"]) for row in load_capacity_ledger(artifacts)["objects"]],
                             [("light_evidence", "ready")])
            self.assertFalse(context.host_state_path.exists())
