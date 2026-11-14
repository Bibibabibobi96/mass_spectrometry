"""Public artifact admission fixtures; no native solve or field qualification."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from msplatform import assembly as assembly_api, components as component_api, examples as example_api
from msplatform import ion_release as ion_release_api
from msplatform.backends import simion as simion_api
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.backends.comsol.assembly_electrostatic_model import validate_request
from msplatform.backends.simion.model import PHYSICS, compile_prepared_model, project_resolved_drive
from msplatform.backends.simion.native_plans import plan_solve_fields
from msplatform.backends.simion.sfi_scalar_binding import _group_vectors, resolve_sfi_scalar_basis
from msplatform.backends.simion.standalone_pa_composition import PaHeader
from msplatform.execution.terminal_publication import publish_terminal_state
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import open_artifact

SOLUTION={'study_tag':'std1','solution_tag':'sol1','dataset_tag':'dset1','dataset_solution':'sol1',
          'solution_empty':False,'solution_count':1,'stored_main_solutions':1,'solution_dofs':7}

class SfiScalarAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        case=example_api.load_example('rf_oatof_functional_v1')
        parts={key:component_api.resolve_component(value) for key,value in case.component_requests.items()}
        assembly=assembly_api.assemble(case.recipe,parts)
        self.snapshot=dict(composition_plan=assembly.composition_plan,components_resolved=assembly.components_resolved,components_source=assembly.components_source)
        compiled=simion_api.compile_geometry(assembly,numerics=case.geometry_numerics)
        packet=ion_release_api.sample_release(case.release).to_dict()
        pulse=dict(mode='timed',time_us=10.,width_us=2.)
        drive=project_resolved_drive(compiled,compiled.components_resolved,pulse=pulse,clock=dict(packet['clock'],phase_reference_instrument_time_us=0.))
        self.model=compile_prepared_model(compiled,compiled.components_resolved,drive=drive,physics=PHYSICS)
        numerics=copy.deepcopy(case.field_numerics);numerics.pop('downstream_convergence_v')
        self.design=plan_solve_fields(self.model,numerics=numerics)['field_design'];self.geometry=compiled.frontend_geometry
        self.flight=dict(pulse=pulse,maximum_flight_us=200.,maximum_step_us=.001,trajectory_quality=17,rf_steps_per_period=80)
        self.projection=project_assembly_geometry(self.snapshot,outer_box_mm={'min':[-10000]*3,'max':[10000]*3})
        self.vectors,_=_group_vectors(self.model.document['drive'])
        self.geometry_ref=self.make_geometry(); self.sample_refs={name:self.make_sample(name) for name in self.vectors}

    def publish(self, name, kind, data, metadata, inputs=None, linked=None):
        run=self.root/name;run.mkdir();records={};outputs=[]
        for key,value in data.items():
            suffix = '.pa' if key in ('field_v', 'field_valid') else '.mph'
            path=run/(key+suffix if isinstance(value,bytes) else key+'.json')
            path.write_bytes(value if isinstance(value,bytes) else json.dumps(value,allow_nan=False).encode())
            records[key]=file_record(path);outputs.append(records[key])
        bound_inputs={}
        for key,value in (inputs or {}).items():
            path=run/(key+'.json');path.write_text(json.dumps(value,allow_nan=False),encoding='utf8');bound_inputs[key]=file_record(path)
        for key,record in (linked or {}).items():
            bound_inputs[key]=record
            if key == 'field_solution_manifest': records[key]=record
        product_id='solution' if kind == 'field_solution' else 'product'
        manifest=dict(schema_version=2,role='simulation_run_manifest',run_id=name,project='instrument_assembly',mode='test_only',status='success',inputs=bound_inputs,outputs=outputs,products={product_id:dict(schema_version=1,kind=kind,status='complete',metadata=metadata,data=records)})
        publish_terminal_state(run,{'status':'success'},manifest)
        return {'manifest':file_record(run/'run_manifest.json'),'product_id':product_id}

    def make_geometry(self):
        payload={'role':'run_artifact_workflow_request','payload':{'action':'build_comsol_geometry','assembly':self.snapshot,'projection':self.projection}}
        return self.publish('geometry','geometry_artifact',{'projection':self.projection},{'backend':'comsol','scope':'geometry_only','native_reopen_verified':True},{'execution_request':payload})

    def make_sample(self,name):
        rows=[dict(instance_id=i,electrode_group_id=g,voltage_v=v) for (i,g),v in self.vectors[name].items()]
        request=dict(group_voltages=rows,relative_permittivity=1.,exterior={'kind':'potential','voltage_v':7. if name=='carrier' else 0.},mesh={'global_automatic_level':9,'electrode_hmax_mm':5.},study={'kind':'stationary'})
        request=validate_request(self.projection,request)
        grid=dict(frame_id=self.projection['assembly_frame_id'],origin_mm=[1. if name=='rf_reference' else 0.,0.,0.],pitch_mm=[1.,1.,1.],dimensions=[3,3,3],block_points=4,study_tag='std1',solution_tag='sol1',dataset_tag='dset1',point_count=27,maximum_mm=[3. if name=='rf_reference' else 2.,2.,2.],coordinate_sanity_mm=1e-6)
        pa=PaHeader(-2,1,10000.,3,3,3,1<<28,1.,1.,1.).pack()+bytes(27*8)
        data={'projection':self.projection,'request':request,'geometry_validation':{'position_mm':1e-6},'reopen_geometry':{'vacuum_domains':[1]},'reopen_solution':{'solution':SOLUTION},'model':b'inert model, never opened as MPH'}
        meta={'backend':'comsol','scope':'single_stationary_workpoint','field_status':'solved','native_reopen_verified':True,'solution':SOLUTION}
        source_ref=self.publish('solution-'+name,'field_solution',data,meta)
        from msplatform.results.artifacts import open_artifact
        source=open_artifact(source_ref,expected_kind='field_solution')
        report=dict(status='success',scope='assembly_world_scalar_samples',field_qualification=False,compute_calls=0,filled_conductor_count=0,coordinate_mapping='world_identity',model_path=str(source.data_path('model')),vacuum_domains=[1],fem_valid=27,invalid_count=0,solution_readback=SOLUTION,coordinate_witness={'status':'insufficient','index':0,'requested_mm':[],'actual_mm':[],'geometry_length_unit':'mm'},**grid)
        sample_data={'projection':self.projection,'grid':grid,'request':request,'reopen_solution':{'solution':SOLUTION},'geometry_validation':{'position_mm':1e-6},'reopen_geometry':{'vacuum_domains':[1]},'report':report,'field_v':pa,'field_valid':pa}
        linked={'field_solution_manifest':source_ref['manifest'],'field_solution_model':source.data_records['model']}
        # field_solution_model is an input identity, not an exported data member.
        result=self.publish(name,'scalar_field_samples',sample_data,{'backend':'comsol','scope':'assembly_world_scalar_samples','field_status':'sampled','frame_id':grid['frame_id']},linked=linked)
        return result
    def resolve(self):
        return resolve_sfi_scalar_basis(model=self.model,geometry=self.geometry,field_design=self.design,flight=self.flight,geometry_artifact=self.geometry_ref,samples=self.sample_refs)

    def test_real_compiled_model_and_published_artifacts(self):
        actual=self.resolve();self.assertEqual(set(actual['bases']),{'carrier','rf_reference','pulse_delta'});self.assertEqual(actual['scope'],'identity_admission_only_not_coverage_or_qualification');self.assertNotEqual(actual['bases']['carrier']['grid']['origin_mm'],actual['bases']['rf_reference']['grid']['origin_mm']);self.assertEqual(actual['carrier_exterior_voltage_v'],7.)

    def test_scalar_consumption_does_not_require_upstream_native_payload(self):
        for name in self.sample_refs:
            (self.root / ('solution-' + name) / 'model.mph').unlink()
        self.assertEqual(set(self.resolve()['bases']), set(self.sample_refs))

    def test_sample_cannot_claim_a_different_solved_workpoint(self):
        item = open_artifact(self.sample_refs['carrier'], expected_kind='scalar_field_samples')
        source_manifest = json.loads(item.data_path('field_solution_manifest').read_text(encoding='utf-8'))
        source_product = source_manifest['products']['solution']
        source_data = {}
        for key, record in source_product['data'].items():
            path = Path(record['path'])
            source_data[key] = path.read_bytes() if key == 'model' else json.loads(path.read_text(encoding='utf-8'))
        source_data['request']['group_voltages'][0]['voltage_v'] += 1.
        wrong = self.publish('wrong-solution', 'field_solution', source_data, source_product['metadata'])
        wrong_model = open_artifact(wrong, expected_kind='field_solution').data_records['model']
        sample_data = {}
        for key in item.data_records:
            if key == 'field_solution_manifest':
                continue
            path = item.data_path(key)
            sample_data[key] = path.read_bytes() if key in ('field_v', 'field_valid') else json.loads(path.read_text(encoding='utf-8'))
        self.sample_refs['carrier'] = self.publish(
            'wrong-solution-sample', 'scalar_field_samples', sample_data, item.metadata,
            linked={'field_solution_manifest': wrong['manifest'], 'field_solution_model': wrong_model})
        with self.assertRaisesRegex(ValueError, 'source workpoint copy differs: request'):
            self.resolve()

    def test_unknown_or_provisional_geometry_manifest_is_rejected(self):
        path = Path(self.geometry_ref['manifest']['path'])
        original = json.loads(path.read_text(encoding='utf-8'))
        for change in ({'schema_version': 999}, {'lifecycle_state': 'provisional'}):
            with self.subTest(change=change):
                path.write_text(json.dumps(dict(original, **change)), encoding='utf-8')
                self.geometry_ref['manifest'] = file_record(path)
                with self.assertRaisesRegex(ValueError, 'successful complete published product required'):
                    self.resolve()

    def test_manifest_and_payload_tamper_refused(self):
        path=Path(self.sample_refs['carrier']['manifest']['path']);path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(AssertionError,'manifest .* byte count changed'):self.resolve()

    def test_real_geometry_and_sample_records_cannot_be_silently_replaced(self):
        path=self.root/'geometry'/'projection.json';path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(AssertionError,'manifest .* byte count changed'):self.resolve()

    def test_unequal_rf_amplitudes_share_temporal_basis(self):
        drive=copy.deepcopy(self.model.document['drive']); rows=[r for groups in drive['groups'].values() for r in groups.values() if r['kind']=='rf'];self.assertGreater(len(rows),1)
        rows[0]['rf_amplitude_v']*=2
        vectors,rf=_group_vectors(drive);self.assertEqual(len(vectors['rf_reference']),len(vectors['carrier']));self.assertNotIn('reference_voltage_v',rf)
        rows[0]['phase_rad']+=.1
        with self.assertRaisesRegex(ValueError,'common RF'):_group_vectors(drive)

    def replacement_sample(self, name, key, change):
        from msplatform.results.artifacts import open_artifact
        item=open_artifact(self.sample_refs[name],expected_kind='scalar_field_samples')
        data={}
        for field in item.data_records:
            if field == 'field_solution_manifest': continue
            path=item.data_path(field)
            data[field]=path.read_bytes() if field in ('field_v','field_valid') else json.loads(path.read_text(encoding='utf8'))
        change(data[key])
        source_path=item.data_path('field_solution_manifest');source=json.loads(source_path.read_text(encoding='utf8'))
        linked={'field_solution_manifest':item.data_records['field_solution_manifest'],'field_solution_model':source['products']['solution']['data']['model']}
        return self.publish('replacement-'+name+'-'+key,'scalar_field_samples',data,item.metadata,linked=linked)

    def test_republished_changed_voltage_is_rejected(self):
        self.sample_refs['carrier']=self.replacement_sample('carrier','request',lambda d:d['group_voltages'][0].__setitem__('voltage_v',d['group_voltages'][0]['voltage_v']+1.))
        with self.assertRaisesRegex(ValueError,'source workpoint copy differs'):self.resolve()

    def test_republished_changed_grid_is_rejected(self):
        self.sample_refs['carrier']=self.replacement_sample('carrier','grid',lambda d:d['origin_mm'].__setitem__(0,1.))
        with self.assertRaises(ValueError):self.resolve()

    def test_republished_changed_member_is_rejected(self):
        self.sample_refs['carrier']=self.replacement_sample('carrier','projection',lambda d:d['members'][0].__setitem__('member_id','wrong'))
        with self.assertRaises(ValueError):self.resolve()

    def test_republished_wrong_report_grid_is_rejected(self):
        self.sample_refs['carrier']=self.replacement_sample('carrier','report',lambda d:d['origin_mm'].__setitem__(0,2.))
        with self.assertRaisesRegex(ValueError,'world scalar grid or solution differs'):self.resolve()

    def test_republished_wrong_dataset_is_rejected(self):
        self.sample_refs['carrier']=self.replacement_sample('carrier','grid',lambda d:d.__setitem__('dataset_tag','wrong'))
        with self.assertRaisesRegex(ValueError,'solution identity'):self.resolve()

    def test_different_physical_pose_is_rejected(self):
        changed=copy.deepcopy(self.snapshot)
        changed['composition_plan']['recipe']['instances'][0]['transform']['translation_mm'][0]+=1.
        other=self.publish('different-pose','geometry_artifact',{'projection':self.projection},{'backend':'comsol','scope':'geometry_only','native_reopen_verified':True},{'execution_request':{'role':'run_artifact_workflow_request','payload':{'action':'build_comsol_geometry','assembly':changed,'projection':self.projection}}})
        self.geometry_ref=other
        with self.assertRaises(ValueError):self.resolve()

    def test_different_component_source_is_rejected(self):
        changed=copy.deepcopy(self.snapshot);changed['components_source']['multipole']['geometry_mm']['inscribed_radius_r0']+=1.
        other=self.publish('different-source','geometry_artifact',{'projection':self.projection},{'backend':'comsol','scope':'geometry_only','native_reopen_verified':True},{'execution_request':{'role':'run_artifact_workflow_request','payload':{'action':'build_comsol_geometry','assembly':changed,'projection':self.projection}}})
        self.geometry_ref=other
        with self.assertRaisesRegex(ValueError, 'RF resolved design differs from its explicit source request'):
            self.resolve()
