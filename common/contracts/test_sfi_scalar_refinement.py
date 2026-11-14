"""Focused published-product tests of explicit SFI scalar refinement."""
import copy,json,subprocess,unittest
from unittest.mock import patch
from pathlib import Path
from common.contracts import test_sfi_scalar_binding as admission
from msplatform.backends.simion.sfi_scalar_binding import resolve_sfi_scalar_basis
from msplatform.backends.simion.standalone_pa_composition import PaHeader
from msplatform.results.artifacts import open_artifact
from msplatform.io.manifest_records import record_path, verify_record
from common.contracts.test_simion_prepared_model import LUA
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
    def test_registered_owner_guards_windows_and_recovery(self):
        import os, sys
        from msplatform.execution import run_session
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.resources import resource_path
        from msplatform.backends.simion import model_execution
        from msplatform.workflows.single_reflection_flight.recorded_birth import track_recorded_birth
        from common.contracts.test_support.sfi_scalar_owner_fixture import make_fixture, inert_native_leaf, retained_owner_directory
        with retained_owner_directory() as directory:
            selected=make_fixture(Path(directory),refinement_windows=True); values=selected['context']
            context=ExecutionContext(workspace=Path(values['workspace']),python_executable=Path(sys.executable),
                powershell_executable=Path(values['powershell_executable']),tools={'simion':Path(sys.executable)},
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
                policy_path=resource_path('host_resource_policy.json'),capacity_policy_path=Path(values['capacity_policy_path']),
                stage_policy_path=Path(values['stage_policy_path']))
            selection=selected['scalar_field_basis']
            windows=selection['refinement_windows']
            self.assertEqual(windows[0]['samples'],windows[2]['samples'])
            self.assertNotEqual(windows[0]['samples'],windows[1]['samples'])
            window_samples=[ref for window in windows[:2] for ref in window['samples'].values()]
            args=dict(preparation_manifest=selected['preparation_manifest'],fields=selected['fields'],
                species_id=selected['species_id'],expected_particle_ids=selected['expected_particle_ids'],
                observations={'plane_observations':[]},context=context,scalar_field_basis=selection)
            observed=[]; leaf=inert_native_leaf(run_session.run_observed_process,observed)
            protected=[]; original_protect=model_execution._protected_source
            def record_protection(session, manifest, *, required_paths=()):
                protected.append((Path(manifest['path']).resolve(), {Path(path).resolve() for path in required_paths}))
                return original_protect(session,manifest,required_paths=required_paths)
            inherited=dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='',MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                           MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='')
            with patch.dict(os.environ,inherited),patch.object(run_session,'run_observed_process',side_effect=leaf), \
                    patch.object(model_execution,'_protected_source',side_effect=record_protection):
                result=track_recorded_birth(**args)
                self.assertEqual(len(observed),3)
                paths={open_artifact(ref,expected_kind='scalar_field_samples').data_path(key).resolve()
                       for ref in window_samples for key in ('field_v','field_valid','grid')}
                base_paths={open_artifact(ref,expected_kind='scalar_field_samples').data_path(key).resolve()
                            for ref in selection['samples'].values() for key in ('field_v','field_valid','grid')}
                self.assertTrue(paths.isdisjoint(base_paths))
                self.assertEqual(len(paths),18)
                for operation in observed:
                    records=operation['immutable_input_records']; actual=[Path(r['path']).resolve() for r in records]
                    self.assertTrue(paths <= set(actual)); self.assertEqual(len(actual),len(set(actual)))
                run=result.manifest_location.parent
                program_path=run/'simion/tracking/instrument.lua'
                manifest=json.loads(result.manifest_location.read_text(encoding='utf8'))
                records=[r for r in manifest['outputs'] if record_path(r,base_dir=run)==program_path]
                self.assertEqual(len(records),1)
                verify_record('published tracking program',records[0],base_dir=run)
                program=program_path.read_text(encoding='utf8')
                self.assertIn('refinement_windows',program)
                self.assertLess(program.index('name='+_lua_value('first')),program.index('name='+_lua_value('second')))
                self.assertLess(program.index('name='+_lua_value('second')),program.index('name='+_lua_value('repeat_first')))
                for ref in window_samples:
                    item=open_artifact(ref,expected_kind='scalar_field_samples')
                    for key in ('field_v','field_valid'):
                        self.assertIn(_lua_value(str(item.data_path(key))),program)
                for ref in window_samples:
                    item=open_artifact(ref,expected_kind='scalar_field_samples')
                    required={item.data_path(key).resolve() for key in ('field_v','field_valid','grid')}
                    self.assertTrue(any(path==item.manifest_location.resolve() and required <= members for path,members in protected))
                    source=Path(item.data_records['field_solution_manifest']['path']).resolve()
                    self.assertTrue(any(path==source for path,_ in protected))
                reused=track_recorded_birth(**args,recovery_reference=result.reference['manifest'])
                self.assertEqual(reused.metadata['reused_unit_count'],1); self.assertEqual(len(observed),3)
                path=Path(selected['tamper_scalar_window_pa'])
                before=path.read_bytes()
                try:
                    path.write_bytes(bytes([before[0]^1])+before[1:])
                    with self.assertRaises((AssertionError,ValueError)): track_recorded_birth(**args)
                    self.assertEqual(len(observed),3)
                finally: path.write_bytes(before)
