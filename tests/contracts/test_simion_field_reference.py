"""Software-only admission contracts for an explicit SIMION field source."""
import base64
import copy
import hashlib
import json
import shutil
from pathlib import Path
import tempfile
import unittest

from msplatform import assembly, components
from msplatform.backends import simion
from msplatform.backends.simion.field_bank import field_bank
from msplatform.backends.simion.field_identity import working_point_member_id
from msplatform.backends.simion.model import compile_prepared_model, model_geometry
from msplatform.backends.simion.native_plans import plan_solve_fields
from msplatform.io.file_identity import canonical_json_sha256
from msplatform.io.manifest_records import file_record
from msplatform.recipes import load_recipe
from msplatform.workflows.native_tracing import _admit_simion_field_reference as admit_simion_field_reference


EXAMPLES = Path(__file__).resolve().parents[2]/'src/msplatform/examples'


def fixture(root, mutation=None):
    """Construct an inert manifest/data fixture; PA bytes are not native evidence."""
    stem='oa_split_tof_native_small_v1'
    study_bytes=(EXAMPLES/(stem+'.json')).read_bytes()
    (root/(stem+'.json')).write_bytes(study_bytes)
    original=(EXAMPLES/(stem+'.toml')).read_text(encoding='utf8')
    raw_recipe=load_recipe(EXAMPLES/(stem+'.toml')).to_dict()
    study=raw_recipe['study']['document']
    parts={name:components.resolve_component(req) for name,req in study['component_requests'].items()}
    instrument=assembly.assemble(study['recipe'],parts)
    compiled=simion.compile_geometry(instrument,numerics=study['numerics']['geometry'])
    drive=copy.deepcopy(study['drive']);drive.pop('clock_authority')
    authority=json.loads(base64.b64decode(raw_recipe['resource_snapshots']['instrument_clock_authority_v1.json']['bytes_base64']))
    drive['clock'].update(clock_epoch_id=authority['clock_epoch_id'],authority_sha256=authority['authority']['sha256'])
    model=compile_prepared_model(compiled,instrument.components_resolved,drive=drive,physics=study['physics'])
    field_numerics=study['numerics']['fields']
    field_plan=plan_solve_fields(model,numerics={k:v for k,v in field_numerics.items() if k!='downstream_convergence_v'})
    design=field_plan['field_design'];domains=[d['domain_id'] for d in design['domains']]
    records={}; folder=root/'field';folder.mkdir()
    def put(key, name, content):
        path=folder/name;path.write_bytes(content if isinstance(content,bytes) else json.dumps(content).encode())
        records[key]=file_record(path,'required_evidence')
    stored_model=copy.deepcopy(model.document)
    if mutation=='drive':
        from msplatform.backends.simion.compiler import _content_sha256
        stored_model['drive']['pulse']['time_us'] += 1.
        stored_model.pop('model_identity_sha256')
        stored_model['model_identity_sha256']=_content_sha256(stored_model)
    put('compiled_model','model.json',stored_model)
    actual_numerics=copy.deepcopy(field_numerics)
    if mutation=='numerics': actual_numerics['downstream_convergence_v']['detector'] *= 2
    actual_design=copy.deepcopy(design)
    if mutation=='design': actual_design['working_points'][0]['electrode_voltages_v']['1'] = 123.
    put('field_numerics','numerics.json',actual_numerics)
    put('field_design','design.json',actual_design)
    put('field_bank','bank.json',field_bank(design,domains))
    put('clock_authority','instrument_clock_authority_v1.json',(EXAMPLES/'instrument_clock_authority_v1.json').read_bytes())
    put('instrument_epoch','instrument_epoch_v1.json',(EXAMPLES/'instrument_epoch_v1.json').read_bytes())
    put('workbench','fields.iob',b'inert-workbench');put('zero_particle_format_control','fields.fly2',b'inert-zero')
    put('downstream_audit','audit.json',{})
    members={}
    for domain in domains:
        members[domain]={}
        for point in design['working_points']:
            name=working_point_member_id(point);key=domain+'_'+name
            put(key,'frontend.'+name+'.pa',b'inert-pa-'+name.encode())
            members[domain][name]=dict(data_key=key,cache_key='fixture',generation_directory='unused')
    native_assets={}
    for role in ('flight_tube','reflectron','detector'):
        names=[role+'.pa'] if role=='reflectron' else [role+x for x in ('.pa#','.pa0','.pa1','.pa-surf')]
        for name in names:put(name,name,b'inert-native-'+name.encode())
        native_assets[role]=dict(carrier=names[0] if role=='reflectron' else names[1],family=[] if role=='reflectron' else names)
    specs={s['role']:s for s in model_geometry(model).downstream_specs}
    spatial=dict(schema_version=1,role='simion_downstream_spatial_identity',raw_geometry={'fixture':[]},
        physical_inputs={role:dict(template_variables=s['template_variables'],grid={k:s['native_instance'][k] for k in ('nx','ny','nz')}) for role,s in specs.items()},
        convergence_v=field_numerics['downstream_convergence_v'],tool_identity={'fixture':'not_native'},builder_identities={'fixture':'not_native'})
    spatial['identity_sha256']=canonical_json_sha256(spatial)
    metadata=dict(backend='simion',field_status='available',source_status='not_requested',
        model_identity_sha256=stored_model['model_identity_sha256'],clock=stored_model['drive']['clock'],
        frontend_members=members,native_assets=native_assets,downstream_identity=spatial)
    if mutation=='clock': metadata['clock']['clock_epoch_id']='wrong-epoch'
    if mutation=='member': members[domains[0]].pop(next(iter(members[domains[0]])))
    manifest=dict(schema_version=1,role='simulation_run_manifest',status='success',inputs=records,outputs=[],
        products=dict(fields=dict(schema_version=1,kind='field_bundle',status='complete',metadata=metadata,data=records)))
    if mutation=='unbound':
        manifest['inputs']=dict(records)
        manifest['inputs'].pop('workbench')
    path=folder/'run_manifest.json';path.write_text(json.dumps(manifest),encoding='utf8')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    author=original.replace('kind = "simion_native"','kind = "simion_native"\n[field_source.reference]\npath = "field/run_manifest.json"\nsha256 = "'+digest+'"\nproduct_id = "fields"')
    recipe_path=root/'recipe.toml';recipe_path.write_text(author,encoding='utf8')
    return load_recipe(recipe_path).to_dict(),model,field_numerics,records,path


class SimionFieldReferenceTests(unittest.TestCase):
    def test_explicit_field_run_skips_build_and_holds_guard_through_track(self):
        # Software protocol fixture only: no native solver or native result.
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import patch
        import numpy as np
        from msplatform.ion_release import sample_release
        from msplatform.physics import CONSTANTS
        from msplatform.results.model import TraceResult
        from msplatform.results.detector_observation import detector_observation
        from msplatform.results.particle_data import write_particle_data
        from msplatform.workflows.native_tracing import _execute
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            recipe,model,_,_,_=fixture(root)
            selected=admit_simion_field_reference(recipe,expected_model=model,field_numerics=recipe['study']['document']['numerics']['fields'])
            release=sample_release(recipe['study']['document']['release'])
            initial=[];terminal=[]
            for row in release.rows:
                position=[row['position_'+a+'_mm']/1000 for a in 'xyz']
                velocity=[row['velocity_'+a+'_m_s'] for a in 'xyz']
                time=row['instrument_time_us']/1e6
                initial.append(dict(particle_id=row['particle_id'],species_id=row['species_id'],position_m=position,velocity_m_s=velocity,time_s=time,
                    mass_kg=row['mass_amu']*CONSTANTS['atomic_mass_constant_kg'],charge_state=row['charge_state'],
                    charge_c=row['charge_state']*CONSTANTS['elementary_charge_c'],weight=row['particle_weight'],
                    parent_particle_id=None,lineage_status='primary_birth'))
                terminal.append(dict(particle_id=row['particle_id'],species_id=row['species_id'],position_m=position,velocity_m_s=velocity,time_s=time,
                    physical_outcome='unknown',stop_reason='time_limit',component_id=None,electrode_id=None,surface_id=None,
                    attribution_method='unavailable',attribution_status='unavailable',started=True,backend_version='software-fixture',
                    native_termination_code=None,native_entity_id=None,detail=None))
            empty=dict(particle_id=np.empty(0,dtype='int64'),time_s=np.empty(0),position_m=np.empty((0,3)),velocity_m_s=np.empty((0,3)))
            observation=detector_observation('complete',[row['particle_id'] for row in initial])
            result=TraceResult(initial,terminal,[],empty,'succeeded',dict(status='complete',detector_observation=observation))
            path=root/'trajectory';path.mkdir()
            clock=dict(basis='experiment_relative',unit='s',**release.to_dict()['clock'])
            write_particle_data(path,result,metadata=dict(schema_version=2,initial_state_basis='native_birth_verified',
                frame_id=model.document['geometry']['frontend_geometry']['native_frame_id'],clock=clock))
            trajectory=SimpleNamespace(data_path=lambda key:path/'execution.json')
            work=root/'work';work.mkdir();(work/'author.toml').write_text('fixture',encoding='utf8')
            class Store:
                def new_work(self):
                    p=root/'asset-work';p.mkdir();return p
                @contextmanager
                def put_asset_claimed(self,*args,**kwargs): yield ('input-asset',root/'asset-work')
                @contextmanager
                def claim_token(self,*args): yield ('lease',root)
                def publish_run(self,*args,**kwargs): self.published=kwargs
            store=Store();active=[]
            @contextmanager
            def guard(*args,**kwargs):
                active.append(True)
                try: yield selected
                finally: active.pop()
            @contextmanager
            def protect(*args,**kwargs): yield
            def reference(store,stack,key,produce,*,kind,raw_root,claims,calls):
                self.assertIn(kind,('field_bundle','trajectory_result'));calls.append(key)
                return produce(),dict(asset_id=None,task_key=key,reused=False)
            def track(*args,**kwargs):
                self.assertTrue(active,'field owner guard must outlive track')
                return trajectory
            context=SimpleNamespace(workspace=root,tools={'simion':Path(__import__('sys').executable)})
            with patch('msplatform.execution.native_source_guard.guard_native_source',guard), \
                 patch('msplatform.execution.native_artifact_controls.protect_native_controls',protect), \
                 patch('msplatform.workflows.native_tracing._native_reference',side_effect=reference), \
                 patch('msplatform.backends.simion.grounded_runtime.prepare_grounded_runtime_fields',return_value=selected) as ground, \
                 patch('msplatform.backends.simion.track',side_effect=track) as fly, \
                 patch('msplatform.backends.simion.build_geometry') as build, \
                 patch('msplatform.backends.simion.prepare_model') as prepare, \
                 patch('msplatform.backends.simion.solve_fields') as solve:
                _execute(store,recipe,context,'run',work,'reservation',None)
            fly.assert_called_once();build.assert_not_called();prepare.assert_not_called();solve.assert_not_called()
            # This conversion seam tests orchestration only, not native ground certification.
            ground.assert_called_once_with(selected,context=context)
            provenance=json.loads((work/'provenance.json').read_text(encoding='utf8'))
            self.assertEqual(provenance['stages']['field']['reuse_scope'],'explicit_field_reference')
            self.assertEqual(provenance['stages']['field']['reference'],selected.reference)

    def test_reference_path_is_not_scientific_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            recipe,_,_,_,manifest=fixture(root)
            alternate=root/'other';alternate.mkdir()
            shutil.copyfile(manifest,alternate/'run_manifest.json')
            author=(root/'recipe.toml').read_text(encoding='utf8').replace('field/run_manifest.json','other/run_manifest.json')
            (root/'other.toml').write_text(author,encoding='utf8')
            other=load_recipe(root/'other.toml').to_dict()
            self.assertEqual(recipe['recipe_id'],other['recipe_id'])
            self.assertNotEqual(recipe['field_source']['reference']['reference']['manifest']['path'],
                                other['field_source']['reference']['reference']['manifest']['path'])

    def test_tampered_frozen_reference_rejected_before_source_guard(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.workflows.native_tracing import preflight_native

        with tempfile.TemporaryDirectory() as directory:
            recipe, _, _, _, _ = fixture(Path(directory))
            recipe['field_source']['reference']['snapshot']['sha256'] = '0' * 64
            with patch('msplatform.execution.native_source_guard.guard_native_source') as guard:
                with self.assertRaises(ValueError):
                    preflight_native(recipe, context=SimpleNamespace(workspace=Path(directory)))
                guard.assert_not_called()

    def test_scientific_mismatch_and_unbound_member_fail_closed(self):
        for mutation, message in (('numerics','field numerics differ'),('design','working-point design'),('drive','physical inputs, drive or clock'),
                                  ('clock','physical inputs, drive or clock'),('member','working-point members')):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                recipe,model,numerics,_,_=fixture(Path(directory),mutation)
                with self.assertRaisesRegex(ValueError,message):
                    admit_simion_field_reference(recipe,expected_model=model,field_numerics=numerics)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'not bound'):
                fixture(Path(directory),'unbound')

    def test_complete_scientific_reference_and_failed_or_missing_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            recipe,model,numerics,records,_=fixture(Path(directory))
            result=admit_simion_field_reference(recipe,expected_model=model,field_numerics=numerics)
            self.assertEqual(result.kind,'field_bundle')
            bad=copy.deepcopy(numerics);bad['downstream_convergence_v']['detector']*=2
            with self.assertRaisesRegex(ValueError,'numerics argument'):
                admit_simion_field_reference(recipe,expected_model=model,field_numerics=bad)
            member=next(name for name in records if name.startswith('parent_'))
            Path(records[member]['path']).unlink()
            with self.assertRaises((ValueError,AssertionError,OSError)):
                admit_simion_field_reference(recipe,expected_model=model,field_numerics=numerics)

    def test_science_model_and_frozen_manifest_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            recipe,model,numerics,records,path=fixture(Path(directory))
            changed=copy.deepcopy(model.document);changed['drive']['clock']['clock_epoch_id']='different'
            from msplatform.backends.simion.compiler import _content_sha256
            from msplatform.backends.simion.artifacts import CompiledPreparedModel
            changed.pop('model_identity_sha256');changed['model_identity_sha256']=_content_sha256(changed)
            other=CompiledPreparedModel(json.dumps(changed))
            with self.assertRaisesRegex(ValueError,'expected model differs'):
                admit_simion_field_reference(recipe,expected_model=other,field_numerics=numerics)
            data=json.loads(path.read_text());data['inputs'].pop('workbench');path.write_text(json.dumps(data),encoding='utf8')
            with self.assertRaises((ValueError,AssertionError,OSError)):
                admit_simion_field_reference(recipe,expected_model=model,field_numerics=numerics)


if __name__ == '__main__': unittest.main()
