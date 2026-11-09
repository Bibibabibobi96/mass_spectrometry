"""Gas-only request and inert native-wiring checks; no COMSOL execution."""

import json
from pathlib import Path
import tempfile
import unittest
from msplatform.backends.comsol import gas_flow
from msplatform.io.manifest_records import file_record
from common.contracts.test_support.comsol_model import InertComsolSession
from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_gas_flow_contract import (
    PROJECT_ROOT,
    _write_fixture,
)


def input_paths():
    return tuple(
        (PROJECT_ROOT / "config" / name).resolve()
        for name in ("baseline.json", "resolved_geometry.json", "gas_flow_science.json", "comsol_solver_numerics.json")
    )


class GasFlowTests(unittest.TestCase):
    def test_request_uses_only_explicit_gas_contracts_and_original_freshness(self):
        request = gas_flow.resolve_gas_flow_request(*input_paths())
        self.assertEqual(request["claim_scope"], "prototype_axisymmetric_empty_enclosure_gas_flow")
        self.assertEqual(set(request["inputs"]), {"baseline", "geometry", "science", "numerics"})
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "geometry.json"
            changed.write_bytes(input_paths()[1].read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "stale"):
                gas_flow.resolve_gas_flow_request(input_paths()[0], changed, *input_paths()[2:])

    def test_actual_action_uses_frozen_launcher_explicit_paths_and_gas_validation(self):
        request = gas_flow.resolve_gas_flow_request(*input_paths())
        with tempfile.TemporaryDirectory() as directory:
            session = InertComsolSession(Path(directory), model_relative_paths=())
            session.expected_operation_ids = ("solve_gas_flow",)
            calls = []

            def inert(operation, **kwargs):
                calls.append((operation, kwargs))
                args = kwargs["arguments"]

                def value(name):
                    return args[args.index(name) + 1]

                output = session.run_dir / "comsol"
                _write_fixture(output)
                (output / request["artifact_names"]["model"]).write_bytes(b"INERT_NOT_A_COMSOL_MODEL")
                (output / "comsol_run_report.txt").write_text("STATUS=PASS\n", encoding="utf-8")
                Path(value("-ReportPath")).write_text("STATUS=PASS\n", encoding="utf-8")
                Path(value("-CompletionPath")).write_text(
                    json.dumps(
                        dict(
                            schema_version=1,
                            role="comsol_launcher_completion",
                            run_id=session.run_id,
                            operations=[
                                dict(
                                    observation=dict(
                                        exit_confirmed=True,
                                        returncode=0,
                                        process_id=123,
                                        process_started_at_utc_ticks=12345,
                                    )
                                )
                            ],
                            host_release=dict(inherited=True, error=None),
                        )
                    ),
                    encoding="utf-8",
                )

            session.run_process = inert
            result = gas_flow._execute(session, request=request, limits={"explicit": True}, parent=None)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], "solve_gas_flow")
            args = calls[0][1]["arguments"]
            self.assertTrue(Path(args[args.index("-File") + 1]).is_relative_to(session.input_dir))
            self.assertEqual(
                json.loads(args[args.index("-HostContextJson") + 1])["workspace"], str(session.context.workspace)
            )
            self.assertEqual(args[args.index("-WorkingDirectory") + 1], str(session.run_dir))
            task = Path(args[args.index("-TaskScript") + 1]).read_text(encoding="utf-8")
            self.assertNotIn("getenv", task)
            for name in ("science", "numerics", "geometry"):
                self.assertIn(str(session.input_dir / (name + ".json")), task)
            product = result["manifest_extra_fields"]["products"]["gas_field"]
            self.assertEqual(product["kind"], "gas_field")
            self.assertNotIn("model", product["data"])
            self.assertIn(str(session.run_dir / "comsol" / request["artifact_names"]["model"]), result["output_paths"])
            self.assertEqual(product["metadata"]["source_status"], "not_requested")
            self.assertEqual(product["metadata"]["scientific_qualification"], "not_granted")


class GasModelResumeTests(unittest.TestCase):
    def test_failed_export_model_requires_positive_writer_and_source_identity(self):
        from msplatform.results.gas_field import read_gas_model

        request = gas_flow.resolve_gas_flow_request(*input_paths())
        for scenario in (
            "valid_failed_export",
            "missing_model_membership",
            "unknown_writer",
            "changed_contract",
            "incomplete_publication",
            "missing_identity",
        ):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                model = root / "retained.mph"
                model.write_bytes(b"INERT_RETAINED_MODEL_NO_CSV")
                model_record = file_record(model, "solver_native_binary")
                completion = dict(
                    schema_version=1,
                    role="run_artifact_workflow_completion",
                    project=gas_flow.PROJECT,
                    run_id="inert-failed-export",
                    mode="axisymmetric_gas_flow_screening",
                    status="failed",
                    writer_completion=dict(
                        operations=[
                            dict(
                                operation_id="solve_gas_flow",
                                resource_release_id="release1",
                                observation=dict(
                                    exit_confirmed=scenario != "unknown_writer",
                                    returncode=1,
                                    process_id=123,
                                    process_started_at_utc_ticks=12345,
                                ),
                            )
                        ],
                        resource_releases=[
                            dict(
                                release_id="release1",
                                completion_receipt=dict(
                                    host_release=dict(
                                        inherited=False,
                                        token="inert-token",
                                        error=None,
                                        result=dict(status="released", token="inert-token"),
                                    )
                                ),
                            )
                        ],
                    ),
                )
                completion_path = root / "completion.json"
                completion_path.write_text(json.dumps(completion), encoding="utf-8")
                completion_record = file_record(completion_path, "required_evidence")
                manifest = dict(
                    schema_version=2,
                    role="simulation_run_manifest",
                    project=gas_flow.PROJECT,
                    run_id="inert-failed-export",
                    mode="axisymmetric_gas_flow_screening",
                    status="failed",
                    inputs=request["inputs"],
                    outputs=[completion_record] + ([] if scenario == "missing_model_membership" else [model_record]),
                )
                manifest_path = root / "run_manifest.json"
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                reference = dict(
                    manifest=file_record(manifest_path, "required_evidence"),
                    model=model_record,
                    completion=completion_record,
                )
                expected = {key: dict(value) for key, value in request["inputs"].items()}
                if scenario == "changed_contract":
                    expected["science"]["sha256"] = "0" * 64
                if scenario == "incomplete_publication":
                    (root / ".run_terminal_publication.json").write_text("{}", encoding="utf-8")
                if scenario == "missing_identity":
                    del reference["completion"]
                if scenario == "valid_failed_export":
                    actual = read_gas_model(reference, expected)
                    self.assertEqual(actual["model"], model_record)
                    self.assertFalse(any(root.glob("*.csv")))
                    self.assertEqual(model.read_bytes(), b"INERT_RETAINED_MODEL_NO_CSV")
                else:
                    with self.assertRaises(ValueError):
                        read_gas_model(reference, expected)


class GasFieldReaderTests(unittest.TestCase):
    def test_historical_data_requires_its_original_contracts_without_reading_model(self):
        from msplatform.results.gas_field import read_gas_field
        from unittest.mock import patch

        for scenario in ("valid", "missing_original", "tampered_csv", "unknown_version"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                csv_path, metadata_path = _write_fixture(root)
                inputs = {}
                for key, name in (
                    ("gas_flow_science", "gas_flow_science.json"),
                    ("comsol_solver_numerics", "comsol_solver_numerics.json"),
                    ("resolved_geometry", "resolved_geometry.json"),
                ):
                    target = root / name
                    target.write_bytes((PROJECT_ROOT / "config" / name).read_bytes())
                    inputs[key] = file_record(target, "required_evidence")
                absent = root / "retired_model.mph"
                model_record = dict(
                    path=str(absent),
                    exists=True,
                    bytes=100000000,
                    sha256="0" * 64,
                    retention_role="solver_native_binary",
                )
                manifest = dict(
                    schema_version=3 if scenario == "unknown_version" else 2,
                    role="simulation_run_manifest",
                    project=gas_flow.PROJECT,
                    run_id="historical-producer",
                    mode="axisymmetric_gas_flow_screening",
                    status="success",
                    inputs=inputs,
                    outputs=[
                        file_record(csv_path, "required_evidence"),
                        file_record(metadata_path, "required_evidence"),
                        model_record,
                    ],
                )
                location = root / "run_manifest.json"
                location.write_text(json.dumps(manifest), encoding="utf-8")
                reference = dict(manifest=file_record(location, "required_evidence"), product_id="gas_field")
                if scenario == "missing_original":
                    Path(inputs["gas_flow_science"]["path"]).unlink()
                if scenario == "tampered_csv":
                    csv_path.write_bytes(csv_path.read_bytes() + b" ")
                if scenario == "valid":
                    opened = []
                    original = Path.open

                    def tracked(path, *args, **kwargs):
                        opened.append(path)
                        return original(path, *args, **kwargs)

                    with patch.object(Path, "open", tracked):
                        field = read_gas_field(reference)
                    self.assertNotIn(absent, opened)
                    self.assertNotIn("model", field.data_locations)
                    self.assertEqual(field.data_locations["science"], root / "gas_flow_science.json")
                    import shutil
                    import subprocess
                    import sys
                    import sysconfig
                    snapshot = root / "snapshot/src/msplatform"
                    shutil.copytree(PROJECT_ROOT.parents[1]/"src/msplatform", snapshot,
                                    ignore=shutil.ignore_patterns("__pycache__"))
                    dependencies = list(dict.fromkeys(sysconfig.get_path(name) for name in ("purelib", "platlib")))
                    code = """
import sys,json,pathlib
sys.path.extend(json.loads(sys.argv[2]))
sys.path.insert(0,sys.argv[1])
class NoExecution:
 def find_spec(self,name,path=None,target=None):
  if name=='msplatform.execution' or name.startswith('msplatform.execution.'):
   raise AssertionError('READ_ONLY_IMPORTED_EXECUTION:'+name)
sys.meta_path.insert(0,NoExecution())
from msplatform.results.gas_field import read_gas_field
result=read_gas_field(json.loads(sys.argv[3]))
assert 'model' not in result.data_locations
assert all(pathlib.Path(module.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())
           for name,module in sys.modules.items() if name=='msplatform' or name.startswith('msplatform.'))
print('COLD_GAS_READER=PASS')
"""
                    child = subprocess.run([sys.executable,"-I","-S","-B","-c",code,str(snapshot.parent),
                        json.dumps(dependencies),json.dumps(reference)],cwd=root,capture_output=True,
                        text=True,encoding="utf-8",timeout=30)
                    self.assertEqual(child.returncode,0,child.stdout+child.stderr)
                    self.assertIn("COLD_GAS_READER=PASS",child.stdout)

                else:
                    with self.assertRaises((FileNotFoundError, AssertionError, ValueError)):
                        read_gas_field(reference)


class GasFlowCapabilityTests(unittest.TestCase):
    def test_query_reuses_actual_validator_without_creating_environment(self):
        from msplatform.capabilities import capabilities

        paths = input_paths()
        arguments = dict(zip(("baseline_path", "geometry_path", "science_path", "numerics_path"), paths))
        result = capabilities(dict(schema_version=1, operation="solve_axisymmetric_gas_flow", arguments=arguments))
        self.assertEqual(result["contract_status"], "accepted")
        self.assertEqual(result["validator"], "msplatform.backends.comsol.gas_flow.resolve_gas_flow_request")
        self.assertEqual(result["native_qualification"], "not_granted")
        arguments["science_path"] = paths[0].parent / "does-not-exist.json"
        rejected = capabilities(dict(schema_version=1, operation="solve_axisymmetric_gas_flow", arguments=arguments))
        self.assertEqual(rejected["contract_status"], "rejected")


class GasFlowOwnerTests(unittest.TestCase):
    def test_public_operation_publishes_gas_data_and_failed_export_model_through_real_owner(self):
        import os
        import sys
        from dataclasses import replace
        from unittest.mock import patch
        from msplatform.execution.processes import ProcessExecutionError
        from msplatform.results.gas_field import read_gas_model
        from common.contracts import test_execution_runtime as runtime

        for failure, author_change in ((False, False), (True, False), (False, True)):
            with self.subTest(failure=failure, author_change=author_change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                author = root / "author inputs"
                author.mkdir()
                paths = []
                for original in input_paths():
                    target = author / original.name
                    target.write_bytes(original.read_bytes())
                    paths.append(target)
                helper = runtime.NormalOwnerTests()
                capacity_policy = root / "fixture-capacity-policy.json"
                capacity_policy.write_text(json.dumps(helper._policy()), encoding="utf-8")
                context = replace(
                    helper._context(root), capacity_policy_path=capacity_policy,
                    tools=dict(comsol_launcher=Path(sys.executable), matlab_root=root)
                )
                policy = root / "stages.json"
                policy.write_text(
                    json.dumps(
                        dict(
                            schema_version=1,
                            role="execution_stage_policy",
                            stages=dict(
                                solve_gas_flow=dict(
                                    limits=dict(
                                        wall_clock_seconds=120,
                                        transient_run_directory_bytes=64 * 1024**2,
                                        process_tree_working_set_bytes=1024**3,
                                        minimum_system_available_memory_bytes=1,
                                        compact_final_retained_bytes=64 * 1024**2,
                                        automatic_retry_count=0,
                                    ),
                                    artifact_retention=dict(
                                        policy_version=1,
                                        **{"class": "solver_review"},
                                        reason="explicit inert owner fixture",
                                    ),
                                )
                            ),
                        )
                    ),
                    encoding="utf-8",
                )
                context = replace(context, stage_policy_path=policy)
                calls = []

                def observed(_context, **kwargs):
                    calls.append(kwargs)
                    args = kwargs["arguments"]

                    def value(name):
                        return args[args.index(name) + 1]

                    task = Path(value("-TaskScript"))
                    run = task.parent.parent
                    native = run / "comsol"
                    request_json = json.loads((run / "inputs/execution_request.json").read_text(encoding="utf-8"))
                    is_resume = request_json["payload"]["resume"] is not None
                    if not is_resume:
                        (native / "axisymmetric_gas_flow.mph").write_bytes(b"INERT_NOT_A_COMSOL_MODEL")
                    (native / "comsol_run_report.txt").write_text(
                        "STATUS=FAIL" if failure else "STATUS=PASS", encoding="utf-8"
                    )
                    for name in ("stdout_path", "stderr_path", "usage_path"):
                        kwargs[name].write_text("{}", encoding="utf-8")
                    receipt = dict(
                        observation=dict(
                            exit_code=7 if failure else 0,
                            root_process_id=os.getpid(),
                            root_process_started_at_utc_ticks=12345,
                        ),
                        host_release=dict(
                            inherited=False,
                            token="inert-token",
                            error=None,
                            result=dict(status="released", token="inert-token"),
                        ),
                    )
                    if failure:
                        raise ProcessExecutionError("inert export failed after MPH save", receipt)
                    _write_fixture(native)
                    if author_change:
                        paths[2].write_text("{}", encoding="utf-8")
                    Path(value("-ReportPath")).write_text("STATUS=PASS", encoding="utf-8")
                    Path(value("-CompletionPath")).write_text(
                        json.dumps(
                            dict(
                                schema_version=1,
                                role="comsol_launcher_completion",
                                run_id=value("-RunId"),
                                operations=[
                                    dict(
                                        observation=dict(
                                            exit_confirmed=True,
                                            returncode=0,
                                            process_id=123,
                                            process_started_at_utc_ticks=12345,
                                        )
                                    )
                                ],
                                host_release=dict(inherited=True, error=None),
                            )
                        ),
                        encoding="utf-8",
                    )
                    return receipt

                with (
                    patch("msplatform.execution.run_session.run_observed_process", side_effect=observed),
                ):
                    if failure:
                        with self.assertRaisesRegex(ProcessExecutionError, "inert export failed after MPH save"):
                            gas_flow.solve_axisymmetric_gas_flow(*paths, context=context)
                    else:
                        product = gas_flow.solve_axisymmetric_gas_flow(*paths, context=context)
                        self.assertEqual(product.kind, "gas_field")
                        self.assertNotIn("model", product.data_locations)
                        self.assertEqual(product.metadata["scientific_qualification"], "not_granted")
                        if author_change:
                            self.assertEqual(paths[2].read_text(encoding="utf-8"), "{}")
                            self.assertEqual(
                                json.loads(product.data_locations["science"].read_text(encoding="utf-8"))["role"],
                                "dual_cone_axisymmetric_gas_flow_science_contract",
                            )
                self.assertEqual(len(calls), 1)
                location = next(context.workspace.glob("artifacts/projects/*/runs/*/run_manifest.json"))
                manifest = json.loads(location.read_text(encoding="utf-8"))
                self.assertEqual(manifest["status"], "failed" if failure else "success")
                if failure:
                    self.assertNotIn("products", manifest)
                    model = next(record for record in manifest["outputs"] if Path(record["path"]).suffix == ".mph")
                    completion = next(
                        record
                        for record in manifest["outputs"]
                        if Path(record["path"]).name == "execution_completion.json"
                    )
                    reference = dict(
                        manifest=file_record(location, "required_evidence"), model=model, completion=completion
                    )
                    request = gas_flow.resolve_gas_flow_request(*paths)
                    accepted = read_gas_model(reference, request["inputs"])
                    self.assertEqual(accepted["model"], model)
                    self.assertFalse(list(location.parent.glob("comsol/*.csv")))
                    original_model = Path(model["path"]).read_bytes()
                    failure = False
                    with (
                        patch("msplatform.execution.run_session.run_observed_process", side_effect=observed),
                    ):
                        reexported = gas_flow.solve_axisymmetric_gas_flow(*paths, context=context, resume=reference)
                    self.assertEqual(reexported.kind, "gas_field")
                    self.assertTrue(reexported.metadata["resumed"])
                    self.assertEqual(Path(model["path"]).read_bytes(), original_model)
                    guards = calls[-1]["immutable_input_records"]
                    self.assertIn(model, guards)
                    self.assertEqual(len(calls), 2)
                    captured = json.loads(
                        (reexported.manifest_location.parent / "logs/capacity_session.json").read_text(encoding="utf-8")
                    )
                    self.assertIn(str(Path(model["path"])), captured["protected_paths"])
