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
    def test_ready_dependencies_fail_fast_and_natural_completion(self) -> None:
        for concurrency, stop, first in ((1, True, 'fail'), (2, True, 'fail'),
                                         (1, False, 'fail'), (2, False, 'fail'),
                                         (2, False, 'pass'), (2, False, 'fallback'),
                                         (2, False, 'launchfail'), (2, False, 'fallback_fail')):
            with self.subTest(concurrency=concurrency, stop=stop, first=first), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                child = root / 'child.ps1'
                child.write_text(r'''
param($Root,$First,$InternalStage,$InternalLogPath)
if($InternalStage-eq'first'-and$First-like'fallback*'){exit 0}
if($InternalStage-eq'first'){
 Start-Sleep -Milliseconds 200
 if($First-eq'pass'){Set-Content -LiteralPath (Join-Path $Root 'first_done') -Value done}
}
if($InternalStage-eq'slow'){Start-Sleep -Milliseconds 500;Set-Content -LiteralPath (Join-Path $Root 'slow_done') -Value done}
if($InternalStage-eq'first'-and$First-eq'fail'){
 Set-Content -LiteralPath $InternalLogPath -Value @('TEST_FAILURE_IMMEDIATE=probe','traceback detail','TEST_FAILURE_IMMEDIATE_END','TEST_DURATION_SECONDS=0.125000 TEST=probe')
 Start-Sleep -Milliseconds 300
}else{Set-Content -LiteralPath $InternalLogPath -Value $InternalStage}
if($InternalStage-eq'dependent'-and-not(Test-Path (Join-Path $Root 'first_done'))){exit 9}
if($InternalStage-eq'first'-and$First-eq'fail'){exit 7}
''', encoding='utf-8')
                summary = root / 'summary.json'
                completed = self.run_script(self.prelude() + f'''
$env:TEMP={quote(root)};$env:TMP={quote(root)}
if({quote(first)}-eq'launchfail'){{
 function Start-Process {{
  param($FilePath,$ArgumentList,$WindowStyle,[switch]$PassThru)
  if($ArgumentList-match '"-InternalStage" "first"'){{throw 'LAUNCH_FAILURE'}}
  Microsoft.PowerShell.Management\Start-Process @PSBoundParameters
 }}
}}
$items=@(
 [pscustomobject]@{{Name='first';Run=$true;Reason='fixture';RequiresStages=@()}},
 [pscustomobject]@{{Name='slow';Run=$true;Reason='fixture';RequiresStages=@()}},
 [pscustomobject]@{{Name='dependent';Run=$true;Reason='fixture';RequiresStages=@('first')}},
 [pscustomobject]@{{Name='late';Run=$true;Reason='fixture';RequiresStages=@()}}
)
$summary=New-GateRunSummary -Items $items -GateName fixture -PythonExe {quote(sys.executable)} -RepoRoot {quote(ROOT)} -SummaryPath {quote(summary)}
$failure=$null
try {{
 Invoke-IndependentGateStageGroup -Items $items -MaxConcurrency {concurrency} -StopOnFailure:${str(stop).lower()} -Summary $summary `
  -GateScriptPath {quote(child)} -PythonExe {quote(sys.executable)} -ChildBaseArguments @('-Root',{quote(root)},'-First',{quote(first)}) `
  -TempNamePrefix gate_fixture_ -FailureMessage failed -InvokeSkipStage {{throw 'unexpected skip'}} -InvokeInlineStage {{
   param($item)
   if($item.Name-ne'first'){{throw 'unexpected fallback'}}
   Invoke-RecordedGateStage -Name first -Reason fallback -Summary $summary -Action {{
    if({quote(first)}-eq'fallback_fail'){{throw 'FALLBACK_FAILURE'}}
    Set-Content -LiteralPath {quote(root / 'first_done')} -Value done
   }}
  }}
}}catch{{$failure=$_}}finally{{Complete-GateRunSummary -Summary $summary -Failure $failure}}
''')
                records = {row['name']: row for row in json.loads(summary.read_text(encoding='utf-8'))['stages']}
                if first in ('fail', 'launchfail', 'fallback_fail'):
                    if first == 'fail':
                        self.assertIn('GATE_LIVE_FAILURE NAME=first', completed.stdout)
                        self.assertLess(completed.stdout.index('GATE_LIVE_FAILURE NAME=first'),
                                        completed.stdout.index('COMPLETE NAME=first'))
                        self.assertEqual(completed.stdout.count('traceback detail'), 1)
                        self.assertEqual(records['first']['test_durations'],
                                         [{'test': 'probe', 'elapsed_seconds': 0.125}])
                    self.assertEqual(records['dependent']['reason_code'], 'PREREQUISITE_NOT_PASSED')
                    self.assertNotIn('START NAME=dependent', completed.stdout)
                    self.assertEqual(records['late']['status'], 'BLOCKED' if stop else 'PASS')
                    if stop:
                        self.assertEqual(records['late']['reason_code'], 'FAIL_FAST')
                        self.assertNotIn('START NAME=late', completed.stdout)
                    if concurrency == 2 or not stop:
                        self.assertEqual(records['slow']['status'], 'PASS')
                        self.assertTrue((root / 'slow_done').is_file(), 'started child must finish naturally')
                else:
                    self.assertTrue(all(row['status'] == 'PASS' for row in records.values()))
                    if first == 'fallback':
                        self.assertEqual(records['first']['reason_code'], 'SERIAL_FALLBACK_COMPLETED')
                    self.assertLess(completed.stdout.index('COMPLETE NAME=first'),
                                    completed.stdout.index('START NAME=dependent'))
                for row in records.values():
                    if row['status'] == 'PASS':
                        self.assertGreaterEqual(row['queue_seconds'], 0)
                        self.assertGreaterEqual(row['launch_seconds'], 0)
                        self.assertGreaterEqual(row['process_elapsed_seconds'], row['launch_seconds'])

    def test_exit_between_completion_sweep_and_slot_count_is_collected_before_dependency(self) -> None:
        for exit_code in (0, 7):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                summary = root / 'summary.json'
                completed = self.run_script(self.prelude() + f'''
$env:TEMP={quote(root)};$env:TMP={quote(root)}
function Start-Process {{
 param($FilePath,$ArgumentList,$WindowStyle,[switch]$PassThru)
 $null=$ArgumentList-match '"-InternalStage" "([^"]+)"';$stage=$Matches[1]
 $null=$ArgumentList-match '"-InternalLogPath" "([^"]+)"';$log=$Matches[1]
 Set-Content -LiteralPath $log -Value "INERT_CHILD=$stage"
 $process=[pscustomobject]@{{Id=1;ExitCode=$(if($stage-eq'first'){{{exit_code}}}else{{0}});ExitReads=0;Stage=$stage}}
 $process|Add-Member ScriptProperty HasExited {{
  $this.ExitReads++
  # First sweep sees running; the next OS-status read sees exited.
  return $this.Stage-ne'first'-or$this.ExitReads-ge2
 }}
 $process|Add-Member ScriptMethod WaitForExit {{}}
 $process|Add-Member ScriptMethod Dispose {{}}
 return $process
}}
$items=@(
 [pscustomobject]@{{Name='first';Run=$true;Reason='fixture';RequiresStages=@()}},
 [pscustomobject]@{{Name='dependent';Run=$true;Reason='fixture';RequiresStages=@('first')}}
)
$summary=New-GateRunSummary -Items $items -GateName fixture -PythonExe {quote(sys.executable)} -RepoRoot {quote(ROOT)} -SummaryPath {quote(summary)}
$failure=$null
try {{
 Invoke-IndependentGateStageGroup -Items $items -MaxConcurrency 1 -Summary $summary `
 -GateScriptPath unused -PythonExe {quote(sys.executable)} -ChildBaseArguments @() -TempNamePrefix gate_fixture_ `
 -FailureMessage failed -InvokeInlineStage {{throw 'unexpected fallback'}} -InvokeSkipStage {{throw 'unexpected skip'}}
}}catch{{$failure=$_}}finally{{Complete-GateRunSummary -Summary $summary -Failure $failure}}
''')
                records = {row['name']: row for row in json.loads(summary.read_text(encoding='utf-8'))['stages']}
                self.assertEqual(records['first']['status'], 'PASS' if exit_code == 0 else 'FAIL')
                if exit_code == 0:
                    self.assertEqual(records['dependent']['status'], 'PASS', completed.stdout)
                    self.assertEqual(completed.stdout.count('GATE_PROCESS=START NAME=dependent '), 1)
                    self.assertLess(completed.stdout.index('COMPLETE NAME=first'),
                                    completed.stdout.index('START NAME=dependent'))
                else:
                    self.assertEqual(records['dependent']['status'], 'BLOCKED')
                    self.assertEqual(records['dependent']['reason_code'], 'PREREQUISITE_NOT_PASSED')
                    self.assertNotIn('START NAME=dependent', completed.stdout)

    def test_missing_unselected_and_unresolved_prerequisites_never_run(self) -> None:
        for count, prerequisite, reason in ((1, 'missing', 'PREREQUISITE_MISSING'),
                                            (2, 'not_selected', 'PREREQUISITE_NOT_SELECTED'),
                                            (2, 'cycle', 'UNRESOLVED_PREREQUISITE')):
            with self.subTest(prerequisite=prerequisite), tempfile.TemporaryDirectory() as directory:
                summary = Path(directory) / 'summary.json'
                self.run_script(self.prelude() + f'''
$env:TEMP={quote(directory)};$env:TMP={quote(directory)}
$items=@([pscustomobject]@{{Name='first';Run=$true;Reason='fixture';RequiresStages=@('{prerequisite}')}})
if({count}-gt1){{
 $items+= [pscustomobject]@{{Name='{prerequisite}';Run=${str(prerequisite == 'cycle').lower()};Reason='fixture';RequiresStages=@('first')}}
}}
$summary=New-GateRunSummary -Items $items -GateName fixture -PythonExe {quote(sys.executable)} -RepoRoot {quote(ROOT)} -SummaryPath {quote(summary)}
function Start-Process {{throw 'must not launch'}}
$failure=$null
try {{
 Invoke-IndependentGateStageGroup -Items $items -Summary $summary -MaxConcurrency 2 -GateScriptPath unused `
 -PythonExe {quote(sys.executable)} -ChildBaseArguments @() -TempNamePrefix gate_fixture_ -FailureMessage blocked `
 -InvokeInlineStage {{throw 'must not run inline'}} -InvokeSkipStage {{}}
}}catch{{$failure=$_}}finally{{Complete-GateRunSummary -Summary $summary -Failure $failure}}
''')
                record = json.loads(summary.read_text(encoding='utf-8'))['stages'][0]
                self.assertEqual(record['status'], 'BLOCKED')
                self.assertEqual(record['reason_code'], reason)
                self.assertIsNone(record['execution_seconds'])

    def test_stage_timing_uses_actual_admission_action_and_cleanup_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / 'summary.json'
            self.run_script(self.prelude() + f'''
function Enter-HostResourceStage {{param($Stage,$Role,$Budget) Start-Sleep -Milliseconds 40;@{{token='fixture'}}}}
function Exit-HostResourceStage {{param($Lease) Start-Sleep -Milliseconds 35;throw 'CLEANUP_SECONDARY'}}
$items=@([pscustomobject]@{{Name='timed';Run=$true;Reason='fixture'}})
$summary=New-GateRunSummary -Items $items -GateName fixture -PythonExe {quote(sys.executable)} -RepoRoot {quote(ROOT)} -SummaryPath {quote(summary)}
$failure=$null
try {{Invoke-RecordedGateStage -Name timed -Reason fixture -Summary $summary -Action {{Start-Sleep -Milliseconds 60;throw 'ACTION_PRIMARY'}}}}
catch{{$failure=$_;if($_.Exception.Message-ne'ACTION_PRIMARY'){{throw}};if($_.Exception.Data['gate_release_error']-ne'CLEANUP_SECONDARY'){{throw 'secondary lost'}}}}
finally{{Complete-GateRunSummary -Summary $summary -Failure $failure}}
''')
            row = json.loads(summary.read_text(encoding='utf-8'))['stages'][0]
            for field, minimum in (('resource_wait_seconds', .03), ('execution_seconds', .05), ('cleanup_seconds', .025)):
                self.assertGreaterEqual(row[field], minimum)
            self.assertGreaterEqual(row['elapsed_seconds'], sum(row[field] for field in
                                   ('resource_wait_seconds', 'execution_seconds', 'cleanup_seconds')))
            self.assertIsNone(row['process_elapsed_seconds'], 'inline stage has no child process timer')

    def test_real_integration_file_entry_records_parallel_stages_in_script_scope(self) -> None:
        """Invoke the real root as a script, not as the global -Command prelude."""
        with tempfile.TemporaryDirectory(prefix="parallel_gate_root_") as directory:
            root = Path(directory)
            common = root / "common"
            temporary = root / "temporary"
            for path in (common, temporary, root / "projects", root / "integrations"):
                path.mkdir()
            for name in ("verify_repository_integration.ps1", "parallel_gate_support.ps1",
                         "require_powershell7.ps1"):
                shutil.copyfile(ROOT / "common" / name, common / name)
            (common / "gate_catalog_support.ps1").write_text(
                (ROOT / "common/gate_catalog_support.ps1").read_text(encoding="utf-8") + """
function Read-GateCatalog {
    param($RepoRoot)
    return [pscustomobject]@{
        stage='fixture_regression'; dependency_profile='stdlib'
        repository_integration_group='regression'
        command=[pscustomobject]@{runner='python'; arguments=@('common/fixture_regression.py')}
    }
}
""", encoding="utf-8", newline="\n")
            (common / "host_execution_lease.ps1").write_text("""
function Get-HostResourceBudget { param($Stage, $Role) return @{} }
function Enter-HostResourceStage { param($Stage, $Role, $Budget) return @{} }
function Exit-HostResourceStage { param($Lease) }
""", encoding="utf-8", newline="\n")
            (common / "verify_documentation.ps1").write_text(
                "param($PythonExe)\nWrite-Output 'ROOT_DOCUMENTATION_MARKER'\n",
                encoding="utf-8", newline="\n",
            )
            (common / "verify_repository_text_bytes.py").write_text(
                "print('ROOT_TEXT_MARKER')\n", encoding="utf-8", newline="\n")
            (common / "fixture_regression.py").write_text(
                "print('ROOT_REGRESSION_MARKER')\n", encoding="utf-8", newline="\n")
            driver = root / "driver.ps1"
            driver.write_text(f"""
param($PythonExe, $SummaryPath)
$ErrorActionPreference = 'Stop'
& {quote(common / 'verify_repository_integration.ps1')} -PythonExe $PythonExe `
    -MaxConcurrency 2 -SummaryPath $SummaryPath
exit $LASTEXITCODE
""", encoding="utf-8", newline="\n")
            environment = dict(os.environ, TEMP=str(temporary), TMP=str(temporary))
            environment.pop("MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN", None)
            for exit_code, documentation_fails in ((0, False), (7, False), (0, True)):
                with self.subTest(exit_code=exit_code, documentation_fails=documentation_fails):
                    (common / "verify_documentation.ps1").write_text(
                        "param($PythonExe)\nWrite-Output 'ROOT_DOCUMENTATION_MARKER'\n" +
                        ("throw 'DOCUMENTATION_FAILURE'\n" if documentation_fails else ""), encoding="utf-8")
                    (common / "verify_development_standards.py").write_text(
                        f"print('ROOT_DEVELOPMENT_MARKER')\nraise SystemExit({exit_code})\n",
                        encoding="utf-8", newline="\n",
                    )
                    summary = root / f"summary_{exit_code}_{documentation_fails}.json"
                    completed = subprocess.run(
                        [shutil.which("pwsh"), "-NoProfile", "-File",
                         str(driver), "-PythonExe", sys.executable,
                         "-SummaryPath", str(summary)],
                        cwd=root, env=environment, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=40, check=False,
                    )
                    self.assertEqual(completed.returncode, int(bool(exit_code or documentation_fails)),
                                     completed.stdout + completed.stderr)
                    document = json.loads(summary.read_text(encoding="utf-8"))
                    records = {record["name"]: record for record in document["stages"]}
                    self.assertEqual(document["status"], "FAIL" if exit_code or documentation_fails else "PASS")
                    self.assertEqual(records['documentation']['status'], 'FAIL' if documentation_fails else 'PASS')
                    self.assertEqual(records["repository_text_bytes"]["status"], "PASS")
                    self.assertEqual(records["ruff_all"]["status"], "PASS")
                    self.assertEqual(records["development_standards"]["status"],
                                     "FAIL" if exit_code else "PASS")
                    self.assertEqual(records["fixture_regression"]["status"], "PASS")
                    self.assertEqual(completed.stdout.count("ROOT_TEXT_MARKER"), 1)
                    self.assertEqual(completed.stdout.count("ROOT_DOCUMENTATION_MARKER"), 1)
                    self.assertEqual(completed.stdout.count("GATE_PROCESS=COMPLETE NAME="), 4)
                    for name in ("repository_text_bytes", "development_standards", "ruff_all"):
                        self.assertEqual(records[name]["log_retained"], bool(exit_code))

    def test_real_changed_file_entry_stops_queued_stages_after_scoped_check_failure(self) -> None:
        for concurrency in (1, 2):
            with self.subTest(concurrency=concurrency), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                common = root / 'common'
                for path in (common, root / 'temporary', root / 'projects', root / 'integrations'):
                    path.mkdir()
                for name in ('verify_changed.ps1', 'parallel_gate_support.ps1', 'require_powershell7.ps1'):
                    shutil.copyfile(ROOT / 'common' / name, common / name)
                (common / 'gate_catalog_support.ps1').write_text(
                    (ROOT / 'common/gate_catalog_support.ps1').read_text(encoding='utf-8') + r'''
function Read-GateCatalog {param($RepoRoot)
 @(Get-Content -Raw (Join-Path $PSScriptRoot 'fixture_catalog.json')|ConvertFrom-Json)
}
''', encoding='utf-8')
                (common / 'host_execution_lease.ps1').write_text('''
function Get-HostResourceBudget {param($Stage,$Role) @{}}
function Enter-HostResourceStage {param($Stage,$Role,$Budget) @{}}
function Exit-HostResourceStage {param($Lease)}
''', encoding='utf-8')
                (common / 'verify_repository_hygiene.ps1').write_text("Write-Output 'HYGIENE_OK'\n", encoding='utf-8')
                (common / 'verify_repository_text_bytes.py').write_text("print('BYTES_OK')\n", encoding='utf-8')
                (common / 'changed.ps1').write_text('# fixture\n', encoding='utf-8')
                (common / 'verify_development_standards.py').write_text(
                    "import json, pathlib, sys, time\n"
                    "assert sys.argv[1] == '--changed-paths-file'\n"
                    "assert json.loads(pathlib.Path(sys.argv[2]).read_text()) == ['common/changed.ps1']\n"
                    "print('SCOPED_STANDARD_PATHS_OK')\ntime.sleep(.2)\nraise SystemExit(7)\n", encoding='utf-8')
                routes = []
                for name in ('project_registry', 'rf_multipole_generated_publications', 'fixture_regression'):
                    (common / (name + '.py')).write_text(
                        "import time\ntime.sleep(1 if " + repr(name) + " == 'project_registry' else 0)\nprint('STAGE_DONE')\n",
                        encoding='utf-8')
                    routes.append(dict(stage=name, dependency_profile='stdlib', repository_integration_group='regression',
                                       matches=[dict(prefix='common/', reason='fixture')],
                                       command=dict(runner='python', arguments=['common/' + name + '.py'])))
                (common / 'fixture_catalog.json').write_text(json.dumps(routes), encoding='utf-8')
                summary = root / 'summary.json'
                environment = dict(os.environ, TEMP=str(root / 'temporary'), TMP=str(root / 'temporary'))
                environment.pop('MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN', None)
                completed = subprocess.run(
                    [shutil.which('pwsh'), '-NoProfile', '-File', str(common / 'verify_changed.ps1'),
                     '-PythonExe', sys.executable, '-MaxConcurrency', str(concurrency),
                     '-ChangedPath', 'common/changed.ps1', '-SummaryPath', str(summary)],
                    cwd=root, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=40, check=False)
                self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
                records = {row['name']: row for row in json.loads(summary.read_text(encoding='utf-8'))['stages']}
                self.assertEqual(records['development_standards']['status'], 'FAIL')
                self.assertIn('SCOPED_STANDARD_PATHS_OK', completed.stdout)
                for name in ('rf_multipole_generated_publications', 'fixture_regression'):
                    self.assertEqual(records[name]['reason_code'], 'FAIL_FAST')
                    self.assertNotIn('START NAME=' + name, completed.stdout)
                if concurrency == 2:
                    self.assertEqual(records['project_registry']['status'], 'PASS')

    def test_failed_child_receipt_cannot_be_overridden_by_zero_process_exit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="parallel_gate_receipt_") as directory:
            root = Path(directory)
            summary = root / "summary.json"
            child = root / "child.ps1"
            child.write_text("""
param($InternalStage, $InternalLogPath)
Set-Content -LiteralPath $InternalLogPath -Value ('DIAG_' + $InternalStage)
if ($InternalStage -eq 'second') {
    '{"status":"FAIL","reason_code":"STAGE_EXCEPTION","exit_code":7}' |
        Set-Content -LiteralPath ($InternalLogPath + '.result.json')
}
exit 0
""", encoding="utf-8", newline="\n")
            self.run_script(self.prelude() + f"""
$env:TEMP = {quote(root)}
$env:TMP = {quote(root)}
$items = @([pscustomobject]@{{Name='first';Run=$true;Reason='fixture'}},
    [pscustomobject]@{{Name='second';Run=$true;Reason='fixture'}})
$summary = New-GateRunSummary -Items $items -GateName fixture `
    -PythonExe {quote(sys.executable)} -RepoRoot {quote(ROOT)} -SummaryPath {quote(summary)}
$failure = $null
try {{
    Invoke-IndependentGateStageGroup -Items $items -Summary $summary -MaxConcurrency 2 `
        -GateScriptPath {quote(child)} -PythonExe {quote(sys.executable)} `
        -ChildBaseArguments @() -TempNamePrefix 'parallel_gate_test_' `
        -FailureMessage 'test group failed' -InvokeInlineStage {{ throw 'unexpected inline' }} `
        -InvokeSkipStage {{ throw 'unexpected skip' }}
    throw 'failure receipt was ignored'
}} catch {{
    $failure = $_
    if ($_.Exception.Message -ne 'test group failed: second=7') {{ throw }}
}} finally {{ Complete-GateRunSummary -Summary $summary -Failure $failure }}
""")
            document = json.loads(summary.read_text(encoding="utf-8"))
            self.assertEqual(document["status"], "FAIL")
            failed = document["stages"][1]
            self.assertEqual(failed["status"], "FAIL")
            self.assertEqual(failed["child_exit_code"], 0)
            self.assertTrue(failed["log_retained"])
            self.assertTrue(Path(failed["log_path"]).is_file())

    def test_group_summary_failure_preserves_launch_error_and_environment(self) -> None:
        with tempfile.TemporaryDirectory(prefix="parallel_gate_receipt_") as directory:
            root = Path(directory)
            child = root / "child.ps1"
            summary = root / "summary.json"
            child.write_text(
                "param($InternalStage, $InternalLogPath)\nStart-Sleep -Milliseconds 200\n"
                "Set-Content -LiteralPath $InternalLogPath -Value 'CHILD_FINISHED'\n",
                encoding="utf-8", newline="\n",
            )
            completed = self.run_script(self.prelude() + f"""
$env:TEMP = {quote(root)}
$env:TMP = {quote(root)}
$env:MPLCONFIGDIR = 'prior-matplotlib-config'
$items = @([pscustomobject]@{{Name='first';Run=$true;Reason='fixture'}},
    [pscustomobject]@{{Name='second';Run=$true;Reason='fixture'}})
$summary = New-GateRunSummary -Items $items -GateName fixture `
    -PythonExe {quote(sys.executable)} -RepoRoot {quote(ROOT)} -SummaryPath {quote(summary)}
$script:failRecording = $false
$writer = ${{function:Write-GateRunSummary}}
function Write-GateRunSummary {{
    param($Summary)
    if ($script:failRecording) {{ throw 'SUMMARY_WRITE_FAILURE' }}
    & $writer -Summary $Summary
}}
$script:childId = $null
function Start-Process {{
    param($FilePath, $ArgumentList, $WindowStyle, [switch]$PassThru)
    if ($null -ne $script:childId) {{
        $script:failRecording = $true
        throw 'ORIGINAL_LAUNCH_FAILURE'
    }}
    $process = Microsoft.PowerShell.Management\\Start-Process @PSBoundParameters
    $script:childId = $process.Id
    return $process
}}
$failure = $null
try {{
    Invoke-IndependentGateStageGroup -Items $items -Summary $summary -MaxConcurrency 2 `
        -GateScriptPath {quote(child)} -PythonExe {quote(sys.executable)} `
        -ChildBaseArguments @() -TempNamePrefix 'parallel_gate_test_' `
        -FailureMessage 'test group failed' -InvokeInlineStage {{ throw 'unexpected inline' }} `
        -InvokeSkipStage {{ throw 'unexpected skip' }}
    throw 'missing launch failure'
}} catch {{
    $failure = $_
    if ($_.Exception.Message -ne 'ORIGINAL_LAUNCH_FAILURE') {{ throw }}
}} finally {{ Complete-GateRunSummary -Summary $summary -Failure $failure }}
if ($env:MPLCONFIGDIR -ne 'prior-matplotlib-config') {{ throw 'matplotlib environment leaked' }}
if (Get-Process -Id $script:childId -ErrorAction SilentlyContinue) {{ throw 'child survived unwind' }}
Write-Output 'ORIGINAL_LAUNCH_FAILURE_PRESERVED'
""")
            self.assertIn("ORIGINAL_LAUNCH_FAILURE_PRESERVED", completed.stdout)
            self.assertIn("SUMMARY_WRITE_FAILURE", completed.stdout)

    def test_real_integration_entry_dispatches_once_and_preserves_failure(self) -> None:
        """Exercise the unchanged root entry with isolated catalog/resource inputs."""
        with tempfile.TemporaryDirectory(prefix="parallel_gate_entry_") as directory:
            root = Path(directory)
            common = root / "common"
            common.mkdir()
            for name in ("verify_repository_integration.ps1", "parallel_gate_support.ps1",
                         "require_powershell7.ps1"):
                shutil.copyfile(ROOT / "common" / name, common / name)
            (common / "gate_catalog_support.ps1").write_text(
                (ROOT / "common/gate_catalog_support.ps1").read_text(encoding="utf-8")
                + "\nfunction Read-GateCatalog { param($RepoRoot) return @() }\n",
                encoding="utf-8", newline="\n",
            )
            for exit_code, fail_recording in ((0, False), (7, False), (7, True), (0, True)):
                with self.subTest(exit_code=exit_code, fail_recording=fail_recording):
                    (common / "verify_repository_text_bytes.py").write_text(
                        f"print('ROOT_ENTRY_MARKER')\nraise SystemExit({exit_code})\n",
                        encoding="utf-8", newline="\n",
                    )
                    (common / "host_execution_lease.ps1").write_text(f"""
$script:failRecording = $false
$script:summaryWriter = ${{function:Write-GateRunSummary}}
function Write-GateRunSummary {{
    param($Summary)
    if ($script:failRecording) {{ throw 'SUMMARY_WRITE_FAILURE' }}
    & $script:summaryWriter -Summary $Summary
}}
function Get-HostResourceBudget {{ param($Stage, $Role) return @{{}} }}
function Enter-HostResourceStage {{ param($Stage, $Role, $Budget) return @{{}} }}
function Exit-HostResourceStage {{ param($Lease) $script:failRecording = ${str(fail_recording).lower()} }}
""", encoding="utf-8", newline="\n")
                    log = root / f"stage_{exit_code}_{fail_recording}.log"
                    script = f"""
$env:SIMULATION_PYTHON_EXE = 'previous-runtime'
& {quote(common / 'verify_repository_integration.ps1')} -PythonExe {quote(sys.executable)} `
    -InternalStage repository_text_bytes -InternalLogPath {quote(log)}
$code = $LASTEXITCODE
if ($env:SIMULATION_PYTHON_EXE -ne 'previous-runtime') {{ throw 'runtime environment leaked' }}
Write-Output 'RUNTIME_RESTORED'
exit $code
"""
                    completed = subprocess.run(
                        [shutil.which("pwsh"), "-NoProfile", "-Command", script],
                        cwd=root, capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=30, check=False,
                    )
                    self.assertEqual(completed.returncode, int(bool(exit_code or fail_recording)),
                                     completed.stdout + completed.stderr)
                    self.assertIn("RUNTIME_RESTORED", completed.stdout)
                    text = log.read_text(encoding="utf-8")
                    self.assertEqual(text.count("ROOT_ENTRY_MARKER"), 1, text)
                    if exit_code:
                        self.assertIn("Gate catalog command failed with exit code 7", text)
                    if fail_recording:
                        self.assertIn("SUMMARY_WRITE_FAILURE", text)
                    else:
                        record = json.loads(Path(str(log) + ".result.json").read_text(encoding="utf-8"))
                        self.assertEqual(record["status"], "FAIL" if exit_code else "PASS")

    def test_summary_write_failure_does_not_replace_original_stage_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="parallel_gate_summary_") as directory:
            summary = Path(directory) / "summary.json"
            completed = self.run_script(self.prelude() + f"""
$items = @([pscustomobject]@{{Name='fixture';Run=$true;Reason='fixture'}})
$summary = New-GateRunSummary -Items $items -GateName fixture `
    -PythonExe {quote(sys.executable)} -RepoRoot {quote(ROOT)} -SummaryPath {quote(summary)}
$script:failRecording = $false
$writer = ${{function:Write-GateRunSummary}}
function Write-GateRunSummary {{
    param($Summary)
    if ($script:failRecording) {{ throw 'SUMMARY_WRITE_FAILURE' }}
    & $writer -Summary $Summary
}}
$failure = $null
try {{
    Invoke-RecordedGateStage -Name fixture -Reason fixture -Summary $summary -Action {{
        $script:failRecording = $true
        throw 'ORIGINAL_STAGE_FAILURE'
    }}
}} catch {{
    $failure = $_
    if ($_.Exception.Message -ne 'ORIGINAL_STAGE_FAILURE') {{ throw }}
}} finally {{ Complete-GateRunSummary -Summary $summary -Failure $failure }}
Write-Output 'ORIGINAL_FAILURE_PRESERVED'
""")
            self.assertIn("ORIGINAL_FAILURE_PRESERVED", completed.stdout)
            self.assertIn("SUMMARY_WRITE_FAILURE", completed.stdout)

    def test_summary_records_inline_failure_blocked_and_unselected_stages(self) -> None:
        with tempfile.TemporaryDirectory(prefix="parallel_gate_summary_") as directory:
            summary = Path(directory) / "summary.json"
            completed = self.run_script(self.prelude() + f"""
$items = @(
    [pscustomobject]@{{Name='pass';Run=$true;Reason='fixture'}},
    [pscustomobject]@{{Name='fail';Run=$true;Reason='fixture'}},
    [pscustomobject]@{{Name='blocked';Run=$true;Reason='fixture';RequiresStages=@('fail')}},
    [pscustomobject]@{{Name='unused';Run=$false;Reason='no_route_match'}}
)
$summary = New-GateRunSummary -Items $items -GateName fixture `
    -PythonExe {quote(sys.executable)} -RepoRoot {quote(ROOT)} -SummaryPath {quote(summary)}
$initial = Get-Content -LiteralPath {quote(summary)} -Raw | ConvertFrom-Json
if ($initial.status -ne 'RUNNING' -or $initial.stages[0].status -ne 'PENDING') {{
    throw 'initial plan was not persisted'
}}
$failure = $null
function Invoke-FixtureStage {{
    param([string]$Name, [scriptblock]$Action)
    Invoke-RecordedGateStage -Name $Name -Reason fixture -Summary $summary -Action {{ & $Action }}
}}
try {{
    Invoke-FixtureStage -Name pass -Action {{ 'passed' }}
    Invoke-FixtureStage -Name fail -Action {{
        & {quote(sys.executable)} -c 'raise SystemExit(7)'
        if ($LASTEXITCODE -ne 0) {{ throw 'expected nonzero stage' }}
    }}
}} catch {{ $failure = $_ }} finally {{ Complete-GateRunSummary -Summary $summary -Failure $failure }}
""")
            document = json.loads(summary.read_text(encoding="utf-8"))
            self.assertIn(f"GATE_SUMMARY_PATH={summary}", completed.stdout)
            self.assertEqual(document["status"], "FAIL")
            records = {record["name"]: record for record in document["stages"]}
            self.assertEqual(records["pass"]["status"], "PASS")
            self.assertEqual(records["fail"]["status"], "FAIL")
            self.assertEqual(records["fail"]["exit_code"], 7)
            self.assertEqual(records["blocked"]["status"], "BLOCKED")
            self.assertEqual(records["blocked"]["reason_code"], "PREREQUISITE_NOT_PASSED")
            self.assertIsNone(records["blocked"]["elapsed_seconds"])
            self.assertEqual(records["unused"]["status"], "NOT_APPLICABLE")
            self.assertGreaterEqual(document["elapsed_seconds"], records["fail"]["elapsed_seconds"])

    def test_summary_marks_controlled_interruption_without_claiming_completion(self) -> None:
        with tempfile.TemporaryDirectory(prefix="parallel_gate_summary_") as directory:
            summary = Path(directory) / "summary.json"
            script = self.prelude() + f"""
$items = @([pscustomobject]@{{Name='interrupted';Run=$true;Reason='fixture'}})
$summary = New-GateRunSummary -Items $items -GateName fixture `
    -PythonExe {quote(sys.executable)} -RepoRoot {quote(ROOT)} -SummaryPath {quote(summary)}
$failure = $null
try {{
    Invoke-RecordedGateStage -Name interrupted -Reason fixture -Summary $summary -Action {{
        throw [Management.Automation.PipelineStoppedException]::new('controlled interruption')
    }}
}} catch {{ $failure = $_ }} finally {{ Complete-GateRunSummary -Summary $summary -Failure $failure }}
"""
            completed = subprocess.run(
                [shutil.which("pwsh"), "-NoProfile", "-Command", script],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=30, check=False,
            )
            self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            document = json.loads(summary.read_text(encoding="utf-8"))
            self.assertEqual(document["status"], "INTERRUPTED")
            self.assertEqual(document["stages"][0]["status"], "INTERRUPTED")
            self.assertIsNotNone(document["finished_at"])

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
                    script.write_text(self.prelude() + f"""
$okay = Invoke-LoggedGateStage -Name fixture -LogPath {quote(log)} -Action {{
    Invoke-RecordedGateStage -Name fixture -Reason fixture -Action {{
        Write-Output 'FIRST_LINE'
        while (-not (Test-Path -LiteralPath {quote(release)})) {{ Start-Sleep -Milliseconds 20 }}
        & {quote(sys.executable)} {quote(emitter)}
        if ($LASTEXITCODE -ne 0) {{ throw 'native emitter failed' }}
        {"throw 'EXPECTED_STAGE_ERROR'" if failed else "Write-Output 'FINAL_LINE'"}
    }}
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
                    result = json.loads(Path(str(log) + ".result.json").read_text(encoding="utf-8"))
                    self.assertEqual(result["status"], "FAIL" if failed else "PASS")
                    self.assertIsNotNone(result["finished_at"])

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
            summary = Path(directory) / "summary.json"
            child.write_text(
                "param($InternalStage, $InternalLogPath)\nStart-Sleep -Seconds 1\n"
                "Set-Content -LiteralPath $InternalLogPath -Value 'CHILD_FINISHED'\n",
                encoding="utf-8",
            )
            started = time.monotonic()
            completed = self.run_script(self.prelude() + f"""
$env:TEMP = {quote(directory)}
$env:TMP = {quote(directory)}
$script:started = $null
function Start-Process {{
    param($FilePath, $ArgumentList, $WindowStyle, [switch]$PassThru)
    if ($null -ne $script:started) {{ throw 'injected second launch failure' }}
    $script:started = Microsoft.PowerShell.Management\Start-Process @PSBoundParameters
    $script:childId = $script:started.Id
    return $script:started
}}
$items = @(
    [pscustomobject]@{{Name='first';Run=$true;Reason='fixture'}},
    [pscustomobject]@{{Name='second';Run=$true;Reason='fixture'}},
    [pscustomobject]@{{Name='third';Run=$true;Reason='fixture';RequiresStages=@('second')}}
)
$summary = New-GateRunSummary -Items $items -GateName fixture `
    -PythonExe {quote(sys.executable)} -RepoRoot {quote(ROOT)} -SummaryPath {quote(summary)}
$failure = $null
try {{
    Invoke-IndependentGateStageGroup -Items $items -MaxConcurrency 2 -Summary $summary `
        -GateScriptPath {quote(child)} -PythonExe {quote(sys.executable)} `
        -ChildBaseArguments @() -TempNamePrefix 'parallel_gate_test_' `
        -FailureMessage 'test group failed' -InvokeInlineStage {{ throw 'unexpected inline' }} `
        -InvokeSkipStage {{ throw 'unexpected skip' }}
    throw 'missing launch failure'
}} catch {{
    $failure = $_
    if ($_.Exception.Message -ne 'injected second launch failure') {{ throw }}
}} finally {{ Complete-GateRunSummary -Summary $summary -Failure $failure }}
if ($null -eq $script:started) {{ throw 'first child never started' }}
# The Process object has been disposed; natural completion precedes cleanup.
if (Get-Process -Id $script:childId -ErrorAction SilentlyContinue) {{ throw 'child survived' }}
""")
            self.assertGreaterEqual(time.monotonic() - started, 0.8)
            retained = re.search(r"^GATE_DIAGNOSTICS=RETAINED PATH=(.+)$", completed.stdout, re.MULTILINE)
            self.assertIsNotNone(retained, completed.stdout)
            group = Path(retained.group(1).strip())
            self.assertEqual(group.parent.resolve(), Path(directory).resolve())
            self.assertIn("CHILD_FINISHED", (group / "00_first.log").read_text(encoding="utf-8"))
            self.assertIn("injected second launch failure", (group / "group_failure.log").read_text(encoding="utf-8"))
            self.assertFalse((group / "matplotlib").exists())
            document = json.loads(summary.read_text(encoding="utf-8"))
            records = {record["name"]: record for record in document["stages"]}
            self.assertEqual(document["status"], "FAIL")
            self.assertEqual(records["first"]["status"], "PASS")
            self.assertEqual(records["second"]["reason_code"], "CHILD_START_FAILED")
            self.assertEqual(records["third"]["status"], "BLOCKED")
            self.assertEqual(records["third"]["reason_code"], "PREREQUISITE_NOT_PASSED")

    def test_failed_group_keeps_reported_logs_until_explicit_cleanup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="parallel_gate_fixture_") as directory:
            child = Path(directory) / "child.ps1"
            summary = Path(directory) / "summary.json"
            child.write_text(
                "param($InternalStage, $InternalLogPath)\n"
                "Set-Content -LiteralPath $InternalLogPath -Value ('DIAG_' + $InternalStage)\n"
                "if ($InternalStage -eq 'second') { exit 7 }\n",
                encoding="utf-8",
            )
            completed = self.run_script(self.prelude() + f"""
$env:TEMP = {quote(directory)}
$env:TMP = {quote(directory)}
$items = @(
    [pscustomobject]@{{Name='first';Run=$true;Reason='fixture'}},
    [pscustomobject]@{{Name='second';Run=$true;Reason='fixture'}}
)
$summary = New-GateRunSummary -Items $items -GateName fixture `
    -PythonExe {quote(sys.executable)} -RepoRoot {quote(ROOT)} -SummaryPath {quote(summary)}
$failure = $null
try {{
    Invoke-IndependentGateStageGroup -Items $items -MaxConcurrency 2 -Summary $summary `
        -GateScriptPath {quote(child)} -PythonExe {quote(sys.executable)} `
        -ChildBaseArguments @() -TempNamePrefix 'parallel_gate_test_' `
        -FailureMessage 'test group failed' -InvokeInlineStage {{ throw 'unexpected inline' }} `
        -InvokeSkipStage {{ throw 'unexpected skip' }}
    throw 'missing stage failure'
}} catch {{
    $failure = $_
    if ($_.Exception.Message -ne 'test group failed: second=7') {{ throw }}
}} finally {{ Complete-GateRunSummary -Summary $summary -Failure $failure }}
""")
            reported_logs = re.findall(
                r"^GATE_PROCESS=START NAME=(\w+) PID=\d+ LOG_PATH=(.+)$",
                completed.stdout, re.MULTILINE,
            )
            self.assertEqual(len(reported_logs), 2, completed.stdout)
            self.assertIn("GATE_DIAGNOSTICS=TEMPORARY PATH=", completed.stdout)
            self.assertIn("GATE_DIAGNOSTICS=RETAINED PATH=", completed.stdout)
            self.assertNotIn("GATE_DIAGNOSTICS=CLEANED PATH=", completed.stdout)
            document = json.loads(summary.read_text(encoding="utf-8"))
            self.assertEqual(document["status"], "FAIL")
            self.assertEqual([record["status"] for record in document["stages"]], ["PASS", "FAIL"])
            self.assertEqual(document["stages"][1]["child_exit_code"], 7)
            self.assertTrue(all(record["log_retained"] for record in document["stages"]))
            for name, log_path in reported_logs:
                log = Path(log_path.strip())
                self.assertEqual(log.parent.parent.resolve(), Path(directory).resolve())
                self.assertEqual(log.read_text(encoding="utf-8").strip(), f"DIAG_{name}")
                self.assertFalse((log.parent / "matplotlib").exists())
            command = re.search(
                r"^GATE_DIAGNOSTICS_CLEANUP=AFTER_REVIEW COMMAND=(.+)$", completed.stdout, re.MULTILINE,
            )
            self.assertIsNotNone(command, completed.stdout)
            self.run_script(self.prelude() + f"""
$env:TEMP = {quote(directory)}
$env:TMP = {quote(directory)}
{command.group(1)}
""")
            self.assertFalse(Path(reported_logs[0][1].strip()).parent.exists())

    def test_missing_child_log_records_serial_fallback_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="parallel_gate_fixture_") as directory:
            child = Path(directory) / "child.ps1"
            child.write_text("param($InternalStage, $InternalLogPath)\nexit 7\n", encoding="utf-8")
            completed = self.run_script(self.prelude() + f"""
$env:TEMP = {quote(directory)}
$env:TMP = {quote(directory)}
$items = @(@{{Name='first';Run=$true}}, @{{Name='second';Run=$true}})
try {{
    Invoke-IndependentGateStageGroup -Items $items -MaxConcurrency 2 `
        -GateScriptPath {quote(child)} -PythonExe {quote(sys.executable)} `
        -ChildBaseArguments @() -TempNamePrefix 'parallel_gate_test_' `
        -FailureMessage 'test group failed' -InvokeInlineStage {{ throw 'FALLBACK_ERROR' }} `
        -InvokeSkipStage {{ throw 'unexpected skip' }}
    throw 'missing fallback failure'
}} catch {{
    if ($_.Exception.Message -notlike 'test group failed: *serial_fallback_failed_after_7*') {{ throw }}
}}
""")
            logs = re.findall(r"^GATE_PROCESS=START .+ LOG_PATH=(.+)$", completed.stdout, re.MULTILINE)
            self.assertEqual(len(logs), 2, completed.stdout)
            for log_path in logs:
                log = Path(log_path.strip())
                self.assertEqual(log.parent.parent.resolve(), Path(directory).resolve())
                self.assertIn("FALLBACK_ERROR", log.read_text(encoding="utf-8"))

    def test_repository_partitions_preserve_all_modules_and_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="parallel_gate_partition_") as directory:
            root = Path(directory)
            common = root / "common"
            for path in (common, root / "temporary", root / "projects/fixture/tests", root / "integrations"):
                path.mkdir(parents=True)
            for name in ("verify_repository_integration.ps1", "parallel_gate_support.ps1",
                         "require_powershell7.ps1"):
                shutil.copyfile(ROOT / "common" / name, common / name)
            (common / "gate_catalog_support.ps1").write_text(
                (ROOT / "common/gate_catalog_support.ps1").read_text(encoding="utf-8") + r'''
function Read-GateCatalog {param($RepoRoot)
    @([pscustomobject]@{stage='fixture';dependency_profile='locked';repository_integration_group='regression';
      command=[pscustomobject]@{runner='powershell';script='common/owner.ps1';parameters=[pscustomobject]@{PythonExe='{python}'}};
      repository_integration_command=[pscustomobject]@{runner='powershell';script='common/owner.ps1';parameters=[pscustomobject]@{PythonExe='{python}';PreflightOnly=$true}};
      test_selection=[pscustomobject]@{scope='projects/fixture/tests/'};
      repository_integration_partition=[pscustomobject]@{count=3;parameter='SelectedTestModules';default_seconds=1;measured_seconds=[pscustomobject]@{test_a=10}}})
}
''', encoding="utf-8", newline="\n")
            (common / "host_execution_lease.ps1").write_text(
                "function Get-HostResourceBudget {param($Stage,$Role) @{}}\n"
                "function Enter-HostResourceStage {param($Stage,$Role,$Budget) @{}}\n"
                "function Exit-HostResourceStage {param($Lease)}\n", encoding="utf-8")
            (common / "verify_documentation.ps1").write_text("param($PythonExe)\n", encoding="utf-8")
            for name in ("verify_repository_text_bytes", "verify_development_standards"):
                (common / f"{name}.py").write_text("pass\n", encoding="utf-8")
            (common / "owner.ps1").write_text('''param($PythonExe,[switch]$PreflightOnly,[switch]$PreflightValidated,[string[]]$SelectedTestModules)
if($PreflightOnly){if($env:FIXTURE_PREFLIGHT_FAIL){throw 'PREFLIGHT_FAILURE'};Write-Output 'OWNER_PREFLIGHT';return}
if(-not$PreflightValidated){throw 'PARTITION_PREFLIGHT_NOT_BOUND'}
foreach($module in $SelectedTestModules){Write-Output "MODULE=$module"}
if($SelectedTestModules -contains 'projects.fixture.tests.test_b'){throw 'SHARD_FAILURE'}
''', encoding="utf-8")
            for name in ("a", "b", "c", "d"):
                (root / f"projects/fixture/tests/test_{name}.py").write_text("", encoding="utf-8")
            summary = root / "summary.json"
            env = dict(os.environ, TEMP=str(root / "temporary"), TMP=str(root / "temporary"))
            env.pop("MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN", None)
            result = subprocess.run(
                [shutil.which("pwsh"), "-NoProfile", "-File", str(common / "verify_repository_integration.ps1"),
                 "-PythonExe", sys.executable, "-MaxConcurrency", "3", "-SummaryPath", str(summary)],
                cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(summary.exists(), result.stdout + result.stderr)
            records = {row["name"]: row for row in json.loads(summary.read_text(encoding="utf-8"))["stages"]}
            parts = [row for name, row in records.items() if name.startswith("fixture__tests_")]
            self.assertEqual(len(parts), 3)
            self.assertEqual(records["fixture"]["status"], "PASS")
            self.assertEqual(sum(row["status"] == "FAIL" for row in parts), 1)
            self.assertTrue(all(row["requires_stages"] == ["fixture"] for row in parts))
            modules = [m for row in parts for m in row["command"]["parameters"]["SelectedTestModules"]]
            self.assertCountEqual(modules, [f"projects.fixture.tests.test_{name}" for name in "abcd"])
            self.assertEqual(len(modules), len(set(modules)))
            self.assertIn("SHARD_FAILURE", result.stdout + result.stderr)
            env["FIXTURE_PREFLIGHT_FAIL"] = "1"
            failed_summary = root / "preflight_failure.json"
            result = subprocess.run(
                [shutil.which("pwsh"), "-NoProfile", "-File", str(common / "verify_repository_integration.ps1"),
                 "-PythonExe", sys.executable, "-MaxConcurrency", "3", "-SummaryPath", str(failed_summary)],
                cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            records = {row["name"]: row for row in json.loads(failed_summary.read_text(encoding="utf-8"))["stages"]}
            self.assertEqual(records["fixture"]["status"], "FAIL")
            self.assertTrue(all(row["status"] == "BLOCKED" for name, row in records.items()
                                if name.startswith("fixture__tests_")))

    def test_nested_group_serializes_inherited_reservation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="parallel_gate_fixture_") as directory:
            child = Path(directory) / "child.ps1"
            summary = Path(directory) / "summary.json"
            child.write_text(
                "param($InternalStage, $InternalLogPath)\n"
                "Start-Sleep -Milliseconds 100\n"
                'Set-Content -LiteralPath $InternalLogPath -Value @($InternalStage, "RECEIVED_LOG_PATH=$InternalLogPath")\n',
                encoding="utf-8",
            )
            completed = self.run_script(self.prelude() + f"""
$env:MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN = 'isolated-mock-parent'
$items = @(
    [pscustomobject]@{{Name='first';Run=$true;Reason='fixture'}},
    [pscustomobject]@{{Name='second';Run=$true;Reason='fixture'}}
)
$summary = New-GateRunSummary -Items $items -GateName fixture `
    -PythonExe {quote(sys.executable)} -RepoRoot {quote(ROOT)} -SummaryPath {quote(summary)}
Invoke-IndependentGateStageGroup -Items $items -MaxConcurrency 2 -Summary $summary `
    -GateScriptPath {quote(child)} -PythonExe {quote(sys.executable)} `
    -ChildBaseArguments @() -TempNamePrefix 'parallel_gate_test_' `
    -FailureMessage 'test group failed' -InvokeInlineStage {{ throw 'unexpected inline' }} `
    -InvokeSkipStage {{ throw 'unexpected skip' }}
Complete-GateRunSummary -Summary $summary
""")
            self.assertIn("REASON=inherited_resource_reservation", completed.stdout)
            self.assertIn("GATE_DIAGNOSTICS=CLEANED PATH=", completed.stdout)
            self.assertNotIn("GATE_DIAGNOSTICS=RETAINED PATH=", completed.stdout)
            document = json.loads(summary.read_text(encoding="utf-8"))
            self.assertEqual(document["status"], "PASS")
            self.assertTrue(all(record["status"] == "PASS" for record in document["stages"]))
            self.assertTrue(all(not record["log_retained"] for record in document["stages"]))
            reported_logs = re.findall(
                r"^GATE_PROCESS=START NAME=(\w+) PID=\d+ LOG_PATH=(.+)$",
                completed.stdout, re.MULTILINE,
            )
            self.assertEqual([name for name, _ in reported_logs], ["first", "second"])
            for _, log_path in reported_logs:
                self.assertIn(f"RECEIVED_LOG_PATH={log_path}", completed.stdout)
                self.assertFalse(Path(log_path.strip()).parent.exists(), "successful group left temporary logs")
            self.assertLess(
                completed.stdout.index("COMPLETE NAME=first"),
                completed.stdout.index("START NAME=second"),
            )


if __name__ == "__main__":
    unittest.main()
