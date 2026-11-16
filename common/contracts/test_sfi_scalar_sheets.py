import subprocess
import unittest
from pathlib import Path

from common.contracts.test_simion_prepared_model import LUA
from msplatform.backends.simion.resources import native_resource_path
from msplatform.backends.simion.sfi_scalar_binding import _ideal_sheet_projection
from msplatform.backends.simion.tracking_program import _instrument_common_scalar, _lua_value

root = Path(__file__).resolve().parents[2]

grid = dict(origin_mm=[-2., -2., -1.], pitch_mm=[1., 1., 1.], dimensions=[5, 5, 3])
def member(shape):
    return dict(member_id='sheet', instance_id='oa', electrode_group_id='g', representation_role='ideal_surface',
                shape=shape, transform=dict(rotation=[[1,0,0],[0,1,0],[0,0,1]], translation_mm=[0,0,0]))

class SheetTests(unittest.TestCase):
    def test_fractional_edge_and_exact_plane_nodes(self):
        fractional = dict(origin_mm=[0., 0., 0.], pitch_mm=[.1, .1, .1], dimensions=[8, 8, 8])
        node = 3 * .1
        self.assertEqual(node, .30000000000000004)
        lower = member(dict(kind='box', center_mm=[.4,.4,node], size_mm=[.2,.2,0.]))
        upper = member(dict(kind='box', center_mm=[.2,.2,node], size_mm=[.20000000000000007,.20000000000000007,0.]))
        for shape in (lower, upper):
            rows = _ideal_sheet_projection({'members':[shape]}, fractional)
            self.assertTrue(any(r['j_min'] <= 3 <= r['j_max'] and r['i_min'] <= 3 <= r['i_max'] and r['k'] == 3 for r in rows))
        disk = member(dict(kind='annulus', center_xy_mm=[.4,.4], z_min_mm=node, z_max_mm=node,
                           inner_radius_mm=0., outer_radius_mm=.1))
        rows = _ideal_sheet_projection({'members':[disk]}, fractional)
        self.assertTrue(any(r['j_min'] == 4 and r['i_min'] <= 3 <= r['i_max'] for r in rows))
        fractional['origin_mm'][0] = -.1
        rows = _ideal_sheet_projection({'members':[lower]}, fractional)
        self.assertTrue(any(r['j_min'] == 3 and r['i_min'] <= 4 <= r['i_max'] for r in rows))
        lower['shape']['center_mm'][2] = .3
        with self.assertRaisesRegex(ValueError, 'not aligned'):
            _ideal_sheet_projection({'members':[lower]}, fractional)

    def test_fractional_grid_and_signed_poses(self):
        fractional = dict(origin_mm=[-2., -2., -.75], pitch_mm=[.5, .5, .25], dimensions=[9, 9, 7])
        sheet = member(dict(kind='box', center_mm=[0.,0.,0.], size_mm=[2.,1.,0.]))
        sheet['transform'] = dict(rotation=[[0,-1,0],[1,0,0],[0,0,1]], translation_mm=[.5,0.,.25])
        rows = _ideal_sheet_projection({'members':[sheet]}, fractional)
        self.assertEqual([(r['j_min'],r['i_min'],r['i_max'],r['k']) for r in rows],
                         [(j,4,6,4) for j in range(2,7)])
        self.assertTrue(all((r['instance_id'],r['electrode_group_id'],r['member_id']) == ('oa','g','sheet') for r in rows))
        sheet['transform'] = dict(rotation=[[1,0,0],[0,-1,0],[0,0,-1]], translation_mm=[.5,0.,.25])
        reverse = _ideal_sheet_projection({'members':[sheet]}, fractional)
        self.assertEqual([(r['j_min'],r['i_min'],r['i_max'],r['k']) for r in reverse],
                         [(j,3,7,4) for j in range(3,6)])
        sheet['transform']['translation_mm'][2] = .3
        with self.assertRaisesRegex(ValueError, 'not aligned'):
            _ideal_sheet_projection({'members':[sheet]}, fractional)
        sheet['shape'] = dict(kind='box', center_mm=[0.,0.,0.], size_mm=[0.,1.,2.])
        sheet['transform'] = dict(rotation=[[0,0,1],[0,1,0],[-1,0,0]], translation_mm=[0.,0.,0.])
        sideways = _ideal_sheet_projection({'members':[sheet]}, fractional)
        self.assertEqual([(r['j_min'],r['i_min'],r['i_max'],r['k']) for r in sideways],
                         [(j,2,6,3) for j in range(3,6)])
        sheet['shape'] = dict(kind='box', center_mm=[0.,0.,0.], size_mm=[1.,0.,2.])
        sheet['transform'] = dict(rotation=[[0,0,-1],[1,0,0],[0,-1,0]], translation_mm=[0.,0.,0.])
        sideways_y = _ideal_sheet_projection({'members':[sheet]}, fractional)
        self.assertEqual([(r['j_min'],r['i_min'],r['i_max'],r['k']) for r in sideways_y],
                         [(j,2,6,3) for j in range(3,6)])

    def test_partial_sheet_routing_and_guard(self):
        local_grid = dict(origin_mm=[-4.,-4.,-4.], pitch_mm=[1.,1.,1.], dimensions=[11,11,11])
        sheet = member(dict(kind='box', center_mm=[0.,0.,.5], size_mm=[2.,2.,0.]))
        with self.assertRaisesRegex(ValueError, 'not aligned'):
            _ideal_sheet_projection({'members':[sheet]}, local_grid)
        unsupported = _ideal_sheet_projection({'members':[sheet]}, local_grid, allow_partial=True)
        self.assertEqual(len(unsupported), 1)
        self.assertEqual(unsupported[0]['member_id'], 'sheet')
        self.assertLess(unsupported[0]['unsupported_bounds_mm'][2][0], .5)
        self.assertGreater(unsupported[0]['unsupported_bounds_mm'][2][1], .5)
        window_grid = dict(origin_mm=[-4.,-4.,-4.5], pitch_mm=[1.,1.,1.], dimensions=[11,11,11])
        aligned = _ideal_sheet_projection({'members':[sheet]}, window_grid)
        self.assertTrue(aligned)
        self.assertTrue(all(row['k'] == 5 for row in aligned))
        record = {'field_v': {'path': 'v'}, 'field_valid': {'path': 'mask'}}
        basis = {'bases': {n: {'grid': local_grid, 'records': record, 'ideal_sheet_projection': unsupported}
                           for n in ('carrier', 'rf_reference', 'pulse_delta')},
                 'rf': {'waveform':'sine','frequency_hz':1.,'phase_rad':0.},
                 'clock': {'phase_reference_instrument_time_us':0.}}
        template = 'local single_flight_trace_path=\n    single_flight_frontend=single_flight_frontend_component.new\n  if instance==nil then return end\n  end\nend\nfunction segment.instance_adjust()'
        self.assertEqual(_instrument_common_scalar(template, basis, '', '', False).count('unsupported_bounds_mm='), 3)
        if not LUA.is_file(): self.skipTest('plain Lua unavailable')
        adapter = native_resource_path('scalar_field_adapter.lua').read_text(encoding='utf-8')
        binding = dict(mode='comsol_static_scalar_v', scalar_pa='base', valid_pa='mask', **local_grid,
                       ideal_sheet_projection=unsupported,
                       refinement_windows=[dict(name='sheet', active_box_mm=[[-1.,1.],[-1.,1.],[-1.,1.]],
                           mode='comsol_static_scalar_v', scalar_pa='window', valid_pa='mask', **window_grid,
                           ideal_sheet_projection=aligned)])
        lua = """simion={pas={},experimental={}}; function simion.early_access() end
local invalid=false; local evaluations=0
function simion.pas:open(path) return {symmetry='3dplanar',nx=11,ny=11,nz=11,dx_mm=1,dy_mm=1,dz_mm=1,debug_max_voltage=100,
 potential=function(self,i,j,k) if path=='mask' and invalid then return 0 end return path=='mask' and 1 or 7 end,
 potential_vc=function() evaluations=evaluations+1; return 7 end, electrode=function() end} end
simion.experimental.field_array=function() return {efield=function() evaluations=evaluations+1; return 1,2,3 end} end
local adapter=(function()
""" + adapter + "\nend)()\nlocal binding=" + _lua_value(binding) + """
local f=adapter(binding,'raw_sample'); assert(f(0,0,3)==7); assert(f(0,0,1)==7)
ion_number=47; ion_time_of_flight=12.5
local before=evaluations; local ok,err=pcall(f,0,0,1.01)
assert(not ok and string.find(err,'V_UNREPRESENTED_SHEET') and string.find(err,'world=',1,true) and string.find(err,'level=base',1,true) and string.find(err,'member=sheet',1,true) and string.find(err,'ion=47',1,true) and string.find(err,'elapsed_us=12.5',1,true) and string.find(err,'scalar=base',1,true) and evaluations==before)
before=evaluations; ok,err=pcall(f,20,0,3)
assert(not ok and string.find(err,'V_SUPPORT_BOX_OUTSIDE') and string.find(err,'axis=1',1,true) and string.find(err,'dimension=11',1,true) and string.find(err,'world=(20,0,3)',1,true) and string.find(err,'ion=47',1,true) and string.find(err,'mask=mask',1,true) and evaluations==before)
invalid=true; before=evaluations; ok,err=pcall(f,0,0,0)
assert(not ok and string.find(err,'V_SUPPORT_UNKNOWN') and evaluations==before)
invalid=false; binding.ideal_sheet_projection[1].unsupported_bounds_mm[3][1]=0/0
ok,err=pcall(adapter,binding,'raw_sample'); assert(not ok and string.find(err,'invalid unsupported sheet bounds'))
"""
        result = subprocess.run([str(LUA), '-'], input=lua, text=True, capture_output=True,
                                cwd=root, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_clipped_boundary_support_stays_fail_closed(self):
        if not LUA.is_file(): self.skipTest('plain Lua unavailable')
        adapter = native_resource_path('scalar_field_adapter.lua').read_text(encoding='utf8')
        lua = """simion={pas={},experimental={}};function simion.early_access()end
local bad=nil;local nonfinite=nil;local evaluated=0
function simion.pas:open(path)return {symmetry='3dplanar',nx=5,ny=5,nz=5,dx_mm=1,dy_mm=1,dz_mm=1,debug_max_voltage=100,
 potential=function(self,i,j,k) assert(i>=0 and i<5 and j>=0 and j<5 and k>=0 and k<5);if path=='mask' then return bad and i==bad[1] and j==bad[2] and k==bad[3] and 0 or 1 end;if nonfinite and i==nonfinite[1] and j==nonfinite[2] and k==nonfinite[3] then return 0/0 end;return 3 end,
 potential_vc=function()evaluated=evaluated+1;return 3 end,electrode=function()end}end
simion.experimental.field_array=function()return {efield=function()evaluated=evaluated+1;return 1,2,3 end}end
local adapter=(function()
""" + adapter + "\nend)()\n" + """
local b={mode='comsol_static_scalar_v',scalar_pa='v',valid_pa='mask',origin_mm={0,0,0},pitch_mm={1,1,1},dimensions={5,5,5},ideal_sheet_projection={}}
local f=adapter(b,'raw_sample')
for axis=1,3 do for _,x in ipairs({0,.1,.9837869794909693,3.9,4}) do local q={2,2,2};q[axis]=x;assert(f(unpack(q))==3) end end
for axis=1,3 do for _,x in ipairs({-0.0001,4.0001}) do local q={2,2,2};q[axis]=x;local before=evaluated;local ok,err=pcall(f,unpack(q));assert(not ok and string.find(err,'V_SUPPORT_BOX_OUTSIDE',1,true) and evaluated==before) end end
bad={0,2,2};local before=evaluated;local ok,err=pcall(f,.1,2,2);assert(not ok and string.find(err,'V_SUPPORT_UNKNOWN',1,true) and evaluated==before)
bad={2,2,2};ok,err=pcall(f,2,2,2);assert(not ok and string.find(err,'V_SUPPORT_UNKNOWN',1,true) and evaluated==before)
bad=nil;nonfinite={0,2,2};ok,err=pcall(f,.1,2,2);assert(not ok and string.find(err,'V_SUPPORT_NONFINITE',1,true) and evaluated==before)
"""
        result=subprocess.run([str(LUA),'-'],input=lua,text=True,capture_output=True,cwd=root,timeout=30,check=False)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_failure_context_precedes_long_paths(self):
        if not LUA.is_file(): self.skipTest('plain Lua unavailable')
        adapter = native_resource_path('scalar_field_adapter.lua').read_text(encoding='utf8')
        lua = """simion={pas={},experimental={}};function simion.early_access()end
local bad=false;local mask='mask'..string.rep('m',700);local scalar='scalar'..string.rep('s',700)
function simion.pas:open(path) return {symmetry='3dplanar',nx=7,ny=7,nz=7,dx_mm=1,dy_mm=1,dz_mm=1,debug_max_voltage=100,potential=function()return path==mask and (bad and 0 or 1) or 3 end,potential_vc=function()return 3 end,electrode=function()end}end
simion.experimental.field_array=function()return {efield=function()return 1,2,3 end}end
local adapter=(function()
""" + adapter + "\nend)()\n" + """
ion_number=47;ion_time_of_flight=12.5;ion_instance=9
local binding={mode='comsol_static_scalar_v',scalar_pa=scalar,valid_pa=mask,origin_mm={0,0,0},pitch_mm={1,1,1},dimensions={7,7,7},ideal_sheet_projection={}}
local f=adapter(binding,'raw_sample')
local function check(ok,err,kind) assert(not ok);local prefix=string.sub(err,1,400);assert(string.find(prefix,kind,1,true) and string.find(prefix,'world=',1,true) and string.find(prefix,'level=base',1,true) and string.find(prefix,'ion=47',1,true) and string.find(prefix,'elapsed_us=12.5',1,true) and string.find(prefix,'ion_instance=9',1,true),err) end
local ok,err=pcall(f,20,3,3);check(ok,err,'V_SUPPORT_BOX_OUTSIDE')
bad=true;ok,err=pcall(f,3,3,3);check(ok,err,'V_SUPPORT_UNKNOWN');bad=false
binding.ideal_sheet_projection={{instance_id='oa',electrode_group_id='g',member_id='sheet',unsupported_bounds_mm={{2,4},{2,4},{2,4}}}}
f=adapter(binding,'raw_sample');ok,err=pcall(f,3,3,3);check(ok,err,'V_UNREPRESENTED_SHEET')
"""
        result = subprocess.run([str(LUA), '-'], input=lua, text=True, capture_output=True,
                                cwd=root, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_sfi_identity_mask_pool_and_query_support(self):
        if not LUA.is_file(): self.skipTest('plain Lua unavailable')
        adapter = native_resource_path('scalar_field_adapter.lua').read_text(encoding='utf8')
        composer = native_resource_path('sfi_scalar_field.lua').read_text(encoding='utf8')
        lua = """simion={pas={},experimental={}}; function simion.early_access() end
local opens={};local invalid={};local checks={}
function simion.pas:open(path)
 opens[path]=(opens[path] or 0)+1
 return {symmetry='3dplanar',nx=7,ny=7,nz=7,dx_mm=1,dy_mm=1,dz_mm=1,debug_max_voltage=100,
 potential=function(self,i,j,k) if path:sub(1,1)=='m' then checks[path]=(checks[path] or 0)+1;return invalid[path] and 0 or 1 end return 3 end,
 potential_vc=function() return 3 end,electrode=function() end}
end
simion.experimental.field_array=function() return {efield=function() return 1,2,3 end} end
local adapter=(function()
""" + adapter + "\nend)()\nlocal composer=(function()\n" + composer + "\nend)()\n" + """
local function binding(v,m,hash,origin)
 return {mode='comsol_static_scalar_v',scalar_pa=v,valid_pa=m,origin_mm={origin,0,0},pitch_mm={1,1,1},dimensions={7,7,7},ideal_sheet_projection={},mask_identity={sha256=string.rep(hash,64),bytes=2800,frame_id='world'}}
end
local a=binding('v1','m1','a',0);local b=binding('v2','m2','a',0);local c=binding('v3','m3','a',0)
local kernel={compile_physical=function() return {differential_at=function() return 0 end} end};local pulse={is_active_at=function() return false end};local inst={scale=1,pa={dx_mm=1,dy_mm=1,dz_mm=1},wb_to_pa_orient=function(self,x,y,z)return x,y,z end}
local make=function(x,y,z) return composer.new(adapter,kernel,pulse,{carrier=x,rf_reference=y,pulse_delta=z},{phase_reference_instrument_time_us=0}) end
local sample=make(a,b,c);assert(opens.v1==1 and opens.v2==1 and opens.v3==1 and opens.m1==1 and opens.m2==nil and opens.m3==nil)
sample(inst,3,3,3,0);local count=checks.m1;assert(count==27);sample(inst,3,3,3,0);assert(checks.m1==count+27,'query support must be fresh')
local d=binding('v4','m4','b',0);local e=binding('v5','m5','a',1);local other=make(a,d,e);assert(opens.m4==1 and opens.m5==1,'different identity and grid must not share');invalid.m4=true
local ok,err=pcall(other,inst,3,3,3,0);assert(not ok and string.find(err,'V_SUPPORT_UNKNOWN',1,true),'zero RF coefficient must still check support')
"""
        result = subprocess.run([str(LUA), '-'], input=lua, text=True, capture_output=True,
                                cwd=root, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_composed_three_basis_and_shared_mask_support(self):
        if not LUA.is_file(): self.skipTest('plain Lua unavailable')
        adapter = native_resource_path('scalar_field_adapter.lua').read_text(encoding='utf-8')
        composer = native_resource_path('sfi_scalar_field.lua').read_text(encoding='utf-8')
        common = dict(mode='comsol_static_scalar_v', valid_pa='mask',
                      origin_mm=[-4.,-4.,-4.], pitch_mm=[1.,1.,1.], dimensions=[11,11,11])
        sheet = member(dict(kind='box', center_mm=[0.,0.,.5], size_mm=[2.,2.,0.]))
        unsupported = _ideal_sheet_projection({'members':[sheet]}, common, allow_partial=True)
        window_grid = dict(origin_mm=[-4.,-4.,-4.5], pitch_mm=[1.,1.,1.], dimensions=[11,11,11])
        aligned = _ideal_sheet_projection({'members':[sheet]}, window_grid)
        terms = []
        for index in range(3):
            terms.append(dict(common, scalar_pa='base'+str(index), coefficient=1.,
                ideal_sheet_projection=unsupported if index==2 else [],
                refinement_windows=[dict(name='sheet', active_box_mm=[[-1.,1.],[-1.,1.],[-1.,1.]],
                    mode='comsol_static_scalar_v',scalar_pa='win'+str(index), valid_pa='windowmask',
                    **window_grid,ideal_sheet_projection=aligned)]))
        binding = dict(response_terms=terms)
        sfi = {name:{key:value for key,value in term.items() if key!='coefficient'}
               for name,term in zip(('carrier','rf_reference','pulse_delta'),terms,strict=True)}
        lua = """simion={pas={},experimental={}}; function simion.early_access() end
local invalid=false; local evals=0; local maskopens=0
function simion.pas:open(path)
 if path=='mask' or path=='windowmask' then maskopens=maskopens+1 end
 return {symmetry='3dplanar',nx=11,ny=11,nz=11,dx_mm=1,dy_mm=1,dz_mm=1,debug_max_voltage=100,
 potential=function(self,i,j,k) if path=='mask' or path=='windowmask' then return invalid and 0 or 1 end return 7 end,
 potential_vc=function() evals=evals+1; return 7 end,electrode=function() end}
end
simion.experimental.field_array=function() return {efield=function() evals=evals+1; return 1,2,3 end} end
local adapter=(function()
""" + adapter + "\nend)()\nlocal composer=(function()\n" + composer + "\nend)()\nlocal binding=" + _lua_value(binding) + "\nlocal bindings=" + _lua_value(sfi) + """
local combined=adapter(binding,'raw_sample'); assert(maskopens==2)
local v,ex,ey,ez=combined(0,0,1); assert(v==21 and ex==3 and ey==6 and ez==9)
local before=evals; local ok,err=pcall(combined,0,0,1.01)
assert(not ok and string.find(err,'V_UNREPRESENTED_SHEET') and evals==before+4)
invalid=true;before=evals;ok,err=pcall(combined,0,0,0)
assert(not ok and string.find(err,'V_SUPPORT_UNKNOWN') and evals==before)
invalid=false
local inst={scale=1,pa={dx_mm=1,dy_mm=1,dz_mm=1},wb_to_pa_orient=function(self,x,y,z)return x,y,z end}
local kernel={compile_physical=function() return {differential_at=function() return 0 end} end}
local pulse={is_active_at=function() return false end}
local actual=composer.new(adapter,kernel,pulse,bindings,{phase_reference_instrument_time_us=0})
local x,y,z=actual(inst,0,0,1,0); assert(x==-1 and y==-2 and z==-3)
before=evals;ok,err=pcall(actual,inst,0,0,1.01,0)
assert(not ok and string.find(err,'V_UNREPRESENTED_SHEET') and evals==before+2)
invalid=true;before=evals;ok,err=pcall(actual,inst,0,0,0,0)
assert(not ok and string.find(err,'V_SUPPORT_UNKNOWN') and evals==before)
"""
        result = subprocess.run([str(LUA), '-'], input=lua, text=True, capture_output=True,
                                cwd=root, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_program_serializes_each_sheet_table(self):
        record = {'field_v': {'path': 'v'}, 'field_valid': {'path': 'mask'}}
        basis = {'bases': {n: {'grid': grid, 'records': record, 'ideal_sheet_projection': []}
                           for n in ('carrier', 'rf_reference', 'pulse_delta')},
                 'rf': {'waveform':'sine','frequency_hz':1.,'phase_rad':0.},
                 'clock': {'phase_reference_instrument_time_us':0.}}
        template = 'local single_flight_trace_path=\n    single_flight_frontend=single_flight_frontend_component.new\n  if instance==nil then return end\n  end\nend\nfunction segment.instance_adjust()'
        output = _instrument_common_scalar(template, basis, '', '', False)
        self.assertEqual(output.count('ideal_sheet_projection='), 3)

    def test_projection_and_real_lua_adapter(self):
        box = member(dict(kind='box', center_mm=[0.,0.,0.], size_mm=[2.,2.,0.]))
        disk = member(dict(kind='annulus', center_xy_mm=[0.,0.], z_min_mm=0., z_max_mm=0., inner_radius_mm=0., outer_radius_mm=1.))
        project = lambda m: _ideal_sheet_projection(dict(members=m), grid)
        self.assertEqual(project([]), [])
        rectangle, circle = project([box]), project([disk])
        self.assertEqual([(r['j_min'],r['i_min'],r['i_max']) for r in rectangle], [(1,1,3),(2,1,3),(3,1,3)])
        self.assertEqual([(r['j_min'],r['i_min'],r['i_max']) for r in circle], [(1,2,2),(2,1,3),(3,2,2)])
        bad = member(dict(kind='box',center_mm=[0.,0.,0.5],size_mm=[2.,2.,0.]))
        with self.assertRaisesRegex(ValueError, 'not aligned'): project([bad])
        disk['transform']['translation_mm']=[100.,0.,0.]
        self.assertEqual(project([disk]), [])
        if not LUA.is_file(): self.skipTest('plain Lua unavailable')
        adapter = native_resource_path('scalar_field_adapter.lua').read_text(encoding='utf-8')
        binding = dict(mode='comsol_static_scalar_v', scalar_pa='v', valid_pa='mask', origin_mm=grid['origin_mm'],
                       pitch_mm=grid['pitch_mm'], dimensions=grid['dimensions'], ideal_sheet_projection=circle)
        lua = """simion={pas={},experimental={}}; function simion.early_access() end
local marked=0; local invalid=false
function simion.pas:open(path) return {symmetry='3dplanar',nx=5,ny=5,nz=3,dx_mm=1,dy_mm=1,dz_mm=1,debug_max_voltage=100,
 potential=function(self,i,j,k) if path=='mask' then if invalid then return 0 else return 1 end end return 7 end,
 potential_vc=function() return 7 end, electrode=function() marked=marked+1 end} end
simion.experimental.field_array=function() return {efield=function() return 1,2,3 end} end
local adapter=(function()\n""" + adapter + "\nend)()\nlocal binding=" + _lua_value(binding) + """
local sample=adapter(binding,'raw_sample'); assert(marked==5); local v=sample(0,0,0); assert(v==7)
invalid=true; local ok,err=pcall(sample,0,0,0); assert(not ok and string.find(err,'V_SUPPORT_UNKNOWN'))
invalid=false; binding.ideal_sheet_projection={}; marked=0; adapter(binding,'raw_sample'); assert(marked==0)
binding.ideal_sheet_projection=""" + _lua_value(rectangle) + """; marked=0; adapter(binding,'raw_sample'); assert(marked==9)
"""
        result = subprocess.run([str(LUA), '-'], input=lua, text=True, capture_output=True,
                                cwd=root, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)


class ScalarRepresentationPreflightTests(unittest.TestCase):
    def test_partial_alignment_and_ordered_overlap(self):
        from msplatform.backends.simion.scalar_sample_binding import preflight_scalar_representation
        sheet=member(dict(kind='box',center_mm=[0.,0.,.5],size_mm=[2.,2.,0.]))
        projection=dict(assembly_frame_id='world',members=[sheet])
        base=dict(frame_id='world',origin_mm=[-4.,-4.,-4.],pitch_mm=[1.,1.,1.],dimensions=[11,11,11])
        aligned=dict(frame_id='world',origin_mm=[-4.,-4.,-4.5],pitch_mm=[1.,1.,1.],dimensions=[11,11,11])
        windows=[dict(name='first',active_box_mm=[[-1.,1.]]*3,grid=aligned),dict(name='second',active_box_mm=[[-.5,.5]]*3,grid=aligned)]
        with self.assertRaisesRegex(ValueError,'not aligned'):preflight_scalar_representation(projection,base,windows,allow_partial_sheets=False)
        result=preflight_scalar_representation(projection,base,windows,allow_partial_sheets=True)
        self.assertEqual([x['name'] for x in result['levels']],['base','first','second'])
        self.assertIn('unsupported_bounds_mm',result['levels'][0]['ideal_sheet_projection'][0])
        self.assertTrue(all(x['k']==5 for x in result['levels'][1]['ideal_sheet_projection']))
        self.assertEqual(result['scope'],'representation_only_no_mask_or_trajectory_claim')

    def test_invalid_grid_policy_shape_and_halo(self):
        import copy
        from msplatform.backends.simion.scalar_sample_binding import preflight_scalar_representation
        sheet=member(dict(kind='box',center_mm=[0.,0.,0.],size_mm=[2.,2.,0.]))
        projection=dict(assembly_frame_id='world',members=[sheet]);grid=dict(frame_id='world',origin_mm=[-4.,-4.,-4.],pitch_mm=[1.,1.,1.],dimensions=[11,11,11])
        window=dict(name='a',active_box_mm=[[-1.,1.]]*3,grid=grid)
        for key,value in [('frame_id','other'),('pitch_mm',[1.,0.,1.]),('origin_mm',[float('nan'),0.,0.]),('dimensions',[11,11,1])]:
            bad=copy.deepcopy(grid);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):preflight_scalar_representation(projection,bad,[],allow_partial_sheets=True)
        with self.assertRaises(ValueError):preflight_scalar_representation(projection,grid,[],allow_partial_sheets='yes')
        bad=copy.deepcopy(window);bad['active_box_mm']=[[-4.,1.],[-1.,1.],[-1.,1.]]
        with self.assertRaisesRegex(ValueError,'halo'):preflight_scalar_representation(projection,grid,[bad],allow_partial_sheets=True)
        with self.assertRaisesRegex(ValueError,'unique'):preflight_scalar_representation(projection,grid,[window,window],allow_partial_sheets=True)
        unsupported=copy.deepcopy(projection);unsupported['members'][0]['shape']={'kind':'unsupported'}
        with self.assertRaises(ValueError):preflight_scalar_representation(unsupported,grid,[],allow_partial_sheets=True)


    def test_disjoint_unsupported_orientation_and_two_node_capability(self):
        import copy
        from msplatform.backends.simion.scalar_sample_binding import preflight_scalar_representation
        grid=dict(frame_id='world',origin_mm=[-4.,-4.,-4.],pitch_mm=[1.,1.,1.],dimensions=[11,11,11])
        sheet=member(dict(kind='box',center_mm=[100.,0.,0.],size_mm=[0.,2.,2.]))
        projection=dict(assembly_frame_id='world',members=[sheet])
        result=preflight_scalar_representation(projection,grid,[],allow_partial_sheets=True)
        self.assertEqual(result['levels'][0]['ideal_sheet_projection'],[])
        intersect=copy.deepcopy(projection);intersect['members'][0]['shape']['center_mm'][0]=0.
        with self.assertRaisesRegex(ValueError,'orientation'):preflight_scalar_representation(intersect,grid,[],allow_partial_sheets=True)
        small=dict(frame_id='world',origin_mm=[0.,0.,0.],pitch_mm=[1.,1.,1.],dimensions=[3,3,2])
        report=preflight_scalar_representation(dict(assembly_frame_id='world',members=[]),small,[],allow_partial_sheets=True)
        self.assertFalse(report['levels'][0]['any_supported_stencil'])


if __name__ == '__main__':
    unittest.main()
