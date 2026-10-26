"""Provider selection and frozen target identity regressions; no solver."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import copy

from common.contracts.frozen_inputs import freeze_file
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import static_field_binding as field_binding_module
from common.contracts.write_run_manifest import file_record
from integrations.workflows.accelerator_interface.prepare import (
    CONFIG, ION_PROCESSOR, load_selection, verified_reference,
    validate_execution_contract, finalize_interface, prepare_interface,
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

    def test_finalize_native_strategy_requires_matching_actual_parent_and_all_windows(self):
        module = 'integrations.workflows.accelerator_interface.prepare'
        field_module = 'projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding'
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import resolve_native_refine_numerics
        from common.contracts.file_identity import file_sha256
        for strategy in (None, False, True):
            for bad_level in (None, 0, 1, 2, 3, 4):
                with self.subTest(strategy=strategy, bad_level=bad_level), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    reference, design, fields, source, run = [root/name for name in ('reference', 'design', 'fields', 'source', 'run')]
                    for path in (reference/'simion', design/'results', design/'inputs', fields, source, run/'inputs', run/'results'):
                        path.mkdir(parents=True)
                    original, selected = self._native_contract(), self._native_contract()
                    if strategy is None:
                        original['simion']['numerical_profiles']['native_static_field']['refine']['skipped_point'] = False
                    else:
                        selected['simion']['numerical_profiles']['native_static_field']['refine']['skipped_point'] = strategy
                    for owner in (reference, design, fields):
                        (owner/'run_manifest.json').write_text('{}', encoding='utf-8')
                    (design/'inputs/accelerator_request.json').write_text('{}', encoding='utf-8')
                    (design/'inputs/composition_plan.json').write_text('{}', encoding='utf-8')
                    (design/'inputs/accelerator_selection.json').write_text('{}')
                    (design/'inputs/accelerator_dependency.json').write_text('{}')
                    (reference/'simion/trajectory_contract.json').write_text(json.dumps(original), encoding='utf-8')
                    (reference/'simion/accelerator_provider_runtime_receipt.json').write_text('{}', encoding='utf-8')
                    (design/'results/accelerator_interface_preparation.json').write_text(json.dumps(dict(
                        selected_provider=ION_PROCESSOR, joint_preparation=dict(assembly=dict(composition_plan=dict(recipe={}))), inputs=dict(reference_manifest=dict(
                            sha256=file_sha256(reference/'run_manifest.json'))))), encoding='utf-8')
                    execution = root/'execution.json'
                    execution.write_text(json.dumps(selected), encoding='utf-8')
                    numerics = resolve_native_refine_numerics(selected)
                    binding = dict(mode='native_static_pa', native_solver_numerics=dict(numerics),
                                   refinement_windows=[dict(native_solver_numerics=dict(numerics)) for _ in range(4)])
                    if bad_level is not None:
                        level = [binding, *binding['refinement_windows']][bad_level]
                        level['native_solver_numerics']['refine_skipped_point'] = not strategy if strategy is not None else False
                    with patch(module+'.verified_reference', side_effect=lambda owner, relative, **kwargs: owner/relative), patch(module+'.verified_preparation_reference', side_effect=lambda owner, relative, **kwargs: owner/relative), \
                         patch(module+'._resolve_ip_matching') as handoff, \
                         patch(module+'._joint_binding_inputs', side_effect=lambda **kw: dict(binding=field_binding_module.load_binding(fields/'results/field_binding.json'))), \
                         patch('projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff.prepare_handoff'), \
                         patch(field_module+'.load_binding', return_value=binding) as load, \
                         patch('projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff.compare_measured_exit_energy', return_value={}), \
                         patch('integrations.workflows.accelerator_interface.prepare.bind_joint_workbench', return_value={}):
                        if bad_level is None:
                            receipt = finalize_interface(source_run=source, reference_mr_run=reference, design_run=design,
                                field_run=fields, run_directory=run, contract_path=execution)
                            self.assertEqual(receipt['execution_contract_provenance']['native_refine_change']['current'], numerics)
                        else:
                            with self.assertRaisesRegex(ValueError, 'native field Refine numerics'):
                                finalize_interface(source_run=source, reference_mr_run=reference, design_run=design,
                                    field_run=fields, run_directory=run, contract_path=execution)
                            handoff.assert_not_called()
                        load.assert_called_once_with(fields/'results/field_binding.json')

    def test_explicit_ip_request_and_relative_recipe_are_frozen_without_a_default(self):
        module = 'integrations.workflows.accelerator_interface.prepare'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference, run = root/'reference', root/'run'
            for path in (reference/'simion', run/'inputs', run/'results'):
                path.mkdir(parents=True)
            (reference/'run_manifest.json').write_text('{}')
            (reference/'simion/trajectory_contract.json').write_text(json.dumps(dict(
                accelerator=dict(focus_y_anchor=dict(project_y_mm=-55)),
                coordinate_system=dict(frame_id='test.frame'))))
            (reference/'simion/accelerator_provider_runtime_receipt.json').write_text(json.dumps(dict(
                mrtof_projection=dict(target_axial_energy_per_charge_v=4372))))
            (run/'results/mrtof_handoff').mkdir()
            (run/'results/mrtof_handoff/handoff_receipt.json').write_text('{}')
            explicit = root/'request.json'
            recipe = root/'recipe.json'
            recipe.write_text('{}')
            explicit.write_text(json.dumps(dict(composition_plan=dict(path='recipe.json'), policies=dict(energy_adjustment='preserve_measured_workpoint'))))
            with patch(module+'.verified_reference', side_effect=lambda owner, relative, **kwargs: owner/relative), patch(module+'.verified_preparation_reference', side_effect=lambda owner, relative, **kwargs: owner/relative), \
                 patch(module+'._resolve_ip_matching', return_value={}), \
                 patch('integrations.workflows.accelerator_interface.prepare.prepare_joint_flight', return_value={}):
                result = prepare_interface(source_run=root/'source', reference_mr_run=reference,
                    run_directory=run, provider=ION_PROCESSOR, lua_executable=root/'lua.exe',
                    matching_request_path=explicit)
            record = result['inputs']['accelerator_request']
            self.assertEqual(Path(record['path']).read_bytes(), explicit.read_bytes())
            self.assertEqual(record['source_path'], str(explicit.resolve()))
            self.assertEqual(Path(result['inputs']['composition_plan']['path']).read_bytes(), recipe.read_bytes())
            self.assertNotIn('request_contract', json.loads((CONFIG/'accelerator_interfaces.json').read_text())['providers'][ION_PROCESSOR])
            with self.assertRaisesRegex(ValueError, 'ion processor provider'):
                prepare_interface(source_run=None, reference_mr_run=reference, run_directory=root/'other',
                    provider='orthogonal_accelerator', matching_request_path=explicit)

    def test_ip_design_requires_an_explicit_request_before_any_input_is_frozen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, 'MatchingRequestPath'):
                prepare_interface(source_run=root/'source', reference_mr_run=root/'reference',
                    run_directory=root/'run', provider=ION_PROCESSOR, lua_executable=root/'lua')
            self.assertFalse((root/'run').exists())

    def test_measured_peak_reference_is_explicit_observation_change_not_physics(self):
        from common.analysis.peak_metrics import AnalysisSettings
        original = dict(simion=dict(default_trajectory_profile_id='same', trajectory_profiles=dict(
            same=dict(trajectory_quality=8, maximum_step_us=.002, purpose='unit'))),
            peak_analysis=dict(method_id='common_gaussian_kde_time_v1',
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

    def test_finalize_freezes_selected_step_contract_and_rejects_other_changes(self):
        module = 'integrations.workflows.accelerator_interface.prepare'
        original = dict(simion=dict(default_trajectory_profile_id='same', trajectory_profiles=dict(
            same=dict(trajectory_quality=3, maximum_step_us=.004, purpose='unit'))), source=dict(fixed=True),
            downstream_fixed_grid_workpoint_profile=dict(automatic_iteration=dict(
                maximum_iterations=5, advance_multiplier=1., damping_factor=.5)))
        selected = copy.deepcopy(original)
        selected['simion']['trajectory_profiles']['same']['maximum_step_us'] = .002
        selected['downstream_fixed_grid_workpoint_profile']['automatic_iteration']['maximum_iterations'] = 30
        for field in ('source', 'quality', 'selector', 'timeout'):
            changed = copy.deepcopy(selected)
            if field == 'source':
                changed['source']['fixed'] = False
            elif field == 'quality':
                changed['simion']['trajectory_profiles']['same']['trajectory_quality'] = 8
            elif field == 'selector':
                changed['simion']['default_trajectory_profile_id'] = 'other'
            else:
                changed['simion']['full_path_timeout_us'] = 20
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_execution_contract(original, changed, allow_controller_budget=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference, design, fields, source, run = [root/name for name in ('reference','design','fields','source','finalized')]
            for path in (reference/'simion',design/'results',design/'inputs',fields,source,run/'inputs',run/'results'):
                path.mkdir(parents=True)
            (design/'inputs/accelerator_request.json').write_text('{}')
            (design/'inputs/composition_plan.json').write_text('{}')
            (design/'inputs/accelerator_selection.json').write_text('{}')
            (design/'inputs/accelerator_dependency.json').write_text('{}')
            (reference/'run_manifest.json').write_text('{}')
            (fields/'run_manifest.json').write_text('{}')
            (design/'run_manifest.json').write_text('{}')
            (reference/'simion/trajectory_contract.json').write_text(json.dumps(original))
            (reference/'simion/accelerator_provider_runtime_receipt.json').write_text('{}')
            from common.contracts.file_identity import file_sha256
            (design/'results/accelerator_interface_preparation.json').write_text(json.dumps(dict(
                selected_provider=ION_PROCESSOR, joint_preparation=dict(assembly=dict(composition_plan=dict(recipe={}))), inputs=dict(reference_manifest=dict(
                    sha256=file_sha256(reference/'run_manifest.json'))))))
            execution = root/'execution.json'
            execution.write_text(json.dumps(selected, separators=(',', ':'))+'\n')
            with patch(module+'.verified_reference', side_effect=lambda run, relative, **kwargs: run/relative), patch(module+'.verified_preparation_reference', side_effect=lambda run, relative, **kwargs: run/relative), \
                 patch(module+'._joint_binding_inputs',return_value=dict(binding={})), \
                 patch(module+'._resolve_ip_matching'), \
                 patch('projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff.prepare_handoff'), \
                 patch('projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff.compare_measured_exit_energy',return_value={}), \
                 patch('integrations.workflows.accelerator_interface.prepare.bind_joint_workbench',return_value={}) as bind:
                receipt = finalize_interface(source_run=source,reference_mr_run=reference,design_run=design,
                                             field_run=fields,run_directory=run,contract_path=execution)
            self.assertEqual(Path(receipt['inputs']['reference_trajectory']['path']).read_bytes(),execution.read_bytes())
            self.assertEqual(receipt['execution_contract_provenance']['selected_profile']['maximum_step_us'],.002)
            self.assertEqual(receipt['execution_contract_provenance']['execution_budget_change']['maximum_iterations'],
                             dict(previous=5,current=30))
            self.assertEqual(bind.call_args.kwargs['execution_contract'],receipt['execution_contract_provenance'])
            self.assertEqual(Path(receipt['inputs']['historical_reference_trajectory']['path']).read_bytes(),
                             (reference/'simion/trajectory_contract.json').read_bytes())

    def test_interrupted_reference_requires_explicit_status_and_unchanged_file(self):
        with tempfile.TemporaryDirectory() as directory:
            run=Path(directory)
            config=run/'run_config.json'
            config.write_text('{}')
            log=run/'completed_batch.log'
            log.write_text('status,Fly completed. 10 splats\n')
            manifest=dict(project='parallel_mirror_dual_stripe_mr_tof',status='interrupted',
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
            manifest = dict(project='parallel_mirror_dual_stripe_mr_tof', status='success',
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
            manifest = dict(project='parallel_mirror_dual_stripe_mr_tof', status='success',
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
            manifest = dict(project='parallel_mirror_dual_stripe_mr_tof', status='success',
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
            manifest = dict(project='parallel_mirror_dual_stripe_mr_tof', status='success',
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
