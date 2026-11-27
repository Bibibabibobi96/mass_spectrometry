"""Inert native-process leaf for OA focus; no solver accuracy is implied."""
import json
import math
from pathlib import Path
import subprocess
import tempfile
import sys

from msplatform.io.manifest_records import file_record


def run_leaf(actual_process, context, **kwargs):
    """Use actual monitored Python process, replacing only proprietary output format."""
    run = kwargs['working_directory']
    args = kwargs['arguments']
    joined = ' '.join(str(value) for value in args)
    output = 'INERT_NOT_SIMION\n'
    if 'build_frontend_geometry.lua' in joined:
        geometry = json.loads((run/'inputs/compiled_geometry.json').read_text(encoding='utf-8'))['frontend_geometry']
        domain = geometry['numerical_domains']['oa']
        dims = [domain['dimensions']['n'+axis] for axis in 'xyz']
        pitch = [domain['cell_mm_xyz'][axis] for axis in 'xyz']
        (run/'simion/geometry/oa.pa#').write_bytes(b'INERT_RAW_NOT_PA')
        (run/'results/oa_surface.csv').write_text('0,0,0,0.25,nil,nil\n')
        (run/'results/oa_surface_state.json').write_text(json.dumps(dict(schema_version=1,mode='empty',grid=dims,pitch=pitch,scanned_nodes=math.prod(dims),offset_nodes=0)))
        output += 'BUILD_GEOMETRY=PASS ROLE=oa\n'
    elif 'build_geometry_iob.lua' in joined:
        mode = args[-2]
        if mode == 'build_geometry':
            (run/'simion/geometry/geometry.iob').write_bytes(b'INERT_IOB')
            (run/'simion/geometry/geometry.fly2').write_text('particles{coordinates=0,}\n')
            (run/'simion/geometry/iob_seed/iob_seed_placeholder_01.pa0').write_bytes(b'INERT_SEED')
        output += 'INDEPENDENT_OA_GEOMETRY_IOB'+('_REOPEN' if mode=='verify_geometry' else '')+'=PASS\n'
    elif '-RequestPath' in args:
        request = json.loads(Path(args[args.index('-RequestPath')+1]).read_text(encoding='utf-8-sig'))
        outputs=[]; releases={}
        for item in request['copies']:
            original=item['source_record']; target=Path(item['destination']);target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(Path(original['path']).read_bytes()); actual=file_record(target,original['retention_role']);outputs.append(actual)
            for record in (original,actual): releases[record['path']]=dict(record,write_delete_guarded=False)
        Path(request['receipt_path']).write_text(json.dumps(dict(schema_version=1,role='payload_materialization',status='success',primary=None,secondary_errors=[],outputs=outputs,source_and_destination_releases=list(releases.values()))))
    elif 'build_model_iob.lua' in joined:
        mode=args[-2]
        if mode=='build_model':
            (run/'simion/geometry/geometry.iob').write_bytes(b'INERT_IOB')
            (run/'simion/geometry/geometry.fly2').write_text('particles{coordinates=0,}\n')
            (run/'simion/geometry/iob_seed/iob_seed_placeholder_01.pa0').write_bytes(b'INERT_SEED')
        else:(run/'results/model_drive_readback.txt').write_text('INERT_NOT_NATIVE')
        output+='INDEPENDENT_OA_MODEL_'+('BUILD' if mode=='build_model' else 'READBACK')+'=PASS\n'
    elif 'refine_rf_field_family.lua' in joined:
        from msplatform.backends.simion.rf_field_execution import _domain_labels
        model=json.loads((run/'inputs/compiled_model.json').read_text())
        labels=_domain_labels(model['geometry']['frontend_geometry'],'oa')
        raw=run/'simion/fields/oa/oa.pa#'
        for eid in [0,*labels]:raw.with_suffix('.pa'+str(eid)).write_bytes(b'INERT_RESPONSE')
        output+='INDEPENDENT_RF_REFINE=PASS\n'
    elif 'audit_rf_field_family.lua' in joined:
        (run/'results/rf_field_audit.json').write_text(json.dumps(dict(role='simion_rf_fractional_field_audit',status='success',checked_domains=['oa'],fixture='INERT_ONLY')))
        output+='INDEPENDENT_RF_FIELDS_READBACK=PASS\n'
    elif 'build_tracking_iob.lua' in joined:
        mode=args[-2];native_root=Path(args[-3]).parent.parent
        if mode=='build':
            (native_root/'simion/tracking/instrument.iob').write_bytes(b'INERT_IOB')
            (native_root/'simion/geometry/iob_seed/iob_seed_placeholder_01.pa0').write_bytes(b'INERT_SEED')
        output+='INDEPENDENT_OA_TRACKING_IOB'+('_REOPEN' if mode=='verify' else '')+'=PASS\n'
    elif 'fly' in args:
        output += focus_lua_output(run)
    else:
        raise AssertionError('unhandled inert focus native operation: '+joined)
    return actual_process(context,**dict(kwargs,executable=Path(sys.executable),arguments=['-I','-c','print('+repr(output)+')']))


def focus_lua_output(run):
    """Run generated callbacks under Lua with inert SIMION globals and TestPlane."""
    from tests.contracts.test_simion_prepared_model import LUA
    rows=json.loads((run/'inputs/canonical_source_states.json').read_text(encoding='utf-8'))
    program=(run/'simion/tracking/instrument.lua').read_text(encoding='utf-8')
    head="simion={workbench_program=function() segment={} end,import=function() return function(...) return {tstep_adjust=function() end,other_actions=function() end} end end};sim_grouped=1;adj_elect={};ion_instance=1;ion_run=1;ion_time_of_birth=0;ion_time_step=.05;ion_splat=0;ion_time_of_flight=0;\n"
    tail='\nsegment.initialize_run()\n'
    for ion,row in enumerate(rows,1):
        tail += f"ion_number={ion};ion_splat=0;ion_time_of_flight=0;ion_mass={row['mass_amu']!r};ion_charge={row['charge_state']!r};\n"
        tail += ''.join(f"ion_p{axis}_mm={row['position_'+axis+'_mm']!r};ion_v{axis}_mm={row['velocity_'+axis+'_m_s']/1000!r};\n" for axis in 'xyz')
        tail += 'segment.initialize();segment.other_actions();ion_time_of_flight=.05;ion_pz_mm=-1;segment.other_actions();segment.terminate()\n'
    with tempfile.TemporaryDirectory(prefix='inert-focus-lua-') as directory:
        script=Path(directory)/'callback.lua';script.write_text(head+program+tail,encoding='utf-8',newline='\n')
        process=subprocess.run([str(LUA),str(script)],capture_output=True,text=True,timeout=30,check=True,cwd=script.parent)
    return process.stdout+f'\nstatus,Fly completed. {len(rows)} splats\n'
