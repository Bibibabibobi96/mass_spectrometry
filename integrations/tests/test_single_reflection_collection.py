"""Bounded synthetic native logs test real preparation and analyzer contracts."""
from __future__ import annotations

import csv
import copy
import json
import math
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from integrations.workflows.single_reflection_flight.census import canonical_census, read_native_events
from common.contracts.write_run_manifest import file_record
from integrations.tests.test_single_reflection_preparation import fixture, write_json
from integrations.workflows.single_reflection_flight.prepare import prepare
from integrations.workflows.single_reflection_flight.collect import collect_log, compare_collections, select_pulse
from integrations.workflows.single_reflection_flight.pulse import resolve_phase_flight

ROOT = Path(__file__).resolve().parents[2]


class SingleReflectionCollectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        request_path, self.run, request = fixture(self.root)
        self.flight = dict(pulse=dict(mode='held_off'), maximum_flight_us=10., maximum_step_us=.1,
                           trajectory_quality=8, rf_steps_per_period=32)
        request['flight'] = self.flight
        write_json(request_path, request)
        self.preparation = prepare(request_path, self.run)
        folder = self.run / 'simion/full_instrument'
        folder.mkdir(parents=True)
        outputs = {}
        for key, filename in (('iob', 'instrument.iob'), ('program', 'instrument.lua'),
                              ('particles', 'instrument.fly2'), ('build_spec', 'iob_build.lua')):
            path = folder / filename
            path.write_text('INERT_CONTROL_NOT_NATIVE_EVIDENCE', encoding='utf-8')
            outputs[key] = file_record(path)
        provenance = json.loads((self.run / 'inputs/source_provenance.json').read_text())
        self.workbench = dict(role='single_reflection_workbench_preparation', phase='full_instrument', particle_count=100,
            source_transform_applied=False, source_record=self.preparation['outputs']['projected_source'],
            clock_epoch_id=provenance['clock_epoch_id'], outputs=outputs, inputs={}, flight=copy.deepcopy(self.flight))
        with (self.run / 'inputs/projected_source.csv').open(newline='', encoding='utf-8-sig') as stream:
            self.source = list(csv.DictReader(stream))
        self.lines = []
        for source in self.source:
            pid = int(source['particle_id'])
            t = float(source['instrument_time_us'])
            state = ' '.join(f'{a}_mm={float(source[f"position_{a}_mm"]):.17g}' for a in 'xyz')
            state += ' ' + ' '.join(f'v{a}_mm_per_us={float(source[f"velocity_{a}_m_s"])/1000:.17g}' for a in 'xyz')
            self.lines.append(f'TRACE: source_release ion={pid} particle_id={pid} instrument_time_us={t:.17g} {state}')
            self.lines.append(f'TRACE: handoff_terminal_raw ion={pid} instance=3 instrument_time_us={t+1:.17g} {state}')
            xyz = ' '.join(f'{a}={float(source[f"position_{a}_mm"]):.17g}' for a in 'xyz')
            self.lines.append(f'TRACE: non_detector_splat ion={pid} instance=3 t={t+1:.17g} {xyz} zmax=0')
        self.lines.append(f'status,Fly completed. {len(self.source)} splats')
        self.log = self.run / 'native.stdout.log'
        self.write_log(self.lines)

    def write_log(self, lines, name=None):
        path = self.log if name is None else self.run / name
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return path

    def collect(self, path=None):
        return collect_log(self.preparation, self.workbench, self.run, path or self.log)

    @unittest.skipUnless(os.name == 'nt', 'Windows execution junction semantics')
    def test_collection_embeds_enduring_input_paths_after_junction_removal(self):
        alias = self.root / 'execution_alias'
        linked = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(self.run)],
            cwd=self.root, capture_output=True, text=True, check=False, timeout=30)
        self.assertEqual(linked.returncode, 0, linked.stdout + linked.stderr)
        original = copy.deepcopy(self.preparation)
        try:
            for record in [self.preparation['input_records']['request'], *(
                    self.preparation['outputs'][key] for key in
                    ('frontend_geometry', 'frontend_field_design', 'projected_source'))]:
                record['path'] = str(alias / Path(record['path']).relative_to(self.run))
            self.workbench['source_record'] = self.preparation['outputs']['projected_source']
            result = self.collect()
        finally:
            os.rmdir(alias)
        for name, record in (
                ('request_record', original['input_records']['request']),
                ('geometry_record', original['outputs']['frontend_geometry']),
                ('field_design_record', original['outputs']['frontend_field_design']),
                ('source_record', original['outputs']['projected_source'])):
            self.assertEqual(result[name], record)
            self.assertTrue(Path(result[name]['path']).is_file())

    def split_batches(self):
        original = copy.deepcopy(self.workbench)
        count = len(self.source)
        middle = count//2
        cases = []
        for index, (start, end) in enumerate(((0,middle),(middle,count)),1):
            lines = [re.sub(r'\bion=(\d+)', lambda m: 'ion='+str(int(m[1])-start), line)
                     for line in self.lines[3*start:3*end]]+[f'status,Fly completed. {end-start} splats']
            log = self.write_log(lines, f'batch_{index}.stdout.log')
            case = copy.deepcopy(original)
            case.update(source_row_range=[start+1,end],expected_particle_ids=[int(row['particle_id'])
                for row in self.source[start:end]],stdout=str(log),replay_stdout=str(log))
            cases.append(case)
        self.workbench['batches'] = cases
        return cases

    def test_batch_logs_require_each_native_completion_and_exact_cohort_coverage(self):
        cases = self.split_batches()
        baseline = self.collect()
        self.assertEqual(len(baseline['native_terminals']),100)
        self.assertEqual(len(baseline['log_record']),2)
        replay = collect_log(self.preparation,self.workbench,self.run,replay=True)
        self.assertTrue(compare_collections(baseline,replay)['passed'])
        path = Path(cases[1]['stdout'])
        original = path.read_text()
        path.write_text(original.replace('status,Fly completed.',''))
        with self.assertRaisesRegex(ValueError,'completion sentinel'):
            self.collect()
        path.write_text(original)
        cases[1]['expected_particle_ids'] = cases[0]['expected_particle_ids']
        with self.assertRaisesRegex(ValueError,'source-row binding'):
            self.collect()

    def test_inline_flight_is_derived_from_authority_and_shared_by_all_batches(self):
        self.workbench['flight']['maximum_step_us'] = .2
        with self.assertRaisesRegex(ValueError, 'frozen scientific request'):
            self.collect()
        self.workbench['flight'] = copy.deepcopy(self.flight)
        cases = self.split_batches()
        cases[1]['flight']['trajectory_quality'] += 1
        with self.assertRaisesRegex(ValueError, 'batch flight differs'):
            self.collect()

    def discovery(self, candidates):
        author = dict(self.flight, pulse=dict(mode='discover', width_us=.1, candidate_times_us=candidates))
        request_path = Path(self.preparation['input_records']['request']['path'])
        request = json.loads(request_path.read_text())
        request['flight'] = author
        write_json(request_path, request)
        self.preparation['input_records']['request'] = file_record(request_path)
        self.flight = resolve_phase_flight(author, phase='discovery')
        self.workbench['flight'] = copy.deepcopy(self.flight)
        self.workbench['phase'] = 'discovery'

    def shared_line(self, pid=1, target=1.5, actual=None):
        g = json.loads(Path(self.preparation['outputs']['frontend_geometry']['path']).read_text())['accelerator_projection']
        z = (g['repeller_front_z_mm'] + g['grid1_z_mm']) / 2
        return (f'TRACE: native_shared_time ion={pid} particle_id={pid} instance=3 '
                f'candidate_time_us={target:.17g} instrument_time_us={target if actual is None else actual:.17g} '
                f'x_mm={g["axis_x_mm"]:.17g} y_mm={g["axis_y_mm"]:.17g} z_mm={z:.17g} '
                'vx_mm_per_us=1 vy_mm_per_us=2 vz_mm_per_us=3 kinetic_energy_eV=4')

    def collection_record(self, collection, name='discovery_collection.json'):
        path = self.run / name
        write_json(path, collection)
        return file_record(path)

    def test_recorded_pre_pulse_continuation_keeps_parent_ledger_and_replay(self):
        selected = [self.source[7], self.source[6]]
        for row in selected:
            row['instrument_time_us'] = '10'
        source_path = self.run / 'inputs/projected_source.csv'
        with source_path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=selected[0].keys(), lineterminator='\n')
            writer.writeheader(); writer.writerows(selected)
        source_record = file_record(source_path)
        self.preparation['outputs']['projected_source'] = source_record
        provenance_path = self.run / 'inputs/source_provenance.json'
        provenance = json.loads(provenance_path.read_text())
        provenance.update(source_kind='recorded_pre_pulse_state', particle_count=2,
            continued_particle_ids=[8, 7], continued_particle_count=2,
            original_mother_particle_ids=list(range(1, 101)), original_mother_particle_count=100,
            uncontinued_mother_particle_ids=[*range(1, 7), *range(9, 101)], restart_state_time_us=10.,
            original_birth_times_us={'8': 8., '7': 7.})
        write_json(provenance_path, provenance)
        self.preparation['outputs']['source_provenance'] = file_record(provenance_path)
        self.workbench.update(particle_count=2, source_record=source_record)
        self.source = selected
        self.lines = []
        for native_ion, row in enumerate(selected, 1):
            pid, t = int(row['particle_id']), float(row['instrument_time_us'])
            state = ' '.join(f'{a}_mm={float(row[f"position_{a}_mm"]):.17g}' for a in 'xyz')
            state += ' ' + ' '.join(f'v{a}_mm_per_us={float(row[f"velocity_{a}_m_s"])/1000:.17g}' for a in 'xyz')
            self.lines.extend((f'TRACE: source_release ion={native_ion} particle_id={pid} instrument_time_us={t:.17g} {state}',
                f'TRACE: handoff_terminal_raw ion={native_ion} instance=3 instrument_time_us={t+1:.17g} {state}',
                f'TRACE: non_detector_splat ion={native_ion} instance=3 t={t+1:.17g} x={float(row["position_x_mm"]):.17g} y={float(row["position_y_mm"]):.17g} z={float(row["position_z_mm"]):.17g} zmax=0'))
        self.lines.append(f'status,Fly completed. {len(selected)} splats')
        result = self.collect(self.write_log(self.lines))
        self.assertEqual(result['role'], 'single_reflection_recorded_pre_pulse_continuation_collection')
        self.assertEqual(result['continuation']['continued_particle_ids'], [8, 7])
        self.assertEqual(result['continuation']['original_mother_particle_count'], 100)
        self.assertEqual(len(result['native_terminals']), 2)
        replay = self.collect(self.write_log(self.lines, 'replay.stdout.log'))
        comparison = compare_collections(result, replay)
        self.assertTrue(comparison['passed'])
        self.assertEqual(comparison['continued_count'], 2)
        self.split_batches()
        batched = self.collect()
        self.assertEqual([row['particle_id'] for row in batched['native_terminals']],[8,7])
        self.assertEqual(batched['continuation'],result['continuation'])
        self.discovery([10.5])
        for case in self.workbench['batches']:
            case['flight'] = copy.deepcopy(self.workbench['flight'])
            path = Path(case['stdout'])
            lines = path.read_text().splitlines()
            sample = self.shared_line(pid=case['expected_particle_ids'][0],target=10.5)
            lines.insert(1,re.sub(r'\bion=\d+','ion=1',sample))
            path.write_text('\n'.join(lines)+'\n')
        discovery = self.collect()
        decision = select_pulse(self.preparation,self.run,self.collection_record(discovery))
        self.assertEqual(decision['schema_version'],2)
        self.assertEqual(decision['selection']['execution_cohort_count'],2)
        self.assertEqual(discovery['continuation']['original_mother_particle_count'],100)

    def test_discovery_collects_actual_shared_states_for_complete_mother(self):
        candidates = [float(row['instrument_time_us']) + .5 for row in self.source]
        self.discovery(candidates)
        shared = [self.shared_line(pid, t) for pid, t in enumerate(candidates, 1)]
        result = self.collect(self.write_log([*shared, *self.lines]))
        self.assertEqual(len(result['native_shared_states']), 100)
        self.assertEqual(len(result['native_terminals']), 100)
        self.assertEqual(result['census']['census']['source_release'], 100)
        for pid, row in enumerate(result['native_shared_states'], 1):
            self.assertEqual(row['particle_id'], pid)
            self.assertEqual(row['candidate_time_us'], candidates[pid-1])
            self.assertEqual(row['instrument_time_us'], candidates[pid-1])
            self.assertEqual([row[f'v{a}_mm_per_us'] for a in 'xyz'], [1., 2., 3.])
            self.assertEqual(row['kinetic_energy_eV'], 4.)
        record = self.collection_record(result)
        self.log.unlink()  # Selection consumes the verified collection, not raw log again.
        decision = select_pulse(self.preparation, self.run, record)
        self.assertEqual(decision['status'], 'success')
        self.assertEqual(decision['input_records']['collection'], record)

    def test_discovery_preserves_actual_time_with_only_serialization_allowance(self):
        self.discovery([1.5])
        actual = 1.5 + 16 * math.ulp(1.5)
        result = self.collect(self.write_log([self.shared_line(actual=actual), *self.lines]))
        row = result['native_shared_states'][0]
        self.assertEqual(row['candidate_time_us'], 1.5)
        self.assertEqual(row['instrument_time_us'], actual)
        self.assertNotEqual(row['candidate_time_us'], row['instrument_time_us'])
        for line in (self.shared_line(actual=1.5 + 64 * math.ulp(1.5)),
                     self.shared_line(target=1.5 + math.ulp(1.5))):
            with self.subTest(line=line), self.assertRaisesRegex(ValueError, 'shared-time'):
                self.collect(self.write_log([line, *self.lines]))

    def test_discovery_rejects_duplicate_unknown_malformed_and_outside_lifetime(self):
        self.discovery([.5, 1.5, 2.5])
        valid = self.shared_line()
        cases = {
            'duplicate': [valid, valid],
            'unknown_id': [self.shared_line(pid=101)],
            'wrong_id': [valid.replace('particle_id=1 ', 'particle_id=2 ')],
            'nonfinite': [valid.replace('vx_mm_per_us=1 ', 'vx_mm_per_us=nan ')],
            'missing_state': [valid.replace(' vy_mm_per_us=2', '')],
            'duplicate_field': [valid + ' instance=3'],
            'before_birth': [self.shared_line(target=.5)],
            'after_terminal': [self.shared_line(target=2.5)],
        }
        for name, extra in cases.items():
            with self.subTest(case=name), self.assertRaises(ValueError):
                self.collect(self.write_log([*extra, *self.lines]))

    def test_discovery_missing_observation_is_unsupported_and_binding_mismatch_rejected(self):
        self.discovery([1.5])
        collection = self.collect()
        self.assertEqual(collection['native_shared_states'], [])
        record = self.collection_record(collection)
        decision = select_pulse(self.preparation, self.run, record)
        self.assertEqual(decision['status'], 'no_supported_candidate')
        self.assertNotIn('actual_pulse_time_us', decision)
        tally = decision['selection']['candidate_status_counts'][0]
        self.assertEqual(tally['numerical_unsupported'], 1)
        self.assertEqual(tally['not_born'], 99)
        for key in ('request_record', 'geometry_record', 'field_design_record', 'source_record', 'phase', 'native_complete', 'flight'):
            changed = copy.deepcopy(collection)
            if key.endswith('_record'):
                changed[key]['bytes'] += 1
            elif key == 'phase':
                changed[key] = 'full_instrument'
            elif key == 'flight':
                changed[key]['observation_times_us'] = [1.6]
            else:
                changed[key] = False
            with self.subTest(key=key), self.assertRaises(ValueError):
                select_pulse(self.preparation, self.run, self.collection_record(changed))
        outside = self.root / 'outside_collection.json'
        write_json(outside, collection)
        with self.assertRaisesRegex(ValueError, 'escapes'):
            select_pulse(self.preparation, self.run, file_record(outside))

    def test_discovery_cli_writes_negative_decision_before_nonzero_exit(self):
        self.discovery([1.5])
        record = self.collection_record(self.collect())
        preparation, workbench = self.run/'preparation.json', self.run/'workbench.json'
        write_json(preparation, self.preparation)
        write_json(workbench, self.workbench)
        output = self.run/'results/discovery'
        command = [sys.executable, '-m', 'integrations.workflows.single_reflection_flight.collect',
                   '--preparation', str(preparation), '--workbench', str(workbench), '--run', str(self.run),
                   '--output', str(output), '--select-pulse', '--collection-record', json.dumps(record)]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertFalse(receipt['passed'])
        decision_path = output/'pulse_decision.json'
        self.assertEqual(receipt['output_records']['pulse_decision.json'], file_record(decision_path))
        decision = json.loads(decision_path.read_text())
        self.assertEqual(decision['status'], 'no_supported_candidate')
        self.assertNotIn('actual_pulse_time_us', decision)

    def test_complete_100_mother_held_off_zero_detector_and_replay(self):
        original = (self.run / 'inputs/projected_source.csv').read_bytes()
        baseline = self.collect()
        replay = self.collect(self.write_log(['native header', *self.lines], 'replay.stdout.log'))
        self.assertTrue(compare_collections(baseline, replay)['passed'])
        self.assertEqual(baseline['census']['census']['source_release'], 100)
        self.assertEqual(baseline['census']['census']['detector_crossing'], 0)
        self.assertEqual(len(baseline['native_terminals']), 100)
        self.assertIsNone(baseline['census']['pulse_effective_time_us'])
        self.assertNotIn('pulse_effective_peak', baseline['census'])
        self.assertEqual((self.run / 'inputs/projected_source.csv').read_bytes(), original)

    def test_timed_all_lost_before_pulse_still_has_complete_census(self):
        self.flight['pulse'] = dict(mode='timed', time_us=200., width_us=2.)
        self.workbench['flight'] = copy.deepcopy(self.flight)
        path = Path(self.preparation['input_records']['request']['path'])
        request = json.loads(path.read_text())
        request['flight'] = self.flight
        write_json(path, request)
        self.preparation['input_records']['request'] = file_record(path)
        result = self.collect()
        self.assertEqual(result['census']['pulse_effective_time_us'], 200.)
        self.assertEqual(result['census']['census']['pre_pulse_state'], 0)
        self.assertEqual(result['census']['terminal_taxonomy']['terminal_outcome_count'], 100)

    def test_timed_replay_compares_actual_pulse_state_and_rejects_duplicate(self):
        self.flight['pulse'] = dict(mode='timed', time_us=1.5, width_us=.1)
        self.workbench['flight'] = copy.deepcopy(self.flight)
        path = Path(self.preparation['input_records']['request']['path'])
        request = json.loads(path.read_text())
        request['flight'] = self.flight
        write_json(path, request)
        self.preparation['input_records']['request'] = file_record(path)
        pulse = 'TRACE: handoff_pulse_on ion=1 instrument_time_us=1.5 x_mm=0 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0'
        baseline = self.collect(self.write_log([self.lines[0], pulse, *self.lines[1:]], 'pulse.log'))
        replay = self.collect(self.write_log([self.lines[0], pulse.replace('x_mm=0 ', 'x_mm=0.1 '), *self.lines[1:]], 'pulse_changed.log'))
        self.assertFalse(compare_collections(baseline, replay)['passed'])
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.collect(self.write_log([self.lines[0], pulse, pulse, *self.lines[1:]], 'pulse_duplicate.log'))

    def test_missing_duplicate_drifting_birth_terminal_and_completion_rejected(self):
        cases = {
            'birth_missing': self.lines[1:],
            'birth_duplicate': [self.lines[0], *self.lines],
            'birth_clock': [self.lines[0].replace('instrument_time_us=1 ', 'instrument_time_us=1.01 '), *self.lines[1:]],
            'terminal_missing': [self.lines[0], *self.lines[2:]],
            'terminal_duplicate': [self.lines[0], self.lines[1], *self.lines[1:]],
            'lifetime': [self.lines[0], self.lines[1].replace('instrument_time_us=2 ', 'instrument_time_us=0 '), *self.lines[2:]],
            'census_missing': [*self.lines[:2], *self.lines[3:]],
            'native_incomplete': self.lines[:-1],
            'heldoff_pulse': [*self.lines, 'TRACE: handoff_pulse_on ion=1 instrument_time_us=1'],
        }
        for case, lines in cases.items():
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.collect(self.write_log(lines, case + '.log'))

    def test_replay_detects_per_id_terminal_and_controls_drift(self):
        baseline = self.collect()
        changed = list(self.lines)
        changed[1] = changed[1].replace('instance=3', 'instance=2')
        changed[2] = changed[2].replace('instance=3', 'instance=2')
        replay = self.collect(self.write_log(changed, 'different.log'))
        self.assertFalse(compare_collections(baseline, replay)['passed'])
        Path(self.workbench['outputs']['program']['path']).write_text('CHANGED', encoding='utf-8')
        with self.assertRaises(Exception):
            self.collect()

    def test_detector_projection_is_distinct_and_serialization_allowance_is_bounded(self):
        lines = list(self.lines)
        lines[1] = lines[1].replace('instance=3', 'instance=4')
        lines[2] = 'TRACE: detector_crossing ion=1 t=1.25 x=0 y=0 z=0 r=0 zmax=1'
        baseline = self.collect(self.write_log(lines, 'detected.log'))
        self.assertEqual(baseline['census']['census']['detector_crossing'], 1)
        self.assertEqual(baseline['native_terminals'][0]['instrument_time_us'], 2.)
        end = baseline['census']['terminal_taxonomy']['particle_outcomes'][0]
        self.assertEqual(end['terminal_instrument_time_us'], 2.25)
        self.assertNotIn('vx_mm_per_us', end)
        replay = copy.deepcopy(baseline)
        value = replay['native_terminals'][0]['vx_mm_per_us']
        replay['native_terminals'][0]['vx_mm_per_us'] = value + math.ulp(max(1., abs(value)))
        self.assertTrue(compare_collections(baseline, replay)['passed'])
        replay['native_terminals'][0]['vx_mm_per_us'] = value + 128 * math.ulp(max(1., abs(value)))
        self.assertFalse(compare_collections(baseline, replay)['passed'])

    def test_three_x_observations_keep_actual_brackets_and_replay_events(self):
        source = self.source[0]
        t = float(source['instrument_time_us'])
        extras = []
        for offset, event in enumerate(('single_flight_handoff', 'accelerator_sidewall_inner_forward', 'accelerator_axis_forward'), 1):
            extras.append(f'TRACE: {event} ion=1 particle_id=1 instrument_time_us={t+offset/4:.17g} '
                f'x_mm={offset/4} y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0 '
                f'step_start_instrument_time_us={t:.17g} step_end_instrument_time_us={t+1:.17g} step_start_x_mm=0 step_end_x_mm=1')
        baseline = self.collect(self.write_log([self.lines[0], *extras, *self.lines[1:]], 'crossings.log'))
        self.assertEqual(baseline['census']['census']['accelerator_axis_forward'], 1)
        crossing = next(row for row in baseline['canonical_events'] if row['event'] == 'multipole_handoff')
        self.assertEqual(crossing['step_end_x_mm'], 1.)
        comparison = compare_collections(baseline, self.collect())
        self.assertFalse(comparison['passed'])
        with self.assertRaisesRegex(ValueError, 'bracket'):
            self.collect(self.write_log([self.lines[0], extras[0].split(' step_start_')[0], *self.lines[1:]], 'unbracketed.log'))

    def test_cli_existing_output_directory_and_saved_replay_evidence(self):
        preparation, workbench = self.run / 'preparation.json', self.run / 'workbench.json'
        write_json(preparation, self.preparation)
        write_json(workbench, self.workbench)
        output = self.run / 'results/single_reflection/flight'
        output.mkdir(parents=True)
        existing = output / 'native.stderr.log'
        existing.write_text('original evidence', encoding='utf-8')
        command = [sys.executable, '-m', 'integrations.workflows.single_reflection_flight.collect',
            '--preparation', str(preparation), '--workbench', str(workbench), '--run', str(self.run),
            '--log', str(self.log), '--output', str(output)]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['passed'])
        baseline_record=json.loads(result.stdout)['output_records']['collection.json']
        replay_log=self.run/'replay.stdout.log'
        replay_log.write_bytes(self.log.read_bytes())
        self.log.unlink()  # Replay must consume the first collection, not parse the old raw log again.
        command[command.index('--log')+1]=str(replay_log)
        replay = subprocess.run([*command, '--baseline-record', json.dumps(baseline_record)], cwd=ROOT,
            capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertEqual(existing.read_text(), 'original evidence')
        self.assertTrue((output / 'replay_comparison.json').is_file())
        baseline_record['bytes']+=1
        command[command.index('--output')+1]=str(output/'bad_baseline')
        rejected=subprocess.run([*command,'--baseline-record',json.dumps(baseline_record)],cwd=ROOT,
            capture_output=True,text=True,timeout=60,check=False)
        self.assertNotEqual(rejected.returncode,0)
        self.assertIn('baseline collection',rejected.stderr)



class CanonicalCensusTests(unittest.TestCase):
    def test_census_has_no_randomness_requirement_or_peak_computation(self):
        text = "\n".join([
            "TRACE: source_release ion=1 particle_id=1 instrument_time_us=1 x_mm=0 y_mm=0 z_mm=0 vx_mm_per_us=0 vy_mm_per_us=0 vz_mm_per_us=1",
            "TRACE: accelerator_sidewall_inner_forward ion=1 particle_id=1 instrument_time_us=1.25 x_mm=0.25 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0 step_start_instrument_time_us=1 step_end_instrument_time_us=2 step_start_x_mm=0 step_end_x_mm=1",
            "TRACE: accelerator_axis_forward ion=1 particle_id=1 instrument_time_us=1.5 x_mm=0.5 y_mm=0 z_mm=0 vx_mm_per_us=1 vy_mm_per_us=0 vz_mm_per_us=0 step_start_instrument_time_us=1 step_end_instrument_time_us=2 step_start_x_mm=0 step_end_x_mm=1",
            "TRACE: non_detector_splat ion=1 instance=3 t=2 x=1 y=0 z=0 zmax=0",
        ])
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "native.log"
            log.write_text(text, encoding="utf-8")
            for pulse in (None, 10.0):
                evidence = read_native_events([log], 100., [1])
                summary = canonical_census(evidence, [1], pulse_time_us=pulse)
                self.assertEqual(summary["census"]["detector_crossing"], 0)
                self.assertFalse(summary["peak_or_bootstrap_computed"])
                self.assertEqual(summary["terminal_taxonomy"]["terminal_outcome_count"], 1)
                self.assertEqual(evidence['rows'][1]["step_start_instrument_time_us"], 1.)
                self.assertEqual(summary["census"]["accelerator_axis_forward"], 1)


if __name__ == '__main__':
    unittest.main()
