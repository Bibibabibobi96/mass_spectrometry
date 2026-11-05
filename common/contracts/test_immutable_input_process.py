"""Real OS input guards across the existing GATE process owner's failure drain."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from msplatform.execution.context import ExecutionContext
from msplatform.execution.manifest_records import file_record
from msplatform.execution.processes import ProcessExecutionError, run_observed_process
from msplatform.execution.resources import resource_path


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows PowerShell required')
class ImmutableInputProcessTests(unittest.TestCase):
    def _case(self, root, *, owner=None):
        state = os.environ.get('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH')
        self.assertTrue(state, 'Use the normal public GATE')
        context = ExecutionContext(workspace=root, python_executable=Path(sys.executable),
            powershell_executable=Path(shutil.which('pwsh')), tools={}, host_state_path=Path(state),
            policy_path=resource_path('host_resource_policy.json'))
        source = root/'immutable data.bin'
        source.write_bytes(b'original immutable input')
        record = file_record(source, 'solver_native_binary')
        result = root/'child.json'
        code = '''import json,sys,time
from pathlib import Path
p=Path(sys.argv[1]);result=Path(sys.argv[2]);blocked=[]
for action in (lambda:p.write_bytes(b'CORRUPT'),lambda:p.unlink()):
 try: action();blocked.append(False)
 except PermissionError: blocked.append(True)
time.sleep(1)
result.write_text(json.dumps(blocked));print('ACTUAL_CHILD_EXIT',flush=True)
'''
        kwargs = dict(executable=Path(sys.executable), arguments=['-I','-c',code,str(source),str(result)],
            working_directory=root, run_directory=root, stdout_path=root/'out.log', stderr_path=root/'err.log',
            usage_path=root/'usage.json', role='GATE', stage='unclassified', run_id='immutable-input-software',
            limits=None, immutable_input_records=[record])
        return context, source, result, kwargs

    def _owner_copy(self, root, insertion='', resource_edit=None):
        folder = root/'owner'
        folder.mkdir()
        for name in ('process_owner.ps1','resource_process_support.ps1','host_execution_lease.ps1','payload_file_support.ps1'):
            text = resource_path(name).read_text(encoding='utf-8')
            if name == 'process_owner.ps1':
                marker = ". (Join-Path $PSScriptRoot 'resource_process_support.ps1')"
                self.assertEqual(text.count(marker), 1)
                text = text.replace(marker, marker+'\n'+insertion)
            if name == 'resource_process_support.ps1' and resource_edit:
                text = resource_edit(text)
            (folder/name).write_text(text, encoding='utf-8', newline='\n')
        return folder/'process_owner.ps1'

    def test_actual_guard_denies_write_delete_then_releases_after_exit_and_invalid_launches_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context, source, result, kwargs = self._case(root)
            receipt = run_observed_process(context, **kwargs)
            self.assertEqual(json.loads(result.read_text()), [True, True])
            self.assertEqual(source.read_bytes(), b'original immutable input')
            self.assertEqual(receipt['observation']['exit_code'], 0)
            self.assertTrue(receipt['host_release']['inherited'])
            source.write_bytes(b'released')
            source.unlink()
            for broken in ({**kwargs['immutable_input_records'][0], 'bytes':True},
                           {**kwargs['immutable_input_records'][0], 'sha256':'bad'}):
                with self.subTest(broken=broken), patch('msplatform.execution.processes.subprocess.Popen') as launch:
                    with self.assertRaisesRegex(ValueError, 'immutable inputs'):
                        run_observed_process(context, **dict(kwargs, immutable_input_records=[broken]))
                    launch.assert_not_called()

    def test_observation_and_wait_faults_preserve_primary_and_guard_through_natural_exit(self):
        for fault in ('observation','wait'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                context, source, result, kwargs = self._case(root)
                insertion = ''
                edit = None
                if fault == 'observation':
                    insertion = "function Update-RepositoryProcessObservation {throw 'ORIGINAL_OBSERVATION_FAULT'}"
                else:
                    insertion = "function Update-RepositoryProcessObservation {throw 'ORIGINAL_OBSERVATION_FAULT'}"
                    def edit(text):
                        marker = '$process.WaitForExit();$rootExitConfirmed=$process.HasExited'
                        self.assertGreaterEqual(text.count(marker), 2)
                        finalizer = text.index('# Observation failure must not return the caller')
                        wait = text.index(marker,finalizer)
                        return text[:wait]+"throw 'WAIT_SECONDARY_FAULT'\n        "+text[wait:]
                owner = self._owner_copy(root, insertion, edit)
                real_resource = resource_path
                with patch('msplatform.execution.processes.resource_path',
                           side_effect=lambda name:owner if name == 'process_owner.ps1' else real_resource(name)):
                    with self.assertRaisesRegex(ProcessExecutionError, 'ORIGINAL_.*_FAULT') as caught:
                        run_observed_process(context, **kwargs)
                self.assertTrue(caught.exception.observed_process_exit_confirmed)
                if fault == 'wait':
                    self.assertIn('observed_process_wait_error', caught.exception.receipt['error']['data'])
                self.assertEqual(json.loads(result.read_text()), [True, True])
                self.assertEqual(source.read_bytes(), b'original immutable input')
                source.unlink()

    def test_unknown_family_keeps_holder_and_guard_alive_until_known_empty_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context, source, result, kwargs = self._case(root)
            events = root/'unknown-events.txt'
            # Actual sampler/child remain real. Only two post-exit observations
            # are made unknown; neither may unwind the process/guard owner.
            insertion = r'''
$script:ActualImmutableSample=${function:Get-ManagedSolverProcessSample}
$script:UnknownSamples=0
function Get-ManagedSolverProcessSample {
 param($RootProcessIds,$TrackedProcessIds,$RootProcessStartedAtUtcTicks,$TrackedProcessStartedAtUtcTicks)
 $sample=& $script:ActualImmutableSample @PSBoundParameters
 if(@($sample.active_process_ids).Count-eq0-and$script:UnknownSamples-lt2){
   $script:UnknownSamples++
   try{$s=[IO.File]::OpenWrite($env:INERT_GUARDED_INPUT);$s.Dispose();throw 'GUARD_DROPPED'}
   catch [IO.IOException]{[IO.File]::AppendAllText($env:INERT_UNKNOWN_EVENTS,"LOCKED_UNKNOWN`n")}
   $sample.ancestry_complete=$false
 }
 return $sample
}
'''
            owner = self._owner_copy(root, insertion)
            real_resource = resource_path
            with patch.dict(os.environ, INERT_GUARDED_INPUT=str(source), INERT_UNKNOWN_EVENTS=str(events)), patch(
                    'msplatform.execution.processes.resource_path',
                    side_effect=lambda name:owner if name == 'process_owner.ps1' else real_resource(name)):
                receipt = run_observed_process(context, **kwargs)
            self.assertEqual(events.read_text().splitlines(), ['LOCKED_UNKNOWN','LOCKED_UNKNOWN'])
            self.assertEqual(receipt['observation']['exit_code'], 0)
            self.assertEqual(json.loads(result.read_text()), [True, True])
            source.unlink()

    def test_known_child_outlives_root_without_losing_input_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context, source, result, kwargs = self._case(root)
            child = root/'child.py'
            child.write_text('''import sys,time,json
from pathlib import Path
time.sleep(2)
p=Path(sys.argv[1]);blocked=False
try:p.write_bytes(b'CORRUPT')
except PermissionError:blocked=True
Path(sys.argv[2]).write_text(json.dumps(blocked))
''', encoding='utf-8')
            code = 'import subprocess,sys,time;subprocess.Popen([sys.executable,"-I",sys.argv[1],sys.argv[2],sys.argv[3]]);time.sleep(1)'
            receipt = run_observed_process(context, **dict(kwargs,
                arguments=['-I','-c',code,str(child),str(source),str(result)]))
            self.assertIs(json.loads(result.read_text()), True)
            self.assertEqual(receipt['observation']['exit_code'], 0)
            self.assertEqual(source.read_bytes(), b'original immutable input')
            source.unlink()

    def test_large_unbuffered_guard_and_wrong_hash_fail_before_child_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context, source, result, kwargs = self._case(root)
            source.write_bytes(b'INERT_NOT_PA' + b'x'*(8*1024*1024))
            record = file_record(source, 'solver_native_binary')
            with self.assertRaisesRegex(ProcessExecutionError, 'SHA256 differs'):
                run_observed_process(context, **dict(kwargs, immutable_input_records=[dict(record, sha256='F'*64)]))
            self.assertFalse(result.exists())
            receipt = run_observed_process(context, **dict(kwargs, immutable_input_records=[record]))
            self.assertEqual(receipt['observation']['exit_code'], 0)
            self.assertEqual(json.loads(result.read_text()), [True, True])
            self.assertEqual(file_record(source, 'solver_native_binary'), record)
            source.unlink()
