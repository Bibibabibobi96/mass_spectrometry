"""Public IP-MR recipe preflight using real compiled and owner-bound inert fixtures."""
from functools import partial
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from msplatform.backends.simion.ip_mr_field_execution import execute_ip_mr_sampled_fields
from msplatform.contracts.gas_species import NITROGEN
from msplatform.execution.completion import no_particle_batch_completion_api
from msplatform.execution.owner import run_managed_stage
from msplatform.io.manifest_records import file_record
from msplatform.recipes import load_recipe
from msplatform.workflows.native_tracing import preflight_native
from tests.contracts.test_support import ip_mr_sampled_field_fixture as fixture
from tests.components.ion_processor.test_functional import HS1_SOURCE_FIXTURE

ROOT=Path(__file__).resolve().parents[2]


class PublicIpMrRecipeTests(unittest.TestCase):
    def test_recipe_uses_the_selected_ip_gas_environment_authority(self):
        from msplatform.recipes.native import _resolved_hs1_gas, _snapshot
        from msplatform.contracts.gas_species import HS1_EXAMPLE_ASSUMPTION
        _,_,model=fixture._fixture_geometry()
        author=json.loads((ROOT/'tests/contracts/test_support/ip_mr_current_requests.json').read_bytes())
        study={'component_requests':author['component_requests'],'drive':copy.deepcopy(model.document['drive'])}
        study['drive']['ip_schedule'].pop('native_timing')
        box={'minimum_mm':[0,-10,-10],'maximum_mm':[211,10,10],
             'lower_closed':[True]*3,'upper_closed':[True]*3}
        request={'environment_instance_id':'ion_processor','bath_domain':box,'outer_domain':box}
        author=json.loads((ROOT/'src/msplatform/components/ion_processor/config/gas_environment.json').read_bytes())
        author['outer_state']=dict(pressure_pa=4.,temperature_k=300.,bulk_velocity_m_s=[1.,2.,3.])
        environment=json.dumps(author).encode()
        resources={'hs1_request.json':_snapshot(json.dumps(request).encode()),
                   'hs1_environment.json':_snapshot(environment)}
        gas=_resolved_hs1_gas(study,resources)
        self.assertEqual(gas['status'],'gas')
        self.assertEqual(gas['species_data'][0]['dataset_sha256'],NITROGEN['dataset_sha256'])
        self.assertEqual(gas['collision_models'][0]['data']['dataset_sha256'],HS1_EXAMPLE_ASSUMPTION['dataset_sha256'])
        request['environment_instance_id']='mrtof'
        resources['hs1_request.json']=_snapshot(json.dumps(request).encode())
        with self.assertRaisesRegex(ValueError,'selected IP instance'):
            _resolved_hs1_gas(study,resources)

    @patch.dict(os.environ, {'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':''})
    def test_published_field_and_hs1_reach_real_preflight_without_native(self):
        # Freeze the actual author drive, excluding the compiler-derived timing projection.
        from msplatform.backends.simion.model import compile_prepared_model
        _, compiled_check, model_check = fixture._fixture_geometry()
        author_drive = copy.deepcopy(model_check.document['drive'])
        author_drive['ip_schedule'].pop('native_timing')
        self.assertEqual(compile_prepared_model(compiled_check, compiled_check.components_resolved,
            drive=author_drive, physics=model_check.document['physics']).document, model_check.document)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                'MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH': str(Path(directory)/'host.sqlite3'),
                'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN':'', 'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID':'',
                'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE':''}), \
                fixture.build_sampled_field_fixture(Path(directory)) as selected:
            root=Path(directory);ids=selected['expected_operation_ids'];observed=[]
            limits=dict(wall_clock_seconds=120,transient_run_directory_bytes=16777216,process_tree_working_set_bytes=536870912,
                minimum_system_available_memory_bytes=1,compact_final_retained_bytes=16777216,automatic_retry_count=0)
            with fixture.inert_native_leaf(observed):
                result=run_managed_stage(selected['context'],descriptor=dict(project='instrument_assembly',mode='sim',software=[]),
                    run_id='20261114_000102__test__python__public-ip-mr-fields',
                    payload={'action':'solve_fields','model':selected['model_reference']},committed_new_bytes=16777216,
                    commitment_inputs=[selected['budget']],retention=selected['retention'],expected_operation_ids=ids,
                    operation_dependencies={name:[ids[i-1]] for i,name in enumerate(ids) if i},
                    action=partial(execute_ip_mr_sampled_fields,model_reference=selected['model_reference'],
                        scalar_field_basis=selected['scalar_field_basis'],priority_evidence=selected['priority_evidence'],limits=limits),
                    action_record=file_record(Path(execute_ip_mr_sampled_fields.__code__.co_filename)),
                    source_references=selected['prepared']['source_references'],completion_api=no_particle_batch_completion_api)
            self.assertEqual(observed,list(ids))
            assembly,compiled,model=fixture._fixture_geometry()
            template=json.loads((ROOT/'src/msplatform/examples/oa_split_tof_native_small_v1.json').read_bytes())
            rf=json.loads((ROOT/'src/msplatform/examples/rf_oatof_functional_v1.json').read_bytes())
            author=json.loads((ROOT/'tests/contracts/test_support/ip_mr_current_requests.json').read_bytes())
            components=copy.deepcopy(author['component_requests']);components['multipole']=rf['component_requests']['multipole']
            domains={'ip':fixture._domain([[-.1,190.6],[-3.6,3.6],[-3.6,3.6]],[.1]*3),
                'analyzer':fixture._domain([[-63,63],[-142.5,458.5],[-325.5,325.5]],[.5]*3),
                'detector':fixture._domain([[-26,25.5],[-87.5,-36.5],[94.5,97.5]],[.5]*3),
                'multipole':{'cell_mm_xyz':dict.fromkeys('xyz',.1)}}
            template.update(component_requests=components,recipe=assembly.composition_plan['recipe'],
                physics=model.document['physics'],release=rf['release'])
            template['drive']=copy.deepcopy(model.document['drive'])
            template['drive']['ip_schedule'].pop('native_timing')
            template['drive']['clock_authority']={'example_resource':'instrument_clock_authority_v1.json'}
            template['numerics']={'geometry':{'domains':domains},'fields':{'mode':'frozen_sampled_field'},
                'tracing':{'end_policy':{'maximum_particle_age_us':200.},
                    'simion':{'maximum_step_us':.001,'trajectory_quality':17,'rf_steps_per_period':80,'grouped':0}}}
            body=json.dumps(template).encode();(root/'study.json').write_bytes(body)
            def write_record(name,data):
                (root/name).write_bytes(data)
                return {'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest().upper()}
            author=json.loads((ROOT/'src/msplatform/components/ion_processor/config/gas_environment.json').read_bytes())
            author['outer_state']=dict(pressure_pa=4.,temperature_k=300.,bulk_velocity_m_s=[1.,2.,3.])
            env=json.dumps(author).encode()
            environment=write_record('gas.json',env);vendor=write_record('vendor.lua',HS1_SOURCE_FIXTURE.encode())
            box=lambda lo,hi:{'minimum_mm':lo,'maximum_mm':hi,'lower_closed':[True]*3,'upper_closed':[True]*3}
            hs1={'bath_domain':box([0,-10,-10],[211,10,10]),
                'outer_domain':box([-10000]*3,[10000]*3),
                'numerics':{'seed':40,'hs1_steps_per_mfp':20},'environment_instance_id':'ion_processor',
                'environment_record':environment,'vendor_record':vendor}
            hbytes=json.dumps(hs1).encode();(root/'hs1.json').write_bytes(hbytes)
            manifest=Path(result['manifest']['path']);reference=os.path.relpath(manifest,root).replace('\\','/')
            toml=f'''schema_version = 2
constants_version = "repository_particle_physics_v1"
label = "IP MR inert software fixture"
particle_tracer = "simion"
field_assembly_strategy = "sampled_joint_field"
particle_field_coupling = "external_given_field"
[study]
path = "study.json"
sha256 = "{hashlib.sha256(body).hexdigest()}"
[field_source]
kind = "simion_native"
[field_source.reference]
path = "{reference}"
sha256 = "{hashlib.sha256(manifest.read_bytes()).hexdigest()}"
product_id = "fields"
[recording]
mode = "observation_times"
observation_times_us = [1.0]
plane_observations = []
[gas_environment]
status = "hs1"
path = "hs1.json"
sha256 = "{hashlib.sha256(hbytes).hexdigest()}"
'''
            (root/'recipe.toml').write_text(toml,encoding='utf8')
            recipe=load_recipe(root/'recipe.toml').to_dict()
            result=preflight_native(recipe,context=selected['context'])
            self.assertTrue(result['implemented']);self.assertFalse(result['native_verified'])


if __name__=='__main__': unittest.main()
