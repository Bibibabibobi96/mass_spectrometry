"""Focused published-product tests of explicit SFI scalar refinement."""
import copy,json,subprocess,unittest
from unittest.mock import patch
from pathlib import Path
from tests.contracts import test_sfi_scalar_binding as admission
from msplatform.backends.simion.sfi_scalar_binding import resolve_sfi_scalar_basis
from msplatform.backends.simion.standalone_pa_composition import PaHeader
from msplatform.results.artifacts import open_artifact
from tests.contracts.test_simion_prepared_model import LUA
from msplatform.backends.simion.resources import native_resource_path
from msplatform.backends.simion.tracking_program import _lua_value

class RefinementBindingTests(unittest.TestCase):
    # Reuse fixture construction without rediscovering the admission test suite.
    setUp = admission.SfiScalarAdmissionTests.setUp
    publish = admission.SfiScalarAdmissionTests.publish
    make_geometry = admission.SfiScalarAdmissionTests.make_geometry
    make_sample = admission.SfiScalarAdmissionTests.make_sample
    def test_real_adapter_first_match_and_no_mask_fallback(self):
        if not LUA.is_file(): self.skipTest('plain Lua unavailable')
        def binding(path):
            return dict(mode='comsol_static_scalar_v',scalar_pa=path,valid_pa=path+'mask',
                        origin_mm=[-2.,-2.,-2.],pitch_mm=[1.,1.,1.],dimensions=[7,7,7],ideal_sheet_projection=[])
        base=binding('base'); first=binding('first'); second=binding('second')
        first.update(name='first',active_box_mm=[[0.,.5]]*3)
        second.update(name='second',active_box_mm=[[0.,.5]]*3)
        base['refinement_windows']=[first,second]
        adapter=native_resource_path('scalar_field_adapter.lua').read_text(encoding='utf8')
        script="""simion={pas={},experimental={}}; function simion.early_access() end
local bad=false
function simion.pas:open(path) return {path=path,symmetry='3dplanar',nx=7,ny=7,nz=7,dx_mm=1,dy_mm=1,dz_mm=1,debug_max_voltage=100,
 potential=function() if bad and path=='firstmask' then return 0 end if string.find(path,'mask') then return 1 end return 7 end,
 potential_vc=function() if path=='first' then return 11 elseif path=='second' then return 22 else return 33 end end,
 electrode=function() end} end
simion.experimental.field_array=function() return {efield=function() return 1,2,3 end} end
local adapter=(function()\n"""+adapter+"\nend)()\nlocal binding="+_lua_value(base)+"""
local sample=adapter(binding,'raw_sample'); assert(sample(.25,.25,.25)==11); assert(sample(1,1,1)==33)
bad=true; local ok,err=pcall(sample,.25,.25,.25); assert(not ok and string.find(err,'V_SUPPORT_UNKNOWN'))
"""
        result=subprocess.run([str(LUA),'-'],input=script,text=True,capture_output=True,cwd=Path(__file__).resolve().parents[2],timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def sample_level(self,name,ref):
        item=open_artifact(ref,expected_kind='scalar_field_samples')
        data={}
        for key in item.data_records:
            if key=='field_solution_manifest':continue
            path=item.data_path(key)
            data[key]=path.read_bytes() if key in ('field_v','field_valid') else json.loads(path.read_text(encoding='utf8'))
        grid=data['grid'];grid.update(origin_mm=[-2.,-2.,-2.],pitch_mm=[1.,1.,1.],dimensions=[7,7,7],point_count=343,maximum_mm=[4.,4.,4.])
        data['report'].update(grid);data['report']['fem_valid']=343;data['report']['invalid_count']=0
        pa=PaHeader(-2,1,10000.,7,7,7,1<<28,1.,1.,1.).pack()+bytes(343*8)
        data['field_v']=pa;data['field_valid']=pa
        return self.publish(name,'scalar_field_samples',data,item.metadata,
            linked={'field_solution_manifest':item.data_records['field_solution_manifest'],
                    'field_solution_model':json.loads(item.manifest_location.read_text(encoding='utf8'))['inputs']['field_solution_model']})
    def resolve_windows(self,windows):
        return resolve_sfi_scalar_basis(model=self.model,geometry=self.geometry,field_design=self.design,
            flight=self.flight,geometry_artifact=self.geometry_ref,samples=self.sample_refs,refinement_windows=windows)
    def test_ordered_overlap_and_invalid_definitions(self):
        levels={name:self.sample_level('window-'+name,ref) for name,ref in self.sample_refs.items()}
        windows=[dict(name='first',active_box_mm=[[0.,.5]]*3,samples=levels),dict(name='second',active_box_mm=[[0.,.5]]*3,samples=levels)]
        result=self.resolve_windows(windows)
        for item in result['bases'].values():
            self.assertEqual([x['name'] for x in item['refinement_windows']],['first','second'])
            self.assertEqual(item['refinement_windows'][0]['active_box_mm'],[[0.,.5]]*3)
        bad=copy.deepcopy(windows);bad[1]['name']='first'
        with self.assertRaisesRegex(ValueError,'unique'):self.resolve_windows(bad)
        bad=copy.deepcopy(windows);bad[0]['active_box_mm']=[[-2.,-.5]]*3
        with self.assertRaisesRegex(ValueError,'halo'):self.resolve_windows(bad)
        bad=copy.deepcopy(windows);del bad[0]['samples']['carrier']
        with self.assertRaisesRegex(ValueError,'three explicit'):self.resolve_windows(bad)
        bad=copy.deepcopy(windows);bad[0]['samples']['carrier']=levels['rf_reference']
        with self.assertRaises(ValueError):self.resolve_windows(bad)
        bad=copy.deepcopy(windows)
        record=bad[0]['samples']['carrier']['manifest']
        record['sha256']='0'*64 if record['sha256'] != '0'*64 else '1'*64
        with self.assertRaises((ValueError,AssertionError)):
            self.resolve_windows(bad)

class RefinementOwnerTests(unittest.TestCase):
    def test_historical_window_basis_rejects_tracking_before_owner(self):
        import tempfile
        from tests.contracts.test_sfi_recorded_birth_entry import historical_fixture
        from msplatform.workflows.single_reflection_flight.recorded_birth import track_recorded_birth
        case=RefinementBindingTests(methodName='runTest');case.setUp();self.addCleanup(case.doCleanups)
        levels={name:case.sample_level('retired-window-'+name,ref) for name,ref in case.sample_refs.items()}
        windows=[dict(name='first',active_box_mm=[[0.,.5]]*3,samples=levels),
                 dict(name='repeat_first',active_box_mm=[[0.,.5]]*3,samples=copy.deepcopy(levels))]
        admitted=case.resolve_windows(windows)
        for basis in admitted['bases'].values():
            self.assertEqual([row['name'] for row in basis['refinement_windows']],['first','repeat_first'])
        with tempfile.TemporaryDirectory() as directory:
            selected,receipt,_=historical_fixture(Path(directory))
            selected['scalar_field_basis']=dict(geometry_artifact=case.geometry_ref,samples=case.sample_refs,
                                                refinement_windows=windows)
            with patch('msplatform.execution.owner.run_managed_stage') as owner:
                for recovery in (None,{'path':str(Path(directory)/'unused-recovery.json')}):
                    with self.assertRaisesRegex(ValueError,'legacy composite.*read-only'):
                        track_recorded_birth(**selected,recovery_reference=recovery)
                    owner.assert_not_called()
                source=Path(receipt['input_records']['particle_source']['path']);original=source.read_bytes()
                try:
                    source.write_bytes(original+b'\n')
                    with self.assertRaisesRegex(AssertionError,'byte count changed'):
                        track_recorded_birth(**selected)
                    owner.assert_not_called()
                finally:source.write_bytes(original)
        item=open_artifact(levels['carrier'],expected_kind='scalar_field_samples')
        path=item.data_path('field_v');original=path.read_bytes()
        try:
            path.write_bytes(original+b'\x00')
            with self.assertRaises((AssertionError,ValueError)):
                case.resolve_windows(windows)
        finally:path.write_bytes(original)
