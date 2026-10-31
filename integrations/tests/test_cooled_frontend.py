"""Artifact-free unified real-electrode geometry and mode regressions."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from integrations.workflows.cooled_frontend.geometry import compile_cooled_frontend, compile_field_plan
from integrations.workflows.cooled_frontend.prepare import compile_probe_plan, prepare_cooled_frontend
from integrations.workflows.cooled_frontend import prepare as cooled_prepare
from integrations.workflows.cooled_frontend import runtime as cooled_runtime
from integrations.workflows.cooled_frontend.runtime import fields
from integrations.workflows.cooled_frontend.program import build_program
from integrations.workflows.local_frontend import runtime as shared_runtime
from integrations.runtime.single_flight_frontend import compile_frontend
from integrations.runtime.build_single_flight_program import _standalone_dynamic_field_lua
from integrations.tests.frontend_fixtures import canonical_frontend_fixture, canonical_three_zone_frontend_fixture
from projects.dual_pressure_rectilinear_ion_processor.tests.test_cooled_buncher import buncher_fixture, native_pose
from projects.dual_pressure_rectilinear_ion_processor.analysis.cooled_buncher import build_cooled_buncher_contract
from integrations.tests.test_local_frontend_workflow import fixture, REPO
from common.contracts.rigid_transform import RigidTransform
from common.contracts import capacity_ledger
from common.simion import pa_family_cache
from common.contracts.write_run_manifest import file_record
from common.integration.resolve_assembly import compile_assembly_layout
from projects.dual_pressure_rectilinear_ion_processor.analysis.cooled_buncher import export_cooled_buncher_assembly_interface


def cooled_fixture(variant="three_zone"):
    model, guide, registration, request, ids = buncher_fixture()
    conditioner = build_cooled_buncher_contract(model, guide_contract=guide, native_to_assembly=native_pose(guide, registration), request=request, electrode_ids=ids)
    _, _, component = canonical_three_zone_frontend_fixture() if variant == "three_zone" else canonical_frontend_fixture()
    # The two-zone pose uses the mechanical exit origin; PA padding stays in its adapter.
    component["transform"] = dict(rotation=[[0,1,0],[1,0,0],[0,0,-1]], translation_mm=[0.,51.5,34.]) if variant == "three_zone" else dict(rotation=[[1,0,0],[0,1,0],[0,0,1]], translation_mm=[0.,51.5,0.])
    connection = dict(spatial_registration=registration)
    drive = dict(capture_voltages_v={k:0. for k in ids}, closed_voltages_v={k:1. for k in ids}, release_voltages_v={k:2. for k in ids}, entrance_close_us=20., release_start_us=100.)
    return guide, connection, component, conditioner, drive


def cooled_request_fixture(workspace,variant="three_zone"):
    path,request=fixture(workspace)
    request.update(schema_version=3)
    request.pop("composition_plan")
    model_path=workspace/request["source"]["resolved_model"]["path"]
    model=json.loads(model_path.read_text())
    model["numerics"]=json.loads((REPO/"projects/dual_pressure_rectilinear_ion_processor/config/numerics.json").read_text())
    model_path.write_text(json.dumps(model),encoding="utf-8")
    record=file_record(model_path)
    request["source"]["resolved_model"].update(bytes=record["bytes"],sha256=record["sha256"])
    manifest_path=workspace/request["source"]["producer_manifest"]["path"]
    manifest=json.loads(manifest_path.read_text());manifest["inputs"]["resolved_model"]=record
    manifest_path.write_text(json.dumps(manifest),encoding="utf-8")
    record=file_record(manifest_path)
    request["source"]["producer_manifest"].update(bytes=record["bytes"],sha256=record["sha256"])
    guide,connection,component,conditioner,drive=cooled_fixture(variant)
    request.update(role="instrument_assembly_cooled_frontend_request",accelerator_component=component,conditioner=dict(schema_version=1,role="ion_processor_hp_end_buncher_request",inner_center_inset_mm=5.,inner_length_mm=2.5),
        drive=drive,pressure_scale=0,field_source=None,common_pulse_decision=None,
        design_targets=dict(thermal_sigma_y_mm=.4,static_release_energy_gain_ev=5.),
        pulse=dict(policy_id="actual_field_reference_exit_centering_v1",target="oa_exit_geometric_center",reference_temperature_policy="provider_gas_temperature"))
    from projects.orthogonal_accelerator.analysis.assembly_interface import resolve_assembly_interface
    native = native_pose(guide, connection["spatial_registration"])
    oa = resolve_assembly_interface(component["requirements"], geometry_profile_id=component["geometry_profile_id"])
    oa_pose = RigidTransform(oa["local_frame_id"], "mrtof_global_cartesian", component.pop("transform")["rotation"],
                            [0., 51.5, 34.] if variant == "three_zone" else [0., 51.5, 0.]).to_contract()
    recipe = dict(schema_version=1, role="assembly_recipe", integration_id="instrument_assembly",
        recipe_id="cooled_oa", assembly_frame_id="mrtof_global_cartesian", position_tolerance_mm=1e-9, angular_tolerance_rad=1e-12,
        instances=[dict(instance_id="cooler", project_id="dual_pressure_rectilinear_ion_processor", transform=native),
                   dict(instance_id="accelerator", project_id="orthogonal_accelerator", transform=oa_pose)],
        connections=[dict(connection_id="cooler_oa", upstream=dict(instance_id="cooler", port_id="exit_gate_outer_face"),
                          downstream=dict(instance_id="accelerator", port_id="side_entry"), gap_mm=1., coupling_mode="monolithic_joint_solve")])
    parent = compile_assembly_layout(recipe, {
        "cooler": export_cooled_buncher_assembly_interface(conditioner, guide),
        "accelerator": oa,
    })
    parent_path = workspace / "parent_composition_plan.json"
    parent_path.write_text(json.dumps(parent, indent=2) + "\n", encoding="utf-8")
    request["composition_plan"] = file_record(parent_path)
    request["numerics"].pop("refine_policy")
    request["numerics"].update(cell_mm_xyz=dict(x=.2,y=.2,z=.2),refine_convergence_v=1e-5,extraction_sample_interval_us=.01,trajectory_sample_interval_us=5.,collision_seed=1001,hs1_steps_per_mfp=20)
    path.write_text(json.dumps(request),encoding="utf-8")
    return path,request


def _parent_path(request):
    return Path(request["composition_plan"]["path"])


def _replace_parent(request, parent):
    path = _parent_path(request)
    path.write_text(json.dumps(parent, indent=2) + "\n", encoding="utf-8")
    request["composition_plan"] = file_record(path)


def renamed_cooled_parent(request):
    """Rename the parent instances and preserve the same provider interfaces."""
    parent = json.loads(_parent_path(request).read_text())
    recipe = parent["recipe"]
    names = {recipe["connections"][0]["upstream"]["instance_id"]: "source_a",
             recipe["connections"][0]["downstream"]["instance_id"]: "oa_b"}
    for item in recipe["instances"]:
        item["instance_id"] = names[item["instance_id"]]
    recipe["instances"].reverse()
    for endpoint in ("upstream", "downstream"):
        route = recipe["connections"][0][endpoint]
        route["instance_id"] = names[route["instance_id"]]
    parent = compile_assembly_layout(recipe, {names[key]: value for key, value in parent["components"].items()})
    _replace_parent(request, parent)


def extend_parent(request, count):
    """Add isolated valid provider instances to exercise parent growth."""
    parent = json.loads(_parent_path(request).read_text())
    for index in range(3, count + 1):
        instance_id = f"future_oa_{index}"
        item = copy.deepcopy(next(item for item in parent["recipe"]["instances"]
                                  if item["instance_id"] == "accelerator"))
        item["instance_id"] = instance_id
        item["transform"]["translation_mm"][0] += 100 * index
        parent["recipe"]["instances"].append(item)
        parent["components"][instance_id] = copy.deepcopy(parent["components"]["accelerator"])
    parent = compile_assembly_layout(parent["recipe"], parent["components"])
    _replace_parent(request, parent)


def publish_inert_fields(run, cache_root):
    """Exercise the real public transaction using explicitly non-native bytes."""
    (run / "inputs/native_discovery.json").write_text(json.dumps(dict(
        bytes=1, sha256="A"*64, file_version="PURE_INERT_TEST")), encoding="utf-8")
    plan = cooled_runtime.field_cache_plan(run, cache_root=cache_root)
    progress = {}
    evidence = run / "inputs/inert_verification.txt"
    evidence.write_text("INERT_TRANSACTION_TEST_ONLY_NO_NATIVE_VERIFICATION\n", encoding="utf-8")
    for member in plan["domains"][0]["members"]:
        status = cooled_runtime.advance_field_cache(run, member)
        for name in status["missing_files"]:
            (Path(status["build_directory"]) / name).write_bytes(b"PURE_TEST_NOT_NATIVE_PA"*3)
        status = cooled_runtime.advance_field_cache(run, member)
        if status["action_required"] == "verify":
            status = cooled_runtime.advance_field_cache(run, member, evidence)
        status["refine_performed"] = False
        progress[member["member_id"]] = status
    return cooled_runtime.finalize_field_stage(run, plan, progress)



class CooledFrontendTests(unittest.TestCase):
    def test_two_zone_author_recipe_uses_mechanical_frame(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            author, request = cooled_request_fixture(root, "two_zone")
            plan = json.loads(_parent_path(request).read_text())
            accelerator = next(row for row in plan["recipe"]["instances"]
                               if row["instance_id"] == "accelerator")
            self.assertEqual(accelerator["transform"]["translation_mm"], [0., 51.5, 0.])
            result = prepare_cooled_frontend(author, root / "run", REPO, root,
                run_id="20261022_120000__build__python__cooled-fixture")
            region = result["frontend"]["accelerator_local_region"]
            self.assertEqual(region["planes"], dict(repeller=34., grid1=30., exit=0.))
            self.assertEqual(region["port"]["center_mm"], [0., 35., 32.])

    def test_two_zone_fixture_preserves_world_gate_and_exit_geometry(self):
        guide, connection, component, conditioner, _ = cooled_fixture("two_zone")
        self.assertEqual(component["transform"]["translation_mm"], [0., 51.5, 0.])
        _, frontend = compile_cooled_frontend(guide, connection, component, conditioner,
            cell_mm_xyz=dict(x=.2, y=.2, z=.2), exit_gap_mm=1.)
        region = frontend["accelerator_local_region"]
        self.assertEqual(region["planes"], dict(repeller=34., grid1=30., exit=0.))
        self.assertEqual(conditioner["geometry"]["exit_face_center_mr_mm"], [0., 33.5, 32.])
        self.assertEqual(region["port"]["center_mm"], [0., 35., 32.])
        self.assertEqual(region["port"]["flange_min_mm"] - 33.5, 1.)
        misplaced = copy.deepcopy(component)
        misplaced["transform"]["translation_mm"][2] = -6.
        with self.assertRaisesRegex(ValueError, "OA side aperture must follow and align"):
            compile_cooled_frontend(guide, connection, misplaced, conditioner,
                cell_mm_xyz=dict(x=.2, y=.2, z=.2), exit_gap_mm=1.)

    def test_saved_workbench_requires_public_pin_but_field_metadata_does_not(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            author, _ = cooled_request_fixture(root)
            artifacts = root/"artifacts"
            run = artifacts/"projects/instrument_assembly/runs/20261024_120000__test__python__cooled-pin"
            prepare_cooled_frontend(author, run, REPO, root, run_id=run.name)
            config = run/"run_config.json"
            config.write_text(json.dumps(dict(schema_version=2, run_id=run.name, project="instrument_assembly",
                capacity_ledger_lifecycle=dict(schema_version=1, enabled=True, artifact_root=str(artifacts),
                    light_evidence_budget_bytes=1))), encoding="utf-8")
            capacity_ledger.initialize_capacity_ledger(artifacts, objects=[])
            capacity_ledger.record_capacity_object(artifacts, path=run, object_class="rebuildable_payload",
                bytes_count=config.stat().st_size, status="writing", owner=str(run.resolve()),
                recovery_reason="inert fixture", recovery_task="fixture closes owner", review_deadline="2026-11-24",
                recovery_evidence_paths=(config,))
            cache_root = artifacts/"common/simion/pa_family_cache"
            # Explicitly model a previously published, unpinned generation.
            with patch.object(cooled_runtime, "_FIELD_PUBLICATION_PIN_REASON", None):
                published = publish_inert_fields(run, cache_root)
            bundle = cooled_runtime.field_cache_plan(run, cache_root=cache_root)
            plan = bundle["domains"][0]["members"][0]
            with patch.object(pa_family_cache, "_verify_payload_record", side_effect=AssertionError("no PA rehash")):
                actual = fields(run)
                hit = cooled_runtime.advance_field_cache(run, plan)
                self.assertEqual(hit["action_required"], "complete")
                transaction = cooled_runtime.load_pa_family_cache_transaction(cache_root, plan["cache_key"])
                self.assertIsNone(transaction["published_pin_reason"])
                ctx = dict(decision=dict(actual_pulse_time_us=110.), rows=[dict(particle_id=1)],
                    frontend=dict(frame_id="assembly"), fields=actual, experiment=dict(pressure_scale=1),
                    conditioner=dict(gas=dict(parameters=dict(hp_pressure_pa=1.,cross_section_m2=1e-18,mean_free_path_mm=-1),
                        domain_native_mm=dict(x_min=0.,x_max=10.,transverse_halfwidth=2.))))
                batch_plan = dict(schema_version=1,role="simion_single_wave_particle_batch_plan",particle_count=1,
                    batch_count=1,batches=[dict(index=1,count=1,particle_id_min=1,particle_id_max=1,simion_particle_id_offset=0)])
                with patch.object(cooled_runtime,"context",return_value=ctx), \
                        patch.object(shared_runtime,"_owner",return_value=run), \
                        patch.object(shared_runtime,"_phase",return_value={}), \
                        patch.object(shared_runtime,"_case",side_effect=lambda *a,**k:dict(iob_path=a[2]+".iob")) as materialize:
                    with self.assertRaisesRegex(pa_family_cache.PAFamilyCacheError,"publication pin binding"):
                        cooled_runtime.materialize_batches(run,"extraction",batch_plan,110.,[0.,110.])
                    materialize.assert_not_called()
                    pa_family_cache.advance_pa_family_cache_transaction(cache_root,plan["identity"],plan["filenames"],
                        owner=str(run.resolve()), published_pin_reason=cooled_runtime._FIELD_PUBLICATION_PIN_REASON,
                        published_pin_generation_sha256=published["working_points"][0]["generation_sha256"])
                    for member, row in zip(bundle["domains"][0]["members"][1:], published["working_points"][1:]):
                        pa_family_cache.advance_pa_family_cache_transaction(cache_root, member["identity"], member["filenames"],
                            owner=str(run.resolve()), published_pin_reason=cooled_runtime._FIELD_PUBLICATION_PIN_REASON,
                            published_pin_generation_sha256=row["generation_sha256"])
                    with patch.object(cooled_runtime,"validate_pa_family_cache_generation",
                            wraps=cooled_runtime.validate_pa_family_cache_generation) as validated:
                        result=cooled_runtime.materialize_batches(run,"extraction",batch_plan,110.,[0.,110.])
                    self.assertEqual(validated.call_count, 7)
                    self.assertTrue(all(call.kwargs == dict(verify_payload=False, require_publication_pin=True)
                                        for call in validated.call_args_list))
                    self.assertFalse(result["gui_fly_performed"])
            # A genuinely new public transaction publishes its durable pin as
            # part of the same lifecycle, without a later owner repair.
            new_plan = copy.deepcopy(plan)
            new_plan["identity"]["builder_identity"]["operating_builder"] = "B"*64
            new_plan["cache_key"] = pa_family_cache.canonical_pa_family_cache_key(new_plan["identity"])
            building = cooled_runtime.advance_field_cache(run, new_plan)
            for name in building["missing_files"]:
                (Path(building["build_directory"])/name).write_bytes(b"INERT_NEW_BUILDER_NOT_NATIVE"*3)
            cooled_runtime.advance_field_cache(run, new_plan)
            complete = cooled_runtime.advance_field_cache(run, new_plan, run/"inputs/inert_verification.txt")
            transaction = cooled_runtime.load_pa_family_cache_transaction(cache_root, new_plan["cache_key"])
            self.assertEqual(transaction["published_pin_reason"], cooled_runtime._FIELD_PUBLICATION_PIN_REASON)
            pa_family_cache.validate_pa_family_cache_generation(complete["generation_directory"],
                verify_payload=False, require_publication_pin=True)
            for path in root.rglob("*"):
                if path.is_file():
                    path.chmod(stat.S_IREAD|stat.S_IWRITE)

    def test_public_transaction_preserves_members_and_hit_without_materialization(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            try:
                author, _ = cooled_request_fixture(root)
                run = root/"artifacts/projects/instrument_assembly/runs/20261022_120000__build__python__cooled-fixture"
                prepare_cooled_frontend(author, run, REPO, root, run_id=run.name)
                (run/"inputs/native_discovery.json").write_text(json.dumps(dict(bytes=1,sha256="A"*64,file_version="INERT")))
                bundle = cooled_runtime.field_cache_plan(run, cache_root=root/"cache")
                plan = bundle["domains"][0]["members"][0]
                first = cooled_runtime.advance_field_cache(run, plan)
                retained = Path(first["build_directory"])/first["missing_files"][0]
                retained.write_bytes(b"INERT_RETAINED_MEMBER"*4)
                original = retained.read_bytes()
                next_run = run.with_name(run.name+"__r02")
                shutil.copytree(run/"inputs", next_run/"inputs")
                resumed = cooled_runtime.advance_field_cache(next_run, plan)
                self.assertEqual(resumed["missing_files"], [])
                self.assertEqual(resumed["action_required"], "verify")
                self.assertEqual(retained.read_bytes(), original)
                transaction = cooled_runtime.load_pa_family_cache_transaction(plan["cache_root"],plan["cache_key"])
                self.assertEqual(transaction["owner"], str(run.resolve()))
                with self.assertRaises((KeyError, ValueError)):
                    cooled_runtime.finalize_field_stage(next_run, bundle, {plan["member_id"]: resumed})
                verification = next_run/"inputs/inert_verification.txt"
                verification.write_text("INERT_NO_NATIVE_CLAIM")
                published = cooled_runtime.advance_field_cache(next_run, plan, verification)
                self.assertFalse(Path(first["scratch_directory"]).exists())
                hit = cooled_runtime.advance_field_cache(next_run, plan)
                self.assertEqual(hit["generation_directory"], published["generation_directory"])
                self.assertEqual((Path(hit["generation_directory"])/plan["filenames"][0]).read_bytes(), original)
            finally:
                for path in root.rglob("*"):
                    if path.is_file():
                        path.chmod(stat.S_IREAD|stat.S_IWRITE)

    def test_working_field_key_excludes_population_pressure_clock_and_collision(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            author,_=cooled_request_fixture(root)
            run=root/"run"
            prepare_cooled_frontend(author,run,REPO,root,run_id="20261022_120000__build__python__cooled-fixture")
            (run/"inputs/native_discovery.json").write_text(json.dumps(dict(bytes=1,sha256="A"*64,file_version="INERT")))
            first=cooled_runtime.field_cache_plan(run,cache_root=root/"cache")
            for name in ("cooled_experiment.json","source_identity.json","cooled_drive.json"):
                path=run/"inputs"/name
                data=json.loads(path.read_text());data.update(pressure_scale=2,particle_count=2,release_start_us=1234.,random_collisions="changed")
                path.write_text(json.dumps(data))
            self.assertEqual([m["cache_key"] for m in first["domains"][0]["members"]],[m["cache_key"] for m in cooled_runtime.field_cache_plan(run,cache_root=root/"cache")["domains"][0]["members"]])
            field_path=run/"inputs/cooled_field_plan.json"
            data=json.loads(field_path.read_text())
            data["working_points"][0]["electrode_voltages_v"]["1"]+=1.
            field_path.write_text(json.dumps(data))
            identities = list((run/"inputs").glob("cooled_member_*_identity.json"))
            for identity in identities: identity.unlink()
            changed=cooled_runtime.field_cache_plan(run,cache_root=root/"cache")
            self.assertNotEqual(first["domains"][0]["members"][0]["cache_key"],changed["domains"][0]["members"][0]["cache_key"])
            front_path=run/"inputs/frontend_contract.json"
            front=json.loads(front_path.read_text());front["cell_mm_xyz"]["x"]*=2;front_path.write_text(json.dumps(front))
            for identity in identities: identity.unlink()
            self.assertNotEqual([m["cache_key"] for m in changed["domains"][0]["members"]],[m["cache_key"] for m in cooled_runtime.field_cache_plan(run,cache_root=root/"cache")["domains"][0]["members"]])

    def test_field_identity_excludes_audit_but_includes_actual_builders(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            author,_=cooled_request_fixture(root)
            run=root/"run"
            prepare_cooled_frontend(author,run,REPO,root,run_id="20261022_120000__build__python__cooled-fixture")
            (run/"inputs/native_discovery.json").write_text(json.dumps(dict(bytes=1,sha256="A"*64,file_version="INERT")))
            original=cooled_runtime.field_cache_plan(run,cache_root=root/"cache")
            sha=cooled_runtime.file_sha256
            for filename, changes_key in (("verify_cooled_fields.lua",False),
                                           ("build_dirichlet_patch_operating_pa.lua",True),
                                           ("export_detached_standalone_pa.lua",True)):
                with self.subTest(filename=filename):
                    for identity in (run/"inputs").glob("cooled_member_*_identity.json"): identity.unlink()
                    with patch.object(cooled_runtime,"file_sha256",side_effect=lambda p: "F"*64 if Path(p).name==filename else sha(p)):
                        changed=cooled_runtime.field_cache_plan(run,cache_root=root/"cache")
                    self.assertEqual([m["cache_key"] for m in changed["domains"][0]["members"]] !=
                                     [m["cache_key"] for m in original["domains"][0]["members"]], changes_key)

    def test_native_audit_spec_is_actual_seven_voltage_tables(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            author,_=cooled_request_fixture(root)
            run=root/"run"
            prepared=prepare_cooled_frontend(author,run,REPO,root,run_id="20261022_120000__build__python__cooled-fixture")
            rows=[]
            for kind in cooled_runtime.KINDS:
                spec=cooled_runtime.field_verification_spec(run,root/"ordinary",member_id=kind)
                rows.extend(row.split("\t") for row in spec.read_text().splitlines())
            self.assertEqual([row[1] for row in rows if row[0]=="field"],list(cooled_runtime.KINDS))
            points={point["kind"]:point for point in prepared["field_plan"]["working_points"]}
            conditioner=prepared["frontend"]["conditioner_contract"]
            for name,eid in conditioner["electrode_ids"].items():
                for kind in cooled_runtime.KINDS:
                    row=next(row for row in rows if row[:3]==["metal",kind,name])
                    self.assertEqual(float(row[-1]),points[kind]["electrode_voltages_v"][str(eid)])
            if LUA.is_file():
                harness=root/"inert_pa_api.lua"
                harness.write_text(r'''
local spec,audit,output,scenario=arg[1],arg[2],arg[3],arg[4]
local grid,paths,values=nil,{},{}
for line in io.lines(spec) do
 local row={};for value in (line..'\t'):gmatch('(.-)\t') do row[#row+1]=value end
 if row[1]=='grid' then grid={};for i=2,7 do grid[i-1]=tonumber(row[i]) end
 elseif row[1]=='field' then paths[row[3]]=row[2];values[row[2]]={}
 elseif row[1]=='metal' then values[row[2]][row[4]..':'..row[5]..':'..row[6]]=tonumber(row[7]) end
end
simion={pas={close=function() end}}
function simion.pas:open(path)
 local kind=assert(paths[path])
 return {nx=grid[1]+(scenario=='grid' and 1 or 0),ny=grid[2],nz=grid[3],
 dx_mm=grid[4],dy_mm=grid[5],dz_mm=grid[6],potential_type='electric',close=function() end,
 point=function(_,x,y,z)
  local v=values[kind][x..':'..y..':'..z]
  if v~=nil then return v+(scenario=='voltage' and 1 or scenario=='roundoff' and 1e-12 or 0),scenario~='mask' end
  return 0,false
 end}
end
arg={spec,output}
local okay,message=pcall(dofile,audit)
assert(okay==(scenario=='pass' or scenario=='roundoff'),tostring(message))
print('INERT_PA_API_BOUNDARY=PASS '..scenario)
''',encoding="utf-8",newline="\n")
                audit=Path(cooled_runtime.__file__).with_name("verify_cooled_fields.lua")
                for scenario in ("pass","roundoff","grid","voltage","mask"):
                    checked=subprocess.run([str(LUA),str(harness),str(spec),str(audit),str(root/"audit.tsv"),scenario],cwd=root,
                        capture_output=True,text=True,timeout=30,check=False)
                    self.assertEqual(checked.returncode,0,checked.stdout+checked.stderr)
    def test_scheduler_materialization_derives_replay_policy_from_actual_gas(self):
        for scale, pressure, sigma, mfp, active in (
                (1, 1., 1e-18, -1., True), (0, 1., 1e-18, -1., False),
                (1, 0., 1e-18, -1., False), (1, 1., 0., -1., False),
                (1, 1., 0., 2., True)):
            with self.subTest(scale=scale, pressure=pressure, sigma=sigma, mfp=mfp), \
                    tempfile.TemporaryDirectory() as temporary:
                run = Path(temporary)
                (run / "results").mkdir()
                context = dict(decision=dict(actual_pulse_time_us=110.),
                               rows=[dict(particle_id=i) for i in (1, 2)], frontend=dict(frame_id="assembly"),
                               fields=dict(records={"carrier_off": dict(path=str(run/"generation/carrier.pa"), generation_directory=str(run/"generation"))}, receipt={}, identity_validation={}),
                               experiment=dict(pressure_scale=scale),
                               conditioner=dict(gas=dict(parameters=dict(hp_pressure_pa=pressure,
                                   cross_section_m2=sigma, mean_free_path_mm=mfp),
                                   domain_native_mm=dict(x_min=0., x_max=10., transverse_halfwidth=2.))))
                plan = dict(schema_version=1, role="simion_single_wave_particle_batch_plan",
                            particle_count=2, batch_count=2, batches=[
                                dict(index=i, count=1, particle_id_min=i, particle_id_max=i,
                                     simion_particle_id_offset=i-1) for i in (1, 2)])
                with patch.object(cooled_runtime, "context", return_value=context), \
                        patch.object(cooled_runtime, "validate_pa_family_cache_generation", return_value={}), \
                        patch.object(cooled_runtime.shared, "_owner", return_value=run), \
                        patch.object(cooled_runtime.shared, "_phase", return_value={}), \
                        patch.object(cooled_runtime.shared, "_case", side_effect=lambda *a, **k: dict(iob_path=a[2]+".iob")), \
                        patch.object(cooled_runtime.shared, "materialize_batches",
                                     wraps=cooled_runtime.shared.materialize_batches) as materialize:
                    result = cooled_runtime.materialize_batches(run, "extraction", plan, 110., [0., 110.])
                receipt = json.loads(Path(result["receipt_path"]).read_text())
                self.assertEqual(receipt, result)
                self.assertEqual(len(list((run / "results").glob("*.json"))), 1)
                self.assertIs(materialize.call_args.kwargs["context"], context)
                self.assertIs(materialize.call_args.kwargs["program_builder"], build_program)
                policy = materialize.call_args.kwargs["default_replay_policy"]
                self.assertEqual(receipt["default_replay_policy"], policy)
                self.assertEqual([case["index"] for case in receipt["batches"]], [1, 2])
                self.assertFalse(receipt["gui_fly_performed"])
                self.assertEqual(policy["collision_active"], active)
                self.assertEqual(policy["effective_hp_pressure_pa"], scale*pressure)
                self.assertEqual(policy["scope"], "saved_controls_only" if active else "fresh_process")
                self.assertEqual(policy["comparison_policy"], "independent_stochastic_collisions"
                                 if active else "deterministic_trajectory_parity")
                self.assertEqual(policy["gas_domain_native_mm"], context["conditioner"]["gas"]["domain_native_mm"])

    def test_frozen_parent_plan_clock_and_identity_are_the_only_authored_placement(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            request_path, request = cooled_request_fixture(workspace)
            output = workspace/"prepared"
            result = prepare_cooled_frontend(request_path, output, REPO, workspace,
                                             run_id="20261022_120000__build__python__cooled-fixture")
            inputs = output/"inputs"
            identity = json.loads((inputs/"integration_identity.json").read_text())
            self.assertEqual((identity["integration_id"], identity["workflow_id"]), ("instrument_assembly", "cooled_frontend"))
            self.assertEqual(identity["composition_plan"]["sha256"], hashlib.sha256((inputs/"composition_plan.json").read_bytes()).hexdigest().upper())
            self.assertTrue((inputs/"clock_authority.json").is_file())
            self.assertTrue((inputs/"instrument_epoch.json").is_file())
            self.assertFalse((inputs/"source_clock.json").exists())
            self.assertFalse((inputs/"source.fly2").exists())
            self.assertEqual(result["assembly_plan"]["connection_checks"][0]["gap_mm"], 1.)
            self.assertNotIn("transform", request["accelerator_component"])
            self.assertNotIn("registration", request)

    def test_prepared_output_derives_only_from_the_frozen_parent_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            request_path, request = cooled_request_fixture(workspace)
            output = workspace / "prepared"
            parent = _parent_path(request).resolve()
            frozen = (output / "inputs" / "parent_composition_plan.json").resolve()
            with patch.object(cooled_prepare, "_load", wraps=cooled_prepare._load) as load:
                prepare_cooled_frontend(request_path, output, REPO, workspace,
                                        run_id="20261022_120000__build__python__cooled-fixture")
            loaded = [Path(call.args[0]).resolve() for call in load.call_args_list]
            self.assertIn(frozen, loaded)
            self.assertNotIn(parent, loaded)

    def test_parent_instance_names_and_order_preserve_geometry_source_drive_and_clock(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            path, request = cooled_request_fixture(workspace)
            original_dir, renamed_dir = workspace / "original_instances", workspace / "renamed_instances"
            original = prepare_cooled_frontend(path, original_dir, REPO, workspace,
                                               run_id="20261022_120000__build__python__cooled-fixture")
            renamed_cooled_parent(request)
            path.write_text(json.dumps(request), encoding="utf-8")
            renamed = prepare_cooled_frontend(path, renamed_dir, REPO, workspace,
                                              run_id="20261022_120000__build__python__cooled-fixture")
            self.assertEqual({row["instance_id"] for row in renamed["assembly_plan"]["recipe"]["instances"]},
                             {"source_a", "oa_b"})
            for key in ("frontend", "conditioner", "field_plan", "probe_plan"):
                self.assertEqual(original[key], renamed[key], key)
            for name in ("frontend.gem", "release_raw.csv", "release_global.csv", "cooled_field_plan.json",
                         "cooled_drive.json", "registration.json", "clock_authority.json", "instrument_epoch.json"):
                self.assertEqual((original_dir / "inputs" / name).read_bytes(),
                                 (renamed_dir / "inputs" / name).read_bytes(), name)

    def test_explicit_local_scope_is_stable_when_parent_grows(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            path, request = cooled_request_fixture(workspace)
            full = prepare_cooled_frontend(path, workspace / "two", REPO, workspace,
                                           run_id="20261022_120000__build__python__cooled-fixture")
            baseline_parent = json.loads(_parent_path(request).read_text())
            for count in (3, 4):
                with self.subTest(parent_instance_count=count):
                    candidate = copy.deepcopy(request)
                    candidate_parent = workspace / f"parent_{count}.json"
                    candidate_parent.write_text(json.dumps(baseline_parent, indent=2) + "\n", encoding="utf-8")
                    candidate["composition_plan"] = file_record(candidate_parent)
                    extend_parent(candidate, count)
                    candidate["local_scope"] = dict(
                        instance_ids=["cooler", "accelerator"],
                        research_scope="cooled frontend through orthogonal accelerator",
                        boundary_assumptions="other parent instances are outside this local field solve",
                    )
                    path.write_text(json.dumps(candidate), encoding="utf-8")
                    local_dir = workspace / f"local_{count}"
                    local = prepare_cooled_frontend(path, local_dir, REPO, workspace,
                                                    run_id="20261022_120000__build__python__cooled-fixture")
                    self.assertEqual(local["assembly_plan"]["scope"]["kind"], "local")
                    self.assertEqual(local["assembly_plan"]["scope"]["instance_ids"], ["cooler", "accelerator"])
                    for name in ("frontend.gem", "release_global.csv", "cooled_field_plan.json"):
                        self.assertEqual((workspace / "two" / "inputs" / name).read_bytes(),
                                         (local_dir / "inputs" / name).read_bytes(), name)
                    self.assertEqual(full["frontend"], local["frontend"])

    def test_full_scope_rejects_unknown_parent_instances(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            path, request = cooled_request_fixture(workspace)
            extend_parent(request, 3)
            path.write_text(json.dumps(request), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "explicitly selected cooler"):
                prepare_cooled_frontend(path, None, REPO, workspace)

    def test_managed_failure_retains_the_verified_frozen_parent_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            path, request = cooled_request_fixture(workspace)
            extend_parent(request, 3)
            path.write_text(json.dumps(request), encoding="utf-8")
            output = workspace / "managed_failure"
            output.mkdir()
            (output / "run_config.json").write_text(json.dumps({"project": "instrument_assembly"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "explicitly selected cooler"):
                prepare_cooled_frontend(path, output, REPO, workspace,
                                        run_id="20261022_120000__build__python__cooled-fixture")
            self.assertEqual((output / "inputs" / "parent_composition_plan.json").read_bytes(),
                             _parent_path(request).read_bytes())

    def test_recipe_wrong_provider_and_endpoint_fail_before_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            path, original = cooled_request_fixture(workspace)
            for defect in ("provider", "endpoint", "port", "coupling"):
                request = copy.deepcopy(original)
                parent = json.loads(_parent_path(request).read_text())
                recipe = parent["recipe"]
                if defect == "provider":
                    parent["components"]["cooler"]["project_id"] = "orthogonal_accelerator"
                elif defect == "endpoint":
                    recipe["connections"][0]["downstream"]["instance_id"] = "absent"
                elif defect == "port":
                    recipe["connections"][0]["upstream"]["port_id"] = "guide_exit"
                else:
                    recipe["connections"][0]["coupling_mode"] = "state_handoff"
                _replace_parent(request, parent)
                path.write_text(json.dumps(request), encoding="utf-8")
                output = workspace / defect
                with self.subTest(defect=defect), self.assertRaises(ValueError):
                    prepare_cooled_frontend(path, output, REPO, workspace,
                                            run_id="20261022_120000__build__python__cooled-fixture")
                self.assertTrue((output / "inputs" / "parent_composition_plan.json").is_file())

    def test_legacy_placement_and_misalignment_fail_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            path, original = cooled_request_fixture(workspace)
            for kind in ("legacy", "component_pose", "misaligned"):
                request = copy.deepcopy(original)
                if kind == "legacy":
                    request["registration"] = {}
                elif kind == "component_pose":
                    request["accelerator_component"]["transform"] = {}
                else:
                    parent = json.loads(_parent_path(request).read_text())
                    parent["recipe"]["instances"][1]["transform"]["translation_mm"][0] += 1.
                    _replace_parent(request, parent)
                path.write_text(json.dumps(request), encoding="utf-8")
                output = workspace/kind
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    prepare_cooled_frontend(path, output, REPO, workspace,
                                            run_id="20261022_120000__build__python__cooled-fixture")
                if kind == "legacy":
                    self.assertFalse(output.exists())
                else:
                    self.assertTrue((output / "inputs" / "parent_composition_plan.json").is_file())

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 unavailable")
    def test_managed_prepare_freezes_selected_runtime_before_preparing(self):
        import sys
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            request_path, request = cooled_request_fixture(workspace)
            renamed_cooled_parent(request)
            request_path.write_text(json.dumps(request), encoding="utf-8")
            output = workspace/"managed"
            output.mkdir()
            config = output/"run_config.json"
            config.write_text(json.dumps(dict(project="wrong_owner", run_id="20261022_120000__build__python__cooled-fixture")))
            command = ["pwsh", "-NoProfile", "-File", str(REPO/"integrations/workflows/cooled_frontend/execute.ps1"),
                       "-Request", str(request_path), "-RepoRoot", str(REPO), "-Python", sys.executable,
                       "-PrepareOnly", "-OutputDirectory", str(output)]
            refused = subprocess.run(command, cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("managed run owner", refused.stderr)
            self.assertFalse((output/"inputs").exists())
            freeze = """
param($Repo,$Output)
. (Join-Path $Repo 'integrations/runtime/dependencies.ps1')
$inventory=Join-Path $Repo 'integrations/config/runtime_dependencies.json'
$null=Freeze-ConsumerDependencies -RepoRoot $Repo -ContractPath $inventory -InputDir $Output -OwnerId instrument_assembly -ConsumerId cooled_frontend
"""
            script = workspace/"freeze.ps1"
            script.write_text(freeze, encoding="utf-8")
            frozen = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(REPO), str(output/"inputs")],
                                    cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertEqual(frozen.returncode, 0, frozen.stdout+frozen.stderr)
            snapshot = output/"inputs/runtime_snapshot"
            import os
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            prepared = subprocess.run([sys.executable, "-B", "-s", "-m", "integrations.workflows.cooled_frontend.prepare",
                "--request", str(request_path), "--repo-root", str(REPO), "--workspace-root", str(workspace),
                "--output-directory", str(output), "--run-id", "20261022_120000__build__python__cooled-fixture"],
                cwd=snapshot, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(prepared.returncode, 0, prepared.stdout+prepared.stderr)
            self.assertTrue((output/"inputs/composition_plan.json").exists())
            plan = json.loads((output/"inputs/composition_plan.json").read_text(encoding="utf-8"))
            self.assertEqual({item["instance_id"] for item in plan["recipe"]["instances"]}, {"source_a", "oa_b"})
            self.assertTrue((snapshot/"integrations/workflows/cooled_frontend/prepare.py").exists())
            self.assertTrue((snapshot/"common/simion/collision_hs1.py").exists())
            self.assertFalse((snapshot/"projects/dual_pressure_rectilinear_ion_processor/analysis/functional.py").exists())
            # Exercise new static imports and dynamic seed resources from this same frozen tree.
            smoke_code = ("from pathlib import Path; import sys; "
                "import common.simion.workbench_seed as seed; "
                "import integrations.workflows.local_frontend.runtime as local; "
                "import integrations.workflows.cooled_frontend.runtime as cooled; "
                "import integrations.workflows.single_reflection_flight.field_plan as fields; "
                "root=Path.cwd().resolve(); "
                "assert all(Path(m.__file__).resolve().is_relative_to(root) for m in (seed,local,cooled,fields)); "
                "first=seed.freeze_workbench_seed(Path(sys.argv[1]),root); "
                "before={k:Path(v['frozen']['path']).stat().st_mtime_ns for k,v in first.items()}; "
                "second=seed.freeze_workbench_seed(Path(sys.argv[1]),root); "
                "assert before=={k:Path(v['frozen']['path']).stat().st_mtime_ns for k,v in second.items()}; "
                "assert set(second)=={'seed','placeholder'}; print('FROZEN_MEMBER_AND_SEED=PASS')")
            smoke = subprocess.run([sys.executable, "-B", "-s", "-c", smoke_code, str(output)],
                cwd=snapshot, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(smoke.returncode,0,smoke.stdout+smoke.stderr)
            self.assertIn("FROZEN_MEMBER_AND_SEED=PASS",smoke.stdout)

    def test_existing_bare_default_geometry_bytes_unchanged(self):
        guide, connection, component = canonical_frontend_fixture()
        gem, _ = compile_frontend(guide, connection, accelerator_component=component, cell_mm_xyz=dict(x=.1,y=.2,z=.1))
        self.assertEqual(hashlib.sha256(gem.encode()).hexdigest(), "a1a28cd7f08f7cfb079b12201a0091dd0f9228cf3f3e93537c01fffada908aa1")

    def test_two_and_three_zone_keep_original_guide_and_real_conditioner(self):
        for variant in ("two_zone", "three_zone"):
            with self.subTest(variant=variant):
                guide, connection, component, conditioner, _ = cooled_fixture(variant)
                before = copy.deepcopy((guide, connection, component, conditioner))
                gem, frontend = compile_cooled_frontend(guide, connection, component, conditioner, cell_mm_xyz=dict(x=.2,y=.2,z=.2), exit_gap_mm=1.)
                self.assertEqual((guide,connection,component,conditioner), before)
                self.assertEqual(frontend["guide_exit_center_mm"], dict(x=0.,y=-68.,z=32.))
                self.assertEqual(frontend["junction_enclosure"]["exit_to_oa_gap_mm"],1.)
                self.assertTrue(set(range(40,47)).issubset(frontend["physical_electrode_ids"]))
                self.assertEqual(gem.count("pa_define("),1)
                self.assertIn("e(46)",gem)
                self.assertLessEqual(frontend["instance_bounds_mm"]["y_min"],-97.)

    def test_real_modes_reconstruct_seed_endpoints_and_independent_controls(self):
        guide, connection, component, conditioner, drive = cooled_fixture()
        _, frontend = compile_cooled_frontend(guide, connection, component, conditioner, cell_mm_xyz=dict(x=.2,y=.2,z=.2), exit_gap_mm=1.)
        plan = compile_field_plan(frontend,guide,drive,hp_rf_peak_amplitude_v=conditioner["drive"]["rf_amplitude_v"],refine_convergence_v=1e-5)
        modes={p["kind"]:p["electrode_voltages_v"] for p in plan["working_points"]}
        self.assertEqual(len(modes),7)
        for key in modes["carrier_off"]:
            self.assertEqual(modes["carrier_off"][key]+modes["entry_close_delta"][key],plan["stage_endpoint_voltages_v"]["closed"][key])
            self.assertEqual(modes["carrier_off"][key]+modes["entry_close_delta"][key]+modes["release_delta"][key],plan["stage_endpoint_voltages_v"]["release"][key])
        self.assertEqual(modes["rf_differential_unit"]["40"],conditioner["drive"]["hp_to_guide_amplitude_ratio"])
        self.assertEqual([int(k) for k,v in modes["inner_auxiliary_unit"].items() if v], [45])
        self.assertEqual([int(k) for k,v in modes["hp_common_unit"].items() if v], [40,41,42,44,45])
        probe, rows=compile_probe_plan(conditioner,frontend,plan)
        self.assertEqual(probe["local_stencil_count"],125)
        self.assertEqual(rows[0]["x_mm"],-.4)
        self.assertEqual(rows[-1]["y_mm"],51.5)
        self.assertEqual(len(probe["working_point_kinds"]),7)

    def test_pressure_controls_freeze_identical_births_geometry_fields_and_clocks(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace=Path(temporary)
            path,request=cooled_request_fixture(workspace)
            for pressure in (0,1):
                request["pressure_scale"]=pressure
                path.write_text(json.dumps(request),encoding="utf-8")
                result=prepare_cooled_frontend(path,workspace/f"p{pressure}",REPO,workspace, run_id="20261022_120000__build__python__cooled-fixture")
                self.assertEqual(result["particle_count"],100)
            for name in ("release_global.csv","frontend.gem","cooled_field_plan.json","cooled_drive.json","cooled_probe_points.csv"):
                self.assertEqual((workspace/"p0/inputs"/name).read_bytes(),(workspace/"p1/inputs"/name).read_bytes())
            self.assertEqual(json.loads((workspace/"p0/inputs/cooled_experiment.json").read_text())["pressure_scale"],0)

    def test_field_receipt_requires_seven_readonly_actual_owner_handles(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace=Path(temporary)
            path,_=cooled_request_fixture(workspace)
            run=workspace/"artifacts/projects/instrument_assembly/runs/20261022_120000__build__python__cooled-fixture"
            self.assertEqual(run.parents[4],workspace)
            prepare_cooled_frontend(path,run,REPO,workspace, run_id="20261022_120000__build__python__cooled-fixture")
            records=[]
            try:
                result=publish_inert_fields(run, workspace/"cache")
                records=result["working_points"]
                self.assertEqual(len(fields(run)["records"]),7)
                self.assertTrue(Path(result["receipt_path"]).is_file())
                ctx=shared_runtime._context(run,field_provider=fields)
                inputs=run/"inputs"
                ctx.update(conditioner=json.loads((inputs/"conditioner_contract.json").read_text()),
                           cooled_drive=json.loads((inputs/"cooled_drive.json").read_text()),
                           experiment=json.loads((inputs/"cooled_experiment.json").read_text()),
                           voltage_calibration=dict(inner_correction_v=0.,release_hp_common_correction_v=0.),
                           hs1_source="-- pure test companion; no native collision claim\n",
                           cooled_module_source=(Path(__file__).parents[1]/"workflows/cooled_frontend/cooled_frontend.lua").read_text())
                case=shared_runtime._case(run,"extraction","pure_case",ctx["rows"][:1],ctx,
                    dict(pulse_time_us=110.,shared_times_us=[0.,20.,100.,110.,120.]),program_builder=build_program)
                program=Path(case["program_path"]).read_text()
                expected_paths=[Path(row["path"]).as_posix() for row in records if row["kind"] != "carrier_off"]
                for row in records:
                    if row['kind'] in {'rf_differential_unit', 'pulse_delta'}:
                        self.assertIn(json.dumps(Path(row['path']).as_posix()), program)
                self.assertIn("cooled_frontend_component.install",program)
                self.assertIn("voltage_waveforms=single_flight_voltage_waveforms",program)
                self.assertIn("local single_flight_source_particle_id={1}",program)
                self.assertEqual(case["count"],1)
                self.assertEqual(case["merge_offset"],0)
                self.assertTrue(Path(case["working_directory"],"cooled_collision_hs1.lua").is_file())
                if LUA.is_file():
                    glue=program[program.index("local function single_flight_exact_basename"):program.index("local function single_flight_apply_standalone_dynamic_field")]
                    configuration=program.split("end)()\ncooled_frontend_component.install(",1)[1].split(", {\n clock=",1)[0]
                    response_names=expected_paths
                    from integrations.runtime.single_flight_source import lua_value as _lua_value
                    transport=glue+"\nlocal cfg="+configuration+"\nlocal expected="+_lua_value(response_names)+r'''
local expected_paths={};for _,path in ipairs(expected) do expected_paths[path]=true end
local base={nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1,symmetry='planar',potential_type='electric'}
base.path='''+_lua_value("misleading_relative_path/"+Path(records[0]["path"]).name)+r'''
simion={pas={},wb={instances={{pa=base,filename='''+_lua_value(Path(records[0]["path"]).name)+r'''}}}}
local opened={}
function simion.pas:open(path)
 assert(expected_paths[path],'sidecar guessed a directory instead of using explicit member transport')
 opened[path]=true;return base
end
single_flight_initialize_standalone_dynamic_fields()
segment={initialize_run=function() end}
function simion.import() return {} end
local component=assert(loadfile(arg[1]))()
component.install(cfg,{voltage_waveforms=assert(loadfile(arg[2]))(),validate_response=function(response,label) single_flight_assert_matching_response(simion.wb.instances[1],response,label) end})
segment.initialize_run()
for _,path in ipairs(expected) do assert(opened[path],'missing actual response transport '..path) end
local count=0;for _ in pairs(opened) do count=count+1 end
assert(count==6,'sidecars were duplicated or omitted')
print('SEVEN_FIELD_TRANSPORT=PASS')
'''
                    harness=Path(case["working_directory"])/"transport.lua"
                    harness.write_text(transport,encoding="utf-8",newline="\n")
                    component=harness.with_name("component.lua")
                    component.write_text(ctx["cooled_module_source"].replace("adjustable ",""),encoding="utf-8",newline="\n")
                    verified=subprocess.run([str(LUA),str(harness),str(component),str(REPO/"common/simion/voltage_waveforms.lua")],cwd=harness.parent,capture_output=True,text=True,timeout=30,check=False)
                    self.assertEqual(verified.returncode,0,verified.stdout+verified.stderr)
                    parsed=Path(case["working_directory"])/"pure_syntax.lua"
                    parsed.write_text(program.replace("adjustable ",""),encoding="utf-8")
                    loader=parsed.with_name("parse_only.lua");loader.write_text("assert(loadfile(arg[1]))",encoding="utf-8")
                    checked=subprocess.run([str(LUA),str(loader),str(parsed)],cwd=loader.parent,timeout=30,capture_output=True,text=True,encoding="utf-8",check=False)
                    self.assertEqual(checked.returncode,0,checked.stdout+checked.stderr)
                bank_path=Path(result["receipt"]["field_bank_path"])
                bank=json.loads(bank_path.read_text())
                self.assertEqual(bank["schema_version"],2)
                role=bank["dynamic_roles"][0]
                self.assertEqual(role["rf_differential_pa_basenames"],[Path(next(row for row in records if row["kind"] == "rf_differential_unit")["path"]).name])
                self.assertEqual(role["rf_reference_voltage_v"],1.)
                self.assertNotIn("rf_differential_pa_basename",role)
                # A receipt-bound bank is consumed through the shared schema-2
                # validator: a stale singular v1 row cannot silently reach the
                # cooled Program.
                valid_bank=copy.deepcopy(bank)
                bank["schema_version"]=1
                bank_path.write_text(json.dumps(bank),encoding="utf-8")
                receipt_path=Path(result["receipt_path"])
                receipt=json.loads(receipt_path.read_text())
                receipt["field_bank_record"]=file_record(bank_path)
                receipt_path.write_text(json.dumps(receipt),encoding="utf-8")
                with self.assertRaisesRegex(ValueError,"field bank role/member projection differs"):
                    fields(run)
                bank_path.write_text(json.dumps(valid_bank),encoding="utf-8")
                receipt["field_bank_record"]=file_record(bank_path)
                receipt_path.write_text(json.dumps(receipt),encoding="utf-8")
                Path(records[-1]["path"]).chmod(stat.S_IREAD|stat.S_IWRITE)
                with self.assertRaisesRegex(ValueError,"read-only"):
                    fields(run)
            finally:
                for record in records:
                    Path(record["path"]).chmod(stat.S_IREAD|stat.S_IWRITE)


LUA=Path(shutil.which("lua") or r"C:\Program Files\SIMION-2020\lua.exe")


@unittest.skipUnless(LUA.is_file(),"plain Lua interpreter unavailable")
class CooledCallbackTests(unittest.TestCase):
    def test_field_composition_collision_order_and_id_stream_reset(self):
        source=(REPO/"integrations/workflows/cooled_frontend/cooled_frontend.lua").read_text(encoding="utf-8").replace("adjustable ","")
        harness=_standalone_dynamic_field_lua([])+r'''
local module_path=assert(arg[1])
local public=assert(loadfile(arg[2]))()
local edge_calls,step_order={},{}
local forced_cap=nil
local shared={cap_before_edge=function(time,dt,edge)
 edge_calls[#edge_calls+1]={time,dt,edge};step_order[#step_order+1]='edge'
 if forced_cap then return forced_cap end
 return public.cap_before_edge(time,dt,edge)
end}
segment={};local calls={};local terminated={};local t,id=0,20;local state={next_track=5};local core_stop=false
ion_number=1;ion_instance=1;ion_px_mm=.5;ion_py_mm=0;ion_pz_mm=0
ion_vx_mm=0;ion_vy_mm=0;ion_vz_mm=0;ion_time_step=1;ion_splat=0
ion_dvoltsx_gu=0;ion_dvoltsy_gu=0;ion_dvoltsz_gu=0
local base={nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1,symmetry='planar',potential_type='electrostatic'}
function base:inside_vc() return true end
function base:field_vc() return 1,2,3 end
local opens=0;local responses={}
local hs={segment={}}
function hs.reset_run_state() calls[#calls+1]='reset' end
function hs.segment.initialize() calls[#calls+1]='hsinit' end
function hs.segment.tstep_adjust() step_order[#step_order+1]='hs';ion_time_step=math.min(ion_time_step,.5) end
function hs.segment.other_actions() ion_vx_mm=ion_vx_mm+1 end
function hs.bound_parameters() return {gas_mass_amu=_gas_mass_amu,temperature_k=_temperature_k,pressure_pa=_pressure_pa,sigma_m2=_sigma_m2,mean_free_path_mm=_mean_free_path_mm,steps_per_mfp=_steps_per_MFP,random_seed=_random_seed,mark_collisions=_mark_collisions,trace_level=_trace_level} end
simion={wb={instances={{pa=base,wb_to_pa_coords=function(_,x,y,z) return x,y,z end}}},pas={}}
function simion.pas:open(path) opens=opens+1;local response=setmetatable({},{__index=base});responses[path]=response;return response end
function simion.import() segment.initialize=function() error('import clobbered core') end;return hs end
function seed(value) calls[#calls+1]='seed'..value end
segment.initialize=function() calls[#calls+1]='coreinit' end
segment.initialize_run=function() calls[#calls+1]='core_run' end
segment.terminate=function() terminated[#terminated+1]=ion_number end
segment.tstep_adjust=function() step_order[#step_order+1]='core';ion_time_step=math.min(ion_time_step,.25) end
segment.other_actions=function()
 assert(ion_vx_mm>0,'core observed stale pre-collision state')
 if core_stop then state.terminal='local_timeout';ion_splat=1 end
end
local cfg={hs1_path='fake',pose={rotation={{1,0,0},{0,1,0},{0,0,1}},translation_mm={0,0,0}},pressure_scale=1,
 gas={parameters={mass_amu=28,temperature_k=300,hp_pressure_pa=1,cross_section_m2=1,mean_free_path_mm=-1},domain_native_mm={x_min=0,x_max=1,transverse_halfwidth=2}},
 numerics={hs1_steps_per_mfp=20,collision_seed=123,extraction_sample_interval_us=.01},
 drive={entrance_close_us=10,release_start_us=20},calibration={inner_correction_v=3,release_hp_common_correction_v=4},
 extra_fields={entry_close_delta='a',release_delta='b',inner_auxiliary_unit='c',hp_common_unit='d'}}
assert(loadfile(module_path))().install(cfg,{clock=function() return t end,voltage_waveforms=shared,particle_id=function() return id end,state_for=function() return state end,
 validate_response=function(response,label) single_flight_assert_matching_response(simion.wb.instances[1],response,label) end})
segment.initialize_run();segment.initialize();assert(calls[2]=='coreinit')
segment.tstep_adjust();assert(calls[#calls]=='seed142');assert(ion_time_step==.25)
for _,sample in ipairs({{9.875,.125},{10,.25},{10.125,.25},
                       {19.875,.125},{20,.25},{20.125,.25}}) do
 t=sample[1];ion_time_step=1
 local count=#edge_calls
 segment.tstep_adjust()
 assert(ion_time_step==sample[2],'shared edge cap changed before/exact/after behavior')
 assert(#edge_calls==count+2,'both declared edges must use the injected public kernel')
 assert(edge_calls[count+1][1]==t and edge_calls[count+1][2]==.25 and edge_calls[count+1][3]==10)
 assert(edge_calls[count+2][1]==t and edge_calls[count+2][3]==20)
 local n=#step_order
 assert(step_order[n-3]=='hs' and step_order[n-2]=='core' and step_order[n-1]=='edge' and step_order[n]=='edge',
  'HS1/core/edge callback order changed')
end
-- A distinct injected result proves the consumer uses, rather than just calls, it.
forced_cap=.0625;t=10;ion_time_step=1;segment.tstep_adjust();assert(ion_time_step==forced_cap);forced_cap=nil
assert(hs.pressure()==1);ion_px_mm=1;assert(hs.pressure()==0);ion_px_mm=.5
for _,sample in ipairs({{0,-3},{10,-4},{20,-6}}) do t=sample[1];ion_dvoltsx_gu=0;segment.efield_adjust();assert(ion_dvoltsx_gu==sample[2]) end
segment.other_actions();assert(state.next_track<=20.01)
-- An unfinished ID switch is still rejected; it cannot silently reset HS1.
ion_number=2;id=3
local accepted,reason=pcall(segment.other_actions)
assert(not accepted and tostring(reason):find('unfinished collision stream interleaved',1,true))
ion_number=1;id=20
-- Reproduce a core max-age stop with no terminate before the next ID.
core_stop=true;t=1700;segment.other_actions();core_stop=false
assert(state.terminal=='local_timeout' and ion_splat==1)
local count=#calls;segment.tstep_adjust();segment.other_actions();assert(#calls==count,'closed stream was activated again')
ion_number=2;id=3;state={next_track=5};ion_splat=0
segment.tstep_adjust();assert(calls[#calls]=='seed125')
-- A native electrode/PA-exit splat also closes without running HS1 again.
ion_splat=2;local vx=ion_vx_mm;segment.other_actions();assert(ion_vx_mm==vx)
ion_number=3;id=7;state={next_track=5};ion_splat=0
segment.tstep_adjust();assert(calls[#calls]=='seed129')
-- Native PA exit ends ID3, still before SIMION's delayed terminate phase.
ion_instance=0;ion_splat=1;segment.other_actions()
ion_number=4;id=9;state={next_track=5};ion_splat=0;ion_instance=1
segment.tstep_adjust();assert(calls[#calls]=='seed131')
-- A native global callback outside all PA instances still closes the stream.
ion_instance=0;ion_splat=1;segment.other_actions()
ion_number=5;id=11;state={next_track=5};ion_splat=0;ion_instance=1
segment.tstep_adjust();assert(calls[#calls]=='seed133')
ion_splat=1;segment.other_actions()
assert(#terminated==0,'terminate must not be required between sequential particles')
-- Official flow: only after ALL ions splat, call terminate for each saved ion.
for number=1,5 do ion_number=number;segment.terminate() end
assert(#terminated==5)
for number=1,5 do assert(terminated[number]==number) end
segment.initialize_run();ion_number=1;id=20;state={next_track=5};ion_splat=0
segment.tstep_adjust();assert(calls[#calls]=='seed142')
assert(opens==4,'repeat Fly duplicated PA handles')
for _,key in ipairs({'symmetry','potential_type'}) do
  responses.d[key]='mismatched'
  local accepted,reason=pcall(segment.initialize_run)
  assert(not accepted and tostring(reason):find(key=='symmetry' and 'symmetry differs' or 'potential type differs',1,true),
    'mismatched extra PA metadata did not use shared core rejection')
  responses.d[key]=nil
end
segment.initialize_run()
responses.d.field_vc=function() return nil,nil,nil end
local accepted,reason=pcall(segment.efield_adjust)
assert(not accepted and tostring(reason):find('cooled response field is undefined',1,true),'undefined extra field did not fail closed')
print('COOLED_CALLBACK_HARNESS=PASS')
'''
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            module=directory/"module.lua";module.write_text(source,encoding="utf-8")
            script=directory/"harness.lua";script.write_text(harness,encoding="utf-8")
            result=subprocess.run([str(LUA),str(script),str(module),str(REPO/"common/simion/voltage_waveforms.lua")],cwd=directory,timeout=30,capture_output=True,text=True,encoding="utf-8",check=False)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn("COOLED_CALLBACK_HARNESS=PASS",result.stdout)


if __name__ == "__main__":
    unittest.main()
