"""Geometry orchestration with inert process outputs; no native qualification."""
from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.test_simion_geometry_compiler import compiler_inputs
from common.contracts.test_simion_native_plans import SEED
from msplatform.backends.simion.compiler import compile_geometry
from msplatform.backends.simion.geometry_execution import execute_geometry, GEOMETRY_RESOURCES
from msplatform.backends.simion.native_plans import plan_geometry_build
from msplatform.execution.manifest_records import verify_record


class InertSession:
    """Only test transport/materialization; never impersonate a native receipt."""

    def __init__(self, root, compiled, *, omit_marker=False, omit_output=False):
        self.run_dir = self.artifact_run_dir = root
        self.input_dir, self.log_dir = root / "inputs", root / "logs"
        self.context = SimpleNamespace(tools={"simion": Path(__file__).resolve()})
        self.plan = plan_geometry_build(compiled, run_directory=root, seed_record=SEED,
            native_path_resource=root / "inputs/native_sources/native_run_path.lua")
        self.expected_operation_ids = tuple(op["operation_id"] for op in self.plan.operations)
        self.inputs, self.roles, self.calls = {}, {}, []
        self.omit_marker, self.omit_output = omit_marker, omit_output

    def canonical_path(self, path):
        return Path(path).resolve()

    def declare_file(self, path, role):
        self.roles[str(path)] = role

    def add_input(self, name, record):
        verify_record(name, record)
        self.inputs[name] = copy.deepcopy(record)

    def run_process(self, operation_id, **options):
        self.calls.append((operation_id, options))
        operation = self.plan.operations[len(self.calls) - 1]
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.log_dir / f"operation_{len(self.calls):04d}.stdout.log").write_bytes(
            b"inert orchestration test only\n" if self.omit_marker else
            operation["success_marker"].encode("ascii"))
        if not self.omit_output:
            for path in operation["outputs"]:
                Path(path).write_bytes(b"INERT TEST BYTES - NOT SIMION OUTPUT")


class GeometryExecutionTests(unittest.TestCase):
    def prepared(self, directory, **options):
        root = Path(directory)
        assembly, numerics, _ = compiler_inputs(root / "author")
        compiled = compile_geometry(assembly, numerics=numerics)
        return compiled, InertSession(root / "run", compiled, **options)

    def test_materializes_actual_plan_and_frozen_resources_without_extra_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            compiled, session = self.prepared(directory)
            original = copy.deepcopy(compiled)
            result = execute_geometry(session, compiled=compiled, seed_record=SEED, limits={"timeout_seconds": 600})
            self.assertEqual(compiled, original)
            self.assertEqual([name for name, _ in session.calls], list(session.expected_operation_ids))
            for _, options in session.calls:
                script = Path(options["arguments"][3])
                self.assertEqual(script.parent, session.input_dir / "native_sources")
                self.assertTrue(script.is_file())
                self.assertEqual(options["limits"], {"timeout_seconds": 600})
                self.assertNotIn("refine", options["arguments"])
                self.assertNotIn("fly", options["arguments"])
            for name in (*GEOMETRY_RESOURCES, "native_run_path.lua"):
                record = session.inputs["native_source_" + name]
                verify_record(name, record)
                self.assertEqual(Path(record["path"]).parent, session.input_dir / "native_sources")
            self.assertEqual(Path(session.inputs["structural_seed"]["path"]).read_bytes(), Path(SEED["path"]).read_bytes())
            product = result["manifest_extra_fields"]["products"]["geometry"]
            self.assertEqual(product["metadata"]["field_status"], "not_solved")
            self.assertEqual(product["metadata"]["relocation_qualification"], "not_assessed")
            self.assertEqual((session.input_dir / "no_particles.fly2").read_text(encoding="utf-8"),
                             "particles {\n  coordinates = 0,\n}\n")
            self.assertEqual(product["data"]["zero_particle_format_control"]["retention_role"], "required_evidence")
            self.assertEqual(product["metadata"]["sampled_particles"], 0)
            self.assertFalse(list(session.run_dir.rglob("*.ion")))
            for record in product["data"].values():
                verify_record("inert product member", record)

    def test_native_marker_and_declared_outputs_are_both_required(self):
        for options, error in (({"omit_marker": True}, ValueError), ({"omit_output": True}, FileNotFoundError)):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                compiled, session = self.prepared(directory, **options)
                with self.assertRaises(error):
                    execute_geometry(session, compiled=compiled, seed_record=SEED, limits={})
                self.assertEqual(len(session.calls), 1)

    def test_explicit_io_mode_is_transported_to_every_native_geometry_process(self):
        with tempfile.TemporaryDirectory() as directory:
            compiled, session = self.prepared(directory)
            session.context.tools["simion"] = Path(directory) / "simion.exe"
            result = execute_geometry(session, compiled=compiled, seed_record=SEED, limits={},
                                      allow_asynchronous_io=False)
            self.assertEqual(len(session.calls), len(session.expected_operation_ids))
            for _, options in session.calls:
                argv = options["arguments"]
                self.assertEqual(argv[:3], ["--nogui", "--noprompt", "--lua"])
                self.assertIn("d.allow_asynchronous_io=false", argv[3])
                self.assertEqual(argv[4], "lua")
                self.assertEqual(Path(argv[5]).parent, session.input_dir / "native_sources")
            self.assertIs(result["summary"]["requested_allow_asynchronous_io"], False)

    def test_undeclared_operations_and_escape_are_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            compiled, session = self.prepared(directory)
            session.expected_operation_ids = ()
            with self.assertRaisesRegex(ValueError, "admitted operations"):
                execute_geometry(session, compiled=compiled, seed_record=SEED, limits={})
            self.assertFalse(session.run_dir.exists())
            session.expected_operation_ids = tuple(op["operation_id"] for op in session.plan.operations)
            session.plan.materializations[str(Path(directory) / "escaped.lua")] = "return {}"
            with patch("msplatform.backends.simion.geometry_execution.plan_geometry_build", return_value=session.plan):
                with self.assertRaisesRegex(ValueError, "escapes"):
                    execute_geometry(session, compiled=compiled, seed_record=SEED, limits={})
            self.assertFalse(session.run_dir.exists())
            self.assertFalse((Path(directory) / "escaped.lua").exists())
