"""Public scalar bridge contracts; all native operations are inert."""
import base64
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from msplatform import assembly, components
from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.recipes import load_recipe
from msplatform.workflows.scalar_tracing import compile_scalar_inputs
from tests.contracts import test_split_scalar_binding as split_fixture


class ScalarWorkflowTests(unittest.TestCase):
    def setUp(self):
        base = split_fixture.SplitScalarBindingTests()
        base.setUp()
        self.addCleanup(base.doCleanups)
        self.helper, self.model = base.helper, base.model
        examples = Path(__file__).resolve().parents[2] / "src/msplatform/examples"
        self.recipe = load_recipe(examples / "oa_split_tof_comsol_small_v1.toml").to_dict()
        simion = load_recipe(examples / "oa_split_tof_native_small_v1.toml").to_dict()
        self.recipe["particle_tracer"] = "simion"
        self.recipe["field_assembly_strategy"] = "sampled_joint_field"
        self.recipe["study"]["document"]["numerics"]["tracing"] = simion["study"]["document"]["numerics"]["tracing"]
        study = self.recipe["study"]["document"]
        parts = {name: components.resolve_component(value) for name,value in study["component_requests"].items()}
        self.instrument = assembly.assemble(study["recipe"], parts)
        snapshot = {"composition_plan": self.instrument.composition_plan,
                    "components_resolved": self.instrument.components_resolved,
                    "components_source": self.instrument.components_source}
        self.projection = project_assembly_geometry(snapshot, outer_box_mm=study["numerics"]["geometry"]["outer_box_mm"])
        def frozen(product):
            raw = ("manifest-" + product).encode()
            digest = hashlib.sha256(raw).hexdigest().upper()
            reference = {"manifest":{"path":str(self.helper.root/(product+".json")),"bytes":len(raw),"sha256":digest},"product_id":product}
            return {"reference":reference,"snapshot":{"sha256":digest,"bytes_base64":base64.b64encode(raw).decode()}}
        self.recipe["field_source"] = {"kind":"comsol_native", "reference":frozen("background"),
            "collision_reference":frozen("fields"), "sampling":{"world":{"frame_id":"oatof_global",
            "origin_mm":[-400,-400,-100],"pitch_mm":[100,100,102],"dimensions":[9,9,11],"block_points":128},"windows":[]}}
        model_path = self.helper.root / "collision-model.json"
        model_path.write_text(json.dumps(self.model.document), encoding="utf-8")
        record = {"path":str(model_path),"bytes":model_path.stat().st_size,"sha256":"0"*64}
        self.artifacts = {
            "background":SimpleNamespace(reference=self.recipe["field_source"]["reference"]["reference"],metadata={"backend":"comsol","scope":"co_resident_stationary_workpoint","co_resident_workpoint":"background"},data_records={"prepared_manifest":record},data_path=lambda key:model_path),
            "on":SimpleNamespace(reference={"manifest":self.recipe["field_source"]["reference"]["reference"]["manifest"],"product_id":"on"},metadata={"backend":"comsol","scope":"co_resident_stationary_workpoint","co_resident_workpoint":"on"}),
            "model":SimpleNamespace(metadata={"backend":"comsol","scope":"assembly_electrostatic_unsolved","native_reopen_verified":True},data_records={"geometry_manifest":record},data_path=lambda key:model_path),
            "geometry":SimpleNamespace(reference={"manifest":record,"product_id":"geometry"},metadata={"backend":"comsol","scope":"geometry_only","native_reopen_verified":True}),
            "fields":SimpleNamespace(reference=self.recipe["field_source"]["collision_reference"]["reference"],metadata={"backend":"simion","field_status":"available","source_status":"not_requested","model_identity_sha256":self.model.document["model_identity_sha256"],"clock":self.model.document["drive"]["clock"]},data_path=lambda key:model_path),
        }
        self.solutions = {"background":{"study_tag":"std1","solution_tag":"sol1","dataset_tag":"dset1"},
                          "on":{"study_tag":"std2","solution_tag":"sol2","dataset_tag":"dset2"}}
        rows = {"background":[],"on":[]}
        for instance,groups in study["drive"]["groups"].items():
            for group,item in groups.items():
                for name in rows:
                    value = item["voltage_v"] if item["kind"] == "static" else item["off_voltage_v" if name == "background" else "on_voltage_v"]
                    rows[name].append({"instance_id":instance,"electrode_group_id":group,"voltage_v":value})
        self.requests = {name:validate_request(self.projection,{"group_voltages":value,**study["numerics"]["fields"],"study":{"kind":"stationary"}}) for name,value in rows.items()}

    def compile(self):
        def read(obj, key):
            if key == "projection": return copy.deepcopy(self.projection)
            if key == "request": return copy.deepcopy(self.requests[next(name for name in ("background","on") if self.artifacts[name] is obj)])
            raise AssertionError(key)
        def opened(reference, *, expected_kind):
            return self.artifacts[reference["product_id"]]
        def solution(obj):
            return self.solutions[next(name for name in ("background","on") if self.artifacts[name] is obj)]
        with patch("msplatform.workflows.scalar_tracing.open_artifact",side_effect=opened), \
             patch("msplatform.workflows.scalar_tracing._read",side_effect=read), \
             patch("msplatform.backends.comsol.assembly_field_export._validate_field_solution_source",side_effect=solution):
            return compile_scalar_inputs(self.recipe)

    def test_explicit_authorities_and_full_world_grid(self):
        result = self.compile()
        self.assertEqual(result["grids"]["world"]["dimensions"], [9,9,11])
        self.assertNotEqual(result["solutions"]["off"]["solution_tag"], result["solutions"]["on"]["solution_tag"])
        self.assertEqual(result["instrument"].components_resolved, self.instrument.components_resolved)

    def test_rejects_missing_collision_and_uncovered_world_and_wrong_physics(self):
        before = copy.deepcopy(self.recipe)
        for mutation in (
            lambda r:r["field_source"].pop("collision_reference"),
            lambda r:r["field_source"]["sampling"]["world"]["origin_mm"].__setitem__(0,-399),
            lambda r:r["study"]["document"]["physics"].__setitem__("boundary_policy","native_zero_neumann"),
        ):
            self.recipe = copy.deepcopy(before)
            mutation(self.recipe)
            with self.assertRaises((ValueError,KeyError)):
                self.compile()
        self.recipe = before
        self.requests["on"]["group_voltages"][0]["voltage_v"] += 1
        with self.assertRaisesRegex(ValueError,"workpoint"):
            self.compile()

    def test_inert_owner_runs_existing_exports_and_keeps_field_cache_independent_of_species(self):
        from msplatform.workflows.scalar_tracing import run_scalar_stages
        from msplatform.backends.comsol import assembly_field_export
        from msplatform.backends import simion
        admitted = self.compile()
        captured = []
        calls = []
        exported_objects = []
        def artifact(name, manifest=None):
            record = {"path":str(self.helper.root / (name + ".json")),"sha256":hashlib.sha256((manifest or name).encode()).hexdigest().upper(),"bytes":1}
            return SimpleNamespace(reference={"manifest":record,"product_id":name},metadata={})
        def exported(solution, *, grids, context):
            calls.append(("export", solution.reference["product_id"], copy.deepcopy(grids)))
            products = {name:artifact("samples_"+name, "export-"+solution.reference["product_id"]) for name in grids}
            for product in products.values():
                product.reference["manifest"] = copy.deepcopy(products["world"].reference["manifest"])
            exported_objects.extend(products.values())
            return products
        def derive(raw, *, context):
            calls.append(("support",raw.reference["product_id"]))
            return artifact("support-"+raw.reference["manifest"]["sha256"][:8]+raw.reference["product_id"])
        def world(field, *, scalar_field_basis, context):
            calls.append(("world",field.reference,copy.deepcopy(scalar_field_basis)))
            result=artifact("world")
            result.metadata={"field_representation":"split_scalar_world_with_collision_geometry","field_source":"comsol_off_on_scalar_samples","collision_source_reference":field.reference}
            return result
        def track(field, particles, **kwargs):
            calls.append(("track",particles.rows,kwargs))
            return artifact("trajectory")
        def cache(name,key,kind,produce):
            captured.append((name,key))
            return produce(), {"asset_id":name,"task_key":key,"reused":False}
        def run(species):
            particle=SimpleNamespace(rows=[{"species_id":species}],to_dict=lambda:{"rows":[{"species_id":species}]})
            with patch("msplatform.workflows.scalar_tracing.compile_scalar_inputs",return_value=admitted), \
                 patch("msplatform.ion_release.sample_release",side_effect=lambda request:particle), \
                 patch("msplatform.workflows.scalar_tracing.open_artifact",side_effect=lambda ref,**kw: next(x for x in (admitted["background"],admitted["on"],admitted["prepared"],admitted["geometry"],admitted["collision"],*exported_objects) if x.reference == ref)), \
                 patch.object(assembly_field_export,"export_world_scalar_grids",side_effect=exported), \
                 patch.object(assembly_field_export,"derive_world_scalar_support",side_effect=derive), \
                 patch.object(simion,"prepare_split_scalar_world",side_effect=world), \
                 patch.object(simion,"track",side_effect=track):
                return run_scalar_stages(self.recipe,self.instrument,particle,context=object(),stage_cache=cache,
                    invoke=lambda call:call(),implementation={"comsol":{"source":"c"},"simion":{"source":"s"}},epoch_record={"sha256":"0"*64})
        # Prepared mock below carries a real owner reference, as the production path does.
        self.artifacts["model"].reference={"manifest":{"path":str(self.helper.root / "model.json"),"bytes":1,"sha256":"A"*64},"product_id":"model"}
        run("species-a")
        first=dict(captured)
        captured.clear(); calls.clear()
        changed=copy.deepcopy(self.recipe)
        self.recipe["label"]="a different label"
        run("species-b")
        second=dict(captured)
        self.recipe=changed
        for name in ("scalar_export_off","scalar_export_on","scalar_support_off_world","scalar_support_on_world","scalar_world"):
            self.assertEqual(first[name],second[name])
        self.assertNotEqual(first["scalar_trace"],second["scalar_trace"])
        self.assertEqual([row[0] for row in calls],["export","support","export","support","world","track"])
        self.assertEqual(calls[0][2]["world"]["solution_tag"],"sol1")
        self.assertEqual(calls[2][2]["world"]["solution_tag"],"sol2")
        self.assertEqual(calls[-1][2]["propagation"]["scope"],"continuous_assembly")
        self.assertEqual(calls[-1][2]["scalar_field_basis"],calls[-2][2])
        self.assertEqual(set(calls[-2][2]["samples"]),{"off","on"})
        self.assertEqual(calls[-2][2]["geometry_artifact"],admitted["geometry"].reference)
        calls.clear();captured.clear();exported_objects.clear()
        admitted['windows']=[{'name':'near','active_box_mm':{'min':[0,0,0],'max':[1,1,1]}},
                             {'name':'far','active_box_mm':{'min':[2,2,2],'max':[3,3,3]}}]
        admitted['grids']['near']=copy.deepcopy(admitted['grids']['world'])
        admitted['grids']['far']=copy.deepcopy(admitted['grids']['world'])
        run('species-a')
        world_selection=next(row[2] for row in calls if row[0]=='world')
        track_selection=next(row[2]['scalar_field_basis'] for row in calls if row[0]=='track')
        self.assertEqual(track_selection,world_selection)
        self.assertEqual([row['name'] for row in track_selection['refinement_windows']],['near','far'])
        for row in track_selection['refinement_windows']:
            self.assertEqual(set(row['samples']),{'off','on'})

    def test_birth_must_match_frozen_source_and_mass_scan_allocated_ids(self):
        from msplatform.workflows.scalar_tracing import run_scalar_stages
        from msplatform.ion_release import sample_release
        from msplatform.workflows.mass_scan import prepare_mass_scan
        admitted = self.compile()
        release = self.recipe["study"]["document"]["release"]
        original = sample_release(release)
        bad = copy.deepcopy(original.to_dict())
        bad["rows"][0]["position_x_mm"] += 1.
        fake = SimpleNamespace(rows=bad["rows"], to_dict=lambda:bad)
        with patch("msplatform.workflows.scalar_tracing.compile_scalar_inputs", return_value=admitted):
            with self.assertRaisesRegex(ValueError, "births differ"):
                run_scalar_stages(self.recipe,self.instrument,fake,context=object(),
                    stage_cache=lambda *args: self.fail("no owner on invalid source"), invoke=lambda fn:fn(),
                    implementation={"comsol":{},"simion":{}},epoch_record={"sha256":"0"*64})
        release = copy.deepcopy(release)
        release.pop("particle_ids", None)
        second = copy.deepcopy(release)
        second["species_id"] = "second-species"
        scan = {"schema_version":1,"role":"canonical_mass_scan_request","species_requests":[release,second]}
        self.recipe["study"]["document"]["release"] = scan
        second_birth = prepare_mass_scan(scan)[1]
        with patch("msplatform.workflows.scalar_tracing.compile_scalar_inputs", return_value=admitted):
            with self.assertRaisesRegex(RuntimeError,"ADMISSION_REACHED"):
                run_scalar_stages(self.recipe,self.instrument,second_birth,context=object(),
                    stage_cache=lambda *args: (_ for _ in ()).throw(RuntimeError("ADMISSION_REACHED")),
                    invoke=lambda fn:fn(),implementation={"comsol":{},"simion":{}},epoch_record={"sha256":"0"*64})
