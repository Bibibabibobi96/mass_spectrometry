"""Real managed field owner; native child replaced with inert process only."""
import os
import json
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
            runs=selected['context'].workspace/'artifacts/projects/instrument_assembly/runs'
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
                    with self.assertRaisesRegex(AssertionError,'byte count changed'):launch(between)
                completion=runs/between/'results/execution_completion.json';self.assertTrue(completion.is_file())
                writer=json.loads(completion.read_text(encoding='utf8'))['writer_completion']
                self.assertTrue(all(row['observation']['exit_confirmed'] for row in writer['operations']))
                self.assertTrue(all(row['completion_receipt']['host_release']['result']['status']=='released' for row in writer['resource_releases']))
                self.assertEqual(json.loads((runs/between/'run_manifest.json').read_text(encoding='utf8'))['status'],'failed');safe=True
            finally:
                if safe:sample_path.write_bytes(original)
            verify_record('restored synthetic sample',sample_record);self.assertEqual(len(observed),11)
            outside=Path(tmp)/'unprotected.bin';outside.write_bytes(b'INERT');outside_record=file_record(outside,'required_evidence')
            from msplatform.backends.simion import ip_mr_field_execution as subject
            original_prepare=subject.prepare_ip_mr_field_inputs
            def inject(*args,**kwargs):
                value=original_prepare(*args,**kwargs);value['immutable_input_records'].append(outside_record);return value
            observed.clear()
            with patch.object(subject,'prepare_ip_mr_field_inputs',side_effect=inject),fixture.inert_native_leaf(observed):
                with self.assertRaisesRegex(ValueError,'no active owner protection'):launch('20261114_000106__test__python__collision-unprotected')
            self.assertEqual(observed,[])
