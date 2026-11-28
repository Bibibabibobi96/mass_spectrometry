"""Real managed field owner; native child replaced with inert process only."""
import os
import copy
import json
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
from msplatform.execution.processes import ProcessExecutionError
from msplatform.io.manifest_records import file_record,verify_record
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

class SampledFieldExecutionTests(unittest.TestCase):
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
                return run_managed_stage(selected['context'],descriptor=dict(project='instrument_assembly',mode='sim',software=[]),run_id=run_id,payload={'action':'inert_sampled_fields'},committed_new_bytes=16777216,commitment_inputs=[selected['budget']],retention=selected['retention'],expected_operation_ids=ids,operation_dependencies={name:[ids[i-1]] for i,name in enumerate(ids) if i},action=partial(execute_ip_mr_sampled_fields,model_reference=selected['model_reference'],scalar_field_basis=selected['scalar_field_basis'],priority_evidence=selected['priority_evidence'],limits=limits),action_record=file_record(Path(__import__('msplatform.backends.simion.ip_mr_field_execution',fromlist=['']).__file__),'required_evidence'),source_references=prepared['source_references'],completion_api=no_particle_batch_completion_api)
            with fixture.inert_native_leaf(observed): result=launch('20261114_000102__test__python__collision-fields')
            fields=open_artifact({'manifest':result['manifest'],'product_id':'fields'},expected_kind='field_bundle')
            self.assertEqual(fields.metadata['field_representation'],'assembly_sampled_basis_with_collision_geometry')
            self.assertEqual(fields.metadata['source_status'],'not_requested');self.assertEqual(observed,list(ids))
            self.assertIn('collision_iob_spec',fields.data_records);self.assertIn('zero_particle_format_control',fields.data_records)
            observed.clear()
            with fixture.inert_native_leaf(observed,failure_operation='collision_verify_01'):
                with self.assertRaises(ProcessExecutionError):launch('20261114_000103__test__python__collision-failure')
            self.assertEqual(observed,['collision_build_01','collision_verify_01'])
            for record in prepared['immutable_input_records']:verify_record('preserved source',record)
            sample=open_artifact(selected['scalar_field_basis']['samples']['carrier'],expected_kind='scalar_field_samples')
            sample_path=sample.data_path('field_v');sample_record=sample.data_records['field_v'];original=sample_path.read_bytes()
            runs=selected['context'].workspace/'artifacts/assemblies/instrument_assembly/runs'
            observed.clear();locked='20261114_000104__test__python__collision-lock'
            with fixture.inert_native_leaf(observed,child_mutate=sample_path):
                with self.assertRaises(ProcessExecutionError):launch(locked)
            self.assertEqual(observed,['collision_build_01']);self.assertEqual(sample_path.read_bytes(),original)
            self.assertIn('PermissionError',(runs/locked/'logs/operation_0001.stderr.log').read_text(encoding='utf8'))
            failed=json.loads((runs/locked/'run_manifest.json').read_text(encoding='utf8'));self.assertEqual(failed['status'],'failed');self.assertFalse(failed.get('products'))
            observed.clear();between='20261114_000105__test__python__collision-between';safe=False
            def mutate(operation):
                if operation=='collision_build_01':sample_path.write_bytes(original+b'X')
            try:
                with fixture.inert_native_leaf(observed,after_operation=mutate):
                    with self.assertRaises(PermissionError):launch(between)
                completion=runs/between/'results/execution_completion.json';self.assertTrue(completion.is_file())
                writer=json.loads(completion.read_text(encoding='utf8'))['writer_completion']
                self.assertTrue(all(row['observation']['exit_confirmed'] for row in writer['operations']))
                self.assertTrue(all(row['completion_receipt']['host_release']['result']['status']=='released' for row in writer['resource_releases']))
                self.assertEqual(json.loads((runs/between/'run_manifest.json').read_text(encoding='utf8'))['status'],'failed');safe=True
            finally:
                if safe:sample_path.write_bytes(original)
            verify_record('restored synthetic sample',sample_record);self.assertEqual(len(observed),1)
            sample_path.write_bytes(original+b'X')
            with self.assertRaisesRegex(AssertionError,'byte count changed'):
                verify_record('publication identity after guard release',sample_record)
            sample_path.write_bytes(original)
            outside=Path(tmp)/'unprotected.bin';outside.write_bytes(b'INERT');outside_record=file_record(outside,'required_evidence')
            from msplatform.backends.simion import ip_mr_field_execution as subject
            original_prepare=subject.prepare_ip_mr_field_inputs
            def inject(*args,**kwargs):
                value=original_prepare(*args,**kwargs);value['immutable_input_records'].append(outside_record);return value
            observed.clear()
            with patch.object(subject,'prepare_ip_mr_field_inputs',side_effect=inject),fixture.inert_native_leaf(observed):
                with self.assertRaisesRegex(ValueError,'no active owner protection'):launch('20261114_000106__test__python__collision-unprotected')
            self.assertEqual(observed,[])

            # Reuse the same already-published 17 samples for the derived carrier.
            from msplatform.backends.comsol.assembly_field_export import derive_world_scalar_support
            from msplatform.backends.simion.ip_mr_field_execution import prepare_ip_mr_field_inputs
            from msplatform.backends.simion.ip_mr_tracking_admission import admit_ip_mr_tracking_fields, protect_ip_mr_tracking_fields
            from msplatform.execution.capacity_protection import load_capacity_protection_leases, path_is_protected
            context=selected['context'];policy=context.stage_policy_path
            from msplatform.storage import ArtifactStore
            store = ArtifactStore(Path(tmp)/'store')
            stage=json.loads(policy.read_text(encoding='utf8'));stage['stages']['export_assembly_world_scalar']={
                'limits':dict(stage['stages']['track']['limits']),'artifact_retention':dict(selected['retention'])}
            policy.write_text(json.dumps(stage),encoding='utf8')
            selection=copy.deepcopy(selected['scalar_field_basis']);raw_ref=selection['samples']['carrier']
            raw=open_artifact(raw_ref,expected_kind='scalar_field_samples')
            preserved={name:raw.data_path(name).read_bytes() for name in ('field_v','field_valid','report')}
            derived=derive_world_scalar_support(raw_ref,context=context,publish_prepared_support=True,artifact_store=store)
            self.assertEqual(derived.metadata['original_samples_reference'],raw.reference)
            selection['samples']['carrier']=derived.reference
            derived_plan=prepare_ip_mr_field_inputs(selected['model_reference'],scalar_field_basis=selection,
                priority_evidence=selected['priority_evidence'],output_directory=Path(tmp)/'derived-preflight')
            original_path=raw.manifest_location.resolve()
            self.assertTrue(any(Path(x['manifest_record']['path']).resolve()==original_path for x in derived_plan['source_references']))
            derived_ids=derived_plan['expected_operation_ids'];derived_observed=[];lease_checks=[]
            def check_derived_field(_operation):
                view=load_capacity_protection_leases(context.workspace/'artifacts')
                self.assertTrue(path_is_protected(original_path,view['protected_paths']));lease_checks.append('field')
            from msplatform.backends.simion import operations
            solve_policy=copy.deepcopy(stage['stages']['track'])
            solve_policy['limits']['transient_run_directory_bytes']=5*1024**3
            solve_policy['limits']['reserved_run_payload_bytes']=5*1024**3
            stage['stages']['solve_fields']=solve_policy
            policy.write_text(json.dumps(stage),encoding='utf8')
            with fixture.inert_native_leaf(derived_observed,after_operation=check_derived_field):
                derived_fields=operations.solve_fields(selected['model_reference'],numerics={},context=context,
                    scalar_field_basis=dict(selection,collision_priority_evidence=selected['priority_evidence']),artifact_store=store)
            self.assertEqual(derived_observed,list(derived_ids))
            from msplatform.backends.simion.ip_mr_field_execution import prepare_reused_ip_mr_collisions
            reuse_plan=prepare_reused_ip_mr_collisions(selected['model_reference'],scalar_field_basis=selection,
                priority_evidence=selected['priority_evidence'],reuse_reference=derived_fields.reference,
                output_directory=Path(tmp)/'reuse-preflight')
            relative_reference={'manifest':dict(derived_fields.reference['manifest'],path='run_manifest.json'),'product_id':'fields'}
            def resolve_relative(record,base):
                return derived_fields.manifest_location if record['path']=='run_manifest.json' else Path(record['path'])
            relative_opened=open_artifact(relative_reference,expected_kind='field_bundle',resolver=resolve_relative)
            relative_plan=prepare_reused_ip_mr_collisions(selected['model_reference'],scalar_field_basis=selection,
                priority_evidence=selected['priority_evidence'],reuse_reference=relative_opened,
                output_directory=Path(tmp)/'relative-reuse-preflight')
            self.assertEqual(relative_plan['collision_producer_reference'],derived_fields.reference)
            for key in ('compiled_model','clock_authority','instrument_epoch'):
                changed_plan=copy.deepcopy(reuse_plan)
                changed_plan['prepared_records'][key]['sha256']='0'*64
                with self.subTest(changed_prepared_record=key), patch.object(subject,'prepare_ip_mr_field_inputs',return_value=changed_plan):
                    with self.assertRaisesRegex(ValueError,'prepared record differs'):
                        prepare_reused_ip_mr_collisions(selected['model_reference'],scalar_field_basis=selection,
                            priority_evidence=selected['priority_evidence'],reuse_reference=derived_fields.reference,
                            output_directory=Path(tmp)/'changed-prepared-preflight')
            missing_reference=copy.deepcopy(derived_fields.reference)
            missing_reference['manifest']['path']=str(Path(tmp)/'missing-producer.json')
            with self.assertRaises((AssertionError,FileNotFoundError,ValueError)):
                prepare_reused_ip_mr_collisions(selected['model_reference'],scalar_field_basis=selection,
                    priority_evidence=selected['priority_evidence'],reuse_reference=missing_reference,
                    output_directory=Path(tmp)/'missing-reuse-preflight')
            bad_reference=copy.deepcopy(derived_fields.reference)
            bad_reference['manifest']['sha256']='0'*64
            with self.assertRaisesRegex(AssertionError, 'SHA-256 changed'):
                prepare_reused_ip_mr_collisions(selected['model_reference'],scalar_field_basis=selection,
                    priority_evidence=selected['priority_evidence'],reuse_reference=bad_reference,
                    output_directory=Path(tmp)/'bad-reuse-preflight')
            bad_evidence=copy.deepcopy(selected['priority_evidence'])
            bad_evidence['boxes_record']['sha256']='0'*64
            with self.assertRaisesRegex(AssertionError, 'SHA-256 changed'):
                prepare_reused_ip_mr_collisions(selected['model_reference'],scalar_field_basis=selection,
                    priority_evidence=bad_evidence,reuse_reference=derived_fields.reference,
                    output_directory=Path(tmp)/'bad-priority-preflight')
            from msplatform.backends.simion import model_execution, operations
            from msplatform.execution.capacity_ledger import load_capacity_ledger
            solve_stage=copy.deepcopy(stage['stages']['track'])
            solve_stage['limits']['reserved_run_payload_bytes']=solve_stage['limits']['transient_run_directory_bytes']
            stage['stages']['solve_fields']=solve_stage
            policy.write_text(json.dumps(stage),encoding='utf8')
            reuse_operations=[];collision_lease=[]
            original_protected_source=model_execution._protected_source
            def observe_protected_source(session,manifest,**kwargs):
                result=original_protected_source(session,manifest,**kwargs)
                if Path(manifest['path']).resolve()==derived_fields.manifest_location.resolve():
                    view=load_capacity_protection_leases(context.workspace/'artifacts')
                    self.assertTrue(path_is_protected(derived_fields.manifest_location.resolve(),view['protected_paths']))
                    collision_lease.append(True)
                return result
            public_selection=dict(selection,collision_priority_evidence=selected['priority_evidence'])
            with fixture.inert_native_leaf(reuse_operations), patch.object(model_execution,'_protected_source',side_effect=observe_protected_source):
                reused=operations.solve_fields(selected['model_reference'],numerics={},context=context,
                    scalar_field_basis=public_selection,reuse_collision_geometry=derived_fields.reference,artifact_store=store)
            self.assertEqual(reuse_operations,[]);self.assertTrue(collision_lease)
            reuse_run=reused.manifest_location.parent
            completion=json.loads((reuse_run/'results/execution_completion.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(completion['writer_completion']['operations'],[])
            self.assertEqual(completion['writer_completion']['resource_releases'],[])
            ledger=load_capacity_ledger(context.workspace/'artifacts')
            relative_run=reuse_run.relative_to(context.workspace/'artifacts').as_posix()
            rows=[row for row in ledger['objects'] if row['path']==relative_run]
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['status'],'ready')
            logical=sum(path.stat().st_size for path in reuse_run.rglob('*') if path.is_file())
            self.assertGreater(logical,0);self.assertGreater(rows[0]['bytes'],0)
            print('COLLISION_REUSE_PUBLIC_ACCOUNTING='+json.dumps({'logical_file_bytes':logical,
                'ledger_bytes':rows[0]['bytes'],'native_operations':len(reuse_operations)},sort_keys=True),flush=True)
            self.assertEqual(reused.metadata['collision_producer_reference'],derived_fields.reference)
            for key in set(derived_fields.data_records)-{'sampled_basis','compiled_model','clock_authority','instrument_epoch'}:
                self.assertEqual(reused.data_records[key],derived_fields.data_records[key])
            self.assertNotEqual(reused.data_path('sampled_basis'),derived_fields.data_path('sampled_basis'))
            from msplatform.io import manifest_records
            from msplatform.backends.simion import ip_mr_tracking_admission as tracking_admission
            collision_key=next(key for key in derived_fields.data_records if key.endswith('_collision'))
            collision_path=derived_fields.data_locations[collision_key].resolve()
            real_file_record=manifest_records.file_record
            collision_reads=[]
            def count_records(path,*args,**kwargs):
                if Path(path).resolve()==collision_path:collision_reads.append(str(path))
                return real_file_record(path,*args,**kwargs)
            with patch.object(manifest_records,'file_record',side_effect=count_records), \
                 patch.object(tracking_admission,'_verify_original_collision_producer',
                              wraps=tracking_admission._verify_original_collision_producer) as verify_producer:
                admission=admit_ip_mr_tracking_fields(reused.reference)
            self.assertEqual(verify_producer.call_count,1)
            self.assertEqual(len(collision_reads),2)
            original_small=tracking_admission._small_product
            def mutated_reader(reference,kind,names):
                owner,product,path=original_small(reference,kind,names)
                if kind!='field_bundle' or reference!=derived_fields.reference:return owner,product,path
                owner,product=copy.deepcopy(owner),copy.deepcopy(product)
                if mutation=='status':owner['status']='failed'
                elif mutation=='model':product['metadata']['model_identity_sha256']='0'*64
                elif mutation=='clock':product['metadata']['clock']={}
                elif mutation=='flattened':product['metadata']['collision_producer_reference']=derived_fields.reference
                else:
                    record=product['data'][collision_key]; prior=copy.deepcopy(record)
                    if mutation=='path':record['path']=str(collision_path.parent/'different.pa')
                    elif mutation=='relative_wrong':record['path']=os.path.relpath(collision_path.parent/'different.pa',path.parent)
                    elif mutation=='equivalent':
                        record['path']=os.path.relpath(collision_path,path.parent)
                        record['sha256']=record['sha256'].lower()
                    elif mutation=='bytes':record['bytes']+=1
                    elif mutation=='hash':record['sha256']='0'*64
                    elif mutation=='role':record['retention_role']='required_evidence'
                    if mutation=='unbound':
                        owner['outputs']=[row for row in owner['outputs'] if row!=prior]
                        owner['inputs']={k:row for k,row in owner['inputs'].items() if row!=prior}
                    else:
                        owner['outputs']=[record if row==prior else row for row in owner['outputs']]
                        owner['inputs']={k:(record if row==prior else row) for k,row in owner['inputs'].items()}
                return owner,product,path
            for mutation in ('status','model','clock','flattened','path','relative_wrong','bytes','hash','role','unbound'):
                with self.subTest(collision_producer_mutation=mutation), patch.object(tracking_admission,'_small_product',side_effect=mutated_reader):
                    with self.assertRaises((ValueError,AssertionError)):
                        tracking_admission._verify_original_collision_producer(reused,derived_fields.reference)
            mutation='equivalent'
            with patch.object(tracking_admission,'_small_product',side_effect=mutated_reader):
                self.assertIsNone(tracking_admission._verify_original_collision_producer(reused,derived_fields.reference))
            self.assertEqual(admission['collision_reference'],derived_fields.reference)
            self.assertIn(str(derived_fields.manifest_location.resolve()),[str(Path(x['path']).resolve()) for x in admission['source_manifests']])

            self.assertEqual(len(admission['basis']['bases']),17)
            self.assertTrue(any(Path(x['path']).resolve()==original_path for x in admission['source_manifests']))
            def check_tracking(session):
                view=load_capacity_protection_leases(context.workspace/'artifacts')
                self.assertTrue(path_is_protected(original_path,view['protected_paths']))
                protect_ip_mr_tracking_fields(session,admission);lease_checks.append('track')
                return dict(status='success',summary={},output_paths=[],required_output_paths=[],retention_preserve_paths=[],manifest_extra_fields={})
            unique={str(Path(x['path']).resolve()):x for x in admission['source_manifests']}
            run_managed_stage(context,descriptor=dict(project='instrument_assembly',mode='test',software=[]),
                run_id='20261114_000109__test__python__derived-track-protection',payload={'action':'sampled_protection'},
                committed_new_bytes=16777216,commitment_inputs=[selected['budget']],retention=selected['retention'],
                expected_operation_ids=(),operation_dependencies={},action=check_tracking,
                action_record=file_record(Path(__file__),'required_evidence'),
                source_references=[dict(manifest_record=x) for x in unique.values()],completion_api=no_particle_batch_completion_api)
            self.assertEqual(lease_checks.count('field'),len(derived_ids));self.assertEqual(lease_checks.count('track'),1)
            self.assertEqual(preserved,{name:raw.data_path(name).read_bytes() for name in preserved})
            self.assertEqual(load_capacity_protection_leases(context.workspace/'artifacts')['audit'],[])
