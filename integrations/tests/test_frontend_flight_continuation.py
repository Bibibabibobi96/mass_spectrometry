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
    def test_unobserved_recovery_observes_only_missing_unit(self) -> None:
        script=r'''param($Support,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. $Support
. (Join-Path (Get-Location) 'common/resource_budget_support.ps1')
New-Item -ItemType Directory (Join-Path $Root results),(Join-Path $Root inputs) -Force|Out-Null
$dispatch=Join-Path $Root 'inputs/dispatch.json'
@{estimation=@{kind='formal_first_batch_observation';recovered_missing_observation=$true}}|ConvertTo-Json -Depth 20|Set-Content $dispatch
$continuation=Join-Path $Root 'inputs/continuation.json'
@{units=@(@{key='one';action='reuse'},@{key='two';action='replay'},@{key='three';action='replay'})}|ConvertTo-Json -Depth 20|Set-Content $continuation
function New-Case($index,$name){[pscustomobject]@{index=$index;case_id=$name;count=1;expected_particle_ids=@($index);source_row_range=@($index,$index);simion_particle_id_offset=0;merge_offset=0;working_directory=$Root;environment=@{};stdout=(Join-Path $Root "$name.log");stderr=(Join-Path $Root "$name.err");fly_arguments=@('fly')}}
$initial=[pscustomobject]@{coverage='complete_population';pending_particle_ids=@();batches=@((New-Case 1 'one'),(New-Case 2 'two'),(New-Case 3 'three'));gui_case=$null}
$script:built=@();$script:started=@();$script:joined=@()
function Invoke-FrontendIobBuild {param($Case,$Phase,$RunDirectory,$SimionExe,$Limits,$Python,$RepoRoot) $script:built+=@($Case.case_id)}
function Write-RunJson {param($Path,$Value,$Depth) $Value|ConvertTo-Json -Depth $Depth|Set-Content $Path}
function Start-ObservedFormalProcess {param($DispatchPlanPath,$ProcessSpecification)
 $script:started+=@($ProcessSpecification.name)
 return [pscustomobject]@{resource_budget_exceeded=$false;completed_naturally=$true;exit_code=0;observed_peak_process_tree_working_set_bytes=10;observed_process_cpu_percent=1;observed_background_cpu_percent=0;available_memory_bytes=100;total_physical_memory_bytes=200;process_record=[pscustomobject]@{completed=$true;name=$ProcessSpecification.name;exit_code=0}}
}
function Invoke-FrontendRuntimePython {param($Python,$RepoRoot,$RunDirectory,$Name,$Arguments,[switch]$Json)
 if($Name-ne'extraction.recovered-missing-dispatch'-or$Arguments-notcontains'--recovered-missing-plan'){throw 'missing calibrated scheduler CLI'}
}
function Invoke-ResourceBudgetedProcesses {param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords,$OnProcessCompleted)
 if(@($ProcessSpecifications).Count-ne1-or$ProcessSpecifications[0].name-ne'three'){throw 'unexpected sibling dispatch'}
 $script:joined=@($ExistingProcessRecords|ForEach-Object{$_.name})
 return @{resource_budget_exceeded=$false;processes=@(@{name='two';exit_code=0},@{name='three';exit_code=0})}
}
function Complete-ResourceUsage {param($RunDir,$UsagePath)}
$result=Invoke-FrontendFlightPhase -RunDirectory $Root -ProjectRunsRoot $Root -RepoRoot $Root -Python unused -RuntimeModule fixture -SimionExe unused -Limits @{} -Phase extraction -Prepared @{dispatch_request_path='unused'} -FixedDispatchPlanPath $dispatch -ContinuationPlanPath $continuation -ContinuationWorkbench $initial -WorkbenchReceiptPath (Join-Path $Root 'results/workbench.json')
if(($script:built-join',')-ne'two,three'-or($script:started-join',')-ne'two'-or($script:joined-join',')-ne'two'){throw 'completed prefix was rebuilt or re-emitted'}
if(@($result.reused_batches).Count-ne1-or$result.reused_batches[0].case_id-ne'one'){throw 'reused prefix missing'}
exit 0
'''
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'missing.ps1';path.write_text(script,encoding='utf-8')
            result=subprocess.run(['pwsh','-NoProfile','-File',str(path),str(SUPPORT),directory],cwd=REPO,
                                  capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_formal_first_controls_and_provisional_plan_exist_before_dispatch(self) -> None:
        script=r'''param($Support,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. $Support
New-Item -ItemType Directory (Join-Path $Root results),(Join-Path $Root logs) -Force|Out-Null
function Write-RunJson {param($Path,$Value,$Depth) $Value|ConvertTo-Json -Depth $Depth|Set-Content $Path}
function Invoke-FrontendRuntimePython {param($Python,$RepoRoot,$RunDirectory,$Name,$Arguments,[switch]$Json)
 if($Name-like '*.dispatch-plan'){@{estimation=@{kind='formal_first_batch_observation'}}|ConvertTo-Json|Set-Content (Join-Path $Root 'results/extraction.dispatch_plan.json')}
 if($Name-like '*.materialize-initial'){return [pscustomobject]@{batches=@([pscustomobject]@{index=1;case_id='batch';count=1;expected_particle_ids=@(1);source_row_range=@(1,1);simion_particle_id_offset=0;merge_offset=0;working_directory=$Root;environment=@{};stdout=(Join-Path $Root stdout);stderr=(Join-Path $Root stderr);fly_arguments=@('fly')})}}
}
function Invoke-FrontendIobBuild {param($Case,$Phase,$RunDirectory,$SimionExe,$Limits,$Python,$RepoRoot) $Case|Add-Member -NotePropertyName iob_built -NotePropertyValue $true}
function Invoke-SimionBatchPhase {param($DispatchPlanPath,$RunDir,$UsagePath,$FirstSpecification,$Replan,$PrepareRemaining,$AfterDrain,$OnProcessCompleted)
 $workbench=Get-Content (Join-Path $Root 'results/workbench.json') -Raw|ConvertFrom-Json
 if(-not$workbench.batches[0].iob_built-or-not(Test-Path (Join-Path $Root 'results/extraction.provisional_dispatch_plan.json'))){throw 'first evidence missing before launch'}
 throw 'stop before native launch'
}
try{Invoke-FrontendFlightPhase -RunDirectory $Root -ProjectRunsRoot $Root -RepoRoot $Root -Python unused -RuntimeModule fixture -SimionExe unused -Limits @{} -Phase extraction -Prepared @{dispatch_request_path='unused'} -WorkbenchReceiptPath (Join-Path $Root 'results/workbench.json')}
catch{if($_.Exception.Message-ne'stop before native launch'){throw}}
exit 0
'''
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'provisional.ps1';path.write_text(script,encoding='utf-8')
            result=subprocess.run(['pwsh','-NoProfile','-File',str(path),str(SUPPORT),directory],cwd=REPO,
                                  capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_completion_fact_checks_controls_without_republishing_manifest(self) -> None:
        from common.simion.native_completion import validate_frontend_batch_completion

        script = r'''param($Support,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. $Support
function Write-RunJson {param($Path,$Value,$Depth=30,[switch]$Atomic) if(-not$Atomic){throw 'fact must be atomic'};$Value|ConvertTo-Json -Depth $Depth|Set-Content -LiteralPath $Path}
function Write-VerifiedRunManifest {throw 'must not re-read manifest inputs per batch'}
$controls=@('program','particles','build_spec','iob');$outputs=@{}
foreach($kind in $controls){$path=Join-Path $Root "$kind.txt";[IO.File]::WriteAllText($path,$kind);$outputs[$kind]=@{path=$path}}
$stdout=Join-Path $Root 'stdout.log';[IO.File]::WriteAllText($stdout,'native')
$workbench=Join-Path $Root 'workbench.json'
@{batches=@(@{case_id='batch_0001';count=2;source_row_range=@(1,2);outputs=$outputs})}|ConvertTo-Json -Depth 20|Set-Content $workbench
$dispatch=Join-Path $Root 'dispatch.json';'{}'|Set-Content $dispatch
$record=[pscustomobject]@{name='batch_0001';exit_code=0;specification=@{stdout=$stdout}}
Write-FrontendBatchCheckpoint -Record $record -Phase full_instrument -RunDirectory $Root -RunConfig unused -WorkbenchReceiptPath $workbench -DispatchPlanPath $dispatch -Python unused -RepoRoot unused
$reopen=Join-Path $Root 'reopen.log';'verified'|Set-Content $reopen
@{batches=@(@{case_id='batch_0001';count=2;source_row_range=@(1,2);control_records=@(@{path=$outputs.program.path});iob_path=$outputs.iob.path;iob_reopen_record=@{path=$reopen}})}|ConvertTo-Json -Depth 20|Set-Content $workbench
Write-FrontendBatchCheckpoint -Record $record -Phase pulse -RunDirectory $Root -RunConfig unused -WorkbenchReceiptPath $workbench -DispatchPlanPath $dispatch -Python unused -RepoRoot unused
Remove-Item $reopen
try{Write-FrontendBatchCheckpoint -Record $record -Phase pulse -RunDirectory $Root -RunConfig unused -WorkbenchReceiptPath $workbench -DispatchPlanPath $dispatch -Python unused -RepoRoot unused;throw 'missing reopen accepted'}
catch{if(-not([string]$_).Contains('lacks control')){throw}}
$record.name='failed_batch';$record.exit_code=2
Write-FrontendBatchCheckpoint -Record $record -Phase full_instrument -RunDirectory $Root -RunConfig unused -WorkbenchReceiptPath $workbench -DispatchPlanPath $dispatch -Python unused -RepoRoot unused
if(Test-Path (Join-Path $Root 'results/frontend_batch_completion/full_instrument/failed_batch.json')){throw 'nonzero exit checkpointed'}
exit 0
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'checkpoint.ps1'
            path.write_text(script, encoding='utf-8')
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(path), str(SUPPORT), str(root)],
                                    cwd=REPO, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            receipt = root / 'results/frontend_batch_completion/full_instrument/batch_0001.json'
            validate_frontend_batch_completion(receipt, phase='full_instrument', case_id='batch_0001',
                                               stdout=root/'stdout.log', count=2, row_range=[1, 2])
            import json
            value = json.loads(receipt.read_text(encoding='utf-8-sig'))
            value['exit_code'] = 2
            receipt.write_text(json.dumps(value), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'differs'):
                validate_frontend_batch_completion(receipt, phase='full_instrument', case_id='batch_0001',
                                                   stdout=root/'stdout.log', count=2, row_range=[1, 2])

    def test_whole_unit_plan_starts_only_replay_batches(self) -> None:
        """Use the real helper with a fixed dispatch and public replay plan."""

        script = r"""param($Support)
$ErrorActionPreference='Stop'
. $Support
. (Join-Path (Get-Location) 'common/resource_budget_support.ps1')
$root=Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory (Join-Path $root inputs),(Join-Path $root results),(Join-Path $root logs) -Force|Out-Null
try{
 function New-Case([int]$Index){
  [pscustomobject]@{index=$Index;case_id=('batch_{0:D2}' -f $Index);count=2;expected_particle_ids=@(1,2);simion_particle_id_offset=0;merge_offset=0;working_directory=$root;iob_path=(Join-Path $root ('batch_{0:D2}.iob' -f $Index));iob_builder_arguments=@('build');fly_arguments=@('fly');environment=@{};stdout=('batch_{0:D2}.stdout.log' -f $Index);stderr=('batch_{0:D2}.stderr.log' -f $Index)}
 }
 $dispatch=Join-Path $root 'inputs/fixed_dispatch.json'
 @{estimation=@{kind='fixed_recovery'}}|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $dispatch
 foreach($scenario in @('one_missing','none_missing','worker_failure','budget_exceeded')){
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
   if($scenario-eq'budget_exceeded'){return @{resource_budget_exceeded=$true;processes=@()}}
   return @{resource_budget_exceeded=$false;processes=@($ProcessSpecifications|ForEach-Object{@{name=$_.name;exit_code=0}})}
  }
  function Complete-ResourceUsage {param($RunDir,$UsagePath)}
  $merged=[pscustomobject]@{coverage='complete_population';pending_particle_ids=@();batches=@((New-Case 1),(New-Case 2));gui_case=$null}
  function Write-RunJson {param($Path,$Value,$Depth) ConvertTo-Json -InputObject $Value -Depth $Depth|Set-Content -LiteralPath $Path}
  $workbenchPath=Join-Path $root "results/$scenario.workbench.json"
  try{
   $result=Invoke-FrontendFlightPhase -RunDirectory $root -ProjectRunsRoot $root -RepoRoot $root -Python $PSHOME -RuntimeModule fixture -SimionExe 'inert-simion.exe' -Limits @{} -Phase extraction -Prepared @{dispatch_request_path='unused'} -FixedDispatchPlanPath $dispatch -ContinuationPlanPath $continuation -ContinuationWorkbench $merged -WorkbenchReceiptPath $workbenchPath
   if($scenario-in@('worker_failure','budget_exceeded')){throw 'worker failure was suppressed'}
  }catch{
   $expectedError=if($scenario-eq'worker_failure'){'inert worker failure'}else{'batch flight failed'}
   if($scenario-notin@('worker_failure','budget_exceeded')-or-not([string]$_).Contains($expectedError)){throw}
   if($scenario-eq'budget_exceeded'-and(-not$_.Exception.Data.Contains('simion_wave_writer_completion_confirmed')-or$_.Exception.Data['simion_wave_writer_completion_confirmed'])){throw 'unknown writer not propagated'}
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
