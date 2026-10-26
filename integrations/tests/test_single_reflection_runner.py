"""The public single-reflection owner creates and terminalizes its managed run."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "integrations/workflows/single_reflection_flight/run.ps1"


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is required")
class SingleReflectionRunnerTests(unittest.TestCase):
    def test_persistent_iob_copy_admission_reuse_and_rejection(self) -> None:
        """Exercise the production lazy-copy function with the real public copy API."""
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "copy.ps1"
            script.write_text(r'''param($Repo,$Root)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/simion/short_pa_path_support.ps1')
$RepoRoot=$Repo;$Python='inert-unused';$script:admissions=0;$script:reject=$false
$capacity=[pscustomobject]@{committed_new_bytes=[long]0}
$paGuards=[Collections.Generic.List[string]]::new()
function Update-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$Session,$RemainingCommittedNewBytes)
 if($RemainingCommittedNewBytes-gt$Session.committed_new_bytes){
  $script:admissions++
  if($script:reject){throw 'inert capacity admission rejected'}
 }
 $Session.committed_new_bytes=$RemainingCommittedNewBytes
 return @{session=$Session}
}
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'integrations/workflows/single_reflection_flight/execute.ps1'),[ref]$null,[ref]$null)
$definition=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Initialize-InstrumentIobPaCopies'},$true)
. ([scriptblock]::Create($definition.Extent.Text))
$source=Join-Path $Root 'source.pa';$target=Join-Path $Root 'run/simion/iob_fields/source.pa'
[IO.File]::WriteAllText($source,'INERT_PA_NOT_NATIVE_EVIDENCE')
$record=@{path=$source;bytes=(Get-Item -LiteralPath $source).Length;sha256=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash}
$prepared=@{iob_pa_copies=@(@{source_record=$record;destination=$target})}
try {
 Initialize-InstrumentIobPaCopies -Prepared @{iob_pa_copies=@()}
 if($script:admissions-ne0){throw 'zero work acquired capacity'}
 Initialize-InstrumentIobPaCopies -Prepared $prepared
 $writeTime=(Get-Item -LiteralPath $target).LastWriteTimeUtc
 Initialize-InstrumentIobPaCopies -Prepared $prepared
 if($script:admissions-ne1-or$capacity.committed_new_bytes-ne0){throw 'copy was admitted more than once or reservation was not consumed'}
 if((Get-Item -LiteralPath $target).LastWriteTimeUtc-ne$writeTime){throw 'existing run-local copy was rewritten'}
 if($global:MassSpectrometryShortPaCopies.Count-ne0-or$paGuards.Count-ne1){throw 'publication did not transfer to the existing immutable consumption guard'}
 if((Get-FileHash -LiteralPath $source).Hash-ne$record.sha256-or(Get-FileHash -LiteralPath $target).Hash-ne$record.sha256){throw 'source/copy identity changed'}
 $denied=Join-Path $Root 'denied/carrier.pa';$script:reject=$true;$failed=$false
 try {Initialize-InstrumentIobPaCopies -Prepared @{iob_pa_copies=@(@{source_record=$record;destination=$denied})}}
 catch {if($_.Exception.Message-notmatch'capacity admission rejected'){throw};$failed=$true}
 if(-not$failed-or(Test-Path -LiteralPath $denied)){throw 'copy started before capacity admission'}
 Write-Output 'COPY_LIFECYCLE=PASS'
}finally{
 foreach($path in $paGuards){$null=Unprotect-ImmutablePaSource -Source $path}
 if(Test-Path -LiteralPath $target){[IO.File]::SetAttributes($target,[IO.FileAttributes]::Normal)}
}
''', encoding="utf-8")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(REPO), temporary],
                                    cwd=script.parent, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("COPY_LIFECYCLE=PASS", result.stdout)

    def test_owner_selects_default_fly_and_seals_success_or_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            runner = repo / "integrations/workflows/single_reflection_flight/run.ps1"
            runner.parent.mkdir(parents=True)
            shutil.copyfile(RUNNER, runner)
            common = repo / "common"
            (common / "contracts").mkdir(parents=True)
            (common / "require_powershell7.ps1").write_text("", encoding="utf-8")
            (common / "contracts/run_artifact_support.ps1").write_text(_SUPPORT, encoding="utf-8")
            (runner.parent / "execute.ps1").write_text(_EXECUTE, encoding="utf-8")
            python = root / "python.cmd"
            python.write_text('@echo off\r\necho %*>> "%~dp0python_calls.log"\r\nexit /b 0\r\n', encoding="utf-8")
            request = root / "request.json"
            budget = root / "budget.json"
            request.write_text("{}\n", encoding="utf-8")
            budget.write_text("{}\n", encoding="utf-8")

            success = self._run(repo, python, request, budget, "20261023_020000__sim__simion__single-reflection-owner")
            self.assertEqual(success.returncode, 0, success.stdout + success.stderr)
            self.assertIn("SINGLE_REFLECTION_RUN=PASS", success.stdout)
            run = root / "artifacts/projects/instrument_assembly/runs/20261023_020000__sim__simion__single-reflection-owner"
            invocation = json.loads((run / "results/invocation.json").read_text(encoding="utf-8"))
            self.assertEqual(invocation["stage"], "fly")
            self.assertTrue(invocation["fly"])
            self.assertEqual(invocation["capacity_lease_id"], "owner-capacity-session")
            self.assertFalse(invocation["field_design_only"])
            self.assertEqual(json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))["status"], "success")
            self.assertEqual(json.loads((run / "summary.json").read_text(encoding="utf-8"))["requested_stage"], "fly")
            self.assertFalse(json.loads((run / "summary.json").read_text(encoding="utf-8"))["fly_executed"])
            config = json.loads((run / "run_config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["inputs"]["public_runner"], str(run / "inputs/run_single_reflection_flight.ps1"))
            events = (run / "events.txt").read_text(encoding="utf-8")
            self.assertIn("capacity:0", events)
            self.assertIn("retention", events)
            self.assertIn("capacity_release", events)
            self.assertEqual(events.count("capacity:0\n"), 1)
            self.assertEqual(events.count("capacity_release\n"), 1)

            failed = self._run(repo, python, request, budget, "20261023_020001__sim__simion__single-reflection-owner", fail=True)
            self.assertNotEqual(failed.returncode, 0)
            failed_run = root / "artifacts/projects/instrument_assembly/runs/20261023_020001__sim__simion__single-reflection-owner"
            failed_summary = json.loads((failed_run / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(failed_summary["status"], "failed")
            self.assertEqual(failed_summary["failure_stage"], "execute_frozen_workflow")
            self.assertEqual(json.loads((failed_run / "run_manifest.json").read_text(encoding="utf-8"))["status"], "failed")

            before_calls = (root / 'python_calls.log').read_text()
            deferred = self._run(repo, python, request, budget,
                '20261023_020004__sim__simion__single-reflection-owner', defer=True)
            self.assertNotEqual(deferred.returncode, 0)
            deferred_run = root / 'artifacts/projects/instrument_assembly/runs/20261023_020004__sim__simion__single-reflection-owner'
            summary = json.loads((deferred_run / 'summary.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(summary['reason'], 'inert native audit failure')
            self.assertTrue(summary['capacity_finalization_deferred'])
            self.assertEqual(summary['capacity_accounting_failure'], 'inert accounting failure')
            self.assertNotIn('capacity_release', (deferred_run / 'events.txt').read_text())
            self.assertEqual((root / 'python_calls.log').read_text(), before_calls, 'deferred owner sealed the payload')

            parent = root / "parent"
            parent.mkdir()
            borrowed = root / "grandparent/native.log"
            borrowed.parent.mkdir()
            borrowed.write_text("INERT_NOT_NATIVE_EVIDENCE", encoding="utf-8")
            (parent / "run_manifest.json").write_text(json.dumps(dict(inputs=dict(continuation_artifact_baseline_0=dict(path=str(borrowed))))), encoding="utf-8")
            request.write_text(json.dumps(dict(continuation=dict(predecessor_run_manifest=dict(path="parent/run_manifest.json")))), encoding="utf-8")
            continued = self._run(repo, python, request, budget, "20261023_020002__sim__simion__single-reflection-owner")
            self.assertEqual(continued.returncode, 0, continued.stdout + continued.stderr)
            continued_run = root / "artifacts/projects/instrument_assembly/runs/20261023_020002__sim__simion__single-reflection-owner"
            self.assertEqual(json.loads((continued_run / "protected.json").read_text(encoding="utf-8-sig")), [str(continued_run), str(parent), str(borrowed)])
            workbench_run_id = "20261023_020003__sim__simion__single-reflection-owner"
            workbench_result = self._run(repo, python, request, budget, workbench_run_id, workbench=True)
            self.assertEqual(workbench_result.returncode, 0, workbench_result.stdout + workbench_result.stderr)
            workbench_run = root / "artifacts/projects/instrument_assembly/runs" / workbench_run_id
            self.assertTrue(json.loads((workbench_run / "summary.json").read_text(encoding="utf-8-sig"))["workbench_executed"])

    def test_execute_finalization_preserves_replaced_owner_session_on_accounting_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / 'execute_finalization.ps1'
            script.write_text(r'''param($Repo)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'integrations/workflows/single_reflection_flight/execute.ps1'),[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Extent.Text.StartsWith('if($capacity){')-and$n.Extent.Text.Contains('defer_capacity_finalization')},$true)
if($null-eq$node){throw 'actual capacity finalization boundary missing'}
$Python='unused';$RepoRoot=$Repo
function Exit-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session) $script:released++}
function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$RemainingCommittedNewBytes) $script:zeroed++;$Session.committed_new_bytes=$RemainingCommittedNewBytes}
$results=@()
foreach($mode in @('borrowed','owned','deferred')){
 $script:released=0;$script:zeroed=0
 $WorkflowCapacitySession=[pscustomobject]@{committed_new_bytes=100}
 $capacity=[pscustomobject]@{committed_new_bytes=100}
 $ownsCapacity=$mode-eq'owned'
 if($mode-eq'deferred'){$capacity|Add-Member -NotePropertyName defer_capacity_finalization -NotePropertyValue 'accounting failed'}
 . ([scriptblock]::Create($node.Extent.Text))
 $reason=if($WorkflowCapacitySession.PSObject.Properties['defer_capacity_finalization']){$WorkflowCapacitySession.defer_capacity_finalization}else{''}
 $results+=@{mode=$mode;released=$script:released;zeroed=$script:zeroed;reason=$reason;committed=$capacity.committed_new_bytes}
}
ConvertTo-Json -InputObject $results -Compress
''', encoding='utf-8')
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(REPO)],
                cwd=script.parent, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            rows = json.loads(result.stdout)
            self.assertEqual([(r['released'], r['zeroed']) for r in rows], [(0, 1), (1, 0), (0, 0)])
            self.assertEqual(rows[2]['reason'], 'accounting failed')
            self.assertEqual(rows[2]['committed'], 100)

    def test_runner_has_no_wall_clock_termination_policy(self) -> None:
        source = RUNNER.read_text(encoding="utf-8")
        self.assertNotIn("wall_clock_seconds", source)
        self.assertIn("execute.ps1", source)
        self.assertIn("Complete-FailedRun", source)
        self.assertIn("-UseShortExecutionPath", source)
        self.assertIn("oatof_reflectron_ideal_10_5.gem", source)
        self.assertIn("Remove-RunPackageExecutionAlias -Package $package", source)

    @staticmethod
    def _run(repo: Path, python: Path, request: Path, budget: Path, run_id: str, *, fail: bool = False, workbench: bool = False, defer: bool = False) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        if fail:
            env["SINGLE_REFLECTION_RUNNER_TEST_FAIL"] = "1"
        if defer:
            env['SINGLE_REFLECTION_RUNNER_TEST_DEFER'] = '1'
        return subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(repo / "integrations/workflows/single_reflection_flight/run.ps1"),
             "-Request", str(request), "-ExecutionBudgetPath", str(budget), "-RunId", run_id,
             "-Python", str(python), "-RepoRoot", str(repo), *(["-WorkbenchOnly"] if workbench else [])],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )


_SUPPORT = r'''
function Write-RunJson { param($Path,$Value,$Depth) $Value|ConvertTo-Json -Depth 100|Set-Content -LiteralPath $Path -Encoding utf8 }
function Copy-VerifiedRunInput { param($Source,$Destination) Copy-Item -LiteralPath $Source -Destination $Destination }
function New-RunPackage {
 param($Python,$RepoRoot,$ArtifactRoot,$RunId,$Project,$Mode,$Software,[switch]$RetentionContractEnabled,$RetentionClass,$RetentionReason,[switch]$CapacityLedgerLifecycleEnabled,[switch]$UseShortExecutionPath,$AdditionalDirectories,$ExpectedExecutionRelativePaths)
 $run=Join-Path $ArtifactRoot "runs/$RunId";New-Item -ItemType Directory -Force -Path (Join-Path $run 'inputs'),(Join-Path $run 'results'),(Join-Path $run 'logs')|Out-Null
 Write-RunJson -Path (Join-Path $run 'run_config.json') -Value @{run_id=$RunId;project=$Project;mode=$Mode;inputs=@{};artifact_retention=@{class='solver_review'}}
 Write-RunJson -Path (Join-Path $run 'summary.json') -Value @{status='checkpoint'}
 return [pscustomobject]@{run_dir=$run;artifact_run_dir=$run;input_dir=(Join-Path $run 'inputs');result_dir=(Join-Path $run 'results');log_dir=(Join-Path $run 'logs');run_config=(Join-Path $run 'run_config.json');summary=(Join-Path $run 'summary.json')}
}
function Remove-RunPackageExecutionAlias { param($Package) }
function Enter-ArtifactWorkflowCapacitySession { param($RunDirectory,$CommittedNewBytes,$ProtectedPaths) Write-RunJson -Path (Join-Path $RunDirectory 'protected.json') -Value @($ProtectedPaths);[IO.File]::AppendAllText((Join-Path $RunDirectory 'events.txt'),"capacity:$CommittedNewBytes`n");$global:ownerCapacitySession=[pscustomobject]@{status='active';run=$RunDirectory;lease_id='owner-capacity-session'};return $global:ownerCapacitySession }
function Update-ArtifactWorkflowCapacitySession { param($Session) return [pscustomobject]@{session=$Session} }
function Exit-ArtifactWorkflowCapacitySession { param($Session) [IO.File]::AppendAllText((Join-Path $Session.run 'events.txt'),"capacity_release`n");$Session.status='released' }
function Apply-RunArtifactRetention { param($RunConfig) $run=Split-Path -Parent $RunConfig;[IO.File]::AppendAllText((Join-Path $run 'events.txt'),"retention`n");$path=Join-Path $run 'retention_actions.json';'{}'|Set-Content $path;return $path }
function Write-VerifiedRunManifest { param($RunConfig,$Status) $run=Split-Path -Parent $RunConfig;Write-RunJson -Path (Join-Path $run 'run_manifest.json') -Value @{status=$Status} }
function Complete-FailedRun { param($RunConfig,$Summary,$SummaryRole,$Reason,$Software,$Status,$FailureStage,$AdditionalSummaryProperties) $value=@{status=$Status;failure_stage=$FailureStage;reason=$Reason};foreach($key in $AdditionalSummaryProperties.Keys){$value[$key]=$AdditionalSummaryProperties[$key]};Write-RunJson -Path $Summary -Value $value;Write-VerifiedRunManifest -RunConfig $RunConfig -Status $Status }
'''

_EXECUTE = r'''
param($Request,$ExecutionBudgetPath,$OutputDirectory,[switch]$FieldDesignOnly,[switch]$WorkbenchOnly,[switch]$Fly,$RepoRoot,$Python,$WorkflowCapacitySession)
if(-not[object]::ReferenceEquals($WorkflowCapacitySession,$global:ownerCapacitySession)-or$WorkflowCapacitySession.status-ne'active'){throw 'execute did not borrow the owner capacity object'}
if($env:SINGLE_REFLECTION_RUNNER_TEST_DEFER){$WorkflowCapacitySession|Add-Member -NotePropertyName defer_capacity_finalization -NotePropertyValue 'inert accounting failure';throw 'inert native audit failure'}
if($env:SINGLE_REFLECTION_RUNNER_TEST_FAIL){throw 'inert execute failure'}
if($WorkbenchOnly){$folder=Join-Path $OutputDirectory 'results/single_reflection';New-Item -ItemType Directory -Path $folder|Out-Null;@{role='single_reflection_workbench_preparation'}|ConvertTo-Json|Set-Content (Join-Path $folder 'workbench_preparation.json')}
$selected=if($FieldDesignOnly){'field_design'}elseif($WorkbenchOnly){'workbench'}else{'fly'};@{stage=$selected;field_design_only=[bool]$FieldDesignOnly;workbench_only=[bool]$WorkbenchOnly;fly=[bool]$Fly;capacity_lease_id=$WorkflowCapacitySession.lease_id}|ConvertTo-Json|Set-Content (Join-Path $OutputDirectory 'results/invocation.json') -Encoding utf8
'''


if __name__ == "__main__":
    unittest.main()
