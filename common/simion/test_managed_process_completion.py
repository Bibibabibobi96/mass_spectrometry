"""Owned-handle completion, without a solver, host grant or production ledger."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from common import host_resource_python as adapter


SUPPORT = Path(__file__).resolve().parents[1] / "resource_budget_support.ps1"


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows process identities required")
class ManagedProcessCompletionTests(unittest.TestCase):
    def run_script(self, source, *arguments):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "fixture.ps1"
            script.write_text(source, encoding="utf-8")
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(script), str(SUPPORT), *map(str, arguments)],
                cwd=SUPPORT.parent.parent, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            line = next(line for line in completed.stdout.splitlines() if line.startswith("COMPLETION="))
            return json.loads(line.split("=", 1)[1])

    def test_budgeted_process_waits_same_root_after_observation_error(self):
        """A sampling error cannot return input ownership before the real root exits."""
        script = r'''
param($Support,$Python,$Root,$Scenario,[int]$Code)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. $Support
$script:original=[IO.IOException]::new('TEST_ONLY observation failed')
$script:waitError=[IO.IOException]::new('TEST_ONLY owned handle wait failed')
$script:owned=$null;$script:birth=0;$script:samples=0;$script:updates=0;$script:stops=@()
$script:update=(Get-Command Update-RepositoryProcessObservation).ScriptBlock
function Start-Process {
 param($FilePath,$ArgumentList,[switch]$PassThru,$WindowStyle,$WorkingDirectory,$RedirectStandardOutput,$RedirectStandardError,$Environment)
 $script:owned=Microsoft.PowerShell.Management\Start-Process @PSBoundParameters
 $script:birth=$script:owned.StartTime.ToUniversalTime().Ticks
 if($Scenario-eq'wait_error'){
  $script:owned|Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {throw $script:waitError} -Force
 }
 return $script:owned
}
function Get-ManagedSolverProcessSample {
 param($RootProcessIds,$TrackedProcessIds,$RootProcessStartedAtUtcTicks,$TrackedProcessStartedAtUtcTicks)
 $script:samples++
 if($Scenario-eq('sample'+$script:samples)-or$Scenario-eq'wait_error'){throw $script:original}
 [pscustomobject]@{tracked_process_ids=$RootProcessIds;tracked_process_started_at_utc_ticks=$RootProcessStartedAtUtcTicks;
   active_process_ids=@($(if(-not$script:owned.HasExited){$script:owned.Id}));working_set_bytes=0;ancestry_complete=$true}
}
function Update-RepositoryProcessObservation {
 param($Observation,$Sample,[switch]$Final)
 $script:updates++
 if($Scenario-eq('observation'+$script:updates)){throw $script:original}
 if($Scenario-eq'danger'){$Observation.critical_seconds=0}
 & $script:update @PSBoundParameters
}
function Get-RepositoryAvailableMemoryBytes {if($Scenario-eq'danger'){return [int64](100MB)};return [int64](8GB)}
function Stop-ManagedSolverProcesses {
 param($ProcessIds,$ExpectedStartedAtUtcTicks)
 if($Scenario-ne'danger'){throw 'Healthy root must not be killed'}
 # Verify the danger decision and exact owned identities without terminating the inert root.
 $script:stops+=@{ids=$ProcessIds;births=$ExpectedStartedAtUtcTicks}
}
$limits=[pscustomobject]@{wall_clock_seconds=60;transient_run_directory_bytes=1GB;
 process_tree_working_set_bytes=1GB;minimum_system_available_memory_bytes=1}
$caught=$null;$result=$null;$atReturn=$null
try{
 try{
  $result=Invoke-ResourceBudgetedProcess -Limits $limits -RunDir $Root -UsagePath (Join-Path $Root 'usage.json') `
   -FilePath $Python -ArgumentList @('-B',(Join-Path $Root 'root.py'),$Root,[string]$Code)
 }catch{$caught=$_}
 $waitCause=$(if($null-ne$caught-and$null-ne$caught.Exception.Data['observed_process_wait_error']){
   $caught.Exception.Data['observed_process_wait_error'].Exception})
 # PowerShell wraps a throwing ScriptMethod; keep the original cause in that chain.
 while($null-ne$waitCause-and-not[object]::ReferenceEquals($waitCause,$script:waitError)){$waitCause=$waitCause.InnerException}
 $atReturn=@{pid=$script:owned.Id;birth=$script:birth;exited=$script:owned.HasExited;
  completed=(Test-Path -LiteralPath (Join-Path $Root 'completed.json'));result=$result;stops=$script:stops;
  same_exception=($null-ne$caught-and[object]::ReferenceEquals($caught.Exception,$script:original));
  same_wait_error=[object]::ReferenceEquals($waitCause,$script:waitError);
  error=$(if($null-ne$caught){$caught.Exception.Message});
  exit_confirmed=$(if($null-ne$caught){$caught.Exception.Data['observed_process_exit_confirmed']});
  returncode=$(if($null-ne$caught){$caught.Exception.Data['observed_process_returncode']})}
}finally{
 # The red version may return early; the fixture still joins its real root before deleting files.
 if($null-ne$script:owned){
  # Bypass only the injected wait fault; this is still the original real handle.
  $null=$script:owned.GetType().GetMethod('WaitForExit',[type[]]@()).Invoke($script:owned,@())
  $script:owned.Dispose()
 }
}
'COMPLETION='+($atReturn|ConvertTo-Json -Depth 12 -Compress)
'''
        worker = """from pathlib import Path
import json,os,sys,time
time.sleep(1.2)
Path(sys.argv[1], 'completed.json').write_text(json.dumps({'pid': os.getpid()}), encoding='utf-8')
raise SystemExit(int(sys.argv[2]))
"""
        scenarios = [(name, 7) for name in ("sample1", "sample2", "observation1", "observation2", "wait_error")]
        for scenario, code in scenarios + [("normal", 0), ("normal", 7), ("danger", 7)]:
            with self.subTest(scenario=scenario, code=code), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "root.py").write_text(worker, encoding="utf-8")
                result = self.run_script(script, sys._base_executable, root, scenario, code)
                self.assertEqual(result["exited"], scenario != "wait_error", result)
                self.assertEqual(result["completed"], scenario != "wait_error", result)
                self.assertGreater(result["birth"], 0)
                self.assertEqual(result["pid"], json.loads((root / "completed.json").read_text())["pid"])
                if scenario in {"normal", "danger"}:
                    self.assertIsNone(result["error"], result)
                    self.assertEqual(result["result"]["exit_code"], code)
                    self.assertEqual(result["result"]["resource_budget_exceeded"], scenario == "danger")
                else:
                    self.assertTrue(result["same_exception"], result)
                    self.assertEqual(result["error"], "TEST_ONLY observation failed")
                    self.assertEqual(result["exit_confirmed"], scenario != "wait_error", result)
                    self.assertEqual(result["returncode"], None if scenario == "wait_error" else code)
                    self.assertEqual(result["same_wait_error"], scenario == "wait_error", result)
                if scenario == "danger":
                    self.assertEqual(result["result"]["limit_name"], "system_available_memory")
                    self.assertEqual(result["stops"], [{"ids": [result["pid"]], "births": {str(result["pid"]): result["birth"]}}])
                else:
                    self.assertEqual(result["stops"], [])

    def test_managed_stdio_waits_actual_worker_and_drains_output_after_completion(self):
        script = r'''
param($Support,$Python,$Root,$Scenario,[int]$Code)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. $Support
if($Scenario-eq'sample_error'){function Get-ManagedSolverProcessSample {throw 'initial observation unavailable'}}
if($Scenario-eq'ack_error'){
 $definition=(Get-Command Invoke-RepositoryManagedPythonProcess).Definition
 $definition=$definition.Replace('$launcher.StandardInput.WriteLine(($ready|ConvertTo-Json -Compress));$launcher.StandardInput.Close()',
   '$launcher.StandardInput.WriteLine(($ready|ConvertTo-Json -Compress));throw "ACK failed after delivery"')
 Set-Item Function:\Invoke-RepositoryManagedPythonProcess -Value ([scriptblock]::Create($definition))
}
$receipt=$null;$errorText=$null
$workerCommand='from common.host_resource_python import await_managed_process_start; await_managed_process_start(); import sys; exec(compile(open(sys.argv[1],encoding="utf-8").read(),sys.argv[1],"exec"))'
try{
 $receipt=Invoke-RepositoryManagedPythonProcess -Python $Python -ArgumentList @('-B','-c',$workerCommand,(Join-Path $Root 'worker.py'),$Root,[string]$Code) `
  -WorkingDirectory (Split-Path -Parent (Split-Path -Parent $Support)) -StandardOutputPath (Join-Path $Root 'stdout.log') -StandardErrorPath (Join-Path $Root 'stderr.log')
}catch{$errorText=$_.Exception.Message;$receipt=$_.Exception.Data['managed_python_completion']}
'COMPLETION='+(@{receipt=$receipt;error=$errorText}|ConvertTo-Json -Depth 30 -Compress)
'''
        worker = """from pathlib import Path
import subprocess,sys,time
from common.simion.process_observation import run_observed_process
root=Path(sys.argv[2])
(root/'work_started').write_text('started')
result,_=run_observed_process([sys._base_executable,'-B','-c',"import time;time.sleep(.15);print('native finished')"],cwd=root,stdout=root/'native.log',stderr=root/'native.err')
assert result.returncode==0
(root/'completion').write_text('complete')
for i in range(4):
    print('late stdout 中文 '+str(i),flush=True)
    print('late stderr 中文 '+str(i),file=sys.stderr,flush=True)
    time.sleep(.05)
raise SystemExit(int(sys.argv[3]))
"""
        for scenario, code in (("normal", 0), ("normal", 7), ("sample_error", 0), ("ack_error", 0)):
            with self.subTest(scenario=scenario, code=code), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "worker.py").write_text(worker, encoding="utf-8")
                result = self.run_script(script, sys.executable, root, scenario, code)
                receipt = result["receipt"]
                self.assertTrue(receipt["launcher_exit_confirmed"])
                self.assertTrue(receipt["stdout_drained"])
                self.assertTrue(receipt["stderr_drained"])
                if scenario == "sample_error":
                    self.assertIn("initial observation unavailable", result["error"])
                    self.assertFalse(receipt["ownership_confirmed"])
                    self.assertFalse(receipt["ack_attempted"])
                    self.assertFalse((root / "work_started").exists())
                else:
                    if scenario == "ack_error":
                        self.assertEqual(result["error"], "ACK failed after delivery")
                    else:
                        self.assertIsNone(result["error"])
                    self.assertTrue(receipt["ack_attempted"])
                    self.assertNotIn("observed_family_completion", receipt)
                    self.assertTrue(receipt["ownership_confirmed"])
                    self.assertTrue(receipt["worker_exit_confirmed"])
                    self.assertEqual(receipt["exit_code"], code)
                    self.assertNotEqual(receipt["launcher_process_id"], receipt["worker_process_id"])
                    self.assertEqual((root / "completion").read_text(), "complete")
                    self.assertIn("late stdout 中文 3", (root / "stdout.log").read_text(encoding="utf-8"))
                    self.assertIn("late stderr 中文 3", (root / "stderr.log").read_text(encoding="utf-8"))

    def test_worker_eof_or_wrong_ack_cannot_start_work(self):
        environment = os.environ.copy()
        environment["MASS_SPECTROMETRY_MANAGED_PROCESS_NONCE"] = "a" * 32
        code = "from common.host_resource_python import await_managed_process_start; await_managed_process_start(); print('WORK_STARTED')"
        for mode in ("eof", "wrong_nonce", "wrong_pid", "wrong_birth"):
            with self.subTest(mode=mode):
                process = subprocess.Popen([sys.executable, "-B", "-c", code], cwd=SUPPORT.parent.parent,
                                           env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, text=True, encoding="utf-8")
                try:
                    ready = json.loads(process.stdout.readline())
                    self.assertEqual(ready["role"], "repository_managed_process_ready")
                    self.assertEqual(len(ready["started"]), 19)
                    acknowledgement = {**ready, "role": "repository_managed_process_ack"}
                    if mode == "wrong_nonce":
                        acknowledgement["nonce"] = "b" * 32
                    elif mode == "wrong_pid":
                        acknowledgement["pid"] += 1
                    elif mode == "wrong_birth":
                        acknowledgement["started"] = str(int(ready["started"]) + 1)
                    output, errors = process.communicate("" if mode == "eof" else json.dumps(acknowledgement) + "\n", timeout=10)
                    self.assertNotEqual(process.returncode, 0, errors)
                    self.assertNotIn("WORK_STARTED", output)
                finally:
                    if process.stdin and not process.stdin.closed:
                        process.stdin.close()
                    process.wait()
                    for stream in (process.stdout, process.stderr):
                        stream.close()

    def test_python_nongrant_adapter_uses_same_actual_worker_and_logs(self):
        command = ("from common.host_resource_python import await_managed_process_start; await_managed_process_start(); "
                   "import os,sys,time; print('worker='+str(os.getpid()),flush=True); "
                   "time.sleep(.05); print('last stderr 中文',file=sys.stderr,flush=True); sys.exit(int(sys.argv[1]))")
        token = os.environ.get(adapter._TOKEN)
        reentry = os.environ.get(adapter._REENTRY)
        for code in (0, 7):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                receipt = adapter.run_managed_python_process(
                    ["-B", "-c", command, str(code)], cwd=SUPPORT.parent.parent,
                    stdout=root / "out.log", stderr=root / "err.log",
                )
                self.assertEqual(receipt["exit_code"], code)
                self.assertEqual((root / "out.log").read_text().strip(), "worker=" + str(receipt["worker_process_id"]))
                self.assertIn("last stderr 中文", (root / "err.log").read_text(encoding="utf-8"))
                self.assertEqual(os.environ.get(adapter._TOKEN), token)
                self.assertEqual(os.environ.get(adapter._REENTRY), reentry)

    def test_python_nongrant_adapter_keeps_transport_error_and_rejects_missing_receipt(self):
        original = KeyboardInterrupt("parent transport interrupted")
        original.observed_process_exit_confirmed = False
        with patch.object(adapter, "_bridge", side_effect=original):
            with self.assertRaises(KeyboardInterrupt) as raised:
                adapter.run_managed_python_process(["-c", "unused"], cwd=Path.cwd(), stdout=Path("unused.out"), stderr=Path("unused.err"))
        self.assertIs(raised.exception, original)
        self.assertFalse(original.observed_process_exit_confirmed)
        self.assertIsNone(original.managed_python_completion)
        for output in (b"", b"HOST_RESOURCE_PYTHON_RESULT={}",
                       b'HOST_RESOURCE_PYTHON_RESULT={"completion":null,"error":null}'):
            with self.subTest(output=output), patch.object(adapter, "_bridge", return_value=subprocess.CompletedProcess([], 0, output)):
                with self.assertRaises((RuntimeError, ValueError)) as raised:
                    adapter.run_managed_python_process(["-c", "unused"], cwd=Path.cwd(), stdout=Path("unused.out"), stderr=Path("unused.err"))
                self.assertIsNone(raised.exception.managed_python_completion)

    def test_venv_bad_ready_cannot_attest_worker_but_still_drains_late_logs(self):
        script = r'''
param($Support,$Python,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. $Support
$code='import os,sys,time; print("invalid READY",flush=True); time.sleep(.1); print("late stdout",flush=True); print("late stderr",file=sys.stderr,flush=True); sys.exit(7)'
try{
 Invoke-RepositoryManagedPythonProcess -Python $Python -ArgumentList @('-B','-c',$code) `
  -WorkingDirectory $Root -StandardOutputPath (Join-Path $Root 'out.log') -StandardErrorPath (Join-Path $Root 'err.log')
 throw 'Expected invalid READY failure'
}catch{
 $r=$_.Exception.Data['managed_python_completion']
 'COMPLETION='+(@{receipt=$r;error=$_.Exception.Message}|ConvertTo-Json -Depth 20 -Compress)
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_script(script, sys.executable, root)
            receipt = result["receipt"]
            self.assertFalse(receipt["ownership_confirmed"])
            self.assertFalse(receipt["ack_attempted"])
            self.assertFalse(receipt["worker_exit_confirmed"])
            self.assertIsNone(receipt["exit_code"])
            self.assertTrue(receipt["launcher_exit_confirmed"])
            self.assertTrue(receipt["stdout_drained"])
            self.assertTrue(receipt["stderr_drained"])
            self.assertNotIn("observed_family_completion", receipt)
            self.assertEqual((root / "out.log").read_text().splitlines(), ["invalid READY", "late stdout"])
            self.assertEqual((root / "err.log").read_text().strip(), "late stderr")


if __name__ == "__main__":
    unittest.main()
