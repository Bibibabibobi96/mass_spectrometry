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
            (common / "contracts/run_artifact_workflow.ps1").write_text(_WORKFLOW, encoding="utf-8")
            (common / "paths").mkdir()
            (common / "paths/workspace_paths.ps1").write_text(_PATHS, encoding="utf-8")
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
            self.assertIn(f'RESULT={root / "artifacts/projects/instrument_assembly/scratch/workflow_results/20261023_020000__sim__simion__single-reflection-owner/result.json"} TOTAL_SECONDS=', success.stdout)
            invocation = json.loads((run / "results/invocation.json").read_text(encoding="utf-8"))
            self.assertEqual(invocation["stage"], "fly")
            self.assertTrue(invocation["fly"])
            self.assertEqual(invocation["capacity_lease_id"], "owner-capacity-session")
            self.assertFalse(invocation["field_design_only"])
            self.assertEqual(json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))["status"], "success")
            self.assertEqual(json.loads((run / "summary.json").read_text(encoding="utf-8"))["requested_stage"], "fly")
            self.assertFalse(json.loads((run / "summary.json").read_text(encoding="utf-8"))["fly_executed"])
            summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["simulation_path"], "continuous_assembly")
            self.assertEqual(summary["trajectory_execution"], "not_executed")
            self.assertEqual(summary["composition_plan_path"], str(run / "inputs/composition_plan.json"))
            self.assertEqual(summary["source_provenance_path"], str(run / "inputs/source_provenance.json"))
            self.assertGreater(summary["elapsed_before_finalization_seconds"], 0)
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
            request_data = json.loads(request.read_text(encoding="utf-8"))
            request_data["source"] = {"kind": "recorded_pre_pulse_state", "instance_id": "oatof"}
            request.write_text(json.dumps(request_data), encoding="utf-8")
            workbench_result = self._run(repo, python, request, budget, workbench_run_id, workbench=True)
            self.assertEqual(workbench_result.returncode, 0, workbench_result.stdout + workbench_result.stderr)
            workbench_run = root / "artifacts/projects/instrument_assembly/runs" / workbench_run_id
            self.assertTrue(json.loads((workbench_run / "summary.json").read_text(encoding="utf-8-sig"))["workbench_executed"])
            restarted = json.loads((workbench_run / "summary.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(restarted["simulation_path"], "continuous_assembly")
            self.assertEqual(restarted['original_birth_to_terminal_path'], 'segmented_handoff')
            self.assertEqual(restarted["source_kind"], "recorded_pre_pulse_state")
            self.assertTrue(restarted["state_restart"])
            self.assertEqual(restarted["restart_state_time_us"], 80.0)
            self.assertEqual(restarted["trajectory_execution"], "not_executed")
            self.assertFalse(restarted['state_restart_executed'])
            self.assertIsNone(restarted['restart_plane'])
            self.assertEqual(restarted['continuous_segment_start'], 'recorded_pre_pulse_volume_state')
            self.assertEqual(restarted['continued_particle_ids'], [8, 7])
            self.assertEqual(restarted['original_mother_particle_count'], 100)
            self.assertEqual(restarted['uncontinued_mother_particle_ids'], [i for i in range(1, 101) if i not in (7, 8)])
            self.assertEqual(restarted['state_time_semantics'], 'recorded_pre_pulse_state_time_us_no_epoch_shift')

            for index, (kind, extent, reused, expected) in enumerate((
                    ('recorded_birth', 'original_birth_to_terminal', False, 'continuous_assembly'),
                    ('recorded_pre_pulse_state', 'declared_source_to_terminal', False, 'continuous_assembly'),
                    ('recorded_pre_pulse_state', 'original_birth_to_terminal', False, 'segmented_handoff'),
                    ('recorded_pre_pulse_state', 'original_birth_to_terminal', True, 'segmented_handoff')), 10):
                request_data['source'] = dict(kind=kind, instance_id='oatof' if kind=='recorded_pre_pulse_state' else 'multipole')
                request_data['propagation_scope'] = extent
                definition = request.parent/'validation.json'
                definition.write_text(json.dumps(dict(question='predeclared functional fixture')), encoding='utf-8')
                request_data['validation_contract'] = dict(path=str(definition))
                request.write_text(json.dumps(request_data), encoding='utf-8')
                run_id = f'20261023_0200{index:02d}__sim__simion__single-reflection-owner'
                result = self._run(repo, python, request, budget, run_id, native=not reused, reused=reused)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                report = json.loads((root/'artifacts/projects/instrument_assembly/runs'/run_id/'summary.json').read_text())
                self.assertEqual(report['simulation_path'], expected)
                self.assertEqual(report['propagation_scope'], extent)
                frozen = root/'artifacts/projects/instrument_assembly/runs'/run_id/'inputs/functional_validation.json'
                self.assertEqual(Path(report['validation_contract_path']), frozen)
                self.assertEqual(frozen.read_bytes(), definition.read_bytes())
                self.assertEqual(report['clock_epoch_id'], 'instrument_clock_epoch_v1')
                self.assertEqual(report['target_frame_id'], 'oatof_global')
                self.assertEqual(report['continuous_segment_executed'], not reused)
                self.assertEqual(report['native_flight_batch_count'], 0 if reused else 1)
                if reused:
                    self.assertEqual(report['trajectory_execution'], 'reused_complete_batches')
                    self.assertFalse(report['state_restart_executed'])
                    self.assertEqual(report['reused_flight_batch_count'], 2)

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
            self.assertEqual([(r['released'], r['zeroed']) for r in rows], [(0, 0), (1, 0), (0, 0)])
            self.assertEqual(rows[2]['reason'], 'accounting failed')
            self.assertEqual(rows[2]['committed'], 100)

    @staticmethod
    def _run(repo: Path, python: Path, request: Path, budget: Path, run_id: str, *, fail: bool = False, workbench: bool = False, defer: bool = False, native: bool = False, reused: bool = False) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        if fail:
            env["SINGLE_REFLECTION_RUNNER_TEST_FAIL"] = "1"
        if defer:
            env['SINGLE_REFLECTION_RUNNER_TEST_DEFER'] = '1'
        if native:
            env['SINGLE_REFLECTION_RUNNER_TEST_NATIVE'] = '1'
        if reused:
            env['SINGLE_REFLECTION_RUNNER_TEST_REUSED'] = '1'
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
function Copy-VerifiedRunInput { param($Source,$Destination) Copy-Item -LiteralPath $Source -Destination $Destination;return $Destination }
function New-RunPackage {
 param($Python,$RepoRoot,$ArtifactRoot,$RunId,$Project,$Mode,$Software,[switch]$RetentionContractEnabled,$RetentionClass,$RetentionReason,[switch]$CapacityLedgerLifecycleEnabled,[switch]$UseShortExecutionPath,$AdditionalDirectories,$ExpectedExecutionRelativePaths,$PathContext)
 $run=Join-Path $ArtifactRoot "runs/$RunId";New-Item -ItemType Directory -Force -Path (Join-Path $run 'inputs'),(Join-Path $run 'results'),(Join-Path $run 'logs')|Out-Null
 Write-RunJson -Path (Join-Path $run 'run_config.json') -Value @{run_id=$RunId;project=$Project;mode=$Mode;inputs=@{};artifact_retention=@{class='solver_review'}}
 Write-RunJson -Path (Join-Path $run 'summary.json') -Value @{status='checkpoint'}
 return [pscustomobject]@{native_path_preparation=@{calls=0;elapsed_seconds=0.0;transport_bytes=0};run_dir=$run;artifact_run_dir=$run;input_dir=(Join-Path $run 'inputs');result_dir=(Join-Path $run 'results');log_dir=(Join-Path $run 'logs');run_config=(Join-Path $run 'run_config.json');summary=(Join-Path $run 'results/../summary.json')}
}
function Remove-RunPackageExecutionAlias { param($Package) }
function Enter-ArtifactWorkflowCapacitySession { param($RunDirectory,$CommittedNewBytes,$ProtectedPaths,$SourceReferences,$Owner) foreach($source in $SourceReferences){$ProtectedPaths+=@($source.protected_paths)};Write-RunJson -Path (Join-Path $RunDirectory 'protected.json') -Value @($ProtectedPaths);[IO.File]::AppendAllText((Join-Path $RunDirectory 'events.txt'),"capacity:$CommittedNewBytes`n");$global:ownerCapacitySession=[pscustomobject]@{status='active';run=$RunDirectory;lease_id='owner-capacity-session';owner=$Owner};return $global:ownerCapacitySession }
function Update-ArtifactWorkflowCapacitySession { param($Session) return [pscustomobject]@{session=$Session} }
function Exit-ArtifactWorkflowCapacitySession { param($Session) [IO.File]::AppendAllText((Join-Path $Session.run 'events.txt'),"capacity_release`n");$Session.status='released' }
function Save-RunEnvironment {param($Names);return @{}}
function Restore-RunEnvironment {param($Names,$Snapshot)}
function Invoke-RunToolRootContext {
 param($RepoRoot,$Operation)
 # Source ownership is independently tested with real two-root leases. This is the runner routing fixture.
 $parent=Join-Path (Split-Path -Parent $RepoRoot) 'parent'
 $paths=if(Test-Path (Join-Path $parent 'run_manifest.json')){@($parent,(Join-Path (Split-Path -Parent $RepoRoot) 'grandparent/native.log'))}else{@()}
 return @{source_references=@(@{protected_paths=$paths})}
}
'''

_WORKFLOW = r'''
param($ResultPath,[switch]$ResumeFinalization)
. (Join-Path $PSScriptRoot 'run_artifact_support.ps1')
function Initialize-RunArtifactPowerShellOwner {
 param($Python,$RepoRoot,$Package,$CapacitySession,$EntrypointPath,$CommitmentInputPaths,$ResultPath,$Software)
 if($CapacitySession.owner-cne('run-artifact-workflow:instrument_assembly:'+(Get-Content $Package.run_config -Raw|ConvertFrom-Json).run_id)){throw 'Public owner session identity was not passed'}
 if(-not(Test-Path $EntrypointPath)-or@($CommitmentInputPaths).Count-ne1-or-not(Test-Path $CommitmentInputPaths[0])){throw 'Public owner lacks frozen entrypoint/budget'}
 $runId=(Get-Content $Package.run_config -Raw|ConvertFrom-Json).run_id
 if(-not$ResultPath){$ResultPath=Join-Path (Split-Path -Parent (Split-Path -Parent $Package.artifact_run_dir)) ('scratch/workflow_results/'+$runId+'/result.json')}
 return @{completion_written=$false;session=$CapacitySession;package=$Package;result_path=$ResultPath}
}
function Complete-RunArtifactPowerShellOwner {
 param($Context,$Status,$Summary,$OutputPaths,$WriterCompletion,$WritersStopped,$OriginalFailure)
 if(-not$WritersStopped-or$WriterCompletion.operations.Count-or$WriterCompletion.resource_releases.Count){throw 'Inert consumer fixture started an unexpected writer'}
 $run=$Context.package.artifact_run_dir
 [IO.File]::AppendAllText((Join-Path $run 'events.txt'),"retention`n")
 $Summary.status=$Status
 Write-RunJson -Path $Context.package.summary -Value $Summary
 Write-RunJson -Path (Join-Path $run 'run_manifest.json') -Value @{status=$Status}
 $null=Exit-ArtifactWorkflowCapacitySession -Session $Context.session
 $Context.completion_written=$true
 return @{status=$Status}
}
'''

_PATHS = r'''
function Resolve-WorkspacePaths {param($SourceRoot,$Python);$root=Join-Path (Split-Path -Parent $SourceRoot) artifacts;return @{source_root=$SourceRoot;artifact_root=$root;execution_root=(Join-Path $root common/execution_aliases);host_resource_state_path=(Join-Path $root common/host.sqlite3)}}
'''

_EXECUTE = r'''
param($NativeOperations,$ResourceReleases,$PhaseTimings,$Request,$ExecutionBudgetPath,$OutputDirectory,[switch]$FieldDesignOnly,[switch]$WorkbenchOnly,[switch]$Fly,$RepoRoot,$Python,$WorkflowCapacitySession)
if(-not[object]::ReferenceEquals($WorkflowCapacitySession,$global:ownerCapacitySession)-or$WorkflowCapacitySession.status-ne'active'){throw 'execute did not borrow the owner capacity object'}
if($env:SINGLE_REFLECTION_RUNNER_TEST_DEFER){$WorkflowCapacitySession|Add-Member -NotePropertyName defer_capacity_finalization -NotePropertyValue 'inert accounting failure';throw 'inert native audit failure'}
if($env:SINGLE_REFLECTION_RUNNER_TEST_FAIL){throw 'inert execute failure'}
$requestData=Get-Content -LiteralPath $Request -Raw|ConvertFrom-Json -AsHashtable
$folder=Join-Path $OutputDirectory 'results/single_reflection';New-Item -ItemType Directory -Path $folder -Force|Out-Null
Write-RunJson -Path (Join-Path $folder 'preparation_receipt.json') -Value @{default_replay_requested=$false}
Write-RunJson -Path (Join-Path $folder 'workbench_preparation.json') -Value @{default_replay_verification=@{requested=$false;status='not_requested';native_fly_performed=$false}}
$source=@{source_kind='recorded_birth';source_instance_id='multipole';propagation_scope='declared_source_to_terminal';
 state_time_semantics='original_birth_time_s_times_1e6_no_epoch_shift';source_frame_id='multipole_local';target_frame_id='oatof_global';clock_epoch_id='instrument_clock_epoch_v1';particle_count=100}
if($requestData.ContainsKey('propagation_scope')){$source.propagation_scope=$requestData.propagation_scope}
if($requestData.ContainsKey('source')){
 $source.source_kind=$requestData.source.kind;$source.source_instance_id=$requestData.source.instance_id
 if($source.source_kind-eq'recorded_pre_pulse_state'){
  $source.restart_state_time_us=80.0;$source.continued_particle_ids=@(8,7);$source.original_mother_particle_ids=@(1..100)
  $source.original_mother_particle_count=100;$source.uncontinued_mother_particle_ids=@(1..100|Where-Object {$_-notin@(7,8)})
  $source.source_frame_id='oatof_global';$source.state_time_semantics='recorded_pre_pulse_state_time_us_no_epoch_shift'
 }
}
if($requestData.ContainsKey('validation_contract')){
 $frozen=Join-Path $OutputDirectory 'inputs/functional_validation.json'
 Copy-Item -LiteralPath $requestData.validation_contract.path -Destination $frozen
 $source.input_records=@{validation_contract=@{path=(Join-Path $OutputDirectory 'retired_execution_alias/inputs/functional_validation.json')}}
}
$source|ConvertTo-Json|Set-Content (Join-Path $OutputDirectory 'inputs/source_provenance.json') -Encoding utf8
if($env:SINGLE_REFLECTION_RUNNER_TEST_NATIVE-or$env:SINGLE_REFLECTION_RUNNER_TEST_REUSED){
 $folder=Join-Path $OutputDirectory 'results/single_reflection';New-Item -ItemType Directory -Path $folder -Force|Out-Null
 if($env:SINGLE_REFLECTION_RUNNER_TEST_NATIVE){ConvertTo-Json -InputObject @(@{phase='baseline';exit_code=0})|Set-Content (Join-Path $folder 'flight_execution_records.json')}
 else{ConvertTo-Json -InputObject @{default_replay_verification=@{requested=$false;status='not_requested';native_fly_performed=$false};batches=@(@{continuation_source=@{};replay_continuation_source=@{}})}|Set-Content (Join-Path $folder 'workbench_preparation.json')}
}
if($WorkbenchOnly){$folder=Join-Path $OutputDirectory 'results/single_reflection';New-Item -ItemType Directory -Path $folder -Force|Out-Null;@{role='single_reflection_workbench_preparation'}|ConvertTo-Json|Set-Content (Join-Path $folder 'workbench_preparation.json')}
$selected=if($FieldDesignOnly){'field_design'}elseif($WorkbenchOnly){'workbench'}else{'fly'};@{stage=$selected;field_design_only=[bool]$FieldDesignOnly;workbench_only=[bool]$WorkbenchOnly;fly=[bool]$Fly;capacity_lease_id=$WorkflowCapacitySession.lease_id}|ConvertTo-Json|Set-Content (Join-Path $OutputDirectory 'results/invocation.json') -Encoding utf8
'''


if __name__ == "__main__":
    unittest.main()
