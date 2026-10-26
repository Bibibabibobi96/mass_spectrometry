"""Process-lifecycle regressions for budgeted gate orchestration.

Tests use mocked entry points or an isolated SQLite ledger with fixture telemetry;
they never touch the host ledger. Atomic accounting has separate scheduler tests.
"""

from __future__ import annotations

import os
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "common/parallel_gate_support.ps1"


def quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell Core is required")
class ParallelGateSupportTests(unittest.TestCase):
    def test_adapter_uses_real_facade_with_isolated_ledger(self) -> None:
        with tempfile.TemporaryDirectory(prefix="parallel_gate_ledger_") as directory:
            ledger = Path(directory) / "isolated.sqlite3"
            completed = self.run_script(f"""
. {quote(ROOT / 'common/host_execution_lease.ps1')}
. {quote(SUPPORT)}
$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH = {quote(ledger)}
$env:SIMULATION_PYTHON_EXE = {quote(sys._base_executable)}
# Deterministic resource observations; no claim about the host's actual load.
function Get-HostResourceSnapshot {{
    return @{{ complete=$true; logical_processors=4; cpu_percent=0;
        total_memory_bytes=32GB; available_memory_bytes=24GB; io_pressure=$false;
        processes=@(@{{pid=$PID;parent_pid=0;started='fixture-owner';memory_bytes=64MB}}) }}
}}
# Use the real central budget policy as well as the real facade.
$script:performed = 0
Invoke-ResourceBudgetedGateAction -Name 'outer-fixture' -Action {{
    Invoke-ResourceBudgetedGateAction -Name 'nested-fixture' -Action {{ $script:performed += 1 }}
}}
try {{
    Invoke-ResourceBudgetedGateAction -Name 'failed-fixture' -Action {{ throw 'fixture failure' }}
    throw 'missing failure'
}} catch {{ if ($_.Exception.Message -ne 'fixture failure') {{ throw }} }}
$snapshot = Get-HostResourceStatus -StatePath {quote(ledger)}
if (@($snapshot.records).Count -ne 0) {{ throw 'ledger reservation leaked' }}
if ($env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN) {{ throw 'token environment leaked' }}
if ($script:performed -ne 1) {{ throw 'nested action did not execute once' }}
""")
            self.assertIn("INHERITED=True", completed.stdout)
            self.assertTrue(ledger.exists())

    def test_plan_only_does_not_create_resource_ledger(self) -> None:
        with tempfile.TemporaryDirectory(prefix="parallel_gate_plan_") as directory:
            ledger = Path(directory) / "isolated.sqlite3"
            completed = self.run_script(f"""
$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH = {quote(ledger)}
$env:SIMULATION_PYTHON_EXE = 'prior-runtime'
& {quote(ROOT / 'common/verify_changed.ps1')} -PythonExe {quote(sys._base_executable)} `
    -ChangedPath README.md -PlanOnly
if ($LASTEXITCODE -ne 0) {{ throw 'plan failed' }}
if ($env:SIMULATION_PYTHON_EXE -ne 'prior-runtime') {{ throw 'runtime environment leaked' }}
""")
            self.assertIn("CHANGED_GATE_PLAN=PASS", completed.stdout)
            self.assertFalse(ledger.exists(), "read-only planning acquired resources")

    def test_gate_runtime_transport_and_restore_on_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="parallel_gate_runtime_") as directory:
            ledger = Path(directory) / "isolated.sqlite3"
            request = Path(directory) / "request.json"
            request.write_text(json.dumps({
                "python_exe": sys._base_executable,
                "changed_paths": ["README.md"], "full_scope": False,
            }), encoding="utf-8")
            for name, extra, expected in (
                ("verify_changed.ps1", f"-InternalRequestPath {quote(request)}",
                 "Unknown changed-gate stage: fixture_missing"),
                ("verify_repository_integration.ps1", "",
                 "Unknown repository integration stage: fixture_missing"),
            ):
                with self.subTest(gate=name):
                    self.run_script(f"""
$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH = {quote(ledger)}
$env:SIMULATION_PYTHON_EXE = 'prior-runtime'
$global:observedRuntime = $null
# Observe the actual entry script after runtime validation, before any admission.
$breakpoint = Set-PSBreakpoint -Command Resolve-GateConcurrency -Action {{
    $global:observedRuntime = $env:SIMULATION_PYTHON_EXE
}}
try {{
    try {{
        & {quote(ROOT / 'common' / name)} -PythonExe {quote(sys._base_executable)} `
            -InternalStage fixture_missing {extra}
        throw 'missing stage error'
    }} catch {{ if ($_.Exception.Message -ne {quote(expected)}) {{ throw }} }}
}} finally {{ Remove-PSBreakpoint -Breakpoint $breakpoint }}
if ($global:observedRuntime -ne {quote(sys._base_executable)}) {{
    throw 'custom runtime was not transported before admission'
}}
if ($env:SIMULATION_PYTHON_EXE -ne 'prior-runtime') {{ throw 'runtime environment leaked' }}
""")
            self.assertFalse(ledger.exists(), "invalid stages acquired resources")

    def run_script(self, text: str) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment.pop("MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN", None)
        completed = subprocess.run(
            [shutil.which("pwsh"), "-NoProfile", "-Command", text + "\nexit 0\n"],
            cwd=ROOT, env=environment, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        return completed

    def prelude(self) -> str:
        return f"""
. {quote(SUPPORT)}
function Get-HostResourceBudget {{ param($Stage, $Role) return @{{ stage=$Stage; role=$Role }} }}
function Enter-HostResourceStage {{ param($Stage, $Role, $Budget)
    if ($Budget.stage -ne $Stage -or $Budget.role -ne $Role) {{ throw 'wrong budget' }}
    $script:acquired += 1
    return @{{ token='isolated-mock' }}
}}
function Exit-HostResourceStage {{ param($Lease)
    if ($Lease.token -ne 'isolated-mock') {{ throw 'wrong lease' }}
    $script:released += 1
}}
$script:acquired = 0
$script:released = 0
"""

    def test_logged_stage_flushes_while_alive_and_closes_after_success_or_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="parallel_gate_stream_") as directory:
            root = Path(directory)
            emitter = root / "emitter.py"
            emitter.write_text(
                "import sys\nprint('LATER_STDOUT', flush=True)\n"
                "print('NATIVE_STDERR', file=sys.stderr, flush=True)\n",
                encoding="utf-8", newline="\n",
            )
            for failed in (False, True):
                with self.subTest(failed=failed):
                    log = root / f"stage_{failed}.log"
                    release = root / f"release_{failed}"
                    script = root / f"stage_{failed}.ps1"
                    script.write_text(f"""
. {quote(SUPPORT)}
$okay = Invoke-LoggedGateStage -Name fixture -LogPath {quote(log)} -Action {{
    Write-Output 'FIRST_LINE'
    while (-not (Test-Path -LiteralPath {quote(release)})) {{ Start-Sleep -Milliseconds 20 }}
    & {quote(sys.executable)} {quote(emitter)}
    if ($LASTEXITCODE -ne 0) {{ throw 'native emitter failed' }}
    {"throw 'EXPECTED_STAGE_ERROR'" if failed else "Write-Output 'FINAL_LINE'"}
}}
if ($okay -ne ${str(not failed).lower()}) {{ throw 'stage success result changed' }}
$exclusive = [IO.File]::Open({quote(log)}, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
$exclusive.Dispose()
Write-Output "STAGE_RESULT=$okay"
exit 0
""", encoding="utf-8", newline="\n")
                    process = subprocess.Popen(
                        [shutil.which("pwsh"), "-NoProfile", "-File", str(script)],
                        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, encoding="utf-8", errors="replace",
                    )
                    try:
                        deadline = time.monotonic() + 15
                        text = ""
                        while process.poll() is None and time.monotonic() < deadline:
                            if log.exists():
                                text = log.read_text(encoding="utf-8")
                                if "FIRST_LINE" in text:
                                    break
                            time.sleep(0.025)
                        self.assertIn("FIRST_LINE", text)
                        self.assertIsNone(process.poll(), "stage exited before live log observation")
                        self.assertNotIn("LATER_STDOUT", text)
                    finally:
                        release.touch()
                        stdout, stderr = process.communicate(timeout=20)
                    self.assertEqual(process.returncode, 0, stdout + stderr)
                    text = log.read_text(encoding="utf-8")
                    self.assertLess(text.index("FIRST_LINE"), text.index("LATER_STDOUT"))
                    self.assertIn("NATIVE_STDERR", text)
                    self.assertIn("EXPECTED_STAGE_ERROR" if failed else "FINAL_LINE", text)
                    self.assertNotIn("FIRST_LINE", stdout, "live stage output bypassed stable replay")

    def test_action_releases_on_success_and_failure(self) -> None:
        self.run_script(self.prelude() + """
function Invoke-TestStage {
    param([scriptblock]$Action)
    Invoke-ResourceBudgetedGateAction -Name 'first' -Action { & $Action }
}
Invoke-TestStage -Action { 'work' }
try {
    Invoke-ResourceBudgetedGateAction -Name 'second' -Action { throw 'expected failure' }
    throw 'missing failure'
} catch {
    if ($_.Exception.Message -ne 'expected failure') { throw }
}
if ($script:acquired -ne 2 -or $script:released -ne 2) { throw 'reservation leaked' }
""")

    def test_ruff_worker_limit_restores_environment_after_failure(self) -> None:
        self.run_script(self.prelude() + """
$env:RAYON_NUM_THREADS = '3'
foreach ($stage in @('ruff_all', 'ruff_changed_python')) {
    try {
        Invoke-ResourceBudgetedGateAction -Name $stage -Action {
            if ($env:RAYON_NUM_THREADS -ne '1') { throw 'worker limit missing' }
            throw 'fixture failure'
        }
    } catch { if ($_.Exception.Message -ne 'fixture failure') { throw } }
    if ($env:RAYON_NUM_THREADS -ne '3') { throw 'worker environment leaked' }
}
Remove-Item Env:RAYON_NUM_THREADS
Invoke-ResourceBudgetedGateAction -Name 'ruff_all' -Action {
    if ($env:RAYON_NUM_THREADS -ne '1') { throw 'worker limit missing' }
}
if ($env:RAYON_NUM_THREADS) { throw 'unset worker environment not restored' }
""")

    @unittest.skipUnless(os.name == "nt", "Windows console code-page inheritance contract")
    def test_stage_utf8_reaches_python_child_powershell_and_restores_cp936(self) -> None:
        with tempfile.TemporaryDirectory(prefix="parallel_gate_encoding_") as directory:
            root = Path(directory)
            child = root / "child.ps1"
            child.write_text(
                "[Console]::Out.WriteLine('中文标准输出')\n"
                "[Console]::Error.WriteLine('中文错误输出')\nexit 7\n",
                encoding="utf-8", newline="\n",
            )
            probe = root / "probe.py"
            probe.write_text("""import subprocess, sys
result = subprocess.run([sys.argv[1], '-NoProfile', '-File', sys.argv[2]],
    cwd=sys.argv[3], capture_output=True, timeout=15, check=False)
assert result.returncode == 7
stdout, stderr = result.stdout, result.stderr
if sys.argv[4] == 'before':
    assert stdout.decode('cp936').strip() == '中文标准输出'
    assert stderr.decode('cp936').strip() == '中文错误输出'
    try:
        stderr.decode('utf-8')
    except UnicodeDecodeError:
        pass
    else:
        raise AssertionError('CP936 reproduction did not reach the child')
else:
    assert stdout == '中文标准输出\\r\\n'.encode('utf-8')
    assert stderr == '中文错误输出\\r\\n'.encode('utf-8')
print('ENCODING_PROBE=' + sys.argv[4])
""", encoding="utf-8", newline="\n")
            completed = self.run_script(self.prelude() + f"""
$prior = [Console]::OutputEncoding
try {{
    [Console]::OutputEncoding = [Text.Encoding]::GetEncoding(936)
    & {quote(sys.executable)} {quote(probe)} {quote(shutil.which('pwsh'))} {quote(child)} {quote(root)} before
    if ($LASTEXITCODE -ne 0) {{ throw 'CP936 reproduction failed' }}
    foreach ($failed in @($false, $true)) {{
        try {{
            Invoke-ResourceBudgetedGateAction -Name outer -Action {{
                if ([Console]::OutputEncoding.CodePage -ne 65001) {{ throw 'outer is not UTF8' }}
                try {{
                    Invoke-ResourceBudgetedGateAction -Name nested -Action {{
                        & {quote(sys.executable)} {quote(probe)} {quote(shutil.which('pwsh'))} {quote(child)} {quote(root)} stage
                        if ($LASTEXITCODE -ne 0) {{ throw 'UTF8 transport failed' }}
                        if ($failed) {{ throw 'expected encoding fixture failure' }}
                    }}
                }} finally {{
                    if ([Console]::OutputEncoding.CodePage -ne 65001) {{ throw 'nested restore failed' }}
                }}
            }}
            if ($failed) {{ throw 'failure was swallowed' }}
        }} catch {{
            if (-not $failed -or $_.Exception.Message -ne 'expected encoding fixture failure') {{ throw }}
        }}
        if ([Console]::OutputEncoding.CodePage -ne 936) {{ throw 'outer restore failed' }}
    }}
    if ($script:acquired -ne 4 -or $script:released -ne 4) {{ throw 'encoding fixture lease leaked' }}
}} finally {{ [Console]::OutputEncoding = $prior }}
""")
            self.assertEqual(completed.stdout.count("ENCODING_PROBE=before"), 1)
            self.assertEqual(completed.stdout.count("ENCODING_PROBE=stage"), 2)

    def test_group_unwinding_waits_for_its_child_before_cleanup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="parallel_gate_fixture_") as directory:
            child = Path(directory) / "child.ps1"
            child.write_text(
                "param($InternalStage, $InternalLogPath)\nStart-Sleep -Seconds 1\n",
                encoding="utf-8",
            )
            started = time.monotonic()
            self.run_script(self.prelude() + f"""
$script:started = $null
function Start-Process {{
    param($FilePath, $ArgumentList, $WindowStyle, [switch]$PassThru)
    if ($null -ne $script:started) {{ throw 'injected second launch failure' }}
    $script:started = Microsoft.PowerShell.Management\Start-Process @PSBoundParameters
    $script:childId = $script:started.Id
    return $script:started
}}
$items = @(@{{Name='first';Run=$true}}, @{{Name='second';Run=$true}})
try {{
    Invoke-IndependentGateStageGroup -Items $items -MaxConcurrency 2 `
        -GateScriptPath {quote(child)} -PythonExe {quote(sys.executable)} `
        -ChildBaseArguments @() -TempNamePrefix 'parallel_gate_test_' `
        -FailureMessage 'test group failed' -InvokeInlineStage {{ throw 'unexpected inline' }} `
        -InvokeSkipStage {{ throw 'unexpected skip' }}
    throw 'missing launch failure'
}} catch {{
    if ($_.Exception.Message -ne 'injected second launch failure') {{ throw }}
}}
if ($null -eq $script:started) {{ throw 'first child never started' }}
# The Process object has been disposed; natural completion precedes cleanup.
if (Get-Process -Id $script:childId -ErrorAction SilentlyContinue) {{ throw 'child survived' }}
""")
            self.assertGreaterEqual(time.monotonic() - started, 0.8)

    def test_nested_group_serializes_inherited_reservation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="parallel_gate_fixture_") as directory:
            child = Path(directory) / "child.ps1"
            child.write_text(
                "param($InternalStage, $InternalLogPath)\n"
                "Start-Sleep -Milliseconds 100\n"
                'Set-Content -LiteralPath $InternalLogPath -Value @($InternalStage, "RECEIVED_LOG_PATH=$InternalLogPath")\n',
                encoding="utf-8",
            )
            completed = self.run_script(self.prelude() + f"""
$env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN = 'isolated-mock-parent'
$items = @(@{{Name='first';Run=$true}}, @{{Name='second';Run=$true}})
Invoke-IndependentGateStageGroup -Items $items -MaxConcurrency 2 `
    -GateScriptPath {quote(child)} -PythonExe {quote(sys.executable)} `
    -ChildBaseArguments @() -TempNamePrefix 'parallel_gate_test_' `
    -FailureMessage 'test group failed' -InvokeInlineStage {{ throw 'unexpected inline' }} `
    -InvokeSkipStage {{ throw 'unexpected skip' }}
""")
            self.assertIn("REASON=inherited_resource_reservation", completed.stdout)
            reported_logs = re.findall(
                r"^GATE_PROCESS=START NAME=(\w+) PID=\d+ LOG_PATH=(.+)$",
                completed.stdout, re.MULTILINE,
            )
            self.assertEqual([name for name, _ in reported_logs], ["first", "second"])
            for _, log_path in reported_logs:
                self.assertIn(f"RECEIVED_LOG_PATH={log_path}", completed.stdout)
            self.assertLess(
                completed.stdout.index("COMPLETE NAME=first"),
                completed.stdout.index("START NAME=second"),
            )


if __name__ == "__main__":
    unittest.main()
