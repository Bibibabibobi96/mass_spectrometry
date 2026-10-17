"""Provider selection and frozen target identity regressions; no solver."""
import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.write_run_manifest import file_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepare_accelerator_interface import (
    CONFIG, ION_PROCESSOR, freeze_file, load_selection, verified_reference,
)


class InterfacePreparationTests(unittest.TestCase):
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
