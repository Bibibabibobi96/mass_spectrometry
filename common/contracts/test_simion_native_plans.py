"""Plan and real Lua dispatch checks with explicitly inert native objects."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from common.contracts.test_simion_geometry_compiler import compiler_inputs
from msplatform.backends.simion.compiler import compile_geometry
from msplatform.backends.simion.native_plans import (
    plan_geometry_build, plan_solve_fields, operating_member_identity, plan_operating_member, plan_downstream_solve,
)
from msplatform.backends.simion.resources import native_resource_path, structural_seed_path
from msplatform.backends.simion.source import lua_value, render_restart_fly2
from msplatform.backends.simion.tof_geometry import resolve_physical_geometry
from msplatform.execution.resources import resource_path


LUA = Path("C:/Program Files/SIMION-2020/lua.exe")
REPO = Path(__file__).resolve().parents[2]
SEED = dict(path=str(structural_seed_path(4)),
    bytes=20940,sha256="437d67349bccc25b63da2befe79b5c1b78448a150c768277515e6a2adf5f6daa")
TOOL = dict(simion_identity=dict(release="SIMION 2020",executable_bytes=123,executable_sha256="A"*64),
    builder_identity=dict(operating_builder="B"*64,exporter="C"*64))
NATIVE_PATH = resource_path("native_run_path.lua")


class NativePlanTests(unittest.TestCase):
    def test_installed_structural_seeds_require_exact_source_bytes(self):
        import hashlib
        from unittest.mock import patch
        from msplatform.backends.simion import resources

        actual = {count: structural_seed_path(count).read_bytes() for count in (4, 5)}
        for count, content in actual.items():
            with self.subTest(count=count):
                self.assertEqual((len(content), hashlib.sha256(content).hexdigest()),
                                 resources.STRUCTURAL_SEEDS[count])
                self.assertEqual(structural_seed_path(count).parent.name, "resources")
        for count in (True, False, 0, 3, 6, "4", None):
            with self.subTest(invalid_count=count), self.assertRaisesRegex(ValueError, "seed count"):
                structural_seed_path(count)
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory)
            (package / "resources").mkdir()
            with patch.object(resources, "files", return_value=package):
                for count in (4, 5):
                    with self.subTest(missing=count), self.assertRaisesRegex(FileNotFoundError, f"{count}_instance_seed"):
                        structural_seed_path(count)
                    seed = package / "resources" / f"{count}_instance_seed.iob"
                    seed.write_bytes(actual[count])
                    self.assertEqual(structural_seed_path(count), seed)
                    seed.write_bytes(actual[count][:-1] + bytes([actual[count][-1] ^ 1]))
                    with self.subTest(wrong_hash=count), self.assertRaisesRegex(ValueError, "identity differs"):
                        structural_seed_path(count)

    def test_source_free_geometry_plan_has_real_build_and_reopen_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            assembly,numerics,_=compiler_inputs(root/"author")
            compiled=compile_geometry(assembly,numerics=numerics)
            original=copy.deepcopy(compiled)
            plan=plan_geometry_build(compiled,run_directory=root/"new run",seed_record=SEED,
                native_path_resource=NATIVE_PATH)
            self.assertEqual(compiled,original)
            self.assertFalse((root/"new run").exists())
            self.assertEqual(len(plan.operations),6)
            self.assertEqual([op["stage"] for op in plan.operations],["prepare"]*6)
            self.assertEqual([op["operation_id"] for op in plan.operations][-2:],["build_geometry","verify_geometry"])
            for op in plan.operations:
                self.assertEqual(op["role"],"SIMION")
                self.assertNotIn("refine",op["arguments"])
                self.assertNotIn("fly",op["arguments"])
                if op["operation_id"] in {"geometry_flight_tube","geometry_reflectron","geometry_detector"}:
                    self.assertEqual(op["arguments"][-1],"geometry-only")
            controls = [Path(p) for p in plan.declared_outputs if Path(p).suffix == '.fly2']
            self.assertEqual(controls, [root/'new run/simion/geometry/geometry.fly2'])
            self.assertFalse(any(Path(p).suffix == '.ion' for p in plan.declared_outputs))
            self.assertEqual(plan.materializations[str(root/'new run/inputs/no_particles.fly2')], render_restart_fly2([]))
            self.assertEqual(len(plan.input_copies),1)
            with self.assertRaisesRegex(ValueError,"ASCII native projection"):
                plan_geometry_build(compiled,run_directory=root/"未投影的源路径",seed_record=SEED,
                    native_path_resource=NATIVE_PATH)
            for bad in ({**SEED,"sha256":"0"*64},{**SEED,"bytes":16_403_404}):
                with self.assertRaisesRegex(ValueError,"seed identity"):
                    plan_geometry_build(compiled,run_directory=root/"new run",seed_record=bad,
                        native_path_resource=NATIVE_PATH)

    def test_field_plan_preserves_original_three_members_and_real_parent_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            assembly,numerics,_=compiler_inputs(Path(directory))
            compiled=compile_geometry(assembly,numerics=numerics)
            field_domains=copy.deepcopy(numerics["frontend_domains"])
            field_domains["parent"]["refine_convergence_v"]=dict(carrier_off=.001,rf_reference=.002,pulse_delta=.003)
            plan=plan_solve_fields(compiled,assembly["components_resolved"],
                drive=dict(pulse_voltage_policy_id="all_accelerator_electrodes_zero_before_pulse_v1",rf_reference_voltage_v=10000.),
                numerics=dict(boundary_policy="native_zero_neumann",frontend_domains=field_domains))
            self.assertEqual([r["member_id"] for r in plan["ordered_members"]],["carrier_off","rf_reference","pulse_delta"])
            identity=operating_member_identity(plan,domain_id="parent",member_id="rf_reference",tool_identity=TOOL)
            self.assertEqual(identity["boundary_policy"],"native_zero_neumann")
            self.assertEqual(identity["rf_reference_voltage_v"],10000.)
            self.assertEqual(identity["working_points"][0]["refine_convergence_v"],.002)
            self.assertEqual(identity["simion_identity"],TOOL["simion_identity"])
            self.assertEqual(identity["builder_identity"],TOOL["builder_identity"])
            self.assertEqual({v for v in identity["working_points"][0]["electrode_voltages_v"].values()},
                             {-10000.,0.,10000.})
            # A real published same-member identity is required before fine cache identity exists.
            fine=copy.deepcopy(plan)
            fine["field_design"]["domains"].append(dict(fine["field_design"]["domains"][0],
                domain_id="entrance_refinement",boundary_policy="parent_dirichlet"))
            parent=dict(cache_key="D"*64,record=dict(kind="rf_reference",path="frontend.rf_reference.pa",bytes=100,sha256="E"*64))
            bound=operating_member_identity(fine,domain_id="entrance_refinement",member_id="rf_reference",
                tool_identity=TOOL,published_parent=parent)
            self.assertEqual(bound["boundary_policy"]["parent_cache_key"],"D"*64)
            self.assertEqual(bound["boundary_policy"]["parent_working_points"][0]["sha256"],"E"*64)
            for invalid in (None,{**parent,"record":dict(parent["record"],kind="pulse_delta")}):
                with self.assertRaisesRegex(ValueError,"same-member"):
                    operating_member_identity(fine,domain_id="entrance_refinement",member_id="rf_reference",
                        tool_identity=TOOL,published_parent=invalid)
            raw=dict(path=str(Path(directory)/"raw.pa#"),bytes=123,sha256="F"*64)
            operations,bound_identity=plan_operating_member(plan,domain_id="parent",member_id="rf_reference",
                tool_identity=TOOL,raw_geometry_record=raw,working_directory=Path(directory)/"scratch",
                payload_directory=Path(directory)/"payload",resource_paths=dict(
                    operating_builder=native_resource_path("build_dirichlet_patch_operating_pa.lua"),
                    exporter=native_resource_path("export_detached_standalone_pa.lua"),
                    verifier=native_resource_path("audit_frontend_working_fields.lua")))
            self.assertEqual(bound_identity,identity)
            self.assertEqual([op["stage"] for op in operations.operations],["pa_refine","prepare","prepare"])
            self.assertEqual(operations.operations[0]["arguments"][-1],"0.002")
            self.assertIn("zero_neumann",operations.operations[0]["arguments"])
            self.assertTrue(operations.operations[1]["outputs"][0].endswith("frontend.rf_reference.pa"))

    def test_downstream_solve_preserves_fractional_families_and_never_rebuilds(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            assembly,numerics,_=compiler_inputs(root/"author")
            compiled=compile_geometry(assembly,numerics=numerics)
            assets={role:dict(raw_record=dict(path=str(root/(role+".pa#")),bytes=100,sha256="A"*64),
                surface_records=[] if role=="reflectron" else [dict(path=str(root/(role+".pa-surf")),bytes=20,sha256="B"*64)])
                for role in ("flight_tube","reflectron","detector")}
            def plan(value=assets):
                return plan_downstream_solve(compiled,raw_geometry_assets=value,working_directory=root/"scratch",
                    convergence_v=dict(flight_tube=.001,reflectron=.002,detector=.003),
                    exporter_resource=native_resource_path("export_standalone_pa.lua"),
                    verifier_resource=native_resource_path("audit_downstream_fields.lua"))
            actual=plan()
            self.assertEqual([op["stage"] for op in actual.operations],["pa_refine","pa_refine","pa_refine","prepare","prepare"])
            self.assertTrue(all(op["arguments"][-2]=="solve-only" for op in actual.operations[:3]))
            self.assertEqual(len(actual.input_copies),5)
            self.assertFalse(any("gem2pa" in op["arguments"] for op in actual.operations))
            for role in ("flight_tube","detector"):
                changed=copy.deepcopy(assets);changed[role]["surface_records"]=[]
                with self.assertRaisesRegex(ValueError,"surface companions"):
                    plan(changed)
            changed=copy.deepcopy(assets);changed["reflectron"]["raw_record"]["path"]=str(root/"response.pa1")
            with self.assertRaisesRegex(ValueError,"family responses are forbidden"):
                plan(changed)

    @unittest.skipUnless(LUA.is_file(),"plain Lua interpreter unavailable")
    def test_all_three_actual_builder_geometry_modes_dispatch_no_refine_or_adjust(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            assembly,numerics,_=compiler_inputs(root/"author")
            compiled=compile_geometry(assembly,numerics=numerics)
            contract=compiled.frontend_geometry["downstream_build_contract"]
            provider=copy.deepcopy(assembly["components_resolved"]["oatof"])
            provider.update(contract)
            contract=dict(contract,physical_geometry=resolve_physical_geometry(provider))
            for spec in compiled.downstream_specs:
                role=spec["role"]
                case=root/role;case.mkdir()
                projection=case/"projection.lua"
                projection.write_text("return "+lua_value(contract),encoding="utf-8")
                gem=case/"source.gem";gem.write_text(spec["template_text"],encoding="utf-8")
                raw_grids=[]
                if role=="reflectron":
                    for electrode in contract["physical_geometry"]["simion"][role]["electrodes"]:
                        for region in electrode["regions"]:
                            if region["axial_mm"][0]==region["axial_mm"][1]:
                                raw_grids.append(dict(row=round(region["axial_mm"][0]/numerics["geometry_build"][role]["cell_axial_mm"]),
                                                     electrode_id=electrode["local_electrode_id"]))
                builder=native_resource_path("build_"+role+"_variant.lua")
                script=case/"dispatch.lua"
                base_program=("arg="+lua_value([str(gem),str(case/"raw.pa#"),str(projection),"geometry-only"])+
                    "\nrows="+lua_value(raw_grids)+"\n"+r'''
local commands={}
local refined,adjusted=0,0
local pa={nx=1,ny=1,nz=1}
for _,row in ipairs(rows) do pa.nx=math.max(pa.nx,row.row+1) end
function pa:point(x,y,z)
 for _,row in ipairs(rows) do if x==row.row then return row.electrode_id,true end end
 return 0,false
end
function pa:close() end
function pa:refine(options)
 assert(arg[4]=='solve-only' and options.convergence==.001 and options.resume==false,'FORBIDDEN_OR_WRONG_REFINE')
 refined=refined+1
end
function pa:fast_adjust(values) assert(arg[4]=='solve-only','FORBIDDEN_FAST_ADJUST');adjusted=adjusted+1 end
function pa:save() assert(arg[4]=='solve-only','FORBIDDEN_PA_SAVE') end
simion={pas={}}
function simion.pas:open() return pa end
function simion.pas:close() end
function simion.command(command)
 if arg[4]=='geometry-only' then assert(command:match('^gem2pa '),'FORBIDDEN_NON_GEOMETRY_COMMAND '..command)
 else assert(command:match('^fastadj '),'SOLVE_REBUILT_GEOMETRY '..command) end
 commands[#commands+1]=command
end
dofile(BUILDER)
if arg[4]=='geometry-only' then
 assert(#commands==1 and refined==0 and adjusted==0,'geometry performed a solve')
else
 assert(refined==1 and #commands+adjusted==1,'solve must refine/adjust exactly once without GEM2PA')
end
assert(_G.var==nil,'GEM context leaked')
print('INERT_GEOMETRY_DISPATCH=PASS')
'''.replace("BUILDER",json.dumps(str(builder))))
                for mode in ("geometry-only","solve-only"):
                    program=base_program.replace("geometry-only",mode,1)
                    if mode=="solve-only":
                        program=program.replace("\nrows=","\narg[5]='0.001'\nrows=",1)
                    script.write_text(program,encoding="utf-8")
                    result=subprocess.run([str(LUA),str(script)],cwd=root,capture_output=True,text=True,encoding="utf-8",timeout=30)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                    self.assertIn("BUILD_GEOMETRY=PASS ROLE="+role if mode=="geometry-only" else "BUILD: PASS",result.stdout)
                    self.assertIn("INERT_GEOMETRY_DISPATCH=PASS",result.stdout)

    @unittest.skipUnless(LUA.is_file(),"plain Lua interpreter unavailable")
    def test_real_geometry_iob_branch_rejects_outside_bootstrap_before_slot_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for outside in (False,True):
                case=root/str(outside);case.mkdir()
                seed=case/"4_instance_seed.iob";seed.write_bytes(b"INERT_SOFTWARE_SEED_NOT_IOB")
                rows=[]
                for i,role in enumerate(("flight_tube","reflectron","accelerator","detector"),1):
                    rows.append(dict(role=role,instance_index=i,priority_number=i,path=str(case/(role+".pa#")),
                        grid=dict(nx=3,ny=4,nz=5,dx_mm=.1,dy_mm=.2,dz_mm=.3),
                        placement=dict(x_mm=i,y_mm=0,z_mm=0,az_deg=0,el_deg=0,rt_deg=0,scale=1)))
                empty=case/'no_particles.fly2'
                empty.write_text(render_restart_fly2([]),encoding='utf-8')
                spec=dict(schema_version=1,role="single_reflection_iob_build",instances=rows,
                    empty_particle_control=str(empty),
                    seed_iob=str(seed),output_iob=str(case/"geometry.iob"),
                    bootstrap_paths=[str(case/f"iob_seed_placeholder_{i:02d}.pa0") for i in range(1,5)])
                program="spec="+lua_value(spec)+"\noutside="+lua_value(outside)+"\n"+r'''
local slot_changes=0
local zero_loaded=false
local function norm(s) return s:gsub('\\','/') end
local function pa()
 local p={nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1}
 function p:size(x,y,z)
  assert(x>=3 and y>=3 and z>=3,'SIMION2020 minimum neutral bootstrap dimensions')
  self.nx,self.ny,self.nz=x,y,z
 end
 function p:save(path) local f=assert(io.open(path,'wb'));f:write('INERT_NOT_PA');f:close() end
 function p:close() end
 function p:load()
  slot_changes=slot_changes+1;self.path=norm(self.filename)
  self.nx,self.ny,self.nz=3,4,5;self.dx_mm,self.dy_mm,self.dz_mm=.1,.2,.3
 end
 return setmetatable(p,{__index=function(t,k) if k=='path' then return rawget(t,'_normalized_path') end end,
  __newindex=function(t,k,v) if k=='path' then rawset(t,'_normalized_path',norm(v)) else rawset(t,k,v) end end})
end
local slots={}
local instances=newproxy(true)
getmetatable(instances).__index=slots
getmetatable(instances).__newindex=slots
getmetatable(instances).__len=function() return #spec.instances end
simion={pas={},wb={instances=instances}}
function simion.pas:open() return pa() end
function simion.pas:close() end
function simion.wb:load_particles(path)
 local f=assert(io.open(path,'rb'));local text=f:read('*a');f:close()
 assert(text:gsub('%s','')=='particles{coordinates=0,}','nonzero source requested')
 zero_loaded=true
end
function simion.wb:save(path)
 assert(zero_loaded,'factory definitions were not explicitly cleared')
 local f=assert(io.open(path,'wb'));f:write('INERT_NOT_IOB');f:close()
 f=assert(io.open(path:gsub('%.iob$','.fly2'),'wb'));f:write('particles { coordinates = 0 }');f:close()
end
function simion.command(command)
 assert(not command:find('refine') and not command:find('fly') and not command:find('fastadj'),'FORBIDDEN_NATIVE_ACTION')
 for i,path in ipairs(spec.bootstrap_paths) do
  local p=pa();p.path=outside and '/unowned/author.pa0' or path
  local item={pa=p,_debug_update_size=function() end}
  if command:find('geometry.iob',1,true) then
   local row=spec.instances[i];p.path=row.path
   for k,v in pairs(row.grid) do p[k]=v end
   for property,key in pairs({x='x_mm',y='y_mm',z='z_mm',az='az_deg',el='el_deg',rt='rt_deg',scale='scale'}) do item[property]=row.placement[key] end
  end
  simion.wb.instances[i]=item
 end
end
local core=assert(loadfile(CORE))()
local okay,message=pcall(function() core(spec,'build_geometry',function(x) return x end) end)
if outside then
 assert(not okay and tostring(message):find('outside this private bootstrap'),tostring(message))
 assert(slot_changes==0,'unowned PA was replaced before rejection')
else
 assert(okay,message);assert(slot_changes==4)
 core(spec,'verify_geometry',function(x) return x end)
 for _,path in ipairs(spec.bootstrap_paths) do local f=io.open(path,'rb');assert(not f,'bootstrap not cleaned') end
end
print('INERT_IOB_DISPATCH=PASS OUTSIDE='..tostring(outside))
'''
                program=program.replace("CORE",json.dumps(str(native_resource_path("iob_core.lua"))))
                script=case/"check.lua";script.write_text(program,encoding="utf-8")
                result=subprocess.run([str(LUA),str(script)],cwd=case,capture_output=True,text=True,encoding="utf-8",timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn("INERT_IOB_DISPATCH=PASS",result.stdout)


if __name__ == "__main__":
    unittest.main()
