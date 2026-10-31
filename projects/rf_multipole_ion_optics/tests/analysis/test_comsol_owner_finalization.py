"""Thin finite COMSOL owner tests; native execution is never invoked."""

from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from common.contracts import test_run_artifact_workflow as workflow_fixture

REPO = Path(__file__).resolve().parents[4]
CLI = REPO / "projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1"
OUTER = (
    REPO
    / "projects/rf_multipole_ion_optics/workflows/no_collision_transport/run_comsol.ps1"
)
PWSH = shutil.which("pwsh")


@unittest.skipUnless(PWSH, "PowerShell 7 required")
class ComsolOwnerFinalizationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = workflow_fixture.RunArtifactWorkflowTests()

    def test_bootstrap_admission_failures_keep_primary_and_restore_explicit_python(
        self,
    ):
        # Actual initialization/try/catch/finally and real environment API.
        # Only admission boundaries are inert; no common fault matrix is copied.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ps = r"""
$ErrorActionPreference='Stop'
. '@@REPO@@/common/contracts/run_artifact_workflow.ps1'
$ast=[Management.Automation.Language.Parser]::ParseFile('@@CLI@@',[ref]$null,[ref]$null)
$ast.FindAll({param($node) $node-is[Management.Automation.Language.FunctionDefinitionAst]},$true)|ForEach-Object{Invoke-Expression $_.Extent.Text}
$outer=@($ast.EndBlock.Statements|Where-Object{
 $_-is[Management.Automation.Language.TryStatementAst]-and@($_.Body.FindAll({param($command) $command-is[Management.Automation.Language.CommandAst]-and$command.GetCommandName()-eq'Enter-ArtifactWorkflowCapacitySession'},$true)).Count
})
if($outer.Count-ne1){throw 'Expected the actual bootstrap admission boundary'}
$first=@($ast.EndBlock.Statements|Where-Object{$_-is[Management.Automation.Language.AssignmentStatementAst]-and$_.Left-is[Management.Automation.Language.VariableExpressionAst]-and$_.Left.VariablePath.UserPath-eq'ownerContext'})[0]
$source=[IO.File]::ReadAllText('@@CLI@@')
$bootstrap=[scriptblock]::Create($source.Substring($first.Extent.StartOffset,$outer[0].Extent.EndOffset-$first.Extent.StartOffset))
function Enter-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$ArtifactRoot,$RunDirectory,$CommittedNewBytes,$ProtectedPaths,$Owner)
 $script:events.Add('capacity')
 if($Python-cne'@@PYTHON@@'-or$env:SIMULATION_PYTHON_EXE-cne$Python){throw 'EXPLICIT_PYTHON_NOT_INSTALLED_BEFORE_HOST_ADMISSION'}
 if(Test-Path -LiteralPath (Join-Path $RepoRoot '.venv')){throw 'Fixture unexpectedly has a local venv'}
 if($scenario-eq'capacity'){throw 'CAPACITY_PRIMARY'}
 $script:session=[pscustomobject]@{fixture=$true;status='active'}
 return $script:session
}
function New-RunPackage {
 param($Python,$RepoRoot,$ArtifactRoot,$PathContext,$RunId,$Project,$Mode,
  [switch]$RetentionContractEnabled,[switch]$CapacityLedgerLifecycleEnabled,
  $RetentionClass,$RetentionReason,$Software,[switch]$UseShortExecutionPath,$ExpectedExecutionRelativePaths)
 $script:events.Add('package')
 if($env:SIMULATION_PYTHON_EXE-cne$Python){throw 'EXPLICIT_PYTHON_LOST_BEFORE_PACKAGE'}
 throw 'PACKAGE_PRIMARY'
}
function Exit-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$Session)
 $script:events.Add('rollback')
 if(-not[object]::ReferenceEquals($Session,$script:session)-or$Python-cne'@@PYTHON@@'-or$env:SIMULATION_PYTHON_EXE-cne$Python){throw 'WRONG_ADMISSION_ROLLBACK'}
 if($scenario-eq'package_cleanup'){throw 'ROLLBACK_SECONDARY'}
}
function Invoke-ResourceBudgetedProcess {$script:nativeCount++;throw 'NATIVE_MUST_NOT_START'}
function Remove-RunPackageExecutionAlias {$script:aliasCount++;throw 'NO_PACKAGE_ALIAS_MUST_EXIST'}
$python='@@PYTHON@@';$repoRoot=Join-Path '@@ROOT@@' 'no-venv-source'
$projectArtifactRoot=Join-Path '@@ROOT@@' 'artifacts/projects/rf_multipole_ion_optics'
$workspacePaths=@{artifact_root=(Join-Path '@@ROOT@@' 'artifacts');host_resource_state_path=(Join-Path '@@ROOT@@' 'host.sqlite3')}
$RunId='20261031_030000__test__comsol__inert-bootstrap';$ProjectId='rf_multipole_ion_optics'
$resolvedBudget=@{limits=@{transient_run_directory_bytes=1048576L}}
$particleSourceInput='unused-source';$sourceFamilyInput='unused-family';$engineeringBudgetInput='unused-budget';$RetentionClass='solver_review';$RetentionReason='inert bootstrap';$executionCapacityPaths=@()
$records=@(foreach($scenario in @('capacity','package','package_cleanup')){
 foreach($callerPresent in @($true,$false)){
  if($callerPresent){$env:SIMULATION_PYTHON_EXE='CALLER_PYTHON'}else{Remove-Item Env:SIMULATION_PYTHON_EXE -ErrorAction SilentlyContinue}
  $env:PYTHONPATH='CALLER_PATH'
  $script:events=[Collections.Generic.List[string]]::new();$script:nativeCount=0;$script:aliasCount=0;$script:session=$null
  $failure=$null;try{& $bootstrap}catch{$failure=$_}
  $expected=if($scenario-eq'capacity'){'CAPACITY_PRIMARY'}else{'PACKAGE_PRIMARY'}
  if($null-eq$failure-or$failure.Exception.Message-cne$expected){throw "PRIMARY_MASKED:$scenario/$($failure.Exception.Message)"}
  $events=$script:events-join','
  $expectedEvents=if($scenario-eq'capacity'){'capacity'}else{'capacity,package,rollback'}
  if($events-cne$expectedEvents){throw "WRONG_ROLLBACK:$events"}
  if($scenario-eq'package_cleanup'-and$failure.Exception.Data['preparation_cleanup_error']-cne'ROLLBACK_SECONDARY'){throw 'SECONDARY_CLEANUP_NOT_PRESERVED'}
  if(($callerPresent-and$env:SIMULATION_PYTHON_EXE-cne'CALLER_PYTHON')-or(-not$callerPresent-and$null-ne[Environment]::GetEnvironmentVariable('SIMULATION_PYTHON_EXE','Process'))-or$env:PYTHONPATH-cne'CALLER_PATH'){throw 'CALLER_ENVIRONMENT_NOT_RESTORED'}
  if($script:nativeCount-or$script:aliasCount-or(Test-Path -LiteralPath $projectArtifactRoot)){throw 'BOOTSTRAP_CREATED_NATIVE_OR_RUN'}
  @{scenario=$scenario;caller_present=$callerPresent;primary=$failure.Exception.Message;events=$events;native_count=$script:nativeCount}
 }
})
ConvertTo-Json -InputObject $records -Compress
"""
            for key, value in {
                "@@REPO@@": str(REPO),
                "@@CLI@@": str(CLI),
                "@@PYTHON@@": sys.executable,
                "@@ROOT@@": str(root),
            }.items():
                ps = ps.replace(key, value.replace("'", "''"))
            outcome = self.fixture.run_ps(root, ps)
            self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
            records = json.loads(outcome.stdout.splitlines()[-1])
            self.assertEqual(len(records), 6)
            self.assertTrue(all(item["native_count"] == 0 for item in records))

    def test_normal_public_prepare_and_optional_family_reach_only_inert_native_boundary(self):
        # The entire normal scripts execute; only the actual native process boundary is inert.
        from common.contracts.capacity_ledger import initialize_capacity_ledger
        import hashlib

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            for relative in ("common", "config", "projects/rf_multipole_ion_optics"):
                shutil.copytree(REPO / relative, source / relative,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            policy = source/"common/contracts/artifact_capacity_policy.json"
            policy_document = json.loads(policy.read_text(encoding="utf-8"))
            # The family arm declares up to 4 GiB total new commitment.
            # A fixed 8 GiB fixture ceiling includes 4 GiB of metadata/headroom;
            # this is admission bookkeeping, not allocated payload or solver RAM.
            policy_document.update(target_gib=8, minimum_free_gib=0)
            policy.write_text(json.dumps(policy_document), encoding="utf-8")
            budget = source / "projects/rf_multipole_ion_optics/variants/quadrupole/config/bare_transport_budget.json"
            document = json.loads(budget.read_text(encoding="utf-8-sig"))
            document["pilot_authorization"]["authorized"] = True
            budget.write_text(json.dumps(document), encoding="utf-8")
            artifacts = root / "artifacts"
            artifacts.mkdir()
            initialize_capacity_ledger(artifacts, objects=[])
            support = source / "common/resource_budget_support.ps1"
            with support.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(r"""
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$UsagePath,$FilePath,$ArgumentList)
 [ordered]@{run_dir=$RunDir;metadata=$env:MULTIPOLE_L3_PARTICLE_SOURCE_METADATA;native_started=$false}|ConvertTo-Json|Set-Content -LiteralPath $env:P4_BOUNDARY_PATH -Encoding utf8
 throw 'P4_INERT_NATIVE_BOUNDARY_NO_PROCESS_STARTED'
}
""")
            original_source = source / "projects/rf_multipole_ion_optics/config/sources/rf_multipole_family_mother_sample_v1_100.csv"
            family = root / "family.json"
            family.write_text(json.dumps({"schema_version": 1, "operating_points": {
                "fixture": {"mass_amu": 100, "charge_state": 1,
                            "kinetic_energy_eV": {"distribution": "uniform", "min": 0, "max": 100}}}}), encoding="utf-8")
            for family_enabled in (False, True):
                with self.subTest(family=family_enabled):
                    boundary = root / ("family_boundary.json" if family_enabled else "plain_boundary.json")
                    run_id = "20261031_09000" + str(int(family_enabled)) + "__test__comsol__p4-normal"
                    command = [PWSH, "-NoProfile", "-NonInteractive", "-File"]
                    if family_enabled:
                        command += [str(source / CLI.relative_to(REPO)), "-ProjectId", "rf_multipole_ion_optics",
                                    "-DesignProfileId", "quadrupole_no_acceleration_full_length",
                                    "-ParticleSourcePath", str(original_source), "-EngineeringBudgetPath", str(budget),
                                    "-SourceFamilyPath", str(family), "-OperatingPointId", "fixture",
                                    "-WorkingRegionMaximumElementSizeMm", "0.5"]
                    else:
                        command += [str(source / OUTER.relative_to(REPO))]
                    command += ["-RuntimeProfileId", "quadrupole_no_acceleration_full_length",
                                "-RunId", run_id, "-PythonExe", sys.executable]
                    environment = dict(os.environ, MASS_SPECTROMETRY_ARTIFACT_ROOT=str(artifacts),
                                       MASS_SPECTROMETRY_EXECUTION_ROOT=str(root / "exec"),
                                       MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(root / "host.sqlite3"),
                                       P4_BOUNDARY_PATH=str(boundary))
                    environment.pop("PYTHONPATH", None)
                    for name in ("MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN",
                                 "MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID",
                                 "MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE"):
                        environment.pop(name, None)
                    outcome = subprocess.run(command, cwd=root, env=environment, capture_output=True,
                                             text=True, encoding="utf-8", errors="replace", timeout=300)
                    self.assertNotEqual(outcome.returncode, 0)
                    self.assertIn("P4_INERT_NATIVE_BOUNDARY_NO_PROCESS_STARTED", outcome.stdout + outcome.stderr)
                    self.assertFalse(json.loads(boundary.read_text(encoding="utf-8-sig"))["native_started"])
                    run = artifacts / "projects/rf_multipole_ion_optics/runs" / run_id
                    config = json.loads((run / "run_config.json").read_text(encoding="utf-8-sig"))
                    self.assertEqual(Path(config["inputs"]["particle_source"]).read_bytes(), original_source.read_bytes())
                    self.assertEqual(Path(config["inputs"]["engineering_budget"]).read_bytes(), budget.read_bytes())
                    metadata = json.loads(Path(config["inputs"]["particle_source_metadata"]).read_text(encoding="utf-8-sig"))
                    if family_enabled:
                        self.assertEqual(Path(config["inputs"]["particle_source_family"]).read_bytes(), family.read_bytes())
                        self.assertEqual(metadata["operating_point_binding"]["source_family_sha256"], hashlib.sha256(family.read_bytes()).hexdigest().upper())
                    else:
                        self.assertIsNone(config["inputs"]["particle_source_family"])
                        self.assertIsNone(metadata["operating_point_binding"])
                    self.assertFalse(list(run.rglob("*.mph")))

    def owner_fixture(self, root):
        _, run, _, _ = self.fixture.invoke_fixture(
            root,
            {},
            retention="solver_review",
            failure_stage="retention_before",
            project="rf_multipole_ion_optics",
            host_state=str(root / "host.sqlite3"),
        )
        for relative in (
            "inputs/execution_request.json",
            "results/execution_completion.json",
            "logs/prepared_wait.json",
        ):
            (run / relative).unlink()
        entry = run / "inputs/finite_owner.ps1"
        shutil.copyfile(CLI, entry)
        budget = run / "inputs/owner_budget.json"
        budget.write_text('{"peak_bytes":1048576}', encoding="utf-8")
        return run, entry, budget

    def setup_ps(self, run, entry, budget, result):
        return f""". '{REPO / "common/contracts/run_artifact_workflow.ps1"}'
$ast=[Management.Automation.Language.Parser]::ParseFile('{CLI}',[ref]$null,[ref]$null)
$ast.FindAll({{param($node) $node-is[Management.Automation.Language.FunctionDefinitionAst]-and$node.Name-in@('Close-FiniteComsolStage','Get-FiniteComsolWriterCompletion','Complete-FiniteComsolOwner')}},$true)|ForEach-Object{{Invoke-Expression $_.Extent.Text}}
$session=Get-Content -LiteralPath '{run / "logs/capacity_session.json"}' -Raw|ConvertFrom-Json
$package=@{{native_path_preparation=@{{calls=0;elapsed_seconds=0.0;transport_bytes=0L}};run_config='{run / "run_config.json"}';run_dir='{run}';artifact_run_dir='{run}'}}
$context=Initialize-RunArtifactPowerShellOwner -Python '{sys.executable}' -RepoRoot '{REPO}' -Package $package -CapacitySession $session -ResultPath '{result}' -EntrypointPath '{entry}' -CommitmentInputPaths @('{budget}') -Software @('Python')
$state=@{{native_attempted=$false;wrapper_observation=$null;launcher_receipt=$null;host_lease=$null;writer_unknown=$false;finalization_started=$false;usage_path=$null;phase_timings=@{{prepare=0.1}};timer=[Diagnostics.Stopwatch]::StartNew()}}
"""

    def test_real_owner_success_and_failure_keep_scientific_status(self):
        for status in ("success", "failed"):
            with (
                self.subTest(status=status),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                run, entry, budget = self.owner_fixture(root)
                config_path = run / "run_config.json"
                config = json.loads(config_path.read_text(encoding="utf-8-sig"))
                config["mode"] = "resolved_design_transport"
                config_path.write_text(json.dumps(config), encoding="utf-8")
                science = run / "inputs/finite_extraction_science.json"
                science.write_text(json.dumps({"resolved_design_sha256": "fixture"}), encoding="utf-8")
                result = root / "owner_result.json"
                ps = (
                    self.setup_ps(run, entry, budget, result)
                    + f"""
# Execute the production scientific-config rewrite before the real finalizer.
# The previous fixture started after this boundary and missed lifecycle loss.
$initial=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
$RunId='{run.name}';$ProjectId='rf_multipole_ion_optics'
$RetentionClass=$initial.artifact_retention.class;$RetentionReason=$initial.artifact_retention.reason
$package.path_context=$initial.paths
$ownerContext=$context
$profile=@{{project_root='fixture'}};$sourceMeta=@{{source_sha256='fixture';operating_point_binding=$null}}
$sourceFamily=$null;$volumeSnapshotReceipt=$null;$volumeReceiptIdentity=$null
$sourceFamilySha=$null;$resolvedHash='fixture';$modeId='fixture';$RuntimeProfileId='fixture';$DesignProfileId='fixture';$StopStage='transport'
$registry=$null;$descriptor=$null;$profiles=$null;$engineeringBudget=$null;$profileResolution=$null
$request=$null;$variables=$null;$envelope=$null;$modeRegistry=$null;$resolved=$null;$particleSource=$null
$sourceMetadata=$null;$numerics=$null;$codeInventory=$null;$evidence=$null;$fieldSamplingPlan=$null;$fieldSamplePoints=$null;$task=$null
$extractionScience='{science}'
$start=@($ast.EndBlock.Statements.FindAll({{param($n) $n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$configDocument'}},$true))[0]
$finish=@($ast.FindAll({{param($n) $n-is[Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'Write-RunJson'-and$n.Extent.Text-match'Value \\$configDocument'}},$true))[0]
if($null-eq$start-or$null-eq$finish){{throw 'Actual scientific configuration boundary missing'}}
$source=[IO.File]::ReadAllText('{CLI}')
Invoke-Expression $source.Substring($start.Extent.StartOffset,$finish.Extent.EndOffset-$start.Extent.StartOffset)
$rewritten=Get-Content -LiteralPath $package.run_config -Raw|ConvertFrom-Json -AsHashtable
if(($rewritten.capacity_ledger_lifecycle|ConvertTo-Json -Compress)-cne($initial.capacity_ledger_lifecycle|ConvertTo-Json -Compress)){{throw 'Package lifecycle authority changed'}}
if($rewritten.inputs.finite_extraction_science-cne$extractionScience){{throw 'Frozen extraction science input was not retained'}}
$primary=$null
if('{status}'-eq'failed'){{try{{throw 'PRIMARY_SOURCE_SENTINEL'}}catch{{$primary=$_}}}}
$summary=@{{role='multipole_finite_3d_transport_summary';qualification_status='UNQUALIFIED';failure_stage='prepare';failure_reason='PRIMARY_SOURCE_SENTINEL'}}
$null=Complete-FiniteComsolOwner -Context $context -State $state -RunId '{run.name}' -Status '{status}' -Summary $summary -OriginalFailure $primary
"""
                )
                outcome = self.fixture.run_ps(root, ps)
                self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
                manifest = json.loads(
                    (run / "run_manifest.json").read_text(encoding="utf-8-sig")
                )
                self.assertEqual(manifest["status"], status)
                answer = json.loads(result.read_text(encoding="utf-8-sig"))
                if status == "failed":
                    self.assertEqual(
                        answer["exception"]["message"], "PRIMARY_SOURCE_SENTINEL"
                    )

    def test_unknown_writer_retains_real_capacity_and_original_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, entry, budget = self.owner_fixture(root)
            result = root / "owner_result.json"
            ps = (
                self.setup_ps(run, entry, budget, result)
                + f"""
$lease=[IO.File]::ReadAllBytes([string]$session.lease.path)
$state.native_attempted=$true
try{{throw 'PRIMARY_NATIVE_SENTINEL'}}catch{{$primary=$_}}
try{{$null=Complete-FiniteComsolOwner -Context $context -State $state -RunId '{run.name}' -Status failed -Summary @{{failure_stage='native'}} -OriginalFailure $primary;throw 'UNKNOWN_ACCEPTED'}}catch{{if($_.Exception.Message-notmatch'native writer completion is unknown'){{throw}}}}
if($context.completion_written-or$context.finalized){{throw 'UNKNOWN_TERMINALIZED'}}
if([Convert]::ToBase64String([IO.File]::ReadAllBytes([string]$session.lease.path))-cne[Convert]::ToBase64String($lease)){{throw 'CAPACITY_CHANGED'}}
"""
            )
            outcome = self.fixture.run_ps(root, ps)
            self.assertEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
            answer = json.loads(result.read_text(encoding="utf-8-sig"))
            self.assertFalse(answer["writers_confirmed"])
            self.assertEqual(answer["exception"]["message"], "PRIMARY_NATIVE_SENTINEL")
            self.assertIn(
                "wrapper process completion is unknown", answer["secondary_errors"][0]
            )

    def test_original_cli_resume_skips_science_and_native_and_keeps_failed_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run, entry, budget = self.owner_fixture(root)
            result = root / "owner_result.json"
            ps = (
                self.setup_ps(run, entry, budget, result)
                + f"""
function Apply-RunArtifactRetention {{throw 'CLEANUP_RETENTION_SENTINEL'}}
try{{throw 'PRIMARY_ANALYSIS_SENTINEL'}}catch{{$primary=$_}}
try{{$null=Complete-FiniteComsolOwner -Context $context -State $state -RunId '{run.name}' -Status failed -Summary @{{failure_stage='analysis';failure_reason='PRIMARY_ANALYSIS_SENTINEL'}} -OriginalFailure $primary;throw 'CLOSURE_UNEXPECTEDLY_PASSED'}}catch{{if($_.Exception.Message-ne'CLEANUP_RETENTION_SENTINEL'){{throw}}}}
"""
            )
            failed = self.fixture.run_ps(root, ps)
            self.assertEqual(failed.returncode, 0, failed.stdout + failed.stderr)
            prior = json.loads(result.read_text(encoding="utf-8-sig"))
            self.assertEqual(prior["exception"]["message"], "PRIMARY_ANALYSIS_SENTINEL")
            self.assertIn("CLEANUP_RETENTION_SENTINEL", prior["secondary_errors"])
            # Resume the actual PowerShell owner's frozen request, not a new callback.
            tree = root / "source"
            target = (
                tree
                / "projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1"
            )
            target.parent.mkdir(parents=True)
            shutil.copyfile(CLI, target)
            outer = (
                tree
                / "projects/rf_multipole_ion_optics/workflows/no_collision_transport/run_comsol.ps1"
            )
            outer.parent.mkdir(parents=True)
            shutil.copyfile(OUTER, outer)
            shutil.copytree(
                REPO / "common/contracts",
                tree / "common/contracts",
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            shutil.copytree(
                REPO / "common/paths",
                tree / "common/paths",
                ignore=shutil.ignore_patterns("__pycache__"),
            )
            for relative in (
                "common/resource_budget_support.ps1",
                "common/require_powershell7.ps1",
                "common/host_execution_lease.ps1",
                "common/host_resource_scheduler.py",
                "common/host_resource_policy.json",
            ):
                destination = tree / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPO / relative, destination)
            before = (root / "callback_count.txt").read_bytes()
            env = os.environ.copy()
            env.pop("PYTHONPATH", None)
            env["MASS_SPECTROMETRY_ARTIFACT_ROOT"] = str(root / "poison_artifacts")
            env["MASS_SPECTROMETRY_EXECUTION_ROOT"] = str(root / "poison_execution")
            env["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"] = str(
                root / "poison.sqlite3"
            )
            outcome = subprocess.run(
                [
                    PWSH,
                    "-NoProfile",
                    "-File",
                    str(outer),
                    "-ResumeFinalization",
                    "-RunId",
                    run.name,
                    "-ResultPath",
                    str(result),
                    "-ArtifactRootPath",
                    str(root / "artifacts"),
                    "-PythonExe",
                    sys.executable,
                ],
                cwd=REPO,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=90,
            )
            self.assertNotEqual(outcome.returncode, 0, outcome.stdout + outcome.stderr)
            self.assertIn(
                "finalization completed; original execution status=failed",
                outcome.stdout + outcome.stderr,
            )
            self.assertEqual((root / "callback_count.txt").read_bytes(), before)
            self.assertEqual(
                json.loads((run / "run_manifest.json").read_text(encoding="utf-8-sig"))[
                    "status"
                ],
                "failed",
            )
            self.assertFalse((tree / "config").exists())
            self.assertFalse((root / "poison_artifacts").exists())
            self.assertFalse((root / "poison_execution").exists())
            self.assertFalse((root / "poison.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
