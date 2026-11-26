"""Native owner control receipts describe workers, not Compute/Fly counts."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from msplatform.workflows.native_evidence import summarize_native_workers


def control(nonce, *, grouped=False):
    common = {'nonce': nonce, 'binding_id': 'binding'}
    reg = {'process_id': 123, 'started_at_utc_ticks': 456, 'registration': 'registered'}
    obs = {'root_process_id': 123, 'root_process_started_at_utc_ticks': 456, 'exit_code': 0}
    native = {'host_release': {'inherited': False, 'token': 'token', 'error': None,
                               'result': {'status': 'released', 'token': 'token'}}, 'error': None}
    worker = {**common, **reg}
    if grouped:
        worker = {**common, 'workers': [{**reg, 'operation_id': 'first'},
                   {'operation_id': 'second', 'process_id': 124, 'started_at_utc_ticks': 457, 'registration': 'quick_exit'}]}
        native.update(observations={'first': obs, 'second': {'root_process_id': 124,
            'root_process_started_at_utc_ticks': 457, 'exit_code': 2}}, not_started=['third'])
    else:
        native['observation'] = obs
    return {'receipt': {**common, 'receipt': native}, 'worker': worker,
            'host': {'nonce': nonce, 'token': 'token', 'inherited': False}, 'ack': common}


class NativeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def write(self, data, nonce='a'*32):
        for kind, value in data.items():
            (self.root/f'native-control-{nonce}.{kind}.json').write_text(json.dumps(value), encoding='utf-8')

    def test_single_and_group_actual_worker_observations(self):
        self.write(control('a'*32))
        result = summarize_native_workers(self.root)
        self.assertEqual((result['status'], result['observed_completed_worker_count']), ('available', 1))
        self.assertEqual(result['workers'][0]['returncode'], 0)
        self.assertEqual(set(result['controls'][0]['records']), {'receipt', 'host', 'worker', 'ack'})
        self.write(control('b'*32, grouped=True), 'b'*32)
        # The duplicate actual process identity across controls is not double-counted.
        result = summarize_native_workers(self.root)
        self.assertEqual((result['status'], result['observed_completed_worker_count']), ('unavailable', None))
        for path in self.root.glob('native-control-' + 'a'*32 + '.*.json'):
            path.unlink()
        result = summarize_native_workers(self.root)
        self.assertEqual((result['status'], result['observed_completed_worker_count']), ('available', 2))
        self.assertEqual([row['returncode'] for row in result['workers']], [0, 2])

    def test_missing_inconsistent_and_no_receipts_are_unavailable(self):
        self.assertEqual(summarize_native_workers(self.root)['reason'], 'no_native_control_evidence')
        base = control('a'*32)
        cases = [lambda d: d.pop('worker'), lambda d: d['ack'].__setitem__('binding_id', 'wrong'),
                 lambda d: d['receipt']['receipt']['observation'].__setitem__('root_process_started_at_utc_ticks', 999),
                 lambda d: d['receipt']['receipt']['host_release'].__setitem__('error', 'failed')]
        for mutate in cases:
            for path in self.root.glob('*'): path.unlink()
            data = copy.deepcopy(base); mutate(data); self.write(data)
            with self.subTest(mutate=mutate):
                result = summarize_native_workers(self.root)
                self.assertEqual(result['status'], 'unavailable')
                self.assertIsNone(result['observed_completed_worker_count'])
                self.assertTrue(result['reason'])

    def test_group_missing_completion_and_invalid_nonce_fail_closed(self):
        data = control('a'*32, grouped=True)
        del data['receipt']['receipt']['observations']['second']
        self.write(data)
        self.assertIsNone(summarize_native_workers(self.root)['observed_completed_worker_count'])
        for path in self.root.glob('*'): path.unlink()
        self.write(control('b'*32), 'a'*32)
        self.assertEqual(summarize_native_workers(self.root)['status'], 'unavailable')

    def test_existing_microsecond_creation_identity_rule(self):
        data = control('a'*32)
        data['worker']['started_at_utc_ticks'] = 450
        self.write(data)
        self.assertEqual(summarize_native_workers(self.root)['status'], 'available')

    def test_group_pressure_relaunch_preserves_both_actual_exit_codes(self):
        data = control('a'*32, grouped=True)
        worker = data['worker']
        worker['workers'] = [dict(worker['workers'][0], attempt=1),
                             dict(worker['workers'][0], attempt=2, process_id=125, started_at_utc_ticks=458)]
        victim = {'root_process_id': 123, 'root_process_started_at_utc_ticks': 456, 'exit_code': -9}
        last = {'root_process_id': 125, 'root_process_started_at_utc_ticks': 458, 'exit_code': 0}
        data['receipt']['receipt'].update(observations={'first': last}, not_started=[], attempts=[
            {'operation_id': 'first', 'attempt': 1, 'pressure_terminated': True, 'observation': victim},
            {'operation_id': 'first', 'attempt': 2, 'pressure_terminated': False, 'observation': last}])
        self.write(data)
        result = summarize_native_workers(self.root)
        self.assertEqual(result['observed_completed_worker_count'], 2)
        self.assertEqual([(r['attempt'], r['returncode'], r['pressure_terminated']) for r in result['workers']],
                         [(1, -9, True), (2, 0, False)])
        for mutate in (lambda d: d['receipt']['receipt']['attempts'].pop(0),
                       lambda d: d['worker']['workers'].append(copy.deepcopy(d['worker']['workers'][0])),
                       lambda d: d['receipt']['receipt']['attempts'][0].__setitem__('attempt', 3),
                       lambda d: d['receipt']['receipt']['observations'].__setitem__('first', {'root_process_id': 125,
                           'root_process_started_at_utc_ticks': 458, 'exit_code': 99})):
            broken = copy.deepcopy(data); mutate(broken); self.write(broken)
            with self.subTest(mutate=mutate):
                self.assertIsNone(summarize_native_workers(self.root)['observed_completed_worker_count'])


if __name__ == '__main__':
    unittest.main()
