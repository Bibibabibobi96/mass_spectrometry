"""Recorded births pass through the public recipe without a native solver."""
import base64
import copy
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from msplatform.particle_release import sample_release
from msplatform.particle_release.cylinder import CANONICAL_COLUMNS
from msplatform.recipes import load_recipe
from msplatform.workflows.native_tracing import _realizations, preflight_native

EXAMPLES = Path(__file__).resolve().parents[2] / 'src/msplatform/examples'


class PublicRecordedBirthTests(unittest.TestCase):
    def test_public_recorded_run_publishes_and_rereads_with_inert_native_leaf(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import patch
        import re
        import sys
        import numpy as np
        from msplatform.physics import CONSTANTS
        from msplatform.results.model import TraceResult
        from msplatform.results.detector_observation import detector_observation
        from msplatform.results.particle_data import write_particle_data
        from msplatform.workflows.tracing import run_recipe
        from tests.contracts.test_simion_field_reference import fixture
        from msplatform.workflows.native_tracing import _admit_simion_field_reference
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            original,model,_,_,_=fixture(root)
            selected=_admit_simion_field_reference(original,expected_model=model,
                field_numerics=original['study']['document']['numerics']['fields'])
            study=copy.deepcopy(original['study']['document']);release=study['release']
            generated=sample_release(release).to_dict()['realization']['generator_rows']
            source=root/'birth.csv'
            with source.open('w',encoding='utf8',newline='') as handle:
                writer=csv.DictWriter(handle,fieldnames=CANONICAL_COLUMNS,extrasaction='ignore',lineterminator='\n')
                writer.writeheader();writer.writerows(generated)
            data=source.read_bytes()
            study['release']={'schema_version':1,'role':'canonical_recorded_birth_request',
                'source_record':{'path':'birth.csv','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest().upper()},
                'clock':release['clock'],'instrument_origin_us':release['instrument_origin_us'],
                'species_id':release['species_id'],'species':release['release_spec']['species'],
                'source_component_id':release['source_component_id'],'frame_id':release['release_spec']['frame_id'],
                'relative_weights':release['relative_weights'],'particle_ids':[row['particle_id'] for row in generated]}
            content=json.dumps(study).encode();(root/'oa_split_tof_native_small_v1.json').write_bytes(content)
            author=root/'recipe.toml';text=author.read_text(encoding='utf8')
            text=re.sub(r'(?m)^sha256 = "[a-fA-F0-9]{64}"', 'sha256 = "'+hashlib.sha256(content).hexdigest()+'"',text,count=1)
            author.write_text(text,encoding='utf8')
            loaded=load_recipe(author);recipe=loaded.to_dict()
            frozen=root/'inputs';frozen.mkdir();(frozen/'recorded_birth.csv').write_bytes(data)
            packet=_realizations(study['release'],resource_root=frozen)[0]
            initial=[];terminal=[]
            for row in packet['rows']:
                position=[row['position_'+a+'_mm']/1000 for a in 'xyz'];velocity=[row['velocity_'+a+'_m_s'] for a in 'xyz'];time=row['instrument_time_us']/1e6
                initial.append(dict(particle_id=row['particle_id'],species_id=row['species_id'],position_m=position,velocity_m_s=velocity,time_s=time,
                    mass_kg=row['mass_amu']*CONSTANTS['atomic_mass_constant_kg'],charge_state=row['charge_state'],charge_c=row['charge_state']*CONSTANTS['elementary_charge_c'],
                    weight=row['particle_weight'],parent_particle_id=None,lineage_status='primary_birth'))
                terminal.append(dict(particle_id=row['particle_id'],species_id=row['species_id'],position_m=position,velocity_m_s=velocity,time_s=time,
                    physical_outcome='unknown',stop_reason='time_limit',component_id=None,electrode_id=None,surface_id=None,
                    attribution_method='unavailable',attribution_status='unavailable',started=True,backend_version='inert-software',native_termination_code=None,native_entity_id=None,detail=None))
            arrays=dict(particle_id=np.empty(0,dtype='int64'),time_s=np.empty(0),position_m=np.empty((0,3)),velocity_m_s=np.empty((0,3)))
            result=TraceResult(initial,terminal,[],arrays,'succeeded',dict(status='complete',detector_observation=detector_observation('complete',[r['particle_id'] for r in initial])))
            trajectory_dir=root/'trajectory';trajectory_dir.mkdir()
            write_particle_data(trajectory_dir,result,metadata=dict(schema_version=2,initial_state_basis='native_birth_verified',
                frame_id=model.document['geometry']['frontend_geometry']['native_frame_id'],clock={'basis':'experiment_relative','unit':'s',**packet['clock']},species=recipe['species']))
            trajectory=SimpleNamespace(data_path=lambda key:trajectory_dir/'execution.json')
            @contextmanager
            def guard(*args,**kwargs): yield selected
            @contextmanager
            def protect(*args,**kwargs): yield
            def reference(store,stack,key,produce,*,kind,raw_root,claims,calls,account,**kwargs):
                calls.append(key);return produce(),dict(asset_id=None,task_key=key,reused=False)
            def track(_field,particles,**kwargs):
                self.assertEqual(particles['recorded_source']['species_kind'],'ion')
                self.assertEqual([row['particle_id'] for row in particles['rows']],study['release']['particle_ids'])
                return trajectory
            workspace=root/'workspace';workspace.mkdir()
            context=SimpleNamespace(workspace=workspace,python_executable=Path(sys.executable),
                powershell_executable=Path(sys.executable),tools={'simion':Path(sys.executable)})
            with patch('msplatform.execution.native_source_guard.guard_native_source',guard), \
                 patch('msplatform.execution.native_artifact_controls.protect_native_controls',protect), \
                 patch('msplatform.workflows.native_tracing._native_reference',side_effect=reference), \
                 patch('msplatform.backends.simion.grounded_runtime.prepare_grounded_runtime_fields',return_value=selected), \
                 patch('msplatform.backends.simion.track',side_effect=track) as fly:
                output=run_recipe(author,artifact_root=root/'store',context=context,reserve_bytes=100_000_000)
                fly.assert_called_once()
                text = author.read_text(encoding='utf8').replace('[gas_environment]',
                    'field_interventions = [{id="base", selector="real"}, {id="drift", selector="ideal:drift.ez"}]\n\n[gas_environment]')
                author.write_text(text, encoding='utf8')
                fly.reset_mock()
                collection=run_recipe(author,artifact_root=root/'store',context=context,reserve_bytes=100_000_000)
                self.assertEqual(fly.call_count, 2)
                self.assertIs(fly.call_args_list[0].args[1], fly.call_args_list[1].args[1])
                self.assertEqual([call.kwargs['observations']['field_intervention']['id'] for call in fly.call_args_list], ['base', 'drift'])
                pulse = study['drive']['pulse']
                study['drive']['pulse'] = {'mode': 'discover', 'width_us': pulse['width_us'],
                    'candidate_times_us': [pulse['time_us'], pulse['time_us'] + 5.0]}
                updated = json.dumps(study).encode()
                (root/'oa_split_tof_native_small_v1.json').write_bytes(updated)
                discovery_text = re.sub(r'(?m)^sha256 = "[a-fA-F0-9]{64}"',
                    'sha256 = "' + hashlib.sha256(updated).hexdigest() + '"', text, count=1)
                discovery_text = discovery_text.replace('field_interventions = [{id="base", selector="real"}, {id="drift", selector="ideal:drift.ez"}]\n', '')
                author.write_text(discovery_text, encoding='utf8')
                pilot_dir = root/'inert-pilot'; pilot_dir.mkdir()
                for key in ('collection', 'observations', 'source_provenance', 'compiled_model'):
                    (pilot_dir/(key+'.json')).write_text('{}', encoding='utf8')
                manifest = pilot_dir/'run_manifest.json'; manifest.write_text('{}', encoding='utf8')
                pilot = SimpleNamespace(reference={'manifest': {'path': str(manifest), 'bytes': 2,
                    'sha256': hashlib.sha256(b'{}').hexdigest().upper()}, 'product_id': 'trajectory'},
                    data_path=lambda key: pilot_dir/(key+'.json'))
                (trajectory_dir/'collection.json').write_text(json.dumps({'discovery_resolution':
                    {'decision': {'status': 'success'}, 'effective_pulse': {'mode': 'timed', 'time_us': pulse['time_us'], 'width_us': pulse['width_us']}}}), encoding='utf8')
                trajectory.data_path = lambda key: trajectory_dir/('collection.json' if key == 'collection' else 'execution.json')
                def phase_track(_field, particles, **kwargs):
                    phase = kwargs['observations']['pulse_discovery']['phase']
                    return pilot if phase == 'discovery' else trajectory
                fly.side_effect = phase_track; fly.reset_mock()
                discovery = run_recipe(author,artifact_root=root/'store',context=context,reserve_bytes=100_000_000)
                self.assertEqual([call.kwargs['observations']['pulse_discovery']['phase'] for call in fly.call_args_list], ['discovery', 'selected'])
                self.assertIs(fly.call_args_list[0].args[1], fly.call_args_list[1].args[1])
                self.assertEqual(fly.call_args_list[1].kwargs['observations']['pulse_discovery']['pilot'], pilot.reference)
                self.assertTrue((Path(discovery['run_path'])/'discovery/0000/0000/selection.json').is_file())
            self.assertEqual(collection['summary']['role'], 'field_intervention_collection')
            self.assertEqual([case['id'] for case in collection['summary']['cases']], ['base', 'drift'])
            self.assertEqual(collection['summary']['cases'][0]['summary'], collection['summary']['cases'][1]['summary'])
            with self.assertRaisesRegex(ValueError, 'unique'):
                author.write_text(text.replace('id="drift"', 'id="base"'), encoding='utf8')
                load_recipe(author)
            from msplatform.workflows.tracing import inspect_results
            index = Path(collection['run_path']) / 'collection.json'
            changed = json.loads(index.read_text(encoding='utf8'))
            changed['cases'][1]['selector'] = 'real'
            index.write_text(json.dumps(changed), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'incomplete or modified'):
                inspect_results(collection['run_id'], artifact_root=root/'store')
            self.assertEqual(output['run_state']['execution_status'],'succeeded')
            self.assertEqual(output['summary']['execution_status'],'succeeded')
            from msplatform.results.particle_data import read_particle_data
            reread=read_particle_data(Path(output['run_path']))
            self.assertEqual(len(reread['initial_states']),len(initial))
            self.assertEqual(reread['metadata']['species'],recipe['species'])

    def test_owner_evidence_distinguishes_native_asset_and_external_reference(self):
        from types import SimpleNamespace
        from msplatform.workflows.native_tracing import _native_owner_evidence
        with tempfile.TemporaryDirectory() as directory:
            store=SimpleNamespace(root=Path(directory)/'store')
            stage=store.root/'assets/native_stage/ab/0123456789abcdef/runs/actual/run_manifest.json'
            artifact=SimpleNamespace(reference={'manifest':{'path':str(stage),'bytes':1,'sha256':'A'*64},'product_id':'fields'})
            evidence=_native_owner_evidence(store,artifact)
            self.assertEqual(evidence['kind'],'artifact_store_native_stage')
            self.assertEqual(evidence['asset_id'],'0123456789abcdef')
            self.assertEqual(evidence['manifest'],artifact.reference['manifest'])
            artifact.reference['manifest']['path']=str(Path(directory)/'old/runs/source/run_manifest.json')
            self.assertEqual(_native_owner_evidence(store,artifact)['kind'],'protected_external_native_source')

    def test_trace_reuse_changes_with_gas_data_or_vendor_identity(self):
        from msplatform.workflows.native_tracing import _trace_cache_key
        recipe={'gas_environment':{'status':'hs1','path':'hs1.json','sha256':'A'*64},
                'gas_data':{'species_data':{'dataset_sha256':'1'*64},'collision_assumption':{'dataset_sha256':'2'*64}},
                'resource_snapshots':{'hs1_environment.json':{'sha256':'3'*64},'hs1_vendor.lua':{'sha256':'4'*64}}}
        values=dict(field_key='field',particles={'source':'birth'},propagation={'scope':'continuous_assembly'},
                    observations={'plane_observations':[]},numerics={'step':1},recipe=recipe,implementation={'source':'fixed'})
        original=_trace_cache_key(**values)
        for mutate in ('species_data','collision_assumption','vendor'):
            changed=copy.deepcopy(recipe)
            if mutate=='vendor': changed['resource_snapshots']['hs1_vendor.lua']['sha256']='5'*64
            else: changed['gas_data'][mutate]['dataset_sha256']='5'*64
            self.assertNotEqual(original,_trace_cache_key(**dict(values,recipe=changed)))
        self.assertEqual(original,_trace_cache_key(**values))

    def test_cache_admits_no_detector_only_when_not_requested(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.workflows.native_tracing import _complete_trajectory
        artifact=SimpleNamespace(kind='trajectory_result',data_path=lambda key:Path('/tmp/particle_data_execution.json'))
        data={'execution_status':'succeeded','metadata':{'species':[{'species_id':'ion'}]},
              'data_integrity':{'status':'complete','detector_observation':{'status':'not_requested'}}}
        with patch('msplatform.workflows.native_tracing.read_particle_data',return_value=data):
            self.assertFalse(_complete_trajectory(artifact))
            self.assertTrue(_complete_trajectory(artifact,detector_required=False))
            data['data_integrity']['detector_observation']['status']='incomplete'
            self.assertFalse(_complete_trajectory(artifact,detector_required=False))
            data['data_integrity']['detector_observation']['status']='not_requested'
            data['metadata']['species']=[]
            self.assertFalse(_complete_trajectory(artifact,detector_required=False))

    def test_hs1_resources_are_frozen_and_typed_without_defaults(self):
        from msplatform.recipes.native import _resource_snapshots, _validate_resources
        from msplatform.workflows.native_tracing import _hs1_request
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            study=json.loads((EXAMPLES/'oa_split_tof_native_small_v1.json').read_bytes())
            author=json.loads((EXAMPLES.parent/'components/ion_processor/config/gas_environment.json').read_bytes())
            author['outer_state']=dict(pressure_pa=0.,temperature_k=300.,bulk_velocity_m_s=[0.,0.,0.])
            environment=json.dumps(author).encode()
            vendor=b'explicit test-only vendor bytes'
            (root/'environment.json').write_bytes(environment);(root/'vendor.lua').write_bytes(vendor)
            def record(name, data):
                return {'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest().upper()}
            box={'minimum_mm':[-1.,-1.,-1.], 'maximum_mm':[1.,1.,1.],
                 'lower_closed':[True]*3,'upper_closed':[True]*3}
            request={'bath_domain':box,'outer_domain':box,
                'numerics':{'seed':7,'hs1_steps_per_mfp':1},'environment_instance_id':'ip',
                'environment_record':record('environment.json',environment),'vendor_record':record('vendor.lua',vendor)}
            payload=json.dumps(request).encode();(root/'hs1.json').write_bytes(payload)
            gas={'status':'hs1','path':'hs1.json','sha256':hashlib.sha256(payload).hexdigest().upper()}
            snapshots=_resource_snapshots(study,root/'study.json',gas,root/'recipe.toml')
            _validate_resources(study,snapshots,gas)
            staged=root/'staged';staged.mkdir()
            for name,snapshot in snapshots.items():
                (staged/name).write_bytes(base64.b64decode(snapshot['bytes_base64']))
            parsed=_hs1_request({'gas_environment':gas},staged)
            self.assertEqual(parsed['environment_instance_id'],'ip')
            self.assertEqual(parsed['environment_record']['sha256'],hashlib.sha256(environment).hexdigest().upper())
            self.assertEqual(parsed['vendor_record']['sha256'],hashlib.sha256(vendor).hexdigest().upper())
            (root/'environment.json').write_bytes(b'tamper')
            with self.assertRaisesRegex(ValueError,'environment_record differs'):
                _resource_snapshots(study,root/'study.json',gas,root/'recipe.toml')

    def test_explicit_observations_do_not_invent_tof_detector(self):
        from types import SimpleNamespace
        from msplatform.workflows.native_tracing import _flight_request
        instrument=SimpleNamespace(components={'ip':SimpleNamespace(provider_id='ion_processor'),
                                                'mr':SimpleNamespace(provider_id='multi_reflection_tof')},
                                   composition_plan={'scope':{'instance_ids':['ip','mr']}})
        study={'numerics':{'tracing':{'end_policy':{'maximum_particle_age_us':100.}}}}
        recipe={'study':{'document':study},'recording':{'observation_times_us':[1.0], 'plane_observations':[]},
                'gas_environment':{'status':'vacuum'}}
        _, observations=_flight_request(recipe,instrument,{'rows':[{'particle_id':1}]})
        self.assertEqual(observations['plane_observations'],[])
        recipe['recording'].pop('plane_observations')
        with self.assertRaisesRegex(ValueError,'requires explicit plane observations'):
            _flight_request(recipe,instrument,{'rows':[{'particle_id':1}]})

    def test_frozen_recorded_birth_public_preflight_and_tamper_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = 'oa_split_tof_native_small_v1'
            study = json.loads((EXAMPLES / (name + '.json')).read_bytes())
            release = study['release']
            generated = sample_release(release).to_dict()['realization']['generator_rows']
            csv_path = root/'birth.csv'
            with csv_path.open('w', encoding='utf8', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=CANONICAL_COLUMNS, extrasaction='ignore', lineterminator='\n')
                writer.writeheader();writer.writerows(generated)
            payload=csv_path.read_bytes()
            study['release'] = {'schema_version':1, 'role':'canonical_recorded_birth_request',
                'source_record':{'path':'birth.csv','bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest().upper()},
                'clock':release['clock'],'instrument_origin_us':release['instrument_origin_us'],
                'species_id':release['species_id'],'species':release['release_spec']['species'],
                'source_component_id':release['source_component_id'],'frame_id':release['release_spec']['frame_id'],
                'relative_weights':release['relative_weights'], 'particle_ids':[row['particle_id'] for row in generated]}
            content=json.dumps(study).encode(); (root/(name+'.json')).write_bytes(content)
            text=(EXAMPLES/(name+'.toml')).read_text(encoding='utf8')
            import re
            text=re.sub(r'(?m)^sha256 = "[a-fA-F0-9]{64}"', 'sha256 = "'+hashlib.sha256(content).hexdigest()+'"', text, count=1)
            author=root/(name+'.toml');author.write_text(text,encoding='utf8')
            recipe=load_recipe(author).to_dict()
            self.assertTrue(preflight_native(recipe)['implemented'])
            self.assertFalse(preflight_native(recipe)['native_verified'])
            frozen=root/'frozen';frozen.mkdir();(frozen/'recorded_birth.csv').write_bytes(base64.b64decode(recipe['resource_snapshots']['recorded_birth.csv']['bytes_base64']))
            actual=_realizations(study['release'],resource_root=frozen)[0]
            self.assertEqual(actual['recorded_source']['species_kind'],'ion')
            self.assertEqual([row['particle_id'] for row in actual['rows']], study['release']['particle_ids'])
            bad=copy.deepcopy(study['release']);bad['species']['mass_amu'] *= 2
            with self.assertRaisesRegex(ValueError,'rows differ from the explicit species'):
                _realizations(bad,resource_root=frozen)
            bad=copy.deepcopy(recipe);del bad['study']['document']['release']['species']['species_kind']
            with self.assertRaises(ValueError): preflight_native(bad)
            csv_path.write_bytes(payload+b'tamper')
            self.assertTrue(preflight_native(recipe)['implemented'])
            with self.assertRaisesRegex(ValueError,'source bytes differ'):
                load_recipe(author)
            forged=copy.deepcopy(recipe);forged['resource_snapshots']['recorded_birth.csv']['bytes_base64']=base64.b64encode(b'bad').decode()
            with self.assertRaises(ValueError): preflight_native(forged)


if __name__ == '__main__': unittest.main()
