"""Actual public lifecycle recovery through the two original assembly CLIs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from common.contracts.capacity_ledger import initialize_capacity_ledger


REPO = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
class AssemblyFinalizationRecoveryTests(unittest.TestCase):
    def test_retention_failure_resumes_original_cli_without_scientific_inputs(self):
        for workflow, mode in (("prepared_joint", "prepared_joint"), ("oa_mr", "oa_mr")):
            for failure in ("retention", "publication", "unknown"):
                unknown = failure == "unknown"
                with self.subTest(workflow=workflow, failure=failure), tempfile.TemporaryDirectory() as temporary:
                    workspace = Path(temporary)
                    artifacts = workspace / "artifacts"
                    artifacts.mkdir()
                    initialize_capacity_ledger(artifacts, objects=[])
                    facade = workspace / "repo"
                    for source in (REPO / "common").rglob("*"):
                        if source.is_file() and source.suffix in {".ps1", ".json"} and "assets" not in source.parts:
                            target = facade / source.relative_to(REPO)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(source, target)
                    cli = facade / f"integrations/workflows/{workflow}/execute.ps1"
                    cli.parent.mkdir(parents=True)
                    shutil.copyfile(REPO / cli.relative_to(facade), cli)
                    run_id = "20261030_120000__test__python__assembly-finalization"
                    project = artifacts / "projects/instrument_assembly"
                    run = project / "runs" / run_id
                    result = project / "scratch/workflow_results" / run_id / "result.json"
                    prepare = r'''
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $env:WF_REPO 'common/contracts/run_artifact_workflow.ps1')
$package=New-RunPackage -Python $env:WF_PYTHON -RepoRoot $env:WF_REPO -ArtifactRoot $env:WF_PROJECT -RunId $env:WF_RUN_ID -Project instrument_assembly -Mode $env:WF_MODE -Software @('PowerShell software fixture') -RetentionContractEnabled -RetentionClass solver_review -RetentionReason 'inert public lifecycle fixture' -CapacityLedgerLifecycleEnabled
$authority=Join-Path $package.input_dir 'authority.json';Write-RunJson -Path $authority -Value @{output_budget_bytes=1048576}
$entry=Join-Path $package.input_dir 'owner.ps1';'throw "Scientific entrypoint must never execute during finalization"'|Set-Content $entry
$session=Enter-ArtifactWorkflowCapacitySession -Python $env:WF_PYTHON -RepoRoot $env:WF_REPO -ArtifactRoot $env:WF_ARTIFACTS -RunDirectory $package.artifact_run_dir -CommittedNewBytes 1048576 -ProtectedPaths @($package.artifact_run_dir) -Owner ('run-artifact-workflow:instrument_assembly:'+$env:WF_RUN_ID)
$context=Initialize-RunArtifactPowerShellOwner -Python $env:WF_PYTHON -RepoRoot $env:WF_REPO -Package $package -CapacitySession $session -EntrypointPath $entry -CommitmentInputPaths @($authority)
$payload=Join-Path $package.result_dir 'analysis.json';Write-RunJson -Path $payload -Value @{status='valid';scientific_result='not_evaluated'}
if($env:WF_FAILURE-eq'publication'){function Publish-WorkflowTerminal {throw 'injected-publication-failure'}}else{function Apply-RunArtifactRetention {throw 'injected-retention-failure'}}
try{$outcome=Complete-RunArtifactPowerShellOwner -Context $context -Status success -Summary @{schema_version=1;role='inert_assembly_summary';execution_status='completed';data_validity='valid';scientific_result='not_evaluated'} -OutputPaths @($payload) -WritersStopped ($env:WF_UNKNOWN-ne'1') -WriterCompletion @{operations=@();resource_releases=@()}}
catch{
 if($env:WF_UNKNOWN-eq'1'){if($_.Exception.Message-notlike'*writer completion is unknown*'){throw}}
 else{if($_.Exception.Message-cne('injected-'+$env:WF_FAILURE+'-failure')){throw};$outcome=$_.Exception.Data['workflow_result']}
}
if($env:WF_UNKNOWN-ne'1'-and$outcome.exception.message-cne('injected-'+$env:WF_FAILURE+'-failure')){throw 'actual retention failure did not propagate'}
exit 0
'''
                    env = {**os.environ, "WF_REPO": str(REPO), "WF_PYTHON": sys.executable,
                           "WF_ARTIFACTS": str(artifacts), "WF_PROJECT": str(project),
                           "WF_RUN_ID": run_id, "WF_MODE": mode, "WF_UNKNOWN": str(int(unknown)), "WF_FAILURE": failure}
                    prepared = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", prepare],
                        cwd=REPO, env=env, capture_output=True, text=True, encoding="utf-8", timeout=40)
                    self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
                    self.assertEqual(json.loads(result.read_text(encoding="utf-8-sig"))["resume_action"],
                                     "inspect_writer_completion" if unknown else "resume_finalization")
                    command = [shutil.which("pwsh"), "-NoProfile", "-File", str(cli), "-ResumeFinalization",
                               "-RunId", run_id, "-RepoRoot", str(facade), "-PythonExe", sys.executable]
                    resumed = subprocess.run(command, cwd=REPO, capture_output=True, text=True,
                        encoding="utf-8", timeout=40)
                    self.assertEqual(resumed.returncode == 0, not unknown, resumed.stdout + resumed.stderr)
                    manifest_path = run / "run_manifest.json"
                    if unknown:
                        self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8-sig"))["status"], "checkpoint")
                        self.assertFalse((run / "results/execution_completion.json").exists())
                    else:
                        self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8-sig"))["status"], "success")
                        original = manifest_path.read_bytes()
                        again = subprocess.run(command, cwd=REPO, capture_output=True, text=True,
                            encoding="utf-8", timeout=40)
                        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
                        self.assertEqual(manifest_path.read_bytes(), original)
