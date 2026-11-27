"""SFI original-birth consumer wiring; native owner is not executed."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from msplatform import examples as example_api
from tests.workflows.single_reflection.test_single_reflection_preparation import fixture, scientific_preparation_fixture, write_json
from msplatform.backends.simion.model import compile_prepared_model, project_resolved_drive, PHYSICS
from msplatform.backends.simion.compiler import compile_geometry
from msplatform.backends.simion.geometry import compile_frontend_geometry
from msplatform.execution.terminal_publication import publish_terminal_state
from msplatform.workflows.single_reflection_flight.prepare import prepare
from msplatform.backends.simion.tracking_program import _bound_tracking_model


class RecordedBirthConsumerTests(unittest.TestCase):
    def setUp(self):
        self.case = example_api.load_example('rf_oatof_functional_v1')

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

    def test_historical_prepared_model_checks_frozen_geometry_identity(self):
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
                _bound_tracking_model(model, {'multipole':components['multipole']},
                    components['oatof'], prepared_geometry, changed, request['flight'])
            wrong = copy.deepcopy(design)
            wrong['domains'][0]['gem_sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'GEM differs'):
                _bound_tracking_model(model, {'multipole':components['multipole']},
                    components['oatof'], prepared_geometry, wrong, request['flight'])
