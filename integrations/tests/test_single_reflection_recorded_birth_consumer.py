"""SFI original-birth consumer wiring; native owner is not executed."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common.contracts import test_simion_tracking_execution as tracking_fixture
from integrations.tests.test_single_reflection_preparation import fixture, scientific_preparation_fixture, write_json
from msplatform.backends.simion.model import compile_prepared_model, project_resolved_drive, PHYSICS
from msplatform.backends.simion.compiler import compile_geometry
from msplatform.backends.simion.geometry import compile_frontend_geometry
from msplatform.execution.terminal_publication import publish_terminal_state
from msplatform.io.manifest_records import file_record
from msplatform.workflows.single_reflection_flight.prepare import prepare
from msplatform.workflows.single_reflection_flight import recorded_birth


class RecordedBirthConsumerTests(unittest.TestCase):
    def setUp(self):
        tracking_fixture.TrackingExecutionPlanTests.setUp(self)

    def test_scientific_request_two_domain_gems_and_field_depth_match_original_compiler(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, support = root/'target', root/'support'
            target.mkdir()
            support.mkdir()
            request_path, run, request = scientific_preparation_fixture(target, recorded_birth=True)
            _, _, old_request = fixture(support, entrance_refinement=True)
            request['numerics']['frontend_domains']['entrance_refinement'] = (
                old_request['numerics']['frontend_domains']['entrance_refinement'])
            write_json(request_path, request)
            prepared = prepare(request_path, run)
            components = {key:json.loads(Path(prepared['input_records']['instance_design__'+key]['path']).read_text())
                          for key in request['providers']['instances']}
            plan = json.loads((run/'inputs/composition_plan.json').read_text())
            old_gems, old_geometry = compile_frontend_geometry({'multipole':components['multipole']},
                components['oatof'], composition_plan=plan, numerical_domains=request['numerics']['frontend_domains'],
                accelerator_variant='three_zone_square',
                electrode_bindings={key:value['electrode_bindings'] for key,value in request['providers']['instances'].items()},
                provider_inputs={key:prepared['input_records']['instance_design__'+key] for key in components})
            geometry = json.loads((run/'inputs/frontend_geometry.json').read_text())
            self.assertEqual((run/'inputs/frontend.gem').read_text(encoding='utf-8'), old_gems['parent'])
            self.assertEqual((run/'inputs/frontend_entrance_refinement.gem').read_text(encoding='utf-8'),
                             old_gems['entrance_refinement'])
            self.assertEqual(geometry['numerical_domains'], old_geometry['numerical_domains'])
            self.assertEqual(geometry['backend_electrode_bindings']['bindings'], old_geometry['backend_electrode_bindings']['bindings'])
            design = json.loads((run/'inputs/frontend_field_design.json').read_text())
            self.assertEqual([domain['domain_id'] for domain in design['domains']], ['parent', 'entrance_refinement'])
            for domain in design['domains']:
                self.assertEqual(domain['refine_convergence_v'],
                                 request['numerics']['frontend_domains'][domain['domain_id']]['refine_convergence_v'])

    def test_saved_replay_request_is_refused_before_field_or_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            request_path, run, request = scientific_preparation_fixture(Path(directory), recorded_birth=True)
            request['verify_saved_workbench_replay'] = True
            request['flight'] = dict(pulse=self.case.drive['pulse'], maximum_flight_us=200.,
                maximum_step_us=.001, trajectory_quality=17, rf_steps_per_period=80)
            write_json(request_path, request)
            prepared = prepare(request_path, run)
            manifest = dict(schema_version=2, role='simulation_run_manifest', run_id='sfi-fixture',
                project='instrument_assembly', mode='single_reflection_flight', status='success',
                inputs={**prepared['input_records'], **prepared['outputs']}, outputs=[])
            publish_terminal_state(run, {'status': 'success'}, manifest)
            with patch.object(recorded_birth, 'open_artifact') as opened, \
                 patch('msplatform.execution.owner.run_managed_stage') as owner, \
                 self.assertRaisesRegex(ValueError, 'saved replay'):
                recorded_birth.track_recorded_birth(preparation_manifest=file_record(run/'run_manifest.json'),
                    fields={}, species_id='explicit-fixture', expected_particle_ids=list(range(1, 101)),
                    observations={'plane_observations': []}, context=None)
            opened.assert_not_called()
            owner.assert_not_called()

    def test_real_prepared_source_calls_public_track_and_binds_producer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path, run, request = scientific_preparation_fixture(root, recorded_birth=True)
            request['flight'] = dict(pulse=self.case.drive['pulse'], maximum_flight_us=200.,
                maximum_step_us=.001, trajectory_quality=17, rf_steps_per_period=80)
            write_json(request_path, request)
            prepared = prepare(request_path, run)
            records = {**prepared['input_records'], **prepared['outputs']}
            manifest = dict(schema_version=2, role='simulation_run_manifest', run_id='sfi-fixture',
                project='instrument_assembly', mode='single_reflection_flight', status='success',
                inputs=records, outputs=[])
            publish_terminal_state(run, {'status': 'success'}, manifest)
            producer = file_record(run/'run_manifest.json')
            ids = list(range(1, 101))
            source_epoch = prepared['input_records']['instrument_epoch']
            components = {key:json.loads(Path(prepared['input_records']['instance_design__'+key]['path']).read_text())
                          for key in request['providers']['instances']}
            plan = json.loads((run/'inputs/composition_plan.json').read_text())
            old_gems, old_geometry = compile_frontend_geometry({'multipole':components['multipole']},
                components['oatof'], composition_plan=plan,
                numerical_domains=request['numerics']['frontend_domains'], accelerator_variant='three_zone_square',
                electrode_bindings={key:value['electrode_bindings'] for key,value in request['providers']['instances'].items()},
                provider_inputs={key:prepared['input_records']['instance_design__'+key] for key in components})
            prepared_geometry = json.loads((run/'inputs/frontend_geometry.json').read_text())
            self.assertEqual((run/'inputs/frontend.gem').read_text(encoding='utf-8'), old_gems['parent'])
            for key in ('numerical_domains', 'native_frame_id', 'downstream_pa_instances'):
                self.assertEqual(prepared_geometry[key], old_geometry[key])
            self.assertEqual(prepared_geometry['backend_electrode_bindings']['bindings'],
                             old_geometry['backend_electrode_bindings']['bindings'])
            self.assertIn('raw_physical_samples', prepared_geometry)
            self.assertIn('downstream_build_contract', prepared_geometry)
            domains = {name:{key:value for key,value in domain.items() if key != 'refine_convergence_v'}
                       for name,domain in request['numerics']['frontend_domains'].items()}
            tof = components['oatof']
            compiled = compile_geometry({'composition_plan':plan, 'components_resolved':components},
                numerics=dict(frontend_domains=domains, geometry_build=tof['simion_geometry_build'],
                    detector_marker=tof['simion_detector_marker'],
                    electrode_group_native_ids={key:value['electrode_bindings']
                                                for key,value in request['providers']['instances'].items()}))
            drive = project_resolved_drive(compiled, components, pulse=request['flight']['pulse'],
                clock=dict(clock_epoch_id='instrument_clock_epoch_v1', authority_sha256=source_epoch['sha256'],
                           phase_reference_instrument_time_us=0.))
            model = compile_prepared_model(compiled, components, drive=drive, physics=PHYSICS)
            design = json.loads((run/'inputs/frontend_field_design.json').read_text())
            for transform in (str.upper, str.lower):
                changed = copy.deepcopy(design)
                for domain in changed['domains']:
                    domain['gem_sha256'] = transform(domain['gem_sha256'])
                recorded_birth._bound_tracking_model(model, {'multipole':components['multipole']},
                    components['oatof'], prepared_geometry, changed, request['flight'])
            wrong = copy.deepcopy(design)
            wrong['domains'][0]['gem_sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'GEM differs'):
                recorded_birth._bound_tracking_model(model, {'multipole':components['multipole']},
                    components['oatof'], prepared_geometry, wrong, request['flight'])
            field_run = root/'software-field-fixture'
            field_run.mkdir()
            model_path = field_run/'compiled_model.json'
            model_path.write_text(json.dumps(model.document), encoding='utf-8')
            data = {'compiled_model':file_record(model_path), 'instrument_epoch':source_epoch,
                    'clock_authority':prepared['input_records']['clock_authority']}
            metadata = dict(backend='simion', field_status='available', source_status='not_requested',
                model_identity_sha256=model.document['model_identity_sha256'], clock=model.document['drive']['clock'],
                fixture_only=True)
            field_manifest = dict(schema_version=2, role='simulation_run_manifest', run_id='inert-field',
                project='instrument_assembly', mode='software-fixture', status='success', inputs=data, outputs=[],
                products={'fields':dict(schema_version=1,kind='field_bundle',status='complete',metadata=metadata,data=data)})
            publish_terminal_state(field_run, {'status':'success'}, field_manifest)
            field_reference = {'manifest':file_record(field_run/'run_manifest.json'), 'product_id':'fields'}
            from types import SimpleNamespace
            context = SimpleNamespace(tools={'simion':Path(__file__)})
            stage = {'limits': {'transient_run_directory_bytes': 1}, 'artifact_retention': {}}
            with patch('msplatform.execution.stage_policy.read_stage_policy', return_value=(stage, {})), \
                 patch('msplatform.execution.owner.run_managed_stage', return_value={'manifest': {}}) as owner, \
                 patch('msplatform.results.artifacts.open_artifact', return_value='published'):
                result = recorded_birth.track_recorded_birth(preparation_manifest=producer, fields=field_reference,
                    species_id='explicit-fixture', expected_particle_ids=ids,
                    observations={'plane_observations': []}, context=context)
                self.assertEqual(result, 'published')
                call = owner.call_args.kwargs
                self.assertEqual(call['payload']['propagation']['scope'], 'continuous_assembly')
                self.assertEqual(len(call['payload']['particles']['mother']['records']), 100)
                self.assertIn({'manifest_record': producer}, call['source_references'])
                self.assertIn('source_provenance', call['payload']['birth_source_authority']['records'])
            for mismatch in ('pulse', 'clock'):
                altered_pulse = dict(request['flight']['pulse'])
                if mismatch == 'pulse':
                    altered_pulse['time_us'] += 1.
                altered_clock = dict(drive['clock'])
                if mismatch == 'clock':
                    altered_clock['authority_sha256'] = 'B' * 64
                altered_drive = project_resolved_drive(compiled, components, pulse=altered_pulse, clock=altered_clock)
                altered_model = compile_prepared_model(compiled, components, drive=altered_drive, physics=PHYSICS)
                bad_run = root/('software-field-'+mismatch)
                bad_run.mkdir()
                bad_model_path = bad_run/'compiled_model.json'
                bad_model_path.write_text(json.dumps(altered_model.document), encoding='utf-8')
                bad_data = dict(data, compiled_model=file_record(bad_model_path))
                bad_metadata = dict(metadata, model_identity_sha256=altered_model.document['model_identity_sha256'],
                                    clock=altered_model.document['drive']['clock'])
                bad_manifest = dict(schema_version=2, role='simulation_run_manifest', run_id='inert-'+mismatch,
                    project='instrument_assembly', mode='software-fixture', status='success', inputs=bad_data,
                    outputs=[], products={'fields':dict(schema_version=1,kind='field_bundle',status='complete',
                                                      metadata=bad_metadata,data=bad_data)})
                publish_terminal_state(bad_run, {'status':'success'}, bad_manifest)
                bad_ref = {'manifest':file_record(bad_run/'run_manifest.json'), 'product_id':'fields'}
                with self.subTest(mismatch=mismatch), patch('msplatform.execution.owner.run_managed_stage') as owner, \
                     self.assertRaises(ValueError):
                    recorded_birth.track_recorded_birth(preparation_manifest=producer, fields=bad_ref,
                        species_id='explicit-fixture', expected_particle_ids=ids,
                        observations={'plane_observations': []}, context=context)
                owner.assert_not_called()
            geometry_path = run/'inputs/frontend_geometry.json'
            manifest_path = run/'run_manifest.json'
            original_geometry, original_manifest = geometry_path.read_bytes(), manifest_path.read_bytes()
            try:
                geometry = json.loads(original_geometry)
                geometry['native_frame_id'] = 'different-frame'
                geometry_path.write_text(json.dumps(geometry), encoding='utf-8')
                changed_manifest = json.loads(original_manifest)
                changed_manifest['inputs']['frontend_geometry'] = file_record(geometry_path)
                manifest_path.write_text(json.dumps(changed_manifest), encoding='utf-8')
                with patch('msplatform.execution.owner.run_managed_stage') as owner, self.assertRaises(ValueError):
                    recorded_birth.track_recorded_birth(preparation_manifest=file_record(manifest_path), fields=field_reference,
                        species_id='explicit-fixture', expected_particle_ids=ids,
                        observations={'plane_observations': []}, context=context)
                owner.assert_not_called()
            finally:
                geometry_path.write_bytes(original_geometry)
                manifest_path.write_bytes(original_manifest)
            Path(prepared['input_records']['metadata']['path']).write_bytes(b'tamper')
            with patch('msplatform.execution.owner.run_managed_stage') as owner, self.assertRaises(AssertionError):
                recorded_birth.track_recorded_birth(preparation_manifest=producer, fields=field_reference,
                    species_id='explicit-fixture', expected_particle_ids=ids,
                    observations={'plane_observations': []}, context=context)
            owner.assert_not_called()
