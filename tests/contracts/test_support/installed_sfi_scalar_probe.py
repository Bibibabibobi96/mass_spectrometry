"""Installed public SFI scalar consumer through the managed owner, inert native leaf.

Fixture inputs are generated before source denial from one real provider Assembly.
All model/field/solution files are synthetic test data, not commercial evidence.
"""
import json
import os
from pathlib import Path
import sys
import sysconfig
import subprocess
from unittest.mock import patch


def run(fixture, leaf, timer, arm, blocked_roots):
    """Run one isolated arm against its own published fixture and inert native leaf."""
    from msplatform.backends.simion import resources, sfi_scalar_binding, tracking_execution
    from msplatform.execution import run_session
    from msplatform.results.artifacts import open_artifact
    from msplatform.execution.context import ExecutionContext
    from msplatform.execution.resources import resource_path
    from msplatform.io.manifest_records import record_path, verify_record
    from msplatform.workflows.single_reflection_flight import recorded_birth

    purelib=Path(sysconfig.get_paths()['purelib']).resolve()
    for module, relative in ((recorded_birth,'workflows/single_reflection_flight/recorded_birth.py'),
                             (sfi_scalar_binding,'backends/simion/sfi_scalar_binding.py'),
                             (tracking_execution,'backends/simion/tracking_execution.py')):
        assert Path(module.__file__).resolve()==purelib/'msplatform'/relative
    c=fixture['context']; context=ExecutionContext(workspace=Path(c['workspace']),python_executable=Path(sys.executable),
        powershell_executable=Path(c['powershell_executable']),tools={'simion':Path(sys.executable)},
        host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
        policy_path=resource_path('host_resource_policy.json'),capacity_policy_path=Path(c['capacity_policy_path']),
        stage_policy_path=Path(c['stage_policy_path']))
    selection=fixture['scalar_field_basis']; observed=[]
    call=dict(preparation_manifest=fixture['preparation_manifest'],fields=fixture['fields'],
              species_id=fixture['species_id'],expected_particle_ids=fixture['expected_particle_ids'],
              observations={'plane_observations':[]},context=context,scalar_field_basis=selection)
    private=dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='',MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                 MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='')
    with timer('sfi_scalar_managed_consumer',str(arm)), patch.dict(os.environ,private), \
         patch.object(run_session,'run_observed_process',side_effect=leaf(run_session.run_observed_process,observed)):
        result=recorded_birth.track_recorded_birth(**call)
    assert observed, 'actual managed owner did not reach inert native leaf'
    expected_scalar_paths=set()
    for reference in selection['samples'].values():
        selected_sample=open_artifact(reference,expected_kind='scalar_field_samples')
        expected_scalar_paths.update(selected_sample.data_path(key).resolve() for key in ('field_v','field_valid','grid'))
    windows=selection.get('refinement_windows',[])
    if windows:
        assert [window['name'] for window in windows]==['first','second','repeat_first']
        assert windows[0]['samples']==windows[2]['samples']
        assert windows[0]['samples']!=windows[1]['samples']
        for window in windows[:2]:
            for reference in window['samples'].values():
                sample=open_artifact(reference,expected_kind='scalar_field_samples')
                expected_scalar_paths.update(sample.data_path(key).resolve() for key in ('field_v','field_valid','grid'))
        assert len(expected_scalar_paths)==27, len(expected_scalar_paths)
    assert len(observed)==3, len(observed)
    for item in observed:
        options=item[0] if isinstance(item,tuple) else item
        records=options['immutable_input_records']
        paths=[Path(row['path']).resolve() for row in records]
        assert len(paths)==len(set(paths)), 'native immutable inputs contain duplicate paths'
        assert expected_scalar_paths <= set(paths), expected_scalar_paths-set(paths)
    assert result.kind=='trajectory_result'
    run=result.manifest_location.parent
    manifest=json.loads(result.manifest_location.read_text(encoding='utf8'))
    assert manifest['status']=='success'
    completion=json.loads((run/'results/execution_completion.json').read_text(encoding='utf8'))
    releases=completion['writer_completion']['resource_releases']
    assert releases, 'owner host release evidence missing'
    for row in releases:
        host=row['completion_receipt']['host_release']
        assert host['inherited'] is False and host['error'] is None
        assert host['result']=={'status':'released','token':host['token']}
    inputs=manifest['inputs']
    for basis in ('carrier','rf_reference','pulse_delta'):
        for key in ('field_v','field_valid','grid'):
            assert 'scalar_'+basis+'_'+key in inputs
    for name in ('scalar_field_adapter.lua','sfi_scalar_field.lua','rf_drive.lua','single_flight_pulse_hook.lua'):
        key='resource_'+name
        assert key in inputs and Path(inputs[key]['path']).is_file(), key
        installed=resources.native_resource_path(name)
        assert installed.resolve().is_relative_to(purelib),name
        assert Path(inputs[key]['path']).read_bytes()==installed.read_bytes(),name
    # The owner binds producer references through this verified frozen document.
    basis_record=inputs['scalar_field_basis']
    verify_record('installed scalar basis',basis_record,base_dir=run)
    basis=json.loads(record_path(basis_record,base_dir=run).read_text(encoding='utf8'))
    assert basis['geometry_reference']==selection['geometry_artifact']
    assert set(basis['bases'])==set(selection['samples'])
    for name,entry in selection['samples'].items():
        assert basis['bases'][name]['reference']==entry,name
    if windows:
        from msplatform.backends.simion.tracking_program import _lua_value
        request=json.loads((run/'inputs/execution_request.json').read_text(encoding='utf8'))
        sources=request['capacity']['source_references']
        for name in ('carrier','rf_reference','pulse_delta'):
            levels=basis['bases'][name]['refinement_windows']
            assert [level['name'] for level in levels]==['first','second','repeat_first']
            for index,window in enumerate(windows):
                assert levels[index]['reference']==window['samples'][name]
            assert levels[0]['reference']==levels[2]['reference'] and levels[0]['reference']!=levels[1]['reference']
            for level in levels[:2]:
                ref=level['reference']['manifest']
                assert sum(row.get('manifest_record')==ref for row in sources)==1
                for key in ('field_v','field_valid','grid'):
                    assert inputs['scalar_'+name+'_window_'+str(levels.index(level)+1)+'_'+key]==level['records'][key]
        program_path=run/'simion/tracking/instrument.lua'
        program_records=[row for row in manifest['outputs'] if record_path(row,base_dir=run)==program_path]
        assert len(program_records)==1
        verify_record('installed scalar tracking program',program_records[0],base_dir=run)
        program=program_path.read_text(encoding='utf8')
        positions=[program.index('name='+_lua_value(window['name'])) for window in windows]
        assert positions==sorted(positions) and len(set(positions))==3
    collection=json.loads(result.data_path('collection').read_text(encoding='utf8'))
    assert collection['original_mother']['mother_particle_ids']==fixture['expected_particle_ids']
    # Whole-unit recovery must retain the same basis and mother, with no native replay.
    with patch.dict(os.environ,private), patch.object(run_session,'run_observed_process',side_effect=AssertionError('unexpected recovery native leaf')):
        recovered=recorded_birth.track_recorded_birth(**call,recovery_reference=result.reference['manifest'])
    assert recovered.kind=='trajectory_result' and recovered.metadata['reused_unit_count']==1
    recovered_collection=json.loads(recovered.data_path('collection').read_text(encoding='utf8'))
    assert recovered_collection['original_mother']['mother_particle_ids']==fixture['expected_particle_ids']
    assert json.loads(recovered.manifest_location.read_text(encoding='utf8'))['status']=='success'
    # Changed or missing scalar input must be refused before the inert leaf.
    for mode in ('tamper','missing'):
        selected=Path(fixture['tamper_scalar_pa']); original=selected.read_bytes()
        try:
            if mode=='tamper': selected.write_bytes(original+b'\x00')
            else: selected.unlink()
            with patch.object(run_session,'run_observed_process',side_effect=AssertionError('unexpected native leaf')):
                try: recorded_birth.track_recorded_birth(**call)
                except AssertionError as error:
                    expected='byte count changed' if mode=='tamper' else 'is missing'
                    assert expected in str(error),str(error)
                else: raise AssertionError('changed scalar PA accepted')
        finally: selected.write_bytes(original)
        assert selected.read_bytes()==original
    if windows:
        selected=Path(fixture['tamper_scalar_window_pa']); original=selected.read_bytes()
        try:
            selected.write_bytes(original+b'\x00')
            with patch.object(run_session,'run_observed_process',side_effect=AssertionError('unexpected native leaf')):
                try: recorded_birth.track_recorded_birth(**call)
                except AssertionError as error:
                    assert 'byte count changed' in str(error) and str(selected) in str(error),str(error)
                else: raise AssertionError('changed window-only scalar PA accepted')
        finally: selected.write_bytes(original)
        assert selected.read_bytes()==original
    # Physical removal is confined to this arm and restored byte-for-byte.
    for name in ('scalar_field_adapter.lua','sfi_scalar_field.lua'):
        resource=resources.native_resource_path(name); original=resource.read_bytes()
        try:
            resource.unlink()
            code = r'''import importlib.abc,json,os,pathlib,sys
blocked=[pathlib.Path(p).resolve() for p in json.loads(sys.argv[2])]
def deny(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes)):
  p=pathlib.Path(os.fsdecode(args[0])).resolve()
  if any(p.is_relative_to(root) for root in blocked): raise AssertionError('author read: '+str(p))
sys.addaudithook(deny)
class Guard(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'common','projects','integrations'}: raise AssertionError('author import: '+fullname)
sys.meta_path.insert(0,Guard())
from msplatform.backends.simion.resources import native_resource_path
try: native_resource_path(sys.argv[1])
except FileNotFoundError as error:
 assert sys.argv[1] in str(error),str(error)
 print('MISSING_SCALAR_RESOURCE=PASS')
else: raise AssertionError('missing resource accepted')
'''
            child=subprocess.run([sys.executable,'-I','-B','-c',code,name,json.dumps([str(p) for p in blocked_roots])],
                cwd=Path(c['workspace']),capture_output=True,text=True,encoding='utf8',timeout=30,check=False)
            assert child.returncode==0 and 'MISSING_SCALAR_RESOURCE=PASS' in child.stdout,(child.stdout,child.stderr)
        finally: resource.write_bytes(original)
        assert resource.read_bytes()==original
    for name,module in tuple(sys.modules.items()):
        if (name=='msplatform' or name.startswith('msplatform.')) and getattr(module,'__file__',None):
            assert Path(module.__file__).resolve().is_relative_to(purelib),name
    print('INSTALLED_SFI_SCALAR_OWNER=PASS native=INERT arm='+str(arm),flush=True)
