"""Focused inert and negative tests for the public RF COMSOL field stage."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from msplatform.backends.comsol.resources import native_resource_path
from msplatform.backends.comsol.rf_stationary_field import run_field_operations
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.workflows.rf_stationary import _build_parser, _field_runtime, solve_comsol


class _Session:
    def __init__(self, root: Path):
        self.run_dir = self.artifact_run_dir = root
        self.input_dir = root / "inputs"
        self.result_dir = root / "results"
        self.log_dir = root / "logs"
        self.run_id = "inert-rf-field"
        self.expected_operation_ids = ("solve_stationary_fields", "verify_stationary_fields")
        self.context = SimpleNamespace(workspace=root, python_executable=root / "python.exe",
            powershell_executable=root / "pwsh.exe", host_state_path=root / "host.sqlite3",
            policy_path=root / "policy.json", tools={"comsol_launcher": root / "comsol.exe",
                                                     "matlab_root": root / "matlab"})
        self.inputs = {}
        self.operations = []
        self.declared = []
        for directory in (self.input_dir, self.result_dir, self.log_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def declare_file(self, path, role):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.declared.append((path, role))
        return path

    def canonical_path(self, path):
        return Path(path).resolve()

    def add_input(self, name, record):
        self.inputs[name] = record

    def run_process(self, operation, **kwargs):
        self.operations.append(operation)
        task = self.input_dir / f"{operation}.m"
        body = task.read_text(encoding="utf-8")
        bootstrap = self.log_dir / f"{operation}.bootstrap.log"
        completion = self.log_dir / f"{operation}.launcher.json"
        completion.write_text(json.dumps({"schema_version": 1, "role": "comsol_launcher_completion",
            "run_id": self.run_id, "operations": [{"observation": {"exit_confirmed": True,
            "returncode": 0, "process_id": 7, "process_started_at_utc_ticks": 1}}],
            "host_release": {"inherited": True, "error": None}}), encoding="utf-8")
        if operation == "solve_stationary_fields":
            self.assert_solve_body(body)
            (self.result_dir / "finite_3d_transport.mph").write_bytes(b"inert-model")
            bootstrap.write_text("CHECKPOINT=MESH_COMPLETE\nCHECKPOINT=STATIONARY_FIELDS_COMPLETE\n"
                "STOP_STAGE=field_solve\nPARTICLE_PHYSICS_CREATED=0\nPARTICLE_STUDIES_CREATED=0\n"
                "MODEL_SAVED=true\nFIELD_SOLVE_DIAGNOSTIC=PASS\nSTATUS=PASS\n", encoding="utf-8")
            progress = self.log_dir / "solver_progress" / "stationary_field_progress.log"
            progress.parent.mkdir(exist_ok=True)
            progress.write_text("inert progress", encoding="utf-8")
        else:
            self.assert_verify_body(body)
            bootstrap.write_text("CHECKPOINT=STATIONARY_FIELD_SAMPLES_COMPLETE\nSTATUS=PASS\n", encoding="utf-8")
            (self.result_dir / "stored_solution_verification.json").write_text(json.dumps({
                "native_solves": 0, "parent_model_saved": False,
                "solution_tags": ["sol_es"]}), encoding="utf-8")

    def assert_solve_body(self, body):
        raise NotImplementedError

    def assert_verify_body(self, body):
        raise NotImplementedError


class _InertSession(_Session):
    def assert_solve_body(self, body):
        if "MULTIPOLE_L3_STOP_STAGE','field_solve'" not in body or "run(" not in body:
            raise AssertionError("field-only science was not invoked")

    def assert_verify_body(self, body):
        if "read_rf_saved_stationary_solution(request)" not in body or "mphsolinfo" not in body:
            raise AssertionError("cold stored-solution verification is incomplete")
        if "runAll" in body or "model.save" in body:
            raise AssertionError("cold verification computes or saves")


class RfStationaryFieldSolveTests(unittest.TestCase):
    def test_inert_backend_reaches_solve_then_zero_compute_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repo"
            science = repository / "projects/rf_multipole_ion_optics/comsol/solve_finite_3d_transport.m"
            science.parent.mkdir(parents=True)
            science.write_text("% inert science", encoding="utf-8")
            (repository / "common/comsol").mkdir(parents=True)
            source = root / "source.csv"
            source.write_text("fixture", encoding="utf-8")
            runtime = {"design_profile_resolution": {"resolved_design": {
                "role": "multipole_resolved_design_do_not_edit", "resolved_sha256": "A" * 64}},
                "solver_numerics": {"comsol": {"values": {"mesh": {}}}},
                "particle_source": {"path": str(source)}}
            session = _InertSession(root / "run")
            points = session.input_dir / "points.csv"
            points.write_text("fixture", encoding="utf-8")
            samples = session.result_dir / "stationary_field_samples.csv"
            with patch("msplatform.backends.comsol.rf_stationary_field.validate_source",
                       return_value={"role": "multipole_canonical_particle_source_metadata"}):
                result = run_field_operations(session, runtime=runtime, science_task=science,
                                              points=points, samples=samples, limits={})
            self.assertEqual(session.operations, ["solve_stationary_fields", "verify_stationary_fields"])
            self.assertEqual(result["solution_tags"], ["sol_es"])
            self.assertIn((session.log_dir / "solver_progress/stationary_field_progress.log",
                           "required_evidence"), session.declared)
            self.assertIn("multipole_resolved_design", session.inputs)
            self.assertTrue(any(name.startswith("science_resource_") for name in session.inputs))

    def test_missing_or_noncanonical_science_fails_before_native(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = _InertSession(Path(temporary))
            with self.assertRaisesRegex(ValueError, "science resource"):
                run_field_operations(session, runtime={}, science_task=Path(temporary) / "missing.m",
                    points=Path(temporary) / "points", samples=Path(temporary) / "samples", limits={})
            self.assertEqual(session.operations, [])

    def test_wrong_operation_graph_fails_before_native(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = _InertSession(Path(temporary))
            session.expected_operation_ids = ("solve_stationary_fields",)
            with self.assertRaisesRegex(ValueError, "operation graph"):
                run_field_operations(session, runtime={}, science_task=Path("unused"),
                    points=Path("unused"), samples=Path("unused"), limits={})
            self.assertEqual(session.operations, [])

    def test_runtime_requires_field_solve_and_matching_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runtime.json"
            runtime = {"schema_version": 1, "role": "multipole_resolved_runtime_profile",
                "project_id": "rf_multipole_ion_optics", "stop_stage": "transport"}
            path.write_text(json.dumps(runtime), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "field_solve"):
                _field_runtime(path, {})

    def test_public_cli_and_installed_resources_expose_stage(self):
        arguments = _build_parser().parse_args(["solve-comsol", "--budget", "budget.json",
            "--run-id", "run", "--source-id", "source", "--workspace", ".", "--python", "python",
            "--powershell", "pwsh", "--host-state", "host", "--policy", "policy",
            "--resolved-runtime", "runtime.json", "--preregistration", "prereg.json",
            "--science-task", "science.m", "--sampling-plan", "plan.json",
            "--comsol-launcher", "comsol", "--matlab-root", "matlab"])
        self.assertEqual(arguments.command, "solve-comsol")
        for name in ("read_rf_saved_stationary_solution.m", "export_comsol_stationary_field_samples.m"):
            self.assertTrue(native_resource_path(name).is_file())

    def test_saved_static_field_uses_the_readable_potential_gradient(self):
        source = native_resource_path("read_rf_saved_stationary_solution.m").read_text(encoding="utf-8")
        for axis in ("x", "y", "z"):
            self.assertIn(f"-d(Vstatic,{axis})", source)
        self.assertNotIn("es_static.Ex", source)

    def test_managed_field_solve_supplies_native_retention_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = {
                "design_profile_resolution": {
                    "resolved_design": {"resolved_sha256": "A" * 64},
                    "profiles_path": str(root / "design.json"),
                },
                "particle_source": {
                    "profile_id": "source", "registry_path": str(root / "source.json"),
                },
                "runtime_profile_registry_path": str(root / "runtime.json"),
                "design_profile_id": "design", "runtime_profile_id": "profile",
                "solver_numerics": {"comsol": {"profile_id": "numerics"}},
                "solver_numerics_registry_paths": {"comsol": str(root / "numerics.json")},
                "engineering_budget": {"path": str(root / "budget.json")},
            }
            science = root / "science.m"
            science.write_text("% inert", encoding="utf-8")
            for name in ("budget.json", "prereg.json", "plan.json", "resolved.json"):
                (root / name).write_text("{}", encoding="utf-8")
            calls = []
            with (
                patch("msplatform.workflows.rf_stationary._budget",
                      return_value=({"limits": {"transient_run_directory_bytes": 1}}, object())),
                patch("msplatform.workflows.rf_stationary._field_runtime", return_value=runtime),
                patch("msplatform.workflows.rf_stationary.sampling.generate_stationary_field_sample_rows",
                      return_value=[]),
                patch("msplatform.workflows.rf_stationary.validate_preregistration",
                      return_value={"field_sampling": {"expected_point_count": 0}}),
                patch("msplatform.workflows.rf_stationary.run_managed_stage",
                      side_effect=lambda *args, **kwargs: calls.append(kwargs) or {"status": "success"}),
            ):
                result = solve_comsol(resolved_runtime=root / "resolved.json",
                    preregistration=root / "prereg.json", science_task=science,
                    sampling_plan=root / "plan.json", budget=root / "budget.json",
                    run_id="run", source_id="source", context=SimpleNamespace())
            self.assertEqual(result["status"], "success")
            self.assertEqual(calls[0]["completion_api"], no_particle_batch_completion_api)

    def test_project_science_saves_only_its_field_only_branch(self):
        science = Path(__file__).resolve().parents[2] / "comsol/solve_finite_3d_transport.m"
        text = science.read_text(encoding="utf-8")
        branch = text[text.index("    if fieldSolveOnly"):text.index("    cpt = comp.physics.create")]
        self.assertIn("model.save(modelPath)", branch)
        self.assertIn("MODEL_SAVED=true", branch)
        self.assertNotIn("ChargedParticleTracing", branch)


if __name__ == "__main__":
    unittest.main()
