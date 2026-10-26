"""Regression coverage for whole-unit frontend continuation dispatch."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
SUPPORT = REPO / "integrations/runtime/frontend_flight_support.ps1"


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 unavailable")
class FrontendFlightContinuationTests(unittest.TestCase):
    def test_whole_unit_plan_starts_only_replay_batches(self) -> None:
        """Use the real helper with a fixed dispatch and public replay plan."""

        script = r"""param($Support)
$ErrorActionPreference='Stop'
. $Support
$root=Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory (Join-Path $root inputs),(Join-Path $root results),(Join-Path $root logs) -Force|Out-Null
try{
 function New-Case([int]$Index){
  [pscustomobject]@{index=$Index;case_id=('batch_{0:D2}' -f $Index);count=2;expected_particle_ids=@(1,2);simion_particle_id_offset=0;merge_offset=0;working_directory=$root;iob_path=(Join-Path $root ('batch_{0:D2}.iob' -f $Index));iob_builder_arguments=@('build');fly_arguments=@('fly');environment=@{};stdout=('batch_{0:D2}.stdout.log' -f $Index);stderr=('batch_{0:D2}.stderr.log' -f $Index)}
 }
 $dispatch=Join-Path $root 'inputs/fixed_dispatch.json'
 @{estimation=@{kind='fixed_recovery'}}|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $dispatch
 foreach($scenario in @('one_missing','none_missing','worker_failure')){
  $continuation=Join-Path $root ("inputs/{0}.whole_unit.json" -f $scenario)
  $actions=if($scenario-ne'none_missing'){@('reuse','replay')}else{@('reuse','reuse')}
  @{schema_version=1;role='simion_whole_unit_replay_plan';status='ready';units=@(
    @{key='batch_01';action=$actions[0];terminal_outputs=@()},@{key='batch_02';action=$actions[1];terminal_outputs=@()}
  )}|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $continuation
  $script:builds=[Collections.Generic.List[string]]::new();$script:starts=[Collections.Generic.List[string]]::new()
  function Invoke-FrontendRuntimePython {
   param($Python,$RepoRoot,$RunDirectory,$Name,[string[]]$Arguments,[switch]$Json)
   throw 'Continuation must not materialize already merged batches again.'
  }
  function Invoke-FrontendIobBuild {param($Case,$Phase,$RunDirectory,$SimionExe,$Limits,$Python,$RepoRoot)$script:builds.Add([string]$Case.case_id)}
  function Invoke-ResourceBudgetedProcesses {
   param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords)
   foreach($spec in @($ProcessSpecifications)){$script:starts.Add([string]$spec.name)}
   if($scenario-eq'worker_failure'){throw 'inert worker failure'}
   return @{resource_budget_exceeded=$false;processes=@($ProcessSpecifications|ForEach-Object{@{name=$_.name;exit_code=0}})}
  }
  function Complete-ResourceUsage {param($RunDir,$UsagePath)}
  $merged=[pscustomobject]@{coverage='complete_population';pending_particle_ids=@();batches=@((New-Case 1),(New-Case 2));gui_case=$null}
  function Write-RunJson {param($Path,$Value,$Depth) ConvertTo-Json -InputObject $Value -Depth $Depth|Set-Content -LiteralPath $Path}
  $workbenchPath=Join-Path $root "results/$scenario.workbench.json"
  try{
   $result=Invoke-FrontendFlightPhase -RunDirectory $root -ProjectRunsRoot $root -RepoRoot $root -Python $PSHOME -RuntimeModule fixture -SimionExe 'inert-simion.exe' -Limits @{} -Phase extraction -Prepared @{dispatch_request_path='unused'} -FixedDispatchPlanPath $dispatch -ContinuationPlanPath $continuation -ContinuationWorkbench $merged -WorkbenchReceiptPath $workbenchPath
   if($scenario-eq'worker_failure'){throw 'worker failure was suppressed'}
  }catch{
   if($scenario-ne'worker_failure'-or-not([string]$_).Contains('inert worker failure')){throw}
   if(-not(Test-Path -LiteralPath $workbenchPath)){throw 'failed worker lost its prepared whole-phase workbench'}
   continue
  }
  $expected=if($scenario-eq'one_missing'){@('batch_02')}else{@()}
  if(($script:builds -join ',') -ne ($expected -join ',')){throw "$scenario IOB build set differs: $($script:builds -join ',')"}
  if(($script:starts -join ',') -ne ($expected -join ',')){throw "$scenario SIMION start set differs: $($script:starts -join ',')"}
  $reused=@($result.reused_batches|ForEach-Object{[string]$_.case_id}) -join ','
  $expectedReuse=if($scenario-eq'one_missing'){'batch_01'}else{'batch_01,batch_02'}
  if($reused -ne $expectedReuse){throw "$scenario reused batch record differs"}
  if($scenario-eq'none_missing' -and @($result.native_process_records).Count){throw 'zero-missing recovery fabricated a native exit record'}
 }
 'WHOLE_UNIT_CONTINUATION=PASS'
}finally{Remove-Item -LiteralPath $root -Recurse -Force}
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "continuation.ps1"
            path.write_text(script, encoding="utf-8", newline="\n")
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(path), str(SUPPORT)],
                cwd=REPO,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("WHOLE_UNIT_CONTINUATION=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
