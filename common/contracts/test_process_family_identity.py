"""Pure process snapshots exercise the actual installed family sampler; no OS process query."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from msplatform.execution.resources import resource_path


@unittest.skipUnless(shutil.which('pwsh'),'PowerShell required')
class ProcessFamilyIdentityTests(unittest.TestCase):
    def _time_edge_snapshots(self):
        script=r"""
function Assert-HostResourceHeavyStage {}
function Test-HostResourceConsoleProcess {param($ImagePath) return $false}
function Get-HostResourceNativeProcessCreationTicks {param($ProcessId) return $null}
. $args[0]
# Load the existing pure fallback-parent lookup, not a second test algorithm.
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($args[1],[ref]$tokens,[ref]$errors)
$lookup=$ast.Find({param($node) $node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq'Get-HostResourceSnapshotParent'},$true)
Invoke-Expression $lookup.Extent.Text
function row($id,$ticks){[pscustomobject]@{Id=$id;StartTime=[datetime]::new([long]$ticks,[DateTimeKind]::Utc);Path='inert-python.exe';WorkingSet64=10;PrivateMemorySize64=10;TotalProcessorTime=[timespan]::Zero}}
function parent($child,$parent){[pscustomobject]@{ProcessId=$child;ParentProcessId=$parent;ExecutablePath='inert-python.exe'}}
function snapshot($rows,$parents,$fallback){
 $ps=$null
 if($fallback){$map=[Collections.Generic.Dictionary[int,int]]::new();foreach($p in $parents){$map.Add([int]$p.ProcessId,[int]$p.ParentProcessId)};$ps=[pscustomobject]@{parents=$map;complete=$true;started_at_utc_ticks=($t+1000000)}}
 [pscustomobject]@{processes=@($rows);cim_processes=@($parents);parent_snapshot=$ps}
}
$t=[datetime]::Parse('2026-01-01T00:00:00Z').ToUniversalTime().Ticks
$facts=@()
foreach($fallback in @($false,$true)){
 $first=Get-ManagedSolverProcessSample -RootProcessIds @(100) -RootProcessStartedAtUtcTicks @{'100'=($t+4000)} -ProcessSnapshot (snapshot @((row 100 ($t+4000)),(row 200 ($t+5000))) @((parent 100 99),(parent 200 100)) $fallback)
 $shared=@{RootProcessIds=@(100);RootProcessStartedAtUtcTicks=@{'100'=($t+4000)};TrackedProcessIds=$first.tracked_process_ids;TrackedProcessStartedAtUtcTicks=$first.tracked_process_started_at_utc_ticks}
 $legal=Get-ManagedSolverProcessSample @shared -ProcessSnapshot (snapshot @((row 200 ($t+5000)),(row 250 ($t+6000))) @((parent 200 100),(parent 250 200)) $fallback)
 $negative=Get-ManagedSolverProcessSample @shared -ProcessSnapshot (snapshot @((row 300 ($t+1000)),(row 400 ($t+3000))) @((parent 300 200),(parent 400 300)) $fallback)
 $fresh=Get-ManagedSolverProcessSample @shared -ProcessSnapshot (snapshot @((row 100 ($t+4000)),(row 200 ($t+8000)),(row 250 ($t+9000))) @((parent 100 99),(parent 200 100),(parent 250 200)) $fallback)
 $unknown=row 200 ($t+5000);$unknown.PSObject.Properties.Remove('StartTime');$unknown|Add-Member ScriptProperty StartTime {throw 'CONTROLLED_IDENTITY_UNKNOWN'}
 $uncertain=Get-ManagedSolverProcessSample -RootProcessIds @(100) -RootProcessStartedAtUtcTicks @{'100'=($t+4000)} -ProcessSnapshot (snapshot @((row 100 ($t+4000)),$unknown,(row 250 ($t+6000))) @((parent 100 99),(parent 200 100),(parent 250 200)) $fallback)
 $orphanUnknown=Get-ManagedSolverProcessSample -RootProcessIds @(100) -RootProcessStartedAtUtcTicks @{'100'=($t+4000)} -TrackedProcessIds $uncertain.tracked_process_ids -TrackedProcessStartedAtUtcTicks $uncertain.tracked_process_started_at_utc_ticks -ProcessSnapshot (snapshot @($unknown,(row 250 ($t+6000))) @((parent 200 100),(parent 250 200)) $fallback)
 $facts+=@{fallback=$fallback;legal=@($legal.active_process_ids);negative=@($negative.active_process_ids);negative_known=$negative.ancestry_complete;fresh=@($fresh.active_process_ids);fresh_birth=$fresh.tracked_process_started_at_utc_ticks['200'];expected_fresh_birth=($t+8000);unknown=@($uncertain.active_process_ids);unknown_complete=$uncertain.ancestry_complete;unknown_ids=@($uncertain.unknown_ancestry_process_ids);orphan_unknown=@($orphanUnknown.active_process_ids);orphan_unknown_complete=$orphanUnknown.ancestry_complete;invented_unknown_birth=$orphanUnknown.tracked_process_started_at_utc_ticks.ContainsKey('200')}
}
ConvertTo-Json -InputObject @($facts) -Depth 8 -Compress
"""
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'time-edges.ps1';path.write_text(script,encoding='utf-8',newline='\n')
            result=subprocess.run([shutil.which('pwsh'),'-NoLogo','-NoProfile','-File',str(path),
                str(resource_path('resource_process_support.ps1')),str(resource_path('host_execution_lease.ps1'))],
                capture_output=True,timeout=30,cwd=directory)
        self.assertEqual(result.returncode,0,result.stderr.decode('utf-8','replace'))
        return json.loads(result.stdout.decode('utf-8-sig'))

    def test_parent_pid_edge_cannot_adopt_older_driver_but_keeps_real_orphans(self):
        for facts in self._time_edge_snapshots():
            with self.subTest(native_parent_fallback=facts['fallback']):
                self.assertEqual(facts['legal'],[200,250])
                self.assertEqual(facts['negative'],[],facts)
                self.assertEqual(facts['fresh'],[100,200,250])
                self.assertEqual(facts['fresh_birth'],facts['expected_fresh_birth'])

    def test_unknown_descendant_birth_stays_active_unknown_after_root_exit(self):
        for facts in self._time_edge_snapshots():
            with self.subTest(native_parent_fallback=facts['fallback']):
                self.assertEqual(facts['unknown'],[100,200,250],facts)
                self.assertFalse(facts['unknown_complete'])
                self.assertIn(200,facts['unknown_ids'])
                self.assertEqual(facts['orphan_unknown'],[200,250])
                self.assertFalse(facts['orphan_unknown_complete'])
                self.assertFalse(facts['invented_unknown_birth'])

    def test_exited_identity_survives_empty_poll_and_reused_pid_is_not_owned(self):
        script = r"""
function Assert-HostResourceHeavyStage {}
function Test-HostResourceConsoleProcess {param($ImagePath) return $false}
function Get-HostResourceNativeProcessCreationTicks {param($ProcessId) return $null}
. $args[0]
function row($id,$ticks){[pscustomobject]@{Id=$id;StartTime=[datetime]::new([long]$ticks,[DateTimeKind]::Utc);Path='python.exe';WorkingSet64=10;PrivateMemorySize64=10;TotalProcessorTime=[timespan]::Zero}}
function snapshot($rows,$parents){[pscustomobject]@{processes=@($rows);cim_processes=@($parents);parent_snapshot=$null}}
$rootTicks=[datetime]::Parse('2026-01-01T00:00:00Z').ToUniversalTime().Ticks
$childTicks=$rootTicks+100
$first=Get-ManagedSolverProcessSample -RootProcessIds @(100) -RootProcessStartedAtUtcTicks @{'100'=$rootTicks} -ProcessSnapshot (snapshot @((row 100 $rootTicks),(row 200 $childTicks)) @([pscustomobject]@{ProcessId=100;ParentProcessId=99;ExecutablePath='python.exe'},[pscustomobject]@{ProcessId=200;ParentProcessId=100;ExecutablePath='python.exe'}))
# A live real child remains owned after its root exits.
$orphan=Get-ManagedSolverProcessSample -RootProcessIds @(100) -RootProcessStartedAtUtcTicks @{'100'=$rootTicks} -TrackedProcessIds $first.tracked_process_ids -TrackedProcessStartedAtUtcTicks $first.tracked_process_started_at_utc_ticks -ProcessSnapshot (snapshot @((row 200 $childTicks)) @([pscustomobject]@{ProcessId=200;ParentProcessId=100;ExecutablePath='python.exe'}))
$empty=Get-ManagedSolverProcessSample -RootProcessIds @(100) -RootProcessStartedAtUtcTicks @{'100'=$rootTicks} -TrackedProcessIds $orphan.tracked_process_ids -TrackedProcessStartedAtUtcTicks $orphan.tracked_process_started_at_utc_ticks -ProcessSnapshot (snapshot @() @())
$reused=Get-ManagedSolverProcessSample -RootProcessIds @(100) -RootProcessStartedAtUtcTicks @{'100'=$rootTicks} -TrackedProcessIds $empty.tracked_process_ids -TrackedProcessStartedAtUtcTicks $empty.tracked_process_started_at_utc_ticks -ProcessSnapshot (snapshot @((row 200 ($childTicks+100))) @([pscustomobject]@{ProcessId=200;ParentProcessId=999;ExecutablePath='python.exe'}))
@{first=@($first.active_process_ids);orphan=@($orphan.active_process_ids);empty=@($empty.active_process_ids);empty_births=$empty.tracked_process_started_at_utc_ticks;reused=@($reused.active_process_ids);reused_ancestry=$reused.ancestry_complete;child_ticks=$childTicks}|ConvertTo-Json -Depth 8 -Compress
"""
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'snapshots.ps1';path.write_text(script,encoding='utf-8',newline='\n')
            result=subprocess.run([shutil.which('pwsh'),'-NoLogo','-NoProfile','-File',str(path),str(resource_path('resource_process_support.ps1'))],capture_output=True,timeout=30,cwd=directory)
        self.assertEqual(result.returncode,0,result.stderr.decode('utf-8','replace'))
        facts=json.loads(result.stdout.decode('utf-8'))
        self.assertEqual(facts['first'],[100,200]);self.assertEqual(facts['orphan'],[200]);self.assertEqual(facts['empty'],[])
        self.assertEqual(facts['reused'],[],facts)
        self.assertEqual(facts['empty_births']['200'],facts['child_ticks'])


if __name__=='__main__':unittest.main()
