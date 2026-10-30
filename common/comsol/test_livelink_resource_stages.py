"""Exercise LiveLink scheduling boundaries with isolated process and scheduler doubles."""

from __future__ import annotations

import os
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]

SCHEDULER = r'''
function Write-Event($Name) { Add-Content -LiteralPath $env:STAGE_EVENTS -Value $Name }
function Get-HostResourceBudget { param($Role,$Stage) return @{schema_version=1;unknown_peak=$true;exclusive_resources=@()} }
function Enter-HostResourceStage {
    param($Role,$Stage,$Budget,$RunId)
    Write-Event "enter:${Stage}:unknown=$($Budget.unknown_peak)"
    return @{token='isolated-test';inherited=($env:STAGE_RELEASE -eq 'inherited')}
}
function Update-HostResourceStage {
    param($Lease,$Stage,$Budget,$RetainedMemoryBytes)
    if ($Stage -eq 'postprocess' -and $global:FakeServerLive) { throw 'server is still live at transition' }
    if ($Stage -eq 'solver') {
        if ($Budget.exclusive_resources -notcontains 'comsol-server-session') { throw 'missing COMSOL session lock' }
        Write-Event "solver_locks:$($Budget.exclusive_resources -join ',')"
    }
    Write-Event "update:${Stage}:unknown=$($Budget.unknown_peak)"
}
function Register-HostResourceProcess {
    param($Lease,$ProcessId)
    Write-Event "register:$ProcessId"
    if ($env:STAGE_SCENARIO -eq 'registration_failure') { throw 'registration failed' }
}
function Exit-HostResourceStage {
    param($Lease,[switch]$PassThru)
    Write-Event 'exit'
    if($env:STAGE_RELEASE -eq 'error'){throw 'TEST_ONLY release failed'}
    if($PassThru -and -not $Lease.inherited){
        return @{status=$(if($env:STAGE_RELEASE -eq 'retained'){'retained'}else{'released'});token=$Lease.token}
    }
}
function Receive-HostResourceStage {
    param($Lease)
    if (-not $global:FakeLauncherProcess.HasExited) { throw 'scheduler polled while launcher is running' }
    Write-Event 'receive'
}
'''

LAUNCHER = r'''
function Start-ComsolLauncherProcess {
    param($FilePath,$Arguments)
    $global:FakeLaunchCount++
    $global:FakeServerLive=$true
    Write-Event 'launch'
    if ($env:STAGE_SCENARIO -eq 'assembly_arguments') {
        Write-Event ('launcher_arguments:' + (ConvertTo-Json -InputObject @($Arguments) -Compress))
    }
    $reportText = "STATUS=PASS`n"
    if ($env:STAGE_SCENARIO -eq 'task_failure') {
        $reportText = "STATUS=FAIL`nERROR=Study Compute failed`n"
    }
    if ($env:STAGE_SCENARIO -eq 'startup_retry' -and $global:FakeLaunchCount -eq 1) {
        $reportText = "STATUS=FAIL`nERROR=mphload mphopen Not connected to a server`n"
    }
    if ($env:STAGE_SCENARIO -in @('running_then_pass','running_without_terminal')) {
        $reportText = "STATUS=RUNNING`n"
    }
    if ($env:STAGE_SCENARIO -notlike 'timeout_*') {
        [IO.File]::WriteAllText($env:COMSOL_BOOTSTRAP_REPORT,$reportText)
    }
    $reader = [pscustomobject]@{}
    $reader | Add-Member ScriptMethod ReadToEndAsync {
        return [Threading.Tasks.Task]::FromResult[string]('')
    }
    $process = [pscustomobject]@{
        Id=999999
        StartTime=[DateTime]::Now
        HasExited=($env:STAGE_SCENARIO -notin @('registration_failure','running_then_pass') -and $env:STAGE_SCENARIO -notlike 'timeout_*')
        ExitCode=$(if ($env:STAGE_SCENARIO -eq 'running_without_terminal') { 3 } else { 0 })
        StandardOutput=$reader
        StandardError=$reader
        RefreshCount=0
    }
    $process | Add-Member ScriptMethod Refresh {
        Write-Event 'refresh_live'
        $this.RefreshCount++
        if ($this.RefreshCount -ge 2) {
            if ($env:STAGE_SCENARIO -eq 'timeout_warn_pass') {
                [IO.File]::WriteAllText($env:COMSOL_BOOTSTRAP_REPORT,"STATUS=PASS`n")
            } elseif ($env:STAGE_SCENARIO -eq 'timeout_warn_failure') {
                [IO.File]::WriteAllText($env:COMSOL_BOOTSTRAP_REPORT,"STATUS=FAIL`nERROR=real failure`n")
                $this.ExitCode=2
            } elseif ($env:STAGE_SCENARIO -eq 'timeout_warn_missing') {
                $this.ExitCode=3
            }
            $this.HasExited=$true
        }
    }
    $process | Add-Member ScriptMethod Kill { param($Tree) Write-Event 'kill'; $this.HasExited=$true }
    $process | Add-Member ScriptMethod WaitForExit {
        param($Milliseconds)
        Write-Event 'wait'
        if ($env:STAGE_SCENARIO -eq 'running_then_pass') {
            [IO.File]::WriteAllText($env:COMSOL_BOOTSTRAP_REPORT,"STATUS=PASS`n")
            $this.HasExited=$true
        }
        return $true
    }
    $global:FakeLauncherProcess=$process
    return $process
}
function Stop-ComsolAttemptServers {
    param($RootProcessId,$Observation,$Reason)
    Write-Event "server_cleanup:$Reason"
    if ($env:STAGE_SCENARIO -eq 'cleanup_failure') { throw 'server cleanup failed' }
    $global:FakeServerLive=$false
}
'''


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
class LiveLinkResourceStageTests(unittest.TestCase):
    """Keep real launcher control flow; replace only external effects in a temp tree."""

    creation_flags = 0

    def run_scenario(
        self, scenario: str, *, supplied_budget: int = 0, assembly_mode: str | None = None,
        crash_scenario: str | None = None, observation_scenario: str | None = None,
        completion: bool = False, release: str = '',
    ) -> tuple[int, list[str], str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comsol = root / "common" / "comsol"
            comsol.mkdir(parents=True)
            (root / "common" / "require_powershell7.ps1").write_text("", encoding="utf-8")
            (root / "common" / "host_execution_lease.ps1").write_text(
                (ROOT / "common/host_execution_lease.ps1").read_text(encoding="utf-8") + SCHEDULER,
                encoding="utf-8")
            shutil.copy2(ROOT / "common/host_resource_policy.json", root / "common")
            shutil.copy2(ROOT / "common/resource_budget_support.ps1", root / "common")
            (comsol / "resolve_comsol_64.ps1").write_text(
                "function Get-Comsol64Launcher { return $env:FAKE_LAUNCHER }", encoding="utf-8"
            )
            (comsol / "livelink_environment.ps1").write_text(
                "function Get-ComsolRuntimeWritePaths { param($UserProfile,$TempPath) return @() }\n"
                "function Assert-ComsolRuntimeWriteAccess { param($Paths) }", encoding="utf-8"
            )
            shutil.copy2(ROOT / "common/comsol/livelink_failure_classification.ps1", comsol)
            shutil.copy2(ROOT / "common/comsol/run_comsol_r2025b.ps1", comsol)
            (root / "launcher.exe").write_bytes(b"test double; never executed")
            (root / "task.m").write_text("% not executed", encoding="utf-8")
            (root / "launcher_double.ps1").write_text(LAUNCHER, encoding="utf-8")
            if crash_scenario:
                (root / "controlled_child.ps1").write_text(r'''
# TEST_ONLY: controlled file transport fixture, not a JVM/solver crash.
$bytes=[Text.Encoding]::UTF8.GetBytes("TEST_ONLY owned log`r`n") + [byte[]](0..255)
$name="hs_err_pid$PID.log"
$source=Join-Path (Get-Location).Path $name
[IO.File]::WriteAllBytes($source,$bytes)
if ($env:CRASH_SCENARIO -eq 'old') {
    [IO.File]::SetCreationTimeUtc($source,[DateTime]::UtcNow.AddMinutes(-1))
}
if ($env:CRASH_SCENARIO -eq 'conflict') {
    [IO.File]::WriteAllText((Join-Path (Split-Path -Parent $env:COMSOL_BOOTSTRAP_REPORT) $name),'TEST_ONLY existing destination')
}
@{pid=$PID;working_directory=(Get-Location).Path}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path (Get-Location).Path 'child_facts.json')
if ($env:OBSERVATION_SCENARIO) {
    # TEST_ONLY native ancestry, never a commercial model or solver.
    $seconds=if($env:OBSERVATION_SCENARIO-eq'critical'){20}else{3}
    $worker=Start-Process -FilePath (Get-Process -Id $PID).Path -WindowStyle Hidden -PassThru -ArgumentList @('-NoProfile','-Command',"Start-Sleep -Seconds $seconds")
    @{process_id=$worker.Id;started_at_utc_ticks=$worker.StartTime.ToUniversalTime().Ticks}|
      ConvertTo-Json|Set-Content -LiteralPath (Join-Path (Get-Location).Path 'worker_identity.json')
    if($env:OBSERVATION_SCENARIO-eq'critical'){
        Start-Sleep -Seconds $seconds
    }else{
        # The worker starts its sleep after loading pwsh. Matching parent and
        # worker sleeps do not establish completion, especially under a gate.
        $worker.WaitForExit()
        if($worker.ExitCode-ne0){throw 'TEST_ONLY owned worker failed'}
    }
}
if ($env:CRASH_SCENARIO -ne 'no_report') {
    $status=if($env:CRASH_SCENARIO -eq 'success'){'PASS'}else{'FAIL'}
    [IO.File]::WriteAllText($env:COMSOL_BOOTSTRAP_REPORT,"STATUS=$status`nERROR=TEST_ONLY task result`n")
}
if($env:CRASH_SCENARIO -eq 'success'){exit 0}else{exit 7}
''', encoding="utf-8")
            events = root / "events.txt"
            wrapper = root / "exercise.ps1"
            wrapper.write_text(r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$OutputEncoding=[Console]::OutputEncoding
Write-Output 'ENCODING_PROBE=中文'
[Console]::Error.WriteLine('ENCODING_PROBE=中文')
$path=Join-Path $PSScriptRoot 'common/comsol/run_comsol_r2025b.ps1'
$text=[IO.File]::ReadAllText($path)
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Start-ComsolLauncherProcess'},$true)
$double=[IO.File]::ReadAllText((Join-Path $PSScriptRoot 'launcher_double.ps1'))
if ($env:CRASH_SCENARIO) {
    # Exercise the actual ProcessStartInfo factory with a real pwsh child;
    # replace only vendor arguments and vendor server cleanup.
    $double=$function.Extent.Text.Replace('function Start-ComsolLauncherProcess','function Start-ControlledChildProcess') + @'

function Start-ComsolLauncherProcess {
    param($FilePath,$Arguments)
    Write-Event 'launch'
    $global:FakeServerLive=$true
    $global:FakeLauncherProcess=Start-ControlledChildProcess -FilePath $FilePath -Arguments @('-NoProfile','-File',(Join-Path $repoRoot 'controlled_child.ps1'))
    Write-Event ("launcher_identity:{0}:{1}" -f $global:FakeLauncherProcess.Id,$global:FakeLauncherProcess.StartTime.ToUniversalTime().Ticks)
    return $global:FakeLauncherProcess
}
function Stop-ComsolAttemptServers {
    param($RootProcessId,$Observation,$Reason)
    Write-Event "server_cleanup:$Reason"
    $global:FakeServerLive=$false
}
'@
}
$text=$text.Substring(0,$function.Extent.StartOffset)+$double+$text.Substring($function.Extent.EndOffset)
if ($env:STAGE_SCENARIO -like 'timeout_*') {
    $text=$text.Replace('$reportDeadline = [DateTime]::UtcNow.AddSeconds($StartupReportTimeoutSeconds)', '$reportDeadline = [DateTime]::UtcNow.AddSeconds(-1)')
}
if ($env:OBSERVATION_SCENARIO) {
    $observeFixture=@'
function Get-CimInstance { throw 'TEST_ONLY forced CIM denial' }
$script:observationClock=[datetimeoffset]::UtcNow
$script:memorySamples=0
function Get-RepositoryUtcNow {
 if($env:OBSERVATION_SCENARIO-in@('critical','transient')){$script:observationClock=$script:observationClock.AddSeconds(8);return $script:observationClock}
 return [datetimeoffset]::UtcNow
}
function Get-RepositoryAvailableMemoryBytes {
 $script:memorySamples++
 if($env:OBSERVATION_SCENARIO-eq'critical'-or($env:OBSERVATION_SCENARIO-eq'transient'-and$script:memorySamples%2-eq1)){return [int64](100MB)}
 return [int64](8GB)
}
if($env:OBSERVATION_SCENARIO-eq'metric_failure'){
 function Write-ResourceUsage {param($Usage,$Path);throw 'TEST_ONLY metrics write failure'}
}
$script:realObserve=${function:Update-RepositoryProcessObservation}
function Update-RepositoryProcessObservation {
 param($Observation,$Sample,[switch]$Final)
 $result=& $script:realObserve @PSBoundParameters
 Write-Event "observation:known=$($result.observation_known):danger=$($result.physical_danger):timer=$($Observation.critical_since)"
 return $result
}
'@
    $anchor=". (Join-Path `$repoRoot 'common\resource_budget_support.ps1')"
    if(-not$text.Contains($anchor)){throw 'Observation import anchor missing'}
    $text=$text.Replace($anchor,$anchor+"`n"+$observeFixture)
}
[IO.File]::WriteAllText($path,$text)
$global:FakeLaunchCount=0
$global:FakeServerLive=$false
$arguments=@{TaskScript=(Join-Path $PSScriptRoot 'task.m');ReportPath=(Join-Path $PSScriptRoot 'logs/report.txt');StartupRetryDelaySeconds=1;RunId='test-resource-stages'}
if($env:STAGE_COMPLETION -eq '1'){$arguments.CompletionPath=Join-Path $PSScriptRoot 'completion.json'}
if($env:OBSERVATION_SCENARIO-in@('ordinary','metric_failure')){
 $arguments.Limits=[pscustomobject]@{wall_clock_seconds=1;process_tree_working_set_bytes=1;transient_run_directory_bytes=1;minimum_system_available_memory_bytes=1;compact_final_retained_bytes=1}
 $arguments.RunDir=$PSScriptRoot;$arguments.UsagePath=Join-Path $PSScriptRoot 'logs/usage.json'
}
if ($env:STAGE_SCENARIO -like 'timeout_warn_*') { $arguments.StartupReportTimeoutAction='warn' }
if ($env:STAGE_SCENARIO -eq 'timeout_stop') { $arguments.StartupReportTimeoutAction='stop'; $arguments.StartupAttempts=1 }
if ($env:STAGE_ASSEMBLY_MODE -ne '') { $arguments.AssemblyScalabilityMode=$env:STAGE_ASSEMBLY_MODE }
if ($env:STAGE_ASSEMBLY_MODE -eq 'matrix') {
    $arguments.ProcessorCount=8
    $arguments.Allocator='native'
}
if ($env:STAGE_SUPPLIED_BUDGET -ne '0') {
    $resources=if ($env:STAGE_SUPPLIED_BUDGET -eq '2') { @('project-extra') } else { @() }
    $arguments.ResourceBudgets=@{solver=@{schema_version=1;unknown_peak=$false;cpu_cores=[int]$env:STAGE_SUPPLIED_BUDGET;memory_bytes=1024;io_slots=0;exclusive_resources=@($resources)}}
}
$sentinel=$null
if($env:OBSERVATION_SCENARIO-eq'critical'){
 $sentinel=Start-Process -FilePath (Get-Process -Id $PID).Path -WindowStyle Hidden -PassThru -ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 60')
}
try { & $path @arguments } finally {
 if($null-ne$sentinel){
  if($sentinel.HasExited){throw 'Physical-danger cleanup stopped an unrelated sibling'}
  Stop-Process -Id $sentinel.Id -Force;$sentinel.WaitForExit()
 }
}
''', encoding="utf-8")
            environment = dict(os.environ, STAGE_SCENARIO=scenario, STAGE_EVENTS=str(events),
                               FAKE_LAUNCHER=str(root / "launcher.exe"), MATLAB_R2025B_ROOT=str(root),
                               STAGE_SUPPLIED_BUDGET=str(int(supplied_budget)),
                               STAGE_ASSEMBLY_MODE=assembly_mode or '',
                               CRASH_SCENARIO=crash_scenario or '', OBSERVATION_SCENARIO=observation_scenario or '')
            environment.update(STAGE_COMPLETION='1' if completion else '0', STAGE_RELEASE=release)
            if crash_scenario:
                environment["FAKE_LAUNCHER"] = str(shutil.which("pwsh"))
            if scenario == 'prelaunch_failure':
                environment['FAKE_LAUNCHER'] = str(root / 'missing.exe')
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(wrapper)], cwd=root, env=environment,
                capture_output=True, creationflags=self.creation_flags, timeout=30,
            )
            # Capture bytes so locale failures cannot disappear in reader threads.
            # repr preserves every diagnostic byte even if PowerShell regresses.
            output = repr(completed.stdout) + "\n" + repr(completed.stderr)
            probe = "ENCODING_PROBE=中文".encode("utf-8")
            self.assertIn(probe, completed.stdout, output)
            self.assertIn(probe, completed.stderr, output)
            entries = events.read_text(encoding="utf-8-sig").splitlines() if events.exists() else []
            if completion:
                receipt = json.loads((root / 'completion.json').read_text(encoding='utf-8'))
                self.assertEqual(receipt['schema_version'], 1)
                self.assertEqual(receipt['role'], 'comsol_launcher_completion')
                self.assertEqual(receipt['run_id'], 'test-resource-stages')
                self.assertEqual(len(receipt['operations']), 0 if scenario == 'prelaunch_failure' else 1)
                for operation in receipt['operations']:
                    self.assertTrue(operation['observation']['exit_confirmed'])
                    self.assertIsInstance(operation['observation']['returncode'], int)
                    self.assertGreater(operation['observation']['process_id'], 0)
                    self.assertGreater(operation['observation']['process_started_at_utc_ticks'], 0)
                    if crash_scenario:
                        identities = [entry.split(':')[1:] for entry in entries if entry.startswith('launcher_identity:')]
                        self.assertEqual(identities, [[str(operation['observation']['process_id']), str(operation['observation']['process_started_at_utc_ticks'])]])
                self.assertEqual(receipt['host_release']['token'], 'isolated-test')
                self.assertEqual(receipt['host_release']['inherited'], release == 'inherited')
                if release == 'error':
                    self.assertEqual(receipt['host_release']['error'], 'TEST_ONLY release failed')
                elif release == 'inherited':
                    self.assertIsNone(receipt['host_release']['result'])
                else:
                    self.assertEqual(receipt['host_release']['result']['status'], release or 'released')
                self.assertEqual(list(root.glob('completion.json.*.tmp')), [])
            if observation_scenario:
                output += "\nOBSERVATION_EVENTS=" + repr(entries)
            if observation_scenario:
                # The owned worker must have finished or been stopped with its launcher.
                # PID reuse is not evidence that the original worker is live.
                probe = subprocess.run(["pwsh", "-NoProfile", "-Command",
                    "$ErrorActionPreference='Stop';$identity=Get-Content ./worker_identity.json -Raw|ConvertFrom-Json;"
                    "$worker=Get-Process -Id $identity.process_id -ErrorAction SilentlyContinue;"
                    "if($null-ne$worker-and-not$worker.HasExited){"
                    "try{$ticks=$worker.StartTime.ToUniversalTime().Ticks}catch{if($worker.HasExited){exit 0};throw};"
                    "if($ticks-eq$identity.started_at_utc_ticks){"
                    "Write-Output \"OWNED_WORKER_STILL_LIVE PID=$($worker.Id) START_TICKS=$ticks\";exit 1}};exit 0"],
                    cwd=root, capture_output=True, timeout=15, check=False)
                self.assertEqual(probe.returncode, 0, output + "\nWORKER_PROBE=" + repr(probe.stdout) + repr(probe.stderr))
                self.assertEqual((root / "logs/usage.json").exists(), observation_scenario == "ordinary")
            if crash_scenario:
                facts = json.loads((root / "child_facts.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(Path(facts["working_directory"]).resolve(), root.resolve())
                name = f"hs_err_pid{facts['pid']}.log"
                source, destination = root / name, root / "logs" / name
                expected = b"TEST_ONLY owned log\r\n" + bytes(range(256))
                if crash_scenario in {"old", "conflict"}:
                    self.assertEqual(source.read_bytes(), expected)
                    if crash_scenario == "conflict":
                        self.assertEqual(destination.read_bytes(), b"TEST_ONLY existing destination")
                    else:
                        self.assertFalse(destination.exists())
                else:
                    self.assertFalse(source.exists())
                    self.assertEqual(destination.read_bytes(), expected)
            return completed.returncode, entries, output

    def test_completion_receipt_keeps_native_and_actual_release_separate(self) -> None:
        for release in ('', 'retained', 'error', 'inherited'):
            with self.subTest(release=release):
                code, _, output = self.run_scenario('success', completion=True, release=release)
                self.assertEqual(code == 0, release in ('', 'inherited'), output)

    def test_completion_release_error_preserves_original_task_failure(self) -> None:
        code, _, output = self.run_scenario('task_failure', completion=True, release='error')
        self.assertNotEqual(code, 0, output)
        self.assertIn('R2025b LiveLink task failed', output)
        self.assertIn('COMSOL_CLOSEOUT_ERROR=TEST_ONLY release failed', output)

    def test_completion_receipt_records_real_child_exit_and_no_fictitious_launch(self) -> None:
        code, _, output = self.run_scenario('success', crash_scenario='success', completion=True)
        self.assertEqual(code, 0, output)
        code, _, output = self.run_scenario('task_failure', crash_scenario='failure', completion=True)
        self.assertNotEqual(code, 0, output)
        code, _, output = self.run_scenario('prelaunch_failure', completion=True)
        self.assertNotEqual(code, 0, output)
        self.assertIn('COMSOL MATLAB launcher not found', output)

    def test_actual_server_cleanup_requires_owned_ancestry_and_retained_creation(self) -> None:
        """Role candidates are inert pwsh PIDs; ancestry and stop operations are real."""
        for scenario in ("owned", "stale_identity", "orphan", "observation_failure"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                launcher = root / "TEST_ONLY_launcher.ps1"
                facts, release = root / "worker.json", root / "release"
                launcher.write_text(f"""
$worker=Start-Process -FilePath (Get-Process -Id $PID).Path -WindowStyle Hidden -PassThru -ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 30')
@{{pid=$worker.Id;started=$worker.StartTime.ToUniversalTime().Ticks}}|ConvertTo-Json|Set-Content -LiteralPath '{facts}'
$deadline=[DateTime]::UtcNow.AddSeconds(20)
while(-not(Test-Path -LiteralPath '{release}')){{if([DateTime]::UtcNow-ge$deadline){{throw 'TEST_ONLY launcher release timed out'}};Start-Sleep -Milliseconds 20}}
""", encoding="utf-8")
                script = f"""
$ErrorActionPreference='Stop'
. '{ROOT / 'common/resource_budget_support.ps1'}'
function Get-CimInstance {{throw 'TEST_ONLY forced CIM denial'}}
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('{ROOT / 'common/comsol/run_comsol_r2025b.ps1'}',[ref]$tokens,[ref]$errors)
$definition=$ast.Find({{param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Stop-ComsolAttemptServers'}},$true)
. ([scriptblock]::Create($definition.Extent.Text))
$exe=(Get-Process -Id $PID).Path
$ownedLauncher=Start-Process -FilePath $exe -WindowStyle Hidden -PassThru -ArgumentList @('-NoProfile','-File','{launcher}')
$sibling=Start-Process -FilePath $exe -WindowStyle Hidden -PassThru -ArgumentList @('-NoProfile','-Command','Start-Sleep -Seconds 30')
$worker=$null
try{{
 $deadline=[DateTime]::UtcNow.AddSeconds(10)
 while(-not(Test-Path -LiteralPath '{facts}')){{if([DateTime]::UtcNow-ge$deadline){{throw 'TEST_ONLY worker facts missing'}};Start-Sleep -Milliseconds 20}}
 $workerFact=Get-Content -LiteralPath '{facts}' -Raw|ConvertFrom-Json
 $worker=Get-Process -Id $workerFact.pid
 $script:serverRoleCandidates=@($worker.Id,$sibling.Id)
 function Get-ComsolServerProcessIds {{$script:serverRoleCandidates}}
 $observation=@{{tracked_ticks=@{{([string]$ownedLauncher.Id)=$ownedLauncher.StartTime.ToUniversalTime().Ticks}}}}
 if('{scenario}'-ne'owned'){{$observation.tracked_ticks[[string]$worker.Id]=[int64]$workerFact.started}}
 if('{scenario}'-eq'stale_identity'){{$observation.tracked_ticks[[string]$worker.Id]=[int64]$workerFact.started-1}}
 if('{scenario}'-eq'orphan'){{Set-Content -LiteralPath '{release}' -Value release;$ownedLauncher.WaitForExit();if($worker.HasExited){{throw 'Worker did not outlive its launcher'}}}}
 if('{scenario}'-eq'observation_failure'){{function Get-ManagedSolverProcessSample {{throw 'TEST_ONLY ancestry observation unavailable'}}}}
 if('{scenario}'-eq'observation_failure'){{
  try{{try{{throw 'TEST_ONLY original scientific failure'}}finally{{Stop-ComsolAttemptServers -RootProcessId $ownedLauncher.Id -Observation $observation -Reason 'task failure'}}}}
  catch{{if($_.Exception.Message-ne'TEST_ONLY original scientific failure'){{throw}}}}
 }}else{{Stop-ComsolAttemptServers -RootProcessId $ownedLauncher.Id -Observation $observation -Reason 'task completion'}}
 if($sibling.HasExited){{throw 'Unrelated same-role candidate was stopped'}}
 if('{scenario}'-eq'stale_identity'){{
  if($worker.HasExited-or$observation.tracked_ticks[[string]$worker.Id]-ne([int64]$workerFact.started-1)){{throw 'Stale creation identity was overwritten or stopped'}}
 }}elseif(-not$worker.HasExited){{throw 'Verified owned server candidate remains alive'}}
 'TEST_ONLY_SERVER_CLEANUP=PASS'
}}finally{{
 foreach($process in @($ownedLauncher,$worker,$sibling)){{if($null-ne$process-and-not$process.HasExited){{$process.Kill($true);$process.WaitForExit()}}}}
}}
"""
                result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=30, check=False, creationflags=self.creation_flags)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("TEST_ONLY_SERVER_CLEANUP=PASS", result.stdout)

    def test_owned_jvm_log_moves_raw_bytes_after_success_failure_and_no_report(self) -> None:
        for scenario in ("success", "failure", "no_report"):
            with self.subTest(scenario=scenario):
                code, events, output = self.run_scenario("success", crash_scenario=scenario)
                self.assertEqual(code == 0, scenario == "success", output)
                self.assertEqual(events[-1], "exit")
                if scenario == "failure":
                    self.assertIn("R2025b LiveLink task failed", output)

    def test_owned_native_observation_warns_or_stops_only_sustained_danger(self) -> None:
        for observation in ("ordinary", "transient", "critical"):
            with self.subTest(observation=observation):
                code, events, output = self.run_scenario("success", crash_scenario="success",
                                                       observation_scenario=observation)
                self.assertEqual(code == 0, observation != "critical", output)
                self.assertEqual(events.count("launch"), 1)
                if observation == "critical":
                    self.assertIn("COMSOL_PHYSICAL_MEMORY_DANGER", output)
                    self.assertFalse(any(e.startswith("server_cleanup:") for e in events))
                if observation == "ordinary":
                    self.assertIn("RESOURCE_BUDGET_WARNING=wall_clock_seconds", output)
                    self.assertIn("RESOURCE_BUDGET_WARNING=process_tree_working_set_bytes", output)

    def test_metrics_failure_keeps_native_scientific_failure(self) -> None:
        code, events, output = self.run_scenario("success", crash_scenario="failure",
                                               observation_scenario="metric_failure")
        self.assertNotEqual(code, 0, output)
        self.assertIn("R2025b LiveLink task failed", output)
        self.assertIn("RESOURCE_OBSERVATION_WARNING", output)
        self.assertEqual(events.count("launch"), 1)

    def test_unowned_or_conflicting_jvm_log_preserves_source_and_task_failure(self) -> None:
        for scenario in ("old", "conflict"):
            with self.subTest(scenario=scenario):
                code, events, output = self.run_scenario("success", crash_scenario=scenario)
                self.assertNotEqual(code, 0, output)
                self.assertIn("R2025b LiveLink task failed", output)
                self.assertEqual(events[-1], "exit")
                self.assertEqual("COMSOL_JVM_CRASH_LOG_NOT_MOVED" in output, scenario == "conflict")

    def test_default_assembly_mode_does_not_override_comsol(self) -> None:
        for mode in (None, 'auto'):
            with self.subTest(mode=mode):
                code, events, output = self.run_scenario('assembly_arguments', assembly_mode=mode)
                self.assertEqual(code, 0, output)
                arguments = json.loads(next(e.split(':', 1)[1] for e in events
                                            if e.startswith('launcher_arguments:')))
                self.assertNotIn('-memoptassem', arguments)
                self.assertEqual(arguments[0:3], ['-login', 'auto', 'matlab'])

    def test_explicit_assembly_modes_are_forwarded_before_target(self) -> None:
        for mode in ('off', 'matrix', 'vector', 'on'):
            with self.subTest(mode=mode):
                code, events, output = self.run_scenario('assembly_arguments', assembly_mode=mode)
                self.assertEqual(code, 0, output)
                arguments = json.loads(next(e.split(':', 1)[1] for e in events
                                            if e.startswith('launcher_arguments:')))
                expected = ['-memoptassem', mode, '-login', 'auto', 'matlab']
                if mode == 'matrix':
                    expected = ['-np', '8', '-alloc', 'native'] + expected
                self.assertEqual(arguments[:len(expected)], expected)
                self.assertEqual(arguments.count('-memoptassem'), 1)
                self.assertEqual(events[-1], 'exit')

    def test_invalid_assembly_mode_fails_before_resource_admission(self) -> None:
        code, events, output = self.run_scenario('assembly_arguments', assembly_mode='invalid')
        self.assertNotEqual(code, 0, output)
        self.assertEqual(events, [])
        self.assertIn('AssemblyScalabilityMode', output)

    def test_success_registers_before_postprocess_and_releases(self) -> None:
        code, events, output = self.run_scenario("success")
        self.assertEqual(code, 0, output)
        self.assertEqual(events, ["enter:prepare:unknown=True", "solver_locks:comsol-server-session",
                                  "update:solver:unknown=True", "launch",
                                  "register:999999", "receive", "server_cleanup:task completion",
                                  "update:postprocess:unknown=True", "exit"])

    def test_explicit_solver_budget_is_forwarded(self) -> None:
        for supplied, locks in ((1, "comsol-server-session"), (2, "project-extra,comsol-server-session")):
            with self.subTest(budget=supplied):
                code, events, output = self.run_scenario("success", supplied_budget=supplied)
                self.assertEqual(code, 0, output)
                self.assertIn("update:solver:unknown=False", events)
                self.assertIn("solver_locks:" + locks, events)
                self.assertLess(events.index("update:solver:unknown=False"), events.index("launch"))

    def test_registration_failure_stops_only_started_launcher_and_releases(self) -> None:
        code, events, _ = self.run_scenario("registration_failure")
        self.assertNotEqual(code, 0)
        self.assertEqual(events[-5:], ["register:999999", "kill", "wait",
                                      "server_cleanup:resource registration failure", "exit"])
        self.assertFalse(any("postprocess" in event for event in events))

    def test_compute_failure_does_not_retry_and_releases(self) -> None:
        code, events, _ = self.run_scenario("task_failure")
        self.assertNotEqual(code, 0)
        self.assertEqual(events.count("launch"), 1)
        self.assertLess(events.index("server_cleanup:task failure"), events.index("update:postprocess:unknown=True"))
        self.assertEqual(events[-1], "exit")

    def test_cleanup_failure_keeps_solver_budget_until_exit(self) -> None:
        code, events, _ = self.run_scenario("cleanup_failure")
        self.assertNotEqual(code, 0)
        self.assertFalse(any("update:postprocess" in event for event in events))
        self.assertEqual(events[-1], "exit")

    def test_retry_reenters_prepare_then_solver(self) -> None:
        code, events, output = self.run_scenario("startup_retry")
        self.assertEqual(code, 0, output)
        self.assertEqual(events.count("launch"), 2)
        self.assertEqual(events.count("update:prepare:unknown=True"), 1)
        self.assertEqual(events.count("update:solver:unknown=True"), 2)
        self.assertEqual(events[-1], "exit")

    def test_running_report_allows_long_task_to_reach_pass(self) -> None:
        code, events, output = self.run_scenario("running_then_pass")
        self.assertEqual(code, 0, output)
        self.assertIn("wait", events)
        self.assertEqual(events.count("launch"), 1)
        self.assertIn("server_cleanup:task completion", events)

    def test_wait_loops_poll_only_process_then_refresh_terminal_lease(self) -> None:
        for scenario, wait_event in (
            ("running_then_pass", "wait"), ("timeout_warn_pass", "refresh_live"),
        ):
            with self.subTest(scenario=scenario):
                code, events, output = self.run_scenario(scenario)
                self.assertEqual(code, 0, output)
                self.assertIn(wait_event, events)
                self.assertEqual(events.count("receive"), 1)
                self.assertLess(events.index("register:999999"), events.index(wait_event))
                self.assertLess(max(i for i, event in enumerate(events) if event == wait_event),
                                events.index("receive"))
                self.assertLess(events.index("receive"), events.index("server_cleanup:task completion"))
                self.assertEqual(events[-2:], ["update:postprocess:unknown=True", "exit"])

    def test_process_exit_with_running_report_fails_closed(self) -> None:
        code, events, _ = self.run_scenario("running_without_terminal")
        self.assertNotEqual(code, 0)
        self.assertEqual(events.count("launch"), 1)
        self.assertIn("server_cleanup:task failure", events)

    def test_explicit_stop_timeout_stops_launcher(self) -> None:
        code, events, _ = self.run_scenario("timeout_stop")
        self.assertNotEqual(code, 0)
        self.assertIn("kill", events)
        self.assertEqual(events.count("launch"), 1)

    def test_warning_timeout_keeps_same_live_attempt_for_late_report(self) -> None:
        code, events, output = self.run_scenario("timeout_warn_pass")
        self.assertEqual(code, 0, output)
        self.assertNotIn("kill", events)
        self.assertEqual(events.count("launch"), 1)
        self.assertEqual(events.count("refresh_live"), 2)
        self.assertEqual(output.count("continuing the same attempt"), 1)

    def test_warning_timeout_does_not_swallow_real_failure_or_missing_report(self) -> None:
        for scenario in ("timeout_warn_failure", "timeout_warn_missing"):
            with self.subTest(scenario=scenario):
                code, events, output = self.run_scenario(scenario)
                self.assertNotEqual(code, 0, output)
                self.assertNotIn("kill", events)
                self.assertEqual(events.count("launch"), 1)
                self.assertEqual(events[-1], "exit")


class LiveLinkBootstrapContractTests(unittest.TestCase):
    """The bootstrap report separates startup readiness from task completion."""

    def test_running_precedes_task_and_pass_follows_it(self) -> None:
        source = (ROOT / "common/comsol/livelink_r2025b/comsolstartup.m").read_text(encoding="utf-8")
        running = source.index('writeBootstrapReport(bootstrapReportPath, "RUNNING", "")')
        task = source.index("executeComsolTask(bootstrapTaskPath)")
        passed = source.index('writeBootstrapReport(bootstrapReportPath, "PASS", "")')
        self.assertLess(running, task)
        self.assertLess(task, passed)
        self.assertIn(
            'writeBootstrapReport(bootstrapReportPath, "FAIL", getReport(ME, \'extended\'))',
            source,
        )
        self.assertIn("function executeComsolTask(taskPath)", source)
        self.assertIn("run(taskPath);", source)
        self.assertIn("catch reportException", source)
        failure_catch = source.index("catch ME")
        nonzero_exit = source.index("exit(2)", failure_catch)
        self.assertGreater(nonzero_exit, source.index("catch reportException", failure_catch))


@unittest.skipUnless(os.name == "nt", "CREATE_NO_WINDOW is Windows-specific")
class HiddenLiveLinkResourceStageTests(LiveLinkResourceStageTests):
    """Repeat every boundary under the hidden process mode used by repository gates."""

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)


if __name__ == "__main__":
    unittest.main()
