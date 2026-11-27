"""Pure COMSOL workflow compilation; no native qualification."""
import copy
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from msplatform import assembly, components
from msplatform.particle_release import sample_release
from msplatform.workflows.comsol_tracing import compile_comsol_inputs, run_comsol_stages


class ComsolWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[2] / 'src/msplatform/examples/oa_split_tof_native_small_v1.json'
        cls.study = json.loads(path.read_text(encoding='utf-8'))
        cls.instrument = assembly.assemble(cls.study['recipe'], {k: components.resolve_component(v) for k, v in cls.study['component_requests'].items()})
        cls.particles = sample_release(cls.study['release'])

    def recipe(self):
        study = copy.deepcopy(self.study)
        study['physics']['boundary_policy'] = 'comsol_finite_exterior_potential'
        study['numerics']['geometry'] = {'outer_box_mm': {'min': [-400, -400, -100], 'max': [400, 400, 920]}, 'geometry_validation': {'position_mm': 1e-6, 'normal_abs': 1e-6}}
        study['numerics']['fields'] = {'relative_permittivity': 1.0, 'exterior': {'kind': 'potential', 'voltage_v': 0.0}, 'mesh': {'global_automatic_level': 5, 'electrode_hmax_mm': 5.0}}
        study['numerics']['tracing'] = {'end_policy': {'maximum_particle_age_us': 100.0}, 'comsol': {'maximum_step_us': 0.01, 'relative_tolerance': 1e-4, 'absolute_tolerance': 1e-6}, 'birth_validation': {'position_atol_m': 1e-10, 'velocity_atol_m_s': 1e-5}}
        return {'field_source': {'kind': 'comsol_native'}, 'study': {'document': study}, 'recording': {'observation_times_us': [0.0, 80.0513730009902, 90.0, 100.0]}}

    def test_original_voltage_groups_and_source_frame(self):
        result = compile_comsol_inputs(self.recipe(), self.instrument, self.particles)
        off = {(r['instance_id'], r['electrode_group_id']): r['voltage_v'] for r in result['requests']['off']['group_voltages']}
        on = {(r['instance_id'], r['electrode_group_id']): r['voltage_v'] for r in result['requests']['on']['group_voltages']}
        self.assertEqual(off['oa', 'repeller'], 0.0)
        self.assertEqual(on['oa', 'repeller'], 2140.0)
        self.assertEqual(off['tof', 'reflectron_backplate'], on['tof', 'reflectron_backplate'])
        self.assertEqual(len(off), 43)
        self.assertEqual(len(result['source']['rows']), 3)
        self.assertEqual(result['source']['rows'][0]['frame_id'], 'oatof_global')
        self.assertEqual(result['source']['rows'][0]['position_x_mm'], self.particles.rows[0]['position_x_mm'])

    def test_workflow_claims_both_basis_products_without_second_solve(self):
        manifest = {'sha256': 'shared'}
        background = SimpleNamespace(reference={'manifest': manifest, 'product_id': 'background'})
        active = SimpleNamespace(reference={'manifest': manifest, 'product_id': 'on'})
        expected = SimpleNamespace(reference={'manifest': {'sha256': 'trajectory'}, 'product_id': 'trajectory'})
        geometry, model = object(), object()
        artifact_by_stage = {'geometry': geometry, 'model': model, 'basis': background, 'basis_on': active, 'trace': expected}
        called = []
        def cache(name, key, kind, produce):
            called.append(name)
            return artifact_by_stage[name], {'asset_id': name}
        compiled = compile_comsol_inputs(self.recipe(), self.instrument, self.particles)
        plan = {'background': {'projection': compiled['projection'], 'request': compiled['requests']['off']},
                'on': {'projection': compiled['projection'], 'request': compiled['requests']['on']}}
        with patch('msplatform.backends.comsol.assembly_particle_tracing.prepare_basis_model') as solve, \
             patch('msplatform.backends.comsol.assembly_particle_tracing.prepare_assembly_pulse', return_value=plan):
            trajectory, receipts = run_comsol_stages(self.recipe(), self.instrument, self.particles,
                context=object(), invoke=lambda f: f(), stage_cache=cache,
                implementation={'version': 'test'}, epoch_record={'sha256': 'epoch'})
        self.assertIs(trajectory, expected)
        self.assertEqual(called, ['geometry', 'model', 'basis', 'basis_on', 'trace'])
        self.assertEqual(receipts['basis_on']['asset_id'], 'basis_on')
        solve.assert_not_called()

    def test_explicit_basis_reference_skips_solve_and_rejects_wrong_science(self):
        manifest = {'sha256': 'shared'}
        reference = {'manifest': manifest, 'product_id': 'background'}
        background = SimpleNamespace(reference=reference)
        active = SimpleNamespace(reference={'manifest': manifest, 'product_id': 'on'})
        trajectory = object()
        by_stage = {'basis_reference': background, 'basis_on_reference': active, 'trace': trajectory}
        called = []
        def cache(name, key, kind, produce):
            called.append(name)
            return by_stage[name], {'asset_id': name}
        recipe = self.recipe(); recipe['field_source']['reference'] = {'reference': reference, 'snapshot': {}}
        compiled = compile_comsol_inputs(recipe, self.instrument, self.particles)
        plan = {'background': {'projection': compiled['projection'], 'request': compiled['requests']['off']},
                'on': {'projection': compiled['projection'], 'request': compiled['requests']['on']}}
        with patch('msplatform.backends.comsol.assembly_particle_tracing.prepare_assembly_pulse', return_value=plan), \
             patch('msplatform.backends.comsol.assembly_particle_tracing.prepare_basis_model') as solve:
            result, receipts = run_comsol_stages(recipe, self.instrument, self.particles, context=object(),
                invoke=lambda f: f(), stage_cache=cache, implementation={'version': 'a'}, epoch_record={'sha256': 'epoch'})
            self.assertIs(result, trajectory)
            self.assertEqual(called, ['basis_reference', 'basis_on_reference', 'trace'])
            self.assertEqual(receipts['basis']['execution_kind'], 'explicit_reference_validation')
            solve.assert_not_called()
            plan['on']['request'] = dict(plan['on']['request'], relative_permittivity=2)
            with self.assertRaisesRegex(ValueError, 'differ from the frozen study'):
                run_comsol_stages(recipe, self.instrument, self.particles, context=object(),
                    invoke=lambda f: f(), stage_cache=cache, implementation={'version': 'b'}, epoch_record={'sha256': 'epoch'})

    def test_rejects_inexact_native_particle_ids_before_any_stage(self):
        particles = self.particles.to_dict()
        particles['rows'][0]['particle_id'] = 2**53 + 1
        altered = SimpleNamespace(to_dict=lambda: particles)
        with self.assertRaisesRegex(ValueError, 'particle IDs'):
            compile_comsol_inputs(self.recipe(), self.instrument, altered)

    def test_rejects_unsupported_pulse_and_boundary(self):
        for mutation in ('boundary', 'pulse', 'horizon', 'bad_group', 'missing_tolerances'):
            recipe = self.recipe()
            study = recipe['study']['document']
            if mutation == 'boundary': study['physics']['boundary_policy'] = 'native_zero_neumann'
            elif mutation == 'pulse': study['drive']['pulse']['mode'] = 'held_off'
            elif mutation == 'horizon': recipe['recording']['observation_times_us'][-1] = 99.0
            elif mutation == 'bad_group': study['drive']['groups']['oa']['repeller']['off_voltage_v'] = 1.0
            else: del study['numerics']['tracing']['birth_validation']['position_atol_m']
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                compile_comsol_inputs(recipe, self.instrument, self.particles)
