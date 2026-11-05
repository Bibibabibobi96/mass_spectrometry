"""Inert session transport tests, not CAD-engine/native/GUI qualification."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from msplatform.exporters.execution import (
    WORKER_CODE, execute_cad_export, export_worker, no_particle_batch_completion_api,
)
from msplatform.execution.run_session import RunSession
from msplatform.execution.manifest_records import verify_record


class InertSession:
    declare_file = RunSession.declare_file
    add_input = RunSession.add_input
    classify_file = RunSession.classify_file

    def __init__(self, root, mode="success"):
        self.run_dir = self.artifact_run_dir = root
        self.input_dir, self.result_dir, self.log_dir = (root / name for name in ("inputs", "results", "logs"))
        self.log_dir.mkdir()
        self.run_config = root / "run_config.json"
        self.run_config.write_text('{"inputs":{}}', encoding="utf-8")
        self.context = SimpleNamespace(python_executable=Path(sys.executable))
        self.expected_operation_ids = ("export_step",)
        self.file_roles, self.calls, self._lock = {}, [], RLock()
        self.mode = mode

    def canonical_path(self, path):
        return Path(path).resolve()

    def run_process(self, operation_id, **kwargs):
        self.calls.append((operation_id, kwargs))
        if self.mode == "process_failure":
            raise RuntimeError("inert observed process failure")
        request_path = Path(kwargs["arguments"][-1])
        if self.mode == "worker_escape":
            request = json.loads(request_path.read_text(encoding="utf-8"))
            request["step_path"] = str(self.run_dir.parent / "escaped.step")
            request_path.write_text(json.dumps(request), encoding="utf-8")
        elif self.mode == "worker_bool_schema":
            request = json.loads(request_path.read_text(encoding="utf-8"))
            request["schema_version"] = True
            request_path.write_text(json.dumps(request), encoding="utf-8")
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            export_worker(request_path)
        (self.log_dir / "operation_0001.stdout.log").write_text(
            "" if self.mode == "missing_marker" else stream.getvalue(), encoding="utf-8")
        if self.mode in {"missing_step", "missing_report"}:
            (self.result_dir / ("assembly.step" if self.mode == "missing_step" else "cad_export_report.json")).unlink()
        if self.mode == "tampered_step":
            with (self.result_dir / "assembly.step").open("ab") as output:
                output.write(b"changed after report")
        if self.mode == "tampered_input":
            with (self.input_dir / "cad_assembly.json").open("ab") as output:
                output.write(b" ")
        if self.mode == "bool_report_schema":
            path = self.result_dir / "cad_export_report.json"
            report = json.loads(path.read_text(encoding="utf-8"))
            report["schema_version"] = True
            path.write_text(json.dumps(report), encoding="utf-8")


def inert_export(snapshot, *, destination, representation, options):
    """Explicit tiny fake STEP only; actual CAD engine is tested separately."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"INERT_TRANSPORT_NOT_STEP_OR_SCIENTIFIC_EVIDENCE")
    return dict(schema_version=1, role="assembly_step_projection", representation=representation,
                length_unit="mm", step_path=str(destination), options=options)


class CadExecutionTests(unittest.TestCase):
    def execute(self, session):
        with patch("msplatform.exporters.step.export_assembly_step", side_effect=inert_export) as exporter:
            result = execute_cad_export(session, snapshot={"explicit_complete_test_snapshot": "transport_only"},
                representation="physical_solids", options={"write_pcurves": False, "precision_mode": 0},
                limits={"timeout_seconds": 20})
        return result, exporter

    def test_action_freezes_inputs_uses_one_installed_worker_and_returns_owner_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            session = InertSession(Path(directory))
            result, exporter = self.execute(session)
            exporter.assert_called_once()
            self.assertEqual(set(result), {"status", "summary", "output_paths", "required_output_paths",
                                          "retention_preserve_paths", "manifest_extra_fields"})
            self.assertEqual(result["retention_preserve_paths"], [])
            self.assertEqual(len(session.calls), 1)
            operation, call = session.calls[0]
            self.assertEqual((operation, call["role"], call["stage"]), ("export_step", "GATE", "cad_export"))
            self.assertEqual(call["executable"], Path(sys.executable))
            self.assertEqual(call["arguments"][:2], ["-c", WORKER_CODE])
            self.assertNotIn("environment", call)
            product = result["manifest_extra_fields"]["products"]["cad_geometry"]
            self.assertEqual(product["kind"], "cad_geometry")
            self.assertEqual(product["status"], "complete")
            self.assertEqual(product["data"]["step"]["retention_role"], "solver_native_binary")
            for name, record in product["data"].items():
                verify_record(name, record)
                self.assertTrue(Path(record["path"]).is_relative_to(session.run_dir))
            self.assertEqual(len(json.loads(session.run_config.read_text())["inputs"]), 3)
            undeclared = session.run_dir / "unexpected.step"
            undeclared.write_bytes(b"unexpected")
            with self.assertRaisesRegex(ValueError, "undeclared file"):
                session.classify_file(undeclared)

    def test_partial_marker_missing_outputs_tampering_and_worker_boundary_fail_closed(self):
        for mode in ("missing_marker", "missing_step", "missing_report", "tampered_step", "tampered_input",
                     "bool_report_schema", "worker_escape", "worker_bool_schema", "process_failure"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                session = InertSession(Path(directory), mode)
                exception = (AssertionError if mode in {"tampered_step", "tampered_input"} else
                             RuntimeError if mode == "process_failure" else
                             FileNotFoundError if mode in {"missing_step", "missing_report"} else ValueError)
                with self.assertRaises(exception):
                    self.execute(session)
                self.assertEqual(len(session.calls), 1)
                self.assertFalse((session.run_dir.parent / "escaped.step").exists())

    def test_existing_destination_and_escaping_session_are_rejected_before_transport(self):
        for mode in ("existing", "escape"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                session = InertSession(Path(directory))
                if mode == "existing":
                    session.result_dir.mkdir()
                    (session.result_dir / "assembly.step").write_bytes(b"untouched original")
                else:
                    session.canonical_path = lambda path: session.run_dir.parent / Path(path).name
                with self.assertRaises((ValueError, FileExistsError)):
                    self.execute(session)
                self.assertEqual(session.calls, [])
                if mode == "existing":
                    self.assertEqual((session.result_dir / "assembly.step").read_bytes(), b"untouched original")

    def test_no_particle_batch_policy_does_not_accept_partial_step_or_trace_exemptions(self):
        policy = no_particle_batch_completion_api()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "partial.step").write_bytes(b"partial")
            self.assertEqual(policy.recoverable_batch_logs(root), set())
            self.assertIsNone(policy.recoverable_batch_log_kind(root / "partial.step"))
            self.assertFalse(policy.has_recoverable_batch_completion(root / "partial.step"))
            (root / "logs").mkdir()
            for kind in ("trace", "stdout"):
                path = root / "logs" / f"simion__batch01.{kind}.log"
                path.write_text("status,Fly completed. 1 splats")
                with self.assertRaisesRegex(ValueError, "unexpected particle batch"):
                    policy.recoverable_batch_logs(root)
                self.assertIsNone(policy.recoverable_batch_log_kind(path))
                self.assertFalse(policy.has_recoverable_batch_completion(path))
                path.unlink()
