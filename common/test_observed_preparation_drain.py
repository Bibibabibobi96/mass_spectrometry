from pathlib import Path
import subprocess
import tempfile
import unittest


class ObservedPreparationDrainTest(unittest.TestCase):
    def test_completed_first_failure_preserves_native_and_checkpoint_facts(self):
        support = Path(__file__).with_name("resource_budget_support.ps1")
        script = r"""
. $args[0]
$workspace=$args[1]
function Write-RepositorySchedulerEvent {}
function Get-RunDirectoryBytes {return 0}
function Write-ResourceUsage {}
function Start-ObservedFormalProcess {param($DispatchPlanPath,$ProcessSpecification)
 $script:observations++
 return [pscustomobject]@{resource_budget_exceeded=$false;completed_naturally=$true;exit_code=1;process_record=$script:records[0]}
}
$plan=Join-Path $workspace 'plan.json'
@{role='simion_repository_dispatch_plan';particle_count=1;estimation=@{kind='fixture'};limits=@{
 maximum_concurrency=1;launch_stagger_seconds=1;memory_critical_seconds=1;
 memory_recovery_stable_seconds=1;maximum_memory_recovery_attempts=1;
 maximum_memory_danger_termination_attempts=1;memory_critical_reserve_bytes=1;
 memory_admission_reserve_bytes=2;minimum_process_cpu_percent=1
}}|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $plan
foreach($scenario in @('ordinary','observed_unknown','wave_unknown','later_unknown','prepare_unknown')){
 $script:observations=0;$script:callbacks=0;$script:verified=0
 $script:records=@([pscustomobject]@{name='first';completed=$true;exit_code=1;
  peak_working_set_bytes=1;peak_managed_memory_bytes=1;specification=[pscustomobject]@{}})
 if($scenario-eq'later_unknown'){$script:records+= [pscustomobject]@{name='second';completed=$true;exit_code=0;
  peak_working_set_bytes=1;peak_managed_memory_bytes=1;specification=[pscustomobject]@{}}}
 $callback={param($record)
  $script:callbacks++
  try{throw "checkpoint rejected $($record.name)"}catch{
   if($scenario-eq'observed_unknown'-or($scenario-eq'later_unknown'-and$record.name-eq'second')){$_.Exception.Data['observed_process_exit_confirmed']=$false}
   if($scenario-eq'wave_unknown'){$_.Exception.Data['simion_wave_writer_completion_confirmed']=$false}
   throw
  }
 }
 try{
  if($scenario-eq'later_unknown'){
   Invoke-ResourceBudgetedProcesses -DispatchPlanPath $plan -RunDir $workspace -UsagePath unused -ExistingProcessRecords $script:records -OnProcessCompleted $callback
  }elseif($scenario-eq'prepare_unknown'){
   try{throw 'prepare original'}catch{
    $_.Exception.Data['observed_process_exit_confirmed']=$false
    Invoke-ObservedPreparationFailureDrain -Failure $_ -DispatchPlanPath $plan -RunDir $workspace -UsagePath unused -ProcessRecords $script:records -OnProcessCompleted $callback -AfterDrain {$script:verified++}
   }
  }else{
   Invoke-SimionBatchPhase -DispatchPlanPath $plan -RunDir $workspace -UsagePath unused -FirstSpecification @{name='first'} -Replan {throw 'must not replan failed native'} -PrepareRemaining {throw 'must not prepare siblings'} -OnProcessCompleted $callback -AfterDrain {$script:verified++}
  }
  throw 'missing failure'
 }catch{
  $known=$scenario-eq'ordinary'
  if([bool]$_.Exception.Data['simion_wave_writer_completion_confirmed']-ne$known){throw "wrong writer proof for $scenario : $_"}
  if($known-and($_.Exception.Message-ne'Formal first batch did not continue or complete safely.'-or$_.Exception.Data['simion_first_batch_drain_error']-ne'checkpoint rejected first')){throw 'native primary or checkpoint secondary lost'}
  if($scenario-eq'prepare_unknown'-and$_.Exception.Message-ne'prepare original'){throw 'preparation primary lost'}
 }
 if($script:callbacks-ne$script:records.Count-or$script:verified-ne[int]($scenario-eq'ordinary')){throw "callback count/verification differs: $scenario"}
 if($script:observations-ne[int]($scenario-in@('ordinary','observed_unknown','wave_unknown'))){throw 'observation repeated'}
}
exit 0
"""
        with tempfile.TemporaryDirectory() as temporary:
            runner = Path(temporary) / "fixture.ps1"
            runner.write_text(script, encoding="utf-8", newline="\n")
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(runner), str(support), temporary],
                cwd=Path(__file__).resolve().parents[1], timeout=30,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_post_drain_native_verifier_unknown_blocks_all_closeout_paths(self):
        support = Path(__file__).with_name("resource_budget_support.ps1")
        script = r"""
. $args[0]
foreach($scenario in @('success','nonzero','wave_failure','prepare_failure')){
 function Start-ObservedFormalProcess {param($DispatchPlanPath,$ProcessSpecification)
  return @{resource_budget_exceeded=$false;completed_naturally=$false;exit_code=0;process_record=@{completed=$false;id=42}}
 }
 function Invoke-ResourceBudgetedProcesses {param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords,$OnProcessCompleted)
  if($scenario-eq'wave_failure'){try{throw 'wave primary'}catch{$_.Exception.Data['simion_wave_writer_completion_confirmed']=$true;throw}}
  $code=if($scenario-eq'nonzero'){1}else{0}
  return @{resource_budget_exceeded=$false;processes=@(@{exit_code=$code})}
 }
 $arguments=@{DispatchPlanPath='p';RunDir='r';UsagePath='u';
  AfterDrain={try{throw 'native verifier unknown'}catch{$_.Exception.Data['observed_process_exit_confirmed']=$false;throw}};
  PrepareRemaining={if($scenario-eq'prepare_failure'){throw 'prepare primary'};return [pscustomobject]@{pending=@(@{name='one'})}}}
 if($scenario-eq'prepare_failure'){$arguments.FirstSpecification=@{name='first'};$arguments.Replan={}}
 try{Invoke-SimionBatchPhase @arguments;throw 'missing failure'}catch{
  if(-not$_.Exception.Data.Contains('simion_wave_writer_completion_confirmed')-or$_.Exception.Data['simion_wave_writer_completion_confirmed']){throw "native verifier falsely completed: $scenario / $($_.Exception.Message)"}
  if($scenario-eq'prepare_failure'-and($_.Exception.Message-ne'prepare primary'-or$_.Exception.Data['simion_first_batch_verification_error']-ne'native verifier unknown')){throw 'prepare or verifier error lost'}
  if($scenario-eq'wave_failure'-and($_.Exception.Message-ne'wave primary'-or$_.Exception.Data['simion_wave_verification_error']-ne'native verifier unknown')){throw 'wave or verifier error lost'}
 }
}
exit 0
"""
        script = script.replace(". $args[0]", ". '" + str(support).replace("'", "''") + "'")
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", script],
            cwd=Path(__file__).resolve().parents[1], timeout=30, capture_output=True,
            text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_independent_preparation_writer_stays_unknown_with_or_without_drain(self):
        support = Path(__file__).with_name("resource_budget_support.ps1")
        script = r"""
. $args[0]
foreach($withFirst in @($false,$true)){
 foreach($drainFails in @($false,$true)){
  $script:verified=0;$script:drains=0;$script:closed=0
  function Start-ObservedFormalProcess {param($DispatchPlanPath,$ProcessSpecification)
   return @{resource_budget_exceeded=$false;completed_naturally=$false;exit_code=0;process_record=@{completed=$false;id=42}}
  }
  function Invoke-ResourceBudgetedProcesses {param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords,$OnProcessCompleted)
   $script:drains++
   if($drainFails){throw 'drain secondary'}
   return @{resource_budget_exceeded=$false;processes=@(@{id=42;exit_code=0})}
  }
  $arguments=@{DispatchPlanPath='p';RunDir='r';UsagePath='u';AfterDrain={$script:verified++};OnDrained={$script:closed++};
   PrepareRemaining={try{throw 'prepare primary'}catch{$_.Exception.Data['observed_process_exit_confirmed']=$false;throw}}}
  if($withFirst){$arguments.FirstSpecification=@{name='first'};$arguments.Replan={}}
  try{Invoke-SimionBatchPhase @arguments;throw 'missing primary'}catch{
   if($_.Exception.Message-ne'prepare primary'-or$_.Exception.Data['simion_wave_writer_completion_confirmed']){throw}
   if($withFirst-and$drainFails-and$_.Exception.Data['simion_first_batch_drain_error']-ne'drain secondary'){throw 'secondary lost'}
  }
  if($script:verified-ne0-or$script:closed-ne0-or$script:drains-ne[int]$withFirst){throw 'unsafe preparation closeout'}
 }
}
exit 0
"""
        script = script.replace(". $args[0]", ". '" + str(support).replace("'", "''") + "'")
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", script],
            cwd=Path(__file__).resolve().parents[1], timeout=30, capture_output=True,
            text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_batch_phase_preserves_wave_failure_and_runs_verification_only_when_stopped(self):
        support = Path(__file__).with_name("resource_budget_support.ps1")
        script = r"""
. $args[0]
$script:confirmed=$true;$script:verified=0
function Invoke-ResourceBudgetedProcesses {param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords,$OnProcessCompleted)
 try{throw 'wave failed'}catch{$_.Exception.Data['simion_wave_writer_completion_confirmed']=$script:confirmed;throw}
}
foreach($confirmed in @($true,$false)) {
 $script:confirmed=$confirmed
 try{Invoke-SimionBatchPhase -DispatchPlanPath p -RunDir r -UsagePath u -PrepareRemaining {[pscustomobject]@{pending=@(@{name='one'})}} -AfterDrain {$script:verified++;throw 'verification failed'};throw 'missing'}
 catch {
  if($_.Exception.Message-ne'wave failed'){throw}
  if($confirmed-and$_.Exception.Data['simion_wave_verification_error']-ne'verification failed'){throw 'missing secondary'}
 }
}
if($script:verified-ne1){throw 'verification ran with unknown writer'}
exit 0
"""
        script = script.replace(". $args[0]", ". '" + str(support).replace("'", "''") + "'")
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=Path(__file__).resolve().parents[1], timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_batch_phase_writer_proof_for_unstarted_and_unknown_first(self):
        support = Path(__file__).with_name("resource_budget_support.ps1")
        script = r"""
. $args[0]
try {Invoke-SimionBatchPhase -DispatchPlanPath p -RunDir r -UsagePath u -PrepareRemaining {throw 'prepare'};throw 'missing'}
catch {if($_.Exception.Message-ne'prepare'-or-not$_.Exception.Data['simion_wave_writer_completion_confirmed']){throw}}
function Start-ObservedFormalProcess {param($DispatchPlanPath,$ProcessSpecification)
  try{throw 'identity unavailable'}catch{$_.Exception.Data['simion_first_batch_writer_unknown']=$true;throw}
}
try {Invoke-SimionBatchPhase -DispatchPlanPath p -RunDir r -UsagePath u -FirstSpecification @{} -Replan {} -PrepareRemaining {throw 'should not run'};throw 'missing'}
catch {if($_.Exception.Message-ne'identity unavailable'-or-not$_.Exception.Data['simion_first_batch_drain_error']){throw}}
exit 0
"""
        script = script.replace(". $args[0]", ". '" + str(support).replace("'", "''") + "'")
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=Path(__file__).resolve().parents[1], timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_batch_phase_observation_checkpoint_and_zero_reuse(self):
        support = Path(__file__).with_name("resource_budget_support.ps1")
        script = r"""
. $args[0]
$script:launches=0; $script:checkpoints=0; $script:verified=0; $script:replanned=0
function Start-ObservedFormalProcess {param($DispatchPlanPath,$ProcessSpecification)
  $script:launches++; return [pscustomobject]@{resource_budget_exceeded=$false;completed_naturally=$false;exit_code=0;process_record=[pscustomobject]@{completed=$false;id=42}}
}
function Invoke-ResourceBudgetedProcesses {param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords,$OnProcessCompleted)
  if(@($ExistingProcessRecords).Count-ne1-or@($ProcessSpecifications).Count-ne1){throw 'wrong wave'}
  & $OnProcessCompleted $ExistingProcessRecords[0]
  return [pscustomobject]@{resource_budget_exceeded=$false;processes=@(@{name='first';exit_code=0})}
}
$result=Invoke-SimionBatchPhase -DispatchPlanPath p -RunDir r -UsagePath u -FirstSpecification @{name='first'} `
 -Replan {param($formal) if($formal.process_record.id-ne42){throw 'wrong formal'};$script:replanned++} `
 -PrepareRemaining {param($formal) [pscustomobject]@{pending=@(@{name='second'});marker=$formal.process_record.id}} `
 -OnProcessCompleted {param($record) $script:checkpoints++} -AfterDrain {$script:verified++}
if($result.prepared.marker-ne42-or$script:launches-ne1-or$script:replanned-ne1-or$script:checkpoints-ne1-or$script:verified-ne1){throw 'phase contract failed'}
$empty=Invoke-SimionBatchPhase -DispatchPlanPath p -RunDir r -UsagePath u -PrepareRemaining {param($formal) [pscustomobject]@{pending=@()}}
if(@($empty.processes).Count-ne0-or$script:launches-ne1){throw 'reuse launched native work'}
"""
        script = script.replace(". $args[0]", ". '" + str(support).replace("'", "''") + "'")
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=Path(__file__).resolve().parents[1], timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_batch_phase_preparation_failure_drains_and_preserves_primary(self):
        support = Path(__file__).with_name("resource_budget_support.ps1")
        script = r"""
. $args[0]
$script:checkpoints=0; $script:verified=0
function Start-ObservedFormalProcess {param($DispatchPlanPath,$ProcessSpecification)
  return [pscustomobject]@{resource_budget_exceeded=$false;completed_naturally=$false;exit_code=0;process_record=[pscustomobject]@{completed=$false;id=42}}
}
function Invoke-ResourceBudgetedProcesses {param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords,$OnProcessCompleted)
  if(@($ProcessSpecifications).Count-ne0-or@($ExistingProcessRecords).Count-ne1){throw 'wrong drain'}
  & $OnProcessCompleted $ExistingProcessRecords[0]
  return [pscustomobject]@{resource_budget_exceeded=$false;processes=@()}
}
try {
 Invoke-SimionBatchPhase -DispatchPlanPath p -RunDir r -UsagePath u -FirstSpecification @{name='first'} -Replan {} `
  -PrepareRemaining {throw 'prepare failed'} -OnProcessCompleted {param($record) $script:checkpoints++} -AfterDrain {$script:verified++}
 throw 'missing failure'
} catch {if($_.Exception.Message-ne'prepare failed'){throw}}
if($script:checkpoints-ne1-or$script:verified-ne1){throw 'drain callback missing'}
exit 0
"""
        script = script.replace(". $args[0]", ". '" + str(support).replace("'", "''") + "'")
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=Path(__file__).resolve().parents[1], timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_formal_observation_replans_and_drains_failure(self):
        support = Path(__file__).with_name("resource_budget_support.ps1")
        script = r"""
. $args[0]
$script:drains=0
function Start-ObservedFormalProcess {param($DispatchPlanPath,$ProcessSpecification) return [pscustomobject]@{resource_budget_exceeded=$false;completed_naturally=$false;exit_code=0;process_record=[pscustomobject]@{completed=$false;id=42}}}
function Invoke-ResourceBudgetedProcesses {param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords) $script:drains++;return @{resource_budget_exceeded=$false}}
$formal=Invoke-SimionFormalObservation -DispatchPlanPath plan -RunDir run -UsagePath usage -ProcessSpecification @{} -Replan {param($observed) if($observed.process_record.id -ne 42){throw 'wrong worker'}}
if ($formal.process_record.id -ne 42 -or $script:drains -ne 0) {throw 'worker not retained'}
$script:verified=$false
try { Invoke-SimionFormalObservation -DispatchPlanPath plan -RunDir run -UsagePath usage -ProcessSpecification @{} -Replan {throw 'replan failed'} -AfterDrain {$script:verified=$true} } catch {if ($_.Exception.Message -ne 'replan failed'){throw}}
if ($script:drains -ne 1 -or -not $script:verified) {throw 'worker not drained and verified'}
exit 0
"""
        script = script.replace(". $args[0]", ". '" + str(support).replace("'", "''") + "'")
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=Path(__file__).resolve().parents[1], timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_successful_drain_reports_completion_before_rethrow(self):
        support = Path(__file__).with_name("resource_budget_support.ps1")
        script = r"""
. $args[0]
$script:stopped = $false
function Invoke-ResourceBudgetedProcesses {
  param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords)
  return [pscustomobject]@{resource_budget_exceeded=$false}
}
try {
  try { throw 'original failure' } catch {
    Invoke-ObservedPreparationFailureDrain -Failure $_ -DispatchPlanPath plan -RunDir run -UsagePath usage `
      -ProcessRecords @([pscustomobject]@{id=1}) -OnDrained {param($result) $script:stopped=-not $result.resource_budget_exceeded}
  }
} catch { if ($_.Exception.Message -ne 'original failure') { throw } }
if (-not $script:stopped) { throw 'completion not reported' }
exit 0
"""
        script = script.replace(". $args[0]", ". '" + str(support).replace("'", "''") + "'")
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=Path(__file__).resolve().parents[1], timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_drain_and_callback_preserve_original_failure(self):
        support = Path(__file__).with_name('resource_budget_support.ps1')
        script = r'''
. $args[0]
$script:drained = $false
$script:verified = $false
function Invoke-ResourceBudgetedProcesses {
  param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords)
  if (@($ProcessSpecifications).Count -ne 0 -or @($ExistingProcessRecords).Count -ne 1) { throw 'wrong drain' }
  $script:drained = $true
  throw 'drain failure'
}
try {
  try { throw 'original failure' } catch {
    Invoke-ObservedPreparationFailureDrain -Failure $_ -DispatchPlanPath plan -RunDir run -UsagePath usage `
      -ProcessRecords @([pscustomobject]@{id=1}) -AfterDrain { $script:verified=$true; throw 'verification failure' }
  }
} catch {
  if ($_.Exception.Message -ne 'original failure') { throw }
  if ($_.Exception.Data['simion_first_batch_drain_error'] -ne 'drain failure') { throw 'drain error missing' }
}
if (-not $script:drained -or $script:verified) { throw 'verification must wait for confirmed writer completion' }
exit 0
'''
        script = script.replace(". $args[0]", ". '" + str(support).replace("'", "''") + "'")
        result = subprocess.run(['pwsh', '-NoProfile', '-Command', script], cwd=Path(__file__).resolve().parents[1], timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_drain_budget_failure_does_not_confirm_writer(self):
        support = Path(__file__).with_name("resource_budget_support.ps1")
        script = r"""
. $args[0]
function Invoke-ResourceBudgetedProcesses {param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords)
  return @{resource_budget_exceeded=$true}}
try { try {throw 'original'} catch {
  Invoke-ObservedPreparationFailureDrain -Failure $_ -DispatchPlanPath plan -RunDir run -UsagePath usage -ProcessRecords @(@{completed=$false})
} } catch {
  if($_.Exception.Message-ne'original'-or-not$_.Exception.Data['simion_first_batch_drain_error']){throw}
  exit 0
}
exit 1
"""
        script = script.replace(". $args[0]", ". '" + str(support).replace("'", "''") + "'")
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=Path(__file__).resolve().parents[1],
                                timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_post_drain_verification_failure_preserves_original(self):
        support = Path(__file__).with_name("resource_budget_support.ps1")
        script = r"""
. $args[0]
function Invoke-ResourceBudgetedProcesses {param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords)
  return @{resource_budget_exceeded=$false}}
try { try {throw 'original'} catch {
  Invoke-ObservedPreparationFailureDrain -Failure $_ -DispatchPlanPath plan -RunDir run -UsagePath usage -ProcessRecords @(@{completed=$false}) -AfterDrain {throw 'verification failed'}
} } catch {
  if ($_.Exception.Message -ne 'original' -or $_.Exception.Data['simion_first_batch_verification_error'] -ne 'verification failed') {throw}
  exit 0
}
exit 1
"""
        script = script.replace(". $args[0]", ". '" + str(support).replace("'", "''") + "'")
        result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=Path(__file__).resolve().parents[1],
                                timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
