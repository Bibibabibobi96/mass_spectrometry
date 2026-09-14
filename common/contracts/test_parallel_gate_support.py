"""Process-lifecycle regressions for budgeted gate orchestration.

Tests use mocked entry points or an isolated SQLite ledger with fixture telemetry;
they never touch the host ledger. Atomic accounting has separate scheduler tests.
"""

from __future__ import annotations

import os
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
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
function Get-HostResourceBudget {{ param($Stage, $Role)
    return @{{schema_version=1;cpu_cores=1;memory_bytes=256MB;io_slots=0;
        exclusive_resources=@();unknown_peak=$false}}
}}
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

    def test_group_unwinding_terminates_its_child_before_cleanup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="parallel_gate_fixture_") as directory:
            child = Path(directory) / "child.ps1"
            child.write_text(
                "param($InternalStage, $InternalLogPath)\nStart-Sleep -Seconds 60\n",
                encoding="utf-8",
            )
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
# The Process object has been disposed; query the recorded process identity.
if (Get-Process -Id $script:childId -ErrorAction SilentlyContinue) {{ throw 'child survived' }}
""")

    def test_nested_group_serializes_inherited_reservation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="parallel_gate_fixture_") as directory:
            child = Path(directory) / "child.ps1"
            child.write_text(
                "param($InternalStage, $InternalLogPath)\n"
                "Start-Sleep -Milliseconds 100\n"
                "Set-Content -LiteralPath $InternalLogPath -Value $InternalStage\n",
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
            self.assertLess(
                completed.stdout.index("COMPLETE NAME=first"),
                completed.stdout.index("START NAME=second"),
            )


if __name__ == "__main__":
    unittest.main()
