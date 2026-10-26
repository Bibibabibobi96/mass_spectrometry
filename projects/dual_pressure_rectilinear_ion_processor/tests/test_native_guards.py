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
foreach($name in @('Enter-IonProcessorNativeFlightGuards','Complete-IonProcessorNativeFlightGuards','Wait-IonProcessorExistingFormalProcesses')){
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
$wait=$ast.Find({param($a) $a-is[Management.Automation.Language.FunctionDefinitionAst]-and$a.Name-eq'Wait-IonProcessorExistingFormalProcesses'},$true)
if($null-eq$wait){throw 'missing healthy-formal completion helper'}
if($wait.Extent.Text-match'Stop-ManagedSolverProcesses'){throw 'healthy-formal completion helper must not stop the solver'}
Invoke-Expression $wait.Extent.Text
$dispatchTry=@($ast.FindAll({param($a) $a-is[Management.Automation.Language.TryStatementAst]-and$a.Body.Extent.Text-match'Invoke-ResourceBudgetedProcesses'},$true)|Sort-Object { $_.Extent.EndOffset-$_.Extent.StartOffset }|Select-Object -First 1)
$catch=$(if($null-ne$dispatchTry){$dispatchTry.CatchClauses[0]}else{$null})
if($null-eq$catch-or$catch.Extent.Text-notmatch'Wait-IonProcessorExistingFormalProcesses'){throw 'dispatch failure must wait for the formal worker'}
if($catch.Extent.Text-match'Stop-ManagedSolverProcesses'){throw 'dispatch failure must not stop the formal worker'}
$marker=Join-Path $Directory 'natural_terminal.marker'
$pwsh=(Get-Command pwsh -ErrorAction Stop).Source
$child=Start-Process -FilePath $pwsh -ArgumentList @('-NoLogo','-NoProfile','-Command',"Start-Sleep -Milliseconds 300; Set-Content -LiteralPath '$marker' -Value natural") -PassThru
$record=[pscustomobject]@{active=$true;completed=$false;pressure_terminated=$false;exit_code=$null;process=$child}
$caught=$false
try {throw 'unrelated post-formal failure'} catch {Wait-IonProcessorExistingFormalProcesses -ProcessRecords @($record);$caught=$true}
if(-not$caught-or-not$record.completed-or$record.active){throw 'healthy formal worker was not awaited to terminal'}
if(-not(Test-Path -LiteralPath $marker)){throw 'healthy formal worker did not naturally publish its marker'}
if($record.exit_code-ne0){throw 'healthy formal worker exit was not preserved'}
'HEALTHY_FORMAL_FAILURE_PASS'
'''


class NativeGuardTests(unittest.TestCase):
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
