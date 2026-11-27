"""Provider selection and frozen target identity regressions; no solver."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import copy

from msplatform.execution.inputs import freeze_file
from msplatform.execution.retention import file_record
from msplatform.workflows.accelerator_interface.prepare import (
    CONFIG, ION_PROCESSOR, load_selection, verified_reference,
    validate_execution_contract,
)


class InterfacePreparationTests(unittest.TestCase):
    @staticmethod
    def _native_contract():
        return dict(simion=dict(default_trajectory_profile_id='same', trajectory_profiles=dict(
            same=dict(trajectory_quality=8, maximum_step_us=.002, purpose='unit')),
            numerical_profiles=dict(native_static_field=dict(refine=dict(convergence_v=1e-5),
                                                               surface='fractional'))),
            source=dict(fixed=True), geometry=dict(grid_pitch_mm=[.01, .1, .1]),
            downstream_fixed_grid_workpoint_profile=dict(automatic_iteration=dict(
                maximum_iterations=5, advance_multiplier=1., damping_factor=.5)))

    def test_native_refine_strategy_changes_preserve_explicit_identities(self):
        for before in (None, False, True):
            for after in (None, False, True):
                with self.subTest(before=before, after=after):
                    original, selected = self._native_contract(), self._native_contract()
                    for contract, value in ((original, before), (selected, after)):
                        if value is not None:
                            contract['simion']['numerical_profiles']['native_static_field']['refine']['skipped_point'] = value
                    saved = copy.deepcopy((original, selected))
                    change = validate_execution_contract(original, selected)['native_refine_change']
                    self.assertEqual((original, selected), saved)
                    if before is after:
                        self.assertIsNone(change)
                    else:
                        for key, value in (('previous', before), ('current', after)):
                            expected = dict(refine_stopping='contract_convergence', convergence_v=1e-5)
                            if value is not None:
                                expected['refine_skipped_point'] = value
                            self.assertEqual(change[key], expected)
                    bounded = copy.deepcopy(selected)
                    bounded['downstream_fixed_grid_workpoint_profile']['automatic_iteration']['maximum_iterations'] = 30
                    result = validate_execution_contract(original, bounded, allow_controller_budget=True)
                    self.assertEqual(result['native_refine_change'], change)
                    self.assertEqual(result['execution_budget_change']['maximum_iterations'], dict(previous=5, current=30))

    def test_native_refine_strategy_rejects_invalid_types_and_unrelated_changes(self):
        for side in ('reference', 'selected'):
            for value in (0, 1, 'false', 'true', None, [], {}):
                contracts = dict(reference=self._native_contract(), selected=self._native_contract())
                contracts[side]['simion']['numerical_profiles']['native_static_field']['refine']['skipped_point'] = value
                with self.subTest(side=side, value=value), self.assertRaisesRegex(ValueError, 'Boolean'):
                    validate_execution_contract(contracts['reference'], contracts['selected'])
        for kind in ('convergence', 'extra_refine', 'surface', 'physics', 'grid', 'missing_reference', 'missing_selected'):
            original, selected = self._native_contract(), self._native_contract()
            native = selected['simion']['numerical_profiles']['native_static_field']
            native['refine']['skipped_point'] = False
            if kind == 'convergence':
                native['refine']['convergence_v'] = 2e-5
            elif kind == 'extra_refine':
                native['refine']['max_overrelaxation'] = 1
            elif kind == 'surface':
                native['surface'] = 'other'
            elif kind == 'physics':
                selected['source']['fixed'] = False
            elif kind == 'grid':
                selected['geometry']['grid_pitch_mm'][0] = .02
            else:
                target = original if kind == 'missing_reference' else selected
                del target['simion']['numerical_profiles']['native_static_field']
            for allow_budget in (False, True):
                bounded = copy.deepcopy(selected)
                if allow_budget:
                    bounded['downstream_fixed_grid_workpoint_profile']['automatic_iteration']['maximum_iterations'] = 30
                with self.subTest(kind=kind, allow_budget=allow_budget), self.assertRaises(ValueError):
                    validate_execution_contract(original, bounded, allow_controller_budget=allow_budget)




    def test_measured_peak_reference_is_explicit_observation_change_not_physics(self):
        from msplatform.analysis.peak_metrics import AnalysisSettings
        original = dict(simion=dict(default_trajectory_profile_id='same', trajectory_profiles=dict(
            same=dict(trajectory_quality=8, maximum_step_us=.002, purpose='unit'))),
            peak_analysis=dict(method_id='common_gaussian_kde_time_v2',
                resolution_definition='mean_tof_us/(2*direct_fwhm_tof_us)',
                time_basis='instrument_arrival_us_from_common_zero_birth', settings=vars(AnalysisSettings())))
        with tempfile.TemporaryDirectory() as directory:
            timing = Path(directory)/'timing.json'
            timing.write_text(json.dumps(dict(schema_version=1, role='native_electrode_timing', pulse_start_us=10.0)))
            selected = copy.deepcopy(original)
            peak = selected['peak_analysis']
            peak.update(time_basis='instrument_arrival_minus_common_extraction_pulse_us',
                        common_time_reference=dict(clock_epoch_id='frozen', field='pulse_start_us', timing=file_record(timing)))
            result = validate_execution_contract(original, selected)
            self.assertEqual(result['analysis_change']['current'], peak)
            self.assertIsNone(result['numerical_change'])
            self.assertIsNone(validate_execution_contract(selected, selected)['analysis_change'])
            legacy = copy.deepcopy(selected)
            legacy['peak_analysis']['method_id'] = 'common_gaussian_kde_time_v1'
            upgraded = validate_execution_contract(legacy, selected)
            self.assertEqual(upgraded['analysis_change']['change_kind'], 'measured_detector_peak_method_upgrade')
            self.assertEqual(upgraded['analysis_change']['previous']['method_id'], 'common_gaussian_kde_time_v1')
            legacy = copy.deepcopy(original)
            legacy['peak_analysis']['method_id'] = 'common_gaussian_kde_time_v1'
            upgraded = validate_execution_contract(legacy, selected)
            self.assertEqual(upgraded['analysis_change']['previous'], legacy['peak_analysis'])
            self.assertEqual(upgraded['analysis_change']['current'], selected['peak_analysis'])
            self.assertIsNone(upgraded['numerical_change'])
            invalid_legacy = copy.deepcopy(legacy)
            invalid_legacy['peak_analysis']['time_basis'] = 'unknown'
            with self.assertRaises(ValueError):
                validate_execution_contract(invalid_legacy, selected)
            invalid_legacy = copy.deepcopy(legacy)
            invalid_legacy['peak_analysis']['settings']['grid_points'] += 2
            with self.assertRaises(ValueError):
                validate_execution_contract(invalid_legacy, selected)
            for kind in ('method', 'settings', 'field', 'hash', 'physics'):
                changed = copy.deepcopy(selected)
                if kind == 'method':
                    changed['peak_analysis']['method_id'] = 'other'
                elif kind == 'settings':
                    changed['peak_analysis']['settings']['grid_points'] += 2
                elif kind == 'field':
                    changed['peak_analysis']['common_time_reference']['field'] = 'other'
                elif kind == 'hash':
                    changed['peak_analysis']['common_time_reference']['timing']['sha256'] = '0'*64
                else:
                    changed['source'] = dict(changed_physics=True)
                with self.subTest(kind=kind), self.assertRaises((ValueError, AssertionError)):
                    validate_execution_contract(original, changed)
            timing.write_text('{}')
            with self.assertRaises((ValueError, AssertionError)):
                validate_execution_contract(selected, selected)

    def test_joint_analysis_preflight_binds_source_and_clock_before_field(self):
        from types import SimpleNamespace
        from msplatform.analysis.peak_metrics import AnalysisSettings
        from msplatform.workflows.accelerator_interface.prepare import preflight_joint_analysis
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference, receipt_path, states, selected, timing = [root/name for name in
                ('reference.json', 'receipt.json', 'states.csv', 'selected.json', 'timing.json')]
            source = root/'source'
            timing.write_text(json.dumps(dict(schema_version=1, role='native_electrode_timing', pulse_start_us=10.0)))
            states.write_text('fixture')
            original = dict(simion=dict(default_trajectory_profile_id='same', trajectory_profiles=dict(
                same=dict(trajectory_quality=8, maximum_step_us=.002, purpose='unit'))),
                peak_analysis=dict(method_id='common_gaussian_kde_time_v1',
                    resolution_definition='mean_tof_us/(2*direct_fwhm_tof_us)',
                    time_basis='instrument_arrival_us_from_common_zero_birth', settings=vars(AnalysisSettings())))
            current = copy.deepcopy(original)
            current['peak_analysis'].update(method_id='common_gaussian_kde_time_v2',
                time_basis='instrument_arrival_minus_common_extraction_pulse_us',
                common_time_reference=dict(clock_epoch_id='epoch', field='pulse_start_us', timing=file_record(timing)))
            reference.write_text(json.dumps(original)); selected.write_text(json.dumps(current))
            receipt = dict(schema_version=2, role='ion_processor_component_exit_export', status='prepared',
                source_project='ion_processor', source_instance_id='ip',
                target_instance_id='mr', source_run=str(source), clock_epoch_id='epoch',
                outputs=dict(component_states=file_record(states)))
            receipt_path.write_text(json.dumps(receipt))
            paths = {'inputs/reference_trajectory.json': reference,
                'results/ion_processor_exit/component_exit_receipt.json': receipt_path,
                'results/ion_processor_exit/component_particle_state.csv': states}
            table = SimpleNamespace(report=dict(clock_epoch_ids=['epoch']),
                rows=[dict(particle_id=7, instrument_time_us=11.)])
            with patch('msplatform.workflows.accelerator_interface.prepare.verified_preparation_reference',
                       side_effect=lambda run, relative: paths[relative]), \
                 patch('msplatform.contracts.particle_state.load_component_particle_state_csv', return_value=table):
                preflight_joint_analysis(root, source, selected)
                with self.assertRaisesRegex(ValueError, 'selected IP run'):
                    preflight_joint_analysis(root, root/'different', selected)
                table.rows[0]['instrument_time_us'] = 9.
                with self.assertRaisesRegex(ValueError, 'pulse time'):
                    preflight_joint_analysis(root, source, selected)
                table.rows[0]['instrument_time_us'] = 11.
                current['peak_analysis']['common_time_reference']['clock_epoch_id'] = 'other'
                selected.write_text(json.dumps(current))
                with self.assertRaisesRegex(ValueError, 'clock authority'):
                    preflight_joint_analysis(root, source, selected)


    def test_interrupted_reference_requires_explicit_status_and_unchanged_file(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)
            config=run/'run_config.json'
            config.write_text('{}')
            log=run/'completed_batch.log'
            log.write_text('status,Fly completed. 10 splats\n')
            manifest=dict(project='multi_reflection_tof',status='interrupted',
                          run_config=file_record(config),inputs={},outputs=[file_record(log)])
            (run/'run_manifest.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                verified_reference(run,log.name)
            self.assertEqual(verified_reference(run,log.name,required_status='interrupted'),log)
            log.write_text('changed')
            with self.assertRaises(AssertionError):
                verified_reference(run,log.name,required_status='interrupted')

    def test_provider_selection_keeps_oa_default_and_allows_ion_processor(self):
        registry = CONFIG / 'accelerator_interfaces.json'
        self.assertEqual(load_selection(registry, None)[0], 'orthogonal_accelerator')
        self.assertEqual(load_selection(registry, ION_PROCESSOR)[0], ION_PROCESSOR)
        with self.assertRaises(ValueError):
            load_selection(registry, 'unknown')

    def test_reference_input_requires_bound_unchanged_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            contract = run / 'trajectory.json'
            contract.write_text('{}', encoding='utf-8')
            config = run / 'run_config.json'
            config.write_text(json.dumps({'inputs': {'trajectory_path': str(contract),
                                                     'optional_input': None}}), encoding='utf-8')
            manifest = dict(project='multi_reflection_tof', status='success',
                            run_config=file_record(config), inputs={'trajectory': file_record(contract)}, outputs=[])
            (run / 'run_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            self.assertEqual(verified_reference(run, 'trajectory.json'), contract)
            contract.write_text('{"changed":true}', encoding='utf-8')
            with self.assertRaises(AssertionError):
                verified_reference(run, 'trajectory.json')

    def test_freezing_refuses_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source', Path(directory) / 'target'
            source.write_bytes(b'original')
            frozen = freeze_file(source, target)
            self.assertEqual(target.read_bytes(), b'original')
            self.assertEqual(frozen['source_path'], str(source.resolve()))
            with self.assertRaises(FileExistsError):
                freeze_file(source, target)

    def test_reference_ignores_normalized_projection_and_verifies_manifest_record(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            binding = run / 'static_field_binding.json'
            binding.write_bytes(b'{"field":1}\n')
            config = run / 'run_config.json'
            config.write_text(json.dumps({'inputs': {'static_field_dependencies': {
                'path': str(binding), 'mode': 'native_static_pa', 'records': {}}}}), encoding='utf-8')
            manifest = dict(project='multi_reflection_tof', status='success',
                            run_config=file_record(config), inputs={'static_field_binding': file_record(binding)},
                            outputs=[])
            (run / 'run_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            self.assertEqual(verified_reference(run, binding.name), binding)
            binding.write_bytes(b'{"field":2}\n')
            with self.assertRaises(AssertionError):
                verified_reference(run, binding.name)

    def test_normalized_projection_alone_does_not_bind_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            binding = run / 'static_field_binding.json'
            binding.write_bytes(b'{}\n')
            config = run / 'run_config.json'
            config.write_text(json.dumps({'inputs': {'static_field_dependencies': {
                'path': str(binding), 'mode': 'native_static_pa'}}}), encoding='utf-8')
            manifest = dict(project='multi_reflection_tof', status='success',
                            run_config=file_record(config), inputs={}, outputs=[])
            (run / 'run_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'does not bind'):
                verified_reference(run, binding.name)

    def test_reference_accepts_config_bound_input_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            contract = run / 'reference_operating_point.lua'
            original = b'return {energy=4372}\n'
            contract.write_bytes(original)
            config = run / 'run_config.json'
            config_text = json.dumps({'inputs': {
                'joint_reference_operating_point': file_record(contract)}})
            config.write_text(config_text, encoding='utf-8')
            manifest = dict(project='multi_reflection_tof', status='success',
                            run_config=file_record(config), inputs={}, outputs=[])
            (run / 'run_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            self.assertEqual(verified_reference(run, contract.name), contract)
            unbound = run / 'unbound.lua'
            unbound.write_bytes(original)
            with self.assertRaisesRegex(ValueError, 'does not bind'):
                verified_reference(run, unbound.name)
            contract.write_bytes(b'return {}\n')
            with self.assertRaises(AssertionError):
                verified_reference(run, contract.name)
            contract.write_bytes(original)
            config.write_text(config_text + ' ', encoding='utf-8')
            with self.assertRaises(AssertionError):
                verified_reference(run, contract.name)


if __name__ == '__main__':
    unittest.main()
