"""Recorded-birth entry through the real public owner with inert native leaves."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.contracts.test_support.sfi_scalar_owner_fixture import (
    inert_native_leaf, make_fixture, retained_owner_directory,
)
from msplatform.execution import run_session
from msplatform.execution.resources import resource_path
from msplatform.results.artifacts import open_artifact
from msplatform.workflows.single_reflection_flight import recorded_birth


class RecordedBirthEntryTests(unittest.TestCase):
    def test_old_request_parameter_is_rejected_before_entry(self):
        script = Path(__file__).resolve().parents[2] / 'src/msplatform/workflows/resources/single_reflection_flight.ps1'
        command = [shutil.which('pwsh'), '-NoProfile', '-NonInteractive', '-File', str(script),
                   '-PreparationManifest', 'unused', '-FieldsReference', 'unused', '-SpeciesId', 'unused',
                   '-ExpectedParticleIds', 'unused', '-Observations', 'unused', '-Environment', 'unused',
                   '-Workspace', 'unused', '-Profile', 'unused', '-Request', 'old.json']
        result = subprocess.run(command, cwd=script.parents[4], capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=30, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Request', result.stderr)
        self.assertNotIn('OWNER_RETURNED=', result.stdout)

    def test_entry_owner_recovery_and_bad_field(self):
        with retained_owner_directory() as directory:
            root = Path(directory)
            selected = make_fixture(root)
            values = selected['context']
            environment = {
                'schema_version': 1, 'role': 'execution_environment',
                'tools': {'python': sys.executable, 'powershell': values['powershell_executable'],
                          'simion': sys.executable},
                'policy': {'host_state_path': os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH'],
                           'policy_path': str(resource_path('host_resource_policy.json')),
                           'capacity_policy_path': values['capacity_policy_path']},
                'profiles': {'fixture': {'stage_policy_path': values['stage_policy_path']}},
            }
            def save(name, value):
                path = root / (name + '.json')
                path.write_text(json.dumps(value), encoding='utf-8')
                return str(path)
            env = save('environment', environment)
            fields = save('fields', selected['fields'])
            ids = save('ids', selected['expected_particle_ids'])
            observations = save('observations', {'plane_observations': []})
            basis = save('basis', selected['scalar_field_basis'])
            base = ['entry', '--preparation-manifest', selected['preparation_manifest']['path'],
                    '--fields-reference', fields, '--species-id', selected['species_id'],
                    '--expected-particle-ids', ids, '--observations', observations,
                    '--environment', env, '--workspace', values['workspace'], '--profile', 'fixture',
                    '--scalar-field-basis', basis]
            observed = []
            leaf = inert_native_leaf(run_session.run_observed_process, observed)
            inherited = {'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN': '',
                         'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID': '',
                         'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE': ''}
            def invoke(arguments):
                output = io.StringIO()
                with patch.object(sys, 'argv', arguments), contextlib.redirect_stdout(output):
                    recorded_birth.main()
                lines = [line for line in output.getvalue().splitlines() if line.startswith('OWNER_RETURNED=')]
                self.assertEqual(len(lines), 1)
                return json.loads(lines[0].split('=', 1)[1])
            with patch.dict(os.environ, inherited), patch.object(run_session, 'run_observed_process', side_effect=leaf):
                first = invoke(base)
                self.assertEqual(len(observed), 3)
                product = open_artifact(first, expected_kind='trajectory_result')
                collection = json.loads(product.data_path('collection').read_text(encoding='utf-8'))
                self.assertEqual(collection['original_mother']['mother_particle_ids'], selected['expected_particle_ids'])
                recovery = save('recovery', first['manifest'])
                second = open_artifact(invoke(base + ['--recovery-reference', recovery]),
                                       expected_kind='trajectory_result')
                self.assertEqual(second.metadata['reused_unit_count'], 1)
                self.assertEqual(len(observed), 3)
                from msplatform.examples import load_example
                release = copy.deepcopy(load_example('rf_oatof_functional_v1').release)
                propagation = {'schema_version': 1, 'scope': 'continuous_assembly',
                    'end_policy': {'maximum_particle_age_us': 200.}, 'consumed_plane_events': [], 'stop': None}
                numerics = {'maximum_step_us': .001, 'trajectory_quality': 17, 'rf_steps_per_period': 80}
                fresh = ['entry', '--release-request', save('release', release), '--fields-reference', fields,
                         '--propagation', save('propagation', propagation), '--numerics', save('numerics', numerics),
                         '--observations', observations, '--environment', env, '--workspace', values['workspace'],
                         '--profile', 'fixture', '--scalar-field-basis', basis]
                fresh_product = open_artifact(invoke(fresh), expected_kind='trajectory_result')
                fresh_collection = json.loads(fresh_product.data_path('collection').read_text(encoding='utf-8'))
                self.assertEqual(fresh_collection['original_mother']['mother_particle_ids'], release['particle_ids'])
                self.assertEqual(len(observed), 6)
                bad_clock = copy.deepcopy(release)
                bad_clock['clock']['authority_sha256'] = '0' * 64
                wrong_clock = list(fresh)
                wrong_clock[wrong_clock.index('--release-request') + 1] = save('bad-clock', bad_clock)
                with self.assertRaises((AssertionError, ValueError)):
                    invoke(wrong_clock)
                self.assertEqual(len(observed), 6)
                invalid = dict(selected['fields'], product_id='missing')
                with self.assertRaises((KeyError, ValueError)):
                    invoke(base[:2] + [base[2]] + ['--fields-reference', save('bad-fields', invalid)] + base[5:])
                self.assertEqual(len(observed), 6)

            # Only the commercial leaves are replaced inside the real Python
            # child launched by the public PowerShell entry.
            bootstrap = root / 'inert_entry_bootstrap.py'
            evidence = root / 'powershell-child.json'
            bootstrap.write_text('''import importlib.util, json, os, runpy, sys
from pathlib import Path
from unittest.mock import patch
from tests.contracts.test_support.sfi_scalar_owner_fixture import inert_native_leaf
from msplatform.execution import run_session
seen=[]
args=sys.argv[1:]
i=args.index("-m")
assert args[i+1] == "msplatform.workflows.single_reflection_flight.recorded_birth"
sys.argv=[args[i+1], *args[i+2:]]
origin=importlib.util.find_spec(sys.argv[0]).origin
print("INERT_CHILD_ORIGIN="+json.dumps({"pid":os.getpid(),"python":sys.executable,"module":origin,"argv":sys.argv}),flush=True)
actual=run_session.run_observed_process
normal=inert_native_leaf(actual,seen)
def leaf(context,**options):
    if os.environ.get("SFI_ENTRY_EXPECTED_FAILURE") == "1" and options["role"] == "SIMION":
        seen.append({"inert_failure":True})
        return actual(context,**dict(options,executable=Path(sys.executable),arguments=["-I","-c","import sys; print('INERT_EXPECTED_FAILURE', flush=True); sys.exit(7)"],role="GATE",stage="inert_sfi_tracking"))
    return normal(context,**options)
try:
    with patch.object(run_session,"run_observed_process",side_effect=leaf):
        runpy.run_module(sys.argv[0],run_name="__main__")
finally:
    Path(os.environ["SFI_ENTRY_CHILD_EVIDENCE"]).write_text(json.dumps({"operations":len(seen)}),encoding="utf8")
''', encoding='utf-8')
            shim = root / 'inert_python.cmd'
            shim.write_text(f'@"{sys.executable}" -B -X utf8 "{bootstrap}" %*\r\n', encoding='utf-8')
            script = Path(__file__).resolve().parents[2] / 'src/msplatform/workflows/resources/single_reflection_flight.ps1'
            command = [shutil.which('pwsh'), '-NoProfile', '-NonInteractive', '-File', str(script),
                       '-Python', str(shim), '-ReleaseRequest', fresh[2], '-FieldsReference', fields,
                       '-Propagation', fresh[6], '-Numerics', fresh[8], '-Observations', observations,
                       '-Environment', env, '-Workspace', values['workspace'], '-Profile', 'fixture',
                       '-ScalarFieldBasis', basis]
            child_env = dict(os.environ, **inherited, SFI_ENTRY_CHILD_EVIDENCE=str(evidence))
            child = subprocess.run(command, cwd=script.parents[4], env=child_env, capture_output=True,
                                   text=True, encoding='utf-8', errors='replace', timeout=300, check=False)
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
            self.assertEqual(json.loads(evidence.read_text(encoding='utf-8'))['operations'], 3)
            origin_line = next(line for line in child.stdout.splitlines() if line.startswith('INERT_CHILD_ORIGIN='))
            origin = json.loads(origin_line.split('=', 1)[1])
            self.assertGreater(origin['pid'], 0)
            self.assertEqual(Path(origin['python']).resolve(), Path(sys.executable).resolve())
            self.assertEqual(Path(origin['module']).resolve(), script.parents[4] / 'src/msplatform/workflows/single_reflection_flight/recorded_birth.py')
            self.assertEqual(origin['argv'][origin['argv'].index('--release-request') + 1], fresh[2])
            print('SFI_CHILD_EVIDENCE=' + json.dumps(origin), flush=True)
            output_line = next(line for line in child.stdout.splitlines() if line.startswith('OWNER_RETURNED='))
            product = open_artifact(json.loads(output_line.split('=', 1)[1]), expected_kind='trajectory_result')
            collection = json.loads(product.data_path('collection').read_text(encoding='utf-8'))
            self.assertEqual(collection['original_mother']['mother_particle_ids'], release['particle_ids'])
            census = collection['census']
            self.assertEqual(census['clock_basis'], 'canonical_instrument_time_us')
            self.assertEqual(census['census']['detector_crossing'], 0)
            taxonomy = census['terminal_taxonomy']
            self.assertEqual(taxonomy['category_counts'], {'non_detector_splat_instance_3': len(release['particle_ids'])})
            births = {row['particle_id']: row['instrument_time_us'] for row in collection['canonical_events']
                      if row['event'] == 'source_release'}
            self.assertEqual(set(births), set(release['particle_ids']))
            for terminal in taxonomy['particle_outcomes']:
                self.assertEqual(terminal['terminal_instrument_time_us'], births[terminal['particle_id']] + 1.)

            # The public PowerShell entry rejects mismatched inputs before its
            # child can start any native-leaf operation.
            for flag, path in (('-ReleaseRequest', save('ps-bad-clock', bad_clock)),
                               ('-FieldsReference', save('ps-bad-fields', invalid))):
                rejected_command = list(command)
                rejected_command[rejected_command.index(flag) + 1] = path
                rejected = subprocess.run(rejected_command, cwd=script.parents[4], env=child_env,
                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300, check=False)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertNotIn('OWNER_RETURNED=', rejected.stdout)
                self.assertEqual(json.loads(evidence.read_text(encoding='utf-8'))['operations'], 0)
            scalar_path = Path(selected['tamper_scalar_pa'])
            original_scalar = scalar_path.read_bytes()
            try:
                scalar_path.write_bytes(bytes([original_scalar[0] ^ 1]) + original_scalar[1:])
                rejected = subprocess.run(command, cwd=script.parents[4], env=child_env,
                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300, check=False)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertNotIn('OWNER_RETURNED=', rejected.stdout)
                self.assertEqual(json.loads(evidence.read_text(encoding='utf-8'))['operations'], 0)
            finally:
                scalar_path.write_bytes(original_scalar)

            # A separate workspace keeps the intentionally failed producer out of
            # retained_owner_directory's success-only cleanup check.  Never remove
            # it unless its real child and capacity lease have both closed.
            failed_root = Path(tempfile.mkdtemp(prefix='sfi-entry-failed-owner-'))
            safely_closed = False
            failed_command = list(command)
            failed_command[failed_command.index('-Workspace') + 1] = str(failed_root)
            try:
                from msplatform.execution.capacity_protection import _lease_path
                failed_env = dict(child_env, SFI_ENTRY_EXPECTED_FAILURE='1')
                failed = subprocess.run(failed_command, cwd=script.parents[4], env=failed_env,
                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300, check=False)
                self.assertNotEqual(failed.returncode, 0)
                self.assertIn('exit 7', failed.stderr)
                self.assertNotIn('OWNER_RETURNED=', failed.stdout)
                result_paths = list((failed_root / 'artifacts').rglob('result.json'))
                self.assertEqual(len(result_paths), 1)
                result = json.loads(result_paths[0].read_text(encoding='utf-8'))
                self.assertEqual(result['status'], 'failed')
                run = Path(result['run_directory'])
                completion = json.loads((run / 'results/execution_completion.json').read_text(encoding='utf-8'))
                operation = completion['writer_completion']['operations'][0]['observation']
                self.assertEqual(operation['returncode'], 7)
                self.assertTrue(operation['exit_confirmed'])
                releases = completion['writer_completion']['resource_releases']
                self.assertTrue(releases)
                self.assertTrue(all(item['completion_receipt']['host_release']['result']['status'] == 'released'
                                    for item in releases))
                self.assertIn('INERT_EXPECTED_FAILURE', (run / 'logs/operation_0001.stdout.log').read_text())
                capacity = result['capacity_session']
                self.assertEqual(capacity['status'], 'released')
                self.assertFalse(_lease_path(Path(capacity['artifact_root']), capacity['lease_id']).exists())
                safely_closed = True
            finally:
                if safely_closed:
                    shutil.rmtree(failed_root)
                else:
                    print('RETAINED_FAILED_SFI_ENTRY_FIXTURE', failed_root, flush=True)


    def test_partial_unit_recovery_through_entry(self):
        from msplatform.examples import load_example
        with retained_owner_directory() as directory:
            root = Path(directory)
            selected = make_fixture(root)
            values = selected['context']
            environment = {
                'schema_version': 1, 'role': 'execution_environment',
                'tools': {'python': sys.executable, 'powershell': values['powershell_executable'], 'simion': sys.executable},
                'policy': {'host_state_path': os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH'],
                           'policy_path': str(resource_path('host_resource_policy.json')),
                           'capacity_policy_path': values['capacity_policy_path']},
                'profiles': {'fixture': {'stage_policy_path': values['stage_policy_path']}},
            }
            def save(name, value):
                path = root / (name + '.json')
                path.write_text(json.dumps(value), encoding='utf-8')
                return str(path)
            def invoke(arguments):
                output = io.StringIO()
                with patch.object(sys, 'argv', arguments), contextlib.redirect_stdout(output):
                    recorded_birth.main()
                lines = [line for line in output.getvalue().splitlines() if line.startswith('OWNER_RETURNED=')]
                self.assertEqual(len(lines), 1)
                return json.loads(lines[0].split('=', 1)[1])
            release = copy.deepcopy(load_example('rf_oatof_functional_v1').release)
            propagation = {'schema_version': 1, 'scope': 'continuous_assembly',
                'end_policy': {'maximum_particle_age_us': 200.}, 'consumed_plane_events': [], 'stop': None}
            numerics = {'maximum_step_us': .001, 'trajectory_quality': 17, 'rf_steps_per_period': 80}
            fresh = ['entry', '--release-request', save('release', release),
                     '--fields-reference', save('fields', selected['fields']),
                     '--propagation', save('propagation', propagation), '--numerics', save('numerics', numerics),
                     '--observations', save('observations', {'plane_observations': []}),
                     '--environment', save('environment', environment), '--workspace', values['workspace'],
                     '--profile', 'fixture', '--scalar-field-basis', save('basis', selected['scalar_field_basis'])]
            inherited = {'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN': '',
                         'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID': '',
                         'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE': ''}
            # Exercise the real fixed-partition dispatcher with the repository's
            # existing inert unit transport. Only executable/arguments are
            # replaced; the SIMION/flight host stage and CPU telemetry are real.
            from tests.contracts.test_simion_tracking_units import INERT
            from tests.contracts.test_support.grouped_tracking_fixture import grouped_inert_transport
            from msplatform.execution.capacity_protection import _lease_path
            from msplatform.execution.run_session import RunSession
            from msplatform.io.manifest_records import file_record, require_completed_terminal_publication
            unit_root = Path(tempfile.mkdtemp(prefix='sfi-entry-partial-units-'))
            unit_closed = False
            script_path = unit_root / 'inert-unit.py'
            script_path.write_text(INERT, encoding='utf-8', newline='\n')
            phase = {'fail': True}
            unit_calls = []
            original_single, original_group = RunSession.run_process, RunSession.run_process_group
            def payload(session, name, argv, *, partial_log=False):
                key = name.split('__')[-1]
                index = int(key.split('_')[-1])
                kind = 'fly' if name.startswith('track_fly') else ('build' if name.startswith('build_') else 'verify')
                value = {'kind': kind}
                if kind == 'fly':
                    all_rows = json.loads((session.input_dir / 'canonical_source_states.json').read_text(encoding='utf-8'))
                    value.update(native_run=key, rows=all_rows[(index - 1) * 50:index * 50], partial=partial_log,
                                 delay=2. if partial_log else .2)
                else:
                    value['iob'] = str(session.run_dir / 'units' / key / 'simion/tracking/instrument.iob')
                target = session.declare_file(session.input_dir / (name + '.inert.json'), 'required_evidence')
                target.write_text(json.dumps(value), encoding='utf-8')
                session.add_input('inert_' + name, file_record(target, 'required_evidence'))
                return ['-I', '-B', str(script_path), str(target)]
            def single(session, name, *, immutable_input_records=(), **options):
                unit_calls.append((session.run_id, name))
                options.update(immutable_input_records=immutable_input_records,
                    arguments=payload(session, name, options['arguments']), executable=Path(sys.executable),
                    role='SIMION', stage='prepare')
                return original_single(session, name, **options)
            def normal_flight_group(session, specs, **options):
                options.update(role='SIMION', stage='flight')
                return original_group(session, specs, **options)
            grouped = grouped_inert_transport(normal_flight_group, payload, unit_calls,
                                              is_failed=lambda _session: phase['fail'])
            unit_args = list(fresh) + ['--unit-size', '50']
            unit_args[unit_args.index('--workspace') + 1] = str(unit_root)
            def results():
                return sorted((unit_root / 'artifacts').rglob('result.json'))
            try:
                with patch.dict(os.environ, inherited), patch.object(RunSession, 'run_process', new=single), \
                     patch.object(RunSession, 'run_process_group', new=grouped):
                    with self.assertRaises(Exception):
                        invoke(unit_args)
                    failed_result = json.loads(results()[-1].read_text(encoding='utf-8'))
                    self.assertEqual(failed_result['status'], 'failed')
                    failed_run = Path(failed_result['run_directory'])
                    index = json.loads((failed_run / 'logs/tracking_units.json').read_text(encoding='utf-8'))
                    self.assertEqual([unit['complete'] for unit in index['units']], [True, False])
                    predecessor = file_record(failed_run / 'run_manifest.json', 'required_evidence')
                    phase['fail'] = False
                    start_calls = len(unit_calls)
                    resumed_ref = invoke(unit_args + ['--recovery-reference', save('partial-recovery', predecessor)])
                    resumed = open_artifact(resumed_ref, expected_kind='trajectory_result')
                    self.assertEqual(resumed.metadata['reused_unit_count'], 1)
                    self.assertEqual(len(unit_calls) - start_calls, 3)
                    recovered = json.loads(resumed.data_path('collection').read_text(encoding='utf-8'))
                    self.assertEqual(recovered['original_mother']['mother_particle_ids'], release['particle_ids'])
                    self.assertEqual(recovered['census']['clock_basis'], 'canonical_instrument_time_us')
                    self.assertEqual(recovered['census']['census']['detector_crossing'], 0)
                    start_calls = len(unit_calls)
                    complete_ref = invoke(unit_args + ['--recovery-reference', save('complete-recovery', resumed_ref['manifest'])])
                    self.assertEqual(open_artifact(complete_ref, expected_kind='trajectory_result').metadata['reused_unit_count'], 2)
                    self.assertEqual(len(unit_calls), start_calls)
                    modified = copy.deepcopy(release)
                    modified['particle_ids'][0], modified['particle_ids'][1] = modified['particle_ids'][1], modified['particle_ids'][0]
                    changed_args = list(unit_args)
                    changed_args[changed_args.index('--release-request') + 1] = save('changed-release', modified)
                    with self.assertRaises((AssertionError, ValueError)):
                        invoke(changed_args + ['--recovery-reference', save('changed-source-parent', resumed_ref['manifest'])])
                    self.assertEqual(len(unit_calls), start_calls)
                    for path in (open_artifact(selected['fields'], expected_kind='field_bundle').data_path('compiled_model'),
                                 Path(selected['tamper_scalar_pa'])):
                        original = path.read_bytes()
                        try:
                            path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
                            with self.assertRaises((AssertionError, ValueError)):
                                invoke(unit_args + ['--recovery-reference', save('tampered-parent', resumed_ref['manifest'])])
                            self.assertEqual(len(unit_calls), start_calls)
                        finally:
                            path.write_bytes(original)
                for result_path in results():
                    result = json.loads(result_path.read_text(encoding='utf-8'))
                    run = Path(result['run_directory'])
                    require_completed_terminal_publication(run / 'run_manifest.json')
                    completion = json.loads((run / 'results/execution_completion.json').read_text(encoding='utf-8'))
                    self.assertTrue(all(row['observation']['exit_confirmed'] for row in completion['writer_completion']['operations']))
                    self.assertTrue(all(row['completion_receipt']['host_release']['result']['status'] == 'released'
                                        for row in completion['writer_completion']['resource_releases']))
                    capacity = result['capacity_session']
                    self.assertEqual(capacity['status'], 'released')
                    self.assertFalse(_lease_path(Path(capacity['artifact_root']), capacity['lease_id']).exists())
                unit_closed = True
            finally:
                if unit_closed:
                    shutil.rmtree(unit_root)
                else:
                    print('RETAINED_SFI_UNIT_RECOVERY_FIXTURE', unit_root, flush=True)


if __name__ == '__main__':
    unittest.main()
