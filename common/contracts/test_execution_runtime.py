"""Execution configuration and installed scheduler contracts; no native tools."""
from pathlib import Path
from contextlib import closing
import os
import json
import sqlite3
import subprocess
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

from msplatform.execution.context import ExecutionContext
from msplatform.execution.resources import resource_path
from msplatform.execution import host_resource_scheduler
from msplatform.execution.recovery import WholeUnitReplayUnit
from msplatform.execution.processes import run_observed_process, ProcessExecutionError
from msplatform.execution import recovery as batch_continuation


class ExecutionRuntimeTests(unittest.TestCase):
    def test_primary_admission_and_native_failure_survive_release_and_close_secondary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = Path(os.environ.get('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH', str(root/'state')))
            context = ExecutionContext(workspace=root, python_executable=Path(sys.executable),
                powershell_executable=root/'not-started-pwsh.exe', tools={}, host_state_path=state,
                policy_path=root/'not-read-policy.json')
            observation = dict(exit_code=7, root_process_id=123, root_process_started_at_utc_ticks=456)
            cases = [
                (dict(observation=None, error=dict(type='ValueError', message='ORIGINAL_ADMISSION_FAILURE',
                    data={'observed_process_exit_confirmed': False}), host_release=None), 'ORIGINAL_ADMISSION_FAILURE', False),
                (dict(observation=observation, error=None, host_release=dict(inherited=False, token='owner',
                    result=dict(status='acquired', token='owner'), error='release-secondary')), 'Observed process failed with exit 7', True),
            ]
            for receipt, expected, exited in cases:
                with self.subTest(primary=expected):
                    child = Mock(returncode=1)
                    child.communicate.return_value = (
                        ('EXECUTION_PROCESS_RESULT='+json.dumps(receipt)).encode('utf-8'), b'raw-owner-stderr')
                    child.stdout.close.side_effect = OSError('CLOSE_SECONDARY')
                    with patch('msplatform.execution.processes.subprocess.Popen', return_value=child):
                        with self.assertRaises(ProcessExecutionError) as caught:
                            run_observed_process(context, executable=root/'not-started-tool', arguments=['-V'],
                                working_directory=root, run_directory=root, stdout_path=root/'out', stderr_path=root/'err',
                                usage_path=root/'usage', role='GATE', stage='fixture', run_id='not-started', limits=None)
                    self.assertEqual(str(caught.exception), expected)
                    self.assertEqual(caught.exception.observed_process_exit_confirmed, exited)
                    self.assertTrue(any('host release secondary' in note for note in caught.exception.__notes__))
                    self.assertTrue(any('CLOSE_SECONDARY' in note for note in caught.exception.__notes__))
                    child.kill.assert_not_called()

    def test_context_is_explicit_immutable_configuration_without_directory_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools = {"simion": root / "unprobed-simion.exe"}
            context = ExecutionContext(workspace=root / "not-created",
                python_executable=root / "unprobed-python.exe",
                powershell_executable=root / "unprobed-pwsh.exe", tools=tools,
                host_state_path=root / "shared-state.sqlite3", policy_path=root / "explicit-policy.json")
            tools["simion"] = root / "changed.exe"
            self.assertEqual(context.tools["simion"], root / "unprobed-simion.exe")
            self.assertFalse(context.workspace.exists())
            self.assertFalse(context.host_state_path.exists())
            with self.assertRaises(TypeError):
                context.tools["simion"] = root / "mutated.exe"
            with self.assertRaisesRegex(ValueError, "workspace must be absolute"):
                ExecutionContext(workspace=Path("relative"),
                    python_executable=context.python_executable,
                    powershell_executable=context.powershell_executable, tools={},
                    host_state_path=context.host_state_path, policy_path=context.policy_path)

    def test_inherited_token_has_one_explicit_state_owner_and_required_boundary(self):
        from msplatform.execution.processes import inherited_host_token
        context = Mock(host_state_path=Path.cwd() / "explicit-state.sqlite3")
        with patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN": "",
                                   "MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH": ""}):
            self.assertFalse(inherited_host_token(context))
            with self.assertRaisesRegex(ValueError, "actual inherited host lease"):
                inherited_host_token(context, required=True)
        for state in ("", str(Path.cwd() / "different-state.sqlite3")):
            with self.subTest(state=state), patch.dict(os.environ, {
                "MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN": "actual-owner-token",
                "MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH": state}):
                with self.assertRaisesRegex(ValueError, "inherited lease owner"):
                    inherited_host_token(context, required=True)
        with patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN": "actual-owner-token",
                                   "MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH": str(context.host_state_path)}):
            self.assertEqual(inherited_host_token(context, required=True), "actual-owner-token")

    def test_raw_byte_locks_preserve_os_errors_and_cache_seek_failure(self):
        from msplatform.execution import file_lock
        from msplatform.backends.simion import pa_family_cache
        handle = Mock()
        for platform, module_name, error_type in (("nt", "msvcrt", OSError), ("posix", "fcntl", BlockingIOError)):
            module = Mock(LK_NBLCK=1, LK_UNLCK=2, LOCK_EX=1, LOCK_NB=2, LOCK_UN=4)
            error = error_type("original OS lock failure")
            module.locking.side_effect = error
            module.flock.side_effect = error
            with self.subTest(platform=platform), patch.object(file_lock.os, "name", platform), patch.dict(sys.modules, {module_name: module}):
                for function in (file_lock.acquire_exclusive_byte_lock, file_lock.release_exclusive_byte_lock):
                    with self.assertRaises(error_type) as caught:
                        function(handle)
                    self.assertIs(caught.exception, error)
        with patch.object(pa_family_cache, "acquire_exclusive_byte_lock", side_effect=OSError("busy")):
            self.assertFalse(pa_family_cache._PAFamilyCacheKeyLock._try_lock(handle))
        handle.seek.side_effect = OSError("seek primary")
        with self.assertRaisesRegex(OSError, "seek primary"):
            pa_family_cache._PAFamilyCacheKeyLock._try_lock(handle)

    def test_installed_host_requires_policy_before_any_state_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-created.sqlite3"
            with self.assertRaisesRegex(ValueError, "explicit policy"):
                host_resource_scheduler.transact(path, {}, {})
            self.assertFalse(path.exists())

    def test_legacy_whole_unit_symbol_has_one_installed_owner(self):
        self.assertIs(batch_continuation.WholeUnitReplayUnit, WholeUnitReplayUnit)
        self.assertEqual(WholeUnitReplayUnit.__module__, "msplatform.execution.recovery")


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'Windows PowerShell execution required')
class ObservedExecutionTests(unittest.TestCase):
    def test_shared_terminal_guard_interoperates_with_legacy_reader_and_excludes_publisher(self):
        from msplatform.execution.file_lock import shared_process_file_lock, process_file_lock
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lock = root / ".run_terminal_publication.lock"
            repository = Path(__file__).resolve().parents[2]
            with shared_process_file_lock(lock, timeout_seconds=0):
                with shared_process_file_lock(lock, timeout_seconds=0):
                    with self.assertRaises(TimeoutError):
                        with process_file_lock(lock, timeout_seconds=0):
                            self.fail("Publisher entered a live shared terminal guard")
                script = ". '" + str(repository / "common/contracts/run_artifact_support.ps1").replace("'", "''") + "'; "
                script += "$g=Enter-RunTerminalConsumptionGuard -RunDirectory '" + str(root).replace("'", "''") + "' -TimeoutSeconds 1;try{'SHARED_READER_OK'}finally{$g.Dispose()}"
                result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command", script],
                    cwd=root, capture_output=True, encoding="utf-8", timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("SHARED_READER_OK", result.stdout)
                self.assertEqual(lock.stat().st_size, 0)
            with process_file_lock(lock, timeout_seconds=0):
                self.assertEqual(lock.stat().st_size, 1)

    def test_frozen_host_adapter_dot_sources_without_python_or_virtualenv(self):
        with tempfile.TemporaryDirectory(prefix='frozen host source ') as directory:
            root = Path(directory)
            repository = Path(__file__).resolve().parents[2]
            bridge = root/'common/host_execution_lease.ps1'
            bridge.parent.mkdir()
            shutil.copyfile(repository/'common/host_execution_lease.ps1', bridge)
            canonical = root/'src/msplatform/execution/resources/host_execution_lease.ps1'
            canonical.parent.mkdir(parents=True)
            shutil.copyfile(resource_path('host_execution_lease.ps1'), canonical)
            environment = dict(os.environ)
            environment.pop('SIMULATION_PYTHON_EXE', None)
            command = ". '"+str(bridge).replace("'", "''")+"'; Get-Command Enter-HostExecutionLease | Select-Object -ExpandProperty Name"
            result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-NonInteractive', '-Command', command],
                cwd=root, env=environment, capture_output=True, encoding='utf-8', timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('Enter-HostExecutionLease', result.stdout)
            self.assertFalse((root/'.venv').exists())
            canonical.unlink()
            missing = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-NonInteractive', '-Command', command],
                cwd=root, env=environment, capture_output=True, encoding='utf-8', timeout=15)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn('Frozen execution host resource is unavailable', missing.stderr)

    def test_legacy_dynamic_private_state_never_touches_context_default_database(self):
        with tempfile.TemporaryDirectory(prefix='execution-state-isolation-') as directory:
            root = Path(directory)
            outer, private = root/'context-default.sqlite3', root/'private.sqlite3'
            with closing(sqlite3.connect(outer)) as db, db:
                db.execute('CREATE TABLE sentinel (value TEXT)')
                db.execute('INSERT INTO sentinel VALUES (?)', ('must-remain-byte-identical',))
            before = outer.read_bytes()
            repository = Path(__file__).resolve().parents[2]
            quote = lambda value: "'"+str(value).replace("'", "''")+"'"
            script = f"""
$ErrorActionPreference='Stop'
. {quote(repository/'common/host_execution_lease.ps1')}
$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH={quote(private)}
function Get-HostResourceSnapshot {{
 return @{{complete=$true;logical_processors=4;cpu_percent=100;total_memory_bytes=32GB;
 available_memory_bytes=24GB;io_pressure=$false;processes=@(@{{pid=$PID;parent_pid=0;
 started=(Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks.ToString('D19');memory_bytes=32MB}})}}
}}
$lease=Enter-HostResourceStage -Role GATE -Stage fixture -Budget (Get-HostResourceBudget -Profile measured-small-check)
try {{if($lease.state_path-cne{quote(private)}){{throw 'private state was not selected'}}}}
finally {{Exit-HostResourceStage -Lease $lease}}
Write-Output 'PRIVATE_STATE_ISOLATED'
"""
            environment = dict(os.environ, SIMULATION_PYTHON_EXE=sys.executable,
                MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(outer))
            environment.pop('MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN', None)
            result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-NonInteractive', '-Command', script],
                cwd=repository, env=environment, capture_output=True, encoding='utf-8', errors='replace', timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('PRIVATE_STATE_ISOLATED', result.stdout)
            self.assertEqual(outer.read_bytes(), before)
            with closing(sqlite3.connect(private)) as db:
                document = json.loads(db.execute('SELECT document FROM state WHERE id=1').fetchone()[0])
            self.assertEqual(document['records'], [])
            context = ExecutionContext(workspace=root, python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={}, host_state_path=private,
                policy_path=resource_path('host_resource_policy.json'))
            with patch.dict(os.environ, {'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN': 'inherited-explicit-owner',
                    'MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH': str(outer)}), \
                    patch('msplatform.execution.processes.subprocess.Popen') as launched:
                with self.assertRaisesRegex(ValueError, 'differs from the inherited lease owner'):
                    run_observed_process(context, executable=Path(sys.executable), arguments=['-V'],
                        working_directory=root, run_directory=root, stdout_path=root/'out', stderr_path=root/'err',
                        usage_path=root/'usage', role='GATE', stage='fixture', run_id='not-started', limits=None)
                launched.assert_not_called()
            self.assertEqual(outer.read_bytes(), before)

    def test_live_start_identity_is_published_before_child_exit(self):
        self._assert_live_start_identity(None)

    def test_budgeted_usage_retains_same_start_identity_after_final_sample(self):
        self._assert_live_start_identity(dict(wall_clock_seconds=30,transient_run_directory_bytes=16*1024*1024,
            process_tree_working_set_bytes=512*1024*1024,minimum_system_available_memory_bytes=1024*1024*1024,
            compact_final_retained_bytes=16*1024*1024,automatic_retry_count=0))

    def _assert_live_start_identity(self, limits):
        with tempfile.TemporaryDirectory(prefix='early-identity-software-') as directory:
            root = Path(directory)
            state = os.environ.get('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH')
            self.assertTrue(state,'Run under public GATE')
            context = ExecutionContext(workspace=root,python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')),tools={},host_state_path=Path(state),
                policy_path=resource_path('host_resource_policy.json'))
            usage = root/'usage.json'
            code = ("import json,os,time;from pathlib import Path;p=Path("+repr(str(usage))+");deadline=time.monotonic()+5\n"
                    "while not p.exists() and time.monotonic()<deadline:time.sleep(.02)\n"
                    "assert p.exists(),'LIVE_START_IDENTITY_MISSING'\n"
                    "value=json.loads(p.read_text(encoding='utf-8-sig'));start=value['process_start']\n"
                    "assert start['root_process_id']==os.getpid(),start\n"
                    "print(json.dumps(start),flush=True)\n")
            try:
                receipt = run_observed_process(context,executable=Path(sys._base_executable),arguments=['-I','-c',code],
                    working_directory=root,run_directory=root,stdout_path=root/'out.log',stderr_path=root/'err.log',
                    usage_path=usage,role='GATE',stage='early_identity_software',run_id='early-identity-real-child',limits=limits)
            except ProcessExecutionError as error:
                error.add_note('ACTUAL_CHILD_STDERR='+ (root/'err.log').read_text(encoding='utf-8'))
                raise
            start = json.loads((root/'out.log').read_text(encoding='utf-8'))
            self.assertEqual(start['root_process_id'],receipt['observation']['root_process_id'])
            self.assertEqual(start['root_process_started_at_utc_ticks'],receipt['observation']['root_process_started_at_utc_ticks'])
            self.assertEqual(start['identity_status'],'known')
            self.assertEqual(start['requested_executable'],str(Path(sys._base_executable)))
            self.assertEqual(start['requested_window_style'],'Hidden')
            self.assertEqual(start['operation'],dict(run_id='early-identity-real-child',role='GATE',stage='early_identity_software'))
            self.assertEqual(start['usage_path'],str(usage))
            self.assertTrue(start['observed_at_utc'])
            self.assertIn(start['actual_image_status'],('known','unknown'))
            if start['actual_image_status']=='known':self.assertTrue(Path(start['actual_image_path']).is_absolute())
            else:self.assertIsNone(start['actual_image_path'])
            self.assertEqual(receipt['observation']['exit_code'],0)
            self.assertTrue(receipt['host_release']['inherited'])
            persisted = json.loads(usage.read_text(encoding='utf-8-sig'))
            self.assertEqual(persisted['process_start'],start)
            if limits is None:self.assertEqual(persisted['budget_observation'],'not_requested')
            else:self.assertEqual(persisted['limits'],limits)

    def _start_identity_test_context(self, root, replacements=()):
        state = os.environ.get('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH')
        self.assertTrue(state,'Run under public GATE')
        context = ExecutionContext(workspace=root,python_executable=Path(sys.executable),
            powershell_executable=Path(shutil.which('pwsh')),tools={},host_state_path=Path(state),
            policy_path=resource_path('host_resource_policy.json'))
        resources = root/'resources'
        resources.mkdir()
        for path in resource_path('process_owner.ps1').parent.glob('*.ps1'):
            shutil.copyfile(path,resources/path.name)
        source = (resources/'resource_process_support.ps1').read_text(encoding='utf-8')
        for before,after in replacements:
            self.assertEqual(source.count(before),1)
            source = source.replace(before,after)
        (resources/'resource_process_support.ps1').write_text(source,encoding='utf-8',newline='\n')
        return context,resources/'process_owner.ps1'

    def test_start_snapshot_failure_preserves_primary_and_drains_real_guarded_child(self):
        from msplatform.execution.manifest_records import file_record
        identity_anchor = 'try{$rootProcessStartedAtUtcTicks=[int64]$process.StartTime.ToUniversalTime().Ticks}'
        write_anchor = '$usage.process_start=$facts\n  Write-ResourceUsage -Usage $usage -Path $Observation.usage_path'
        for identity_failure,write_failure in ((False,True),(True,False),(True,True)):
            with self.subTest(identity_failure=identity_failure,write_failure=write_failure),tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                changes = []
                if identity_failure:changes.append((identity_anchor,"try{throw 'IDENTITY_PRIMARY'}"))
                if write_failure:changes.append((write_anchor,"throw 'SNAPSHOT_PUBLICATION_FAILURE'"))
                context,owner = self._start_identity_test_context(root,changes)
                payload = root/'guarded.bin';payload.write_bytes(b'UNCHANGED_IMMUTABLE')
                record = file_record(payload,'required_evidence')
                code = ('from pathlib import Path;import time;p=Path('+repr(str(payload))+');blocked=False\n'
                    'try:\n p.open("ab").close()\nexcept OSError:\n blocked=True\n'
                    'assert blocked,"GUARD_RELEASED_EARLY"\nprint("ACTUAL_GUARD_STILL_HELD",flush=True)\n'
                    'time.sleep(.1)\nprint("ACTUAL_CHILD_FINISHED",flush=True)')
                expected = 'IDENTITY_PRIMARY' if identity_failure else 'SNAPSHOT_PUBLICATION_FAILURE'
                with patch('msplatform.execution.processes.resource_path',return_value=owner):
                    with self.assertRaisesRegex(ProcessExecutionError,expected) as caught:
                        run_observed_process(context,executable=Path(sys._base_executable),arguments=['-I','-c',code],
                            working_directory=root,run_directory=root,stdout_path=root/'out',stderr_path=root/'err',usage_path=root/'usage.json',
                            role='GATE',stage='early_identity_software',run_id='start-failure-real-child',limits=None,
                            immutable_input_records=[record])
                error = caught.exception
                self.assertTrue(error.observed_process_exit_confirmed)
                self.assertEqual(error.observed_process_returncode,0)
                self.assertTrue(error.receipt['host_release']['inherited'])
                self.assertIsNone(error.receipt['host_release']['error'])
                self.assertIn('ACTUAL_GUARD_STILL_HELD',(root/'out').read_text())
                self.assertIn('ACTUAL_CHILD_FINISHED',(root/'out').read_text())
                if identity_failure and write_failure:
                    self.assertIn('SNAPSHOT_PUBLICATION_FAILURE',error.receipt['error']['data']['process_start_snapshot_error'])
                if identity_failure and not write_failure:
                    start = json.loads((root/'usage.json').read_text(encoding='utf-8-sig'))['process_start']
                    self.assertEqual(start['identity_status'],'unknown')
                    self.assertIsNone(start['root_process_started_at_utc_ticks'])
                    self.assertGreater(start['root_process_id'],0)
                with payload.open('ab') as stream:stream.write(b'')
                self.assertEqual(payload.read_bytes(),b'UNCHANGED_IMMUTABLE')

    def test_fast_exit_and_start_failure_do_not_fabricate_start_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory);context,_ = self._start_identity_test_context(root)
            parameters = dict(working_directory=root,run_directory=root,stdout_path=root/'out',stderr_path=root/'err',
                usage_path=root/'usage.json',role='GATE',stage='early_identity_software',run_id='fast-exit-real-child',limits=None)
            receipt = run_observed_process(context,executable=Path(sys._base_executable),arguments=['-I','-c','pass'],**parameters)
            start = json.loads((root/'usage.json').read_text(encoding='utf-8-sig'))['process_start']
            self.assertEqual(start['root_process_id'],receipt['observation']['root_process_id'])
            self.assertEqual(start['root_process_started_at_utc_ticks'],receipt['observation']['root_process_started_at_utc_ticks'])
            self.assertEqual(receipt['observation']['exit_code'],0)
            (root/'usage.json').unlink()
            with self.assertRaises(ProcessExecutionError) as caught:
                run_observed_process(context,executable=root/'absent-owned-tool.exe',arguments=['-V'],**parameters)
            self.assertFalse(caught.exception.observed_process_exit_confirmed)
            self.assertIsNone(caught.exception.receipt['observation'])
            self.assertFalse((root/'usage.json').exists())

    def test_start_observation_metadata_rejects_unsupported_shape_before_launch(self):
        source = resource_path('resource_process_support.ps1')
        script = r"""
function Assert-HostResourceHeavyStage {}
function Test-HostResourceConsoleProcess {param($ImagePath) return $false}
. $args[0]
$bad=@(@{},@{run_id='r';role='GATE';stage='s';extra='bad'},@{run_id='';role='GATE';stage='s'},
       @{run_id=1;role='GATE';stage='s'},@{run_id='r';role=$true;stage='s'})
$count=0
foreach($metadata in $bad){
  try{Assert-RepositoryProcessObservationMetadata -Metadata $metadata -UsagePath $args[1];throw 'INVALID_ACCEPTED'}
  catch{if($_.Exception.Message-eq'INVALID_ACCEPTED'){throw};$count++}
}
try{Assert-RepositoryProcessObservationMetadata -Metadata @{run_id='r';role='GATE';stage='s'} -UsagePath 'relative.json';throw 'INVALID_ACCEPTED'}
catch{if($_.Exception.Message-eq'INVALID_ACCEPTED'){throw};$count++}
Assert-RepositoryProcessObservationMetadata -Metadata $null -UsagePath ''
Write-Output "REJECTED=$count"
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'metadata.ps1';path.write_text(script,encoding='utf-8',newline='\n')
            result = subprocess.run([shutil.which('pwsh'),'-NoProfile','-File',str(path),str(source),str(Path(directory)/'usage.json')],
                capture_output=True,text=True,encoding='utf-8',timeout=30,cwd=directory)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('REJECTED=6',result.stdout)

    def test_window_style_reaches_real_start_process_and_keeps_immutable_drain(self):
        with tempfile.TemporaryDirectory(prefix='visible-launch-software-') as directory:
            root = Path(directory)
            state = os.environ.get('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH')
            self.assertTrue(state, 'Run under public GATE')
            context = ExecutionContext(workspace=root, python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={}, host_state_path=Path(state),
                policy_path=resource_path('host_resource_policy.json'))
            resources = root/'resources'
            resources.mkdir()
            # Private exact-body copy adds only an observation immediately at
            # Start-Process; no production fault hook or different launch path.
            source = resource_path('resource_process_support.ps1').read_text(encoding='utf-8-sig')
            needle = '$process=Start-Process @startArguments'
            self.assertEqual(source.count(needle), 1)
            captured = root/'actual-window-style.txt'
            instrumented = source.replace(needle,
                "[IO.File]::WriteAllText('"+str(captured).replace("'", "''")+"',[string]$startArguments.WindowStyle)\n  "+needle)
            for path in resource_path('process_owner.ps1').parent.glob('*.ps1'):
                shutil.copyfile(path, resources/path.name)
            (resources/'resource_process_support.ps1').write_text(instrumented, encoding='utf-8')
            payload = root/'guarded.bin'
            payload.write_bytes(b'ORIGINAL_IMMUTABLE')
            from msplatform.execution.manifest_records import file_record
            record = file_record(payload, 'required_evidence')
            parameters = dict(working_directory=root, run_directory=root, stdout_path=root/'out.log',
                stderr_path=root/'err.log', usage_path=root/'usage.json', role='GATE', stage='window_style_software',
                run_id='inert-window-style', limits=None, immutable_input_records=[record])
            code = ('from pathlib import Path;p=Path('+repr(str(payload))+');blocked=False\n'
                    'try:\n p.open("ab").close()\nexcept OSError:\n blocked=True\n'
                    'assert blocked,"immutable input was not guarded"\nprint("ACTUAL_GUARD_OK")')
            with patch('msplatform.execution.processes.resource_path', return_value=resources/'process_owner.ps1'):
                for options, expected in (({}, 'Hidden'), ({'window_style':'Normal'}, 'Normal')):
                    with self.subTest(expected=expected):
                        receipt = run_observed_process(context, executable=Path(sys.executable),
                            arguments=['-I','-c',code], **parameters, **options)
                        self.assertEqual(captured.read_text(), expected)
                        self.assertEqual(receipt['observation']['exit_code'], 0)
                        self.assertGreater(receipt['observation']['root_process_id'], 0)
                        self.assertGreater(receipt['observation']['root_process_started_at_utc_ticks'], 0)
                        self.assertTrue(receipt['host_release']['inherited'])
                        self.assertIsNone(receipt['host_release']['error'])
                        self.assertIn('ACTUAL_GUARD_OK', (root/'out.log').read_text())
                        with payload.open('ab') as stream:
                            stream.write(b'')  # Writable only after actual child drain/release.
                with patch('msplatform.execution.processes._invoke_process_owner') as launch:
                    for invalid in ('normal', 'Minimized', '', None, True, 1, []):
                        with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'window_style'):
                            run_observed_process(context, executable=Path(sys.executable), arguments=['-V'],
                                window_style=invalid, **parameters)
                    launch.assert_not_called()
            self.assertEqual(payload.read_bytes(), b'ORIGINAL_IMMUTABLE')

    def test_real_process_preserves_unicode_arguments_logs_failure_and_owner_facts(self):
        with tempfile.TemporaryDirectory(prefix='installed execution 空格 ') as directory:
            root = Path(directory)
            state = os.environ.get('MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH')
            self.assertTrue(state, 'Run this owner contract under the public GATE')
            context = ExecutionContext(workspace=root, python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={}, host_state_path=Path(state),
                policy_path=resource_path('host_resource_policy.json'))
            parameters = dict(working_directory=root, run_directory=root, stdout_path=root/'out.log',
                stderr_path=root/'err.log', usage_path=root/'usage.json', role='GATE',
                stage='unclassified', run_id='software-installed-execution', limits=None,
                environment={'PYTHONIOENCODING': 'utf-8'})
            receipt = run_observed_process(context, executable=Path(sys.executable),
                arguments=['-c', 'import sys;print(sys.argv[1]);print("raw-stderr",file=sys.stderr)', 'value 含 空格'],
                **parameters)
            self.assertEqual((root/'out.log').read_text(encoding='utf-8').strip(), 'value 含 空格')
            self.assertIn('raw-stderr', (root/'err.log').read_text(encoding='utf-8'))
            self.assertGreater(receipt['observation']['root_process_id'], 0)
            self.assertGreater(receipt['observation']['root_process_started_at_utc_ticks'], 0)
            self.assertEqual(receipt['observation']['exit_code'], 0)
            self.assertTrue(receipt['host_release']['inherited'])
            self.assertIsNone(receipt['host_release']['result'])
            with self.assertRaisesRegex(ProcessExecutionError, 'exit 7') as raised:
                run_observed_process(context, executable=Path(sys.executable),
                    arguments=['-c', 'import sys;print("original-failure",file=sys.stderr);sys.exit(7)'], **parameters)
            self.assertTrue(raised.exception.observed_process_exit_confirmed)
            self.assertEqual(raised.exception.observed_process_returncode, 7)
            self.assertIn('original-failure', (root/'err.log').read_text(encoding='utf-8'))
            with patch('msplatform.execution.processes.resource_path', side_effect=FileNotFoundError('required resource missing')), \
                 patch('msplatform.execution.processes.subprocess.Popen') as launch:
                with self.assertRaisesRegex(FileNotFoundError, 'required resource missing'):
                    run_observed_process(context, executable=Path(sys.executable), arguments=['-V'], **parameters)
                launch.assert_not_called()


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell execution required")
class NormalOwnerTests(unittest.TestCase):
    def _context(self, root):
        return ExecutionContext(workspace=root / "study with spaces", python_executable=Path(sys.executable),
            powershell_executable=Path(shutil.which("pwsh")), tools={}, host_state_path=root / "private-host.sqlite3",
            policy_path=resource_path("host_resource_policy.json"), execution_root=root / "aliases")

    def _arguments(self, root, action):
        from msplatform.execution.manifest_records import file_record
        budget = root / "budget.json"
        budget.write_text('{"bytes":1048576}', encoding="utf-8")
        return dict(descriptor=dict(project="instrument_assembly", mode="geometry", software=[]),
            run_id="20261104_120000__build__python__normal-owner", payload={"science_input": 13},
            committed_new_bytes=1048576, commitment_inputs=[file_record(budget, "required_evidence")],
            retention=dict(policy_version=1, **{"class": "compact"}, reason=None),
            expected_operation_ids=[], operation_dependencies={}, action=action,
            action_record=file_record(Path(__file__), "required_evidence"))

    def _policy(self):
        from msplatform.execution.capacity_admission import _capacity_policy
        return dict(_capacity_policy(), target_gib=1, minimum_free_gib=0)

    @staticmethod
    def _action(session):
        path = session.declare_file(session.result_dir / "geometry.txt", "required_evidence")
        path.write_text("real fixture output", encoding="utf-8")
        return dict(status="success", summary={"native_launches": 0}, output_paths=[str(path)],
                    required_output_paths=[str(path)], retention_preserve_paths=[], manifest_extra_fields={})

    def test_actual_package_capacity_retention_and_finalization_resume_without_reinvoking_action(self):
        from msplatform.execution import owner
        from msplatform.execution.capacity_ledger import load_capacity_ledger
        from msplatform.execution.capacity_protection import load_capacity_protection_leases
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = self._context(root)
            calls = []
            def action(session):
                calls.append(session.run_id)
                return self._action(session)
            arguments = self._arguments(root, action)
            policy = self._policy()
            with patch.object(owner, "_capacity_policy", return_value=policy), patch(
                    "msplatform.execution.capacity_admission._capacity_policy", return_value=policy):
                with patch("msplatform.execution.workflow_publication.publish_terminal_state", side_effect=OSError("PUBLICATION_FAULT")):
                    with self.assertRaisesRegex(OSError, "PUBLICATION_FAULT"):
                        owner.run_managed_stage(context, **arguments)
                result_path = next((context.workspace / "artifacts").rglob("result.json"))
                pending = json.loads(result_path.read_text(encoding="utf-8"))
                self.assertEqual(pending["resume_action"], "resume_finalization")
                self.assertTrue(pending["writers_confirmed"])
                self.assertTrue(load_capacity_protection_leases(context.workspace / "artifacts")["audit"])
                result = owner.resume_finalization(context, result_path)
                self.assertEqual(result["status"], "success")
                self.assertEqual(result["stage"], "complete")
                manifest_bytes = Path(result["manifest"]["path"]).read_bytes()
                repeated = owner.resume_finalization(context, result_path)
                self.assertEqual(repeated["status"], "success")
                self.assertEqual(Path(result["manifest"]["path"]).read_bytes(), manifest_bytes)
            self.assertEqual(calls, [arguments["run_id"]])
            self.assertEqual(load_capacity_protection_leases(context.workspace / "artifacts")["audit"], [])
            ledger = load_capacity_ledger(context.workspace / "artifacts")
            self.assertEqual([(row["class"], row["status"]) for row in ledger["objects"]], [("light_evidence", "ready")])
            self.assertFalse(context.host_state_path.exists())
            self.assertEqual(json.loads((Path(result["run_directory"]) / "run_config.json").read_text())["parameters"], {"science_input": 13})

    def test_unknown_writer_retains_capacity_and_refuses_finalization(self):
        from msplatform.execution import owner
        from msplatform.execution.capacity_protection import load_capacity_protection_leases
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = self._context(root)
            def unknown(session):
                session._active.add("unknown-child")
                return self._action(session)
            arguments = self._arguments(root, unknown)
            policy = self._policy()
            with patch.object(owner, "_capacity_policy", return_value=policy), patch(
                    "msplatform.execution.capacity_admission._capacity_policy", return_value=policy):
                with self.assertRaisesRegex(ValueError, "completion is unknown"):
                    owner.run_managed_stage(context, **arguments)
            result_path = next((context.workspace / "artifacts").rglob("result.json"))
            with self.assertRaisesRegex(ValueError, "confirmed stopped writers"):
                owner.resume_finalization(context, result_path)
            self.assertTrue(load_capacity_protection_leases(context.workspace / "artifacts")["audit"])
            manifest = json.loads(next((context.workspace / "artifacts").rglob("run_manifest.json")).read_text())
            self.assertEqual(manifest["status"], "checkpoint")

    def test_tampered_completion_input_refuses_recovery_without_action(self):
        from msplatform.execution import owner
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = self._context(root)
            arguments = self._arguments(root, self._action)
            policy = self._policy()
            with patch.object(owner, "_capacity_policy", return_value=policy), patch(
                    "msplatform.execution.capacity_admission._capacity_policy", return_value=policy), patch(
                    "msplatform.execution.workflow_publication.publish_terminal_state", side_effect=OSError("PUBLICATION_FAULT")):
                with self.assertRaisesRegex(OSError, "PUBLICATION_FAULT"):
                    owner.run_managed_stage(context, **arguments)
            request = next((context.workspace / "artifacts").rglob("execution_request.json"))
            request.write_bytes(request.read_bytes() + b" ")
            result = next((context.workspace / "artifacts").rglob("result.json"))
            with self.assertRaisesRegex(AssertionError, "execution_request byte count changed"):
                owner.resume_finalization(context, result)


    def test_real_zero_and_seven_processes_bind_original_pid_release_and_failure(self):
        from types import SimpleNamespace
        from msplatform.execution import owner
        for exit_code in (0, 7):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                context = self._context(root)
                receipts = []
                def action(session):
                    receipt = session.run_process("native-fixture", executable=Path(sys.executable),
                        arguments=["-c", f"import sys;print('ACTUAL_CHILD');sys.exit({exit_code})"],
                        role="GATE", stage="software_tests", limits=None)
                    receipts.append(receipt)
                    return self._action(session)
                arguments = self._arguments(root, action)
                arguments["expected_operation_ids"] = ["native-fixture"]
                arguments["completion_api"] = lambda: SimpleNamespace(recoverable_batch_logs=lambda _root: set())
                policy = self._policy()
                private_environment = dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN="",
                    MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID="", MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE="",
                    MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(context.host_state_path))
                with patch.dict(os.environ, private_environment), patch.object(owner, "_capacity_policy", return_value=policy), patch(
                        "msplatform.execution.capacity_admission._capacity_policy", return_value=policy):
                    if exit_code:
                        with self.assertRaisesRegex(ProcessExecutionError, "Observed process failed with exit 7"):
                            owner.run_managed_stage(context, **arguments)
                    else:
                        result = owner.run_managed_stage(context, **arguments)
                        self.assertEqual(result["status"], "success")
                result_path = next((context.workspace / "artifacts").rglob("result.json"))
                result = json.loads(result_path.read_text())
                self.assertEqual(result["stage"], "complete")
                self.assertEqual(result["status"], "failed" if exit_code else "success")
                run = Path(result["run_directory"])
                completion = json.loads((run / "results/execution_completion.json").read_text())
                observation = completion["writer_completion"]["operations"][0]["observation"]
                self.assertEqual(observation["returncode"], exit_code)
                self.assertGreater(observation["process_id"], 0)
                self.assertGreater(observation["process_started_at_utc_ticks"], 0)
                release = completion["writer_completion"]["resource_releases"][0]["completion_receipt"]["host_release"]
                self.assertEqual(release["result"], {"status": "released", "token": release["token"]})
                self.assertEqual(len(receipts), 0 if exit_code else 1)
                self.assertIn("ACTUAL_CHILD", (run / "logs/operation_0001.stdout.log").read_text())
                self.assertTrue(context.host_state_path.is_file())


    def test_stopped_payload_seal_source_protection_and_real_alias_keep_original_identity(self):
        from msplatform.execution import owner
        from msplatform.execution.capacity_ledger import load_capacity_ledger
        from msplatform.execution.capacity_protection import load_capacity_protection_leases, path_is_protected
        from msplatform.execution.manifest_records import file_record
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = self._context(root)
            payload_bytes = b"fixture-native-payload-not-a-solver-result"
            def make_payload(session):
                path = session.declare_file(session.result_dir / "field.pa", "solver_native_binary")
                path.write_bytes(payload_bytes)
                return dict(status="success", summary={"native_launches": 0}, output_paths=[str(path)],
                    required_output_paths=[str(path)], retention_preserve_paths=[], manifest_extra_fields={})
            arguments = self._arguments(root, make_payload)
            arguments["retention"] = dict(policy_version=1, **{"class": "solver_review"}, reason="fixture payload reuse")
            arguments["use_short_execution_path"] = True
            policy = self._policy()
            with patch.object(owner, "_capacity_policy", return_value=policy), patch(
                    "msplatform.execution.capacity_admission._capacity_policy", return_value=policy):
                producer = owner.run_managed_stage(context, **arguments)
                producer_run = Path(producer["run_directory"])
                payload = producer_run / "results/field.pa"
                self.assertEqual(payload.read_bytes(), payload_bytes)
                completion = json.loads((producer_run / "results/execution_completion.json").read_text())
                alias = Path(completion["package"]["execution_alias"])
                self.assertFalse(alias.exists())
                self.assertEqual(producer["capacity"]["action"], "seal_stopped_payload")
                self.assertTrue(producer["capacity"]["ledger_entry"]["pin"])
                manifest_before = Path(producer["manifest"]["path"]).read_bytes()
                field_record = file_record(payload, "solver_native_binary")
                def consume(session):
                    leases = load_capacity_protection_leases(session.artifact_root)
                    self.assertTrue(path_is_protected(producer_run, leases["protected_paths"]))
                    session.add_input("field", field_record)
                    return self._action(session)
                arguments = self._arguments(root, consume)
                arguments["run_id"] = "20261104_120001__build__python__source-consumer"
                arguments["source_references"] = [{"manifest_record": producer["manifest"]}]
                consumer = owner.run_managed_stage(context, **arguments)
                self.assertEqual(consumer["status"], "success")
            self.assertEqual(payload.read_bytes(), payload_bytes)
            self.assertEqual(Path(producer["manifest"]["path"]).read_bytes(), manifest_before)
            entries = load_capacity_ledger(context.workspace / "artifacts")["objects"]
            self.assertEqual(len(entries), 2)
            self.assertEqual(load_capacity_protection_leases(context.workspace / "artifacts")["audit"], [])


    def test_four_units_reuse_two_complete_and_replay_interrupted_and_unstarted_once(self):
        from types import SimpleNamespace
        from msplatform.execution import owner
        from msplatform.execution.manifest_records import file_record
        from msplatform.execution.recovery import build_whole_unit_replay_plan, WholeUnitReplayUnit
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = self._context(root)
            ids = {"u1": 3, "u2": 17, "u3": 55, "u4": 101}
            def parent_action(session):
                outputs = []
                for key in ("u3", "u1", "u2"):
                    path = session.declare_file(session.result_dir / (key + ".json"), "required_evidence")
                    path.write_text(json.dumps({"particle_id": ids[key], "complete": key != "u2"}), encoding="utf-8")
                    outputs.append(str(path))
                return dict(status="interrupted", summary={"fixture_units": 4}, output_paths=outputs,
                    required_output_paths=outputs, retention_preserve_paths=[], manifest_extra_fields={})
            arguments = self._arguments(root, parent_action)
            arguments["completion_api"] = lambda: SimpleNamespace(recoverable_batch_logs=lambda _root: set())
            policy = self._policy()
            with patch.object(owner, "_capacity_policy", return_value=policy), patch(
                    "msplatform.execution.capacity_admission._capacity_policy", return_value=policy):
                parent = owner.run_managed_stage(context, **arguments)
                parent_root = Path(parent["run_directory"])
                before = {path.name: path.read_bytes() for path in (parent_root / "results").glob("u*.json")}
                calls = []
                def child_action(session):
                    plan_path = session.declare_file(session.input_dir / "simion_whole_unit_replay_plan.json", "required_evidence")
                    plan = build_whole_unit_replay_plan(predecessor_run_dir=parent_root, output_dir=session.input_dir,
                        units=tuple(WholeUnitReplayUnit(key, (Path("results") / (key + ".json"),), key in {"u1", "u3"})
                                    for key in ("u3", "u2", "u1", "u4")))
                    session.add_input("replay_plan", file_record(plan_path, "required_evidence"))
                    observed_ids = []
                    outputs = []
                    for row in plan["units"]:
                        key = row["key"]
                        if row["action"] == "reuse":
                            path = Path(row["terminal_outputs"][0]["path"])
                            session.add_input("reused_" + key, file_record(path, "required_evidence"))
                        else:
                            calls.append(key)
                            path = session.declare_file(session.result_dir / (key + ".json"), "required_evidence")
                            path.write_text(json.dumps({"particle_id": ids[key], "complete": True}), encoding="utf-8")
                            outputs.append(str(path))
                        observed_ids.append(json.loads(path.read_text())["particle_id"])
                    self.assertEqual(plan["reusable_unit_count"], 2)
                    self.assertEqual(plan["replay_unit_count"], 2)
                    self.assertEqual(sorted(observed_ids), [3, 17, 55, 101])
                    self.assertEqual(len(set(observed_ids)), 4)
                    return dict(status="success", summary={"mother_ids": sorted(observed_ids), "native_launches": 0},
                        output_paths=outputs, required_output_paths=outputs,
                        retention_preserve_paths=[], manifest_extra_fields={})
                arguments = self._arguments(root, child_action)
                arguments["run_id"] = "20261104_120002__build__python__unit-replay"
                arguments["source_references"] = [{"manifest_record": parent["manifest"]}]
                child = owner.run_managed_stage(context, **arguments)
            self.assertEqual(child["status"], "success")
            self.assertEqual(calls, ["u2", "u4"])
            self.assertEqual(before, {path.name: path.read_bytes() for path in (parent_root / "results").glob("u*.json")})


    def test_action_primary_survives_publication_secondary_and_resume_does_not_repeat_action(self):
        from types import SimpleNamespace
        from msplatform.execution import owner
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = self._context(root)
            calls = []
            def action(session):
                calls.append(session.run_id)
                raise ValueError("ORIGINAL_ACTION_FAILURE")
            arguments = self._arguments(root, action)
            arguments["completion_api"] = lambda: SimpleNamespace(recoverable_batch_logs=lambda _root: set())
            policy = self._policy()
            with patch.object(owner, "_capacity_policy", return_value=policy), patch(
                    "msplatform.execution.capacity_admission._capacity_policy", return_value=policy):
                with patch("msplatform.execution.workflow_publication.publish_terminal_state", side_effect=OSError("SECONDARY_PUBLICATION")):
                    with self.assertRaisesRegex(ValueError, "ORIGINAL_ACTION_FAILURE") as caught:
                        owner.run_managed_stage(context, **arguments)
                self.assertTrue(any("SECONDARY_PUBLICATION" in note for note in caught.exception.__notes__))
                result_path = next((context.workspace / "artifacts").rglob("result.json"))
                failed = json.loads(result_path.read_text())
                self.assertEqual(failed["exception"]["message"], "ORIGINAL_ACTION_FAILURE")
                self.assertTrue(any("SECONDARY_PUBLICATION" in note for note in failed["exception"]["notes"]))
                result = owner.resume_finalization(context, result_path, completion_api=arguments["completion_api"])
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["stage"], "complete")
            self.assertEqual(result["exception"]["message"], "ORIGINAL_ACTION_FAILURE")
            self.assertEqual(calls, [arguments["run_id"]])

    def test_callable_record_must_bind_actual_source_before_workspace_creation(self):
        from msplatform.execution import owner
        from msplatform.execution.manifest_records import file_record
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = self._context(root)
            arguments = self._arguments(root, self._action)
            arguments["action_record"] = file_record(root / "budget.json", "required_evidence")
            with self.assertRaisesRegex(ValueError, "callable source differs"):
                owner.run_managed_stage(context, **arguments)
            self.assertFalse(context.workspace.exists())

    def test_original_process_failure_exit_facts_allow_safe_finalization_without_fabrication(self):
        from types import SimpleNamespace
        from msplatform.execution import owner
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = self._context(root)
            receipt = dict(observation=None, error=dict(message="ORIGINAL_PROCESS_FAILURE", data=dict(
                observed_process_exit_confirmed=True, observed_process_returncode=7,
                observed_process_id=123, observed_process_started_at_utc_ticks=456)),
                host_release=dict(inherited=False, token="fixture-owned-release",
                    result=dict(status="released", token="fixture-owned-release"), error=None))
            def action(session):
                session.run_process("fixture", executable=Path(sys.executable), arguments=["-V"],
                    role="GATE", stage="software_tests", limits=None)
            arguments = self._arguments(root, action)
            arguments["expected_operation_ids"] = ["fixture"]
            arguments["completion_api"] = lambda: SimpleNamespace(recoverable_batch_logs=lambda _root: set())
            policy = self._policy()
            with patch.object(owner, "_capacity_policy", return_value=policy), patch(
                    "msplatform.execution.capacity_admission._capacity_policy", return_value=policy), patch(
                    "msplatform.execution.run_session.run_observed_process",
                    side_effect=ProcessExecutionError("ORIGINAL_PROCESS_FAILURE", receipt)):
                with self.assertRaisesRegex(ProcessExecutionError, "ORIGINAL_PROCESS_FAILURE"):
                    owner.run_managed_stage(context, **arguments)
            result = json.loads(next((context.workspace / "artifacts").rglob("result.json")).read_text())
            self.assertEqual(result["stage"], "complete")
            completion = json.loads((Path(result["run_directory"]) / "results/execution_completion.json").read_text())
            self.assertEqual(completion["writer_completion"]["operations"][0]["observation"], dict(
                exit_confirmed=True, returncode=7, process_id=123, process_started_at_utc_ticks=456))
