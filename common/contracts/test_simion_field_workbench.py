"""Pure source-free field-container plans and actual Lua dispatch with inert PAs."""
import ast
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest

from common.contracts.test_simion_geometry_compiler import compiler_inputs
from common.contracts.test_simion_native_plans import SEED, NATIVE_PATH, LUA
from msplatform.backends.simion.compiler import compile_geometry
from msplatform.backends.simion.native_plans import plan_solve_fields, plan_field_workbench, _field_plan
from msplatform.backends.simion.field_validation import require_supported_split_interfaces
from msplatform.backends.simion.frontend import frontend_electrode_maps
from msplatform.backends.simion.resources import native_resource_path
from msplatform.backends.simion.source import lua_value


def case(root):
    assembly,numerics,_=compiler_inputs(root/'author')
    compiled=compile_geometry(assembly,numerics=numerics)
    domains=copy.deepcopy(numerics['frontend_domains'])
    for domain in domains.values():
        domain['refine_convergence_v']=dict(carrier_off=.001,rf_reference=.002,pulse_delta=.003)
    design=plan_solve_fields(compiled,assembly['components_resolved'],
        drive=dict(pulse_voltage_policy_id='all_accelerator_electrodes_zero_before_pulse_v1',rf_reference_voltage_v=10000.),
        numerics=dict(boundary_policy='native_zero_neumann',frontend_domains=domains))['field_design']
    carriers={role:dict(path=str(root/(role+'.pa')),bytes=123,sha256='A'*64)
              for role in ('flight_tube','reflectron','accelerator','detector')}
    responses=[]
    for domain in design['domains']:
        grid=dict(domain['dimensions'],**{f'd{a}_mm':domain['cell_mm_xyz'][a] for a in 'xyz'})
        for point in design['working_points']:
            if point['kind']!='carrier_off':
                responses.append(dict(domain=domain['domain_id'],kind=point['kind'],
                    path=str(root/(point['kind']+'.pa')),grid=grid))
    return assembly,compiled,design,carriers,responses


class FieldWorkbenchTests(unittest.TestCase):
    def test_real_geometry_field_projection_is_source_free_and_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            assembly,compiled,design,carriers,responses=case(root)
            original=copy.deepcopy((compiled,design,carriers,responses))
            plan=plan_field_workbench(compiled,field_design=design,components_resolved=assembly['components_resolved'],
                carriers=carriers,response_fields=responses,run_directory=root/'run',seed_record=SEED,native_path_resource=NATIVE_PATH)
            self.assertEqual((compiled,design,carriers,responses),original)
            self.assertEqual([r['operation_id'] for r in plan.operations],['build_fields','verify_fields'])
            self.assertEqual(len(plan.input_copies),1)
            self.assertFalse((root/'run').exists())
            self.assertEqual(len(plan.materializations),2)
            text=plan.materializations[str(root/'run/inputs/field_iob.lua')]
            for name in ('response_fields','interface_field_probes','native_priority_occupancy_probes'):
                self.assertIn(name,text)
            self.assertNotIn('projected_source',text)
            self.assertFalse(any(str(p).endswith('.lua') for p in plan.declared_outputs))
            for wrong in (responses[:-1],responses+[responses[0]]):
                with self.assertRaisesRegex(ValueError,'cover exactly'):
                    plan_field_workbench(compiled,field_design=design,components_resolved=assembly['components_resolved'],
                        carriers=carriers,response_fields=wrong,run_directory=root/'run',seed_record=SEED,native_path_resource=NATIVE_PATH)
            broken=copy.deepcopy(responses);broken[0]['grid']['nx']+=1
            with self.assertRaisesRegex(ValueError,'response grid'):
                plan_field_workbench(compiled,field_design=design,components_resolved=assembly['components_resolved'],
                    carriers=carriers,response_fields=broken,run_directory=root/'run',seed_record=SEED,native_path_resource=NATIVE_PATH)

    def test_nonzero_actual_bound_exit_rejected_without_changing_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            _,compiled,design,_,_=case(Path(directory))
            _,ids=frontend_electrode_maps(compiled.frontend_geometry)
            for value in (1.,True,float('nan'),None):
                changed=copy.deepcopy(design)
                changed['accelerator_voltage_states']['operating_voltages_v'][ids['accelerator_grid2_id']]=value
                before=copy.deepcopy(changed)
                with self.subTest(value=value),self.assertRaisesRegex(ValueError,'actual ON'):
                    require_supported_split_interfaces(compiled.frontend_geometry,changed)
                with self.assertRaisesRegex(ValueError,'actual ON'):
                    _field_plan(compiled,changed)
                self.assertEqual(repr(changed),repr(before))

    def test_original_probe_algorithms_are_single_canonical_implementations(self):
        from integrations.workflows.single_reflection_flight import runtime
        from msplatform.backends.simion import field_validation
        for name in ('interface_field_probes','native_priority_occupancy_probes'):
            self.assertIs(getattr(runtime,name),getattr(field_validation,name))
        tree=ast.parse(Path(runtime.__file__).read_text(encoding='utf-8'))
        self.assertFalse(any(isinstance(n,ast.FunctionDef) and n.name in
            {'interface_field_probes','native_priority_occupancy_probes'} for n in tree.body))

    @unittest.skipUnless(LUA.is_file(),'plain Lua interpreter unavailable')
    def test_actual_field_modes_preserve_solved_audits_without_source_or_program(self):
        self._check_field_modes(('none','grid','interface','priority','ambient_program','nonzero_source'))

    @unittest.skipUnless(LUA.is_file(),'plain Lua interpreter unavailable')
    def test_loaded_iob_paths_use_full_absolute_identity(self):
        self._check_field_modes(('path_dotdot','path_case','path_unc_equivalent','path_dotted_filename',
            'path_wrong_directory','path_wrong_drive','path_unc_wrong_share','path_wrong_filename',
            'path_drive_relative','path_namespace','path_above_root','path_unc_above_root'))

    def _check_field_modes(self, faults):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            assembly,compiled,design,carriers,responses=case(root)
            for fault in faults:
                with self.subTest(fault=fault):
                    folder=root/fault;folder.mkdir()
                    plan=plan_field_workbench(compiled,field_design=design,components_resolved=assembly['components_resolved'],
                        carriers=carriers,response_fields=responses,run_directory=folder,seed_record=SEED,native_path_resource=NATIVE_PATH)
                    for path,text in plan.materializations.items():
                        p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8',newline='\n')
                    seed=Path(plan.input_copies[0]['destination']);seed.parent.mkdir(parents=True,exist_ok=True);seed.write_bytes(b'INERT_NOT_IOB')
                    (folder/'simion/fields').mkdir(parents=True)
                    if fault=='ambient_program': (folder/'simion/fields/fields.lua').write_text('error("FORBIDDEN")')
                    if fault=='nonzero_source': (folder/'inputs/no_particles.fly2').write_text('particles { standard_beam {} }')
                    program='spec=dofile('+lua_value(str(folder/'inputs/field_iob.lua'))+')\nfault='+lua_value(fault)+'\n'+r'''
local function norm(s) return s:gsub('\\','/'):lower() end
if fault=='path_unc_equivalent' or fault=='path_unc_wrong_share' or fault=='path_unc_above_root' then
 spec.instances[1].path='//server/share/carriers/flight_tube.pa'
elseif fault=='path_dotted_filename' then
 spec.instances[1].path=spec.instances[1].path:gsub('flight_tube%.pa$','flight..tube.v1.pa')
end
local function loaded_path(path)
 path=norm(path)
 if fault=='path_dotdot' or fault=='path_unc_equivalent' then return path:gsub('/([^/]+)$','/unused/./../%1') end
 if fault=='path_case' then return path:upper() end
 if fault=='path_wrong_directory' then return path:gsub('/([^/]+)$','/wrong/%1') end
 if fault=='path_wrong_drive' then return (path:sub(1,1)=='c' and 'd' or 'c')..path:sub(2) end
 if fault=='path_unc_wrong_share' then return path:gsub('//server/share/','//server/other/') end
 if fault=='path_wrong_filename' then return path..'.different' end
 if fault=='path_drive_relative' then return 'c:flight_tube.pa' end
 if fault=='path_namespace' then return '//?/c:/flight_tube.pa' end
 if fault=='path_above_root' then return 'c:/../../flight_tube.pa' end
 if fault=='path_unc_above_root' then return '//server/share/../flight_tube.pa' end
 return path
end

local loads,queries=0,0
local function pa(path)
 local p={nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1,symmetry='3dplanar'}
 function p:size(x,y,z) self.nx,self.ny,self.nz=x,y,z end
 function p:close() end
 function p:save(path) local f=assert(io.open(path,'wb'));f:write('INERT_NOT_PA');f:close() end
 function p:point() return fault=='interface' and 1 or 0,true end
 function p:potential_vc() return fault=='interface' and 1 or 0 end
 function p:field_vc() queries=queries+1;return 0,0,0 end
 function p:inside_vc() return true end
 function p:load()
  self.path=self.filename
  for _,row in ipairs(spec.instances) do if row.path==self.filename then for k,v in pairs(row.grid) do self[k]=v end end end
 end
 if path then
  for _,row in ipairs(spec.response_fields) do if row.path==path then
   for k,v in pairs(row.grid) do p[k]=v end
   if fault=='grid' then p.nx=p.nx+1 end
  end end
 end
 return setmetatable(p,{__index=function(t,k) if k=='path' then return rawget(t,'_path') end end,
 __newindex=function(t,k,v) if k=='path' then rawset(t,'_path',norm(v)) else rawset(t,k,v) end end})
end
local slots={}
local instances=newproxy(true)
getmetatable(instances).__index=slots
getmetatable(instances).__newindex=slots
getmetatable(instances).__len=function() return #spec.instances end
simion={pas={},wb={instances=instances}}
function simion.pas:open(path) return pa(path) end
function simion.pas:close() end
function simion.wb:load_particles(path)
 local f=assert(io.open(path));local text=f:read('*a');f:close()
 assert(text:gsub('%s','')=='particles{coordinates=0,}')
end
function simion.wb:save(path)
 local f=assert(io.open(path,'wb'));f:write('INERT_NOT_IOB');f:close()
 f=assert(io.open(path:gsub('%.iob$','.fly2'),'wb'));f:write('particles { coordinates = 0 }');f:close()
end
function simion.wb:find_at() return false,fault=='priority' and 4 or 3,nil end
function simion.command(command)
 loads=loads+1
 assert(not command:find('fly') and not command:find('refine') and not command:find('fastadj'))
 for i,row in ipairs(spec.instances) do
  local p=pa();p.path=loads==1 and spec.bootstrap_paths[i] or (i==1 and loaded_path(row.path) or row.path)
  local item={pa=p,_debug_update_size=function() end}
  function item:wb_to_pa_coords(x,y,z) return x,y,z end
  function item:pa_to_wb_coords(x,y,z) return x,y,z end
  function item:pa_to_wb_orient(x,y,z) return x,y,z end
  function item:inside_wc() return true end
  if loads>1 then
   for k,v in pairs(row.grid) do p[k]=v end
   for property,key in pairs({x='x_mm',y='y_mm',z='z_mm',az='az_deg',el='el_deg',rt='rt_deg',scale='scale'}) do item[property]=row.placement[key] end
  end
  slots[i]=item
 end
end
local core=assert(loadfile(CORE))()
local okay,message=pcall(function()
 core(spec,'build_fields',function(x) return x end)
 core(spec,'verify_fields',function(x) return x end)
end)
local path_positive={path_dotdot=true,path_case=true,path_unc_equivalent=true,path_dotted_filename=true}
if fault=='none' or path_positive[fault] then assert(okay,message);assert(queries>0,'solved field queries were skipped')
else
 assert(not okay,'fault was accepted: '..fault)
 local expected=({grid='response grid differs',interface='grounded grid node differs',priority='priority/occupancy point mismatch',ambient_program='forbids automatic',nonzero_source='contains a particle'})[fault]
 if fault:find('path_',1,true)==1 then
  if fault=='path_drive_relative' or fault=='path_namespace' then expected='unsupported absolute PA path'
  elseif fault=='path_above_root' or fault=='path_unc_above_root' then expected='PA path escapes absolute root'
  else expected='saved PA path differs' end
 end
 assert(tostring(message):find(expected,1,true),tostring(message))
end
print('INERT_FIELD_IOB=PASS FAULT='..fault)
'''
                    program=program.replace('CORE',lua_value(str(native_resource_path('iob_core.lua'))))
                    script=folder/'inert.lua';script.write_text(program,encoding='utf-8',newline='\n')
                    result=subprocess.run([str(LUA),str(script)],cwd=folder,capture_output=True,text=True,encoding='utf-8',timeout=30)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                    self.assertIn('INERT_FIELD_IOB=PASS',result.stdout)


if __name__=='__main__': unittest.main()
