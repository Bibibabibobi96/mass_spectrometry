"""Real OS input guards across the existing GATE process owner's failure drain."""
import json
import os
from pathlib import Path
import shutil
import subprocess
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
                history = r'''
$script:FactOriginalWrite=${function:Write-ResourceUsage}
function Write-ResourceUsage {
 param($Usage,$Path)
 if($Usage.Contains('last_process_observation')){
  [IO.File]::AppendAllText((Join-Path (Split-Path -Parent $Path) 'last-fact-history.jsonl'),
    (($Usage.last_process_observation|ConvertTo-Json -Depth 12 -Compress)+"`n"))
 }
 & $script:FactOriginalWrite @PSBoundParameters
}
'''
                text = text.replace(marker, marker+'\n'+history+'\n'+insertion)
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
            latest = json.loads(kwargs['usage_path'].read_text())['last_process_observation']
            self.assertEqual(latest['wait_phase'], 'immutable_drain_confirmed_empty')
            self.assertTrue(latest['root_exit_confirmed'])
            self.assertEqual(latest['sample']['active_process_ids'], [])
            source.write_bytes(b'released')
            source.unlink()
            for broken in ({**kwargs['immutable_input_records'][0], 'bytes':True},
                           {**kwargs['immutable_input_records'][0], 'sha256':'bad'}):
                with self.subTest(broken=broken), patch('msplatform.execution.processes.subprocess.Popen') as launch:
                    with self.assertRaisesRegex(ValueError, 'immutable inputs'):
                        run_observed_process(context, **dict(kwargs, immutable_input_records=[broken]))
                    launch.assert_not_called()

    def test_observation_and_wait_faults_preserve_primary_and_guard_through_natural_exit(self):
        for fault in ('observation','wait','publication'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                context, source, result, kwargs = self._case(root)
                insertion = ''
                edit = None
                if fault in ('observation', 'publication'):
                    insertion = "function Update-RepositoryProcessObservation {throw 'ORIGINAL_OBSERVATION_FAULT'}"
                    if fault == 'publication':
                        insertion += r'''
$script:PublishOriginal=${function:Write-ResourceUsage}
function Write-ResourceUsage {
 param($Usage,$Path)
 if($Usage.Contains('last_process_observation')){throw 'LAST_FACT_PUBLICATION_FAULT'}
 & $script:PublishOriginal @PSBoundParameters
}
'''
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
            history = [json.loads(line) for line in (root/'last-fact-history.jsonl').read_text().splitlines()]
            self.assertTrue(any(row['sample'] and row['sample']['ancestry_complete'] is False for row in history))
            self.assertEqual(history[-1]['wait_phase'], 'immutable_drain_confirmed_empty')
            self.assertTrue(history[-1]['sample']['ancestry_complete'])
            self.assertTrue(all(row['sampled_at_utc'] is None or row['sampled_at_utc'] <= row['recorded_at_utc']
                                for row in history))
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
deadline=time.monotonic()+15
while not Path(sys.argv[3]).exists():
 if time.monotonic()>deadline:raise RuntimeError('owned child was never observed after parent exit')
 time.sleep(.01)
p=Path(sys.argv[1]);blocked=False
try:p.write_bytes(b'CORRUPT')
except PermissionError:blocked=True
Path(sys.argv[2]).write_text(json.dumps(blocked))
''', encoding='utf-8')
            release = root/'release-owned-child'
            code = 'import subprocess,sys,time;subprocess.Popen([sys.executable,"-I",sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4]]);time.sleep(1)'
            insertion = r'''
$script:OwnedChildSample=${function:Get-ManagedSolverProcessSample}
function Get-ManagedSolverProcessSample {
 param($RootProcessIds,$TrackedProcessIds,$RootProcessStartedAtUtcTicks,$TrackedProcessStartedAtUtcTicks)
 $sample=& $script:OwnedChildSample @PSBoundParameters
 if(@($sample.active_process_ids).Count-gt0-and@($sample.active_process_ids)-notcontains$RootProcessIds[0]){
   [IO.File]::WriteAllText($env:INERT_RELEASE_CHILD,'observed_owned_child_after_root_exit')
 }
 return $sample
}
'''
            owner = self._owner_copy(root, insertion)
            real_resource = resource_path
            with patch.dict(os.environ, INERT_RELEASE_CHILD=str(release)), patch(
                    'msplatform.execution.processes.resource_path',
                    side_effect=lambda name:owner if name == 'process_owner.ps1' else real_resource(name)):
                receipt = run_observed_process(context, **dict(kwargs,
                    arguments=['-I','-c',code,str(child),str(source),str(result),str(release)]))
            history = [json.loads(line) for line in (root/'last-fact-history.jsonl').read_text().splitlines()]
            self.assertTrue(any(row['sample'] and row['sample']['active_process_ids'] and
                                row['managed_active'] is True and row['root_process_id'] not in row['sample']['active_process_ids']
                                for row in history), history)
            self.assertEqual(history[-1]['wait_phase'], 'immutable_drain_confirmed_empty')
            self.assertIs(json.loads(result.read_text()), True)
            self.assertEqual(receipt['observation']['exit_code'], 0)
            self.assertEqual(source.read_bytes(), b'original immutable input')
            source.unlink()

    def test_last_fact_publication_reuses_sample_and_legacy_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root/'facts.ps1'
            script.write_text(r"""
param($Resource,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Resource,[ref]$null,[ref]$null)
foreach($name in @('Write-ResourceUsage','Write-RepositoryLastProcessObservation')){
 $f=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
 if($null-eq$f){throw 'Fact implementation missing'}
 Invoke-Expression $f.Extent.Text
}
function Get-RepositoryUtcNow {[datetimeoffset]'2026-11-05T00:00:02Z'}
$script:FactWrites=0;$script:ActualFactWrite=${function:Write-ResourceUsage}
function Write-ResourceUsage {
 param($Usage,$Path)
 $script:FactWrites++
 & $script:ActualFactWrite @PSBoundParameters
}
function Get-ManagedSolverProcessSample {throw 'EXTRA_SAMPLE_FORBIDDEN'}
function Get-RepositoryProcessSnapshot {throw 'EXTRA_SNAPSHOT_FORBIDDEN'}
function Get-RunDirectoryBytes {throw 'EXTRA_DIRECTORY_SCAN_FORBIDDEN'}
$path=Join-Path $Root facts.json
$observation=@{usage=$null;usage_path=$path;root_process_id=7;root_process_started_at_utc_ticks=100}
Write-RepositoryLastProcessObservation -Observation $observation -Phase legacy -Reason no_output
if(Test-Path $path){throw 'Legacy no-metadata invocation gained an output'}
$observation.start_receipt=@{budget_observation='not_requested';process_start=@{root_process_id=7}}
$sample=[pscustomobject]@{active_process_ids=@(9);tracked_process_ids=@(7,9);
 tracked_process_started_at_utc_ticks=@{'7'=100;'9'=200};unknown_ancestry_process_ids=@(9);
 ancestry_complete=$false;system_console_host_process_ids=@();process_parent_ids=@{'9'=7;'88'=99}}
Write-RepositoryLastProcessObservation -Observation $observation -Sample $sample `
 -SampledAt ([datetimeoffset]'2026-11-05T00:00:01Z') -Phase process_observation `
 -Reason managed_process_active -ManagedActive $true
Write-RepositoryLastProcessObservation -Observation $observation -Phase root_handle_wait `
 -Reason await_original_handle_exit -RootExitConfirmed $false
$sample.process_parent_ids['88']=100
Write-RepositoryLastProcessObservation -Observation $observation -Sample $sample `
 -SampledAt ([datetimeoffset]'2026-11-05T00:00:01Z') -Phase root_handle_wait `
 -Reason await_original_handle_exit -RootExitConfirmed $false
if($script:FactWrites-ne2){throw 'Unrelated parent edge churn caused an extra diagnostic write'}
$ownedFacts=$observation.start_receipt.last_process_observation.sample.process_parent_ids
if($ownedFacts.Count-ne1-or$ownedFacts['9']-ne7-or$ownedFacts.Contains('88')){
 throw 'Unrelated parent edge contaminated owned facts'
}
$sample.active_process_ids[0]=999;$sample.tracked_process_started_at_utc_ticks['9']=999
Write-RepositoryLastProcessObservation -Observation $observation -Phase root_handle_wait `
 -Reason await_original_handle_exit -RootExitConfirmed $false
if($script:FactWrites-ne2){throw 'Repeated unchanged fact added a write'}
$receipt=Get-Content $path -Raw|ConvertFrom-Json
if($receipt.budget_observation-cne'not_requested'-or$receipt.PSObject.Properties.Name-contains'limits'){
 throw 'No-budget facts invented budget measurements'
}
$f=$receipt.last_process_observation
if(@($f.sample.active_process_ids)[0]-ne9-or$f.sample.tracked_process_started_at_utc_ticks.'9'-ne200){throw 'Recorded sample retained mutable references'}
if(([datetimeoffset]$f.sampled_at_utc).UtcDateTime-ne([datetimeoffset]'2026-11-05T00:00:01Z').UtcDateTime `
 -or([datetimeoffset]$f.recorded_at_utc).UtcDateTime-ne([datetimeoffset]'2026-11-05T00:00:02Z').UtcDateTime `
 -or$f.sample.ancestry_complete-or$f.wait_phase-cne'root_handle_wait'-or$f.root_exit_confirmed){throw 'Stale sample or unknown fact was reclassified'}
function Write-ResourceUsage {throw 'CONTROLLED_FACT_PUBLISH_FAILURE'}
Write-RepositoryLastProcessObservation -Observation $observation -Phase root_handle_wait -Reason preserve
if($observation.last_process_observation_error-cne'CONTROLLED_FACT_PUBLISH_FAILURE'){throw 'Publication error lost'}
'FACTS_WITHOUT_SAMPLING=PASS'
""", encoding='utf-8', newline='\n')
            result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File', str(script),
                                     str(resource_path('resource_process_support.ps1')), str(root)],
                                    cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('FACTS_WITHOUT_SAMPLING=PASS', result.stdout)

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
