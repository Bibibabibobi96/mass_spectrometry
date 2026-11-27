"""Real managed field owner; native child replaced with inert process only."""
import copy
import os
from pathlib import Path
import tempfile
import shutil
from contextlib import contextmanager
import unittest
from functools import partial
from unittest.mock import patch
from tests.contracts.test_support import ip_mr_sampled_field_fixture as fixture
from msplatform.backends.simion.ip_mr_field_execution import execute_ip_mr_sampled_fields
from msplatform.execution.owner import run_managed_stage
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import open_artifact

@contextmanager
def retained_on_failure():
    root=Path(tempfile.mkdtemp(prefix='ip-mr-sampled-owner-'))
    try:
        yield root
    except BaseException:
        print('RETAINED_INERT_OWNER_FIXTURE',root,flush=True)
        raise
    else:
        shutil.rmtree(root)


def exercise_published_ip_mr_tracking(test, fields, context, tmp):
    """Actual public owner/action and generated Lua; native process leaf is inert."""
    import ast,json,os,sys
    from unittest.mock import patch
    from msplatform.backends.simion import operations
    from msplatform.backends.simion.ip_mr_tracking_admission import admit_ip_mr_tracking_fields
    from msplatform import examples as example_api, ion_release as ion_release_api
    from msplatform.contracts.gas import BoxDomain,GasFieldSpec,GasSource,GasSpecies,GasState
    from tests.components.ion_processor.test_functional import HS1_SOURCE_FIXTURE
    root=Path(tmp)/'public_tracking_fixture';root.mkdir()
    ref=fields.reference;ad=admit_ip_mr_tracking_fields(ref);baseline=ad['model'].document['drive']['ip_schedule']['baseline']
    box=lambda lo,hi:BoxDomain(lo,hi,(True,True,True),(True,True,True))
    outer=GasFieldSpec(field_id='outer',frame_id=baseline['clock']['frame_id'],representation='uniform',composition_id='ion_processor_explicit_single_gas',composition=(GasSpecies('ion_processor_model_gas',baseline['gas']['mass_amu'],1),),domain=box((-10000,-10000,-10000),(10000,10000,10000)),source=GasSource('prescribed','test',()),uniform_state=GasState('gas',4,baseline['gas']['temperature_k'],(1,2,3)))
    packet=ion_release_api.sample_release(example_api.load_example('rf_oatof_functional_v1').release).to_dict()
    vendor=root/'vendor.lua';vendor.write_text(HS1_SOURCE_FIXTURE,encoding='utf8')
    request=dict(bath_domain=box((0,-10,-10),(211,10,10)),outer=outer,vendor_record=file_record(vendor),numerics=dict(seed=40,hs1_steps_per_mfp=20))
    propagation=dict(schema_version=1,scope='continuous_assembly',dynamics=dict(kinematics='nonrelativistic',collisions='hs1',space_charge='none'),end_policy=dict(maximum_particle_age_us=200.),consumed_plane_events=[],stop=None)
    numerics=dict(maximum_step_us=.001,trajectory_quality=17,rf_steps_per_period=80,grouped=0)
    from msplatform.execution.run_session import RunSession
    original=RunSession.run_process;observed=[]
    provider=os.environ.get('SIMION_LUA_EXE') or shutil.which('lua') or shutil.which('lua5.1')
    if not provider: raise unittest.SkipTest('Lua 5.1 provider unavailable')
    lua=Path(provider)
    from tests.contracts import test_ip_mr_tracking_program as program_fixture
    test_path=Path(program_fixture.__file__)
    tree=ast.parse(test_path.read_text(encoding='utf8'))
    prefix=next(ast.literal_eval(node.value) for node in ast.walk(tree) if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='prefix' for t in node.targets))
    prefix=prefix.replace('BG_INDEX','5')
    def inert(session,operation_id,*,immutable_input_records,**kw):
     observed.append(operation_id);run=session.run_dir
     if operation_id=='build_tracking_iob':
      code="from pathlib import Path\n"+"Path("+repr(str(run/'simion/tracking/instrument.iob'))+").write_bytes(b'INERT_IOB')\n"
      for i in range(1,6):code+="Path("+repr(str(run/f'inputs/structural_seed/iob_seed_placeholder_{i:02d}.pa0'))+").write_bytes(b'INERT_BOOTSTRAP')\n"
      code+="print('IP_MR_SAMPLED_TRACKING_IOB=PASS')"
      executable=Path(sys.executable);args=['-I','-c',code]
     elif operation_id=='verify_tracking_iob':
      executable=Path(sys.executable);args=['-I','-c',"print('IP_MR_SAMPLED_TRACKING_IOB_REOPEN=PASS')"]
     elif operation_id=='track_fly':
      rows=json.loads((run/'inputs/canonical_source_states.json').read_text(encoding='utf8'))
      binding=json.loads((run/'inputs/sampled_basis.json').read_text(encoding='utf8'));grids={tuple(item['grid']['pitch_mm']) for item in binding['bases'].values()}
      assert len(grids)==1;pitch=next(iter(grids));assert pitch[0]==pitch[1]==pitch[2]
      actual_prefix=prefix.replace('dx_mm=1,dy_mm=1,dz_mm=1,debug_max_voltage=100','dx_mm=%s,dy_mm=%s,dz_mm=%s,debug_max_voltage=100'%pitch)
      program=(run/'simion/tracking/instrument.lua').read_text(encoding='utf8').replace('adjustable ','')
      suffix=['segment.initialize_run()']
      for i,row in enumerate(rows,1):
       suffix.append('ion_number=%d;ion_instance=1;ion_run=1;ion_time_of_birth=0;ion_time_of_flight=0;ion_splat=0;ion_mass=%.17g;ion_charge=%.17g'%(i,row['mass_amu'],row['charge_state']))
       suffix.append(';'.join('ion_p%s_mm=%.17g'%(x,row['position_'+x+'_mm']) for x in 'xyz'))
       suffix.append(';'.join('ion_v%s_mm=%.17g'%(x,row['velocity_'+x+'_m_s']/1000) for x in 'xyz'))
       suffix.append('segment.initialize();ion_time_of_flight=.1;ion_splat=nil;segment.terminate()')
      suffix.append("print('status,Fly completed. %d splats')"%len(rows))
      harness=root/'inert_generated_harness.lua';harness.write_text(actual_prefix+'\n'+program+'\n'+'\n'.join(suffix),encoding='utf8')
      executable=lua;args=[str(harness)]
     else:raise AssertionError(operation_id)
     return original(session,operation_id,executable=executable,arguments=args,role='GATE',stage='inert_generated_tracking',limits=kw['limits'],immutable_input_records=immutable_input_records)
    with test.assertRaisesRegex(ValueError,'already published'):
        operations.track(ref,packet,propagation=propagation,observations={'plane_observations':[]},numerics=numerics,context=context,hs1_request=request,scalar_field_basis={})
    with test.assertRaisesRegex(ValueError,'absolute predecessor'):
        operations.track(ref,packet,propagation=propagation,observations={'plane_observations':[]},numerics=numerics,context=context,hs1_request=request,recovery_reference={'path':'relative'})
    with patch.object(RunSession,'run_process',new=inert):
        result=operations.track(ref,packet,propagation=propagation,observations={'plane_observations':[]},numerics=numerics,context=context,hs1_request=request)
    test.assertEqual((result.kind,result.product_id),('trajectory_result','trajectory'))
    test.assertEqual(observed,['build_tracking_iob','verify_tracking_iob','track_fly'])
    collection=json.loads(result.data_path('collection').read_text(encoding='utf8'))
    test.assertEqual(collection['census']['execution_particle_ids'],collection['census']['mother_particle_ids'])
    test.assertEqual(len(collection['native_terminals']),len(packet['rows']))
    test.assertEqual(len(collection['original_mother']['mother_records']),len(packet['rows']))
    test.assertEqual(collection['mr_observations']['status'],'not_recorded')
    test.assertTrue(all(row['category']=='unknown_native_terminal' for row in collection['census']['terminal_taxonomy']['particle_outcomes']))


class SampledTrackingProducerTests(unittest.TestCase):
    @patch.dict(os.environ,{'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':''})
    def test_owner_publication_failure_and_source_guards(self):
        limits=dict(wall_clock_seconds=120,transient_run_directory_bytes=16777216,process_tree_working_set_bytes=536870912,minimum_system_available_memory_bytes=1,compact_final_retained_bytes=16777216,automatic_retry_count=0)
        with retained_on_failure() as tmp, fixture.build_sampled_field_fixture(tmp) as selected:
            ids=selected['expected_operation_ids'];prepared=selected['prepared'];observed=[]
            from msplatform.backends.simion.ip_mr_collision_lineage import collision_conversion_result
            plan=prepared['geometry_plan'];self.assertEqual(len(plan['tasks']),4);task=plan['tasks'][0]
            output=Path(task['output_path']);output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(b'INERT')
            surface=output.with_suffix('.pa-surf');surface.write_bytes(b'INERT')
            build=Path(tmp)/'build.log';verify=Path(tmp)/'verify.log';converter=Path(tmp)/'converter.lua';converter.write_text('-- inert',encoding='utf8')
            build.write_text('RAW_COLLISION_BUILD=PASS nodes=27 metal_nodes=2 surface_nodes=1 FIELD_STATUS=not_solved REFINE=False FLY=False\n',encoding='utf8')
            verify.write_text('RAW_COLLISION_VERIFY=PASS nodes=27 metal_nodes=2 surface_nodes=1 FIELD_STATUS=not_solved REFINE=False FLY=False\n',encoding='utf8')
            def lineage():return collision_conversion_result(plan,task,output_record=file_record(output),surface_record=file_record(surface),build_log_record=file_record(build),verify_log_record=file_record(verify),converter_record=file_record(converter))
            self.assertEqual(lineage()['nodes'],27)
            verify.write_text('RAW_COLLISION_VERIFY=PASS nodes=28 metal_nodes=2 surface_nodes=1 FIELD_STATUS=not_solved REFINE=False FLY=False\n',encoding='utf8')
            with self.assertRaisesRegex(ValueError,'node counts differ'):lineage()
            output.unlink();surface.unlink()
            def launch(run_id):
                return run_managed_stage(selected['context'],descriptor=dict(project='instrument_assembly',mode='sim',software=[]),run_id=run_id,payload={'action':'solve_fields','model':selected['model_reference']},committed_new_bytes=16777216,commitment_inputs=[selected['budget']],retention=selected['retention'],expected_operation_ids=ids,operation_dependencies={name:[ids[i-1]] for i,name in enumerate(ids) if i},action=partial(execute_ip_mr_sampled_fields,model_reference=selected['model_reference'],scalar_field_basis=selected['scalar_field_basis'],priority_evidence=selected['priority_evidence'],limits=limits),action_record=file_record(Path(__import__('msplatform.backends.simion.ip_mr_field_execution',fromlist=['']).__file__),'required_evidence'),source_references=prepared['source_references'],completion_api=no_particle_batch_completion_api)
            with fixture.inert_native_leaf(observed): result=launch('20261114_000102__test__python__collision-fields')
            fields=open_artifact({'manifest':result['manifest'],'product_id':'fields'},expected_kind='field_bundle')
            self.assertEqual(fields.metadata['field_representation'],'assembly_sampled_basis_with_collision_geometry')
            self.assertEqual(fields.metadata['source_status'],'not_requested');self.assertEqual(observed,list(ids))
            self.assertIn('collision_iob_spec',fields.data_records);self.assertIn('zero_particle_format_control',fields.data_records)
            from msplatform.backends.simion.ip_mr_tracking_admission import admit_ip_mr_tracking_fields
            from msplatform.backends.simion.rf_tracking_execution import plan_ip_mr_tracking_workbench
            from msplatform.backends.simion.model import model_geometry
            from msplatform.execution.resources import resource_path
            from msplatform.backends.simion.ip_mr_tracking_admission import _verified_solution_manifest
            from msplatform.backends.simion import ip_mr_tracking_admission as admission_module
            actual_open=Path.open
            def no_mph_open(path,*args,**kwargs):
                if path.suffix.lower()=='.mph': raise AssertionError('tracking must not read MPH')
                return actual_open(path,*args,**kwargs)
            actual_artifact=admission_module.open_artifact
            def no_solution_open(reference,*,expected_kind,**kwargs):
                if expected_kind=='field_solution': raise AssertionError('full solution open forbidden')
                return actual_artifact(reference,expected_kind=expected_kind,**kwargs)
            with patch.object(Path,'open',new=no_mph_open), patch.object(admission_module,'open_artifact',side_effect=no_solution_open):
                admission=admit_ip_mr_tracking_fields(fields.reference)
            levels=list(admission['basis']['bases'].values())
            sample=open_artifact(levels[0]['reference'],expected_kind='scalar_field_samples')
            ref=levels[0]['field_solution_reference']
            self.assertEqual(_verified_solution_manifest(sample,ref)['sha256'],ref['manifest']['sha256'])
            with self.assertRaises((KeyError,ValueError)):
                _verified_solution_manifest(sample,dict(ref,product_id='missing'))
            other=next(level['field_solution_reference'] for level in levels if level['field_solution_reference']['manifest']['sha256']!=ref['manifest']['sha256'])
            with self.assertRaisesRegex(ValueError,'solution reference differs'):
                _verified_solution_manifest(sample,other)
            # Distinct metadata is legal but gets a separate real verification.
            original_project = admission_module._ip_mr_bindings
            original_verify = admission_module.verify_record
            checked = []
            def with_duplicate(document, basis):
                projection, records = original_project(document, basis)
                return projection, [*records, dict(records[0])]
            def with_other_role(document, basis):
                projection, records = original_project(document, basis)
                return projection, [*records, dict(records[0], retention_role='other_role')]
            def with_conflict(document, basis):
                projection, records = original_project(document, basis)
                return projection, [*records, dict(records[0], sha256='0'*64)]
            def record_verify(name, record, **kwargs):
                checked.append((name, dict(record)))
                return original_verify(name, record, **kwargs)
            with patch.object(admission_module, '_ip_mr_bindings', side_effect=with_duplicate):
                duplicate = admit_ip_mr_tracking_fields(fields.reference)
            self.assertEqual(duplicate['immutable_input_records'], admission['immutable_input_records'])
            with patch.object(admission_module, '_ip_mr_bindings', side_effect=with_other_role), \
                 patch.object(admission_module, 'verify_record', side_effect=record_verify):
                admit_ip_mr_tracking_fields(fields.reference)
            self.assertTrue(any(name == 'IP–MR tracking immutable input' and row.get('retention_role') == 'other_role'
                                for name, row in checked))
            with patch.object(admission_module, '_ip_mr_bindings', side_effect=with_conflict):
                with self.assertRaisesRegex(ValueError, 'conflicting tracking input identities'):
                    admit_ip_mr_tracking_fields(fields.reference)
            self.assertEqual(len(admission['basis']['bases']),17)
            self.assertEqual(len(admission['priority']['instances']),5)
            from msplatform.backends.simion.ip_mr_tracking_admission import protect_ip_mr_tracking_fields
            protected={}
            def protect_action(session):
                first = Path(admission["immutable_input_records"][0]["path"])
                original = first.read_bytes()
                try:
                    first.write_bytes(original+b" ")
                    with self.assertRaises(AssertionError):
                        protect_ip_mr_tracking_fields(session,admission)
                finally:
                    first.write_bytes(original)
                protect_ip_mr_tracking_fields(session,admission)
                from msplatform.execution.capacity_protection import load_capacity_protection_leases, path_is_protected
                view=load_capacity_protection_leases(session.artifact_root)
                for item in admission['basis']['bases'].values():
                    for level in [item, *item.get('refinement_windows', [])]:
                        self.assertTrue(path_is_protected(Path(level['field_solution_reference']['manifest']['path']),view['protected_paths']))
                protected['checked']=len(admission['immutable_input_records'])
                return dict(status='success',summary={'protected':protected['checked']},output_paths=[],required_output_paths=[],retention_preserve_paths=[],manifest_extra_fields={})
            manifests={}
            for item in admission['source_manifests']:
                key=str(Path(item['path']).resolve())
                if key in manifests:
                    self.assertEqual((manifests[key]['bytes'],manifests[key]['sha256']), (item['bytes'],item['sha256']))
                manifests[key]=item
            run_managed_stage(selected['context'],descriptor=dict(project='instrument_assembly',mode='test',software=[]),
                run_id='20261114_000107__test__python__sampled-protection',payload={'action':'sampled_protection'},
                committed_new_bytes=16777216,commitment_inputs=[selected['budget']],retention=selected['retention'],
                expected_operation_ids=(),operation_dependencies={},action=protect_action,
                action_record=file_record(Path(__file__),'required_evidence'),
                source_references=[dict(manifest_record=row) for row in manifests.values()],completion_api=no_particle_batch_completion_api)
            self.assertGreater(protected['checked'],0)
            root=Path(tmp)/'tracking';root.mkdir()
            native=plan_ip_mr_tracking_workbench(model_geometry(admission['model']),admission=admission,
                run_directory=root,program='-- inert Program',program_metadata={'collision_priority_applied':True},native_source_rows=[dict(mass_amu='1',charge_state='1',position_x_mm='0',position_y_mm='0',position_z_mm='0',velocity_x_m_s='0',velocity_y_m_s='0',velocity_z_m_s='0')],
                native_path_resource=resource_path('native_run_path.lua'))
            spec=native.materializations[str(root/'inputs/tracking_iob.lua')]
            self.assertIn('ip_mr_sampled_tracking_iob',spec)
            self.assertIn('assembly_sampled_basis_with_collision_geometry',spec)
            self.assertGreater(len(native.input_copies),1)
            for copied in native.input_copies:
                self.assertTrue(Path(copied['source_record']['path']).is_file())
                self.assertTrue(Path(copied['destination']).is_relative_to(root/'inputs'))
            self.assertIn('native_fields',spec)
            self.assertNotIn('/runs/',spec.split('native_fields',1)[1])
            from msplatform.backends.simion.source import lua_value
            for copied in native.input_copies:
                if copied['source_record']['path'].endswith('.pa-surf'):
                    companion = Path(copied['destination'])
                    pa = companion.with_suffix('').with_suffix('.pa')
                    self.assertTrue(any(Path(row['destination']) == pa for row in native.input_copies))
                    self.assertIn('fractional_surface='+lua_value(str(companion)),spec)
            without_surfaces=copy.deepcopy(admission)
            removed_surfaces = {}
            for key in list(without_surfaces['source'].data_records):
                if key.endswith('_surface'):
                    path = without_surfaces['source'].data_path(key)
                    removed_surfaces[path] = path.read_bytes()
                    del without_surfaces['source']._records[key]
                    path.unlink()
            absent=plan_ip_mr_tracking_workbench(model_geometry(without_surfaces['model']),admission=without_surfaces,
                run_directory=root/'empty',program='-- inert Program',program_metadata={'collision_priority_applied':True},
                native_source_rows=[dict(mass_amu='1',charge_state='1',position_x_mm='0',position_y_mm='0',position_z_mm='0',velocity_x_m_s='0',velocity_y_m_s='0',velocity_z_m_s='0')],
                native_path_resource=resource_path('native_run_path.lua'))
            empty_spec=absent.materializations[str(root/'empty/inputs/tracking_iob.lua')]
            self.assertIn('fractional_surface='+lua_value(str(root/'empty/inputs/native_fields/multipole_collision.pa-surf')),empty_spec)
            self.assertNotIn('multipole_surface.pa-surf',empty_spec)
            for path, content in removed_surfaces.items():
                path.write_bytes(content)
            self.assertEqual(len(native.operations),2)
            basis_path=fields.data_path('sampled_basis');saved=basis_path.read_bytes()
            try:
                basis_path.write_bytes(saved+b' ')
                with self.assertRaises((ValueError,AssertionError)):
                    admit_ip_mr_tracking_fields(fields.reference)
            finally:
                basis_path.write_bytes(saved)
            exercise_published_ip_mr_tracking(self,fields,selected['context'],tmp)


class PurposeScopedSolutionManifestTests(unittest.TestCase):
    from tests.contracts.test_sfi_scalar_binding import SfiScalarAdmissionTests as _fixture
    setUp = _fixture.setUp
    publish = _fixture.publish
    make_geometry = _fixture.make_geometry
    make_sample = _fixture.make_sample

    def test_missing_tampered_failed_and_wrong_kind_refuse(self):
        import copy, json
        from msplatform.backends.simion.ip_mr_tracking_admission import _verified_solution_manifest
        from msplatform.io.manifest_records import file_record
        sample = open_artifact(self.sample_refs['carrier'], expected_kind='scalar_field_samples')
        record = dict(sample.data_records['field_solution_manifest'], path=str(sample.data_path('field_solution_manifest')))
        ref = {'manifest': record, 'product_id':'solution'}
        _verified_solution_manifest(sample,ref)
        # Identical bytes at a different manifest location are not the published source.
        relocated_dir=self.root/'relocated-solution-owner';relocated_dir.mkdir()
        relocated=relocated_dir/'run_manifest.json';relocated.write_bytes(Path(record['path']).read_bytes())
        relocated_ref={'manifest':file_record(relocated),'product_id':'solution'}
        with self.assertRaisesRegex(ValueError,'solution reference differs'):
            _verified_solution_manifest(sample,relocated_ref)
        from types import SimpleNamespace
        from msplatform.backends.simion.scalar_sample_binding import _small_product
        from msplatform.execution.terminal_publication import publish_terminal_state
        original_doc=json.loads(Path(record['path']).read_text(encoding='utf8'))
        original_doc['products']['alternate']=copy.deepcopy(original_doc['products']['solution'])
        alternate_dir=self.root/'alternate-solution-owner';alternate_dir.mkdir()
        publish_terminal_state(alternate_dir,{'status':'success'},original_doc)
        alternate_record=file_record(alternate_dir/'run_manifest.json')
        alternate_ref={'manifest':alternate_record,'product_id':'alternate'}
        _small_product(alternate_ref,'field_solution',())
        alternate_sample=SimpleNamespace(data_records={'field_solution_manifest':alternate_record},
            data_locations={'field_solution_manifest':alternate_dir/'run_manifest.json'})
        with self.assertRaisesRegex(ValueError,'solution product identity differs'):
            _verified_solution_manifest(alternate_sample,alternate_ref)
        with self.assertRaises((ValueError,AssertionError,KeyError)):
            _verified_solution_manifest(sample,self.geometry_ref)
        bad = copy.deepcopy(ref);bad['manifest']['path']=str(self.root/'missing.json')
        with self.assertRaises((FileNotFoundError,ValueError,AssertionError)):
            _verified_solution_manifest(sample,bad)
        path=Path(record['path']);original=path.read_bytes()
        try:
            path.write_bytes(original+b' ')
            with self.assertRaises((ValueError,AssertionError)):
                _verified_solution_manifest(sample,ref)
            doc=json.loads(original);doc['status']='failed';path.write_text(json.dumps(doc),encoding='utf8')
            bad=copy.deepcopy(ref);bad['manifest']=file_record(path)
            with self.assertRaises((ValueError,AssertionError)):
                _verified_solution_manifest(sample,bad)
        finally:
            path.write_bytes(original)
