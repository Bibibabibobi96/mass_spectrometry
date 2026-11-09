"""Independent RF unsolved-model contracts and explicitly inert owner transport."""
import copy
from dataclasses import asdict
import sys
from types import SimpleNamespace
import json
import math
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.test_simion_geometry_compiler import independent_rf_inputs
from common.contracts import test_simion_model_execution as fixture
from msplatform.backends import simion
from msplatform.backends.simion import model as model_api, model_execution
from msplatform.backends.simion.native_plans import plan_model_preparation
from msplatform.backends.simion.resources import native_resource_path, structural_seed_path
from msplatform.execution.clock_authority import validate_clock_authority
from msplatform.execution.resources import resource_path
from msplatform.io.manifest_records import file_record
from msplatform import capabilities


def rf_inputs():
    assembly, numerics = independent_rf_inputs()
    compiled = simion.compile_geometry(assembly, numerics=numerics)
    components = {name: compiled.components_resolved[name] for name in compiled.frontend_geometry['composition_plan']['scope']['instance_ids']}
    clock = dict(clock_epoch_id='RF_fixture_epoch', authority_sha256='A'*64, phase_reference_instrument_time_us=0.)
    drive = model_api.project_resolved_drive(compiled, components, clock=clock)
    return compiled, components, drive


def clock_reference():
    from importlib.resources import files
    root = Path(str(files('msplatform.examples')))
    path = root / 'instrument_clock_authority_v1.json'
    contract = json.loads(path.read_text(encoding='utf-8'))
    return dict(contract=file_record(path,'required_evidence'),
        authority=file_record(root / contract['authority']['path'],'required_evidence'), data_root=str(root))


def assets_at(root, compiled):
    result = {}
    root.mkdir(parents=True)
    for name in compiled.frontend_gems:
        entries = {}
        for label, suffix in [('raw_geometry','.pa#'),('fractional_surface','.pa-surf'),('surface_witnesses','.csv')]:
            path = root / (name+suffix)
            path.write_bytes(('INERT_NOT_NATIVE_'+label).encode())
            entries[label] = file_record(path, 'required_evidence' if label=='surface_witnesses' else 'solver_native_binary')
        result[name] = dict(raw_record=entries['raw_geometry'],surface_records=[entries['fractional_surface']],witness_record=entries['surface_witnesses'])
    return result


def inert_rf_session(root, source):
    root.mkdir(parents=True)
    session=fixture._InertModelSession(root,source)
    original=session.run_process
    def process(operation_id,**kwargs):
        original(operation_id,**kwargs)
        if operation_id in ('build_model','verify_model'):
            ordinal=session.expected_operation_ids.index(operation_id)+1
            marker='BUILD' if operation_id=='build_model' else 'READBACK'
            (session.log_dir/f'operation_{ordinal:04d}.stdout.log').write_text('INDEPENDENT_RF_MODEL_'+marker+'=PASS')
    session.run_process=process
    return session


class RfPreparedModelTests(unittest.TestCase):
    def test_actual_groups_frame_and_domain_targets_have_no_fake_tof_or_pulse(self):
        compiled, components, drive = rf_inputs()
        before = copy.deepcopy((compiled,components,drive))
        document = model_api.compile_prepared_model(compiled,components,drive=drive,physics=model_api.RF_PHYSICS).document
        self.assertEqual((compiled,components,drive),before)
        self.assertEqual(document['native_frame_id'],'rf_test_global')
        self.assertNotIn('pulse',document['drive'])
        self.assertNotIn('downstream_geometry',document)
        self.assertNotIn('pulse_voltage_policy_id',document['physics'])
        self.assertEqual(document['field_status'],'not_solved')
        self.assertEqual(document['source_status'],'not_requested')
        for row in document['native_drive_rows']:
            name,group=row['instance_id'],row['electrode_group_id']
            self.assertEqual(row['native_targets'],[dict(domain=name,electrode_id=compiled.frontend_geometry['electrode_bindings'][name][group])])
        self.assertEqual(set(document['drive']['groups']),{'first','second'})

    def test_mapping_permutations_and_malformed_real_drives_fail_at_same_compiler(self):
        compiled,components,drive=rf_inputs()
        assembly,numerics=independent_rf_inputs()
        numerics['electrode_group_native_ids']={name:{group:127-eid for group,eid in values.items()}
            for name,values in compiled.frontend_geometry['electrode_bindings'].items()}
        permuted=simion.compile_geometry(assembly,numerics=numerics)
        remapped=model_api.compile_prepared_model(permuted,components,drive=drive,physics=model_api.RF_PHYSICS).document
        for row in remapped['native_drive_rows']:
            self.assertEqual(row['native_targets'][0]['electrode_id'],numerics['electrode_group_native_ids'][row['instance_id']][row['electrode_group_id']])
        for mutation in ('pulse','missing_group','polarity','frequency','stale_geometry'):
            current=copy.deepcopy(drive)
            geometry=copy.deepcopy(compiled)
            if mutation=='pulse': current['pulse']=dict(mode='held_off')
            elif mutation=='missing_group': current['groups']['first'].pop(next(iter(current['groups']['first'])))
            elif mutation=='polarity':
                row=next(value for value in current['groups']['first'].values() if value['kind']=='rf')
                row['polarity'] *= -1
            elif mutation=='frequency':
                row=next(value for value in current['groups']['first'].values() if value['kind']=='rf')
                row['frequency_hz']=0
            else: geometry.frontend_geometry['numerical_domains']['first']['instance_origin_mm']['x']+=1
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                model_api.compile_prepared_model(geometry,components,drive=current,physics=model_api.RF_PHYSICS)

    def test_capability_uses_the_actual_rf_compiler_and_never_claims_native(self):
        compiled,components,drive=rf_inputs()
        arguments=dict(compiled=compiled,components_resolved=components,drive=drive,physics=model_api.RF_PHYSICS)
        result=capabilities.capabilities(dict(schema_version=1,operation='prepare_model',arguments=arguments))
        self.assertEqual(result['contract_status'],'accepted')
        self.assertEqual(result['validator'],'msplatform.backends.simion.model.compile_prepared_model')
        self.assertEqual(result['native_qualification'],'not_granted')
        arguments['drive']=dict(drive,pulse=dict(mode='held_off'))
        result=capabilities.capabilities(dict(schema_version=1,operation='prepare_model',arguments=arguments))
        self.assertNotEqual(result['contract_status'],'accepted')

    def test_plan_retains_both_native_companions_pose_and_only_three_operations(self):
        compiled,components,drive=rf_inputs()
        model=model_api.compile_prepared_model(compiled,components,drive=drive,physics=model_api.RF_PHYSICS)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            assets=assets_at(root/'source',compiled)
            seed=file_record(structural_seed_path(2),'required_evidence')
            plan=plan_model_preparation(model,geometry_assets=assets,run_directory=root/'run',seed_record=seed,native_path_resource=resource_path('native_run_path.lua'))
            self.assertEqual([op['operation_id'] for op in plan.operations],['materialize_geometry','build_model','verify_model'])
            self.assertEqual(len(plan.input_copies),7)
            self.assertEqual(sum(row['destination'].endswith('.csv') for row in plan.input_copies),2)
            self.assertTrue(all('refine' not in op['arguments'] and 'fly' not in op['arguments'] for op in plan.operations[1:]))
            spec=plan.materializations[str(root/'run/inputs/geometry_iob.lua')]
            self.assertIn('independent_rf_geometry_iob_build',spec)
            self.assertIn('surface_witnesses',spec)
            self.assertIn('rotation',spec)
            for name in ('first','second'):
                self.assertIn(name,spec)
            bad=copy.deepcopy(assets)
            del bad['first']['witness_record']
            with self.assertRaisesRegex(ValueError,'explicit raw and surface records'):
                plan_model_preparation(model,geometry_assets=bad,run_directory=root/'other',seed_record=seed,native_path_resource=resource_path('native_run_path.lua'))

    def test_actual_lua_rf_readback_does_not_initialize_any_pulse(self):
        compiled,components,drive=rf_inputs()
        for groups in drive['groups'].values():
            for row in groups.values():
                if row['kind']=='rf':
                    row.update(waveform='cosine',phase_rad=.37,rf_amplitude_v=17.,frequency_hz=1200000.,
                        common_mode_v=3.25,dc_v=row['polarity']*2.5)
        model=model_api.compile_prepared_model(compiled,components,drive=drive,physics=model_api.RF_PHYSICS)
        configuration=model_api.render_model_configuration(model)
        root=native_resource_path('model_drive.lua').parent
        script=("local config=(function() "+configuration+" end)(); local rf=dofile("+json.dumps(str(root/'rf_drive.lua'))+"); "
            "local consumer=dofile("+json.dumps(str(root/'model_drive.lua'))+").new(config,rf,{compile_physical=function() error('invented pulse') end},nil); "
            "assert(config.pulse==nil); for _,t in ipairs({0,0.125,0.25}) do for _,row in ipairs(consumer.evaluate_at(t)) do print(string.format('%s|%s|%.17g|%.17g',row.instance_id,row.electrode_group_id,t,row.voltage_v)) end end")
        result=subprocess.run([str(fixture.LUA),'-e',script],cwd=root,text=True,capture_output=True,timeout=30,check=True)
        for line in result.stdout.splitlines():
            instance,group,t,actual=line.split('|');row=drive['groups'][instance][group]
            expected=row['voltage_v'] if row['kind']=='static' else row['common_mode_v']+row['dc_v']+row['polarity']*row['rf_amplitude_v']*getattr(math,'sin' if row['waveform']=='sine' else 'cos')(2*math.pi*row['frequency_hz']*float(t)*1e-6+row['phase_rad'])
            self.assertAlmostEqual(float(actual),expected,places=10)

    def test_shared_action_copies_witness_evidence_and_uses_existing_materializer(self):
        compiled,components,drive=rf_inputs()
        reference=clock_reference()
        validated=validate_clock_authority(Path(reference['contract']['path']),Path(reference['data_root']))
        drive['clock'].update(clock_epoch_id=validated['clock_epoch_id'],authority_sha256=validated['authority_sha256'])
        model=model_api.compile_prepared_model(compiled,components,drive=drive,physics=model_api.RF_PHYSICS)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            assets=assets_at(root/'source',compiled)
            session=inert_rf_session(root/'run',root/'source')
            provenance=root/'source/manifest.json';provenance.write_text('{}')
            result=model_execution._execute_model_preparation(session,model=model,assets=assets,
                source_manifest_record=file_record(provenance,'required_evidence'),clock_authority_reference=reference,
                seed_record=file_record(structural_seed_path(2),'required_evidence'),limits={},
                materialize_geometry=fixture._inert_small_materialization,
                materializer_record=file_record(Path(fixture._inert_small_materialization.__code__.co_filename),'required_evidence'))
            product=result['manifest_extra_fields']['products']['model']
            self.assertEqual(product['kind'],'prepared_model')
            self.assertEqual(product['metadata']['field_status'],'not_solved')
            self.assertEqual(product['metadata']['native_frame_id'],'rf_test_global')
            self.assertEqual(set(product['metadata']['native_assets']),{'first','second'})
            for row in product['metadata']['native_assets'].values():
                self.assertEqual(set(row),{'raw_geometry','fractional_surface','surface_witnesses'})
                witness=product['data'][row['surface_witnesses']]
                self.assertEqual(witness['retention_role'],'required_evidence')
                self.assertIn('INERT_NOT_NATIVE',Path(witness['path']).read_text())
            self.assertEqual([row['operation_id'] for row in session.operations],['materialize_geometry','build_model','verify_model'])

    def test_published_geometry_requires_real_rf_surface_and_witness_bindings(self):
        from msplatform.execution.terminal_publication import publish_terminal_state
        compiled,components,drive=rf_inputs()
        reference=clock_reference()
        validated=validate_clock_authority(Path(reference['contract']['path']),Path(reference['data_root']))
        drive['clock'].update(clock_epoch_id=validated['clock_epoch_id'],authority_sha256=validated['authority_sha256'])
        model=model_api.compile_prepared_model(compiled,components,drive=drive,physics=model_api.RF_PHYSICS)
        with tempfile.TemporaryDirectory() as directory:
            for missing in (False,True):
                root=Path(directory)/str(missing)
                assets=assets_at(root/'producer',compiled)
                records={};names={}
                compiled_path=root/'producer/compiled.json'
                compiled_path.write_text(json.dumps(model.document['geometry']))
                records['compiled_geometry']=file_record(compiled_path,'required_evidence')
                for name,row in assets.items():
                    names[name]={}
                    for label,record in [('raw_geometry',row['raw_record']),('fractional_surface',row['surface_records'][0]),('surface_witnesses',row['witness_record'])]:
                        key=name+'_'+label;records[key]=record;names[name][label]=key
                if missing: del names['first']['surface_witnesses']
                manifest=dict(schema_version=2,role='simulation_run_manifest',run_id='inert-RF-source',
                    project='software_fixture',mode='explicit_inert_RF_geometry',status='success',inputs={},
                    outputs=list(records.values()),products=dict(geometry=dict(schema_version=1,kind='geometry_artifact',
                        status='complete',metadata=dict(backend='simion',geometry_materialized=True,field_status='not_solved',
                            source_status='not_requested',native_assets=names),data=records)))
                publish_terminal_state(root/'producer',{'status':'success'},manifest)
                session=inert_rf_session(root/'run',root/'producer')
                arguments=dict(model=model,geometry_reference=dict(manifest=file_record(root/'producer/run_manifest.json'),product_id='geometry'),
                    clock_authority_reference=reference,seed_record=file_record(structural_seed_path(2),'required_evidence'),
                    limits={},materialize_geometry=fixture._inert_small_materialization,
                    materializer_record=file_record(Path(fixture._inert_small_materialization.__code__.co_filename),'required_evidence'))
                with self.subTest(missing=missing),patch.object(model_execution,'resolve_consumed_run_capacity_owner',return_value=dict(run_directory=str(root/'producer'))),patch('subprocess.Popen',side_effect=AssertionError('no native process in inert fixture')):
                    if missing:
                        with self.assertRaisesRegex(ValueError,'surface closure differs'):
                            model_execution.execute_model(session,**arguments)
                        self.assertEqual(session.operations,[])
                    else:
                        result=model_execution.execute_model(session,**arguments)
                        self.assertEqual(result['manifest_extra_fields']['products']['model']['metadata']['field_status'],'not_solved')
                        self.assertEqual(len(session.operations),3)

    def test_public_prepare_dispatches_existing_owner_without_fake_pulse_or_tof_seed(self):
        compiled,components,_=rf_inputs()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=root/'compiled.json';path.write_text(json.dumps(asdict(compiled)))
            manifest=root/'source-manifest.json';manifest.write_text('INERT_SOURCE_BOUNDARY')
            source=SimpleNamespace(reference=dict(manifest=file_record(manifest,'required_evidence'),product_id='geometry'),data_path=lambda _key:path)
            context=SimpleNamespace(tools=dict(simion=Path(sys.executable)))
            stage=dict(limits=dict(transient_run_directory_bytes=1),artifact_retention=dict(policy_version=1,**{'class':'solver_review'},reason='inert fixture'))
            drive=dict(clock_authority=dict(example_resource='instrument_clock_authority_v1.json'),clock=dict(phase_reference_instrument_time_us=0.))
            with patch('msplatform.backends.simion.operations.artifact_reader.open_artifact',return_value=source),patch('msplatform.execution.stage_policy.read_stage_policy',return_value=(stage,file_record(path,'required_evidence'))),patch('msplatform.execution.owner.run_managed_stage',side_effect=RuntimeError('INERT_OWNER_BOUNDARY')) as managed:
                with self.assertRaisesRegex(RuntimeError,'INERT_OWNER_BOUNDARY'):
                    simion.prepare_model(source.reference,drive=drive,physics=model_api.RF_PHYSICS,context=context)
            request=managed.call_args.kwargs
            self.assertEqual(request['expected_operation_ids'],('materialize_geometry','build_model','verify_model'))
            self.assertIs(request['action'].func,model_execution.execute_model)
            self.assertNotIn('pulse',request['payload']['model']['drive'])
            self.assertEqual(request['payload']['model']['native_frame_id'],'rf_test_global')
            self.assertEqual(request['action'].keywords['seed_record'],file_record(structural_seed_path(2),'required_evidence'))
            self.assertEqual(request['source_references'],[dict(manifest_record=source.reference['manifest'])])

    def test_single_real_rf_model_needs_no_connection_or_placeholder(self):
        from msplatform import assembly as assembly_api
        instrument,numerics=independent_rf_inputs()
        recipe=instrument.composition_plan['recipe']
        recipe['instances']=recipe['instances'][:1]
        recipe['connections']=[]
        single=assembly_api.assemble(recipe,{'first':instrument.components['first']})
        compiled=simion.compile_geometry(single,numerics=dict(component_domains={'first':numerics['component_domains']['first']}))
        components={'first':compiled.components_resolved['first']}
        drive=model_api.project_resolved_drive(compiled,components,clock=dict(clock_epoch_id='single_RF',authority_sha256='A'*64,phase_reference_instrument_time_us=0.))
        document=model_api.compile_prepared_model(compiled,components,drive=drive,physics=model_api.RF_PHYSICS).document
        self.assertEqual(set(document['components_resolved']),{'first'})
        self.assertEqual(document['geometry']['frontend_geometry']['composition_plan']['connection_checks'],[])
        self.assertTrue(all(row['native_targets'][0]['domain']=='first' for row in document['native_drive_rows']))
