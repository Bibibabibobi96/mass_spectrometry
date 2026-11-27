"""Bind the real split-model contract to authenticated response-file records."""
from __future__ import annotations

from contextlib import contextmanager
import copy
import json
import subprocess
import sys
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

from msplatform.backends.simion.reflectron_response_binding import compile_response_fit, plan_response_axis_sampling, fit_sampled_axis, sample_response_axis, plan_compensated_reflectron
from msplatform.backends.simion.model import compile_prepared_model, model_geometry
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import open_artifact
from tests.contracts import test_split_scalar_binding as split_fixture


class ReflectronResponseBindingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = split_fixture.SplitScalarBindingTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.model = self.fixture.model
        self.root = Path(self.fixture.tmp.name)
        document = self.model.document
        tof = document["components_resolved"][document["geometry"]["frontend_geometry"]["tof_instance_id"]]
        count = 4 + tof["rings"]["stage1_count"] + tof["rings"]["stage2_count"]
        self.spatial = {"role": "test_derived_operator", "identity_sha256": "A" * 64}
        spec = next(row for row in model_geometry(self.model, downstream_drive=True).downstream_specs
                    if row["role"] == "reflectron")
        instance, variables = spec["native_instance"], spec["template_variables"]
        self.grid = {**{key: instance[key] for key in ("nx", "ny", "nz")},
                     "dx_mm": variables["mmgu_axial"], "dy_mm": variables["mmgu_radial"],
                     "dz_mm": variables["mmgu_radial"]}
        self.records, self.paths = {}, {}
        model_path = self.root / "compiled_model.json"
        model_path.write_text(json.dumps(document), encoding="utf-8")
        self.records["compiled_model"] = file_record(model_path, "required_evidence")
        self.paths["compiled_model"] = model_path
        responses = []
        for i in range(1, count + 1):
            key = "response_" + str(i)
            path = self.root / ("reflectron_response_" + str(i) + ".pa")
            path.write_bytes(("response-" + str(i)).encode())
            self.records[key] = file_record(path, "solver_native_binary")
            self.paths[key] = path
            responses.append({"response_id": i, "data_key": key})
        self.metadata = {"model_identity_sha256": document["model_identity_sha256"],
                         "downstream_identity": self.spatial, "reflectron_response_basis": {
                             "schema_version": 2, "model_identity_sha256": document["model_identity_sha256"],
                             "downstream_identity": self.spatial, "grid": self.grid,
                             "symmetry": "2dcylindrical", "responses": responses}}

    def artifact(self):
        path = self.root / "run_manifest.json"
        manifest = {"schema_version": 2, "role": "simulation_run_manifest", "status": "success",
                    "project": "instrument_assembly", "run_id": self.root.name, "mode": "fixture",
                    "inputs": {}, "outputs": list(self.records.values()),
                    "products": {"fields": {"schema_version": 1, "kind": "field_bundle", "status": "complete",
                                             "metadata": self.metadata, "data": self.records}}}
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return open_artifact({"manifest": file_record(path, "required_evidence"), "product_id": "fields"},
                             expected_kind="field_bundle")

    def compile(self):
        return compile_response_fit(self.artifact(), expected_model=self.model,
            expected_downstream_identity=self.spatial, expected_grid=self.grid,
            expected_frame_id="oatof_global", regularization=0.0001)

    def test_split_basis_binds_order_geometry_and_explicit_parameter(self):
        result = self.compile()
        self.assertEqual(result["frame_id"], "oatof_global")
        self.assertEqual([r["response_id"] for r in result["responses"]],
                         list(range(1, len(result["responses"]) + 1)))
        self.assertEqual(result["fit_parameters"]["regularization"], 0.0001)
        self.assertEqual(result["fit_parameters"]["stage1_count"], 10)

    def test_rebias_composition_is_followed_by_fresh_native_audit(self):
        from msplatform.backends.simion.field_execution import _run_rebias_operations
        from msplatform.backends.simion.resources import native_resource_path
        root = self.root / "rebias"
        root.mkdir()
        base, one, two, output = (root / name for name in ("base.pa", "one.pa", "two.pa", "new.pa"))
        for path in (base, one, two): path.write_bytes(b"INERT_ONLY")
        records_in = [file_record(path, "solver_native_binary") for path in (base, one, two)]
        by_path = {row["path"]: row for row in records_in}
        copied = list(records_in)
        audit_spec, audit_output = root / "audit.lua", root / "audit.json"
        resources = {name: native_resource_path(name) for name in ("compose_standalone_pa.lua", "audit_downstream_fields.lua")}
        resources_records = {"resource_" + name: file_record(path, "required_evidence") for name, path in resources.items()}
        audit_plan = SimpleNamespace(operations=[{"arguments": ["--nogui", "--noprompt", "lua",
            str(resources["audit_downstream_fields.lua"]), str(audit_spec)], "outputs": [str(audit_output)]}],
            materializations={str(audit_spec): "return {}\n"})
        class Session:
            def __init__(self):
                self.context = SimpleNamespace(tools={"simion": root / "simion.exe"})
                self.expected_operation_ids = ["compose_reflectron", "audit_rebiased_downstream"]
                self.log_dir = root / "logs"; self.log_dir.mkdir(exist_ok=True); self.calls = []; self.inputs = {}; self.fail_marker = False
            def declare_file(self, path, _role): return Path(path)
            def canonical_path(self, path): return Path(path).resolve()
            def add_input(self, name, record): self.inputs[name] = record
            def run_process(self, operation_id, **kwargs):
                self.calls.append((operation_id, kwargs))
                if operation_id == "compose_reflectron":
                    output.write_bytes(b"INERT_COMPOSED")
                    marker = "MISSING" if self.fail_marker else "STANDALONE_PA_COMPOSITION=PASS"
                else:
                    audit_output.write_text('{"status":"success"}', encoding="utf-8")
                    marker = "DOWNSTREAM_NATIVE_AUDIT=PASS"
                index = self.expected_operation_ids.index(operation_id) + 1
                (self.log_dir / f"operation_{index:04d}.stdout.log").write_text(marker, encoding="utf-8")
        session = Session()
        audit = _run_rebias_operations(session, reflectron_plan={"carrier_path": str(output),
            "response_paths": [str(one), str(two)]}, rebias_plan={"responses": [{"coefficient": 0.1},
            {"coefficient": -0.2}]}, rebias_base=base, by_path=by_path, copied=copied,
            resources=resources, records=resources_records, downstream_plan=audit_plan, limits={},
            allow_asynchronous_io=None)
        self.assertEqual([item[0] for item in session.calls], ["compose_reflectron", "audit_rebiased_downstream"])
        self.assertTrue(session.calls[0][1]["arguments"][-2].endswith(",0.10000000000000001"))
        self.assertTrue(session.calls[0][1]["arguments"][-1].endswith(",-0.20000000000000001"))
        self.assertEqual(audit["path"], str(audit_output))
        self.assertIn(str(output), {row["path"] for row in session.calls[1][1]["immutable_input_records"]})
        session.fail_marker = True; session.calls.clear()
        with self.assertRaisesRegex(ValueError, "composition completion marker"):
            _run_rebias_operations(session, reflectron_plan={"carrier_path": str(output),
                "response_paths": [str(one), str(two)]}, rebias_plan={"responses": [{"coefficient": 0.1},
                {"coefficient": -0.2}]}, rebias_base=base, by_path=by_path, copied=copied,
                resources=resources, records=resources_records, downstream_plan=audit_plan, limits={},
                allow_asynchronous_io=None)
        self.assertEqual([item[0] for item in session.calls], ["compose_reflectron"])

    def test_store_field_action_holds_both_source_guards(self):
        from msplatform.backends.simion.field_execution import execute_fields
        store = object()
        model_ref = {"manifest": {"path": "model"}, "product_id": "model"}
        field_ref = self.artifact().reference
        basis = {"reference": field_ref, "fit": {}, "regularization": 0.0}
        events = []
        @contextmanager
        def guard(reference, *, expected_kind, expected_artifact_root, artifact_store):
            self.assertIs(artifact_store, store)
            events.append("enter_" + expected_kind)
            try:
                yield SimpleNamespace(reference=reference)
            finally:
                events.append("exit_" + expected_kind)
        def body(_session, **kwargs):
            events.append("execute")
            self.assertEqual(kwargs["model_reference"], model_ref)
            self.assertEqual(kwargs["compensated_basis"]["reference"], field_ref)
            return {"status": "fixture"}
        session = SimpleNamespace(context=SimpleNamespace(workspace=self.root))
        materializer_record = file_record(Path(__file__), 'required_evidence')
        limits = {'reserved_run_payload_bytes': 0}
        with patch("msplatform.execution.owner.current_managed_native_store", return_value={"store": store}), \
             patch("msplatform.execution.native_source_guard.guard_native_source", guard), \
             patch("msplatform.backends.simion.field_execution._execute_fields", side_effect=body):
            result = execute_fields(session, model_reference=model_ref, numerics={}, limits=limits,
                materialize_geometry=lambda *a, **k: None, materializer_record=materializer_record, compensated_basis=basis)
        self.assertEqual(result["status"], "fixture")
        self.assertEqual(events, ["enter_prepared_model", "enter_field_bundle", "execute",
                                  "exit_field_bundle", "exit_prepared_model"])
        with patch("msplatform.execution.owner.current_managed_native_store", return_value=None):
            with self.assertRaisesRegex(ValueError, "managed native Store scope"):
                execute_fields(session, model_reference=model_ref, numerics={}, limits=limits,
                    materialize_geometry=lambda *a, **k: None, materializer_record=materializer_record, compensated_basis=basis)

    def test_compensated_field_graph_has_owned_composition_and_fresh_audit(self):
        from msplatform.backends.simion.field_execution import plan_fields_execution
        from tests.contracts.test_simion_field_action import public_case
        model, numerics, _clock, _root = public_case()
        requested = {"reference": self.artifact().reference, "fit": {"status": "success",
            "role": "oatof_reflectron_monotone_axis_field_voltage_fit"}, "regularization": 0.0}
        graph = plan_fields_execution(model, numerics=numerics, compensated_basis=requested)
        self.assertTrue(graph["reuse_requested"])
        self.assertTrue(graph["compensated_basis_requested"])
        self.assertEqual(graph["operation_dependencies"]["compose_reflectron"], ["materialize_geometry"])
        self.assertEqual(graph["operation_dependencies"]["audit_rebiased_downstream"], ["compose_reflectron"])
        self.assertIn("audit_rebiased_downstream", graph["operation_dependencies"]["downstream_fields"])
        with self.assertRaisesRegex(ValueError, "exclusive"):
            plan_fields_execution(model, numerics=numerics, compensated_basis=requested,
                                  reuse_fields_reference=self.artifact().reference)

    def test_rebias_binds_exact_new_model_and_only_changed_ring_coefficients(self):
        from msplatform.analysis.reflectron_compensation import compile_compensated_study
        binding = self.compile()
        original = self.model.document
        groups = original["drive"]["groups"]["tof"]
        params = binding["fit_parameters"]
        fit = {"role": "oatof_reflectron_monotone_axis_field_voltage_fit", "status": "success",
               "fit": {"regularization": 0.0001},
               "fixed_endpoints_V": {"entrance": 0.0, "midgrid": params["midgrid_voltage_v"],
                                     "backplate": params["backplate_voltage_v"], "shield": 0.0}}
        for stage in (1, 2):
            count = params[f"stage{stage}_count"]
            values = [groups[f"reflectron_stage{stage}_ring_{i}"]["voltage_v"] for i in range(1, count + 1)]
            fit[f"stage{stage}_count"] = count
            fit[f"baseline_stage{stage}_ring_voltages_V"] = values
            fit[f"stage{stage}_ring_voltages_V"] = [values[0] + 1, *values[1:]]
        author = compile_compensated_study({"drive": original["drive"]}, instance_id="tof", fit=fit)
        new_model = compile_prepared_model(model_geometry(self.model), original["components_resolved"],
                                            drive=author["drive"], physics=original["physics"])
        fake_assets = {"reflectron": {"carrier_record": {"path": "fixture-only.pa"}}}
        options = dict(original_model=self.model, compensated_model=new_model,
            expected_downstream_identity=self.spatial, expected_grid=self.grid,
            expected_frame_id="oatof_global", fit=fit, regularization=0.0001)
        with patch("msplatform.backends.simion.field_closure.require_downstream_reuse", return_value=(None, fake_assets)):
            plan = plan_compensated_reflectron(self.artifact(), **options)
            active = [row for row in plan["responses"] if row["coefficient"] != 0]
            self.assertEqual(len(active), 2)
            self.assertTrue(all(abs(row["coefficient"] - 0.0001) < 1e-14 for row in active))
            with self.assertRaisesRegex(ValueError, "exact authored ring change"):
                plan_compensated_reflectron(self.artifact(), **dict(options, compensated_model=self.model))
            with self.assertRaisesRegex(ValueError, "regularization differs"):
                plan_compensated_reflectron(self.artifact(), **dict(options, regularization=0.2))

    def test_sampling_action_registers_immutable_inputs_and_axis_output(self):
        from msplatform.backends.simion.reflectron_response_binding import _sample_axis_action
        field = self.artifact()
        root = self.root / "owner"
        class Session:
            def __init__(self):
                self.run_dir = root; self.input_dir = root / "inputs"; self.log_dir = root / "logs"
                self.context = SimpleNamespace(tools={"simion": root / "simion.exe"})
                self.inputs = {}; self.roles = {}; self.calls = []
                self.input_dir.mkdir(parents=True); self.log_dir.mkdir(parents=True)
            def declare_file(self, path, role):
                path = Path(path); self.roles[str(path)] = role; return path
            def canonical_path(self, path): return Path(path).resolve()
            def add_input(self, name, record): self.inputs[name] = record
            def run_process(self, operation_id, **kwargs):
                self.calls.append((operation_id, kwargs))
                axis = self.run_dir / "simion/axis/response_axis.csv"
                axis.parent.mkdir(parents=True, exist_ok=True); axis.write_text("x_mm\n0\n", encoding="utf-8")
                (self.log_dir / "operation_0001.stdout.log").write_text("AXIS_BASIS_EXPORT=PASS\n", encoding="utf-8")
        session = Session()
        result = _sample_axis_action(session, field_reference=field.reference, expected_model=self.model,
            expected_downstream_identity=self.spatial, expected_grid=self.grid, expected_frame_id="oatof_global",
            regularization=0.0001, maximum_x_mm=1, limits={})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["manifest_extra_fields"]["products"]["axis"]["kind"], "axis_response_samples")
        operation, call = session.calls[0]
        self.assertEqual(operation, "sample_reflectron_responses")
        immutable = {row["path"] for row in call["immutable_input_records"]}
        self.assertEqual(immutable, {row["path"] for row in session.inputs.values()})
        self.assertEqual(len([name for name in session.inputs if name.startswith("response_")]), len(self.paths) - 1)
        self.assertEqual(session.roles[result["output_paths"][0]], "required_evidence")

    def test_sampling_admits_source_guard_and_store_owner_before_native_stage(self):
        field = self.artifact()
        store = SimpleNamespace(root=self.root / "store")
        context = SimpleNamespace(tools={"simion": Path(sys.executable)}, workspace=self.root)
        policy = {"limits": {"transient_run_directory_bytes": 1024}, "artifact_retention": {}}
        sequence = []
        @contextmanager
        def guard(reference, **kwargs):
            self.assertEqual(reference, field.reference)
            self.assertIs(kwargs["artifact_store"], store)
            sequence.append("source_enter")
            try:
                yield field
            finally:
                sequence.append("source_exit")
        @contextmanager
        def owner(actual_store, **kwargs):
            self.assertIs(actual_store, store)
            self.assertEqual(kwargs["budget"], 1024)
            sequence.append("store_enter")
            try:
                yield {}
            finally:
                sequence.append("store_exit")
        def stage(_context, **kwargs):
            sequence.append("native_stage")
            self.assertIs(kwargs["artifact_store"], store)
            self.assertEqual(kwargs["source_references"], [{"manifest_record": field.reference["manifest"]}])
            raise RuntimeError("fixture stage boundary")
        with patch("msplatform.execution.native_source_guard.guard_native_source", guard), \
             patch("msplatform.execution.owner.standalone_native_store", owner), \
             patch("msplatform.execution.owner.run_managed_stage", side_effect=stage), \
             patch("msplatform.execution.stage_policy.read_stage_policy", return_value=(policy, {})):
            with self.assertRaisesRegex(RuntimeError, "fixture stage boundary"):
                sample_response_axis(field, expected_model=self.model, expected_downstream_identity=self.spatial,
                    expected_grid=self.grid, expected_frame_id="oatof_global", regularization=0.0001,
                    maximum_x_mm=1.0, context=context, artifact_store=store)
        self.assertEqual(sequence, ["source_enter", "store_enter", "native_stage", "store_exit", "source_exit"])

    def test_sample_fit_reads_manifest_and_normalizes_ordered_native_columns(self):
        binding = self.compile()
        count = len(binding["responses"])
        axis = self.root / "axis.csv"
        header = ["x_mm", *[f"basis_{i}_V" for i in range(1, count + 1)]]
        axis.write_text(",".join(header) + "\n" + "0," + ",".join(["10000"] * count) + "\n" +
            "1," + ",".join(["5000"] * count) + "\n", encoding="utf-8")
        record = file_record(axis, "required_evidence")
        metadata = {"binding": binding, "maximum_x_mm": 1, "samples_unit": "V", "position_unit": "mm",
                    "basis_normalization_v": 10000.0}
        manifest_path = self.root / "axis_manifest.json"
        manifest_path.write_text(json.dumps({"schema_version": 2, "role": "simulation_run_manifest",
            "status": "success", "project": "instrument_assembly", "run_id": self.root.name,
            "mode": "fixture", "inputs": {}, "outputs": [record], "products": {"axis": {
                "schema_version": 1, "kind": "axis_response_samples", "status": "complete",
                "metadata": metadata, "data": {"axis_csv": record}}}}), encoding="utf-8")
        artifact = open_artifact({"manifest": file_record(manifest_path, "required_evidence"), "product_id": "axis"}, expected_kind="axis_response_samples")
        with patch("msplatform.analysis.reflectron_voltage_fit.optimize", return_value={"status": "fixture"}) as optimize:
            self.assertEqual(fit_sampled_axis(artifact), {"status": "fixture"})
            args, kwargs = optimize.call_args
            self.assertEqual(args[0].tolist(), [0.0, 1.0])
            self.assertEqual(args[1][0].tolist(), [1.0] * count)
            self.assertEqual(args[1][1].tolist(), [0.5] * count)
            self.assertEqual(kwargs, binding["fit_parameters"])
        axis.write_text("bad\n", encoding="utf-8")
        with self.assertRaises((ValueError, AssertionError)):
            fit_sampled_axis(artifact)

    def test_sampling_plan_uses_ordered_independent_files_and_rejects_bad_limits(self):
        kwargs = dict(expected_model=self.model, expected_downstream_identity=self.spatial,
            expected_grid=self.grid, expected_frame_id="oatof_global", regularization=0.0001,
            sampling_directory=self.root / "sample", exporter_resource=self.root / "export.lua")
        binding, plan = plan_response_axis_sampling(self.artifact(), maximum_x_mm=1.0, **kwargs)
        spec = next(iter(plan.materializations.values()))
        for row in binding["responses"]:
            self.assertIn(Path(row["path"]).name, spec)
        self.assertEqual(plan.operations[0]["operation_id"], "sample_reflectron_responses")
        self.assertTrue(plan.declared_outputs[0].endswith("response_axis.csv"))
        for invalid in (True, -1, float("nan"), float("inf"), self.grid["nx"] * self.grid["dx_mm"]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                plan_response_axis_sampling(self.artifact(), maximum_x_mm=invalid, **kwargs)

    def test_axis_lua_samples_explicit_standalone_inputs(self):
        from msplatform.backends.simion.resources import native_resource_path
        from msplatform.backends.simion.source import lua_value
        lua = Path("C:/Program Files/SIMION-2020/lua.exe")
        if not lua.is_file():
            self.skipTest("plain Lua unavailable")
        output = self.root / "axis.csv"
        spec = self.root / "axis.lua"
        spec.write_text("return " + lua_value(dict(responses=["one.pa", "two.pa"], output=str(output),
            maximum_x_mm=2, grid=dict(nx=3, ny=1, nz=1, dx_mm=1, dy_mm=1, dz_mm=1),
            symmetry="2dcylindrical")), encoding="utf-8")
        harness = self.root / "sample_test.lua"
        harness.write_text("""local n=0
simion={pas={close=function() end,open=function(_,path)
 n=n+1; assert(path==({'one.pa','two.pa'})[n]); local index=n
 return {refinable=false,potential_type='electric',symmetry='2dcylindrical',
 nx=3,ny=1,nz=1,dx_mm=1,dy_mm=1,dz_mm=1,
 potential=function(_,x) return index*10+x end}
end}}
arg={""" + lua_value(str(spec)) + """}
dofile(""" + lua_value(str(native_resource_path("export_axis_basis.lua"))) + ")\n",
            encoding="utf-8")
        result = subprocess.run([str(lua), str(harness)], capture_output=True, text=True, timeout=30, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("AXIS_BASIS_EXPORT=PASS", result.stdout)
        self.assertEqual(output.read_text(encoding="utf-8").splitlines(),
            ["x_mm,basis_1_V,basis_2_V", "0,10,20", "1,11,21", "2,12,22"])

    def test_wrong_frame_or_basis_identity_and_tamper_fail(self):
        with self.assertRaisesRegex(ValueError, "frame"):
            compile_response_fit(self.artifact(), expected_model=self.model,
                expected_downstream_identity=self.spatial, expected_grid=self.grid,
                expected_frame_id="wrong", regularization=0.0001)
        with self.assertRaisesRegex(ValueError, "grid differs from the selected model"):
            compile_response_fit(self.artifact(), expected_model=self.model,
                expected_downstream_identity=self.spatial, expected_grid={**self.grid, "nx": self.grid["nx"] + 1},
                expected_frame_id="oatof_global", regularization=0.0001)
        for key in ("model_identity_sha256", "downstream_identity", "grid"):
            original = copy.deepcopy(self.metadata)
            self.metadata["reflectron_response_basis"][key] = "wrong"
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.compile()
            self.metadata = original
        self.metadata["reflectron_response_basis"]["responses"][0]["response_id"] = 2
        with self.assertRaisesRegex(ValueError, "IDs, order"):
            self.compile()

    def test_actual_response_bytes_are_rechecked(self):
        self.paths["response_1"].write_bytes(b"tampered")
        with self.assertRaises(AssertionError):
            self.compile()

    def test_endpoint_voltages_follow_the_explicit_study_drive(self):
        document = self.model.document
        tof_id = document["geometry"]["frontend_geometry"]["tof_instance_id"]
        drive = copy.deepcopy(document["drive"])
        drive["groups"][tof_id]["reflectron_midgrid"]["voltage_v"] = 1400.0
        drive["groups"][tof_id]["reflectron_backplate"]["voltage_v"] = 2400.0
        for stage, first, last in ((1, 0.0, 1400.0), (2, 1400.0, 2400.0)):
            count = document["components_resolved"][tof_id]["rings"][f"stage{stage}_count"]
            for index in range(1, count + 1):
                drive["groups"][tof_id][f"reflectron_stage{stage}_ring_{index}"]["voltage_v"] = (
                    first + (last - first) * index / (count + 1))
        self.model = compile_prepared_model(model_geometry(self.model), document["components_resolved"],
                                            drive=drive, physics=document["physics"])
        model_path = self.paths["compiled_model"]
        model_path.write_text(json.dumps(self.model.document), encoding="utf-8")
        self.records["compiled_model"] = file_record(model_path, "required_evidence")
        identity = self.model.document["model_identity_sha256"]
        self.metadata["model_identity_sha256"] = identity
        self.metadata["reflectron_response_basis"]["model_identity_sha256"] = identity
        result = self.compile()
        self.assertEqual(result["fit_parameters"]["midgrid_voltage_v"], 1400.0)
        self.assertEqual(result["fit_parameters"]["backplate_voltage_v"], 2400.0)

    def test_nonlinear_authored_ring_baseline_is_not_relabelled_linear(self):
        document = self.model.document
        tof_id = document["geometry"]["frontend_geometry"]["tof_instance_id"]
        drive = copy.deepcopy(document["drive"])
        drive["groups"][tof_id]["reflectron_stage1_ring_1"]["voltage_v"] += 1.0
        self.model = compile_prepared_model(model_geometry(self.model), document["components_resolved"],
                                            drive=drive, physics=document["physics"])
        model_path = self.paths["compiled_model"]
        model_path.write_text(json.dumps(self.model.document), encoding="utf-8")
        self.records["compiled_model"] = file_record(model_path, "required_evidence")
        identity = self.model.document["model_identity_sha256"]
        self.metadata["model_identity_sha256"] = identity
        self.metadata["reflectron_response_basis"]["model_identity_sha256"] = identity
        with self.assertRaisesRegex(ValueError, "linear-divider baseline"):
            self.compile()


if __name__ == "__main__":
    unittest.main()
