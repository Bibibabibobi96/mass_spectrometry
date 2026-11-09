"""Independent OA tracking uses actual canonical models; software is not native qualification."""
import copy
import json
import subprocess
import tempfile
from pathlib import Path
from common.contracts.test_simion_prepared_model import LUA
from msplatform.contracts.particle_physics import kinetic_energy_ev
from msplatform.backends.simion.rf_tracking_program import render_rf_controls
from common.contracts.test_simion_prepared_model import oa_model_inputs
from common.contracts.test_simion_rf_tracking import rf_tracking_case
from msplatform.backends.simion.model import compile_prepared_model, RF_PHYSICS
from msplatform.backends.simion.tracking_execution import plan_tracking_execution
import unittest


def oa_tracking_case(pulse_mode="timed"):
    instrument,_,compiled,drive=oa_model_inputs()
    if pulse_mode is None:
        drive.pop('pulse')
        for groups in drive['groups'].values():
            for name,row in list(groups.items()):
                if row['kind']=='pulse':groups[name]=dict(kind='static',voltage_v=row['off_voltage_v'])
    elif pulse_mode!='timed':drive['pulse']={'mode':pulse_mode}
    model=compile_prepared_model(compiled,instrument.components_resolved,drive=drive,physics=RF_PHYSICS)
    _,_,packet,clocks,propagation,numerics=rf_tracking_case()
    names=compiled.frontend_geometry['composition_plan']['scope']['instance_ids']
    packet=copy.deepcopy(packet)
    packet['clock']={key:drive['clock'][key] for key in ('clock_epoch_id','authority_sha256')}
    for row,name in zip(packet['rows'],names,strict=True):
        row.update(source_component_id=name,target_component_id=name,
            frame_id=compiled.frontend_geometry['composition_plan']['components'][name]['local_frame_id'],clock_epoch_id=drive['clock']['clock_epoch_id'])
        packet['mother']['records'][row['particle_id']]=dict(row,source_component_entry_time_us=row['instrument_time_us'])
    clocks['instrument_epoch']['sha256']=drive['clock']['authority_sha256']
    numerics.pop('rf_steps_per_period')
    return compiled,model,packet,clocks,propagation,numerics


def oa_plan(**changes):
    compiled,model,packet,clocks,propagation,numerics=oa_tracking_case(changes.pop("pulse_mode","timed"))
    plan=plan_tracking_execution(model,particles=changes.pop('particles',packet),clock_records=clocks,
        propagation=changes.pop('propagation',propagation),observations=changes.pop('observations',dict(plane_observations=[])),
        numerics=changes.pop('numerics',numerics),**changes)
    return compiled,model,packet,plan


class OaTrackingTests(unittest.TestCase):
    def test_actual_two_three_zone_model_preserves_signed_sparse_mother_and_pose(self):
        compiled,model,packet,plan=oa_plan()
        self.assertEqual(plan['flight']['tracking_kind'],'independent_oa')
        self.assertEqual([r['particle_id'] for r in plan['rows']],[7,91])
        self.assertEqual([r['charge_state'] for r in plan['rows']],[1,-2])
        self.assertEqual([r['particle_weight'] for r in plan['rows']],[2.5,4.])
        for original,projected in zip(packet['rows'],plan['rows'],strict=True):
            pose=next(item['transform'] for item in compiled.frontend_geometry['composition_plan']['recipe']['instances'] if item['instance_id']==original['source_component_id'])
            for i,axis in enumerate('xyz'):
                self.assertAlmostEqual(projected['position_'+axis+'_mm'],sum(pose['rotation'][i][j]*original['position_'+a+'_mm'] for j,a in enumerate('xyz'))+pose['translation_mm'][i])
                self.assertAlmostEqual(projected['velocity_'+axis+'_m_s'],sum(pose['rotation'][i][j]*original['velocity_'+a+'_m_s'] for j,a in enumerate('xyz')))
        self.assertEqual(plan['source_provenance']['mother_particle_ids'],[7,91])
        self.assertEqual([r['particle_birth_time_us'] for r in plan['rows']],[1.25,1.25])
        self.assertEqual(plan['absolute_deadlines_us_by_particle_id'],{7:6.25,91:6.25})
        self.assertEqual(model.document['geometry']['frontend_geometry']['role'],'simion_independent_oa_geometry')

    def test_real_model_pulse_callbacks_use_absolute_clock_and_cap_both_edges(self):
        import subprocess,tempfile
        from pathlib import Path
        from common.contracts.test_simion_prepared_model import LUA
        from msplatform.backends.simion.rf_tracking_program import render_rf_controls
        self.assertTrue(LUA.is_file())
        for mode,with_planes in [(m,p) for m in ('timed','held_on','held_off',None) for p in (False,True)]:
            with self.subTest(mode=mode,with_planes=with_planes),tempfile.TemporaryDirectory() as directory:
                _,_,_,_,propagation,_=oa_tracking_case(mode)
                propagation['end_policy']={'absolute_instrument_end_us':50.}
                _,_,_,_,_,numerics=oa_tracking_case(mode)
                definition=dict(schema_version=1,observation_id='oa_exit',source_instance_id='two',port_id='axial_exit',max_records=2)
                _,model,_,plan=oa_plan(pulse_mode=mode,propagation=propagation,numerics=dict(numerics,maximum_step_us=10.),observations=dict(plane_observations=[definition] if with_planes else []))
                controls=render_rf_controls(model,plan,assets={},native_sources={})
                target=next(row['native_targets'][0]['electrode_id'] for row in model.document['native_drive_rows'] if row['instance_id']=='two' and row['electrode_group_id']=='repeller')
                code="simion={workbench_program=function() segment={} end};ion_number=1;ion_instance=1;adj_elect={};sim_grouped=1;ion_time_of_flight=0;\n"+controls['program']
                code+='\nsegment.initialize_run();ion_mass=100;ion_charge=1;ion_splat=0;ion_px_mm=0;ion_py_mm=0;ion_pz_mm=0;ion_vx_mm=0;ion_vy_mm=0;ion_vz_mm=0;segment.initialize();ion_vx_mm=0;ion_vy_mm=0;ion_vz_mm=0;\n'
                code+="\nfor _,t in ipairs({9.5,10,11.5,12}) do ion_time_of_flight=t-1.25;ion_time_step=10;segment.fast_adjust();segment.tstep_adjust();print('ROW '..t..' '..adj_elect["+str(target)+"]..' '..ion_time_step) end"
                script=Path(directory)/'pulse.lua';script.write_text(code,encoding='utf-8')
                out=subprocess.run([str(LUA),str(script)],cwd=script.parent,capture_output=True,text=True,encoding='utf-8',timeout=30)
                self.assertEqual(out.returncode,0,out.stderr)
                rows=[list(map(float,line.split()[1:])) for line in out.stdout.splitlines() if line.startswith('ROW ')]
                self.assertEqual(len(rows),4)
                voltages=[r[1] for r in rows]
                self.assertEqual(voltages,[-5.,2000.,2000.,-5.] if mode=='timed' else [2000.]*4 if mode=='held_on' else [-5.]*4)
                self.assertEqual([r[2] for r in rows],[.5,2.,.5,10.] if mode=='timed' else [10.]*4)
                self.assertEqual(controls['build_metadata']['tracking_kind'],'independent_oa')

    def test_zero_handoff_and_recovery_identity_keep_full_original_mother(self):
        from msplatform.assembly.handoff import HandoffResult,HandoffMother,HandoffClock
        from msplatform.contracts.clock import ClockIdentity
        from msplatform.backends.simion.tracking_units import tracking_applicability
        _,_,packet,plan=oa_plan()
        clock=ClockIdentity(**packet['clock']);mother=HandoffMother(packet['mother']['records'],packet['mother']['fates'])
        zero=HandoffResult((),(),(7,91),mother,HandoffClock(clock,clock),'time_snapshot')
        _,_,_,empty=oa_plan(particles=zero,propagation=dict(plan['propagation'],scope='state_relaunch'))
        self.assertFalse(empty['native_requested']);self.assertEqual(empty['expected_operation_ids'],[])
        self.assertEqual(empty['source_provenance']['mother_particle_ids'],[7,91])
        original=tracking_applicability(plan)
        changed=copy.deepcopy(plan);changed['source_provenance']['mother_records'][0]['particle_weight']+=1
        self.assertNotEqual(tracking_applicability(changed),original)

    def test_actual_oa_iob_uses_original_family_and_honest_oa_role(self):
        import tempfile
        from pathlib import Path
        from common.contracts.test_simion_rf_tracking import field_assets
        from msplatform.backends.simion.rf_tracking_execution import plan_rf_tracking_workbench
        from msplatform.execution.resources import resource_path
        _,_,_,plan=oa_plan()
        compiled,_,_,_=oa_plan()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);assets=field_assets(root/'original',compiled)
            graph=plan_rf_tracking_workbench(compiled,carriers=assets,run_directory=root/'run',program='EXPLICIT_PROGRAM',native_source_rows=plan['native_source_rows'],native_path_resource=resource_path('native_run_path.lua'))
            text=graph.materializations[str(root/'run/inputs/tracking_iob.lua')]
            self.assertIn('independent_oa_tracking_iob',text)
            self.assertNotIn('independent_rf_tracking_iob',text)
            self.assertEqual([o['success_marker'] for o in graph.operations],['INDEPENDENT_OA_TRACKING_IOB=PASS','INDEPENDENT_OA_TRACKING_IOB_REOPEN=PASS'])
            for row in assets.values():self.assertIn(row['carrier_record']['path'].replace('\\','\\\\'),text)
            self.assertEqual(len(graph.input_copies),1)

    def test_explicit_collision_policy_unknown_numerics_and_wrong_clock_reject(self):
        _,_,packet,clocks,propagation,numerics=oa_tracking_case()
        with self.assertRaises(ValueError):oa_plan(propagation=dict(propagation,dynamics=dict(kinematics='nonrelativistic',collisions='gas',space_charge='none')))
        with self.assertRaises(ValueError):oa_plan(numerics=dict(numerics,rf_steps_per_period=32))
        for field,value in [('frame_id','wrong-frame'),('particle_id',999),('instrument_time_us',-1.)]:
            malformed=copy.deepcopy(packet);malformed['rows'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):oa_plan(particles=malformed)
        packet['clock']['clock_epoch_id']='another'
        with self.assertRaises(ValueError):oa_plan(particles=packet)

    def test_actual_oa_program_plane_recrossing_and_cut_preserve_accepted_endpoints(self):
        from msplatform.backends.simion.rf_tracking_collection import collect_rf_tracking_logs
        compiled,model,packet,clocks,propagation,numerics=oa_tracking_case()
        component=compiled.frontend_geometry['composition_plan']['components']['two']
        port=component['ports']['axial_exit']
        # The native positions below use the independent matrix oracle, while
        # the production observer uses its existing proper-plane transform.
        transform=next(r['transform'] for r in compiled.frontend_geometry['composition_plan']['recipe']['instances'] if r['instance_id']=='two')
        center=[sum(transform['rotation'][i][j]*port['center_mm'][j] for j in range(3))+transform['translation_mm'][i] for i in range(3)]
        normal=[sum(transform['rotation'][i][j]*port['outward_normal'][j] for j in range(3)) for i in range(3)]
        for row in packet['rows']:
            row.update(source_component_id='two',target_component_id='two',frame_id=component['local_frame_id'])
            for i,a in enumerate('xyz'):
                row['position_'+a+'_mm']=port['center_mm'][i]-port['outward_normal'][i]
                row['velocity_'+a+'_m_s']=port['outward_normal'][i]*1000
            row['kinetic_energy_eV']=kinetic_energy_ev(row['mass_amu'],*[row['velocity_'+a+'_m_s'] for a in 'xyz'])
            packet['mother']['records'][row['particle_id']]=dict(row,source_component_entry_time_us=1.25)
        for cut in (False,True):
            definition=dict(schema_version=1,observation_id='rf_exit',source_instance_id='two',port_id='axial_exit',max_records=2)
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

    def test_actual_oa_collector_preserves_unknown_deadline_and_original_mother(self):
        from msplatform.backends.simion.rf_tracking_collection import collect_rf_tracking_logs
        _,model,_,plan=oa_plan()
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
