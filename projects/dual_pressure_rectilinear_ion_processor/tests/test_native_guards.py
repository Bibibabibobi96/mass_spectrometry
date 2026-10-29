"""Real public file guards around inert temporary families; no solver execution."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection

PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parents[1]
HARNESS = r'''param($Repo,$Runner,$Directory,$Mode)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/simion/short_pa_path_support.ps1')
$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
foreach($name in @('Enter-IonProcessorNativeFlightGuards','Complete-IonProcessorNativeFlightGuards')){
 $node=$ast.Find({param($a) $a-is[Management.Automation.Language.FunctionDefinitionAst]-and$a.Name-eq$name},$true)
 Invoke-Expression $node.Extent.Text
}
function Write-RunJson {param($Path,$Value) $Value|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $Path -Encoding utf8}
$prefix=Join-Path $Directory 'processor.pa'
$model=Get-Content (Join-Path $Directory 'resolved_model.json') -Raw|ConvertFrom-Json
$expectedCount=$model.native_projection.electrode_ids.Count+3
foreach($suffix in (@('#','0','-surf')+@($model.native_projection.electrode_ids|ForEach-Object{[string]$_}))){[IO.File]::WriteAllText($prefix+$suffix,'inert fixture '+$suffix)}
$controller=$prefix+'0'
$record=@{path=$controller;bytes=(Get-Item $controller).Length;sha256=(Get-FileHash $controller -Algorithm SHA256).Hash}
$context=@{records=[Collections.Generic.List[object]]::new();status='acquiring';error=$null}
$outer=$null
if($Mode-eq'outer'){$outer=Protect-ImmutablePaSource -Source $controller -ExpectedBytes $record.bytes -ExpectedSha256 $record.sha256}
$originalHash=(Get-Command Get-ImmutablePaSourceVerificationSha256).ScriptBlock
$script:injectFailure=$false
function Get-ImmutablePaSourceVerificationSha256 {
 param($Stream,$Length)
 if($script:injectFailure-and$Stream.Name.EndsWith('processor.pa1')){return ('0'*64)}
 & $originalHash -Stream $Stream -Length $Length
}
if($Mode-eq'acquisition'){
 $record.sha256='0'*64
 $caught=$false
 try {Enter-IonProcessorNativeFlightGuards $model $record $context} catch {$caught=$true}
 if(-not$caught){throw 'acquisition mismatch accepted'}
}else{
 Enter-IonProcessorNativeFlightGuards $model $record $context -FreshBuild:($Mode-eq'fresh')
 if($context.records.Count-ne$expectedCount){throw 'family did not derive response count from frozen projection'}
 foreach($entry in $context.records){
  $blocked=$false
  try {$writer=[IO.File]::Open($entry.path,'Open','Write','ReadWrite');$writer.Dispose()} catch {$blocked=$true}
  if(-not$blocked){throw 'family member remained writable'}
 }
}
if($Mode-eq'drift'){$script:injectFailure=$true}
$verification=Join-Path $Directory 'verification.json'
$completionFailed=$false
try {Complete-IonProcessorNativeFlightGuards $context $verification} catch {$completionFailed=$true}
if($completionFailed-ne($Mode-in@('drift','acquisition'))){throw 'completion failed-closed outcome differs'}
$report=Get-Content $verification -Raw|ConvertFrom-Json
if($report.status-ne$(if($completionFailed){'failed'}else{'verified'})){throw 'receipt does not report measured outcome'}
if($Mode-ne'acquisition'-and$report.records.Count-ne$expectedCount){throw 'receipt omitted native family members'}
if($Mode-eq'outer'){
 if(-not$global:MassSpectrometryImmutablePaSourceGuards.ContainsKey($controller)){throw 'borrowed outer guard released'}
 Unprotect-ImmutablePaSource -Source $controller|Out-Null
}
if($global:MassSpectrometryImmutablePaSourceGuards.Count){throw 'owned file guard leaked'}
'GUARD_FIXTURE_PASS'
'''

HEALTHY_FORMAL_FAILURE_HARNESS = r'''param($Runner,$Directory)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
if($ast.Extent.Text-notmatch'Invoke-SimionBatchPhase'){throw 'owner does not use public batch phase'}
if($ast.Extent.Text-match'Wait-IonProcessorExistingFormalProcesses'){throw 'owner retains replaced drain implementation'}
if($ast.Extent.Text-match'Stop-ManagedSolverProcesses'){throw 'owner must not terminate healthy workers'}
'HEALTHY_FORMAL_FAILURE_PASS'
'''


class NativeGuardTests(unittest.TestCase):
    def test_preparation_and_template_observation_keep_unknown_writer_protection(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/"prepare_observation.ps1"
            script.write_text(r'''param($Repo,$Runner,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/simion/short_pa_path_support.ps1')
$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$preparation=$ast.Find({param($a)$a-is[Management.Automation.Language.ForEachStatementAst]-and$a.Extent.Text-match'ION_PROCESSOR_STAGE='},$true)
$template=$ast.Find({param($a)$a-is[Management.Automation.Language.IfStatementAst]-and$a.Clauses[0].Item1.Extent.Text-eq'$iobPreparation.requires_vendor_templates'-and$a.Extent.Text-match'batch_iob_template_resource_usage.json'},$true)
$owner=$ast.Find({param($a)$a-is[Management.Automation.Language.TryStatementAst]-and$a.Body.Extent.Text-match'Enter-ArtifactWorkflowCapacitySession'},$true)
if($null-eq$preparation-or$null-eq$template-or$null-eq$owner.Finally){throw 'production preparation/template/owner boundary missing'}
$failedOperation=$ast.Find({param($a)$a-is[Management.Automation.Language.FunctionDefinitionAst]-and$a.Name-eq'Add-IonProcessorFailedOperation'},$true)
Invoke-Expression $failedOperation.Extent.Text
function Get-HostResourceBudget {param($Role,$Stage) @{}}
function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes) $Lease}
function Set-IonProcessorRunStage {param($Context,$Stage)}
function Exit-HostExecutionLease {$script:forbiddenClosures++;throw 'unknown host owner released'}
function Exit-ArtifactWorkflowCapacitySession {$script:forbiddenClosures++;throw 'unknown capacity owner released'}
function Apply-RunArtifactRetention {$script:forbiddenClosures++;throw 'unknown outputs terminalized'}
function Invoke-ResourceBudgetedProcess {
 if($script:mode-in@('success','nonzero')){return [pscustomobject]@{exit_code=$(if($script:mode-eq'success'){0}else{7});root_process_id=$PID;root_process_started_at_utc_ticks=(Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks}}
 $nativeException=[InvalidOperationException]::new('ORIGINAL_NATIVE_OBSERVATION_FAILURE')
 if($script:mode-ne'missing'){$nativeException.Data['observed_process_exit_confirmed']=($script:mode-eq'confirmed')}
 if($script:mode-eq'confirmed'){
  $nativeException.Data['observed_process_id']=$PID
  $nativeException.Data['observed_process_started_at_utc_ticks']=(Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks
  $nativeException.Data['observed_process_returncode']=0
 }
 throw $nativeException
}
$run=$Root;$solver=$Root;$RunId='inert-fixture';$SimionExe='must-not-launch'
$package=@{result_dir=$Root;log_dir=$Root;run_dir=$Root;summary=(Join-Path $Root 'summary.json')}
$profile=@{limits=@{};native_field_query_memory_bytes=1}
$commands=@(@{name='workbench';stage='prepare';arguments=@('--inert')})
$pa=Join-Path $Root 'processor.pa0';[IO.File]::WriteAllText($pa,'inert native field')
$paRecord=@{path=$pa;bytes=(Get-Item $pa).Length;sha256=(Get-FileHash $pa -Algorithm SHA256).Hash}
$iobPreparation=@{requires_vendor_templates=$true;native_pa0_record=$paRecord;script='inert-template.lua'}
foreach($kind in @('prepare','template')){foreach($script:mode in @('success','nonzero','confirmed','unknown','missing')){
 $writersStopped=$true;$caught=$null;$script:forbiddenClosures=0;$lease=@{};$capacity=@{}
 $nativeOperations=[Collections.Generic.List[object]]::new();$ownerContext=$null
 $runObservation=@{stage='native_preparation';timer=[Diagnostics.Stopwatch]::StartNew()}
 $continuationReadGuards=@{streams=@()};$continuationFieldGuards=@{records=[Collections.Generic.List[object]]::new()}
 if($kind-eq'prepare'){
  $source=Protect-ImmutablePaSource -Source $pa -ExpectedBytes $paRecord.bytes -ExpectedSha256 $paRecord.sha256
  $continuationFieldGuards.records.Add(@{path=$pa;owns_guard=(-not$source.already_protected)})
 }
 try {
  try{. ([scriptblock]::Create($(if($kind-eq'prepare'){$preparation.Extent.Text}else{$template.Extent.Text})))}catch{$caught=$_}
  $known=$script:mode-in@('success','nonzero','confirmed')
  if($writersStopped-ne$known){throw "wrong stop fact for $kind/$script:mode"}
  if(($null-eq$caught)-ne($script:mode-eq'success')){throw "wrong outcome for $kind/$script:mode : $caught"}
  if($script:mode-in@('confirmed','unknown','missing')-and$caught.Exception.Message-ne'ORIGINAL_NATIVE_OBSERVATION_FAILURE'){throw 'primary observation failure was replaced'}
  $held=$global:MassSpectrometryImmutablePaSourceGuards.ContainsKey($pa)
  if($held-ne($kind-eq'prepare'-or-not$known)){throw 'local template guard release did not follow actual stop fact'}
  if(-not$known){
   $primaryRunFailure=$caught;$runObservation=@{stage='native_preparation';timer=[Diagnostics.Stopwatch]::StartNew()};$failureStage='native_preparation';$failureReason=$caught.Exception.Message;$savedPythonPath=$env:PYTHONPATH
   Push-Location .
   . ([scriptblock]::Create('try {} finally '+$owner.Finally.Extent.Text))
   if($script:forbiddenClosures){throw 'unknown preparation writer reached owner closure'}
   $blocked=$false;try{$writer=[IO.File]::Open($pa,'Open','Write','ReadWrite');$writer.Dispose()}catch{$blocked=$true}
   if(-not$blocked){throw 'unknown preparation writer lost its real PA protection'}
   if($primaryRunFailure.Exception.Message-ne'ORIGINAL_NATIVE_OBSERVATION_FAILURE'){throw 'owner closure replaced primary error'}
  }
 } finally {
  if($global:MassSpectrometryImmutablePaSourceGuards.ContainsKey($pa)){Unprotect-ImmutablePaSource -Source $pa|Out-Null}
 }
}}
''', encoding="utf-8")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(script), str(REPO),
                                     str(PROJECT/"simion/run_functional.ps1"), directory],
                                    cwd=REPO, timeout=30, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_explicit_field_and_partial_replay_acquire_one_real_source_guard(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/"combined_field_owner.ps1"
            script.write_text(r'''param($Repo,$Runner,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/simion/short_pa_path_support.ps1')
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$definition=$ast.Find({param($a)$a-is[Management.Automation.Language.FunctionDefinitionAst]-and$a.Name-eq'Protect-IonProcessorPreviousField'},$true)
Invoke-Expression $definition.Extent.Text
$calls=@($ast.FindAll({param($a)$a-is[Management.Automation.Language.CommandAst]-and$a.GetCommandName()-eq'Protect-IonProcessorPreviousField'},$true)|Sort-Object {$_.Extent.StartOffset})
if($calls.Count-ne2){throw 'expected the normal and partial field-consumption branches'}
$normal=$calls[0].Parent.Parent.Parent;$partial=$calls[1].Parent.Parent.Parent
if($normal-isnot[Management.Automation.Language.IfStatementAst]-or$partial-isnot[Management.Automation.Language.IfStatementAst]){throw 'field owner calls lost their production branches'}
# Keep the real OS lock and payload verifier; only shorten contention failure.
$actualPublicationGuard=(Get-Command Enter-RunTerminalConsumptionGuard).ScriptBlock
function Enter-RunTerminalConsumptionGuard {param($RunDirectory)
 $script:guardCalls++
 & $actualPublicationGuard -RunDirectory $RunDirectory -TimeoutSeconds 0
}
$source=Join-Path $Root 'source';$folder=Join-Path $source 'simion'
$run=Join-Path $Root 'child';$inputs=Join-Path $run 'inputs'
New-Item -ItemType Directory -Path $folder,$inputs -Force|Out-Null
$records=@();foreach($suffix in @('#','0','1','2','-surf')){
 $path=Join-Path $folder ('processor.pa'+$suffix);[IO.File]::WriteAllText($path,'inert field '+$suffix)
 $records+=@{path=$path;bytes=(Get-Item $path).Length;sha256=(Get-FileHash $path -Algorithm SHA256).Hash}
}
Set-Content (Join-Path $source 'run_config.json') '{}'
$manifest=Join-Path $source 'run_manifest.json'
@{project='dual_pressure_rectilinear_ion_processor';status='success';inputs=@{};outputs=$records}|ConvertTo-Json -Depth 10|Set-Content $manifest
@{native_projection=@{electrode_ids=@(1,2)};native_field=@{source_manifest=$manifest;source_manifest_sha256=(Get-FileHash $manifest -Algorithm SHA256).Hash}}|ConvertTo-Json -Depth 10|Set-Content (Join-Path $inputs 'resolved_model.json')
$package=@{input_dir=$inputs};$continuationFieldRun=$source
# Adoption's pure Python projection has separate behavior tests. This fixture
# executes both real owner branches and their real source/PA guards without Fly.
$python={$script:adoptCalls++;$global:LASTEXITCODE=0}
foreach($case in @(@{partial=$false;explicit=$true;missing=0},@{partial=$true;explicit=$true;missing=1},@{partial=$true;explicit=$false;missing=1},@{partial=$true;explicit=$true;missing=0})){
 $partialContinuation=$case.partial;$partialReplayCount=$case.missing
 $NativeFieldRun=if($case.explicit){$source}else{''}
 $continuationFieldGuards=@{records=[Collections.Generic.List[object]]::new();manifest_stream=$null;run_config_stream=$null;publication_guard=$null}
 $script:guardCalls=0;$script:adoptCalls=0
 try {
  . ([scriptblock]::Create($normal.Extent.Text))
  . ([scriptblock]::Create($partial.Extent.Text))
  $expected=if(-not$case.partial-or$case.missing){1}else{0}
  if($script:guardCalls-ne$expected-or$script:adoptCalls-ne[int]($case.missing-gt0)){throw 'normal/partial explicit-field source acquired more than once or adoption differed'}
  if($continuationFieldGuards.records.Count-ne(5*$expected)){throw 'actual guarded family differs'}
  foreach($path in @($records.path)+@($manifest,(Join-Path $source 'run_config.json'))){
   $blocked=$false;try{$writer=[IO.File]::Open($path,'Open','Write','ReadWrite');$writer.Dispose()}catch{$blocked=$true}
   if($blocked-ne[bool]$expected){throw 'real source protection differs from actual consumption'}
  }
 } finally {
  foreach($entry in $continuationFieldGuards.records){if($entry.owns_guard){Unprotect-ImmutablePaSource -Source $entry.path|Out-Null}}
  foreach($key in @('manifest_stream','run_config_stream','publication_guard')){if($null-ne$continuationFieldGuards[$key]){$continuationFieldGuards[$key].Dispose()}}
 }
 if($global:MassSpectrometryImmutablePaSourceGuards.Count){throw 'source PA guard leaked'}
}
''', encoding="utf-8")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(script), str(REPO),
                                     str(PROJECT/"simion/run_functional.ps1"), directory],
                                    cwd=REPO, timeout=30, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_partial_adopted_field_keeps_external_guard_without_fresh_write(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/"field_owner.ps1"
            script.write_text(r'''param($Runner,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$calls=@($ast.FindAll({param($a)$a-is[Management.Automation.Language.CommandAst]-and$a.GetCommandName()-eq'Enter-IonProcessorNativeFlightGuards'},$true))
if($calls.Count-ne1){throw 'fresh field guard owner call is not unique'}
$node=$calls[0].Parent.Parent.Parent
if($node-isnot[Management.Automation.Language.IfStatementAst]){throw 'fresh field guard lacks its owner branch'}
$run=$Root;New-Item -ItemType Directory -Path (Join-Path $Root 'inputs')|Out-Null
Set-Content (Join-Path $Root 'inputs/resolved_model.json') '{}'
function Enter-IonProcessorNativeFlightGuards {
 param($ResolvedModel,$Pa0Record,$Context,[switch]$FreshBuild)
 if(-not$FreshBuild){throw 'newly built family was not persisted before protection'}
 $script:freshCalls++
}
foreach($case in @(@{native='';templates=$false},@{native='explicit-parent';templates=$false},@{native='';templates=$true})){
 $NativeFieldRun=$case.native;$partialContinuation=$true;$nativeFlightGuardContext=$null;$script:freshCalls=0
 $iobPreparation=@{requires_vendor_templates=$case.templates;native_pa0_record=@{path='owned-by-field-provider'}}
 . ([scriptblock]::Create($node.Extent.Text))
 if($script:freshCalls-ne[int]$case.templates){throw 'adopted external family entered fresh writable guard or fresh family was skipped'}
 if(-not$case.templates-and$null-ne$nativeFlightGuardContext){throw 'external family acquired a second guard context'}
}
''', encoding="utf-8")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(script),
                                     str(PROJECT/"simion/run_functional.ps1"), directory],
                                    cwd=REPO, timeout=30, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_consumption_guard_blocks_real_python_terminal_writer_before_journal(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            writer = root / "writer.py"
            writer.write_text('''import sys
from pathlib import Path
from common.contracts import write_run_manifest as publication
root = Path(sys.argv[1])
original = publication.process_file_lock
publication.process_file_lock = lambda path: original(path, timeout_seconds=0)
try:
    publication.publish_terminal_state(root, {"status":"success"},
        {"status":"success", "run_id":root.name})
except TimeoutError:
    assert not (root/publication.TERMINAL_JOURNAL_NAME).exists()
    print("WRITER_BLOCKED_BEFORE_JOURNAL")
else:
    print("WRITER_PUBLISHED")
''', encoding="utf-8")
            script = root / "publication_guard.ps1"
            script.write_text(r'''param($Repo,$Root,$Writer)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$python=Join-Path $Repo '.venv/Scripts/python.exe';$env:PYTHONPATH=$Repo
$guard=Enter-RunTerminalConsumptionGuard -RunDirectory $Root
try {
 $text=& $python $Writer $Root
 if($LASTEXITCODE-ne0-or$text-ne'WRITER_BLOCKED_BEFORE_JOURNAL'){throw 'consumer and publisher do not share one lock'}
} finally {$guard.Dispose()}
$text=& $python $Writer $Root
if($LASTEXITCODE-ne0-or$text-ne'WRITER_PUBLISHED'){throw 'publication did not resume after consumer release'}
Set-Content (Join-Path $Root '.run_terminal_publication.json') '{}'
$caught=$false;try{$guard=Enter-RunTerminalConsumptionGuard -RunDirectory $Root}catch{$caught=$true}
if(-not$caught){$guard.Dispose();throw 'consumer accepted pending terminal journal'}
''', encoding="utf-8")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(script), str(REPO), str(root), str(writer)],
                cwd=REPO, timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_observation_reports_stage_durations_failure_and_recovery(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "observation.ps1"
            script.write_text(r'''param($Runner,$Root)
$ErrorActionPreference='Stop';$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$errors)
foreach($name in @('Set-IonProcessorRunStage','Set-IonProcessorRunObservation')){
 $node=$ast.Find({param($a)$a-is[Management.Automation.Language.FunctionDefinitionAst]-and$a.Name-eq$name},$true)
 Invoke-Expression $node.Extent.Text
}
$context=@{timer=[Diagnostics.Stopwatch]::StartNew();stage='prepare';stage_started_seconds=0.0;phase_durations_seconds=[ordered]@{}}
Set-IonProcessorRunStage -Context $context -Stage flight
$summary=@{execution_status='failed';data_validity='unknown';science_status='unknown'}
Set-IonProcessorRunObservation -Summary $summary -Context $context -Run $Root -NativeCompleted $false -WritersStopped $true -FailureStage flight -FailureReason 'worker sentinel'
if($summary.failure_stage-ne'flight'-or$summary.failure_reason-ne'worker sentinel'-or$summary.recovery_action-notmatch'ContinuationPredecessorManifestPath'-or$summary.result_path-ne(Join-Path $Root 'run_manifest.json')-or$summary.phase_durations_seconds.Count-ne2-or$summary.total_elapsed_seconds-lt0){throw 'failure observation incomplete'}
Set-IonProcessorRunObservation -Summary $summary -Context $context -Run $Root -NativeCompleted $false -WritersStopped $false -FailureStage flight
if($summary.recovery_action-notmatch'confirm native writer completion'){throw 'unknown writer authorized recovery'}
Set-IonProcessorRunObservation -Summary $summary -Context $context -Run $Root -NativeCompleted $true -WritersStopped $true
if($null-ne$summary.failure_stage-or$summary.recovery_action-ne'none'){throw 'success observation retained failure'}
''', encoding="utf-8")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(script), str(PROJECT / "simion/run_functional.ps1"), temporary],
                cwd=REPO, timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_owner_preserves_primary_error_when_finalization_also_fails(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/"finalization.ps1"
            script.write_text(r'''param($Runner,$Root)
$ErrorActionPreference='Stop';$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$node=$ast.Find({param($a)$a-is[Management.Automation.Language.TryStatementAst]-and$null-ne$a.Finally-and$a.Finally.Extent.Text-match'ion_processor_finalization_error'},$true)
if($null-eq$node){throw 'owner finalization missing'}
$body=$node.Finally.Extent.Text; $body=$body.Substring(1,$body.Length-2)
function Set-IonProcessorRunStage {param($Context,$Stage)}
function Set-IonProcessorRunObservation {param($Summary,$Context,$Run,$NativeCompleted,$WritersStopped,$FailureStage,$FailureReason)}
$runObservation=@{stage='finalization';timer=[Diagnostics.Stopwatch]::StartNew()};$failureStage='';$failureReason=''
$configPath=Join-Path $Root 'run_config.json';Set-Content $configPath '{"inputs":{}}'
$summaryPath=Join-Path $Root 'summary.json';Set-Content $summaryPath '{"status":"failed"}'
$writersStopped=$true;$lease=$null;$package=@{run_config=$configPath;run_dir=$Root;summary=$summaryPath};$capacity=$null;$runSucceeded=$false;$nativeCompleted=$false
$nativeOperations=[Collections.Generic.List[object]]::new();$ownerContext=@{result_path=(Join-Path $Root 'result.json')};$run=$Root
$continuationReadGuards=@{streams=@()};$continuationFieldGuards=@{records=@();manifest_stream=$null}
$savedPythonPath=$env:PYTHONPATH;$python='fixture';$repoRoot=$Root
function Write-RunJson {param($Path,$Value) $Value|ConvertTo-Json -Depth 32|Set-Content $Path}
function Complete-RunArtifactPowerShellOwner {throw 'finalization sentinel'}
$caught=$null;Push-Location $Root
try {
 try {throw 'original science sentinel'} catch {$primaryRunFailure=$_;throw} finally {& ([scriptblock]::Create($body))}
}catch{$caught=$_}
if($caught.Exception.Message-ne'original science sentinel'){throw 'primary error was replaced'}
if($caught.Exception.Data['ion_processor_finalization_error']-notmatch'finalization sentinel'){throw 'secondary error was not retained'}
''', encoding="utf-8")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(script), str(PROJECT/"simion/run_functional.ps1"), directory],
                                    cwd=REPO, timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_continuation_source_files_are_locked_before_identity_validation(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/"source_guard.ps1"
            script.write_text(r'''param($Runner,$Root)
$ErrorActionPreference='Stop';$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$node=$ast.Find({param($a)$a-is[Management.Automation.Language.FunctionDefinitionAst]-and$a.Name-eq'Protect-IonProcessorContinuationInputs'},$true)
Invoke-Expression $node.Extent.Text
New-Item -ItemType Directory -Force -Path (Join-Path $Root 'simion_batch_0001'),(Join-Path $Root 'simion'),(Join-Path $Root 'results')|Out-Null
$csv=Join-Path $Root 'simion_batch_0001/events.csv';$archive=Join-Path $Root 'results/merged_worker_csv_batch_0001.zip'
$sample=Join-Path $Root 'simion/native_field_samples.csv'
foreach($path in @($csv,$archive,$sample)){[IO.File]::WriteAllText($path,'inert')}
[IO.File]::WriteAllText((Join-Path $Root 'run_config.json'),'{}')
@{inputs=@{};outputs=@(@{path=$csv},@{path=$archive},@{path=$sample});run_config=@{path='run_config.json'}}|ConvertTo-Json -Depth 8|Set-Content (Join-Path $Root 'run_manifest.json')
$context=@{streams=[Collections.Generic.List[object]]::new()}
Protect-IonProcessorContinuationInputs -Predecessor $Root -Context $context
foreach($path in @($csv,$archive,$sample,(Join-Path $Root 'run_manifest.json'))){
 $blocked=$false;try{$w=[IO.File]::Open($path,'Open','Write','ReadWrite');$w.Dispose()}catch{$blocked=$true}
 if(-not$blocked){throw 'continuation source remained writable'}
}
foreach($stream in $context.streams){$stream.Dispose()}
''', encoding="utf-8")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(script), str(PROJECT/"simion/run_functional.ps1"), directory],
                                    cwd=REPO, timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_public_batch_phase_receives_only_missing_original_units(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/"pending.ps1"
            script.write_text(r'''param($Runner,$Root)
$ErrorActionPreference='Stop';$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$node=$ast.Find({param($a)$a-is[Management.Automation.Language.AssignmentStatementAst]-and$a.Left.Extent.Text-eq'$prepareRemaining'},$true)
if($null-eq$node-or$ast.Extent.Text-notmatch'Invoke-SimionBatchPhase.*-PrepareRemaining \$prepareRemaining'){throw 'public phase not wired'}
$batchPlanPath=Join-Path $Root 'batches.json'
@{batches=@(@{index=1;count=2},@{index=2;count=2},@{index=3;count=2})}|ConvertTo-Json -Depth 5|Set-Content $batchPlanPath
$formalIndex=$null;$partialContinuation=$true;$replayKeys=@('batch_0002')
function New-IonProcessorProcessSpecification {param($Batch) return @{name=('batch_'+$Batch.index);scheduler_batch=$Batch}}
Invoke-Expression $node.Extent.Text
$result=& $prepareRemaining $null
if(@($result.pending).Count-ne1-or$result.pending[0].scheduler_batch.index-ne2-or$result.pending[0].scheduler_batch.count-ne2){throw 'missing batch selection differs'}
''', encoding="utf-8")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(script), str(PROJECT/"simion/run_functional.ps1"), directory],
                                    cwd=REPO, timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_reused_partial_batches_take_real_zero_native_owner_branch(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/"all_reused.ps1"
            script.write_text(r'''param($Runner,$Root)
$ErrorActionPreference='Stop';$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$node=$ast.Find({param($a)$a-is[Management.Automation.Language.IfStatementAst]-and$a.Extent.Text.StartsWith('if($ContinuationPredecessorManifestPath-and-not$partialContinuation)')},$true)
if($null-eq$node){throw 'missing continuation branch'}
$run=$Root;$repoRoot=$Root;$python='pythonFixture';$ContinuationPredecessorManifestPath='parent';$partialContinuation=$true;$partialReplayCount=0
$predecessor='parent';$package=@{result_dir=(Join-Path $Root 'results')};$partialPlan=@{units=@(@{action='reuse'},@{action='reuse'})}
New-Item -ItemType Directory -Force -Path $package.result_dir,(Join-Path $Root 'inputs/partial_batch_replay')|Out-Null
Set-Content (Join-Path $Root 'inputs/partial_batch_replay/batch_plan.json') '{}'
function pythonFixture {$global:LASTEXITCODE=0;$script:called=@($args)}
function Enter-HostExecutionLease {param($Role,$Stage) if($Role-ne'SIMION'-or$Stage-ne'postprocess'){throw 'heavy admission'};return @{stage=$Stage}}
function Invoke-ResourceBudgetedProcess {throw 'native process started'}
function Invoke-SimionBatchPhase {throw 'native wave started'}
function Write-RunJson {param($Path,$Value) $Value|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $Path}
Invoke-Expression $node.Extent.Text
if(-not$nativeCompleted-or$lease.stage-ne'postprocess'-or$script:called-notcontains'merge-batches'){throw 'all-reuse owner branch failed'}
$usage=Get-Content (Join-Path $package.result_dir 'simion_batch_resource_usage.json') -Raw|ConvertFrom-Json
if($usage.execution_wave.process_count-ne0-or$usage.execution_wave.reused_batch_count-ne2){throw 'reuse accounting differs'}
''', encoding="utf-8")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(script), str(PROJECT/"simion/run_functional.ps1"), directory],
                                    cwd=REPO, timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_previous_field_manifest_identity_is_held_against_writers(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/"prior_field.ps1"
            script.write_text(r'''param($Repo,$Runner,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/simion/short_pa_path_support.ps1')
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$node=$ast.Find({param($a)$a-is[Management.Automation.Language.FunctionDefinitionAst]-and$a.Name-eq'Protect-IonProcessorPreviousField'},$true)
Invoke-Expression $node.Extent.Text
$folder=Join-Path $Root 'simion';New-Item -ItemType Directory -Path $folder|Out-Null
$records=@();foreach($suffix in @('#','0','1','2','-surf')){
 $path=Join-Path $folder ('processor.pa'+$suffix);[IO.File]::WriteAllText($path,'field '+$suffix)
 $records+=@{path=$path;bytes=(Get-Item $path).Length;sha256=(Get-FileHash $path -Algorithm SHA256).Hash}
}
Set-Content (Join-Path $Root 'run_config.json') '{}'
@{project='dual_pressure_rectilinear_ion_processor';status='success';inputs=@{};outputs=$records}|ConvertTo-Json -Depth 10|Set-Content (Join-Path $Root 'run_manifest.json')
$context=@{records=[Collections.Generic.List[object]]::new();manifest_stream=$null};$model=@{native_projection=@{electrode_ids=@(1,2)}}
$actualHash=(Get-Command Get-ImmutablePaSourceVerificationSha256).ScriptBlock;$script:payloadReads=@{}
function Get-ImmutablePaSourceVerificationSha256 {param($Stream,$Length)
 if(-not$script:payloadReads.ContainsKey($Stream.Name)){$script:payloadReads[$Stream.Name]=0}
 $script:payloadReads[$Stream.Name]++
 & $actualHash -Stream $Stream -Length $Length
}
Protect-IonProcessorPreviousField -FieldRun $Root -ResolvedModel $model -Context $context
if($context.records.Count-ne5){throw 'field family incomplete'}
if($script:payloadReads.Count-ne5-or@($script:payloadReads.Values|Where-Object{$_-ne1}).Count){throw 'protected family was reread'}
foreach($entry in $context.records){
 $blocked=$false;try{$w=[IO.File]::Open($entry.path,'Open','Write','ReadWrite');$w.Dispose()}catch{$blocked=$true}
 if(-not$blocked){throw 'prior field remained writable'}
}
foreach($entry in $context.records){if($entry.owns_guard){Unprotect-ImmutablePaSource -Source $entry.path|Out-Null}}
$context.manifest_stream.Dispose()
$context.run_config_stream.Dispose();$context.publication_guard.Dispose()
$context.records.Clear()
if($global:MassSpectrometryImmutablePaSourceGuards.Count){throw 'guard leaked'}
$target=Join-Path $folder 'processor.pa1';[IO.File]::WriteAllText($target,'wrong 1')
$caught=$false;try{Protect-IonProcessorPreviousField -FieldRun $Root -ResolvedModel $model -Context $context}catch{$caught=$true}
if(-not$caught-or$global:MassSpectrometryImmutablePaSourceGuards.Count){throw 'corrupt source accepted or failed acquisition leaked'}
$manifest=Get-Content (Join-Path $Root 'run_manifest.json') -Raw|ConvertFrom-Json;$manifest.status='running'
$manifest|ConvertTo-Json -Depth 12|Set-Content (Join-Path $Root 'run_manifest.json')
$caught=$false;try{Protect-IonProcessorPreviousField -FieldRun $Root -ResolvedModel $model -Context $context}catch{$caught=$true}
if(-not$caught){throw 'unknown source writer accepted'}
Set-Content (Join-Path $Root '.run_terminal_publication.json') '{}'
$caught=$false;try{Protect-IonProcessorPreviousField -FieldRun $Root -ResolvedModel $model -Context $context}catch{$caught=$true}
if(-not$caught){throw 'pending source journal accepted'}
''', encoding="utf-8")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(script), str(REPO), str(PROJECT/"simion/run_functional.ps1"), directory],
                                    cwd=REPO, timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_batch_completion_records_observed_exit_for_each_owner(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "completion.ps1"
            script.write_text(r'''param($Runner,$Directory)
$ErrorActionPreference='Stop';$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$node=$ast.Find({param($a)$a-is[Management.Automation.Language.FunctionDefinitionAst]-and$a.Name-eq'Write-IonProcessorBatchCompletion'},$true)
Invoke-Expression $node.Extent.Text
function Write-RunJson {param($Path,$Value) $Value|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $Path -Encoding utf8}
foreach($exit in @(0,7)){
 $batch=@{index=($exit+1);count=3};$record=@{specification=@{scheduler_batch=$batch};completed=$true;exit_code=$exit;name='worker'}
 Write-IonProcessorBatchCompletion -Record $record -ResultDirectory $Directory
 $actual=Get-Content (Join-Path $Directory ('native_batch_completion_{0:D4}.json'-f[int]$batch.index)) -Raw|ConvertFrom-Json
 if($actual.exit_code-ne$exit-or-not$actual.completed-or$actual.batch.count-ne3){throw 'wrong completion fact'}
}
$record.completed=$false;$caught=$false
try {Write-IonProcessorBatchCompletion -Record $record -ResultDirectory $Directory}catch{$caught=$true}
if(-not$caught){throw 'uncompleted owner accepted'}
if($ast.Extent.Text-notmatch '-OnProcessCompleted \$checkpoint'){throw 'checkpoint not wired to public wave'}
''', encoding="utf-8")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(script), str(PROJECT / "simion/run_functional.ps1"), directory],
                                    cwd=REPO, timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_continuation_projects_ancestry_before_capacity_and_rechecks_after(self) -> None:
        script = (PROJECT / "simion/run_functional.ps1").read_text(encoding="utf-8")
        first = script.index("continuation_protection_paths;print")
        capacity = script.index("$capacity=Enter-ArtifactWorkflowCapacitySession")
        second = script.index("continuation_protection_paths;print", first + 1)
        continuation = script.index("$lease=Invoke-IonProcessorCompletedContinuation")
        self.assertLess(first, capacity)
        self.assertLess(capacity, second)
        self.assertLess(second, continuation)
        self.assertIn("continuation ancestry changed after capacity admission", script)

    def test_completed_continuation_uses_only_analysis_lease_and_no_native_process(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "continuation_fixture.ps1"
            script.write_text(r'''param($Runner,$Root)
$ErrorActionPreference='Stop';$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$node=$ast.Find({param($a)$a-is[Management.Automation.Language.FunctionDefinitionAst]-and$a.Name-eq'Invoke-IonProcessorCompletedContinuation'},$true)
Invoke-Expression $node.Extent.Text
function pythonFixture {$global:LASTEXITCODE=0; $script:arguments=@($args); 'synthetic continuation'}
function Enter-HostExecutionLease {param($Role,$Stage) if($Role-ne'SIMION'-or$Stage-ne'postprocess'){throw 'heavy admission'};return @{stage=$Stage}}
function Invoke-ResourceBudgetedProcess {throw 'native process started'}
function Invoke-ResourceBudgetedProcesses {throw 'native wave started'}
$lease=Invoke-IonProcessorCompletedContinuation -Python 'pythonFixture' -Run $Root -Predecessor (Join-Path $Root 'parent') -RepoRoot $Root
if($lease.stage-ne'postprocess'-or$script:arguments-notcontains'prepare-continuation'){throw 'continuation routing differs'}
''', encoding="utf-8")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(script), str(PROJECT / "simion/run_functional.ps1"), directory],
                                    cwd=REPO, timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_analysis_exit_distinguishes_scientific_failure_from_diagnostic_failure(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "analysis_fixture.ps1"
            script.write_text(r'''param($Runner)
$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$node=$ast.Find({param($a)$a-is[Management.Automation.Language.FunctionDefinitionAst]-and$a.Name-eq'Set-IonProcessorAnalysisConclusion'},$true)
Invoke-Expression $node.Extent.Text
foreach($case in @(@{code=0;execution='completed';science='passed';data='valid';diagnostics=$true},@{code=2;execution='completed';science='not_passed';data='valid';diagnostics=$true},@{code=1;execution='analysis_failed';science='unknown';data='unknown';diagnostics=$false})){
 $summary=@{};Set-IonProcessorAnalysisConclusion -Summary $summary -AnalysisExit $case.code -NativeCompleted $true
 if($summary.execution_status-ne$case.execution-or$summary.science_status-ne$case.science-or$summary.data_validity-ne$case.data-or$summary.diagnostics_complete-ne$case.diagnostics-or-not$summary.native_completed-or$summary.analysis_exit_code-ne$case.code){throw 'analysis conclusion differs'}
}
''', encoding="utf-8")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(script), str(PROJECT / "simion/run_functional.ps1")],
                                    cwd=REPO, timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_scientific_negative_summary_is_manifest_bound_after_owner_branch(self) -> None:
        from projects.dual_pressure_rectilinear_ion_processor.analysis import batching
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "20261029_120000__test__simion__negative-fixture"
            run.mkdir()
            summary = run / "summary.json"
            summary.write_text(json.dumps(dict(role="ion_processor_functional_summary", status="failed", checks={"capture": False})), encoding="utf-8")
            (run / "run_config.json").write_text(json.dumps(dict(schema_version=2, run_id=run.name,
                project="dual_pressure_rectilinear_ion_processor", mode="native_electrode_functional",
                project_root=str(run), inputs={}, artifact_retention=dict(policy_version=1, **{"class": "solver_review"}, reason="Fixture"))), encoding="utf-8")
            script = run / "owner_fixture.ps1"
            script.write_text(r'''param($Runner,$SummaryPath)
$ErrorActionPreference='Stop';$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$node=$ast.Find({param($a)$a-is[Management.Automation.Language.FunctionDefinitionAst]-and$a.Name-eq'Set-IonProcessorAnalysisConclusion'},$true)
Invoke-Expression $node.Extent.Text
function Write-RunJson {param($Path,$Value) $Value|ConvertTo-Json -Depth 32|Set-Content -LiteralPath $Path -Encoding utf8}
$text=[IO.File]::ReadAllText($Runner)
$start=$text.IndexOf('$summary=Get-Content $package.summary')
$end=$text.IndexOf("`n} catch {",$start)
if($start-lt0-or$end-lt0){throw 'missing actual summary branch'}
$package=@{summary=$SummaryPath};$analysisExit=2;$nativeCompleted=$true;$finished=$false;$runSucceeded=$true;$run=Split-Path $SummaryPath
try {Invoke-Expression $text.Substring($start,$end-$start);throw 'negative exit was accepted'} catch {
 if($_.Exception.Message-notmatch'Analysis or required diagnostics incomplete'){throw}
}
if(-not$finished-or$runSucceeded){throw 'negative completion state differs'}
''', encoding="utf-8")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(script), str(PROJECT / "simion/run_functional.ps1"), str(summary)],
                                    cwd=REPO, timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            script.unlink()
            manifest = batching.publish_manifest(run, "failed")
            measured = json.loads(summary.read_text(encoding="utf-8-sig"))
            self.assertEqual((measured["analysis_exit_code"], measured["data_validity"], measured["science_status"]), (2, "valid", "not_passed"))
            self.assertTrue(measured["native_completed"] and measured["diagnostics_complete"])
            self.assertTrue(any(Path(record["path"]).resolve() == summary for record in manifest["outputs"]))

    def test_unknown_writer_finally_does_not_release_or_publish(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "unknown_fixture.ps1"
            script.write_text(r'''param($Runner)
$ErrorActionPreference='Stop'
$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$null,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$node=$ast.Find({param($a)$a-is[Management.Automation.Language.TryStatementAst]-and$a.Body.Extent.Text-match'Enter-ArtifactWorkflowCapacitySession'},$true)
if($null-eq$node-or$null-eq$node.Finally){throw 'missing owner finally'}
function Exit-HostExecutionLease {throw 'host release was called'}
function Exit-ArtifactWorkflowCapacitySession {throw 'capacity release was called'}
function Apply-RunArtifactRetention {throw 'retention was called'}
function Set-IonProcessorRunStage {param($Context,$Stage)}
$runObservation=@{stage='finalization';timer=[Diagnostics.Stopwatch]::StartNew()};$failureStage='';$failureReason=''
$writersStopped=$false;$lease=@{};$capacity=@{};$package=@{};$savedPythonPath=$env:PYTHONPATH
Push-Location .
Invoke-Expression ('try {} finally '+$node.Finally.Extent.Text)
''', encoding="utf-8")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(script), str(PROJECT / "simion/run_functional.ps1")],
                                    cwd=REPO, timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def check_mode(self, mode: str) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 required for real Windows file-guard fixture")
        with tempfile.TemporaryDirectory(prefix="native_guard_fixture_") as temporary:
            directory = Path(temporary)
            baseline = json.loads((PROJECT / "config/baseline.json").read_text(encoding="utf-8"))
            numerics = json.loads((PROJECT / "config/numerics.json").read_text(encoding="utf-8"))
            model = {"native_projection": native_projection(baseline, numerics)}
            (directory / "resolved_model.json").write_text(json.dumps(model), encoding="utf-8")
            script = directory / "fixture.ps1"
            script.write_text(HARNESS, encoding="utf-8")
            result = subprocess.run([pwsh, "-NoLogo", "-NoProfile", "-File", str(script), str(REPO),
                                     str(PROJECT / "simion/run_functional.ps1"), str(directory), mode],
                                    cwd=REPO, timeout=30, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("GUARD_FIXTURE_PASS", result.stdout)
            receipt = json.loads((directory / "verification.json").read_text(encoding="utf-8-sig"))
            if mode != "acquisition":
                self.assertEqual(len(receipt["records"]), len(model["native_projection"]["electrode_ids"])+3)
            if mode == "drift":
                self.assertEqual(sum(r["verified"] for r in receipt["records"]), len(receipt["records"])-1)
                self.assertIn("identity changed", " ".join(receipt["errors"]))

    def test_all_derived_members_guarded_and_verified(self) -> None:
        self.check_mode("success")

    def test_fresh_writable_build_is_persisted_before_guarding(self) -> None:
        self.check_mode("fresh")

    def test_existing_owner_guard_is_preserved(self) -> None:
        self.check_mode("outer")

    def test_identity_drift_records_failure_and_releases_all_owned_guards(self) -> None:
        self.check_mode("drift")

    def test_partial_acquisition_failure_releases_owned_guards(self) -> None:
        self.check_mode("acquisition")

    def test_post_formal_failure_waits_for_healthy_worker_without_stopping_it(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 required for real healthy-worker failure fixture")
        with tempfile.TemporaryDirectory(prefix="healthy_formal_failure_") as temporary:
            directory = Path(temporary)
            script = directory / "fixture.ps1"
            script.write_text(HEALTHY_FORMAL_FAILURE_HARNESS, encoding="utf-8")
            result = subprocess.run(
                [pwsh, "-NoLogo", "-NoProfile", "-File", str(script),
                 str(PROJECT / "simion/run_functional.ps1"), str(directory)],
                cwd=REPO, timeout=30, capture_output=True, text=True,
                encoding="utf-8", errors="replace", check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("HEALTHY_FORMAL_FAILURE_PASS", result.stdout)
