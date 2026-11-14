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

if __name__ == '__main__': unittest.main()
