"""Explicit failed-action outputs over the real owner; no native subprocesses."""

import json
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
                context = helper._context(root)
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
