"""Provider selection and frozen target identity regressions; no solver."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import copy

from common.contracts.write_run_manifest import file_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepare_accelerator_interface import (
    CONFIG, ION_PROCESSOR, freeze_file, load_selection, verified_reference,
    validate_execution_contract, finalize_interface,
)


class InterfacePreparationTests(unittest.TestCase):
    def test_finalize_freezes_selected_step_contract_and_rejects_other_changes(self):
        module = 'projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepare_accelerator_interface'
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
            for path in (reference/'simion',design/'results',fields,source,run/'inputs',run/'results'):
                path.mkdir(parents=True)
            (reference/'run_manifest.json').write_text('{}')
            (fields/'run_manifest.json').write_text('{}')
            (design/'run_manifest.json').write_text('{}')
            (reference/'simion/trajectory_contract.json').write_text(json.dumps(original))
            (reference/'simion/accelerator_provider_runtime_receipt.json').write_text('{}')
            from common.contracts.file_identity import file_sha256
            (design/'results/accelerator_interface_preparation.json').write_text(json.dumps(dict(
                selected_provider=ION_PROCESSOR, inputs=dict(reference_manifest=dict(
                    sha256=file_sha256(reference/'run_manifest.json'))))))
            execution = root/'execution.json'
            execution.write_text(json.dumps(selected, separators=(',', ':'))+'\n')
            with patch(module+'.verified_reference', side_effect=lambda run, relative: run/relative), \
                 patch(module+'._prepare_ip_handoff'), \
                 patch('projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff.compare_measured_exit_energy',return_value={}), \
                 patch('projects.parallel_mirror_dual_stripe_mr_tof.analysis.joint_flight_preparation.bind_joint_workbench',return_value={}) as bind:
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
