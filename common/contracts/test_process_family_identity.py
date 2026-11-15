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

    def test_retained_historical_contradiction_is_rechecked_without_dropping_uncertain(self):
        script = r"""
function Assert-HostResourceHeavyStage {}
function Test-HostResourceConsoleProcess {param($ImagePath) return $false}
function Get-HostResourceNativeProcessCreationTicks {param($ProcessId) return $null}
. $args[0]
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($args[1],[ref]$tokens,[ref]$errors)
$lookup=$ast.Find({param($node) $node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq'Get-HostResourceSnapshotParent'},$true)
Invoke-Expression $lookup.Extent.Text
function row($id,$ticks){[pscustomobject]@{Id=$id;StartTime=[datetime]::new([long]$ticks,[DateTimeKind]::Utc);Path='inert.exe';WorkingSet64=10;PrivateMemorySize64=10;TotalProcessorTime=[timespan]::Zero}}
function snapshot($row,$child,$parent,$fallback){
 $entry=[pscustomobject]@{ProcessId=$child;ParentProcessId=$parent;ExecutablePath='inert.exe'};$ps=$null
 if($fallback){$map=[Collections.Generic.Dictionary[int,int]]::new();$map.Add($child,$parent);$ps=[pscustomobject]@{parents=$map;complete=$true;started_at_utc_ticks=639303251814695845}}
 [pscustomobject]@{processes=@($row);cim_processes=@($entry);parent_snapshot=$ps}
}
$root=27280;$parent=25840;$child=25612;$rt=[long]639303245074356451;$pt=[long]639303251814685845;$old=[long]639302224202655781
$facts=@()
foreach($fallback in @($false,$true)){
 $base=@{RootProcessIds=@($root);RootProcessStartedAtUtcTicks=@{"$root"=$rt};TrackedProcessIds=@($root,$parent,$child)}
 $bad=Get-ManagedSolverProcessSample @base -TrackedProcessStartedAtUtcTicks @{"$root"=$rt;"$parent"=$pt;"$child"=$old} -ProcessSnapshot (snapshot (row $child $old) $child $parent $fallback)
 $earlySnapshot=snapshot (row $child $old) $child $parent $fallback
 if($fallback){$earlySnapshot.parent_snapshot.started_at_utc_ticks=$old-1}
 $early=Get-ManagedSolverProcessSample @base -TrackedProcessStartedAtUtcTicks @{"$root"=$rt;"$parent"=$pt;"$child"=$old} -ProcessSnapshot $earlySnapshot
 $untracked=Get-ManagedSolverProcessSample -RootProcessIds @($root) -RootProcessStartedAtUtcTicks @{"$root"=$rt} -TrackedProcessIds @($root,$parent) -TrackedProcessStartedAtUtcTicks @{"$root"=$rt;"$parent"=$pt} -ProcessSnapshot $earlySnapshot
 $later=$rt+1000
 $uncertain=Get-ManagedSolverProcessSample @base -TrackedProcessStartedAtUtcTicks @{"$root"=$rt;"$parent"=$pt;"$child"=$later} -ProcessSnapshot (snapshot (row $child $later) $child $parent $fallback)
 $reusedSnapshot=snapshot (row $child $later) $child $parent $fallback
 $reusedSnapshot.processes=@((row $child $later),(row $parent ($pt+1000)))
 $reused=Get-ManagedSolverProcessSample @base -TrackedProcessStartedAtUtcTicks @{"$root"=$rt;"$parent"=$pt;"$child"=$later} -ProcessSnapshot $reusedSnapshot
 $unknown=row $child $later;$unknown.PSObject.Properties.Remove('StartTime');$unknown|Add-Member ScriptProperty StartTime {throw 'CONTROLLED_UNKNOWN'}
 $missing=Get-ManagedSolverProcessSample @base -TrackedProcessStartedAtUtcTicks @{"$root"=$rt;"$parent"=$pt;"$child"=$later} -ProcessSnapshot (snapshot $unknown $child $parent $fallback)
 $noRoot=Get-ManagedSolverProcessSample -RootProcessIds @($root) -RootProcessStartedAtUtcTicks @{} -TrackedProcessIds @($child) -TrackedProcessStartedAtUtcTicks @{"$child"=$old} -ProcessSnapshot (snapshot (row $child $old) $child $root $fallback)
 $facts+=@{fallback=$fallback;bad=@($bad.active_process_ids);bad_complete=$bad.ancestry_complete;bad_unknown=@($bad.unknown_ancestry_process_ids);early=@($early.active_process_ids);early_complete=$early.ancestry_complete;early_unknown=@($early.unknown_ancestry_process_ids);untracked=@($untracked.active_process_ids);untracked_complete=$untracked.ancestry_complete;untracked_unknown=@($untracked.unknown_ancestry_process_ids);uncertain=@($uncertain.active_process_ids);uncertain_complete=$uncertain.ancestry_complete;uncertain_unknown=@($uncertain.unknown_ancestry_process_ids);reused=@($reused.active_process_ids);reused_complete=$reused.ancestry_complete;reused_unknown=@($reused.unknown_ancestry_process_ids);missing=@($missing.active_process_ids);missing_complete=$missing.ancestry_complete;no_root=@($noRoot.active_process_ids);no_root_complete=$noRoot.ancestry_complete}
}
ConvertTo-Json -InputObject @($facts) -Depth 8 -Compress
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'contradiction.ps1'
            path.write_text(script, encoding='utf-8', newline='\n')
            result = subprocess.run([shutil.which('pwsh'), '-NoLogo', '-NoProfile', '-File', str(path),
                str(resource_path('resource_process_support.ps1')), str(resource_path('host_execution_lease.ps1'))],
                capture_output=True, timeout=30, cwd=directory)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        for facts in json.loads(result.stdout.decode('utf-8-sig')):
            with self.subTest(fallback=facts['fallback']):
                self.assertEqual(facts['bad'], [], facts)
                self.assertTrue(facts['bad_complete'], facts)
                self.assertEqual(facts['bad_unknown'], [], facts)
                self.assertEqual(facts['early'], [], facts)
                self.assertTrue(facts['early_complete'], facts)
                self.assertEqual(facts['early_unknown'], [], facts)
                self.assertEqual(facts['untracked'], [], facts)
                self.assertTrue(facts['untracked_complete'], facts)
                self.assertEqual(facts['untracked_unknown'], [], facts)
                self.assertEqual(facts['uncertain'], [25612], facts)
                self.assertFalse(facts['uncertain_complete'], facts)
                self.assertIn(25612, facts['uncertain_unknown'], facts)
                self.assertEqual(facts['reused'], [25612], facts)
                self.assertFalse(facts['reused_complete'], facts)
                self.assertIn(25612, facts['reused_unknown'], facts)
                self.assertEqual(facts['missing'], [25612], facts)
                self.assertFalse(facts['missing_complete'], facts)
                self.assertEqual(facts['no_root'], [25612], facts)
                self.assertFalse(facts['no_root_complete'], facts)

    def test_multiple_roots_require_birth_before_every_bound_root(self):
        script = r"""
function Assert-HostResourceHeavyStage {}
function Test-HostResourceConsoleProcess {param($ImagePath) return $false}
function Get-HostResourceNativeProcessCreationTicks {param($ProcessId) return $null}
. $args[0]
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($args[1],[ref]$tokens,[ref]$errors)
$lookup=$ast.Find({param($node) $node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-eq'Get-HostResourceSnapshotParent'},$true)
Invoke-Expression $lookup.Extent.Text
$t=[datetime]::Parse('2026-01-01T00:00:00Z').ToUniversalTime().Ticks
function row($ticks){[pscustomobject]@{Id=200;StartTime=[datetime]::new([long]$ticks,[DateTimeKind]::Utc);Path='inert.exe';WorkingSet64=10;PrivateMemorySize64=10;TotalProcessorTime=[timespan]::Zero}}
function snapshot($ticks,$fallback){
 $entry=[pscustomobject]@{ProcessId=200;ParentProcessId=100;ExecutablePath='inert.exe'};$ps=$null
 if($fallback){$map=[Collections.Generic.Dictionary[int,int]]::new();$map.Add(200,100);$ps=[pscustomobject]@{parents=$map;complete=$true;started_at_utc_ticks=($t+1000000)}}
 [pscustomobject]@{processes=@((row $ticks));cim_processes=@($entry);parent_snapshot=$ps}
}
$facts=@()
foreach($fallback in @($false,$true)){
 $base=@{RootProcessIds=@(100,101);TrackedProcessIds=@(100,101,200)}
 $between=Get-ManagedSolverProcessSample @base -RootProcessStartedAtUtcTicks @{'100'=$t;'101'=($t+1000)} -TrackedProcessStartedAtUtcTicks @{'100'=$t;'101'=($t+1000);'200'=($t+500)} -ProcessSnapshot (snapshot ($t+500) $fallback)
 $older=Get-ManagedSolverProcessSample @base -RootProcessStartedAtUtcTicks @{'100'=$t;'101'=($t+1000)} -TrackedProcessStartedAtUtcTicks @{'100'=$t;'101'=($t+1000);'200'=($t-100)} -ProcessSnapshot (snapshot ($t-100) $fallback)
 $missing=Get-ManagedSolverProcessSample @base -RootProcessStartedAtUtcTicks @{'100'=$t} -TrackedProcessStartedAtUtcTicks @{'100'=$t;'200'=($t-100)} -ProcessSnapshot (snapshot ($t-100) $fallback)
 $facts+=@{fallback=$fallback;between=@($between.active_process_ids);between_complete=$between.ancestry_complete;older=@($older.active_process_ids);older_complete=$older.ancestry_complete;older_unknown=@($older.unknown_ancestry_process_ids);missing=@($missing.active_process_ids);missing_complete=$missing.ancestry_complete;missing_unknown=@($missing.unknown_ancestry_process_ids)}
}
ConvertTo-Json -InputObject @($facts) -Depth 8 -Compress
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'multi-root.ps1'
            path.write_text(script, encoding='utf-8', newline='\n')
            result = subprocess.run([shutil.which('pwsh'), '-NoLogo', '-NoProfile', '-File', str(path),
                str(resource_path('resource_process_support.ps1')), str(resource_path('host_execution_lease.ps1'))],
                capture_output=True, timeout=30, cwd=directory)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        for facts in json.loads(result.stdout.decode('utf-8-sig')):
            with self.subTest(fallback=facts['fallback']):
                self.assertEqual(facts['between'], [200], facts)
                self.assertTrue(facts['between_complete'], facts)
                self.assertEqual(facts['older'], [], facts)
                self.assertTrue(facts['older_complete'], facts)
                self.assertEqual(facts['older_unknown'], [], facts)
                self.assertEqual(facts['missing'], [200], facts)
                self.assertFalse(facts['missing_complete'], facts)
                self.assertIn(200, facts['missing_unknown'], facts)

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
