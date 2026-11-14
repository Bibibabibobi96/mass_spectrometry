"""Real managed field owner; native child replaced with inert process only."""
import os
from pathlib import Path
import tempfile
import shutil
from contextlib import contextmanager
import unittest
from functools import partial
from unittest.mock import patch
from common.contracts.test_support import ip_mr_sampled_field_fixture as fixture
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
    from projects.dual_pressure_rectilinear_ion_processor.tests.test_functional import HS1_SOURCE_FIXTURE
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
    from common.contracts import test_ip_mr_tracking_program as program_fixture
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
       suffix.append('ion_number=%d;ion_instance=1;ion_time_of_flight=0;ion_splat=0;ion_mass=%.17g;ion_charge=%.17g'%(i,row['mass_amu'],row['charge_state']))
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
            admission=admit_ip_mr_tracking_fields(fields.reference)
            self.assertEqual(len(admission['basis']['bases']),17)
            self.assertEqual(len(admission['priority']['instances']),5)
            from msplatform.backends.simion.ip_mr_tracking_admission import protect_ip_mr_tracking_fields
            protected={}
            def protect_action(session):
                protect_ip_mr_tracking_fields(session,admission)
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
            self.assertEqual(len(native.input_copies),1)
            self.assertEqual(len(native.operations),2)
            basis_path=fields.data_path('sampled_basis');saved=basis_path.read_bytes()
            try:
                basis_path.write_bytes(saved+b' ')
                with self.assertRaises((ValueError,AssertionError)):
                    admit_ip_mr_tracking_fields(fields.reference)
            finally:
                basis_path.write_bytes(saved)
            exercise_published_ip_mr_tracking(self,fields,selected['context'],tmp)
