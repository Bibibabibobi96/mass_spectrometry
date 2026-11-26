"""COMSOL co-resident basis and native observation boundary tests."""
import csv
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from msplatform.backends.comsol.assembly_particle_tracing import _basis_mesh_limit, _native_exact_count, _rows, _validate_failed_basis_evidence, prepare_assembly_pulse
from msplatform.backends.comsol.assembly_field_export import _validate_field_solution_source, validate_grid
from msplatform.backends.comsol.particle_data import read_observations
from msplatform.physics import CONSTANTS
from msplatform.results.particle_data import write_particle_data, read_particle_data, summarize_particle_data

COLUMNS = ('particle_id','native_particle_index','instrument_time_us','x_mm','y_mm','z_mm',
           'vx_m_per_s','vy_m_per_s','vz_m_per_s','state_present','solver_raw_status','solver_stop_time_us')


class ComsolParticleTracingTests(unittest.TestCase):
    def test_failed_basis_recovery_requires_declared_stopped_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); (root / 'results').mkdir()
            model = root / 'assembly-pulse-basis.mph'; model.write_bytes(b'model')
            report = root / 'results' / 'solve_pulse_basis.json'; report.write_text('{}')
            manifest = {'status': 'failed', 'run_id': 'run'}
            summary = {'status': 'failed', 'run_id': 'run', 'writers_stopped': True}
            host = {'host_release': {'inherited': False, 'result': {'status': 'released', 'token': 't'}, 'token': 't', 'error': None}}
            completion = {'status': 'failed', 'run_id': 'run', 'file_roles': {str(model): 'solver_native_binary', str(report): 'required_evidence'},
                'writer_completion': {'operations': [{'operation_id': 'solve_pulse_basis', 'observation': {'exit_confirmed': True, 'returncode': 0}, 'resource_release_id': 'r'}],
                                      'resource_releases': [{'release_id': 'r', 'completion_receipt': host}]}}
            _validate_failed_basis_evidence(manifest, summary, completion, root, model, report)
            for change in ('wrong_root', 'missing_role', 'bad_exit', 'missing_report'):
                bad = copy.deepcopy(completion); selected = report
                if change == 'wrong_root': selected = root / 'other.json'; selected.write_text('{}')
                elif change == 'missing_role': del bad['file_roles'][str(model)]
                elif change == 'bad_exit': bad['writer_completion']['operations'][0]['observation']['returncode'] = 1
                else: report.unlink()
                with self.subTest(change=change), self.assertRaises((ValueError, FileNotFoundError)):
                    _validate_failed_basis_evidence(manifest, summary, bad, root, model, selected)

    @unittest.skipUnless(__import__('os').name == 'nt', 'Windows immutable file handle required')
    def test_recovery_identity_rejects_changed_file(self):
        from msplatform.io.file_identity import guarded_file_identity
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'captured.mph'; path.write_bytes(b'old')
            with guarded_file_identity(path) as guard:
                size, digest = guard.bytes_count, guard.sha256
            path.write_bytes(b'new')
            with self.assertRaises(ValueError), guarded_file_identity(path, expected_bytes=size, expected_sha256=digest):
                pass

    def test_matlab_scientific_notation_count_is_exact(self):
        self.assertEqual(_native_exact_count(6.27792e6), 6277920)
        for value in (True, -1, 1.5, float('inf'), 2**53 + 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _native_exact_count(value)

    def test_mesh_guard_is_explicit_in_engineering_policy(self):
        self.assertEqual(_basis_mesh_limit({'runtime': {'maximum_mesh_elements': 5000000}}), 5000000)
        for policy in ({}, {'runtime': {}}, {'runtime': {'maximum_mesh_elements': True}},
                       {'runtime': {'maximum_mesh_elements': 0}},
                       {'runtime': {'maximum_mesh_elements': 1, 'other': 2}}):
            with self.subTest(policy=policy), self.assertRaisesRegex(ValueError, 'maximum mesh'):
                _basis_mesh_limit(policy)

    def test_export_selects_cold_reopened_co_resident_workpoint(self):
        def solution(study, tag, dataset):
            return {'study_tag': study, 'solution_tag': tag, 'dataset_tag': dataset,
                    'dataset_solution': tag, 'solution_empty': False, 'solution_count': 1,
                    'stored_main_solutions': 1, 'solution_dofs': 12}
        off, on = solution('std1', 'sol1', 'off'), solution('std2', 'sol2', 'on')
        report = {'operation': 'reopen', 'compute_calls': 0, 'off_solution': off, 'on_solution': on,
                  'mesh_identity': {'sha256': 'a'}, 'vacuum_domains': [1], 'group_keys': ['oa/grid'],
                  'off_voltages_v': [0], 'on_voltages_v': [100]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def write(value):
                (root / 'reopen_pulse_basis.json').write_text(json.dumps(value))
                (root / 'reopen_solution.json').write_text(json.dumps({'co_resident_workpoint': 'on', 'solution': on}))
                (root / 'request.json').write_text(json.dumps({'group_voltages': [
                    {'instance_id': 'oa', 'electrode_group_id': 'grid', 'voltage_v': 100}]}))
            write(report)
            metadata = {'backend': 'comsol', 'scope': 'co_resident_stationary_workpoint',
                        'field_status': 'solved', 'native_reopen_verified': True,
                        'co_resident_workpoint': 'on', 'solution': on}
            source = SimpleNamespace(metadata=metadata, data_path=lambda name: root / (name + '.json'))
            self.assertEqual(_validate_field_solution_source(source), on)
            grid = {'frame_id': 'world', 'origin_mm': [0, 0, 0], 'pitch_mm': [1, 1, 1],
                    'dimensions': [3, 3, 3], 'block_points': 10,
                    'study_tag': 'std2', 'solution_tag': 'sol2', 'dataset_tag': 'on'}
            projection = {'assembly_frame_id': 'world', 'outer_box_mm': {'min': [0, 0, 0], 'max': [2, 2, 2]}}
            self.assertEqual(validate_grid(grid, projection, on)['point_count'], 27)
            for mutation in ('same_solution', 'wrong_selection', 'wrong_dataset', 'no_mesh', 'wrong_voltage'):
                changed = copy.deepcopy(report)
                if mutation == 'same_solution':
                    changed['on_solution'] = copy.deepcopy(changed['off_solution'])
                elif mutation == 'wrong_selection':
                    changed['on_solution']['study_tag'] = 'unrelated'
                elif mutation == 'wrong_dataset':
                    changed['on_solution']['dataset_solution'] = 'wrong'
                elif mutation == 'no_mesh':
                    changed['mesh_identity'] = None
                else:
                    changed['on_voltages_v'] = [101]
                write(changed)
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    _validate_field_solution_source(source)

    def test_prepare_preserves_background_and_rejects_mismatched_bases(self):
        assembly = SimpleNamespace(composition_plan={}, components_resolved={}, components_source={})
        projection = {'outer_box_mm': {}, 'assembly_frame_id': 'world', 'members': []}
        off_request = {'group_voltages': [{'instance_id': 'oa', 'electrode_group_id': 'pulse', 'voltage_v': 0},
                                         {'instance_id': 'tof', 'electrode_group_id': 'mirror', 'voltage_v': 200}],
                       'relative_permittivity': 1, 'exterior': {}, 'mesh': {}, 'study': {}}
        on_request = copy.deepcopy(off_request)
        on_request['group_voltages'][0]['voltage_v'] = 100
        off = {'model': {'sha256': 'a' * 64, 'bytes': 100}, 'projection': projection, 'descriptor': {'members': []},
               'request': off_request, 'solution_tag': 'sol_off', 'reference': {}}
        on = {**copy.deepcopy(off), 'request': on_request, 'solution_tag': 'sol_on'}
        row = {'particle_id': 1, 'state_event': 'source_birth', 'parent_particle_id': None,
               'clock_epoch_id': 'epoch', 'frame_id': 'world', 'instrument_time_us': 0.0,
               'mass_amu': 100.0, 'charge_state': 1, 'species_id': 'ion'}
        source = {'rows': [row], 'clock': {'clock_epoch_id': 'epoch', 'authority_sha256': 'A' * 64},
                  'constants_version': CONSTANTS['version']}
        kwargs = dict(pulse_groups=[{'instance_id': 'oa', 'electrode_group_id': 'pulse'}],
                      drive={'on_us': 1.0, 'off_us': 2.0}, source=source,
                      numerics={'maximum_step_us': .01, 'relative_tolerance': 1e-6, 'absolute_tolerance': 1e-7},
                      observation_times_us=[0.0, 1.0, 2.0, 3.0])
        with patch('msplatform.backends.comsol.assembly_particle_tracing.Assembly', SimpleNamespace), \
             patch('msplatform.backends.comsol.assembly_particle_tracing.project_assembly_geometry', return_value=projection), \
             patch('msplatform.backends.comsol.assembly_particle_tracing.validate_component_particle_state_rows', return_value=SimpleNamespace(rows=[row])):
            with patch('msplatform.backends.comsol.assembly_particle_tracing._workpoint', side_effect=[off, on]):
                plan = prepare_assembly_pulse(assembly, None, None, **kwargs)
            self.assertEqual(plan['background']['request']['group_voltages'][1]['voltage_v'], 200)
            self.assertEqual(plan['native']['background_solution_tag'], 'sol_off')
            changed = copy.deepcopy(on)
            changed['request']['group_voltages'][1]['voltage_v'] = 0
            with patch('msplatform.backends.comsol.assembly_particle_tracing._workpoint', side_effect=[off, changed]), self.assertRaises(ValueError):
                prepare_assembly_pulse(assembly, None, None, **kwargs)
            changed = copy.deepcopy(on)
            changed['model']['sha256'] = 'b' * 64
            with patch('msplatform.backends.comsol.assembly_particle_tracing._workpoint', side_effect=[off, changed]), self.assertRaisesRegex(ValueError, 'independent MPH'):
                prepare_assembly_pulse(assembly, None, None, **kwargs)

    def test_basis_voltage_rows_reject_duplicate_or_nonfinite(self):
        row = {'instance_id': 'oa', 'electrode_group_id': 'plate', 'voltage_v': 10.0}
        self.assertEqual(_rows({'group_voltages': [row]}), {('oa', 'plate'): 10.0})
        for rows in ([row, row], [{**row, 'voltage_v': float('nan')}]):
            with self.assertRaises(ValueError):
                _rows({'group_voltages': rows})

    def test_realistic_observations_preserve_missing_terminal_and_initial_binding(self):
        source = [{'particle_id': 9, 'species_id': 'ion', 'time_s': 0.0,
                   'position_m': [0.001, 0.002, 0.003], 'velocity_m_s': [1.0, 2.0, 3.0],
                   'mass_kg': 1e-25, 'charge_state': 1, 'charge_c': 1.602176634e-19,
                   'weight': 1.0, 'parent_particle_id': None, 'lineage_status': 'primary_birth'}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'native.csv'
            def write(status, x=1.0):
                with path.open('w', newline='', encoding='utf-8') as stream:
                    writer = csv.writer(stream)
                    writer.writerow(COLUMNS)
                    writer.writerow([9, 1, 10, x, 2, 3, 1, 2, 3, 1, status, 'nan'])
                    writer.writerow([9, 1, 12, 1.2, 2, 3, 1, 2, 3, 1, status, 11])
            kwargs = dict(initial_states=source, epoch_us=10, backend_version='COMSOL 6.4',
                          observation_times_us=[10, 12], position_atol_m=1e-12, velocity_atol_m_s=1e-9,
                          boundary_policy='metal_and_outer_freeze_ideal_pass')
            write(1)
            active = read_observations(path, **kwargs)
            self.assertEqual(active.data_integrity['status'], 'complete')
            self.assertEqual(active.terminal_states[0]['stop_reason'], 'time_limit')
            self.assertEqual(active.terminal_states[0]['attribution_status'], 'unavailable')
            self.assertAlmostEqual(active.trajectories['position_m'][1, 0], .0012)
            write(2)
            frozen = read_observations(path, **kwargs)
            self.assertEqual(frozen.data_integrity['status'], 'complete')
            self.assertEqual(frozen.terminal_states[0]['time_s'], 1e-6)
            self.assertEqual(frozen.terminal_states[0]['velocity_m_s'], [1.0, 2.0, 3.0])
            self.assertEqual(frozen.terminal_states[0]['attribution_status'], 'unavailable')
            with self.assertRaisesRegex(ValueError, 'boundary policy'):
                read_observations(path, **{**kwargs, 'boundary_policy': 'unverified'})
            path.write_text(path.read_text().replace(',2,11', ',2,13'), encoding='utf-8')
            self.assertEqual(read_observations(path, **kwargs).data_integrity['missing_terminal_particle_ids'], [9])
            write(4)
            disappeared = read_observations(path, **kwargs)
            self.assertEqual(disappeared.data_integrity['missing_terminal_particle_ids'], [9])
            write_particle_data(Path(directory), disappeared, metadata={'schema_version': 2,
                'initial_state_basis': 'native_birth_verified', 'frame_id': 'world',
                'clock': {'basis': 'experiment_relative', 'unit': 's'}})
            self.assertEqual(summarize_particle_data(read_particle_data(Path(directory)))['census']['counts']['missing_record'], 1)
            write(1, x=1.1)
            with self.assertRaisesRegex(ValueError, 'original birth'):
                read_observations(path, **kwargs)


if __name__ == '__main__':
    unittest.main()
