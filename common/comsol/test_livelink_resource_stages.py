"""Exercise LiveLink scheduling boundaries with isolated process and scheduler doubles."""

from __future__ import annotations

import os
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
    return @{token='isolated-test'}
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
function Exit-HostResourceStage { param($Lease) Write-Event 'exit' }
function Receive-HostResourceStage { param($Lease) }
'''

LAUNCHER = r'''
function Start-ComsolLauncherProcess {
    param($FilePath,$Arguments)
    $global:FakeLaunchCount++
    $global:FakeServerLive=$true
    Write-Event 'launch'
    $reportText = "STATUS=PASS`n"
    if ($env:STAGE_SCENARIO -eq 'task_failure') {
        $reportText = "STATUS=FAIL`nERROR=Study Compute failed`n"
    }
    if ($env:STAGE_SCENARIO -eq 'startup_retry' -and $global:FakeLaunchCount -eq 1) {
        $reportText = "STATUS=FAIL`nERROR=mphload mphopen Not connected to a server`n"
    }
    [IO.File]::WriteAllText($env:COMSOL_BOOTSTRAP_REPORT,$reportText)
    $reader = [pscustomobject]@{}
    $reader | Add-Member ScriptMethod ReadToEndAsync {
        return [Threading.Tasks.Task]::FromResult[string]('')
    }
    $process = [pscustomobject]@{
        Id=999999; HasExited=($env:STAGE_SCENARIO -ne 'registration_failure')
        ExitCode=0; StandardOutput=$reader; StandardError=$reader
    }
    $process | Add-Member ScriptMethod Kill { param($Tree) Write-Event 'kill'; $this.HasExited=$true }
    $process | Add-Member ScriptMethod WaitForExit { Write-Event 'wait' }
    return $process
}
function Stop-ComsolAttemptServers {
    param($Before,$Reason)
    Write-Event "server_cleanup:$Reason"
    if ($env:STAGE_SCENARIO -eq 'cleanup_failure') { throw 'server cleanup failed' }
    $global:FakeServerLive=$false
}
'''


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
class LiveLinkResourceStageTests(unittest.TestCase):
    """Keep real launcher control flow; replace only external effects in a temp tree."""

    creation_flags = 0

    def run_scenario(self, scenario: str, *, supplied_budget: int = 0) -> tuple[int, list[str], str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            comsol = root / "common" / "comsol"
            comsol.mkdir(parents=True)
            (root / "common" / "require_powershell7.ps1").write_text("", encoding="utf-8")
            (root / "common" / "host_execution_lease.ps1").write_text(SCHEDULER, encoding="utf-8")
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
$text=$text.Substring(0,$function.Extent.StartOffset)+$double+$text.Substring($function.Extent.EndOffset)
$ast=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-ComsolServerProcessIds'},$true)
$text=$text.Substring(0,$function.Extent.StartOffset)+'function Get-ComsolServerProcessIds { Write-Event "servers_snapshot"; return @() }'+$text.Substring($function.Extent.EndOffset)
[IO.File]::WriteAllText($path,$text)
$global:FakeLaunchCount=0
$global:FakeServerLive=$false
$arguments=@{TaskScript=(Join-Path $PSScriptRoot 'task.m');ReportPath=(Join-Path $PSScriptRoot 'report.txt');StartupRetryDelaySeconds=1;RunId='test-resource-stages'}
if ($env:STAGE_SUPPLIED_BUDGET -ne '0') {
    $resources=if ($env:STAGE_SUPPLIED_BUDGET -eq '2') { @('project-extra') } else { @() }
    $arguments.ResourceBudgets=@{solver=@{schema_version=1;unknown_peak=$false;cpu_cores=[int]$env:STAGE_SUPPLIED_BUDGET;memory_bytes=1024;io_slots=0;exclusive_resources=@($resources)}}
}
& $path @arguments
''', encoding="utf-8")
            environment = dict(os.environ, STAGE_SCENARIO=scenario, STAGE_EVENTS=str(events),
                               FAKE_LAUNCHER=str(root / "launcher.exe"), MATLAB_R2025B_ROOT=str(root),
                               STAGE_SUPPLIED_BUDGET=str(int(supplied_budget)))
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
            return completed.returncode, entries, output

    def test_success_registers_before_postprocess_and_releases(self) -> None:
        code, events, output = self.run_scenario("success")
        self.assertEqual(code, 0, output)
        self.assertEqual(events, ["enter:prepare:unknown=True", "solver_locks:comsol-server-session",
                                  "update:solver:unknown=True", "servers_snapshot", "launch",
                                  "register:999999", "server_cleanup:task completion",
                                  "update:postprocess:unknown=True", "exit"])

    def test_explicit_solver_budget_is_forwarded(self) -> None:
        for supplied, locks in ((1, "comsol-server-session"), (2, "project-extra,comsol-server-session")):
            with self.subTest(budget=supplied):
                code, events, output = self.run_scenario("success", supplied_budget=supplied)
                self.assertEqual(code, 0, output)
                self.assertIn("update:solver:unknown=False", events)
                self.assertIn("solver_locks:" + locks, events)
                self.assertLess(events.index("update:solver:unknown=False"), events.index("servers_snapshot"))
                self.assertLess(events.index("servers_snapshot"), events.index("launch"))

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


@unittest.skipUnless(os.name == "nt", "CREATE_NO_WINDOW is Windows-specific")
class HiddenLiveLinkResourceStageTests(LiveLinkResourceStageTests):
    """Repeat every boundary under the hidden process mode used by repository gates."""

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)


if __name__ == "__main__":
    unittest.main()
