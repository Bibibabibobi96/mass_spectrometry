"""RF CLI wiring to the real common stopped-writer finalization owner."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from common.contracts import test_run_artifact_workflow as fixtures

REPO = Path(__file__).resolve().parents[4]
PROJECT = "rf_multipole_ion_optics"


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
class RfPowerShellOwnerTests(unittest.TestCase):
    def test_batch_completion_passes_original_native_identity_and_rejects_unknown_exit(self):
        support = REPO / "projects" / PROJECT / "runtime/simion_execution.ps1"
        text = support.read_text()
        callback = text[text.index("    $complete={"):text.index("    $receipt = Invoke-SimionBatchPhase", text.index("    $complete={"))]
        script = """$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$NativeOperations=[Collections.Generic.List[object]]::new();$CaseName=''
""" + callback + """
$record=@{exit_code=0;root_process_id=71;root_process_started_at_utc_ticks=[long]12345;specification=@{name='original-batch'}}
& $complete $record
if($NativeOperations.Count-ne1-or$NativeOperations[0].operation_id-cne'fly:original-batch'-or$NativeOperations[0].observation.process_id-ne71-or$NativeOperations[0].observation.process_started_at_utc_ticks-ne12345){throw 'Native identity was invented or lost'}
$record.exit_code=$null;$blocked=$false;try{& $complete $record}catch{$blocked=$true}
if(-not$blocked-or$NativeOperations.Count-ne1){throw 'Unknown native exit was recorded as stopped'}
"""
        process = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script], cwd=REPO,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_original_clis_resume_publication_seal_and_reject_unknown_without_source_arguments(self):
        helper = fixtures.RunArtifactWorkflowTests()
        for workflow, failure in (("interface_readiness", "publication"),
                                  ("mass_filter_reference", "seal"),
                                  ("interface_readiness", "unknown")):
            with self.subTest(workflow=workflow, failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, run, _, _ = helper.invoke_fixture(root, {}, project=PROJECT,
                    retention="solver_review", failure_stage="retention_before")
                for relative in ("inputs/execution_request.json", "results/execution_completion.json", "logs/prepared_wait.json"):
                    (run / relative).unlink()
                cli = REPO / "projects" / PROJECT / "workflows" / workflow / "run_simion.ps1"
                entry = run / "inputs/owner.ps1"
                shutil.copyfile(cli, entry)
                budget = run / "inputs/numerics.json"
                budget.write_text('{"fixture_budget_bytes":1048576}')
                result_path = run.parent.parent / "scratch/workflow_results" / run.name / "result.json"
                hook = "function Publish-WorkflowTerminal {throw 'RF_PUBLICATION_SENTINEL'}"
                if failure == "seal":
                    hook = """$actualCapacity=${function:Invoke-RunCapacityCommand}
function Invoke-RunCapacityCommand {param($Python,$RepoRoot,$Arguments,$FailureLabel)
 if('seal-stopped-payload'-in$Arguments){throw 'RF_SEAL_SENTINEL'}
 & $actualCapacity @PSBoundParameters
}
"""
                first = helper.run_ps(root, f""". '{fixtures.OWNER}'
function Invoke-ArtifactCapacityGate {{return @{{satisfied=$true;fixture_admission=$true}}}}
$session=Get-Content '{run / 'logs/capacity_session.json'}' -Raw|ConvertFrom-Json
$package=@{{run_config='{run / 'run_config.json'}';run_dir='{run}';artifact_run_dir='{run}'}}
$context=Initialize-RunArtifactPowerShellOwner -Python '{sys.executable}' -RepoRoot '{REPO}' -Package $package -CapacitySession $session -EntrypointPath '{entry}' -CommitmentInputPaths @('{budget}')
{hook}
try{{
 Complete-RunArtifactPowerShellOwner -Context $context -Status success -Summary @{{execution_status='completed';data_validity='valid';scientific_result='functional_fail'}} -OutputPaths @('{run / 'results/science.json'}') -WriterCompletion @{{operations=@();resource_releases=@()}} -WritersStopped ${str(failure != 'unknown').lower()}|Out-Null
 throw 'injection not reached'
}}catch{{if($_.Exception.Message-notmatch'RF_PUBLICATION_SENTINEL|RF_SEAL_SENTINEL|writer completion is unknown'){{throw}}}}
""")
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                before = (run / "run_manifest.json").read_bytes()
                command = [shutil.which("pwsh"), "-NoProfile", "-File", str(cli),
                    "-ArtifactRootPath", str(run.parent.parent), "-RunId", run.name,
                    "-PythonExe", sys.executable, "-ResultPath", str(result_path), "-ResumeFinalization"]
                resumed = subprocess.run(command, cwd=REPO, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=90)
                if failure == "unknown":
                    self.assertNotEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
                    self.assertEqual((run / "run_manifest.json").read_bytes(), before)
                    continue
                self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
                result = json.loads(result_path.read_text(encoding="utf-8-sig"))
                self.assertTrue(result["terminal_published"] and result["lease_released"] and result["capacity_finalized"])
                self.assertEqual(result["scientific_result"], "functional_fail")
                if failure == "seal":
                    self.assertEqual((run / "run_manifest.json").read_bytes(), before)
                terminal = (run / "run_manifest.json").read_bytes()
                repeated = subprocess.run(command, cwd=REPO, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=90)
                self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
                self.assertEqual((run / "run_manifest.json").read_bytes(), terminal)

    def test_real_consumers_share_release_and_completion_and_remove_private_terminal_paths(self):
        project = REPO / "projects" / PROJECT
        for workflow in ("interface_readiness", "mass_filter_reference"):
            source = (project / "workflows" / workflow / "run_simion.ps1").read_text()
            for token in ("Initialize-RunArtifactPowerShellOwner", "Complete-RunArtifactPowerShellOwner",
                          "Get-RfSimionStoppedWriterCompletion", "NativeOperations=$nativePreparation",
                          "$ownerContext.completion_written", "-CapacityOwner"):
                self.assertIn(token, source)
            for removed in ("Apply-RunArtifactRetention", "Write-VerifiedRunManifest", "seal-stopped-payload"):
                self.assertNotIn(removed, source)
