"""Public RF-IP Store owner integration; vendor leaf is explicitly inert."""
import json
import os
import copy
import sys
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from msplatform.recipes import load_recipe
from msplatform.io.manifest_records import file_record
from msplatform.workflows.native_tracing import run_loaded_recipe
from tests.contracts.test_support.rf_ip_native_recipe import write_rf_ip_recipe_fixture


class PublicRfIpStoreTests(unittest.TestCase):
    @patch.dict(os.environ, {'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':''})
    def test_rf_ip_public_store_owner_chain(self):
        from tests.contracts.test_execution_runtime import NormalOwnerTests
        from msplatform.execution.capacity_ledger import initialize_capacity_ledger
        with (nullcontext(tempfile.mkdtemp(prefix='rf-ip-recovery-', dir=os.environ['RF_IP_TEST_EVIDENCE_ROOT']))
              if os.environ.get('RF_IP_TEST_EVIDENCE_ROOT') else tempfile.TemporaryDirectory()) as directory:
            root=Path(directory);helper=NormalOwnerTests();context=helper._context(root)
            capacity=root/'capacity.json';capacity.write_text(json.dumps(helper._policy()))
            binary=root/'inert-simion.exe';binary.write_bytes(b'INERT_NOT_SIMION')
            stage=dict(limits=dict(wall_clock_seconds=120,transient_run_directory_bytes=128*1024**2,
                process_tree_working_set_bytes=1024**3,minimum_system_available_memory_bytes=1,
                compact_final_retained_bytes=128*1024**2,automatic_retry_count=0),
                artifact_retention=dict(policy_version=1,**{'class':'solver_review'},reason='inert RF-IP'))
            stages={name:copy.deepcopy(stage) for name in ('build_geometry','prepare_model','solve_fields','track')}
            stages['solve_fields']['limits']['reserved_run_payload_bytes']=0
            policy=root/'stages.json';policy.write_text(json.dumps(dict(schema_version=1,role='execution_stage_policy',stages=stages)))
            context=replace(context,capacity_policy_path=capacity,stage_policy_path=policy,tools={'simion':binary})
            artifact_root=context.workspace/'artifacts';artifact_root.mkdir(parents=True);initialize_capacity_ledger(artifact_root,objects=[])
            loaded=load_recipe(write_rf_ip_recipe_fixture(root/'author'));calls=[];fail_unit=[False];group_sizes=[]
            from msplatform.execution import run_session
            actual_process=run_session.run_observed_process
            def observed(_context,**kw):
                args=kw['arguments'];run=kw['working_directory'];joined=' '.join(args);out='INERT_NOT_SIMION\n'
                if 'build_frontend_geometry.lua' in joined:
                    (run/'simion/geometry/parent.pa#').write_bytes(b'inert')
                    (run/'simion/geometry/parent.pa-surf').write_bytes(b'inert')
                    (run/'results/parent_surface.csv').write_text('0,0,0,0.25,nil,nil\n')
                    out+='BUILD_GEOMETRY=PASS ROLE=parent\n'
                elif 'build_geometry_iob.lua' in joined:
                    mode=args[-2]
                    if mode=='build_geometry':
                        (run/'simion/geometry/geometry.iob').write_bytes(b'inert')
                        (run/'simion/geometry/geometry.fly2').write_text('particles{coordinates=0,}\n')
                        (run/'simion/geometry/iob_seed/iob_seed_placeholder_01.pa0').write_bytes(b'inert')
                    out+='RF_IP_GEOMETRY_IOB'+('_REOPEN' if mode=='verify_geometry' else '')+'=PASS\n'
                elif '-RequestPath' in args:
                    selected=json.loads(Path(args[args.index('-RequestPath')+1]).read_text(encoding='utf-8-sig')); outputs=[]; releases={}
                    for item in selected['copies']:
                        original=item['source_record'];target=Path(item['destination']);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(Path(original['path']).read_bytes())
                        actual=file_record(target,original['retention_role']);outputs.append(actual)
                        for rec in (original,actual):releases[rec['path']]=dict(rec,write_delete_guarded=False)
                    Path(selected['receipt_path']).write_text(json.dumps(dict(schema_version=1,role='payload_materialization',status='success',primary=None,secondary_errors=[],outputs=outputs,source_and_destination_releases=list(releases.values()))))
                elif 'build_model_iob.lua' in joined:
                    mode=args[-2]
                    if mode=='build_model':
                        (run/'simion/geometry/geometry.iob').write_bytes(b'inert')
                        (run/'simion/geometry/geometry.fly2').write_text('particles{coordinates=0,}\n')
                        (run/'simion/geometry/iob_seed/iob_seed_placeholder_01.pa0').write_bytes(b'inert')
                    else:(run/'results/model_drive_readback.txt').write_text('INERT_NOT_NATIVE')
                    out+='RF_IP_MODEL_'+('BUILD' if mode=='build_model' else 'READBACK')+'=PASS\n'
                elif 'refine_rf_field_family.lua' in joined:
                    from msplatform.backends.simion.rf_field_execution import _domain_labels
                    model=json.loads((run/'inputs/compiled_model.json').read_text())
                    labels=_domain_labels(model['geometry']['frontend_geometry'],'parent')
                    raw=run/'simion/fields/parent/parent.pa#'
                    for eid in [0,*labels]:raw.with_suffix('.pa'+str(eid)).write_bytes(b'inert')
                    out+='INDEPENDENT_RF_REFINE=PASS\n'
                elif 'audit_rf_field_family.lua' in joined:
                    (run/'results/rf_field_audit.json').write_text(json.dumps(dict(role='simion_rf_fractional_field_audit',status='success',checked_domains=['parent'],fixture='INERT_ONLY')))
                    out+='INDEPENDENT_RF_FIELDS_READBACK=PASS\n'
                elif 'build_tracking_iob.lua' in joined:
                    mode=args[-2]
                    native_root=Path(args[-3]).parent.parent
                    if mode=='build':
                        (native_root/'simion/tracking/instrument.iob').write_bytes(b'inert')
                        (native_root/'simion/geometry/iob_seed/iob_seed_placeholder_01.pa0').write_bytes(b'inert')
                    out+='RF_IP_TRACKING_IOB'+('_REOPEN' if mode=='verify' else '')+'=PASS\n'
                elif 'fly' in args:
                    from tests.contracts.test_support.terminal_evidence_fixture import native_run_from_program, terminal_wire_lines
                    rows=json.loads((run/'inputs/canonical_source_states.json').read_text())
                    token=native_run_from_program(run/'simion/tracking/instrument.lua')
                    lines=['RF_DYNAMICS_V1: {"grouped":0,"repulsion":"none","relativity":0,"segment_global":1}']
                    for ion,row in enumerate(rows,1):
                        state=dict(event='source_release',reason='none',particle_id=row['particle_id'],ion=ion,
                            instrument_time_us=row['instrument_time_us'],mass_amu=row['mass_amu'],charge_state=row['charge_state'],instance=1)
                        state.update({axis+'_mm':row['position_'+axis+'_mm'] for axis in 'xyz'})
                        state.update({'v'+axis+'_mm_per_us':row['velocity_'+axis+'_m_s']/1000 for axis in 'xyz'})
                        lines.extend(terminal_wire_lines(row,ion,token,2.,1))
                        lines.extend(['RF_NATIVE_STATE_V1: '+json.dumps(state),'RF_NATIVE_STATE_V1: '+json.dumps(dict(state,event='terminal',reason='unknown',instrument_time_us=2.))])
                    out+='\n'.join(lines)+f'\nstatus,Fly completed. {len(rows)} splats\n'
                else:
                    raise AssertionError('inert test leaf has not implemented '+joined)
                calls.append(args)
                if 'build_tracking_iob.lua' in joined:
                    return actual_process(_context, **dict(kw, executable=Path(sys.executable),
                        arguments=['-I','-c','print('+repr(out)+')']))
                for name in ('stdout_path','stderr_path','usage_path'):kw[name].write_text(out if name=='stdout_path' else '{}')
                return dict(observation=dict(exit_code=0,root_process_id=os.getpid(),root_process_started_at_utc_ticks=12345),host_release=dict(inherited=False,token='inert',error=None,result=dict(status='released',token='inert')))
            actual_group=run_session.run_observed_process_group
            def inert_group(actual_context,**kw):
                from tests.contracts.test_support.terminal_evidence_fixture import native_run_from_program, terminal_wire_lines
                full_rows=json.loads((kw['run_directory']/'inputs/canonical_source_states.json').read_text())
                prepared=[]
                for spec in kw['specifications']:
                    item=dict(spec);batch=spec['scheduler_batch'];lo=batch['particle_id_min']-1;hi=batch['particle_id_max']
                    rows=full_rows[lo:hi];unit_root=Path(spec['arguments'][-1]).parents[2]
                    token=native_run_from_program(unit_root/'simion/tracking/instrument.lua')
                    lines=['RF_DYNAMICS_V1: {"grouped":0,"repulsion":"none","relativity":0,"segment_global":1}']
                    for ion,row in enumerate(rows,1):
                        state=dict(event='source_release',reason='none',particle_id=row['particle_id'],ion=ion,
                            instrument_time_us=row['instrument_time_us'],mass_amu=row['mass_amu'],charge_state=row['charge_state'],instance=1)
                        state.update({axis+'_mm':row['position_'+axis+'_mm'] for axis in 'xyz'})
                        state.update({'v'+axis+'_mm_per_us':row['velocity_'+axis+'_m_s']/1000 for axis in 'xyz'})
                        lines.extend(terminal_wire_lines(row,ion,token,2.,1))
                        lines.extend(['RF_NATIVE_STATE_V1: '+json.dumps(state),'RF_NATIVE_STATE_V1: '+json.dumps(dict(state,event='terminal',reason='unknown',instrument_time_us=2.))])
                    lines.append(f'status,Fly completed. {len(rows)} splats')
                    script='import time;time.sleep(3);print('+repr('\n'.join(lines))+')'
                    if fail_unit[0] and batch['particle_id_min']==3:
                        script='import time;time.sleep(3);raise SystemExit(7)'
                    item.update(executable=Path(sys.executable),arguments=['-I','-c',script])
                    prepared.append(item)
                calls.append(['inert_real_process_group'])
                group_sizes.append(len(prepared))
                return actual_group(actual_context,**dict(kw,specifications=prepared))
            with patch('msplatform.backends.simion.tracking_execution.windows_binary_version',return_value='inert'), \
                    patch('msplatform.execution.run_session.run_observed_process',side_effect=observed), \
                    patch('msplatform.execution.run_session.run_observed_process_group',side_effect=inert_group):
                result=run_loaded_recipe(loaded,context=context,artifact_root=root/'store',reserve_bytes=256*1024**2)
                from msplatform.storage import ArtifactStore
                from msplatform.workflows.native_tracing import preflight_native
                store=ArtifactStore(root/'store');field_id=result['provenance']['stages']['field']['asset_id']
                with store.claim_verified(field_id) as selected:
                    field_reference=json.loads((selected/'reference.json').read_text(encoding='utf8'))
                author=root/'author/author.toml';manifest=Path(field_reference['manifest']['path'])
                relative=os.path.relpath(manifest,author.parent).replace('\\','/')
                reference_toml=(f'[field_source.reference]\npath = "{relative}"\n'
                    f'sha256 = "{field_reference["manifest"]["sha256"]}"\nproduct_id = "fields"\n')
                external=author.with_name('reference.toml');external.write_text(author.read_text().replace('[recording]',reference_toml+'[recording]'),encoding='utf8')
                selected_recipe=load_recipe(external).to_dict()
                report=preflight_native(selected_recipe,context=context,artifact_store=store)
                self.assertTrue(report['implemented'])
                forged=copy.deepcopy(selected_recipe);forged['field_source']['reference']['snapshot']['sha256']='0'*64
                with self.assertRaises(ValueError):preflight_native(forged,context=context,artifact_store=store)
                before_reference=len(calls)
                selected_run=run_loaded_recipe(load_recipe(external),context=context,artifact_root=root/'store',reserve_bytes=256*1024**2)
                self.assertEqual(selected_run['run_state']['execution_status'],'succeeded')
                self.assertFalse(any('refine_rf_field_family.lua' in ' '.join(call) or 'build_frontend_geometry.lua' in ' '.join(call)
                                     for call in calls[before_reference:]))
                first_count=len(calls)
                repeated=run_loaded_recipe(loaded,context=context,artifact_root=root/'store',reserve_bytes=256*1024**2)
                self.assertEqual(len(calls),first_count)
                prior_manifests=set(root.rglob('run_manifest.json'))
                fail_unit[0]=True
                with self.assertRaises(Exception) as failure:
                    run_loaded_recipe(loaded,context=context,artifact_root=root/'store',reserve_bytes=256*1024**2,
                                      tracking_execution={'unit_size':1,'dispatch_profiles':[]})
                fail_unit[0]=False
                new_manifests=set(root.rglob('run_manifest.json'))-prior_manifests
                failed=[p for p in new_manifests if json.loads(p.read_text(encoding='utf-8-sig')).get('status')=='failed']
                self.assertEqual(len(failed),1, f'original failure: {failure.exception!r}; manifests: {new_manifests!r}')
                completion=json.loads((failed[0].parent/'results/execution_completion.json').read_text(encoding='utf-8-sig'))
                self.assertEqual(completion['exception']['message'],'Observed batch wave failed.')
                self.assertTrue(any('unit_0003' in note and 'exit 7' in note for note in completion['exception']['notes']))
                index=json.loads((failed[0].parent/'logs/tracking_units.json').read_text(encoding='utf-8-sig'))
                self.assertEqual([row['complete'] for row in index['units']],[True,True,False])
                before_recovery=len(calls)
                partitioned=run_loaded_recipe(loaded,context=context,artifact_root=root/'store',reserve_bytes=256*1024**2,
                    tracking_execution={'unit_size':1,'dispatch_profiles':[],
                                        'recovery_reference':file_record(failed[0],'required_evidence')})
                self.assertEqual(sum(call==['inert_real_process_group'] for call in calls[before_recovery:]),1)
                self.assertEqual(group_sizes[-1],1)
            self.assertEqual(result['run_state']['execution_status'],'succeeded')
            self.assertEqual(repeated['run_state']['execution_status'],'succeeded')
            self.assertEqual(partitioned['run_state']['execution_status'],'succeeded')
            self.assertEqual(partitioned['summary']['census']['mother_count'],3)
