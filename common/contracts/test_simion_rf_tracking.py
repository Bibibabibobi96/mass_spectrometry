"""Independent RF tracking contracts; mocked callbacks are not native qualification."""
import copy
import json
import math
import os
import shutil
import sys
from pathlib import Path
import subprocess
import tempfile
import unittest
from msplatform.assembly.handoff import HandoffMother,HandoffClock,HandoffResult
from msplatform.contracts.clock import ClockIdentity
from msplatform.contracts.particle_physics import kinetic_energy_ev,mass_to_charge_th
from common.contracts.test_simion_rf_prepared_model import rf_inputs
from common.contracts.test_component_particle_state import valid_row
from common.contracts.test_simion_prepared_model import LUA
from msplatform.backends.simion.model import compile_prepared_model,RF_PHYSICS
from msplatform.backends.simion.tracking_execution import plan_tracking_execution
from msplatform.backends.simion.rf_tracking_program import render_rf_controls
from msplatform.backends.simion.rf_tracking_execution import plan_rf_tracking_workbench
from msplatform.backends.simion.source import lua_value
from msplatform.execution.resources import resource_path
from msplatform.io.manifest_records import file_record


def rf_tracking_case():
    compiled,components,drive=rf_inputs()
    model=compile_prepared_model(compiled,components,drive=drive,physics=RF_PHYSICS)
    clock={key:drive['clock'][key] for key in ['clock_epoch_id','authority_sha256']}
    names=compiled.frontend_geometry['composition_plan']['scope']['instance_ids']
    rows=[];records={}
    for pid,name,mass,charge,weight in [(7,names[0],100.,1,2.5),(91,names[1],200.,-2,4.)]:
        row=valid_row(pid)
        row.update(parent_particle_id=None,source_component_id=name,target_component_id=name,frame_id=compiled.frontend_geometry['composition_plan']['components'][name]['local_frame_id'],
            clock_epoch_id=clock['clock_epoch_id'],state_event='source_birth',instrument_time_us=1.25,
            lineage_birth_time_us=1.25,particle_birth_time_us=1.25,lineage_age_us=0.,particle_age_us=0.,last_component_elapsed_time_us=0.,
            species_id="species_"+str(pid),mass_amu=mass,charge_state=charge,mass_to_charge_Th=mass_to_charge_th(mass,charge),particle_weight=weight,
            phase_reference_id=None,phase_rad=None,kinetic_energy_eV=kinetic_energy_ev(mass,*[row['velocity_'+a+'_m_s'] for a in 'xyz']))
        rows.append(row);records[pid]=dict(row,source_component_entry_time_us=1.25)
    packet=dict(schema_version=1,role='canonical_release_realization',state_kind='source_birth',rows=rows,
        mother=dict(records=records,fates=[dict(particle_id=pid,category="released") for pid in records]),clock=clock,realization=dict(spec=dict(particle_count=2)))
    clocks={key:dict(path='C:/pure-test/'+key+'.json',exists=True,bytes=32,
        sha256=clock['authority_sha256'] if key=='instrument_epoch' else 'A'*64) for key in ['clock_authority','instrument_epoch']}
    propagation=dict(schema_version=1,scope='continuous_assembly',end_policy=dict(maximum_particle_age_us=5.),consumed_plane_events=[],stop=None,
        dynamics=dict(kinematics='nonrelativistic',collisions='none',space_charge='none'))
    numerics=dict(maximum_step_us=.01,trajectory_quality=5,rf_steps_per_period=32)
    return compiled,model,packet,clocks,propagation,numerics


def plan_case(**changes):
    compiled,model,packet,clocks,propagation,numerics=rf_tracking_case()
    plan=plan_tracking_execution(model,particles=changes.pop('particles',packet),clock_records=clocks,
        propagation=changes.pop('propagation',propagation),observations=changes.pop('observations',dict(plane_observations=[])),
        numerics=changes.pop('numerics',numerics),**changes)
    return compiled,model,packet,plan


def field_assets(root,compiled):
    result={}
    for name,labels in compiled.frontend_geometry['electrode_bindings'].items():
        directory=root/name;directory.mkdir(parents=True)
        family=[]
        for suffix in ['.pa#','.pa0','.pa-surf',*('.pa'+str(n) for n in sorted(set(labels.values())))]:
            path=directory/(name+suffix);path.write_bytes(b'INERT_NOT_NATIVE_PA');family.append(file_record(path,'solver_native_binary'))
        witness=directory/'surface.csv';witness.write_text('INERT_NOT_NATIVE_WITNESS')
        result[name]=dict(carrier_record=next(r for r in family if r['path'].endswith('.pa0')),family_records=family,witness_record=file_record(witness,'required_evidence'))
    return result


class RfTrackingTests(unittest.TestCase):
    @unittest.skipUnless(LUA.is_file(),'plain Lua interpreter unavailable')
    def test_documented_program_quality_range_is_written_and_read_back(self):
        _,_,_,_,_,numerics=rf_tracking_case()
        for quality in (0,-500,-1,1,500):
            with self.subTest(quality=quality):
                _,model,packet,plan=plan_case(numerics=dict(numerics,trajectory_quality=quality))
                self.assertEqual(plan['flight']['trajectory_quality'],quality)
                self.assertEqual([row['particle_id'] for row in plan['rows']],[7,91])
                self.assertEqual([row['instrument_time_us'] for row in plan['rows']],[1.25,1.25])
                program=render_rf_controls(model,plan,assets={},native_sources={})['program']
                stub="simion={workbench_program=function() segment={} end};sim_grouped=1;sim_segment_global=0;"
                code=stub+program+'\nsegment.initialize_run();assert(sim_trajectory_quality=='+str(quality)+');print("QUALITY_READBACK="..sim_trajectory_quality)'
                with tempfile.TemporaryDirectory() as directory:
                    root=Path(directory);script=root/'quality.lua';script.write_text(code,encoding='utf-8')
                    completed=subprocess.run([str(LUA),str(script)],cwd=root,capture_output=True,text=True,timeout=30)
                    self.assertEqual(completed.returncode,0,completed.stderr)
                    self.assertIn('QUALITY_READBACK='+str(quality),completed.stdout)
        for quality in (True,False,-501,501,0.0,'0',None):
            with self.subTest(invalid=quality),self.assertRaises(ValueError):
                plan_case(numerics=dict(numerics,trajectory_quality=quality))
        with self.assertRaises(ValueError):
            plan_case(numerics=dict(numerics,trajectory_quality=0,rf_steps_per_period=0))

    @unittest.skipUnless(LUA.is_file(),'plain Lua interpreter unavailable')
    def test_callback_permissions_and_outside_instance_terminal_keep_full_mother(self):
        from msplatform.backends.simion.rf_tracking_collection import collect_rf_tracking_logs
        _,model,_,plan=plan_case()
        controls=render_rf_controls(model,plan,assets={},native_sources={})
        stub='''local current='load'
local r={ion_number=1,ion_instance=1,ion_mass=100,ion_charge=1,ion_time_of_flight=0,ion_time_step=.01,ion_splat=0,
 ion_px_mm=0,ion_py_mm=0,ion_pz_mm=0,ion_vx_mm=0,ion_vy_mm=0,ion_vz_mm=0,
 sim_grouped=1,sim_repulsion='none',sim_relativity=0,sim_trajectory_quality=5,sim_segment_global=0}
local writable={ion_mass={initialize=true,other_actions=true},ion_charge={initialize=true,other_actions=true},
 ion_time_of_flight={other_actions=true},ion_time_step={tstep_adjust=true},ion_splat={initialize=true,other_actions=true},
 sim_grouped={initialize_run=true},sim_repulsion={initialize_run=true},sim_relativity={initialize_run=true},
 sim_trajectory_quality={initialize_run=true},sim_segment_global={load=true,initialize_run=true}}
for _,axis in ipairs({'x','y','z'}) do
 writable['ion_p'..axis..'_mm']={initialize=true,other_actions=true}
 writable['ion_v'..axis..'_mm']={initialize=true,other_actions=true}
end
setmetatable(_G,{__index=function(_,key)
 if r[key]~=nil then
  assert(key~='ion_splat' or current=='initialize' or current=='other_actions','Read access denied to ion_splat in '..current)
  assert(key~='ion_time_step' or current~='initialize','Read access denied to ion_time_step in initialize')
  return r[key]
 end
end,__newindex=function(env,key,value)
 if r[key]~=nil then assert(writable[key] and writable[key][current],'Write access denied to '..key..' in '..current);r[key]=value
 else rawset(env,key,value) end
end})
simion={workbench_program=function() segment={} end}
adj_elect={}
local function callback(name) current=name;segment[name]();current='load' end
'''
        script=stub+controls['program']+'\ncallback("initialize_run")\n'
        for ion,state in enumerate(plan['rows'],1):
            script+='r.ion_number='+str(ion)+';r.ion_instance=1;r.ion_splat=0;r.ion_time_of_flight=0;r.ion_mass='+repr(state['mass_amu'])+';r.ion_charge='+str(state['charge_state'])+';\n'
            for axis in 'xyz':script+='r.ion_p'+axis+'_mm='+repr(state['position_'+axis+'_mm'])+';\n'
            script+='callback("initialize");callback("fast_adjust");callback("tstep_adjust")\n'
            if ion==1:
                # An arbitrary previously observed flag is not a current
                # terminate value or a basis for inventing physical loss.
                script+='r.ion_time_of_flight=.5;r.ion_splat=4;callback("other_actions");callback("terminate")\n'
            else:
                script+='r.ion_time_of_flight=5;r.ion_instance=0;\n'
                script+='if r.sim_segment_global==1 then callback("other_actions");callback("terminate") end\n'
        script+="assert(r.sim_segment_global==1,'outside-instance callbacks require explicit coverage');print('status,Fly completed. 2 splats')\n"
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);source=root/'permissions.lua';source.write_text(script)
            result=subprocess.run([str(LUA),str(source)],cwd=root,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            log=root/'observed.log';log.write_text(result.stdout)
            collection=collect_rf_tracking_logs([log],source_rows={r['particle_id']:r for r in plan['rows']},source_provenance=plan['source_provenance'],flight=plan['flight'],
                batches=[dict(source_row_range=[1,2],expected_particle_ids=[7,91],build_metadata=controls['build_metadata'])])
            self.assertEqual([r['particle_id']for r in collection['native_terminals']],[7,91])
            self.assertEqual(collection['native_terminals'][1]['instance'],0)
            self.assertTrue(all('raw_ion_splat'not in r for r in collection['canonical_events']))
            self.assertEqual([r['category']for r in collection['census']['terminal_taxonomy']['particle_outcomes']],['unknown_native_terminal','censored_at_absolute_deadline'])
            self.assertFalse(collection['census']['unknown_is_loss'])
    @unittest.skipUnless(LUA.is_file(),'plain Lua interpreter unavailable')
    def test_rf_cold_verifier_uses_rf_guarantees_without_tof_priority_probes(self):
        from msplatform.backends.simion.resources import native_resource_path
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);iob=root/'instrument.iob';pa=root/'original.pa0'
            iob.write_bytes(b'INERT_IOB');pa.write_bytes(b'INERT_PA')
            iob.with_suffix('.lua').write_text('-- INERT');iob.with_suffix('.fly2').write_text('particles{}')
            surface=root/'original.pa-surf';surface.write_bytes(b'INERT_SURFACE')
            witness=root/'surface.csv';witness.write_text('0,0,0,nil,nil,nil\n')
            row=dict(role='rf',instance_index=1,priority_number=1,path=str(pa),fractional_surface=str(surface),surface_witnesses=str(witness),
                response_ids=[1],grid=dict(nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1),rotation=[[1,0,0],[0,1,0],[0,0,1]],
                placement=dict(x_mm=0,y_mm=0,z_mm=0,az_deg=0,el_deg=0,rt_deg=0,scale=1),
                physical_samples=[dict(gu=[0,0,0],metal=True,electrode_id=1),dict(gu=[1,0,0],metal=False)])
            spec=dict(schema_version=1,role='independent_rf_tracking_iob',instances=[row],output_iob=str(iob),response_fields=[])
            stub='''local pa={nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1,electrode_numbers={1}}
function pa:surface_info() return nil,nil,nil end
function pa:point(x) return 0,x==0 end
local item={pa=pa,x=0,y=0,z=0,az=0,el=0,rt=0,scale=1,ox=0,oy=0,oz=0}
function item:pa_to_wb_orient(x,y,z) return x,y,z end
function item:pa_to_wb_coords(x,y,z) return x,y,z end
simion={wb={instances={item}},pas={open=function() return {close=function()end} end},command=function()end}
'''
            for change,message in [('valid',None),('mapping','mapping differs'),('pose','placement differs'),('metal','physical node differs'),('surface','surface readback differs')]:
                mutation={'valid':'','mapping':'pa.electrode_numbers={2}','pose':'item.x=1',
                    'metal':'function pa:point() return 0,false end','surface':'function pa:surface_info() return .5,nil,nil end'}[change]
                script=stub+'\npa.path='+lua_value(str(pa))+'\n'+mutation+'\nlocal spec='+lua_value(spec)+'\n'
                script+='assert(loadfile('+lua_value(str(native_resource_path('iob_core.lua')))+'))()(spec,"verify",function(path)return path end)\n'
                path=root/(change+'.lua');path.write_text(script)
                result=subprocess.run([str(LUA),str(path)],cwd=root,capture_output=True,text=True,timeout=30)
                with self.subTest(change=change):
                    if message is None:
                        self.assertEqual(result.returncode,0,result.stderr)
                        self.assertIn('INDEPENDENT_RF_TRACKING_COLD=PASS',result.stdout)
                    else:
                        self.assertNotEqual(result.returncode,0)
                        self.assertIn(message,result.stderr)
    def test_explicit_dynamics_and_grouped_scheduling_are_distinct(self):
        _,_,_,_,propagation,numerics=rf_tracking_case()
        for grouped in (0,1):
            _,model,_,plan=plan_case(numerics=dict(numerics,grouped=grouped))
            program=render_rf_controls(model,plan,assets={},native_sources={})['program']
            self.assertIn('local rf_grouped='+str(grouped),program)
            self.assertIn("sim_repulsion='none'",program)
            self.assertIn('sim_relativity=0',program)
        for invalid in (True,2,'1'):
            with self.subTest(grouped=invalid),self.assertRaisesRegex(ValueError,'grouped'):
                plan_case(numerics=dict(numerics,grouped=invalid))
        for invalid in (None,dict(kinematics='relativistic',collisions='none',space_charge='none')):
            with self.subTest(dynamics=invalid),self.assertRaisesRegex(ValueError,'explicit collision-free'):
                plan_case(propagation=dict(propagation,dynamics=invalid))

    @unittest.skipUnless(os.name=='nt' and shutil.which('pwsh'),'Windows public process owner required')
    def test_actual_owner_reader_original_family_guards_and_zero_survivor(self):
        from unittest.mock import patch
        from common.contracts.test_simion_rf_fields import model_source,session_for,execute
        from msplatform.execution import owner,run_session,capacity_admission
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.capacity_protection import _lease_path
        from msplatform.backends.simion import track
        from msplatform.results.artifacts import open_artifact
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);seed=model_source(root/'seed')
            fields=session_for(root/'inert_fields',seed,dict(refine_policy='vendor_default'))
            with patch('msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner',return_value=dict(run_directory=str(root/'seed'))):
                field_result=execute(fields,seed,dict(refine_policy='vendor_default'))
            field_product=field_result['manifest_extra_fields']['products']['fields']
            policy=root/'capacity.json';policy.write_text(json.dumps(dict(capacity_admission._capacity_policy(),target_gib=1,minimum_free_gib=0)))
            budget=root/'budget.json';budget.write_text('{"bytes":16777216}')
            retention=dict(policy_version=1,**{'class':'solver_review'},reason='Inert RF tracking owner and reader regression; no native science')
            stage=root/'stage.json';stage.write_text(json.dumps(dict(schema_version=1,role='execution_stage_policy',stages=dict(track=dict(
                limits=dict(wall_clock_seconds=120,transient_run_directory_bytes=16777216,process_tree_working_set_bytes=536870912,
                    minimum_system_available_memory_bytes=1073741824,compact_final_retained_bytes=16777216,
                    automatic_retry_count=0),artifact_retention=retention)))))
            context=ExecutionContext(workspace=root/'study',python_executable=Path(sys.executable),powershell_executable=Path(shutil.which('pwsh')),
                tools=dict(simion=Path(sys.executable)),host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
                policy_path=resource_path('host_resource_policy.json'),capacity_policy_path=policy,stage_policy_path=stage)
            def source_action(session):
                records={}
                for name,record in field_product['data'].items():
                    relative=Path('clock')/Path(record['path']).name if name in {'clock_authority','instrument_epoch'} else Path(record['path']).relative_to(fields.run_dir)
                    target=session.declare_file(session.input_dir/relative,record['retention_role'])
                    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(Path(record['path']).read_bytes())
                    records[name]=file_record(session.canonical_path(target),record['retention_role']);session.add_input(name,records[name])
                paths=[Path(r['path']) for r in records.values()]
                return dict(status='success',summary=dict(fixture='INERT_ONLY'),output_paths=paths,required_output_paths=paths,
                    retention_preserve_paths=[],manifest_extra_fields=dict(products=dict(fields=dict(field_product,data=records))))
            result=owner.run_managed_stage(context,descriptor=dict(project='instrument_assembly',mode='inert_rf_fields',software=[]),
                run_id='20261109_000002__test__python__inert-rf-fields',payload={},committed_new_bytes=16777216,
                commitment_inputs=[file_record(budget,'required_evidence')],retention=retention,expected_operation_ids=(),operation_dependencies={},
                action=source_action,action_record=file_record(Path(__file__),'required_evidence'))
            reference=dict(manifest=result['manifest'],product_id='fields')
            artifact=open_artifact(reference,expected_kind='field_bundle')
            _,_,packet,_,propagation,numerics=rf_tracking_case()
            clock=seed.model.document['drive']['clock'];packet['clock']={k:clock[k] for k in ('clock_epoch_id','authority_sha256')}
            for row in packet['rows']:row['clock_epoch_id']=clock['clock_epoch_id']
            for row in packet['mother']['records'].values():row['clock_epoch_id']=clock['clock_epoch_id']
            originals={r['path']:Path(r['path']).read_bytes() for key,r in artifact.data_records.items() if '_family_' in key}
            actual_process=run_session.run_observed_process;observed=[];remove_bootstrap=[False]
            def inert_native(actual_context,**options):
                if options['role']!='SIMION':return actual_process(actual_context,**options)
                run=Path(options['working_directory']);args=options['arguments'];observed.append(options)
                paths=[r['path'] for r in options['immutable_input_records']]
                self.assertTrue(set(originals)<=set(paths))
                if 'fly' not in args:
                    mode=args[-2];iob=run/'simion/tracking/instrument.iob'
                    code="from pathlib import Path\n"+("Path("+repr(str(iob))+").write_bytes(b'INERT_NOT_NATIVE_IOB')\n" if mode=='build' else '')
                    if mode=='build':
                        # Keep an actual generated intermediate to verify that
                        # the owner declares it BEFORE any supplier writes.
                        neutral=run/'simion/geometry/iob_seed/iob_seed_placeholder_01.pa0'
                        code+='Path('+repr(str(neutral))+').write_bytes(b"INERT_GENERATED_NEUTRAL_BOOTSTRAP")\n'
                        if remove_bootstrap[0]:
                            code+='Path('+repr(str(neutral))+').unlink()\n'
                    code+="print("+repr('INDEPENDENT_RF_TRACKING_IOB=PASS' if mode=='build' else 'INDEPENDENT_RF_TRACKING_IOB_REOPEN=PASS')+")"
                else:
                    rows=json.loads((run/'inputs/canonical_source_states.json').read_text());lines=['RF_DYNAMICS_V1: {"grouped":1,"repulsion":"none","relativity":0,"segment_global":1}']
                    for ion,row in enumerate(rows,1):
                        state=dict(event='source_release',reason='none',particle_id=row['particle_id'],ion=ion,instrument_time_us=row['instrument_time_us'],
                            mass_amu=row['mass_amu'],charge_state=row['charge_state'],instance=1)
                        state.update({a+'_mm':row['position_'+a+'_mm'] for a in 'xyz'});state.update({'v'+a+'_mm_per_us':row['velocity_'+a+'_m_s']/1000 for a in 'xyz'})
                        lines.extend(['RF_NATIVE_STATE_V1: '+json.dumps(state),'RF_NATIVE_STATE_V1: '+json.dumps(dict(state,event='terminal',reason='unknown',instrument_time_us=2.))])
                    lines.append('status,Fly completed. 2 splats');code='print('+repr('\n'.join(lines))+')'
                code="for p in "+repr(list(originals))+":\n try:\n  f=open(p,'ab');f.close()\n except PermissionError: pass\n else: raise AssertionError('original family is writable')\n"+code
                return actual_process(actual_context,**dict(options,executable=Path(sys.executable),arguments=['-I','-c',code],role='GATE',stage='inert_rf_tracking'))
            private=dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='',MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='')
            with patch.dict(os.environ,private),patch.object(run_session,'run_observed_process',side_effect=inert_native):
                current=track(reference,packet,propagation=propagation,observations=dict(plane_observations=[]),numerics=numerics,context=context)
                reread=open_artifact(current.reference,expected_kind='trajectory_result')
                collection=json.loads(reread.data_path('collection').read_text())
                self.assertEqual(collection['native_calls'],3);self.assertEqual(len(observed),3)
                self.assertEqual([r['particle_id'] for r in collection['native_terminals']],[7,91])
                self.assertEqual([r['charge_state'] for r in collection['native_terminals']],[1,-2])
                self.assertTrue(all(r['category']=='unknown_native_terminal' for r in collection['census']['terminal_taxonomy']['particle_outcomes']))
                from msplatform.backends.simion.trajectory_analysis import analyze_published_trajectory
                analyzed=analyze_published_trajectory(reread,selection=dict(schema_version=1,particle_ids=[7,91],observation=None,
                    unexecuted_fate_label_field=None),method=dict(schema_version=1,kind='census'))
                self.assertEqual(analyzed['status'],'analysis_completed')
                self.assertEqual(len(observed),3)  # Read-only analysis launches no supplier.
                actual_clock=ClockIdentity(**packet['clock']);mother=HandoffMother({r['particle_id']:r for r in collection['original_mother']['mother_records']},collection['original_mother']['mother_fates'])
                empty=HandoffResult((),(),(7,91),mother,HandoffClock(actual_clock,actual_clock),'time_snapshot')
                zero=track(reference,empty,propagation=dict(propagation,scope='state_relaunch'),observations=dict(plane_observations=[]),numerics=numerics,context=context,source_reference=current.reference)
                zero_collection=json.loads(zero.data_path('collection').read_text())
                self.assertEqual(len(observed),3);self.assertEqual(zero_collection['native_calls'],0)
                self.assertEqual(zero_collection['original_mother']['mother_records'],collection['original_mother']['mother_records'])
                remove_bootstrap[0]=True
                removed=track(reference,packet,propagation=propagation,observations=dict(plane_observations=[]),numerics=numerics,context=context)
                open_artifact(removed.reference,expected_kind='trajectory_result')
                self.assertEqual(len(observed),6)
                self.assertFalse((removed.manifest_location.parent/'simion/geometry/iob_seed/iob_seed_placeholder_01.pa0').exists())
                removed_completion=json.loads((removed.manifest_location.parent/'results/execution_completion.json').read_text())
                self.assertIn(str(removed.manifest_location.parent/'simion/geometry/iob_seed/iob_seed_placeholder_01.pa0'),removed_completion['file_roles'])
            for path,before in originals.items():self.assertEqual(Path(path).read_bytes(),before)
            for product in (current,zero,removed):
                completion=json.loads((product.manifest_location.parent/'results/execution_completion.json').read_text())
                writer=completion['writer_completion']
                self.assertEqual(len(writer['operations']),0 if product is zero else 3)
                self.assertTrue(all(r['observation']['exit_confirmed'] and r['observation']['returncode']==0 for r in writer['operations']))
                self.assertTrue(all(r['completion_receipt']['host_release']['result']['status']=='released' for r in writer['resource_releases']))
                result_path=root/'study/artifacts/projects/instrument_assembly/scratch/workflow_results'/product.manifest_location.parent.name/'result.json'
                final=json.loads(result_path.read_text());capacity=final['capacity_session']
                self.assertEqual((final['status'],capacity['status']),('success','released'))
                self.assertFalse(_lease_path(Path(capacity['artifact_root']),capacity['lease_id']).exists())
    def test_birth_transform_once_signed_species_sparse_ids_and_clock(self):
        compiled,model,packet,plan=plan_case(unit_size=1)
        self.assertEqual(plan['flight']['tracking_kind'],'independent_rf')
        self.assertNotIn('pulse',plan['flight'])
        self.assertEqual([row['particle_id'] for row in plan['rows']],[7,91])
        self.assertEqual([row['charge_state'] for row in plan['rows']],[1,-2])
        self.assertEqual([row['mass_amu'] for row in plan['rows']],[100.,200.])
        self.assertEqual([row['particle_weight'] for row in plan['rows']],[2.5,4.])
        poses={r['instance_id']:r['transform'] for r in compiled.frontend_geometry['composition_plan']['recipe']['instances']}
        for source,row in zip(packet['rows'],plan['rows'],strict=True):
            pose=poses[source['source_component_id']]
            for i,axis in enumerate('xyz'):
                self.assertAlmostEqual(row['position_'+axis+'_mm'],sum(pose['rotation'][i][j]*source['position_'+a+'_mm'] for j,a in enumerate('xyz'))+pose['translation_mm'][i])
                self.assertAlmostEqual(row['velocity_'+axis+'_m_s'],sum(pose['rotation'][i][j]*source['velocity_'+a+'_m_s'] for j,a in enumerate('xyz')))
            self.assertEqual(row['instrument_time_us'],1.25)
            self.assertEqual(row['particle_birth_time_us'],1.25)
            self.assertEqual(row['frame_id'],model.document['native_frame_id'])
        self.assertEqual(plan['absolute_deadlines_us_by_particle_id'],{7:6.25,91:6.25})
        self.assertEqual([u['expected_particle_ids'] for u in plan['units']],[[7],[91]])
        self.assertEqual([r['particle_id'] for r in plan['source_provenance']['mother_records']],[7,91])
    def test_zero_survivor_keeps_full_mother_without_native(self):
        compiled,model,packet,clocks,propagation,numerics=rf_tracking_case()
        clock=ClockIdentity(**packet['clock'])
        mother=HandoffMother(packet['mother']['records'],[dict(particle_id=7,category='unknown'),dict(particle_id=91,category='lost')])
        empty=HandoffResult((),(),(7,91),mother,HandoffClock(clock,clock),'time_snapshot')
        plan=plan_tracking_execution(model,particles=empty,clock_records=clocks,propagation=dict(propagation,scope='state_relaunch'),
            observations=dict(plane_observations=[]),numerics=numerics)
        self.assertFalse(plan['native_requested']);self.assertEqual(plan['expected_operation_ids'],[])
        self.assertEqual(len(plan['source_provenance']['mother_records']),2)
        self.assertEqual(plan['source_provenance']['mother_fates'],list(mother.fates))
    def test_wrong_pulse_numerics_and_clock_fail_without_native(self):
        _,_,_,_,_,numerics=rf_tracking_case()
        for change in [dict(numerics,pulse=dict(mode='held_off')),dict(numerics,maximum_step_us=0),dict(numerics,rf_steps_per_period=True)]:
            with self.subTest(change=change),self.assertRaises(ValueError):plan_case(numerics=change)
    def test_workbench_references_original_family_and_only_copies_small_structural_seed(self):
        compiled,_,_,plan=plan_case()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);assets=field_assets(root/'producer',compiled)
            projected=plan_rf_tracking_workbench(compiled,carriers=assets,run_directory=root/'run',program='-- PURE INERT PROGRAM',
                native_source_rows=plan['native_source_rows'],native_path_resource=resource_path('native_run_path.lua'))
            self.assertEqual(len(projected.input_copies),1)
            self.assertEqual(projected.declared_outputs,(str(root/'run/simion/tracking/instrument.iob'),
                str(root/'run/simion/geometry/iob_seed/iob_seed_placeholder_01.pa0'),str(root/'run/simion/geometry/iob_seed/iob_seed_placeholder_02.pa0')))
            self.assertEqual(projected.operations[0]['outputs'],list(projected.declared_outputs))
            self.assertTrue(projected.input_copies[0]['source_record']['path'].endswith('.iob'))
            self.assertEqual([op['operation_id'] for op in projected.operations],['build_tracking_iob','verify_tracking_iob'])
            text=projected.materializations[str(root/'run/inputs/tracking_iob.lua')]
            for asset in assets.values():self.assertIn(lua_value(asset['carrier_record']['path']),text)
            self.assertNotIn('refine',str([op['arguments'] for op in projected.operations]).lower())
    @unittest.skipUnless(LUA.is_file(),'plain Lua interpreter unavailable')
    def test_rf_program_plane_recrossing_cap_and_cut_keep_accepted_endpoint(self):
        from msplatform.backends.simion.rf_tracking_collection import collect_rf_tracking_logs
        compiled,model,packet,clocks,propagation,numerics=rf_tracking_case()
        component=compiled.frontend_geometry['composition_plan']['components']['first']
        port=component['ports']['mechanical_exit']
        # The native positions below use the independent matrix oracle, while
        # the production observer uses its existing proper-plane transform.
        transform=next(r['transform'] for r in compiled.frontend_geometry['composition_plan']['recipe']['instances'] if r['instance_id']=='first')
        center=[sum(transform['rotation'][i][j]*port['center_mm'][j] for j in range(3))+transform['translation_mm'][i] for i in range(3)]
        normal=[sum(transform['rotation'][i][j]*port['outward_normal'][j] for j in range(3)) for i in range(3)]
        for row in packet['rows']:
            row.update(source_component_id='first',target_component_id='first',frame_id=component['local_frame_id'])
            for i,a in enumerate('xyz'):
                row['position_'+a+'_mm']=port['center_mm'][i]-port['outward_normal'][i]
                row['velocity_'+a+'_m_s']=port['outward_normal'][i]*1000
            row['kinetic_energy_eV']=kinetic_energy_ev(row['mass_amu'],*[row['velocity_'+a+'_m_s'] for a in 'xyz'])
            packet['mother']['records'][row['particle_id']]=dict(row,source_component_entry_time_us=1.25)
        for cut in (False,True):
            definition=dict(schema_version=1,observation_id='rf_exit',source_instance_id='first',port_id='mechanical_exit',max_records=2)
            policy=dict(propagation,scope='segmented_upstream',stop=dict(schema_version=1,scope='segmented_upstream',observation_id='rf_exit',direction='outward',occurrence=1)) if cut else propagation
            plan=plan_tracking_execution(model,particles=packet,clock_records=clocks,propagation=policy,
                observations=dict(plane_observations=[definition]),numerics=numerics)
            controls=render_rf_controls(model,plan,assets={},native_sources={})
            script='simion={workbench_program=function() segment={} end};sim_grouped=1;adj_elect={};ion_instance=1;ion_time_step=1;\n'+controls['program']+'\nsegment.initialize_run()\n'
            for ion,state in enumerate(plan['rows'],1):
                script+='ion_number='+str(ion)+';ion_time_of_flight=0;ion_splat=0;ion_mass='+repr(state['mass_amu'])+';ion_charge='+str(state['charge_state'])+';\n'
                for a in 'xyz':script+='ion_p'+a+'_mm='+repr(state['position_'+a+'_mm'])+';ion_v'+a+'_mm=0;\n'
                script+='segment.initialize()\n'
                for step in range(1,2 if cut else 4):
                    script+='ion_time_of_flight='+str(step)+';\n'
                    for i,a in enumerate('xyz'):
                        script+='ion_p'+a+'_mm='+repr(center[i]+normal[i]*(1 if step%2 else -1))+';ion_v'+a+'_mm='+repr(normal[i]*(1 if step%2 else -1))+';\n'
                    script+='segment.other_actions()\n'
                # Actual SIMION terminate exposes START. Preserve it separately
                # from the observer's accepted END, as existing V2 requires.
                script+='ion_time_of_flight=0;\n'
                for a in 'xyz':script+='ion_p'+a+'_mm='+repr(state['position_'+a+'_mm'])+';\n'
                script+='segment.terminate()\n'
            script+="print('status,Fly completed. 2 splats')\n"
            with self.subTest(cut=cut),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);path=root/'program.lua';path.write_text(script)
                output=subprocess.run([str(LUA),str(path)],cwd=root,capture_output=True,text=True,timeout=30,check=True)
                log=root/'inert.log';log.write_text(output.stdout)
                collected=collect_rf_tracking_logs([log],source_rows={r['particle_id']:r for r in plan['rows']},source_provenance=plan['source_provenance'],
                    flight=plan['flight'],batches=[dict(source_row_range=[1,2],expected_particle_ids=[7,91],build_metadata=controls['build_metadata'])])
                observed=collected['plane_observations']
                if cut:
                    self.assertEqual(observed['status'],'complete')
                    self.assertEqual([r['category'] for r in collected['census']['terminal_taxonomy']['particle_outcomes']],['handoff_cut_stop']*2)
                    self.assertTrue(all(r['instrument_time_us']>1.25 for r in observed['rows']))
                    self.assertTrue(all(r['terminal_instrument_time_us']==1.25 for r in collected['census']['terminal_taxonomy']['particle_outcomes']))
                else:
                    self.assertEqual(observed['status'],'incomplete')
                    self.assertEqual([(r['direction'],r['occurrence']) for r in observed['rows']],[('outward',1),('inward',1)])
                    self.assertEqual(len(observed['incomplete']),1)
                    self.assertFalse(collected['census']['unknown_is_loss'])

    @unittest.skipUnless(LUA.is_file(),'plain Lua interpreter unavailable')
    def test_actual_rf_kernel_callback_uses_absolute_clock_and_signed_source(self):
        compiled,model,packet,plan=plan_case()
        controls=render_rf_controls(model,plan,assets={},native_sources={})
        first=plan['rows'][0]
        globals_='simion={workbench_program=function() segment={} end};sim_grouped=1;adj_elect={};ion_number=1;ion_instance=1;ion_time_of_flight=0;ion_time_step=100;ion_splat=0;ion_mass=100;ion_charge=1;'
        for axis in 'xyz':globals_+='ion_p'+axis+'_mm='+repr(first['position_'+axis+'_mm'])+';ion_v'+axis+'_mm=0;'
        code=globals_+controls['program']+'\nsegment.initialize_run();segment.initialize();segment.fast_adjust();segment.tstep_adjust();for id,v in pairs(adj_elect) do print(string.format("V %d %.17g",id,v)) end;print("STEP "..ion_time_step)'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);script=root/'callback.lua';script.write_text(code)
            result=subprocess.run([str(LUA),str(script)],cwd=root,capture_output=True,text=True,timeout=30,check=True)
        birth=next(json.loads(line.split('RF_NATIVE_STATE_V1:',1)[1]) for line in result.stdout.splitlines() if 'RF_NATIVE_STATE_V1:' in line)
        self.assertEqual((birth['particle_id'],birth['instrument_time_us']),(7,1.25))
        values={int(line.split()[1]):float(line.split()[2]) for line in result.stdout.splitlines() if line.startswith('V ')}
        for row in model.document['native_drive_rows']:
            if row['instance_id']!='first':continue
            expected=row['voltage_v'] if row['kind']=='static' else row['common_mode_v']+row['dc_v']+row['polarity']*row['rf_amplitude_v']*getattr(math,'sin' if row['waveform']=='sine' else 'cos')(2*math.pi*row['frequency_hz']*1.25e-6+row['phase_rad'])
            self.assertAlmostEqual(values[row['native_targets'][0]['electrode_id']],expected,places=10)
        step=float(next(line.split()[1] for line in result.stdout.splitlines() if line.startswith('STEP ')))
        self.assertLessEqual(step,.01)

    def test_collector_preserves_unknown_and_deadline_endpoints_without_calling_tof_taxonomy(self):
        from msplatform.backends.simion.rf_tracking_collection import collect_rf_tracking_logs
        _,model,_,plan=plan_case()
        controls=render_rf_controls(model,plan,assets={},native_sources={})
        lines=['RF_DYNAMICS_V1: {"grouped":1,"repulsion":"none","relativity":0,"segment_global":1}']
        for ion,state in enumerate(plan['rows'],1):
            row=dict(event='source_release',reason='none',particle_id=state['particle_id'],ion=ion,
                instrument_time_us=state['instrument_time_us'],mass_amu=state['mass_amu'],charge_state=state['charge_state'],instance=1)
            row.update({axis+'_mm':state['position_'+axis+'_mm'] for axis in 'xyz'})
            row.update({'v'+axis+'_mm_per_us':state['velocity_'+axis+'_m_s']/1000 for axis in 'xyz'})
            lines.append('RF_NATIVE_STATE_V1: '+json.dumps(row))
            if ion==2:
                endpoint=dict(row,event='deadline_endpoint',reason='absolute_deadline',instrument_time_us=6.25)
                lines.append('RF_NATIVE_STATE_V1: '+json.dumps(endpoint))
            terminal=dict(row,event='terminal',reason='unknown' if ion==1 else 'deadline',instrument_time_us=2. if ion==1 else 6.24)
            lines.append('RF_NATIVE_STATE_V1: '+json.dumps(terminal))
        lines.append('status,Fly completed. 2 splats')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'inert.log';path.write_text('\n'.join(lines)+'\n')
            args=dict(source_rows={r['particle_id']:r for r in plan['rows']},source_provenance=plan['source_provenance'],flight=plan['flight'],
                batches=[dict(source_row_range=[1,2],expected_particle_ids=[7,91],build_metadata=controls['build_metadata'])])
            result=collect_rf_tracking_logs([path],**args)
            self.assertEqual([r['category'] for r in result['census']['terminal_taxonomy']['particle_outcomes']],['unknown_native_terminal','censored_at_absolute_deadline'])
            self.assertFalse(result['census']['unknown_is_loss'])
            self.assertEqual(result['census']['terminal_taxonomy']['particle_outcomes'][1]['accepted_endpoint']['instrument_time_us'],6.25)
            self.assertEqual(result['original_mother']['mother_records'],plan['source_provenance']['mother_records'])
            self.assertEqual([r['charge_state'] for r in result['native_terminals']],[1,-2])
            for control in [dict(grouped=1,repulsion='none',relativity=0),
                            dict(grouped=1,repulsion='none',relativity=0,segment_global=0),
                            dict(grouped=1,repulsion='none',relativity=0,segment_global=True)]:
                path.write_text('\n'.join(['RF_DYNAMICS_V1: '+json.dumps(control),*lines[1:]])+'\n')
                with self.subTest(control=control),self.assertRaisesRegex(ValueError,'dynamics'):
                    collect_rf_tracking_logs([path],**args)
            path.write_text('\n'.join(lines[:1]+lines[2:])+'\n')
            with self.assertRaisesRegex(ValueError,'actual births'):collect_rf_tracking_logs([path],**args)
    def test_recovery_fingerprint_binds_rf_renderer_and_full_mother(self):
        from msplatform.backends.simion.tracking_units import tracking_applicability
        _,_,_,plan=plan_case(unit_size=1)
        before=tracking_applicability(plan)
        changed=copy.deepcopy(plan);changed['source_provenance']['mother_records'][0]['particle_weight']+=1
        self.assertNotEqual(tracking_applicability(changed),before)
        changed=copy.deepcopy(plan);changed['numerics']['rf_steps_per_period']+=1
        self.assertNotEqual(tracking_applicability(changed),before)
    def test_capabilities_share_rf_pulse_free_plan(self):
        from msplatform.capabilities import capabilities
        _,model,packet,clocks,policy,numerics=rf_tracking_case()
        args=dict(model=model,particles=packet,clock_records=clocks,propagation=policy,observations=dict(plane_observations=[]),numerics=numerics)
        result=capabilities(dict(schema_version=1,operation='track',arguments=args))
        self.assertEqual(result['contract_status'],'accepted')
        self.assertEqual(result['native_qualification'],'not_granted')


if __name__=='__main__':unittest.main()
