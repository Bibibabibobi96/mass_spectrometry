"""Independent stage plans and real manifest readers over explicitly inert files."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from msplatform.backends.simion import dual_cone_stages as stages
from msplatform.backends.simion.model import RF_PHYSICS
from msplatform.io.manifest_records import file_record
from common.contracts.test_dual_cone_transport_execution import request, ROOT


CLOCK = dict(
    clock_epoch_id="instrument_clock_epoch_v1",
    authority_sha256="6A035131B2BDBA6F7F20CBF6B6FD20EDAA5DCB3D7EC8EB7349F74F7AC35238A0",
    phase_reference_instrument_time_us=0,
)


def geometry():
    values = request()
    return stages.plan_geometry_stage(resolved=values["resolved"], numerics=values["numerics"])["projection"]


def model(*, amplitude=None, placement=None):
    electric = copy.deepcopy(request()["science"]["electric_field"])
    if amplitude is not None:
        electric["stage_1"]["rf_amplitude_v_zero_to_peak_per_group"] = amplitude
    return stages.plan_model_stage(geometry(), electric_field=electric, clock=CLOCK, physics=RF_PHYSICS,
                                   placement=placement)["projection"]


def record(root, name, text="INERT_NOT_NATIVE"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return file_record(path, "required_evidence")


def receipts(*names, unknown=False):
    return json.dumps(
        [
            dict(
                operation_id=name,
                observation=dict(
                    exit_confirmed=not unknown, returncode=0, process_id=123, process_started_at_utc_ticks=456
                ),
            )
            for name in names
        ]
    )


def clocks(root):
    result = {}
    for key, name in (
        ("clock_authority", "instrument_clock_authority_v1.json"),
        ("instrument_epoch", "instrument_epoch_v1.json"),
    ):
        path = root / name
        path.write_bytes((ROOT / "src/msplatform/examples" / name).read_bytes())
        result[key] = file_record(path, "required_evidence")
    return result


def publish(root, kind, data, metadata):
    manifest = root / "run_manifest.json"
    manifest.write_text(
        json.dumps(
            dict(
                schema_version=2,
                role="simulation_run_manifest",
                status="success",
                project="inert-dualcone",
                run_id=root.name,
                mode="explicit_inert_reader_fixture",
                inputs={},
                outputs=list(data.values()),
                products={
                    "product": dict(
                        schema_version=1,
                        kind=kind,
                        status="complete",
                        data=data,
                        metadata=dict(backend="simion", domain_id="dual_cone", **metadata),
                    )
                },
            )
        )
    )
    return dict(manifest=file_record(manifest, "required_evidence"), product_id="product")


def raw_data(root):
    return {
        name: record(root, filename)
        for name, filename in (
            ("raw_geometry", "dual_cone.pa#"),
            ("fractional_surface", "dual_cone.pa-surf"),
            ("surface_witnesses", "surface.csv"),
            ("workbench", "model.iob"),
            ("zero_particle_format_control", "model.fly2"),
        )
    }


def fields_fixture(root, *, unknown=False, missing=None, amplitude=None, placement=None):
    root.mkdir(parents=True, exist_ok=True)
    doc = model(amplitude=amplitude, placement=placement)
    raw = raw_data(root)
    implementation = {name: record(root, name + ".inert") for name in ("simion", "refiner", "auditor")}
    authority = {name: raw[name] for name in ("raw_geometry", "fractional_surface", "surface_witnesses")}
    identity = stages.plan_fields_stage(
        doc, numerics=request()["numerics"], raw_records=authority, implementation_records=implementation
    )["spatial_identity"]
    data = dict(
        compiled_model=record(root, "model.json", json.dumps(doc)),
        family_raw=raw["raw_geometry"],
        family_surface=raw["fractional_surface"],
        family_carrier=record(root, "dual_cone.pa0"),
        surface_witnesses=raw["surface_witnesses"],
        field_native_receipts=record(root, "refine.json", receipts("refine_fields", unknown=unknown)),
        field_audit_receipts=record(root, "audit-process.json", receipts("audit_fields")),
        field_audit=record(root, "audit.json", json.dumps(dict(status="success", checked_domains=["dual_cone"]))),
        **clocks(root),
    )
    for eid in stages.ELECTRODE_IDS:
        data["response_" + str(eid)] = record(root, "dual_cone.pa" + str(eid))
    if missing is not None:
        data.pop(missing)
    metadata = dict(
        field_status="available",
        source_status="not_requested",
        field_representation="producer_owned_dual_cone_fractional_family",
        spatial_identity=identity,
    )
    return publish(root, "field_bundle", data, metadata), identity


class IndependentStageTests(unittest.TestCase):
    def test_geometry_and_model_need_no_gas_sds_source_or_trajectory(self):
        values = request()
        numerics = {name: values["numerics"][name] for name in ("schema_version", "role", "pa", "workbench")}
        numerics["pa"].pop("refine_policy")
        from unittest.mock import patch

        with (
            patch.object(Path, "mkdir", side_effect=AssertionError("pure stage attempted directory creation")),
            patch("subprocess.Popen", side_effect=AssertionError("pure stage attempted process launch")),
            patch(
                "msplatform.ion_release.release.generate_release_states",
                side_effect=AssertionError("source-free stage sampled particles"),
            ),
        ):
            result = stages.plan_geometry_stage(resolved=values["resolved"], numerics=numerics)
            stages.plan_model_stage(
                result["projection"],
                electric_field=values["science"]["electric_field"],
                clock=CLOCK,
                physics=RF_PHYSICS,
            )
        self.assertEqual(result["sampled_particles"], 0)
        self.assertEqual(result["fly_calls"], 0)
        self.assertEqual(result["refine_calls"], 0)
        prepared = stages.plan_model_stage(
            result["projection"], electric_field=values["science"]["electric_field"], clock=CLOCK, physics=RF_PHYSICS
        )
        self.assertEqual(prepared["sampled_particles"], 0)
        self.assertEqual(prepared["canonical_iob_role"], "implemented_pending_native_validation")
        self.assertNotIn("gas", json.dumps(prepared["projection"]))
        self.assertNotIn("source_spec", json.dumps(prepared["projection"]))

    def test_drive_changes_model_but_not_the_spatial_basis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = {name: record(root, name) for name in ("raw_geometry", "fractional_surface", "surface_witnesses")}
            resources = {name: record(root, name) for name in ("simion", "refiner", "auditor")}
            original = model()
            changed = model(amplitude=123)
            self.assertNotEqual(original["identity_sha256"], changed["identity_sha256"])
            first = stages.plan_fields_stage(
                original, numerics=request()["numerics"], raw_records=raw, implementation_records=resources
            )
            numerics = request()["numerics"]
            numerics["trajectory"]["sample_interval_us"] = 7
            second = stages.plan_fields_stage(
                changed, numerics=numerics, raw_records=raw, implementation_records=resources
            )
            self.assertEqual(first["spatial_identity"], second["spatial_identity"])
            numerics["pa"]["refine_policy"] = "explicit_convergence"
            numerics["pa"]["convergence_v"] = 0.0001
            refined = stages.plan_fields_stage(
                changed, numerics=numerics, raw_records=raw, implementation_records=resources
            )
            self.assertNotEqual(first["spatial_identity"], refined["spatial_identity"])

    def test_source_free_products_require_actual_native_closure(self):
        for kind in ("geometry_artifact", "prepared_model"):
            for missing in (None, "fractional_surface", "zero_particle_format_control", "native_stage_receipts"):
                with self.subTest(kind=kind, missing=missing), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    data = raw_data(root)
                    if kind == "geometry_artifact":
                        data["compiled_geometry"] = record(root, "geometry.json", json.dumps(geometry()))
                        data["native_stage_receipts"] = record(
                            root,
                            "native.json",
                            receipts("build_geometry", "build_geometry_model", "verify_geometry_model"),
                        )
                        validator = stages.require_geometry_product
                    else:
                        data["compiled_model"] = record(root, "model.json", json.dumps(model()))
                        data["native_stage_receipts"] = record(
                            root, "native.json", receipts("materialize_geometry", "build_model", "verify_model")
                        )
                        data.update(clocks(root))
                        for name in ("model_configuration", "model_readback"):
                            data[name] = record(root, name)
                        validator = stages.require_model_product
                    if missing is not None:
                        data.pop(missing)
                    reference = publish(
                        root,
                        kind,
                        data,
                        dict(sampled_particles=0, field_status="not_solved", source_status="not_requested"),
                    )
                    if missing is None:
                        self.assertEqual(validator(reference).kind, kind)
                    else:
                        with self.assertRaisesRegex(ValueError, "closure is missing|no declared data member"):
                            validator(reference)

    def test_saved_basis_reuse_is_explicit_and_never_schedules_refine(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference, identity = fields_fixture(root / "producer")
            product, producer = stages.require_fields_product(reference, expected_spatial_identity=identity)
            self.assertEqual(product.reference, producer.reference)
            authority = {
                name: record(root, name) for name in ("raw_geometry", "fractional_surface", "surface_witnesses")
            }
            resources = {name: record(root, name) for name in ("simion", "refiner", "auditor")}
            graph = stages.plan_fields_stage(
                model(amplitude=123),
                numerics=request()["numerics"],
                raw_records=authority,
                implementation_records=resources,
                reuse_reference=reference,
            )
            self.assertEqual(graph["expected_operation_ids"], ["audit_fields"])
            self.assertNotIn("refine_fields", graph["expected_operation_ids"])
            self.assertEqual(graph["native_status"], "not_executed")

    def test_missing_response_unknown_writer_and_changed_operator_fail(self):
        for scenario in ("missing", "unknown_writer", "changed_operator"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                reference, identity = fields_fixture(
                    Path(directory),
                    unknown=scenario == "unknown_writer",
                    missing="response_22" if scenario == "missing" else None,
                )
                if scenario == "changed_operator":
                    identity = dict(identity, identity_sha256="0" * 64)
                with self.assertRaises(ValueError):
                    stages.require_fields_product(reference, expected_spatial_identity=identity)

    def test_saved_field_fly_requires_explicit_gas_source_sds_and_collision_inputs(self):
        from projects.dual_cone_tandem_quadrupole_ion_interface.tests.test_gas_flow_contract import _write_fixture
        from common.contracts.test_dual_cone_transport_execution import CONFIG
        from msplatform.backends.simion.dual_cone_transport import SDS_FILES

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference, _ = fields_fixture(root / "field")
            gas = root / "gas"
            gas.mkdir()
            csv_path, metadata = _write_fixture(gas)
            inputs = {}
            for key, name in (
                ("gas_flow_science", "gas_flow_science.json"),
                ("comsol_solver_numerics", "comsol_solver_numerics.json"),
                ("resolved_geometry", "resolved_geometry.json"),
            ):
                path = gas / name
                path.write_bytes((CONFIG / name).read_bytes())
                inputs[key] = file_record(path, "required_evidence")
            manifest = gas / "run_manifest.json"
            manifest.write_text(
                json.dumps(
                    dict(
                        schema_version=2,
                        role="simulation_run_manifest",
                        status="success",
                        project="dual_cone_tandem_quadrupole_ion_interface",
                        mode="axisymmetric_gas_flow_screening",
                        run_id="inert",
                        inputs=inputs,
                        outputs=[
                            file_record(csv_path, "required_evidence"),
                            file_record(metadata, "required_evidence"),
                        ],
                    )
                )
            )
            gas_reference = dict(manifest=file_record(manifest, "required_evidence"), product_id="gas_field")
            values = request()
            sds = {name: record(root, name) for name in SDS_FILES}
            kwargs = dict(
                fields_reference=reference,
                gas_field_reference=gas_reference,
                source_spec=values["source_spec"],
                numerics=values["numerics"],
                collision_science=values["science"]["gas"],
                collision_sds_records=sds,
            )
            graph = stages.plan_saved_field_fly(**kwargs)
            self.assertEqual(graph["expected_operation_ids"], ["build_tracking_model", "verify_tracking_model", "fly"])
            self.assertEqual(graph["refine_calls"], 0)
            self.assertEqual(graph["geometry_build_calls"], 0)
            self.assertEqual(graph["collision"]["collision_gas_mass_amu"], 28.0134)
            self.assertEqual(graph["protection_status"], "owner_acquisition_required")
            self.assertEqual(graph["source_count"], 100)
            with self.assertRaisesRegex(ValueError, "five-file"):
                stages.plan_saved_field_fly(**dict(kwargs, collision_sds_records={}))
            with self.assertRaisesRegex(ValueError, "positive"):
                stages.plan_saved_field_fly(
                    **dict(kwargs, collision_science=dict(values["science"]["gas"], collision_gas_mass_amu=0))
                )
            recorded = json.loads(metadata.read_text())
            recorded["solution_summary"]["mass_balance_relative_error"] = 1.0
            metadata.write_text(json.dumps(recorded))
            producer = json.loads(manifest.read_text())
            producer["outputs"][1] = file_record(metadata, "required_evidence")
            manifest.write_text(json.dumps(producer))
            limited_reference = dict(manifest=file_record(manifest, "required_evidence"), product_id="gas_field")
            from msplatform.results.gas_field import read_gas_field

            self.assertEqual(read_gas_field(limited_reference).data.row_count, 100)
            with self.assertRaisesRegex(ValueError, "mass-balance contract"):
                stages.plan_saved_field_fly(**dict(kwargs, gas_field_reference=limited_reference))


class StageOwnerGraphTests(unittest.TestCase):
    def test_actual_plans_use_real_owner_dependencies_and_reject_undeclared_fallback(self):
        import os
        import sys
        from dataclasses import replace
        from unittest.mock import patch
        from common.contracts.test_execution_runtime import NormalOwnerTests
        from msplatform.execution.owner import run_managed_stage
        from msplatform.execution.completion import no_particle_batch_completion_api

        for name in ("geometry", "model", "fields", "reuse"):
            with self.subTest(stage=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                helper = NormalOwnerTests()
                policy = root / "capacity.json"
                policy.write_text(json.dumps(helper._policy()))
                context = replace(helper._context(root), capacity_policy_path=policy)
                if name == "geometry":
                    values = request()
                    graph = stages.plan_geometry_stage(resolved=values["resolved"], numerics=values["numerics"])
                elif name == "model":
                    graph = stages.plan_model_stage(
                        geometry(),
                        electric_field=request()["science"]["electric_field"],
                        clock=CLOCK,
                        physics=RF_PHYSICS,
                    )
                else:
                    reference, _ = fields_fixture(root / "producer")
                    raw = {
                        key: record(root, key) for key in ("raw_geometry", "fractional_surface", "surface_witnesses")
                    }
                    implementation = {key: record(root, key) for key in ("simion", "refiner", "auditor")}
                    graph = stages.plan_fields_stage(
                        model(),
                        numerics=request()["numerics"],
                        raw_records=raw,
                        implementation_records=implementation,
                        reuse_reference=reference if name == "reuse" else None,
                    )
                calls = []

                def observed(_context, **kwargs):
                    calls.append(kwargs)
                    for key in ("stdout_path", "stderr_path", "usage_path"):
                        kwargs[key].write_text("INERT_OWNER_GRAPH_NO_NATIVE_RESULT")
                    return dict(
                        observation=dict(
                            exit_code=0, root_process_id=os.getpid(), root_process_started_at_utc_ticks=12345
                        ),
                        host_release=dict(
                            inherited=False, token="inert", error=None, result=dict(status="released", token="inert")
                        ),
                    )

                def action(session):
                    # The owner itself rejects omitted dependencies and forbidden
                    # fallback names before the mocked process transport runs.
                    forbidden = "refine_fields" if name == "reuse" else "hidden_automatic_fly"
                    with self.assertRaisesRegex(ValueError, "undeclared"):
                        session.run_process(
                            forbidden,
                            executable=Path(sys.executable),
                            arguments=["-V"],
                            role="GATE",
                            stage="software_tests",
                            limits=None,
                        )
                    if len(graph["expected_operation_ids"]) > 1:
                        with self.assertRaisesRegex(ValueError, "prerequisites"):
                            session.run_process(
                                graph["expected_operation_ids"][-1],
                                executable=Path(sys.executable),
                                arguments=["-V"],
                                role="GATE",
                                stage="software_tests",
                                limits=None,
                            )
                    for operation in graph["expected_operation_ids"]:
                        session.run_process(
                            operation,
                            executable=Path(sys.executable),
                            arguments=["-V"],
                            role="GATE",
                            stage="software_tests",
                            limits=None,
                        )
                    output = session.declare_file(session.result_dir / "graph.json", "required_evidence")
                    output.write_text(json.dumps(graph))
                    return dict(
                        status="success",
                        summary={"native_status": "not_executed"},
                        output_paths=[output],
                        required_output_paths=[output],
                        retention_preserve_paths=[],
                        manifest_extra_fields={},
                    )

                arguments = helper._arguments(root, action)
                arguments.update(
                    expected_operation_ids=graph["expected_operation_ids"],
                    operation_dependencies=graph["operation_dependencies"],
                    action_record=file_record(Path(__file__), "required_evidence"),
                    completion_api=no_particle_batch_completion_api,
                )
                with patch("msplatform.execution.run_session.run_observed_process", side_effect=observed):
                    result = run_managed_stage(context, **arguments)
                self.assertEqual(result["status"], "success")
                self.assertEqual(len(calls), len(graph["expected_operation_ids"]))


class ExistingModelConsumerTests(unittest.TestCase):
    def test_dual_cone_projection_uses_actual_existing_source_free_lua_consumer(self):
        import shutil
        import subprocess
        from msplatform.backends.simion.resources import native_resource_path

        lua = Path(shutil.which("lua") or shutil.which("lua5.1") or "C:/Program Files/SIMION-2020/lua.exe")
        if not lua.is_file():
            self.skipTest("plain Lua unavailable; no native fallback")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            projection = model()
            configuration = root / "drive.lua"
            configuration.write_text(stages.render_model_stage_configuration(projection))
            script = root / "consumer.lua"
            script.write_text(
                """local pure=setmetatable({},{__index=function(_,name)
 assert(name~='simion' and name~='segment','source-free consumer used native state')
 return _G[name]
end})
local function load_pure(path)
 local chunk=assert(loadfile(path));setfenv(chunk,pure);return chunk()
end
local config=load_pure(%s)
local consumer=load_pure(%s).new(config,load_pure(%s),{}, {})
local zero=consumer.evaluate_at(0)
assert(#zero==7,'actual seven-electrode drive missing')
for i=1,7 do assert(zero[i].voltage_v==0) end
local quarter=consumer.evaluate_at(1e6/570000/4)
assert(quarter[4].native_targets[1].electrode_id==11 and quarter[4].voltage_v==300)
assert(quarter[5].native_targets[1].electrode_id==12 and quarter[5].voltage_v==-300)
assert(quarter[6].native_targets[1].electrode_id==21 and quarter[6].voltage_v==300)
assert(quarter[7].native_targets[1].electrode_id==22 and quarter[7].voltage_v==-300)
assert(consumer.describe().model_identity_sha256==%s)
print('DUAL_CONE_EXISTING_MODEL_CONSUMER=PASS SOURCE=False FIELD=False')
"""
                % (
                    json.dumps(str(configuration)),
                    json.dumps(str(native_resource_path("model_drive.lua"))),
                    json.dumps(str(native_resource_path("rf_drive.lua"))),
                    json.dumps(projection["identity_sha256"]),
                )
            )
            result = subprocess.run([str(lua), str(script)], cwd=root, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("SOURCE=False FIELD=False", result.stdout)


class NamedTargetPlanningTests(unittest.TestCase):
    def test_explicit_saved_products_preserve_world_placement_and_frame(self):
        """Real product readers over inert files; no solver or owner is invoked."""
        from unittest.mock import patch
        from common.contracts.test_dual_cone_placement import pose
        from common.contracts.test_simion_rf_prepared_model import clock_reference
        from msplatform.workflows.dual_cone_stages import plan_to, run_to

        values = request()
        default = stages.device_placement(values["resolved"], values["numerics"]).to_contract()
        placed = pose(values).to_contract()
        shifted = copy.deepcopy(placed)
        shifted["translation_mm"][0] += 1
        other_frame = copy.deepcopy(placed)
        other_frame["to_frame_id"] = "different_laboratory_mm"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            products = {}
            for name, placement in (("legacy", None), ("default", default), ("placed", placed),
                                    ("shifted", shifted), ("frame", other_frame)):
                geometry_root = root / name / "geometry"
                data = raw_data(geometry_root)
                data["compiled_geometry"] = record(geometry_root, "geometry.json", json.dumps(geometry()))
                data["native_stage_receipts"] = record(geometry_root, "native.json", receipts(
                    "build_geometry", "build_geometry_model", "verify_geometry_model"))
                metadata = dict(sampled_particles=0, field_status="not_solved", source_status="not_requested")
                if placement is not None:
                    metadata["placement"] = placement
                    data["placement"] = record(geometry_root, "placement.json", json.dumps(placement))
                geometry_reference = publish(geometry_root, "geometry_artifact", data, metadata)
                model_root = root / name / "model"
                data = raw_data(model_root)
                data["compiled_model"] = record(model_root, "model.json", json.dumps(model(placement=placement)))
                data["native_stage_receipts"] = record(model_root, "native.json", receipts(
                    "materialize_geometry", "build_model", "verify_model"))
                data.update(clocks(model_root))
                for key in ("model_configuration", "model_readback"):
                    data[key] = record(model_root, key)
                model_reference = publish(model_root, "prepared_model", data, dict(
                    sampled_particles=0, field_status="not_solved", source_status="not_requested"))
                fields, _identity = fields_fixture(root / name / "fields", placement=placement)
                products[name] = dict(geometry=geometry_reference, model=model_reference, fields=fields)
            with patch("msplatform.workflows.dual_cone_stages.run_managed_stage") as owner:
                for name in ("legacy", "default", "placed"):
                    with self.subTest(matching=name):
                        plan = plan_to(target="fields", available=products[name])
                        self.assertEqual(plan["stages"], [])
                        self.assertEqual(run_to(plan).reference, products[name]["fields"])
                matching = dict(products["legacy"], geometry=products["default"]["geometry"])
                self.assertEqual(plan_to(target="fields", available=matching)["stages"], [])
                for name in ("shifted", "frame", "legacy"):
                    for left, right in (("geometry", "fields"), ("geometry", "model"), ("model", "fields")):
                        with self.subTest(conflict=name, stages=(left, right)):
                            target = "fields" if right == "fields" else "model"
                            with self.assertRaisesRegex(ValueError, "conflicting world placement or frame"):
                                plan_to(target=target, available={left: products["placed"][left],
                                                                 right: products[name][right]})
                selected = dict(resolved=values["resolved"], numerics=values["numerics"], placement=placed)
                self.assertEqual(plan_to(target="fields", request={"geometry": selected},
                                         available={"fields": products["placed"]["fields"]})["stages"], [])
                with self.assertRaisesRegex(ValueError, "placement.*model request"):
                    plan_to(target="fields", request={"geometry": selected},
                            available={"fields": products["shifted"]["fields"]})
                explicit_default = dict(resolved=values["resolved"], numerics=values["numerics"], placement=default)
                self.assertEqual(plan_to(target="geometry", request={"geometry": explicit_default},
                                         available={"geometry": products["legacy"]["geometry"]})["stages"], [])
                rebind = plan_to(target="fields", available={"fields": products["legacy"]["fields"]}, request={
                    "geometry": selected,
                    "model": dict(electric_field=values["science"]["electric_field"], clock=CLOCK,
                                  physics=RF_PHYSICS, placement=placed, clock_authority_reference=clock_reference()),
                    "fields": dict(numerics=values["numerics"])})
                self.assertEqual(rebind["stages"], ["geometry", "model", "fields"])
                for conflicting in (shifted, other_frame):
                    with self.subTest(request_conflict=conflicting):
                        with self.assertRaisesRegex(ValueError, "requests have conflicting world placement or frame"):
                            plan_to(target="model", request={
                                "geometry": selected,
                                "model": dict(electric_field=values["science"]["electric_field"], clock=CLOCK,
                                              physics=RF_PHYSICS, placement=conflicting,
                                              clock_authority_reference=clock_reference())})
                omitted_geometry_placement = dict(resolved=values["resolved"], numerics=values["numerics"])
                rebind_without_geometry_placement = plan_to(target="model", request={
                    "geometry": omitted_geometry_placement,
                    "model": dict(electric_field=values["science"]["electric_field"], clock=CLOCK,
                                  physics=RF_PHYSICS, placement=placed, clock_authority_reference=clock_reference())})
                self.assertEqual(rebind_without_geometry_placement["stages"], ["geometry", "model"])
                owner.assert_not_called()

    def test_geometry_target_has_no_context_source_or_model_dependency_and_binds_request(self):
        from unittest.mock import patch
        from msplatform.workflows.dual_cone_stages import plan_to, run_to
        values = request()
        numerics = {key: values["numerics"][key] for key in ("schema_version", "role", "pa", "workbench")}
        selected = dict(geometry=dict(resolved=values["resolved"], numerics=numerics))
        with patch("msplatform.workflows.dual_cone_stages.run_managed_stage") as owner:
            plan = plan_to(target="geometry", request=selected)
            self.assertEqual(plan["stages"], ["geometry"])
            self.assertEqual(plan["request_authorities"], [])
            self.assertEqual(plan["available"], {})
            with self.assertRaisesRegex(ValueError, "execution context"):
                run_to(plan)
            changed = copy.deepcopy(plan)
            changed["request"]["geometry"]["resolved"]["role"] = "CHANGED"
            with self.assertRaisesRegex(ValueError, "modified"):
                run_to(changed)
            for target in ("model", "fields", "trajectory"):
                with self.subTest(target=target), self.assertRaisesRegex(ValueError, "model request"):
                    plan_to(target=target, request=selected)
            for invalid in ([], "geometry"):
                with self.assertRaises(ValueError):
                    plan_to(target="geometry", request=invalid)
            owner.assert_not_called()

    def test_explicit_missing_or_conflicting_product_is_never_repaired(self):
        from unittest.mock import patch
        from msplatform.workflows.dual_cone_stages import plan_to
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fields, _identity = fields_fixture(root / "fields")
            with patch("msplatform.workflows.dual_cone_stages.run_managed_stage") as owner:
                plan = plan_to(target="fields", available={"fields": fields})
                self.assertEqual(plan["stages"], [])
                values = request()
                changed = copy.deepcopy(values["numerics"])
                changed["pa"]["grid_points_xyz"]["x"] += 2
                with self.assertRaisesRegex(ValueError, "conflicting geometry"):
                    plan_to(target="fields", request={"geometry": dict(resolved=values["resolved"], numerics=changed)},
                            available={"fields": fields})
                altered = copy.deepcopy(fields)
                altered["manifest"]["path"] = str(root / "missing.json")
                with self.assertRaises((ValueError, AssertionError)):
                    plan_to(target="fields", available={"fields": altered})
                owner.assert_not_called()

    def test_complete_trajectory_selection_requires_actual_terminal_data_not_upstream_files(self):
        from msplatform.workflows.dual_cone_stages import plan_to, run_to
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = {name: record(root, name + ".txt")
                    for name in ("final_state", "metrics", "preparation_receipt", "source_csv")}
            metadata = dict(model="dual_cone_sds_gas_assisted_transport")
            reference = publish(root, "trajectory_result", data, metadata)
            plan = plan_to(target="trajectory", available={"trajectory": reference})
            self.assertEqual(plan["stages"], [])
            self.assertEqual(run_to(plan).reference, reference)
            data.pop("final_state")
            reference = publish(root, "trajectory_result", data, metadata)
            with self.assertRaises((KeyError, ValueError)):
                plan_to(target="trajectory", available={"trajectory": reference})

    def test_saved_fields_do_not_ignore_explicit_geometry_world_placement(self):
        from msplatform.workflows.dual_cone_stages import plan_to
        from common.contracts.test_dual_cone_placement import pose
        values = request()
        with tempfile.TemporaryDirectory() as directory:
            fields, _identity = fields_fixture(Path(directory) / "fields")
            matching = stages.device_placement(values["resolved"], values["numerics"]).to_contract()
            same = plan_to(target="fields", available={"fields": fields}, request={"geometry": dict(
                resolved=values["resolved"], numerics=values["numerics"], placement=matching)})
            self.assertEqual(same["stages"], [])
            with self.assertRaisesRegex(ValueError, "placement.*model request"):
                plan_to(target="fields", available={"fields": fields}, request={"geometry": dict(
                    resolved=values["resolved"], numerics=values["numerics"], placement=pose(values))})
