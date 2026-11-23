"""Fact-only terminal wire and reconciliation tests."""
import copy
import json
import tempfile
from pathlib import Path
import unittest

from msplatform.backends.simion.terminal_evidence import (
    attach_terminal_evidence, collect_terminal_evidence, parse_terminal_wire, reconcile_terminal_evidence,
    render_terminal_6d_rec,
)


def row(event='terminate', seq=4, **changes):
    value = dict(schema_version=1, particle_id=7, ion=1, native_run='unit', ion_run=1,
        capture_sequence=seq, event=event, raw_birth_us=0., raw_tof_us=1., raw_step_us=.01,
        source_origin_us=4., pipeline_clock_us=5., instrument_time_us=5., instance=2,
        x_mm=1., y_mm=2., z_mm=3., vx_mm_per_us=4., vy_mm_per_us=5., vz_mm_per_us=6.,
        splat=None, grouped=0)
    value.update(changes)
    return value


def wire(value):
    return 'SIMION_TERMINAL_V1: '+json.dumps(value, allow_nan=False)


class TerminalEvidenceTests(unittest.TestCase):
    def test_unordered_transport_uses_capture_order_and_isolates_ions(self):
        records=[row('initialize',1),row('other_actions_before',2),row('other_actions_after',3),row()]
        other=row('initialize',1,particle_id=91,ion=2)
        got=parse_terminal_wire([wire(records[3]),wire(other),wire(records[1]),wire(records[0]),wire(records[2])],native_run='unit',ion=1,particle_id=7)
        self.assertEqual([r['event'] for r in got['records']], [r['event'] for r in records])
        self.assertEqual(got['status'],'recorded_v1')
        self.assertEqual(parse_terminal_wire(['legacy text'],native_run='unit',ion=1,particle_id=7)['status'],'legacy_absent')

    def test_wire_refuses_bad_identity_order_duplicate_and_nonfinite(self):
        start=row('initialize',1); end=row(); before=row('other_actions_before',2); after=row('other_actions_after',3)
        cases=[[start,dict(end,particle_id=8)],[start,dict(end,native_run='other')],
               [start,dict(end,capture_sequence=1)],
               [start,dict(after,capture_sequence=2),dict(before,capture_sequence=3),end],
               [start,dict(end,x_mm=float('nan'))]]
        for records in cases:
            with self.subTest(records=records),self.assertRaises(ValueError):
                parse_terminal_wire(['SIMION_TERMINAL_V1: '+json.dumps(r) for r in records],native_run='unit',ion=1,particle_id=7)
        self.assertFalse(parse_terminal_wire([wire(start),wire(before),wire(end)],native_run='unit',ion=1,particle_id=7)['callback_pair_complete'])
        with self.assertRaises(ValueError):
            parse_terminal_wire(['SIMION_TERMINAL_V1: {"schema_version":1,"schema_version":1}'],native_run='unit',ion=1,particle_id=7)

    def test_relationships_remain_separate_from_unknown_cause(self):
        terminal=row()
        for time,expected in ((4.9,'before'),(5.,'equal'),(5.1,'after')):
            pre=row('other_actions_before',2,instrument_time_us=time,splat=-1)
            result=reconcile_terminal_evidence(terminal,pre)
            self.assertEqual(result['pre_action_time_relation'],expected)
            self.assertEqual(result['pre_action_6d'],'equal')
            self.assertEqual(result['physical_cause'],'unknown')
            self.assertEqual(result['facts']['pre_action'],pre)
        missing=reconcile_terminal_evidence(terminal)
        self.assertEqual(missing['pre_action_time_relation'],'absent')
        self.assertIsNone(missing['program_changed_stop'])
        self.assertTrue(missing['terminal_6d_complete'])
        partial=reconcile_terminal_evidence({'particle_id':7,'x_mm':1.})
        self.assertFalse(partial['terminal_6d_complete'])
        self.assertFalse(any(partial['raw_clock_available'].values()))
        self.assertEqual(partial['physical_cause'],'unknown')

    def test_rec_preserves_native_start_terminal_6d_without_cause_relabeling(self):
        initial = row('initialize', 1, raw_tof_us=0., raw_step_us=None)
        terminal = row(raw_tof_us=1.25, raw_step_us=None)
        evidence = {'status': 'recorded_v1', 'particle_evidence': [
            {'raw': {'records': [initial, terminal]},
             'reconciliation': {'physical_cause': 'unknown'}}]}
        actual = render_terminal_6d_rec(evidence).splitlines()
        self.assertEqual(actual[0], 'Ion,Event,TOF,X,Y,Z,Vx,Vy,Vz')
        self.assertEqual(actual[1], '1,Start,0,1,2,3,4,5,6')
        self.assertEqual(actual[2], '1,Splat,1.25,1,2,3,4,5,6')
        self.assertEqual(evidence['particle_evidence'][0]['reconciliation']['physical_cause'], 'unknown')
        incomplete = copy.deepcopy(evidence)
        incomplete['particle_evidence'][0]['raw']['records'][1]['vz_mm_per_us'] = None
        with self.assertRaisesRegex(ValueError, 'finite native TOF and 6D'):
            render_terminal_6d_rec(incomplete)
        with self.assertRaisesRegex(ValueError, 'complete current terminal evidence'):
            render_terminal_6d_rec({'status': 'legacy_absent'})

    def test_own_stop_and_legacy_observations_do_not_replace_terminal(self):
        end=row();pre=row('other_actions_before',2,splat=0,x_mm=9.);post=row('other_actions_after',3,splat=1,x_mm=8.)
        request={'particle_id':7,'ion':1,'native_run':'unit','x_mm':99.}
        result=reconcile_terminal_evidence(end,pre,post,request=request)
        self.assertTrue(result['program_changed_stop'])
        self.assertEqual(result['pre_action_6d'],'different')
        self.assertEqual(result['facts']['terminal']['x_mm'],1.)
        self.assertEqual(result['facts']['request']['x_mm'],99.)
        self.assertEqual(result['physical_cause'],'unknown')
        pre['splat']=-1
        self.assertFalse(reconcile_terminal_evidence(end,pre,post)['program_changed_stop'])
        pre['splat']=0;post['splat']=-1
        self.assertTrue(reconcile_terminal_evidence(end,pre,post)['program_changed_stop'])

    def test_collection_requires_new_wire_and_keeps_classification_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'native.log'
            initial=row('initialize',1,raw_step_us=None)
            terminal=row(raw_step_us=None)
            pre=row('other_actions_before',2,instrument_time_us=5.01,splat=-1)
            after=row('other_actions_after',3,instrument_time_us=5.01,splat=-1)
            path.write_text('\n'.join(wire(r) for r in (initial,pre,after,terminal)),encoding='utf8')
            batch=dict(expected_particle_ids=[7],build_metadata=dict(terminal_evidence=dict(schema_version=1,native_run='unit')))
            result=dict(native_terminals=[terminal],census=dict(unknown_is_loss=False))
            actual=attach_terminal_evidence(copy.deepcopy(result),[path],[batch])
            self.assertEqual(actual['census'],result['census'])
            evidence=actual['terminal_evidence']['particle_evidence'][0]['reconciliation']
            self.assertEqual(evidence['pre_action_time_relation'],'after')
            self.assertEqual(evidence['physical_cause'],'unknown')
            self.assertTrue(evidence['terminal_6d_complete'])
            bad=copy.deepcopy(result);bad['native_terminals'][0]['x_mm']=9.
            with self.assertRaisesRegex(ValueError,'wire/native state differs'):
                attach_terminal_evidence(bad,[path],[batch])
            path.write_text('legacy only',encoding='utf8')
            with self.assertRaisesRegex(ValueError,'required terminal v1'):
                attach_terminal_evidence(result,[path],[batch])
            legacy=attach_terminal_evidence(result,[path],[dict(expected_particle_ids=[7])])
            self.assertEqual(legacy['terminal_evidence']['status'],'legacy_absent')

    def test_batch_run_identity_raw_birth_and_partial_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'native.log'
            initial = row('initialize', 1, raw_birth_us=3., raw_tof_us=0., raw_step_us=None)
            terminal = row('terminate', 4, raw_birth_us=3., raw_step_us=None)
            path.write_text('\n'.join([wire(terminal), wire(initial)]), encoding='utf8')
            batch = dict(native_run='unit', expected_particle_ids=[7, 91])
            result = collect_terminal_evidence([path], [batch])
            self.assertEqual(result[7]['status'], 'recorded_v1')
            self.assertEqual(result[91]['status'], 'legacy_absent')
            with self.assertRaisesRegex(ValueError, 'required terminal v1'):
                collect_terminal_evidence([path], [batch], require_v1=True)
            self.assertEqual(result[7]['records'][0]['raw_tof_us'], 0.)
            self.assertEqual(result[7]['records'][0]['raw_birth_us'], 3.)
            for altered in (dict(terminal, ion_run=2), dict(terminal, ion_run=0),
                            dict(terminal, native_run='wrong'), dict(terminal, ion=2)):
                path.write_text('\n'.join([wire(initial), wire(altered)]), encoding='utf8')
                with self.subTest(altered=altered), self.assertRaises(ValueError):
                    collect_terminal_evidence([path], [batch])
            other = row('initialize', 1, ion=2, particle_id=7)
            path.write_text('\n'.join([wire(initial), wire(other), wire(terminal)]), encoding='utf8')
            with self.assertRaises(ValueError):
                collect_terminal_evidence([path], [batch])
            with self.assertRaises(ValueError):
                reconcile_terminal_evidence(terminal, row('other_actions_before', 2, ion_run=2))

    def test_explicit_internal_callbacks_leave_legacy_binding_unchanged(self):
        from msplatform.backends.simion.terminal_evidence import append_terminal_recorder

        callbacks = dict(particle_id='original_particle_id', source_origin_us='source_birth',
                         pipeline_clock_us='elapsed_clock', instrument_time_us='elapsed_clock')
        actual = append_terminal_recorder('PROGRAM', recorder_source='return {}', native_run='dual', callbacks=callbacks)
        self.assertIn('particle_id=original_particle_id', actual)
        self.assertIn('source_origin_us=source_birth', actual)
        legacy = append_terminal_recorder('PROGRAM', recorder_source='return {}', native_run='single')
        self.assertIn('particle_id=single_flight_canonical_particle_id', legacy)
        for broken in ({}, dict(callbacks, particle_id=''), dict(callbacks, extra='value')):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                append_terminal_recorder('', recorder_source='', native_run='dual', callbacks=broken)

    def test_retained_sfi_and_ip_mr_examples_remain_unknown(self):
        for terminal_time, callback_time in ((4.106731510075654, 4.106731511075654),
                                              (5.20681410792426, 5.2148420942233935)):
            end = row(instrument_time_us=terminal_time)
            pre = row('other_actions_before', 2, instrument_time_us=callback_time, splat=-1)
            result = reconcile_terminal_evidence(end, pre)
            self.assertEqual(result['pre_action_time_relation'], 'after')
            self.assertEqual(result['physical_cause'], 'unknown')
            self.assertIsNone(result['native_splat_after'])

    def test_identity_sequence_and_finiteness_refused(self):
        end=row()
        for bad in (row('other_actions_before',2,particle_id=8),row('other_actions_before',2,native_run='other'),row('other_actions_before',4),row('other_actions_before',2,x_mm=float('inf'))):
            with self.subTest(bad=bad),self.assertRaises(ValueError):reconcile_terminal_evidence(end,bad)
        original=copy.deepcopy(end);reconcile_terminal_evidence(end);self.assertEqual(end,original)


if __name__ == '__main__':
    unittest.main()
