"""Neutral sampled whole-unit recovery with actual owner and inert leaves only."""

import json
import os
import subprocess
from pathlib import Path
import shutil
import sys
import threading
import time
import unittest
from unittest.mock import patch

from tests.contracts import test_generic_scalar_derived_tracking_managed as fixture
from tests.contracts.test_support.grouped_tracking_fixture import grouped_inert_transport
from msplatform.backends.simion import operations
from msplatform.execution.capacity_protection import load_capacity_protection_leases, path_is_protected
from msplatform.execution.resources import resource_path
from msplatform.execution.run_session import RunSession
from msplatform.io.manifest_records import file_record
from msplatform.results.artifacts import open_artifact


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows PowerShell required')
class NeutralSampledRecoveryTests(unittest.TestCase):
    def test_public_partial_recovery_and_original_source_tamper(self):
        case = fixture.GenericScalarTrackingManagedTests(methodName='runTest')
        self.addCleanup(case.doCleanups)
        case._exercise(True, self._recovery)

    def test_fresh_process_explicit_provider_registration_and_recovery(self):
        case = fixture.GenericScalarTrackingManagedTests(methodName='runTest')
        self.addCleanup(case.doCleanups)
        case._exercise(True, self._cold_recovery)

    def _cold_recovery(self, field, packet, propagation, numerics, context, refs, expected_paths, inert, actual_single, directory):
        del inert, actual_single
        transport = Path(directory) / 'cold_recovery_input.json'
        names = ('workspace', 'python_executable', 'powershell_executable', 'host_state_path',
                 'policy_path', 'execution_root', 'capacity_policy_path', 'stage_policy_path')
        context_data = {name: str(getattr(context, name)) for name in names}
        context_data['tools'] = {name: str(path) for name, path in context.tools.items()}
        payload = dict(field=field.reference, packet=packet, propagation=propagation, numerics=numerics,
                       context=context_data, refs=refs, expected_paths=sorted(expected_paths), directory=directory)
        transport.write_text(json.dumps(payload, allow_nan=False), encoding='utf8')
        repo = Path(__file__).resolve().parents[2]
        script = ("import sys;sys.path[:0]=" + repr([str(repo / 'src'), str(repo)]) + ";"
                  "from tests.contracts.test_generic_scalar_tracking_recovery import cold_recovery_child;"
                  "cold_recovery_child(sys.argv[1],sys.argv[2])")
        process = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(transport), str(repo)],
                                 cwd=directory, capture_output=True, text=True, encoding='utf8', timeout=600)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn('COLD_REGISTERED_RECOVERY=PASS', process.stdout)

    def _recovery(self, field, packet, propagation, numerics, context, refs, expected_paths, inert, actual_single, directory):
        root = Path(directory)
        copied = root / 'recovery_ps'
        copied.mkdir()
        for name in ('batch_process_owner.ps1', 'simion_dispatch_support.ps1', 'resource_process_support.ps1', 'host_execution_lease.ps1', 'payload_file_support.ps1'):
            text = resource_path(name).read_text(encoding='utf8')
            if name == 'batch_process_owner.ps1':
                marker = ". (Join-Path $PSScriptRoot 'simion_dispatch_support.ps1')"
                self.assertIn(marker, text)
                text = text.replace(marker, marker + "\nfunction Assert-HostResourceHeavyStage {}\nfunction Get-SystemCpuPercent {return 0}\n")
            (copied / name).write_text(text, encoding='utf8', newline='\n')
        actual_group = RunSession.run_process_group
        from msplatform.execution.simion_dispatch import plan_simion_dispatch as actual_dispatch
        calls = []
        fail = [True]
        checks = []
        selected_source_paths = {}
        gate = {}
        def check(session, records):
            view = load_capacity_protection_leases(context.workspace / 'artifacts')
            for ref in refs:
                self.assertTrue(path_is_protected(Path(ref['manifest']['path']), view['protected_paths']))
            actual = {str(Path(row['path']).resolve()) for row in records}
            self.assertTrue(expected_paths <= actual)
            self.assertTrue(globals().get('COLD_PROVIDER_PATHS', set()) <= actual)
            from msplatform.backends.simion import generic_geometry, mr_geometry
            from msplatform.components import cad_geometry
            for module in (generic_geometry, mr_geometry, cad_geometry):
                self.assertIn(selected_source_paths.get(module.__name__, str(Path(module.__file__).resolve())), actual)
                copy_name = module.__name__.replace('.', '_') + '.py'
                self.assertTrue(any(Path(path).name == copy_name and 'native_sources' in Path(path).parts for path in actual))

            checks.append(len(refs))
        def single(session, operation_id, *, immutable_input_records=(), **kwargs):
            if '__unit_' not in operation_id:
                return inert(session, operation_id, immutable_input_records=immutable_input_records, **kwargs)
            calls.append((session.run_id, operation_id))
            check(session, immutable_input_records)
            unit = operation_id.split('__')[-1]
            output = session.run_dir / 'units' / unit / 'simion/tracking/instrument.iob'
            build = operation_id.startswith('build_tracking_iob')
            marker = 'NEUTRAL_SAMPLED_TRACKING_IOB=PASS' if build else 'NEUTRAL_SAMPLED_TRACKING_IOB_REOPEN=PASS'
            code = 'from pathlib import Path\n'
            if build:
                code += f'p=Path({str(output)!r});p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INERT")\n'
            code += f'print({marker!r})\n'
            return actual_single(session, operation_id, executable=Path(sys.executable),
                arguments=['-I','-B','-c',code], role='GATE', stage='inert_model',
                limits=kwargs['limits'], immutable_input_records=immutable_input_records)
        def payload(session, name, argv, *, partial_log=False):
            unit = int(name.split('_')[-1])
            row = json.loads((session.input_dir / 'canonical_source_states.json').read_text(encoding='utf8'))[unit-1]
            code = 'import json,sys,time\nfrom pathlib import Path\n'
            code += f'Path({str(gate["ready"])!r}).write_text("ready")\n'
            code += f'while not Path({str(gate["release"])!r}).exists(): time.sleep(.05)\n'
            from tests.contracts.test_support.terminal_evidence_fixture import native_run_from_program, inert_wire_source
            program=session.run_dir/'units'/name.split('__')[-1]/'simion/tracking/instrument.lua'
            code += inert_wire_source()+'native_run='+repr(native_run_from_program(program))+'\n'
            code += 'r=' + repr(row) + '\n'
            code += 'print(\'RF_DYNAMICS_V1: {"grouped":1,"repulsion":"none","relativity":0,"segment_global":1}\')\n'
            code += 's=dict(event="source_release",reason="none",particle_id=r["particle_id"],ion=1,instrument_time_us=r["instrument_time_us"],mass_amu=r["mass_amu"],charge_state=r["charge_state"],instance=1);s.update({a+"_mm":r["position_"+a+"_mm"] for a in "xyz"});s.update({"v"+a+"_mm_per_us":r["velocity_"+a+"_m_s"]/1000 for a in "xyz"});print("RF_NATIVE_STATE_V1: "+json.dumps(s));s.update(event="terminal",reason="unknown",instrument_time_us=2.);print("RF_NATIVE_STATE_V1: "+json.dumps(s))\n'
            code += 'print("\\n".join(terminal_wire_lines(r,1,native_run,2.,1)))\n'
            code += 'sys.exit(7)\n' if partial_log else 'print("status,Fly completed. 1 splats")\n'
            return ['-I','-B','-c',code]
        grouped = grouped_inert_transport(actual_group, payload, calls, is_failed=lambda _: fail[0],
                                          sort_failed=lambda row: row['scheduler_batch']['index'])
        def group(session, specs, *, immutable_input_records=(), **kwargs):
            gate.update(ready=root / ('ready_' + str(len(checks))),
                        release=root / ('release_' + str(len(checks))))
            result, errors = [], []
            def worker():
                try:
                    result.append(grouped(session, specs, immutable_input_records=immutable_input_records, **kwargs))
                except BaseException as exc:
                    errors.append(exc)
            thread = threading.Thread(target=worker)
            thread.start()
            try:
                deadline = time.monotonic() + 30
                while not gate['ready'].exists() and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue(gate['ready'].exists(), 'inert grouped child did not reach pause')
                check(session, immutable_input_records)
            finally:
                gate['release'].write_text('release', encoding='utf8')
                thread.join(30)
            if thread.is_alive():
                raise RuntimeError('inert grouped child did not exit')
            if errors:
                raise errors[0]
            return result[0]
        def dispatch(*args, **kwargs):
            value = actual_dispatch(*args, **kwargs)
            value['estimation'] = dict(kind='exact_resource_profile', per_process_memory_budget_bytes=1024**2,
                                       per_process_cpu_percent=1., observed_batch_work_units=1)
            value['limits'].update(maximum_concurrency=1, launch_stagger_seconds=1)
            return value
        real_resource = resource_path
        run_root = context.workspace / 'artifacts/projects/instrument_assembly/runs'
        before = set(run_root.iterdir())
        def track(recovery=None):
            return operations.track(field, packet, propagation=propagation, observations=dict(plane_observations=[]),
                                    numerics=numerics, context=context, unit_size=1, recovery_reference=recovery)
        with patch.object(RunSession, 'run_process', new=single), patch.object(RunSession, 'run_process_group', new=group), \
             patch('msplatform.execution.simion_dispatch.plan_simion_dispatch', side_effect=dispatch), \
             patch('msplatform.execution.processes.resource_path', side_effect=lambda name: copied/name if name == 'batch_process_owner.ps1' else real_resource(name)):
            with self.assertRaisesRegex(Exception, "batch wave failed"):
                track()
            created = set(run_root.iterdir()) - before
            self.assertEqual(len(created), 1)
            failed = created.pop()
            index = json.loads((failed / 'logs/tracking_units.json').read_text(encoding='utf8'))
            self.assertEqual([row['complete'] for row in index['units']], [True, False])
            predecessor = file_record(failed / 'run_manifest.json', 'required_evidence')
            original = open_artifact(refs[-1], expected_kind='scalar_field_samples')
            target = original.data_path('field_valid')
            saved = target.read_bytes()
            try:
                target.write_bytes(saved + b'tamper')
                prior = len(calls)
                with self.assertRaises((AssertionError, ValueError)):
                    track(predecessor)
                self.assertEqual(len(calls), prior)
            finally:
                target.write_bytes(saved)
            # Select the same real-byte copy for both recovery attempts; only its bytes change.
            from msplatform.backends.simion import neutral_sampled_field
            from msplatform.components import cad_geometry
            source_paths = neutral_sampled_field.neutral_source_paths
            source_name = 'msplatform.components.cad_geometry'
            selected = root / 'selected_cad_geometry.py'
            original_bytes = Path(cad_geometry.__file__).read_bytes()
            selected.write_bytes(original_bytes)
            selected_source_paths[source_name] = str(selected.resolve())
            def selected_source(model):
                paths = source_paths(model)
                paths[source_name] = selected
                return paths
            fail[0] = False
            with patch.object(neutral_sampled_field, 'neutral_source_paths', side_effect=selected_source):
                prior = len(calls)
                result = track(predecessor)
                names = [name for _, name in calls[prior:]]
                self.assertEqual([n.split('__')[0] for n in names], ['build_tracking_iob','verify_tracking_iob','track_fly'])
                self.assertTrue(all(n.endswith('unit_0002') for n in names))
                selected.write_bytes(original_bytes + b'\n# changed source\n')
                prior = len(calls)
                with self.assertRaisesRegex(ValueError, 'tracking predecessor scientific applicability or partition differs'):
                    track(predecessor)
                self.assertEqual(len(calls), prior)
            collection = json.loads(result.data_path('collection').read_text(encoding='utf8'))
            self.assertEqual([row['particle_id'] for row in collection['native_terminals']], [7,91])
            self.assertEqual(collection['original_mother']['mother_records'], list(packet['mother']['records'].values()))
            self.assertEqual(collection['clock_epoch_id'], packet['clock']['clock_epoch_id'])
            self.assertTrue(checks and all(value == len(refs) for value in checks))
        self.assertEqual(load_capacity_protection_leases(context.workspace / 'artifacts')['audit'], [])


def cold_recovery_child(transport, repo):
    """Fresh interpreter: actual references and context cross only JSON wire."""
    from msplatform.contracts.machine_contracts import ContractError
    from msplatform.execution.context import ExecutionContext
    from msplatform.components.registry import project_descriptor
    import msplatform
    root = Path(repo).resolve()
    if not Path(msplatform.__file__).resolve().is_relative_to(root / 'src'):
        raise AssertionError('unexpected installed source origin')
    payload = json.loads(Path(transport).read_text(encoding='utf8'))
    context = ExecutionContext(**payload['context'])
    records = payload['packet']['mother']['records']
    restored = {int(key): value for key, value in records.items()}
    if len(restored) != len(records) or any(str(key) != original for key, original in zip(restored, records, strict=True)):
        raise ValueError('mother identifier JSON transport differs')
    payload['packet']['mother']['records'] = restored
    field = open_artifact(payload['field'], expected_kind='field_bundle')
    try:
        operations.track(field, payload['packet'], propagation=payload['propagation'],
                         observations=dict(plane_observations=[]), numerics=payload['numerics'],
                         context=context, unit_size=1)
    except ContractError as error:
        if str(error) not in {'unsupported component project: toy_registered',
                              'unsupported component project: toy_other'}:
            raise
    else:
        raise AssertionError('unregistered provider unexpectedly admitted')
    from tests.contracts.test_support import registered_component, generic_other_provider
    registered_component.ensure_registered()
    generic_other_provider.ensure_registered()
    from msplatform.execution.inputs import resolve_python_module_sources
    provider_paths = set()
    for project in ('toy_registered', 'toy_other'):
        descriptor = project_descriptor(project)
        if not descriptor.source_closure:
            raise AssertionError('provider source closure missing')
        provider_paths.update(str(path.resolve()) for path in resolve_python_module_sources(descriptor.source_closure).values())
    globals()['COLD_PROVIDER_PATHS'] = provider_paths
    def unexpected(*args, **kwargs):
        raise AssertionError('unexpected non-unit inert operation')
    case = NeutralSampledRecoveryTests(methodName='runTest')
    case._recovery(field, payload['packet'], payload['propagation'], payload['numerics'], context,
                   payload['refs'], set(payload['expected_paths']), unexpected, RunSession.run_process,
                   payload['directory'])
    print('COLD_REGISTERED_RECOVERY=PASS', flush=True)
