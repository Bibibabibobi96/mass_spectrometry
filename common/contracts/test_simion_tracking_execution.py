"""Actual public release/model tracking projections; no native process starts."""
import copy
import unittest

from msplatform import assembly as assembly_api, components as component_api, examples as example_api
from msplatform import ion_release as ion_release_api
from msplatform.backends import simion as simion_api
from msplatform.assembly.handoff import HandoffMother,HandoffClock,HandoffResult,prepare_handoff_states,HandoffSelection
from msplatform.contracts.rigid_transform import RigidTransform
from msplatform.contracts.clock import ClockIdentity
from msplatform.backends.simion.model import compile_prepared_model,project_resolved_drive,PHYSICS
from msplatform.backends.simion.tracking_execution import plan_tracking_execution


def tracking_action_fixture(self, root):
    """One real model/field protocol fixture shared by pure and inert-owner tests."""
    import json
    import shutil
    import sys
    from pathlib import Path
    from types import SimpleNamespace
    from importlib.resources import files
    from msplatform.backends.simion.field_bank import field_bank
    from msplatform.backends.simion.field_identity import working_point_member_id
    from msplatform.backends.simion.native_plans import plan_solve_fields
    from msplatform.results.artifacts import OpenedArtifact
    from msplatform.io.manifest_records import file_record,verify_record
    native=root/'inert-native/simion.exe';native.parent.mkdir()
    shutil.copyfile(sys.executable,native)  # Identity-only binary; Session.run_process never executes it.
    producer=root/'producer';producer.mkdir()
    records={}
    def put(key,name,*,value=None,raw=None):
        path=producer/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw if raw is not None else (json.dumps(value,allow_nan=False)+'\n').encode())
        records[key]=file_record(path,'required_evidence' if path.suffix=='.json' else 'solver_native_binary')
    put('compiled_model','model.json',raw=self.model.document_json.encode() if hasattr(self.model,'document_json') else json.dumps(self.model.document).encode())
    put('clock_authority','clock_authority.json',raw=files('msplatform.examples').joinpath('instrument_clock_authority_v1.json').read_bytes())
    put('instrument_epoch','instrument_epoch_v1.json',raw=files('msplatform.examples').joinpath('instrument_epoch_v1.json').read_bytes())
    numerical=copy.deepcopy(self.case.field_numerics);numerical.pop('downstream_convergence_v')
    design=plan_solve_fields(self.model,numerics=numerical)['field_design']
    domains=[row['domain_id'] for row in design['domains']]
    put('field_design','design.json',value=design);put('field_bank','bank.json',value=field_bank(design,domains))
    put('workbench','fields.iob',raw=b'INERT_NOT_NATIVE_IOB');put('downstream_audit','audit.json',value={'fixture':'INERT'})
    put('zero_particle_format_control','fields.fly2',raw=b'particles { coordinates = 0 }\n')
    bindings={}
    for domain in domains:
        bindings[domain]={}
        for point in design['working_points']:
            member=working_point_member_id(point);key=domain+'_'+member
            put(key,('frontend' if domain=='parent' else 'frontend_entrance_refinement')+'.'+member+'.pa',raw=b'INERT_NOT_PA')
            bindings[domain][member]={'data_key':key,'cache_key':'provenance_only','generation_directory':'FORBIDDEN_RUNTIME_LOOKUP'}
    assets={}
    for role in ('flight_tube','reflectron','detector'):
        family=[]
        for suffix in (('.pa',) if role=='reflectron' else ('.pa#','.pa0','.pa1','.pa-surf')):
            key=role+suffix;put(key,role+suffix,raw=b'INERT_NOT_PA')
            if role!='reflectron':family.append(key)
        assets[role]=dict(carrier=role+('.pa' if role=='reflectron' else '.pa0'),family=family)
    metadata=dict(backend='simion',field_status='available',source_status='not_requested',
        model_identity_sha256=self.model.document['model_identity_sha256'],clock=self.model.document['drive']['clock'],
        frontend_members=bindings,native_assets=assets,downstream_identity={'fixture':'INERT_SPATIAL_IDENTITY'})
    artifact=OpenedArtifact(kind='field_bundle',product_id='fields',reference={'manifest':{'path':str(producer/'run_manifest.json'),'bytes':123,'sha256':'D'*64}},
        metadata=metadata,records=records,paths={key:Path(row['path']) for key,row in records.items()},producer={})
    class Session:
        run_dir=root/'run'
        input_dir=run_dir/'inputs';result_dir=run_dir/'results';log_dir=run_dir/'logs'
        expected_operation_ids=('build_tracking_iob','verify_tracking_iob','track_fly')
        operation_dependencies=dict(verify_tracking_iob=['build_tracking_iob'],track_fly=['verify_tracking_iob'])
        context=SimpleNamespace(tools={'simion':native})
        inputs={};calls=[]
        def __init__(inner,run=None,fault=None):
            inner.run_dir=run or root/'run'
            inner.input_dir=inner.run_dir/'inputs';inner.result_dir=inner.run_dir/'results';inner.log_dir=inner.run_dir/'logs'
            inner.inputs={};inner.calls=[];inner.fault=fault
        def declare_file(inner,path,role):return Path(path)
        def canonical_path(inner,path):return Path(path).resolve()
        def add_input(inner,name,record):verify_record(name,record);inner.inputs[name]=record
        def run_process(inner,operation_id,*,immutable_input_records,**kwargs):
            # Actual identities are checked, but no process is launched.
            for record in immutable_input_records:verify_record('inert protocol input',record)
            paths={Path(row['path']) for row in immutable_input_records}
            program=inner.run_dir/'simion/tracking/instrument.lua'
            self.assertEqual(inner.canonical_path(program) in paths,operation_id!='build_tracking_iob')
            self.assertFalse(any('FORBIDDEN_RUNTIME_LOOKUP' in str(path) for path in paths))
            self.assertIn(producer/'fields.iob',paths)
            self.assertIn(producer/'fields.fly2',paths)
            inner.calls.append(dict(id=operation_id,inputs=copy.deepcopy(immutable_input_records),kwargs=kwargs))
            ordinal=inner.expected_operation_ids.index(operation_id)+1
            inner.log_dir.mkdir(parents=True,exist_ok=True)
            if operation_id=='build_tracking_iob':
                program.with_suffix('.iob').write_bytes(b'INERT_NOT_NATIVE_IOB')
                text='SINGLE_REFLECTION_IOB=PASS\n'
            elif operation_id=='verify_tracking_iob':text='MISSING_MARKER\n' if inner.fault=='verify_marker' else 'SINGLE_REFLECTION_IOB_REOPEN=PASS\n'
            else:
                rows=json.loads((inner.input_dir/'canonical_source_states.json').read_text())
                lines=[]
                for ion,row in enumerate(rows,1):
                    pid,t=row['particle_id'],row['instrument_time_us']
                    state=' '.join(f'{a}_mm={row["position_"+a+"_mm"]:.17g}' for a in 'xyz')+' '+' '.join(f'v{a}_mm_per_us={row["velocity_"+a+"_m_s"]/1000:.17g}' for a in 'xyz')
                    xyz=' '.join(f'{a}={row["position_"+a+"_mm"]:.17g}' for a in 'xyz')
                    lines.extend((f'TRACE: source_release ion={ion} particle_id={pid} instrument_time_us={t:.17g} {state}',
                        f'TRACE: handoff_terminal_raw ion={ion} instance=3 instrument_time_us={t+1:.17g} {state}',
                        f'TRACE: non_detector_splat ion={ion} instance=3 t={t+1:.17g} {xyz} zmax=0'))
                text='\n'.join(lines)+(f'\nstatus,Fly completed. {len(rows)} splats\n' if inner.fault!='completion' else '\n')
            (inner.log_dir/f'operation_{ordinal:04d}.stdout.log').write_text(text,encoding='utf-8')
            # Explicit protocol double; actual OS ownership is covered by
            # the separate original-owner inert integration fixture.
            receipt=dict(observation=dict(exit_code=0,root_process_id=123,
                root_process_started_at_utc_ticks=456),error=None,
                host_release=dict(inherited=False,token='INERT_PROTOCOL',
                    result=dict(status='released',token='INERT_PROTOCOL'),error=None))
            (inner.log_dir/f'operation_{ordinal:04d}.process.json').write_text(json.dumps(receipt),encoding='utf-8')
            return receipt
    return artifact,Session,producer


class TrackingExecutionPlanTests(unittest.TestCase):
    def test_public_track_binds_recorded_birth_producer_and_rejects_tamper(self):
        import csv
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        from msplatform.execution.terminal_publication import publish_terminal_state
        from msplatform.io.manifest_records import file_record
        from msplatform.ion_release.authoring import load_recorded_release
        from msplatform.ion_release.cylinder import CANONICAL_COLUMNS

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fields, Session, _ = tracking_action_fixture(self, root)
            producer = root / 'birth-producer'
            producer.mkdir()
            source, evidence = producer/'source.csv', producer/'request.json'
            ids = [11, 1009, 2001]
            original = copy.deepcopy(self.packet['realization']['generator_rows'][:3])
            for row, pid in zip(original, ids, strict=True):
                row['particle_id'] = pid
            with source.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=CANONICAL_COLUMNS, extrasaction='ignore', lineterminator='\n')
                writer.writeheader()
                writer.writerows(original)
            evidence.write_text('{}', encoding='utf-8')
            records = {'source': file_record(source), 'request': file_record(evidence)}
            manifest = dict(schema_version=2, role='simulation_run_manifest', run_id='birth-fixture',
                project='instrument_assembly', mode='source', status='success', inputs=records, outputs=[])
            publish_terminal_state(producer, {'status': 'success'}, manifest)
            authority = {'manifest': file_record(producer/'run_manifest.json'), 'records': records}
            packet = load_recorded_release(records['source'], clock=ClockIdentity(**self.packet['clock']),
                frame_id=self.case.release['release_spec']['frame_id'], source_component_id='multipole',
                species_id='explicit', relative_weights=None, instrument_origin_us=0., expected_particle_ids=ids)
            session = Session()
            limits = {'transient_run_directory_bytes': 1}
            stage = {'limits': limits, 'artifact_retention': {}}
            with patch('msplatform.execution.stage_policy.read_stage_policy', return_value=(stage, {})), \
                 patch('msplatform.execution.owner.run_managed_stage', return_value={'manifest': {}}) as owner, \
                 patch('msplatform.results.artifacts.open_artifact', return_value='published'):
                self.assertEqual(simion_api.track(fields, packet, propagation=self.policy,
                    observations={'plane_observations': []}, numerics=self.numerics, context=session.context,
                    birth_source_authority=authority), 'published')
                call = owner.call_args.kwargs
                self.assertIn({'manifest_record': authority['manifest']}, call['source_references'])
                self.assertEqual(call['payload']['birth_source_authority'], authority)
                self.assertEqual(call['action'].keywords['birth_source_authority'], authority)
            evidence.write_text('tampered', encoding='utf-8')
            with patch('msplatform.execution.owner.run_managed_stage') as owner, self.assertRaises(AssertionError):
                simion_api.track(fields, packet, propagation=self.policy, observations={'plane_observations': []},
                    numerics=self.numerics, context=session.context, birth_source_authority=authority)
            owner.assert_not_called()

    def test_recorded_birth_owner_freezes_bytes_before_recovery_and_native(self):
        import csv
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        from msplatform.backends.simion.tracking_execution import execute_tracking
        from msplatform.io.manifest_records import file_record
        from msplatform.execution.terminal_publication import publish_terminal_state
        from msplatform.ion_release.authoring import load_recorded_release
        from msplatform.ion_release.cylinder import CANONICAL_COLUMNS

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact, Session, _ = tracking_action_fixture(self, root)
            producer = root / 'recorded-producer'
            producer.mkdir()
            source = producer / 'recorded.csv'
            ids = [11, 1009, 2001]
            original = copy.deepcopy(self.packet['realization']['generator_rows'][:3])
            for row, pid in zip(original, ids, strict=True):
                row['particle_id'] = pid
            with source.open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=CANONICAL_COLUMNS, extrasaction='ignore', lineterminator='\n')
                writer.writeheader()
                writer.writerows(original)
            selected = file_record(source)
            metadata = producer / 'source_metadata.json'
            metadata.write_text('{}', encoding='utf-8')
            authority_records = {'source': selected, 'metadata': file_record(metadata)}
            manifest = dict(schema_version=2, role='simulation_run_manifest', run_id='source-fixture',
                project='instrument_assembly', mode='source', status='success', inputs=authority_records, outputs=[])
            publish_terminal_state(producer, {'status': 'success'}, manifest)
            authority = {'manifest': file_record(producer/'run_manifest.json'), 'records': authority_records}
            packet = load_recorded_release(selected, clock=ClockIdentity(**self.packet['clock']),
                frame_id=self.case.release['release_spec']['frame_id'], source_component_id='multipole',
                species_id='declared', relative_weights={11: .5, 1009: 2., 2001: 3.},
                instrument_origin_us=12.5, expected_particle_ids=ids)
            from msplatform.execution.inputs import freeze_file
            manifest_path = producer/'run_manifest.json'
            manifest_bytes = manifest_path.read_bytes()
            changing = Session(root/'changing')
            def mutate_at_copy(source_path, destination, **kwargs):
                if Path(destination).name == 'manifest.json' and Path(destination).parent.name == 'birth_authority':
                    manifest_path.write_bytes(manifest_bytes + b' ')
                return freeze_file(source_path, destination, **kwargs)
            try:
                with patch('msplatform.backends.simion.model_execution._protected_source'), \
                     patch('msplatform.execution.inputs.freeze_file', side_effect=mutate_at_copy), \
                     self.assertRaisesRegex(ValueError, 'frozen birth authority manifest differs'):
                    execute_tracking(changing, fields_reference=artifact, particles=packet, propagation=self.policy,
                        observations={'plane_observations': []}, numerics=self.numerics, limits={},
                        birth_source_authority=authority)
            finally:
                manifest_path.write_bytes(manifest_bytes)
            self.assertEqual(changing.calls, [])
            session = Session(root/'recorded')
            def stop_at_recovery(*args, **kwargs):
                frozen = session.inputs['recorded_birth_source']
                self.assertEqual(Path(frozen['path']).read_bytes(), source.read_bytes())
                self.assertEqual((frozen['bytes'], frozen['sha256']), (selected['bytes'], selected['sha256']))
                self.assertEqual(Path(session.inputs['birth_authority_0002']['path']).read_bytes(), metadata.read_bytes())
                self.assertEqual(Path(session.inputs['birth_authority_manifest']['path']).read_bytes(),
                                 (producer/'run_manifest.json').read_bytes())
                self.assertEqual(session.calls, [])
                raise RuntimeError('recovery boundary reached')
            with patch('msplatform.backends.simion.model_execution._protected_source'), \
                 patch('msplatform.backends.simion.tracking_units.prepare_tracking_recovery', side_effect=stop_at_recovery), \
                 self.assertRaisesRegex(RuntimeError, 'recovery boundary reached'):
                execute_tracking(session, fields_reference=artifact, particles=packet, propagation=self.policy,
                    observations={'plane_observations': []}, numerics=self.numerics, limits={},
                    recovery_reference={'path': 'explicit-fixture'}, birth_source_authority=authority)
            self.assertEqual(session.calls, [])
            successful = Session(root/'successful')
            with patch('msplatform.backends.simion.model_execution._protected_source'):
                result = execute_tracking(successful, fields_reference=artifact, particles=packet, propagation=self.policy,
                    observations={'plane_observations': []}, numerics=self.numerics, limits={},
                    birth_source_authority=authority)
            data = result['manifest_extra_fields']['products']['trajectory']['data']
            self.assertEqual(Path(data['recorded_birth_source']['path']).read_bytes(), source.read_bytes())
            self.assertEqual(data['recorded_birth_source']['sha256'], selected['sha256'])
            self.assertEqual([row['id'] for row in successful.calls], list(successful.expected_operation_ids))
            source.write_bytes(b'changed before freeze')
            rejected = Session(root/'rejected')
            with patch('msplatform.backends.simion.model_execution._protected_source'), self.assertRaises(AssertionError):
                execute_tracking(rejected, fields_reference=artifact, particles=packet, propagation=self.policy,
                    observations={'plane_observations': []}, numerics=self.numerics, limits={},
                    birth_source_authority=authority)
            self.assertEqual(rejected.calls, [])

    def setUp(self):
        self.case=example_api.load_example('rf_oatof_functional_v1')
        parts={key:component_api.resolve_component(value) for key,value in self.case.component_requests.items()}
        assembly=assembly_api.assemble(self.case.recipe,parts)
        self.compiled=simion_api.compile_geometry(assembly,numerics=self.case.geometry_numerics)
        self.packet=ion_release_api.sample_release(self.case.release).to_dict()
        components={key:self.compiled.components_resolved[key] for key in self.compiled.frontend_geometry['composition_plan']['scope']['instance_ids']}
        self.drive=project_resolved_drive(self.compiled,components,pulse=dict(mode='timed',time_us=10.,width_us=2.),
            clock=dict(self.packet['clock'],phase_reference_instrument_time_us=0.))
        self.model=compile_prepared_model(self.compiled,components,drive=self.drive,physics=PHYSICS)
        # Explicit metadata doubles only: action must verify the real files.
        self.clocks={key:dict(path='C:/pure-test/'+key+'.json',exists=True,bytes=32,
            sha256=self.packet['clock']['authority_sha256'] if key=='instrument_epoch' else 'A'*64)
            for key in ('clock_authority','instrument_epoch')}
        self.policy=dict(schema_version=1,scope='continuous_assembly',end_policy=dict(maximum_particle_age_us=200.),consumed_plane_events=[],stop=None)
        self.numerics=dict(maximum_step_us=.001,trajectory_quality=17,rf_steps_per_period=80)
    def plan(self,**kwargs):
        return plan_tracking_execution(self.model,particles=kwargs.pop('particles',self.packet),clock_records=self.clocks,
            propagation=kwargs.pop('propagation',self.policy),observations=dict(plane_observations=[]),
            numerics=kwargs.pop('numerics',self.numerics),**kwargs)
    def test_real_sparse_births_fullmother_clock_and_independent_cyclic_pose_oracle(self):
        before=copy.deepcopy(self.packet)
        plan=self.plan()
        self.assertEqual(self.packet,before)
        self.assertEqual(len(plan['rows']),100)
        self.assertEqual([row['particle_id'] for row in plan['rows']],self.case.release['particle_ids'])
        self.assertEqual(plan['source_provenance']['mother_particle_ids'],self.case.release['particle_ids'])
        poses={row['instance_id']:row['transform'] for row in self.case.recipe['instances']}
        self.assertEqual(poses['multipole']['rotation'],[[0,0,1],[1,0,0],[0,1,0]])
        translation=poses['multipole']['translation_mm']
        self.assertEqual(poses['oatof']['rotation'],[[1,0,0],[0,1,0],[0,0,1]])
        self.assertEqual(poses['oatof']['translation_mm'],[0,0,0])
        for original,row,native in zip(self.packet['rows'],plan['rows'],plan['native_source_rows'],strict=True):
            expected=[original['position_z_mm']+translation[0],original['position_x_mm']+translation[1],original['position_y_mm']+translation[2]]
            self.assertEqual([row['position_'+a+'_mm'] for a in 'xyz'],expected)
            self.assertEqual([row['velocity_'+a+'_m_s'] for a in 'xyz'],[original['velocity_z_m_s'],original['velocity_x_m_s'],original['velocity_y_m_s']])
            self.assertEqual(row['particle_birth_time_us'],original['particle_birth_time_us'])
            self.assertEqual(row['particle_age_us'],0.)
            self.assertEqual(plan['absolute_deadlines_us_by_particle_id'][row['particle_id']],original['particle_birth_time_us']+200.)
            self.assertEqual(float(native['instrument_time_us']),original['instrument_time_us'])
        self.assertGreater(len({row['instrument_time_us'] for row in plan['rows']}),1)
        self.assertEqual(plan['expected_operation_ids'],['build_tracking_iob','verify_tracking_iob','track_fly'])
    def test_snapshot_arrival_does_not_reset_birth_deadline_and_zero_has_no_native(self):
        birth=self.plan()
        clock=ClockIdentity(**self.packet['clock'])
        records={row['particle_id']:row for row in birth['source_provenance']['mother_records']}
        mother=HandoffMother(records,birth['source_provenance']['mother_fates'])
        state=copy.deepcopy(birth['rows'][0]);start=5.
        state.update(instrument_time_us=start,lineage_age_us=start-state['lineage_birth_time_us'],
            particle_age_us=start-state['particle_birth_time_us'],last_component_elapsed_time_us=start-state['particle_birth_time_us'],state_event='snapshot')
        identity=RigidTransform('oatof_global','oatof_global',((1,0,0),(0,1,0),(0,0,1)),(0,0,0))
        handoff=prepare_handoff_states([state],transform=identity,clock=HandoffClock(clock,clock),
            selection=HandoffSelection('time_snapshot',(state['particle_id'],),start),mother=mother)
        policy=dict(self.policy,scope='state_relaunch')
        result=self.plan(particles=handoff,propagation=policy)
        self.assertEqual(result['rows'][0]['instrument_time_us'],start)
        self.assertEqual(result['absolute_deadlines_us_by_particle_id'],birth['absolute_deadlines_us_by_particle_id'])
        self.assertEqual(result['rows'][0]['particle_birth_time_us'],state['particle_birth_time_us'])
        empty=HandoffResult((),(),tuple(records),mother,HandoffClock(clock,clock),'time_snapshot')
        result=self.plan(particles=empty,propagation=policy)
        self.assertEqual(result['expected_operation_ids'],[])
        self.assertFalse(result['native_requested'])
        self.assertEqual(len(result['source_provenance']['mother_records']),100)
    def test_workbench_transport_uses_structural_seed_and_solved_projection_without_refine(self):
        from common.contracts.test_simion_field_workbench import case
        from common.contracts.test_simion_native_plans import NATIVE_PATH
        from msplatform.backends.simion.tracking_execution import plan_tracking_workbench
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            assembly,compiled,design,carriers,responses=case(root)
            before=copy.deepcopy((compiled,design,carriers,responses))
            source=self.plan()['native_source_rows']
            fields=dict(path=str(root/'published/fields.iob'),bytes=123,sha256='B'*64)
            plan=plan_tracking_workbench(compiled,field_design=design,components_resolved=assembly['components_resolved'],
                carriers=carriers,response_fields=responses,field_workbench_record=fields,run_directory=root/'run',
                program='-- inert transport-only Program fixture\n',native_source_rows=source,native_path_resource=NATIVE_PATH)
            self.assertEqual((compiled,design,carriers,responses),before)
            from msplatform.backends.simion.resources import structural_seed_path
            self.assertEqual(len(plan.input_copies),1)
            seed=plan.input_copies[0]
            self.assertEqual(Path(seed['source_record']['path']), structural_seed_path(4))
            self.assertEqual(Path(seed['destination']), root/'run/simion/geometry/iob_seed/4_instance_seed.iob')
            self.assertEqual([row['operation_id'] for row in plan.operations],['build_tracking_iob','verify_tracking_iob'])
            self.assertEqual([row['arguments'][-2] for row in plan.operations],['build','verify'])
            self.assertEqual(len(plan.materializations),3)
            self.assertFalse((root/'run').exists())
            spec=plan.materializations[str(root/'run/inputs/tracking_iob.lua')]
            self.assertIn('4_instance_seed.iob',spec)
            self.assertNotIn('spec.seed_iob=',spec)
            self.assertNotIn(str(root/'published/fields.iob'),spec)
            self.assertIn('response_fields',spec)
            self.assertIn('native_priority_occupancy_probes',spec)
            self.assertIn('interface_field_probes',spec)
            for operation in plan.operations:
                self.assertNotIn('refine',operation['arguments'])
                self.assertNotIn('gem2pa',operation['arguments'])
            with self.assertRaisesRegex(ValueError,'zero handoff'):
                plan_tracking_workbench(compiled,field_design=design,components_resolved=assembly['components_resolved'],
                    carriers=carriers,response_fields=responses,field_workbench_record=fields,run_directory=root/'run',
                    program='-- unused',native_source_rows=[],native_path_resource=NATIVE_PATH)

    def test_explicit_end_numerics_clock_and_source_bindings_fail_before_native(self):
        for end in ({},{'maximum_particle_age_us':0},{'maximum_particle_age_us':True},
                    {'maximum_particle_age_us':float('inf')},{'absolute_instrument_end_us':.01},
                    {'maximum_particle_age_us':200,'absolute_instrument_end_us':200}):
            with self.subTest(end=end),self.assertRaises(ValueError): self.plan(propagation=dict(self.policy,end_policy=end))
        with self.assertRaises(ValueError): self.plan(numerics=dict(self.numerics,rf_frequency_hz=1.))
        changed=copy.deepcopy(self.packet);changed['clock']['authority_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'clock'): self.plan(particles=changed)
        changed=copy.deepcopy(self.packet);changed['rows'][0]['source_component_id']='unbound'
        with self.assertRaisesRegex(ValueError,'source component'): self.plan(particles=changed)

    def test_render_uses_real_model_bank_and_owned_records_without_cache_paths(self):
        from pathlib import Path
        import tempfile
        from msplatform.backends.simion.native_plans import plan_solve_fields
        from msplatform.backends.simion.field_bank import field_bank
        from msplatform.backends.simion.field_identity import working_point_member_id
        from msplatform.backends.simion.resources import native_resource_path
        from msplatform.execution.resources import resource_path
        from msplatform.backends.simion.tracking_execution import _render_tracking_controls
        numerical=copy.deepcopy(self.case.field_numerics)
        numerical.pop('downstream_convergence_v')
        design=plan_solve_fields(self.model,numerics=numerical)['field_design']
        domains=[row['domain_id'] for row in design['domains']]
        names=dict(analyzer_component_source='oatof_analyzer_component.lua',pulse_hook_source='single_flight_pulse_hook.lua',
            frontend_hook_source='single_flight_frontend_hook.lua',rf_drive_kernel_source='rf_drive.lua',voltage_waveforms_source='voltage_waveforms.lua')
        sources={key:native_resource_path(value).read_text(encoding='utf-8') for key,value in names.items()}
        sources['native_path_source']=resource_path('native_run_path.lua').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            record=lambda name:dict(path=str(root/name),exists=True,bytes=123,sha256='A'*64)
            frontend={domain:{working_point_member_id(point):record(('frontend' if domain=='parent' else 'frontend_entrance_refinement')+'.'+working_point_member_id(point)+'.pa')
                for point in design['working_points']} for domain in domains}
            downstream={}
            for role in ('flight_tube','reflectron','detector'):
                family=[record(role+suffix) for suffix in ('.pa#','.pa0','.pa1','.pa-surf')] if role!='reflectron' else []
                downstream[role]=dict(carrier_record=family[1] if family else record(role+'.pa'),family_records=family)
            kwargs=dict(field_design=design,stored_bank=field_bank(design,domains),frontend_records=frontend,
                downstream_assets=downstream,downstream_receipt=record('audit.json'),native_sources=sources)
            result=_render_tracking_controls(self.model,self.plan(),**kwargs)
            self.assertIn('simion.workbench_program()',result['program'])
            self.assertEqual(len(result['immutable_input_records']),sum(map(len,frontend.values()))+9)
            self.assertEqual(result['build_metadata']['source_clock']['original_birth_times_us'],
                [row['particle_birth_time_us'] for row in self.packet['rows']])
            changed=copy.deepcopy(kwargs);changed['stored_bank']['dynamic_roles'][0]['instance_index']=999
            with self.assertRaisesRegex(ValueError,'actual design'):
                _render_tracking_controls(self.model,self.plan(),**changed)
            changed=copy.deepcopy(kwargs);changed['frontend_records'][domains[0]].pop('carrier_off')
            with self.assertRaisesRegex(ValueError,'cover'):
                _render_tracking_controls(self.model,self.plan(),**changed)
            import json
            persisted=json.loads(json.dumps(design,allow_nan=False))
            self.assertNotEqual(persisted,design)  # native table int -> JSON str
            actual=_render_tracking_controls(self.model,self.plan(),**dict(kwargs,field_design=persisted))
            self.assertEqual(actual['program'],result['program'])
            for fault in ('missing','extra','value'):
                bad=copy.deepcopy(persisted)
                table=bad['accelerator_voltage_states']['operating_voltages_v']
                key=next(iter(table))
                if fault=='missing':table.pop(key)
                elif fault=='extra':table['999999']=0.
                else:table[key]+=1.
                with self.subTest(fault=fault),self.assertRaises(ValueError):
                    _render_tracking_controls(self.model,self.plan(),**dict(kwargs,field_design=bad))

    def test_fly_uses_verified_execution_alias_and_canonical_records(self):
        """Real public alias, inert native protocol; no SIMION process is launched."""
        import json
        import os
        import shutil
        import sys
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from msplatform.execution.context import ExecutionContext
        from msplatform.execution.resources import resource_path
        from msplatform.execution.run_paths import create_execution_alias,remove_execution_alias
        from msplatform.backends.simion.tracking_execution import execute_tracking
        if os.name!='nt' or not shutil.which('pwsh'):
            self.skipTest('public Windows execution alias requires PowerShell')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,Session,_=tracking_action_fixture(self,root)
            workspace=root/'workspace';workspace.mkdir()
            context=ExecutionContext(workspace=workspace,python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')),tools={},
                host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
                policy_path=resource_path('host_resource_policy.json'))
            for fault in (None,'completion'):
                with self.subTest(fault=fault):
                    canonical=workspace/'artifacts/projects/instrument_assembly/runs'/('run_'+str(fault))
                    canonical.mkdir(parents=True)
                    alias=Path(create_execution_alias(context,canonical)['execution_alias'])
                    class AliasSession(Session):
                        def declare_file(inner,path,role):return inner.canonical_path(path)
                        def run_process(inner,operation_id,*,immutable_input_records,**kwargs):
                            if operation_id=='track_fly':
                                native_iob=alias/'simion/tracking/instrument.iob'
                                self.assertEqual(kwargs['arguments'][-1],str(native_iob))
                                self.assertEqual(kwargs['arguments'][2],'--lua')
                                self.assertIn('d.allow_asynchronous_io=false',kwargs['arguments'][3])
                                self.assertEqual(kwargs['arguments'][-4:],['fly','--retain-trajectories','0',str(native_iob)])
                                self.assertNotEqual(str(native_iob),str(native_iob.resolve()))
                                self.assertTrue(os.path.samefile(native_iob,native_iob.resolve()))
                                build_spec=(alias/'inputs/tracking_iob.lua').read_text()
                                from msplatform.backends.simion.source import lua_value
                                self.assertIn('spec.output_iob='+lua_value(str(native_iob)),build_spec)
                            return super().run_process(operation_id,immutable_input_records=immutable_input_records,**kwargs)
                    session=AliasSession(alias,fault)
                    try:
                        with patch('msplatform.backends.simion.model_execution._protected_source'):
                            arguments=dict(fields_reference=artifact,particles=self.packet,propagation=self.policy,
                                observations={'plane_observations':[]},numerics=self.numerics,limits={},allow_asynchronous_io=False)
                            if fault:
                                with self.assertRaisesRegex(ValueError,'completion'):execute_tracking(session,**arguments)
                                self.assertFalse((canonical/'results/collection.json').exists())
                            else:
                                result=execute_tracking(session,**arguments)
                                collection=json.loads(Path(result['manifest_extra_fields']['products']['trajectory']['data']['collection']['path']).read_text())
                                self.assertEqual(len(collection['original_mother']['mother_records']),100)
                                self.assertTrue(collection['native_complete'])
                                mode=collection['fly_io_mode_override']
                                self.assertIs(mode['requested'],False)
                                self.assertEqual(mode['phase'],'before_fly_command_not_after_iob_load')
                                self.assertEqual(mode['stdout_data_keys'],['native_stdout'])
                                self.assertNotIn('applied',mode)
                                self.assertIs(collection['fly_trajectory_retention']['requested'],False)
                        self.assertEqual(len(session.calls),3)
                        self.assertTrue(all(Path(record['path']).is_relative_to(canonical)
                            for record in session.inputs.values()))
                    finally:
                        remove_execution_alias(context,alias,canonical)
                    self.assertFalse(alias.exists())
                    self.assertTrue((canonical/'simion/tracking/instrument.iob').is_file())

    def test_owned_action_protocol_freezes_real_controls_and_reparses_all_actual_wire(self):
        """Inert operation protocol only; no native format or OS lock claim."""
        import json
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        from msplatform.backends.simion.tracking_execution import execute_tracking
        from msplatform.results.artifacts import OpenedArtifact

        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            artifact,Session,producer=tracking_action_fixture(self,root)
            metadata,records=artifact.metadata,artifact.data_records
            session=Session()
            with patch('msplatform.backends.simion.model_execution._protected_source') as protection:
                result=execute_tracking(session,fields_reference=artifact,particles=self.packet,propagation=self.policy,
                    observations={'plane_observations':[]},numerics=self.numerics,limits={})
            self.assertEqual(protection.call_count,1)
            self.assertEqual([row['id'] for row in session.calls],list(session.expected_operation_ids))
            from msplatform.backends.simion.resources import structural_seed_path
            seed_path = structural_seed_path(4)
            for call in session.calls:
                guarded = {Path(row['path']).name for row in call['inputs']}
                self.assertIn('fields.iob', guarded)
                self.assertIn('fields.fly2', guarded)
                self.assertIn('4_instance_seed.iob', guarded)
            original_seed = seed_path.read_bytes()
            for fault in ('missing', 'tampered'):
                fake = root/fault/'4_instance_seed.iob'
                fake.parent.mkdir()
                if fault == 'tampered':
                    fake.write_bytes(bytes([original_seed[0] ^ 1]) + original_seed[1:])
                failed = Session(root/('bad_'+fault))
                with patch('msplatform.backends.simion.resources.structural_seed_path', return_value=fake), \
                        patch('msplatform.backends.simion.model_execution._protected_source'), \
                        self.subTest(fault=fault), self.assertRaises((AssertionError, FileNotFoundError, ValueError)):
                    execute_tracking(failed, fields_reference=artifact, particles=self.packet, propagation=self.policy,
                        observations={'plane_observations':[]}, numerics=self.numerics, limits={})
                self.assertEqual(failed.calls, [])
            self.assertEqual(seed_path.read_bytes(), original_seed)
            product=result['manifest_extra_fields']['products']['trajectory']
            self.assertNotIn('tracking_workbench',product['data'])
            self.assertIn('native_controls',product['data']);self.assertIn('native_stdout',product['data'])
            collection=json.loads(Path(product['data']['collection']['path']).read_text())
            self.assertTrue(collection['native_complete'])
            self.assertEqual(len(collection['native_terminals']),100)
            self.assertEqual(collection['original_mother']['mother_particle_ids'],self.case.release['particle_ids'])
            self.assertEqual(collection['native_calls'],3)
            self.assertTrue(all(row['kwargs']['role']=='SIMION' for row in session.calls))
            clock=ClockIdentity(**self.packet['clock'])
            source_mother=HandoffMother({row['particle_id']:row for row in collection['original_mother']['mother_records']},
                collection['original_mother']['mother_fates'])
            empty=HandoffResult((),(),tuple(source_mother.records),source_mother,HandoffClock(clock,clock),'time_snapshot')
            parent=OpenedArtifact(kind='trajectory_result',product_id='trajectory',reference={'manifest':{'path':str(session.run_dir/'manifest.json')}},
                metadata=product['metadata'],records=product['data'],paths={key:Path(row['path']) for key,row in product['data'].items()},producer={})
            zero=Session(root/'zero');zero.expected_operation_ids=();zero.operation_dependencies={}
            with patch('msplatform.backends.simion.model_execution._protected_source'),patch(
                    'msplatform.results.artifacts.open_artifact',return_value=parent):
                zero_result=execute_tracking(zero,fields_reference=artifact,particles=empty,
                    propagation=dict(self.policy,scope='state_relaunch'),observations={'plane_observations':[]},
                    numerics=self.numerics,limits={},source_reference=parent.reference)
            self.assertEqual(zero.calls,[])
            zero_collection=json.loads(Path(zero_result['manifest_extra_fields']['products']['trajectory']['data']['collection']['path']).read_text())
            self.assertIsNone(zero_collection['native_complete'])
            self.assertEqual(zero_collection['native_calls'],0)
            for key in ('mother_particle_ids','mother_records','mother_fates','clock_authority_sha256'):
                self.assertEqual(zero_collection['original_mother'][key],collection['original_mother'][key])
            for key in ('clock_authority','instrument_epoch'):
                previous=collection['original_mother']['clock_records'][key]
                current=zero_collection['original_mother']['clock_records'][key]
                self.assertEqual((current['bytes'],current['sha256']),(previous['bytes'],previous['sha256']))
                self.assertNotEqual(current['path'],previous['path'])  # freshly frozen owner transport
            self.assertFalse((zero.run_dir/'simion').exists())
            wrong=OpenedArtifact(kind='prepared_model',product_id='model',reference=artifact.reference,metadata=metadata,
                records=records,paths={key:Path(row['path']) for key,row in records.items()},producer={})
            from msplatform.backends.simion.field_closure import require_downstream_reuse
            with self.assertRaisesRegex(ValueError,'field_bundle'):require_downstream_reuse(wrong,metadata['downstream_identity'])
            for fault,message,count in [('verify_marker','completion marker',2),('completion','completion',3)]:
                failed=Session(root/fault,fault)
                with patch('msplatform.backends.simion.model_execution._protected_source'),self.subTest(fault=fault),self.assertRaisesRegex(ValueError,message):
                    execute_tracking(failed,fields_reference=artifact,particles=self.packet,propagation=self.policy,
                        observations={'plane_observations':[]},numerics=self.numerics,limits={})
                self.assertEqual(len(failed.calls),count)
                self.assertFalse((failed.result_dir/'collection.json').exists())
            (producer/'fields.lua').write_text('error("UNDECLARED_HOOK")',encoding='utf-8')
            rejected=Session(root/'ambient_hook')
            with self.assertRaisesRegex(ValueError,'undeclared automatic'):
                execute_tracking(rejected,fields_reference=artifact,particles=self.packet,propagation=self.policy,
                    observations={'plane_observations':[]},numerics=self.numerics,limits={})
            self.assertEqual(rejected.calls,[])


class PublicObservationTests(unittest.TestCase):
    def setUp(self):
        from integrations.tests.test_single_reflection_program import field_observation_spec
        self.case = TrackingExecutionPlanTests()
        self.case.setUp()
        self.spec = field_observation_spec(anchor=self.case.packet['rows'][0]['particle_id'],
            clock=self.case.packet['clock']['clock_epoch_id'], source_instance='multipole')
        end_before, end_after = self.spec['buckets'][6:8]
        end_before.update(time_min_us=11., time_max_us=12., target_time_us=12.)
        end_after.update(time_min_us=12., time_max_us=13., target_time_us=12.)
        self.observations = dict(plane_observations=[], native_field_observation=self.spec)

    def plan(self, observations):
        return plan_tracking_execution(self.case.model, particles=self.case.packet,
            clock_records=self.case.clocks, propagation=self.case.policy,
            observations=observations, numerics=self.case.numerics)

    def test_real_public_track_passes_frozen_spec_and_default_is_unchanged(self):
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        from msplatform.backends.simion import operations
        before = copy.deepcopy((self.case.packet, self.observations))
        with tempfile.TemporaryDirectory() as directory:
            fields, Session, _ = tracking_action_fixture(self.case, Path(directory))
            session = Session()
            stage = {'limits': {'transient_run_directory_bytes': 1}, 'artifact_retention': {}}
            with patch('msplatform.execution.stage_policy.read_stage_policy', return_value=(stage, {})), \
                 patch('msplatform.execution.owner.run_managed_stage', return_value={'manifest': {}}) as owner, \
                 patch('msplatform.results.artifacts.open_artifact', return_value='published'):
                result = operations.track(fields, self.case.packet, propagation=self.case.policy,
                    observations=self.observations, numerics=self.case.numerics, context=session.context)
                self.assertEqual(result, 'published')
                actual = owner.call_args.kwargs
                self.assertEqual(actual['payload']['observations'], self.observations)
                self.assertEqual(actual['action'].keywords['observations'], self.observations)
                plain = dict(plane_observations=[])
                operations.track(fields, self.case.packet, propagation=self.case.policy,
                    observations=plain, numerics=self.case.numerics, context=session.context)
                self.assertEqual(owner.call_args.kwargs['payload']['observations'], plain)
        self.assertEqual((self.case.packet, self.observations), before)

    def test_invalid_observation_rejected_before_owner(self):
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        from msplatform.backends.simion import operations
        with tempfile.TemporaryDirectory() as directory:
            fields, Session, _ = tracking_action_fixture(self.case, Path(directory))
            for key, value in [('clock_epoch_id','wrong'), ('source_instance_id','wrong'),
                               ('eligible_batch_anchor_particle_id', 999999), ('max_rows', 17)]:
                bad = copy.deepcopy(self.observations)
                bad['native_field_observation'][key] = value
                with self.subTest(key=key), patch('msplatform.execution.owner.run_managed_stage') as owner:
                    with self.assertRaises(ValueError):
                        operations.track(fields, self.case.packet, propagation=self.case.policy,
                            observations=bad, numerics=self.case.numerics, context=Session().context)
                    owner.assert_not_called()

    def test_renderer_instruments_only_anchor_unit_using_actual_program(self):
        from pathlib import Path
        import tempfile
        from msplatform.backends.simion.tracking_execution import _render_tracking_controls
        from msplatform.backends.simion.native_plans import plan_solve_fields
        from msplatform.backends.simion.field_bank import field_bank
        from msplatform.backends.simion.field_identity import working_point_member_id
        from msplatform.backends.simion.resources import native_resource_path
        from msplatform.backends.simion.tracking_units import slice_tracking_plan
        from msplatform.execution.resources import resource_path
        numerical = copy.deepcopy(self.case.case.field_numerics)
        numerical.pop('downstream_convergence_v')
        design = plan_solve_fields(self.case.model, numerics=numerical)['field_design']
        domains = [row['domain_id'] for row in design['domains']]
        names = dict(analyzer_component_source='oatof_analyzer_component.lua', pulse_hook_source='single_flight_pulse_hook.lua',
                     frontend_hook_source='single_flight_frontend_hook.lua', rf_drive_kernel_source='rf_drive.lua',
                     voltage_waveforms_source='voltage_waveforms.lua')
        sources = {key:native_resource_path(value).read_text(encoding='utf-8') for key,value in names.items()}
        sources['native_path_source'] = resource_path('native_run_path.lua').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def record(name):
                return dict(path=str(root/name), exists=True, bytes=123, sha256='A'*64)
            frontend = {domain:{working_point_member_id(point):record(
                ('frontend' if domain=='parent' else 'frontend_entrance_refinement')+'.'+working_point_member_id(point)+'.pa')
                for point in design['working_points']} for domain in domains}
            downstream = {}
            for role in ('flight_tube','reflectron','detector'):
                family = [record(role+suffix) for suffix in ('.pa#','.pa0','.pa1','.pa-surf')] if role!='reflectron' else []
                downstream[role] = dict(carrier_record=family[1] if family else record(role+'.pa'), family_records=family)
            kwargs = dict(field_design=design, stored_bank=field_bank(design, domains), frontend_records=frontend,
                          downstream_assets=downstream, downstream_receipt=record('audit.json'), native_sources=sources)
            plan = plan_tracking_execution(self.case.model, particles=self.case.packet,
                clock_records=self.case.clocks, propagation=self.case.policy, observations=self.observations,
                numerics=self.case.numerics, unit_size=50)
            first = _render_tracking_controls(self.case.model, slice_tracking_plan(plan, plan['units'][0]), **kwargs)
            second = _render_tracking_controls(self.case.model, slice_tracking_plan(plan, plan['units'][1]), **kwargs)
            self.assertIn('applied_field_observation_header', first['program'])
            self.assertEqual(first['build_metadata']['native_field_observation']['specification'], self.spec)
            self.assertNotIn('applied_field_observation_header', second['program'])
            self.assertNotIn('native_field_observation', second['build_metadata'])

    def test_renderer_binds_static_detector_carrier_and_slot(self):
        self.spec["domain_id"] = "detector"
        from pathlib import Path
        import tempfile
        from msplatform.backends.simion.tracking_execution import _render_tracking_controls
        from msplatform.backends.simion.native_plans import plan_solve_fields
        from msplatform.backends.simion.field_bank import field_bank
        from msplatform.backends.simion.field_identity import working_point_member_id
        from msplatform.backends.simion.resources import native_resource_path
        from msplatform.backends.simion.tracking_units import slice_tracking_plan
        from msplatform.execution.resources import resource_path
        numerical = copy.deepcopy(self.case.case.field_numerics)
        numerical.pop('downstream_convergence_v')
        design = plan_solve_fields(self.case.model, numerics=numerical)['field_design']
        domains = [row['domain_id'] for row in design['domains']]
        names = dict(analyzer_component_source='oatof_analyzer_component.lua', pulse_hook_source='single_flight_pulse_hook.lua',
                     frontend_hook_source='single_flight_frontend_hook.lua', rf_drive_kernel_source='rf_drive.lua',
                     voltage_waveforms_source='voltage_waveforms.lua')
        sources = {key:native_resource_path(value).read_text(encoding='utf-8') for key,value in names.items()}
        sources['native_path_source'] = resource_path('native_run_path.lua').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def record(name):
                return dict(path=str(root/name), exists=True, bytes=123, sha256='A'*64)
            frontend = {domain:{working_point_member_id(point):record(
                ('frontend' if domain=='parent' else 'frontend_entrance_refinement')+'.'+working_point_member_id(point)+'.pa')
                for point in design['working_points']} for domain in domains}
            downstream = {}
            for role in ('flight_tube','reflectron','detector'):
                family = [record(role+suffix) for suffix in ('.pa#','.pa0','.pa1','.pa-surf')] if role!='reflectron' else []
                downstream[role] = dict(carrier_record=family[1] if family else record(role+'.pa'), family_records=family)
            kwargs = dict(field_design=design, stored_bank=field_bank(design, domains), frontend_records=frontend,
                          downstream_assets=downstream, downstream_receipt=record('audit.json'), native_sources=sources)
            plan = plan_tracking_execution(self.case.model, particles=self.case.packet,
                clock_records=self.case.clocks, propagation=self.case.policy, observations=self.observations,
                numerics=self.case.numerics, unit_size=50)
            first = _render_tracking_controls(self.case.model, slice_tracking_plan(plan, plan['units'][0]), **kwargs)
            second = _render_tracking_controls(self.case.model, slice_tracking_plan(plan, plan['units'][1]), **kwargs)
            self.assertIn('applied_field_observation_header', first['program'])
            self.assertEqual(first['build_metadata']['native_field_observation']['specification'], self.spec)
            context = first['build_metadata']['native_field_observation']['context']
            self.assertEqual(context['instance_index'], 4)
            self.assertEqual(context['observation_basis'], 'native_entry_gradient_no_extra_query')
            self.assertEqual(context['static_carrier_record'], downstream['detector']['carrier_record'])
            self.assertIn("basis='native_entry_gradient_no_extra_query'", first['program'])
            self.assertIn('carrier_native_path=instance.pa.path', first['program'])
            self.assertNotIn('applied_field_observation_header', second['program'])
            self.assertNotIn('native_field_observation', second['build_metadata'])
            for role, index in (('flight_tube',1),('reflectron',2)):
                self.spec['domain_id'] = role
                selected = plan_tracking_execution(self.case.model, particles=self.case.packet,
                    clock_records=self.case.clocks, propagation=self.case.policy, observations=self.observations,
                    numerics=self.case.numerics, unit_size=50)
                value = _render_tracking_controls(self.case.model, slice_tracking_plan(selected, selected['units'][0]), **kwargs)
                actual = value['build_metadata']['native_field_observation']['context']
                self.assertEqual(actual['instance_index'], index)
                self.assertEqual(actual['static_carrier_record'], downstream[role]['carrier_record'])

    def test_observation_affects_recovery_identity(self):
        from msplatform.backends.simion.tracking_units import tracking_applicability
        plain = self.plan(dict(plane_observations=[]))
        observed = self.plan(self.observations)
        self.assertNotEqual(tracking_applicability(plain), tracking_applicability(observed))
        self.assertEqual(observed['observations'], self.observations)

if __name__=='__main__': unittest.main()
